
"""
Weather Data Loader
-------------------
Loads validated historical weather observations
from CSV into InfluxDB.
"""

import csv
import json
import logging
import os
import subprocess
import sys

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision


# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    PROJECT_ROOT / "data" / "weather" /
    "nyc_weather_hourly_2025_01.csv"
)
VALIDATION_REPORT = (
    PROJECT_ROOT / "data" / "weather" /
    "weather_validation_report.json"
)

GX_VALIDATION_REPORT = (
    PROJECT_ROOT / "data" / "weather" /
    "weather_gx_validation_report.json"
)

load_dotenv(PROJECT_ROOT / ".env")

INFLUXDB_URL = "http://localhost:8086"
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")

TIMEZONE = ZoneInfo("America/New_York")

MEASUREMENT = "weather"

NUMERIC_FIELDS = [
    "latitude",
    "longitude",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "snowfall",
    "wind_speed_10m",
    "cloud_cover",
]

REQUIRED_COLUMNS = [
    "timestamp",
    "latitude",
    "longitude",
    "location",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "snowfall",
    "wind_speed_10m",
    "cloud_cover",
    "weather_code",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# Validation
# --------------------------------------------------


# --------------------------------------------------
# Validation
# --------------------------------------------------

def verify_validation_report(report_file, validator_name):
    """Ensure a validation report exists and passed."""

    if not report_file.exists():
        raise FileNotFoundError(
            f"{validator_name} report not found: {report_file}"
        )

    with report_file.open(encoding="utf-8") as file:
        report = json.load(file)

    if report.get("validation_status") != "PASSED":
        raise ValueError(
            f"{validator_name} validation failed."
        )

    logger.info("%s validation: PASSED", validator_name)


def run_validations():
    """Run both validation systems before loading data."""

    logger.info("Running custom weather validation...")

    custom_validator = (
        PROJECT_ROOT / "src" / "weather" /
        "validate_weather.py"
    )

    subprocess.run(
        [
            sys.executable,
            str(custom_validator),
            "--input",
            str(INPUT_FILE),
            "--report",
            str(VALIDATION_REPORT),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )

    logger.info("Running Great Expectations validation...")

    gx_validator = (
        PROJECT_ROOT / "src" / "weather" /
        "validate_weather_gx.py"
    )

    subprocess.run(
        [
            sys.executable,
            str(gx_validator),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )

    verify_validation_report(
        VALIDATION_REPORT,
        "Custom",
    )

    verify_validation_report(
        GX_VALIDATION_REPORT,
        "Great Expectations",
    )

    logger.info("All weather data validations passed.")

# --------------------------------------------------
# CSV Loading
# --------------------------------------------------

def load_weather_records():
    """Read CSV records and convert them into InfluxDB points."""

    if not INPUT_FILE.exists():
        raise FileNotFoundError(INPUT_FILE)

    points = []

    with INPUT_FILE.open(
        "r",
        newline="",
        encoding="utf-8"
    ) as file:

        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError("CSV has no header.")

        missing_columns = (
            set(REQUIRED_COLUMNS) - set(reader.fieldnames)
        )

        if missing_columns:
            raise ValueError(
                f"Missing columns: {sorted(missing_columns)}"
            )

        for row_number, row in enumerate(reader, start=2):

            timestamp = datetime.fromisoformat(row["timestamp"])

            # Interpret the source timestamp in New York local time.
            timestamp = timestamp.replace(tzinfo=TIMEZONE)

            point = (
                Point(MEASUREMENT)
                .tag("location", row["location"])
                .time(timestamp, WritePrecision.S)
            )

            for field in NUMERIC_FIELDS:
                point.field(field, float(row[field]))

            point.field("weather_code", int(row["weather_code"]))

            points.append(point)

    if not points:
        raise ValueError("No weather records found.")

    logger.info("Loaded %s weather records.", len(points))

    return points


# --------------------------------------------------
# InfluxDB Writing
# --------------------------------------------------

def write_to_influxdb(points):
    """Write weather points to InfluxDB in batches."""

    if not all([
        INFLUXDB_TOKEN,
        INFLUXDB_ORG,
        INFLUXDB_BUCKET
    ]):
        raise ValueError(
            "InfluxDB credentials are missing. "
            "Check your .env file."
        )

    with InfluxDBClient(
        url=INFLUXDB_URL,
        token=INFLUXDB_TOKEN,
        org=INFLUXDB_ORG
    ) as client:

        with client.write_api() as write_api:

            batch_size = 200

            for start in range(0, len(points), batch_size):

                batch = points[start:start + batch_size]

                write_api.write(
                    bucket=INFLUXDB_BUCKET,
                    org=INFLUXDB_ORG,
                    record=batch
                )

                logger.info(
                    "Submitted records %s to %s",
                    start + 1,
                    start + len(batch)
                )

    logger.info(
        "Successfully submitted %s weather points.",
        len(points)
    )


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():

    logger.info("Starting weather-to-InfluxDB pipeline.")

    run_validations()

    points = load_weather_records()

    write_to_influxdb(points)

    logger.info("Weather data loading completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Weather data loading failed.")
        raise
