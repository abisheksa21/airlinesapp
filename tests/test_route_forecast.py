"""Tests for the leakage-safe route forecast helpers."""

from api.route_forecast import (
    MIN_COMPLETED_FOR_MATCH,
    build_route_forecast,
    expanding_baseline_backtest,
    parse_target_month,
    wilson_interval,
)
from datetime import date, timedelta
from contextlib import contextmanager

import duckdb


def test_wilson_interval_is_bounded_and_contains_observed_rate():
    interval = wilson_interval(80, 100)
    assert interval is not None
    assert 0 <= interval[0] < 0.8 < interval[1] <= 1


def test_target_month_defaults_to_the_month_after_latest_observation():
    assert parse_target_month(None, date(2026, 6, 18)) == date(2026, 7, 1)
    assert parse_target_month("2025-09", date(2026, 6, 18)) == date(2025, 9, 1)


def test_expanding_backtest_uses_only_prior_months():
    rows = [
        {"period": "2025-01", "completed_flights": MIN_COMPLETED_FOR_MATCH, "late_flights": 0, "delay_sum": 0},
        {"period": "2025-02", "completed_flights": 10, "late_flights": 10, "delay_sum": 1000},
        {"period": "2025-03", "completed_flights": 10, "late_flights": 0, "delay_sum": 0},
    ]
    result = expanding_baseline_backtest(rows)
    assert result["months_scored"] == 2
    assert result["mean_absolute_error_minutes"] == 62.5


def test_expanding_backtest_reports_insufficient_history():
    result = expanding_baseline_backtest([
        {"period": "2025-01", "completed_flights": 10, "late_flights": 2, "delay_sum": 20},
    ])
    assert result["status"] == "insufficient_history"
    assert result["months_scored"] == 0


def test_route_forecast_respects_target_cutoff_and_requested_slice():
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE flights (
            FlightDate DATE,
            Origin VARCHAR,
            Dest VARCHAR,
            Marketing_Airline_Network VARCHAR,
            CRSDepTime INTEGER,
            Cancelled INTEGER,
            ArrDelay DOUBLE,
            ArrDel15 INTEGER
        )
        """
    )

    rows = []
    for index in range(30):
        rows.append((date(2024, 1, 1) + timedelta(days=index), "JFK", "LAX", "AA", 800, 0, 10.0, 0))
    for index in range(30):
        rows.append((date(2024, 2, 1) + timedelta(days=index % 28), "JFK", "LAX", "AA", 800, 0, 20.0, 1))
    # These rows must not leak into a March forecast because they occur in the
    # requested target month. Their extreme delay makes leakage obvious.
    for index in range(10):
        rows.append((date(2024, 3, 1) + timedelta(days=index), "JFK", "LAX", "AA", 800, 0, 100.0, 1))
    connection.executemany("INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    result = build_route_forecast(
        connection,
        origin="jfk",
        dest="lax",
        carrier="aa",
        departure_hour=8,
        target_month="2024-03",
    )

    assert result["matched_scope"] == "route + airline + departure hour"
    assert result["training_cutoff"] == "2024-03-01"
    assert result["completed_flights"] == 60
    assert result["expected_arrival_delay_minutes"] == 15.0
    assert result["late_probability"] == 0.5
    assert result["validation"]["months_scored"] == 1
    connection.close()


def test_route_forecast_uses_prior_t100_load_band_without_leakage():
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE flights (
            FlightDate DATE,
            Origin VARCHAR,
            Dest VARCHAR,
            Marketing_Airline_Network VARCHAR,
            CRSDepTime INTEGER,
            Cancelled INTEGER,
            ArrDelay DOUBLE,
            ArrDel15 INTEGER
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE bts_t100_segment_route_month (
            Year INTEGER,
            Month INTEGER,
            UniqueCarrier VARCHAR,
            Origin VARCHAR,
            Dest VARCHAR,
            seats_available INTEGER,
            passengers INTEGER,
            departures_scheduled INTEGER,
            departures_performed INTEGER
        )
        """
    )

    month_specs = [(1, 5.0, 0), (2, 10.0, 0), (3, 15.0, 1), (4, 20.0, 1)]
    flight_rows = []
    for month, delay, late_flag in month_specs:
        for index in range(30):
            flight_rows.append((date(2024, month, 1) + timedelta(days=index % 28), "JFK", "LAX", "AA", 800, 0, delay, late_flag))
    connection.executemany("INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?, ?)", flight_rows)

    traffic_rows = [(2023, 12, "AA", "JFK", "LAX", 1000, 900, 30, 30)]
    traffic_rows.extend((2024, month, "AA", "JFK", "LAX", 1000, 900, 30, 30) for month in range(1, 5))
    connection.executemany("INSERT INTO bts_t100_segment_route_month VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", traffic_rows)

    result = build_route_forecast(
        connection,
        origin="JFK",
        dest="LAX",
        carrier="AA",
        departure_hour=8,
        target_month="2024-05",
    )

    assert result["model"] == "t100_traffic_band_baseline"
    assert result["traffic_context"]["status"] == "used"
    assert result["traffic_context"]["reference_period"] == "2024-04"
    assert result["traffic_context"]["traffic_band"] == "higher load"
    assert result["traffic_context"]["matched_months"] == 4
    assert result["traffic_context"]["matched_late_flights"] == 60
    assert result["expected_arrival_delay_minutes"] == 12.5
    connection.close()


def test_api_route_forecast_opens_database_context(monkeypatch):
    import api.main as main

    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE flights (
            FlightDate DATE,
            Origin VARCHAR,
            Dest VARCHAR,
            Marketing_Airline_Network VARCHAR,
            CRSDepTime INTEGER,
            Cancelled INTEGER,
            ArrDelay DOUBLE,
            ArrDel15 INTEGER
        )
        """
    )
    connection.executemany(
        "INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (date(2024, 1, 1) + timedelta(days=index), "JFK", "LAX", "AA", 800, 0, 10.0, 0)
            for index in range(30)
        ],
    )

    @contextmanager
    def database_context():
        yield connection

    monkeypatch.setattr(main, "open_readonly_connection", lambda: database_context())
    result = main.route_forecast(
        origin="JFK",
        dest="LAX",
        carrier="AA",
        departure_hour=8,
        target_month="2024-02",
    )

    assert result["completed_flights"] == 30
    assert result["model"] == "historical_baseline"
