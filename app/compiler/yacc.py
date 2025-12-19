from app.compiler.ast_nodes import (
    AggregationNode,
    ColumnIndexNode,
    ColumnNameNode,
    OrderByNode,
    OrderByParameter,
    SortingWay,
    AliasNode,
    JoinNode,
)
from app.core.errors import ParserError


start = "start"


def p_start(p):
    """start : select
    | insert
    | update
    | delete"""
    p[0] = p[1]


def p_empty(p):
    "empty :"
    pass


def p_error(p):
    value, line_number, position = p.value, p.lineno, p.lexpos
    raise ParserError(
        f"Syntax error at token '{value}' on line {line_number}, position {position}.",
        p.value,
        p.lineno,
        p.lexpos,
    )


# else:
#         raise ParserError("Syntax error at EOF")


###########################
# ==== SELECT STATEMENT​​ ====
###########################


def p_select(p):
    """select : SELECT distinct select_columns into_statement from_statement where group order limit_or_tail SIMICOLON"""
    # unpack parts for clarity
    distinct = p[2]
    select_columns = p[3]
    into_stmt = p[4]
    from_stmt = p[5]
    where_clause = p[6]
    group_clause = p[7]
    order_clause = p[8]
    limit_tail = p[9]

    if type(select_columns) == str:
        select_columns = "'" + select_columns + "'"

    extraction_code = ""

    if isinstance(from_stmt, JoinNode):
        left_node = from_stmt.left
        right_node = from_stmt.right

        def get_source_info(node):
            if isinstance(node, tuple):
                return node[0], node[1]
            return node, None

        l_ds, l_alias = get_source_info(left_node)
        r_ds, r_alias = get_source_info(right_node)

        l_type, l_path = l_ds.split(":", 1)
        r_type, r_path = r_ds.split(":", 1)

        l_alias_repr = f"'{l_alias}'" if l_alias else "None"
        r_alias_repr = f"'{r_alias}'" if r_alias else "None"

        extraction_code = (
            f"left_data = etl.extract('{l_type}', '{l_path}')\n"
            f"right_data = etl.extract('{r_type}', '{r_path}')\n"
            f"extracted_data = etl.apply_join(left_data, right_data, {from_stmt.condition}, '{from_stmt.join_type}', {l_alias_repr}, {r_alias_repr})\n"
        )
    else:
        if isinstance(from_stmt, tuple):
            datasource, alias = from_stmt
            file_type, file_path = datasource.split(":", 1)
            extraction_code = (
                f"extracted_data = etl.extract('{file_type}','{file_path}')\n"
                f"extracted_data = extracted_data.add_prefix('{alias}.')\n"
            )
        else:
            datasource = from_stmt
            file_type, file_path = datasource.split(":", 1)
            extraction_code = f"extracted_data = etl.extract('{file_type}','{file_path}')\n"

    if into_stmt:
        load_type, load_path = into_stmt.split(":", 1)

    p[0] = (
        "from app import etl\n"
        "from app.compiler.ast_nodes import *\n\n"
        f"{extraction_code}"
        f"transformed_data = etl.transform_select(\n"
        f"   extracted_data,\n"
        f"   {{\n"
        f"        'COLUMNS':  {select_columns},\n"
        f"        'DISTINCT': {distinct},\n"
        f"        'FILTER':   {where_clause},\n"
        f"        'GROUP':    {group_clause},\n"
        f"        'ORDER':    {order_clause},\n"
        f"        'LIMIT_OR_TAIL':    {limit_tail},\n"
        f"    }}\n"
        f")\n"
        f"{f"etl.load(transformed_data,'{load_type}','{load_path}')" if into_stmt else "" }\n"
    )


###########################
# ==== INSERT STATEMENT ====
###########################


def p_insert(p):
    "insert : INSERT INTO DATASOURCE icolumn VALUES insert_values SIMICOLON"

    p[3] = str(p[3]).replace("\\", "\\\\")
    p[0] = (
        f"from app import etl\n"
        f"import pandas as pd\n"
        f"\n"
        f"values = {p[6]}\n"
        f"data_destination = '{p[3]}'\n"
        f"data = pd.DataFrame(values, columns={p[4]})\n"
        f"etl.load(data, data_destination)\n"
    )


###########################
# ==== Update STATEMENT ====
###########################
def p_update(p):
    "update : UPDATE DATASOURCE SET assigns where SIMICOLON"
    p[0] = None


###########################
# ==== DELETE STATEMENT​​ ====
###########################


def p_delete(p):
    "delete : DELETE FROM DATASOURCE where"
    p[0] = None


##########################
# ====== COMPARISON =======
##########################


def p_logical(p):
    """logical :  EQUAL
    | NOTEQUAL
    | BIGGER_EQUAL
    | BIGGER
    | SMALLER_EQUAL
    | SMALLER"""
    p[0] = p[1]


##########################
# ====== WHERE CLAUSE =====
##########################


def p_where(p):
    "where : WHERE conditions"
    p[0] = p[2]


def p_where_empty(p):
    "where : empty"
    p[0] = None


def p_cond_parens(p):
    "conditions : LPAREN conditions RPAREN"
    p[0] = p[2]


def p_cond_3(p):
    """conditions : conditions AND conditions
    | conditions OR conditions
    | exp LIKE STRING
    | exp logical exp"""
    p[0] = {"type": p[2], "left": p[1], "right": p[3]}


def p_conditions_not(p):
    "conditions : NOT conditions"
    p[0] = {"type": p[1], "operand": p[2]}


##########################
# ========== EXP ==========
##########################


def p_exp(p):
    """exp : column
    | STRING
    | NUMBER"""

    p[0] = p[1]


##########################
# ========== EXP ==========
##########################
def p_NUMBER(p):
    """NUMBER : NEGATIVE_INTNUMBER
    | POSITIVE_INTNUMBER
    | FLOATNUMBER"""
    p[0] = p[1]


###########################
# ======== Distinct ========
###########################


def p_distinct(p):
    """distinct : DISTINCT"""
    p[0] = True


def p_distinct_empty(p):
    """distinct : empty"""
    p[0] = False


###########################
# ======== COLUMNS =========
###########################
def p_column(p):
    """column : COLNUMBER
    | BRACKETED_COLNAME
    | SIMPLE_COLNAME"""
    c = str(p[1])
    if c.startswith("[") and c.endswith("]") and not c[1:-1].isdigit():
        c = c[1:-1]
    p[0] = c


def p_columns(p):
    """columns : columns COMMA columns"""
    p[0] = []
    p[0].extend(p[1])
    p[0].extend(p[3])


def p_columns_base(p):
    """columns : select_unit"""
    p[0] = [p[1]]


def p_select_unit_col(p):
    """select_unit : column"""
    p[0] = p[1]


def p_select_unit_agg(p):
    """select_unit : AGGREGATION_FUNCTION LPAREN column RPAREN
    | AGGREGATION_FUNCTION LPAREN TIMES RPAREN"""
    p[0] = (p[1], p[3])
    if p[3] == "*" and p[1] != "size":
        raise ParserError(
            f"Syntax error: You cannot use * with aggregation functions except SIZE(*)",
            "*",
            -1,
            -1,
        )


def p_select_unit_col_alias(p):
    """select_unit : column AS SIMPLE_COLNAME"""
    p[0] = AliasNode(expr=p[1], alias=str(p[3]))


def p_select_unit_agg_alias(p):
    """select_unit : AGGREGATION_FUNCTION LPAREN column RPAREN AS SIMPLE_COLNAME
    | AGGREGATION_FUNCTION LPAREN TIMES RPAREN AS SIMPLE_COLNAME"""
    # produce a tuple (function, column, alias)
    p[0] = (p[1], p[3], str(p[6]))


def p_aggregation_function(p):
    """aggregation_function : AGGREGATION_FUNCTION LPAREN column RPAREN
    | AGGREGATION_FUNCTION LPAREN TIMES RPAREN"""
    p[0] = (p[1], p[3])
    if p[3] == "*" and p[1] != "size":
        raise ParserError(
            f"Syntax error: You cannot use * with aggregation functions except SIZE(*)",
            "*",
            -1,
            -1,
        )


###########################
# ===== SELECT COLUMNS​​ =====
###########################


def p_select_columns_all(p):
    "select_columns : TIMES"
    p[0] = "__all__"


def p_select_columns(p):
    "select_columns : columns"
    p[0] = p[1]


###########################
# ========= Into ===========
###########################


def p_into_statement(p):
    "into_statement : INTO DATASOURCE"
    p[0] = p[2]


def p_into_statement_empty(p):
    "into_statement : empty"


###########################
# ======= Group by =========
###########################
def p_group(p):
    """group : GROUP BY icolumns"""
    p[0] = p[3]


def p_group_empty(p):
    """group : empty"""
    p[0] = None


def p_from_statement(p):
    """from_statement : FROM datasource_alias"""
    p[0] = p[2]


def p_datasource_alias_plain(p):
    """datasource_alias : DATASOURCE"""
    p[0] = p[1]


def p_datasource_alias_as(p):
    """datasource_alias : DATASOURCE AS SIMPLE_COLNAME"""
    p[0] = (p[1], str(p[3]))


def p_datasource_alias_plainname(p):
    """datasource_alias : DATASOURCE SIMPLE_COLNAME"""
    p[0] = (p[1], str(p[2]))


def p_from_statement_join(p):
    """from_statement : FROM datasource_alias INNER JOIN datasource_alias ON conditions"""
    p[0] = JoinNode(left=p[2], right=p[5], join_type="inner", condition=p[7])


###########################
# ======= Order by =========
###########################
def p_simple_column_name(p):
    """simple_column_name : SIMPLE_COLNAME"""
    p[0] = ColumnNameNode(str(p[1]))


def p_bracketed_column_name(p):
    """bracketed_column_name : BRACKETED_COLNAME"""
    token = str(p[1])
    # to remove the scare brackets token[1:-1]
    p[0] = ColumnNameNode(token[1:-1])


def p_column_index(p):
    """column_index : COLNUMBER"""
    token = str(p[1])
    # to remove the scare brackets token[1:-1] and cast the str to int
    index = int(token[1:-1])

    p[0] = ColumnIndexNode(index=index)


def p_custom_column(p):
    """custom_column : bracketed_column_name
    | simple_column_name
    | column_index"""
    p[0] = p[1]


def p_custom_aggregation_column(p):
    """custom_aggregation_column : AGGREGATION_FUNCTION LPAREN custom_column RPAREN
    | AGGREGATION_FUNCTION LPAREN TIMES RPAREN"""
    function = str(p[1])
    column = p[3]
    if function == "size" and column == "*":
        column = ColumnNameNode("*")
    p[0] = AggregationNode(function, column)


def p_order_by_param(p):
    """order_by_param : custom_aggregation_column way
    | custom_column way"""
    sorting_way: SortingWay = p[2]
    parameter = p[1]
    p[0] = OrderByParameter(parameter=parameter, way=sorting_way)


def p_order_by_parameters_base(p):
    """order_by_parameters : order_by_param"""
    p[0] = list[OrderByParameter]([p[1]])


def p_order_by_parameters(p):
    """order_by_parameters : order_by_parameters COMMA order_by_parameters"""
    params_list = list[OrderByParameter]()
    params_list.extend(p[1])
    params_list.extend(p[3])
    p[0] = params_list


def p_order(p):
    """order : ORDER BY order_by_parameters"""
    p[0] = OrderByNode(parameters=p[3])


def p_order_empty(p):
    "order : empty"
    p[0] = None


def p_way_asc(p):
    """way : ASC
    | empty"""
    p[0] = SortingWay.ASC


def p_way_desc(p):
    "way : DESC"
    p[0] = SortingWay.DESC


###########################
# ========= Limit & Tail ==========
###########################


def p_limit_or_tail(p):
    """limit_or_tail : LIMIT POSITIVE_INTNUMBER
    | TAIL POSITIVE_INTNUMBER"""
    p[0] = (p[1], p[2])


def p_limit_or_tail_empty(p):
    """limit_or_tail : empty"""
    p[0] = None


###########################
# ========= VALUES​ =========
###########################


def p_value(p):
    """value : STRING
    | NUMBER"""

    p[0] = p[1]


def p_values(p):
    "values : values COMMA values"
    p[0] = []
    p[0].extend(p[1])
    p[0].extend(p[3])


###########################
# ===== INSERT VALUES​ ======
###########################


def p_values_end(p):
    "values : value"
    p[0] = [p[1]]


def p_single_values(p):
    "single_values : LPAREN values RPAREN"
    p[0] = p[2]


def p_insert_values(p):
    "insert_values : insert_values COMMA insert_values"
    p[0] = []
    p[0].extend(p[1])
    p[0].extend(p[3])


def p_insert_values_end(p):
    "insert_values : single_values"
    p[0] = [p[1]]


###########################
# ===== Insert Columns​​ =====
###########################


def p_icolumn(p):
    "icolumn : LPAREN icolumns RPAREN"
    p[0] = p[2]


def p_icolumn_empty(p):
    "icolumn : empty"
    p[0] = None


def p_icolumns(p):
    """icolumns : icolumns COMMA icolumns"""
    p[0] = []
    p[0].extend(p[1])
    p[0].extend(p[3])


def p_icolumns_base(p):
    """icolumns : column"""
    p[0] = [p[1]]


###########################
# ==== ASSIGNS STATEMENT​​ ===
###########################


def p_assign(p):
    "assign : column EQUAL value"
    p[0] = (p[1], p[3])


def p_assigns(p):
    "assigns : assign COMMA assigns"
    p[0] = [p[1]].extend(p[3])


def p_assigns_end(p):
    "assigns : assign"
    p[0] = [p[1]]
