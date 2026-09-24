"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import DateRangePreset from "../DateRangePreset";
import { carrierName } from "../../lib/carriers";
import { ChartFrame } from "./ChartFrame";
import { DataTable } from "./DataTable";
import { Breadcrumbs, EntityHeader } from "./EntityHeader";
import { ErrorState, LoadingState } from "./states";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";
type Carrier = { carrier: string; total_flights: number; completed_flights: number; on_time_rate: number | null; avg_arrival_delay_minutes: number | null; cancellation_rate: number | null };
type Airport = { airport: string; total_flights: number; completed_flights: number; on_time_rate: number | null; avg_arrival_delay_minutes: number | null; cancellation_rate: number | null };
type Route = { route: string; total_flights: number; completed_flights: number; on_time_rate: number | null; avg_arrival_delay_minutes: number | null; cancellation_rate: number | null };
type DirectoryRow = Carrier | Airport | Route;
type ChartDatum = { label: string; value: number };
type DirectoryKind = "carrier" | "airport" | "route";

function percent(value: number | null | undefined) { return value == null ? "—" : `${(value * 100).toFixed(1)}%`; }
function integer(value: number | null | undefined) { return value == null ? "—" : new Intl.NumberFormat("en-US").format(value); }
function delay(value: number | null | undefined) { return value == null ? "—" : `${value.toFixed(1)} min`; }
function routeHref(route: string) { const [origin, destination] = route.split("→").map((part) => part.trim()); return origin && destination ? `/routes/${origin}-${destination}` : "/routes"; }

function DirectoryIntro({ crumb, eyebrow, title, description, researchHref }: { crumb: string; eyebrow: string; title: string; description: string; researchHref: string }) {
  return <div className="directory-intro"><Breadcrumbs items={[{ label: crumb }]} /><EntityHeader eyebrow={eyebrow} title={title} description={description} researchHref={researchHref} />
  </div>;
}

function DirectoryFilter({ label, value, onChange, placeholder, count }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; count: string }) {
  const id = `filter-${label.toLowerCase()}`;
  return <div className="directory-local-filter"><label htmlFor={id}><span className="section-label">Search these results · {label}</span><input id={id} type="search" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label><span className="directory-filter-count">{count}</span></div>;
}

function ExpandableTable({ columns, rows, initialCount = 8 }: { columns: string[]; rows: ReactNode[][]; initialCount?: number }) {
  const [expanded, setExpanded] = useState(false);
  const visibleRows = expanded ? rows : rows.slice(0, initialCount);
  return <div className="directory-expandable-table"><p>Showing {visibleRows.length} of {rows.length} matches</p><DataTable columns={columns} rows={visibleRows} />{rows.length > initialCount && <button type="button" className="directory-show-more" onClick={() => setExpanded((value) => !value)}>{expanded ? "Show fewer" : `Show all ${rows.length}`} <span aria-hidden="true">{expanded ? "↑" : "↓"}</span></button>}</div>;
}

function RankedBarChart({ rows, measure, valueFormatter, color = "#1b6f9b", limit = 8 }: { rows: ChartDatum[]; measure: string; valueFormatter: (value: number) => string; color?: string; limit?: number }) {
  const visibleRows = rows.slice(0, limit);
  if (!visibleRows.length) return <p className="directory-empty">No matching objects in this period. Try a wider date range or clear a selection.</p>;
  const chartHeight = Math.min(390, Math.max(112, visibleRows.length * 31 + 46));
  return <div className="directory-bar-chart"><ResponsiveContainer width="100%" height={chartHeight}><BarChart data={visibleRows} layout="vertical" margin={{ top: 4, right: 18, left: 4, bottom: 4 }}><XAxis type="number" tick={{ fontSize: 10, fill: "#718094" }} tickFormatter={valueFormatter} axisLine={false} tickLine={false} /><YAxis dataKey="label" type="category" width={86} tick={{ fontSize: 10, fill: "#42566b" }} axisLine={false} tickLine={false} /><Tooltip cursor={{ fill: "#edf4f4" }} formatter={(value: number | string) => [valueFormatter(Number(value)), measure]} /><Bar dataKey="value" fill={color} radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer></div>;
}

function useDirectory<T>(url: string, key: string) {
  const [data, setData] = useState<T[]>([]);
  const [availableThrough, setAvailableThrough] = useState<string | undefined>();
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let current = true;
    setLoading(true);
    setFailed(false);
    fetch(`${API_BASE}${url}`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((payload) => { if (current) { setData(payload[key] ?? []); setAvailableThrough(payload.end_date); } })
      .catch(() => { if (current) setFailed(true); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [key, url]);
  return { data, failed, loading, availableThrough };
}

function DirectoryPeriodFilter({
  kind,
  carrierOptions = [],
  airportOptions = [],
  availableThrough,
  onApply,
  onReset,
}: {
  kind: DirectoryKind;
  carrierOptions?: string[];
  airportOptions?: string[];
  availableThrough?: string;
  onApply: (rows: DirectoryRow[], period: string, method: string, focus: string, focusItem?: DirectoryRow) => void;
  onReset: () => void;
}) {
  const [carrier, setCarrier] = useState("");
  const [airport, setAirport] = useState("");
  const [origin, setOrigin] = useState("");
  const [dest, setDest] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [presetKey, setPresetKey] = useState(0);
  const [rangeReady, setRangeReady] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function apply() {
    setBusy(true);
    setError("");
    const params = new URLSearchParams({ kind, limit: kind === "airport" ? "500" : "50" });
    // Carrier and airport choices are focus reads, not peer-list filters.
    // Keep every peer for the same period; the local search box controls chart/table rows.
    if (kind === "route") {
      if (origin) params.set("origin", origin);
      if (dest) params.set("dest", dest);
    }
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    try {
      const response = await fetch(`${API_BASE}/api/public/directory-scope?${params.toString()}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not load these directory results.");
      let focusItem: DirectoryRow | undefined;
      if (kind === "airport" && airport) {
        const focusedParams = new URLSearchParams(params);
        focusedParams.set("airport", airport);
        focusedParams.set("limit", "1");
        const focusedResponse = await fetch(`${API_BASE}/api/public/directory-scope?${focusedParams.toString()}`);
        if (focusedResponse.ok) {
          const focusedPayload = await focusedResponse.json();
          focusItem = focusedPayload.rows?.[0] as Airport | undefined;
        }
      }
      const period = payload.start_date && payload.end_date ? `${payload.start_date} to ${payload.end_date}` : "All available history";
      const focus = kind === "carrier" ? carrier : kind === "airport" ? airport : origin && dest ? `${origin}→${dest}` : origin || dest;
      onApply((payload.rows ?? []) as DirectoryRow[], period, payload.scope_method ?? "Exact flight dates", focus, focusItem);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load these directory results.");
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setCarrier(""); setAirport(""); setOrigin(""); setDest(""); setStartDate(""); setEndDate("");
    setError(""); setPresetKey((value) => value + 1); onReset();
  }

  const heading = kind === "carrier" ? "Filter airlines and time" : kind === "airport" ? "Filter airports and time" : "Filter routes and time";
  const instruction = kind === "carrier"
    ? "Choose an airline to focus it, then compare it with every carrier over the same period."
    : kind === "airport"
      ? "Choose an airport to focus its profile, then compare it with other airports over the same period."
      : "Choose an origin and destination to inspect that direction; the reverse route is separate.";
  const sameAirportRoute = kind === "route" && Boolean(origin) && origin === dest;
  const selectedDirection = origin && dest ? `${origin} → ${dest}` : origin ? `${origin} → choose destination` : dest ? `Choose origin → ${dest}` : "All directional routes";
  return <section className="public-scope-panel directory-period-filter" aria-label={`${kind} directory filters`}>
    <div className="public-scope-heading"><div><span className="section-label">Change what the directory compares</span><h2>{heading}</h2><p>{instruction} Applying the filter refreshes the numbers, chart, and table together.</p></div><span className="public-scope-mark">BTS HISTORY</span></div>
    <div className="public-scope-controls">
      {kind === "carrier" && <label className="filter-field"><span className="filter-label">Airline</span><select value={carrier} onChange={(event) => setCarrier(event.target.value)}><option value="">All airlines</option>{carrierOptions.map((code) => <option key={code} value={code}>{code} — {carrierName(code)}</option>)}</select></label>}
      {kind === "airport" && <label className="filter-field"><span className="filter-label">Airport</span><select value={airport} onChange={(event) => setAirport(event.target.value)}><option value="">All airports</option>{airportOptions.map((code) => <option key={code} value={code}>{code}</option>)}</select></label>}
      {kind === "route" && <><label className="filter-field"><span className="filter-label">Origin</span><select value={origin} onChange={(event) => setOrigin(event.target.value)}><option value="">All origins</option>{airportOptions.map((code) => <option key={code} value={code}>{code}</option>)}</select></label><label className="filter-field"><span className="filter-label">Destination</span><select value={dest} onChange={(event) => setDest(event.target.value)}><option value="">All destinations</option>{airportOptions.map((code) => <option key={code} value={code}>{code}</option>)}</select></label></>}
      <DateRangePreset key={presetKey} startDate={startDate} endDate={endDate} onChange={(start, end) => { setStartDate(start); setEndDate(end); }} onReadyChange={setRangeReady} includeAllTimeAndMonth latestAvailableDate={availableThrough} />
      <button type="button" className="public-scope-submit" onClick={apply} disabled={busy || !rangeReady || (kind === "route" && Boolean(origin) && origin === dest)}>{busy ? "Updating results…" : "Apply filters"}</button>
      <button type="button" className="directory-filter-reset" onClick={reset} disabled={busy}>Reset</button>
    </div>
    {kind === "route" && <div className="directory-route-direction" aria-live="polite"><span>ROUTE DIRECTION</span><strong>{selectedDirection}</strong><small>{origin && dest ? `This is ${origin} → ${dest}; ${dest} → ${origin} is a different result.` : "Choose both airports to see the direction that will be queried."}</small></div>}
    <p className="public-scope-hint">{sameAirportRoute ? "Choose different origin and destination airports." : <>Calendar years/months use the compact monthly warehouse. Holiday and custom ranges use the exact dates selected. {kind === "route" ? "Routes remain directional." : ""}</>}</p>
    {error && <p className="public-scope-error" role="alert">{error}</p>}
  </section>;
}

function periodEvidence(period: string, count: number, method: string, scopeMethod: string, caveat: string) {
  return { source: "BTS Marketing Carrier On-Time Performance", period, sample: `${count} directory results`, method: `${method} · ${scopeMethod}`, caveat };
}

export function CarrierDirectory() {
  const { data: initial, failed, loading, availableThrough } = useDirectory<Carrier>("/api/public/directory-scope?kind=carrier&limit=50", "rows");
  const [scoped, setScoped] = useState<Carrier[] | null>(null);
  const [period, setPeriod] = useState("All available history");
  const [scopeMethod, setScopeMethod] = useState("compact monthly aggregates");
  const [focusedCarrier, setFocusedCarrier] = useState("");
  const [query, setQuery] = useState("");
  const data = scoped ?? initial;
  const filtered = useMemo(() => { const term = query.trim().toLowerCase(); return term ? data.filter((item) => `${item.carrier} ${carrierName(item.carrier)}`.toLowerCase().includes(term)) : data; }, [data, query]);
  const focus = useMemo(() => {
    if (!focusedCarrier) return null;
    const item = data.find((row) => row.carrier === focusedCarrier);
    if (!item) return null;
    const comparable = data.filter((row) => row.on_time_rate != null && row.completed_flights > 0);
    const completed = comparable.reduce((sum, row) => sum + row.completed_flights, 0);
    const networkRate = completed ? comparable.reduce((sum, row) => sum + (row.on_time_rate ?? 0) * row.completed_flights, 0) / completed : null;
    const rank = [...comparable].sort((a, b) => (b.on_time_rate ?? 0) - (a.on_time_rate ?? 0)).findIndex((row) => row.carrier === focusedCarrier) + 1;
    return { item, networkRate, rank, count: comparable.length };
  }, [data, focusedCarrier]);
  return <div className="public-page public-directory-page"><DirectoryIntro crumb="Carriers" eyebrow="Carrier directory" title="Airline performance, with context." description="Compare U.S. marketing carriers in the BTS flight record. Open a profile for its routes, airports, and delay patterns." researchHref="/research/explore?object=carrier" />
    {!failed && <DirectoryPeriodFilter kind="carrier" carrierOptions={initial.map((item) => item.carrier)} availableThrough={availableThrough} onApply={(rows, nextPeriod, method, focus) => { setScoped(rows as Carrier[]); setPeriod(nextPeriod); setScopeMethod(method); setFocusedCarrier(focus); setQuery(""); }} onReset={() => { setScoped(null); setPeriod("All available history"); setScopeMethod("compact monthly aggregates"); setFocusedCarrier(""); setQuery(""); }} />}
    {!loading && focus && <section className="directory-focus-read directory-focus-before-search" aria-live="polite"><div><span className="section-label">AIRLINE IN CONTEXT · {period}</span><h2>{carrierName(focus.item.carrier)} <small>({focus.item.carrier})</small></h2><p>{percent(focus.item.on_time_rate)} on time across {integer(focus.item.completed_flights)} completed flights; {focus.networkRate == null ? "no network comparison is available" : `${(Math.abs((focus.item.on_time_rate ?? 0) - focus.networkRate) * 100).toFixed(1)} points ${(focus.item.on_time_rate ?? 0) >= focus.networkRate ? "above" : "below"} the flight-weighted average across ${focus.count} carriers`}.</p></div><div className="directory-focus-stats"><span><b>{focus.rank || "—"} / {focus.count}</b><small>on-time rank</small></span><span><b>{delay(focus.item.avg_arrival_delay_minutes)}</b><small>average arrival delay</small></span><span><b>{percent(focus.item.cancellation_rate)}</b><small>cancellation rate</small></span></div><Link href={`/carriers/${focus.item.carrier}`}>Open full profile ↗</Link></section>}
    <DirectoryFilter label="airlines" value={query} onChange={setQuery} placeholder="Search results by name or code, e.g. Delta or DL" count={`${filtered.length} of ${data.length} carriers · ${period}`} />
    {failed ? <ErrorState title="Carrier directory unavailable" /> : loading ? <LoadingState title="Ranking carriers" /> : !data.length ? <p className="directory-empty">No carriers match this period. Reset the filters or choose a wider range.</p> : <section className="public-section directory-results">
      <ChartFrame title="On-time arrival by carrier" interpretation={`Comparison for ${period.toLowerCase()}. The selected airline stays beside its peers; the same period is applied to the table below.`} evidence={periodEvidence(period, filtered.length, "Carrier-level aggregation; on-time rate weighted by completed flights", scopeMethod, "Carriers serve different networks, airports, and time periods.")}><RankedBarChart rows={filtered.filter((item) => item.on_time_rate != null).map((item) => ({ label: `${item.carrier}${item.carrier === focusedCarrier ? " · selected" : ""}`, value: Number(((item.on_time_rate ?? 0) * 100).toFixed(1)) }))} measure="On-time arrival" valueFormatter={(value) => `${value.toFixed(1)}%`} limit={12} /></ChartFrame>
      <ChartFrame title="Carrier reliability comparison" interpretation="Observed flight volume, on-time rate, arrival delay, and cancellations for the selected period." evidence={periodEvidence(period, filtered.length, "Rates weighted by their underlying flight counts", scopeMethod, "This is a descriptive comparison, not a causal ranking.")}><ExpandableTable columns={["Carrier", "Flights", "On-time", "Avg delay", "Cancelled"]} rows={filtered.map((item) => [<Link key={item.carrier} href={`/carriers/${item.carrier}`}>{carrierName(item.carrier)} <small>({item.carrier})</small></Link>, integer(item.total_flights), percent(item.on_time_rate), delay(item.avg_arrival_delay_minutes), percent(item.cancellation_rate)])} /></ChartFrame>
    </section>}
  </div>;
}

export function AirportDirectory() {
  const { data: initial, failed, loading, availableThrough } = useDirectory<Airport>("/api/public/directory-scope?kind=airport&limit=500", "rows");
  const { data: airportOptions } = useDirectory<string>("/api/airports/list", "airports");
  const [scoped, setScoped] = useState<Airport[] | null>(null);
  const [period, setPeriod] = useState("All available history");
  const [scopeMethod, setScopeMethod] = useState("compact monthly aggregates");
  const [focusedAirport, setFocusedAirport] = useState("");
  const [focusedAirportRecord, setFocusedAirportRecord] = useState<Airport | null>(null);
  const [query, setQuery] = useState("");
  const data = scoped ?? initial;
  const filtered = useMemo(() => { const term = query.trim().toLowerCase(); return term ? data.filter((item) => item.airport.toLowerCase().includes(term)) : data; }, [data, query]);
  const focused = focusedAirportRecord ?? (focusedAirport ? data.find((item) => item.airport === focusedAirport) ?? null : null);
  return <div className="public-page public-directory-page"><DirectoryIntro crumb="Airports" eyebrow="Airport directory" title="Where the network is concentrated." description="See where U.S. flight activity clusters, then compare activity and historical performance over a chosen period." researchHref="/research/explore?object=airport" />
    {!failed && <DirectoryPeriodFilter kind="airport" airportOptions={airportOptions} availableThrough={availableThrough} onApply={(rows, nextPeriod, method, focus, focusItem) => { setScoped(rows as Airport[]); setPeriod(nextPeriod); setScopeMethod(method); setFocusedAirport(focus); setFocusedAirportRecord((focusItem as Airport | undefined) ?? null); setQuery(""); }} onReset={() => { setScoped(null); setPeriod("All available history"); setScopeMethod("compact monthly aggregates"); setFocusedAirport(""); setFocusedAirportRecord(null); setQuery(""); }} />}
    {!loading && focused && <section className="directory-focus-read directory-focus-before-search" aria-live="polite"><div><span className="section-label">AIRPORT READ · {period}</span><h2>{focused.airport}</h2><p>{integer(focused.total_flights)} arrivals/departures are represented in this period. On-time and delay values describe the associated flights; they are not a measure of airport-controlled performance.</p></div><div className="directory-focus-stats"><span><b>{percent(focused.on_time_rate)}</b><small>associated flights on time</small></span><span><b>{delay(focused.avg_arrival_delay_minutes)}</b><small>average arrival delay</small></span><span><b>{percent(focused.cancellation_rate)}</b><small>cancellation rate</small></span></div><Link href={`/airports/${focused.airport}`}>Open airport profile ↗</Link></section>}
    <DirectoryFilter label="airports" value={query} onChange={setQuery} placeholder="Search results by IATA code, e.g. ORD" count={`${filtered.length} of ${data.length} airports · ${period}`} />
    {failed ? <ErrorState title="Airport directory unavailable" /> : loading ? <LoadingState title="Reading airport activity" /> : !data.length ? <p className="directory-empty">No airports match this period. Reset the filters or choose a wider range.</p> : <section className="public-section directory-results">
     <ChartFrame title="Airport activity at a glance" interpretation={`Arrivals and departures associated with each airport in ${period.toLowerCase()}. Activity is not, by itself, a measure of congestion.`} evidence={periodEvidence(period, filtered.length, "One record per flight endpoint at each airport", scopeMethod, "A volume count alone cannot show congestion or delay causality.")}><RankedBarChart rows={filtered.map((item) => ({ label: item.airport, value: item.total_flights }))} measure="Observed airport flight events" valueFormatter={(value) => integer(value)} color="#25836f" /></ChartFrame>
      <ChartFrame title="Airport comparison" interpretation="Activity and arrival performance for flights associated with each airport." evidence={periodEvidence(period, filtered.length, "Airport-level flight-event aggregation", scopeMethod, "On-time figures describe associated flights; they are not an airport-controlled outcome.")}><ExpandableTable columns={["Airport", "Flight events", "On-time", "Avg delay", "Profile"]} rows={filtered.map((item) => [<Link key={item.airport} href={`/airports/${item.airport}`}>{item.airport}</Link>, integer(item.total_flights), percent(item.on_time_rate), delay(item.avg_arrival_delay_minutes), <Link className="table-action" key={`${item.airport}-open`} href={`/airports/${item.airport}`}>Open →</Link>])} /></ChartFrame>
    </section>}
  </div>;
}

export function RouteDirectory() {
  const { data: initial, failed, loading, availableThrough } = useDirectory<Route>("/api/public/directory-scope?kind=route&limit=50", "rows");
  const { data: airportOptions } = useDirectory<string>("/api/airports/list", "airports");
  const [scoped, setScoped] = useState<Route[] | null>(null);
  const [period, setPeriod] = useState("All available history");
  const [scopeMethod, setScopeMethod] = useState("compact monthly aggregates");
  const [focusedRoute, setFocusedRoute] = useState("");
  const [query, setQuery] = useState("");
  const data = scoped ?? initial;
  const filtered = useMemo(() => { const term = query.trim().toLowerCase(); return term ? data.filter((item) => item.route.toLowerCase().includes(term)) : data; }, [data, query]);
  const focused = focusedRoute ? data.find((item) => item.route === focusedRoute) : null;
  const focusedEndpoints = focused?.route.split("→").map((part) => part.trim()) ?? [];
  return <div className="public-page public-directory-page"><DirectoryIntro crumb="Routes" eyebrow="Route explorer" title="Every direction has its own story." description="Routes are directional: LAX → SFO and SFO → LAX are measured separately. Compare a route or endpoint over time." researchHref="/research/explore?object=route" />
    {!failed && <DirectoryPeriodFilter kind="route" airportOptions={airportOptions} availableThrough={availableThrough} onApply={(rows, nextPeriod, method, focus) => { setScoped(rows as Route[]); setPeriod(nextPeriod); setScopeMethod(method); setFocusedRoute(focus); setQuery(""); }} onReset={() => { setScoped(null); setPeriod("All available history"); setScopeMethod("compact monthly aggregates"); setFocusedRoute(""); setQuery(""); }} />}
    {!loading && focused && <section className="directory-focus-read directory-focus-before-search route-focus-read" aria-live="polite"><div><span className="section-label">DIRECTIONAL ROUTE · {period}</span><h2>{focused.route}</h2><p>{integer(focused.total_flights)} scheduled flights in this direction; {percent(focused.on_time_rate)} arrived within 15 minutes. This is not the reverse route.</p></div><div className="directory-focus-stats"><span><b>{delay(focused.avg_arrival_delay_minutes)}</b><small>average arrival delay</small></span><span><b>{percent(focused.cancellation_rate)}</b><small>cancellation rate</small></span><span><b>{integer(focused.completed_flights)}</b><small>completed flights</small></span></div>{focusedEndpoints.length === 2 && <Link href={`/routes/${focusedEndpoints[1]}-${focusedEndpoints[0]}`}>See {focusedEndpoints[1]} → {focusedEndpoints[0]} instead ↗</Link>}</section>}
    <DirectoryFilter label="routes" value={query} onChange={setQuery} placeholder="Search results, e.g. LAX or LAX → SFO" count={`${filtered.length} of ${data.length} routes · ${period}`} />
    {failed ? <ErrorState title="Route directory unavailable" /> : loading ? <LoadingState title="Ranking directional routes" /> : !data.length ? <p className="directory-empty">No routes match this period. Reset the filters or choose a wider range.</p> : <section className="public-section directory-results">
      <ChartFrame title="On-time arrival across routes" interpretation={`Leading directional routes in ${period.toLowerCase()}. The same origin/destination direction is used in the list below.`} evidence={periodEvidence(period, filtered.length, "Directional route aggregation; on-time rate weighted by completed flights", scopeMethod, "The two directions are intentionally separate measures.")}><RankedBarChart rows={filtered.filter((item) => item.on_time_rate != null).map((item) => ({ label: item.route, value: Number(((item.on_time_rate ?? 0) * 100).toFixed(1)) }))} measure="On-time arrival" valueFormatter={(value) => `${value.toFixed(1)}%`} color="#8666c9" /></ChartFrame>
      <ChartFrame title="Most-observed directional routes" interpretation="Open a route profile for its historical pattern and carrier mix." evidence={periodEvidence(period, filtered.length, "Directional route aggregation", scopeMethod, "A route’s performance varies by carrier, departure time, and period.")}><ExpandableTable columns={["Route", "Flights", "On-time", "Avg delay", "Profile"]} rows={filtered.map((item) => [<Link key={item.route} href={routeHref(item.route)}>{item.route}</Link>, integer(item.total_flights), percent(item.on_time_rate), delay(item.avg_arrival_delay_minutes), <Link key={`${item.route}-open`} className="table-action" href={routeHref(item.route)}>Open →</Link>])} /></ChartFrame>
    </section>}
  </div>;
}
