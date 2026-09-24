"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { carrierName } from "../../lib/carriers";
import { useMode } from "../../lib/mode";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

type SearchEntry = { id: string; kind: "Carrier" | "Airport" | "Route" | "Aircraft"; label: string; meta: string; href: string };

function routeHref(route: string) {
  const [origin, destination] = route.split("→").map((part) => part.trim());
  return origin && destination ? `/routes/${origin}-${destination}` : "/routes";
}

export function GlobalSearch({ compact = false, floating = false }: { compact?: boolean; floating?: boolean }) {
  const { mode } = useMode();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<SearchEntry[]>([]);
  const [aircraftEntries, setAircraftEntries] = useState<SearchEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const searchIndexLoading = useRef(false);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open || entries.length || searchIndexLoading.current) return;
    let current = true;
    searchIndexLoading.current = true;
    setLoading(true);
    Promise.all([
      fetch(`${API_BASE}/api/carriers`).then((response) => response.ok ? response.json() : { carriers: [] }),
      fetch(`${API_BASE}/api/airports/list`).then((response) => response.ok ? response.json() : { airports: [] }),
      fetch(`${API_BASE}/api/routes`).then((response) => response.ok ? response.json() : { routes: [] }),
    ]).then(([carrierData, airportData, routeData]) => {
      if (!current) return;
      const carrierEntries = (carrierData.carriers ?? []).map((item: { carrier: string }) => ({ id: `carrier-${item.carrier}`, kind: "Carrier" as const, label: carrierName(item.carrier), meta: item.carrier, href: `/carriers/${item.carrier}` }));
      const airportEntries = (airportData.airports ?? []).map((airport: string) => ({ id: `airport-${airport}`, kind: "Airport" as const, label: airport, meta: "Airport profile", href: `/airports/${airport}` }));
      const routeEntries = (routeData.routes ?? []).map((item: { route: string; total_flights?: number }) => ({ id: `route-${item.route}`, kind: "Route" as const, label: item.route, meta: item.total_flights ? `${item.total_flights.toLocaleString()} observed flights` : "Route profile", href: routeHref(item.route) }));
      setEntries([...carrierEntries, ...airportEntries, ...routeEntries]);
    }).catch(() => { if (current) setEntries([]); }).finally(() => {
      searchIndexLoading.current = false;
      if (current) setLoading(false);
    });
    return () => {
      current = false;
      searchIndexLoading.current = false;
    };
  }, [entries.length, open]);

  useEffect(() => {
    const tailPrefix = query.trim().toUpperCase();
    if (!open || tailPrefix.length < 2 || !/^[A-Z0-9]+$/.test(tailPrefix)) {
      setAircraftEntries([]);
      return;
    }
    let current = true;
    const timer = window.setTimeout(() => fetch(`${API_BASE}/api/aircraft/search?q=${encodeURIComponent(tailPrefix)}&limit=5`)
      .then((response) => response.ok ? response.json() : { results: [] })
      .then((payload) => {
        if (!current) return;
        setAircraftEntries((payload.results ?? []).map((item: { tail: string; carrier?: string; total_flights?: number }) => ({
          id: `aircraft-${item.tail}`,
          kind: "Aircraft" as const,
          label: item.tail,
          meta: `${item.carrier ?? "Observed carrier"}${item.total_flights ? ` · ${item.total_flights.toLocaleString()} observed flights` : ""}`,
          href: `/aircraft/${item.tail}`,
        })));
      })
      .catch(() => { if (current) setAircraftEntries([]); }), 350);
    return () => { current = false; window.clearTimeout(timer); };
  }, [open, query]);

  const results = useMemo(() => {
    const cleaned = query.trim().toLowerCase();
    if (!cleaned) return entries.slice(0, 9);
    return [...aircraftEntries, ...entries.filter((entry) => `${entry.label} ${entry.meta} ${entry.kind}`.toLowerCase().includes(cleaned))].slice(0, 9);
  }, [aircraftEntries, entries, query]);

  return <>
    <button type="button" className={`global-search-trigger ${compact ? "compact" : ""} ${floating ? "floating" : ""}`} onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open} aria-label="Search the whole app or ask Copilot" title="Search everything or ask Copilot (Ctrl+K)"><span aria-hidden="true">⌕</span><span>{floating ? "Ask / search" : compact ? "Search" : "Search an airline, airport, route, aircraft, or question"}</span><kbd>Ctrl K</kbd></button>
    {open && <div className={`command-backdrop ${floating ? "floating" : ""}`} role="presentation" onMouseDown={() => setOpen(false)}><section className={`command-palette ${floating ? "floating" : ""}`} role="dialog" aria-modal="true" aria-label="Search the aviation intelligence platform" onMouseDown={(event) => event.stopPropagation()}><div className="command-input"><span aria-hidden="true">⌕</span><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find an airport, airline, route, aircraft, or ask a question" /><kbd>Esc</kbd></div><p className="command-hint">This searches the whole app. Use the page filter for only the airports, carriers, or routes shown on that page.</p><div className="command-results">{loading && <p>Loading searchable objects…</p>}{!loading && results.map((entry) => <Link href={entry.href} key={entry.id} onClick={() => setOpen(false)}><span className="command-kind">{entry.kind}</span><strong>{entry.label}</strong><small>{entry.meta}</small><b>↗</b></Link>)}{!loading && !results.length && <p>No matching object yet. Ask Copilot below using the same wording.</p>}</div>{query.trim() && <Link className="command-question" href={`${mode === "public" ? "/copilot" : "/research/copilot"}?question=${encodeURIComponent(query.trim())}`} onClick={() => setOpen(false)}><span>Ask Copilot</span><strong>“{query.trim()}”</strong><b>↗</b></Link>}</section></div>}
  </>;
}

export function CommandPalette() { return <GlobalSearch compact />; }
