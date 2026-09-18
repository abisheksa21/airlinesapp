"""Build compact, warehouse-backed tables used by the dashboard.

The raw ``flights`` table remains the source of truth.  These derived tables
keep only the dimensions and metrics the website repeatedly asks for, which
means the public pages do not need to rescan every raw column for every visit.
They are deterministic and can always be rebuilt from ``flights``.
"""

from __future__ import annotations

from typing import Any

import duckdb

from config import DUCKDB_FILE
from api.metrics import COMPLETED_FLIGHT_SQL, ON_TIME_FLAG_SQL, SEVERE_DELAY_SQL
from pipeline.otp_core import CORE_TABLE_NAME, build_otp_core_table


ANALYTICS_TABLES = (
    CORE_TABLE_NAME,
    "analytics_network_month",
    "analytics_carrier_month",
    "analytics_route_month",
    "analytics_t100_route_month",
    "analytics_airport_month",
    "analytics_airport_operational_month",
    "analytics_carrier_profile",
    "analytics_airport_profile",
    "analytics_airport_profile_month",
    "analytics_route_hour",
)

PROFILE_TABLES = (
    "analytics_carrier_profile",
    "analytics_airport_profile",
    "analytics_airport_profile_month",
)


# Keep the public profile summary on the same definitions as the health-score
# endpoint.  These fields are materialized once during a pipeline refresh so a
# public profile visit does not rescan the 60M-row raw table.
PROFILE_STATS_SQL = f"""
    COUNT(*) AS total_flights,
    SUM(CASE WHEN {COMPLETED_FLIGHT_SQL} THEN 1 ELSE 0 END) AS completed_flights,
    AVG(CASE WHEN {COMPLETED_FLIGHT_SQL} THEN ArrDelay END) AS avg_arrival_delay,
    VAR_POP(CASE WHEN {COMPLETED_FLIGHT_SQL} THEN ArrDelay END) AS var_arrival_delay,
    AVG(CASE WHEN {COMPLETED_FLIGHT_SQL}
        THEN CASE WHEN {ON_TIME_FLAG_SQL} THEN 1.0 ELSE 0.0 END END) * 100 AS on_time_percentage,
    VAR_POP(CASE WHEN {COMPLETED_FLIGHT_SQL}
        THEN CASE WHEN {ON_TIME_FLAG_SQL} THEN 1.0 ELSE 0.0 END END) AS var_on_time_indicator,
    AVG(CASE WHEN {SEVERE_DELAY_SQL} THEN 1.0 WHEN {COMPLETED_FLIGHT_SQL} THEN 0.0 END) * 100 AS severe_delay_percentage,
    VAR_POP(CASE WHEN {SEVERE_DELAY_SQL} THEN 1.0 WHEN {COMPLETED_FLIGHT_SQL} THEN 0.0 END) AS var_severe_indicator,
    AVG(Cancelled) * 100 AS cancellation_percentage,
    VAR_POP(CAST(Cancelled AS DOUBLE)) AS var_cancelled_indicator,
    AVG(Diverted) * 100 AS diversion_percentage,
    VAR_POP(CAST(Diverted AS DOUBLE)) AS var_diverted_indicator
"""

AIRPORT_EVENTS_CTE = """
    WITH airport_flights AS (
        SELECT
            row_number() OVER () AS flight_id,
            FlightDate, Cancelled, Diverted, ArrDelay, ArrDel15, Origin, Dest
        FROM analytics_flight_core
        WHERE FlightDate IS NOT NULL AND (Origin IS NOT NULL OR Dest IS NOT NULL)
    ), airport_events AS (
        SELECT flight_id, Origin AS airport, FlightDate, Cancelled, Diverted, ArrDelay, ArrDel15
        FROM airport_flights
        WHERE Origin IS NOT NULL
        UNION ALL
        SELECT flight_id, Dest AS airport, FlightDate, Cancelled, Diverted, ArrDelay, ArrDel15
        FROM airport_flights
        WHERE Dest IS NOT NULL AND Dest <> Origin
    )
"""


def build_profile_summary_tables(connection: Any) -> dict[str, int]:
    """Build only the compact profile tables needed by public pages.

    This is useful for an existing warehouse that already has the older
    aggregate tables but not the new profile layer. It intentionally avoids
    rebuilding every analytics table; the next complete pipeline refresh will
    build the same tables as part of :func:`build_analytics_tables`.
    """
    source_table = CORE_TABLE_NAME
    source_exists = connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main' AND table_name = ?",
        [source_table],
    ).fetchone()[0]
    if not source_exists:
        source_table = "flights"
    airport_events_cte = AIRPORT_EVENTS_CTE.replace("analytics_flight_core", source_table)

    connection.execute(
        f"""
        CREATE OR REPLACE TABLE analytics_carrier_profile AS
        SELECT Marketing_Airline_Network AS carrier, {PROFILE_STATS_SQL}
        FROM {source_table}
        WHERE FlightDate IS NOT NULL AND Marketing_Airline_Network IS NOT NULL
        GROUP BY Marketing_Airline_Network
        ORDER BY carrier
        """
    )

    # Materialize the airport event grain once.  Both airport aggregates use
    # the same de-duplicated flight-at-airport rows; rebuilding the CTE for
    # each table would otherwise scan the raw warehouse twice more.
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _airport_profile_events AS
        {airport_events_cte}
        SELECT * FROM airport_events
        """
    )
    try:
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE analytics_airport_profile AS
            SELECT airport, {PROFILE_STATS_SQL}
            FROM _airport_profile_events
            WHERE airport IS NOT NULL
            GROUP BY airport
            ORDER BY airport
            """
        )
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE analytics_airport_profile_month AS
            SELECT
                airport,
                strftime(FlightDate, '%Y-%m') AS year_month,
                COUNT(*) AS total_flights,
                COUNT(*) FILTER (WHERE {COMPLETED_FLIGHT_SQL}) AS completed_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM _airport_profile_events
            WHERE airport IS NOT NULL
            GROUP BY airport, year_month
            ORDER BY airport, year_month
            """
        )
    finally:
        connection.execute("DROP TABLE IF EXISTS _airport_profile_events")

    return {
        table_name: int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
        for table_name in (
            "analytics_carrier_profile",
            "analytics_airport_profile",
            "analytics_airport_profile_month",
        )
    }


def build_t100_route_month_table(connection: Any) -> int:
    """Materialize the T-100 data at the route-month grain used by models.

    The BTS T-100 source has carrier/detail rows.  Research pages compare it
    beside OTP at a route + month grain, so aggregating it once during refresh
    prevents every interactive request from re-reading millions of source
    records.  If a warehouse has not loaded T-100 yet, we retain an empty,
    typed table so the application can degrade gracefully to OTP-only views.
    """
    source_exists = connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main' AND table_name = ?",
        ["bts_t100_segment_route_month"],
    ).fetchone()[0]
    if not source_exists:
        connection.execute(
            """
            CREATE OR REPLACE TABLE analytics_t100_route_month AS
            SELECT
                CAST(NULL AS VARCHAR) AS origin,
                CAST(NULL AS VARCHAR) AS dest,
                CAST(NULL AS DATE) AS period_date,
                CAST(NULL AS BIGINT) AS seats_available,
                CAST(NULL AS BIGINT) AS passengers,
                CAST(NULL AS BIGINT) AS departures_scheduled,
                CAST(NULL AS BIGINT) AS departures_performed,
                CAST(NULL AS DOUBLE) AS load_factor,
                CAST(NULL AS DOUBLE) AS completion_rate
            WHERE FALSE
            """
        )
    else:
        connection.execute(
            """
            CREATE OR REPLACE TABLE analytics_t100_route_month AS
            SELECT
                Origin AS origin,
                Dest AS dest,
                make_date(CAST(Year AS INTEGER), CAST(Month AS INTEGER), 1) AS period_date,
                SUM(COALESCE(seats_available, 0)) AS seats_available,
                SUM(COALESCE(passengers, 0)) AS passengers,
                SUM(COALESCE(departures_scheduled, 0)) AS departures_scheduled,
                SUM(COALESCE(departures_performed, 0)) AS departures_performed,
                SUM(COALESCE(passengers, 0)) / NULLIF(SUM(COALESCE(seats_available, 0)), 0) AS load_factor,
                SUM(COALESCE(departures_performed, 0)) / NULLIF(SUM(COALESCE(departures_scheduled, 0)), 0) AS completion_rate
            FROM bts_t100_segment_route_month
            WHERE Origin IS NOT NULL AND Dest IS NOT NULL AND Year IS NOT NULL AND Month IS NOT NULL
            GROUP BY Origin, Dest, Year, Month
            ORDER BY origin, dest, period_date
            """
        )
    return int(connection.execute("SELECT COUNT(*) FROM analytics_t100_route_month").fetchone()[0])


def build_analytics_tables(connection: Any) -> dict[str, int]:
    """Replace all dashboard aggregate tables and return their row counts."""
    core_count = build_otp_core_table(connection)
    statements = {
        "analytics_network_month": """
            CREATE OR REPLACE TABLE analytics_network_month AS
            SELECT
                strftime(FlightDate, '%Y-%m') AS year_month,
                COUNT(*) AS total_flights,
                COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS completed_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate,
                COUNT(DISTINCT Origin || '-' || Dest) AS unique_routes,
                COUNT(DISTINCT Origin) + COUNT(DISTINCT Dest) AS airport_endpoint_count
            FROM analytics_flight_core
            WHERE FlightDate IS NOT NULL
            GROUP BY year_month
            ORDER BY year_month
        """,
        "analytics_carrier_month": """
            CREATE OR REPLACE TABLE analytics_carrier_month AS
            SELECT
                Marketing_Airline_Network AS carrier,
                strftime(FlightDate, '%Y-%m') AS year_month,
                COUNT(*) AS total_flights,
                COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS completed_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM analytics_flight_core
            WHERE FlightDate IS NOT NULL AND Marketing_Airline_Network IS NOT NULL
            GROUP BY Marketing_Airline_Network, year_month
            ORDER BY carrier, year_month
        """,
        "analytics_route_month": """
            CREATE OR REPLACE TABLE analytics_route_month AS
            SELECT
                Origin AS origin,
                Dest AS dest,
                strftime(FlightDate, '%Y-%m') AS year_month,
                COUNT(*) AS total_flights,
                COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS completed_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate,
                MAX(Distance) AS distance_miles
            FROM analytics_flight_core
            WHERE FlightDate IS NOT NULL AND Origin IS NOT NULL AND Dest IS NOT NULL
            GROUP BY Origin, Dest, year_month
            ORDER BY origin, dest, year_month
        """,
        "analytics_airport_month": """
            CREATE OR REPLACE TABLE analytics_airport_month AS
            WITH airport_events AS (
                SELECT
                    Origin AS airport,
                    strftime(FlightDate, '%Y-%m') AS year_month,
                    'outbound' AS direction,
                    Dest AS related_airport
                FROM analytics_flight_core
                WHERE FlightDate IS NOT NULL AND Origin IS NOT NULL
                UNION ALL
                SELECT
                    Dest AS airport,
                    strftime(FlightDate, '%Y-%m') AS year_month,
                    'inbound' AS direction,
                    Origin AS related_airport
                FROM analytics_flight_core
                WHERE FlightDate IS NOT NULL AND Dest IS NOT NULL
            )
            SELECT
                airport,
                year_month,
                COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound_flights,
                COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound_flights,
                COUNT(*) AS total_flights,
                COUNT(DISTINCT related_airport) AS unique_routes,
                COUNT(DISTINCT year_month || '-' || related_airport) AS route_month_pairs
            FROM airport_events
            WHERE related_airport IS NOT NULL
            GROUP BY airport, year_month
            ORDER BY airport, year_month
        """,
        # This is deliberately an *origin airport + month* operational
        # context table.  It makes three observed BTS signals available at a
        # compact grain: weather-coded delay exposure, NAS-coded delay
        # exposure, and how concentrated scheduled departures were in the
        # airport's busiest clock hour.  It is not a live weather feed, an
        # FAA capacity declaration, or a causal attribution table.
        "analytics_airport_operational_month": """
            CREATE OR REPLACE TABLE analytics_airport_operational_month AS
            WITH airport_month AS (
                SELECT
                    Origin AS airport,
                    strftime(FlightDate, '%Y-%m') AS year_month,
                    COUNT(*) AS total_departures,
                    COUNT(*) FILTER (
                        WHERE Cancelled = 0 AND DepDelay IS NOT NULL
                    ) AS completed_departures,
                    AVG(CASE
                        WHEN Cancelled = 0 AND DepDelay IS NOT NULL THEN DepDelay
                    END) AS avg_departure_delay_minutes,
                    AVG(CASE
                        WHEN COALESCE(WeatherDelay, 0) > 0 THEN 1.0 ELSE 0.0
                    END) AS weather_affected_rate,
                    SUM(COALESCE(WeatherDelay, 0)) / NULLIF(COUNT(*), 0)
                        AS weather_delay_minutes_per_departure,
                    AVG(CASE
                        WHEN COALESCE(NASDelay, 0) > 0 THEN 1.0 ELSE 0.0
                    END) AS nas_affected_rate,
                    SUM(COALESCE(NASDelay, 0)) / NULLIF(COUNT(*), 0)
                        AS nas_delay_minutes_per_departure
                FROM analytics_flight_core
                WHERE FlightDate IS NOT NULL AND Origin IS NOT NULL
                GROUP BY airport, year_month
            ), airport_hour AS (
                SELECT
                    Origin AS airport,
                    strftime(FlightDate, '%Y-%m') AS year_month,
                    CAST(FLOOR(CRSDepTime / 100) AS INTEGER) AS scheduled_hour,
                    COUNT(*) AS scheduled_departures
                FROM analytics_flight_core
                WHERE FlightDate IS NOT NULL
                  AND Origin IS NOT NULL
                  AND CRSDepTime IS NOT NULL
                  AND CAST(FLOOR(CRSDepTime / 100) AS INTEGER) BETWEEN 0 AND 23
                GROUP BY airport, year_month, scheduled_hour
            ), airport_peak AS (
                SELECT
                    airport,
                    year_month,
                    MAX(scheduled_departures) AS peak_hour_departures,
                    COUNT(*) AS active_scheduled_hours
                FROM airport_hour
                GROUP BY airport, year_month
            )
            SELECT
                month.airport,
                month.year_month,
                month.total_departures,
                month.completed_departures,
                month.avg_departure_delay_minutes,
                month.weather_affected_rate,
                month.weather_delay_minutes_per_departure,
                month.nas_affected_rate,
                month.nas_delay_minutes_per_departure,
                COALESCE(peak.peak_hour_departures, 0) AS peak_hour_departures,
                COALESCE(peak.peak_hour_departures, 0) / NULLIF(month.total_departures, 0)
                    AS peak_hour_share,
                COALESCE(peak.active_scheduled_hours, 0) AS active_scheduled_hours
            FROM airport_month AS month
            LEFT JOIN airport_peak AS peak
              ON month.airport = peak.airport
             AND month.year_month = peak.year_month
            ORDER BY month.airport, month.year_month
        """,
        "analytics_route_hour": """
            CREATE OR REPLACE TABLE analytics_route_hour AS
            SELECT
                Origin AS origin,
                Dest AS dest,
                Marketing_Airline_Network AS carrier,
                CAST(FLOOR(CRSDepTime / 100) AS INTEGER) AS departure_hour,
                COUNT(*) AS total_flights,
                COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS completed_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                quantile_cont(ArrDelay, 0.50) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS median_arrival_delay_minutes,
                quantile_cont(ArrDelay, 0.90) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS p90_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM analytics_flight_core
            WHERE Origin IS NOT NULL AND Dest IS NOT NULL AND CRSDepTime IS NOT NULL
            GROUP BY Origin, Dest, Marketing_Airline_Network, departure_hour
            ORDER BY origin, dest, carrier, departure_hour
        """,
    }

    counts: dict[str, int] = {CORE_TABLE_NAME: core_count}
    for table_name in ANALYTICS_TABLES:
        if table_name == CORE_TABLE_NAME or table_name in PROFILE_TABLES:
            continue
        if table_name == "analytics_t100_route_month":
            counts[table_name] = build_t100_route_month_table(connection)
            continue
        connection.execute(statements[table_name])
        counts[table_name] = int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    counts.update(build_profile_summary_tables(connection))
    return counts


def main() -> None:
    """Refresh the compact dashboard tables in the configured warehouse."""
    if not DUCKDB_FILE.exists():
        raise SystemExit(f"Warehouse not found: {DUCKDB_FILE}")
    connection = duckdb.connect(str(DUCKDB_FILE))
    try:
        counts = build_analytics_tables(connection)
        for table_name, count in counts.items():
            print(f"{table_name}: {count:,} rows")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
