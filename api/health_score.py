"""
Explainable health-score formula. Originally ported from the prior
platform's route_health.py (v1, hand-picked weights). The weights below
were later empirically calibrated: computed from 6,133 routes by splitting
each route's history chronologically (early ~70% / late ~30%), then
correlating each early-period component with that same route's ACTUAL
on-time rate in the later period. Weights are each component's correlation
with real future performance, normalized to sum to 1.0 -- not a guess.

Components (all 0-100):
- reliability: on-time percentage, as-is
- delay_severity: 100 - avg_arrival_delay * 2
- severe_delay_exposure: 100 - (% of flights delayed >60min) * 5
- cancellation_resilience: 100 - cancellation_pct * 10
- diversion_resilience: 100 - diversion_pct * 20

Weighted (calibrated against future on-time rate, n=6,133 routes):
  reliability              0.290  (r=+0.585 with future performance)
  delay_severity           0.251  (r=+0.507)
  severe_delay_exposure    0.275  (r=+0.556)
  cancellation_resilience  0.125  (r=+0.253)
  diversion_resilience     0.059  (r=+0.119)

Rating bands: >=90 Excellent, >=80 Strong, >=70 Watch, >=60 Weak, else Critical.

Uncertainty quantification (standard_error / confidence_interval_95), added
alongside the point score, not replacing it: every component is a sample
mean or sample proportion over a finite number of flights, so it has a real
standard error, computed via the standard "SE of a sample mean" formula
(sqrt(variance / n)) using variances DuckDB computes directly via VAR_POP,
propagated through each component's known linear transform (e.g.
delay_score = 100 - 2*avg_delay, so SE(delay_score) = 2*SE(avg_delay)).
The overall score's SE combines the five components' SEs assuming they're
independent (Var(sum of weighted components) = sum of weight^2 * Var), which
is a disclosed simplification -- the components are computed from the same
flights and aren't strictly independent (e.g. a cancelled flight can't also
be severely delayed), but this is the same assumption behind any quick
composite-score error-propagation estimate, and errs conservative in
practice since cancellation/diversion (the most correlated-by-construction
components with the others) carry small weights. Good enough to answer
"is an 82 meaningfully different from an 80," not a rigorous joint model.
"""

from __future__ import annotations

from typing import Any

from scipy import stats as scipy_stats

from api.db import open_readonly_connection
from api.metrics import COMPLETED_FLIGHT_SQL, ON_TIME_FLAG_SQL, SEVERE_DELAY_SQL

MINIMUM_FLIGHTS_FOR_FULL_CONFIDENCE = 30
Z_95 = scipy_stats.norm.ppf(0.975)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(value, maximum))


def _get_rating(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 80:
        return "Strong"
    if score >= 70:
        return "Watch"
    if score >= 60:
        return "Weak"
    return "Critical"


#: The raw aggregate expressions behind every health-score component, in a
#: fixed column order. Shared by compute_health_score (one entity) and any
#: caller that wants ALL entities' stats from a single GROUP BY query instead
#: of one query per entity -- see score_from_row below and its use in
#: api/main.py's network-protection-portfolio endpoint, which previously
#: issued one full-table-scan query per candidate (N sequential scans over
#: 60.7M rows) instead of one grouped scan.
RAW_STAT_SELECT_EXPRS = f"""
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


def _standard_error(variance: float | None, n: int) -> float:
    if not variance or n <= 0:
        return 0.0
    return (max(variance, 0.0) / n) ** 0.5


def score_from_row(row: tuple) -> dict | None:
    """Same scoring math as compute_health_score, applied to one row of
    RAW_STAT_SELECT_EXPRS output (in that column order) instead of running
    its own query. Lets a caller compute the raw stats for many entities in
    one grouped query and still get identical, non-duplicated scoring."""
    total_flights = int(row[0] or 0)
    if total_flights == 0:
        return None

    completed_flights = int(row[1] or 0)
    avg_arrival_delay = float(row[2] or 0)
    var_arrival_delay = row[3]
    on_time_percentage = float(row[4] or 0)
    var_on_time_indicator = row[5]
    severe_delay_percentage = float(row[6] or 0)
    var_severe_indicator = row[7]
    cancellation_percentage = float(row[8] or 0)
    var_cancelled_indicator = row[9]
    diversion_percentage = float(row[10] or 0)
    var_diverted_indicator = row[11]

    reliability_score = _clamp(on_time_percentage)
    delay_score = _clamp(100 - max(avg_arrival_delay, 0) * 2)
    severe_delay_score = _clamp(100 - severe_delay_percentage * 5)
    cancellation_score = _clamp(100 - cancellation_percentage * 10)
    diversion_score = _clamp(100 - diversion_percentage * 20)

    health_score = round(
        reliability_score * 0.290
        + delay_score * 0.251
        + severe_delay_score * 0.275
        + cancellation_score * 0.125
        + diversion_score * 0.059,
        2,
    )

    # Standard error of each component, propagated from the standard error
    # of the underlying sample mean/proportion through that component's
    # known linear transform -- see module docstring for the full method
    # and its independence-assumption caveat on the combined figure.
    se_reliability = 100 * _standard_error(var_on_time_indicator, completed_flights)
    se_delay = 2 * _standard_error(var_arrival_delay, completed_flights)
    se_severe_delay = 5 * 100 * _standard_error(var_severe_indicator, completed_flights)
    se_cancellation = 10 * 100 * _standard_error(var_cancelled_indicator, total_flights)
    se_diversion = 20 * 100 * _standard_error(var_diverted_indicator, total_flights)

    se_health_score = (
        (0.290 * se_reliability) ** 2
        + (0.251 * se_delay) ** 2
        + (0.275 * se_severe_delay) ** 2
        + (0.125 * se_cancellation) ** 2
        + (0.059 * se_diversion) ** 2
    ) ** 0.5
    margin = round(Z_95 * se_health_score, 2)

    return {
        "score": health_score,
        "rating": _get_rating(health_score),
        "standard_error": round(se_health_score, 4),
        "confidence_interval_95": [round(health_score - margin, 2), round(health_score + margin, 2)],
        "sample": {
            "total_flights": total_flights,
            "completed_flights": completed_flights,
            "minimum_for_full_confidence": MINIMUM_FLIGHTS_FOR_FULL_CONFIDENCE,
            "status": "sufficient" if total_flights >= MINIMUM_FLIGHTS_FOR_FULL_CONFIDENCE else "limited",
        },
        "component_scores": {
            "reliability": round(reliability_score, 2),
            "delay_severity": round(delay_score, 2),
            "severe_delay_exposure": round(severe_delay_score, 2),
            "cancellation_resilience": round(cancellation_score, 2),
            "diversion_resilience": round(diversion_score, 2),
        },
        "component_standard_errors": {
            "reliability": round(se_reliability, 4),
            "delay_severity": round(se_delay, 4),
            "severe_delay_exposure": round(se_severe_delay, 4),
            "cancellation_resilience": round(se_cancellation, 4),
            "diversion_resilience": round(se_diversion, 4),
        },
        "weights": {
            "reliability": 0.290,
            "delay_severity": 0.251,
            "severe_delay_exposure": 0.275,
            "cancellation_resilience": 0.125,
            "diversion_resilience": 0.059,
        },
        "calibration": {
            "method": "Each weight is that component's Pearson correlation with the SAME "
            "route's actual future on-time rate, normalized to sum to 1.0 -- not hand-picked.",
            "sample_size_routes": 6133,
            "correlations_with_future_performance": {
                "reliability": 0.585,
                "delay_severity": 0.507,
                "severe_delay_exposure": 0.556,
                "cancellation_resilience": 0.253,
                "diversion_resilience": 0.119,
            },
        },
    }


def compute_health_score(where_clause: str, params: list[Any]) -> dict | None:
    """where_clause is a raw SQL WHERE body (no leading 'WHERE'), applied to
    the flights table. Returns None if there's no matching data at all.

    For scoring MANY entities at once (e.g. every carrier or the top N
    airports), prefer one GROUP BY query with RAW_STAT_SELECT_EXPRS plus
    score_from_row per result row -- this function runs its own full
    query and is meant for the single-entity case."""
    query = f"SELECT {RAW_STAT_SELECT_EXPRS} FROM flights WHERE {where_clause}"
    with open_readonly_connection() as connection:
        row = connection.execute(query, params).fetchone()
    return score_from_row(row)


def compare_health_scores(score_a: dict, score_b: dict) -> dict:
    """Two-sample z-test on the difference between two already-computed
    health scores (each a score_from_row/compute_health_score result, so
    each carries its own standard_error). Answers the question a bare
    "82 vs 80" comparison can't: is that gap distinguishable from the
    noise in each score's own sample, or small enough that either entity
    could easily be the "better" one on a different slice of the same
    data. Valid as long as the two scores come from non-overlapping flight
    samples (true for any two different carriers/airports/routes)."""
    diff = round(score_a["score"] - score_b["score"], 2)
    se_diff = ((score_a["standard_error"] ** 2) + (score_b["standard_error"] ** 2)) ** 0.5
    if se_diff == 0:
        z = float("inf") if diff != 0 else 0.0
        p_value = 0.0 if diff != 0 else 1.0
    else:
        z = diff / se_diff
        p_value = 2 * scipy_stats.norm.sf(abs(z))
    return {
        "score_difference": diff,
        "standard_error_of_difference": round(se_diff, 4),
        "z_statistic": round(z, 4) if z not in (float("inf"), float("-inf")) else z,
        "p_value": round(float(p_value), 6),
        "significant_at_0_05": bool(p_value < 0.05),
    }
