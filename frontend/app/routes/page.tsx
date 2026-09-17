"use client";

import { useState, useEffect } from "react";
import RouteChart from "../components/RouteChart";
import DateRangePreset from "../components/DateRangePreset";
import PublicPageGuide from "../components/PublicPageGuide";
import { Health } from "../lib/health";
import TrendChart from "../components/TrendChart";
import DelayCauseChart from "../components/DelayCauseChart";
import { CARRIER_NAMES, carrierName } from "../lib/carriers";
import HealthBadge from "../components/HealthBadge";
import DiversionLandingChart from "../components/DiversionLandingChart";
import { formatNumber, formatPercent } from "../lib/format";
import { useMode } from "../lib/mode";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

type Route = { route: string; total_flights: number; on_time_rate: number };
type Cause = { cause: string; minutes: number; share: number };
type MonthPoint = { month: string; total_flights: number; on_time_rate: number };
type RouteCarrier = { carrier: string; total_flights: number; on_time_rate: number };
type T100TrafficContext = {
  status: string;
  model: string;
  target_period: string;
  reference_period: string | null;
  traffic_scope: string;
  load_factor: number | null;
  traffic_band: string | null;
  passengers: number | null;
  seats_available: number | null;
  completion_rate: number | null;
  reference_staleness_months: number | null;
  baseline_expected_delay_minutes: number | null;
  baseline_late_probability: number | null;
  traffic_expected_delay_minutes: number | null;
  traffic_late_probability: number | null;
  delta_expected_delay_minutes: number | null;
  delta_late_probability: number | null;
  matched_months: number;
  matched_completed_flights: number;
  matched_late_flights: number;
  minimum_traffic_match_months: number;
  reason?: string;
};
type RouteForecast = {
  origin: string;
  dest: string;
  carrier: string | null;
  departure_hour: number | null;
  target_period: string;
  target_is_future: boolean;
  requested_scope: string;
  matched_scope: string;
  used_fallback: boolean;
  source_table: string;
  training_start: string | null;
  training_through: string | null;
  training_cutoff: string;
  training_months: number;
  scheduled_flights: number;
  total_flights: number;
  completed_flights: number;
  late_flights: number;
  on_time_rate: number | null;
  late_probability: number | null;
  late_probability_ci_95: [number | null, number | null];
  cancellation_probability: number | null;
  cancellation_probability_ci_95: [number | null, number | null];
  expected_arrival_delay_minutes: number | null;
  avg_arrival_delay_minutes: number | null;
  median_arrival_delay_minutes: number | null;
  p90_arrival_delay_minutes: number | null;
  cancellation_rate: number | null;
  confidence: string;
  validation: {
    status: string;
    months_scored: number;
    mean_absolute_error_minutes: number | null;
    brier_score_late_probability: number | null;
    minimum_prior_completed: number;
  };
  model: string;
  baseline_expected_arrival_delay_minutes: number | null;
  baseline_late_probability: number | null;
  traffic_context: T100TrafficContext;
  traffic_validation: {
    status: string;
    months_scored: number;
    mean_absolute_error_minutes: number | null;
    brier_score_late_probability: number | null;
    minimum_prior_completed: number;
    minimum_traffic_months: number;
  };
  interpretation: string;
};

type RouteMLForecast = {
  status: "candidate" | "insufficient_history";
  origin: string;
  dest: string;
  carrier?: string | null;
  departure_hour?: number | null;
  requested_scope?: string;
  matched_scope?: string;
  used_fallback?: boolean;
  target_period: string;
  training_cutoff: string;
  model: string;
  training_start?: string;
  training_through?: string;
  examples?: number;
  minimum_examples?: number;
  reason?: string;
  training_examples?: number;
  routes_in_training_panel?: number;
  route_history_months?: number;
  predictions?: {
    expected_arrival_delay_minutes: number;
    late_probability: number;
    cancellation_probability: number;
  };
  split?: {
    train_examples: number;
    validation_examples: number;
    test_examples: number;
    train_end: string;
    validation_end: string;
  };
  validation_metrics?: {
    examples: number;
    delay_minutes_mae: number | null;
    late_rate_mae: number | null;
    cancellation_rate_mae: number | null;
  };
  test_metrics?: {
    examples: number;
    delay_minutes_mae: number | null;
    late_rate_mae: number | null;
    cancellation_rate_mae: number | null;
  };
  baseline_test_metrics?: {
    examples: number;
    delay_minutes_mae: number | null;
    late_rate_mae: number | null;
    cancellation_rate_mae: number | null;
  };
  t100_ablation?: {
    with_t100_test_metrics: {
      examples: number;
      delay_minutes_mae: number | null;
      late_rate_mae: number | null;
      cancellation_rate_mae: number | null;
    };
    without_t100_test_metrics: {
      examples: number;
      delay_minutes_mae: number | null;
      late_rate_mae: number | null;
      cancellation_rate_mae: number | null;
    };
    improved_targets: string[];
    note: string;
  };
  model_selection?: {
    improved_targets: string[];
    note: string;
  };
  features_for_target?: Record<string, number>;
  interpretation?: string;
  traffic_context?: {
    scope: string;
    reference_period: string | null;
    load_factor: number | null;
    passengers: number | null;
    seats_available: number | null;
    completion_rate: number | null;
    staleness_months: number | null;
  };
};

type ForecastMethod = "math" | "ml" | "comparison";


type RouteDetail = {
  origin: string;
  dest: string;
  total_flights: number;
  on_time_rate: number;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number;
  distance_miles: number | null;
  health: Health | null;
  months: MonthPoint[];
  causes: Cause[];
  carriers: RouteCarrier[];
};

function buildQuery(params: Record<string, string>): string {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v) usp.set(k, v);
  });
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

export default function RoutesPage() {
  const { mode } = useMode();
  const [ranking, setRanking] = useState<{ routes: Route[] } | null>(null);
  const [airports, setAirports] = useState<string[]>([]);
  const [origin, setOrigin] = useState("");
  const [dest, setDest] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [detail, setDetail] = useState<RouteDetail | null>(null);
  const [diversions, setDiversions] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [forecastOrigin, setForecastOrigin] = useState("");
  const [forecastDest, setForecastDest] = useState("");
  const [forecastCarrier, setForecastCarrier] = useState("");
  const [forecastHour, setForecastHour] = useState("");
  const [forecastMonth, setForecastMonth] = useState("");
  const [forecast, setForecast] = useState<RouteForecast | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastNotFound, setForecastNotFound] = useState(false);
  const [mlForecast, setMlForecast] = useState<RouteMLForecast | null>(null);
  const [mlForecastLoading, setMlForecastLoading] = useState(false);
  const [mlForecastError, setMlForecastError] = useState(false);
  const [forecastMethod, setForecastMethod] = useState<ForecastMethod>("math");

  useEffect(() => {
    fetch(`${API_BASE}/api/routes`)
      .then((r) => r.json())
      .then(setRanking)
      .catch(() => setRanking(null));

    fetch(`${API_BASE}/api/airports/list`)
      .then((r) => r.json())
      .then((d) => setAirports(d.airports ?? []))
      .catch(() => setAirports([]));
  }, []);

  async function lookupRoute() {
    if (!origin || !dest) return;
    setLoading(true);
    setNotFound(false);
    const qs = buildQuery({ origin, dest, start_date: startDate, end_date: endDate });
    try {
      const res = await fetch(`${API_BASE}/api/route-detail${qs}`);
      if (res.status === 404) {
        setDetail(null);
        setNotFound(true);
        return;
      }
      setDetail(await res.json());

      try {
        const divRes = await fetch(`${API_BASE}/api/diversions${qs}`);
        setDiversions(divRes.ok ? await divRes.json() : null);
      } catch {
        setDiversions(null);
      }
    } catch {
      setNotFound(true);
    } finally {
      setLoading(false);
    }
  }

  async function runForecast() {
    if (!forecastOrigin || !forecastDest) return;
    setForecastLoading(true);
    setForecastNotFound(false);
    setMlForecast(null);
    setMlForecastError(false);
    setForecastMethod("math");
    const qs = buildQuery({
      origin: forecastOrigin,
      dest: forecastDest,
      carrier: forecastCarrier,
      departure_hour: forecastHour,
      target_month: forecastMonth,
    });
    try {
      const res = await fetch(`${API_BASE}/api/route-forecast${qs}`);
      if (res.status === 404) {
        setForecast(null);
        setForecastNotFound(true);
        return;
      }
      setForecast(await res.json());
    } catch {
      setForecast(null);
      setForecastNotFound(true);
    } finally {
      setForecastLoading(false);
    }
  }

  async function runMLForecast() {
    if (!forecastOrigin || !forecastDest) return;
    setMlForecastLoading(true);
    setMlForecastError(false);
    const qs = buildQuery({
      origin: forecastOrigin,
      dest: forecastDest,
      target_month: forecastMonth,
    });
    try {
      const res = await fetch(`${API_BASE}/api/route-panel-forecast${qs}`);
      if (!res.ok) {
        setMlForecast(null);
        setMlForecastError(true);
        return;
      }
      const payload = await res.json();
      setMlForecast(payload);
      setForecastMethod(payload.status === "candidate" ? "comparison" : "ml");
    } catch {
      setMlForecast(null);
      setMlForecastError(true);
    } finally {
      setMlForecastLoading(false);
    }
  }

  return (
    <main className={`page surface-page ${mode === "researcher" ? "surface-researcher" : ""}`}>
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; {mode === "researcher" ? "Research workspace / routes" : "Routes"}</p>
        <h1 className="title">Routes</h1>
        <p className="subtitle">{mode === "researcher"
          ? "Trace a network signal from the busiest directional connections into route-level delay, carrier, diversion, and expected-outcome evidence."
          : "See the busiest connections and check the historical pattern for a route you care about."}</p>
      </header>

      {mode === "public" && (
        <PublicPageGuide
          topic="routes"
          explanation="A route is directional: LAX → SFO is different from SFO → LAX. Start with busy connections, then test one route below."
          note="Bar color = historical on-time rate for that directional connection."
        />
      )}

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Busiest routes</h2>
          <span className="section-note">Top 15 directional routes, bar color = on-time rate</span>
        </div>
        <div className="screen">
          {ranking ? <RouteChart data={ranking.routes} /> : <p className="error-text">Loading...</p>}
        </div>
      </section>

      {mode === "researcher" && ranking && (
        <section className="section research-evidence-section">
          <div className="section-head">
            <h2 className="section-title">Route evidence table</h2>
            <span className="section-note">Top directional connections</span>
          </div>
          <div className="screen">
            <p className="page-note research-reading-note">
              A route is directional: ATL → LAX is a different observation from LAX → ATL. Volume shows how often the connection appears in the record; on-time rate shows the historical outcome for that connection.
            </p>
            <div className="rotation-table-wrap">
              <table className="compare-table research-data-table">
                <thead><tr><th>Connection</th><th>Flights</th><th>On-time</th><th>Reading</th></tr></thead>
                <tbody>
                  {ranking.routes.map((route) => (
                    <tr key={route.route}>
                      <td><strong>{route.route}</strong></td>
                      <td>{route.total_flights.toLocaleString()}</td>
                      <td>{(route.on_time_rate * 100).toFixed(1)}%</td>
                      <td>{route.on_time_rate >= 0.8 ? "Stronger historical reliability" : route.on_time_rate >= 0.7 ? "Mixed historical reliability" : "Worth investigating"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Look up a route</h2>
        </div>
        <div className="screen">
          <div className="route-lookup-row">
            <label className="filter-field">
              <span className="filter-label">Origin</span>
              <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
                <option value="">Select airport</option>
                {airports.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              <span className="filter-label">Destination</span>
              <select value={dest} onChange={(e) => setDest(e.target.value)}>
                <option value="">Select airport</option>
                {airports.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </label>
            <DateRangePreset
              startDate={startDate}
              endDate={endDate}
              onChange={(start, end) => { setStartDate(start); setEndDate(end); }}
            />
            <button
              type="button"
              className="compare-run"
              onClick={lookupRoute}
              disabled={!origin || !dest || loading}
            >
              {loading ? "Looking up..." : "Look up"}
            </button>
          </div>

          {notFound && !loading && <p className="error-text" style={{ marginTop: "1rem" }}>No flights found for that route/date range.</p>}

          {detail && !notFound && (
            <div className="route-detail">
              <div className="board board-compact" style={{ marginTop: "1.5rem" }}>
                <Tile label="Total flights" value={detail.total_flights.toLocaleString()} />
                <Tile label="On-time rate" value={`${(detail.on_time_rate * 100).toFixed(1)}%`} />
                <Tile label="Avg arrival delay" value={`${formatNumber(detail.avg_arrival_delay_minutes)} min`} tone="rust" />
                <Tile
                  label="Distance"
                  value={detail.distance_miles ? `${detail.distance_miles.toLocaleString()} mi` : "\u2014"}
                />
              </div>

              <HealthBadge health={detail.health} />

              {detail.months.length > 0 && (
                <div style={{ marginTop: "1.5rem" }}>
                  <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>On-time rate over time</p>
                  <TrendChart data={detail.months} />
                </div>
              )}

              <div className="route-detail-grid">
                <div>
                  <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Delay causes on this route</p>
                  <DelayCauseChart data={detail.causes} />
                </div>
                <div>
                  <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Carriers flying this route</p>
                  <table className="compare-table">
                    <thead>
                      <tr>
                        <th>Carrier</th>
                        <th>Flights</th>
                        <th>On-time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.carriers.map((c) => (
                        <tr key={c.carrier}>
                          <td>{c.carrier} &mdash; {carrierName(c.carrier)}</td>
                          <td>{c.total_flights.toLocaleString()}</td>
                          <td>{(c.on_time_rate * 100).toFixed(1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {diversions && (
                <div style={{ marginTop: "2rem" }}>
                  <p className="eyebrow" style={{ marginBottom: "0.25rem" }}>
                    Diversion deep-dive
                  </p>
                  <p className="page-note" style={{ marginBottom: "0.75rem" }}>
                    {diversions.diverted_flights.toLocaleString()} of{" "}
                    {diversions.total_flights.toLocaleString()} flights on this route were
                    diverted ({(diversions.diversion_rate * 100).toFixed(3)}%).
                    {diversions.diverted_flights > 0 && (
                      <>
                        {" "}Below: how many airports each diverted flight landed at before
                        stopping, and whether it eventually reached the original scheduled
                        destination.
                      </>
                    )}
                  </p>
                  {diversions.diverted_flights > 0 && diversions.landing_buckets?.length > 0 ? (
                    <DiversionLandingChart data={diversions.landing_buckets} />
                  ) : (
                    diversions.diverted_flights === 0 && (
                      <p className="page-note">No diverted flights on this route in scope.</p>
                    )
                  )}

                  {diversions.average_diversion_cost && (
                    <div style={{ marginTop: "1.5rem" }}>
                      <p className="eyebrow" style={{ marginBottom: "0.5rem" }}>What a diversion actually costs</p>
                      <div className="board board-compact">
                        <div className="tile">
                          <span className="tile-label">Avg arrival delay</span>
                          <span className="tile-value rust">{formatNumber(diversions.average_diversion_cost.avg_arrival_delay_minutes, 0)} min</span>
                        </div>
                        <div className="tile">
                          <span className="tile-label">
                            {diversions.average_diversion_cost.avg_extra_distance_miles >= 0
                              ? "Avg extra distance flown"
                              : "Avg distance cut short"}
                          </span>
                          <span className="tile-value rust">
                            {Math.abs(diversions.average_diversion_cost.avg_extra_distance_miles).toFixed(0)} mi
                          </span>
                        </div>
                        <div className="tile">
                          <span className="tile-label">Avg extra time</span>
                          <span className="tile-value rust">{diversions.average_diversion_cost.avg_extra_time_minutes.toFixed(0)} min</span>
                        </div>
                      </div>
                      <p className="page-note" style={{ marginTop: "0.5rem" }}>
                        Distance compares the diversion&apos;s actual flown distance against the
                        originally scheduled route &mdash; usually shorter, not longer, since a
                        diversion typically means landing at an unplanned airport partway through
                        rather than completing (or exceeding) the original route. Time is almost
                        always longer, even when distance is shorter. Both are real numbers from
                        the diversion record, not an estimate.
                      </p>
                    </div>
                  )}

                  {diversions.top_diversion_airports?.length > 0 && (
                    <div style={{ marginTop: "1.5rem" }}>
                      <p className="eyebrow" style={{ marginBottom: "0.5rem" }}>Where diverted flights actually land</p>
                      <table className="compare-table">
                        <thead>
                          <tr>
                            <th>Diversion airport</th>
                            <th>Flights</th>
                            <th>Reached original destination</th>
                            <th>Avg arrival delay</th>
                          </tr>
                        </thead>
                        <tbody>
                          {diversions.top_diversion_airports.map((a: any) => (
                            <tr key={a.airport}>
                              <td>{a.airport}</td>
                              <td>{a.diverted_flights.toLocaleString()}</td>
                              <td>{(a.reached_destination_rate * 100).toFixed(0)}%</td>
                              <td>{a.avg_arrival_delay_minutes != null ? `${a.avg_arrival_delay_minutes.toFixed(0)} min` : "\u2014"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      <section className="section" id="expected-delay">
        <div className="section-head">
          <h2 className="section-title">What delay might I expect?</h2>
          <span className="section-note">Historical baseline, not a promise</span>
        </div>
        <div className="screen">
          <p className="page-note" style={{ marginTop: 0, marginBottom: "1rem" }}>
            Choose a route and optional filters. We use only earlier completed flights in the BTS history
            to estimate the expected delay, late-arrival chance, and cancellation chance for the target month.
          </p>
          <div className="route-lookup-row">
            <label className="filter-field">
              <span className="filter-label">Origin</span>
              <select
                value={forecastOrigin}
                onChange={(e) => setForecastOrigin(e.target.value)}
                aria-label="Forecast origin airport"
              >
                <option value="">Select airport</option>
                {airports.map((airport) => <option key={airport} value={airport}>{airport}</option>)}
              </select>
            </label>
            <label className="filter-field">
              <span className="filter-label">Destination</span>
              <select
                value={forecastDest}
                onChange={(e) => setForecastDest(e.target.value)}
                aria-label="Forecast destination airport"
              >
                <option value="">Select airport</option>
                {airports.map((airport) => <option key={airport} value={airport}>{airport}</option>)}
              </select>
            </label>
            <label className="filter-field">
              <span className="filter-label">Airline (optional)</span>
              <select value={forecastCarrier} onChange={(e) => setForecastCarrier(e.target.value)}>
                <option value="">All airlines</option>
                {Object.keys(CARRIER_NAMES).map((code) => (
                  <option key={code} value={code}>{code} &mdash; {carrierName(code)}</option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              <span className="filter-label">Departure hour (optional)</span>
              <select value={forecastHour} onChange={(e) => setForecastHour(e.target.value)}>
                <option value="">All times</option>
                {Array.from({ length: 24 }, (_, hour) => (
                  <option key={hour} value={hour}>{formatHour(hour)}</option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              <span className="filter-label">Target month (optional)</span>
              <input
                type="month"
                value={forecastMonth}
                onChange={(e) => setForecastMonth(e.target.value)}
                aria-label="Forecast target month"
              />
            </label>
            <button
              type="button"
              className="compare-run"
              onClick={runForecast}
              disabled={!forecastOrigin || !forecastDest || forecastLoading}
            >
              {forecastLoading ? "Checking history..." : "Show expected delay"}
            </button>
          </div>

          {forecastNotFound && !forecastLoading && (
            <p className="error-text" style={{ marginTop: "1rem" }}>No historical flights matched this route.</p>
          )}

          {forecast && !forecastNotFound && (
            <div className="forecast-result">
              <div className="decision-verdict">
                <span className="decision-verdict-label">What the history suggests</span>
                <p>
                  For {forecast.target_period}, earlier comparable flights on {forecast.origin} &rarr; {forecast.dest}{" "}
                  had an expected outcome of {formatDelayOutcome(forecast.expected_arrival_delay_minutes)}.
                  {forecast.late_probability != null && (
                    <> The historical chance of arriving at least 15 minutes late was {formatPercent(forecast.late_probability)}.</>
                  )}
                  {forecast.model === "t100_traffic_band_baseline" && forecast.traffic_context.load_factor != null && (
                    <> The latest available T-100 record was {formatPercent(forecast.traffic_context.load_factor)} full, and similar traffic months helped refine that estimate.</>
                  )}
                </p>
              </div>
              <div className="board board-compact" style={{ marginTop: "1.25rem", marginBottom: "1rem" }}>
                <Tile label="Expected delay" value={formatDelayOutcome(forecast.expected_arrival_delay_minutes)} tone="rust" />
                <Tile label="Chance 15+ min late" value={formatPercent(forecast.late_probability)} />
                <Tile label="Chance of cancellation" value={formatPercent(forecast.cancellation_probability)} tone="rust" />
                <Tile label="Completed flights" value={forecast.completed_flights.toLocaleString()} />
              </div>
              <p className="page-note">
                This used the {forecast.matched_scope} history ({forecast.confidence}).
                {forecast.used_fallback && " The exact combination was too small, so the result widened the comparison and tells you which level it used."}
                {" "}It is a historical guide, not a promise about one flight. See the <a href="/glossary">glossary</a> for the metric definitions.
              </p>
              {mode === "researcher" && (
                <ResearchForecastExplorer
                  forecast={forecast}
                  mlForecast={mlForecast}
                  mlForecastLoading={mlForecastLoading}
                  mlForecastError={mlForecastError}
                  forecastMethod={forecastMethod}
                  onMethodChange={setForecastMethod}
                  onRunMLForecast={runMLForecast}
                />
              )}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

function ResearchForecastExplorer({
  forecast,
  mlForecast,
  mlForecastLoading,
  mlForecastError,
  forecastMethod,
  onMethodChange,
  onRunMLForecast,
}: {
  forecast: RouteForecast;
  mlForecast: RouteMLForecast | null;
  mlForecastLoading: boolean;
  mlForecastError: boolean;
  forecastMethod: ForecastMethod;
  onMethodChange: (method: ForecastMethod) => void;
  onRunMLForecast: () => void;
}) {
  const tabs: Array<{ id: ForecastMethod; label: string; hint: string }> = [
    { id: "math", label: "Math baseline", hint: "What the historical calculation does" },
    { id: "ml", label: "ML candidate", hint: "What the learned model does" },
    { id: "comparison", label: "Comparison", hint: "Which one is better on held-out history" },
  ];

  return (
    <div className="research-evidence-section forecast-explorer">
      <div className="forecast-explorer-heading">
        <div>
          <span className="method-kicker">Research lens</span>
          <h3 className="section-title">Read the same forecast three ways.</h3>
          <p className="page-note">
            Start with the transparent calculation, inspect the ML candidate, then compare their evidence.
            The public answer still uses the baseline.
          </p>
        </div>
        <span className="method-status">No hidden replacement</span>
      </div>

      <div className="forecast-method-tabs" role="tablist" aria-label="Forecast methods">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={forecastMethod === tab.id}
            className={`forecast-method-tab ${forecastMethod === tab.id ? "active" : ""}`}
            onClick={() => onMethodChange(tab.id)}
          >
            <span>{tab.label}</span>
            <small>{tab.hint}</small>
          </button>
        ))}
      </div>

      <div className="forecast-method-panel" role="tabpanel">
        {forecastMethod === "math" && <MathForecastPanel forecast={forecast} />}
        {forecastMethod === "ml" && (
          <MLForecastPanel
            forecast={mlForecast}
            loading={mlForecastLoading}
            error={mlForecastError}
            onRun={onRunMLForecast}
          />
        )}
        {forecastMethod === "comparison" && (
          <ForecastComparisonPanel forecast={forecast} mlForecast={mlForecast} />
        )}
      </div>
    </div>
  );
}

function MathForecastPanel({ forecast }: { forecast: RouteForecast }) {
  const trafficUsed = forecast.model === "t100_traffic_band_baseline";
  const traffic = forecast.traffic_context;

  return (
    <div>
      <div className="method-panel-intro">
        <span className="method-kicker">01 · Transparent calculation</span>
        <h4>Average what happened before.</h4>
        <p>
          The baseline finds comparable flights before the target month and turns their recorded outcomes into three simple rates.
          Every number can be traced back to the BTS history.
        </p>
      </div>
      <div className="method-step-grid">
        <div className="method-step-card">
          <span>1</span>
          <strong>Choose comparable history</strong>
          <p>Use {forecast.matched_scope} observations and stop before {forecast.training_cutoff}.</p>
        </div>
        <div className="method-step-card">
          <span>2</span>
          <strong>Calculate the outcomes</strong>
          <p>Delay is total delay divided by completed flights; late chance is 15+ minute late flights divided by completed flights.</p>
        </div>
        <div className="method-step-card">
          <span>3</span>
          <strong>Check cancellations</strong>
          <p>Cancellation chance is cancelled flights divided by scheduled flights, so it uses a different denominator.</p>
        </div>
      </div>
      <div className="method-formula-grid">
        <div><span>Expected delay</span><code>delay minutes ÷ completed flights</code></div>
        <div><span>Late probability</span><code>late flights ÷ completed flights</code></div>
        <div><span>Cancellation probability</span><code>cancelled flights ÷ scheduled flights</code></div>
      </div>
      <div className="method-context-note">
        <strong>{trafficUsed ? "T-100 is an adjustment, not a replacement." : "T-100 is checked, but not forced into the answer."}</strong>{" "}
        {trafficUsed
          ? `The latest prior traffic was ${formatPercent(traffic.load_factor)} full. The baseline compares earlier months in the same traffic band and uses them only when at least ${traffic.minimum_traffic_match_months} matches are available.`
          : traffic.reason ?? "There was not enough matching prior traffic context to adjust the historical average."}
      </div>
      <div className="method-context-note method-uncertainty-note">
        <strong>Uncertainty check:</strong> the late-rate estimate is shown with a 95% range of {formatPercent(forecast.late_probability_ci_95[0])}–{formatPercent(forecast.late_probability_ci_95[1])}. A smaller sample produces a wider range, so the result is not treated as equally reliable in every case.
      </div>
      <div className="method-proof-row">
        <span>Sample: {forecast.completed_flights.toLocaleString()} completed flights · {forecast.training_months} months</span>
        <span>Rolling delay error: {formatMinutes(forecast.validation.mean_absolute_error_minutes)}</span>
      </div>
    </div>
  );
}

function MLForecastPanel({
  forecast,
  loading,
  error,
  onRun,
}: {
  forecast: RouteMLForecast | null;
  loading: boolean;
  error: boolean;
  onRun: () => void;
}) {
  return (
    <div>
      <div className="method-panel-intro">
        <span className="method-kicker">02 · Learned candidate</span>
        <h4>Let the data learn combinations of signals.</h4>
        <p>
          Instead of choosing one average by hand, ML learns how prior performance, recent movement, traffic context, distance, and seasonality relate to later route outcomes.
        </p>
      </div>
      <div className="method-step-grid">
        <div className="method-step-card">
          <span>1</span>
          <strong>Learn from many routes</strong>
          <p>The shared model sees historical route-month examples, not just this one route.</p>
        </div>
        <div className="method-step-card">
          <span>2</span>
          <strong>Keep the cutoff honest</strong>
          <p>Each training example uses earlier history and lagged T-100 context only; future months are held back.</p>
        </div>
        <div className="method-step-card">
          <span>3</span>
          <strong>Test before trusting</strong>
          <p>The candidate is scored on later months and is not promoted just because it produces a number.</p>
        </div>
      </div>
      <div className="method-feature-row">
        <span>Prior route performance</span>
        <span>Recent route movement</span>
        <span>Lagged T-100 traffic</span>
        <span>Distance + season</span>
      </div>
      <div className="method-context-note">
        <strong>Important boundary:</strong> this is a small regularized regression, not a neural network. It learns a weight for each signal while discouraging extreme weights. It does not use the selected airline or departure hour, so it is a route-level benchmark, not a prediction for one specific flight.
      </div>

      {!forecast && !loading && (
        <div className="method-run-card">
          <div>
            <strong>Ready to run the ML candidate?</strong>
            <p>The first run trains the shared panel; later runs are faster while the backend cache is warm.</p>
          </div>
          <button type="button" className="compare-run" onClick={onRun}>Run ML candidate</button>
        </div>
      )}
      {loading && <p className="method-loading">Training and scoring the route-panel candidate…</p>}
      {error && <p className="error-text">The ML comparison could not be loaded. The Math baseline remains available.</p>}
      {forecast?.status === "insufficient_history" && (
        <div className="decision-verdict">
          <span className="decision-verdict-label">ML not promoted</span>
          <span>{forecast.reason} It will not invent a prediction from a small sample.</span>
        </div>
      )}
      {forecast?.status === "candidate" && forecast.predictions && forecast.test_metrics && forecast.baseline_test_metrics && (
        <div className="ml-output-block">
          <div className="board board-compact">
            <Tile label="ML expected delay" value={formatDelayOutcome(forecast.predictions.expected_arrival_delay_minutes)} tone="rust" />
            <Tile label="ML late probability" value={formatPercent(forecast.predictions.late_probability)} />
            <Tile label="ML cancellation probability" value={formatPercent(forecast.predictions.cancellation_probability)} tone="rust" />
            <Tile label="Training examples" value={(forecast.training_examples ?? 0).toLocaleString()} />
          </div>
          <div className="method-proof-row">
            <span>Learned from {(forecast.routes_in_training_panel ?? 0).toLocaleString()} routes · {forecast.training_start ?? "—"} to {forecast.training_through ?? "—"}</span>
            <span>Cutoff: {forecast.training_cutoff}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function ForecastComparisonPanel({
  forecast,
  mlForecast,
}: {
  forecast: RouteForecast;
  mlForecast: RouteMLForecast | null;
}) {
  if (
    mlForecast?.status !== "candidate"
    || !mlForecast.predictions
    || !mlForecast.test_metrics
    || !mlForecast.baseline_test_metrics
  ) {
    return (
      <div className="method-empty-state">
        <span className="method-kicker">03 · Evidence check</span>
        <h4>Run the ML candidate to compare it.</h4>
        <p>The Math baseline is already available above. The Comparison tab will show which approach has lower error on later held-out months.</p>
      </div>
    );
  }

  const predictions = mlForecast.predictions;
  const testMetrics = mlForecast.test_metrics;
  const baselineTestMetrics = mlForecast.baseline_test_metrics;

  const rows = [
    ["Expected delay", formatDelayOutcome(forecast.expected_arrival_delay_minutes), formatDelayOutcome(predictions.expected_arrival_delay_minutes)],
    ["Chance 15+ min late", formatPercent(forecast.late_probability), formatPercent(predictions.late_probability)],
    ["Chance of cancellation", formatPercent(forecast.cancellation_probability), formatPercent(predictions.cancellation_probability)],
  ];
  const improved = mlForecast.model_selection?.improved_targets ?? [];
  const ablation = mlForecast.t100_ablation;
  const ablationRows = ablation ? [
    ["Expected delay", formatMinutes(ablation.with_t100_test_metrics.delay_minutes_mae), formatMinutes(ablation.without_t100_test_metrics.delay_minutes_mae)],
    ["Chance 15+ min late", formatNumber(ablation.with_t100_test_metrics.late_rate_mae, 4), formatNumber(ablation.without_t100_test_metrics.late_rate_mae, 4)],
    ["Chance of cancellation", formatNumber(ablation.with_t100_test_metrics.cancellation_rate_mae, 4), formatNumber(ablation.without_t100_test_metrics.cancellation_rate_mae, 4)],
  ] : [];

  return (
    <div>
      <div className="method-panel-intro">
        <span className="method-kicker">03 · Evidence check</span>
        <h4>Put the outputs side by side.</h4>
        <p>These are two estimates for the same route question. The winner is decided by later held-out history, not by which output looks more sophisticated.</p>
      </div>
      <div className="method-comparison-table-wrap">
        <table className="method-comparison-table">
          <thead><tr><th>Outcome</th><th>Math baseline</th><th>ML candidate</th></tr></thead>
          <tbody>{rows.map(([label, math, ml]) => <tr key={label}><th>{label}</th><td>{math}</td><td>{ml}</td></tr>)}</tbody>
        </table>
      </div>
      <div className="method-score-grid">
        <div><span>Delay error on later months</span><strong>{formatMinutes(testMetrics.delay_minutes_mae)} ML · {formatMinutes(baselineTestMetrics.delay_minutes_mae)} Math</strong></div>
        <div><span>Late-rate error on later months</span><strong>{formatNumber(testMetrics.late_rate_mae, 4)} ML · {formatNumber(baselineTestMetrics.late_rate_mae, 4)} Math</strong></div>
        <div><span>Cancellation-rate error on later months</span><strong>{formatNumber(testMetrics.cancellation_rate_mae, 4)} ML · {formatNumber(baselineTestMetrics.cancellation_rate_mae, 4)} Math</strong></div>
      </div>
      <div className="decision-verdict">
        <span className="decision-verdict-label">Decision rule</span>
        <span>
          {improved.length
            ? `ML currently improves ${improved.join(" and ")} on the held-out check.`
            : "The Math baseline currently performs better on the held-out check."}{" "}
          {improved.includes("cancellation_rate")
            ? "The candidate is ready for further testing, but it still remains researcher-only until repeated future checks support promotion."
            : "Because it does not win every outcome, the public answer stays with the transparent Math baseline."}
        </span>
      </div>
      {ablation && (
        <div className="t100-ablation-panel">
          <div className="method-panel-intro">
            <span className="method-kicker">T-100 evidence check</span>
            <h4>Does the traffic data improve the forecast?</h4>
            <p>{ablation.note}</p>
          </div>
          <div className="method-comparison-table-wrap">
            <table className="method-comparison-table">
              <thead><tr><th>Outcome error</th><th>With T-100</th><th>OTP-only</th></tr></thead>
              <tbody>{ablationRows.map(([label, withT100, withoutT100]) => <tr key={label}><th>{label}</th><td>{withT100}</td><td>{withoutT100}</td></tr>)}</tbody>
            </table>
          </div>
          <div className="decision-verdict">
            <span className="decision-verdict-label">Plain-language result</span>
            <span>
              {ablation.improved_targets.length
                ? `T-100 lowers held-out error for ${ablation.improved_targets.map(routeTargetLabel).join(", ")}.`
                : "T-100 does not lower held-out error for any of these outcomes in this run."} The result is evidence for this snapshot, not proof that traffic causes delay.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function formatHour(hour: number): string {
  const suffix = hour < 12 ? "AM" : "PM";
  const display = hour % 12 || 12;
  return `${display}:00 ${suffix}`;
}

function routeTargetLabel(target: string): string {
  return {
    delay_minutes: "expected delay",
    late_rate: "the chance of being 15+ minutes late",
    cancellation_rate: "the chance of cancellation",
  }[target] ?? target.replaceAll("_", " ");
}

function formatDelayOutcome(value: number | null): string {
  if (value == null) return "—";
  const rounded = Math.round(value);
  if (rounded < 0) return `${Math.abs(rounded)} min early`;
  if (rounded === 0) return "On time";
  return `${rounded} min late`;
}

function formatSignedMinutes(value: number | null): string {
  if (value == null) return "—";
  const rounded = value.toFixed(1);
  return `${value >= 0 ? "+" : ""}${rounded} minutes`;
}

function formatSignedPercentagePoints(value: number | null): string {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)} percentage points`;
}

function formatMinutes(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(1)} minutes`;
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: "rust" }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={`tile-value ${tone === "rust" ? "rust" : ""}`}>{value}</span>
    </div>
  );
}
