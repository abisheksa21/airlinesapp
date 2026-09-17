"""
Decision Center D: Predictive Risk Screen.

Adapted from a reference implementation's predictive_operational_risk.py --
verified line-by-line against synthetic data with known ground truth before
being adapted here (see /mnt/user-data/outputs/verify_predictive_risk_model.py
for the same test, runnable standalone). That verification confirmed the
model correctly recovers a strong true signal, correctly assigns near-zero
weight to pure noise, calibration bins track observed rates closely, and
PR-AUC clears the random baseline on a held-out test set -- the CODE is
mathematically sound. What it has NOT been verified against is this site's
actual 60M-row warehouse, which this environment has no way to query
(no duckdb, no network) -- that verification is on whoever runs this for
real, same as every other unverified-until-run piece built this session.

Eight features per entity-month, not six. The original six (severe_delay_rate,
cancellation_rate, average_departure_delay, late_aircraft_delay_share,
ground_delay_share, log_flight_volume) were a single current-month snapshot
with no sense of trajectory or calendar -- a real, identified limitation:
the model had no way to know a carrier was improving or declining, or that
some months are historically rougher regardless of recent performance.

Two features added to address that directly:
  trend_severe_delay_rate  -- this month's severe-delay rate minus the
      average of the entity's own prior 3 months. Positive = recently
      getting worse, negative = recently improving.
  seasonal_index            -- this entity's own historical average for
      THIS SAME CALENDAR MONTH (across all prior years), minus its own
      overall average across all months. Positive = this calendar month
      has historically run worse than this entity's typical month.

Both are computed using ONLY that entity's own history strictly before
(trend) or up to and including (seasonal's own-month lookback is strictly
before too) the feature period -- verified with an explicit no-leakage
test before being wired in: altering a LATER month's data provably cannot
change an EARLIER month's trend/seasonal feature values. See
tests/test_predictive_risk_seasonality.py.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from api.db import best_flight_table, open_readonly_connection
from api.metrics import COMPLETED_FLIGHT_SQL, SEVERE_DELAY_SQL

# Training the panel model (query + build examples + fit logistic regression
# + Platt calibration) is the expensive part of a request -- and it's the
# SAME work regardless of which single entity the caller wants scored, since
# the panel is "all entities of this type in this date range." Without
# caching, checking 5 different carriers means 5 full independent retrains
# of the identical 11-carrier panel. Confirmed this matters on a real
# resource-constrained deploy: on Render's Starter tier (0.5 vCPU), this
# endpoint alone took ~24s standalone and intermittently 502'd (Render's own
# proxy timeout) when it followed other requests in quick succession on the
# same instance. TTL is short (the warehouse doesn't change within a
# session, but this isn't meant to serve stale data indefinitely either).
_PANEL_CACHE: dict[tuple, tuple[float, dict]] = {}
_PANEL_CACHE_LOCK = threading.Lock()
PANEL_CACHE_TTL_SECONDS = 600

FEATURE_NAMES = (
    "severe_delay_rate",
    "cancellation_rate",
    "average_departure_delay",
    "late_aircraft_delay_share",
    "ground_delay_share",
    "log_flight_volume",
    "trend_severe_delay_rate",
    "seasonal_index",
)

TREND_LOOKBACK_MONTHS = 3
BASELINE_SMOOTHING = 1.0


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


@dataclass
class Standardizer:
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, values: np.ndarray) -> "Standardizer":
        mean = values.mean(axis=0)
        scale = values.std(axis=0)
        scale = np.where(scale < 1e-9, 1.0, scale)
        return cls(mean=mean, scale=scale)

    def transform(self, values: np.ndarray) -> np.ndarray:
        return (values - self.mean) / self.scale


@dataclass
class LogisticModel:
    coefficients: np.ndarray
    intercept: float

    def decision_function(self, values: np.ndarray) -> np.ndarray:
        return values @ self.coefficients + self.intercept

    def predict_proba(self, values: np.ndarray) -> np.ndarray:
        return _sigmoid(self.decision_function(values))


def fit_logistic_regression(
    values: np.ndarray,
    labels: np.ndarray,
    *,
    learning_rate: float = 0.05,
    iterations: int = 2500,
    l2: float = 0.02,
    positive_weight: float | None = None,
) -> LogisticModel:
    if len(values) != len(labels) or len(values) < 4:
        raise ValueError("At least four aligned training examples are required.")
    if len(np.unique(labels)) < 2:
        raise ValueError("Training labels must contain both risk classes.")
    coefficients = np.zeros(values.shape[1], dtype=float)
    intercept = 0.0
    if positive_weight is None:
        positives = max(float(labels.sum()), 1.0)
        negatives = max(float(len(labels) - labels.sum()), 1.0)
        positive_weight = negatives / positives
    sample_weight = np.where(labels == 1, positive_weight, 1.0)
    normalizer = float(sample_weight.sum())
    for _ in range(iterations):
        probabilities = _sigmoid(values @ coefficients + intercept)
        error = (probabilities - labels) * sample_weight
        gradient = values.T @ error / normalizer + l2 * coefficients
        intercept_gradient = float(error.sum() / normalizer)
        coefficients -= learning_rate * gradient
        intercept -= learning_rate * intercept_gradient
    return LogisticModel(coefficients=coefficients, intercept=intercept)


def fit_platt_calibrator(scores: np.ndarray, labels: np.ndarray) -> tuple[LogisticModel, bool]:
    """Platt scaling: fit a second, 1-feature logistic regression of the
    label on the first model's raw decision score, on a set the first
    model never trained on. This is what actually makes predict_proba's
    output trustworthy as a probability, not just a monotonic risk rank.

    Returns (model, calibrated). calibrated is False when there wasn't
    enough validation data (or only one label class present) to fit a
    real calibrator -- the returned model is then an identity passthrough
    (raw sigmoid of the base model's score, uncalibrated). Callers should
    surface calibrated=False rather than silently presenting an
    uncalibrated probability as if it had been calibrated."""
    values = np.asarray(scores, dtype=float).reshape(-1, 1)
    if len(values) < 4 or len(np.unique(labels)) < 2:
        return LogisticModel(coefficients=np.array([1.0]), intercept=0.0), False
    return fit_logistic_regression(values, labels, learning_rate=0.03, iterations=1500, l2=0.01, positive_weight=1.0), True


def _pr_auc(labels: np.ndarray, probabilities: np.ndarray) -> float:
    order = np.argsort(-probabilities)
    sorted_labels = labels[order]
    positives = float(sorted_labels.sum())
    if positives == 0:
        return 0.0
    tp = np.cumsum(sorted_labels)
    fp = np.cumsum(1 - sorted_labels)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / positives
    return float(np.trapezoid(np.r_[1.0, precision], np.r_[0.0, recall]))


def evaluate_probabilities(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    """Includes calibration_bins deliberately -- predicted-vs-observed risk
    rate per probability band is the actual test of whether this model's
    confidence means anything, not just whether it ranks cases correctly."""
    clipped = np.clip(probabilities, 1e-9, 1 - 1e-9)
    brier = float(np.mean((clipped - labels) ** 2))
    log_loss = float(-np.mean(labels * np.log(clipped) + (1 - labels) * np.log(1 - clipped)))
    bins: list[dict[str, Any]] = []
    for lower in np.linspace(0.0, 0.8, 5):
        upper = lower + 0.2
        mask = (clipped >= lower) & (clipped < upper if upper < 1.0 else clipped <= upper)
        if mask.any():
            bins.append({
                "probability_band": f"{lower:.1f}-{upper:.1f}",
                "count": int(mask.sum()),
                "mean_predicted_probability": round(float(clipped[mask].mean()), 4),
                "observed_risk_rate": round(float(labels[mask].mean()), 4),
            })
    return {
        "examples": int(len(labels)),
        "positive_rate": round(float(labels.mean()), 4),
        "brier_score": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "precision_recall_auc": round(_pr_auc(labels, clipped), 6),
        "calibration_bins": bins,
    }


def historical_risk_baseline_probabilities(
    rows: list[dict[str, Any]],
    *,
    known_history: list[dict[str, Any]],
    fallback_probability: float,
) -> np.ndarray:
    """Return an expanding, entity-specific probability baseline.

    For each scored example, the baseline is the smoothed share of that
    entity's earlier labelled months that were risky. If an entity has no
    earlier labelled months, it falls back to the training-panel risk rate.
    The scored rows are then added one at a time, so a later row can learn
    from an earlier observed outcome without seeing its own label in advance.
    """
    prior_labels: dict[str, list[int]] = {}
    for row in sorted(known_history, key=lambda item: (str(item["target_period"]), str(item["entity"]))):
        prior_labels.setdefault(str(row["entity"]), []).append(int(row["label"]))

    predictions = np.zeros(len(rows), dtype=float)
    ordered = sorted(enumerate(rows), key=lambda item: (str(item[1]["target_period"]), str(item[1]["entity"])))
    fallback = min(max(float(fallback_probability), 0.0), 1.0)
    for index, row in ordered:
        labels = prior_labels.get(str(row["entity"]), [])
        if labels:
            predictions[index] = (sum(labels) + BASELINE_SMOOTHING) / (
                len(labels) + 2.0 * BASELINE_SMOOTHING
            )
        else:
            predictions[index] = fallback
        prior_labels.setdefault(str(row["entity"]), []).append(int(row["label"]))
    return predictions


def historical_risk_baseline_probability(
    *,
    entity: str,
    known_history: list[dict[str, Any]],
    fallback_probability: float,
) -> float:
    """Score the next period with the same expanding baseline used in tests."""
    entity_rows = [row for row in known_history if str(row["entity"]).upper() == entity.upper()]
    if not entity_rows:
        return min(max(float(fallback_probability), 0.0), 1.0)
    labels = [int(row["label"]) for row in entity_rows]
    return (sum(labels) + BASELINE_SMOOTHING) / (
        len(labels) + 2.0 * BASELINE_SMOOTHING
    )


def _trend_and_seasonal(series: list[dict[str, Any]], index: int, lookback_months: int = TREND_LOOKBACK_MONTHS) -> tuple[float, float]:
    """series is one entity's OWN monthly rows, sorted chronologically.
    index is the position of the feature row within that series. Both
    features use ONLY series[:index] -- strictly before the current row,
    never the current row itself or anything later. Verified with an
    explicit test that altering series[index+1:] cannot change the
    result, and a second test that altering series[index] itself cannot
    change that row's own seasonal_index (overall_avg used to include the
    current row, which self-referentially coupled seasonal_index to the
    very severe_delay_rate value that's ALSO fed as its own separate
    feature -- fixed by excluding it, matching the trend feature's own
    convention).

    The trend lookback is calendar-distance based (via _period_index),
    not list-position based: minimum_flights filtering upstream can
    silently drop a low-volume month from series, and slicing by list
    position would then silently widen "prior 3 months" past 3 actual
    calendar months with no signal that happened."""
    current = series[index]
    current_rate = float(current.get("severe_delay_rate") or 0.0)
    current_period_index = _period_index(str(current["period"]))

    prior_rows = [
        r for r in series[:index]
        if current_period_index - _period_index(str(r["period"])) <= lookback_months
    ]
    if prior_rows:
        prior_avg = float(np.mean([float(r.get("severe_delay_rate") or 0.0) for r in prior_rows]))
        trend = current_rate - prior_avg
    else:
        trend = 0.0  # no prior history yet for this entity -- neutral, not zero-imputed as if "good"

    current_month_num = str(current["period"])[5:7]
    same_month_prior_years = [
        float(r.get("severe_delay_rate") or 0.0)
        for r in series[:index]
        if str(r["period"])[5:7] == current_month_num
    ]
    if same_month_prior_years:
        overall_avg = float(np.mean([float(r.get("severe_delay_rate") or 0.0) for r in series[:index]]))
        seasonal_index = float(np.mean(same_month_prior_years)) - overall_avg
    else:
        seasonal_index = 0.0  # this calendar month never seen before for this entity -- neutral

    return trend, seasonal_index


def build_supervised_examples(
    rows: list[dict[str, Any]],
    *,
    risk_quantile: float = 0.75,
    train_fraction: float = 0.6,
) -> tuple[list[dict[str, Any]], float, str]:
    """Each example: features from entity's month N, label = whether that
    same entity's month N+1 severe_delay_rate exceeded a risk threshold.
    Only CONSECUTIVE month pairs for the same entity are used -- a gap
    (missing month) breaks the pair rather than silently spanning it.

    The risk threshold is a quantile of next-period severe_delay_rate,
    but computed ONLY from examples whose target_period falls in the
    training portion (the first train_fraction of periods,
    chronologically) -- NOT from the full train+validation+test
    population. Computing it over the full population would let
    validation/test-period outcomes influence what counts as "risky" for
    a TRAINING-period example -- look-ahead bias, since in a real
    deployment nothing after the training cutoff would be known yet. The
    SAME train-derived threshold then labels every split, so labels stay
    consistent across train/validation/test; only how the threshold
    itself gets computed changes.

    Returns (examples, threshold, train_end) -- train_end is returned so
    callers reuse the exact period boundary the threshold was computed
    against, instead of recomputing the same formula separately and
    risking the two copies drifting apart."""
    data = sorted(rows, key=lambda row: (str(row["entity"]), str(row["period"])))
    if not 0.5 <= risk_quantile <= 0.95:
        raise ValueError("risk_quantile must be between 0.50 and 0.95")

    by_entity: dict[str, list[dict[str, Any]]] = {}
    for row in data:
        by_entity.setdefault(str(row["entity"]), []).append(row)

    unlabeled: list[dict[str, Any]] = []
    for entity, series in by_entity.items():
        for idx in range(len(series) - 1):
            current = series[idx]
            following = series[idx + 1]
            if _next_month(current["period"]) != following["period"]:
                continue  # a gap between months -- don't pair across it
            trend, seasonal = _trend_and_seasonal(series, idx)
            features = [
                float(current.get("severe_delay_rate") or 0.0),
                float(current.get("cancellation_rate") or 0.0),
                float(current.get("average_departure_delay") or 0.0),
                float(current.get("late_aircraft_delay_share") or 0.0),
                # taxi time as a fraction of total flight duration, NOT a
                # measure of excess/congestion-caused delay -- it includes
                # ordinary taxi time, which scales inversely with flight
                # distance for entirely benign reasons (a short regional
                # hop has a much higher ratio than a transcon flight).
                # Confounded by each entity's route-length mix; treat as
                # an "operational overhead ratio," not a delay signal.
                float(current.get("ground_delay_share") or 0.0),
                float(np.log(max(float(current.get("flight_volume") or 0.0), 1.0))),
                trend,
                seasonal,
            ]
            unlabeled.append({
                "entity": entity,
                "feature_period": str(current["period"]),
                "target_period": str(following["period"]),
                "features": features,
                "target_severe_delay_rate": float(following.get("severe_delay_rate") or 0.0),
            })

    if not unlabeled:
        raise ValueError("No consecutive entity-period examples are available.")

    periods = sorted({e["target_period"] for e in unlabeled})
    train_end = periods[int(len(periods) * train_fraction)]

    train_target_rates = [e["target_severe_delay_rate"] for e in unlabeled if e["target_period"] <= train_end]
    if not train_target_rates:
        raise ValueError("No training-period examples are available to compute the risk threshold.")
    threshold = float(np.quantile(np.asarray(train_target_rates), risk_quantile))

    for e in unlabeled:
        e["label"] = int(e["target_severe_delay_rate"] >= threshold)

    return unlabeled, threshold, train_end


def _period_index(value: str) -> int:
    year, month = value[:7].split("-")
    return int(year) * 12 + int(month) - 1


def _next_month(value: str) -> str:
    index = _period_index(value) + 1
    year, zero_based_month = divmod(index, 12)
    return f"{year:04d}-{zero_based_month + 1:02d}"


def train_temporal_risk_model(
    examples: list[dict[str, Any]],
    *,
    train_end: str,
    validation_end: str,
) -> dict[str, Any]:
    train = [row for row in examples if row["target_period"] <= train_end]
    validation = [row for row in examples if train_end < row["target_period"] <= validation_end]
    test = [row for row in examples if row["target_period"] > validation_end]
    if min(len(train), len(validation), len(test)) < 4:
        raise ValueError(
            f"Temporal split too thin (train={len(train)}, validation={len(validation)}, "
            f"test={len(test)}) -- need at least 4 examples in each. Try widening the date range."
        )

    x_train = np.asarray([row["features"] for row in train], dtype=float)
    y_train = np.asarray([row["label"] for row in train], dtype=int)
    standardizer = Standardizer.fit(x_train)
    model = fit_logistic_regression(standardizer.transform(x_train), y_train)

    x_validation = standardizer.transform(np.asarray([row["features"] for row in validation], dtype=float))
    y_validation = np.asarray([row["label"] for row in validation], dtype=int)
    calibrator, calibrated = fit_platt_calibrator(model.decision_function(x_validation), y_validation)

    def score(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
        values = standardizer.transform(np.asarray([row["features"] for row in rows], dtype=float))
        raw_scores = model.decision_function(values)
        probabilities = calibrator.predict_proba(raw_scores.reshape(-1, 1))
        return np.asarray([row["label"] for row in rows], dtype=int), probabilities

    y_val, p_val = score(validation)
    y_test, p_test = score(test)
    fallback_probability = float(y_train.mean())
    baseline_validation = historical_risk_baseline_probabilities(
        validation,
        known_history=train,
        fallback_probability=fallback_probability,
    )
    baseline_test = historical_risk_baseline_probabilities(
        test,
        known_history=[*train, *validation],
        fallback_probability=fallback_probability,
    )

    coefficient_records = [
        {"feature": name, "standardized_coefficient": round(float(value), 6),
         "direction": "higher_risk" if value > 0 else "lower_risk"}
        for name, value in zip(FEATURE_NAMES, model.coefficients)
    ]

    validation_metrics = evaluate_probabilities(y_val, p_val)
    validation_metrics["caveat"] = (
        "The calibrator was fit on this SAME validation set, so these numbers are optimistic -- "
        "they measure how well the calibrator fits its own training data, not genuine held-out "
        "performance. test_metrics below is the fair, uncontaminated estimate."
    )

    return {
        "standardizer": standardizer,
        "model": model,
        "calibrator": calibrator,
        "calibration_status": "fit" if calibrated else "skipped_insufficient_validation_data",
        "split": {
            "train_end": train_end, "validation_end": validation_end,
            "train_examples": len(train), "validation_examples": len(validation), "test_examples": len(test),
        },
        "validation_metrics": validation_metrics,
        "test_metrics": evaluate_probabilities(y_test, p_test),
        "baseline_validation_metrics": evaluate_probabilities(y_val, baseline_validation),
        "baseline_test_metrics": evaluate_probabilities(y_test, baseline_test),
        "baseline_fallback_probability": round(fallback_probability, 6),
        "coefficients": coefficient_records,
    }


def _query_monthly_entity_rows(
    *, start_date: str, end_date: str, entity_type: str, minimum_flights: int
) -> list[dict[str, Any]]:
    if entity_type == "airport":
        entity_sql = "Origin"
    elif entity_type == "carrier":
        entity_sql = "Marketing_Airline_Network"
    else:
        raise ValueError("entity_type must be 'airport' or 'carrier'")

    with open_readonly_connection() as connection:
        source_table = best_flight_table(
            connection,
            {
                "FlightDate", entity_sql, "Cancelled", "Diverted", "ArrDelay", "ArrDel15",
                "DepDelay", "LateAircraftDelay", "TaxiOut", "TaxiIn", "ActualElapsedTime",
            },
        )
        query = f"""
            SELECT
                {entity_sql} AS entity,
                strftime(FlightDate, '%Y-%m') AS period,
                COUNT(*) AS flight_volume,
                AVG(CASE WHEN {SEVERE_DELAY_SQL} THEN 1.0 WHEN {COMPLETED_FLIGHT_SQL} THEN 0.0 END) AS severe_delay_rate,
                AVG(CASE WHEN Cancelled = 1 THEN 1.0 ELSE 0.0 END) AS cancellation_rate,
                AVG(CASE WHEN {COMPLETED_FLIGHT_SQL} THEN DepDelay END) AS average_departure_delay,
                SUM(CASE WHEN {COMPLETED_FLIGHT_SQL} THEN COALESCE(LateAircraftDelay, 0) ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN {COMPLETED_FLIGHT_SQL} THEN GREATEST(COALESCE(ArrDelay, 0), 0) ELSE 0 END), 0) AS late_aircraft_delay_share,
                -- Despite the name, this is taxi time as a fraction of flight
                -- duration, not excess/congestion-caused delay -- see the
                -- caveat where this column feeds build_supervised_examples.
                    AVG(
                        CASE WHEN {COMPLETED_FLIGHT_SQL} AND TaxiOut IS NOT NULL AND TaxiIn IS NOT NULL AND ActualElapsedTime > 0
                         THEN (TaxiOut + TaxiIn) * 1.0 / ActualElapsedTime END
                ) AS ground_delay_share
            FROM {source_table}
            WHERE FlightDate BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
                AND {entity_sql} IS NOT NULL
            GROUP BY entity, period
            HAVING COUNT(*) >= ?
            ORDER BY entity, period
        """
        rows = connection.execute(query, [start_date, end_date, minimum_flights]).fetchall()

    keys = ["entity", "period", "flight_volume", "severe_delay_rate", "cancellation_rate",
            "average_departure_delay", "late_aircraft_delay_share", "ground_delay_share"]
    return [dict(zip(keys, row)) for row in rows]


def _train_panel(
    *, entity_type: str, start_date: str, end_date: str, minimum_flights: int, risk_quantile: float
) -> dict[str, Any]:
    """The expensive, entity-independent part of get_predictive_operational_risk
    (query + build examples + fit + calibrate) -- cached by its own
    parameters so scoring a different entity against the SAME panel doesn't
    redo it. Returns a dict with an "error" key on failure, same convention
    as the public function, so callers don't need a separate exception path."""
    key = (entity_type, start_date, end_date, minimum_flights, risk_quantile)
    now = time.monotonic()
    with _PANEL_CACHE_LOCK:
        cached = _PANEL_CACHE.get(key)
        if cached is not None and now - cached[0] < PANEL_CACHE_TTL_SECONDS:
            return cached[1]

    rows = _query_monthly_entity_rows(
        start_date=start_date, end_date=end_date, entity_type=entity_type, minimum_flights=minimum_flights
    )
    if not rows:
        result = {"error": "No monthly data matched that filter."}
        with _PANEL_CACHE_LOCK:
            _PANEL_CACHE[key] = (now, result)
        return result

    examples, risk_threshold, train_end = build_supervised_examples(rows, risk_quantile=risk_quantile)
    if len(examples) < 12:
        result = {"error": f"Only {len(examples)} entity-month examples available -- need more history to train and evaluate honestly."}
        with _PANEL_CACHE_LOCK:
            _PANEL_CACHE[key] = (now, result)
        return result

    # validation_end only carves up the EVALUATION split -- train_end came
    # back from build_supervised_examples, which already used it to decide
    # which examples' outcomes were allowed to inform the risk threshold.
    periods = sorted({row["target_period"] for row in examples})
    validation_end = periods[int(len(periods) * 0.8)]

    try:
        fit = train_temporal_risk_model(examples, train_end=train_end, validation_end=validation_end)
    except ValueError as exc:
        result = {"error": str(exc)}
        with _PANEL_CACHE_LOCK:
            _PANEL_CACHE[key] = (now, result)
        return result

    result = {"rows": rows, "examples": examples, "fit": fit, "risk_threshold": risk_threshold}
    with _PANEL_CACHE_LOCK:
        _PANEL_CACHE[key] = (now, result)
    return result


def get_predictive_operational_risk(
    *,
    entity_type: str,
    entity: str,
    start_date: str,
    end_date: str,
    minimum_flights: int = 200,
    risk_quantile: float = 0.75,
) -> dict[str, Any]:
    """Trains one model per entity_type (airport or carrier) using ALL
    entities of that type as panel data -- not just the one requested --
    since a single entity's own month-to-month series alone is nowhere
    near enough examples to fit or evaluate a model honestly. The
    requested entity's most recent period is then scored with that
    network-trained model. The panel itself is cached (see _train_panel)
    since it's identical across different entities of the same type/range."""
    panel = _train_panel(
        entity_type=entity_type, start_date=start_date, end_date=end_date,
        minimum_flights=minimum_flights, risk_quantile=risk_quantile,
    )
    if "error" in panel:
        return panel
    rows = panel["rows"]
    fit = panel["fit"]
    risk_threshold = panel["risk_threshold"]

    entity = entity.upper()
    entity_rows = [row for row in rows if str(row["entity"]).upper() == entity]
    if not entity_rows:
        return {"error": f"No data found for {entity_type} {entity}."}
    latest = entity_rows[-1]
    latest_trend, latest_seasonal = _trend_and_seasonal(entity_rows, len(entity_rows) - 1)

    features = np.asarray([[
        float(latest.get("severe_delay_rate") or 0.0),
        float(latest.get("cancellation_rate") or 0.0),
        float(latest.get("average_departure_delay") or 0.0),
        float(latest.get("late_aircraft_delay_share") or 0.0),
        float(latest.get("ground_delay_share") or 0.0),
        float(np.log(max(float(latest.get("flight_volume") or 0.0), 1.0))),
        latest_trend,
        latest_seasonal,
    ]])
    standardizer: Standardizer = fit["standardizer"]
    model: LogisticModel = fit["model"]
    calibrator: LogisticModel = fit["calibrator"]
    raw_score = model.decision_function(standardizer.transform(features))
    probability = float(calibrator.predict_proba(raw_score.reshape(-1, 1))[0])
    known_entity_history = [
        row for row in panel.get("examples", [])
        if str(row["entity"]).upper() == entity and str(row["target_period"]) <= str(latest["period"])
    ]
    baseline_probability = historical_risk_baseline_probability(
        entity=entity,
        known_history=known_entity_history,
        fallback_probability=float(fit["baseline_fallback_probability"]),
    )

    # These cutoffs are calibrated for risk_quantile=0.75, the only value
    # this endpoint currently uses (risk_quantile isn't exposed as a query
    # param in api/main.py's predictive_risk_endpoint). If that ever
    # changes, these bands need to move with it -- they don't derive from
    # risk_quantile automatically.
    band = "high" if probability >= 0.6 else "elevated" if probability >= 0.4 else "watch" if probability >= 0.25 else "low"

    return {
        "entity_type": entity_type,
        "entity": entity,
        "as_of_period": latest["period"],
        "risk_probability": round(probability, 4),
        "risk_band": band,
        "math_baseline_probability": round(baseline_probability, 4),
        "math_baseline_band": "high" if baseline_probability >= 0.6 else "elevated" if baseline_probability >= 0.4 else "watch" if baseline_probability >= 0.25 else "low",
        "math_baseline_definition": (
            "Laplace-smoothed share of this entity's earlier labelled months that were in the network's risky quartile; "
            "if there is no earlier label, the training-panel risk rate is used."
        ),
        "risk_threshold_definition": (
            f"Trained to predict whether next month's severe-delay rate (ArrDelay >= 60 min, "
            f"not cancelled/diverted) would land in the network's top {(1 - risk_quantile) * 100:.0f}% "
            f"(>= {risk_threshold:.1%})."
        ),
        "current_features": {
            "severe_delay_rate": latest["severe_delay_rate"],
            "cancellation_rate": latest["cancellation_rate"],
            "average_departure_delay": latest["average_departure_delay"],
            "late_aircraft_delay_share": latest["late_aircraft_delay_share"],
            "ground_delay_share": latest["ground_delay_share"],
            "flight_volume": latest["flight_volume"],
            "trend_severe_delay_rate": round(latest_trend, 4),
            "seasonal_index": round(latest_seasonal, 4),
        },
        "model_coefficients": fit["coefficients"],
        "calibration_status": fit["calibration_status"],
        "split": fit["split"],
        "validation_metrics": fit["validation_metrics"],
        "test_metrics": fit["test_metrics"],
        "baseline_validation_metrics": fit["baseline_validation_metrics"],
        "baseline_test_metrics": fit["baseline_test_metrics"],
        "model_selection": {
            "ml_better_on": [
                metric for metric in ("brier_score", "log_loss")
                if fit["test_metrics"][metric] < fit["baseline_test_metrics"][metric]
            ],
            "note": "The ML probability remains a researcher estimate unless it improves held-out probability quality against the transparent historical baseline.",
        },
        "entities_in_training_panel": len({row["entity"] for row in rows}),
    }
