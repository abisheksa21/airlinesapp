from datetime import date, timedelta

import duckdb

from api.optimization.departure_bank_validation import validate_departure_bank_history


def _connection_with_history() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE flights (
            FlightDate DATE,
            Origin VARCHAR,
            CRSDepTime INTEGER,
            Cancelled INTEGER,
            ArrDelay DOUBLE,
            Marketing_Airline_Network VARCHAR
        )
        """
    )
    rows = []
    for year in range(2021, 2026):
        start = date(year, 1, 1)
        for day_offset in range(10):
            current = start + timedelta(days=day_offset)
            # A deliberately concentrated historical bank that can be spread
            # across nearby 15-minute buckets under a ±30-minute rule.
            rows.extend((current, "ORD", 700, 0, 18.0, "AA") for _ in range(5))
            rows.extend((current, "ORD", 715, 0, 16.0, "AA") for _ in range(3))
            rows.extend((current, "ORD", 800, 0, 8.0, "AA") for _ in range(2))
    connection.executemany("INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?)", rows)
    return connection


def test_historical_bank_validation_uses_earlier_equivalent_windows():
    connection = _connection_with_history()
    try:
        result = validate_departure_bank_history(
            connection,
            airport="ord",
            carrier="aa",
            start_date="2025-01-01",
            end_date="2025-01-10",
            window_start_hour=6,
            window_end_hour=10,
            allowed_shift_minutes=30,
            maximum_windows=2,
            reference_lookback_years=2,
            flight_limit=150,
        )
    finally:
        connection.close()

    assert result["status"] == "ready"
    assert result["summary"]["windows_evaluated"] == 2
    assert len(result["records"]) == 2
    assert all(record["reference_years_used"] == 2 for record in result["records"])
    assert all(record["test_window"].startswith(("2024", "2023")) for record in result["records"])
    assert "not a causal estimate" in result["methodology"]["not_claimed"]
