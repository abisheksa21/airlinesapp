"use client";

import { useState } from "react";
import Link from "next/link";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import DateRangePreset from "../DateRangePreset";
import { carrierName } from "../../lib/carriers";
import { ChartFrame } from "./ChartFrame";
import { MetricCard } from "./MetricCard";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";
type ScopeKind = "carrier" | "airport" | "route";
type ScopeResult = {
  kind: ScopeKind;
  entity: string;
  total_flights: number;
  completed_flights: number;
  on_time_rate: number | null;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number | null;
  start_date: string | null;
  end_date: string | null;
  months: Array<{ month: string; total_flights: number; on_time_rate: number | null }>;
  scope_method: string;
};

function percent(value: number | null | undefined) { return value == null ? "—" : `${(value * 100).toFixed(1)}%`; }
function integer(value: number | null | undefined) { return value == null ? "—" : new Intl.NumberFormat("en-US").format(value); }
function delay(value: number | null | undefined) { return value == null ? "—" : `${value.toFixed(1)} min`; }
function periodText(result: ScopeResult) { return result.start_date && result.end_date ? `${result.start_date} to ${result.end_date}` : "All available history"; }
function profileHref(kind: ScopeKind, selected: { carrier: string; airport: string; origin: string; dest: string }) {
  if (kind === "carrier") return `/carriers/${selected.carrier}`;
  if (kind === "airport") return `/airports/${selected.airport}`;
  return `/routes/${selected.origin}-${selected.dest}`;
}

export function PublicScopeLookup({ kind, carrierOptions = [], airportOptions = [] }: { kind: ScopeKind; carrierOptions?: string[]; airportOptions?: string[] }) {
  const [carrier, setCarrier] = useState("");
  const [airport, setAirport] = useState("");
  const [origin, setOrigin] = useState("");
  const [dest, setDest] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [result, setResult] = useState<ScopeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [rangeReady, setRangeReady] = useState(true);

  function changed(action: () => void) { action(); setResult(null); setError(""); }

  async function lookup() {
    setBusy(true);
    setError("");
    setResult(null);
    const params = new URLSearchParams({ kind });
    if (kind === "carrier") params.set("carrier", carrier);
    if (kind === "airport") params.set("airport", airport);
    if (kind === "route") { params.set("origin", origin); params.set("dest", dest); }
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    try {
      const response = await fetch(`${API_BASE}/api/public/scope-summary?${params.toString()}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The selected period could not be loaded.");
      setResult(payload as ScopeResult);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The selected period could not be loaded.");
    } finally {
      setBusy(false);
    }
  }

  const valid = kind === "carrier" ? Boolean(carrier) : kind === "airport" ? Boolean(airport) : Boolean(origin && dest && origin !== dest);
  const canLookup = valid && rangeReady && !busy;
  const entityName = kind === "carrier" ? "airline" : kind;
  const range = result ? periodText(result) : "Selected historical period";

  return <section className="public-scope-panel" aria-labelledby={`scope-title-${kind}`}>
    <div className="public-scope-heading"><div><span className="section-label">Your selection</span><h2 id={`scope-title-${kind}`}>Check one {entityName} over time.</h2><p>Choose the object and period. The results below use only that selection.</p></div><span className="public-scope-mark">BTS HISTORY</span></div>
    <div className="public-scope-controls">
      {kind === "carrier" && <label className="filter-field"><span className="filter-label">Airline</span><select value={carrier} onChange={(event) => changed(() => setCarrier(event.target.value))}><option value="">Choose an airline</option>{carrierOptions.map((code) => <option key={code} value={code}>{code} — {carrierName(code)}</option>)}</select></label>}
      {kind === "airport" && <label className="filter-field"><span className="filter-label">Airport</span><select value={airport} onChange={(event) => changed(() => setAirport(event.target.value))}><option value="">Choose an airport</option>{airportOptions.map((code) => <option key={code} value={code}>{code}</option>)}</select></label>}
      {kind === "route" && <><label className="filter-field"><span className="filter-label">Origin</span><select value={origin} onChange={(event) => changed(() => setOrigin(event.target.value))}><option value="">Choose origin</option>{airportOptions.map((code) => <option key={code} value={code}>{code}</option>)}</select></label><label className="filter-field"><span className="filter-label">Destination</span><select value={dest} onChange={(event) => changed(() => setDest(event.target.value))}><option value="">Choose destination</option>{airportOptions.map((code) => <option key={code} value={code}>{code}</option>)}</select></label></>}
      <DateRangePreset startDate={startDate} endDate={endDate} onChange={(start, end) => changed(() => { setStartDate(start); setEndDate(end); })} onReadyChange={setRangeReady} includeAllTimeAndMonth />
      <button type="button" className="public-scope-submit" onClick={lookup} disabled={!canLookup}>{busy ? "Reading the record…" : "Show results"}</button>
    </div>
    <p className="public-scope-hint">{!rangeReady ? "Choose the year, month, holiday year, or both custom dates before showing results." : "Year and month filters use the monthly warehouse summaries. Holiday and custom dates use the exact dates you select."}</p>
    {error && <p className="public-scope-error" role="alert">{error}</p>}
    {result && <div className="public-scope-result" aria-live="polite">
      <div className="public-scope-result-title"><div><span className="section-label">Selected result · {result.kind}</span><h3>{kind === "carrier" ? carrierName(result.entity) : result.entity}</h3></div><span>{periodText(result)}</span></div>
      <div className="public-metric-grid"><MetricCard label="Observed flights" value={integer(result.total_flights)} detail={`${integer(result.completed_flights)} completed`} /><MetricCard label="On-time arrival" value={percent(result.on_time_rate)} detail="Arrival within 15 minutes" tone="good" /><MetricCard label="Average arrival delay" value={delay(result.avg_arrival_delay_minutes)} detail="Completed flights" tone="watch" /><MetricCard label="Cancellation rate" value={percent(result.cancellation_rate)} detail="Cancelled ÷ scheduled" tone="critical" /></div>
      <ChartFrame title="Monthly on-time pattern in this selection" interpretation="Each point summarizes this selected object for one month. A historical pattern describes those records; it does not predict a specific future flight." evidence={{ source: "BTS Marketing Carrier On-Time Performance", period: range, sample: `${integer(result.total_flights)} flights`, method: result.scope_method, caveat: "Holiday/custom periods are exact dates; their chart groups matching records by calendar month." }}>
        {result.months.length ? <div className="public-scope-chart"><ResponsiveContainer width="100%" height={235}><LineChart data={result.months.map((month) => ({ ...month, on_time_percent: month.on_time_rate == null ? null : Number((month.on_time_rate * 100).toFixed(1)) }))} margin={{ top: 8, right: 18, left: -16, bottom: 0 }}><XAxis dataKey="month" tick={{ fontSize: 10, fill: "#64748b" }} minTickGap={35} tickLine={false} axisLine={false} /><YAxis domain={[50, 100]} tickFormatter={(value) => `${value}%`} tick={{ fontSize: 10, fill: "#64748b" }} tickLine={false} axisLine={false} /><Tooltip formatter={(value) => [`${value}%`, "On-time arrival"]} labelFormatter={(label) => `Month: ${label}`} /><Line type="monotone" dataKey="on_time_percent" stroke="#167b83" strokeWidth={2.5} dot={result.months.length === 1 ? { r: 4 } : false} activeDot={{ r: 4 }} connectNulls /></LineChart></ResponsiveContainer></div> : <p>No monthly observations fall within this selection.</p>}
      </ChartFrame>
      <Link className="public-scope-profile-link" href={profileHref(kind, { carrier, airport, origin, dest })}>Open the full {kind} profile →</Link>
    </div>}
  </section>;
}
