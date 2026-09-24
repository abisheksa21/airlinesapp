"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CARRIER_NAMES, carrierName } from "../lib/carriers";
import { formatInteger, formatNumber } from "../lib/format";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

type Intent = "route" | "carrier" | "airport";

type BaseMetrics = {
  total_flights: number;
  on_time_rate: number | null;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number | null;
};

type RouteMetrics = BaseMetrics & { origin: string; dest: string; distance_miles: number | null };

const INTENTS: Array<{ id: Intent; label: string; question: string; helper: string }> = [
  { id: "route", label: "A route", question: "How does this connection usually go?", helper: "Choose the direction. ATL → LAX and LAX → ATL are different routes." },
  { id: "carrier", label: "An airline", question: "How reliable has this airline been?", helper: "See its historical on-time, delay, and cancellation pattern." },
  { id: "airport", label: "An airport", question: "What is the operating pattern around this airport?", helper: "Read its observed activity and arrival performance together." },
];

function asPercent(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function asDelay(value: number | null): string {
  return value == null ? "—" : `${formatNumber(value)} min`;
}

function performanceLabel(onTimeRate: number | null): string {
  if (onTimeRate == null) return "no clear historical pattern";
  if (onTimeRate >= 0.84) return "a stronger historical reliability pattern";
  if (onTimeRate >= 0.76) return "a mixed but generally steady historical pattern";
  return "a pattern worth planning extra time around";
}

export default function PublicAnswerDesk() {
  const [intent, setIntent] = useState<Intent>("route");
  const [airports, setAirports] = useState<string[]>([]);
  const [carrier, setCarrier] = useState("AA");
  const [airport, setAirport] = useState("ORD");
  const [origin, setOrigin] = useState("ORD");
  const [destination, setDestination] = useState("LAX");
  const [result, setResult] = useState<BaseMetrics | RouteMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectedIntent = useMemo(() => INTENTS.find((item) => item.id === intent) ?? INTENTS[0], [intent]);

  useEffect(() => {
    let current = true;
    fetch(`${API_BASE}/api/airports/list`)
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("Airport list unavailable")))
      .then((payload) => { if (current) setAirports(payload.airports ?? []); })
      .catch(() => { if (current) setAirports([]); });
    return () => { current = false; };
  }, []);

  function chooseIntent(next: Intent) {
    setIntent(next);
    setResult(null);
    setError("");
  }

  async function ask() {
    setLoading(true);
    setResult(null);
    setError("");

    const target = intent === "route"
      ? `${API_BASE}/api/route-detail?origin=${encodeURIComponent(origin)}&dest=${encodeURIComponent(destination)}`
      : intent === "carrier"
        ? `${API_BASE}/api/carrier-detail?carrier=${encodeURIComponent(carrier)}&summary_only=true`
        : `${API_BASE}/api/airport-detail?airport=${encodeURIComponent(airport)}&summary_only=true`;

    try {
      const response = await fetch(target);
      if (!response.ok) throw new Error("No matching flight history was found.");
      setResult(await response.json());
    } catch {
      setError("We could not find enough matching history for that choice. Try another route, airline, or airport.");
    } finally {
      setLoading(false);
    }
  }

  const routeResult = result && intent === "route" ? result as RouteMetrics : null;
  const actionHref = intent === "carrier" ? `/carriers/${carrier}` : intent === "airport" ? `/airports/${airport}` : `/routes/${origin}-${destination}`;
  const actionLabel = intent === "carrier" ? `Open ${carrierName(carrier)} profile` : intent === "airport" ? `Open ${airport} profile` : "Explore this route in detail";

  return (
    <section className="public-answer-desk" aria-labelledby="public-answer-title">
      <div className="answer-desk-heading">
        <div>
          <p className="eyebrow">Ask the flight record</p>
          <h1 id="public-answer-title">Start with the travel question, not the spreadsheet.</h1>
          <p>Choose what you want to understand. The answer uses measured U.S. flight history and states exactly what it can—and cannot—tell you.</p>
        </div>
        <div className="answer-desk-boundary">
          <span className="answer-desk-dot" />
          <div><strong>Historical decision support</strong><small>Not live flight status or a booking tool</small></div>
        </div>
      </div>

      <div className="answer-intent-row" role="tablist" aria-label="Choose a question type">
        {INTENTS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={intent === item.id}
            className={intent === item.id ? "active" : ""}
            onClick={() => chooseIntent(item.id)}
          >
            <span>{item.label}</span>
            <strong>{item.question}</strong>
          </button>
        ))}
      </div>

      <div className="answer-workspace">
        <div className="answer-prompt">
          <p className="answer-prompt-label">Your question</p>
          <h2>{selectedIntent.question}</h2>
          <p>{selectedIntent.helper}</p>
        </div>

        <div className="answer-controls">
          {intent === "route" && <>
            <label><span>From</span><select value={origin} onChange={(event) => setOrigin(event.target.value)}>{airports.map((code) => <option key={code} value={code}>{code}</option>)}</select></label>
            <span className="route-arrow" aria-hidden="true">→</span>
            <label><span>To</span><select value={destination} onChange={(event) => setDestination(event.target.value)}>{airports.map((code) => <option key={code} value={code}>{code}</option>)}</select></label>
          </>}
          {intent === "carrier" && <label className="answer-wide-control"><span>Airline</span><select value={carrier} onChange={(event) => setCarrier(event.target.value)}>{Object.keys(CARRIER_NAMES).map((code) => <option key={code} value={code}>{code} — {carrierName(code)}</option>)}</select></label>}
          {intent === "airport" && <label className="answer-wide-control"><span>Airport</span><select value={airport} onChange={(event) => setAirport(event.target.value)}>{airports.map((code) => <option key={code} value={code}>{code}</option>)}</select></label>}
          <button type="button" className="answer-submit" onClick={ask} disabled={loading || (intent === "route" && (!origin || !destination))}>{loading ? "Reading the record…" : "Show my answer"}</button>
        </div>
      </div>

      {error && <p className="answer-error" role="status">{error}</p>}

      {result && <div className="answer-result" aria-live="polite">
        <div className="answer-result-main">
          <p className="eyebrow">The short answer</p>
          <h2>
            {intent === "route" && <>{origin} → {destination} has {performanceLabel(result.on_time_rate)}.</>}
            {intent === "carrier" && <>{carrierName(carrier)} has {performanceLabel(result.on_time_rate)}.</>}
            {intent === "airport" && <>{airport} shows {performanceLabel(result.on_time_rate)}.</>}
          </h2>
          <p>
            Across <strong>{formatInteger(result.total_flights)}</strong> observed flights, <strong>{asPercent(result.on_time_rate)}</strong> arrived within 15 minutes of schedule.
            {result.avg_arrival_delay_minutes != null && <> The average arrival delay among completed flights was <strong>{asDelay(result.avg_arrival_delay_minutes)}</strong>.</>}
          </p>
        </div>
        <div className="answer-result-facts">
          <div><span>On-time</span><strong>{asPercent(result.on_time_rate)}</strong></div>
          <div><span>Average delay</span><strong>{asDelay(result.avg_arrival_delay_minutes)}</strong></div>
          <div><span>Cancelled</span><strong>{asPercent(result.cancellation_rate)}</strong></div>
          {routeResult && <div><span>Distance</span><strong>{routeResult.distance_miles ? `${formatInteger(routeResult.distance_miles)} mi` : "—"}</strong></div>}
        </div>
        <div className="answer-result-footer">
          <p>This is an observed historical pattern, not a promise about any one flight. Conditions such as weather, air-traffic constraints, and the day of travel can change the outcome.</p>
          <Link href={actionHref} className="answer-detail-link">{actionLabel} <span>→</span></Link>
        </div>
      </div>}
    </section>
  );
}
