from datetime import date

import duckdb

from pipeline.materialize_analytics import build_analytics_tables, build_t100_route_month_table
from pipeline.otp_core import OTP_CORE_COLUMNS


TEXT_COLUMNS = {
    "Marketing_Airline_Network", "Operating_Airline", "Tail_Number", "Origin", "Dest",
    "CancellationCode",
}
DATE_COLUMNS = {"FlightDate"}


def test_materialized_airport_operational_month_uses_real_otp_fields():
    connection = duckdb.connect(":memory:")
    schema = ", ".join(
        f'"{column}" ' + ("DATE" if column in DATE_COLUMNS else "VARCHAR" if column in TEXT_COLUMNS else "DOUBLE")
        for column in OTP_CORE_COLUMNS
    )
    connection.execute(f"CREATE TABLE flights ({schema})")
    try:
        connection.execute(
            """
            INSERT INTO flights (FlightDate, Marketing_Airline_Network, Operating_Airline, Origin, Dest,
                CRSDepTime, Cancelled, Diverted, DepDelay, ArrDelay, ArrDel15, Distance, WeatherDelay, NASDelay)
            VALUES
                (?, 'AA', 'AA', 'ORD', 'LAX', 700, 0, 0, 12, 15, 1, 1744, 10, 0),
                (?, 'AA', 'AA', 'ORD', 'JFK', 700, 0, 0, 20, 22, 1, 740, 0, 20),
                (?, 'AA', 'AA', 'ORD', 'DFW', 815, 0, 0, 5, 3, 0, 800, 0, 0)
            """,
            [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)],
        )
        counts = build_analytics_tables(connection)
        row = connection.execute(
            """
            SELECT total_departures, weather_affected_rate, weather_delay_minutes_per_departure,
                   nas_affected_rate, nas_delay_minutes_per_departure, peak_hour_departures,
                   peak_hour_share
            FROM analytics_airport_operational_month
            WHERE airport = 'ORD' AND year_month = '2025-01'
            """
        ).fetchone()
    finally:
        connection.close()

    assert counts["analytics_airport_operational_month"] == 1
    assert row == (3, 1 / 3, 10 / 3, 1 / 3, 20 / 3, 2, 2 / 3)


def test_compact_t100_route_month_aggregates_detail_rows_once_per_route_month():
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE bts_t100_segment_route_month (
            Origin VARCHAR, Dest VARCHAR, Year INTEGER, Month INTEGER,
            seats_available BIGINT, passengers BIGINT,
            departures_scheduled BIGINT, departures_performed BIGINT
        )
        """
    )
    try:
        connection.execute(
            """
            INSERT INTO bts_t100_segment_route_month VALUES
                ('ORD', 'LAX', 2025, 1, 100, 80, 10, 9),
                ('ORD', 'LAX', 2025, 1, 50, 35, 5, 5),
                ('ORD', 'SFO', 2025, 1, 90, 72, 9, 9)
            """
        )
        count = build_t100_route_month_table(connection)
        row = connection.execute(
            """
            SELECT seats_available, passengers, departures_scheduled,
                   departures_performed, load_factor, completion_rate
            FROM analytics_t100_route_month
            WHERE origin = 'ORD' AND dest = 'LAX' AND period_date = DATE '2025-01-01'
            """
        ).fetchone()
    finally:
        connection.close()

    assert count == 2
    assert row == (150, 115, 15, 14, 115 / 150, 14 / 15)
