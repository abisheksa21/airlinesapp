"""
Tests for api/health_score.py, including the standard-error / confidence-
interval machinery added alongside the existing point score, and the
two-score z-test comparison helper. No prior test file covered this module
at all.

The main test builds a tiny synthetic `flights` table in an in-memory
DuckDB connection and runs the REAL RAW_STAT_SELECT_EXPRS SQL against it,
then checks score_from_row's output against numbers worked out
independently with plain numpy (not by re-deriving health_score.py's own
formula) -- this exercises the actual SQL column order/positions, not just
the Python-side math in isolation.
"""

import sys
from pathlib import Path

import duckdb
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.health_score import (
    RAW_STAT_SELECT_EXPRS,
    compare_health_scores,
    score_from_row,
)


def _build_connection(rows: list[tuple]) -> duckdb.DuckDBPyConnection:
    """rows: (Cancelled, Diverted, ArrDelay) tuples, ArrDelay may be None."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE flights (Cancelled INTEGER, Diverted INTEGER, ArrDelay DOUBLE, ArrDel15 INTEGER)")
    if rows:
        con.executemany(
            "INSERT INTO flights VALUES (?, ?, ?, ?)",
            [(*row, None if row[2] is None else int(row[2] > 15)) for row in rows],
        )
    return con


class TestScoreFromRowAgainstIndependentCalculation:
    def test_matches_hand_derived_stats_via_numpy(self):
        # 4 completed flights (delays 0, 10, 20, 80), 1 cancelled, 0 diverted.
        rows = [
            (0, 0, 0.0),
            (0, 0, 10.0),
            (0, 0, 20.0),
            (0, 0, 80.0),
            (1, 0, None),
        ]
        con = _build_connection(rows)
        row = con.execute(f"SELECT {RAW_STAT_SELECT_EXPRS} FROM flights").fetchone()
        con.close()

        result = score_from_row(row)
        assert result is not None

        delays = np.array([0.0, 10.0, 20.0, 80.0])
        on_time = np.array([1.0, 1.0, 0.0, 0.0])  # <=15 min
        severe = np.array([0.0, 0.0, 0.0, 1.0])  # >60 min
        cancelled = np.array([0.0, 0.0, 0.0, 0.0, 1.0])
        diverted = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
        n_completed, n_total = 4, 5

        expected_reliability = on_time.mean() * 100
        expected_delay_score = 100 - 2 * delays.mean()
        expected_severe_score = max(0.0, 100 - 5 * severe.mean() * 100)
        expected_cancellation_score = max(0.0, 100 - 10 * cancelled.mean() * 100)
        expected_diversion_score = 100 - 20 * diverted.mean() * 100

        assert result["component_scores"]["reliability"] == pytest.approx(expected_reliability, abs=1e-6)
        assert result["component_scores"]["delay_severity"] == pytest.approx(expected_delay_score, abs=1e-6)
        assert result["component_scores"]["severe_delay_exposure"] == pytest.approx(expected_severe_score, abs=1e-6)
        assert result["component_scores"]["cancellation_resilience"] == pytest.approx(expected_cancellation_score, abs=1e-6)
        assert result["component_scores"]["diversion_resilience"] == pytest.approx(expected_diversion_score, abs=1e-6)

        # Standard errors: SE(100 * mean(indicator)) = 100 * sqrt(pop_var / n).
        se_reliability = 100 * np.sqrt(on_time.var() / n_completed)
        se_delay = 2 * np.sqrt(delays.var() / n_completed)
        se_severe = 5 * 100 * np.sqrt(severe.var() / n_completed)
        se_cancellation = 10 * 100 * np.sqrt(cancelled.var() / n_total)
        se_diversion = 20 * 100 * np.sqrt(diverted.var() / n_total)

        assert result["component_standard_errors"]["reliability"] == pytest.approx(se_reliability, abs=1e-4)
        assert result["component_standard_errors"]["delay_severity"] == pytest.approx(se_delay, abs=1e-4)
        assert result["component_standard_errors"]["severe_delay_exposure"] == pytest.approx(se_severe, abs=1e-4)
        assert result["component_standard_errors"]["cancellation_resilience"] == pytest.approx(se_cancellation, abs=1e-4)
        assert result["component_standard_errors"]["diversion_resilience"] == pytest.approx(se_diversion, abs=0.05)

        weights = [0.290, 0.251, 0.275, 0.125, 0.059]
        component_ses = [se_reliability, se_delay, se_severe, se_cancellation, se_diversion]
        expected_se_health = sum((w * se) ** 2 for w, se in zip(weights, component_ses)) ** 0.5
        assert result["standard_error"] == pytest.approx(expected_se_health, rel=1e-3)

        # health_score itself must equal the weighted sum of (already-verified) component scores.
        expected_health_score = sum(
            result["component_scores"][key] * w
            for key, w in zip(
                ["reliability", "delay_severity", "severe_delay_exposure", "cancellation_resilience", "diversion_resilience"],
                weights,
            )
        )
        assert result["score"] == pytest.approx(expected_health_score, abs=0.01)

        # 95% CI must be centered on the score with the reported standard error.
        lo, hi = result["confidence_interval_95"]
        assert lo < result["score"] < hi
        assert (hi - lo) / 2 == pytest.approx(1.959964 * result["standard_error"], abs=0.05)

    def test_zero_variance_gives_zero_standard_error(self):
        """Every completed flight identical -> no uncertainty in that
        component at all, SE must be exactly 0, not NaN or a crash."""
        rows = [(0, 0, 5.0)] * 10
        con = _build_connection(rows)
        row = con.execute(f"SELECT {RAW_STAT_SELECT_EXPRS} FROM flights").fetchone()
        con.close()

        result = score_from_row(row)
        assert result["component_standard_errors"]["delay_severity"] == 0.0
        assert result["component_standard_errors"]["reliability"] == 0.0

    def test_returns_none_for_no_flights(self):
        con = _build_connection([])
        row = con.execute(f"SELECT {RAW_STAT_SELECT_EXPRS} FROM flights").fetchone()
        con.close()
        assert score_from_row(row) is None


class TestCompareHealthScores:
    def test_identical_scores_are_not_significant(self):
        a = {"score": 82.0, "standard_error": 0.5}
        b = {"score": 82.0, "standard_error": 0.5}
        result = compare_health_scores(a, b)
        assert result["score_difference"] == 0.0
        assert result["significant_at_0_05"] is False
        assert result["p_value"] == pytest.approx(1.0, abs=1e-6)

    def test_large_gap_with_tiny_standard_errors_is_significant(self):
        a = {"score": 90.0, "standard_error": 0.1}
        b = {"score": 60.0, "standard_error": 0.1}
        result = compare_health_scores(a, b)
        assert result["significant_at_0_05"] is True
        assert result["p_value"] < 0.0001
        assert result["score_difference"] == pytest.approx(30.0)

    def test_small_gap_with_large_standard_errors_is_not_significant(self):
        """The exact 'is 82 vs 80 real or noise' case this was built for:
        a 2-point gap swamped by sampling uncertainty on small samples."""
        a = {"score": 82.0, "standard_error": 8.0}
        b = {"score": 80.0, "standard_error": 8.0}
        result = compare_health_scores(a, b)
        assert result["significant_at_0_05"] is False

    def test_zero_standard_errors_with_real_difference_is_significant(self):
        a = {"score": 82.0, "standard_error": 0.0}
        b = {"score": 80.0, "standard_error": 0.0}
        result = compare_health_scores(a, b)
        assert result["significant_at_0_05"] is True
        assert result["p_value"] == 0.0

    def test_comparison_is_antisymmetric(self):
        a = {"score": 85.0, "standard_error": 2.0}
        b = {"score": 78.0, "standard_error": 3.0}
        ab = compare_health_scores(a, b)
        ba = compare_health_scores(b, a)
        assert ab["score_difference"] == pytest.approx(-ba["score_difference"])
        assert ab["p_value"] == pytest.approx(ba["p_value"])
        assert ab["significant_at_0_05"] == ba["significant_at_0_05"]
