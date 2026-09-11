"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CARRIER_NAMES, carrierName } from "../lib/carriers";
import { formatInteger, formatNumber, formatPercent } from "../lib/format";
import type { CapacityCorrelationResult, CapacityTrendResult } from "../decision-center/types";
import { useMode } from "../lib/mode";
import CapacityTrendChart from "../components/CapacityTrendChart";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const CARRIER_CODES = Object.keys(CARRIER_NAMES);

type CapacitySummaryResult = {
  source: string;
  overview: {
    route_month_rows: number;
    seats_available: number;
    passengers: number;
    load_factor: number | null;
    first_year: number;
    last_year: number;
  };
};

function relationship(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Not enough variation to say";
  const magnitude = Math.abs(value);
  const strength = magnitude >= 0.5 ? "noticeable" : magnitude >= 0.25 ? "modest" : "weak";
  return `${strength} ${value >= 0 ? "positive" : "negative"} association`;
}

function periodLabel(value: number | null): string {
  if (!value) return "—";
  const year = Math.floor(value / 100);
  const month = value % 100;
  return `${year}-${String(month).padStart(2, "0")}`;
}

export default function CapacityPage() {
  const { mode, setMode } = useMode();
  const [carrier, setCarrier] = useState("");
  const [minimumFlights, setMinimumFlights] = useState("100");
  const [summary, setSummary] = useState<CapacitySummaryResult | null>(null);
  const [result, setResult] = useState<CapacityCorrelationResult | null>(null);
  const [trend, setTrend] = useState<CapacityTrendResult | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [trendLoading, setTrendLoading] = useState(true);
  const [summaryError, setSummaryError] = useState("");
  const [error, setError] = useState("");
  const [trendError, setTrendError] = useState("");

  async function load() {
    if (mode === "public") {
      setSummaryLoading(true);
      setSummaryError("");
      try {
        const response = await fetch(`${API_BASE}/api/capacity/summary`);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail ?? "The T-100 summary is unavailable.");
        setSummary(payload);
      } catch (cause) {
        setSummary(null);
        setSummaryError(cause instanceof Error ? cause.message : "The T-100 summary is unavailable.");
      } finally {
        setSummaryLoading(false);
      }
      return;
    }

    setLoading(true);
    setTrendLoading(true);
    setError("");
    setTrendError("");
    const params = new URLSearchParams({ limit: "30", minimum_flights: minimumFlights });
    if (carrier) params.set("carrier", carrier);
    try {
      const trendParams = new URLSearchParams({ minimum_flights: minimumFlights });
      if (carrier) trendParams.set("carrier", carrier);
      const [comparisonResponse, trendResponse] = await Promise.all([
        fetch(`${API_BASE}/api/capacity/correlation?${params}`),
        fetch(`${API_BASE}/api/capacity/trend?${trendParams}`),
      ]);
      const comparisonPayload = await comparisonResponse.json();
      const trendPayload = await trendResponse.json();
      if (!comparisonResponse.ok) throw new Error(comparisonPayload.detail ?? "The T-100 comparison is unavailable.");
      setResult(comparisonPayload);
      if (!trendResponse.ok) {
        setTrend(null);
        setTrendError(trendPayload.detail ?? "The monthly T-100 trend is unavailable.");
      } else {
        setTrend(trendPayload);
      }
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "The T-100 comparison is unavailable.");
    } finally {
      setLoading(false);
      setTrendLoading(false);
    }
  }

  useEffect(() => { void load(); }, [mode]);

  if (mode === "public") {
    return (
      <main className="page public-capacity-page">
        <header className="public-secondary-hero">
          <p className="eyebrow">Capacity context</p>
          <h1 className="title">How full was the system?</h1>
          <p className="subtitle">T-100 adds passengers, seats, and operated flights to the on-time story. This view keeps the question simple: do fuller route-months look different from less-full ones?</p>
        </header>
        {summaryLoading && <div className="public-result-placeholder">Reading the T-100 snapshot…</div>}
        {summaryError && <div className="inline-data-warning">The capacity snapshot is not available right now. You can still explore the carrier, airport, and route views.</div>}
        {summary && (
          <>
            <section className="public-capacity-result">
              <div><p className="eyebrow">What the capacity record says</p><h2>{formatPercent(summary.overview.load_factor)} of listed seats were filled.</h2><p>That is the network-wide T-100 average across the loaded route-month history.</p></div>
              <div className="public-capacity-metrics">
                <div><span>Route-month records</span><strong>{formatInteger(summary.overview.route_month_rows)}</strong></div>
                <div><span>Passengers recorded</span><strong>{formatInteger(summary.overview.passengers)}</strong></div>
                <div><span>Seats listed</span><strong>{formatInteger(summary.overview.seats_available)}</strong></div>
              </div>
            </section>
            <p className="page-note public-boundary-note">This is a descriptive snapshot, not a claim about cause. The researcher workspace adds the matched on-time comparison, filters, chart, and join details.</p>
          </>
        )}
        <section className="public-capacity-next"><div><p className="eyebrow">Want to investigate?</p><h2>Open the evidence workspace.</h2><p>Use the researcher view to change the minimum flight threshold, filter by airline, and inspect the matched rows.</p></div><button type="button" className="primary-action" onClick={() => setMode("researcher")}>Open researcher view <span>→</span></button></section>
      </main>
    );
  }

  return (
    <main className="page capacity-researcher-page">
      <header className="header research-hero capacity-console-header">
        <div className="capacity-console-lede">
          <p className="eyebrow">Researcher view · BTS T-100 + OTP</p>
          <h1 className="title">Traffic context for on-time performance.</h1>
          <p className="subtitle">
            T-100 adds seats and passengers to the on-time record. Use this console to check whether fuller route-months move with the same month&apos;s on-time result.
          </p>
        </div>
        <div className="capacity-console-meta">
          <div className="hero-actions">
            <span className="status-chip"><span className="status-chip-dot" /> Evidence surface</span>
            <Link href="/methodology#t-100-and-on-time-correlation" className="text-link">Read the full method →</Link>
          </div>
          <div className="capacity-meta-list" aria-label="Capacity analysis scope">
            <div><span>Source</span><strong>BTS T-100 + OTP</strong></div>
            <div><span>Analysis grain</span><strong>Carrier · route · month</strong></div>
          </div>
        </div>
      </header>

      <section className="capacity-explainer capacity-question-bar">
        <div>
          <p className="eyebrow">The question</p>
          <h2>Does a fuller route look different operationally?</h2>
        </div>
        <p>
          We line up both datasets by <strong>carrier + route + month</strong>. The result is an association to investigate, not a claim that passenger demand causes delay.
        </p>
      </section>

      <section className="section capacity-workbench">
        <div className="section-head">
          <div>
            <p className="eyebrow">01 · Define evidence</p>
            <h2 className="section-title">Choose the evidence slice</h2>
          </div>
          <span className="section-note">Live local warehouse · no synthetic traffic values</span>
        </div>
        <div className="screen capacity-controls">
          <label className="filter-field capacity-carrier-field">
            <span className="filter-label">Airline (optional)</span>
            <select value={carrier} onChange={(event) => setCarrier(event.target.value)}>
              <option value="">All carriers</option>
              {CARRIER_CODES.map((code) => <option key={code} value={code}>{code} — {carrierName(code)}</option>)}
            </select>
          </label>
          <label className="filter-field capacity-threshold-field">
            <span className="filter-label">Minimum OTP flights per route-month</span>
            <input type="number" min="1" max="10000" value={minimumFlights} onChange={(event) => setMinimumFlights(event.target.value)} />
          </label>
          <button type="button" className="compare-run" onClick={() => void load()} disabled={loading}>
            {loading ? "Loading evidence…" : "Refresh comparison"}
          </button>
          <p className="capacity-control-hint">The threshold is a confidence control: higher values keep only route-months with more OTP observations.</p>
        </div>
        <div className="capacity-scope-strip" aria-label="Current evidence scope">
          <div><span>Source</span><strong>BTS on-time records + T-100</strong></div>
          <div><span>Unit of comparison</span><strong>Carrier · route · month</strong></div>
          <div><span>Current threshold</span><strong>{minimumFlights} OTP flights</strong></div>
        </div>
      </section>

      {error && <div className="callout callout-warn">{error}</div>}
      {loading && !result && <div className="screen capacity-loading-panel"><span className="status-chip-dot" /><div><strong>Reading matched T-100 and OTP history</strong><p>The first result will appear here when the warehouse query finishes.</p></div></div>}

      {result && (
        <>
          <section className="section capacity-result-section">
            <div className="section-head">
              <div>
                <p className="eyebrow">02 · Read output</p>
                <h2 className="section-title">What the matched history says</h2>
              </div>
              <span className="section-note">{periodLabel(result.overview.first_period)} → {periodLabel(result.overview.last_period)}</span>
            </div>
            <div className="board capacity-board">
              <MetricTile label="Matched route-months" value={formatInteger(result.overview.matched_route_months)} />
              <MetricTile label="Average seats filled" value={formatPercent(result.overview.average_load_factor)} />
              <MetricTile label="Average on-time" value={formatPercent(result.overview.average_on_time_rate)} />
              <MetricTile label="Traffic ↔ on-time" value={result.overview.correlation_load_factor_on_time === null ? "—" : result.overview.correlation_load_factor_on_time.toFixed(2)} tone="signal" />
            </div>
            <div className="capacity-verdict">
              <span className="decision-verdict-label">Simple read</span>
              <strong>{relationship(result.overview.correlation_load_factor_on_time)}</strong> between the share of seats filled and the route-month on-time rate.
              <span className="capacity-verdict-note">A relationship helps decide what to investigate next; it does not isolate the cause.</span>
            </div>
          </section>

          <section className="capacity-reading-guide" aria-label="How to read the T-100 comparison">
            <div><span>01</span><strong>Traffic context</strong><p>T-100 tells us how many seats and passengers were offered on a route each month.</p></div>
            <div><span>02</span><strong>Operating outcome</strong><p>OTP tells us how often the matched flights arrived on time.</p></div>
            <div><span>03</span><strong>Relationship</strong><p>The comparison shows whether the two measures move together. It is not proof of cause.</p></div>
          </section>

          <section className="section">
            <div className="section-head">
              <div>
                <p className="eyebrow">03 · Find the pattern</p>
                <h2 className="section-title">Traffic context over time</h2>
              </div>
              <span className="section-note">same matched history</span>
            </div>
            <div className="screen capacity-trend-screen">
              <p className="page-note capacity-trend-intro">
                Two lines answer the practical question: how full were the matched routes, and how often were their flights on time?
              </p>
              {trendLoading && <p className="page-note">Building the monthly view…</p>}
              {trendError && <p className="page-note">{trendError}</p>}
              {trend && trend.months.length > 0 && <CapacityTrendChart data={trend.months} />}
              {trend && trend.months.length === 0 && <p className="page-note">No monthly trend points met the selected threshold.</p>}
            </div>
          </section>

          <section className="section">
            <div className="section-head">
              <div>
                <p className="eyebrow">04 · Inspect rows</p>
                <h2 className="section-title">Largest matched route-months</h2>
              </div>
              <span className="section-note">Sorted by passengers</span>
            </div>
            <div className="screen table-screen">
              {result.rows.length === 0 ? <p className="page-note">No route-months met the selected minimum.</p> : (
                <div className="table-scroll">
                  <table className="compare-table capacity-table">
                    <thead><tr><th>Period</th><th>Route</th><th>Airline</th><th>Passengers</th><th>Seats filled</th><th>On-time</th><th>OTP flights</th></tr></thead>
                    <tbody>
                      {result.rows.map((row) => (
                        <tr key={`${row.year}-${row.month}-${row.carrier}-${row.origin}-${row.dest}`}>
                          <td>{row.year}-{String(row.month).padStart(2, "0")}</td>
                          <td><strong>{row.origin} → {row.dest}</strong></td>
                          <td>{row.carrier}</td>
                          <td>{formatInteger(row.passengers)}</td>
                          <td>{formatPercent(row.load_factor)}</td>
                          <td>{formatPercent(row.on_time_rate)}</td>
                          <td>{formatInteger(row.otp_flights)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </section>

          <section className="section capacity-footer-grid">
            <div className="screen mini-method-card">
              <p className="eyebrow">What T-100 adds</p>
              <h3>Demand and capacity context</h3>
              <p>Passengers, seats, scheduled departures, and performed departures help describe how heavily a route was being used.</p>
            </div>
            <div className="screen mini-method-card">
              <p className="eyebrow">What it does not add</p>
              <h3>A certified capacity limit</h3>
              <p>This dataset does not contain runway, gate, crew, weather, or causal intervention information. Those remain future research directions.</p>
            </div>
          </section>
          <p className="page-note source-line">{result.source}. <Link href="/glossary">See the glossary</Link> for on-time and load-factor definitions, or <Link href="/methodology#t-100-and-on-time-correlation">open the methodology</Link> for the join and correlation details.</p>
        </>
      )}
    </main>
  );
}

function MetricTile({ label, value, tone }: { label: string; value: string; tone?: "signal" }) {
  return <div className="tile"><span className="tile-label">{label}</span><span className={`tile-value ${tone === "signal" ? "signal" : ""}`}>{value}</span></div>;
}
