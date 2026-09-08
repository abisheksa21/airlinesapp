from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Optional
import hashlib
import json
import os
import threading

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from api.rate_limit import rate_limit_copilot

from api.copilot import ask_copilot, CopilotError
from api.copilot import stream_copilot
from api.copilot import get_summary as copilot_get_summary
from api.copilot import get_trend as copilot_get_trend
from api.copilot import compare_carriers as copilot_compare_carriers
from api.copilot import get_delay_causes as copilot_get_delay_causes
from api.db import database_path, open_readonly_connection
from config import DEFAULT_HEAVY_LOOKBACK_DAYS, DEFAULT_MODEL_LOOKBACK_DAYS, PIPELINE_STATE_FILE
from api.metrics import COMPLETED_FLIGHT_SQL, ON_TIME_FLAG_SQL
from api.analytics import airport_list, airport_ranking, carrier_ranking, network_summary, network_trend, route_hour_baseline, route_ranking
from api import predictive_risk
from api.health_score import compute_health_score, score_from_row, RAW_STAT_SELECT_EXPRS
from api.delay_propagation_markov import get_delay_propagation_markov, STATES as MARKOV_STATES
from api.network_graph import compute_network_resilience
from api.queue_pressure import get_queue_pressure
from api.schedule_padding_trend import get_schedule_padding_trend
from api.optimization.backend import PublicBackend
from api.optimization.departure_bank import BankFlight, solve_departure_bank
from api.optimization.network_protection import InterventionCandidate, solve_portfolio
from api.schemas import ChatRequest
from api.security import require_pipeline_admin

app = FastAPI(title="Airline OTP API")

# Comma-separated list of allowed frontend origins, e.g.
# "https://my-app.vercel.app,https://my-app-git-preview.vercel.app"
# Defaults to local dev only -- a deployed backend MUST set this env var to
# its real frontend domain(s), or the deployed frontend simply can't call it.
_cors_origins_raw = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in _cors_origins_raw.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Guards against triggering /api/admin/check-for-updates twice at once --
# pipeline/auto_update.py drives a real headless Chrome session and writes
# to the warehouse file, so two overlapping runs could genuinely corrupt
# things, not just waste time. Single boolean is enough since this is a
# single-process local dev server, not a multi-worker deployment.
_update_check_lock = threading.Lock()
_update_check_running = False


def _run_auto_update_in_background():
    global _update_check_running
    try:
        # Imported here, not at module load time, so a Selenium/webdriver
        # import problem doesn't take down the whole API on startup --
        # it only matters if someone actually triggers a check.
        from pipeline import auto_update
        auto_update.main()
    except Exception:
        # auto_update.main() already logs its own errors in detail to
        # Logs/auto_update_*.log and pipeline_state.json -- this bare
        # except is just to guarantee the lock always gets released, not
        # to swallow the error silently.
        pass
    finally:
        _update_check_running = False


@app.post("/api/admin/check-for-updates", dependencies=[Depends(require_pipeline_admin)])
def check_for_updates():
    """Manually triggers pipeline/auto_update.py in a background thread --
    non-blocking, so the request returns immediately rather than tying up
    the connection for however long the check takes. Poll /api/data-health
    afterward (last_automated_check) to see the result once it finishes."""
    global _update_check_running
    with _update_check_lock:
        if _update_check_running:
            return {"status": "already_running"}
        _update_check_running = True

    thread = threading.Thread(target=_run_auto_update_in_background, daemon=True)
    thread.start()
    return {"status": "started"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Decision Center v1: for a given carrier, shows which Health Score
# component has the most room to improve relative to peer carriers, and
# exactly how many points the overall score would gain if that one
# component moved to the network median -- holding everything else
# constant. Deliberately scoped to pure arithmetic on the health score's
# OWN already-calibrated weights, not a new predictive model: "if X moved
# to the peer median, the overall score would be Y" is a fact about the
# scoring formula (health_score = sum of component_score * weight), not a
# claim about what would actually happen if a carrier changed anything.
# Says nothing about how easy or hard a given component is to actually
# move -- that's a real, separate question this doesn't answer.
_HEALTH_SCORE_WEIGHTS = {
    "reliability": 0.290,
    "delay_severity": 0.251,
    "severe_delay_exposure": 0.275,
    "cancellation_resilience": 0.125,
    "diversion_resilience": 0.059,
}


@app.get("/api/decision/health-improvement")
def health_improvement_endpoint(carrier: str = Query(...)):
    import statistics

    carrier = carrier.upper()

    entity_health = compute_health_score("Marketing_Airline_Network = ?", [carrier])
    if entity_health is None:
        raise HTTPException(status_code=404, detail="No flights found for that carrier.")

    with open_readonly_connection() as connection:
        all_carriers = [
            r[0]
            for r in connection.execute(
                "SELECT DISTINCT Marketing_Airline_Network FROM flights WHERE Marketing_Airline_Network IS NOT NULL"
            ).fetchall()
        ]

    peer_component_scores: dict[str, list[float]] = {c: [] for c in _HEALTH_SCORE_WEIGHTS}
    for code in all_carriers:
        h = compute_health_score("Marketing_Airline_Network = ?", [code])
        if h is None:
            continue
        for component in _HEALTH_SCORE_WEIGHTS:
            peer_component_scores[component].append(h["component_scores"][component])

    medians = {
        component: statistics.median(values) if values else None
        for component, values in peer_component_scores.items()
    }

    levers = []
    for component, weight in _HEALTH_SCORE_WEIGHTS.items():
        current_value = entity_health["component_scores"][component]
        median_value = medians[component]
        if median_value is None:
            continue
        hypothetical_score = round(
            entity_health["score"] - (current_value * weight) + (median_value * weight), 2
        )
        levers.append({
            "component": component,
            "current_value": current_value,
            "network_median": round(median_value, 2),
            "weight": weight,
            "hypothetical_score_if_at_median": hypothetical_score,
            "point_gain": round(hypothetical_score - entity_health["score"], 2),
        })

    levers.sort(key=lambda l: l["point_gain"], reverse=True)

    return {
        "carrier": carrier,
        "current_score": entity_health["score"],
        "current_rating": entity_health["rating"],
        "peer_count": len(all_carriers),
        "levers": levers,
    }


@app.get("/api/decision/opportunity-ranking")
def opportunity_ranking_endpoint():
    """Decision Center C: unlike A and B, which require picking a carrier
    first, this surfaces where to look in the first place -- every
    carrier's single biggest Health Score lever, ranked network-wide.
    Reuses the exact same swap-one-component-to-median arithmetic as
    /api/decision/health-improvement, computed once for all 11 carriers
    (not 11 separate calls each re-deriving peer medians from scratch).

    Deliberately does NOT collapse point_gain and total_flights into one
    composite "priority score" -- multiplying a 0-100-scale arithmetic gain
    by a flight count would look like a rigorously-derived priority number
    when it's really just two different real facts being multiplied
    together. Both are shown as separate columns; the frontend's synthesis
    is limited to stating the relationship between them in plain language,
    not inventing a fake single ranking metric."""
    import statistics

    with open_readonly_connection() as connection:
        all_carriers = [
            r[0]
            for r in connection.execute(
                "SELECT DISTINCT Marketing_Airline_Network FROM flights WHERE Marketing_Airline_Network IS NOT NULL"
            ).fetchall()
        ]

    carrier_health: dict[str, dict] = {}
    for code in all_carriers:
        h = compute_health_score("Marketing_Airline_Network = ?", [code])
        if h is not None:
            carrier_health[code] = h

    peer_component_scores: dict[str, list[float]] = {c: [] for c in _HEALTH_SCORE_WEIGHTS}
    for h in carrier_health.values():
        for component in _HEALTH_SCORE_WEIGHTS:
            peer_component_scores[component].append(h["component_scores"][component])
    medians = {
        component: statistics.median(values) if values else None
        for component, values in peer_component_scores.items()
    }

    entries = []
    for code, h in carrier_health.items():
        best_component = None
        best_gain = None
        best_median = None
        best_current = None
        for component, weight in _HEALTH_SCORE_WEIGHTS.items():
            median_value = medians[component]
            if median_value is None:
                continue
            current_value = h["component_scores"][component]
            hypothetical = h["score"] - (current_value * weight) + (median_value * weight)
            gain = round(hypothetical - h["score"], 2)
            if best_gain is None or gain > best_gain:
                best_gain = gain
                best_component = component
                best_median = round(median_value, 2)
                best_current = current_value

        entries.append({
            "carrier": code,
            "current_score": h["score"],
            "current_rating": h["rating"],
            "total_flights": h["sample"]["total_flights"],
            "top_lever_component": best_component,
            "top_lever_current_value": best_current,
            "top_lever_network_median": best_median,
            "top_lever_point_gain": best_gain,
        })

    entries.sort(key=lambda e: e["top_lever_point_gain"] or 0, reverse=True)

    return {"peer_count": len(entries), "carriers": entries}


@app.get("/api/decision/network-protection-portfolio")
def network_protection_portfolio_endpoint(
    candidate_type: str = Query("carrier", description="'carrier' or 'airport'"),
    budget: float = Query(3.0, ge=0, description="Available intervention-resource budget"),
    primary_metric: str = Query(
        "severe_delay_exposure",
        description="Which REAL, disclosed metric to optimize against -- never a blended composite",
    ),
    airport_candidate_limit: int = Query(30, ge=1, le=200, description="Airports are pre-filtered to the top N by volume before scoring, to keep this interactive"),
    cost_model: str = Query(
        "unit",
        pattern="^(unit|flight_volume_millions|sqrt_flight_volume)$",
        description="How intervention cost is estimated: unit, flight-volume exposure, or square-root volume proxy",
    ),
    cost_scale: float = Query(1.0, gt=0, description="Positive multiplier applied to the selected cost model"),
):
    """OR Feature 2: given a limited number of interventions, where should
    they go? Optimizes against exactly ONE real metric the caller chooses
    -- total_flights_millions or a Health Score component -- and reports every other
    component for the resulting portfolio too, so nothing is hidden inside
    an invented priority score. See api/optimization/network_protection.py
    for the full methodology, including how marginal_gain is computed (a
    real re-solve with each selected candidate forced out, not an
    approximation)."""
    if candidate_type not in ("carrier", "airport"):
        raise HTTPException(status_code=400, detail="candidate_type must be 'carrier' or 'airport'")
    if primary_metric not in {"total_flights_millions", *_HEALTH_SCORE_WEIGHTS.keys()}:
        raise HTTPException(
            status_code=400,
            detail=f"primary_metric must be one of: total_flights_millions, {', '.join(_HEALTH_SCORE_WEIGHTS.keys())}",
        )
    entity_col = "Marketing_Airline_Network" if candidate_type == "carrier" else "Origin"

    # One grouped scan over the whole table computes every candidate's raw
    # stats at once. This used to loop compute_health_score() once per
    # candidate, each issuing its OWN full sequential scan over all 60.7M
    # rows -- 11 scans for carriers, 30+1 for airports (the pre-filter was
    # ALSO a separate full scan). That N-times-repeated full-table scan,
    # not the MILP solve, is what made this endpoint appear to hang: it's
    # I/O-bound work multiplied by candidate count, not a slow solver --
    # confirmed by profiling (CPU near-idle while the request was pending).
    group_query = f"""
        SELECT {entity_col} AS entity, {RAW_STAT_SELECT_EXPRS}
        FROM flights
        WHERE {entity_col} IS NOT NULL
        GROUP BY {entity_col}
    """
    if candidate_type == "airport":
        # Airports: hundreds of distinct values -- keep the busiest-N
        # pre-filter, but as an ORDER BY/LIMIT on this SAME grouped scan
        # rather than a second full-table-scan query beforehand.
        group_query += " ORDER BY total_flights DESC LIMIT ?"
        group_params = [airport_candidate_limit]
    else:
        group_params = []

    with open_readonly_connection() as connection:
        group_rows = connection.execute(group_query, group_params).fetchall()

    candidates: list[InterventionCandidate] = []
    for row in group_rows:
        code = row[0]
        h = score_from_row(row[1:])
        if h is None:
            continue
        components = dict(h["component_scores"])  # reliability, delay_severity, severe_delay_exposure, cancellation_resilience, diversion_resilience -- all real, all disclosed
        components["total_flights_millions"] = round(h["sample"]["total_flights"] / 1_000_000, 3)
        flight_volume_millions = components["total_flights_millions"]
        if cost_model == "unit":
            intervention_cost = 1.0
        elif cost_model == "flight_volume_millions":
            intervention_cost = max(0.1, flight_volume_millions)
        else:
            intervention_cost = max(0.1, flight_volume_millions ** 0.5)
        candidates.append(InterventionCandidate(
            candidate_id=code,
            candidate_type=candidate_type,
            cost=round(intervention_cost * cost_scale, 3),
            components=components,
        ))

    # For resilience/reliability-style components, a LOWER score is worse
    # (more real risk) -- the optimizer maximizes primary_metric, so invert
    # these so "select the worst-scoring candidates" is what actually gets
    # selected, matching the intuitive meaning of "where's the exposure."
    inverted_metric_used = False
    if primary_metric in _HEALTH_SCORE_WEIGHTS:
        inverted_metric_used = True
        for c in candidates:
            c.components[primary_metric] = round(100.0 - c.components[primary_metric], 3)

    result = solve_portfolio(candidates, budget=budget, primary_metric=primary_metric, backend=PublicBackend())

    return {
        "candidate_type": candidate_type,
        "primary_metric": primary_metric,
        "primary_metric_note": (
            "Health Score components were inverted (100 - score) before optimizing, so a HIGHER "
            "value here means MORE exposure/risk on that dimension -- matching 'where should "
            "intervention go', not 'who already scores best'."
            if inverted_metric_used else None
        ),
        "budget": budget,
        "cost_model": cost_model,
        "cost_scale": cost_scale,
        "status": result.status,
        "selected": result.selected,
        "rejected": result.rejected,
        "resource_consumed": result.resource_consumed,
        "total_coverage": result.total_coverage,
        "residual_exposure": result.residual_exposure,
        "methodology": result.methodology,
    }


@app.get("/api/decision/network-resilience")
def network_resilience_endpoint(
    minimum_flights: int = Query(50, ge=1, description="Routes below this total-flight floor are excluded from the graph entirely"),
    top_n: int = Query(15, ge=1, le=50),
):
    """OR Feature: which airports are structural bridges in the route
    network, vs. which are just high-volume hubs -- a genuinely new
    capability (this project had zero graph modeling anywhere before this).
    Builds a real directed graph (airports as nodes, routes as edges) from
    the whole network and reports degree centrality (raw connection count
    and traffic volume) and betweenness centrality (fraction of shortest
    paths between OTHER airport pairs passing through this one) SEPARATELY
    -- never blended into one score, matching this project's own Health
    Score / Network Protection Portfolio discipline. Betweenness in
    particular can surface airports that matter structurally despite modest
    traffic volume -- see api/network_graph.py for the full methodology and
    tests/test_network_graph.py for verification against synthetic graphs
    with a mathematically known correct answer."""
    result = compute_network_resilience(minimum_flights=minimum_flights, top_n=top_n)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/decision/predictive-risk")
def predictive_risk_endpoint(
    entity_type: str = Query(..., description="'airport' or 'carrier'"),
    entity: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    minimum_flights: int = Query(200, description="Minimum flights for an entity-month to count as a valid observation"),
    # risk_quantile is deliberately NOT exposed here: get_predictive_operational_risk's
    # risk_band cutoffs (0.6/0.4/0.25) are calibrated for the default risk_quantile=0.75
    # and don't move automatically if it changes -- see the comment at those cutoffs.
):
    """Decision Center D: a genuine trained, temporally-validated predictive
    risk model -- not the arbitrary-weight formula an earlier design pass
    used elsewhere. See api/predictive_risk.py for the full methodology and
    its own verification notes; this endpoint just wires it to real dates
    and real query params."""
    if entity_type not in ("airport", "carrier"):
        raise HTTPException(status_code=400, detail="entity_type must be 'airport' or 'carrier'")

    with open_readonly_connection() as connection:
        bounds = connection.execute("SELECT MIN(FlightDate), MAX(FlightDate) FROM flights").fetchone()
    default_end = str(bounds[1])
    default_start = str(date.fromisoformat(default_end) - timedelta(days=DEFAULT_MODEL_LOOKBACK_DAYS))

    result = predictive_risk.get_predictive_operational_risk(
        entity_type=entity_type,
        entity=entity,
        start_date=start_date or default_start,
        end_date=end_date or default_end,
        minimum_flights=minimum_flights,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/decision/departure-bank-smoothing")
def departure_bank_smoothing_endpoint(
    airport: str = Query(...),
    carrier: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="Defaults to the most recent 90 days of available data"),
    end_date: Optional[str] = Query(None),
    window_start_hour: int = Query(6, ge=0, le=23),
    window_end_hour: int = Query(10, ge=0, le=23),
    allowed_shift_minutes: int = Query(30, ge=0, le=180, description="Maximum movement in either direction, in minutes"),
    preferred_bank_limit: Optional[float] = Query(None, ge=0, description="Flights per 15-min bucket before it counts as overloaded; auto-computed from seasonal history if not given"),
    seasonal_lookback_years: int = Query(3, ge=0, le=8, description="How many prior years of the SAME calendar window to use as the congestion/delay baseline. 0 disables this and falls back to using only the current window's own data (the original, more circular baseline)."),
    congestion_weighting: float = Query(
        5.0,
        ge=0,
        description=(
            "Weight on the congestion-overload term relative to the delay-proxy term. Empirically "
            "tuned (not guessed): at very low values the delay-proxy term dominates and the solver "
            "can pile flights into whichever bucket has the lowest historical delay rather than "
            "flattening load. The congestion term itself is a convex, tiered penalty (see "
            "api/optimization/departure_bank.py) that makes concentrating overflow into one bucket "
            "strictly more expensive than spreading the same total overflow -- this is what dropped "
            "the reliably-needed weighting from 40 down to 5 (previously required before the tiered "
            "penalty existed, when a flat linear penalty was indifferent between spread and "
            "concentrated overflow at equal totals). Verified across ORD/ATL/LAX/JFK/DFW with "
            "optimized_peak_load staying comfortably under original_peak_load at this default."
        ),
    ),
    shift_penalty_weight: float = Query(0.05, ge=0),
    mode: str = Query("expected", description="'expected' or 'risk_averse'"),
    flight_limit: int = Query(1500, ge=1, le=3000, description="Safety cap on flights considered -- keeps this interactive. Applied via a random sample of the matching population, not a truncation, so it stays representative even when capped."),
    max_moved_flights: Optional[int] = Query(None, ge=0, description="Optional hard cap on how many sampled flights the optimizer may move"),
):
    """OR Feature 1: can this departure bank be smoothed with minimal
    disruption? Queries real individual flights (not aggregates) in the
    given window, builds one MILP decision variable set per flight, and
    solves via the same open-source HiGHS backend verified in
    tests/test_or_departure_bank.py. See api/optimization/departure_bank.py
    for the full formulation."""
    if window_end_hour <= window_start_hour:
        raise HTTPException(status_code=400, detail="window_end_hour must be after window_start_hour")
    if mode not in ("expected", "risk_averse"):
        raise HTTPException(status_code=400, detail="mode must be 'expected' or 'risk_averse'")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    if not start_date or not end_date:
        with open_readonly_connection() as connection:
            max_date = connection.execute("SELECT MAX(FlightDate) FROM flights").fetchone()[0]
        end_date = end_date or str(max_date)
        start_date = start_date or str(date.fromisoformat(str(max_date)) - timedelta(days=90))

    airport = airport.upper()
    clauses = [
        "FlightDate BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)",
        "Origin = ?", "Cancelled = 0", "CRSDepTime IS NOT NULL",
        "(CRSDepTime / 100) BETWEEN ? AND ?",
    ]
    params: list = [start_date, end_date, airport, window_start_hour, window_end_hour]
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())

    # ORDER BY random(), not CRSDepTime: CRSDepTime is time-of-day only (no
    # date component), so sorting by it across a multi-month range returns
    # every date's numerically-earliest departures (e.g. all 6:00am flights)
    # before any later-window flight, regardless of date -- a sort-order
    # artifact, not a sample. A uniform random sample keeps the capped
    # result statistically representative of the true bucket-load
    # distribution across the whole window instead.
    query = f"""
        SELECT CRSDepTime, ArrDelay, COUNT(*) OVER () AS total_matching
        FROM flights
        WHERE {' AND '.join(clauses)}
        ORDER BY random()
        LIMIT ?
    """
    # Deterministic per-request seed: identical query params should return
    # the identical sample on repeat calls (e.g. a demo re-run, or a user
    # refreshing the page) rather than silently reporting a different
    # original_peak_load each time purely from re-randomizing which flights
    # got drawn. Still a genuine uniform random sample -- just a fixed one
    # for a given set of params, not a smaller/less representative one.
    seed_input = f"{airport}|{carrier}|{start_date}|{end_date}|{window_start_hour}|{window_end_hour}|{flight_limit}"
    seed = (int(hashlib.sha256(seed_input.encode()).hexdigest(), 16) % 2_000_000 - 1_000_000) / 1_000_000
    with open_readonly_connection() as connection:
        connection.execute("SELECT setseed(?)", [seed])
        rows = connection.execute(query, params + [flight_limit]).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No flights matched that airport/carrier/date range/window.")

    total_matching_flights = rows[0][2]
    rows = [(r[0], r[1]) for r in rows]
    if max_moved_flights is not None and max_moved_flights > len(rows):
        raise HTTPException(
            status_code=400,
            detail="max_moved_flights cannot exceed the number of flights considered by this request",
        )
    # If flight_limit truncated the true population, the fetched rows are a
    # SAMPLE, but seasonal_average_load below is computed from the full,
    # uncapped historical population (a separate GROUP BY query, no LIMIT).
    # Comparing sampled current-window bucket counts directly against a
    # full-population-scale threshold means the "overloaded" bar is set
    # ~1/sample_fraction times too high and congestion never registers --
    # sample_fraction rescales the auto-computed limit onto the same scale
    # as the counts it's actually being compared against.
    sample_fraction = min(1.0, len(rows) / total_matching_flights) if total_matching_flights else 1.0

    def to_bucket(crs_dep_time: int) -> int:
        hour, minute = divmod(int(crs_dep_time), 100)
        return min(95, max(0, (hour * 60 + minute) // 15))

    flights: list[BankFlight] = []
    bucket_delays: dict[int, list[float]] = {}
    for i, (crs_dep_time, arr_delay) in enumerate(rows):
        bucket = to_bucket(crs_dep_time)
        flights.append(BankFlight(flight_id=f"F{i}_{crs_dep_time}", original_bucket=bucket))
        if arr_delay is not None:
            bucket_delays.setdefault(bucket, []).append(float(arr_delay))

    point_estimate = {b: (sum(v) / len(v)) for b, v in bucket_delays.items()}

    # Seasonal baseline: the SAME calendar window (same month/day range,
    # same airport/carrier/hour-window), pulled from N prior years. This
    # is a genuinely independent reference point -- unlike comparing the
    # current window against its OWN average (circular if the window being
    # analyzed IS the congested period), this asks "what does this same
    # time of year normally look like." Thanksgiving week compares against
    # prior Thanksgiving weeks; September compares against prior
    # Septembers -- whatever calendar window was actually requested.
    seasonal_bucket_loads: dict[int, list[int]] = {}
    seasonal_bucket_delays: dict[int, list[float]] = {}
    seasonal_years_with_data = 0
    if seasonal_lookback_years > 0:
        start_d = date.fromisoformat(start_date)
        end_d = date.fromisoformat(end_date)
        with open_readonly_connection() as connection:
            for offset in range(1, seasonal_lookback_years + 1):
                season_start = str(start_d - relativedelta(years=offset))
                season_end = str(end_d - relativedelta(years=offset))
                season_clauses = [
                    "FlightDate BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)",
                    "Origin = ?", "Cancelled = 0", "CRSDepTime IS NOT NULL",
                    "(CRSDepTime / 100) BETWEEN ? AND ?",
                ]
                season_params: list = [season_start, season_end, airport, window_start_hour, window_end_hour]
                if carrier:
                    season_clauses.append("Marketing_Airline_Network = ?")
                    season_params.append(carrier.upper())
                season_rows = connection.execute(
                    f"""
                    SELECT
                        CAST((CRSDepTime // 100) * 60 + (CRSDepTime % 100) AS INTEGER) // 15 AS bucket,
                        COUNT(*) AS n,
                        AVG(ArrDelay) AS avg_delay
                    FROM flights
                    WHERE {' AND '.join(season_clauses)}
                    GROUP BY bucket
                    """,
                    season_params,
                ).fetchall()
                if season_rows:
                    seasonal_years_with_data += 1
                for bucket, n, avg_delay in season_rows:
                    seasonal_bucket_loads.setdefault(int(bucket), []).append(int(n))
                    if avg_delay is not None:
                        seasonal_bucket_delays.setdefault(int(bucket), []).append(float(avg_delay))

    used_seasonal_baseline = seasonal_lookback_years > 0 and seasonal_years_with_data > 0

    if used_seasonal_baseline:
        # Blend: current window's own observed delays PLUS the seasonal
        # years' bucket-average delays, pooled together -- more data, more
        # robust estimate, without discarding what actually just happened.
        for b, seasonal_avgs in seasonal_bucket_delays.items():
            combined = list(bucket_delays.get(b, [])) + seasonal_avgs
            if combined:
                point_estimate[b] = sum(combined) / len(combined)

        all_seasonal_loads = [n for loads in seasonal_bucket_loads.values() for n in loads]
        seasonal_average_load = sum(all_seasonal_loads) / len(all_seasonal_loads) if all_seasonal_loads else 0.0

    current_bucket_loads: dict[int, int] = {}
    for f in flights:
        current_bucket_loads[f.original_bucket] = current_bucket_loads.get(f.original_bucket, 0) + 1
    current_average_load = sum(current_bucket_loads.values()) / max(1, len(current_bucket_loads))

    if preferred_bank_limit is None:
        if used_seasonal_baseline:
            # The genuine fix: target the seasonal historical norm (+10%
            # slack for ordinary variance), not 120% of the very window
            # being analyzed -- which could already be an elevated period.
            # Scaled by sample_fraction: seasonal_average_load is a
            # full-population figure (uncapped GROUP BY), but the flights
            # list here is a SAMPLE whenever flight_limit truncated the
            # window -- without this the limit sits ~1/sample_fraction too
            # high and overload never triggers regardless of true congestion.
            preferred_bank_limit_value = round(max(1.0, seasonal_average_load * 1.1 * sample_fraction), 1)
        else:
            preferred_bank_limit_value = round(max(1.0, current_average_load * 1.2), 1)
    else:
        preferred_bank_limit_value = preferred_bank_limit

    limit_map = {t: preferred_bank_limit_value for t in range(96)}
    weight_map = {t: 1.0 for t in range(96)}

    bucket_scenarios = None
    scenario_probs = None
    if mode == "risk_averse":
        # A real, disclosed way to build scenarios without a second
        # historical query per bucket for this first pass: treat each
        # flight actually observed in a bucket as one scenario draw for
        # that bucket's delay distribution. Buckets with only 1-2 flights
        # get a thin, noisy scenario set -- reported plainly via
        # scenario_counts below, not hidden.
        bucket_scenarios = {}
        max_scenarios = max((len(v) for v in bucket_delays.values()), default=1)
        for b, delays in bucket_delays.items():
            padded = list(delays) + [point_estimate[b]] * (max_scenarios - len(delays))
            bucket_scenarios[b] = padded
        for b in point_estimate:
            if b not in bucket_scenarios:
                bucket_scenarios[b] = [point_estimate[b]] * max_scenarios
        scenario_probs = [1.0 / max_scenarios] * max_scenarios

    result = solve_departure_bank(
        flights, n_buckets=96, allowed_shift_minutes=allowed_shift_minutes,
        preferred_bank_limit=limit_map, congestion_weight_by_bucket=weight_map,
        bucket_delay_point_estimate=point_estimate,
        bucket_delay_scenarios=bucket_scenarios, scenario_probs=scenario_probs,
        congestion_weighting=congestion_weighting, shift_penalty_weight=shift_penalty_weight,
        max_moved_flights=max_moved_flights,
        mode=mode, backend=PublicBackend(),
    )

    def bucket_to_time(b: int) -> str:
        total_minutes = b * 15
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"

    return {
        "airport": airport,
        "carrier": carrier,
        "window": f"{window_start_hour:02d}:00-{window_end_hour:02d}:00",
        "date_range": f"{start_date} to {end_date}",
        "flights_considered": len(flights),
        "max_moved_flights": max_moved_flights,
        "total_matching_flights": total_matching_flights,
        "flight_limit_applied": len(rows) == flight_limit,
        "sample_fraction": round(sample_fraction, 4),
        "preferred_bank_limit": preferred_bank_limit_value,
        "preferred_bank_limit_was_auto_computed": preferred_bank_limit is None,
        "seasonal_baseline": {
            "requested_years": seasonal_lookback_years,
            "years_with_data": seasonal_years_with_data,
            "used": used_seasonal_baseline,
            "current_window_average_load": round(current_average_load, 2),
            "seasonal_average_load": round(seasonal_average_load, 2) if used_seasonal_baseline else None,
            "current_vs_seasonal_pct": (
                round(((current_average_load - seasonal_average_load) / seasonal_average_load) * 100, 1)
                if used_seasonal_baseline and seasonal_average_load > 0 else None
            ),
            "note": (
                f"Compared against the SAME calendar window ({start_date[5:]} to {end_date[5:]}, "
                f"i.e. Thanksgiving vs prior Thanksgivings, September vs prior Septembers, etc.) in "
                f"{seasonal_years_with_data} prior year(s) with available data."
                if used_seasonal_baseline else
                "No seasonal baseline used -- either seasonal_lookback_years was 0, or no data existed "
                "in the same calendar window for any prior year. Falling back to this window's own "
                "average as the baseline, which is a real, disclosed limitation, not a silent guess."
            ),
        },
        "status": result.status,
        "mode": result.mode,
        "original_peak_load": result.original_peak_load,
        "optimized_peak_load": result.optimized_peak_load,
        "flights_moved": result.flights_moved,
        "average_movement_minutes": result.average_movement_minutes,
        "objective_decomposition": result.objective_decomposition,
        "original_bank_load": {bucket_to_time(int(b)): n for b, n in result.original_bank_load.items()},
        "optimized_bank_load": {bucket_to_time(int(b)): n for b, n in result.optimized_bank_load.items()},
        "assignments": [
            {**a, "original_time": bucket_to_time(a["original_bucket"]), "assigned_time": bucket_to_time(a["assigned_bucket"])}
            for a in result.assignments
        ],
        "methodology": result.methodology,
    }


@app.get("/api/summary")
def summary_endpoint(
    carrier: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """One real, warehouse-backed summary, optionally filtered by carrier and/or date range."""
    if not carrier and not start_date and not end_date:
        with open_readonly_connection() as connection:
            fast_result = network_summary(connection)
        if fast_result:
            return fast_result
    result = copilot_get_summary(carrier=carrier, start_date=start_date, end_date=end_date)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/trend")
def trend_endpoint(
    carrier: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """On-time rate and flight volume by month, optionally filtered by carrier and/or date range."""
    if not start_date and not end_date:
        with open_readonly_connection() as connection:
            fast_result = network_trend(connection, carrier=carrier)
        if fast_result is not None:
            return {"months": fast_result}
    result = copilot_get_trend(carrier=carrier, start_date=start_date, end_date=end_date)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/carriers")
def carriers_endpoint():
    """On-time rate, avg delay, and cancellation rate per carrier."""
    with open_readonly_connection() as connection:
        fast_result = carrier_ranking(connection)
    if fast_result is not None:
        return {"carriers": fast_result}
    return copilot_compare_carriers()


@app.get("/api/delay-causes")
def delay_causes_endpoint(
    carrier: Optional[str] = Query(None),
    airport: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """Total delay-minutes attributed to each BTS coded cause, optionally
    filtered by carrier, airport, and/or date range.

    These are BTS's own recorded categories, not root causes -- a flight's
    total delay is split across whichever of these apply, only for flights
    that were delayed 15+ minutes and had a cause coded.
    """
    result = copilot_get_delay_causes(
        carrier=carrier, airport=airport, start_date=start_date, end_date=end_date
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/cancellation-causes")
def cancellation_causes_endpoint(
    carrier: Optional[str] = Query(None),
    airport: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """Breakdown of WHY flights were cancelled (BTS's CancellationCode:
    Carrier/Weather/National Air System/Security), as a share of cancelled
    flights -- distinct from delay-causes, which covers why DELAYED (not
    cancelled) flights ran late. This never existed in the old 20-column
    build; CancellationCode wasn't pulled there."""
    clauses = ["Cancelled = 1"]
    params: list = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    base_where = " AND ".join(clauses)
    coded_where = base_where + " AND CancellationCode IS NOT NULL"

    with open_readonly_connection() as connection:
        total_cancelled = connection.execute(
            f"SELECT COUNT(*) FROM flights WHERE {base_where}", params
        ).fetchone()[0]

        rows = connection.execute(
            f"""
            SELECT CancellationCode, COUNT(*) AS cancelled_flights
            FROM flights
            WHERE {coded_where}
            GROUP BY CancellationCode
            """,
            params,
        ).fetchall()

    if total_cancelled == 0:
        raise HTTPException(status_code=404, detail="No cancelled flights found for that filter.")

    code_labels = {
        "A": "Carrier",
        "B": "Weather",
        "C": "National Air System",
        "D": "Security",
    }
    causes = {label: 0 for label in code_labels.values()}
    coded_total = 0
    for code, count in rows:
        label = code_labels.get(code)
        if label:
            causes[label] = count
            coded_total += count

    return {
        "total_cancelled_flights": total_cancelled,
        "coded_cancelled_flights": coded_total,
        "causes": [
            {"cause": label, "cancelled_flights": count, "share": (count / coded_total if coded_total else 0)}
            for label, count in causes.items()
        ],
    }


@app.get("/api/distance-buckets")
def distance_buckets_endpoint(
    carrier: Optional[str] = Query(None),
    airport: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """On-time performance broken out by haul length (short/medium/long-haul,
    bucketed by scheduled Distance), optionally filtered by carrier, airport,
    and/or date range. Buckets: short-haul <500mi, medium-haul 500-1500mi,
    long-haul >1500mi -- these three cover essentially all domestic BTS
    routes, including mainland-Hawaii legs."""
    clauses = ["Distance IS NOT NULL"]
    params: list = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                CASE
                    WHEN Distance < 500 THEN 'Short-haul'
                    WHEN Distance < 1500 THEN 'Medium-haul'
                    ELSE 'Long-haul'
                END AS bucket,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate,
                AVG(Distance) AS avg_distance_miles
            FROM flights
            WHERE {where}
            GROUP BY bucket
            """,
            params,
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No flights matched that filter.")

    bucket_order = {"Short-haul": 0, "Medium-haul": 1, "Long-haul": 2}
    buckets = sorted(
        (
            {
                "bucket": r[0],
                "total_flights": r[1],
                "on_time_rate": r[2],
                "avg_arrival_delay_minutes": r[3],
                "cancellation_rate": r[4],
                "avg_distance_miles": r[5],
            }
            for r in rows
        ),
        key=lambda b: bucket_order[b["bucket"]],
    )
    return {"buckets": buckets}


@app.get("/api/codeshare")
def codeshare_endpoint(
    carrier: Optional[str] = Query(None),
    airport: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """Self-operated vs codeshare-operated split for a marketing carrier.
    BTS's Operating_Airline differs from Marketing_Airline_Network when a
    flight sold under one carrier's code is actually flown by a regional
    partner (e.g. a Delta-coded flight operated by Endeavor Air). Also
    returns the top operating partners by volume for the codeshare-operated
    share. Optionally filtered by carrier, airport, and/or date range."""
    clauses = ["Operating_Airline IS NOT NULL", "Operating_Airline != ''"]
    params: list = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                CASE WHEN Operating_Airline = Marketing_Airline_Network
                     THEN 'Self-operated' ELSE 'Codeshare-operated' END AS group_label,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM flights
            WHERE {where}
            GROUP BY group_label
            """,
            params,
        ).fetchall()

        if not rows:
            raise HTTPException(status_code=404, detail="No flights matched that filter.")

        total_flights = sum(r[1] for r in rows)

        partner_rows = connection.execute(
            f"""
            SELECT
                Operating_Airline,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {where} AND Operating_Airline != Marketing_Airline_Network
            GROUP BY Operating_Airline
            ORDER BY total_flights DESC
            LIMIT 8
            """,
            params,
        ).fetchall()

    group_order = {"Self-operated": 0, "Codeshare-operated": 1}
    groups = sorted(
        (
            {
                "group": r[0],
                "total_flights": r[1],
                "on_time_rate": r[2],
                "avg_arrival_delay_minutes": r[3],
                "cancellation_rate": r[4],
                "share": (r[1] / total_flights if total_flights else 0),
            }
            for r in rows
        ),
        key=lambda g: group_order.get(g["group"], 2),
    )

    return {
        "total_flights": total_flights,
        "groups": groups,
        "top_operating_partners": [
            {"operating_airline": r[0], "total_flights": r[1], "on_time_rate": r[2]}
            for r in partner_rows
        ],
    }


@app.get("/api/turnbacks")
def turnbacks_endpoint(
    carrier: Optional[str] = Query(None),
    airport: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """Gate-return / turnback flights -- BTS's FirstDepTime is only populated
    when a flight pushed back, returned to the gate, and departed again;
    TotalAddGTime is the extra ground time (minutes) that return added.
    TotalAddGTime is TRY_CAST to DOUBLE because it's a sparse column (blank
    on ~99.9% of rows): DuckDB infers each monthly source CSV's column type
    independently before UNION BY NAME merges them, so a month with zero
    turnbacks can infer VARCHAR for an all-blank column while a month with
    turnbacks infers DOUBLE -- the merge then falls back to VARCHAR, and a
    bare AVG() on that would throw a binder error. TRY_CAST sidesteps that
    regardless of which way it landed. NOTE: airport filter is Origin-only
    (not Origin OR Dest like other endpoints) -- a turnback is inherently a
    departure-side event, so filtering by arrival airport wouldn't mean
    anything here. Optionally filtered by carrier and/or date range too."""
    clauses = ["Cancelled = 0"]
    params: list = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("Origin = ?")
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        row = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                SUM(CASE WHEN FirstDepTime IS NOT NULL THEN 1 ELSE 0 END) AS turnback_flights,
                AVG(CASE WHEN FirstDepTime IS NOT NULL THEN TRY_CAST(TotalAddGTime AS DOUBLE) END) AS avg_add_gtime_minutes,
                AVG(CASE WHEN FirstDepTime IS NOT NULL
                    THEN (CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END) END) AS turnback_on_time_rate,
                AVG(CASE WHEN FirstDepTime IS NULL
                    THEN (CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END) END) AS non_turnback_on_time_rate
            FROM flights
            WHERE {where}
            """,
            params,
        ).fetchone()

    if row is None or row[0] == 0:
        raise HTTPException(status_code=404, detail="No flights matched that filter.")

    total_flights, turnback_flights, avg_add_gtime, turnback_otr, non_turnback_otr = row
    return {
        "total_flights": total_flights,
        "turnback_flights": turnback_flights,
        "turnback_rate": (turnback_flights / total_flights if total_flights else 0),
        "avg_add_gtime_minutes": avg_add_gtime,
        "turnback_on_time_rate": turnback_otr,
        "non_turnback_on_time_rate": non_turnback_otr,
    }


@app.get("/api/diversions")
def diversions_endpoint(
    carrier: Optional[str] = Query(None),
    airport: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    dest: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """Multi-leg diversion deep-dive. Among diverted flights: how many
    intermediate airports did they land at before stopping
    (DivAirportLandings), and did they ever reach their original scheduled
    destination (DivReachedDest)? Both are TRY_CAST because they're sparse
    columns (populated only for the small share of diverted flights) -- see
    the TotalAddGTime comment on /api/turnbacks for why that makes them a
    type-inference risk across the monthly source files. Accepts either a
    generic carrier/airport filter or an exact origin+dest route filter (for
    route-specific lookups), plus optional date range -- all combine as AND."""
    clauses = ["1=1"]
    params: list = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if origin:
        clauses.append("Origin = ?")
        params.append(origin.upper())
    if dest:
        clauses.append("Dest = ?")
        params.append(dest.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)
    diverted_where = where + " AND Diverted = 1"

    with open_readonly_connection() as connection:
        overall = connection.execute(
            f"SELECT COUNT(*), SUM(Diverted) FROM flights WHERE {where}",
            params,
        ).fetchone()

        if overall is None or overall[0] == 0:
            raise HTTPException(status_code=404, detail="No flights matched that filter.")

        total_flights, diverted_flights = overall
        diverted_flights = diverted_flights or 0

        landing_rows = connection.execute(
            f"""
            SELECT
                CASE
                    WHEN TRY_CAST(DivAirportLandings AS INTEGER) IS NULL
                         OR TRY_CAST(DivAirportLandings AS INTEGER) <= 1 THEN '1 stop'
                    WHEN TRY_CAST(DivAirportLandings AS INTEGER) = 2 THEN '2 stops'
                    ELSE '3+ stops'
                END AS bucket,
                COUNT(*) AS diverted_flights,
                AVG(CASE WHEN TRY_CAST(DivReachedDest AS INTEGER) = 1 THEN 1.0 ELSE 0.0 END) AS reached_destination_rate
            FROM flights
            WHERE {diverted_where}
            GROUP BY bucket
            """,
            params,
        ).fetchall()

        # The deep-dive: where diverted flights actually land, and what it
        # really cost -- built from Div1Airport/DivDistance/DivArrDelay/
        # DivActualElapsedTime, confirmed real and confirmed completely
        # unused anywhere on this site until now (see the column audit).
        # DivDistance is the ACTUAL distance flown including the diversion
        # detour, vs Distance (the originally scheduled distance) -- the
        # difference is real extra miles, not an estimate.
        top_diversion_airports = connection.execute(
            f"""
            SELECT
                Div1Airport,
                COUNT(*) AS diverted_flights,
                AVG(CASE WHEN TRY_CAST(DivReachedDest AS INTEGER) = 1 THEN 1.0 ELSE 0.0 END) AS reached_destination_rate,
                AVG(DivArrDelay) AS avg_arrival_delay_minutes,
                AVG(DivDistance - Distance) AS avg_extra_distance_miles
            FROM flights
            WHERE {diverted_where} AND Div1Airport IS NOT NULL
            GROUP BY Div1Airport
            ORDER BY diverted_flights DESC
            LIMIT 10
            """,
            params,
        ).fetchall()

        cost_row = connection.execute(
            f"""
            SELECT
                AVG(DivArrDelay) AS avg_arrival_delay_minutes,
                AVG(DivDistance - Distance) AS avg_extra_distance_miles,
                AVG(DivActualElapsedTime - CRSElapsedTime) AS avg_extra_time_minutes
            FROM flights
            WHERE {diverted_where}
                AND DivArrDelay IS NOT NULL AND DivDistance IS NOT NULL
                AND DivActualElapsedTime IS NOT NULL AND CRSElapsedTime IS NOT NULL
            """,
            params,
        ).fetchone()

    bucket_order = {"1 stop": 0, "2 stops": 1, "3+ stops": 2}
    landing_buckets = sorted(
        (
            {
                "bucket": r[0],
                "diverted_flights": r[1],
                "reached_destination_rate": r[2],
            }
            for r in landing_rows
        ),
        key=lambda b: bucket_order.get(b["bucket"], 3),
    )

    return {
        "total_flights": total_flights,
        "diverted_flights": diverted_flights,
        "diversion_rate": (diverted_flights / total_flights if total_flights else 0),
        "landing_buckets": landing_buckets,
        "top_diversion_airports": [
            {
                "airport": r[0],
                "diverted_flights": r[1],
                "reached_destination_rate": r[2],
                "avg_arrival_delay_minutes": r[3],
                "avg_extra_distance_miles": r[4],
            }
            for r in top_diversion_airports
        ],
        "average_diversion_cost": (
            {
                "avg_arrival_delay_minutes": cost_row[0],
                "avg_extra_distance_miles": cost_row[1],
                "avg_extra_time_minutes": cost_row[2],
            }
            if cost_row and cost_row[0] is not None
            else None
        ),
    }


# Sourced from a curated external list (delivery records for the specific
# 737-8/737-9 MAX aircraft in US-carrier service at the moment of the March
# 13, 2019 FAA grounding order), not derived from BTS data -- BTS on-time
# data has no aircraft-type field at all. Verified directly against this
# warehouse before use: all 72 tails show real flight activity ramping up
# through Feb 2019, then a complete 20-month gap with ZERO flights from any
# of the 72 tails (Apr 2019 - Nov 2020, matching the grounding almost
# exactly), then a resumption ramp back to all 72 tails flying by Apr 2021.
GROUNDED_737_MAX_TAILS = {
    "N8710M": "737-8 MAX", "N8705Q": "737-8 MAX", "N8708Q": "737-8 MAX",
    "N8711Q": "737-8 MAX", "N8706W": "737-8 MAX", "N8707P": "737-8 MAX",
    "N8712L": "737-8 MAX", "N324RA": "737-8 MAX", "N8713M": "737-8 MAX",
    "N8709Q": "737-8 MAX", "N8714Q": "737-8 MAX", "N304RB": "737-8 MAX",
    "N8716B": "737-8 MAX", "N8715Q": "737-8 MAX", "N306RC": "737-8 MAX",
    "N308RD": "737-8 MAX", "N8704Q": "737-8 MAX", "N303RE": "737-8 MAX",
    "N310RF": "737-8 MAX", "N303RG": "737-8 MAX", "N8717M": "737-8 MAX",
    "N8718Q": "737-8 MAX", "N314RH": "737-8 MAX", "N315RJ": "737-8 MAX",
    "N316RK": "737-8 MAX", "N8701Q": "737-8 MAX", "N321RL": "737-8 MAX",
    "N323RM": "737-8 MAX", "N8719Q": "737-8 MAX", "N8720L": "737-8 MAX",
    "N324RN": "737-8 MAX", "N326RP": "737-8 MAX", "N8721J": "737-8 MAX",
    "N328RR": "737-8 MAX", "N8726H": "737-8 MAX", "N8727M": "737-8 MAX",
    "N8702L": "737-8 MAX", "N8722L": "737-8 MAX", "N8724J": "737-8 MAX",
    "N8723Q": "737-8 MAX", "N338RS": "737-8 MAX", "N8725L": "737-8 MAX",
    "N336RU": "737-8 MAX", "N335RT": "737-8 MAX", "N8731J": "737-8 MAX",
    "N8730Q": "737-8 MAX", "N350RV": "737-8 MAX", "N8732S": "737-8 MAX",
    "N341RW": "737-8 MAX", "N8729H": "737-8 MAX", "N342RX": "737-8 MAX",
    "N343RY": "737-8 MAX", "N8733M": "737-8 MAX", "N313SB": "737-8 MAX",
    "N8734Q": "737-8 MAX", "N8728Q": "737-8 MAX", "N302SA": "737-8 MAX",
    "N8735L": "737-8 MAX", "N67501": "737-9 MAX", "N37502": "737-9 MAX",
    "N27503": "737-9 MAX", "N37504": "737-9 MAX", "N37506": "737-9 MAX",
    "N47505": "737-9 MAX", "N37507": "737-9 MAX", "N37508": "737-9 MAX",
    "N27509": "737-9 MAX", "N27511": "737-9 MAX", "N37510": "737-9 MAX",
    "N47512": "737-9 MAX", "N37513": "737-9 MAX", "N37514": "737-9 MAX",
}

MAX_GROUNDING_DATE = "2019-03-13"
MAX_UNGROUNDING_DATE = "2020-11-18"
MAX_RESUMPTION_WINDOW_START = "2021-04-01"  # all 72 tails back in service by this point, verified directly

# Immediate pre-grounding window: recent enough to represent the network as
# it actually existed right before the event, not a multi-year average.
MAX_PRE_START = "2019-01-01"
MAX_PRE_END = "2019-03-12"
MAX_POST2019_START = MAX_GROUNDING_DATE
MAX_POST2019_END = "2019-12-31"
# Jan-Feb 2020: still within the grounding, but before COVID's major US
# disruption (~March 2020) -- the one window that isolates grounding impact
# from the pandemic, adapted from a prior version of this analysis.
MAX_EARLY2020_START = "2020-01-01"
MAX_EARLY2020_END = "2020-02-29"
MAX_TIMELINE_START = "2018-01-01"
MAX_TIMELINE_END = "2021-12-31"


def _days_inclusive(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def _sql_literal_list(values) -> str:
    """Render a fixed, server-side-only string list as a safe SQL IN-list
    literal. Only ever called with the hardcoded GROUNDED_737_MAX_TAILS
    keys/carrier codes derived from them below -- never with user input."""
    return ",".join(f"'{v}'" for v in values)


@app.get("/api/max-grounding-study")
def max_grounding_study_endpoint():
    """737 MAX grounding study. Adapted from a more extensive prior version
    of this analysis (an earlier platform build); this streamlines it to
    fit the current schema and scope, keeping the core methodology:

    1. ROUTE-LEVEL EXPOSURE: for each carrier-route with at least one
       flight from the 72 grounded tails in the immediate pre-grounding
       window (Jan 1 - Mar 12, 2019 -- recent enough to reflect the network
       as it actually existed, not a multi-year average), what SHARE of
       that route's flights were MAX -- segmented into exposure tiers
       (high >=50%, moderate 20-49%, low 5-19%, incidental <5%; these are
       prioritization bands, not causal thresholds).
    2. GROUNDING-PERIOD IMPACT: for those exposed routes, how did flight
       frequency (flights/day, normalized for window length) change in two
       windows -- (a) the rest of 2019 after the grounding, and (b) Jan-Feb
       2020, which is STILL within the grounding but BEFORE COVID's major
       US disruption (~March 2020). That second window is the one place in
       this whole study that isolates grounding impact from the pandemic.
    3. CARRIER-NORMALIZED BENCHMARK: each exposed route's frequency change
       is also compared against that carrier's own total schedule change
       over the same window -- contextual evidence a route-specific drop
       wasn't just the carrier flying less overall that quarter, not a
       causal counterfactual.
    4. LONG-RUN PERFORMANCE SINCE RETURN TO SERVICE (kept from the earlier
       version of this endpoint): same-era MAX-vs-control comparison from
       April 2021 onward, once flights actually resumed.

    Deliberately NOT ported from the prior version, to keep this scoped:
    flight-number-level "schedule signature" substitution tracking, and
    per-tail utilization/replacement-tail detail. Those could be added
    later if the route-level view here isn't enough.

    KNOWN LIMITATIONS, disclosed rather than hidden: cancelled flights can
    lack a tail assignment, so cancellations can't be attributed to a
    specific grounded tail by tail-number matching alone. Carrier
    assignment uses the BTS marketing-carrier field, not legal aircraft
    ownership. March 2020 onward is confounded by COVID and is included
    mainly for the monthly timeline's context, not attribution. The
    long-run control group (section 4) can include 737 MAX aircraft these
    carriers took delivery of after 2019, since there's no full current-
    fleet MAX list without the FAA registry -- this dilutes, not
    exaggerates, any true difference."""
    tail_list_sql = _sql_literal_list(GROUNDED_737_MAX_TAILS.keys())
    max8_tail_list_sql = _sql_literal_list(
        t for t, v in GROUNDED_737_MAX_TAILS.items() if v == "737-8 MAX"
    )

    with open_readonly_connection() as connection:
        carrier_rows = connection.execute(
            f"SELECT DISTINCT Marketing_Airline_Network FROM flights WHERE Tail_Number IN ({tail_list_sql})"
        ).fetchall()
        carriers = [r[0] for r in carrier_rows if r[0]]

        if not carriers:
            raise HTTPException(status_code=404, detail="None of the grounded 737 MAX tail numbers were found in this warehouse.")

        carrier_list_sql = _sql_literal_list(carriers)

        # --- 1. Monthly timeline: buildup, the 20-month gap, resumption ---
        timeline_rows = connection.execute(
            f"""
            SELECT
                strftime(FlightDate, '%Y-%m') AS month,
                COUNT(*) AS all_flights,
                COUNT(*) FILTER (WHERE Tail_Number IN ({tail_list_sql})) AS max_tail_flights
            FROM flights
            WHERE Marketing_Airline_Network IN ({carrier_list_sql})
              AND FlightDate >= CAST('{MAX_TIMELINE_START}' AS DATE)
              AND FlightDate <= CAST('{MAX_TIMELINE_END}' AS DATE)
            GROUP BY strftime(FlightDate, '%Y-%m')
            ORDER BY month
            """
        ).fetchall()
        monthly_timeline = [
            {"month": r[0], "all_flights": r[1], "max_tail_flights": r[2]} for r in timeline_rows
        ]

        # --- 2 & 3. Route-level exposure + grounding-period frequency change ---
        route_rows = connection.execute(
            f"""
            SELECT
                Marketing_Airline_Network AS carrier, Origin AS origin, Dest AS dest,
                COUNT(*) FILTER (
                    WHERE FlightDate BETWEEN CAST('{MAX_PRE_START}' AS DATE) AND CAST('{MAX_PRE_END}' AS DATE)
                ) AS pre_route_flights,
                COUNT(*) FILTER (
                    WHERE FlightDate BETWEEN CAST('{MAX_PRE_START}' AS DATE) AND CAST('{MAX_PRE_END}' AS DATE)
                      AND Tail_Number IN ({tail_list_sql})
                ) AS pre_max_flights,
                COUNT(*) FILTER (
                    WHERE FlightDate BETWEEN CAST('{MAX_POST2019_START}' AS DATE) AND CAST('{MAX_POST2019_END}' AS DATE)
                ) AS post_2019_route_flights,
                COUNT(*) FILTER (
                    WHERE FlightDate BETWEEN CAST('{MAX_EARLY2020_START}' AS DATE) AND CAST('{MAX_EARLY2020_END}' AS DATE)
                ) AS early_2020_route_flights
            FROM flights
            WHERE Marketing_Airline_Network IN ({carrier_list_sql})
              AND FlightDate BETWEEN CAST('{MAX_PRE_START}' AS DATE) AND CAST('{MAX_EARLY2020_END}' AS DATE)
            GROUP BY carrier, origin, dest
            HAVING COUNT(*) FILTER (
                WHERE FlightDate BETWEEN CAST('{MAX_PRE_START}' AS DATE) AND CAST('{MAX_PRE_END}' AS DATE)
                  AND Tail_Number IN ({tail_list_sql})
            ) > 0
            ORDER BY pre_max_flights DESC
            """
        ).fetchall()

        carrier_totals_rows = connection.execute(
            f"""
            SELECT
                Marketing_Airline_Network AS carrier,
                COUNT(*) FILTER (
                    WHERE FlightDate BETWEEN CAST('{MAX_PRE_START}' AS DATE) AND CAST('{MAX_PRE_END}' AS DATE)
                ) AS pre_total,
                COUNT(*) FILTER (
                    WHERE FlightDate BETWEEN CAST('{MAX_POST2019_START}' AS DATE) AND CAST('{MAX_POST2019_END}' AS DATE)
                ) AS post_2019_total,
                COUNT(*) FILTER (
                    WHERE FlightDate BETWEEN CAST('{MAX_EARLY2020_START}' AS DATE) AND CAST('{MAX_EARLY2020_END}' AS DATE)
                ) AS early_2020_total
            FROM flights
            WHERE Marketing_Airline_Network IN ({carrier_list_sql})
              AND FlightDate BETWEEN CAST('{MAX_PRE_START}' AS DATE) AND CAST('{MAX_EARLY2020_END}' AS DATE)
            GROUP BY carrier
            """
        ).fetchall()

        pre_days = _days_inclusive(MAX_PRE_START, MAX_PRE_END)
        post_days = _days_inclusive(MAX_POST2019_START, MAX_POST2019_END)
        early_days = _days_inclusive(MAX_EARLY2020_START, MAX_EARLY2020_END)

        def pct_change(before: float, after: float):
            if before == 0:
                return None
            return round((after - before) / before * 100, 2)

        def exposure_tier(share_pct: float) -> str:
            if share_pct >= 50:
                return "high"
            if share_pct >= 20:
                return "moderate"
            if share_pct >= 5:
                return "low"
            return "incidental"

        carrier_change = {}
        for carrier, pre_total, post_total, early_total in carrier_totals_rows:
            pre_fpd = pre_total / pre_days
            post_fpd = post_total / post_days
            early_fpd = early_total / early_days
            carrier_change[carrier] = {
                "pre_flights_per_day": round(pre_fpd, 2),
                "post_2019_change_pct": pct_change(pre_fpd, post_fpd),
                "early_2020_change_pct": pct_change(pre_fpd, early_fpd),
            }

        route_exposure = []
        for carrier, origin, dest, pre_route, pre_max, post_route, early_route in route_rows:
            share_pct = round(pre_max / pre_route * 100, 2) if pre_route else 0.0
            pre_fpd = pre_route / pre_days
            post_fpd = post_route / post_days
            early_fpd = early_route / early_days
            post_change = pct_change(pre_fpd, post_fpd)
            carrier_post_change = carrier_change.get(carrier, {}).get("post_2019_change_pct")
            if post_route == 0:
                status = "dropped"
            elif post_change is None:
                status = "unknown"
            elif post_change <= -50:
                status = "sharply_reduced"
            elif post_change <= -15:
                status = "reduced"
            elif post_change >= 15:
                status = "increased"
            else:
                status = "broadly_maintained"
            route_exposure.append({
                "carrier": carrier,
                "origin": origin,
                "dest": dest,
                "pre_route_flights": pre_route,
                "pre_max_flights": pre_max,
                "pre_max_share_pct": share_pct,
                "exposure_tier": exposure_tier(share_pct),
                "pre_flights_per_day": round(pre_fpd, 2),
                "post_2019_flights_per_day": round(post_fpd, 2),
                "post_2019_change_pct": post_change,
                "early_2020_flights_per_day": round(early_fpd, 2),
                "early_2020_change_pct": pct_change(pre_fpd, early_fpd),
                "carrier_post_2019_change_pct": carrier_post_change,
                "relative_change_vs_carrier_pct_points": (
                    round(post_change - carrier_post_change, 2)
                    if post_change is not None and carrier_post_change is not None
                    else None
                ),
                "post_2019_status": status,
            })
        route_exposure.sort(key=lambda r: r["pre_max_flights"], reverse=True)

        carrier_impact = []
        for carrier in carriers:
            rows_for_carrier = [r for r in route_exposure if r["carrier"] == carrier]
            if not rows_for_carrier:
                continue
            totals = next((c for c in carrier_totals_rows if c[0] == carrier), None)
            pre_total = totals[1] if totals else 0
            pre_max_total = sum(r["pre_max_flights"] for r in rows_for_carrier)
            carrier_impact.append({
                "carrier": carrier,
                "exposed_route_count": len(rows_for_carrier),
                "high_exposure_routes": sum(1 for r in rows_for_carrier if r["exposure_tier"] == "high"),
                "moderate_exposure_routes": sum(1 for r in rows_for_carrier if r["exposure_tier"] == "moderate"),
                "low_exposure_routes": sum(1 for r in rows_for_carrier if r["exposure_tier"] == "low"),
                "incidental_exposure_routes": sum(1 for r in rows_for_carrier if r["exposure_tier"] == "incidental"),
                "pre_grounding_max_flights": pre_max_total,
                "max_share_of_carrier_schedule_pct": (
                    round(pre_max_total / pre_total * 100, 2) if pre_total else None
                ),
                "routes_dropped": sum(1 for r in rows_for_carrier if r["post_2019_status"] == "dropped"),
                "routes_sharply_reduced": sum(1 for r in rows_for_carrier if r["post_2019_status"] == "sharply_reduced"),
                "routes_reduced": sum(1 for r in rows_for_carrier if r["post_2019_status"] == "reduced"),
                "routes_maintained_or_increased": sum(
                    1 for r in rows_for_carrier if r["post_2019_status"] in ("broadly_maintained", "increased")
                ),
                "carrier_post_2019_schedule_change_pct": carrier_change.get(carrier, {}).get("post_2019_change_pct"),
                "carrier_early_2020_schedule_change_pct": carrier_change.get(carrier, {}).get("early_2020_change_pct"),
            })
        carrier_impact.sort(key=lambda c: c["max_share_of_carrier_schedule_pct"] or 0, reverse=True)

        # --- 4. Long-run performance since return to service (kept as-is) ---
        def stats(where_clause: str):
            row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS total_flights,
                    COUNT(DISTINCT Tail_Number) AS distinct_tails,
                    AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                    AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                    AVG(Cancelled * 1.0) AS cancellation_rate
                FROM flights
                WHERE {where_clause}
                """
            ).fetchone()
            return {
                "total_flights": row[0],
                "distinct_tails": row[1],
                "on_time_rate": row[2],
                "avg_arrival_delay_minutes": row[3],
                "cancellation_rate": row[4],
            }

        max_post = stats(
            f"Tail_Number IN ({tail_list_sql}) AND FlightDate >= CAST('{MAX_RESUMPTION_WINDOW_START}' AS DATE)"
        )
        control_post = stats(
            f"""
            Marketing_Airline_Network IN ({carrier_list_sql})
            AND Tail_Number IS NOT NULL AND Tail_Number != ''
            AND Tail_Number NOT IN ({tail_list_sql})
            AND FlightDate >= CAST('{MAX_RESUMPTION_WINDOW_START}' AS DATE)
            """
        )
        max_pre_reference_only = stats(
            f"Tail_Number IN ({tail_list_sql}) AND FlightDate < CAST('{MAX_GROUNDING_DATE}' AS DATE)"
        )

        variant_rows = connection.execute(
            f"""
            SELECT
                CASE WHEN Tail_Number IN ({max8_tail_list_sql}) THEN '737-8 MAX' ELSE '737-9 MAX' END AS variant,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE Tail_Number IN ({tail_list_sql}) AND FlightDate >= CAST('{MAX_RESUMPTION_WINDOW_START}' AS DATE)
            GROUP BY variant
            """
        ).fetchall()

        tail_carrier_rows = connection.execute(
            f"""
            SELECT Tail_Number, Marketing_Airline_Network, COUNT(*) AS cnt
            FROM flights
            WHERE Tail_Number IN ({tail_list_sql})
            GROUP BY Tail_Number, Marketing_Airline_Network
            ORDER BY Tail_Number, cnt DESC
            """
        ).fetchall()
        tail_to_carrier: dict = {}
        for tail, carrier, _cnt in tail_carrier_rows:
            tail_to_carrier.setdefault(tail, carrier)

        tails_by_carrier: dict = {}
        for tail, carrier in tail_to_carrier.items():
            tails_by_carrier.setdefault(carrier, []).append(tail)

        by_carrier = []
        for carrier in carriers:
            carrier_tails_sql = _sql_literal_list(tails_by_carrier.get(carrier, []))
            if not carrier_tails_sql:
                continue
            carrier_max = stats(
                f"Tail_Number IN ({carrier_tails_sql}) AND FlightDate >= CAST('{MAX_RESUMPTION_WINDOW_START}' AS DATE)"
            )
            carrier_control = stats(
                f"""
                Marketing_Airline_Network = '{carrier}'
                AND Tail_Number IS NOT NULL AND Tail_Number != ''
                AND Tail_Number NOT IN ({tail_list_sql})
                AND FlightDate >= CAST('{MAX_RESUMPTION_WINDOW_START}' AS DATE)
                """
            )
            by_carrier.append({
                "carrier": carrier,
                "tail_count": len(tails_by_carrier.get(carrier, [])),
                "max": carrier_max,
                "control": carrier_control,
            })

    return {
        "carriers": carriers,
        "grounding_date": MAX_GROUNDING_DATE,
        "ungrounding_date": MAX_UNGROUNDING_DATE,
        "resumption_window_start": MAX_RESUMPTION_WINDOW_START,
        "pre_grounding_window": {"start": MAX_PRE_START, "end": MAX_PRE_END},
        "post_2019_window": {"start": MAX_POST2019_START, "end": MAX_POST2019_END},
        "early_2020_window": {"start": MAX_EARLY2020_START, "end": MAX_EARLY2020_END},
        "monthly_timeline": monthly_timeline,
        "route_exposure": route_exposure,
        "carrier_impact": carrier_impact,
        "by_carrier": by_carrier,
        "max_post_resumption": max_post,
        "control_post_resumption": control_post,
        "max_pre_grounding_reference_only": max_pre_reference_only,
        "by_variant_post_resumption": [
            {"variant": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in variant_rows
        ],
    }


@app.get("/api/time-of-day")
def time_of_day_endpoint(
    carrier: Optional[str] = Query(None),
    airport: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """On-time rate and average delay by SCHEDULED departure hour (0-23) --
    a simple, direct 'what time of day should I fly' breakdown. Unlike the
    dropped queue-pressure feature, this does no capacity modeling or
    threshold detection, just a straightforward hourly aggregation."""
    clauses = ["CRSDepTime IS NOT NULL"]
    params: list = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("Origin = ?")
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                CAST(FLOOR(CAST(CRSDepTime AS INTEGER) / 100) AS INTEGER) AS scheduled_hour,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes
            FROM flights
            WHERE {where}
            GROUP BY scheduled_hour
            HAVING scheduled_hour BETWEEN 0 AND 23
            ORDER BY scheduled_hour
            """,
            params,
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No flights found for that filter.")

    return {
        "hours": [
            {
                "scheduled_hour": r[0],
                "total_flights": r[1],
                "on_time_rate": r[2],
                "avg_arrival_delay_minutes": r[3],
            }
            for r in rows
        ]
    }


@app.get("/api/airports")
def get_busiest_airports(limit: int = 15):
    """Busiest airports by total flight volume (departures + arrivals combined)."""
    with open_readonly_connection() as connection:
        fast_rows = airport_ranking(connection, limit)
        if fast_rows is not None:
            return {"airports": fast_rows}
        rows = connection.execute(
            """
            WITH per_airport AS (
                SELECT Origin AS airport, 1 AS n FROM flights WHERE Origin IS NOT NULL
                UNION ALL
                SELECT Dest AS airport, 1 AS n FROM flights WHERE Dest IS NOT NULL
            )
            SELECT airport, SUM(n) AS total_flights
            FROM per_airport
            GROUP BY airport
            ORDER BY total_flights DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()

    return {"airports": [{"airport": r[0], "total_flights": r[1]} for r in rows]}


@app.get("/api/aircraft")
def get_busiest_aircraft(limit: int = 15):
    """Busiest aircraft (tail numbers) by total flight volume."""
    with open_readonly_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                Tail_Number AS tail,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE Tail_Number IS NOT NULL AND Tail_Number != ''
            GROUP BY Tail_Number
            ORDER BY total_flights DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()

    return {
        "aircraft": [
            {"tail": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in rows
        ]
    }


@app.get("/api/aircraft/search")
def search_aircraft(
    q: str = Query(..., min_length=1),
    carrier: Optional[str] = Query(None),
    sort: str = Query("flights", pattern="^(flights|alpha)$"),
    limit: int = 300,
):
    """Search tail numbers by prefix, for a typeahead. Returns each match's
    total flight count and its associated carrier. Optionally scoped to a
    single carrier first, which is both faster (a carrier match is highly
    selective) and easier to browse than searching all 8,500+ tails at once."""
    prefix = q.upper().strip() + "%"
    order_clause = "total_flights DESC" if sort == "flights" else "Tail_Number ASC"

    clauses = [
        "Tail_Number ILIKE ?",
        "Tail_Number IS NOT NULL",
        "Tail_Number != ''",
        "Marketing_Airline_Network IS NOT NULL",
    ]
    params: list = [prefix]
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                Tail_Number,
                COUNT(*) AS total_flights,
                ANY_VALUE(Marketing_Airline_Network) AS carrier
            FROM flights
            WHERE {where}
            GROUP BY Tail_Number
            ORDER BY {order_clause}
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

    return {
        "results": [
            {"tail": r[0], "total_flights": r[1], "carrier": r[2]} for r in rows
        ]
    }


@app.get("/api/aircraft-detail")
def aircraft_detail(
    tail: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = 10,
):
    """Full profile for one specific tail number: overall stats, health score,
    operating span, monthly trend, delay causes, and busiest routes flown."""
    tail = tail.upper().strip()

    clauses = ["Tail_Number = ?"]
    params: list = [tail]
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        overview = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                MIN(FlightDate) AS first_flight,
                MAX(FlightDate) AS last_flight,
                COUNT(DISTINCT Marketing_Airline_Network) AS carrier_count,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM flights
            WHERE {where}
            """,
            params,
        ).fetchone()

        if overview is None or overview[0] == 0:
            raise HTTPException(status_code=404, detail="No flights found for that tail number/date range.")

        carrier_rows = connection.execute(
            f"""
            SELECT Marketing_Airline_Network AS carrier, COUNT(*) AS total_flights
            FROM flights
            WHERE {where} AND Marketing_Airline_Network IS NOT NULL
            GROUP BY carrier
            ORDER BY total_flights DESC
            """,
            params,
        ).fetchall()

        trend_rows = connection.execute(
            f"""
            SELECT
                strftime(FlightDate, '%Y-%m') AS year_month,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {where}
            GROUP BY year_month
            ORDER BY year_month
            """,
            params,
        ).fetchall()

        cause_row = connection.execute(
            f"""
            SELECT
                SUM(CarrierDelay) AS carrier,
                SUM(WeatherDelay) AS weather,
                SUM(NASDelay) AS nas,
                SUM(SecurityDelay) AS security,
                SUM(LateAircraftDelay) AS late_aircraft
            FROM flights
            WHERE {where} AND Cancelled = 0
            """,
            params,
        ).fetchone()

        route_rows = connection.execute(
            f"""
            SELECT
                Origin || ' \u2192 ' || Dest AS route,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {where} AND Origin IS NOT NULL AND Dest IS NOT NULL
            GROUP BY Origin, Dest
            ORDER BY total_flights DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

    causes = {
        "Carrier": cause_row[0] or 0,
        "Weather": cause_row[1] or 0,
        "NAS": cause_row[2] or 0,
        "Security": cause_row[3] or 0,
        "Late Aircraft": cause_row[4] or 0,
    }
    cause_total = sum(causes.values()) or 1

    return {
        "tail": tail,
        "total_flights": overview[0],
        "first_flight": str(overview[1]),
        "last_flight": str(overview[2]),
        "carrier_count": overview[3],
        "on_time_rate": overview[4],
        "avg_arrival_delay_minutes": overview[5],
        "cancellation_rate": overview[6],
        "health": compute_health_score(where, params),
        # Only the 72 originally-grounded 737 MAX tails have a known type
        # in this data -- BTS on-time data has no fleet-type field at all,
        # so this is None for every other tail, not "unknown Boeing type."
        "known_aircraft_type": GROUNDED_737_MAX_TAILS.get(tail),
        "carriers": [{"carrier": r[0], "total_flights": r[1]} for r in carrier_rows],
        "months": [
            {"month": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in trend_rows
        ],
        "causes": [
            {"cause": k, "minutes": v, "share": v / cause_total} for k, v in causes.items()
        ],
        "top_routes": [
            {"route": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in route_rows
        ],
    }


# Mirrors config.py's TIGHT_TURNAROUND (25) / TARGET_TURNAROUND (45) minute
# thresholds. Duplicated as local constants rather than imported, since
# api/main.py doesn't currently import from the project-root config module
# and this feature isn't the place to introduce that path untested.
TIGHT_TURNAROUND_MINUTES = 25
TARGET_TURNAROUND_MINUTES = 45


@app.get("/api/delay-propagation")
def delay_propagation_endpoint(
    carrier: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="Defaults to the trailing 12 months of available data"),
    end_date: Optional[str] = Query(None),
):
    """Does a late-arriving aircraft's delay carry over to its next flight?

    IMPORTANT operational note, found via real production testing: this
    endpoint (and /api/delay-propagation-markov, which reuses the same
    sequencing pattern) run LAG/LEAD window functions over Tail_Number,
    FlightDate. Confirmed this endpoint had NO date scoping at all before
    this fix -- it ran over the FULL 59M-row unscoped history on every
    call, including the automatic, unconditional call the Aircraft page
    fires on every page load. That crashed the deployed backend outright
    (confirmed live against production: /api/health itself started
    returning 502 immediately after hitting this endpoint, on a fresh
    request with no prior load). start_date/end_date now default to a
    trailing 12-month window (~7.6M rows, ~7.8x fewer than unscoped) --
    still a real, substantial sample, just no longer processing 8 years
    of history by default. Passing an explicit wider range is still
    possible and this project's disclosure obligation doesn't disappear:
    the scope actually used is reported in the response.
    Sequences each tail's flights within a calendar day by SCHEDULED
    departure time (CRSDepTime, not actual -- ordering by an outcome-
    dependent actual time would risk the same kind of self-referential
    confound that undermined the original queue-pressure attempt), then
    compares each flight's departure delay against its immediate
    predecessor's arrival delay on the same tail, same day. First flight of
    a tail's day has no same-day predecessor and is excluded; overnight-
    boundary rotations (last leg of one day into first leg of the next)
    aren't linked either, which likely understates true propagation
    somewhat but avoids guessing across a day boundary.

    Everything here is computed live from real data, not a pre-calibrated
    composite score. The turnaround-tightness split was meant as a
    mechanism check -- the original prediction was that a genuine aircraft-
    continuity effect should show a STRONGER correlation on tight
    turnarounds (less buffer to absorb a late inbound). Checked directly
    across all 11 carriers, that prediction was wrong: normal turnarounds
    (26-45 min) show the strongest correlation for every single carrier,
    tight turnarounds (<=25 min) are the weakest -- often near zero or
    negative -- for 9 of the 11, and loose turnarounds sit in between.
    Likely explanation (unconfirmed): airlines probably don't schedule a
    <=25-minute turnaround at random -- they reserve it for route/aircraft
    combinations they're confident can reliably execute that fast, so the
    "tight" bucket is a selected sample of especially well-drilled turns,
    not a random sample of risky, undersized buffers. Southwest is the one
    carrier where the tight bucket still shows real propagation, consistent
    with fast standardized turns being its norm rather than the exception.
    Cross-check against this scope's "Late Aircraft" share on the Delays
    page -- BTS's own delay-cause coding is an independent (differently-
    defined, but related) source for the same phenomenon. Optionally
    filtered by marketing carrier."""
    if not start_date or not end_date:
        with open_readonly_connection() as connection:
            max_date = connection.execute("SELECT MAX(FlightDate) FROM flights").fetchone()[0]
        end_date = end_date or str(max_date)
        start_date = start_date or str(date.fromisoformat(str(max_date)) - timedelta(days=365))

    clauses = [
        "FlightDate BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)",
        "Cancelled = 0", "Diverted = 0", "Tail_Number IS NOT NULL", "Tail_Number != ''",
    ]
    params: list = [start_date, end_date]
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        row = connection.execute(
            f"""
            WITH scoped AS (
                SELECT
                    Tail_Number,
                    FlightDate,
                    TRY_CAST(CRSDepTime AS INTEGER) AS crs_dep_hhmm,
                    TRY_CAST(CRSArrTime AS INTEGER) AS crs_arr_hhmm,
                    ArrDelay,
                    DepDelay
                FROM flights
                WHERE {where}
            ),
            minutes AS (
                SELECT
                    Tail_Number,
                    FlightDate,
                    ArrDelay,
                    DepDelay,
                    (crs_dep_hhmm / 100) * 60 + (crs_dep_hhmm % 100) AS crs_dep_minutes,
                    (crs_arr_hhmm / 100) * 60 + (crs_arr_hhmm % 100) AS crs_arr_minutes
                FROM scoped
                WHERE crs_dep_hhmm IS NOT NULL AND crs_arr_hhmm IS NOT NULL
            ),
            sequenced AS (
                SELECT
                    DepDelay,
                    LAG(ArrDelay) OVER (
                        PARTITION BY Tail_Number, FlightDate ORDER BY crs_dep_minutes
                    ) AS predecessor_arr_delay,
                    crs_dep_minutes - LAG(crs_arr_minutes) OVER (
                        PARTITION BY Tail_Number, FlightDate ORDER BY crs_dep_minutes
                    ) AS scheduled_turnaround_minutes
                FROM minutes
            ),
            pairs AS (
                SELECT *
                FROM sequenced
                WHERE predecessor_arr_delay IS NOT NULL AND DepDelay IS NOT NULL
            )
            SELECT
                COUNT(*) AS pairs,
                CORR(predecessor_arr_delay, DepDelay) AS correlation,
                AVG(CASE WHEN predecessor_arr_delay <= 0 THEN DepDelay END) AS avg_dep_delay_predecessor_on_time,
                AVG(CASE WHEN predecessor_arr_delay > 15 THEN DepDelay END) AS avg_dep_delay_predecessor_late_15plus,
                AVG(CASE WHEN predecessor_arr_delay > 60 THEN DepDelay END) AS avg_dep_delay_predecessor_late_60plus,
                CORR(
                    CASE WHEN scheduled_turnaround_minutes IS NOT NULL AND scheduled_turnaround_minutes <= {TIGHT_TURNAROUND_MINUTES} THEN predecessor_arr_delay END,
                    CASE WHEN scheduled_turnaround_minutes IS NOT NULL AND scheduled_turnaround_minutes <= {TIGHT_TURNAROUND_MINUTES} THEN DepDelay END
                ) AS correlation_tight_turnaround,
                COUNT(*) FILTER (WHERE scheduled_turnaround_minutes IS NOT NULL AND scheduled_turnaround_minutes <= {TIGHT_TURNAROUND_MINUTES}) AS pairs_tight_turnaround,
                CORR(
                    CASE WHEN scheduled_turnaround_minutes IS NOT NULL AND scheduled_turnaround_minutes > {TIGHT_TURNAROUND_MINUTES} AND scheduled_turnaround_minutes <= {TARGET_TURNAROUND_MINUTES} THEN predecessor_arr_delay END,
                    CASE WHEN scheduled_turnaround_minutes IS NOT NULL AND scheduled_turnaround_minutes > {TIGHT_TURNAROUND_MINUTES} AND scheduled_turnaround_minutes <= {TARGET_TURNAROUND_MINUTES} THEN DepDelay END
                ) AS correlation_normal_turnaround,
                COUNT(*) FILTER (WHERE scheduled_turnaround_minutes IS NOT NULL AND scheduled_turnaround_minutes > {TIGHT_TURNAROUND_MINUTES} AND scheduled_turnaround_minutes <= {TARGET_TURNAROUND_MINUTES}) AS pairs_normal_turnaround,
                CORR(
                    CASE WHEN scheduled_turnaround_minutes IS NOT NULL AND scheduled_turnaround_minutes > {TARGET_TURNAROUND_MINUTES} THEN predecessor_arr_delay END,
                    CASE WHEN scheduled_turnaround_minutes IS NOT NULL AND scheduled_turnaround_minutes > {TARGET_TURNAROUND_MINUTES} THEN DepDelay END
                ) AS correlation_loose_turnaround,
                COUNT(*) FILTER (WHERE scheduled_turnaround_minutes IS NOT NULL AND scheduled_turnaround_minutes > {TARGET_TURNAROUND_MINUTES}) AS pairs_loose_turnaround
            FROM pairs
            """,
            params,
        ).fetchone()

    if row is None or row[0] == 0:
        raise HTTPException(status_code=404, detail="No same-day multi-leg rotations matched that filter.")

    (
        pairs, correlation,
        avg_on_time, avg_late_15, avg_late_60,
        corr_tight, pairs_tight,
        corr_normal, pairs_normal,
        corr_loose, pairs_loose,
    ) = row

    return {
        "date_range": f"{start_date} to {end_date}",
        "pairs": pairs,
        "correlation": correlation,
        "avg_dep_delay_predecessor_on_time": avg_on_time,
        "avg_dep_delay_predecessor_late_15plus": avg_late_15,
        "avg_dep_delay_predecessor_late_60plus": avg_late_60,
        "turnaround_strata": [
            {"label": f"Tight (\u2264{TIGHT_TURNAROUND_MINUTES} min)", "pairs": pairs_tight, "correlation": corr_tight},
            {"label": f"Normal ({TIGHT_TURNAROUND_MINUTES + 1}\u2013{TARGET_TURNAROUND_MINUTES} min)", "pairs": pairs_normal, "correlation": corr_normal},
            {"label": f"Loose (>{TARGET_TURNAROUND_MINUTES} min)", "pairs": pairs_loose, "correlation": corr_loose},
        ],
    }


@app.get("/api/delay-propagation-markov")
def delay_propagation_markov_endpoint(
    carrier: Optional[str] = Query(None),
    start_state: str = Query("severe", description=f"One of {list(MARKOV_STATES)}"),
    forecast_steps: int = Query(3, ge=1, le=6, description="How many legs ahead to forecast (matrix power)"),
    turnaround_bucket: str = Query("normal", description="'tight', 'normal', or 'loose' -- applied uniformly across all forecasted legs"),
    start_date: Optional[str] = Query(None, description="Defaults to the trailing 12 months of available data"),
    end_date: Optional[str] = Query(None),
):
    """Additive to /api/delay-propagation, NOT a replacement for it -- that
    endpoint's correlation view is still a fine one-step association
    summary. This answers a genuinely different question a single
    correlation coefficient can't: multi-step forecasts like "given this
    flight lands severely delayed, what's the probability the aircraft is
    STILL delayed two legs later," via a real empirical Markov chain and
    matrix powers, not an approximation. See
    api/delay_propagation_markov.py for the full methodology and
    tests/test_delay_propagation_markov.py for verification against
    hand-computed toy examples.

    start_date/end_date default to a trailing 12-month window -- found via
    real production testing that no date scoping at all (the original
    version of this endpoint, and the pre-existing /api/delay-propagation
    it's additive to) crashed the deployed backend outright by running
    window functions over the full ~59M-row unscoped history."""
    result = get_delay_propagation_markov(
        carrier=carrier, start_state=start_state, forecast_steps=forecast_steps, turnaround_bucket=turnaround_bucket,
        start_date=start_date, end_date=end_date,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/decision/propagation-scenario")
def propagation_scenario_endpoint(carrier: Optional[str] = Query(None)):
    """Decision Center: a turnaround-tightness x predecessor-delay grid of
    ACTUAL OBSERVED average knock-on departure delay -- reuses the exact
    same tail/day sequencing CTEs as /api/delay-propagation (same
    same-day-only, scheduled-time-ordered pairing), just grouped instead
    of correlated. Deliberately built on plain historical averages rather
    than a fitted regression: a group-by average doesn't imply causation
    the way a regression slope reads as one, and every cell here is
    something that actually happened in the data, not a projection. This
    is descriptive ("here's what has historically happened under these
    conditions"), not predictive ("here's what would happen if you changed
    your schedule") -- that distinction matters and is stated again in the
    UI, not just here."""
    clauses = ["Cancelled = 0", "Diverted = 0", "Tail_Number IS NOT NULL", "Tail_Number != ''"]
    params: list = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            WITH scoped AS (
                SELECT
                    Tail_Number, FlightDate,
                    TRY_CAST(CRSDepTime AS INTEGER) AS crs_dep_hhmm,
                    TRY_CAST(CRSArrTime AS INTEGER) AS crs_arr_hhmm,
                    ArrDelay, DepDelay
                FROM flights
                WHERE {where}
            ),
            minutes AS (
                SELECT
                    Tail_Number, FlightDate, ArrDelay, DepDelay,
                    (crs_dep_hhmm / 100) * 60 + (crs_dep_hhmm % 100) AS crs_dep_minutes,
                    (crs_arr_hhmm / 100) * 60 + (crs_arr_hhmm % 100) AS crs_arr_minutes
                FROM scoped
                WHERE crs_dep_hhmm IS NOT NULL AND crs_arr_hhmm IS NOT NULL
            ),
            sequenced AS (
                SELECT
                    DepDelay,
                    LAG(ArrDelay) OVER (
                        PARTITION BY Tail_Number, FlightDate ORDER BY crs_dep_minutes
                    ) AS predecessor_arr_delay,
                    crs_dep_minutes - LAG(crs_arr_minutes) OVER (
                        PARTITION BY Tail_Number, FlightDate ORDER BY crs_dep_minutes
                    ) AS scheduled_turnaround_minutes
                FROM minutes
            ),
            pairs AS (
                SELECT *
                FROM sequenced
                WHERE predecessor_arr_delay IS NOT NULL
                    AND DepDelay IS NOT NULL
                    AND scheduled_turnaround_minutes IS NOT NULL
                    AND scheduled_turnaround_minutes > 0
            )
            SELECT
                CASE
                    WHEN scheduled_turnaround_minutes <= {TIGHT_TURNAROUND_MINUTES} THEN 'Tight'
                    WHEN scheduled_turnaround_minutes <= {TARGET_TURNAROUND_MINUTES} THEN 'Normal'
                    ELSE 'Loose'
                END AS turnaround_bucket,
                CASE
                    WHEN predecessor_arr_delay <= 0 THEN 'On time or early'
                    WHEN predecessor_arr_delay <= 60 THEN 'Late (1-60 min)'
                    ELSE 'Very late (60+ min)'
                END AS predecessor_bucket,
                COUNT(*) AS pairs,
                AVG(DepDelay) AS avg_successor_dep_delay
            FROM pairs
            GROUP BY turnaround_bucket, predecessor_bucket
            """,
            params,
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No same-day multi-leg rotations matched that filter.")

    turnaround_order = {"Tight": 0, "Normal": 1, "Loose": 2}
    predecessor_order = {"On time or early": 0, "Late (1-60 min)": 1, "Very late (60+ min)": 2}
    cells = sorted(
        (
            {
                "turnaround_bucket": r[0],
                "predecessor_bucket": r[1],
                "pairs": r[2],
                "avg_successor_dep_delay": r[3],
            }
            for r in rows
        ),
        key=lambda c: (turnaround_order.get(c["turnaround_bucket"], 9), predecessor_order.get(c["predecessor_bucket"], 9)),
    )

    return {
        "carrier": carrier.upper() if carrier else None,
        "tight_turnaround_minutes": TIGHT_TURNAROUND_MINUTES,
        "target_turnaround_minutes": TARGET_TURNAROUND_MINUTES,
        "cells": cells,
    }


def _hhmm_diff_minutes(earlier_hhmm: int, later_hhmm: int) -> int:
    """Minutes between two HHMM clock times on the same calendar day. Does
    not special-case BTS's occasional use of 2400 for midnight -- it still
    resolves to a consistent, monotonically-later value (1440), just not
    literally "0", so diffs stay correct even though the raw value looks
    unusual."""
    earlier_minutes = (earlier_hhmm // 100) * 60 + (earlier_hhmm % 100)
    later_minutes = (later_hhmm // 100) * 60 + (later_hhmm % 100)
    return later_minutes - earlier_minutes


@app.get("/api/aircraft-rotation")
def aircraft_rotation_endpoint(
    tail: str = Query(...),
    date: str = Query(...),
):
    """The actual sequence of flights one tail flew on one calendar day,
    ordered by scheduled departure -- gate-to-gate detail including taxi and
    wheels-off/on times, plus the ground gap (scheduled vs actual) before
    the next leg, which shows directly whether the aircraft made up time on
    the ground or fell further behind. Same-day only (see
    /api/delay-propagation's docstring for why overnight boundaries aren't
    linked). Cancelled/diverted legs are included rather than filtered out,
    since seeing a break in the rotation is itself useful context -- their
    delay/taxi/wheels fields will mostly be null."""
    tail = tail.upper().strip()

    with open_readonly_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                Origin, Dest, Marketing_Airline_Network,
                TRY_CAST(CRSDepTime AS INTEGER) AS crs_dep_time,
                TRY_CAST(DepTime AS INTEGER) AS dep_time,
                DepDelay,
                TRY_CAST(TaxiOut AS DOUBLE) AS taxi_out,
                TRY_CAST(WheelsOff AS INTEGER) AS wheels_off,
                TRY_CAST(WheelsOn AS INTEGER) AS wheels_on,
                TRY_CAST(TaxiIn AS DOUBLE) AS taxi_in,
                TRY_CAST(CRSArrTime AS INTEGER) AS crs_arr_time,
                TRY_CAST(ArrTime AS INTEGER) AS arr_time,
                ArrDelay,
                Cancelled,
                Diverted
            FROM flights
            WHERE Tail_Number = ? AND FlightDate = CAST(? AS DATE)
            ORDER BY TRY_CAST(CRSDepTime AS INTEGER)
            """,
            [tail, date],
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No flights found for that tail number/date.")

    legs = [
        {
            "origin": r[0],
            "dest": r[1],
            "carrier": r[2],
            "crs_dep_time": r[3],
            "dep_time": r[4],
            "dep_delay": r[5],
            "taxi_out": r[6],
            "wheels_off": r[7],
            "wheels_on": r[8],
            "taxi_in": r[9],
            "crs_arr_time": r[10],
            "arr_time": r[11],
            "arr_delay": r[12],
            "cancelled": bool(r[13]),
            "diverted": bool(r[14]),
        }
        for r in rows
    ]

    for i in range(len(legs) - 1):
        current, nxt = legs[i], legs[i + 1]
        current["scheduled_ground_minutes"] = (
            _hhmm_diff_minutes(current["crs_arr_time"], nxt["crs_dep_time"])
            if current["crs_arr_time"] is not None and nxt["crs_dep_time"] is not None
            else None
        )
        current["actual_ground_minutes"] = (
            _hhmm_diff_minutes(current["wheels_on"], nxt["wheels_off"])
            if current["wheels_on"] is not None and nxt["wheels_off"] is not None
            else None
        )
    if legs:
        legs[-1]["scheduled_ground_minutes"] = None
        legs[-1]["actual_ground_minutes"] = None

    return {"tail": tail, "date": date, "legs": legs}


@app.get("/api/routes")
def get_busiest_routes(limit: int = 15):
    """Busiest directional routes (origin -> destination) by flight volume,
    with on-time rate for each route."""
    with open_readonly_connection() as connection:
        fast_rows = route_ranking(connection, limit)
        if fast_rows is not None:
            return {"routes": fast_rows}
        rows = connection.execute(
            """
            SELECT
                Origin || ' \u2192 ' || Dest AS route,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE Origin IS NOT NULL AND Dest IS NOT NULL
            GROUP BY Origin, Dest
            ORDER BY total_flights DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()

    return {
        "routes": [
            {"route": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in rows
        ]
    }


@app.get("/api/airports/list")
def list_all_airports():
    """Every distinct airport code that appears as an origin or destination,
    for populating a search/select control (not ranked, just the full set)."""
    with open_readonly_connection() as connection:
        fast_airports = airport_list(connection)
        if fast_airports is not None:
            return {"airports": fast_airports}
        rows = connection.execute(
            """
            SELECT DISTINCT airport FROM (
                SELECT Origin AS airport FROM flights WHERE Origin IS NOT NULL
                UNION
                SELECT Dest AS airport FROM flights WHERE Dest IS NOT NULL
            )
            ORDER BY airport
            """
        ).fetchall()
    return {"airports": [r[0] for r in rows]}


@app.get("/api/route-detail")
def route_detail(
    origin: str = Query(...),
    dest: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """Full profile for one specific directional route: overall stats, monthly
    trend, delay-cause breakdown, and which carriers fly it."""
    origin = origin.upper()
    dest = dest.upper()

    clauses = ["Origin = ?", "Dest = ?"]
    params: list = [origin, dest]
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        overview = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate,
                MAX(Distance) AS distance
            FROM flights
            WHERE {where}
            """,
            params,
        ).fetchone()

        if overview is None or overview[0] == 0:
            raise HTTPException(status_code=404, detail="No flights found for that route/date range.")

        trend_rows = connection.execute(
            f"""
            SELECT
                strftime(FlightDate, '%Y-%m') AS year_month,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {where}
            GROUP BY year_month
            ORDER BY year_month
            """,
            params,
        ).fetchall()

        cause_row = connection.execute(
            f"""
            SELECT
                SUM(CarrierDelay) AS carrier,
                SUM(WeatherDelay) AS weather,
                SUM(NASDelay) AS nas,
                SUM(SecurityDelay) AS security,
                SUM(LateAircraftDelay) AS late_aircraft
            FROM flights
            WHERE {where} AND Cancelled = 0
            """,
            params,
        ).fetchone()

        carrier_rows = connection.execute(
            f"""
            SELECT
                Marketing_Airline_Network AS carrier,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {where} AND Marketing_Airline_Network IS NOT NULL
            GROUP BY carrier
            ORDER BY total_flights DESC
            """,
            params,
        ).fetchall()

    causes = {
        "Carrier": cause_row[0] or 0,
        "Weather": cause_row[1] or 0,
        "NAS": cause_row[2] or 0,
        "Security": cause_row[3] or 0,
        "Late Aircraft": cause_row[4] or 0,
    }
    cause_total = sum(causes.values()) or 1

    return {
        "origin": origin,
        "dest": dest,
        "total_flights": overview[0],
        "on_time_rate": overview[1],
        "avg_arrival_delay_minutes": overview[2],
        "cancellation_rate": overview[3],
        "distance_miles": overview[4],
        "health": compute_health_score(where, params),
        "months": [
            {"month": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in trend_rows
        ],
        "causes": [
            {"cause": k, "minutes": v, "share": v / cause_total} for k, v in causes.items()
        ],
        "carriers": [
            {"carrier": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in carrier_rows
        ],
    }


@app.get("/api/route-forecast")
def route_forecast(
    origin: str = Query(...),
    dest: str = Query(...),
    carrier: Optional[str] = Query(None),
    departure_hour: Optional[int] = Query(None, ge=0, le=23),
):
    """Return a transparent historical delay baseline for one route scenario.

    This is deliberately not presented as a weather or machine-learning
    forecast.  It answers the first useful question from the public view:
    "How have comparable flights performed historically?"  If the most
    specific route + carrier + departure-hour slice is too small, step back
    to a larger route slice and disclose that fallback in the response.
    """
    origin = origin.upper()
    dest = dest.upper()
    carrier = carrier.upper() if carrier else None

    base_clauses = ["Origin = ?", "Dest = ?"]
    base_params: list = [origin, dest]

    # Try the most specific useful comparison first.  A minimum of 30
    # completed flights avoids presenting a handful of flights as a stable
    # expectation while keeping common routes easy to explore.
    candidates: list[tuple[str, list[str], list]] = []
    if carrier and departure_hour is not None:
        candidates.append(("route + airline + departure hour", [*base_clauses, "Marketing_Airline_Network = ?", "CAST(FLOOR(CRSDepTime / 100) AS INTEGER) = ?"], [*base_params, carrier, departure_hour]))
    if carrier:
        candidates.append(("route + airline", [*base_clauses, "Marketing_Airline_Network = ?"], [*base_params, carrier]))
    if departure_hour is not None:
        candidates.append(("route + departure hour", [*base_clauses, "CAST(FLOOR(CRSDepTime / 100) AS INTEGER) = ?"], [*base_params, departure_hour]))
    candidates.append(("route", [*base_clauses], [*base_params]))

    result = None
    matched_scope = "route"
    with open_readonly_connection() as connection:
        # The exact, most-specific slice is pre-aggregated during the warehouse
        # build. Use it when available so the common public-view question does
        # not rescan the tens-of-millions-row raw table.
        if carrier and departure_hour is not None:
            fast = route_hour_baseline(connection, origin, dest, carrier, departure_hour)
            if fast and fast["completed_flights"] >= 30:
                result = (
                    fast["total_flights"], fast["completed_flights"], fast["on_time_rate"],
                    fast["avg_arrival_delay_minutes"], fast["median_arrival_delay_minutes"],
                    fast["p90_arrival_delay_minutes"], fast["cancellation_rate"],
                )
                matched_scope = "route + airline + departure hour"

        for scope, clauses, params in candidates:
            if result is not None:
                break
            where = " AND ".join(clauses)
            row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS total_flights,
                    COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS completed_flights,
                    AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                    AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                    quantile_cont(ArrDelay, 0.50) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS median_arrival_delay_minutes,
                    quantile_cont(ArrDelay, 0.90) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS p90_arrival_delay_minutes,
                    AVG(Cancelled * 1.0) AS cancellation_rate
                FROM flights
                WHERE {where}
                """,
                params,
            ).fetchone()
            if row and row[0] and row[1] >= 30:
                result = row
                matched_scope = scope
                break

        if result is None:
            # Return the route-level row when the route exists but all slices
            # are small; this produces a useful answer with an honest sample
            # size instead of a misleading 404.
            where = " AND ".join(base_clauses)
            result = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS total_flights,
                    COUNT(*) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS completed_flights,
                    AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                    AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                    quantile_cont(ArrDelay, 0.50) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS median_arrival_delay_minutes,
                    quantile_cont(ArrDelay, 0.90) FILTER (WHERE Cancelled = 0 AND ArrDelay IS NOT NULL) AS p90_arrival_delay_minutes,
                    AVG(Cancelled * 1.0) AS cancellation_rate
                FROM flights
                WHERE {where}
                """,
                base_params,
            ).fetchone()

    if not result or not result[0]:
        raise HTTPException(status_code=404, detail="No flights found for that route.")

    requested_scope = "route"
    if carrier and departure_hour is not None:
        requested_scope = "route + airline + departure hour"
    elif carrier:
        requested_scope = "route + airline"
    elif departure_hour is not None:
        requested_scope = "route + departure hour"

    completed = int(result[1] or 0)
    if completed >= 500:
        confidence = "strong historical sample"
    elif completed >= 100:
        confidence = "useful historical sample"
    else:
        confidence = "small historical sample"

    return {
        "origin": origin,
        "dest": dest,
        "carrier": carrier,
        "departure_hour": departure_hour,
        "requested_scope": requested_scope,
        "matched_scope": matched_scope,
        "used_fallback": matched_scope != requested_scope,
        "total_flights": int(result[0]),
        "completed_flights": completed,
        "on_time_rate": result[2],
        "avg_arrival_delay_minutes": result[3],
        "median_arrival_delay_minutes": result[4],
        "p90_arrival_delay_minutes": result[5],
        "cancellation_rate": result[6],
        "confidence": confidence,
        "interpretation": "A historical baseline from comparable BTS flights. It is not a promise and does not yet use weather, live conditions, or a machine-learning model.",
    }


@app.get("/api/carrier-detail")
def carrier_detail(
    carrier: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = 10,
):
    """Full profile for one specific carrier: overall stats, monthly trend,
    delay causes, and busiest routes/airports. Brought up to parity with
    /api/airport-detail's completeness -- this used to be thinner, relying
    on the frontend to separately call /api/summary, /api/trend, and
    /api/delay-causes with carrier= set, which worked for the existing
    lookup flow but wasn't a single self-contained profile."""
    carrier = carrier.upper()

    clauses = ["Marketing_Airline_Network = ?"]
    params: list = [carrier]
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        overview = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM flights
            WHERE {where}
            """,
            params,
        ).fetchone()

        if overview is None or overview[0] == 0:
            raise HTTPException(status_code=404, detail="No flights found for that carrier/date range.")

        trend_rows = connection.execute(
            f"""
            SELECT
                strftime(FlightDate, '%Y-%m') AS year_month,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {where}
            GROUP BY year_month
            ORDER BY year_month
            """,
            params,
        ).fetchall()

        cause_row = connection.execute(
            f"""
            SELECT
                SUM(CarrierDelay) AS carrier,
                SUM(WeatherDelay) AS weather,
                SUM(NASDelay) AS nas,
                SUM(SecurityDelay) AS security,
                SUM(LateAircraftDelay) AS late_aircraft
            FROM flights
            WHERE {where} AND Cancelled = 0
            """,
            params,
        ).fetchone()

        route_rows = connection.execute(
            f"""
            SELECT
                Origin || ' \u2192 ' || Dest AS route,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {where} AND Origin IS NOT NULL AND Dest IS NOT NULL
            GROUP BY Origin, Dest
            ORDER BY total_flights DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

        airport_rows = connection.execute(
            f"""
            WITH per_airport AS (
                SELECT Origin AS airport, 1 AS n FROM flights WHERE {where} AND Origin IS NOT NULL
                UNION ALL
                SELECT Dest AS airport, 1 AS n FROM flights WHERE {where} AND Dest IS NOT NULL
            )
            SELECT airport, SUM(n) AS total_flights
            FROM per_airport
            GROUP BY airport
            ORDER BY total_flights DESC
            LIMIT ?
            """,
            params + params + [limit],
        ).fetchall()

    causes = {
        "Carrier": cause_row[0] or 0,
        "Weather": cause_row[1] or 0,
        "NAS": cause_row[2] or 0,
        "Security": cause_row[3] or 0,
        "Late Aircraft": cause_row[4] or 0,
    }
    cause_total = sum(causes.values()) or 1

    return {
        "carrier": carrier,
        "total_flights": overview[0],
        "on_time_rate": overview[1],
        "avg_arrival_delay_minutes": overview[2],
        "cancellation_rate": overview[3],
        "health": compute_health_score(where, params),
        "months": [
            {"month": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in trend_rows
        ],
        "causes": [
            {"cause": k, "minutes": v, "share": v / cause_total} for k, v in causes.items()
        ],
        "top_routes": [
            {"route": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in route_rows
        ],
        "top_airports": [{"airport": r[0], "total_flights": r[1]} for r in airport_rows],
    }


@app.get("/api/airport-detail")
def airport_detail(
    airport: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = 10,
):
    """Full profile for one specific airport: combined + inbound/outbound
    stats, monthly trend, delay causes, and busiest routes through it."""
    airport = airport.upper()

    date_clauses = []
    date_params: list = []
    if start_date:
        date_clauses.append("FlightDate >= CAST(? AS DATE)")
        date_params.append(start_date)
    if end_date:
        date_clauses.append("FlightDate <= CAST(? AS DATE)")
        date_params.append(end_date)
    date_where = (" AND " + " AND ".join(date_clauses)) if date_clauses else ""

    combined_where = f"(Origin = ? OR Dest = ?){date_where}"
    combined_params = [airport, airport] + date_params

    with open_readonly_connection() as connection:
        overview = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM flights
            WHERE {combined_where}
            """,
            combined_params,
        ).fetchone()

        if overview is None or overview[0] == 0:
            raise HTTPException(status_code=404, detail="No flights found for that airport/date range.")

        # City/state for the profile page's identity header. BTS's on-time
        # data includes OriginCityName/OriginState/DestCityName/DestState
        # as standard fields -- unconfirmed against this specific warehouse
        # as of writing this, so this is wrapped defensively: if the
        # columns turn out to be named differently, this single query
        # fails and falls back to None rather than breaking the whole
        # endpoint.
        #
        # OriginCityName/DestCityName come formatted as "City, ST" already
        # (confirmed from a real DESCRIBE of this warehouse -- BTS bakes
        # the state into the city name field) -- split off just the city
        # part, since the frontend appends OriginState/DestState itself and
        # was otherwise showing "Chicago, IL, IL".
        city_state = None
        try:
            city_state = connection.execute(
                """
                SELECT city, state, COUNT(*) AS n FROM (
                    SELECT split_part(OriginCityName, ',', 1) AS city, OriginState AS state FROM flights WHERE Origin = ?
                    UNION ALL
                    SELECT split_part(DestCityName, ',', 1) AS city, DestState AS state FROM flights WHERE Dest = ?
                ) combined
                WHERE city IS NOT NULL AND state IS NOT NULL
                GROUP BY city, state
                ORDER BY n DESC
                LIMIT 1
                """,
                [airport, airport],
            ).fetchone()
        except Exception:
            city_state = None

        def direction_stats(column: str):
            where = f"{column} = ?{date_where}"
            params = [airport] + date_params
            row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS total_flights,
                    AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                    AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes
                FROM flights
                WHERE {where}
                """,
                params,
            ).fetchone()
            return {
                "total_flights": row[0] or 0,
                "on_time_rate": row[1],
                "avg_arrival_delay_minutes": row[2],
            }

        outbound = direction_stats("Origin")
        inbound = direction_stats("Dest")

        trend_rows = connection.execute(
            f"""
            SELECT
                strftime(FlightDate, '%Y-%m') AS year_month,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {combined_where}
            GROUP BY year_month
            ORDER BY year_month
            """,
            combined_params,
        ).fetchall()

        cause_row = connection.execute(
            f"""
            SELECT
                SUM(CarrierDelay) AS carrier,
                SUM(WeatherDelay) AS weather,
                SUM(NASDelay) AS nas,
                SUM(SecurityDelay) AS security,
                SUM(LateAircraftDelay) AS late_aircraft
            FROM flights
            WHERE {combined_where} AND Cancelled = 0
            """,
            combined_params,
        ).fetchone()

        route_rows = connection.execute(
            f"""
            SELECT
                Origin || ' \u2192 ' || Dest AS route,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {combined_where}
            GROUP BY Origin, Dest
            ORDER BY total_flights DESC
            LIMIT ?
            """,
            combined_params + [limit],
        ).fetchall()

    causes = {
        "Carrier": cause_row[0] or 0,
        "Weather": cause_row[1] or 0,
        "NAS": cause_row[2] or 0,
        "Security": cause_row[3] or 0,
        "Late Aircraft": cause_row[4] or 0,
    }
    cause_total = sum(causes.values()) or 1

    return {
        "airport": airport,
        "city": city_state[0] if city_state else None,
        "state": city_state[1] if city_state else None,
        "total_flights": overview[0],
        "on_time_rate": overview[1],
        "avg_arrival_delay_minutes": overview[2],
        "cancellation_rate": overview[3],
        "health": compute_health_score(combined_where, combined_params),
        "outbound": outbound,
        "inbound": inbound,
        "months": [
            {"month": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in trend_rows
        ],
        "causes": [
            {"cause": k, "minutes": v, "share": v / cause_total} for k, v in causes.items()
        ],
        "top_routes": [
            {"route": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in route_rows
        ],
    }


@app.get("/api/data-health")
def data_health():
    """Facts about the warehouse itself -- coverage, size, gaps -- so visitors
    can see the data is real and current rather than just trusting it blindly."""
    with open_readonly_connection() as connection:
        overview = connection.execute(
            """
            SELECT
                COUNT(*) AS total_flights,
                MIN(FlightDate) AS start_date,
                MAX(FlightDate) AS end_date,
                COUNT(DISTINCT Marketing_Airline_Network) AS carrier_count,
                COUNT(DISTINCT strftime(FlightDate, '%Y-%m')) AS months_covered
            FROM flights
            """
        ).fetchone()

        months_present = {
            r[0]
            for r in connection.execute(
                "SELECT DISTINCT strftime(FlightDate, '%Y-%m') FROM flights"
            ).fetchall()
        }

        carrier_rows = connection.execute(
            """
            SELECT
                Marketing_Airline_Network AS carrier,
                COUNT(*) AS total_flights,
                MIN(FlightDate) AS start_date,
                MAX(FlightDate) AS end_date
            FROM flights
            WHERE Marketing_Airline_Network IS NOT NULL
            GROUP BY carrier
            ORDER BY total_flights DESC
            """
        ).fetchall()

        column_count = connection.execute(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'flights'"
        ).fetchone()[0]

    # Find any gaps in monthly coverage between the first and last month present.
    start = datetime.strptime(str(overview[1]), "%Y-%m-%d")
    end = datetime.strptime(str(overview[2]), "%Y-%m-%d")
    expected_months = []
    cursor = start.replace(day=1)
    end_marker = end.replace(day=1)
    while cursor <= end_marker:
        expected_months.append(cursor.strftime("%Y-%m"))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    missing_months = [m for m in expected_months if m not in months_present]

    warehouse_size_mb = None
    try:
        warehouse_size_mb = round(database_path().stat().st_size / (1024 * 1024), 1)
    except OSError:
        pass

    # Surfaces pipeline/auto_update.py's last run, so the automated check is
    # visible on the site itself, not just in a log file. None of these
    # fields exist until auto_update.py has actually run at least once.
    pipeline_state = None
    try:
        if PIPELINE_STATE_FILE.exists():
            pipeline_state = json.loads(PIPELINE_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        pipeline_state = None

    return {
        "total_flights": overview[0],
        "start_date": str(overview[1]),
        "end_date": str(overview[2]),
        "carrier_count": overview[3],
        "months_covered": overview[4],
        "expected_months": len(expected_months),
        "missing_months": missing_months,
        "column_count": column_count,
        "warehouse_size_mb": warehouse_size_mb,
        "last_automated_check": (
            {
                "checked_at": pipeline_state.get("last_checked"),
                "result": pipeline_state.get("last_result"),
                "months_added": pipeline_state.get("last_months_added", []),
            }
            if pipeline_state
            else None
        ),
        "carriers": [
            {
                "carrier": r[0],
                "total_flights": r[1],
                "start_date": str(r[2]),
                "end_date": str(r[3]),
            }
            for r in carrier_rows
        ],
    }


@app.get("/api/data-sources")
def data_sources():
    """Expose provenance and availability of non-flight BTS datasets.

    A missing enrichment table is reported as ``not_loaded``. The API never
    fabricates a fallback value when T-100 or a support table has not been
    downloaded and validated yet.
    """
    from pipeline.bts_sources import DATASETS

    with open_readonly_connection() as connection:
        manifest_exists = connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = 'bts_dataset_manifest'
            """
        ).fetchone()[0]
        manifest_rows = {}
        if manifest_exists:
            manifest_rows = {
                row[0]: {
                    "table_name": row[1],
                    "status": row[2],
                    "row_count": row[3],
                    "loaded_at_utc": str(row[4]) if row[4] else None,
                }
                for row in connection.execute(
                    """
                    SELECT dataset, table_name, status, row_count, loaded_at_utc
                    FROM bts_dataset_manifest
                    """
                ).fetchall()
            }

    return {
        "sources": [
            {
                "dataset": dataset.key,
                "label": dataset.label,
                "description": dataset.description,
                "grain": dataset.grain,
                "cadence": dataset.cadence,
                "source_url": dataset.url,
                **manifest_rows.get(
                    dataset.key,
                    {
                        "table_name": None,
                        "status": "not_loaded",
                        "row_count": 0,
                        "loaded_at_utc": None,
                    },
                ),
            }
            for dataset in DATASETS.values()
        ],
        "note": "All values are sourced from BTS downloads or explicit derived aggregates; no synthetic enrichment is used.",
    }


@app.get("/api/capacity/summary")
def capacity_summary(
    carrier: Optional[str] = Query(None),
    origin: Optional[str] = Query(None, min_length=3, max_length=3),
    dest: Optional[str] = Query(None, min_length=3, max_length=3),
    limit: int = Query(25, ge=1, le=100),
):
    """Return real BTS T-100 route-month capacity context when loaded.

    T-100 is aggregated before this endpoint is queried. This avoids the
    common mistake of attaching a monthly passenger/seat total to every
    flight row and thereby multiplying the data.
    """
    clauses = []
    params: list = []
    if carrier:
        clauses.append("UniqueCarrier = ?")
        params.append(carrier.upper())
    if origin:
        clauses.append("Origin = ?")
        params.append(origin.upper())
    if dest:
        clauses.append("Dest = ?")
        params.append(dest.upper())
    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    with open_readonly_connection() as connection:
        exists = connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.views
            WHERE table_name = 'bts_t100_segment_route_month'
            """
        ).fetchone()[0]
        if not exists:
            raise HTTPException(
                status_code=503,
                detail="BTS T-100 Segment is not loaded. Run the BTS enrichment download, clean, and load steps first.",
            )

        overview = connection.execute(
            f"""
            SELECT
                COUNT(*) AS route_month_rows,
                SUM(departures_scheduled),
                SUM(departures_performed),
                SUM(seats_available),
                SUM(passengers),
                MIN(Year),
                MAX(Year)
            FROM bts_t100_segment_route_month
            {where}
            """,
            params,
        ).fetchone()
        rows = connection.execute(
            f"""
            SELECT
                Year,
                Month,
                UniqueCarrier AS carrier,
                Origin,
                Dest,
                departures_scheduled,
                departures_performed,
                seats_available,
                passengers,
                load_factor,
                completion_rate,
                source_rows
            FROM bts_t100_segment_route_month
            {where}
            ORDER BY passengers DESC NULLS LAST, seats_available DESC NULLS LAST
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()

    return {
        "source": "BTS T-100 Domestic Segment",
        "grain": "carrier + route + month (aircraft/service-class rows aggregated)",
        "filters": {"carrier": carrier, "origin": origin, "dest": dest},
        "overview": {
            "route_month_rows": overview[0],
            "departures_scheduled": overview[1],
            "departures_performed": overview[2],
            "seats_available": overview[3],
            "passengers": overview[4],
            "first_year": overview[5],
            "last_year": overview[6],
            "load_factor": (
                overview[4] / overview[3]
                if overview[3] not in (None, 0) and overview[4] is not None
                else None
            ),
            "completion_rate": (
                overview[2] / overview[1]
                if overview[1] not in (None, 0) and overview[2] is not None
                else None
            ),
        },
        "rows": [
            {
                "year": row[0],
                "month": row[1],
                "carrier": row[2],
                "origin": row[3],
                "dest": row[4],
                "departures_scheduled": row[5],
                "departures_performed": row[6],
                "seats_available": row[7],
                "passengers": row[8],
                "load_factor": row[9],
                "completion_rate": row[10],
                "source_rows": row[11],
            }
            for row in rows
        ],
    }


@app.get("/api/capacity/correlation")
def capacity_correlation(
    carrier: Optional[str] = Query(None),
    limit: int = Query(30, ge=5, le=100),
    minimum_flights: int = Query(100, ge=1, le=10000),
):
    """Compare T-100 route-month traffic/capacity with OTP at the same grain.

    T-100 is monthly aggregate data, so this endpoint first aggregates the
    flight-level OTP table to carrier + route + month and then joins the two
    native-grain datasets. It deliberately does not attach a month's seats or
    passengers to individual flights. The correlation is an exploratory
    association, not a causal claim.
    """
    carrier_value = carrier.upper().strip() if isinstance(carrier, str) and carrier else None
    carrier_clause = "AND Marketing_Airline_Network = ?" if carrier_value else ""
    t100_clause = "WHERE UniqueCarrier = ?" if carrier_value else ""
    with open_readonly_connection() as connection:
        exists = connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.views
            WHERE table_name = 'bts_t100_segment_route_month'
            """
        ).fetchone()[0]
        if not exists:
            raise HTTPException(
                status_code=503,
                detail="BTS T-100 Segment is not loaded. Run the BTS enrichment download, clean, and load steps first.",
            )

        query = f"""
            WITH otp_route_month AS (
                SELECT
                    Marketing_Airline_Network AS carrier,
                    Origin,
                    Dest,
                    YEAR(FlightDate) AS Year,
                    MONTH(FlightDate) AS Month,
                    COUNT(*) AS otp_flights,
                    SUM(CASE WHEN {COMPLETED_FLIGHT_SQL} THEN 1 ELSE 0 END) AS completed_flights,
                    AVG(CASE WHEN {COMPLETED_FLIGHT_SQL}
                        THEN CASE WHEN {ON_TIME_FLAG_SQL} THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                    AVG(CASE WHEN {COMPLETED_FLIGHT_SQL} THEN ArrDelay END) AS avg_arrival_delay
                FROM flights
                WHERE Marketing_Airline_Network IS NOT NULL
                    {carrier_clause}
                GROUP BY ALL
                HAVING COUNT(*) >= ?
            ), matched AS (
                SELECT
                    t.Year,
                    t.Month,
                    t.UniqueCarrier AS carrier,
                    t.Origin,
                    t.Dest,
                    t.departures_scheduled,
                    t.departures_performed,
                    t.seats_available,
                    t.passengers,
                    t.load_factor,
                    t.completion_rate,
                    o.otp_flights,
                    o.completed_flights,
                    o.on_time_rate,
                    o.avg_arrival_delay
                FROM bts_t100_segment_route_month t
                INNER JOIN otp_route_month o
                    ON o.carrier = t.UniqueCarrier
                    AND o.Origin = t.Origin
                    AND o.Dest = t.Dest
                    AND o.Year = t.Year
                    AND o.Month = t.Month
                {t100_clause}
            )
            SELECT * FROM matched
        """
        params = [carrier_value, minimum_flights] if carrier_value else [minimum_flights]
        # The optional carrier predicate appears in the OTP CTE before the
        # minimum-flight HAVING parameter. The T-100 predicate, when present,
        # is intentionally appended after that parameter.
        if carrier_value:
            params.append(carrier_value)
        overview = connection.execute(
            f"""
            SELECT
                COUNT(*) AS matched_route_months,
                AVG(load_factor),
                AVG(on_time_rate),
                AVG(avg_arrival_delay),
                CORR(load_factor, on_time_rate),
                CORR(passengers, on_time_rate),
                CORR(seats_available, on_time_rate),
                MIN(Year * 100 + Month),
                MAX(Year * 100 + Month)
            FROM ({query}) matched
            """,
            params,
        ).fetchone()
        rows = connection.execute(
            f"""
            SELECT *
            FROM ({query}) matched
            ORDER BY passengers DESC NULLS LAST, Year DESC, Month DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()

    row_keys = [
        "year", "month", "carrier", "origin", "dest", "departures_scheduled",
        "departures_performed", "seats_available", "passengers", "load_factor",
        "completion_rate", "otp_flights", "completed_flights", "on_time_rate",
        "avg_arrival_delay",
    ]
    return {
        "status": "ok" if overview[0] else "no_matching_route_months",
        "source": "BTS T-100 Domestic Segment + BTS Marketing Carrier On-Time Performance",
        "grain": "carrier + origin + destination + month",
        "filters": {"carrier": carrier_value, "minimum_otp_flights": minimum_flights},
        "overview": {
            "matched_route_months": overview[0],
            "average_load_factor": overview[1],
            "average_on_time_rate": overview[2],
            "average_arrival_delay": overview[3],
            "correlation_load_factor_on_time": overview[4],
            "correlation_passengers_on_time": overview[5],
            "correlation_seats_on_time": overview[6],
            "first_period": overview[7],
            "last_period": overview[8],
        },
        "rows": [dict(zip(row_keys, row)) for row in rows],
        "methodology": {
            "association": "Pearson correlation across matched route-month observations. Values near +1 move together, values near -1 move oppositely, and values near 0 show weak linear association.",
            "interpretation": "This does not prove that fuller flights cause delays. Route mix, season, weather, airport congestion, and carrier scheduling can affect both measurements.",
            "join_policy": "T-100 monthly aggregates are matched to OTP after OTP is aggregated to the same carrier/route/month grain; monthly T-100 values are never copied onto individual flight rows.",
            "missing_data": "Only matched route-months with at least the requested number of OTP flights are included.",
        },
    }


@app.get("/api/queue-pressure")
def queue_pressure_endpoint(
    airport: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
):
    """Hourly congestion/queue-pressure profile for one airport.

    Defaults to the trailing configured lookback rather than the entire
    warehouse. One recent year gives the estimator enough observed days while
    preventing an accidental full-history scan on every profile load.
    """
    if not start_date or not end_date:
        with open_readonly_connection() as connection:
            row = connection.execute("SELECT MIN(FlightDate), MAX(FlightDate) FROM flights").fetchone()
        end_value = date.fromisoformat(str(row[1]))
        default_start = max(date.fromisoformat(str(row[0])), end_value - timedelta(days=DEFAULT_HEAVY_LOOKBACK_DAYS))
        start_date = start_date or str(default_start)
        end_date = end_date or str(row[1])

    try:
        result = get_queue_pressure(
            start_date=start_date, end_date=end_date, airport=airport, carrier=carrier
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if result["status"] == "no_data":
        raise HTTPException(status_code=404, detail="No departure data found for that airport/date range.")

    return result


@app.get("/api/schedule-padding")
def schedule_padding_endpoint(
    carrier: Optional[str] = Query(None),
    airport: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    granularity: str = Query("year", pattern="^(year|month|week|day)$"),
):
    """Scheduled vs actual flight time over time -- is the gap ('padding')
    growing? If carriers pad schedules to inflate on-time stats, scheduled
    elapsed time should creep up even though actual flight times aren't
    changing much. granularity controls the trend's resolution: a single
    year filtered to "year" granularity collapses to one point, so month or
    week granularity matters most for narrow date ranges."""
    clauses = [
        "Cancelled = 0",
        "CRSElapsedTime IS NOT NULL",
        "ActualElapsedTime IS NOT NULL",
        "CRSElapsedTime > 0",
        "ActualElapsedTime > 0",
    ]
    params: list = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    if granularity == "day":
        period_expr = "strftime(FlightDate, '%Y-%m-%d')"
    elif granularity == "week":
        period_expr = "strftime(date_trunc('week', FlightDate), '%Y-%m-%d')"
    elif granularity == "month":
        period_expr = "strftime(date_trunc('month', FlightDate), '%Y-%m')"
    else:
        period_expr = "CAST(EXTRACT(YEAR FROM FlightDate) AS VARCHAR)"

    with open_readonly_connection() as connection:
        overview = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                AVG(CRSElapsedTime) AS avg_scheduled_minutes,
                AVG(ActualElapsedTime) AS avg_actual_minutes
            FROM flights
            WHERE {where}
            """,
            params,
        ).fetchone()

        if overview is None or overview[0] == 0:
            raise HTTPException(status_code=404, detail="No flights matched that filter.")

        period_rows = connection.execute(
            f"""
            SELECT
                {period_expr} AS period,
                COUNT(*) AS total_flights,
                AVG(CRSElapsedTime) AS avg_scheduled_minutes,
                AVG(ActualElapsedTime) AS avg_actual_minutes
            FROM flights
            WHERE {where}
            GROUP BY period
            ORDER BY period
            """,
            params,
        ).fetchall()

    return {
        "total_flights": overview[0],
        "avg_scheduled_minutes": overview[1],
        "avg_actual_minutes": overview[2],
        "avg_padding_minutes": overview[1] - overview[2],
        "granularity": granularity,
        "periods": [
            {
                "period": r[0],
                "total_flights": r[1],
                "avg_scheduled_minutes": r[2],
                "avg_actual_minutes": r[3],
                "padding_minutes": r[2] - r[3],
            }
            for r in period_rows
        ],
        "trend_analysis": get_schedule_padding_trend(where, params),
    }


@app.post("/api/copilot/chat", dependencies=[Depends(rate_limit_copilot)])
def copilot_chat(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    try:
        return ask_copilot(request.message, tier=request.tier, history=request.history)
    except CopilotError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/copilot/chat/stream", dependencies=[Depends(rate_limit_copilot)])
def copilot_chat_stream(request: ChatRequest):
    """SSE version of /api/copilot/chat -- streams stage events (tool_start,
    tool_complete, answer_start, answer_chunk, done/error) as the pipeline
    runs, so the frontend can show live tool-call status and reveal the
    final answer token-by-token instead of waiting for one blocking
    response."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    def event_stream():
        try:
            for event in stream_copilot(request.message, history=request.history, tier=request.tier):
                yield f"data: {json.dumps(event)}\n\n"
        except CopilotError as exc:
            yield f"data: {json.dumps({'stage': 'error', 'message': str(exc)})}\n\n"
        except Exception as exc:
            # Anything not already a CopilotError (a bad DuckDB query, an
            # unexpected argument type from the model, etc.) used to kill
            # the SSE stream silently -- the connection would just end with
            # no "done" or "error" event, leaving the frontend stuck with no
            # way to show what happened. Surface it as a real error instead.
            yield f"data: {json.dumps({'stage': 'error', 'message': f'{type(exc).__name__}: {exc}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
