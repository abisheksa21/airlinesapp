"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useMode, type SiteMode } from "../lib/mode";

const PUBLIC_LINKS = [
  { href: "/", label: "Ask" },
  { href: "/carriers", label: "Airlines" },
  { href: "/airports", label: "Airports" },
  { href: "/routes", label: "Routes" },
];

const RESEARCH_GROUPS = [
  {
    label: "Explore",
    description: "Historical surfaces",
    links: [
      { href: "/carriers", label: "Carriers", note: "Performance by airline" },
      { href: "/airports", label: "Airports", note: "Gateway activity and outcomes" },
      { href: "/routes", label: "Routes", note: "Directional connections" },
      { href: "/aircraft", label: "Aircraft", note: "Equipment and rotations" },
      { href: "/delays", label: "Delay causes", note: "Recorded source categories" },
    ],
  },
  {
    label: "Decide",
    description: "Questions and scenarios",
    links: [
      { href: "/decision-center", label: "Decision Center", note: "Question → evidence → action" },
      { href: "/capacity", label: "T-100 traffic", note: "Passengers and seats beside OTP" },
      { href: "/compare", label: "Compare", note: "Structured historical comparison" },
      { href: "/max-grounding", label: "MAX grounding", note: "Defined disruption study" },
    ],
  },
  {
    label: "Evidence",
    description: "Trust and methods",
    links: [
      { href: "/model-evidence", label: "Model evidence", note: "Repeated temporal validation" },
      { href: "/data-health", label: "Data health", note: "Coverage, refresh, and limits" },
      { href: "/methodology", label: "Methodology", note: "Definitions and calculations" },
      { href: "/research/copilot", label: "Research copilot", note: "Guided project questions" },
    ],
  },
];

function isActive(pathname: string, href: string): boolean {
  return pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
}

export default function Nav() {
  const pathname = usePathname();
  const { mode, setMode } = useMode();
  return mode === "public" ? <PublicNav pathname={pathname} setMode={setMode} /> : <ResearchNav pathname={pathname} setMode={setMode} />;
}

function PublicNav({ pathname, setMode }: { pathname: string; setMode: (mode: SiteMode) => void }) {
  return <>
    <nav className="public-navigation" aria-label="Public navigation">
      <Link href="/" className="public-brand"><span className="public-brand-mark">✦</span><span><strong>Flight Brief</strong><small>Airline Operations Lab</small></span></Link>
      <span className="public-nav-source">Historical U.S. airline performance, in plain language</span>
      <div className="public-nav-links">{PUBLIC_LINKS.map((link) => <Link key={link.href} href={link.href} className={isActive(pathname, link.href) ? "active" : ""}>{link.label}</Link>)}<Link href="/glossary" className={isActive(pathname, "/glossary") ? "active" : ""}>Glossary</Link></div>
      <button type="button" className="public-research-button" onClick={() => setMode("researcher")}><span>Open research workspace</span><span aria-hidden="true">↗</span></button>
    </nav>
    <div className="public-nav-baseline"><span>Historical patterns, not live travel advice</span><span>BTS Marketing Carrier On-Time Performance</span></div>
  </>;
}

function ResearchNav({ pathname, setMode }: { pathname: string; setMode: (mode: SiteMode) => void }) {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    function closeOnOutsideClick(event: PointerEvent) { if (navRef.current && !navRef.current.contains(event.target as Node)) setOpenMenu(null); }
    function closeOnEscape(event: KeyboardEvent) { if (event.key === "Escape") setOpenMenu(null); }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => { document.removeEventListener("pointerdown", closeOnOutsideClick); document.removeEventListener("keydown", closeOnEscape); };
  }, []);

  return <>
    <nav ref={navRef} className="research-navigation" aria-label="Research navigation">
      <Link href="/" className="research-brand"><span className="research-brand-mark">✦</span><span><strong>Airline Ops</strong><small>Research console</small></span></Link>
      <div className="research-nav-title"><span>OPERATIONS INTELLIGENCE</span><strong>Question → evidence → decision</strong></div>
      <div className="research-nav-links">
        <Link href="/" className={isActive(pathname, "/") ? "active" : ""}>Workspace</Link>
        {RESEARCH_GROUPS.map((group) => {
          const groupIsActive = group.links.some((link) => isActive(pathname, link.href));
          const menuId = `research-menu-${group.label.toLowerCase()}`;
          return <div className="research-nav-group" key={group.label}>
            <button type="button" className={`research-nav-group-button ${groupIsActive ? "active" : ""}`} aria-expanded={openMenu === group.label} aria-controls={menuId} onClick={() => setOpenMenu(openMenu === group.label ? null : group.label)}><span>{group.label}</span><span className="research-nav-chevron" aria-hidden="true">⌄</span></button>
            {openMenu === group.label && <div className="research-nav-menu" id={menuId} role="menu" aria-label={`${group.label} pages`}><div className="research-menu-heading"><span>{group.label}</span><small>{group.description}</small></div>{group.links.map((link) => <Link key={link.href} href={link.href} role="menuitem" className={isActive(pathname, link.href) ? "active" : ""} onClick={() => setOpenMenu(null)}><strong>{link.label}</strong><small>{link.note}</small></Link>)}</div>}
          </div>;
        })}
      </div>
      <button type="button" className="research-public-button" onClick={() => setMode("public")}><span className="research-live-dot" />Public view</button>
    </nav>
    <div className="research-nav-baseline"><span>Local research environment</span><span>Open a menu when you need a tool; keep the question in view</span></div>
  </>;
}
