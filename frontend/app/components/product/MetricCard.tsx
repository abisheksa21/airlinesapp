import type { ReactNode } from "react";

export function MetricCard({ label, value, detail, tone = "default" }: { label: string; value: ReactNode; detail?: ReactNode; tone?: "default" | "good" | "watch" | "critical" }) {
  return <article className={`metric-card metric-${tone}`}><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</article>;
}

export function FreshnessBadge({ period, label = "Historical BTS record" }: { period?: string; label?: string }) {
  return <span className="freshness-badge"><i aria-hidden="true" />{label}{period && <b>{period}</b>}</span>;
}

export function EvidenceBadge({ label = "Evidence-backed", tone = "verified" }: { label?: string; tone?: "verified" | "context" | "caution" }) {
  return <span className={`evidence-badge evidence-${tone}`}>{label}</span>;
}
