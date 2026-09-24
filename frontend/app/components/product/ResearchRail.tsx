"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ITEMS = [
  { href: "/research", label: "Workspace", mark: "01" },
  { href: "/research/explore", label: "Explore", mark: "02" },
  { href: "/research/diagnose", label: "Diagnose", mark: "03" },
  { href: "/research/network", label: "Network", mark: "04" },
  { href: "/research/capacity", label: "Capacity", mark: "05" },
  { href: "/research/forecast", label: "Forecast", mark: "06" },
  { href: "/research/decisions", label: "Decisions", mark: "07" },
  { href: "/research/evidence", label: "Evidence", mark: "08" },
  { href: "/research/data", label: "Data", mark: "09" },
  { href: "/research/copilot", label: "Copilot", mark: "10" },
];

function active(pathname: string, href: string) { return href === "/research" ? pathname === href : pathname.startsWith(href); }

export function ResearchRail() {
  const pathname = usePathname();
  return <aside className="research-rail"><Link href="/research" className="research-rail-brand"><span aria-hidden="true">✦</span><strong>Airline<br />Ops</strong><small>Operations intelligence</small></Link><nav aria-label="Research workspace">{ITEMS.map((item) => <Link key={item.href} href={item.href} className={active(pathname, item.href) ? "active" : ""}><i>{item.mark}</i><span>{item.label}</span></Link>)}</nav><div className="research-rail-bottom"><span className="status-dot" />Local warehouse<span>Historical data only</span></div></aside>;
}
