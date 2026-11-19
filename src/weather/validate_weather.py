
"""
Weather Data Validation Module
------------------------------
Validates historical hourly weather data before downstream processing.
Generates a JSON quality report.
"""

import argparse
import json
import logging
from pathlib import Path

import pandas as pd


# Project configuration
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    PROJECT_ROOT / "data" / "weather" / "nyc_weather_hourly_2025_01.csv"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "data" / "weather" / "weather_validation_report.json"
)

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

NUMERIC_COLUMNS = [
    "latitude",
    "longitude",
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
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


def validate_weather(input_file: Path, report_file: Path) -> bool:
    """Validate a weather CSV and save a JSON quality report."""

    logger.info("Starting weather data validation...")
    errors = []
    warnings = []
    checks = {}

    # 1. Check file existence
    if not input_file.exists():
        logger.error("Input file not found: %s", input_file)
        return False

    # 2. Load dataset
    try:
        df = pd.read_csv(input_file)
    except Exception as exc:
        logger.error("Could not read CSV: %s", exc)
        return False

    logger.info("Loaded %s records", len(df))

    checks["file_readable"] = True
    checks["row_count"] = len(df)
    checks["column_count"] = len(df.columns)

    # 3. Required column validation
    missing_columns = [
        column for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    checks["required_columns_present"] = len(missing_columns) == 0

    if missing_columns:
        errors.append(f"Missing required columns: {missing_columns}")

    # Stop if the schema is incomplete
    if missing_columns:
        return save_report(
            report_file, errors, warnings, checks
        )

    # 4. Missing-value validation
    missing_values = df[REQUIRED_COLUMNS].isnull().sum().to_dict()
    total_missing = int(sum(missing_values.values()))

    checks["missing_values"] = {
        column: int(count)
        for column, count in missing_values.items()
    }
    checks["total_missing_values"] = total_missing

    if total_missing:
        errors.append(f"Found {total_missing} missing values")

    # 5. Timestamp validation
    df["timestamp"] = pd.to_datetime(
        df["timestamp"], errors="coerce"
    )

    invalid_timestamps = int(df["timestamp"].isna().sum())

    checks["invalid_timestamps"] = invalid_timestamps

    if invalid_timestamps:
        errors.append(
            f"Found {invalid_timestamps} invalid timestamps"
        )

    valid_timestamps = df["timestamp"].dropna()

    # 6. Duplicate timestamp validation
    duplicate_count = int(
        valid_timestamps.duplicated().sum()
    )

    checks["duplicate_timestamps"] = duplicate_count

    if duplicate_count:
        errors.append(
            f"Found {duplicate_count} duplicate timestamps"
        )

    # 7. Timestamp ordering and hourly continuity
    if len(valid_timestamps) > 0:
        ordered = valid_timestamps.is_monotonic_increasing

        checks["timestamps_ordered"] = bool(ordered)

        if not ordered:
            errors.append("Timestamps are not in ascending order")

        unique_times = valid_timestamps.drop_duplicates().sort_values()

        gaps = unique_times.diff().dropna()
        gap_count = int((gaps != pd.Timedelta(hours=1)).sum())

        checks["non_hourly_intervals"] = gap_count

        if gap_count:
            errors.append(
                f"Found {gap_count} non-hourly timestamp intervals"
            )

        expected_records = int(
            (unique_times.max() - unique_times.min())
            / pd.Timedelta(hours=1)
        ) + 1

        checks["expected_records_in_observed_range"] = (
            expected_records
        )
        checks["actual_unique_timestamps"] = len(unique_times)

        if len(unique_times) != expected_records:
            errors.append(
                "Hourly timestamp sequence contains missing records"
            )

    # 8. Numeric type validation
    numeric_conversion_errors = {}

    for column in NUMERIC_COLUMNS:
        original_non_null = df[column].notna().sum()
        converted = pd.to_numeric(df[column], errors="coerce")

        conversion_errors = int(
            (converted.isna() & df[column].notna()).sum()
        )

        numeric_conversion_errors[column] = conversion_errors
        df[column] = converted

    checks["numeric_conversion_errors"] = (
        numeric_conversion_errors
    )

    if any(numeric_conversion_errors.values()):
        errors.append("Some numeric columns contain invalid values")

    # 9. Physical range validation
    range_rules = {
        "relative_humidity_2m": (0, 100),
        "cloud_cover": (0, 100),
        "temperature_2m": (-90, 60),
        "precipitation": (0, None),
        "rain": (0, None),
        "snowfall": (0, None),
        "wind_speed_10m": (0, None),
        "latitude": (-90, 90),
        "longitude": (-180, 180),
        "weather_code": (0, 99),
    }

    range_violations = {}

    for column, (minimum, maximum) in range_rules.items():
        invalid = pd.Series(False, index=df.index)

        if minimum is not None:
            invalid |= df[column] < minimum

        if maximum is not None:
            invalid |= df[column] > maximum

        count = int(invalid.sum())
        range_violations[column] = count

        if count:
            errors.append(
                f"{column}: {count} values outside allowed range"
            )

    checks["range_violations"] = range_violations

    # 10. Location validation
    invalid_locations = int(
        df["location"].astype("string").str.strip().eq("").sum()
    )

    checks["invalid_location_values"] = invalid_locations

    if invalid_locations:
        errors.append(
            f"Found {invalid_locations} empty location values"
        )

    # 11. Summary statistics
    checks["summary"] = {
        "first_timestamp": (
            str(valid_timestamps.min())
            if len(valid_timestamps) else None
        ),
        "last_timestamp": (
            str(valid_timestamps.max())
            if len(valid_timestamps) else None
        ),
        "average_temperature": (
            round(float(df["temperature_2m"].mean()), 2)
            if df["temperature_2m"].notna().any() else None
        ),
        "average_humidity": (
            round(float(df["relative_humidity_2m"].mean()), 2)
            if df["relative_humidity_2m"].notna().any() else None
        ),
    }

    return save_report(
        report_file, errors, warnings, checks
    )


def save_report(report_file, errors, warnings, checks):
    """Save validation results as JSON."""

    passed = len(errors) == 0

    report = {
        "validation_status": "PASSED" if passed else "FAILED",
        "errors_count": len(errors),
        "warnings_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }

    report_file.parent.mkdir(parents=True, exist_ok=True)

    with open(report_file, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4)

    logger.info("Validation status: %s", report["validation_status"])
    logger.info("Errors: %s", len(errors))
    logger.info("Warnings: %s", len(warnings))
    logger.info("Report saved: %s", report_file)

    for error in errors:
        logger.error(error)

    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate hourly weather data"
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to weather CSV",
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="Path to JSON validation report",
    )

    args = parser.parse_args()

    success = validate_weather(args.input, args.report)

    raise SystemExit(0 if success else 1)
