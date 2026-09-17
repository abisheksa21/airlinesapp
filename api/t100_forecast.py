"""Small, time-aware T-100 feature layer for route forecasting.

T-100 is monthly route traffic context, not a flight-level feature. This
module therefore uses the latest T-100 route-month available before a target
month and compares it with earlier months that had a similar load-factor
band. It is intentionally a transparent benchmark, not a black-box model.
"""

from __future__ import annotations

from typing import Any, Iterable


T100_ROUTE_MONTH_TABLE = "bts_t100_segment_route_month"
MIN_TRAFFIC_MATCH_MONTHS = 3
TRAFFIC_BAND_THRESHOLDS = (0.70, 0.85)


def _period_code(period: str) -> int:
    year, month = (int(part) for part in str(period)[:7].split("-"))
    return year * 12 + month


def _month_gap(later: str, earlier: str) -> int:
    return _period_code(later) - _period_code(earlier)


def traffic_band(load_factor: float | None) -> str | None:
    """Put a load factor into a plain-language operating band."""
    if load_factor is None:
        return None
    if load_factor < TRAFFIC_BAND_THRESHOLDS[0]:
        return "lower load"
    if load_factor < TRAFFIC_BAND_THRESHOLDS[1]:
        return "typical load"
    return "higher load"


def load_t100_route_context(
    connection: Any,
    *,
    origin: str,
    dest: str,
    carrier: str | None,
    target_period: str,
) -> tuple[list[dict[str, Any]], str]:
    """Load route-month traffic rows strictly before the target period.

    When no carrier is selected, the route context is aggregated across
    carriers. When a carrier is selected, it stays at carrier + route + month,
    matching the grain used by the existing T-100 correlation view.
    """
    from api.analytics import table_exists

    if not table_exists(connection, T100_ROUTE_MONTH_TABLE):
        return [], "unavailable"

    carrier_clause = ""
    params: list[Any] = [origin, dest, _period_code(target_period)]
    scope = "route + month across carriers"
    if carrier:
        carrier_clause = "AND UniqueCarrier = ?"
        params.append(carrier)
        scope = "airline + route + month"

    rows = connection.execute(
        f"""
        SELECT
            Year,
            Month,
            SUM(COALESCE(seats_available, 0)) AS seats_available,
            SUM(COALESCE(passengers, 0)) AS passengers,
            SUM(COALESCE(departures_scheduled, 0)) AS departures_scheduled,
            SUM(COALESCE(departures_performed, 0)) AS departures_performed
        FROM {T100_ROUTE_MONTH_TABLE}
        WHERE Origin = ?
          AND Dest = ?
          AND (CAST(Year AS INTEGER) * 12 + CAST(Month AS INTEGER)) < ?
          {carrier_clause}
        GROUP BY Year, Month
        ORDER BY Year, Month
        """,
        params,
    ).fetchall()

    context: list[dict[str, Any]] = []
    for year, month, seats, passengers, scheduled, performed in rows:
        period = f"{int(year):04d}-{int(month):02d}"
        seats_value = float(seats or 0)
        scheduled_value = float(scheduled or 0)
        context.append(
            {
                "period": period,
                "seats_available": int(seats_value),
                "passengers": int(passengers or 0),
                "departures_scheduled": int(scheduled_value),
                "departures_performed": int(performed or 0),
                "load_factor": (float(passengers) / seats_value) if seats_value else None,
                "completion_rate": (
                    float(performed or 0) / scheduled_value if scheduled_value else None
                ),
            }
        )
    return context, scope


def attach_lagged_traffic(
    month_rows: Iterable[dict[str, Any]],
    t100_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach the most recently available T-100 context before each OTP month."""
    ordered_traffic = sorted(t100_rows, key=lambda row: _period_code(row["period"]))
    enriched: list[dict[str, Any]] = []
    for row in sorted(month_rows, key=lambda item: str(item["period"])):
        period = str(row["period"])[:7]
        prior = next(
            (candidate for candidate in reversed(ordered_traffic)
             if _period_code(candidate["period"]) < _period_code(period)),
            None,
        )
        enriched_row = dict(row)
        if prior is None:
            enriched_row.update({
                "traffic_period": None,
                "traffic_load_factor": None,
                "traffic_band": None,
                "traffic_passengers": None,
                "traffic_seats_available": None,
                "traffic_completion_rate": None,
                "traffic_staleness_months": None,
            })
        else:
            enriched_row.update({
                "traffic_period": prior["period"],
                "traffic_load_factor": prior["load_factor"],
                "traffic_band": traffic_band(prior["load_factor"]),
                "traffic_passengers": prior["passengers"],
                "traffic_seats_available": prior["seats_available"],
                "traffic_completion_rate": prior["completion_rate"],
                "traffic_staleness_months": _month_gap(period, prior["period"]),
            })
        enriched.append(enriched_row)
    return enriched


def _metric_summary(
    scored: list[dict[str, float]],
    *,
    status: str,
    minimum_prior_completed: int,
    minimum_traffic_months: int,
) -> dict[str, Any]:
    if not scored:
        return {
            "status": "insufficient_history",
            "months_scored": 0,
            "mean_absolute_error_minutes": None,
            "brier_score_late_probability": None,
            "minimum_prior_completed": minimum_prior_completed,
            "minimum_traffic_months": minimum_traffic_months,
        }
    return {
        "status": status,
        "months_scored": len(scored),
        "mean_absolute_error_minutes": round(
            sum(item["absolute_delay_error"] for item in scored) / len(scored), 3
        ),
        "brier_score_late_probability": round(
            sum(item["late_brier_error"] for item in scored) / len(scored), 6
        ),
        "minimum_prior_completed": minimum_prior_completed,
        "minimum_traffic_months": minimum_traffic_months,
    }


def traffic_band_backtest(
    month_rows: Iterable[dict[str, Any]],
    *,
    minimum_prior_completed: int = 30,
    minimum_traffic_months: int = MIN_TRAFFIC_MATCH_MONTHS,
) -> dict[str, Any]:
    """Score the traffic-band estimate using only earlier months."""
    ordered = sorted(month_rows, key=lambda row: str(row["period"]))
    prior: list[dict[str, Any]] = []
    prior_completed = 0
    scored: list[dict[str, float]] = []

    for row in ordered:
        completed = int(row.get("completed_flights") or 0)
        late = int(row.get("late_flights") or 0)
        delay_sum = float(row.get("delay_sum") or 0.0)
        band = row.get("traffic_band")
        if prior_completed >= minimum_prior_completed and completed > 0 and band:
            candidates = [
                item for item in prior
                if item.get("traffic_band") == band and int(item.get("completed_flights") or 0) > 0
            ]
            candidate_completed = sum(int(item.get("completed_flights") or 0) for item in candidates)
            if len(candidates) >= minimum_traffic_months and candidate_completed >= minimum_prior_completed:
                predicted_delay = sum(float(item.get("delay_sum") or 0.0) for item in candidates) / candidate_completed
                predicted_late = sum(int(item.get("late_flights") or 0) for item in candidates) / candidate_completed
                actual_delay = delay_sum / completed
                actual_late = late / completed
                scored.append({
                    "absolute_delay_error": abs(predicted_delay - actual_delay),
                    "late_brier_error": (predicted_late - actual_late) ** 2,
                })
        prior.append(row)
        prior_completed += completed

    return _metric_summary(
        scored,
        status="traffic_band_baseline",
        minimum_prior_completed=minimum_prior_completed,
        minimum_traffic_months=minimum_traffic_months,
    )


def build_traffic_adjustment(
    month_rows: Iterable[dict[str, Any]],
    t100_rows: list[dict[str, Any]],
    *,
    target_period: str,
    baseline_delay: float | None,
    baseline_late_probability: float | None,
    minimum_prior_completed: int = 30,
    minimum_traffic_months: int = MIN_TRAFFIC_MATCH_MONTHS,
) -> dict[str, Any]:
    """Return a traffic-aware estimate when prior T-100 context is sufficient."""
    target_context = t100_rows[-1] if t100_rows else None
    base = {
        "model": "historical_baseline",
        "target_period": target_period,
        "reference_period": target_context["period"] if target_context else None,
        "traffic_scope": "available" if target_context else "unavailable",
        "load_factor": target_context["load_factor"] if target_context else None,
        "traffic_band": traffic_band(target_context["load_factor"]) if target_context else None,
        "passengers": target_context["passengers"] if target_context else None,
        "seats_available": target_context["seats_available"] if target_context else None,
        "completion_rate": target_context["completion_rate"] if target_context else None,
        "reference_staleness_months": (
            _month_gap(target_period, target_context["period"]) if target_context else None
        ),
        "baseline_expected_delay_minutes": baseline_delay,
        "baseline_late_probability": baseline_late_probability,
        "traffic_expected_delay_minutes": None,
        "traffic_late_probability": None,
        "delta_expected_delay_minutes": None,
        "delta_late_probability": None,
        "matched_months": 0,
        "matched_completed_flights": 0,
        "matched_late_flights": 0,
        "minimum_traffic_match_months": minimum_traffic_months,
    }
    if target_context is None:
        return {**base, "status": "unavailable", "reason": "No T-100 route-month exists before the target month."}

    band = traffic_band(target_context["load_factor"])
    if band is None:
        return {**base, "status": "unavailable", "reason": "The latest prior T-100 row has no usable seat count."}

    candidates = [
        row for row in month_rows
        if row.get("traffic_band") == band and int(row.get("completed_flights") or 0) > 0
    ]
    matched_completed = sum(int(row.get("completed_flights") or 0) for row in candidates)
    matched_late = sum(int(row.get("late_flights") or 0) for row in candidates)
    if len(candidates) < minimum_traffic_months or matched_completed < minimum_prior_completed:
        return {
            **base,
            "status": "insufficient_context",
            "reason": "Fewer than the minimum number of earlier OTP months shared this traffic band.",
            "matched_months": len(candidates),
            "matched_completed_flights": matched_completed,
            "matched_late_flights": matched_late,
        }

    traffic_delay = sum(float(row.get("delay_sum") or 0.0) for row in candidates) / matched_completed
    traffic_late = matched_late / matched_completed
    return {
        **base,
        "status": "used",
        "model": "t100_traffic_band_baseline",
        "traffic_expected_delay_minutes": traffic_delay,
        "traffic_late_probability": traffic_late,
        "delta_expected_delay_minutes": traffic_delay - baseline_delay if baseline_delay is not None else None,
        "delta_late_probability": traffic_late - baseline_late_probability if baseline_late_probability is not None else None,
        "matched_months": len(candidates),
        "matched_completed_flights": matched_completed,
        "matched_late_flights": matched_late,
    }
