"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMode } from "../lib/mode";

const PUBLIC_LINKS = [
  { href: "/", label: "Explore" },
  { href: "/carriers", label: "Carriers" },
  { href: "/airports", label: "Airports" },
  { href: "/routes", label: "Routes" },
  { href: "/glossary", label: "Glossary" },
];

const RESEARCH_LINKS = [
  { href: "/", label: "Workspace" },
  { href: "/carriers", label: "Carriers" },
  { href: "/airports", label: "Airports" },
  { href: "/routes", label: "Routes" },
  { href: "/decision-center", label: "Center" },
  { href: "/capacity", label: "T-100" },
  { href: "/compare", label: "Compare" },
  { href: "/delays", label: "Delays" },
  { href: "/aircraft", label: "Aircraft" },
  { href: "/max-grounding", label: "MAX" },
  { href: "/data-health", label: "Health" },
  { href: "/methodology", label: "Method" },
  { href: "/copilot", label: "Copilot" },
];

export default function Nav() {
  const pathname = usePathname();
  const { mode, setMode } = useMode();
  const links = mode === "public" ? PUBLIC_LINKS : RESEARCH_LINKS;

  return (
    <>
      <nav className={`nav nav-shell ${mode === "researcher" ? "nav-researcher" : "nav-public"}`} aria-label="Primary navigation">
        <Link href="/" className="nav-brand">
          <span className="nav-brand-mark" aria-hidden="true">✦</span>
          <span><strong>Airline</strong><small>Operations Lab</small></span>
        </Link>

        <div className="nav-context">
          <span className="nav-context-overline">{mode === "public" ? "Public brief" : "Research workspace"}</span>
          <span className="nav-context-line">{mode === "public" ? "Understand the network" : "Test the evidence"}</span>
        </div>

        <div className="nav-links">
          {links.map((link) => {
            const active = pathname === link.href || (link.href !== "/" && pathname.startsWith(link.href + "/"));
            return <Link key={link.href} href={link.href} className={active ? "active" : ""}>{link.label}</Link>;
          })}
        </div>

        <button type="button" className={`mode-toggle mode-toggle-${mode}`} onClick={() => setMode(mode === "public" ? "researcher" : "public")} title="Switch between the plain-language public brief and the full researcher workspace">
          <span className={`mode-dot ${mode}`} aria-hidden="true" />
          <span>{mode === "public" ? "Open researcher" : "Public brief"}</span>
          <span aria-hidden="true">↗</span>
        </button>
      </nav>
      <div className={`mode-ribbon mode-ribbon-${mode}`}>
        <span>{mode === "public" ? "PUBLIC VIEW" : "RESEARCHER VIEW"}</span>
        <span>{mode === "public" ? "Plain-language performance and entity profiles" : "Filters, diagnostics, models, and evidence trails"}</span>
      </div>
    </>
  );
}
