"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { carrierName, CARRIER_PROFILES } from "../../lib/carriers";
import { airportDisplayName } from "../../lib/airports";
import { ChartFrame } from "./ChartFrame";
import { CopilotDrawer } from "./EvidenceDrawer";
import { Breadcrumbs, EntityHeader } from "./EntityHeader";
import { DataTable } from "./DataTable";
import { MetricCard } from "./MetricCard";
import { ErrorState, LoadingState } from "./states";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

type Month = { month: string; total_flights: number; on_time_rate: number | null };
type Cause = { cause: string; minutes: number; share: number };
type Detail = { total_flights: number; on_time_rate: number | null; avg_arrival_delay_minutes: number | null; cancellation_rate: number | null; months: Month[]; causes: Cause[]; health?: { score?: number; label?: string } };
type CarrierDetail = Detail & { carrier: string; top_routes: Array<{ route: string; total_flights: number; on_time_rate: number | null }>; top_airports: Array<{ airport: string; total_flights: number }> };
type AirportDetail = Detail & { airport: string; city?: string | null; state?: string | null; outbound?: Detail; inbound?: Detail; top_routes: Array<{ route: string; total_flights: number; on_time_rate: number | null }> };
type RouteDetail = Detail & { origin: string; dest: string; distance_miles?: number | null; carriers: Array<{ carrier: string; total_flights: number; on_time_rate: number | null }> };

function percent(value: number | null | undefined) { return value == null ? "—" : `${(value * 100).toFixed(1)}%`; }
function integer(value: number | null | undefined) { return value == null ? "—" : new Intl.NumberFormat("en-US").format(value); }
function delay(value: number | null | undefined) { return value == null ? "—" : `${value.toFixed(1)} min`; }
function routeHref(route: string) { const [origin, dest] = route.split("→").map((part) => part.trim()); return origin && dest ? `/routes/${origin}-${dest}` : "/routes"; }

function Trend({ months }: { months: Month[] }) {
  const rows = months.map((month) => ({ ...month, on_time_percent: month.on_time_rate == null ? null : +(month.on_time_rate * 100).toFixed(1) }));
  return <div className="profile-trend"><ResponsiveContainer width="100%" height={255}><LineChart data={rows} margin={{ top: 12, right: 12, left: -20, bottom: 0 }}><XAxis dataKey="month" tick={{ fontSize: 10, fill: "#657485" }} minTickGap={42} tickLine={false} axisLine={false} /><YAxis domain={[50, 100]} tickFormatter={(value) => `${value}%`} tick={{ fontSize: 10, fill: "#657485" }} tickLine={false} axisLine={false} /><Tooltip formatter={(value) => [`${value}%`, "On-time arrival"]} labelFormatter={(label) => `Month: ${label}`} /><Line type="monotone" dataKey="on_time_percent" stroke="#1b6f9b" strokeWidth={2.4} dot={false} activeDot={{ r: 4 }} /></LineChart></ResponsiveContainer></div>;
}

function Causes({ causes }: { causes: Cause[] }) {
  const top = causes.slice().sort((a, b) => b.minutes - a.minutes).slice(0, 5);
  const maximum = Math.max(...top.map((item) => item.minutes), 1);
  return <div className="cause-list">{top.map((item) => <div key={item.cause}><span>{item.cause}</span><i><b style={{ width: `${(item.minutes / maximum) * 100}%` }} /></i><strong>{percent(item.share)}</strong></div>)}</div>;
}

function ProfileMetrics({ detail, extra }: { detail: Detail; extra?: { label: string; value: string; tone?: "default" | "good" | "watch" | "critical" } }) {
  return <div className="public-metric-grid profile-metrics"><MetricCard label="Observed flights" value={integer(detail.total_flights)} detail="Matching BTS records" /><MetricCard label="On-time arrival" value={percent(detail.on_time_rate)} detail="Within 15 minutes" tone="good" /><MetricCard label="Average arrival delay" value={delay(detail.avg_arrival_delay_minutes)} detail="Completed flights" tone="watch" />{extra ? <MetricCard label={extra.label} value={extra.value} detail="Historical measure" tone={extra.tone} /> : <MetricCard label="Cancellation rate" value={percent(detail.cancellation_rate)} detail="Cancelled ÷ scheduled" tone="critical" />}</div>;
}

function ProfileBody({ detail, title, narrative, tableTitle, tableColumns, tableRows, period, copilotContext }: { detail: Detail; title: string; narrative: string; tableTitle: string; tableColumns: string[]; tableRows: React.ReactNode[][]; period: string; copilotContext: string }) {
  return <>
    <section className="profile-takeaway" aria-label="Plain-language profile summary">
      <div><span className="section-label">THE SHORT READ</span><p>{narrative}</p></div>
      <div className="profile-scope-facts"><span><small>OBSERVED PERIOD</small><b>{period}</b></span><span><small>RECORDS</small><b>{integer(detail.total_flights)} flights</b></span><span><small>WHAT THIS IS</small><b>Historical BTS summary</b></span></div>
      <p className="profile-limit">On-time means arrival less than 15 minutes late. This profile describes the recorded flights in this period; it is not live status or proof of cause.</p>
    </section>
    <ProfileMetrics detail={detail} />
    <nav className="profile-chapter-links" aria-label="On this profile"><a href="#profile-performance">Performance</a><a href="#profile-connections">Connections</a>{detail.causes.length > 0 && <a href="#profile-delay-causes">Recorded delay causes</a>}<a href="#profile-evidence">Period &amp; limits</a></nav>
    <div className="profile-primary-grid">
      <section id="profile-performance" className="profile-performance-panel">
        <ChartFrame title="Performance over time" interpretation="Monthly on-time arrival in the observed record. The line shows how results varied; it is not a forecast." evidence={{ source: "BTS Marketing Carrier On-Time Performance", period, sample: integer(detail.total_flights), definition: "A completed flight is on time when arrival delay is under 15 minutes.", method: "Monthly aggregation", caveat: "Months can differ in weather, schedules, traffic, and sample size." }}><Trend months={detail.months} /></ChartFrame>
      </section>
      <section id="profile-connections" className="profile-related-card">
        <header><div><span className="section-label">RELATED NETWORK · {period}</span><h2>{tableTitle}</h2></div><p>These are the most-observed connected records in this profile. They provide context, not a causal explanation.</p></header>
        <DataTable columns={tableColumns} rows={tableRows} />
      </section>
    </div>
    <div className="profile-followup-grid">
      {detail.causes.length > 0 && <details id="profile-delay-causes" className="profile-causes-details"><summary><span><small>OPTIONAL DEEPER READ</small><b>Inspect recorded delay causes</b></span><i aria-hidden="true">+</i></summary><ChartFrame title="Recorded delay causes" interpretation="This ranks BTS-recorded delay minutes in the selected profile, as a starting point for a more specific investigation." evidence={{ source: "BTS delay cause fields", period, sample: integer(detail.total_flights), definition: "Shares use the sum of available cause minutes among completed delayed flights.", method: "Cause-minute aggregation", caveat: "Recorded categories do not prove a root cause." }}><Causes causes={detail.causes} /></ChartFrame></details>}
      <aside id="profile-evidence" className="profile-context-column"><CopilotDrawer publicMode context={copilotContext} /><section className="profile-note"><span className="section-label">PERIOD &amp; EVIDENCE LIMIT</span><p>{title} is a historical BTS profile for {period}; it is not live operational status, a booking recommendation, or a causal diagnosis.</p></section></aside>
    </div>
  </>;
}

export function PublicCarrierProfile({ carrier }: { carrier: string }) {
  const [detail, setDetail] = useState<CarrierDetail | null>(null); const [failed, setFailed] = useState(false);
  useEffect(() => { let active = true; fetch(`${API_BASE}/api/carrier-detail?carrier=${encodeURIComponent(carrier)}`).then((response) => response.ok ? response.json() : Promise.reject()).then((value) => { if (active) setDetail(value); }).catch(() => { if (active) setFailed(true); }); return () => { active = false; }; }, [carrier]);
  if (failed) return <div className="public-page public-entity-profile"><ErrorState title="Carrier profile unavailable" action={{ href: "/carriers", label: "Return to carrier directory" }} /></div>;
  if (!detail) return <div className="public-page public-entity-profile"><LoadingState title="Reading this carrier profile" /></div>;
  const profile = CARRIER_PROFILES[carrier]; const title = carrierName(carrier); const period = `${detail.months.at(0)?.month ?? "—"} to ${detail.months.at(-1)?.month ?? "—"}`;
  return <div className="public-page public-entity-profile"><Breadcrumbs items={[{ label: "Carriers", href: "/carriers" }, { label: title }]} /><EntityHeader eyebrow={`Carrier · ${carrier}`} title={title} description={profile?.overview ?? `A BTS marketing carrier profile for ${carrier}.`} period={period} researchHref={`/research/explore?object=carrier&carrier=${carrier}`} /><ProfileBody detail={detail} title={title} narrative={`${title} had ${percent(detail.on_time_rate)} on-time arrivals across ${integer(detail.total_flights)} observed flights from ${period}. Compare its route mix before treating this as a system-wide operating-quality conclusion.`} tableTitle="Most-observed routes" tableColumns={["Route", "Observed flights", "On-time arrival"]} tableRows={detail.top_routes.map((route) => [<Link key={route.route} href={routeHref(route.route)}>{route.route}</Link>, integer(route.total_flights), percent(route.on_time_rate)])} period={period} copilotContext={`Explain the historical ${carrier} carrier profile, including its main delay-cause categories and route context.`} /></div>;
}

export function PublicAirportProfile({ airport }: { airport: string }) {
  const [detail, setDetail] = useState<AirportDetail | null>(null); const [failed, setFailed] = useState(false);
  useEffect(() => { let active = true; fetch(`${API_BASE}/api/airport-detail?airport=${encodeURIComponent(airport)}&summary_only=true`).then((response) => response.ok ? response.json() : Promise.reject()).then((value) => { if (active) setDetail(value); }).catch(() => { if (active) setFailed(true); }); return () => { active = false; }; }, [airport]);
  if (failed) return <div className="public-page public-entity-profile"><ErrorState title="Airport profile unavailable" action={{ href: "/airports", label: "Return to airport directory" }} /></div>;
  if (!detail) return <div className="public-page public-entity-profile"><LoadingState title="Reading this airport profile" /></div>;
  const title = airportDisplayName(airport, detail.city, detail.state); const period = `${detail.months.at(0)?.month ?? "—"} to ${detail.months.at(-1)?.month ?? "—"}`;
  const location = [detail.city, detail.state].filter(Boolean).join(", ");
  return <div className="public-page public-entity-profile"><Breadcrumbs items={[{ label: "Airports", href: "/airports" }, { label: airport }]} /><EntityHeader eyebrow={`Airport · ${airport}`} title={title} description={location ? `${location} · gateway profile` : "Gateway profile from historical BTS flight data"} period={period} researchHref={`/research/explore?object=airport&airport=${airport}`} /><ProfileBody detail={detail} title={title} narrative={`${airport} had ${integer(detail.total_flights)} recorded arrivals and departures from ${period}. ${percent(detail.on_time_rate)} of associated flights arrived on time. This describes the flights using the airport, not performance controlled by the airport itself.`} tableTitle="Most-observed connections" tableColumns={["Route", "Observed flights", "On-time arrival"]} tableRows={detail.top_routes.map((route) => [<Link key={route.route} href={routeHref(route.route)}>{route.route}</Link>, integer(route.total_flights), percent(route.on_time_rate)])} period={period} copilotContext={`Explain the historical operational pattern at ${airport}, including its observed connections and delay context.`} /></div>;
}

export function PublicRouteProfile({ origin, destination }: { origin: string; destination: string }) {
  const [detail, setDetail] = useState<RouteDetail | null>(null); const [failed, setFailed] = useState(false);
  useEffect(() => { let active = true; fetch(`${API_BASE}/api/route-detail?origin=${encodeURIComponent(origin)}&dest=${encodeURIComponent(destination)}`).then((response) => response.ok ? response.json() : Promise.reject()).then((value) => { if (active) setDetail(value); }).catch(() => { if (active) setFailed(true); }); return () => { active = false; }; }, [destination, origin]);
  if (failed) return <div className="public-page public-entity-profile"><ErrorState title="Route profile unavailable" message="There may not be enough matching historical records for this directional connection." action={{ href: "/routes", label: "Return to route explorer" }} /></div>;
  if (!detail) return <div className="public-page public-entity-profile"><LoadingState title="Reading this route profile" /></div>;
  const title = `${origin} → ${destination}`; const period = `${detail.months.at(0)?.month ?? "—"} to ${detail.months.at(-1)?.month ?? "—"}`;
  return <div className="public-page public-entity-profile"><Breadcrumbs items={[{ label: "Routes", href: "/routes" }, { label: title }]} /><EntityHeader eyebrow="Directional route" title={title} description={`${detail.distance_miles ? `${integer(detail.distance_miles)} miles` : "Observed connection"} · this profile is ${origin} → ${destination}; the reverse direction is separate.`} period={period} researchHref={`/research/explore?object=route&route=${origin}-${destination}`} /><ProfileBody detail={detail} title={title} narrative={`${title} had ${percent(detail.on_time_rate)} on-time arrivals across ${integer(detail.total_flights)} observed flights from ${period}, with an average arrival delay of ${delay(detail.avg_arrival_delay_minutes)}. This describes this direction's stored history, not a prediction for a particular travel day.`} tableTitle="Carriers in this route history" tableColumns={["Carrier", "Observed flights", "On-time arrival"]} tableRows={detail.carriers.map((item) => [<Link key={item.carrier} href={`/carriers/${item.carrier}`}>{carrierName(item.carrier)}</Link>, integer(item.total_flights), percent(item.on_time_rate)])} period={period} copilotContext={`Explain the historical ${origin} to ${destination} route profile using on-time, delay-cause, and carrier context without making a live travel prediction.`} /></div>;
}
