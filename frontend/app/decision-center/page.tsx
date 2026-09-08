"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { CARRIER_NAMES, carrierName } from "../lib/carriers";
import type {
  CapacityCorrelationResult,
  Coefficient,
  Lever,
  LeverResult,
  NetworkResilienceResult,
  RankingEntry,
  RankingResult,
  RiskResult,
  ScenarioCell,
  ScenarioResult,
} from "./types";
import {
  COMPONENT_LABELS,
  FEATURE_LABELS,
  PREDECESSOR_COLS,
  COST_MODEL_LABELS,
  DecisionTab,
  METRIC_LABELS,
  TAB_METHOD_ANCHORS,
  TAB_HELP,
  TURNAROUND_ROWS,
} from "./constants";
import { useMode } from "../lib/mode";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const CARRIER_CODES = Object.keys(CARRIER_NAMES);

function scoreColor(score: number): string {
  if (score >= 80) return "#4f9d8f";
  if (score >= 65) return "#e8a33d";
  return "#c9563a";
}

function delayColor(minutes: number): string {
  if (minutes <= 15) return "#4f9d8f";
  if (minutes <= 45) return "#e8a33d";
  return "#c9563a";
}

// Genuinely derives a verdict from the actual cell values -- doesn't force
// a clean story where the data doesn't show one. If the same turnaround
// bucket has the lowest average knock-on delay at every inbound-delay
// level, that's a real, consistent pattern worth stating plainly. If it's
// mixed, saying so honestly is more useful than papering over it.
function deriveScenarioVerdict(result: ScenarioResult): string | null {
  const winners: Record<string, string> = {};
  for (const col of PREDECESSOR_COLS) {
    let best: ScenarioCell | null = null;
    for (const row of TURNAROUND_ROWS) {
      const cell = result.cells.find((c) => c.turnaround_bucket === row && c.predecessor_bucket === col);
      if (cell && (!best || cell.avg_successor_dep_delay < best.avg_successor_dep_delay)) {
        best = cell;
      }
    }
    if (best) winners[col] = best.turnaround_bucket;
  }

  const distinctWinners = new Set(Object.values(winners));
  if (distinctWinners.size === 0) return null;

  if (distinctWinners.size === 1) {
    const winner = [...distinctWinners][0];
    return `Consistent pattern: ${winner.toLowerCase()} turnarounds show the lowest average knock-on delay at every inbound-delay level in this data -- not just on average, but at each of the three levels checked separately.`;
  }

  const parts = PREDECESSOR_COLS.filter((c) => winners[c]).map(
    (c) => `${winners[c].toLowerCase()} does best when the inbound flight was ${c.toLowerCase()}`
  );
  return `Mixed pattern, not a clean story: ${parts.join("; ")}. No single turnaround type wins across every inbound-delay level here.`;
}

// Surfaces the real tension between "biggest arithmetic gap" and "biggest
// flight volume" rather than picking one number and calling it "priority"
// -- those are two different, independently true facts, and which matters
// more is a judgment call this function doesn't make for the reader.
function deriveRankingVerdict(result: RankingResult): string | null {
  if (result.carriers.length === 0) return null;
  const topGain = result.carriers[0];
  const topThree = result.carriers.slice(0, 3);
  const topVolume = topThree.reduce((a, b) => (b.total_flights > a.total_flights ? b : a));

  if (topGain.carrier === topVolume.carrier) {
    return `${carrierName(topGain.carrier)} is the clearest starting point among the first three: it has the largest possible score change (+${topGain.top_lever_point_gain.toFixed(1)} via ${COMPONENT_LABELS[topGain.top_lever_component]}) and the most flights affected.`;
  }

  const ratio = topVolume.total_flights / topGain.total_flights;
  return `The largest possible score change is with ${carrierName(topGain.carrier)} (+${topGain.top_lever_point_gain.toFixed(1)} via ${COMPONENT_LABELS[topGain.top_lever_component]}). ${carrierName(topVolume.carrier)} reaches ${topVolume.total_flights.toLocaleString()} flights among the first three — ${ratio.toFixed(1)}x more — so this page shows both size of change and reach for you to weigh.`;
}

export default function DecisionCenterPage() {
  const { mode, setMode } = useMode();
  const [tab, setTab] = useState<DecisionTab>("levers");
  const [carrierInput, setCarrierInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState(false);

  const [leverResult, setLeverResult] = useState<LeverResult | null>(null);
  const [scenarioResult, setScenarioResult] = useState<ScenarioResult | null>(null);
  const [rankingResult, setRankingResult] = useState<RankingResult | null>(null);
  const [portfolioBudget, setPortfolioBudget] = useState<number | null>(3);

  const [riskEntityType, setRiskEntityType] = useState<"carrier" | "airport">("carrier");
  const [riskEntity, setRiskEntity] = useState("");
  const [airportOptions, setAirportOptions] = useState<string[]>([]);
  const [riskResult, setRiskResult] = useState<RiskResult | null>(null);

  const [bankAirport, setBankAirport] = useState("");
  const [bankCarrier, setBankCarrier] = useState("");
  const [bankWindowStart, setBankWindowStart] = useState(6);
  const [bankWindowEnd, setBankWindowEnd] = useState(10);
  const [bankShift, setBankShift] = useState(30);
  const [bankMaxMoved, setBankMaxMoved] = useState<number | null>(null);
  const [bankMode, setBankMode] = useState<"expected" | "risk_averse">("expected");
  const [bankSeasonalYears, setBankSeasonalYears] = useState(3);
  const [bankResult, setBankResult] = useState<any>(null);

  const [portfolioType, setPortfolioType] = useState<"carrier" | "airport">("carrier");
  const [portfolioBudgetInput, setPortfolioBudgetInput] = useState(3);
  const [portfolioMetric, setPortfolioMetric] = useState("severe_delay_exposure");
  const [portfolioCostModel, setPortfolioCostModel] = useState("unit");
  const [portfolioResult, setPortfolioResult] = useState<any>(null);

  const [resilienceMinFlights, setResilienceMinFlights] = useState(50);
  const [resilienceResult, setResilienceResult] = useState<NetworkResilienceResult | null>(null);
  const [capacityCarrier, setCapacityCarrier] = useState("");
  const [capacityResult, setCapacityResult] = useState<CapacityCorrelationResult | null>(null);

  useEffect(() => {
    if ((riskEntityType === "airport" || tab === "bank") && airportOptions.length === 0) {
      fetch(`${API_BASE}/api/airports/list`)
        .then((r) => r.json())
        .then((data) => setAirportOptions(data.airports ?? []))
        .catch(() => setAirportOptions([]));
    }
  }, [riskEntityType, airportOptions.length, tab]);

  function resetResults() {
    setLeverResult(null);
    setScenarioResult(null);
    setRankingResult(null);
    setRiskResult(null);
    setBankResult(null);
    setPortfolioResult(null);
    setResilienceResult(null);
    setCapacityResult(null);
    setNotFound(false);
    setError(false);
  }

  async function analyze() {
    if (tab === "levers" || tab === "scenario") {
      if (!carrierInput) return;
    } else if (tab === "risk") {
      if (!riskEntity) return;
    } else if (tab === "bank") {
      if (!bankAirport) return;
    }
    setLoading(true);
    setNotFound(false);
    setError(false);
    try {
      if (tab === "levers") {
        const res = await fetch(`${API_BASE}/api/decision/health-improvement?carrier=${encodeURIComponent(carrierInput)}`);
        if (res.status === 404) { setLeverResult(null); setNotFound(true); return; }
        if (!res.ok) throw new Error("not ok");
        setLeverResult(await res.json());
      } else if (tab === "scenario") {
        const res = await fetch(`${API_BASE}/api/decision/propagation-scenario?carrier=${encodeURIComponent(carrierInput)}`);
        if (res.status === 404) { setScenarioResult(null); setNotFound(true); return; }
        if (!res.ok) throw new Error("not ok");
        setScenarioResult(await res.json());
      } else if (tab === "risk") {
        const res = await fetch(`${API_BASE}/api/decision/predictive-risk?entity_type=${riskEntityType}&entity=${encodeURIComponent(riskEntity)}`);
        if (res.status === 404) { setRiskResult(null); setNotFound(true); return; }
        if (!res.ok) throw new Error("not ok");
        setRiskResult(await res.json());
      } else if (tab === "bank") {
        const params = new URLSearchParams({
          airport: bankAirport,
          window_start_hour: String(bankWindowStart), window_end_hour: String(bankWindowEnd),
          allowed_shift_minutes: String(bankShift), mode: bankMode,
          seasonal_lookback_years: String(bankSeasonalYears),
        });
        if (bankCarrier) params.set("carrier", bankCarrier);
        if (bankMaxMoved !== null) params.set("max_moved_flights", String(bankMaxMoved));
        const res = await fetch(`${API_BASE}/api/decision/departure-bank-smoothing?${params}`);
        if (res.status === 404) { setBankResult(null); setNotFound(true); return; }
        if (!res.ok) throw new Error("not ok");
        setBankResult(await res.json());
      } else if (tab === "portfolio") {
        const params = new URLSearchParams({
          candidate_type: portfolioType, budget: String(portfolioBudgetInput), primary_metric: portfolioMetric,
          cost_model: portfolioCostModel,
        });
        const res = await fetch(`${API_BASE}/api/decision/network-protection-portfolio?${params}`);
        if (!res.ok) throw new Error("not ok");
        setPortfolioResult(await res.json());
      } else if (tab === "resilience") {
        const res = await fetch(`${API_BASE}/api/decision/network-resilience?minimum_flights=${resilienceMinFlights}`);
        if (!res.ok) throw new Error("not ok");
        setResilienceResult(await res.json());
      } else if (tab === "capacity") {
        const params = new URLSearchParams({ limit: "30", minimum_flights: "100" });
        if (capacityCarrier) params.set("carrier", capacityCarrier);
        const res = await fetch(`${API_BASE}/api/capacity/correlation?${params}`);
        if (!res.ok) throw new Error("not ok");
        setCapacityResult(await res.json());
      } else {
        const res = await fetch(`${API_BASE}/api/decision/opportunity-ranking`);
        if (!res.ok) throw new Error("not ok");
        setRankingResult(await res.json());
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  const topLever = leverResult?.levers?.[0];

  function scenarioCell(turnaround: string, predecessor: string): ScenarioCell | undefined {
    return scenarioResult?.cells.find(
      (c) => c.turnaround_bucket === turnaround && c.predecessor_bucket === predecessor
    );
  }

  if (mode === "public") {
    return (
      <main className="page researcher-gate">
        <section className="researcher-gate-card">
          <p className="eyebrow">Research workspace</p>
          <h1 className="title">Decision Center is where the questions become tests.</h1>
          <p className="subtitle">
            The public brief is designed to explain the network quickly. This workspace is for comparing carriers,
            checking next-month risk, testing bounded schedule changes, and connecting T-100 traffic with on-time outcomes.
          </p>
          <div className="researcher-gate-actions">
            <button type="button" className="primary-action" onClick={() => setMode("researcher")}>Open researcher workspace <span>→</span></button>
            <Link href="/methodology#decision-center-methodology" className="secondary-action">Read the method first</Link>
          </div>
          <p className="page-note">You can switch back to the public brief at any time from the navigation.</p>
        </section>
      </main>
    );
  }

  return (
    <main className="page decision-center-page surface-page surface-researcher">
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; Decision Center</p>
        <h1 className="title">Decision Center</h1>
        <p className="subtitle">
          Simple questions on real flight data. <Link href="/methodology#decision-center-methodology">See the methodology</Link> for the full math.
        </p>
      </header>

      <section className="decision-guide" aria-label="How to read the Decision Center">
        <div>
          <span className="decision-guide-title">Decision Center in simple words</span>
          <span className="decision-guide-copy">Pick a question → choose a few settings → read the answer.</span>
        </div>
        <div className="decision-guide-legend">
          <span><b>Look back</b> what happened</span>
          <span><b>Look ahead</b> what may happen</span>
          <span><b>Try a change</b> what could improve</span>
        </div>
      </section>

      <div className="sort-toggle" style={{ marginBottom: "1.5rem" }}>
        <button
          type="button"
          className={tab === "levers" ? "sort-toggle-active" : ""}
          onClick={() => { setTab("levers"); resetResults(); }}
        >
          {TAB_HELP.levers.label}
        </button>
        <button
          type="button"
          className={tab === "scenario" ? "sort-toggle-active" : ""}
          onClick={() => { setTab("scenario"); resetResults(); }}
        >
          {TAB_HELP.scenario.label}
        </button>
        <button
          type="button"
          className={tab === "ranking" ? "sort-toggle-active" : ""}
          onClick={() => { setTab("ranking"); resetResults(); }}
        >
          {TAB_HELP.ranking.label}
        </button>
        <button
          type="button"
          className={tab === "risk" ? "sort-toggle-active" : ""}
          onClick={() => { setTab("risk"); resetResults(); }}
        >
          {TAB_HELP.risk.label}
        </button>
        <button
          type="button"
          className={tab === "bank" ? "sort-toggle-active" : ""}
          onClick={() => { setTab("bank"); resetResults(); }}
        >
          {TAB_HELP.bank.label}
        </button>
        <button
          type="button"
          className={tab === "portfolio" ? "sort-toggle-active" : ""}
          onClick={() => { setTab("portfolio"); resetResults(); }}
        >
          {TAB_HELP.portfolio.label}
        </button>
        <button
          type="button"
          className={tab === "resilience" ? "sort-toggle-active" : ""}
          onClick={() => { setTab("resilience"); resetResults(); }}
        >
          {TAB_HELP.resilience.label}
        </button>
        <button
          type="button"
          className={tab === "capacity" ? "sort-toggle-active" : ""}
          onClick={() => { setTab("capacity"); resetResults(); }}
        >
          {TAB_HELP.capacity.label}
        </button>
      </div>

      <section className="section" style={{ marginTop: 0 }}>
        <div className="screen">
          <p className="page-note" style={{ marginBottom: "0.75rem" }}>
            <strong>Question:</strong> {TAB_HELP[tab].question}
          </p>
          <div className="decision-simple-help">
            <div><span>YOU CHOOSE</span>{TAB_HELP[tab].choose}</div>
            <div><span>YOU GET</span>{TAB_HELP[tab].result}</div>
          </div>
          <p className="page-note" style={{ marginTop: "0.75rem" }}>
            <Link href={`/methodology#${TAB_METHOD_ANCHORS[tab]}`}>Open the full methodology</Link> if you want the detailed method.
          </p>
          <div style={{ display: "none" }}>
          {tab === "levers" && (
            <>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is:</strong> for each of the five Health Score components, this
                shows what the overall score would become if that ONE component moved to the
                current network median for that carrier&apos;s peers &mdash; holding everything
                else exactly as it is now.
              </p>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is not:</strong> a prediction of what would actually happen if a
                carrier changed anything, or a claim about how easy or hard any given component is
                to move &mdash; only the arithmetic leverage in the scoring formula.
              </p>
            </>
          )}
          {tab === "scenario" && (
            <>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is:</strong> for same-day, same-tail flight pairs, the actual
                average departure delay of the SECOND flight, broken down by how tight the
                scheduled turnaround was and how late the FIRST flight arrived. Every number here
                is something that really happened in the data.
              </p>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is not:</strong> a prediction of what would happen if a carrier
                changed its turnaround policy. These are historical averages under the conditions
                that actually occurred, not a model of cause and effect &mdash; carriers likely
                don&apos;t assign tight turnarounds at random (see{" "}
                <Link href="/delays">Delays</Link> for the full discussion).
              </p>
            </>
          )}
          {tab === "ranking" && (
            <>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is:</strong> unlike the other two tabs, this doesn&apos;t need a
                carrier picked first &mdash; it ranks every carrier&apos;s single biggest Health
                Score lever, network-wide, so you can see where the largest opportunities are
                before deciding what to look into further.
              </p>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is not:</strong> a single "priority score." Point gain (arithmetic
                opportunity) and flight volume (real-world reach) are shown separately on purpose
                &mdash; multiplying them into one number would look more rigorous than it actually
                is. Which one should drive a decision is a real judgment call this doesn&apos;t
                make for you.
              </p>
            </>
          )}
          {tab === "risk" && (
            <>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is:</strong> a real trained model, not a hand-picked formula.
                Six current-month features (severe-delay rate, cancellation rate, average
                departure delay, late-aircraft share, ground-time share, flight volume) predict
                whether NEXT month's severe-delay rate lands in the network's worst quartile.
                Trained on a chronological split (train/validate/test by date, never mixed) and
                calibrated so the probability actually means what it says &mdash; both the
                model's real test-set performance and its calibration accuracy are shown below,
                not hidden.
              </p>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is not:</strong> a certainty. Every model here is retrained
                fresh from real flight-level aggregates on each request &mdash; check the sample
                sizes and precision-recall AUC before trusting the number. A small test set or
                weak AUC means take the risk band as a rough signal, not a verdict.
              </p>
            </>
          )}

          {tab === "bank" && (
            <>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is:</strong> a real optimizer, not a suggestion engine. Given a
                departure bank at one airport, it decides whether shifting some flights by a small,
                bounded amount (&plusmn;15/30/45 min) would meaningfully reduce how crowded the
                busiest 15-minute slot gets. Solved as an actual MILP (mixed-integer linear
                program) via an open-source solver &mdash; every flight either moves or doesn&apos;t,
                nothing fuzzy about it. The congestion baseline is seasonal by default &mdash; it
                compares this window against the SAME calendar window in prior years (Thanksgiving
                vs. prior Thanksgivings, September vs. prior Septembers), not just this window
                against itself, which would be circular if the window being analyzed is already an
                elevated period.
              </p>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is not:</strong> a claim about certified airport capacity. BTS
                doesn&apos;t provide that, so this uses historical load as the congestion signal,
                labeled as such throughout. It also only rearranges flights already in the dataset
                &mdash; it can&apos;t add, cancel, or move flights across carriers.
              </p>
            </>
          )}

          {tab === "portfolio" && (
            <>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is:</strong> if you can only focus resources on a few
                carriers or airports, which ones give the most real coverage for the budget? A
                real 0/1 knapsack optimization &mdash; pick the metric that matters to you
                (severe-delay exposure, cancellation resilience, or volume), choose how resource
                cost should scale, and it selects the best-value combination under your budget.
                Every OTHER metric is still reported for
                whatever gets selected, so nothing is hidden inside one invented priority score.
              </p>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is not:</strong> a claim that intervening will produce a
                specific improvement &mdash; it's an allocation tool over real, disclosed
                historical metrics, not a causal guarantee.
              </p>
            </>
          )}

          {tab === "resilience" && (
            <>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is:</strong> a real directed graph &mdash; airports as nodes,
                routes as edges &mdash; built from the whole network, not just the busiest routes.
                Reports two genuinely different, separately-computed measures: raw hub-ness
                (connection count and traffic volume) and betweenness centrality (what fraction of
                shortest paths between OTHER airport pairs run through this one). An airport can
                rank low on volume but high on betweenness if it's a structural bridge with few
                alternate routes around it &mdash; that's the actual point of computing it
                separately rather than folding it into one score.
              </p>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                <strong>What this is not:</strong> a simulation of what actually happens to the
                network if an airport closes &mdash; betweenness is a structural proxy, not a
                literal removal-and-resimulate model.
              </p>
            </>
          )}
          </div>

          {(tab === "levers" || tab === "scenario") && (
            <div className="route-lookup-row">
              <label className="filter-field">
                <span className="filter-label">Carrier</span>
                <select value={carrierInput} onChange={(e) => setCarrierInput(e.target.value)}>
                  <option value="">Select carrier</option>
                  {CARRIER_CODES.map((code) => (
                    <option key={code} value={code}>{code} &mdash; {carrierName(code)}</option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="compare-run"
                onClick={analyze}
                disabled={!carrierInput || loading}
              >
                {loading ? "Analyzing..." : "Analyze"}
              </button>
            </div>
          )}
          {tab === "ranking" && (
            <button
              type="button"
              className="compare-run"
              onClick={analyze}
              disabled={loading}
            >
              {loading ? "Ranking..." : "Rank the network"}
            </button>
          )}
          {tab === "risk" && (
            <div className="route-lookup-row">
              <label className="filter-field">
                <span className="filter-label">Who to check</span>
                <select
                  value={riskEntityType}
                  onChange={(e) => { setRiskEntityType(e.target.value as "carrier" | "airport"); setRiskEntity(""); }}
                >
                  <option value="carrier">Carrier</option>
                  <option value="airport">Airport</option>
                </select>
              </label>
              <label className="filter-field">
                <span className="filter-label">{riskEntityType === "carrier" ? "Choose an airline" : "Choose an airport"}</span>
                <select value={riskEntity} onChange={(e) => setRiskEntity(e.target.value)}>
                  <option value="">Select one</option>
                  {riskEntityType === "carrier"
                    ? CARRIER_CODES.map((code) => (
                        <option key={code} value={code}>{code} &mdash; {carrierName(code)}</option>
                      ))
                    : airportOptions.map((code) => <option key={code} value={code}>{code}</option>)}
                </select>
              </label>
              <button
                type="button"
                className="compare-run"
                onClick={analyze}
                disabled={!riskEntity || loading}
              >
                  {loading ? "Checking..." : "Check next month"}
              </button>
            </div>
          )}

          {tab === "bank" && (
            <div className="route-lookup-row" style={{ flexWrap: "wrap" }}>
              <label className="filter-field">
                <span className="filter-label">Airport</span>
                <select value={bankAirport} onChange={(e) => setBankAirport(e.target.value)}>
                  <option value="">Select airport</option>
                  {airportOptions.map((code) => <option key={code} value={code}>{code}</option>)}
                </select>
              </label>
              <label className="filter-field">
                <span className="filter-label">Airline (optional)</span>
                <select value={bankCarrier} onChange={(e) => setBankCarrier(e.target.value)}>
                  <option value="">All carriers</option>
                  {CARRIER_CODES.map((code) => (
                    <option key={code} value={code}>{code} &mdash; {carrierName(code)}</option>
                  ))}
                </select>
              </label>
              <label className="filter-field">
                <span className="filter-label">Busy period starts</span>
                <select value={bankWindowStart} onChange={(e) => setBankWindowStart(Number(e.target.value))}>
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h}:00</option>)}
                </select>
              </label>
              <label className="filter-field">
                <span className="filter-label">Busy period ends</span>
                <select value={bankWindowEnd} onChange={(e) => setBankWindowEnd(Number(e.target.value))}>
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h}:00</option>)}
                </select>
              </label>
              <label className="filter-field">
                <span className="filter-label">Move flights by at most</span>
                <select value={bankShift} onChange={(e) => setBankShift(Number(e.target.value))}>
                  <option value={15}>&plusmn;15 min</option>
                  <option value={30}>&plusmn;30 min</option>
                  <option value={45}>&plusmn;45 min</option>
                </select>
              </label>
              <label className="filter-field">
                <span className="filter-label">Maximum flights to move</span>
                <input
                  type="number"
                  min={0}
                  value={bankMaxMoved ?? ""}
                  placeholder="No cap"
                  onChange={(e) => setBankMaxMoved(e.target.value === "" ? null : Number(e.target.value))}
                  style={{ width: "6rem" }}
                />
              </label>
              <label className="filter-field">
                <span className="filter-label">How cautious?</span>
                <select value={bankMode} onChange={(e) => setBankMode(e.target.value as "expected" | "risk_averse")}>
                  <option value="expected">Use the average result</option>
                  <option value="risk_averse">Be more cautious</option>
                </select>
              </label>
              <label className="filter-field">
                <span className="filter-label">Compare with previous years</span>
                <select value={bankSeasonalYears} onChange={(e) => setBankSeasonalYears(Number(e.target.value))}>
                  <option value={0}>No — this window only</option>
                  <option value={1}>1 prior year</option>
                  <option value={3}>3 prior years</option>
                  <option value={5}>5 prior years</option>
                </select>
              </label>
              <button
                type="button"
                className="compare-run"
                onClick={analyze}
                disabled={!bankAirport || loading}
              >
                  {loading ? "Trying..." : "Try the change"}
              </button>
            </div>
          )}

          {tab === "portfolio" && (
            <div className="route-lookup-row">
              <label className="filter-field">
                <span className="filter-label">Focus on</span>
                <select value={portfolioType} onChange={(e) => setPortfolioType(e.target.value as "carrier" | "airport")}>
                  <option value="carrier">Carrier</option>
                  <option value="airport">Airport</option>
                </select>
              </label>
              <label className="filter-field">
                <span className="filter-label">Number of targets</span>
                <input
                  type="number" min={1} max={20} value={portfolioBudgetInput}
                  onChange={(e) => setPortfolioBudgetInput(Number(e.target.value))}
                  style={{ width: "5rem" }}
                />
              </label>
              <label className="filter-field">
                <span className="filter-label">Attention per target</span>
                <select value={portfolioCostModel} onChange={(e) => setPortfolioCostModel(e.target.value)}>
                  <option value="unit">Equal attention per target</option>
                  <option value="flight_volume_millions">Flight-volume exposure</option>
                  <option value="sqrt_flight_volume">Square-root volume proxy</option>
                </select>
              </label>
              <label className="filter-field">
                <span className="filter-label">Main goal</span>
                <select value={portfolioMetric} onChange={(e) => setPortfolioMetric(e.target.value)}>
                  {Object.entries(METRIC_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <button type="button" className="compare-run" onClick={analyze} disabled={loading}>
                {loading ? "Choosing..." : "Choose focus areas"}
              </button>
            </div>
          )}

          {tab === "resilience" && (
            <div className="route-lookup-row">
              <label className="filter-field">
                <span className="filter-label">Ignore routes with fewer than</span>
                <input
                  type="number" min={1} max={5000} value={resilienceMinFlights}
                  onChange={(e) => setResilienceMinFlights(Number(e.target.value))}
                  style={{ width: "6rem" }}
                />
              </label>
              <button type="button" className="compare-run" onClick={analyze} disabled={loading}>
                {loading ? "Finding..." : "Find important airports"}
              </button>
            </div>
          )}

          {tab === "capacity" && (
            <div className="route-lookup-row">
              <label className="filter-field">
                <span className="filter-label">Airline (optional)</span>
                <select value={capacityCarrier} onChange={(e) => setCapacityCarrier(e.target.value)}>
                  <option value="">All carriers</option>
                  {CARRIER_CODES.map((code) => (
                    <option key={code} value={code}>{code} &mdash; {carrierName(code)}</option>
                  ))}
                </select>
              </label>
              <button type="button" className="compare-run" onClick={analyze} disabled={loading}>
                {loading ? "Comparing..." : "Compare traffic and on-time"}
              </button>
              <Link href="/capacity" className="decision-external-link">Open the full T-100 view →</Link>
            </div>
          )}

          <p className="decision-tab-type">
            <span>{TAB_HELP[tab].kind}</span> {TAB_HELP[tab].result}
          </p>

          {notFound && <p className="error-text" style={{ marginTop: "1rem" }}>No matching flights found for that carrier.</p>}
          {error && <p className="error-text" style={{ marginTop: "1rem" }}>Could not reach the API.</p>}
        </div>
      </section>

      {tab === "levers" && leverResult && (
        <>
          <section className="section">
            <div className="screen">
              <div style={{ display: "flex", alignItems: "center", gap: "1.5rem" }}>
                <span style={{ fontFamily: "var(--font-mono), monospace", fontSize: "2.4rem", fontWeight: 700, color: scoreColor(leverResult.current_score) }}>
                  {Math.round(leverResult.current_score)}
                </span>
                <div>
                  <div style={{ color: scoreColor(leverResult.current_score), fontWeight: 600 }}>{leverResult.current_rating}</div>
                  <div className="tile-label">{carrierName(leverResult.carrier)}&apos;s current Health Score, vs. {leverResult.peer_count} other airlines</div>
                </div>
              </div>

              {topLever && parseFloat(topLever.point_gain.toFixed(1)) > 0 && (
                <div className="decision-verdict">
                  <span className="decision-verdict-label">Recommendation</span>
                  Start with <strong>{COMPONENT_LABELS[topLever.component]}</strong>. In this
                  score-based what-if, bringing it to the network&apos;s typical value would change the score from{" "}
                  <strong>{leverResult.current_score.toFixed(1)}</strong> to{" "}
                  <strong>{topLever.hypothetical_score_if_at_median.toFixed(1)}</strong> ({" "}
                  <strong>+{topLever.point_gain.toFixed(1)} points</strong>). It identifies where
                  to investigate first; it does not promise that the change is easy or causal.
                </div>
              )}
              {topLever && parseFloat(topLever.point_gain.toFixed(1)) <= 0 && (
                <div className="decision-verdict">
                  <span className="decision-verdict-label">Recommendation</span>
                  No single area stands out below the network&apos;s typical value, so this check does
                  not point to one clear opportunity for this airline.
                </div>
              )}
            </div>
          </section>

          <section className="section">
            <div className="section-head">
            <h2 className="section-title">All five areas, biggest score changes first</h2>
            </div>
            <div className="screen">
              <div className="rotation-table-wrap">
                <table className="compare-table">
                  <thead>
                    <tr>
                      <th>Area</th>
                      <th>Current</th>
                      <th>Network typical</th>
                      <th>Importance</th>
                      <th>Current score points</th>
                      <th>Score if matched</th>
                      <th>Score change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {leverResult.levers.map((l) => {
                      const rounded = parseFloat(l.point_gain.toFixed(1)) === 0 ? "0.0" : l.point_gain.toFixed(1);
                      const isPositive = parseFloat(rounded) > 0;
                      return (
                        <tr key={l.component}>
                          <td>{COMPONENT_LABELS[l.component] ?? l.component}</td>
                          <td>{l.current_value.toFixed(1)}</td>
                          <td>{l.network_median.toFixed(1)}</td>
                          <td>{(l.weight * 100).toFixed(1)}%</td>
                          <td>{(l.current_value * l.weight).toFixed(1)}/{(100 * l.weight).toFixed(1)} pts</td>
                          <td>{l.hypothetical_score_if_at_median.toFixed(1)}</td>
                          <td className={isPositive ? "tile-value" : ""}>
                            {isPositive ? "+" : ""}{rounded}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </>
      )}

      {tab === "scenario" && scenarioResult && (
        <section className="section">
          <div className="section-head">
            <h2 className="section-title">
              What happened to the next flight for {carrierName(scenarioResult.carrier ?? "")}
            </h2>
            <span className="section-note">average minutes late</span>
          </div>
          <div className="screen">
            {(() => {
              const verdict = deriveScenarioVerdict(scenarioResult);
              return verdict ? (
                <div className="decision-verdict">
                  <span className="decision-verdict-label">Pattern in the data</span>
                  {verdict}
                </div>
              ) : null;
            })()}

            <div className="rotation-table-wrap" style={{ marginTop: "1.25rem" }}>
              <table className="compare-table">
                <thead>
                  <tr>
                      <th>Planned time before next flight</th>
                    {PREDECESSOR_COLS.map((col) => <th key={col}>{col}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {TURNAROUND_ROWS.map((row) => (
                    <tr key={row}>
                      <td>
                        {row === "Tight" && `Tight (\u2264${scenarioResult.tight_turnaround_minutes} min)`}
                        {row === "Normal" && `Normal (${scenarioResult.tight_turnaround_minutes + 1}\u2013${scenarioResult.target_turnaround_minutes} min)`}
                        {row === "Loose" && `Loose (>${scenarioResult.target_turnaround_minutes} min)`}
                      </td>
                      {PREDECESSOR_COLS.map((col) => {
                        const cell = scenarioCell(row, col);
                        return (
                          <td key={col}>
                            {cell ? (
                              <>
                                <span style={{ color: delayColor(cell.avg_successor_dep_delay), fontWeight: 600 }}>
                                  {cell.avg_successor_dep_delay.toFixed(1)} min
                                </span>
                                <span className="tile-label" style={{ display: "block" }}>
                                  {cell.pairs.toLocaleString()} pairs
                                </span>
                              </>
                            ) : (
                              <span className="tile-label">no data</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="page-note" style={{ marginTop: "1rem" }}>
              Read across a row to see how much a late inbound flight was followed by a late next
              flight. This describes what happened historically; it does not promise what would
              happen if schedules were changed.
            </p>
          </div>
        </section>
      )}

      {tab === "ranking" && rankingResult && (
        <section className="section">
          <div className="section-head">
            <h2 className="section-title">Where each airline has the clearest gap</h2>
            <span className="section-note">{rankingResult.peer_count} carriers</span>
          </div>
          <div className="screen">
            {(() => {
              const verdict = deriveRankingVerdict(rankingResult);
              return verdict ? (
                <div className="decision-verdict">
                  <span className="decision-verdict-label">Reading the ranking</span>
                  {verdict}
                </div>
              ) : null;
            })()}

            {(() => {
              const positiveGainCarriers = rankingResult.carriers.filter(
                (e) => parseFloat(e.top_lever_point_gain.toFixed(1)) > 0
              );
              const budgetOptions: (number | null)[] = [1, 3, 5, null];
              const effectiveBudget = portfolioBudget ?? positiveGainCarriers.length;
              const selected = positiveGainCarriers.slice(0, effectiveBudget);
              const selectedCarrierCodes = new Set(selected.map((e) => e.carrier));
              const totalNetworkFlights = rankingResult.carriers.reduce((sum, e) => sum + e.total_flights, 0);
              const selectedFlights = selected.reduce((sum, e) => sum + e.total_flights, 0);
              const coveragePct = totalNetworkFlights ? (selectedFlights / totalNetworkFlights) * 100 : 0;

              return (
                <>
                  <div style={{ marginTop: "1.5rem" }}>
                    <span className="filter-label" style={{ display: "block", marginBottom: "0.5rem" }}>
                      If you could only focus on a few carriers this cycle, how many?
                    </span>
                    <span className="sort-toggle">
                      {budgetOptions.map((b) => (
                        <button
                          key={b ?? "all"}
                          type="button"
                          className={portfolioBudget === b ? "sort-toggle-active" : ""}
                          onClick={() => setPortfolioBudget(b)}
                        >
                          {b ?? `All ${positiveGainCarriers.length} with a real gap`}
                        </button>
                      ))}
                    </span>
                  </div>

                  {selected.length > 0 ? (
                    <div className="decision-verdict" style={{ marginTop: "1rem" }}>
                      <span className="decision-verdict-label">Portfolio coverage</span>
                      Your top {selected.length} pick{selected.length === 1 ? "" : "s"} by point gain
                      ({selected.map((e) => carrierName(e.carrier)).join(", ")}) collectively touch{" "}
                      <strong>{selectedFlights.toLocaleString()} flights</strong> in this data &mdash;{" "}
                      <strong>{coveragePct.toFixed(1)}%</strong> of the network&apos;s{" "}
                      {totalNetworkFlights.toLocaleString()} total. This is real flight-count coverage,
                      not a combined "priority score" &mdash; point gains from different carriers aren&apos;t
                      on a shared scale, so they aren&apos;t added together here.
                    </div>
                  ) : (
                    <p className="page-note" style={{ marginTop: "1rem" }}>
                      No carrier here has a positive single-component gap against the network median
                      &mdash; there&apos;s nothing this method would recommend focusing on right now.
                    </p>
                  )}

                  <div className="opportunity-leaderboard" style={{ marginTop: "1.25rem" }}>
                    {rankingResult.carriers.map((entry, i) => (
                      <div
                        key={entry.carrier}
                        className={`opportunity-row${selectedCarrierCodes.has(entry.carrier) ? " opportunity-row-selected" : ""}`}
                      >
                        <span className="opportunity-rank">{i + 1}</span>
                        <div className="opportunity-main">
                          <div className="opportunity-carrier">
                            {carrierName(entry.carrier)}
                            <span className="tile-label" style={{ marginLeft: "0.6rem" }}>
                              {entry.current_rating} &middot; score {entry.current_score.toFixed(1)}
                            </span>
                          </div>
                          <div className="page-note" style={{ marginTop: "0.25rem" }}>
                            Largest possible score change: <strong>{COMPONENT_LABELS[entry.top_lever_component] ?? entry.top_lever_component}</strong>{" "}
                            ({entry.top_lever_current_value.toFixed(1)} vs. network typical {entry.top_lever_network_median.toFixed(1)})
                            &mdash; {entry.total_flights.toLocaleString()} flights in this data.
                          </div>
                        </div>
                        {(() => {
                          const rounded = parseFloat(entry.top_lever_point_gain.toFixed(1)) === 0 ? "0.0" : entry.top_lever_point_gain.toFixed(1);
                          const isPositive = parseFloat(rounded) > 0;
                          return (
                            <div className="opportunity-gain" style={{ color: isPositive ? "#4f9d8f" : "#9099a8" }}>
                              {isPositive ? "+" : ""}{rounded}
                              <span className="tile-label" style={{ display: "block", textAlign: "right" }}>possible change</span>
                            </div>
                          );
                        })()}
                      </div>
                    ))}
                  </div>
                </>
              );
            })()}
          </div>
        </section>
      )}

      {tab === "risk" && riskResult && (
        <>
          <section className="section">
            <div className="screen">
              {(() => {
                const bandColor: Record<string, string> = {
                  high: "#c9563a", elevated: "#e8a33d", watch: "#e8a33d", low: "#4f9d8f",
                };
                const color = bandColor[riskResult.risk_band] ?? "#9099a8";
                return (
                  <div style={{ display: "flex", alignItems: "center", gap: "1.5rem" }}>
                    <span style={{ fontFamily: "var(--font-mono), monospace", fontSize: "2.4rem", fontWeight: 700, color }}>
                      {(riskResult.risk_probability * 100).toFixed(0)}%
                    </span>
                    <div>
                      <div style={{ color, fontWeight: 600, textTransform: "capitalize" }}>{riskResult.risk_band} risk</div>
                      <div className="tile-label">
                        {riskEntityType === "carrier" ? carrierName(riskResult.entity) : riskResult.entity}
                        , as of {riskResult.as_of_period}
                      </div>
                    </div>
                  </div>
                );
              })()}

              <p className="page-note" style={{ marginTop: "1rem" }}>{riskResult.risk_threshold_definition}</p>

              <div className="decision-verdict" style={{ marginTop: "1rem" }}>
                <span className="decision-verdict-label">What&apos;s driving this</span>
                {[...riskResult.model_coefficients]
                  .sort((a, b) => Math.abs(b.standardized_coefficient) - Math.abs(a.standardized_coefficient))
                  .slice(0, 3)
                  .map((c, i) => (
                    <span key={c.feature}>
                      {i > 0 && "; "}
                      <strong>{FEATURE_LABELS[c.feature] ?? c.feature}</strong> ({riskResult.current_features[c.feature]?.toFixed(c.feature === "average_departure_delay" ? 1 : 3)})
                      {" "}pushes risk {c.direction === "higher_risk" ? "up" : "down"}
                    </span>
                  ))}
                {" "}&mdash; the three features this model weighted most heavily, in order.
              </div>
            </div>
          </section>

          <section className="section">
            <div className="section-head">
              <h2 className="section-title">How much should I trust this estimate?</h2>
            </div>
            <div className="screen">
              <div className="board board-compact">
                <Tile label="Airlines/airports used" value={`${riskResult.entities_in_training_panel}`} />
                <Tile label="Past examples checked" value={`${riskResult.split.test_examples}`} />
                <Tile label="Test signal (higher is better)" value={riskResult.test_metrics.precision_recall_auc.toFixed(3)} tone={riskResult.test_metrics.precision_recall_auc < 0.55 ? "rust" : undefined} />
                <Tile label="Bad-month rate in test" value={`${(riskResult.test_metrics.positive_rate * 100).toFixed(1)}%`} />
              </div>
              <p className="page-note" style={{ marginTop: "0.75rem" }}>
                The model is checked on later examples it did not see while learning. A higher test
                signal means it separates difficult months better than a random guess. Learning used
                data through {riskResult.split.train_end}; the final check used only later periods.
              </p>

              {riskResult.test_metrics.calibration_bins.length > 0 && (
                <div style={{ marginTop: "1.25rem" }}>
                  <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>
                    Predicted risk compared with what actually happened
                  </p>
                  <table className="compare-table">
                    <thead>
                      <tr><th>Predicted group</th><th>Count</th><th>Average estimate</th><th>Actually observed</th></tr>
                    </thead>
                    <tbody>
                      {riskResult.test_metrics.calibration_bins.map((b) => (
                        <tr key={b.probability_band}>
                          <td>{b.probability_band}</td>
                          <td>{b.count}</td>
                          <td>{(b.mean_predicted_probability * 100).toFixed(1)}%</td>
                          <td>{(b.observed_risk_rate * 100).toFixed(1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="page-note" style={{ marginTop: "0.5rem" }}>
                    If the estimate and the observed result are close, the risk label is behaving
                    sensibly. If they are far apart, treat the label as a rough warning.
                  </p>
                </div>
              )}
            </div>
          </section>
        </>
      )}

      {tab === "bank" && bankResult && (
        <section className="section">
          <div className="screen">
            <div className="board board-compact">
              <Tile label="Busiest period before" value={`${bankResult.original_peak_load} flights`} tone={bankResult.original_peak_load > bankResult.optimized_peak_load ? "rust" : undefined} />
              <Tile label="Busiest period after" value={`${bankResult.optimized_peak_load} flights`} />
              <Tile label="Flights shifted" value={`${bankResult.flights_moved} of ${bankResult.flights_considered}`} />
              <Tile label="Maximum shifts allowed" value={bankResult.max_moved_flights == null ? "None" : String(bankResult.max_moved_flights)} />
              <Tile label="Average shift" value={`${bankResult.average_movement_minutes} min`} />
            </div>

            <div className="decision-verdict" style={{ marginTop: "1rem" }}>
              <span className="decision-verdict-label">What the optimizer suggests</span>
              {bankResult.original_peak_load > bankResult.optimized_peak_load ? (
                <>Under the selected constraints, shifting <strong>{bankResult.flights_moved} flights</strong>
                could reduce the busiest 15-minute period by <strong>{bankResult.original_peak_load - bankResult.optimized_peak_load} flights</strong>.
                This is a schedule experiment to investigate, not a guarantee of certified capacity.</>
              ) : (
                <>The selected shift limits do not reduce the busiest bucket in this window. That is a useful
                result: try a different window or constraint before treating schedule shifting as an intervention.</>
              )}
            </div>

            <p className="page-note" style={{ marginTop: "0.75rem" }}>
              Window {bankResult.window} at {bankResult.airport}{bankResult.carrier ? ` (${bankResult.carrier} only)` : " (all carriers)"}
              , {bankResult.date_range}, {bankResult.mode === "risk_averse" ? "more cautious" : "average-result"} setting.
              Suggested busy-period limit: {bankResult.preferred_bank_limit} flights in 15 minutes
              {bankResult.preferred_bank_limit_was_auto_computed
                ? (bankResult.seasonal_baseline.used
                    ? " (auto-computed from similar past periods)"
                    : " (auto-computed from this window's average load -- no similar past periods available)")
                : " (set by you)"}.
              {bankResult.flight_limit_applied && " Note: the flight count hit the safety cap for this window -- results reflect a truncated sample."}
            </p>

            <div className="decision-verdict" style={{ marginTop: "1rem" }}>
              <span className="decision-verdict-label">Past-year comparison</span>
              <span>
                {" "}{bankResult.seasonal_baseline.note}
                {bankResult.seasonal_baseline.used && (
                  <>
                    {" "}This window is averaging {bankResult.seasonal_baseline.current_window_average_load} flights/bucket
                    vs. a seasonal norm of {bankResult.seasonal_baseline.seasonal_average_load}
                    {bankResult.seasonal_baseline.current_vs_seasonal_pct != null && (
                      <> ({bankResult.seasonal_baseline.current_vs_seasonal_pct > 0 ? "+" : ""}{bankResult.seasonal_baseline.current_vs_seasonal_pct}% vs. normal for this time of year)</>
                    )}.
                  </>
                )}
              </span>
            </div>

            <div className="decision-verdict" style={{ marginTop: "1rem" }}>
              <span className="decision-verdict-label">How the comparison works</span>
              <span> The tool compares this busy period with similar past periods and balances a smaller peak against how far flights have to move.</span>
            </div>

            <div style={{ marginTop: "1.5rem" }}>
              <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Flights in each 15-minute period, before and after</p>
              <table className="compare-table">
                <thead>
                  <tr><th>Time</th><th>Before</th><th>After small shifts</th></tr>
                </thead>
                <tbody>
                  {Array.from(new Set([...Object.keys(bankResult.original_bank_load), ...Object.keys(bankResult.optimized_bank_load)]))
                    .sort()
                    .map((t) => (
                      <tr key={t}>
                        <td>{t}</td>
                        <td>{bankResult.original_bank_load[t] ?? 0}</td>
                        <td>{bankResult.optimized_bank_load[t] ?? 0}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>

            <p className="page-note" style={{ marginTop: "1rem" }}>
              Important: this uses historical flight counts as a congestion signal, not an official airport capacity limit.
            </p>
          </div>
        </section>
      )}

      {tab === "portfolio" && portfolioResult && (
        <section className="section">
          <div className="screen">
            <div className="board board-compact">
              <Tile label="Targets used" value={`${portfolioResult.resource_consumed} / ${portfolioResult.budget}`} />
              <Tile label="Targets selected" value={String(portfolioResult.selected.length)} />
              <Tile label="Other options" value={String(portfolioResult.rejected.length)} />
              <Tile label="Main goal" value={METRIC_LABELS[portfolioResult.primary_metric] ?? portfolioResult.primary_metric} />
              <Tile label="Attention rule" value={COST_MODEL_LABELS[portfolioResult.cost_model] ?? portfolioResult.cost_model} />
            </div>
            <p className="page-note" style={{ marginTop: "0.75rem" }}>
              The tool picks the combination with the most {METRIC_LABELS[portfolioResult.primary_metric] ?? "of the selected measure"}
              while staying within the number of targets you allowed.
            </p>

            <div className="decision-verdict" style={{ marginTop: "1rem" }}>
              <span className="decision-verdict-label">What this gives you</span>
              {portfolioResult.selected.length > 0 ? (
                <>A short list of <strong>{portfolioResult.selected.length} target{portfolioResult.selected.length === 1 ? "" : "s"}</strong>
                that best fit the selected budget and objective. Use it to decide where to look first;
                the historical metrics do not predict the size of an intervention&apos;s effect.</>
              ) : (
                <>No candidate fits the current budget and constraints. Increase the budget or change the
                objective to see a different feasible shortlist.</>
              )}
            </div>

            <div style={{ marginTop: "1.5rem" }}>
              <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Suggested focus areas</p>
              {portfolioResult.selected.map((s: any) => (
                <div key={s.candidate_id} className="decision-verdict" style={{ marginBottom: "0.6rem" }}>
                  <span className="decision-verdict-label">
                    Focus on {s.candidate_type === "carrier" ? carrierName(s.candidate_id) : s.candidate_id}
                  </span>
                  <span>{s.reason}</span>
                </div>
              ))}
            </div>

            <div style={{ marginTop: "1.5rem" }}>
              <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Other measures for these focus areas</p>
              <table className="compare-table">
                <thead><tr><th>Measure</th><th>Selected targets</th><th>Targets not selected</th></tr></thead>
                <tbody>
                  {Object.keys(portfolioResult.total_coverage).map((k) => (
                    <tr key={k}>
                      <td>{k}</td>
                      <td>{portfolioResult.total_coverage[k]}</td>
                      <td>{portfolioResult.residual_exposure[k] ?? "\u2014"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {portfolioResult.rejected.length > 0 && (
              <div style={{ marginTop: "1.5rem" }}>
                <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Other options</p>
                <table className="compare-table">
                  <thead><tr><th>Candidate</th><th>Reason</th></tr></thead>
                  <tbody>
                    {portfolioResult.rejected.map((r: any) => (
                      <tr key={r.candidate_id}>
                        <td>{r.candidate_type === "carrier" ? carrierName(r.candidate_id) : r.candidate_id}</td>
                        <td>{r.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <p className="page-note" style={{ marginTop: "1rem" }}>
              This is a shortlist based on historical measures. It does not guarantee the size of an intervention&apos;s effect.
            </p>
          </div>
        </section>
      )}

      {tab === "resilience" && resilienceResult && (
        <section className="section">
          <div className="screen">
            <div className="board board-compact">
              <Tile label="Airports included" value={String(resilienceResult.scope.airport_count)} />
              <Tile label="Routes included" value={String(resilienceResult.scope.route_count)} />
              <Tile label="Minimum route size" value={String(resilienceResult.scope.minimum_flights_per_route)} />
            </div>

            {resilienceResult.betweenness_centrality.top_structural_bridges[0] && (
              <div className="decision-verdict" style={{ marginTop: "1rem" }}>
                <span className="decision-verdict-label">What this reveals</span>
                <strong>{resilienceResult.betweenness_centrality.top_structural_bridges[0].airport}</strong> is the
                top connector in this view. This is different from busiest: it highlights an airport that links
                otherwise separate parts of the network.
              </div>
            )}

            <div style={{ marginTop: "1.5rem" }}>
              <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>
                Airports that connect different parts of the network
              </p>
              <table className="compare-table">
                <thead><tr><th>Airport</th><th>Connection score</th></tr></thead>
                <tbody>
                  {resilienceResult.betweenness_centrality.top_structural_bridges.map((e) => (
                    <tr key={e.airport}><td>{e.airport}</td><td>{e.value}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ marginTop: "1.5rem", display: "flex", gap: "2rem", flexWrap: "wrap" }}>
              <div style={{ flex: "1 1 300px" }}>
                <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Top by route count</p>
                <table className="compare-table">
                  <thead><tr><th>Airport</th><th>Routes</th></tr></thead>
                  <tbody>
                    {resilienceResult.degree_centrality.top_by_route_count.map((e) => (
                      <tr key={e.airport}><td>{e.airport}</td><td>{e.value}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ flex: "1 1 300px" }}>
                <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Top by flight volume</p>
                <table className="compare-table">
                  <thead><tr><th>Airport</th><th>Flights</th></tr></thead>
                  <tbody>
                    {resilienceResult.degree_centrality.top_by_flight_volume.map((e) => (
                      <tr key={e.airport}><td>{e.airport}</td><td>{e.value.toLocaleString()}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <p className="page-note" style={{ marginTop: "1rem" }}>{resilienceResult.methodology.combination_policy}</p>
          </div>
        </section>
      )}

      {tab === "capacity" && capacityResult && (
        <section className="section">
          <div className="section-head">
            <h2 className="section-title">T-100 traffic beside on-time performance</h2>
            <span className="section-note">matched route-months</span>
          </div>
          <div className="screen">
            <div className="board board-compact">
              <Tile label="Matched route-months" value={capacityResult.overview.matched_route_months.toLocaleString()} />
              <Tile label="Average seats filled" value={formatPercent(capacityResult.overview.average_load_factor)} />
              <Tile label="Average on-time rate" value={formatPercent(capacityResult.overview.average_on_time_rate)} />
              <Tile label="Traffic relationship" value={formatCorrelation(capacityResult.overview.correlation_load_factor_on_time)} />
            </div>

            <p className="page-note" style={{ marginTop: "1rem" }}>
              <strong>Simple read:</strong> {describeCapacityRelationship(capacityResult.overview.correlation_load_factor_on_time)}
              This is a clue to investigate, not proof that fuller flights cause delays.
            </p>
            <p className="page-note" style={{ marginTop: "0.5rem" }}>
              Passengers relationship: <strong>{formatCorrelation(capacityResult.overview.correlation_passengers_on_time)}</strong>
              {" · "}Seats relationship: <strong>{formatCorrelation(capacityResult.overview.correlation_seats_on_time)}</strong>
            </p>

            {capacityResult.rows.length > 0 ? (
              <div className="rotation-table-wrap" style={{ marginTop: "1.25rem" }}>
                <table className="compare-table">
                  <thead>
                    <tr>
                      <th>Month</th><th>Route</th><th>Flights compared</th><th>Seats</th>
                      <th>Passengers</th><th>Seats filled</th><th>On-time</th><th>Avg delay</th>
                    </tr>
                  </thead>
                  <tbody>
                    {capacityResult.rows.map((row) => (
                      <tr key={`${row.year}-${row.month}-${row.carrier}-${row.origin}-${row.dest}`}>
                        <td>{`${row.year}-${String(row.month).padStart(2, "0")}`}</td>
                        <td>{row.origin} → {row.dest}</td>
                        <td>{row.otp_flights.toLocaleString()}</td>
                        <td>{row.seats_available.toLocaleString()}</td>
                        <td>{row.passengers.toLocaleString()}</td>
                        <td>{formatPercent(row.load_factor)}</td>
                        <td>{formatPercent(row.on_time_rate)}</td>
                        <td>{row.avg_arrival_delay == null ? "—" : `${row.avg_arrival_delay.toFixed(1)} min`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="page-note">No route-months matched both datasets at the selected evidence threshold.</p>
            )}

            <p className="page-note" style={{ marginTop: "1rem" }}>
              {capacityResult.source}. {capacityResult.methodology.join_policy}
            </p>
          </div>
        </section>
      )}
    </main>
  );
}

function formatPercent(value: number | null, digits = 1): string {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function formatCorrelation(value: number | null): string {
  return value == null ? "—" : value.toFixed(2);
}

function describeCapacityRelationship(value: number | null): string {
  if (value == null) return "There is not enough matched data to describe a traffic relationship yet. ";
  const magnitude = Math.abs(value);
  if (magnitude < 0.1) return "Traffic and on-time performance barely move together in this snapshot. ";
  if (value < 0) return "Fuller flights tend to be on time slightly less often in this snapshot. ";
  return "Fuller flights tend to be on time slightly more often in this snapshot. ";
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: "rust" }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={`tile-value ${tone === "rust" ? "rust" : ""}`}>{value}</span>
    </div>
  );
}
