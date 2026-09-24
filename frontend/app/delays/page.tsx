"use client";

import { useState, useEffect } from "react";
import DelayCauseChart from "../components/DelayCauseChart";
import DateRangePreset from "../components/DateRangePreset";
import CancellationCauseChart from "../components/CancellationCauseChart";
import DistanceBucketChart from "../components/DistanceBucketChart";
import { CARRIER_NAMES, carrierName } from "../lib/carriers";
import { contextEndDate, contextStartDate, useResearchContext } from "../lib/research-context";
import { ChartFrame } from "../components/product/ChartFrame";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

type Cause = { cause: string; minutes: number; share: number };

type DelayResult = {
  total_flights: number;
  delayed_flights: number;
  causes: Cause[];
};

type CancellationCause = { cause: string; cancelled_flights: number; share: number };
type CancellationResult = {
  total_cancelled_flights: number;
  coded_cancelled_flights: number;
  causes: CancellationCause[];
};

type DistanceBucket = {
  bucket: string;
  total_flights: number;
  on_time_rate: number;
  avg_arrival_delay_minutes: number;
  cancellation_rate: number;
  avg_distance_miles: number;
};
type DistanceBucketResult = { buckets: DistanceBucket[] };
type DelayFilters = { carrier: string; airport: string; startDate: string; endDate: string };

const CARRIER_CODES = Object.keys(CARRIER_NAMES);

function buildQuery(params: Record<string, string>): string {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v) usp.set(k, v);
  });
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

export default function DelaysPage() {
  const { context, update, summary: contextSummary } = useResearchContext();
  const [overview, setOverview] = useState<{ causes: Cause[] } | null>(null);
  const [cancellationOverview, setCancellationOverview] = useState<CancellationResult | null>(null);
  const [distanceOverview, setDistanceOverview] = useState<DistanceBucketResult | null>(null);
  const [allAirports, setAllAirports] = useState<string[]>([]);

  const [carrierInput, setCarrierInput] = useState("");
  const [airportInput, setAirportInput] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const [result, setResult] = useState<DelayResult | null>(null);
  const [cancellationResult, setCancellationResult] = useState<CancellationResult | null>(null);
  const [distanceResult, setDistanceResult] = useState<DistanceBucketResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [cancellationNotFound, setCancellationNotFound] = useState(false);
  const [distanceNotFound, setDistanceNotFound] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/delay-causes`)
      .then((r) => r.json())
      .then(setOverview)
      .catch(() => setOverview(null));

    fetch(`${API_BASE}/api/cancellation-causes`)
      .then((r) => r.json())
      .then(setCancellationOverview)
      .catch(() => setCancellationOverview(null));

    fetch(`${API_BASE}/api/distance-buckets`)
      .then((r) => r.json())
      .then(setDistanceOverview)
      .catch(() => setDistanceOverview(null));

    fetch(`${API_BASE}/api/airports/list`)
      .then((r) => r.json())
      .then((d) => setAllAirports(d.airports ?? []))
      .catch(() => setAllAirports([]));
  }, []);

  async function applyFilters(filters: DelayFilters) {
    setLoading(true);
    setNotFound(false);
    const qs = buildQuery({
      carrier: filters.carrier,
      airport: filters.airport,
      start_date: filters.startDate,
      end_date: filters.endDate,
    });
    setCancellationNotFound(false);
    try {
      const res = await fetch(`${API_BASE}/api/delay-causes${qs}`);
      if (res.status === 404) {
        setResult(null);
        setNotFound(true);
      } else {
        setResult(await res.json());
      }
    } catch {
      setNotFound(true);
    }

    try {
      const cancRes = await fetch(`${API_BASE}/api/cancellation-causes${qs}`);
      if (cancRes.status === 404) {
        setCancellationResult(null);
        setCancellationNotFound(true);
      } else {
        setCancellationResult(await cancRes.json());
      }
    } catch {
      setCancellationNotFound(true);
    }

    setDistanceNotFound(false);
    try {
      const distRes = await fetch(`${API_BASE}/api/distance-buckets${qs}`);
      if (distRes.status === 404) {
        setDistanceResult(null);
        setDistanceNotFound(true);
      } else {
        setDistanceResult(await distRes.json());
      }
    } catch {
      setDistanceNotFound(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const scoped = {
      carrier: context.carrier,
      airport: context.airport,
      startDate: contextStartDate(context.from),
      endDate: contextEndDate(context.to),
    };
    setCarrierInput(scoped.carrier);
    setAirportInput(scoped.airport);
    setStartDate(scoped.startDate);
    setEndDate(scoped.endDate);
    if (Object.values(scoped).some(Boolean)) void applyFilters(scoped);
  }, [context.airport, context.carrier, context.from, context.to]);

  const hasFilter = carrierInput || airportInput || startDate || endDate;
  const selectedPeriod = startDate || endDate ? `${startDate || "earliest"} to ${endDate || "latest"}` : "Full local warehouse";

  return (
    <main className="page">
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; Delays</p>
        <h1 className="title">Delay causes</h1>
        <p className="subtitle">
          BTS&apos;s own recorded categories &mdash; largest contributing category, not a root cause.
        </p>
      </header>

      <section className="section">
        <ChartFrame title="Share of delay-minutes by cause" interpretation="BTS-recorded cause minutes show which category accounts for the largest recorded share of delay time; they do not prove a root cause." evidence={{ source: "BTS Marketing Carrier On-Time Performance delay fields", period: "Full local warehouse", method: "Share of available recorded delay minutes", definition: "Each bar is a recorded cause category's share of total reported delay minutes.", caveat: "BTS cause categories are descriptive classifications, not a complete causal diagnosis." }}>
          {overview ? <DelayCauseChart data={overview.causes} /> : <p className="error-text">Loading...</p>}
        </ChartFrame>
      </section>

      <section className="section">
        <ChartFrame title="Why flights get cancelled" interpretation="Cancellation codes describe flights that did not operate. They are separate from delay causes on completed flights." evidence={{ source: "BTS cancellation-code fields", period: "Full local warehouse", sample: cancellationOverview ? cancellationOverview.total_cancelled_flights.toLocaleString() : undefined, method: "Cancellation count aggregation", definition: "Each category is the BTS-coded reason for a cancelled flight.", caveat: "Classification practices and extraordinary periods can affect category shares." }}>
          {cancellationOverview ? (
            <>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                {cancellationOverview.total_cancelled_flights.toLocaleString()} cancelled flights,{" "}
                {cancellationOverview.coded_cancelled_flights.toLocaleString()} with a coded reason
                ({((cancellationOverview.coded_cancelled_flights / cancellationOverview.total_cancelled_flights) * 100).toFixed(1)}%)
              </p>
              <CancellationCauseChart data={cancellationOverview.causes} />

              <details className="health-methodology" style={{ marginTop: "1.5rem" }}>
                <summary>Why does Security look unusually high?</summary>
                <div className="health-methodology-body">
                  <p>
                    Security-caused cancellations shown here are a meaningfully larger share than
                    most people would expect from real-world air travel. That&apos;s not a bug in
                    this site &mdash; we traced it to a specific, verifiable cause.
                  </p>
                  <p>
                    <strong>It&apos;s almost entirely a 2020 artifact.</strong> Broken out by year,
                    Security cancellations sit at 0&ndash;1% of all cancellations in every year
                    except one: in 2020, 83.1% of that year&apos;s cancellations were coded
                    Security. BTS&apos;s four cancellation categories (Carrier, Weather, National
                    Air System, Security) predate COVID-19 and have no dedicated public-health-emergency
                    code &mdash; when airlines mass-cancelled flights in 2020, they had to force
                    those cancellations into one of the four existing categories, and evidently
                    many defaulted to Security as the catch-all.
                  </p>
                  <p>
                    This also wasn&apos;t uniform across airlines: Allegiant coded 51.6% of its
                    entire cancellation history as Security, Southwest 28.0%, Hawaiian 27.5% &mdash;
                    while Alaska sat at 0.4% and Virgin America at 0.0%. That spread points to
                    individual carriers making different classification choices for their
                    COVID-era cancellations, not a real difference in security-incident rates
                    between airlines.
                  </p>
                  <p>
                    We verified this isn&apos;t a mapping error on our end: BTS&apos;s own A/B/C/D
                    cancellation codes were checked against multiple independent sources and match
                    exactly what&apos;s used here, and the year-by-year and carrier-by-carrier
                    breakdowns were confirmed by querying the warehouse directly.
                  </p>
                </div>
              </details>
            </>
          ) : (
            <p className="error-text">Loading...</p>
          )}
        </ChartFrame>
      </section>

      <section className="section">
        <ChartFrame title="On-time performance by scheduled distance" interpretation="Distance groups make reliability differences visible by scheduled length, but they mix routes, airports, weather, and carrier schedules." evidence={{ source: "BTS Marketing Carrier On-Time Performance", period: "Full local warehouse", sample: distanceOverview ? distanceOverview.buckets.reduce((total, item) => total + item.total_flights, 0).toLocaleString() : undefined, method: "Scheduled-distance bucket aggregation", definition: "Short-haul is under 500 miles, medium-haul is 500–1,500 miles, and long-haul is over 1,500 miles.", caveat: "Distance is an association and does not isolate the operational reason for any performance gap." }}>
          {distanceOverview ? (
            <>
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                Short-haul is under 500 miles, medium-haul 500&ndash;1,500 miles, long-haul
                over 1,500 miles &mdash; covering essentially all domestic routes, including
                mainland&ndash;Hawaii legs. On-time rate barely moves across buckets &mdash;
                79.9% short-haul, 78.0% medium-haul, 78.6% long-haul &mdash; and short-haul is
                actually the best of the three, not the worst, despite carrying the least
                schedule buffer. What does move is cancellation rate, which drops steadily with
                distance: 2.37% short-haul, 2.10% medium-haul, 1.46% long-haul &mdash; a
                long-haul flight is roughly 40% less likely to be cancelled than a short-haul
                one. Average arrival delay tracks neither pattern: medium-haul has the highest
                average delay (6.0 min) despite sitting in the middle, while long-haul has the
                lowest (3.7 min) despite covering the most distance.
              </p>
              <DistanceBucketChart data={distanceOverview.buckets} />

              <details className="health-methodology" style={{ marginTop: "1.5rem" }}>
                <summary>Why doesn&apos;t average delay track on-time rate?</summary>
                <div className="health-methodology-body">
                  <p>
                    This isn&apos;t resolved the way the Security-cancellation finding above
                    was &mdash; we haven&apos;t traced a specific cause yet. One plausible
                    explanation: on-time rate only asks whether a flight lands within 15 minutes
                    of schedule, while average delay is pulled by the full tail of how late the
                    worst flights run. A bucket could have a slightly higher share of on-time
                    flights and still carry a higher average if its late flights, when they are
                    late, tend to run later. That&apos;s a hypothesis, not a confirmed finding
                    &mdash; it would need the same chronological-split, real-data treatment used
                    for the health score and queue-pressure work before it&apos;s stated as fact
                    here.
                  </p>
                  <p>
                    The cancellation-rate pattern is more solid: it&apos;s monotonic (decreases
                    at every step from short to long-haul) across a very large sample in every
                    bucket (6.9M&ndash;30.2M flights), which is a much stronger signal than the
                    small, non-monotonic gaps in on-time rate.
                  </p>
                </div>
              </details>
            </>
          ) : (
            <p className="error-text">Loading...</p>
          )}
        </ChartFrame>
      </section>

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Slice by carrier, airport, and date range</h2>
        </div>
        <div className="screen">
          <div className="route-lookup-row">
            <label className="filter-field">
              <span className="filter-label">Carrier</span>
              <select value={carrierInput} onChange={(e) => { setCarrierInput(e.target.value); update({ carrier: e.target.value }); }}>
                <option value="">All carriers</option>
                {CARRIER_CODES.map((code) => (
                  <option key={code} value={code}>
                    {code} &mdash; {carrierName(code)}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              <span className="filter-label">Airport</span>
              <select value={airportInput} onChange={(e) => { setAirportInput(e.target.value); update({ airport: e.target.value }); }}>
                <option value="">All airports</option>
                {allAirports.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </label>
            <DateRangePreset
              startDate={startDate}
              endDate={endDate}
              onChange={(start, end) => { setStartDate(start); setEndDate(end); update({ from: start, to: end }); }}
            />
            <button
              type="button"
              className="compare-run"
              onClick={() => void applyFilters({ carrier: carrierInput, airport: airportInput, startDate, endDate })}
              disabled={!hasFilter || loading}
            >
              {loading ? "Applying..." : "Apply"}
            </button>
          </div>
          <p className="research-scope-note"><strong>URL scope:</strong> {contextSummary}. {context.route ? "Route direction stays visible in the shared context, but BTS delay-cause aggregates here are carrier/airport/date filters rather than route-specific causes." : "Changing the shared context reruns these carrier, airport, and date aggregates."}</p>

          {notFound && !loading && (
            <p className="error-text" style={{ marginTop: "1rem" }}>No flights matched that filter.</p>
          )}

          {result && !notFound && (
            <div className="route-detail">
              <div className="board board-compact board-compact-2" style={{ marginTop: "1.5rem" }}>
                <Tile label="Total flights in scope" value={result.total_flights.toLocaleString()} />
                <Tile
                  label="Delayed 15+ min"
                  value={`${result.delayed_flights.toLocaleString()} (${((result.delayed_flights / result.total_flights) * 100).toFixed(1)}%)`}
                  tone="rust"
                />
              </div>
              <ChartFrame title="Delay causes in the active scope" interpretation="The chart updates from the carrier, airport, and date values in the shared research URL." evidence={{ source: "BTS Marketing Carrier On-Time Performance delay fields", period: selectedPeriod, sample: result.total_flights.toLocaleString(), method: "Filtered cause-minute aggregation", caveat: "A route value in the shared context is retained for the investigation but is not applied here because this BTS cause endpoint is carrier/airport/date-grained." }} className="scoped-chart-frame">
                <DelayCauseChart data={result.causes} />
              </ChartFrame>

              {cancellationResult && !cancellationNotFound && (
                <ChartFrame title="Cancellation causes in the active scope" interpretation="The categories describe why flights in this carrier, airport, and period scope did not operate." evidence={{ source: "BTS cancellation-code fields", period: selectedPeriod, sample: cancellationResult.total_cancelled_flights.toLocaleString(), method: "Filtered cancellation count aggregation", caveat: "Cancellation-code shares can be affected by reporting conventions and exceptional periods." }} className="scoped-chart-frame">
                  <p className="page-note" style={{ marginBottom: "1rem" }}>
                    {cancellationResult.total_cancelled_flights.toLocaleString()} cancelled flights in scope,{" "}
                    {cancellationResult.coded_cancelled_flights.toLocaleString()} with a coded reason
                  </p>
                  <CancellationCauseChart data={cancellationResult.causes} />
                </ChartFrame>
              )}
              {cancellationNotFound && (
                <p className="page-note" style={{ marginTop: "1.5rem" }}>
                  No cancelled flights in this scope to break down.
                </p>
              )}

              {distanceResult && !distanceNotFound && (
                <ChartFrame title="Haul-length breakdown in the active scope" interpretation="This keeps the active carrier, airport, and date scope while grouping the resulting records by scheduled distance." evidence={{ source: "BTS Marketing Carrier On-Time Performance", period: selectedPeriod, sample: distanceResult.buckets.reduce((total, item) => total + item.total_flights, 0).toLocaleString(), method: "Filtered scheduled-distance bucket aggregation", caveat: "Distance groups still combine multiple routes and operational conditions." }} className="scoped-chart-frame">
                  <DistanceBucketChart data={distanceResult.buckets} />
                </ChartFrame>
              )}
              {distanceNotFound && (
                <p className="page-note" style={{ marginTop: "1.5rem" }}>
                  No flights with a recorded distance in this scope.
                </p>
              )}
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
