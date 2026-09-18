"use client";

import Link from "next/link";
import { useState } from "react";
import { useMode } from "../lib/mode";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

type Metrics = {
  examples: number;
  delay_minutes_mae?: number;
  late_rate_mae?: number;
  late_rate_brier_like?: number;
  cancellation_rate_mae?: number;
  cancellation_rate_brier_like?: number;
};

type Method = { id: string; label: string; feature_names: string[] };

type Evidence = {
  status: "ready" | "unavailable" | "insufficient_history";
  reason?: string;
  cache?: { status: "hit" | "rebuilt"; ttl_seconds: number };
  data?: {
    route_month_examples: number;
    routes: number;
    network_routes_available: number;
    route_sample_limit: number;
    route_sampling: string;
    earliest_outcome_month: string;
    latest_outcome_month: string;
    t100_context_examples: number;
    t100_context_share: number;
    operational_context_examples: number;
    operational_context_share: number;
  };
  methods?: Method[];
  evaluation?: {
    window_count: number;
    test_horizon_months: number;
    minimum_training_periods: number;
    minimum_training_examples: number;
    aggregate: Record<string, Metrics>;
    winner_counts_by_target: Record<string, Record<string, number>>;
    windows: Array<{
      training_through: string;
      test_start: string;
      test_through: string;
      training_examples: number;
      test_examples: number;
      metrics: Record<string, Metrics>;
    }>;
  };
  methodology?: Record<string, string>;
};

const TARGETS = [
  { key: "delay_minutes", label: "Arrival delay" },
  { key: "late_rate", label: "Late-arrival rate" },
  { key: "cancellation_rate", label: "Cancellation rate" },
] as const;

function formatMetric(value: number | undefined, digits = 3): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function formatPercent(value: number | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

function labelForWinner(methods: Method[], wins: Record<string, number> | undefined): string {
  if (!wins || methods.length === 0) return "—";
  const best = Math.max(...methods.map((method) => wins[method.id] ?? 0));
  if (best <= 0) return "No clear winner";
  return methods.filter((method) => (wins[method.id] ?? 0) === best).map((method) => method.label).join(" / ");
}

export default function ModelEvidencePage() {
  const { mode, setMode } = useMode();
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadEvidence(refresh = false) {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/model-evidence/route-panel${refresh ? "?refresh=true" : ""}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The model-evidence check could not run.");
      setEvidence(payload);
    } catch (cause) {
      setEvidence(null);
      setError(cause instanceof Error ? cause.message : "The model-evidence check could not run.");
    } finally {
      setLoading(false);
    }
  }

  if (mode === "public") {
    return (
      <main className="page researcher-gate">
        <section className="researcher-gate-card">
          <p className="eyebrow">Research workspace</p>
          <h1 className="title">Model evidence belongs behind the public brief.</h1>
          <p className="subtitle">The public view shows measured patterns in plain language. This page checks whether a historical baseline, lagged T-100 traffic, and lagged operational context perform better on future months held back from training.</p>
          <button type="button" className="primary-action" onClick={() => setMode("researcher")}>Open researcher workspace <span>→</span></button>
        </section>
      </main>
    );
  }

  const methods = evidence?.methods ?? [];
  const evaluation = evidence?.evaluation;
  return (
    <main className="page model-evidence-page">
      <header className="header research-hero model-evidence-hero">
        <div>
          <p className="eyebrow">Researcher view · repeated temporal validation</p>
          <h1 className="title">Does more evidence help later?</h1>
          <p className="subtitle">We compare a transparent historical baseline with models that add lagged T-100 traffic and prior airport operation signals. Each check trains on earlier months and judges the answer on later months it was not allowed to see.</p>
        </div>
        <div className="hero-actions"><span className="status-chip"><span className="status-chip-dot" /> Research-only validation</span><Link href="/methodology#repeated-temporal-validation" className="text-link">Read the method →</Link></div>
      </header>

      <section className="model-evidence-intro">
        <div><p className="eyebrow">What this page answers</p><h2>Do the added data sources predict a later route-month more accurately?</h2></div>
        <p>A lower error across repeated future windows is useful evidence. It is still not proof that traffic, weather-coded delays, NAS-coded delays, or airport concentration caused an outcome.</p>
      </section>

      <section className="screen model-evidence-run-panel">
        <div><p className="eyebrow">Run the evidence check</p><h2 className="section-title">Four rolling future-month tests</h2><p className="page-note">The first run may take a little while because it fits several compact models over several independent time windows. Later visits reuse the six-hour local cache.</p></div>
        <div className="model-evidence-actions"><button type="button" className="compare-run" onClick={() => void loadEvidence(false)} disabled={loading}>{loading ? "Testing later months…" : evidence ? "Load saved evidence" : "Run repeated check"}</button>{evidence && <button type="button" className="secondary-action" onClick={() => void loadEvidence(true)} disabled={loading}>Rebuild from warehouse</button>}</div>
      </section>

      {error && <div className="callout callout-warn">{error}</div>}
      {loading && <div className="screen model-evidence-loading"><span className="status-chip-dot" /><div><strong>Keeping future months out of training</strong><p>Fitting and evaluating the models in chronological order. This happens once, then is cached locally.</p></div></div>}
      {evidence && evidence.status !== "ready" && <div className="callout callout-warn">{evidence.reason ?? "The available history is not yet sufficient for the repeated evidence check."}</div>}

      {evidence?.status === "ready" && evaluation && evidence.data && (
        <>
          <section className="section">
            <div className="section-head"><div><p className="eyebrow">01 · Evidence scope</p><h2 className="section-title">What was actually checked</h2></div><span className="section-note">{evidence.cache?.status === "hit" ? "cached local evidence" : "freshly rebuilt"}</span></div>
            <div className="board model-evidence-board"><MetricTile label="Route-month examples" value={evidence.data.route_month_examples.toLocaleString()} /><MetricTile label="Routes sampled" value={evidence.data.routes.toLocaleString()} /><MetricTile label="T-100 coverage" value={formatPercent(evidence.data.t100_context_share)} tone="signal" /><MetricTile label="Operation-driver coverage" value={formatPercent(evidence.data.operational_context_share)} tone="signal" /></div>
            <div className="model-evidence-scope-strip"><span>Outcomes: {evidence.data.earliest_outcome_month} → {evidence.data.latest_outcome_month}</span><span>{evidence.data.routes.toLocaleString()} deterministic routes from {evidence.data.network_routes_available.toLocaleString()} available</span><span>{evaluation.window_count} later windows · {evaluation.test_horizon_months} months each</span><span>At least {evaluation.minimum_training_periods} periods and {evaluation.minimum_training_examples.toLocaleString()} earlier examples before each fit</span></div>
            <p className="page-note model-evidence-sampling-note">Sampling note: {evidence.data.route_sampling}</p>
          </section>

          <section className="section">
            <div className="section-head"><div><p className="eyebrow">02 · Compare methods</p><h2 className="section-title">Average error on months held back from training</h2></div><span className="section-note">Lower MAE is better</span></div>
            <div className="screen table-screen"><div className="table-scroll"><table className="compare-table model-evidence-table"><thead><tr><th>Method</th><th>Arrival-delay MAE</th><th>Late-rate MAE</th><th>Cancellation MAE</th><th>Examples</th></tr></thead><tbody>{methods.map((method) => { const metrics = evaluation.aggregate[method.id]; return <tr key={method.id}><td><strong>{method.label}</strong></td><td>{formatMetric(metrics?.delay_minutes_mae, 2)} min</td><td>{formatMetric(metrics?.late_rate_mae, 3)}</td><td>{formatMetric(metrics?.cancellation_rate_mae, 3)}</td><td>{metrics?.examples.toLocaleString() ?? "—"}</td></tr>; })}</tbody></table></div></div>
            <div className="model-evidence-winner-grid">{TARGETS.map((target) => <div key={target.key}><span>{target.label}</span><strong>{labelForWinner(methods, evaluation.winner_counts_by_target[target.key])}</strong><small>Most window-level MAE wins</small></div>)}</div>
          </section>

          <section className="section">
            <div className="section-head"><div><p className="eyebrow">03 · Check stability</p><h2 className="section-title">Every future window stays visible</h2></div><span className="section-note">No hand-picked split</span></div>
            <div className="screen table-screen"><div className="table-scroll"><table className="compare-table model-evidence-window-table"><thead><tr><th>Training through</th><th>Future test window</th><th>Test examples</th>{methods.map((method) => <th key={method.id}>{method.label}<br /><small>delay MAE</small></th>)}</tr></thead><tbody>{evaluation.windows.map((window) => <tr key={window.test_start}><td>{window.training_through}</td><td>{window.test_start} → {window.test_through}</td><td>{window.test_examples.toLocaleString()}</td>{methods.map((method) => <td key={method.id}>{formatMetric(window.metrics[method.id]?.delay_minutes_mae, 2)} min</td>)}</tr>)}</tbody></table></div></div>
          </section>

          <section className="model-evidence-reading-grid"><div className="screen mini-method-card"><p className="eyebrow">T-100 input</p><h3>Traffic context, lagged</h3><p>Seats, passengers, load factor, and T-100 completion data are joined only from a month before the OTP outcome.</p></div><div className="screen mini-method-card"><p className="eyebrow">Operation input</p><h3>Historical airport pressure</h3><p>WeatherDelay, NASDelay, departure delay, and peak-hour concentration are historical airport-month context, not a live forecast or a certified capacity measure.</p></div><div className="screen mini-method-card"><p className="eyebrow">Decision rule</p><h3>Evidence before promotion</h3><p>More complex methods remain researcher candidates unless they improve repeatedly on later, held-back months.</p></div></section>
          <p className="page-note source-line">{evidence.methodology?.interpretation} <Link href="/methodology#repeated-temporal-validation">Full methodology</Link>.</p>
        </>
      )}
    </main>
  );
}

function MetricTile({ label, value, tone }: { label: string; value: string; tone?: "signal" }) {
  return <div className="tile"><span className="tile-label">{label}</span><span className={`tile-value ${tone === "signal" ? "signal" : ""}`}>{value}</span></div>;
}
