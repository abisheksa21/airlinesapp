"use client";

import { useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { CARRIER_NAMES, carrierColor, carrierName } from "../lib/carriers";
import ComparisonChart, { ScenarioTrend } from "../components/ComparisonChart";
import EntityCompare from "../components/EntityCompare";
import { formatNumber } from "../lib/format";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Scenario = {
  id: string;
  label: string;
  carriers: string[]; // empty = all carriers combined as one result
  startDate: string; // "" = no lower bound
  endDate: string; // "" = no upper bound
};

// A "run" is one actual query: a scenario expanded per selected carrier
// (or a single combined run if no carriers are selected).
type Run = {
  key: string;
  label: string;
  carrier: string; // "" = all carriers combined
  startDate: string;
  endDate: string;
  scenarioIndex: number;
};

type Summary = {
  total_flights: number;
  on_time_rate: number;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number;
};

type RunResult = {
  run: Run;
  summary: Summary | null;
  months: { month: string; on_time_rate: number }[] | null;
  error: string | null;
};

const DASH_PATTERNS = ["", "6 3", "2 3", "8 3 2 3", "1 2"];
const PALETTE = ["#e8a33d", "#4f9d8f", "#c9563a", "#5b7fa6", "#8a6642", "#EC008C", "#F9B612", "#00A9E0"];
const CARRIER_CODES = Object.keys(CARRIER_NAMES);
const MAX_RUNS = 24;

let nextId = 1;
function makeScenario(label: string, overrides: Partial<Scenario> = {}): Scenario {
  return { id: `s${nextId++}`, label, carriers: [], startDate: "", endDate: "", ...overrides };
}

function defaultScenarios(): Scenario[] {
  return [
    makeScenario("2018", { startDate: "2018-01-01", endDate: "2018-12-31" }),
    makeScenario("2025", { startDate: "2025-01-01", endDate: "2025-12-31" }),
  ];
}

function expandToRuns(scenario: Scenario, scenarioIndex: number): Run[] {
  const base = { startDate: scenario.startDate, endDate: scenario.endDate };
  if (scenario.carriers.length === 0) {
    return [{ key: scenario.id, label: scenario.label, carrier: "", scenarioIndex, ...base }];
  }
  return scenario.carriers.map((code) => ({
    key: `${scenario.id}-${code}`,
    label: `${scenario.label} \u00b7 ${code}`,
    carrier: code,
    scenarioIndex,
    ...base,
  }));
}

function buildQuery(run: Run): string {
  const params = new URLSearchParams();
  if (run.carrier) params.set("carrier", run.carrier);
  if (run.startDate) params.set("start_date", run.startDate);
  if (run.endDate) params.set("end_date", run.endDate);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

type MetricDirection = "higher-better" | "lower-better";

function bestWorstIndices(
  results: RunResult[],
  getValue: (r: RunResult) => number | null
): { best: number | null; worst: number | null } {
  const values = results.map((r, i) => ({ i, v: r.error ? null : getValue(r) }));
  const valid = values.filter((x) => x.v !== null) as { i: number; v: number }[];
  if (valid.length < 2) return { best: null, worst: null };
  const best = valid.reduce((a, b) => (b.v > a.v ? b : a));
  const worst = valid.reduce((a, b) => (b.v < a.v ? b : a));
  return { best: best.i, worst: worst.i };
}

function cellClass(index: number, best: number | null, worst: number | null): string {
  if (index === best) return "compare-best";
  if (index === worst) return "compare-worst";
  return "";
}

export default function ComparePage() {
  return (
    <Suspense fallback={null}>
      <ComparePageInner />
    </Suspense>
  );
}

function ComparePageInner() {
  const searchParams = useSearchParams();
  const linkedMode = searchParams.get("mode"); // "carrier" | "airport" | "route" | "aircraft"
  const linkedEntity = searchParams.get("entity");
  const linkedCarrier = searchParams.get("carrier");

  const VALID_MODES = ["carrier", "airport", "route", "aircraft"] as const;
  type Mode = (typeof VALID_MODES)[number];
  const [mode, setMode] = useState<Mode>(
    VALID_MODES.includes(linkedMode as Mode) ? (linkedMode as Mode) : "carrier"
  );
  const [scenarios, setScenarios] = useState<Scenario[]>(() => {
    const base = defaultScenarios();
    if (linkedCarrier) {
      return base.map((s) => ({ ...s, carriers: [linkedCarrier] }));
    }
    return base;
  });
  const [results, setResults] = useState<RunResult[] | null>(null);
  const [loading, setLoading] = useState(false);

  const dateErrorIds = new Set(
    scenarios.filter((s) => s.startDate && s.endDate && s.startDate > s.endDate).map((s) => s.id)
  );
  const totalRuns = scenarios.flatMap((s, i) => expandToRuns(s, i)).length;
  const tooManyRuns = totalRuns > MAX_RUNS;
  const canCompare = dateErrorIds.size === 0 && !tooManyRuns && totalRuns > 0;

  function updateScenario(id: string, patch: Partial<Scenario>) {
    setScenarios((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }

  function toggleCarrier(id: string, code: string) {
    setScenarios((prev) =>
      prev.map((s) => {
        if (s.id !== id) return s;
        const has = s.carriers.includes(code);
        return { ...s, carriers: has ? s.carriers.filter((c) => c !== code) : [...s.carriers, code] };
      })
    );
  }

  function setAllCarriers(id: string, codes: string[]) {
    setScenarios((prev) => prev.map((s) => (s.id === id ? { ...s, carriers: codes } : s)));
  }

  function addScenario() {
    setScenarios((prev) => [...prev, makeScenario(`Scenario ${prev.length + 1}`)]);
  }

  function removeScenario(id: string) {
    setScenarios((prev) => prev.filter((s) => s.id !== id));
  }

  function moveScenario(id: string, direction: -1 | 1) {
    setScenarios((prev) => {
      const index = prev.findIndex((s) => s.id === id);
      const target = index + direction;
      if (index === -1 || target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  const runComparison = useCallback(async () => {
    if (!canCompare) return;
    setLoading(true);
    const runs = scenarios.flatMap((s, i) => expandToRuns(s, i));
    const settled = await Promise.all(
      runs.map(async (run): Promise<RunResult> => {
        const qs = buildQuery(run);
        try {
          const [summaryRes, trendRes] = await Promise.all([
            fetch(`${API_BASE}/api/summary${qs}`),
            fetch(`${API_BASE}/api/trend${qs}`),
          ]);
          if (summaryRes.status === 404) {
            return { run, summary: null, months: null, error: "No flights matched." };
          }
          const summary = await summaryRes.json();
          const trendData = await trendRes.json();
          return { run, summary, months: trendData.months ?? null, error: null };
        } catch {
          return { run, summary: null, months: null, error: "Request failed." };
        }
      })
    );
    setResults(settled);
    setLoading(false);
  }, [scenarios]);

  const chartScenarios: ScenarioTrend[] = (results ?? [])
    .filter((r) => r.months && r.months.length > 0)
    .map((r, i) => ({
      key: r.run.key,
      label: r.run.label,
      color: r.run.carrier ? carrierColor(r.run.carrier) : PALETTE[i % PALETTE.length],
      dash: DASH_PATTERNS[r.run.scenarioIndex % DASH_PATTERNS.length],
      months: r.months!,
    }));

  return (
    <main className="page">
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; Compare</p>
        <h1 className="title">Compare</h1>
        <p className="subtitle">
          Any number of carriers, airports, routes, or aircraft &mdash; side by side, same real
          warehouse data.
        </p>
      </header>

      <div className="compare-mode-toggle">
        <button type="button" className={mode === "carrier" ? "compare-mode-active" : ""} onClick={() => setMode("carrier")}>
          Carrier
        </button>
        <button type="button" className={mode === "airport" ? "compare-mode-active" : ""} onClick={() => setMode("airport")}>
          Airport
        </button>
        <button type="button" className={mode === "route" ? "compare-mode-active" : ""} onClick={() => setMode("route")}>
          Route
        </button>
        <button type="button" className={mode === "aircraft" ? "compare-mode-active" : ""} onClick={() => setMode("aircraft")}>
          Aircraft
        </button>
      </div>

      {mode === "airport" && (
        <EntityCompare key="airport" entityType="airport" initialValue={linkedEntity ?? undefined} />
      )}
      {mode === "route" && <EntityCompare key="route" entityType="route" />}
      {mode === "aircraft" && (
        <EntityCompare key="aircraft" entityType="aircraft" initialValue={linkedEntity ?? undefined} />
      )}

      {mode === "carrier" && (
      <>
      <div className="scenario-list">
        {scenarios.map((s, i) => (
          <div key={s.id} className="scenario-card" style={{ borderTopColor: PALETTE[i % PALETTE.length] }}>
            <div className="scenario-card-head">
              <input
                className="scenario-label-input"
                value={s.label}
                onChange={(e) => updateScenario(s.id, { label: e.target.value })}
              />
              <div className="scenario-card-controls">
                <button
                  type="button"
                  className="scenario-move"
                  onClick={() => moveScenario(s.id, -1)}
                  disabled={i === 0}
                  aria-label="Move left"
                  title="Move left"
                >
                  &#8592;
                </button>
                <button
                  type="button"
                  className="scenario-move"
                  onClick={() => moveScenario(s.id, 1)}
                  disabled={i === scenarios.length - 1}
                  aria-label="Move right"
                  title="Move right"
                >
                  &#8594;
                </button>
                {scenarios.length > 1 && (
                  <button
                    type="button"
                    className="scenario-remove"
                    onClick={() => removeScenario(s.id)}
                    aria-label="Remove scenario"
                    title="Remove scenario"
                  >
                    &times;
                  </button>
                )}
              </div>
            </div>

            <div className="filter-field">
              <div className="carrier-label-row">
                <span className="filter-label">
                  Carriers {s.carriers.length > 0 ? `(${s.carriers.length} selected)` : "(all combined)"}
                </span>
                <span className="carrier-quick-actions">
                  <button
                    type="button"
                    className="carrier-quick-btn"
                    onClick={() => setAllCarriers(s.id, [...CARRIER_CODES])}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    className="carrier-quick-btn"
                    onClick={() => setAllCarriers(s.id, [])}
                  >
                    Clear
                  </button>
                </span>
              </div>
              <div className="carrier-chip-row">
                {CARRIER_CODES.map((code) => {
                  const selected = s.carriers.includes(code);
                  return (
                    <button
                      type="button"
                      key={code}
                      className={`carrier-chip ${selected ? "carrier-chip-active" : ""}`}
                      style={selected ? { background: carrierColor(code), borderColor: carrierColor(code) } : undefined}
                      onClick={() => toggleCarrier(s.id, code)}
                      title={carrierName(code)}
                    >
                      {code}
                    </button>
                  );
                })}
              </div>
            </div>

            <label className="filter-field">
              <span className="filter-label">From</span>
              <input
                type="date"
                value={s.startDate}
                min="2018-01-01"
                onChange={(e) => updateScenario(s.id, { startDate: e.target.value })}
              />
            </label>

            <label className="filter-field">
              <span className="filter-label">To</span>
              <input
                type="date"
                value={s.endDate}
                min="2018-01-01"
                onChange={(e) => updateScenario(s.id, { endDate: e.target.value })}
              />
            </label>

            {dateErrorIds.has(s.id) && (
              <p className="scenario-error">&ldquo;From&rdquo; is after &ldquo;To&rdquo;</p>
            )}
          </div>
        ))}

        <button type="button" className="scenario-add" onClick={addScenario}>
          + Add scenario
        </button>
      </div>

      <div className="compare-run-row">
        <button
          type="button"
          className="compare-run"
          onClick={runComparison}
          disabled={loading || !canCompare}
        >
          {loading ? "Comparing..." : "Compare"}
        </button>
        {tooManyRuns && (
          <p className="scenario-error">
            {totalRuns} results requested (max {MAX_RUNS}) &mdash; select fewer carriers or scenarios.
          </p>
        )}
        {dateErrorIds.size > 0 && (
          <p className="scenario-error">Fix the date range error above before comparing.</p>
        )}
      </div>

      {results && (
        <>
          <section className="section">
            <div className="section-head">
              <h2 className="section-title">Results</h2>
            </div>
            <div className="screen" style={{ overflowX: "auto" }}>
              <table className="compare-table">
                <thead>
                  <tr>
                    <th></th>
                    {results.map((r, i) => (
                      <th
                        key={r.run.key}
                        style={{ color: r.run.carrier ? carrierColor(r.run.carrier) : PALETTE[i % PALETTE.length] }}
                      >
                        {r.run.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Carrier</td>
                    {results.map((r) => (
                      <td key={r.run.key}>{r.run.carrier ? carrierName(r.run.carrier) : "All"}</td>
                    ))}
                  </tr>
                  <tr>
                    <td>Total flights</td>
                    {results.map((r) => (
                      <td key={r.run.key}>{r.error ? "\u2014" : r.summary?.total_flights.toLocaleString()}</td>
                    ))}
                  </tr>
                  {(() => {
                    const otr = bestWorstIndices(results, (r) => r.summary?.on_time_rate ?? null);
                    const delay = bestWorstIndices(results, (r) =>
                      r.summary?.avg_arrival_delay_minutes == null
                        ? null
                        : -r.summary.avg_arrival_delay_minutes
                    );
                    const cancel = bestWorstIndices(results, (r) =>
                      r.summary ? -r.summary.cancellation_rate : null
                    );
                    return (
                      <>
                        <tr>
                          <td>On-time rate</td>
                          {results.map((r, i) => (
                            <td key={r.run.key} className={cellClass(i, otr.best, otr.worst)}>
                              {r.error ? "\u2014" : `${(r.summary!.on_time_rate * 100).toFixed(1)}%`}
                            </td>
                          ))}
                        </tr>
                        <tr>
                          <td>Avg arrival delay</td>
                          {results.map((r, i) => (
                            <td key={r.run.key} className={cellClass(i, delay.best, delay.worst)}>
                              {r.error ? "\u2014" : `${formatNumber(r.summary!.avg_arrival_delay_minutes)} min`}
                            </td>
                          ))}
                        </tr>
                        <tr>
                          <td>Cancellation rate</td>
                          {results.map((r, i) => (
                            <td key={r.run.key} className={cellClass(i, cancel.best, cancel.worst)}>
                              {r.error ? "\u2014" : `${(r.summary!.cancellation_rate * 100).toFixed(2)}%`}
                            </td>
                          ))}
                        </tr>
                      </>
                    );
                  })()}
                  <tr>
                    <td></td>
                    {results.map((r) => (
                      <td key={r.run.key} className="error-text">
                        {r.error}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          {chartScenarios.length > 0 && (
            <section className="section">
              <div className="section-head">
                <h2 className="section-title">On-time rate over time</h2>
              </div>
              <div className="screen">
                <ComparisonChart scenarios={chartScenarios} />
                <p className="chart-hint">Click a legend entry to hide/show that line.</p>
              </div>
            </section>
          )}
        </>
      )}
      </>
      )}
    </main>
  );
}
