"""
Tests for the trend_severe_delay_rate / seasonal_index upgrade to the
Predictive Risk Screen (api/predictive_risk.py). Every assertion here was
executed directly against the real, unmodified production functions in
this session (duckdb stubbed at import time only -- the functions under
test never call into it).
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub duckdb so api.predictive_risk imports cleanly without the package
# installed -- the functions tested here never call into it.
if "duckdb" not in sys.modules:
    _stub = types.ModuleType("duckdb")
    _stub.connect = lambda *a, **k: None
    _stub.DuckDBPyConnection = object
    sys.modules["duckdb"] = _stub

from api.predictive_risk import (
    FEATURE_NAMES,
    _trend_and_seasonal,
    build_supervised_examples,
    historical_risk_baseline_probability,
    historical_risk_baseline_probabilities,
)


class TestFeatureSetGrewCorrectly:
    def test_eight_features_including_both_new_ones(self):
        assert len(FEATURE_NAMES) == 8
        assert "trend_severe_delay_rate" in FEATURE_NAMES
        assert "seasonal_index" in FEATURE_NAMES


def _make_panel(entities_with_spike_month: dict[str, int | None], years=(2024, 2025)) -> list[dict]:
    rows = []
    for entity, spike_month in entities_with_spike_month.items():
        for year in years:
            for month in range(1, 13):
                base = 0.30 if (spike_month is not None and month == spike_month) else 0.10
                rows.append({
                    "entity": entity, "period": f"{year}-{month:02d}",
                    "flight_volume": 1000, "severe_delay_rate": base,
                    "cancellation_rate": 0.02, "average_departure_delay": 10.0,
                    "late_aircraft_delay_share": 0.3, "ground_delay_share": 0.15,
                })
    return rows


class TestSeasonalIndexThroughRealPipeline:
    def test_recurring_bad_month_detected(self):
        rows = _make_panel({"AA": 9, "BB": None})
        examples, _, _ = build_supervised_examples(rows, risk_quantile=0.75)
        sept = next(e for e in examples if e["entity"] == "AA" and e["feature_period"] == "2025-09")
        assert sept["features"][7] > 0.1  # seasonal_index

    def test_entity_with_no_pattern_shows_near_zero(self):
        rows = _make_panel({"AA": 9, "BB": None})
        examples, _, _ = build_supervised_examples(rows, risk_quantile=0.75)
        bb_sept = next(e for e in examples if e["entity"] == "BB" and e["feature_period"] == "2025-09")
        assert abs(bb_sept["features"][7]) < 0.01


class TestNoFutureLeakage:
    def test_altering_a_later_month_does_not_change_an_earlier_feature(self):
        """The critical property: computing an earlier month's trend/seasonal
        feature must be provably unaffected by what happens in a later
        month for the same entity."""
        series_a = [{"period": f"2025-{m:02d}", "severe_delay_rate": 0.1} for m in range(1, 8)]
        trend_before, seasonal_before = _trend_and_seasonal(series_a, index=3)  # April

        series_b = [dict(r) for r in series_a]
        series_b[5]["severe_delay_rate"] = 0.99  # corrupt June -- AFTER April
        trend_after, seasonal_after = _trend_and_seasonal(series_b, index=3)

        assert trend_before == trend_after
        assert seasonal_before == seasonal_after

    def test_altering_an_earlier_month_within_the_lookback_window_does_change_trend(self):
        """Sanity check on the above -- this ISN'T testing that nothing
        ever changes anything. A month INSIDE the 3-month lookback window
        should influence trend (that's the whole point of a trend feature)."""
        series_a = [{"period": f"2025-{m:02d}", "severe_delay_rate": 0.1} for m in range(1, 8)]
        trend_before, _ = _trend_and_seasonal(series_a, index=5)  # June; window = series[2:5] = Mar/Apr/May

        series_b = [dict(r) for r in series_a]
        series_b[3]["severe_delay_rate"] = 0.99  # April (index 3) -- INSIDE the window
        trend_after, _ = _trend_and_seasonal(series_b, index=5)

        assert trend_before != trend_after

    def test_month_outside_the_lookback_window_has_no_effect(self):
        """The boundary case: February (index 1) is OUTSIDE June's 3-month
        window (series[2:5] = Mar/Apr/May) -- confirms the window is
        exactly as wide as documented, not accidentally wider."""
        series_a = [{"period": f"2025-{m:02d}", "severe_delay_rate": 0.1} for m in range(1, 8)]
        trend_before, _ = _trend_and_seasonal(series_a, index=5)

        series_b = [dict(r) for r in series_a]
        series_b[1]["severe_delay_rate"] = 0.99  # February -- outside the window
        trend_after, _ = _trend_and_seasonal(series_b, index=5)

        assert trend_before == trend_after


class TestTrendDirection:
    def test_worsening_trajectory_produces_positive_trend(self):
        series = [{"period": f"2025-{m:02d}", "severe_delay_rate": 0.05 + 0.03 * m} for m in range(1, 7)]
        trend, _ = _trend_and_seasonal(series, index=5)
        assert trend > 0.05

    def test_improving_trajectory_produces_negative_trend(self):
        series = [{"period": f"2025-{m:02d}", "severe_delay_rate": 0.30 - 0.03 * m} for m in range(1, 7)]
        trend, _ = _trend_and_seasonal(series, index=5)
        assert trend < -0.05

    def test_no_prior_history_gives_neutral_zero_not_a_guess(self):
        series = [{"period": "2025-01", "severe_delay_rate": 0.5}]
        trend, seasonal = _trend_and_seasonal(series, index=0)
        assert trend == 0.0
        assert seasonal == 0.0


class TestSeasonalIndexIsNotSelfReferential:
    def test_altering_the_current_rows_own_rate_does_not_change_its_seasonal_index(self):
        """seasonal_index's baseline (overall_avg) used to include the
        current row itself, so a high current-month rate would mechanically
        pull its own seasonal_index down by inflating the baseline it's
        subtracted from -- independent of any real seasonal pattern. Fixed
        by excluding the current row from overall_avg, matching how trend
        already excludes it. This test would have FAILED before that fix."""
        series_a = [
            {"period": f"{year}-{month:02d}", "severe_delay_rate": 0.1}
            for year in (2024, 2025) for month in range(1, 13)
        ]
        idx = next(i for i, r in enumerate(series_a) if r["period"] == "2025-09")
        _, seasonal_before = _trend_and_seasonal(series_a, idx)

        series_b = [dict(r) for r in series_a]
        series_b[idx]["severe_delay_rate"] = 0.99  # only the CURRENT row's own value
        _, seasonal_after = _trend_and_seasonal(series_b, idx)

        assert seasonal_before == seasonal_after


class TestTrendLookbackIsCalendarAware:
    def test_a_gap_month_does_not_silently_widen_the_lookback_window(self):
        """The lookback used to be list-position based (series[index-3:index]),
        so a month dropped upstream by the minimum_flights filter would
        silently widen "prior 3 months" past 3 actual calendar months. Now
        it's calendar-distance based via _period_index, so a month more
        than 3 calendar months back is excluded even if it's still within
        3 LIST positions because of a gap."""
        series = [
            {"period": "2025-01", "severe_delay_rate": 0.9},  # 5 calendar months before June -- OUT of a 3-month window
            {"period": "2025-05", "severe_delay_rate": 0.1},  # 1 month before June -- IN
            {"period": "2025-06", "severe_delay_rate": 0.1},  # current, index=2
        ]
        trend, _ = _trend_and_seasonal(series, index=2)
        # If January were wrongly included (old list-position behavior),
        # prior_avg would be (0.9+0.1)/2=0.5 and trend would be -0.4.
        # Calendar-aware, only May counts: prior_avg=0.1, trend=0.0.
        assert trend == 0.0


class TestThresholdDoesNotLeakFutureOutcomes:
    def test_altering_a_post_train_period_outcome_does_not_change_the_threshold(self):
        """The risk-label threshold used to be a quantile over ALL
        next-period outcomes (train+validation+test) computed before any
        split existed -- so a test-period outcome could influence what
        counted as "risky" for a training-period example, which is
        look-ahead bias. Now the threshold is computed only from examples
        whose target_period falls within the training portion. This test
        would have FAILED before that fix."""
        rows = []
        for entity in ("AA", "BB", "CC"):
            for i in range(20):
                year, month = 2024 + i // 12, i % 12 + 1
                rows.append({
                    "entity": entity, "period": f"{year}-{month:02d}",
                    "flight_volume": 1000, "severe_delay_rate": 0.05 + 0.01 * (i % 5),
                    "cancellation_rate": 0.02, "average_departure_delay": 10.0,
                    "late_aircraft_delay_share": 0.3, "ground_delay_share": 0.15,
                })
        _, threshold_before, train_end = build_supervised_examples(rows, risk_quantile=0.75)

        rows_after = [dict(r) for r in rows]
        for r in rows_after:
            if r["entity"] == "AA" and r["period"] > train_end:
                r["severe_delay_rate"] = 0.99  # a large, late-period outcome
                break
        else:
            raise AssertionError("test setup: no post-train_end row found for AA")
        _, threshold_after, _ = build_supervised_examples(rows_after, risk_quantile=0.75)

        assert threshold_before == threshold_after


class TestHistoricalRiskBaseline:
    def test_new_entity_uses_panel_fallback(self):
        rows = [{"entity": "NEW", "target_period": "2025-01", "label": 1}]
        predictions = historical_risk_baseline_probabilities(
            rows, known_history=[], fallback_probability=0.23
        )
        assert predictions.tolist() == [0.23]

    def test_expanding_rate_uses_only_earlier_labels(self):
        history = [{"entity": "AA", "target_period": "2024-01", "label": 1}]
        rows = [
            {"entity": "AA", "target_period": "2024-02", "label": 0},
            {"entity": "AA", "target_period": "2024-03", "label": 1},
        ]
        predictions = historical_risk_baseline_probabilities(
            rows, known_history=history, fallback_probability=0.10
        )
        # One earlier risky month: (1 + 1) / (1 + 2) = 2/3.
        # The second row can see February's observed 0, but not its own label:
        # (1 + 1) / (2 + 2) = 1/2.
        assert predictions[0] == 2 / 3
        assert predictions[1] == 1 / 2

    def test_scored_rows_are_returned_in_original_order(self):
        rows = [
            {"entity": "AA", "target_period": "2024-03", "label": 0},
            {"entity": "AA", "target_period": "2024-02", "label": 1},
        ]
        predictions = historical_risk_baseline_probabilities(
            rows, known_history=[], fallback_probability=0.10
        )
        assert predictions.tolist() == [2 / 3, 0.10]

    def test_single_entity_score_matches_same_baseline_formula(self):
        history = [
            {"entity": "AA", "target_period": "2024-01", "label": 1},
            {"entity": "AA", "target_period": "2024-02", "label": 0},
        ]
        assert historical_risk_baseline_probability(
            entity="AA", known_history=history, fallback_probability=0.10
        ) == 0.5
