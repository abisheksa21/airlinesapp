"use client";

import { useEffect, useState } from "react";
import { type ResearchContext, useResearchContext } from "../../lib/research-context";

const FIELDS: Array<{ key: keyof ResearchContext; label: string; placeholder: string }> = [
  { key: "from", label: "From", placeholder: "2018-01" },
  { key: "to", label: "To", placeholder: "2026-06" },
  { key: "carrier", label: "Carrier", placeholder: "All carriers" },
  { key: "airport", label: "Airport", placeholder: "All airports" },
  { key: "route", label: "Route", placeholder: "ATL → LAX" },
  { key: "metric", label: "Metric", placeholder: "On-time rate" },
];

function ContextInput({ field, value, onCommit }: { field: typeof FIELDS[number]; value: string; onCommit: (value: string) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); }, [value]);
  function commit() { if (draft.trim() !== value) onCommit(draft); }
  return <label><span>{field.label}</span><input value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} placeholder={field.placeholder} /></label>;
}

export function ContextBar() {
  const { context, update, clear } = useResearchContext();
  return <section className="context-bar" aria-label="Research context"><div className="context-bar-title"><span className="section-label">Analysis context</span><p>URL-backed scope</p></div><div className="context-controls">{FIELDS.map((field) => <ContextInput key={field.key} field={field} value={context[field.key]} onCommit={(value) => update({ [field.key]: value })} />)}</div><div className="context-meta"><span>Release: local BTS + T-100</span><span>Version: v1</span><button type="button" onClick={clear}>Reset</button></div></section>;
}
