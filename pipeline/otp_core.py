"""Define the compact, source-backed OTP flight feature layer.

The raw flights table remains the source of truth. This table is a deliberate
projection of fields repeatedly needed by the dashboard, operational analyses,
and the first route-delay forecast. It is rebuilt deterministically from
flights and never contains fabricated observations.
"""

from __future__ import annotations

from typing import Any

CORE_TABLE_NAME = "analytics_flight_core"

# Keep this list explicit. Adding a field should be a deliberate decision
# recorded in OTP_CORE_SCHEMA.md rather than an accidental SELECT *.
OTP_CORE_COLUMNS: tuple[str, ...] = (
    "FlightDate",
    "Year",
    "Quarter",
    "Month",
    "DayofMonth",
    "DayOfWeek",
    "Marketing_Airline_Network",
    "Operating_Airline",
    "Tail_Number",
    "Origin",
    "Dest",
    "CRSDepTime",
    "DepTime",
    "CRSArrTime",
    "ArrTime",
    "Cancelled",
    "CancellationCode",
    "Diverted",
    "DepDelay",
    "DepDel15",
    "ArrDelay",
    "ArrDel15",
    "CRSElapsedTime",
    "ActualElapsedTime",
    "AirTime",
    "Distance",
    "TaxiIn",
    "TaxiOut",
    "WheelsOff",
    "WheelsOn",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
    "FirstDepTime",
    "TotalAddGTime",
    "LongestAddGTime",
    "DivAirportLandings",
    "DivReachedDest",
    "DivActualElapsedTime",
    "DivArrDelay",
    "DivDistance",
)


def build_otp_core_table(connection: Any) -> int:
    """Create the compact OTP projection and return its row count.

    Failing on a missing source column is intentional: silently dropping a
    field would make downstream results look complete while changing their
    meaning.
    """
    source_columns = {row[0] for row in connection.execute("DESCRIBE flights").fetchall()}
    missing = [column for column in OTP_CORE_COLUMNS if column not in source_columns]
    if missing:
        raise RuntimeError(
            "OTP core layer cannot be built; source columns are missing: "
            + ", ".join(missing)
        )

    projection = ", ".join(f'"{column}"' for column in OTP_CORE_COLUMNS)
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE {CORE_TABLE_NAME} AS
        SELECT {projection}
        FROM flights
        """
    )
    return int(connection.execute(f"SELECT COUNT(*) FROM {CORE_TABLE_NAME}").fetchone()[0])
