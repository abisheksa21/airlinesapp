"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { formatNumber } from "../lib/format";
import AircraftChart from "../components/AircraftChart";
import { Health } from "../lib/health";
import DateRangePreset from "../components/DateRangePreset";
import TrendChart from "../components/TrendChart";
import DelayCauseChart from "../components/DelayCauseChart";
import RouteChart from "../components/RouteChart";
import HealthBadge from "../components/HealthBadge";
import TailSearchInput from "../components/TailSearchInput";
import DelayPropagationSummary from "../components/DelayPropagationSummary";
import AircraftRotationTimeline from "../components/AircraftRotationTimeline";
import { CARRIER_NAMES, carrierName } from "../lib/carriers";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Aircraft = { tail: string; total_flights: number; on_time_rate: number };
type MonthPoint = { month: string; total_flights: number; on_time_rate: number };
type Cause = { cause: string; minutes: number; share: number };
type Route = { route: string; total_flights: number; on_time_rate: number };
type Carrier = { carrier: string; total_flights: number };

type AircraftDetail = {
  tail: string;
  total_flights: number;
  first_flight: string;
  last_flight: string;
  carrier_count: number;
  on_time_rate: number;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number;
  health: Health | null;
  carriers: Carrier[];
  months: MonthPoint[];
  causes: Cause[];
  top_routes: Route[];
};

function buildQuery(params: Record<string, string>): string {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v) usp.set(k, v);
  });
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

export default function AircraftPage() {
  const [ranking, setRanking] = useState<{ aircraft: Aircraft[] } | null>(null);

  const [tailInput, setTailInput] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const [detail, setDetail] = useState<AircraftDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const [rotationDate, setRotationDate] = useState("");
  const [rotation, setRotation] = useState<any>(null);
  const [rotationLoading, setRotationLoading] = useState(false);
  const [rotationNotFound, setRotationNotFound] = useState(false);

  const [propagationCarrier, setPropagationCarrier] = useState("");
  const [propagation, setPropagation] = useState<any>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/aircraft`)
      .then((r) => r.json())
      .then(setRanking)
      .catch(() => setRanking(null));

    fetchPropagation("");
  }, []);

  async function fetchPropagation(carrier: string) {
    const qs = buildQuery({ carrier });
    try {
      const res = await fetch(`${API_BASE}/api/delay-propagation${qs}`);
      setPropagation(res.ok ? await res.json() : null);
    } catch {
      setPropagation(null);
    }
  }

  async function lookupAircraft() {
    const tail = tailInput.trim();
    if (!tail) return;
    setLoading(true);
    setNotFound(false);
    const qs = buildQuery({ tail, start_date: startDate, end_date: endDate });
    try {
      const res = await fetch(`${API_BASE}/api/aircraft-detail${qs}`);
      if (res.status === 404) {
        setDetail(null);
        setNotFound(true);
        return;
      }
      const found = await res.json();
      setDetail(found);
      setRotationDate(found.last_flight ?? "");
      setRotation(null);
      setRotationNotFound(false);
    } catch {
      setNotFound(true);
    } finally {
      setLoading(false);
    }
  }

  async function lookupRotation() {
    const tail = tailInput.trim();
    if (!tail || !rotationDate) return;
    setRotationLoading(true);
    setRotationNotFound(false);
    try {
      const res = await fetch(`${API_BASE}/api/aircraft-rotation${buildQuery({ tail, date: rotationDate })}`);
      if (res.status === 404) {
        setRotation(null);
        setRotationNotFound(true);
        return;
      }
      setRotation(await res.json());
    } catch {
      setRotationNotFound(true);
    } finally {
      setRotationLoading(false);
    }
  }

  return (
    <main className="page">
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; Aircraft</p>
        <h1 className="title">Aircraft</h1>
        <p className="subtitle">
          Busiest tails by flight volume, or look up any specific tail number and date range.
        </p>
      </header>

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Busiest aircraft</h2>
          <span className="section-note">Top 15 by total flight volume, bar color = on-time rate</span>
        </div>
        <div className="screen">
          {ranking ? <AircraftChart data={ranking.aircraft} /> : <p className="error-text">Loading...</p>}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Does delay carry over between flights?</h2>
          <span className="section-note">Same-tail, same-day rotations &mdash; live-computed, not a pre-set score</span>
        </div>
        <div className="screen">
          <p className="page-note" style={{ marginBottom: "1rem" }}>
            When an aircraft lands late, does its <em>next</em> flight inherit that delay? This
            sequences each tail&apos;s flights within a calendar day by scheduled departure and
            compares each flight&apos;s departure delay against its immediate predecessor&apos;s
            arrival delay on the same tail. The turnaround-tightness breakdown below was checked
            directly across all 11 carriers, not assumed: propagation is consistently{" "}
            <strong>weakest on tight turnarounds</strong> (&le;25 min) and{" "}
            <strong>strongest on normal ones</strong> (26&ndash;45 min) &mdash; the opposite of
            the original prediction that less buffer should mean more propagation. See below for
            why.
          </p>
          <label className="filter-field" style={{ marginBottom: "1rem", maxWidth: 260 }}>
            <span className="filter-label">Carrier</span>
            <select
              value={propagationCarrier}
              onChange={(e) => {
                setPropagationCarrier(e.target.value);
                fetchPropagation(e.target.value);
              }}
            >
              <option value="">All carriers</option>
              {Object.keys(CARRIER_NAMES).map((code) => (
                <option key={code} value={code}>
                  {code} &mdash; {carrierName(code)}
                </option>
              ))}
            </select>
          </label>
          {propagation ? (
            <DelayPropagationSummary data={propagation} />
          ) : (
            <p className="error-text">Loading...</p>
          )}

          <details className="health-methodology" style={{ marginTop: "1.5rem" }}>
            <summary>Why is propagation weakest on the tightest turnarounds?</summary>
            <div className="health-methodology-body">
              <p>
                The original prediction was that less schedule buffer should mean more
                propagation &mdash; a tight turnaround has less time to absorb a late inbound.
                Checked directly across all 11 carriers, the opposite showed up: normal
                turnarounds have the strongest correlation for every single carrier, tight
                turnarounds are the weakest &mdash; often near zero or negative &mdash; for 9 of
                the 11, and loose turnarounds sit in between.
              </p>
              <p>
                A plausible explanation, not a confirmed one: airlines likely don&apos;t schedule
                a &le;25-minute turnaround at random. They reserve it for route/aircraft
                combinations they&apos;re confident can reliably execute that fast, so the
                &ldquo;tight&rdquo; bucket isn&apos;t a random sample of risky, undersized
                buffers &mdash; it&apos;s a selected sample of especially well-drilled turns,
                engineered to absorb a somewhat-late inbound almost regardless. Normal
                turnarounds are the genuinely ambiguous middle ground, which is where predecessor
                delay would be expected to bite hardest. Southwest is the one carrier where even
                its tight bucket still shows real propagation (0.426, well above every other
                carrier&apos;s tight-bucket number) &mdash; consistent with fast, standardized
                turns being its operating norm rather than the exception, so its &ldquo;tight&rdquo;
                bucket may be less selectively safe than other carriers&apos;.
              </p>
              <p>Correlation by carrier and turnaround tightness, checked directly:</p>
              <div className="rotation-table-wrap">
                <table className="compare-table rotation-table">
                  <thead>
                    <tr>
                      <th>Carrier</th>
                      <th>Tight (&le;25 min)</th>
                      <th>Normal (26&ndash;45 min)</th>
                      <th>Loose (&gt;45 min)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      { code: "AA", tight: 0.160, normal: 0.526, loose: 0.376 },
                      { code: "DL", tight: 0.104, normal: 0.603, loose: 0.429 },
                      { code: "UA", tight: 0.137, normal: 0.511, loose: 0.424 },
                      { code: "WN", tight: 0.426, normal: 0.793, loose: 0.637 },
                      { code: "AS", tight: 0.083, normal: 0.737, loose: 0.551 },
                      { code: "B6", tight: 0.246, normal: 0.737, loose: 0.580 },
                      { code: "NK", tight: -0.094, normal: 0.708, loose: 0.598 },
                      { code: "F9", tight: -0.088, normal: 0.700, loose: 0.557 },
                      { code: "G4", tight: -0.189, normal: 0.649, loose: 0.451 },
                      { code: "HA", tight: 0.342, normal: 0.679, loose: 0.485 },
                      { code: "VX", tight: -0.037, normal: 0.732, loose: 0.520 },
                    ].map((row) => (
                      <tr key={row.code}>
                        <td>{row.code} &mdash; {carrierName(row.code)}</td>
                        <td>{row.tight.toFixed(3)}</td>
                        <td>{row.normal.toFixed(3)}</td>
                        <td>{row.loose.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </details>
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Look up an aircraft</h2>
          <span className="section-note">Start typing a tail number to search</span>
        </div>
        <div className="screen">
          <div className="route-lookup-row">
            <TailSearchInput value={tailInput} onChange={setTailInput} />
            <DateRangePreset
              startDate={startDate}
              endDate={endDate}
              onChange={(start, end) => { setStartDate(start); setEndDate(end); }}
            />
            <button
              type="button"
              className="compare-run"
              onClick={lookupAircraft}
              disabled={!tailInput.trim() || loading}
            >
              {loading ? "Looking up..." : "Look up"}
            </button>
          </div>

          {notFound && !loading && (
            <p className="error-text" style={{ marginTop: "1rem" }}>
              No flights found for that tail number/date range. Tail numbers are case-sensitive
              as recorded by BTS &mdash; try the exact registration, e.g. N123SW.
            </p>
          )}

          {detail && !notFound && (
            <div className="route-detail">
              <p className="page-note" style={{ marginTop: "1.5rem" }}>
                Observed {detail.first_flight} to {detail.last_flight}
                {detail.carrier_count > 1 ? ` \u00b7 flown by ${detail.carrier_count} carriers` : ""}
                {" "}&mdash; wording is &ldquo;observed&rdquo; deliberately, since BTS flight records
                aren&apos;t a complete fleet/ownership registry.
              </p>

              <p className="page-note" style={{ marginBottom: "0.5rem" }}>
                {(() => {
                  const params = new URLSearchParams();
                  if (startDate) params.set("start", startDate);
                  if (endDate) params.set("end", endDate);
                  const qs = params.toString();
                  return (
                    <Link
                      href={`/aircraft/${tailInput}${qs ? `?${qs}` : ""}`}
                      className="profile-action-button"
                    >
                      View {tailInput}&apos;s full profile &rarr;
                    </Link>
                  );
                })()}
              </p>
              {(startDate || endDate) && (
                <p className="page-note" style={{ marginBottom: "0.5rem" }}>
                  Carries this exact date range over automatically.
                </p>
              )}

              <div className="board board-compact" style={{ marginTop: "1rem" }}>
                <Tile label="Total flights" value={detail.total_flights.toLocaleString()} />
                <Tile label="On-time rate" value={`${(detail.on_time_rate * 100).toFixed(1)}%`} />
                <Tile label="Avg arrival delay" value={`${formatNumber(detail.avg_arrival_delay_minutes)} min`} tone="rust" />
                <Tile label="Cancellation rate" value={`${(detail.cancellation_rate * 100).toFixed(2)}%`} tone="rust" />
              </div>

              <HealthBadge health={detail.health} />

              {detail.months.length > 0 && (
                <div style={{ marginTop: "1.5rem" }}>
                  <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>On-time rate over time</p>
                  <TrendChart data={detail.months} />
                </div>
              )}

              <div className="route-detail-grid">
                <div>
                  <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Delay causes</p>
                  <DelayCauseChart data={detail.causes} />
                </div>
                {detail.top_routes.length > 0 && (
                  <div>
                    <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Routes flown</p>
                    <RouteChart data={detail.top_routes} />
                  </div>
                )}
              </div>

              <div style={{ marginTop: "2rem" }}>
                <p className="eyebrow" style={{ marginBottom: "0.25rem" }}>
                  Aircraft rotation for one day
                </p>
                <p className="page-note" style={{ marginBottom: "0.75rem" }}>
                  The actual sequence of flights this tail flew on one calendar day, with the
                  ground gap (scheduled vs actual) before each next leg &mdash; shows directly
                  whether it made up time on the ground or fell further behind. Defaults to this
                  tail&apos;s last observed date; pick a different one to see a different
                  rotation. Same-day only, so a date with just one flight won&apos;t show a
                  carryover comparison.
                </p>
                <div className="route-lookup-row">
                  <label className="filter-field">
                    <span className="filter-label">Date</span>
                    <input
                      type="date"
                      value={rotationDate}
                      min={detail.first_flight}
                      max={detail.last_flight}
                      onChange={(e) => setRotationDate(e.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    className="compare-run"
                    onClick={lookupRotation}
                    disabled={!rotationDate || rotationLoading}
                  >
                    {rotationLoading ? "Loading..." : "Show rotation"}
                  </button>
                </div>

                {rotationNotFound && !rotationLoading && (
                  <p className="error-text" style={{ marginTop: "1rem" }}>
                    No flights found for this tail on that date.
                  </p>
                )}

                {rotation && !rotationNotFound && (
                  rotation.legs.length > 1 ? (
                    <div style={{ marginTop: "1rem" }}>
                      <AircraftRotationTimeline legs={rotation.legs} />
                    </div>
                  ) : (
                    <p className="page-note" style={{ marginTop: "1rem" }}>
                      Only {rotation.legs.length} flight{rotation.legs.length === 1 ? "" : "s"} recorded
                      for this tail on {rotationDate} &mdash; pick a date with a multi-leg rotation
                      to see delay carryover between legs.
                    </p>
                  )
                )}
              </div>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: "rust" }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={`tile-value ${tone === "rust" ? "rust" : ""}`}>{value}</span>
    </div>
  );
}
