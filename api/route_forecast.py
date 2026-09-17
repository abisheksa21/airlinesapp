"""Leakage-safe historical forecasting for one route scenario.

This module deliberately starts with an interpretable expanding baseline rather
than a black-box model. A target month is predicted only from flights before
that month. When enough prior T-100 route-month context exists, a transparent
load-factor-band estimate is compared with that baseline; otherwise the plain
historical baseline remains the answer.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from api.t100_forecast import (
    attach_lagged_traffic,
    build_traffic_adjustment,
    load_t100_route_context,
    traffic_band_backtest,
)

MIN_COMPLETED_FOR_MATCH = 30
WILSON_Z = 1.96


def next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def parse_target_month(value: str | None, latest_observation: date) -> date:
    """Return the first day of the requested month or the next month in data."""
    if not value:
        return next_month(latest_observation)
    try:
        parsed = datetime.strptime(value, "%Y-%m").date()
    except ValueError as exc:
        raise ValueError("target_month must use YYYY-MM format.") from exc
    return parsed.replace(day=1)


def wilson_interval(successes: int, trials: int) -> tuple[float, float] | None:
    """Return a 95% Wilson interval for a binomial proportion."""
    if trials <= 0:
        return None
    successes = max(0, min(successes, trials))
    p = successes / trials
    z2 = WILSON_Z * WILSON_Z
    denominator = 1.0 + z2 / trials
    centre = (p + z2 / (2.0 * trials)) / denominator
    margin = (
        WILSON_Z
        * ((p * (1.0 - p) / trials) + (z2 / (4.0 * trials * trials))) ** 0.5
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def confidence_label(completed_flights: int) -> str:
    if completed_flights >= 1000:
        return "strong historical sample"
    if completed_flights >= 500:
        return "good historical sample"
    if completed_flights >= 100:
        return "useful historical sample"
    if completed_flights >= MIN_COMPLETED_FOR_MATCH:
        return "limited historical sample"
    return "small historical sample"


def expanding_baseline_backtest(
    month_rows: Iterable[dict[str, Any]],
    minimum_prior_completed: int = MIN_COMPLETED_FOR_MATCH,
) -> dict[str, Any]:
    """Evaluate an expanding historical baseline without future leakage.

    Each month is scored using only the months before it. The current month is
    added to the history only after its prediction error is recorded.
    """
    ordered = sorted(month_rows, key=lambda row: str(row["period"]))
    prior_completed = 0
    prior_late = 0
    prior_delay_sum = 0.0
    scored: list[dict[str, float]] = []

    for row in ordered:
        completed = int(row.get("completed_flights") or 0)
        late = int(row.get("late_flights") or 0)
        delay_sum = float(row.get("delay_sum") or 0.0)
        if prior_completed >= minimum_prior_completed and completed > 0:
            predicted_delay = prior_delay_sum / prior_completed
            predicted_late = prior_late / prior_completed
            actual_delay = delay_sum / completed
            actual_late = late / completed
            scored.append({
                "absolute_delay_error": abs(predicted_delay - actual_delay),
                "late_brier_error": (predicted_late - actual_late) ** 2,
            })
        prior_completed += completed
        prior_late += late
        prior_delay_sum += delay_sum

    if not scored:
        return {
            "status": "insufficient_history",
            "months_scored": 0,
            "mean_absolute_error_minutes": None,
            "brier_score_late_probability": None,
            "minimum_prior_completed": minimum_prior_completed,
        }

    return {
        "status": "expanding_baseline",
        "months_scored": len(scored),
        "mean_absolute_error_minutes": round(
            sum(item["absolute_delay_error"] for item in scored) / len(scored), 3
        ),
        "brier_score_late_probability": round(
            sum(item["late_brier_error"] for item in scored) / len(scored), 6
        ),
        "minimum_prior_completed": minimum_prior_completed,
    }


def _stats_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "scheduled_flights",
        "completed_flights",
        "late_flights",
        "delay_sum",
        "average_delay",
        "median_delay",
        "p90_delay",
        "cancelled_flights",
        "first_date",
        "last_date",
        "training_months",
    )
    return dict(zip(keys, row))


def _probability(successes: int, trials: int) -> float | None:
    return successes / trials if trials else None


def build_route_forecast(
    connection: Any,
    *,
    origin: str,
    dest: str,
    carrier: str | None = None,
    departure_hour: int | None = None,
    target_month: str | None = None,
) -> dict[str, Any]:
    """Build a time-aware route forecast from the local warehouse."""
    from api.analytics import table_exists
    from pipeline.otp_core import CORE_TABLE_NAME

    origin = origin.upper()
    dest = dest.upper()
    carrier = carrier.upper() if carrier else None

    source_table = CORE_TABLE_NAME if table_exists(connection, CORE_TABLE_NAME) else "flights"
    latest_row = connection.execute(
        f"SELECT MIN(FlightDate), MAX(FlightDate) FROM {source_table} WHERE FlightDate IS NOT NULL"
    ).fetchone()
    if not latest_row or latest_row[1] is None:
        raise LookupError("The warehouse has no dated flight observations.")
    latest_observation = latest_row[1]
    if isinstance(latest_observation, datetime):
        latest_observation = latest_observation.date()
    elif isinstance(latest_observation, str):
        latest_observation = date.fromisoformat(latest_observation[:10])
    target_start = parse_target_month(target_month, latest_observation)

    requested_scope = "route"
    if carrier and departure_hour is not None:
        requested_scope = "route + airline + departure hour"
    elif carrier:
        requested_scope = "route + airline"
    elif departure_hour is not None:
        requested_scope = "route + departure hour"

    candidates: list[tuple[str, list[str], list[Any]]] = []
    base = ["Origin = ?", "Dest = ?", "FlightDate < CAST(? AS DATE)"]
    base_params: list[Any] = [origin, dest, target_start.isoformat()]
    if carrier and departure_hour is not None:
        candidates.append((
            "route + airline + departure hour",
            [*base, "Marketing_Airline_Network = ?", "CAST(FLOOR(TRY_CAST(CRSDepTime AS DOUBLE) / 100) AS INTEGER) = ?"],
            [*base_params, carrier, departure_hour],
        ))
    if carrier:
        candidates.append((
            "route + airline",
            [*base, "Marketing_Airline_Network = ?"],
            [*base_params, carrier],
        ))
    if departure_hour is not None:
        candidates.append((
            "route + departure hour",
            [*base, "CAST(FLOOR(TRY_CAST(CRSDepTime AS DOUBLE) / 100) AS INTEGER) = ?"],
            [*base_params, departure_hour],
        ))
    candidates.append(("route", base, base_params))

    stats_sql = """
        SELECT
            COUNT(*) AS scheduled_flights,
            COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS completed_flights,
            COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL AND ArrDel15 = 1) AS late_flights,
            SUM(CASE WHEN Cancelled = 0 AND ArrDelay IS NOT NULL THEN ArrDelay ELSE 0 END) AS delay_sum,
            AVG(CASE WHEN Cancelled = 0 AND ArrDelay IS NOT NULL THEN ArrDelay END) AS average_delay,
            quantile_cont(ArrDelay, 0.50) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS median_delay,
            quantile_cont(ArrDelay, 0.90) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS p90_delay,
            COUNT(*) FILTER (WHERE Cancelled = 1) AS cancelled_flights,
            MIN(FlightDate) AS first_date,
            MAX(FlightDate) AS last_date,
            COUNT(DISTINCT strftime(FlightDate, '%Y-%m')) AS training_months
        FROM SOURCE_TABLE
        WHERE PREDICATES
    """

    selected_scope: str | None = None
    selected_stats: dict[str, Any] | None = None
    selected_predicates: list[str] | None = None
    selected_params: list[Any] | None = None
    last_stats: tuple[Any, ...] | None = None

    for scope, predicates, params in candidates:
        row = connection.execute(
            stats_sql.replace("SOURCE_TABLE", source_table).replace(
                "PREDICATES", " AND ".join(predicates)
            ),
            params,
        ).fetchone()
        last_stats = row
        stats = _stats_from_row(row)
        if stats["scheduled_flights"] and (
            stats["completed_flights"] >= MIN_COMPLETED_FOR_MATCH
            or scope == "route"
        ):
            selected_scope = scope
            selected_stats = stats
            selected_predicates = predicates
            selected_params = params
            break

    if selected_stats is None or selected_scope is None:
        if not last_stats or not last_stats[0]:
            raise LookupError(
                f"No flights for {origin} → {dest} before target month {target_start:%Y-%m}."
            )
        selected_scope = candidates[-1][0]
        selected_stats = _stats_from_row(last_stats)
        selected_predicates = candidates[-1][1]
        selected_params = candidates[-1][2]

    completed = int(selected_stats["completed_flights"] or 0)
    late = int(selected_stats["late_flights"] or 0)
    scheduled = int(selected_stats["scheduled_flights"] or 0)
    cancelled = int(selected_stats["cancelled_flights"] or 0)
    baseline_late_probability = _probability(late, completed)
    baseline_expected_delay = selected_stats["average_delay"]
    late_probability = baseline_late_probability
    expected_arrival_delay = baseline_expected_delay
    cancellation_probability = _probability(cancelled, scheduled)

    monthly_sql = """
        SELECT
            strftime(FlightDate, '%Y-%m') AS period,
            COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS completed_flights,
            COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL AND ArrDel15 = 1) AS late_flights,
            SUM(CASE WHEN Cancelled = 0 AND ArrDelay IS NOT NULL THEN ArrDelay ELSE 0 END) AS delay_sum
        FROM SOURCE_TABLE
        WHERE PREDICATES
        GROUP BY period
        ORDER BY period
    """
    month_rows = [
        {
            "period": row[0],
            "completed_flights": row[1],
            "late_flights": row[2],
            "delay_sum": row[3],
        }
        for row in connection.execute(
            monthly_sql.replace("SOURCE_TABLE", source_table).replace(
                "PREDICATES", " AND ".join(selected_predicates or [])
            ),
            selected_params or [],
        ).fetchall()
    ]

    target_period = target_start.strftime("%Y-%m")
    t100_rows, t100_scope = load_t100_route_context(
        connection,
        origin=origin,
        dest=dest,
        carrier=carrier if "airline" in selected_scope else None,
        target_period=target_period,
    )
    month_rows = attach_lagged_traffic(month_rows, t100_rows)
    traffic_context = build_traffic_adjustment(
        month_rows,
        t100_rows,
        target_period=target_period,
        baseline_delay=baseline_expected_delay,
        baseline_late_probability=baseline_late_probability,
    )
    traffic_context["traffic_scope"] = t100_scope
    traffic_validation = traffic_band_backtest(month_rows)

    probability_trials = completed
    probability_successes = late
    if traffic_context["status"] == "used":
        late_probability = traffic_context["traffic_late_probability"]
        expected_arrival_delay = traffic_context["traffic_expected_delay_minutes"]
        probability_trials = int(traffic_context["matched_completed_flights"] or 0)
        probability_successes = int(traffic_context["matched_late_flights"] or 0)

    return {
        "origin": origin,
        "dest": dest,
        "carrier": carrier,
        "departure_hour": departure_hour,
        "target_period": target_start.strftime("%Y-%m"),
        "target_is_future": target_start > latest_observation.replace(day=1),
        "requested_scope": requested_scope,
        "matched_scope": selected_scope,
        "used_fallback": selected_scope != requested_scope,
        "source_table": source_table,
        "training_start": str(selected_stats["first_date"])[:10] if selected_stats["first_date"] else None,
        "training_through": str(selected_stats["last_date"])[:10] if selected_stats["last_date"] else None,
        "training_cutoff": target_start.isoformat(),
        "training_months": int(selected_stats["training_months"] or 0),
        "scheduled_flights": scheduled,
        # Keep the generic name for existing clients while the more precise
        # scheduled/completed names make the forecast semantics explicit.
        "total_flights": scheduled,
        "completed_flights": completed,
        "late_flights": late,
        "on_time_rate": (1.0 - late_probability) if late_probability is not None else None,
        "late_probability": late_probability,
        "late_probability_ci_95": list(wilson_interval(probability_successes, probability_trials) or (None, None)),
        "cancellation_probability": cancellation_probability,
        "cancellation_probability_ci_95": list(wilson_interval(cancelled, scheduled) or (None, None)),
        "cancellation_rate": cancellation_probability,
        "expected_arrival_delay_minutes": expected_arrival_delay,
        "avg_arrival_delay_minutes": expected_arrival_delay,
        "median_arrival_delay_minutes": selected_stats["median_delay"],
        "p90_arrival_delay_minutes": selected_stats["p90_delay"],
        "confidence": confidence_label(completed),
        "validation": expanding_baseline_backtest(month_rows),
        "model": traffic_context["model"],
        "baseline_expected_arrival_delay_minutes": baseline_expected_delay,
        "baseline_late_probability": baseline_late_probability,
        "traffic_context": traffic_context,
        "traffic_validation": traffic_validation,
        "interpretation": (
            "This is a T-100 traffic-band baseline: earlier months with a similar "
            "load-factor band inform the expected delay and late-arrival probability. "
            "It remains an association, not a causal claim."
            if traffic_context["status"] == "used"
            else "This is an expanding historical baseline: the target month is estimated "
            "from earlier comparable BTS flights only. T-100 context was not sufficient "
            "for an adjustment, and the result is not a causal claim."
        ),
    }
