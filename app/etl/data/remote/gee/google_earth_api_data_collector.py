import ee
import pandas as pd
from app.etl.data.remote.gee.data_processor import DataProcessor


class GoogleEarthAPIDataCollector:
    def __init__(self, projectname: str = None):
        ee.Authenticate()
        # Initialize Earth Engine; project is optional now.
        if projectname:
            ee.Initialize(project=projectname)
        else:
            ee.Initialize()

    def _resolve_dataset(self, satellite: str) -> str:
        """Resolve a satellite identifier or dataset alias to an Earth Engine dataset id.

        - If `satellite` contains a '/', assume it's already a full dataset id and return it.
        - Otherwise, map common short aliases (case-insensitive) to dataset ids.
        - Fall back to ERA5 land daily aggregate if unknown.
        """
        if not satellite:
            return "ECMWF/ERA5_LAND/DAILY_AGGR"

        sat = satellite.strip()
        if "/" in sat:
            return sat

        mapping = {
            "ERA5": "ECMWF/ERA5_LAND/DAILY_AGGR",
            "ERA5_LAND": "ECMWF/ERA5_LAND/DAILY_AGGR",
            "S2": "COPERNICUS/S2_SR_HARMONIZED",
            "SENTINEL2": "COPERNICUS/S2_SR_HARMONIZED",
            "S1": "COPERNICUS/S1_GRD",
            "LANDSAT8": "LANDSAT/LC08/C01/T1_SR",
        }

        key = sat.upper()
        return mapping.get(key, "ECMWF/ERA5_LAND/DAILY_AGGR")

    def collect(self, satellite, start_date, end_date, longitude, latitude, scale):
        dataset = self._resolve_dataset(satellite)
        # Branch behavior depending on dataset type
        if "COPERNICUS/S2" in dataset or "SENTINEL-2" in satellite.upper():
            # Sentinel-2 is an optical imagery collection with spectral bands
            df = self.__load_sentinel2(dataset, start_date, end_date, longitude, latitude, scale)
            return df

        # Specific handling for ERA5 Land Daily Aggregate
        if dataset == "ECMWF/ERA5_LAND/DAILY_AGGR":
            df = self.__load_data_from_dataset(
                dataset, start_date, end_date, longitude, latitude, scale
            )
            weather_df = self.__process_data(df)
            return weather_df

        # Generic fallback for any other dataset
        return self.__load_generic_dataset(dataset, start_date, end_date, longitude, latitude, scale)

    def __process_data(self, df):
        calculator_instance = DataProcessor()
        weather_df = pd.DataFrame()
        if "longitude" in df.columns:
            weather_df["longitude"] = df["longitude"]
        if "latitude" in df.columns:
            weather_df["latitude"] = df["latitude"]
        weather_df["date"] = df["time"].apply(
            lambda x: pd.to_datetime(x / 1000, unit="s").date()
        )
        weather_df["temperature"] = df["temperature_2m"] - 273.15
        weather_df["soil_temperature"] = df["soil_temperature_level_1"] - 273.15
        weather_df["season"] = weather_df["date"].apply(
            calculator_instance.assign_season
        )
        weather_df["year"] = weather_df["date"].apply(calculator_instance.assign_year)

        # m/s meters per second
        weather_df["wind_speed"] = calculator_instance.calculate_wind_speed(
            df["u_component_of_wind_10m"], df["v_component_of_wind_10m"]
        )

        # Degree In 360
        weather_df["wind_direction"] = calculator_instance.calculate_wind_direction(
            df["u_component_of_wind_10m"], df["v_component_of_wind_10m"]
        )

        # meters (m)
        # 1 m of precipitation = 1000 mm = 1000 liters per square meter.
        weather_df["total_precipitation"] = df["total_precipitation_sum"]

        weather_df["relative_humidity"] = (
            calculator_instance.calculate_relative_humidity(
                df["temperature_2m"], df["dewpoint_temperature_2m"]
            )
        )

        # grams of water vapor per kilogram of moist air (g/kg).
        weather_df["specific_humidity"] = (
            calculator_instance.calculate_specific_humidity(
                df["dewpoint_temperature_2m"], df["surface_pressure"]
            )
        )

        # negative values indicate evaporation and positive values indicate condensation
        # depth of water (in meters) that would result from
        # the evaporation or evapotranspiration processes.
        weather_df["evapotranspiration"] = df["total_evaporation_sum"]
        weather_df["evaporation"] = (
            df["total_evaporation_sum"]
            - df["evaporation_from_vegetation_transpiration_sum"]
        )
        weather_df = weather_df.round(5)
        return weather_df

    def __load_generic_dataset(
        self, dataset, start_date, end_date, longitude, latitude, scale
    ):
        """Load any Earth Engine dataset for a point, returning all bands."""
        point = ee.Geometry.Point([longitude, latitude])
        collection = ee.ImageCollection(dataset).filterDate(start_date, end_date)

        # Check if collection is empty
        if collection.limit(1).size().getInfo() == 0:
            return pd.DataFrame()

        # Homogenize bands: Select bands from the first image to ensure consistency
        # This fixes errors with heterogeneous collections (e.g., NOAA/CFSR)
        first_image_bands = ee.Image(collection.first()).bandNames()
        collection = collection.select(first_image_bands)

        data = collection.getRegion(point, scale).getInfo()
        if not data or len(data) < 2:
            return pd.DataFrame()

        df = pd.DataFrame(data[1:], columns=data[0])
        if "time" in df.columns:
            df["date"] = df["time"].apply(lambda x: pd.to_datetime(x / 1000, unit="s").date())
        return df

    def __load_data_from_dataset(
        self, dataset, start_date, end_date, longitude, latitude, scale
    ):
        point = ee.Geometry.Point([longitude, latitude])

        dataset = ee.ImageCollection(dataset).filterDate(start_date, end_date)
        dataset = dataset.select(
            [
                "temperature_2m",
                "soil_temperature_level_1",
                "u_component_of_wind_10m",
                "v_component_of_wind_10m",
                "total_precipitation_sum",
                "dewpoint_temperature_2m",
                "surface_pressure",
                "total_evaporation_sum",
                "evaporation_from_vegetation_transpiration_sum",
            ]
        )
        data = dataset.getRegion(point, scale).getInfo()
        df = pd.DataFrame(data[1:], columns=data[0])

        return df

    def __load_sentinel2(self, dataset, start_date, end_date, longitude, latitude, scale):
        """Load Sentinel-2 bands for a point and return a simple dataframe.

        Returns columns: time (ms), and the selected bands. Additionally adds a 'date' column.
        """
        point = ee.Geometry.Point([longitude, latitude])

        collection = ee.ImageCollection(dataset).filterDate(start_date, end_date)

        bands = [
            "B1",
            "B2",
            "B3",
            "B4",
            "B5",
            "B6",
            "B7",
            "B8",
            "B8A",
            "B9",
            "B11",
            "B12",
            "AOT",
            "WVP",
            "SCL",
            "TCI_R",
            "TCI_G",
            "TCI_B",
        ]

        # Compute vegetation (NDVI, EVI, NDWI, and CGI) for each image
        def add_vegetation(image):
            # NDVI: (NIR - Red) / (NIR + Red)
            ndvi = image.expression(
                '((NIR - RED) / (NIR + RED))',
                {
                    'NIR': image.select('B8'),
                    'RED': image.select('B4'),
                },
            ).rename('NDVI')

            # EVI: 2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)
            evi = image.expression(
                '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                {
                    'NIR': image.select('B8'),
                    'RED': image.select('B4'),
                    'BLUE': image.select('B2'),
                },
            ).rename('EVI')

            # NDWI (McFeeters): (Green - NIR) / (Green + NIR)
            ndwi = image.expression(
                '((GREEN - NIR) / (GREEN + NIR))',
                {
                    'NIR': image.select('B8'),
                    'GREEN': image.select('B3'),
                },
            ).rename('NDWI')

            # CGI / GCI (Green Chlorophyll Index): (NIR / Green) - 1
            cgi = image.expression(
                '(NIR / GREEN) - 1',
                {'NIR': image.select('B8'), 'GREEN': image.select('B3')},
            ).rename('CGI')

            return image.addBands([ndvi, evi, ndwi, cgi])

        collection = collection.map(add_vegetation)
        collection = collection.select(bands + ['NDVI', 'EVI', 'NDWI', 'CGI'])

        data = collection.getRegion(point, scale).getInfo()
        df = pd.DataFrame(data[1:], columns=data[0])

        # Add a datetime column for convenience
        if "time" in df.columns:
            df["date"] = df["time"].apply(lambda x: pd.to_datetime(x / 1000, unit="s").date())

        # Ensure NDVI column exists and is numeric (could be None for some entries)
        if 'NDVI' in df.columns:
            df['NDVI'] = pd.to_numeric(df['NDVI'], errors='coerce')

        df = df.round(5)
        return df
