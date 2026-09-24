"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

export type ResearchContext = {
  from: string;
  to: string;
  carrier: string;
  airport: string;
  route: string;
  metric: string;
};

export type ResearchContextPatch = Partial<Record<keyof ResearchContext, string | null | undefined>>;

const CONTEXT_KEYS: Array<keyof ResearchContext> = ["from", "to", "carrier", "airport", "route", "metric"];

function valueFor(searchParams: URLSearchParams, key: keyof ResearchContext) {
  return (searchParams.get(key) ?? "").trim();
}

export function monthStart(value: string): string {
  return /^\d{4}-\d{2}$/.test(value) ? `${value}-01` : "";
}

export function monthEnd(value: string): string {
  if (!/^\d{4}-\d{2}$/.test(value)) return "";
  const [year, month] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

export function contextStartDate(value: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return monthStart(value);
}

export function contextEndDate(value: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return monthEnd(value);
}

export function routeParts(route: string): { origin: string; dest: string } | null {
  const match = route.trim().toUpperCase().match(/^([A-Z]{3})\s*(?:→|->|-)\s*([A-Z]{3})$/);
  return match ? { origin: match[1], dest: match[2] } : null;
}

export function contextSummary(context: ResearchContext) {
  const parts = [
    context.from || context.to ? `${context.from || "earliest"} → ${context.to || "latest"}` : "",
    context.carrier ? `carrier ${context.carrier}` : "",
    context.airport ? `airport ${context.airport}` : "",
    context.route ? `route ${context.route}` : "",
    context.metric ? context.metric : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "No shared filters selected";
}

export function useResearchContext() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const context: ResearchContext = Object.fromEntries(
    CONTEXT_KEYS.map((key) => [key, valueFor(searchParams, key)]),
  ) as ResearchContext;

  function update(patch: ResearchContextPatch, options: { replace?: boolean } = {}) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(patch) as Array<[keyof ResearchContext, string | null | undefined]>) {
      if (!CONTEXT_KEYS.includes(key)) continue;
      if (value?.trim()) next.set(key, value.trim()); else next.delete(key);
    }
    const href = `${pathname}${next.size ? `?${next.toString()}` : ""}`;
    if (options.replace === false) router.push(href, { scroll: false }); else router.replace(href, { scroll: false });
  }

  function clear() {
    const next = new URLSearchParams(searchParams.toString());
    CONTEXT_KEYS.forEach((key) => next.delete(key));
    router.replace(`${pathname}${next.size ? `?${next.toString()}` : ""}`, { scroll: false });
  }

  return { context, update, clear, summary: contextSummary(context) };
}
