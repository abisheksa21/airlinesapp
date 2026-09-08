"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CARRIER_NAMES, carrierName } from "../lib/carriers";
import { formatInteger, formatNumber, formatPercent } from "../lib/format";
import type { CapacityCorrelationResult } from "../decision-center/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const CARRIER_CODES = Object.keys(CARRIER_NAMES);

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
  const [carrier, setCarrier] = useState("");
  const [minimumFlights, setMinimumFlights] = useState("100");
  const [result, setResult] = useState<CapacityCorrelationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ limit: "30", minimum_flights: minimumFlights });
    if (carrier) params.set("carrier", carrier);
    try {
      const response = await fetch(`${API_BASE}/api/capacity/correlation?${params}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The T-100 comparison is unavailable.");
      setResult(payload);
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "The T-100 comparison is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  return (
    <main className="page">
      <header className="header research-hero">
        <p className="eyebrow">Researcher view · BTS T-100 + OTP</p>
        <h1 className="title">Traffic context for on-time performance.</h1>
        <p className="subtitle">
          T-100 tells us how many seats and passengers moved on a route each month.
          This page checks whether that traffic context moves with the same month&apos;s on-time result.
        </p>
        <div className="hero-actions">
          <span className="status-chip"><span className="status-chip-dot" /> Evidence surface</span>
          <Link href="/methodology#t-100-and-on-time-correlation" className="text-link">Read the full method →</Link>
        </div>
      </header>

      <section className="capacity-explainer">
        <div>
          <p className="eyebrow">The question</p>
          <h2>Does a fuller route look different operationally?</h2>
        </div>
        <p>
          We compare the two datasets at the same level: <strong>carrier + route + month</strong>.
          The result is an association to investigate, not a claim that passenger demand causes delay.
        </p>
      </section>

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Choose the evidence slice</h2>
          <span className="section-note">No synthetic traffic values</span>
        </div>
        <div className="screen capacity-controls">
          <label className="filter-field">
            <span className="filter-label">Airline (optional)</span>
            <select value={carrier} onChange={(event) => setCarrier(event.target.value)}>
              <option value="">All carriers</option>
              {CARRIER_CODES.map((code) => <option key={code} value={code}>{code} — {carrierName(code)}</option>)}
            </select>
          </label>
          <label className="filter-field">
            <span className="filter-label">Minimum OTP flights per route-month</span>
            <input type="number" min="1" max="10000" value={minimumFlights} onChange={(event) => setMinimumFlights(event.target.value)} />
          </label>
          <button type="button" className="compare-run" onClick={() => void load()} disabled={loading}>
            {loading ? "Loading evidence…" : "Refresh comparison"}
          </button>
        </div>
      </section>

      {error && <div className="callout callout-warn">{error}</div>}

      {result && (
        <>
          <section className="section">
            <div className="section-head">
              <h2 className="section-title">What the matched history says</h2>
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

          <section className="section">
            <div className="section-head">
              <h2 className="section-title">Largest matched route-months</h2>
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
