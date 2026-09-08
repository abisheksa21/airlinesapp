"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import FilteredOverview from "./components/FilteredOverview";
import { fetchJson } from "./lib/api";
import { formatNumber } from "./lib/format";
import { useMode } from "./lib/mode";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Summary = {
  total_flights: number;
  start_date: string;
  end_date: string;
  carrier_count: number;
  on_time_rate: number;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number;
  unique_routes: number;
  unique_airports: number;
};

type MonthPoint = { month: string; total_flights: number; on_time_rate: number };

export default function Home() {
  const { mode } = useMode();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [trend, setTrend] = useState<{ months: MonthPoint[] } | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [trendLoading, setTrendLoading] = useState(true);
  const [summaryError, setSummaryError] = useState(false);
  const [trendError, setTrendError] = useState(false);

  useEffect(() => {
    let active = true;
    fetchJson<Summary>(`${API_BASE}/api/summary`)
      .then((data) => { if (active) setSummary(data); })
      .catch(() => { if (active) setSummaryError(true); })
      .finally(() => { if (active) setSummaryLoading(false); });

    fetchJson<{ months: MonthPoint[] }>(`${API_BASE}/api/trend`)
      .then((data) => { if (active) setTrend(data); })
      .catch(() => { if (active) setTrendError(true); })
      .finally(() => { if (active) setTrendLoading(false); });

    return () => { active = false; };
  }, []);

  return mode === "researcher"
    ? <ResearchHome summary={summary} trend={trend} summaryLoading={summaryLoading} trendLoading={trendLoading} summaryError={summaryError} trendError={trendError} />
    : <PublicHome summary={summary} trend={trend} summaryLoading={summaryLoading} trendLoading={trendLoading} summaryError={summaryError} trendError={trendError} />;
}

type HomeDataProps = {
  summary: Summary | null;
  trend: { months: MonthPoint[] } | null;
  summaryLoading: boolean;
  trendLoading: boolean;
  summaryError: boolean;
  trendError: boolean;
};

function PublicHome({ summary, trend, summaryLoading, trendLoading, summaryError, trendError }: HomeDataProps) {
  return (
    <main className="page public-home">
      <section className="public-hero">
        <div className="public-hero-copy">
          <p className="eyebrow">A calm starting point for a complicated network</p>
          <h1 className="public-hero-title">See what is happening in the skies.</h1>
          <p className="public-hero-lede">Airline Operations Lab turns the U.S. flight record into a readable brief. Start with a carrier, airport, or route; use the data to understand the pattern before deciding what to investigate.</p>
          <div className="public-hero-actions"><Link href="/carriers" className="primary-action">Explore carriers <span>→</span></Link><Link href="/airports" className="secondary-action">Browse airports</Link></div>
          <div className="public-proof-row"><span><i className="status-light" />BTS warehouse</span><span>{summary ? `${summary.start_date} — ${summary.end_date}` : "2018 — latest available month"}</span></div>
        </div>
        <div className="network-graphic" aria-label="Abstract network map illustration">
          <span className="network-orbit orbit-a" /><span className="network-orbit orbit-b" /><span className="network-orbit orbit-c" />
          <span className="network-node node-1">ATL</span><span className="network-node node-2">DFW</span><span className="network-node node-3">LAX</span><span className="network-node node-4">ORD</span><span className="network-node node-5">SEA</span>
          <span className="network-line line-a" /><span className="network-line line-b" /><span className="network-line line-c" /><span className="network-line line-d" />
          <div className="network-caption"><span>US network</span><strong>{summary ? formatNumber(summary.unique_routes) : "—"}</strong><small>tracked connections</small></div>
        </div>
      </section>

      <section className="public-question-block">
        <div className="section-intro-row"><div><p className="eyebrow">Choose your lens</p><h2>Where should we look first?</h2></div><p>Every path begins with a plain question. The profile page keeps the answer focused; the researcher workspace holds the deeper methods.</p></div>
        <div className="public-lens-grid"><LensCard number="01" href="/carriers" label="Carrier" title="Which airline is more reliable?" copy="Compare on-time performance, cancellations, and delay patterns." accent="cyan" /><LensCard number="02" href="/airports" label="Airport" title="Where is pressure building?" copy="See the busiest gateways and how departures perform through them." accent="violet" /><LensCard number="03" href="/routes#expected-delay" label="Route" title="What should I expect on this connection?" copy="Use the historical route baseline before exploring causes." accent="amber" /></div>
      </section>

      <section className="public-snapshot-section">
        <div className="section-intro-row"><div><p className="eyebrow">Network snapshot</p><h2>The whole system, at a glance.</h2></div><span className="section-note">Measured from BTS on-time records</span></div>
        <SnapshotTiles summary={summary} loading={summaryLoading} error={summaryError} />
        {trendLoading && <div className="public-chart-placeholder"><span className="loading-pulse" /> Preparing the trend view…</div>}
        {trendError && <div className="inline-data-warning">The snapshot is available, but the trend endpoint did not respond. You can still explore profiles.</div>}
        {summary && trend && !trendLoading && <div className="public-trend-card"><div><p className="eyebrow">Long view</p><h3>Is reliability moving?</h3><p>One line across the available history. Open researcher mode for filters and supporting breakdowns.</p></div><div className="public-trend-stat"><strong>{trend.months.length ? `${((trend.months[trend.months.length - 1].on_time_rate ?? 0) * 100).toFixed(1)}%` : "—"}</strong><span>latest on-time rate</span></div></div>}
      </section>

      <section className="public-profile-invite"><div><p className="eyebrow">Context matters</p><h2>Numbers are easier to read when you know what you are looking at.</h2><p>Each carrier and airport has a simple “About” tab with a short history, network role, and source links. Its performance tab stays separate, so reference context is never mistaken for a measured result.</p></div><Link href="/carriers" className="secondary-action">Open the profiles <span>→</span></Link></section>
      <PublicFooter />
    </main>
  );
}

function ResearchHome({ summary, trend, summaryLoading, trendLoading, summaryError, trendError }: HomeDataProps) {
  return (
    <main className="page research-home">
      <header className="research-masthead"><div><p className="eyebrow">Research workspace / network overview</p><h1>From question to evidence.</h1><p>Use the measured history to find a pattern, test a comparison, and decide where a deeper explanation is worth your time.</p></div><div className="research-masthead-status"><span className="research-status-dot" /><strong>{summary ? "Warehouse connected" : summaryLoading ? "Connecting…" : "Needs attention"}</strong><small>{summary ? `${summary.start_date} — ${summary.end_date}` : "BTS source status"}</small></div></header>
      <section className="research-snapshot"><div className="section-intro-row"><div><p className="eyebrow">Workspace snapshot</p><h2>What the warehouse currently knows.</h2></div><span className="section-note">Use these as starting signals, not final conclusions</span></div><SnapshotTiles summary={summary} loading={summaryLoading} error={summaryError} /></section>
      <section className="research-trend"><div className="section-intro-row"><div><p className="eyebrow">Evidence view</p><h2>On-time rate over time</h2></div><div className="research-filter-note">Filter controls live inside the chart view</div></div>{trend && summary ? <FilteredOverview initialSummary={summary} initialTrend={trend} /> : <div className="screen research-empty"><p>{trendLoading ? "Loading the trend query…" : trendError ? "Trend data needs attention. Open Data Health to inspect the source." : "Waiting for the warehouse summary…"}</p></div>}</section>
      <section className="research-surface"><div className="section-intro-row"><div><p className="eyebrow">Research surface</p><h2>Every part of the network, in one place.</h2></div><span className="section-note">Choose a surface, then narrow the question</span></div><div className="research-module-grid"><ResearchModule href="/carriers" index="01" label="Carriers" title="Who is performing differently?" /><ResearchModule href="/airports" index="02" label="Airports" title="Where is pressure concentrated?" /><ResearchModule href="/routes" index="03" label="Routes" title="Which connections carry the signal?" /><ResearchModule href="/delays" index="04" label="Delay causes" title="What categories are recorded?" /><ResearchModule href="/aircraft" index="05" label="Aircraft" title="How does equipment shape operations?" /><ResearchModule href="/capacity" index="06" label="T-100 capacity" title="What supply was scheduled?" /><ResearchModule href="/decision-center" index="07" label="Decision Center" title="What should I investigate next?" featured /><ResearchModule href="/compare" index="08" label="Compare" title="Is the difference meaningful?" /><ResearchModule href="/data-health" index="09" label="Data health" title="Can I trust the coverage?" /></div></section>
      <section className="research-principles"><div><p className="eyebrow">How to use this workspace</p><h2>Three moves, kept deliberately simple.</h2></div><div className="principle-list"><div><span>01</span><p><strong>Find a signal.</strong> Notice a difference in rate, volume, or delay.</p></div><div><span>02</span><p><strong>Locate it.</strong> Break the signal down by carrier, airport, route, or time.</p></div><div><span>03</span><p><strong>Qualify it.</strong> Check volume, coverage, and methodology before calling it an insight.</p></div></div><Link href="/methodology" className="method-link">Read the full methodology →</Link></section>
    </main>
  );
}

function SnapshotTiles({ summary, loading, error }: { summary: Summary | null; loading: boolean; error: boolean }) {
  const value = (ready: string, fallback = "—") => loading ? <span className="loading-inline">Loading<span>…</span></span> : error ? fallback : ready;
  return <div className="snapshot-tiles"><MetricTile label="Flights observed" value={value(summary ? formatNumber(summary.total_flights) : "—")} sub={summary ? `${summary.carrier_count} carriers across ${summary.unique_airports} airports` : "BTS records"} /><MetricTile label="On-time rate" value={value(summary ? `${(summary.on_time_rate * 100).toFixed(1)}%` : "—")} sub="Arrival under 15 minutes late" tone="good" /><MetricTile label="Average arrival delay" value={value(summary ? `${formatNumber(summary.avg_arrival_delay_minutes)} min` : "—")} sub="Cancelled flights excluded" tone="warm" /><MetricTile label="Cancellation rate" value={value(summary ? `${(summary.cancellation_rate * 100).toFixed(2)}%` : "—")} sub="Cancelled ÷ scheduled flights" tone="warm" /></div>;
}

function MetricTile({ label, value, sub, tone = "neutral" }: { label: string; value: React.ReactNode; sub: string; tone?: string }) { return <div className={`metric-tile metric-tile-${tone}`}><span className="metric-label">{label}</span><strong>{value}</strong><small>{sub}</small></div>; }
function LensCard({ number, href, label, title, copy, accent }: { number: string; href: string; label: string; title: string; copy: string; accent: string }) { return <Link href={href} className={`lens-card lens-card-${accent}`}><span className="lens-number">{number}</span><span className="lens-label">{label}</span><h3>{title}</h3><p>{copy}</p><span className="lens-arrow">↗</span></Link>; }
function ResearchCommand({ href, index, title, copy, tag }: { href: string; index: string; title: string; copy: string; tag: string }) { return <Link href={href} className="research-command"><span className="research-command-index">{index}</span><span className="research-command-tag">{tag}</span><h3>{title}</h3><p>{copy}</p><span className="research-command-arrow">→</span></Link>; }
function ResearchModule({ href, index, label, title, featured = false }: { href: string; index: string; label: string; title: string; featured?: boolean }) { return <Link href={href} className={`research-module ${featured ? "research-module-featured" : ""}`}><span className="research-module-index">{index}</span><span className="research-module-label">{label}</span><h3>{title}</h3><span className="research-module-arrow">→</span></Link>; }
function PublicFooter() { return <footer className="methodology public-footer"><p className="eyebrow">Data boundary</p><p>Performance is calculated from the local U.S. Department of Transportation, Bureau of Transportation Statistics (BTS) Marketing Carrier On-Time Performance warehouse. Reference context is labeled and linked separately. The researcher workspace and methodology page explain the more detailed calculations.</p><Link href="/methodology">Read how the numbers are made →</Link></footer>; }
