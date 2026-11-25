
"""
Great Expectations Weather Validation
-------------------------------------
Performs declarative data-quality checks on hourly
weather observations using Great Expectations 1.x.
"""

import json
import logging
from pathlib import Path

import pandas as pd
import great_expectations as gx


# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    PROJECT_ROOT / "data" / "weather" /
    "nyc_weather_hourly_2025_01.csv"
)

REPORT_FILE = (
    PROJECT_ROOT / "data" / "weather" /
    "weather_gx_validation_report.json"
)

EXPECTED_COLUMNS = [
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

RANGE_RULES = {
    "latitude": (-90, 90),
    "longitude": (-180, 180),
    "temperature_2m": (-90, 60),
    "relative_humidity_2m": (0, 100),
    "precipitation": (0, None),
    "rain": (0, None),
    "snowfall": (0, None),
    "wind_speed_10m": (0, None),
    "cloud_cover": (0, 100),
    "weather_code": (0, 99),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# Great Expectations setup
# --------------------------------------------------

def create_batch(df):
    """Create a Great Expectations batch from a Pandas DataFrame."""

    context = gx.get_context(mode="ephemeral")

    data_source = context.data_sources.add_pandas(
        name="weather_gx_datasource"
    )

    data_asset = data_source.add_dataframe_asset(
        name="weather_gx_asset"
    )

    batch_definition = (
        data_asset.add_batch_definition_whole_dataframe(
            name="weather_gx_batch"
        )
    )

    return batch_definition.get_batch(
        batch_parameters={"dataframe": df}
    )


# --------------------------------------------------
# Validation
# --------------------------------------------------

def validate_weather_gx(input_file=INPUT_FILE):
    """Run Great Expectations checks on weather data."""

    logger.info("Starting Great Expectations validation...")

    if not input_file.exists():
        raise FileNotFoundError(
            f"Weather CSV not found: {input_file}"
        )

    df = pd.read_csv(input_file)

    batch = create_batch(df)

    results = []

    def run_expectation(name, expectation):
        """Execute one expectation and record its result."""

        result = batch.validate(expectation)

        results.append({
            "expectation": name,
            "success": bool(result.success),
            "result": result.result,
        })

        logger.info(
            "%s: %s",
            name,
            "PASSED" if result.success else "FAILED",
        )

    # 1. Dataset size
    run_expectation(
        "Expected 744 hourly records",
        gx.expectations.ExpectTableRowCountToEqual(
            value=744
        ),
    )

        # 2. Required columns
    run_expectation(
        "Required columns present",
        gx.expectations.ExpectTableColumnsToMatchSet(
            column_set=EXPECTED_COLUMNS
        ),
    )

    # 3. Non-null values
    for column in EXPECTED_COLUMNS:
        run_expectation(
            f"{column} contains no null values",
            gx.expectations.ExpectColumnValuesToNotBeNull(
                column=column
            ),
        )

    # 4. Timestamp uniqueness
    run_expectation(
        "Timestamps are unique",
        gx.expectations.ExpectColumnValuesToBeUnique(
            column="timestamp"
        ),
    )

    # 5. Timestamp format
    run_expectation(
        "Timestamps are valid datetime strings",
        gx.expectations.ExpectColumnValuesToMatchRegex(
            column="timestamp",
            regex=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$",
        ),
    )

    # 6. Location values
    run_expectation(
        "Location is New York City",
        gx.expectations.ExpectColumnDistinctValuesToEqualSet(
            column="location",
            value_set={"New York City"},
        ),
    )
    # 7. Numeric type and range validation

    INTEGER_COLUMNS = {"weather_code"}

    for column, (minimum, maximum) in RANGE_RULES.items():

        expected_type = (
            "int64"
            if column in INTEGER_COLUMNS
            else "float64"
        )

        if column in INTEGER_COLUMNS:
            type_expectation = (
                gx.expectations.ExpectColumnValuesToBeOfType(
                    column=column,
                    type_="int64",
                )
            )
        else:
            type_expectation = (
                gx.expectations.ExpectColumnValuesToBeInTypeList(
                    column=column,
                    type_list=["int64", "float64"],
                )
            )

        run_expectation(
            f"{column} has a valid numeric type",
            type_expectation,
        )

        if maximum is not None:
            run_expectation(
                f"{column} is between {minimum} and {maximum}",
                gx.expectations.ExpectColumnValuesToBeBetween(
                    column=column,
                    min_value=minimum,
                    max_value=maximum,
                ),
            )
        else:
            run_expectation(
                f"{column} is at least {minimum}",
                gx.expectations.ExpectColumnValuesToBeBetween(
                    column=column,
                    min_value=minimum,
                ),
            )
    # 8. Hourly timestamp sequence
    timestamps = pd.to_datetime(
        df["timestamp"],
        errors="coerce",
    )

    hourly_intervals = timestamps.diff().dropna()

    hourly_success = bool(
        timestamps.notna().all()
        and timestamps.is_monotonic_increasing
        and hourly_intervals.eq(pd.Timedelta(hours=1)).all()
    )

    results.append({
        "expectation": "Timestamps are ordered and hourly",
        "success": hourly_success,
        "result": {
            "checked_intervals": len(hourly_intervals),
            "invalid_intervals": int(
                (~hourly_intervals.eq(pd.Timedelta(hours=1))).sum()
            ),
        },
    })

    # --------------------------------------------------
    # Report
    # --------------------------------------------------

    failed = [
        item for item in results
        if not item["success"]
    ]

    report = {
        "validation_status": (
            "PASSED" if not failed else "FAILED"
        ),
        "total_expectations": len(results),
        "passed_expectations": len(results) - len(failed),
        "failed_expectations": len(failed),
        "results": results,
    }

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with REPORT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(report, file, indent=4, default=str)

    logger.info(
        "Great Expectations status: %s",
        report["validation_status"],
    )

    logger.info(
        "Passed: %s | Failed: %s",
        report["passed_expectations"],
        report["failed_expectations"],
    )

    logger.info("Report saved: %s", REPORT_FILE)

    return not failed


# --------------------------------------------------
# Main
# --------------------------------------------------

if __name__ == "__main__":

    success = validate_weather_gx()

    raise SystemExit(0 if success else 1)
