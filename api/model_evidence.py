"""Repeated, time-ordered evidence checks for the route-panel models.

The application deliberately keeps a transparent historical baseline beside
ML. A single 60/20/20 split is useful for a first check but can be sensitive
to the particular months selected. This module repeats the comparison across
several later, untouched windows. Every feature is constructed before its
target route-month and every model is fitted only on periods before the window
it is evaluated on.

This measures predictive usefulness, not a causal effect of traffic, weather,
NAS, or airport departure concentration.
"""

from __future__ import annotations

from datetime import date
import threading
import time
from typing import Any

from api.route_ml_forecast import (
    PANEL_FEATURE_NAMES,
    PANEL_FULL_FEATURE_INDICES,
    PANEL_MIN_TRAINING_EXAMPLES,
    PANEL_OTP_FEATURE_INDICES,
    PANEL_OTP_FEATURE_NAMES,
    PANEL_T100_FEATURE_INDICES,
    PANEL_T100_FEATURE_NAMES,
    PANEL_TABLE,
    _baseline_predictions,
    _fit_models,
    _metric_summary,
    _period_index,
    _predict_models,
    _query_route_panel,
    build_supervised_panel_examples,
)


EVIDENCE_CACHE_TTL_SECONDS = 60 * 60 * 6
# A fixed, route-ID-only sample keeps a repeated local evaluation responsive
# on a laptop while still drawing from the full time span.  It is disclosed in
# the response and never selected using delay, cancellation, or model output.
EVIDENCE_ROUTE_SAMPLE = 200
_EVIDENCE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_EVIDENCE_CACHE_LOCK = threading.Lock()
TARGETS = ("delay_minutes", "late_rate", "cancellation_rate")


def _period_from_index(index: int) -> str:
    year, zero_month = divmod(index, 12)
    return f"{year:04d}-{zero_month + 1:02d}"


def _evenly_spaced(items: list[str], count: int) -> list[str]:
    if len(items) <= count:
        return items
    if count <= 1:
        return [items[-1]]
    positions = [round(index * (len(items) - 1) / (count - 1)) for index in range(count)]
    return [items[position] for position in sorted(set(positions))]


def _non_overlapping_cutoffs(cutoffs: list[str], *, test_horizon_months: int) -> list[str]:
    """Keep future test windows separate before choosing representative ones.

    Consecutive monthly cutoffs are all eligible individually, but their
    multi-month test windows can overlap.  Reusing the same future outcome in
    several rows would make a repeated test look more independent than it is.
    This helper builds a chronological subset with at least one full test
    horizon between starts.  Training windows may expand and overlap; only the
    untouched outcome windows must remain distinct.
    """
    selected: list[str] = []
    next_allowed_index: int | None = None
    for cutoff in sorted(cutoffs):
        cutoff_index = _period_index(cutoff)
        if next_allowed_index is not None and cutoff_index < next_allowed_index:
            continue
        selected.append(cutoff)
        next_allowed_index = cutoff_index + test_horizon_months
    return selected


def _method_specs(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    traffic_index = PANEL_FEATURE_NAMES.index("traffic_context_available")
    operational_index = PANEL_FEATURE_NAMES.index("operational_context_available")
    has_traffic = any(float(row["features"][traffic_index]) > 0 for row in examples)
    has_operational = any(float(row["features"][operational_index]) > 0 for row in examples)
    specs = [{
        "id": "otp_history",
        "label": "OTP history only",
        "feature_names": list(PANEL_OTP_FEATURE_NAMES),
        "feature_indices": PANEL_OTP_FEATURE_INDICES,
    }]
    if has_traffic:
        specs.append({
            "id": "otp_t100",
            "label": "OTP + lagged T-100",
            "feature_names": list(PANEL_T100_FEATURE_NAMES),
            "feature_indices": PANEL_T100_FEATURE_INDICES,
        })
    if has_operational:
        specs.append({
            "id": "otp_t100_operations" if has_traffic else "otp_operations",
            "label": "OTP + T-100 + lagged operations" if has_traffic else "OTP + lagged operations",
            "feature_names": list(PANEL_FEATURE_NAMES),
            "feature_indices": PANEL_FULL_FEATURE_INDICES,
        })
    return specs


def _eligible_cutoffs(
    examples: list[dict[str, Any]],
    *,
    minimum_training_periods: int,
    test_horizon_months: int,
    minimum_training_examples: int,
) -> list[str]:
    periods = sorted({str(row["period"]) for row in examples})
    cutoffs: list[str] = []
    for position in range(minimum_training_periods, len(periods)):
        cutoff = periods[position]
        cutoff_index = _period_index(cutoff)
        train_count = sum(1 for row in examples if _period_index(str(row["period"])) < cutoff_index)
        test_count = sum(
            1
            for row in examples
            if cutoff_index <= _period_index(str(row["period"])) < cutoff_index + test_horizon_months
        )
        if train_count >= minimum_training_examples and test_count >= 20:
            cutoffs.append(cutoff)
    return cutoffs


def _window_metrics(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    methods: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {
        "math_baseline": _metric_summary(test, _baseline_predictions(test))
    }
    for method in methods:
        fit = _fit_models(train, feature_indices=method["feature_indices"])
        result[method["id"]] = _metric_summary(test, _predict_models(fit, test))
    return result


def _aggregate_windows(
    windows: list[dict[str, Any]], method_ids: list[str]
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, int]],
    dict[str, dict[str, dict[str, Any]]],
]:
    aggregate: dict[str, dict[str, Any]] = {}
    winner_counts: dict[str, dict[str, int]] = {
        target: {method_id: 0 for method_id in method_ids} for target in TARGETS
    }
    for method_id in method_ids:
        total_examples = sum(int(window["metrics"][method_id]["examples"]) for window in windows)
        totals: dict[str, float] = {}
        for window in windows:
            metrics = window["metrics"][method_id]
            examples = int(metrics["examples"])
            for key, value in metrics.items():
                if key == "examples" or value is None:
                    continue
                totals[key] = totals.get(key, 0.0) + float(value) * examples
        aggregate[method_id] = {
            "examples": total_examples,
            **{key: round(value / total_examples, 6) for key, value in totals.items() if total_examples},
        }

    for window in windows:
        for target in TARGETS:
            key = f"{target}_mae"
            usable = [
                (method_id, window["metrics"][method_id].get(key))
                for method_id in method_ids
                if window["metrics"][method_id].get(key) is not None
            ]
            if not usable:
                continue
            best = min(float(value) for _, value in usable)
            for method_id, value in usable:
                if abs(float(value) - best) < 1e-12:
                    winner_counts[target][method_id] += 1

    # The historical baseline remains the decision anchor.  A more complex
    # candidate is not "promoted" merely because it wins one convenient
    # split: it must lower aggregate error AND win more non-overlapping future
    # windows than it loses against the baseline for the same target.
    baseline = aggregate.get("math_baseline", {})
    comparisons: dict[str, dict[str, dict[str, Any]]] = {}
    for target in TARGETS:
        metric = f"{target}_mae"
        target_comparisons: dict[str, dict[str, Any]] = {}
        baseline_value = baseline.get(metric)
        for method_id in method_ids:
            if method_id == "math_baseline":
                continue
            candidate_value = aggregate.get(method_id, {}).get(metric)
            wins = losses = ties = 0
            for window in windows:
                candidate = window["metrics"][method_id].get(metric)
                reference = window["metrics"]["math_baseline"].get(metric)
                if candidate is None or reference is None:
                    continue
                if float(candidate) < float(reference) - 1e-12:
                    wins += 1
                elif float(candidate) > float(reference) + 1e-12:
                    losses += 1
                else:
                    ties += 1
            delta = (
                round(float(candidate_value) - float(baseline_value), 6)
                if candidate_value is not None and baseline_value is not None
                else None
            )
            relative_change = (
                round((float(baseline_value) - float(candidate_value)) / float(baseline_value), 6)
                if candidate_value is not None and baseline_value not in (None, 0)
                else None
            )
            supported = bool(delta is not None and delta < 0 and wins > losses)
            target_comparisons[method_id] = {
                "aggregate_mae_change_vs_baseline": delta,
                "relative_mae_improvement_vs_baseline": relative_change,
                "windows_better_than_baseline": wins,
                "windows_worse_than_baseline": losses,
                "windows_tied_with_baseline": ties,
                "status": "supported_candidate" if supported else "keep_exploratory",
            }
        comparisons[target] = target_comparisons
    return aggregate, winner_counts, comparisons


def _build_evidence(
    connection: Any,
    *,
    max_windows: int,
    minimum_training_periods: int,
    test_horizon_months: int,
    minimum_training_examples: int,
) -> dict[str, Any]:
    from api.analytics import table_exists

    if not table_exists(connection, PANEL_TABLE):
        return {"status": "unavailable", "reason": "The materialized route-month table is unavailable."}
    latest_row = connection.execute(f"SELECT MAX(year_month) FROM {PANEL_TABLE}").fetchone()
    if not latest_row or latest_row[0] is None:
        return {"status": "unavailable", "reason": "The materialized route-month table is empty."}
    latest_period = str(latest_row[0])[:7]
    target_period = _period_from_index(_period_index(latest_period) + 1)
    population_route_count = int(connection.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT origin, dest
            FROM {PANEL_TABLE}
            WHERE year_month < ?
            GROUP BY origin, dest
        )
        """,
        [target_period],
    ).fetchone()[0])
    panel_rows = _query_route_panel(
        connection,
        target_period=target_period,
        max_routes=EVIDENCE_ROUTE_SAMPLE,
    )
    examples = build_supervised_panel_examples(panel_rows)
    if len(examples) < minimum_training_examples:
        return {
            "status": "insufficient_history",
            "reason": "The route-month panel is too small for repeated time-based evaluation.",
            "examples": len(examples),
            "minimum_examples": minimum_training_examples,
        }

    methods = _method_specs(examples)
    cutoffs = _eligible_cutoffs(
        examples,
        minimum_training_periods=minimum_training_periods,
        test_horizon_months=test_horizon_months,
        minimum_training_examples=minimum_training_examples,
    )
    independent_cutoffs = _non_overlapping_cutoffs(
        cutoffs,
        test_horizon_months=test_horizon_months,
    )
    selected_cutoffs = _evenly_spaced(independent_cutoffs, max_windows)
    if len(selected_cutoffs) < 2:
        return {
            "status": "insufficient_history",
            "reason": "There are not enough independent later windows for a repeated evaluation.",
            "examples": len(examples),
            "eligible_windows": len(selected_cutoffs),
        }

    windows: list[dict[str, Any]] = []
    for cutoff in selected_cutoffs:
        cutoff_index = _period_index(cutoff)
        train = [row for row in examples if _period_index(str(row["period"])) < cutoff_index]
        test = [
            row
            for row in examples
            if cutoff_index <= _period_index(str(row["period"])) < cutoff_index + test_horizon_months
        ]
        if len(train) < minimum_training_examples or len(test) < 20:
            continue
        observed_periods = sorted({str(row["period"]) for row in test})
        windows.append({
            "training_through": _period_from_index(cutoff_index - 1),
            "test_start": cutoff,
            "test_through": observed_periods[-1],
            "training_examples": len(train),
            "test_examples": len(test),
            "metrics": _window_metrics(train, test, methods),
        })

    method_records = [{
        "id": "math_baseline",
        "label": "Historical math baseline",
        "feature_names": ["prior route history only"],
    }, *[{key: value for key, value in method.items() if key != "feature_indices"} for method in methods]]
    method_ids = [method["id"] for method in method_records]
    if not windows:
        return {"status": "insufficient_history", "reason": "No repeated time windows met the sample safeguards."}
    aggregate, winner_counts, comparisons = _aggregate_windows(windows, method_ids)

    traffic_index = PANEL_FEATURE_NAMES.index("traffic_context_available")
    operational_index = PANEL_FEATURE_NAMES.index("operational_context_available")
    traffic_examples = sum(float(row["features"][traffic_index]) > 0 for row in examples)
    operational_examples = sum(float(row["features"][operational_index]) > 0 for row in examples)
    return {
        "status": "ready",
        "generated_at": date.today().isoformat(),
        "data": {
            "route_month_examples": len(examples),
            "routes": len({row["route"] for row in examples}),
            "network_routes_available": population_route_count,
            "route_sample_limit": EVIDENCE_ROUTE_SAMPLE,
            "route_sampling": "Deterministic sample by route identifier; not selected by delay, cancellation, or model outcome.",
            "earliest_outcome_month": min(str(row["period"]) for row in examples),
            "latest_outcome_month": max(str(row["period"]) for row in examples),
            "t100_context_examples": traffic_examples,
            "t100_context_share": round(traffic_examples / len(examples), 4),
            "operational_context_examples": operational_examples,
            "operational_context_share": round(operational_examples / len(examples), 4),
        },
        "evaluation": {
            "window_count": len(windows),
            "test_horizon_months": test_horizon_months,
            "minimum_training_periods": minimum_training_periods,
            "minimum_training_examples": minimum_training_examples,
            "test_windows_do_not_overlap": True,
            "windows": windows,
            "aggregate": aggregate,
            "winner_counts_by_target": winner_counts,
            "comparison_to_historical_baseline": comparisons,
        },
        "methods": method_records,
        "methodology": {
            "design": "Rolling time-based holdouts with non-overlapping future test windows. Each row is scored only after its feature month, then tested on later months never used for fitting.",
            "t100_boundary": "T-100 route traffic is ASOF joined only when its month is strictly earlier than the OTP outcome month.",
            "operational_boundary": "WeatherDelay, NASDelay, departure delay, and departure concentration are origin-airport history from a strictly earlier month.",
            "promotion_rule": "A candidate is only labelled supported for a target when it lowers aggregate MAE and wins more separate future windows than it loses against the transparent historical baseline.",
            "interpretation": "Lower MAE means closer predictions. Repeated wins in non-overlapping future windows support predictive usefulness; they do not prove that traffic or operational drivers caused a later result.",
        },
    }


def build_route_panel_temporal_evidence(
    connection: Any,
    *,
    force: bool = False,
    max_windows: int = 4,
    minimum_training_periods: int = 24,
    test_horizon_months: int = 6,
    minimum_training_examples: int = PANEL_MIN_TRAINING_EXAMPLES,
) -> dict[str, Any]:
    """Return cached or newly computed rolling evidence for the route panel."""
    from api.analytics import table_exists

    latest_period = "unavailable"
    if table_exists(connection, PANEL_TABLE):
        latest_row = connection.execute(f"SELECT MAX(year_month) FROM {PANEL_TABLE}").fetchone()
        latest_period = str(latest_row[0])[:7] if latest_row and latest_row[0] is not None else "empty"
    cache_key = f"{latest_period}:{max_windows}:{minimum_training_periods}:{test_horizon_months}:{minimum_training_examples}"
    now = time.monotonic()
    with _EVIDENCE_CACHE_LOCK:
        cached = _EVIDENCE_CACHE.get(cache_key)
        if not force and cached is not None and now - cached[0] < EVIDENCE_CACHE_TTL_SECONDS:
            return {**cached[1], "cache": {"status": "hit", "ttl_seconds": EVIDENCE_CACHE_TTL_SECONDS}}

    result = _build_evidence(
        connection,
        max_windows=max_windows,
        minimum_training_periods=minimum_training_periods,
        test_horizon_months=test_horizon_months,
        minimum_training_examples=minimum_training_examples,
    )
    with _EVIDENCE_CACHE_LOCK:
        _EVIDENCE_CACHE[cache_key] = (now, result)
    return {**result, "cache": {"status": "rebuilt", "ttl_seconds": EVIDENCE_CACHE_TTL_SECONDS}}
