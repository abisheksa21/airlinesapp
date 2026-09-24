"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ErrorState, LoadingState } from "./components/product/states";
import { MetricCard } from "./components/product/MetricCard";
import type { Summary } from "./components/product/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";
type TrendPoint = { month?: string; year_month?: string; on_time_rate: number | null; total_flights?: number };
type HomeData = { summary: Summary; trend: TrendPoint[] };

function percent(value: number | null | undefined) { return value == null ? "—" : `${(value * 100).toFixed(1)}%`; }
function integer(value: number | null | undefined) { return value == null ? "—" : new Intl.NumberFormat("en-US").format(value); }

function TrendSparkline({ trend }: { trend: TrendPoint[] }) {
  const points = trend.filter((point) => point.on_time_rate != null).slice(-12);
  if (points.length < 2) return <div className="overview-sparkline-empty">Not enough monthly history for a trend.</div>;

  const values = points.map((point) => point.on_time_rate ?? 0);
  const min = Math.min(...values);
  const range = Math.max(...values) - min || 0.01;
  const path = values.map((value, index) => {
    const x = 4 + (index / (values.length - 1)) * 292;
    const y = 58 - ((value - min) / range) * 46;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  return <svg className="overview-sparkline" viewBox="0 0 300 64" role="img" aria-label="On-time arrival rate across the latest 12 recorded months">
    <path d="M4 59 H296" className="overview-sparkline-baseline" />
    <path d={path} className="overview-sparkline-line" />
  </svg>;
}

export default function PublicHome() {
  const [data, setData] = useState<HomeData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let current = true;
    Promise.all([
      fetch(`${API_BASE}/api/summary`).then((response) => response.ok ? response.json() : Promise.reject()),
      fetch(`${API_BASE}/api/trend`).then((response) => response.ok ? response.json() : Promise.reject()),
    ]).then(([summary, trendData]) => {
      if (current) setData({ summary, trend: trendData.months ?? trendData.trend ?? [] });
    }).catch(() => { if (current) setError(true); });
    return () => { current = false; };
  }, []);

  const movement = useMemo(() => {
    if (!data?.trend?.length) return null;
    const valid = data.trend.filter((point) => point.on_time_rate != null);
    if (valid.length < 2) return null;
    const latest = valid.at(-1)!;
    const previous = valid.at(-2)!;
    return { label: latest.month ?? latest.year_month ?? "Latest release", change: ((latest.on_time_rate ?? 0) - (previous.on_time_rate ?? 0)) * 100 };
  }, [data]);

  const latestPoint = useMemo(() => data?.trend.filter((point) => point.on_time_rate != null).at(-1) ?? null, [data]);
  return <main className="public-page public-home-dashboard">
    <header className="overview-masthead">
      <div className="overview-masthead-copy">
        <p className="section-label">THE U.S. FLIGHT RECORD · PUBLIC OVERVIEW</p>
        <h1>One clear read on airline performance.</h1>
        <p>Start with what happened across the system. Then compare an airline, airport, or route—or ask a specific question.</p>
        <div className="overview-masthead-actions">
          <Link href="#overview-explore" className="overview-primary-action">Explore the record <span>↓</span></Link>
          <Link href="/copilot" className="overview-secondary-action">Ask about a trip <span>↗</span></Link>
        </div>
      </div>
      <aside className="overview-period-card"><span className="section-label">HISTORICAL BTS RECORD</span><strong>{data?.summary.start_date ?? "—"} — {data?.summary.end_date ?? "—"}</strong><small>Published history · not live flight status</small></aside>
    </header>

    {error && <div className="overview-state"><ErrorState title="The public snapshot is unavailable" message="The navigation and methodology remain available. Start the local FastAPI service to restore data-backed views." action={{ href: "/methodology", label: "View data requirements" }} /></div>}
    {!data && !error && <div className="overview-state"><LoadingState title="Reading the network snapshot" message="Fetching compact summaries only—no raw flight table is sent to the browser." /></div>}
    {data && <>
      <section className="overview-metrics" aria-label="Network snapshot">
        <MetricCard label="Observed flights" value={integer(data.summary.total_flights)} detail={`${data.summary.start_date} to ${data.summary.end_date}`} />
        <MetricCard label="On-time arrival" value={percent(data.summary.on_time_rate)} detail="Arrived within 15 minutes" tone="good" />
        <MetricCard label="Average arrival delay" value={data.summary.avg_arrival_delay_minutes == null ? "—" : `${data.summary.avg_arrival_delay_minutes.toFixed(1)} min`} detail="Completed flights" tone="watch" />
        <MetricCard label="Cancellation rate" value={percent(data.summary.cancellation_rate)} detail="Cancelled ÷ scheduled flights" tone="critical" />
      </section>
      <section className="overview-signal-grid" aria-label="Latest signal and next steps">
        <article className="overview-signal-panel">
          <div className="overview-panel-heading"><div><p className="section-label">LATEST RECORDED MONTH</p><h2>{latestPoint?.month ?? latestPoint?.year_month ?? "Monthly trend"}</h2></div><span className="overview-period-tag">BTS history</span></div>
          <div className="overview-signal-readout"><strong>{percent(latestPoint?.on_time_rate)}</strong><span>arrived on time</span>{movement && <span className={`overview-change ${movement.change >= 0 ? "is-up" : "is-down"}`}>{movement.change >= 0 ? "↑" : "↓"} {Math.abs(movement.change).toFixed(1)} pts from prior month</span>}</div>
          <TrendSparkline trend={data.trend} />
          <p className="overview-caveat">A change between months is a signal to investigate, not an explanation of why performance changed.</p>
        </article>
        <nav className="overview-next-panel" aria-label="Explore this record">
          <div><p className="section-label">CHOOSE A QUESTION</p><h2>Where do you want to look?</h2></div>
          <Link href="/carriers"><b>Compare airlines</b><small>On-time, delay, cancellations, and period filters</small><span>↗</span></Link>
          <Link href="/airports"><b>Understand an airport</b><small>Traffic volume and associated flight outcomes</small><span>↗</span></Link>
          <Link href="/routes"><b>Check a route</b><small>Directional history and reverse-route comparison</small><span>↗</span></Link>
        </nav>
      </section>
      <section className="overview-explorer" id="overview-explore" aria-label="More ways to explore">
        <Link href="/compare"><span>COMPARE</span><b>Put periods or entities side by side</b><small>Same warehouse measures · descriptive, not causal</small><i>↗</i></Link>
        <Link href="/network"><span>NETWORK MAP</span><b>See routes in U.S. geography</b><small>Select an airport or connection</small><i>↗</i></Link>
        <Link href="/copilot"><span>ASK A QUESTION</span><b>Get a plain-language answer</b><small>Ask about a trip, airline, airport, or route</small><i>↗</i></Link>
      </section>
      <footer className="overview-footnote"><span>{integer(data.summary.unique_airports)} airports · {integer(data.summary.unique_routes)} directional routes</span><Link href="/methodology">How to read these measures ↗</Link><span>Historical performance does not guarantee an individual flight’s outcome.</span></footer>
    </>}
  </main>;
}
