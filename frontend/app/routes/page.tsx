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
import { formatNumber } from "../lib/format";
import { useMode } from "../lib/mode";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Route = { route: string; total_flights: number; on_time_rate: number };
type Cause = { cause: string; minutes: number; share: number };
type MonthPoint = { month: string; total_flights: number; on_time_rate: number };
type RouteCarrier = { carrier: string; total_flights: number; on_time_rate: number };
type RouteForecast = {
  origin: string;
  dest: string;
  carrier: string | null;
  departure_hour: number | null;
  requested_scope: string;
  matched_scope: string;
  used_fallback: boolean;
  total_flights: number;
  completed_flights: number;
  on_time_rate: number | null;
  avg_arrival_delay_minutes: number | null;
  median_arrival_delay_minutes: number | null;
  p90_arrival_delay_minutes: number | null;
  cancellation_rate: number | null;
  confidence: string;
  interpretation: string;
};


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
  const [forecast, setForecast] = useState<RouteForecast | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastNotFound, setForecastNotFound] = useState(false);

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
    const qs = buildQuery({
      origin: forecastOrigin,
      dest: forecastDest,
      carrier: forecastCarrier,
      departure_hour: forecastHour,
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
            Choose a route, airline, and departure time. We look at comparable completed flights
            in the BTS history and summarize what usually happened.
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
                  A comparable flight on {forecast.origin} &rarr; {forecast.dest} typically arrived
                  {forecast.median_arrival_delay_minutes != null
                    ? ` ${delaySentence(forecast.median_arrival_delay_minutes)}`
                    : " on time or earlier"}.
                  {forecast.p90_arrival_delay_minutes != null && (
                    <> On a rougher day, the delay reached about {Math.max(0, forecast.p90_arrival_delay_minutes).toFixed(0)} minutes for 1 in 10 comparable flights.</>
                  )}
                </p>
              </div>
              <div className="board board-compact" style={{ marginTop: "1.25rem", marginBottom: "1rem" }}>
                <Tile label="Usually on time" value={forecast.on_time_rate != null ? `${(forecast.on_time_rate * 100).toFixed(1)}%` : "—"} />
                <Tile label="Typical outcome" value={formatDelayOutcome(forecast.median_arrival_delay_minutes)} tone="rust" />
                <Tile label="Rough-day delay" value={forecast.p90_arrival_delay_minutes != null ? `${Math.max(0, forecast.p90_arrival_delay_minutes).toFixed(0)} min late` : "—"} tone="rust" />
                <Tile label="Completed flights" value={forecast.completed_flights.toLocaleString()} />
              </div>
              <p className="page-note">
                This used the {forecast.matched_scope} history ({forecast.confidence}).
                {forecast.used_fallback && " The exact combination was too small, so the result widened the comparison and tells you which level it used."}
                {" "}{forecast.interpretation} See the <a href="/glossary">glossary</a> for the metric definitions.
              </p>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

function formatHour(hour: number): string {
  const suffix = hour < 12 ? "AM" : "PM";
  const display = hour % 12 || 12;
  return `${display}:00 ${suffix}`;
}

function formatDelayOutcome(value: number | null): string {
  if (value == null) return "—";
  const rounded = Math.round(value);
  if (rounded < 0) return `${Math.abs(rounded)} min early`;
  if (rounded === 0) return "On time";
  return `${rounded} min late`;
}

function delaySentence(value: number): string {
  const rounded = Math.round(value);
  if (rounded < 0) return `about ${Math.abs(rounded)} minutes early`;
  if (rounded === 0) return "on time";
  return `about ${rounded} minutes late`;
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: "rust" }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={`tile-value ${tone === "rust" ? "rust" : ""}`}>{value}</span>
    </div>
  );
}
