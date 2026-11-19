
import csv
import logging
from pathlib import Path

import requests

# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

LATITUDE = 40.7128
LONGITUDE = -74.0060

START_DATE = "2025-01-01"
END_DATE = "2025-01-31"

TIMEZONE = "America/New_York"

WEATHER_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "snowfall",
    "wind_speed_10m",
    "cloud_cover",
    "weather_code",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]

OUTPUT_DIR = PROJECT_ROOT / "data" / "weather"
OUTPUT_FILE = OUTPUT_DIR / "nyc_weather_hourly_2025_01.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


def fetch_weather_data():
    """Fetch historical hourly weather data from Open-Meteo."""

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "hourly": ",".join(WEATHER_VARIABLES),
        "timezone": TIMEZONE,
    }

    logger.info("Requesting historical NYC weather data...")

    response = requests.get(
        BASE_URL,
        params=params,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    if "hourly" not in data:
        raise ValueError("Hourly weather data missing from API response")

    return data


def transform_weather_data(data):
    """Convert API arrays into hourly records."""

    hourly = data["hourly"]
    timestamps = hourly["time"]

    records = []

    for index, timestamp in enumerate(timestamps):

        record = {
            "timestamp": timestamp,
            "latitude": data["latitude"],
            "longitude": data["longitude"],
            "location": "New York City",
        }

        for variable in WEATHER_VARIABLES:
            record[variable] = hourly[variable][index]

        records.append(record)

    return records


def save_weather_data(records):
    """Save weather observations to CSV."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not records:
        raise ValueError("No weather records to save")

    with OUTPUT_FILE.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=list(records[0].keys())
        )

        writer.writeheader()
        writer.writerows(records)

    logger.info("Saved %s records", len(records))
    logger.info("Output: %s", OUTPUT_FILE)


def main():

    data = fetch_weather_data()

    records = transform_weather_data(data)

    save_weather_data(records)

    logger.info("Weather ingestion completed successfully!")


if __name__ == "__main__":
    main()
