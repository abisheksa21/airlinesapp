"""Historical replay for the Network Protection portfolio.

The portfolio optimizer itself is deterministic: it selects the best declared
historical metric under a stated resource budget.  That is useful, but it does
not tell us whether the *priority list* remains informative in later periods.

This module makes that narrower check explicit.  For each replay window it:

1. builds candidates from an earlier reference period only;
2. runs the unchanged portfolio optimizer on that earlier information; and
3. compares the selected candidates with the same candidate set in a later,
   non-overlapping outcome period.

No intervention is observed or simulated in the later window.  The result is
therefore a prioritization-stability check, not evidence that intervening at a
selected carrier or airport caused a future improvement.
"""

from __future__ import annotations

from datetime import date
import statistics
import threading
import time
from typing import Any

from dateutil.relativedelta import relativedelta

from api.optimization.backend import PublicBackend
from api.optimization.network_protection import InterventionCandidate, solve_portfolio


VALID_PRIMARY_METRICS = {
    "total_flights_millions",
    "reliability",
    "delay_severity",
    "severe_delay_exposure",
    "cancellation_resilience",
    "diversion_resilience",
}
_CACHE_TTL_SECONDS = 60 * 60 * 6
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()

# The replay intentionally reads compact monthly aggregates rather than the
# raw flight table. A three-window replay otherwise needs several repeated
# full-table scans and makes a Decision Center click unreasonably expensive on
# a laptop. These fields are deterministic refresh outputs from the same BTS
# source, not a second data source or a simplified mock.
_COMPACT_SPECS = {
    "carrier": {
        "table": "analytics_carrier_month",
        "entity": "carrier",
        "total": "total_flights",
        "completed": "completed_flights",
    },
    "airport": {
        "table": "analytics_airport_operational_month",
        "entity": "airport",
        "total": "total_departures",
        "completed": "completed_departures",
    },
}
_COMPACT_REQUIRED_COLUMNS = {
    "year_month",
    "on_time_rate",
    "avg_arrival_delay_minutes",
    "severe_delay_rate",
    "cancellation_rate",
    "diversion_rate",
}


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _range_label(start: date, end: date) -> str:
    """Render a half-open date interval in a compact, unambiguous form."""
    return f"{start.isoformat()} to {(end - relativedelta(days=1)).isoformat()}"


def _compact_spec(connection: Any, candidate_type: str) -> dict[str, str] | None:
    """Return a usable compact-table contract, if the warehouse is refreshed."""
    spec = _COMPACT_SPECS.get(candidate_type)
    if spec is None:
        raise ValueError("candidate_type must be 'carrier' or 'airport'")
    try:
        columns = {row[0] for row in connection.execute(f"DESCRIBE {spec['table']}").fetchall()}
    except Exception:
        return None
    required = {
        spec["entity"], spec["total"], spec["completed"], *_COMPACT_REQUIRED_COLUMNS,
    }
    return spec if required.issubset(columns) else None


def _cost(total_flights: int, *, cost_model: str, cost_scale: float) -> float:
    volume_millions = total_flights / 1_000_000
    if cost_model == "unit":
        base = 1.0
    elif cost_model == "flight_volume_millions":
        base = max(0.1, volume_millions)
    elif cost_model == "sqrt_flight_volume":
        base = max(0.1, volume_millions**0.5)
    else:
        raise ValueError("cost_model must be 'unit', 'flight_volume_millions', or 'sqrt_flight_volume'")
    return round(base * cost_scale, 3)


def _clamp(value: float) -> float:
    return max(0.0, min(value, 100.0))


def _exposure_components(
    *,
    total_flights: int,
    on_time_rate: float | None,
    avg_arrival_delay_minutes: float | None,
    severe_delay_rate: float | None,
    cancellation_rate: float | None,
    diversion_rate: float | None,
) -> dict[str, float]:
    """Match the live portfolio's primary-metric exposure convention.

    Health Score components point upward when performance is better. The live
    focus tool inverts the chosen component so a larger value means more
    exposure requiring attention. The replay evaluates that same exposed
    metric directly from compact monthly aggregates.
    """
    return {
        "total_flights_millions": round(total_flights / 1_000_000, 3),
        "reliability": round(_clamp((1.0 - float(on_time_rate or 0.0)) * 100.0), 3),
        "delay_severity": round(_clamp(max(float(avg_arrival_delay_minutes or 0.0), 0.0) * 2.0), 3),
        "severe_delay_exposure": round(_clamp(max(float(severe_delay_rate or 0.0), 0.0) * 500.0), 3),
        "cancellation_resilience": round(_clamp(max(float(cancellation_rate or 0.0), 0.0) * 1000.0), 3),
        "diversion_resilience": round(_clamp(max(float(diversion_rate or 0.0), 0.0) * 2000.0), 3),
    }


def _records_for_window(
    connection: Any,
    *,
    compact_spec: dict[str, str],
    candidate_type: str,
    start_date: date,
    end_date: date,
    primary_metric: str,
    cost_model: str,
    cost_scale: float,
    airport_candidate_limit: int,
    only_entities: list[str] | None = None,
) -> dict[str, InterventionCandidate]:
    """Aggregate one historical window into the live portfolio's candidates."""
    table = compact_spec["table"]
    entity_col = compact_spec["entity"]
    total_col = compact_spec["total"]
    completed_col = compact_spec["completed"]
    clauses = [
        "year_month >= ?",
        "year_month < ?",
        f"{entity_col} IS NOT NULL",
    ]
    params: list[Any] = [start_date.strftime("%Y-%m"), end_date.strftime("%Y-%m")]
    if only_entities:
        placeholders = ", ".join("?" for _ in only_entities)
        clauses.append(f"{entity_col} IN ({placeholders})")
        params.extend(only_entities)
    query = f"""
        SELECT
            {entity_col} AS entity,
            SUM({total_col}) AS total_flights,
            SUM({completed_col}) AS completed_flights,
            SUM(COALESCE(on_time_rate, 0) * {completed_col}) / NULLIF(SUM({completed_col}), 0) AS on_time_rate,
            SUM(COALESCE(avg_arrival_delay_minutes, 0) * {completed_col}) / NULLIF(SUM({completed_col}), 0) AS avg_arrival_delay_minutes,
            SUM(COALESCE(severe_delay_rate, 0) * {completed_col}) / NULLIF(SUM({completed_col}), 0) AS severe_delay_rate,
            SUM(COALESCE(cancellation_rate, 0) * {total_col}) / NULLIF(SUM({total_col}), 0) AS cancellation_rate,
            SUM(COALESCE(diversion_rate, 0) * {total_col}) / NULLIF(SUM({total_col}), 0) AS diversion_rate
        FROM {table}
        WHERE {' AND '.join(clauses)}
        GROUP BY {entity_col}
        ORDER BY total_flights DESC
    """
    if candidate_type == "airport" and not only_entities:
        query += " LIMIT ?"
        params.append(airport_candidate_limit)

    records: dict[str, InterventionCandidate] = {}
    for row in connection.execute(query, params).fetchall():
        entity = str(row[0])
        total_flights = int(row[1] or 0)
        if total_flights <= 0:
            continue
        records[entity] = InterventionCandidate(
            candidate_id=entity,
            candidate_type=candidate_type,
            cost=_cost(
                total_flights,
                cost_model=cost_model,
                cost_scale=cost_scale,
            ),
            components=_exposure_components(
                total_flights=total_flights,
                on_time_rate=row[3],
                avg_arrival_delay_minutes=row[4],
                severe_delay_rate=row[5],
                cancellation_rate=row[6],
                diversion_rate=row[7],
            ),
        )
    return records


def _record_for_replay(
    connection: Any,
    *,
    compact_spec: dict[str, str],
    candidate_type: str,
    primary_metric: str,
    budget: float,
    cost_model: str,
    cost_scale: float,
    airport_candidate_limit: int,
    reference_start: date,
    reference_end: date,
    outcome_start: date,
    outcome_end: date,
) -> dict[str, Any]:
    historical = _records_for_window(
        connection,
        compact_spec=compact_spec,
        candidate_type=candidate_type,
        start_date=reference_start,
        end_date=reference_end,
        primary_metric=primary_metric,
        cost_model=cost_model,
        cost_scale=cost_scale,
        airport_candidate_limit=airport_candidate_limit,
    )
    if not historical:
        return {
            "status": "skipped",
            "reference_window": _range_label(reference_start, reference_end),
            "future_window": _range_label(outcome_start, outcome_end),
            "reason": "No eligible candidates existed in the earlier reference window.",
        }

    result = solve_portfolio(
        list(historical.values()),
        budget=budget,
        primary_metric=primary_metric,
        backend=PublicBackend(),
    )
    if result.status != "optimal" or not result.selected:
        return {
            "status": "skipped",
            "reference_window": _range_label(reference_start, reference_end),
            "future_window": _range_label(outcome_start, outcome_end),
            "reason": "The earlier candidate set did not produce a feasible non-empty portfolio.",
        }

    candidate_ids = list(historical)
    observed = _records_for_window(
        connection,
        compact_spec=compact_spec,
        candidate_type=candidate_type,
        start_date=outcome_start,
        end_date=outcome_end,
        primary_metric=primary_metric,
        cost_model=cost_model,
        cost_scale=cost_scale,
        airport_candidate_limit=airport_candidate_limit,
        only_entities=candidate_ids,
    )
    if not observed:
        return {
            "status": "skipped",
            "reference_window": _range_label(reference_start, reference_end),
            "future_window": _range_label(outcome_start, outcome_end),
            "reason": "None of the earlier candidates had observations in the later outcome window.",
        }

    selected_ids = [str(row["candidate_id"]) for row in result.selected]
    selected_values = [
        observed[candidate_id].components[primary_metric]
        for candidate_id in selected_ids
        if candidate_id in observed
    ]
    rejected_values = [
        record.components[primary_metric]
        for candidate_id, record in observed.items()
        if candidate_id not in selected_ids
    ]
    if not selected_values:
        return {
            "status": "skipped",
            "reference_window": _range_label(reference_start, reference_end),
            "future_window": _range_label(outcome_start, outcome_end),
            "reason": "Selected candidates did not have later observations to score.",
        }

    selected_mean = sum(selected_values) / len(selected_values)
    rejected_mean = sum(rejected_values) / len(rejected_values) if rejected_values else None
    total_future_metric = sum(record.components[primary_metric] for record in observed.values())
    selected_future_metric = sum(selected_values)
    ranked_future_ids = [
        candidate_id
        for candidate_id, _ in sorted(
            observed.items(),
            key=lambda item: item[1].components[primary_metric],
            reverse=True,
        )
    ]
    top_k = min(len(selected_ids), len(ranked_future_ids))
    top_k_ids = set(ranked_future_ids[:top_k])
    top_k_hits = sum(candidate_id in top_k_ids for candidate_id in selected_ids)

    return {
        "status": "ready",
        "reference_window": _range_label(reference_start, reference_end),
        "future_window": _range_label(outcome_start, outcome_end),
        "candidates_in_reference": len(historical),
        "candidates_observed_later": len(observed),
        "selected_ids": selected_ids,
        "selected_observed_later": len(selected_values),
        "selected_future_metric_mean": round(selected_mean, 4),
        "not_selected_future_metric_mean": round(rejected_mean, 4) if rejected_mean is not None else None,
        "selection_lift": round(selected_mean - rejected_mean, 4) if rejected_mean is not None else None,
        "selected_future_metric_coverage": (
            round(selected_future_metric / total_future_metric, 4)
            if total_future_metric > 0
            else None
        ),
        "top_k": top_k,
        "top_k_hits": top_k_hits,
        "top_k_hit_rate": round(top_k_hits / top_k, 4) if top_k else None,
    }


def build_network_protection_temporal_validation(
    connection: Any,
    *,
    candidate_type: str,
    budget: float,
    primary_metric: str,
    cost_model: str,
    cost_scale: float = 1.0,
    airport_candidate_limit: int = 30,
    maximum_windows: int = 3,
    reference_months: int = 12,
    outcome_horizon_months: int = 3,
    force: bool = False,
) -> dict[str, Any]:
    """Replay a portfolio against distinct later outcome windows.

    Each future period is disjoint.  Reference periods can overlap because a
    later replay is allowed to learn from all history that preceded it, just as
    an expanding time-series evaluation would.
    """
    if primary_metric not in VALID_PRIMARY_METRICS:
        raise ValueError(f"primary_metric must be one of: {', '.join(sorted(VALID_PRIMARY_METRICS))}")
    if budget < 0 or cost_scale <= 0:
        raise ValueError("budget must be non-negative and cost_scale must be positive")
    if maximum_windows < 1 or reference_months < 1 or outcome_horizon_months < 1:
        raise ValueError("maximum_windows, reference_months, and outcome_horizon_months must be at least one")

    compact_spec = _compact_spec(connection, candidate_type)
    if compact_spec is None:
        return {
            "status": "needs_materialization",
            "reason": "The compact monthly replay table is unavailable or outdated. Run 'python -m pipeline.refresh_all --materialize-only' before using this historical check.",
            "methodology": {
                "not_claimed": "The replay is disabled rather than falling back to repeated raw-flight scans that could stall the local app.",
            },
        }
    latest_period = connection.execute(
        f"SELECT MAX(year_month) FROM {compact_spec['table']}"
    ).fetchone()[0]
    if latest_period is None:
        return {"status": "insufficient_history", "reason": "The compact monthly replay table is empty."}
    latest_complete_boundary = date.fromisoformat(f"{str(latest_period)[:7]}-01")
    cache_key = ":".join(map(str, (
        compact_spec["table"], latest_complete_boundary, candidate_type, budget, primary_metric,
        cost_model, cost_scale, airport_candidate_limit, maximum_windows,
        reference_months, outcome_horizon_months,
    )))
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if not force and cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return {**cached[1], "cache": {"status": "hit", "ttl_seconds": _CACHE_TTL_SECONDS}}

    records: list[dict[str, Any]] = []
    for position in range(maximum_windows):
        outcome_end = latest_complete_boundary - relativedelta(months=position * outcome_horizon_months)
        outcome_start = outcome_end - relativedelta(months=outcome_horizon_months)
        reference_end = outcome_start
        reference_start = reference_end - relativedelta(months=reference_months)
        records.append(_record_for_replay(
            connection,
            compact_spec=compact_spec,
            candidate_type=candidate_type,
            primary_metric=primary_metric,
            budget=budget,
            cost_model=cost_model,
            cost_scale=cost_scale,
            airport_candidate_limit=airport_candidate_limit,
            reference_start=reference_start,
            reference_end=reference_end,
            outcome_start=outcome_start,
            outcome_end=outcome_end,
        ))
    records.reverse()
    successful = [record for record in records if record["status"] == "ready"]
    lifts = [float(record["selection_lift"]) for record in successful if record["selection_lift"] is not None]
    coverages = [float(record["selected_future_metric_coverage"]) for record in successful if record["selected_future_metric_coverage"] is not None]
    hit_rates = [float(record["top_k_hit_rate"]) for record in successful if record["top_k_hit_rate"] is not None]
    result = {
        "status": "ready" if successful else "insufficient_history",
        "scope": {
            "candidate_type": candidate_type,
            "primary_metric": primary_metric,
            "budget": budget,
            "cost_model": cost_model,
            "cost_scale": cost_scale,
            "airport_candidate_limit": airport_candidate_limit if candidate_type == "airport" else None,
            "reference_months": reference_months,
            "outcome_horizon_months": outcome_horizon_months,
            "source": compact_spec["table"],
        },
        "summary": {
            "windows_requested": maximum_windows,
            "windows_evaluated": len(successful),
            "windows_with_positive_selection_lift": sum(lift > 0 for lift in lifts),
            "median_selection_lift": round(statistics.median(lifts), 4) if lifts else None,
            "median_selected_future_coverage": round(statistics.median(coverages), 4) if coverages else None,
            "median_top_k_hit_rate": round(statistics.median(hit_rates), 4) if hit_rates else None,
        },
        "records": records,
        "methodology": {
            "design": "Temporal prioritization replay. Each portfolio is chosen from an earlier reference window, then measured only in a later disjoint outcome window.",
            "what_is_checked": "Whether targets selected from earlier historical exposure tend to remain above the non-selected candidates on the same declared metric later.",
            "not_claimed": "No intervention happened in this replay. It is not a causal estimate of improvement, a staffing recommendation, or proof that selected targets should receive resources.",
        },
    }
    with _CACHE_LOCK:
        _CACHE[cache_key] = (now, result)
    return {**result, "cache": {"status": "rebuilt", "ttl_seconds": _CACHE_TTL_SECONDS}}
