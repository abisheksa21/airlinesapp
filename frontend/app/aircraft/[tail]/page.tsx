"use client";

import { useState, useEffect, useRef, Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import DateRangePreset from "../../components/DateRangePreset";
import HealthBadge from "../../components/HealthBadge";
import TrendChart from "../../components/TrendChart";
import DelayCauseChart from "../../components/DelayCauseChart";
import RouteChart from "../../components/RouteChart";
import { carrierName } from "../../lib/carriers";
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

const RESEARCHER_TABS = ["Health Score", "Trend", "Delays & Carriers", "Routes"] as const;
type ResearcherTab = (typeof RESEARCHER_TABS)[number];

export default function AircraftProfilePage() {
  return (
    <Suspense fallback={null}>
      <AircraftProfilePageInner />
    </Suspense>
  );
}

function AircraftProfilePageInner() {
  const params = useParams();
  const searchParams = useSearchParams();
  const tail = String(params.tail ?? "").toUpperCase();
  const { mode, setMode } = useMode();

  const [startDate, setStartDate] = useState(() => searchParams.get("start") ?? "");
  const [endDate, setEndDate] = useState(() => searchParams.get("end") ?? "");
  const [detail, setDetail] = useState<any>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<ResearcherTab>("Health Score");

  const loadTokenRef = useRef(0);

  async function load() {
    if (!tail) return;
    const token = ++loadTokenRef.current;
    setNotFound(false);
    setError(false);
    try {
      const qs = buildQuery({ tail, start_date: startDate, end_date: endDate });
      const res = await fetch(`${API_BASE}/api/aircraft-detail${qs}`);
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
    } catch {
      if (token === loadTokenRef.current) setError(true);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tail, startDate, endDate]);

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

  return (
    <main className="page">
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; Aircraft Profile</p>
        <h1 className="title">{tail}</h1>
        <div className="profile-actions">
          <Link href="/aircraft" className="profile-action-button">&larr; Back to aircraft search</Link>
          <Link href={`/compare?mode=aircraft&entity=${tail}`} className="profile-action-button">Compare {tail} with another tail &rarr;</Link>
        </div>
      </header>

      {notFound && <p className="error-text">No flights found for {tail} in that range.</p>}
      {error && <p className="error-text">Could not load this profile &mdash; check the API is running.</p>}
      {!detail && !notFound && !error && <p className="error-text">Loading...</p>}

      {detail && mode === "public" && (
        <section className="section">
          <div className="screen">
            <p className="page-note" style={{ marginBottom: "1rem" }}>
              {detail.known_aircraft_type
                ? `Known type: ${detail.known_aircraft_type}`
                : "Aircraft type unknown for this tail"}
              {" "}&middot; Observed {detail.first_flight} to {detail.last_flight}
            </p>

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

            <p className="page-note" style={{ marginTop: "1.5rem" }}>
              Want the full breakdown &mdash; trend over time, delay causes, operating carriers,
              routes flown?
            </p>
            <button
              type="button"
              className="profile-action-button"
              style={{ marginTop: "0.6rem" }}
              onClick={() => setMode("researcher")}
            >
              Switch to Researcher mode
            </button>
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
                  <dt>Known type</dt>
                  <dd>
                    {detail.known_aircraft_type ?? "Unknown"}
                    {!detail.known_aircraft_type && (
                      <>
                        {" "}
                        <span className="page-note" style={{ display: "block", marginTop: "0.25rem" }}>
                          BTS on-time data has no fleet-type field &mdash; type is only known for
                          the 72 tails in the{" "}
                          <Link href="/max-grounding">737 MAX grounding study</Link>.
                        </span>
                      </>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Observed</dt>
                  <dd>{detail.first_flight} to {detail.last_flight}</dd>
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
              </dl>
              <p className="page-note">
                Wording is &ldquo;observed&rdquo; deliberately &mdash; BTS flight records
                aren&apos;t a complete fleet/ownership registry.
              </p>
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

              {tab === "Delays & Carriers" && (
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
                  {detail.carriers?.length > 0 && (
                    <section className="section">
                      <div className="section-head">
                        <h2 className="section-title">Carriers observed operating this tail</h2>
                      </div>
                      <div className="screen">
                        <table className="compare-table">
                          <thead>
                            <tr><th>Carrier</th><th>Flights</th></tr>
                          </thead>
                          <tbody>
                            {detail.carriers.map((c: any) => (
                              <tr key={c.carrier}>
                                <td>{carrierName(c.carrier)}</td>
                                <td>{c.total_flights.toLocaleString()}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  )}
                </>
              )}

              {tab === "Routes" && detail.top_routes?.length > 0 && (
                <section className="section" style={{ marginTop: 0 }}>
                  <div className="section-head">
                    <h2 className="section-title">Routes flown</h2>
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
