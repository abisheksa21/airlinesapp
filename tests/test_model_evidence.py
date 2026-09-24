from datetime import date

import duckdb

from api.model_evidence import build_route_panel_temporal_evidence
from api.route_ml_forecast import _query_route_panel


def _panel_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE analytics_route_month (
            origin VARCHAR, dest VARCHAR, year_month VARCHAR,
            total_flights BIGINT, completed_flights BIGINT,
            on_time_rate DOUBLE, avg_arrival_delay_minutes DOUBLE,
            cancellation_rate DOUBLE, distance_miles DOUBLE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE bts_t100_segment_route_month (
            Origin VARCHAR, Dest VARCHAR, Year INTEGER, Month INTEGER,
            seats_available BIGINT, passengers BIGINT,
            departures_scheduled BIGINT, departures_performed BIGINT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE analytics_airport_operational_month (
            airport VARCHAR, year_month VARCHAR, total_departures BIGINT,
            completed_departures BIGINT, avg_departure_delay_minutes DOUBLE,
            weather_affected_rate DOUBLE, weather_delay_minutes_per_departure DOUBLE,
            nas_affected_rate DOUBLE, nas_delay_minutes_per_departure DOUBLE,
            peak_hour_departures BIGINT, peak_hour_share DOUBLE,
            active_scheduled_hours BIGINT
        )
        """
    )
    panel_rows = []
    traffic_rows = []
    operational_rows = []
    for route_index in range(8):
        origin = f"A{route_index:02d}"
        dest = f"B{route_index:02d}"
        for month_index in range(48):
            year = 2019 + month_index // 12
            month = month_index % 12 + 1
            period = f"{year:04d}-{month:02d}"
            delay = 7.0 + route_index + (month_index % 7)
            on_time = 0.94 - ((route_index + month_index) % 8) * 0.025
            panel_rows.append((origin, dest, period, 120, 115, on_time, delay, 0.01 + route_index * 0.002, 300 + route_index * 50))
            traffic_rows.append((origin, dest, year, month, 1500, 1050 + month_index * 2, 120, 118))
            operational_rows.append((
                origin, period, 1000 + route_index * 25, 970, 5 + month_index % 5,
                0.03 + (month_index % 4) * 0.01, 0.8 + month_index % 3,
                0.06 + (route_index % 3) * 0.01, 1.4 + month_index % 4,
                85 + route_index, 0.09, 18,
            ))
    connection.executemany("INSERT INTO analytics_route_month VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", panel_rows)
    connection.executemany("INSERT INTO bts_t100_segment_route_month VALUES (?, ?, ?, ?, ?, ?, ?, ?)", traffic_rows)
    connection.executemany("INSERT INTO analytics_airport_operational_month VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", operational_rows)
    return connection


def test_model_evidence_uses_strictly_lagged_t100_and_operational_context():
    connection = _panel_connection()
    try:
        rows = _query_route_panel(connection, target_period="2023-01")
        february = next(row for row in rows if row["origin"] == "A00" and row["period"] == "2019-02")
        assert february["traffic_period"] == "2019-01"
        assert february["operational_period"] == "2019-01"

        result = build_route_panel_temporal_evidence(
            connection,
            force=True,
            max_windows=3,
            minimum_training_periods=12,
            test_horizon_months=3,
            minimum_training_examples=60,
        )
    finally:
        connection.close()

    assert result["status"] == "ready"
    assert result["data"]["network_routes_available"] == 8
    assert result["data"]["routes"] == 8
    assert "not selected by delay" in result["data"]["route_sampling"]
    assert result["data"]["t100_context_share"] > 0
    assert result["data"]["operational_context_share"] > 0
    method_ids = {method["id"] for method in result["methods"]}
    assert {"math_baseline", "otp_history", "otp_t100", "otp_t100_operations"}.issubset(method_ids)
    assert len(result["evaluation"]["windows"]) == 3
    assert result["evaluation"]["test_windows_do_not_overlap"] is True
    test_starts = [window["test_start"] for window in result["evaluation"]["windows"]]
    assert test_starts == sorted(test_starts)
    assert all(
        (int(later[:4]) * 12 + int(later[5:])) - (int(earlier[:4]) * 12 + int(earlier[5:])) >= 3
        for earlier, later in zip(test_starts, test_starts[1:])
    )
    for window in result["evaluation"]["windows"]:
        assert window["training_through"] < window["test_start"]
        assert "otp_t100_operations" in window["metrics"]
    comparison = result["evaluation"]["comparison_to_historical_baseline"]
    assert "otp_t100" in comparison["delay_minutes"]
    assert comparison["delay_minutes"]["otp_t100"]["status"] in {
        "supported_candidate", "keep_exploratory",
    }
