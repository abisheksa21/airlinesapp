"use client";

import { useState, useEffect } from "react";
import ComparisonChart, { ScenarioTrend } from "./ComparisonChart";
import TailSearchInput from "./TailSearchInput";
import { HealthSummary } from "../lib/health";
import { formatNumber } from "../lib/format";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";
const PALETTE = ["#e8a33d", "#4f9d8f", "#c9563a", "#5b7fa6", "#8a6642", "#EC008C", "#F9B612", "#00A9E0"];
const MAX_ENTITIES = 8;

type EntityType = "route" | "airport" | "aircraft";

type Health = HealthSummary;
type MonthPoint = { month: string; total_flights: number; on_time_rate: number };

type EntityItem = {
  id: string;
  origin: string;
  dest: string;
  airport: string;
  tail: string;
};

type NormalizedResult = {
  id: string;
  label: string;
  total_flights: number;
  on_time_rate: number;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number;
  health: Health | null;
  months: MonthPoint[];
  error: string | null;
};

const RATING_COLORS: Record<string, string> = {
  Excellent: "#4f9d8f",
  Strong: "#7fb069",
  Watch: "#e8a33d",
  Weak: "#d17b3e",
  Critical: "#c9563a",
};

let nextId = 1;
function makeEntity(): EntityItem {
  return { id: `e${nextId++}`, origin: "", dest: "", airport: "", tail: "" };
}

function buildQuery(params: Record<string, string>): string {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v) usp.set(k, v);
  });
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

export default function EntityCompare({
  entityType,
  initialValue,
}: {
  entityType: EntityType;
  initialValue?: string;
}) {
  const [airports, setAirports] = useState<string[]>([]);
  const [entities, setEntities] = useState<EntityItem[]>(() => {
    const first = makeEntity();
    if (initialValue && entityType === "airport") first.airport = initialValue;
    if (initialValue && entityType === "aircraft") first.tail = initialValue;
    return [first, makeEntity()];
  });
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const [results, setResults] = useState<NormalizedResult[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/airports/list`)
      .then((r) => r.json())
      .then((d) => setAirports(d.airports ?? []))
      .catch(() => setAirports([]));
  }, []);

  function updateEntity(id: string, patch: Partial<EntityItem>) {
    setEntities((prev) => prev.map((e) => (e.id === id ? { ...e, ...patch } : e)));
  }

  function addEntity() {
    setEntities((prev) => (prev.length < MAX_ENTITIES ? [...prev, makeEntity()] : prev));
  }

  function removeEntity(id: string) {
    setEntities((prev) => prev.filter((e) => e.id !== id));
  }

  function moveEntity(id: string, direction: -1 | 1) {
    setEntities((prev) => {
      const index = prev.findIndex((e) => e.id === id);
      const target = index + direction;
      if (index === -1 || target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function isEntityFilled(e: EntityItem): boolean {
    if (entityType === "route") return !!(e.origin && e.dest);
    if (entityType === "airport") return !!e.airport;
    return !!e.tail;
  }

  function entityLabel(e: EntityItem): string {
    if (entityType === "route") return `${e.origin} \u2192 ${e.dest}`;
    if (entityType === "airport") return e.airport;
    return e.tail;
  }

  const readyToCompare = entities.length >= 2 && entities.every(isEntityFilled);

  async function fetchOne(e: EntityItem): Promise<NormalizedResult> {
    const label = entityLabel(e);
    const dateParams = { start_date: startDate, end_date: endDate };
    try {
      let url = "";
      if (entityType === "route") {
        url = `${API_BASE}/api/route-detail${buildQuery({ origin: e.origin, dest: e.dest, ...dateParams })}`;
      } else if (entityType === "airport") {
        url = `${API_BASE}/api/airport-detail${buildQuery({ airport: e.airport, ...dateParams })}`;
      } else {
        url = `${API_BASE}/api/aircraft-detail${buildQuery({ tail: e.tail, ...dateParams })}`;
      }
      const res = await fetch(url);
      if (!res.ok) {
        return {
          id: e.id, label, total_flights: 0, on_time_rate: 0, avg_arrival_delay_minutes: 0,
          cancellation_rate: 0, health: null, months: [], error: "No flights matched.",
        };
      }
      const d = await res.json();
      return {
        id: e.id,
        label,
        total_flights: d.total_flights,
        on_time_rate: d.on_time_rate,
        avg_arrival_delay_minutes: d.avg_arrival_delay_minutes,
        cancellation_rate: d.cancellation_rate,
        health: d.health,
        months: d.months ?? [],
        error: null,
      };
    } catch {
      return {
        id: e.id, label, total_flights: 0, on_time_rate: 0, avg_arrival_delay_minutes: 0,
        cancellation_rate: 0, health: null, months: [], error: "Request failed.",
      };
    }
  }

  async function runCompare() {
    if (!readyToCompare) return;
    setLoading(true);
    const settled = await Promise.all(entities.map(fetchOne));
    setResults(settled);
    setLoading(false);
  }

  const chartScenarios: ScenarioTrend[] = (results ?? [])
    .filter((r) => !r.error && r.months.length > 0)
    .map((r, i) => ({ key: r.id, label: r.label, color: PALETTE[i % PALETTE.length], months: r.months }));

  return (
    <div>
      <div className="entity-compare-grid">
        {entities.map((e, i) => (
          <div key={e.id} className="entity-compare-card" style={{ borderTopColor: PALETTE[i % PALETTE.length] }}>
            <div className="scenario-card-head">
              <span className="eyebrow">
                {entityType === "route" ? "Route" : entityType === "airport" ? "Airport" : "Aircraft"} {i + 1}
              </span>
              <div className="scenario-card-controls">
                <button type="button" className="scenario-move" onClick={() => moveEntity(e.id, -1)} disabled={i === 0} title="Move left">&#8592;</button>
                <button type="button" className="scenario-move" onClick={() => moveEntity(e.id, 1)} disabled={i === entities.length - 1} title="Move right">&#8594;</button>
                {entities.length > 2 && (
                  <button type="button" className="scenario-remove" onClick={() => removeEntity(e.id)} title="Remove">&times;</button>
                )}
              </div>
            </div>

            {entityType === "route" && (
              <div className="entity-picker-fields">
                <label className="filter-field">
                  <span className="filter-label">Origin</span>
                  <select value={e.origin} onChange={(ev) => updateEntity(e.id, { origin: ev.target.value })}>
                    <option value="">Select airport</option>
                    {airports.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </label>
                <label className="filter-field">
                  <span className="filter-label">Destination</span>
                  <select value={e.dest} onChange={(ev) => updateEntity(e.id, { dest: ev.target.value })}>
                    <option value="">Select airport</option>
                    {airports.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </label>
              </div>
            )}

            {entityType === "airport" && (
              <label className="filter-field">
                <span className="filter-label">Airport</span>
                <select value={e.airport} onChange={(ev) => updateEntity(e.id, { airport: ev.target.value })}>
                  <option value="">Select airport</option>
                  {airports.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </label>
            )}

            {entityType === "aircraft" && (
              <TailSearchInput
                value={e.tail}
                onChange={(tail) => updateEntity(e.id, { tail })}
              />
            )}
          </div>
        ))}

        {entities.length < MAX_ENTITIES && (
          <button type="button" className="scenario-add" onClick={addEntity}>
            + Add entity
          </button>
        )}
      </div>

      <div className="route-lookup-row" style={{ marginTop: "1.25rem" }}>
        <label className="filter-field">
          <span className="filter-label">From</span>
          <input type="date" value={startDate} min="2018-01-01" onChange={(e) => setStartDate(e.target.value)} />
        </label>
        <label className="filter-field">
          <span className="filter-label">To</span>
          <input type="date" value={endDate} min="2018-01-01" onChange={(e) => setEndDate(e.target.value)} />
        </label>
        <button type="button" className="compare-run" onClick={runCompare} disabled={!readyToCompare || loading}>
          {loading ? "Comparing..." : "Compare"}
        </button>
      </div>

      {results && (
        <>
          <div className="screen" style={{ marginTop: "1.5rem", overflowX: "auto" }}>
            <table className="compare-table">
              <thead>
                <tr>
                  <th></th>
                  {results.map((r, i) => (
                    <th key={r.id} style={{ color: PALETTE[i % PALETTE.length] }}>{r.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Total flights</td>
                  {results.map((r) => <td key={r.id}>{r.error ? "\u2014" : r.total_flights.toLocaleString()}</td>)}
                </tr>
                <tr>
                  <td>On-time rate</td>
                  {results.map((r) => <td key={r.id}>{r.error ? "\u2014" : `${(r.on_time_rate * 100).toFixed(1)}%`}</td>)}
                </tr>
                <tr>
                  <td>Avg arrival delay</td>
                  {results.map((r) => <td key={r.id}>{r.error ? "\u2014" : `${formatNumber(r.avg_arrival_delay_minutes)} min`}</td>)}
                </tr>
                <tr>
                  <td>Cancellation rate</td>
                  {results.map((r) => <td key={r.id}>{r.error ? "\u2014" : `${(r.cancellation_rate * 100).toFixed(2)}%`}</td>)}
                </tr>
                <tr>
                  <td>Health score</td>
                  {results.map((r) => (
                    <td key={r.id}>
                      {r.health ? (
                        <span style={{ color: RATING_COLORS[r.health.rating] ?? "#9099a8" }}>
                          {r.health.score.toFixed(0)} ({r.health.rating})
                        </span>
                      ) : "\u2014"}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td></td>
                  {results.map((r) => <td key={r.id} className="error-text">{r.error}</td>)}
                </tr>
              </tbody>
            </table>
          </div>

          {chartScenarios.length > 0 && (
            <div className="screen" style={{ marginTop: "1.5rem" }}>
              <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>On-time rate over time</p>
              <ComparisonChart scenarios={chartScenarios} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
