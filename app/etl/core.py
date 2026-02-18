from typing import Any, Callable, Tuple
import re
import math
import numpy as np
import pandas as pd
from app.compiler.ast_nodes import *
from app.etl.data.data_factories import (
    LoaderDataFactory,
    ExtractorDataFactory,
)
from app.etl.data.base_data_types import IExtractor, ILoader
from app.etl.helpers import (
    apply_filtering,
    apply_groupby,
    apply_groupby_with_order,
    check_if_column_names_is_in_group_by,
    convert_select_column_indices_to_name,
    generate_aggregation_row,
    get_unique,
    group_by_columns_names,
    apply_order_by_without_groupby,
    apply_join,
)


transformed_data = None


def extract(data_source_type: str, data_source_path: str) -> pd.DataFrame:
    data_extractor: IExtractor = ExtractorDataFactory.create(
        data_source_type, data_source_path
    )
    data: pd.DataFrame = data_extractor.extract()
    return data


def transform_select(data: pd.DataFrame, criteria: dict) -> pd.DataFrame:
    are_select_columns_aggregation = False
    if criteria["COLUMNS"] != "__all__":
        # consider aggregation-only when all select items are tuples and not expression tuples
        are_select_columns_aggregation = all(
            isinstance(item, tuple) and not (len(item) >= 1 and item[0] == "expr")
            for item in criteria["COLUMNS"]
        )
    alias_map: dict[str, str] = {}
    # filtering
    if criteria["FILTER"]:
        data = apply_filtering(data, criteria["FILTER"])

    if (
        not criteria["GROUP"]
        and criteria["ORDER"]
        and not are_select_columns_aggregation
    ):
        order_by_node: OrderByNode = criteria["ORDER"]
        data = apply_order_by_without_groupby(data, order_by_node)

    if criteria["GROUP"]:
        groupby_columns = get_unique(group_by_columns_names(data, criteria["GROUP"]))
        select_columns = convert_select_column_indices_to_name(
            data, criteria["COLUMNS"]
        )
        if not check_if_column_names_is_in_group_by(select_columns, groupby_columns):
            raise Exception("there are is a column isn't in groupby columns")
        if criteria["ORDER"]:
            order_by_node: OrderByNode = criteria["ORDER"]
            data = apply_groupby_with_order(
                data, select_columns, groupby_columns, order_by_node
            )
        else:
            data = apply_groupby(data, select_columns, groupby_columns)

    else:
        if criteria["COLUMNS"] != "__all__":
            columns: list[str | Tuple] = criteria["COLUMNS"]
            is_column_number: Callable[[str], bool] = lambda x: x.startswith(
                "["
            ) and x.endswith("]")
            # if all the select columns are aggregation functions

            if are_select_columns_aggregation:
                # list of tuples each tuple is (aggregation,colum name)
                aggregate_columns: list[Tuple[str | Any]] = []
                for tuple_item in columns:
                    # support (agg, col) and (agg, col, alias)
                    if len(tuple_item) == 2:
                        agg, col = tuple_item
                        alias = None
                    else:
                        agg, col, alias = tuple_item
                    if is_column_number(col):
                        col_name = data.columns[int(col[1:-1])]
                    else:
                        col_name = col
                    aggregate_columns.append((agg, col_name))
                    if alias:
                        new_col = f"{agg}_{col_name}"
                        alias_map[new_col] = alias

                data = generate_aggregation_row(data, aggregate_columns)
                if alias_map:
                    data = data.rename(columns=alias_map)

            else:
                # if there are aggregation tuples mixed with non-aggregation (except expr tuples), error
                if any(isinstance(column, tuple) and (not (len(column) >= 1 and column[0] == "expr")) for column in columns):
                    raise Exception(
                        "there are aggregation columns in select you should use group by"
                    )
                # assuming that select columns don't contain any aggregate
                column_names = []
                for i, column in enumerate(columns):
                    # alias node
                    if isinstance(column, AliasNode):
                        inner = column.expr
                        # expression with alias
                        if isinstance(inner, tuple) and inner[0] == "expr":
                            expr = inner[1]
                            try:
                                # prepare local vars and replace index-style [n] with temporary vars
                                def _prepare_locals(expr_str):
                                    local_vars = {}
                                    def _replace_index(m):
                                        idx = int(m.group(1))
                                        colname = data.columns[idx]
                                        varname = f"__colidx_{idx}"
                                        local_vars[varname] = data[colname]
                                        return varname
                                    expr_to_eval = re.sub(r"\[(\d+)\]", _replace_index, expr_str)
                                    for col in data.columns:
                                        if col not in local_vars:
                                            try:
                                                local_vars[col] = data[col]
                                            except Exception:
                                                pass
                                    return expr_to_eval, local_vars

                                expr_to_eval, local_vars = _prepare_locals(expr)

                                # math functions we want to expose (prefer numpy ufuncs)
                                math_funcs = [
                                    'sin', 'cos', 'tan', 'asin', 'acos', 'atan',
                                    'sqrt', 'log', 'log10', 'exp', 'pow', 'fabs', 'floor', 'ceil'
                                ]

                                # build globals for python eval (prefer numpy functions)
                                math_globals = {"pd": pd, "np": np}
                                for fn in math_funcs:
                                    try:
                                        if hasattr(np, fn):
                                            math_globals[fn] = getattr(np, fn)
                                        else:
                                            math_globals[fn] = getattr(math, fn)
                                    except Exception:
                                        pass

                                # if expression uses math functions or power operator, use python eval
                                uses_func = re.search(r"\b(" + "|".join(math_funcs) + r")\s*\(", expr_to_eval) is not None
                                if uses_func or "**" in expr_to_eval:
                                    result = eval(expr_to_eval, math_globals, local_vars)
                                else:
                                    try:
                                        result = data.eval(expr_to_eval, engine="python", local_dict=local_vars)
                                    except Exception:
                                        result = eval(expr_to_eval, math_globals, local_vars)

                                if isinstance(result, pd.DataFrame):
                                    series = result.iloc[:, 0]
                                elif isinstance(result, np.ndarray):
                                    series = pd.Series(result, index=data.index)
                                else:
                                    series = result
                            except Exception:
                                raise
                            data[column.alias] = series.values
                            column_names.append(column.alias)
                            alias_map[column.alias] = column.alias
                        else:
                            if is_column_number(inner):
                                col_name = data.columns[int(inner[1:-1])]
                            else:
                                col_name = inner
                            column_names.append(col_name)
                            alias_map[col_name] = column.alias
                    # plain expression tuple without alias
                    elif isinstance(column, tuple) and len(column) >= 1 and column[0] == "expr":
                        expr = column[1]
                        try:
                            # prepare locals and replace [n]
                            def _prepare_locals(expr_str):
                                local_vars = {}
                                def _replace_index(m):
                                    idx = int(m.group(1))
                                    colname = data.columns[idx]
                                    varname = f"__colidx_{idx}"
                                    local_vars[varname] = data[colname]
                                    return varname
                                expr_to_eval = re.sub(r"\[(\d+)\]", _replace_index, expr_str)
                                for col in data.columns:
                                    if col not in local_vars:
                                        try:
                                            local_vars[col] = data[col]
                                        except Exception:
                                            pass
                                return expr_to_eval, local_vars

                            expr_to_eval, local_vars = _prepare_locals(expr)

                            math_funcs = [
                                'sin', 'cos', 'tan', 'asin', 'acos', 'atan',
                                'sqrt', 'log', 'log10', 'exp', 'pow', 'fabs', 'floor', 'ceil'
                            ]
                            math_globals = {"pd": pd, "np": np}
                            for fn in math_funcs:
                                try:
                                    if hasattr(np, fn):
                                        math_globals[fn] = getattr(np, fn)
                                    else:
                                        math_globals[fn] = getattr(math, fn)
                                except Exception:
                                    pass

                            uses_func = re.search(r"\b(" + "|".join(math_funcs) + r")\s*\(", expr_to_eval) is not None
                            if uses_func or "**" in expr_to_eval:
                                result = eval(expr_to_eval, math_globals, local_vars)
                            else:
                                try:
                                    result = data.eval(expr_to_eval, engine="python", local_dict=local_vars)
                                except Exception:
                                    result = eval(expr_to_eval, math_globals, local_vars)

                            if isinstance(result, pd.DataFrame):
                                series = result.iloc[:, 0]
                            elif isinstance(result, np.ndarray):
                                series = pd.Series(result, index=data.index)
                            else:
                                series = result
                        except Exception:
                            raise
                        gen_name = f"__expr_{i}"
                        data[gen_name] = series.values
                        column_names.append(gen_name)
                    else:
                        col_name = (
                            data.columns[int(column[1:-1])]
                            if is_column_number(column)
                            else column
                        )
                        column_names.append(col_name)

                # Select columns
                data = data[column_names]
                if alias_map:
                    data = data.rename(columns=alias_map)

    # distinct
    if criteria["DISTINCT"]:
        data = data.drop_duplicates()

    # limit
    if criteria["LIMIT_OR_TAIL"] != None:
        operator, number = criteria["LIMIT_OR_TAIL"]
        if number == 0:
            # empty data frame
            data = pd.DataFrame(columns=data.columns)
        elif operator == "limit":
            data = data[:number]
        else:
            data = data[-number:]

    global transformed_data
    transformed_data = data
    return data


def load(data: pd.DataFrame, source_type: str, data_destination: str):
    data_loader: ILoader = LoaderDataFactory.create(source_type, data_destination)
    data_loader.load(data)
