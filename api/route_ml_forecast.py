"""Leakage-safe machine-learning forecasts for a selected route scenario.

This is the first ML layer in the project. It intentionally sits beside the
transparent historical/T-100 baseline in ``api.route_forecast`` rather than
replacing it silently. It contains both a route-specific candidate and a
broader route-panel candidate trained across many historical route-months.

The model works at route + selected filters + month grain.  For each observed
month it builds features from strictly earlier OTP months and the latest
available earlier T-100 context, then predicts three monthly outcomes:

* expected arrival-delay minutes (regularized regression)
* late-arrival rate (regularized regression of the observed monthly rate)
* cancellation rate (regularized regression of the observed monthly rate)

These are deliberately small, explainable first models. They are not live
flight-level predictions and they do not claim that T-100 traffic causes delay.
The historical baseline is always returned for comparison, and the ML model
is marked unavailable when its route history is too thin to evaluate honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import threading
import time
from typing import Any

import numpy as np

from api.route_forecast import parse_target_month
from api.t100_forecast import attach_lagged_traffic, load_t100_route_context


FEATURE_NAMES = (
    "prior_late_rate",
    "prior_delay_minutes",
    "prior_cancellation_rate",
    "recent_late_rate",
    "recent_delay_minutes",
    "recent_cancellation_rate",
    "traffic_load_factor",
    "traffic_passengers_log",
    "traffic_seats_log",
    "traffic_completion_rate",
    "traffic_context_available",
    "month_sin",
    "month_cos",
    "log_prior_completed_flights",
)

MIN_PRIOR_COMPLETED = 30
MIN_TARGET_COMPLETED = 20
MIN_TRAINING_EXAMPLES = 48
MIN_SPLIT_EXAMPLES = 6
RIDGE_PENALTY = 1.0

PANEL_TABLE = "analytics_route_month"
PANEL_MIN_COMPLETED = 30
PANEL_MIN_TRAINING_EXAMPLES = 120
PANEL_FEATURE_NAMES = (
    "prior_late_rate",
    "prior_delay_minutes",
    "prior_cancellation_rate",
    "recent_late_rate",
    "recent_delay_minutes",
    "recent_cancellation_rate",
    "traffic_load_factor",
    "traffic_passengers_log",
    "traffic_seats_log",
    "traffic_completion_rate",
    "traffic_context_available",
    "traffic_staleness_months",
    "distance_log",
    "month_sin",
    "month_cos",
    "log_prior_completed_flights",
)
# The ablation deliberately removes every lagged T-100 input while keeping
# the same OTP history, distance, seasonality, and sample-size inputs. This
# lets the researcher answer whether T-100 adds predictive value, rather than
# assuming that a richer feature set is automatically better.
PANEL_NO_T100_FEATURE_INDICES = tuple(
    index for index, name in enumerate(PANEL_FEATURE_NAMES) if not name.startswith("traffic_")
)
PANEL_NO_T100_FEATURE_NAMES = tuple(PANEL_FEATURE_NAMES[index] for index in PANEL_NO_T100_FEATURE_INDICES)
PANEL_CACHE_TTL_SECONDS = 600
_PANEL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_PANEL_CACHE_LOCK = threading.Lock()


@dataclass
class Standardizer:
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, values: np.ndarray) -> "Standardizer":
        mean = values.mean(axis=0)
        scale = values.std(axis=0)
        return cls(mean=mean, scale=np.where(scale < 1e-9, 1.0, scale))

    def transform(self, values: np.ndarray) -> np.ndarray:
        return (values - self.mean) / self.scale


@dataclass
class RidgeModel:
    coefficients: np.ndarray
    intercept: float

    def predict(self, values: np.ndarray) -> np.ndarray:
        return values @ self.coefficients + self.intercept


def fit_ridge_regression(
    values: np.ndarray,
    targets: np.ndarray,
    weights: np.ndarray,
    *,
    penalty: float = RIDGE_PENALTY,
) -> RidgeModel:
    """Fit a weighted ridge model using a stable closed-form solve."""
    if len(values) != len(targets) or len(values) != len(weights):
        raise ValueError("values, targets, and weights must have equal lengths")
    if len(values) < 2:
        raise ValueError("At least two examples are required for ridge regression")

    design = np.column_stack([np.ones(len(values)), values])
    safe_weights = np.maximum(np.asarray(weights, dtype=float), 1.0)
    weighted_design = design * safe_weights[:, None]
    normal = design.T @ weighted_design
    normal += np.diag(np.r_[0.0, np.full(values.shape[1], penalty)])
    right_hand = design.T @ (safe_weights * targets)
    solution = np.linalg.solve(normal + np.eye(normal.shape[0]) * 1e-9, right_hand)
    return RidgeModel(coefficients=solution[1:], intercept=float(solution[0]))


def _period_index(period: str) -> int:
    year, month = (int(part) for part in str(period)[:7].split("-"))
    return year * 12 + month - 1


def _period_parts(period: str) -> tuple[int, int]:
    year, month = (int(part) for part in str(period)[:7].split("-"))
    return year, month


def _weighted_mean(rows: list[dict[str, Any]], value: str, weight: str) -> float:
    usable = [row for row in rows if row.get(value) is not None and float(row.get(weight) or 0) > 0]
    if not usable:
        return 0.0
    total_weight = sum(float(row.get(weight) or 0) for row in usable)
    if total_weight <= 0:
        return 0.0
    return sum(float(row[value]) * float(row.get(weight) or 0) for row in usable) / total_weight


def _monthly_outcomes(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    completed = int(row.get("completed_flights") or 0)
    scheduled = int(row.get("scheduled_flights") or 0)
    if completed <= 0:
        delay = None
        late = None
    else:
        delay = float(row.get("delay_sum") or 0.0) / completed
        late = int(row.get("late_flights") or 0) / completed
    cancelled = float(row.get("cancelled_flights") or 0)
    cancellation = cancelled / scheduled if scheduled > 0 else None
    return delay, late, cancellation


def build_feature_vector(
    prior_rows: list[dict[str, Any]],
    context_row: dict[str, Any],
    *,
    period: str,
) -> list[float]:
    """Build features from history before ``period`` plus lagged T-100.

    ``prior_rows`` must contain only months before the feature period.  Keeping
    this boundary explicit makes the no-future-leakage contract easy to test.
    """
    target_index = _period_index(period)
    usable = [
        row for row in prior_rows
        if _period_index(str(row["period"])) < target_index
        and int(row.get("completed_flights") or 0) > 0
    ]
    recent = usable[-3:]
    prior_completed = sum(int(row.get("completed_flights") or 0) for row in usable)

    enriched_prior: list[dict[str, Any]] = []
    for row in usable:
        delay, late, cancellation = _monthly_outcomes(row)
        enriched_prior.append({
            **row,
            "delay_rate": delay,
            "late_rate": late,
            "cancel_rate": cancellation,
        })

    recent_enriched: list[dict[str, Any]] = []
    for row in recent:
        delay, late, cancellation = _monthly_outcomes(row)
        recent_enriched.append({
            **row,
            "delay_rate": delay,
            "late_rate": late,
            "cancel_rate": cancellation,
        })

    _, month = _period_parts(period)
    angle = 2.0 * np.pi * (month - 1) / 12.0
    traffic_load = context_row.get("traffic_load_factor")
    traffic_passengers = context_row.get("traffic_passengers")
    traffic_seats = context_row.get("traffic_seats_available")
    traffic_completion = context_row.get("traffic_completion_rate")

    return [
        _weighted_mean(enriched_prior, "late_rate", "completed_flights"),
        _weighted_mean(enriched_prior, "delay_rate", "completed_flights"),
        _weighted_mean(enriched_prior, "cancel_rate", "scheduled_flights"),
        _weighted_mean(recent_enriched, "late_rate", "completed_flights"),
        _weighted_mean(recent_enriched, "delay_rate", "completed_flights"),
        _weighted_mean(recent_enriched, "cancel_rate", "scheduled_flights"),
        float(traffic_load or 0.0),
        float(np.log1p(max(float(traffic_passengers or 0.0), 0.0))),
        float(np.log1p(max(float(traffic_seats or 0.0), 0.0))),
        float(traffic_completion or 0.0),
        1.0 if traffic_load is not None else 0.0,
        float(np.sin(angle)),
        float(np.cos(angle)),
        float(np.log1p(max(prior_completed, 0))),
    ]


def build_supervised_route_examples(
    month_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[float]]:
    """Turn a route's monthly history into time-ordered ML examples."""
    ordered = sorted(month_rows, key=lambda row: str(row["period"]))
    examples: list[dict[str, Any]] = []
    for index, row in enumerate(ordered):
        completed = int(row.get("completed_flights") or 0)
        delay, late, cancellation = _monthly_outcomes(row)
        prior = ordered[:index]
        prior_completed = sum(int(item.get("completed_flights") or 0) for item in prior)
        if prior_completed < MIN_PRIOR_COMPLETED or completed < MIN_TARGET_COMPLETED:
            continue
        features = build_feature_vector(prior, row, period=str(row["period"]))
        examples.append({
            "period": str(row["period"]),
            "features": features,
            "targets": {
                "delay_minutes": delay,
                "late_rate": late,
                "cancellation_rate": cancellation,
            },
            "baseline": {
                "delay_minutes": features[1],
                "late_rate": features[0],
                "cancellation_rate": features[2],
            },
            "weight": float(max(completed, 1)),
        })
    return examples, [float(row["completed_flights"] or 0) for row in ordered]


def _metric_summary(
    examples: list[dict[str, Any]],
    predictions: dict[str, np.ndarray],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {"examples": len(examples)}
    for target in ("delay_minutes", "late_rate", "cancellation_rate"):
        actual = np.asarray([float(row["targets"][target]) for row in examples], dtype=float)
        predicted = np.asarray(predictions[target], dtype=float)
        error = np.abs(predicted - actual)
        metrics[f"{target}_mae"] = round(float(error.mean()), 4) if len(error) else None
        if target != "delay_minutes":
            metrics[f"{target}_brier_like"] = round(float(np.mean((predicted - actual) ** 2)), 6) if len(error) else None
    return metrics


def _predict_models(
    fit: dict[str, Any],
    examples: list[dict[str, Any]],
) -> dict[str, np.ndarray]:
    if not examples:
        return {target: np.asarray([], dtype=float) for target in ("delay_minutes", "late_rate", "cancellation_rate")}
    values = np.asarray([row["features"] for row in examples], dtype=float)
    feature_indices = fit.get("feature_indices")
    if feature_indices is not None:
        values = values[:, list(feature_indices)]
    values = fit["standardizer"].transform(values)
    return {
        target: np.clip(fit["models"][target].predict(values), 0.0, 1.0) if target != "delay_minutes"
        else np.maximum(fit["models"][target].predict(values), 0.0)
        for target in ("delay_minutes", "late_rate", "cancellation_rate")
    }


def _baseline_predictions(examples: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    return {
        target: np.asarray([float(row["baseline"][target]) for row in examples], dtype=float)
        for target in ("delay_minutes", "late_rate", "cancellation_rate")
    }


def _fit_models(
    examples: list[dict[str, Any]],
    *,
    feature_indices: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    values = np.asarray([row["features"] for row in examples], dtype=float)
    if feature_indices is None:
        feature_indices = tuple(range(values.shape[1]))
    values = values[:, list(feature_indices)]
    standardizer = Standardizer.fit(values)
    scaled = standardizer.transform(values)
    weights = np.asarray([row["weight"] for row in examples], dtype=float)
    models = {
        target: fit_ridge_regression(
            scaled,
            np.asarray([float(row["targets"][target]) for row in examples], dtype=float),
            weights,
        )
        for target in ("delay_minutes", "late_rate", "cancellation_rate")
    }
    return {"standardizer": standardizer, "models": models, "feature_indices": feature_indices}


def _split_examples(examples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(examples, key=lambda row: str(row["period"]))
    train_end = int(len(ordered) * 0.6)
    validation_end = int(len(ordered) * 0.8)
    if train_end < MIN_SPLIT_EXAMPLES or validation_end - train_end < MIN_SPLIT_EXAMPLES or len(ordered) - validation_end < MIN_SPLIT_EXAMPLES:
        raise ValueError("Route history is too thin for a train/validation/test split.")
    return ordered[:train_end], ordered[train_end:validation_end], ordered[validation_end:]


def _coefficient_records(
    models: dict[str, RidgeModel],
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> dict[str, list[dict[str, Any]]]:
    return {
        target: [
            {
                "feature": feature,
                "standardized_coefficient": round(float(coefficient), 6),
                "direction": "higher_prediction" if coefficient > 0 else "lower_prediction",
            }
            for feature, coefficient in zip(feature_names, model.coefficients)
        ]
        for target, model in models.items()
    }


def _query_route_months(
    connection: Any,
    *,
    source_table: str,
    origin: str,
    dest: str,
    carrier: str | None,
    departure_hour: int | None,
    cutoff: date,
) -> list[dict[str, Any]]:
    predicates = ["Origin = ?", "Dest = ?", "FlightDate < CAST(? AS DATE)"]
    params: list[Any] = [origin, dest, cutoff.isoformat()]
    if carrier:
        predicates.append("Marketing_Airline_Network = ?")
        params.append(carrier)
    if departure_hour is not None:
        predicates.append("CAST(FLOOR(TRY_CAST(CRSDepTime AS DOUBLE) / 100) AS INTEGER) = ?")
        params.append(departure_hour)

    rows = connection.execute(
        f"""
        SELECT
            strftime(FlightDate, '%Y-%m') AS period,
            COUNT(*) AS scheduled_flights,
            COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS completed_flights,
            COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL AND ArrDel15 = 1) AS late_flights,
            SUM(CASE WHEN Cancelled = 0 AND ArrDelay IS NOT NULL THEN ArrDelay ELSE 0 END) AS delay_sum,
            COUNT(*) FILTER (WHERE Cancelled = 1) AS cancelled_flights
        FROM {source_table}
        WHERE {' AND '.join(predicates)}
        GROUP BY period
        ORDER BY period
        """,
        params,
    ).fetchall()
    keys = ("period", "scheduled_flights", "completed_flights", "late_flights", "delay_sum", "cancelled_flights")
    return [dict(zip(keys, row)) for row in rows]


def build_route_ml_forecast(
    connection: Any,
    *,
    origin: str,
    dest: str,
    carrier: str | None = None,
    departure_hour: int | None = None,
    target_month: str | None = None,
) -> dict[str, Any]:
    """Train and score a route-specific ML forecast without future leakage."""
    from api.analytics import table_exists
    from pipeline.otp_core import CORE_TABLE_NAME

    origin = origin.upper()
    dest = dest.upper()
    carrier = carrier.upper() if carrier else None
    source_table = CORE_TABLE_NAME if table_exists(connection, CORE_TABLE_NAME) else "flights"

    latest_row = connection.execute(
        f"SELECT MAX(FlightDate) FROM {source_table} WHERE FlightDate IS NOT NULL"
    ).fetchone()
    if not latest_row or latest_row[0] is None:
        raise LookupError("The warehouse has no dated flight observations.")
    latest = latest_row[0]
    if isinstance(latest, datetime):
        latest = latest.date()
    elif isinstance(latest, str):
        latest = date.fromisoformat(latest[:10])
    target_start = parse_target_month(target_month, latest)
    target_period = target_start.strftime("%Y-%m")

    requested_scope = "route"
    if carrier and departure_hour is not None:
        requested_scope = "route + airline + departure hour"
    elif carrier:
        requested_scope = "route + airline"
    elif departure_hour is not None:
        requested_scope = "route + departure hour"

    candidate_filters: list[tuple[str, str | None, int | None]] = []
    if carrier and departure_hour is not None:
        candidate_filters.append(("route + airline + departure hour", carrier, departure_hour))
    if carrier:
        candidate_filters.append(("route + airline", carrier, None))
    if departure_hour is not None:
        candidate_filters.append(("route + departure hour", None, departure_hour))
    candidate_filters.append(("route", None, None))

    selected_scope: str | None = None
    selected_carrier: str | None = None
    selected_hour: int | None = None
    selected_rows: list[dict[str, Any]] = []
    selected_t100_rows: list[dict[str, Any]] = []
    selected_t100_scope = "unavailable"
    selected_examples: list[dict[str, Any]] = []

    for scope, candidate_carrier, candidate_hour in candidate_filters:
        month_rows = _query_route_months(
            connection,
            source_table=source_table,
            origin=origin,
            dest=dest,
            carrier=candidate_carrier,
            departure_hour=candidate_hour,
            cutoff=target_start,
        )
        if not month_rows:
            continue
        t100_rows, t100_scope = load_t100_route_context(
            connection,
            origin=origin,
            dest=dest,
            carrier=candidate_carrier,
            target_period=target_period,
        )
        enriched_rows = attach_lagged_traffic(month_rows, t100_rows)
        examples, _ = build_supervised_route_examples(enriched_rows)
        selected_scope = scope
        selected_carrier = candidate_carrier
        selected_hour = candidate_hour
        selected_rows = enriched_rows
        selected_t100_rows = t100_rows
        selected_t100_scope = t100_scope
        selected_examples = examples
        if len(examples) >= MIN_TRAINING_EXAMPLES:
            break

    if selected_scope is None:
        raise LookupError(f"No earlier flights for {origin} → {dest} before {target_period}.")

    t100_scope = selected_t100_scope
    enriched_rows = selected_rows
    target_context = attach_lagged_traffic([{"period": target_period}], selected_t100_rows)[0]
    examples = selected_examples
    if len(examples) < MIN_TRAINING_EXAMPLES:
        return {
            "status": "insufficient_history",
            "origin": origin,
            "dest": dest,
            "carrier": carrier,
            "departure_hour": departure_hour,
            "requested_scope": requested_scope,
            "matched_scope": selected_scope,
            "used_fallback": selected_scope != requested_scope,
            "target_period": target_period,
            "training_cutoff": target_start.isoformat(),
            "model": "route_ridge_ml",
            "examples": len(examples),
            "minimum_examples": MIN_TRAINING_EXAMPLES,
            "reason": "The selected route scenario does not have enough prior monthly examples for an honest ML evaluation.",
            "t100_scope": t100_scope,
        }

    train, validation, test = _split_examples(examples)
    evaluation_fit = _fit_models(train)
    validation_metrics = _metric_summary(validation, _predict_models(evaluation_fit, validation))
    test_predictions = _predict_models(evaluation_fit, test)
    test_metrics = _metric_summary(test, test_predictions)
    baseline_test_metrics = _metric_summary(test, _baseline_predictions(test))

    # Refit after evaluation using all history before the requested target. The
    # held-out metrics above remain untouched and are the honest model check.
    production_fit = _fit_models(examples)
    target_features = build_feature_vector(enriched_rows, target_context, period=target_period)
    target_values = production_fit["standardizer"].transform(np.asarray([target_features], dtype=float))
    predictions = {
        target: float(production_fit["models"][target].predict(target_values)[0])
        for target in ("delay_minutes", "late_rate", "cancellation_rate")
    }
    predictions["delay_minutes"] = max(predictions["delay_minutes"], 0.0)
    predictions["late_rate"] = min(max(predictions["late_rate"], 0.0), 1.0)
    predictions["cancellation_rate"] = min(max(predictions["cancellation_rate"], 0.0), 1.0)

    return {
        # "candidate" is deliberate: the model ran, but it is not promoted
        # to the public answer until held-out performance beats the baseline.
        "status": "candidate",
        "origin": origin,
        "dest": dest,
        "carrier": carrier,
        "departure_hour": departure_hour,
        "requested_scope": requested_scope,
        "matched_scope": selected_scope,
        "used_fallback": selected_scope != requested_scope,
        "target_period": target_period,
        "target_is_future": target_start > latest.replace(day=1),
        "training_start": examples[0]["period"],
        "training_through": examples[-1]["period"],
        "training_cutoff": target_start.isoformat(),
        "model": "route_ridge_ml",
        "training_examples": len(examples),
        "split": {
            "train_examples": len(train),
            "validation_examples": len(validation),
            "test_examples": len(test),
            "train_end": train[-1]["period"],
            "validation_end": validation[-1]["period"],
        },
        "predictions": {
            "expected_arrival_delay_minutes": round(predictions["delay_minutes"], 3),
            "late_probability": round(predictions["late_rate"], 5),
            "cancellation_probability": round(predictions["cancellation_rate"], 5),
        },
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "baseline_test_metrics": baseline_test_metrics,
        "model_selection": {
            "improved_targets": [
                target for target in ("delay_minutes", "late_rate", "cancellation_rate")
                if test_metrics.get(f"{target}_mae") is not None
                and test_metrics[f"{target}_mae"] < baseline_test_metrics.get(f"{target}_mae", float("inf"))
            ],
            "note": (
                "The ML forecasts are researcher candidates. The public forecast remains the "
                "transparent baseline until the ML candidate wins on future held-out months."
            ),
        },
        "coefficients": _coefficient_records(production_fit["models"]),
        "features_for_target": {
            name: round(float(value), 5) for name, value in zip(FEATURE_NAMES, target_features)
        },
        "traffic_context": {
            "scope": t100_scope,
            "reference_period": target_context.get("traffic_period"),
            "load_factor": target_context.get("traffic_load_factor"),
            "passengers": target_context.get("traffic_passengers"),
            "seats_available": target_context.get("traffic_seats_available"),
            "completion_rate": target_context.get("traffic_completion_rate"),
            "staleness_months": target_context.get("traffic_staleness_months"),
        },
        "interpretation": (
            "The ML estimate uses prior route history, recent route movement, calendar seasonality, "
            "and lagged T-100 traffic context. It is a forward-looking estimate, not a causal claim."
        ),
    }


def _panel_outcomes(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    completed = int(row.get("completed_flights") or 0)
    delay = row.get("avg_arrival_delay_minutes")
    on_time = row.get("on_time_rate")
    late = (1.0 - float(on_time)) if on_time is not None else None
    cancellation = row.get("cancellation_rate")
    return (
        float(delay) if delay is not None and completed > 0 else None,
        late if late is None or 0.0 <= late <= 1.0 else min(max(late, 0.0), 1.0),
        float(cancellation) if cancellation is not None else None,
    )


def build_panel_feature_vector(
    prior_rows: list[dict[str, Any]],
    context_row: dict[str, Any],
    *,
    period: str,
) -> list[float]:
    """Build a route-panel vector from history strictly before ``period``."""
    target_index = _period_index(period)
    usable = [
        row for row in prior_rows
        if _period_index(str(row["period"])) < target_index
        and int(row.get("completed_flights") or 0) > 0
    ]
    recent = usable[-3:]

    def enrich(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for row in rows:
            delay, late, cancellation = _panel_outcomes(row)
            enriched.append({
                **row,
                "delay_rate": delay,
                "late_rate": late,
                "cancel_rate": cancellation,
            })
        return enriched

    prior = enrich(usable)
    recent_enriched = enrich(recent)
    _, month = _period_parts(period)
    angle = 2.0 * np.pi * (month - 1) / 12.0
    distance = context_row.get("distance_miles")
    if distance is None and usable:
        distance = usable[-1].get("distance_miles")
    prior_completed = sum(int(row.get("completed_flights") or 0) for row in usable)
    traffic_period = context_row.get("traffic_period")
    traffic_staleness = (
        max(target_index - _period_index(str(traffic_period)), 0)
        if traffic_period
        else 0
    )
    return [
        _weighted_mean(prior, "late_rate", "completed_flights"),
        _weighted_mean(prior, "delay_rate", "completed_flights"),
        _weighted_mean(prior, "cancel_rate", "total_flights"),
        _weighted_mean(recent_enriched, "late_rate", "completed_flights"),
        _weighted_mean(recent_enriched, "delay_rate", "completed_flights"),
        _weighted_mean(recent_enriched, "cancel_rate", "total_flights"),
        float(context_row.get("traffic_load_factor") or 0.0),
        float(np.log1p(max(float(context_row.get("traffic_passengers") or 0.0), 0.0))),
        float(np.log1p(max(float(context_row.get("traffic_seats_available") or 0.0), 0.0))),
        float(context_row.get("traffic_completion_rate") or 0.0),
        1.0 if traffic_period else 0.0,
        float(traffic_staleness),
        float(np.log1p(max(float(distance or 0.0), 0.0))),
        float(np.sin(angle)),
        float(np.cos(angle)),
        float(np.log1p(max(prior_completed, 0))),
    ]


def build_supervised_panel_examples(
    panel_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build one no-leakage example for each eligible route-month."""
    by_route: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in panel_rows:
        key = (str(row["origin"]), str(row["dest"]))
        by_route.setdefault(key, []).append(row)

    examples: list[dict[str, Any]] = []
    for route_rows in by_route.values():
        ordered = sorted(route_rows, key=lambda row: str(row["period"]))
        prior_completed = 0
        prior_late_numerator = 0.0
        prior_delay_numerator = 0.0
        prior_cancel_numerator = 0.0
        prior_cancel_denominator = 0.0
        recent: list[dict[str, Any]] = []
        for row in ordered:
            completed = int(row.get("completed_flights") or 0)
            delay, late, cancellation = _panel_outcomes(row)
            if (
                prior_completed < MIN_PRIOR_COMPLETED
                or completed < PANEL_MIN_COMPLETED
                or delay is None
                or late is None
                or cancellation is None
            ):
                pass
            else:
                recent_features = recent
                recent_completed = sum(int(item.get("completed_flights") or 0) for item in recent_features)
                recent_late_denominator = recent_completed
                recent_delay_denominator = recent_completed
                recent_cancel_denominator = sum(float(item.get("total_flights") or 0) for item in recent_features)
                recent_late_numerator = sum(float(item["late_rate"]) * int(item.get("completed_flights") or 0) for item in recent_features if item.get("late_rate") is not None)
                recent_delay_numerator = sum(float(item["delay_rate"]) * int(item.get("completed_flights") or 0) for item in recent_features if item.get("delay_rate") is not None)
                recent_cancel_numerator = sum(float(item["cancel_rate"]) * float(item.get("total_flights") or 0) for item in recent_features if item.get("cancel_rate") is not None)
                _, month = _period_parts(str(row["period"]))
                angle = 2.0 * np.pi * (month - 1) / 12.0
                distance = float(row.get("distance_miles") or 0.0)
                traffic_period = row.get("traffic_period")
                traffic_staleness = (
                    max(_period_index(str(row["period"])) - _period_index(str(traffic_period)), 0)
                    if traffic_period
                    else 0
                )
                features = [
                    prior_late_numerator / prior_completed if prior_completed else 0.0,
                    prior_delay_numerator / prior_completed if prior_completed else 0.0,
                    prior_cancel_numerator / prior_cancel_denominator if prior_cancel_denominator else 0.0,
                    recent_late_numerator / recent_late_denominator if recent_late_denominator else 0.0,
                    recent_delay_numerator / recent_delay_denominator if recent_delay_denominator else 0.0,
                    recent_cancel_numerator / recent_cancel_denominator if recent_cancel_denominator else 0.0,
                    float(row.get("traffic_load_factor") or 0.0),
                    float(np.log1p(max(float(row.get("traffic_passengers") or 0.0), 0.0))),
                    float(np.log1p(max(float(row.get("traffic_seats_available") or 0.0), 0.0))),
                    float(row.get("traffic_completion_rate") or 0.0),
                    1.0 if traffic_period else 0.0,
                    float(traffic_staleness),
                    float(np.log1p(max(distance, 0.0))),
                    float(np.sin(angle)),
                    float(np.cos(angle)),
                    float(np.log1p(max(prior_completed, 0))),
                ]
                examples.append({
                    "route": f"{row['origin']}→{row['dest']}",
                    "period": str(row["period"]),
                    "features": features,
                    "targets": {
                        "delay_minutes": delay,
                        "late_rate": late,
                        "cancellation_rate": cancellation,
                    },
                    "baseline": {
                        "delay_minutes": features[1],
                        "late_rate": features[0],
                        "cancellation_rate": features[2],
                    },
                    "weight": float(max(completed, 1)),
                })

            # Add the current month only after its prediction row has been
            # built. This is the panel equivalent of an expanding time split.
            if completed > 0:
                if late is not None:
                    prior_late_numerator += float(late) * completed
                if delay is not None:
                    prior_delay_numerator += float(delay) * completed
                prior_completed += completed
                recent.append({
                    **row,
                    "delay_rate": delay,
                    "late_rate": late,
                    "cancel_rate": cancellation,
                })
                recent = recent[-3:]
            if cancellation is not None and float(row.get("total_flights") or 0) > 0:
                prior_cancel_numerator += float(cancellation) * float(row["total_flights"])
                prior_cancel_denominator += float(row["total_flights"])
    return examples


def _query_route_panel(
    connection: Any,
    *,
    target_period: str,
) -> list[dict[str, Any]]:
    from api.analytics import table_exists

    if not table_exists(connection, PANEL_TABLE):
        return []
    has_t100 = table_exists(connection, "bts_t100_segment_route_month")
    if has_t100:
        rows = connection.execute(
            f"""
            WITH traffic AS (
                SELECT
                    Origin AS origin,
                    Dest AS dest,
                    make_date(CAST(Year AS INTEGER), CAST(Month AS INTEGER), 1) AS period_date,
                    SUM(COALESCE(seats_available, 0)) AS seats_available,
                    SUM(COALESCE(passengers, 0)) AS passengers,
                    SUM(COALESCE(departures_scheduled, 0)) AS departures_scheduled,
                    SUM(COALESCE(departures_performed, 0)) AS departures_performed,
                    SUM(COALESCE(passengers, 0)) / NULLIF(SUM(COALESCE(seats_available, 0)), 0) AS load_factor,
                    SUM(COALESCE(departures_performed, 0)) / NULLIF(SUM(COALESCE(departures_scheduled, 0)), 0) AS completion_rate
                FROM bts_t100_segment_route_month
                GROUP BY Origin, Dest, Year, Month
            ), route_panel AS (
                SELECT
                    origin,
                    dest,
                    year_month AS period,
                    make_date(
                        CAST(left(CAST(year_month AS VARCHAR), 4) AS INTEGER),
                        CAST(right(CAST(year_month AS VARCHAR), 2) AS INTEGER),
                        1
                    ) AS period_date,
                    total_flights,
                    completed_flights,
                    on_time_rate,
                    avg_arrival_delay_minutes,
                    cancellation_rate,
                    distance_miles
                FROM {PANEL_TABLE}
                WHERE year_month < ?
            )
            SELECT
                r.origin,
                r.dest,
                r.period,
                r.total_flights,
                r.completed_flights,
                r.on_time_rate,
                r.avg_arrival_delay_minutes,
                r.cancellation_rate,
                r.distance_miles,
                strftime(t.period_date, '%Y-%m') AS traffic_period,
                t.seats_available AS traffic_seats_available,
                t.passengers AS traffic_passengers,
                t.load_factor AS traffic_load_factor,
                t.completion_rate AS traffic_completion_rate
            FROM route_panel r
            ASOF LEFT JOIN traffic t
              ON r.origin = t.origin
             AND r.dest = t.dest
             AND t.period_date < r.period_date
            ORDER BY r.origin, r.dest, r.period_date
            """,
            [target_period],
        ).fetchall()
    else:
        rows = connection.execute(
            f"""
            SELECT
                origin,
                dest,
                year_month AS period,
                total_flights,
                completed_flights,
                on_time_rate,
                avg_arrival_delay_minutes,
                cancellation_rate,
                distance_miles,
                NULL AS traffic_period,
                NULL AS traffic_seats_available,
                NULL AS traffic_passengers,
                NULL AS traffic_load_factor,
                NULL AS traffic_completion_rate
            FROM {PANEL_TABLE}
            WHERE year_month < ?
            ORDER BY origin, dest, year_month
            """,
            [target_period],
        ).fetchall()
    keys = (
        "origin", "dest", "period", "total_flights", "completed_flights",
        "on_time_rate", "avg_arrival_delay_minutes", "cancellation_rate", "distance_miles",
        "traffic_period", "traffic_seats_available", "traffic_passengers",
        "traffic_load_factor", "traffic_completion_rate",
    )
    return [dict(zip(keys, row)) for row in rows]


def _split_panel_examples(
    examples: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    periods = sorted({str(row["period"]) for row in examples})
    train_end = periods[int(len(periods) * 0.6)]
    validation_end = periods[int(len(periods) * 0.8)]
    train = [row for row in examples if row["period"] <= train_end]
    validation = [row for row in examples if train_end < row["period"] <= validation_end]
    test = [row for row in examples if row["period"] > validation_end]
    if min(len(train), len(validation), len(test)) < MIN_SPLIT_EXAMPLES:
        raise ValueError("The route panel is too thin for a chronological train/validation/test split.")
    return train, validation, test, {
        "train_end": train_end,
        "validation_end": validation_end,
        "train_examples": len(train),
        "validation_examples": len(validation),
        "test_examples": len(test),
    }


def _load_or_train_panel(
    connection: Any,
    *,
    target_period: str,
) -> dict[str, Any]:
    """Load one cached panel fit or build it once for this target month."""
    now = time.monotonic()
    with _PANEL_CACHE_LOCK:
        cached = _PANEL_CACHE.get(target_period)
        if cached is not None and now - cached[0] < PANEL_CACHE_TTL_SECONDS:
            return cached[1]

    panel_rows = _query_route_panel(connection, target_period=target_period)
    if not panel_rows:
        result = {"error": "The materialized route-month panel is unavailable or empty."}
    else:
        examples = build_supervised_panel_examples(panel_rows)
        if len(examples) < PANEL_MIN_TRAINING_EXAMPLES:
            result = {
                "error": "The network route panel does not contain enough eligible route-month examples for an honest ML evaluation.",
                "panel_rows": panel_rows,
                "examples": examples,
            }
        else:
            try:
                train, validation, test, split = _split_panel_examples(examples)
            except ValueError as exc:
                result = {
                    "error": str(exc),
                    "panel_rows": panel_rows,
                    "examples": examples,
                }
            else:
                evaluation_fit = _fit_models(train)
                test_predictions = _predict_models(evaluation_fit, test)
                no_t100_fit = _fit_models(train, feature_indices=PANEL_NO_T100_FEATURE_INDICES)
                no_t100_predictions = _predict_models(no_t100_fit, test)
                with_t100_metrics = _metric_summary(test, test_predictions)
                without_t100_metrics = _metric_summary(test, no_t100_predictions)
                result = {
                    "panel_rows": panel_rows,
                    "examples": examples,
                    "production_fit": _fit_models(examples),
                    "split": split,
                    "test_metrics": with_t100_metrics,
                    "baseline_test_metrics": _metric_summary(test, _baseline_predictions(test)),
                    "t100_ablation": {
                        "with_t100_test_metrics": with_t100_metrics,
                        "without_t100_test_metrics": without_t100_metrics,
                        "with_t100_features": list(PANEL_FEATURE_NAMES),
                        "without_t100_features": list(PANEL_NO_T100_FEATURE_NAMES),
                        "improved_targets": [
                            target
                            for target in ("delay_minutes", "late_rate", "cancellation_rate")
                            if with_t100_metrics.get(f"{target}_mae") is not None
                            and without_t100_metrics.get(f"{target}_mae") is not None
                            and with_t100_metrics[f"{target}_mae"] < without_t100_metrics[f"{target}_mae"]
                        ],
                        "note": (
                            "This is a held-out feature ablation: both models use the same chronological split, "
                            "but the second model removes lagged T-100 traffic inputs. A lower error with T-100 "
                            "supports predictive usefulness in this snapshot; it does not establish causation."
                        ),
                    },
                }

    with _PANEL_CACHE_LOCK:
        _PANEL_CACHE[target_period] = (now, result)
    return result


def build_route_panel_ml_forecast(
    connection: Any,
    *,
    origin: str,
    dest: str,
    target_month: str | None = None,
) -> dict[str, Any]:
    """Train on many routes, then score one selected route."""
    origin = origin.upper()
    dest = dest.upper()
    from api.analytics import table_exists

    if not table_exists(connection, PANEL_TABLE):
        raise LookupError("The materialized route-month analytical table is not available.")
    latest_row = connection.execute(
        f"SELECT MAX(year_month) FROM {PANEL_TABLE}"
    ).fetchone()
    if not latest_row or latest_row[0] is None:
        raise LookupError("The route-month analytical table is not available.")
    latest_period = str(latest_row[0])[:7]
    latest_date = date.fromisoformat(f"{latest_period}-01")
    target_start = parse_target_month(target_month, latest_date)
    target_period = target_start.strftime("%Y-%m")

    panel = _load_or_train_panel(connection, target_period=target_period)
    panel_rows = panel.get("panel_rows", [])
    examples = panel.get("examples", [])
    route_rows = [
        row for row in panel_rows
        if str(row["origin"]).upper() == origin and str(row["dest"]).upper() == dest
    ]
    if not route_rows:
        raise LookupError(f"No route-month history for {origin} → {dest} before {target_period}.")
    if "error" in panel or len(examples) < PANEL_MIN_TRAINING_EXAMPLES:
        return {
            "status": "insufficient_history",
            "origin": origin,
            "dest": dest,
            "target_period": target_period,
            "model": "route_panel_ridge_ml",
            "training_examples": len(examples),
            "minimum_examples": PANEL_MIN_TRAINING_EXAMPLES,
            "reason": panel.get("error", "The network route panel is too thin."),
        }

    split = panel["split"]
    test_metrics = panel["test_metrics"]
    baseline_test_metrics = panel["baseline_test_metrics"]
    production_fit = panel["production_fit"]

    target_context = dict(route_rows[-1])
    target_traffic_rows, _ = load_t100_route_context(
        connection,
        origin=origin,
        dest=dest,
        carrier=None,
        target_period=target_period,
    )
    if target_traffic_rows:
        latest_traffic = target_traffic_rows[-1]
        target_context.update({
            "traffic_period": latest_traffic["period"],
            "traffic_seats_available": latest_traffic["seats_available"],
            "traffic_passengers": latest_traffic["passengers"],
            "traffic_load_factor": latest_traffic["load_factor"],
            "traffic_completion_rate": latest_traffic["completion_rate"],
        })
    target_features = build_panel_feature_vector(route_rows, target_context, period=target_period)
    target_values = production_fit["standardizer"].transform(np.asarray([target_features], dtype=float))
    predictions = {
        target: float(production_fit["models"][target].predict(target_values)[0])
        for target in ("delay_minutes", "late_rate", "cancellation_rate")
    }
    predictions["delay_minutes"] = max(predictions["delay_minutes"], 0.0)
    predictions["late_rate"] = min(max(predictions["late_rate"], 0.0), 1.0)
    predictions["cancellation_rate"] = min(max(predictions["cancellation_rate"], 0.0), 1.0)

    return {
        "status": "candidate",
        "origin": origin,
        "dest": dest,
        "target_period": target_period,
        "target_is_future": target_start > latest_date,
        "matched_scope": "network route panel",
        "model": "route_panel_ridge_ml",
        "training_start": min(str(row["period"]) for row in examples),
        "training_through": max(str(row["period"]) for row in examples),
        "training_cutoff": target_start.isoformat(),
        "training_examples": len(examples),
        "routes_in_training_panel": len({row["route"] for row in examples}),
        "route_history_months": len(route_rows),
        "split": split,
        "predictions": {
            "expected_arrival_delay_minutes": round(predictions["delay_minutes"], 3),
            "late_probability": round(predictions["late_rate"], 5),
            "cancellation_probability": round(predictions["cancellation_rate"], 5),
        },
        "test_metrics": test_metrics,
        "baseline_test_metrics": baseline_test_metrics,
        "t100_ablation": panel.get("t100_ablation"),
        "model_selection": {
            "improved_targets": [
                target for target in ("delay_minutes", "late_rate", "cancellation_rate")
                if test_metrics.get(f"{target}_mae") is not None
                and test_metrics[f"{target}_mae"] < baseline_test_metrics.get(f"{target}_mae", float("inf"))
            ],
            "note": "The panel model is a researcher candidate. It is not promoted to the public answer unless it beats the transparent baseline on future held-out months.",
        },
        "coefficients": _coefficient_records(production_fit["models"], PANEL_FEATURE_NAMES),
        "features_for_target": {
            name: round(float(value), 5) for name, value in zip(PANEL_FEATURE_NAMES, target_features)
        },
        "interpretation": "This model learns from many historical route-months, then estimates the selected route from its prior route history, recent movement, distance, and calendar seasonality. It does not use the selected airline or departure hour, and it is not a causal claim.",
    }
