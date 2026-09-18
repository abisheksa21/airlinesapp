"""Historical stability checks for the departure-bank schedule experiment.

This is intentionally not an impact evaluation. It replays the optimizer on
several old calendar windows using only still-earlier equivalent windows to set
its congestion and delay proxy. The result tells us whether the bounded MILP
repeatedly creates a smaller *simulated schedule peak* under the same rules;
it cannot tell us what real flights would have done if an airline had changed
its schedule in the past.
"""

from __future__ import annotations

from datetime import date
from statistics import median
from typing import Any

from dateutil.relativedelta import relativedelta

from api.db import best_flight_table
from api.optimization.backend import PublicBackend
from api.optimization.departure_bank import BankFlight, solve_departure_bank


def _bucket(crs_dep_time: int) -> int:
    hour, minute = divmod(int(crs_dep_time), 100)
    return min(95, max(0, (hour * 60 + minute) // 15))


def _conditions(
    *,
    start_date: str,
    end_date: str,
    airport: str,
    carrier: str | None,
    window_start_hour: int,
    window_end_hour: int,
) -> tuple[list[str], list[Any]]:
    clauses = [
        "FlightDate BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)",
        "Origin = ?",
        "Cancelled = 0",
        "CRSDepTime IS NOT NULL",
        "(CRSDepTime / 100) BETWEEN ? AND ?",
    ]
    params: list[Any] = [start_date, end_date, airport, window_start_hour, window_end_hour]
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier)
    return clauses, params


def _sample_window(
    connection: Any,
    *,
    table: str,
    start_date: str,
    end_date: str,
    airport: str,
    carrier: str | None,
    window_start_hour: int,
    window_end_hour: int,
    flight_limit: int,
) -> tuple[list[tuple[int, float | None]], int]:
    clauses, params = _conditions(
        start_date=start_date,
        end_date=end_date,
        airport=airport,
        carrier=carrier,
        window_start_hour=window_start_hour,
        window_end_hour=window_end_hour,
    )
    # Hash ordering is deterministic for a fixed historical window. Unlike
    # ORDER BY CRSDepTime it does not privilege the early clock hours when a
    # representative safety sample is needed.
    rows = connection.execute(
        f"""
        SELECT CRSDepTime, ArrDelay, COUNT(*) OVER () AS total_matching
        FROM {table}
        WHERE {' AND '.join(clauses)}
        ORDER BY hash(CAST(FlightDate AS VARCHAR), CAST(CRSDepTime AS VARCHAR), COALESCE(Marketing_Airline_Network, ''))
        LIMIT ?
        """,
        params + [flight_limit],
    ).fetchall()
    if not rows:
        return [], 0
    return [(int(row[0]), float(row[1]) if row[1] is not None else None) for row in rows], int(rows[0][2])


def _reference_profile(
    connection: Any,
    *,
    table: str,
    start_date: str,
    end_date: str,
    airport: str,
    carrier: str | None,
    window_start_hour: int,
    window_end_hour: int,
) -> tuple[dict[int, list[int]], dict[int, list[float]]]:
    clauses, params = _conditions(
        start_date=start_date,
        end_date=end_date,
        airport=airport,
        carrier=carrier,
        window_start_hour=window_start_hour,
        window_end_hour=window_end_hour,
    )
    rows = connection.execute(
        f"""
        SELECT
            CAST((CRSDepTime // 100) * 60 + (CRSDepTime % 100) AS INTEGER) // 15 AS bucket,
            COUNT(*) AS flights,
            AVG(ArrDelay) AS average_delay
        FROM {table}
        WHERE {' AND '.join(clauses)}
        GROUP BY bucket
        """,
        params,
    ).fetchall()
    counts: dict[int, list[int]] = {}
    delays: dict[int, list[float]] = {}
    for bucket, flight_count, average_delay in rows:
        counts.setdefault(int(bucket), []).append(int(flight_count))
        if average_delay is not None:
            delays.setdefault(int(bucket), []).append(float(average_delay))
    return counts, delays


def validate_departure_bank_history(
    connection: Any,
    *,
    airport: str,
    carrier: str | None,
    start_date: str,
    end_date: str,
    window_start_hour: int,
    window_end_hour: int,
    allowed_shift_minutes: int,
    maximum_windows: int = 3,
    reference_lookback_years: int = 3,
    flight_limit: int = 600,
    max_moved_flights: int | None = None,
    congestion_weighting: float = 5.0,
    shift_penalty_weight: float = 0.05,
) -> dict[str, Any]:
    """Replay the schedule experiment across several strictly later holdouts."""
    if window_end_hour <= window_start_hour:
        raise ValueError("window_end_hour must be after window_start_hour")
    if maximum_windows < 1 or reference_lookback_years < 1:
        raise ValueError("maximum_windows and reference_lookback_years must be at least one")
    airport = airport.upper()
    carrier = carrier.upper() if carrier else None
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    table = best_flight_table(
        connection,
        {"FlightDate", "Origin", "CRSDepTime", "Cancelled", "ArrDelay", "Marketing_Airline_Network"},
    )

    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for test_offset in range(1, maximum_windows + 1):
        test_start = start - relativedelta(years=test_offset)
        test_end = end - relativedelta(years=test_offset)
        sample, total_matching = _sample_window(
            connection,
            table=table,
            start_date=test_start.isoformat(),
            end_date=test_end.isoformat(),
            airport=airport,
            carrier=carrier,
            window_start_hour=window_start_hour,
            window_end_hour=window_end_hour,
            flight_limit=flight_limit,
        )
        if not sample:
            skipped.append({"test_window": f"{test_start} to {test_end}", "reason": "No matching completed flights."})
            continue

        reference_counts: dict[int, list[int]] = {}
        reference_delays: dict[int, list[float]] = {}
        reference_years_used = 0
        for reference_offset in range(test_offset + 1, test_offset + reference_lookback_years + 1):
            reference_start = start - relativedelta(years=reference_offset)
            reference_end = end - relativedelta(years=reference_offset)
            counts, delays = _reference_profile(
                connection,
                table=table,
                start_date=reference_start.isoformat(),
                end_date=reference_end.isoformat(),
                airport=airport,
                carrier=carrier,
                window_start_hour=window_start_hour,
                window_end_hour=window_end_hour,
            )
            if counts:
                reference_years_used += 1
            for bucket, values in counts.items():
                reference_counts.setdefault(bucket, []).extend(values)
            for bucket, values in delays.items():
                reference_delays.setdefault(bucket, []).extend(values)
        if not reference_counts:
            skipped.append({
                "test_window": f"{test_start} to {test_end}",
                "reason": "No still-earlier equivalent calendar window was available for the reference profile.",
            })
            continue

        sample_fraction = min(1.0, len(sample) / total_matching) if total_matching else 1.0
        reference_average_load = sum(value for values in reference_counts.values() for value in values) / sum(
            len(values) for values in reference_counts.values()
        )
        preferred_limit = round(max(1.0, reference_average_load * 1.1 * sample_fraction), 1)
        point_estimate = {
            bucket: sum(values) / len(values)
            for bucket, values in reference_delays.items()
            if values
        }
        flights = [
            BankFlight(flight_id=f"{test_start.isoformat()}-{index}", original_bucket=_bucket(crs_dep_time))
            for index, (crs_dep_time, _) in enumerate(sample)
        ]
        applied_move_cap = min(max_moved_flights, len(flights)) if max_moved_flights is not None else None
        result = solve_departure_bank(
            flights,
            n_buckets=96,
            allowed_shift_minutes=allowed_shift_minutes,
            preferred_bank_limit={bucket: preferred_limit for bucket in range(96)},
            congestion_weight_by_bucket={bucket: 1.0 for bucket in range(96)},
            bucket_delay_point_estimate=point_estimate,
            congestion_weighting=congestion_weighting,
            shift_penalty_weight=shift_penalty_weight,
            mode="expected",
            max_moved_flights=applied_move_cap,
            backend=PublicBackend(),
        )
        records.append({
            "test_window": f"{test_start} to {test_end}",
            "reference_years_used": reference_years_used,
            "flights_considered": len(flights),
            "total_matching_flights": total_matching,
            "sample_fraction": round(sample_fraction, 4),
            "preferred_bank_limit": preferred_limit,
            "status": result.status,
            "original_peak_load": result.original_peak_load,
            "optimized_peak_load": result.optimized_peak_load,
            "peak_reduction": result.original_peak_load - result.optimized_peak_load,
            "flights_moved": result.flights_moved,
            "average_movement_minutes": result.average_movement_minutes,
        })

    successful = [record for record in records if record["status"] in {"optimal", "feasible"}]
    reductions = [float(record["peak_reduction"]) for record in successful]
    return {
        "status": "ready" if successful else "insufficient_history",
        "scope": {
            "airport": airport,
            "carrier": carrier,
            "calendar_window": f"{start_date} to {end_date}",
            "departure_window": f"{window_start_hour:02d}:00-{window_end_hour:02d}:00",
            "allowed_shift_minutes": allowed_shift_minutes,
        },
        "summary": {
            "windows_requested": maximum_windows,
            "windows_evaluated": len(successful),
            "windows_with_smaller_simulated_peak": sum(reduction > 0 for reduction in reductions),
            "median_peak_reduction": round(float(median(reductions)), 2) if reductions else None,
            "average_movement_minutes": round(
                sum(float(record["average_movement_minutes"]) for record in successful) / len(successful), 2
            ) if successful else None,
        },
        "records": records,
        "skipped": skipped,
        "methodology": {
            "design": "Historical replay. For every test window, the preferred bank limit and delay proxy are calculated from earlier equivalent calendar windows only.",
            "what_is_checked": "Whether the optimizer repeatedly lowers the simulated 15-minute schedule peak under its declared movement and sampling constraints.",
            "not_claimed": "This is not a causal estimate of delay reduction, certified airport capacity, passenger impact, or an operational recommendation without airline feasibility checks.",
        },
    }
