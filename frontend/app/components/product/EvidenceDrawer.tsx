"use client";

import { useState } from "react";
import Link from "next/link";

export function EvidenceDrawer({ title = "Evidence & boundaries", endpoint, sample, period, caveat, methodologyHref = "/methodology" }: { title?: string; endpoint?: string; sample?: string; period?: string; caveat?: string; methodologyHref?: string }) {
  const [open, setOpen] = useState(false);
  return <aside className={`evidence-drawer ${open ? "open" : ""}`}><button type="button" className="evidence-drawer-toggle" onClick={() => setOpen((value) => !value)} aria-expanded={open}><span>Evidence</span><b>{open ? "−" : "+"}</b></button>{open && <div className="evidence-drawer-content"><span className="section-label">{title}</span><dl>{endpoint && <><dt>Endpoint</dt><dd>{endpoint}</dd></>}{period && <><dt>Period</dt><dd>{period}</dd></>}{sample && <><dt>Sample</dt><dd>{sample}</dd></>}</dl><p>{caveat ?? "This surface presents measured historical data. It does not establish causation or guarantee future performance."}</p><Link href={methodologyHref}>Read methodology →</Link></div>}</aside>;
}

export function CopilotDrawer({ context, publicMode = false }: { context: string; publicMode?: boolean }) {
  const target = `${publicMode ? "/copilot" : "/research/copilot"}?question=${encodeURIComponent(context)}`;
  return <aside className={`copilot-drawer ${publicMode ? "copilot-public" : ""}`}><span className="section-label">Contextual Copilot</span><p>{publicMode ? "Ask a plain-language question and inspect the historical evidence behind it." : "Carry this investigation into Copilot with its active context and limits."}</p><Link href={target}>{publicMode ? "Ask about this object" : "Open with this context"} <b>↗</b></Link></aside>;
}
