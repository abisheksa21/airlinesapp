"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { GlobalSearch } from "./GlobalSearch";
import { CopilotLauncher } from "./CopilotLauncher";
import { ModeSwitcher } from "./ModeSwitcher";
import { ResearchRail } from "./ResearchRail";
import { ContextBar } from "./ContextBar";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { SavedInvestigationMenu } from "./SavedInvestigation";

const LEGACY_RESEARCH_PATHS = ["/aircraft", "/capacity", "/data-health", "/decision-center", "/delays", "/max-grounding", "/model-evidence"];

export function isResearchPath(pathname: string) { return pathname.startsWith("/research") || LEGACY_RESEARCH_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`)); }

const PUBLIC_LINKS = [
  { href: "/", label: "Overview" },
  { href: "/carriers", label: "Carriers" },
  { href: "/airports", label: "Airports" },
  { href: "/routes", label: "Routes" },
  { href: "/compare", label: "Compare" },
  { href: "/network", label: "Network" },
  { href: "/insights", label: "Insights" },
  { href: "/copilot", label: "Copilot" },
];

function selected(pathname: string, href: string) { return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`); }

function PublicShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return <div className="public-product"><header className="public-header"><Link href="/" className="public-wordmark"><span aria-hidden="true">✦</span><strong>Airline<br /><small>Operations Intelligence</small></strong></Link><nav aria-label="Public navigation">{PUBLIC_LINKS.map((link) => <Link href={link.href} key={link.href} className={selected(pathname, link.href) ? "active" : ""}>{link.label}</Link>)}</nav><div className="public-header-actions"><GlobalSearch compact /><ModeSwitcher mode="public" /></div></header><main>{children}</main><footer className="public-footer"><span>Airline Operations Intelligence</span><span>Historical DOT/BTS data, not live flight status</span><div><Link href="/methodology">Methodology</Link><Link href="/glossary">Glossary</Link></div></footer></div>;
}

function ResearchShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const crumb = useMemo(() => pathname.split("/").filter(Boolean).map((part) => part.replace(/-/g, " ")).map((part) => part.charAt(0).toUpperCase() + part.slice(1)), [pathname]);
  return <div className="research-product"><ResearchRail /><section className="research-application"><header className="research-topbar"><div><span className="section-label">Research workspace</span><p>{crumb.join(" / ") || "Workspace"}</p></div><div className="research-topbar-actions"><GlobalSearch compact /><Suspense fallback={null}><SavedInvestigationMenu /></Suspense><ModeSwitcher mode="researcher" /></div></header><Suspense fallback={<div className="research-context-loading" aria-label="Loading workspace context" />}><ContextBar /></Suspense><main className="research-canvas">{children}</main><EvidenceDrawer title="Current workspace" endpoint="Multiple compact FastAPI aggregations" caveat="Open analytical pages only when needed; detailed measures remain backend-aggregated and historical." /></section></div>;
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const research = isResearchPath(pathname);
  useEffect(() => { document.documentElement.dataset.siteMode = research ? "researcher" : "public"; }, [research]);
  return <>{research ? <ResearchShell>{children}</ResearchShell> : <PublicShell>{children}</PublicShell>}<CopilotLauncher mode={research ? "researcher" : "public"} /></>;
}
