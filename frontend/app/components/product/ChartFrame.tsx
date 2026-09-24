"use client";

import { useState, type ReactNode } from "react";
import type { Evidence } from "./types";

export function ChartFrame({ title, interpretation, evidence, children, className = "" }: { title: string; interpretation: string; evidence: Evidence; children: ReactNode; className?: string }) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  return <section className={`chart-frame ${className}`}>
    <header className="chart-frame-header"><div><span className="section-label">Measured view</span><h2>{title}</h2><p>{interpretation}</p></div><button type="button" className="quiet-button" onClick={() => setDetailsOpen((open) => !open)} aria-expanded={detailsOpen}>{detailsOpen ? "Hide details" : "Definition & caveat"}</button></header>
    {children}
    <footer className="chart-evidence"><span><b>Source</b>{evidence.source ?? "Local BTS warehouse"}</span><span><b>Period</b>{evidence.period ?? "Not specified"}</span>{evidence.sample != null && <span><b>Sample</b>{evidence.sample}</span>}<span><b>Method</b>{evidence.method ?? "Descriptive aggregation"}</span></footer>
    {detailsOpen && <div className="chart-details"><p><b>Definition:</b> {evidence.definition ?? "See methodology for the exact calculation."}</p><p><b>Boundary:</b> {evidence.caveat ?? "Observed associations are not causal claims or live operational predictions."}</p></div>}
  </section>;
}

export function MethodologyPopover({ label = "Methodology", children }: { label?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <span className="method-popover"><button type="button" onClick={() => setOpen((current) => !current)} aria-expanded={open}>{label}</button>{open && <span role="note">{children}</span>}</span>;
}
