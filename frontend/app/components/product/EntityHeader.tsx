import Link from "next/link";
import { FreshnessBadge } from "./MetricCard";

export function Breadcrumbs({ items }: { items: Array<{ label: string; href?: string }> }) {
  return <nav className="breadcrumbs" aria-label="Breadcrumb">{items.map((item, index) => <span key={`${item.label}-${index}`}>{item.href ? <Link href={item.href}>{item.label}</Link> : <b>{item.label}</b>}{index < items.length - 1 && <i>/</i>}</span>)}</nav>;
}

export function EntityHeader({ eyebrow, title, description, period, researchHref, children }: { eyebrow: string; title: string; description: string; period?: string; researchHref?: string; children?: React.ReactNode }) {
  return <header className="entity-header"><div><p className="section-label">{eyebrow}</p><h1>{title}</h1><p>{description}</p><FreshnessBadge period={period} /></div><div className="entity-header-actions">{researchHref && <Link className="primary-link" href={researchHref}>Open in Researcher View <span>↗</span></Link>}{children}</div></header>;
}

export function EntitySummary({ title = "Plain-language reading", children }: { title?: string; children: React.ReactNode }) {
  return <aside className="entity-summary"><span className="section-label">{title}</span><p>{children}</p></aside>;
}
