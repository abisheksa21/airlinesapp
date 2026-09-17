"use client";

import { useState, useEffect, useRef, Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import DateRangePreset from "../../components/DateRangePreset";
import HealthBadge from "../../components/HealthBadge";
import TrendChart from "../../components/TrendChart";
import DelayCauseChart from "../../components/DelayCauseChart";
import RouteChart from "../../components/RouteChart";
import TimeOfDayChart from "../../components/TimeOfDayChart";
import TurnbackSummary from "../../components/TurnbackSummary";
import ReferencePanel from "../../components/ReferencePanel";
import { airportDisplayName } from "../../lib/airports";
import { getAirportReference } from "../../lib/reference-profiles";
import { useMode } from "../../lib/mode";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

function buildQuery(params: Record<string, string>): string {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v) usp.set(k, v);
  });
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

function scoreColor(score: number): string {
  if (score >= 80) return "#4f9d8f";
  if (score >= 65) return "#e8a33d";
  return "#c9563a";
}

const RESEARCHER_TABS = ["Health Score", "Trend", "Time & Turnbacks", "Routes"] as const;
type ResearcherTab = (typeof RESEARCHER_TABS)[number];
const PUBLIC_TABS = ["Overview", "About", "Performance"] as const;
type PublicTab = (typeof PUBLIC_TABS)[number];

export default function AirportProfilePage() {
  return (
    <Suspense fallback={null}>
      <AirportProfilePageInner />
    </Suspense>
  );
}

function AirportProfilePageInner() {
  const params = useParams();
  const searchParams = useSearchParams();
  const code = String(params.code ?? "").toUpperCase();
  const { mode, setMode } = useMode();

  const [startDate, setStartDate] = useState(() => searchParams.get("start") ?? "");
  const [endDate, setEndDate] = useState(() => searchParams.get("end") ?? "");
  const [detail, setDetail] = useState<any>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState(false);

  const [timeOfDay, setTimeOfDay] = useState<any>(null);
  const [turnback, setTurnback] = useState<any>(null);
  const [tab, setTab] = useState<ResearcherTab>("Health Score");
  const [publicTab, setPublicTab] = useState<PublicTab>("Overview");

  const loadTokenRef = useRef(0);

  async function load() {
    if (!code) return;
    const token = ++loadTokenRef.current;
    setNotFound(false);
    setError(false);
    try {
      const qs = buildQuery({
        airport: code,
        start_date: startDate,
        end_date: endDate,
        summary_only: mode === "public" ? "true" : "",
      });
      const res = await fetch(`${API_BASE}/api/airport-detail${qs}`);
      if (token !== loadTokenRef.current) return;
      if (res.status === 404) {
        setDetail(null);
        setNotFound(true);
        return;
      }
      if (!res.ok) throw new Error("not ok");
      const data = await res.json();
      if (token !== loadTokenRef.current) return;
      setDetail(data);

      if (mode === "researcher") {
        await Promise.all([
          (async () => {
            try {
              const todRes = await fetch(`${API_BASE}/api/time-of-day${qs}`);
              if (token !== loadTokenRef.current) return;
              setTimeOfDay(todRes.ok ? (await todRes.json()).hours ?? null : null);
            } catch {
              if (token === loadTokenRef.current) setTimeOfDay(null);
            }
          })(),
          (async () => {
            try {
              const tbRes = await fetch(`${API_BASE}/api/turnbacks${qs}`);
              if (token !== loadTokenRef.current) return;
              setTurnback(tbRes.ok ? await tbRes.json() : null);
            } catch {
              if (token === loadTokenRef.current) setTurnback(null);
            }
          })(),
        ]);
      }
    } catch {
      if (token === loadTokenRef.current) setError(true);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, startDate, endDate, mode]);

  const hadCarriedParams = useRef(Boolean(searchParams.get("start") || searchParams.get("end")));
  const previousModeRef = useRef<string | null>(null);
  useEffect(() => {
    const isGenuineSwitch = previousModeRef.current === "public" && mode === "researcher";
    if (isGenuineSwitch && !hadCarriedParams.current) {
      setStartDate("");
      setEndDate("");
    }
    previousModeRef.current = mode;
  }, [mode]);

  useEffect(() => {
    if ((searchParams.get("start") || searchParams.get("end")) && mode === "public") {
      setMode("researcher");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const displayName = airportDisplayName(code, detail?.city, detail?.state);
  const reference = getAirportReference(code, detail?.city, detail?.state);

  return (
    <main className={`page entity-profile-page ${mode === "researcher" ? "entity-profile-researcher" : "entity-profile-public"}`}>
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; Airport Profile</p>
        <h1 className="title">{displayName}</h1>
        <div className="profile-actions">
          <Link href="/airports" className="profile-action-button">&larr; Back to airport rankings and search</Link>
          <Link href={`/compare?mode=airport&entity=${code}`} className="profile-action-button">Compare {code} with another airport &rarr;</Link>
        </div>
      </header>

      {notFound && <p className="error-text">No flights found for {code} in that range.</p>}
      {error && <p className="error-text">Could not load this profile &mdash; check the API is running.</p>}
      {!detail && !notFound && !error && (mode === "researcher" || publicTab !== "About") && (
        <p className="profile-page-loading" role="status" aria-live="polite">
          <span className="loading-pulse" /> Loading measured performance for {code}…
        </p>
      )}

      {mode === "public" && (
        <section className="section">
          <div className="public-profile-shell">
            <div className="public-profile-tabs" role="tablist" aria-label="Public airport profile sections">
              {PUBLIC_TABS.map((item) => <button key={item} type="button" role="tab" aria-selected={publicTab === item} className={publicTab === item ? "active" : ""} onClick={() => setPublicTab(item)}>{item}</button>)}
            </div>

            {publicTab === "About" && <ReferencePanel profile={reference} />}

            {publicTab !== "About" && !detail && <div className="profile-data-loading"><span className="loading-pulse" /> Loading measured performance for {code}…<small>The reference profile is already available in the About tab.</small></div>}

            {publicTab !== "About" && detail && <>
              <div className="public-profile-lede">
                <p className="eyebrow">{publicTab === "Overview" ? "Plain-language read" : "Performance read"}</p>
                <h2>{publicTab === "Overview" ? `${displayName} in one minute` : `How ${code} is performing`}</h2>
                <p>{publicTab === "Overview" ? `${detail.city && detail.state ? `${detail.city}, ${detail.state}` : `${displayName} is identified here by IATA code ${code}`}. This page shows how flights moved through the airport in the BTS record.` : "These numbers are calculated from the BTS warehouse for this airport and the full available history."}</p>
              </div>

            <div className="board">
              <div className="tile">
                <span className="tile-label">Total flights</span>
                <span className="tile-value">{detail.total_flights.toLocaleString()}</span>
              </div>
              <div className="tile">
                <span className="tile-label">On-time rate</span>
                <span className="tile-value">{(detail.on_time_rate * 100).toFixed(1)}%</span>
              </div>
              <div className="tile">
                <span className="tile-label">Avg arrival delay</span>
                <span className="tile-value rust">
                  {detail.avg_arrival_delay_minutes != null ? `${detail.avg_arrival_delay_minutes.toFixed(1)} min` : "\u2014"}
                </span>
              </div>
              <div className="tile">
                <span className="tile-label">Cancellation rate</span>
                <span className="tile-value rust">{(detail.cancellation_rate * 100).toFixed(2)}%</span>
              </div>
            </div>

            {detail.health && (
              <div style={{ display: "flex", alignItems: "center", gap: "1.5rem", marginTop: "1.5rem" }}>
                <span style={{ fontFamily: "var(--font-mono), monospace", fontSize: "2.4rem", fontWeight: 700, color: scoreColor(detail.health.score) }}>
                  {Math.round(detail.health.score)}
                </span>
                <p style={{ margin: 0 }}>
                  Rated <strong style={{ color: scoreColor(detail.health.score) }}>{detail.health.rating}</strong>{" "}
                  overall{" "}
                  &mdash; on-time {(detail.on_time_rate * 100).toFixed(0)}% of the time, cancelling {(detail.cancellation_rate * 100).toFixed(1)}% of flights.
                </p>
              </div>
            )}

            {publicTab === "Performance" && detail.months?.length > 0 && <div className="public-profile-chart"><TrendChart data={detail.months} /></div>}
            <div className="public-profile-action-row">
              <button type="button" className="profile-action-button" onClick={() => setMode("researcher")}>Open researcher workspace →</button>
              <span className="page-note">Trend, causes, time of day, turnbacks, and routes live there.</span>
            </div>
            </>}
          </div>
        </section>
      )}

      {detail && mode === "researcher" && (
        <>
          <section className="section">
            <div className="screen">
              <DateRangePreset
                key={mode}
                startDate={startDate}
                endDate={endDate}
                onChange={(start, end) => { setStartDate(start); setEndDate(end); }}
              />
            </div>
          </section>

          <div className="profile-layout">
            <aside className="profile-facts">
              {detail.health && (
                <div className="profile-facts-health">
                  <span className="profile-facts-score" style={{ color: scoreColor(detail.health.score) }}>
                    {Math.round(detail.health.score)}
                  </span>
                  <span className="tile-value" style={{ color: scoreColor(detail.health.score), fontSize: "0.9rem" }}>
                    {detail.health.rating}
                  </span>
                  <span className="tile-label">Health score</span>
                </div>
              )}
              <dl className="profile-facts-list">
                <div>
                  <dt>Location</dt>
                  <dd>{detail.city && detail.state ? `${detail.city}, ${detail.state}` : "Unavailable"}</dd>
                </div>
                <div>
                  <dt>IATA code</dt>
                  <dd>{code}</dd>
                </div>
                <div>
                  <dt>Total flights</dt>
                  <dd>{detail.total_flights.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>On-time rate</dt>
                  <dd>{(detail.on_time_rate * 100).toFixed(1)}%</dd>
                </div>
                <div>
                  <dt>Avg arrival delay</dt>
                  <dd>{detail.avg_arrival_delay_minutes != null ? `${detail.avg_arrival_delay_minutes.toFixed(1)} min` : "\u2014"}</dd>
                </div>
                <div>
                  <dt>Cancellation rate</dt>
                  <dd>{(detail.cancellation_rate * 100).toFixed(2)}%</dd>
                </div>
                <div>
                  <dt>Outbound on-time</dt>
                  <dd>{detail.outbound?.on_time_rate != null ? `${(detail.outbound.on_time_rate * 100).toFixed(1)}%` : "\u2014"}</dd>
                </div>
                <div>
                  <dt>Inbound on-time</dt>
                  <dd>{detail.inbound?.on_time_rate != null ? `${(detail.inbound.on_time_rate * 100).toFixed(1)}%` : "\u2014"}</dd>
                </div>
              </dl>
            </aside>

            <div className="profile-content">
              <div className="sort-toggle" style={{ marginBottom: "1rem" }}>
                {RESEARCHER_TABS.map((t) => (
                  <button
                    key={t}
                    type="button"
                    className={tab === t ? "sort-toggle-active" : ""}
                    onClick={() => setTab(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>

              {tab === "Health Score" && detail.health && (
                <section className="section" style={{ marginTop: 0 }}>
                  <div className="screen">
                    <HealthBadge health={detail.health} />
                  </div>
                </section>
              )}

              {tab === "Trend" && detail.months?.length > 0 && (
                <section className="section" style={{ marginTop: 0 }}>
                  <div className="screen">
                    <TrendChart data={detail.months} />
                  </div>
                </section>
              )}

              {tab === "Time & Turnbacks" && (
                <>
                  {detail.causes?.length > 0 && (
                    <section className="section" style={{ marginTop: 0 }}>
                      <div className="section-head">
                        <h2 className="section-title">Delay causes</h2>
                      </div>
                      <div className="screen">
                        <DelayCauseChart data={detail.causes} />
                      </div>
                    </section>
                  )}
                  {timeOfDay?.length > 0 && (
                    <section className="section">
                      <div className="section-head">
                        <h2 className="section-title">What time of day should you fly?</h2>
                      </div>
                      <div className="screen">
                        <p className="page-note" style={{ marginBottom: "0.75rem" }}>
                          On-time rate by scheduled departure hour &mdash; departures from this
                          airport only. Low-volume hours (e.g. overnight) can be noisy with fewer
                          flights behind them.
                        </p>
                        <TimeOfDayChart data={timeOfDay} />
                      </div>
                    </section>
                  )}
                  {turnback && (
                    <section className="section">
                      <div className="section-head">
                        <h2 className="section-title">Gate returns and turnbacks</h2>
                      </div>
                      <div className="screen">
                        <p className="page-note" style={{ marginBottom: "0.75rem" }}>
                          A turnback is a flight that pushed back from the gate, then returned
                          before actually departing. Based on flights <strong>departing</strong>{" "}
                          this airport only.
                        </p>
                        <TurnbackSummary data={turnback} />
                      </div>
                    </section>
                  )}
                </>
              )}

              {tab === "Routes" && detail.top_routes?.length > 0 && (
                <section className="section" style={{ marginTop: 0 }}>
                  <div className="section-head">
                    <h2 className="section-title">Busiest routes through {code}</h2>
                  </div>
                  <div className="screen">
                    <RouteChart data={detail.top_routes} />
                  </div>
                </section>
              )}
            </div>
          </div>
        </>
      )}
    </main>
  );
}
