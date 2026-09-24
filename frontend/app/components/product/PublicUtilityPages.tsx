"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChartFrame } from "./ChartFrame";
import { EntityHeader } from "./EntityHeader";
import { NetworkGraph } from "./NetworkGraph";
import { DataTable } from "./DataTable";
import { ErrorState, LoadingState } from "./states";
import type { NetworkMap, Summary } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";
function percent(value: number | null | undefined) { return value == null ? "—" : `${(value * 100).toFixed(1)}%`; }
function integer(value: number | null | undefined) { return value == null ? "—" : new Intl.NumberFormat("en-US").format(value); }

export function PublicNetworkPage() {
  const [data, setData] = useState<NetworkMap | null>(null); const [failed, setFailed] = useState(false);
  useEffect(() => { let current = true; fetch(`${API_BASE}/api/network-map?limit=48`).then((response) => response.ok ? response.json() : Promise.reject()).then((value) => { if (current) setData(value); }).catch(() => { if (current) setFailed(true); }); return () => { current = false; }; }, []);
  return <div className="public-page public-network-page">
    <header className="network-page-heading">
      <div><p className="section-label">PUBLIC VIEW · ROUTE NETWORK</p><h1>Explore the U.S. route map.</h1><p>Select an airport for its profile or a line to open the route direction. This is historical BTS coverage, not live flight tracking.</p></div>
      {data && <div className="network-top-coverage" aria-label="Map coverage"><span><b>{integer(data.coverage.airports_mapped)}</b> airports</span><span><b>{integer(data.coverage.routes_mapped)}</b> directional routes</span><span>{data.period.start_date} — {data.period.end_date}</span></div>}
    </header>
    {failed ? <section className="network-load-state"><ErrorState title="Network map unavailable" /></section> : !data ? <section className="network-load-state"><LoadingState title="Loading the route map" /></section> : <section className="network-map-surface" aria-label="Historical U.S. route map">
      <div className="network-map-surface-heading"><div><span className="section-label">HIGH-VOLUME CONNECTIONS</span><h2>Airport pairs on U.S. geography</h2></div><details className="network-map-method"><summary>Map scope &amp; method</summary><p>{data.source}; U.S. state boundaries from Census TIGERweb. The map combines reciprocal directions into one airport-pair line; selecting a line reveals each directional profile. This is a volume-ranked, coordinate-covered slice—not every U.S. airport or route. Alaska and Hawaii are location insets, schematic and not to scale.</p></details></div>
      <NetworkGraph data={data} />
      <p className="network-map-key"><span><i className="network-key-airport" /> Selectable airport</span><span><i className="network-key-route" /> Selectable airport pair; thicker lines mean more recorded flights combined</span><span>AK/HI insets are schematic · not to scale</span></p>
      <footer className="network-map-source"><span><b>PERIOD</b>{data.period.start_date} to {data.period.end_date}</span><span><b>COVERAGE</b>{integer(data.coverage.airports_mapped)} airports · {integer(data.coverage.routes_mapped)} directional routes</span><span><b>READ THIS AS</b>Historical connections, not a complete national route inventory</span></footer>
    </section>}
  </div>;
}

export function InsightsPage() {
  const [summary, setSummary] = useState<Summary | null>(null); const [trend, setTrend] = useState<Array<{ month: string; on_time_rate: number | null; total_flights: number }>>([]); const [failed, setFailed] = useState(false); const [showAllMonths, setShowAllMonths] = useState(false);
  useEffect(() => { let current = true; Promise.all([fetch(`${API_BASE}/api/summary`).then((response) => response.ok ? response.json() : Promise.reject()), fetch(`${API_BASE}/api/trend`).then((response) => response.ok ? response.json() : Promise.reject())]).then(([summaryPayload, trendPayload]) => { if (current) { setSummary(summaryPayload); setTrend(trendPayload.months ?? []); } }).catch(() => { if (current) setFailed(true); }); return () => { current = false; }; }, []);
  const latest = trend.at(-1); const previous = trend.at(-2); const change = latest?.on_time_rate != null && previous?.on_time_rate != null ? (latest.on_time_rate - previous.on_time_rate) * 100 : null;
  const trendRows = trend.slice(-12).reverse();
  return <div className="public-page public-insights-page"><EntityHeader eyebrow="Public insights" title="Read a signal, then inspect its evidence." description="A short read of the latest system-wide result, its coverage, and what the data cannot tell us." researchHref="/research" />{failed ? <section className="public-section"><ErrorState title="Insights are unavailable" /></section> : !summary ? <section className="public-section"><LoadingState title="Preparing curated signals" /></section> : <><section className="public-section insight-overview"><article className="insight-lead"><span className="section-label">Latest recorded month</span><h2>{latest?.month ?? summary.end_date}: {percent(latest?.on_time_rate)} on-time.</h2><p>{change == null ? "The previous month is not available for a direct comparison." : `${change >= 0 ? "Up" : "Down"} ${Math.abs(change).toFixed(1)} percentage points from the preceding observed month. This describes two historical totals; it does not explain what caused the change.`}</p></article><div className="public-story-grid"><article className="public-story-card"><span className="section-label">System coverage</span><h3>{integer(summary.total_flights)} stored flight records.</h3><p>{integer(summary.unique_airports)} airports and {integer(summary.unique_routes)} directional routes. Check the specific place and period before drawing a conclusion.</p><Link href="/network">Explore the network →</Link></article><article className="public-story-card"><span className="section-label">Data boundary</span><h3>History is not a live forecast.</h3><p>Records run through {summary.end_date}. Weather, air-traffic constraints, and airline operations can make a future flight differ from its history.</p><Link href="/methodology">How to read the measures →</Link></article></div></section><section className="public-section insight-trend-section"><ChartFrame className="insight-trend-frame" title="Recent observed network months" interpretation="A compact view of how the network-wide on-time rate has moved. Month-to-month movement does not identify a cause." evidence={{ source: "BTS Marketing Carrier On-Time Performance", period: `${trend.at(0)?.month ?? summary.start_date} to ${latest?.month ?? summary.end_date}`, sample: `${trend.length} months`, method: "Network-month aggregation", caveat: "A change between two months does not identify a causal driver." }}><DataTable columns={["Month", "On-time arrival", "Observed flights"]} rows={(showAllMonths ? trendRows : trendRows.slice(0, 6)).map((item) => [item.month, percent(item.on_time_rate), integer(item.total_flights)])} />{trendRows.length > 6 && <button className="directory-show-more" type="button" onClick={() => setShowAllMonths((shown) => !shown)}>{showAllMonths ? "Show fewer months" : `Show ${trendRows.length - 6} more months`} <span aria-hidden="true">{showAllMonths ? "↑" : "↓"}</span></button>}</ChartFrame></section></>}</div>;
}
