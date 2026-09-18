"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useMode, type SiteMode } from "../lib/mode";

const PUBLIC_LINKS = [
  { href: "/", label: "Overview" },
  { href: "/carriers", label: "Airlines" },
  { href: "/airports", label: "Airports" },
  { href: "/routes", label: "Routes" },
];

const RESEARCH_GROUPS = [
  {
    label: "Explore",
    links: [
      { href: "/carriers", label: "Carriers" },
      { href: "/airports", label: "Airports" },
      { href: "/routes", label: "Routes" },
      { href: "/aircraft", label: "Aircraft" },
    ],
  },
  {
    label: "Analyze",
    links: [
      { href: "/decision-center", label: "Decision Center" },
      { href: "/capacity", label: "T-100" },
      { href: "/compare", label: "Compare" },
      { href: "/delays", label: "Delay causes" },
      { href: "/max-grounding", label: "MAX grounding" },
    ],
  },
  {
    label: "Reference",
    links: [
      { href: "/data-health", label: "Data health" },
      { href: "/model-evidence", label: "Model evidence" },
      { href: "/methodology", label: "Methodology" },
      { href: "/copilot", label: "Copilot" },
    ],
  },
];

function isActive(pathname: string, href: string): boolean {
  return pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
}

export default function Nav() {
  const pathname = usePathname();
  const { mode, setMode } = useMode();

  return mode === "public"
    ? <PublicNav pathname={pathname} setMode={setMode} />
    : <ResearchNav pathname={pathname} setMode={setMode} />;
}

function PublicNav({ pathname, setMode }: { pathname: string; setMode: (mode: SiteMode) => void }) {
  return (
    <>
      <nav className="public-navigation" aria-label="Public navigation">
        <Link href="/" className="public-brand">
          <span className="public-brand-mark">✦</span>
          <span><strong>Airline</strong><small>Operations Lab</small></span>
        </Link>
        <span className="public-nav-source">A public brief from the U.S. flight record</span>
        <div className="public-nav-links">
          {PUBLIC_LINKS.map((link) => <Link key={link.href} href={link.href} className={isActive(pathname, link.href) ? "active" : ""}>{link.label}</Link>)}
          <Link href="/glossary" className={isActive(pathname, "/glossary") ? "active" : ""}>Glossary</Link>
        </div>
        <button type="button" className="public-research-button" onClick={() => setMode("researcher")}>
          <span>Research workspace</span><span aria-hidden="true">↗</span>
        </button>
      </nav>
      <div className="public-nav-baseline"><span>DOT / BTS MARKETING CARRIER ON-TIME PERFORMANCE</span><span>Understand the pattern before the conclusion</span></div>
    </>
  );
}

function ResearchNav({ pathname, setMode }: { pathname: string; setMode: (mode: SiteMode) => void }) {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    function closeOnOutsideClick(event: PointerEvent) {
      if (navRef.current && !navRef.current.contains(event.target as Node)) setOpenMenu(null);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpenMenu(null);
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  return (
    <>
      <nav ref={navRef} className="research-navigation" aria-label="Research navigation">
        <Link href="/" className="research-brand">
          <span className="research-brand-mark">✦</span>
          <span><strong>Airline Ops</strong><small>Research console</small></span>
        </Link>
        <div className="research-nav-title"><span>OPERATIONS INTELLIGENCE</span><strong>Question → evidence → decision</strong></div>
        <div className="research-nav-links">
          <Link href="/" className={isActive(pathname, "/") ? "active" : ""}>Workspace</Link>
          {RESEARCH_GROUPS.map((group) => {
            const groupIsActive = group.links.some((link) => isActive(pathname, link.href));
            const menuId = `research-menu-${group.label.toLowerCase()}`;
            return (
              <div className="research-nav-group" key={group.label}>
                <button
                  type="button"
                  className={`research-nav-group-button ${groupIsActive ? "active" : ""}`}
                  aria-expanded={openMenu === group.label}
                  aria-controls={menuId}
                  onClick={() => setOpenMenu(openMenu === group.label ? null : group.label)}
                >
                  <span>{group.label}</span><span className="research-nav-chevron" aria-hidden="true">⌄</span>
                </button>
                {openMenu === group.label && (
                  <div className="research-nav-menu" id={menuId} role="menu" aria-label={`${group.label} pages`}>
                    {group.links.map((link) => (
                      <Link
                        key={link.href}
                        href={link.href}
                        role="menuitem"
                        className={isActive(pathname, link.href) ? "active" : ""}
                        onClick={() => setOpenMenu(null)}
                      >
                        {link.label}
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <button type="button" className="research-public-button" onClick={() => setMode("public")}>
          <span className="research-live-dot" />Public view
        </button>
      </nav>
      <div className="research-nav-baseline"><span>RESEARCHER WORKSPACE / LIVE LOCAL WAREHOUSE</span><span>Measured history · forecasts · scenarios · network structure</span></div>
    </>
  );
}
