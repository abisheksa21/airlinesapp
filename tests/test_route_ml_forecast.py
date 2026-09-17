"""Tests for the first route-level ML forecast layer."""

from calendar import monthrange
from datetime import date

import duckdb

from api.route_ml_forecast import (
    PANEL_FEATURE_NAMES,
    PANEL_NO_T100_FEATURE_NAMES,
    build_feature_vector,
    build_route_panel_ml_forecast,
    build_route_ml_forecast,
)


def _flight_rows():
    rows = []
    for month_index in range(60):
        year = 2024 + month_index // 12
        month = month_index % 12 + 1
        delay = 4.0 + (month_index % 14) * 1.5
        cancellations = 2 if month_index % 5 == 0 else 0
        for flight_index in range(30):
            flight_date = date(year, month, min(flight_index + 1, monthrange(year, month)[1]))
            cancelled = int(flight_index < cancellations)
            arrival_delay = None if cancelled else delay + (flight_index % 3 - 1)
            late = None if cancelled else int(arrival_delay >= 15)
            rows.append((
                flight_date,
                "JFK",
                "LAX",
                "AA",
                800,
                cancelled,
                arrival_delay,
                late,
            ))
    return rows


def _connection_with_flights():
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
    connection.executemany("INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?, ?)", _flight_rows())
    return connection


def test_route_ml_forecast_trains_and_returns_all_three_predictions():
    connection = _connection_with_flights()
    try:
        result = build_route_ml_forecast(
            connection,
            origin="jfk",
            dest="lax",
            carrier="aa",
            departure_hour=8,
            target_month="2029-01",
        )
    finally:
        connection.close()

    assert result["status"] == "candidate"
    assert result["model"] == "route_ridge_ml"
    assert result["training_cutoff"] == "2029-01-01"
    assert result["training_examples"] >= 36
    assert result["predictions"]["expected_arrival_delay_minutes"] >= 0
    assert 0 <= result["predictions"]["late_probability"] <= 1
    assert 0 <= result["predictions"]["cancellation_probability"] <= 1
    assert result["test_metrics"]["examples"] >= 6
    assert set(result["coefficients"]) == {"delay_minutes", "late_rate", "cancellation_rate"}


def test_feature_builder_cannot_change_when_future_rows_are_added():
    prior = [
        {
            "period": "2025-01",
            "completed_flights": 100,
            "scheduled_flights": 100,
            "late_flights": 20,
            "delay_sum": 800,
            "cancelled_flights": 0,
            "traffic_load_factor": 0.72,
            "traffic_passengers": 720,
            "traffic_seats_available": 1000,
            "traffic_completion_rate": 0.98,
        }
    ]
    context = {
        "traffic_load_factor": 0.74,
        "traffic_passengers": 740,
        "traffic_seats_available": 1000,
        "traffic_completion_rate": 0.99,
    }
    baseline = build_feature_vector(prior, context, period="2025-02")
    future = {
        "period": "2025-03",
        "completed_flights": 100,
        "scheduled_flights": 100,
        "late_flights": 100,
        "delay_sum": 10000,
        "cancelled_flights": 100,
    }

    # The builder enforces the cutoff itself, so even an accidentally broad
    # history list cannot make a future month alter an earlier forecast.
    assert build_feature_vector(prior + [future], context, period="2025-02") == baseline


def test_route_ml_reports_insufficient_history_instead_of_faking_a_model():
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
        [(date(2025, 1, 1), "JFK", "LAX", "AA", 800, 0, 10.0, 0)] * 40,
    )
    try:
        result = build_route_ml_forecast(
            connection,
            origin="JFK",
            dest="LAX",
            carrier="AA",
            target_month="2025-02",
        )
    finally:
        connection.close()

    assert result["status"] == "insufficient_history"
    assert result["model"] == "route_ridge_ml"


def test_route_panel_model_trains_across_routes_and_scores_one_route():
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE analytics_route_month (
            origin VARCHAR,
            dest VARCHAR,
            year_month VARCHAR,
            total_flights BIGINT,
            completed_flights BIGINT,
            on_time_rate DOUBLE,
            avg_arrival_delay_minutes DOUBLE,
            cancellation_rate DOUBLE,
            distance_miles DOUBLE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE bts_t100_segment_route_month (
            Origin VARCHAR,
            Dest VARCHAR,
            Year INTEGER,
            Month INTEGER,
            seats_available BIGINT,
            passengers BIGINT,
            departures_scheduled BIGINT,
            departures_performed BIGINT
        )
        """
    )
    rows = []
    traffic_rows = []
    for route_index in range(12):
        origin = f"A{route_index:02d}"
        dest = f"B{route_index:02d}"
        for month_index in range(60):
            year = 2024 + month_index // 12
            month = month_index % 12 + 1
            delay = 8.0 + route_index + (month_index % 8)
            rows.append((
                origin,
                dest,
                f"{year:04d}-{month:02d}",
                100,
                98,
                max(0.55, 0.95 - ((route_index + month_index) % 10) * 0.03),
                delay,
                0.01 + (route_index % 4) * 0.005,
                300.0 + route_index * 100,
            ))
            traffic_rows.append((
                origin,
                dest,
                year,
                month,
                1000,
                760 + (month_index % 4) * 10,
                100,
                97,
            ))
    connection.executemany("INSERT INTO analytics_route_month VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.executemany("INSERT INTO bts_t100_segment_route_month VALUES (?, ?, ?, ?, ?, ?, ?, ?)", traffic_rows)
    try:
        result = build_route_panel_ml_forecast(
            connection,
            origin="A00",
            dest="B00",
            target_month="2029-01",
        )
    finally:
        connection.close()

    assert result["status"] == "candidate"
    assert result["model"] == "route_panel_ridge_ml"
    assert result["routes_in_training_panel"] == 12
    assert result["route_history_months"] == 60
    assert result["training_examples"] >= 120
    assert result["test_metrics"]["examples"] > 0
    assert len(result["coefficients"]["delay_minutes"]) == len(PANEL_FEATURE_NAMES)
    assert result["features_for_target"]["traffic_context_available"] == 1.0
    assert result["features_for_target"]["traffic_load_factor"] > 0.0
    assert result["features_for_target"]["traffic_staleness_months"] == 1.0
    assert result["t100_ablation"]["with_t100_test_metrics"]["examples"] == result["test_metrics"]["examples"]
    assert result["t100_ablation"]["without_t100_test_metrics"]["examples"] == result["test_metrics"]["examples"]
    assert result["t100_ablation"]["without_t100_features"] == list(PANEL_NO_T100_FEATURE_NAMES)
    assert all(not name.startswith("traffic_") for name in result["t100_ablation"]["without_t100_features"])
