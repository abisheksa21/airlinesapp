import duckdb

from api.optimization.network_protection_validation import (
    build_network_protection_temporal_validation,
)


def _validation_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE analytics_carrier_month (
            carrier VARCHAR,
            year_month VARCHAR,
            total_flights BIGINT,
            completed_flights BIGINT,
            on_time_rate DOUBLE,
            avg_arrival_delay_minutes DOUBLE,
            severe_delay_rate DOUBLE,
            cancellation_rate DOUBLE,
            diversion_rate DOUBLE
        )
        """
    )
    rows = []
    # AA has persistently greater severe-delay exposure. The replay must
    # select it from a past window and only then encounter that same pattern
    # in held-back later months.
    # Keep every rate below the Health Score's 20% severe-delay cap so the
    # expected exposure ranking is distinct rather than tied at 100.
    severe_counts = {"AA": 3, "BB": 2, "CC": 1, "DD": 0}
    for month_index in range(36):
        year = 2023 + month_index // 12
        month = month_index % 12 + 1
        year_month = f"{year:04d}-{month:02d}"
        for carrier, severe_count in severe_counts.items():
            severe_rate = severe_count / 20
            rows.append((
                carrier, year_month, 20, 20,
                1.0 - severe_rate, 90.0 * severe_rate, severe_rate, 0.0, 0.0,
            ))
    connection.executemany("INSERT INTO analytics_carrier_month VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return connection


def test_portfolio_replay_uses_only_earlier_windows_and_checks_later_exposure():
    connection = _validation_connection()
    try:
        result = build_network_protection_temporal_validation(
            connection,
            candidate_type="carrier",
            budget=1,
            primary_metric="severe_delay_exposure",
            cost_model="unit",
            maximum_windows=3,
            reference_months=12,
            outcome_horizon_months=3,
            force=True,
        )
    finally:
        connection.close()

    assert result["status"] == "ready"
    assert result["summary"]["windows_evaluated"] == 3
    assert result["summary"]["windows_with_positive_selection_lift"] == 3
    for record in result["records"]:
        assert record["status"] == "ready"
        assert record["selected_ids"] == ["AA"]
        assert record["selection_lift"] > 0
        assert record["top_k_hits"] == 1
        assert record["reference_window"].split(" to ")[1] < record["future_window"].split(" to ")[0]
    assert "not a causal estimate" in result["methodology"]["not_claimed"]
