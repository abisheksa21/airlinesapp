"use client";

import { useState, useEffect } from "react";
import MaxTimelineChart from "../components/MaxTimelineChart";
import RouteExposureTable from "../components/RouteExposureTable";
import CarrierImpactSummary from "../components/CarrierImpactSummary";
import MaxGroundingStudy from "../components/MaxGroundingStudy";
import { carrierName } from "../lib/carriers";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

export default function MaxGroundingPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/max-grounding-study`)
      .then((r) => {
        if (!r.ok) throw new Error("not ok");
        return r.json();
      })
      .then(setData)
      .catch(() => setError(true));
  }, []);

  const carrierNames = data ? data.carriers.map((c: string) => carrierName(c)).join(" and ") : "";

  return (
    <main className="page">
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; 737 MAX Grounding</p>
        <h1 className="title">The 737 MAX Grounding</h1>
        <p className="subtitle">
          Two fatal crashes &mdash; Lion Air Flight 610 (Oct 29, 2018) and Ethiopian Airlines
          Flight 302 (Mar 10, 2019) &mdash; led aviation authorities worldwide to ground the
          Boeing 737 MAX on March 13, 2019. US carriers were cleared to resume passenger service
          starting November 18, 2020. This page covers what BTS on-time performance data can
          actually show about that event: how it disrupted the network at the route level while
          grounded, and how the aircraft has performed since returning to service. It does not
          cover (and this dataset cannot show) the broader financial, legal, or manufacturing
          story &mdash; production cuts, cancelled orders, lease-rate effects, litigation,
          compensation claims.
        </p>
      </header>

      {error && (
        <p className="error-text">Could not load the grounding study &mdash; check the API is running.</p>
      )}

      {!data && !error && <p className="error-text">Loading...</p>}

      {data && (
        <>
          <section className="section">
            <div className="section-head">
              <h2 className="section-title">Timeline: buildup, grounding, resumption</h2>
              <span className="section-note">
                {carrierNames}, monthly, {data.pre_grounding_window.start.slice(0, 4)}&ndash;2021
              </span>
            </div>
            <div className="screen">
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                Verified directly against this warehouse: all 72 grounded tails show a complete,
                20-month gap with <strong>zero flights</strong> from {data.grounding_date} until
                {" "}{data.ungrounding_date}, then a resumption ramp back to full strength by{" "}
                {data.resumption_window_start}.
              </p>
              <MaxTimelineChart data={data.monthly_timeline} />
            </div>
          </section>

          <section className="section">
            <div className="section-head">
              <h2 className="section-title">Route-level exposure and grounding impact</h2>
              <span className="section-note">
                Pre-grounding window: {data.pre_grounding_window.start} to {data.pre_grounding_window.end}
              </span>
            </div>
            <div className="screen">
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                For every carrier-route with at least one MAX flight in the immediate
                pre-grounding window, this shows what share of that route&apos;s flights were
                MAX (exposure tier), and how flight frequency on that route changed afterward
                &mdash; both for the rest of 2019, and for Jan&ndash;Feb 2020, which is still
                within the grounding but before COVID&apos;s major US disruption ({data.early_2020_window.start} to{" "}
                {data.early_2020_window.end}) &mdash; the one window here that isolates grounding
                impact from the pandemic. &ldquo;vs. carrier benchmark&rdquo; compares a
                route&apos;s change against that carrier&apos;s own total schedule change over the
                same period &mdash; contextual evidence, not a causal counterfactual, since a
                route drop could still reflect normal scheduling changes unrelated to the MAX.
              </p>
              <RouteExposureTable routes={data.route_exposure} />
            </div>
          </section>

          <section className="section">
            <div className="section-head">
              <h2 className="section-title">Impact by carrier</h2>
            </div>
            <div className="screen">
              <CarrierImpactSummary data={data.carrier_impact} />
            </div>
          </section>

          <section className="section">
            <div className="section-head">
              <h2 className="section-title">Performance since return to service</h2>
              <span className="section-note">72 originally-grounded tails vs. same-carrier control, since {data.resumption_window_start}</span>
            </div>
            <div className="screen">
              <p className="page-note" style={{ marginBottom: "1rem" }}>
                Same-era comparison: these 72 tails vs. {carrierNames}&apos;s other flights, both
                since {data.resumption_window_start} &mdash; not pre-grounding vs. post-resumption,
                since that span is almost entirely confounded by COVID&apos;s effect on the whole
                industry, not the airframe. One disclosed limitation: the &ldquo;other
                flights&rdquo; control group can include additional 737 MAX aircraft these
                carriers took delivery of after 2019 (no full current-fleet MAX list is available
                without the FAA registry) &mdash; that would dilute, not exaggerate, any true
                difference.
              </p>
              <MaxGroundingStudy data={data} />
            </div>
          </section>

          <section className="section">
            <div className="section-head">
              <h2 className="section-title">Methodology and limitations</h2>
            </div>
            <div className="screen">
              <p className="page-note" style={{ marginBottom: "0.75rem" }}>
                Adapted from a more extensive prior version of this analysis, streamlined to fit
                the current schema and scope. Deliberately not carried over: flight-number-level
                &ldquo;schedule signature&rdquo; substitution tracking, and per-tail
                utilization/replacement-tail detail &mdash; those could be added later if the
                route-level view here isn&apos;t enough.
              </p>
              <ul className="page-note" style={{ paddingLeft: "1.2rem" }}>
                <li>Cancelled flights can lack a tail assignment, so cancellations can&apos;t be attributed to a specific grounded tail by tail-number matching alone.</li>
                <li>Carrier assignment uses the BTS marketing-carrier field, not legal aircraft ownership.</li>
                <li>March 2020 onward is confounded by COVID and is included mainly for the timeline&apos;s context, not attribution.</li>
                <li>Exposure tiers (high/moderate/low/incidental) are prioritization bands, not causal thresholds.</li>
              </ul>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
