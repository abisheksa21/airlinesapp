"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import FilterBar, { Filters } from "./FilterBar";
import TrendChart from "./TrendChart";
import { ApiError, fetchJson } from "../lib/api";
import { formatNumber } from "../lib/format";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Summary = {
  total_flights: number;
  start_date: string;
  end_date: string;
  on_time_rate: number;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number;
};
type MonthPoint = { month: string; total_flights: number; on_time_rate: number };

const EMPTY_FILTERS: Filters = { carrier: "", startDate: "", endDate: "" };

function buildQuery(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.carrier) params.set("carrier", filters.carrier);
  if (filters.startDate) params.set("start_date", filters.startDate);
  if (filters.endDate) params.set("end_date", filters.endDate);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export default function FilteredOverview({
  initialSummary,
  initialTrend,
}: {
  initialSummary: Summary | null;
  initialTrend: { months: MonthPoint[] } | null;
}) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [summary, setSummary] = useState<Summary | null>(initialSummary);
  const [trend, setTrend] = useState<{ months: MonthPoint[] } | null>(initialTrend);
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const fetchFiltered = useCallback(async (next: Filters) => {
    // Cancel any still-in-flight request so a stale/malformed response
    // (e.g. from an incomplete date being typed) can never arrive after
    // and overwrite the result of a newer, valid request.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setNotFound(false);
    const qs = buildQuery(next);
    try {
      const [summaryData, trendData] = await Promise.all([
        fetchJson<Summary>(`${API_BASE}/api/summary${qs}`, { signal: controller.signal }),
        fetchJson<{ months: MonthPoint[] }>(`${API_BASE}/api/trend${qs}`, { signal: controller.signal }),
      ]);
      setSummary(summaryData);
      setTrend(trendData);
    } catch (err) {
      if ((err as Error).name === "AbortError") return; // superseded by a newer request, ignore
      if (err instanceof ApiError && err.status === 404) {
        setSummary(null);
        setTrend(null);
      }
      setNotFound(true);
    } finally {
      if (abortRef.current === controller) {
        setLoading(false);
      }
    }
  }, []);

  const isFirstMount = useRef(true);
  useEffect(() => {
    if (isFirstMount.current) {
      isFirstMount.current = false;
      return; // skip refetch on initial mount -- we already have server-fetched data
    }
    // Debounce: wait until the user pauses (e.g. finishes picking a date)
    // before firing, instead of refetching on every intermediate keystroke.
    const timer = setTimeout(() => fetchFiltered(filters), 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.carrier, filters.startDate, filters.endDate]);

  function handleFilterChange(next: Filters) {
    setFilters(next);
  }

  return (
    <div>
      <FilterBar filters={filters} onChange={handleFilterChange} />

      {loading && <p className="filter-status">Loading...</p>}

      {notFound && !loading && (
        <p className="filter-status error-text">No flights matched that filter.</p>
      )}

      {!notFound && summary && (
        <div className="board board-compact">
          <MiniTile label="Total flights" value={summary.total_flights.toLocaleString()} />
          <MiniTile label="On-time rate" value={`${(summary.on_time_rate * 100).toFixed(1)}%`} />
          <MiniTile
            label="Avg arrival delay"
            value={`${formatNumber(summary.avg_arrival_delay_minutes)} min`}
            tone="rust"
          />
          <MiniTile
            label="Cancellation rate"
            value={`${(summary.cancellation_rate * 100).toFixed(2)}%`}
            tone="rust"
          />
        </div>
      )}

      {!notFound && trend && trend.months.length > 0 && <TrendChart data={trend.months} />}
    </div>
  );
}

function MiniTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "rust";
}) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={`tile-value ${tone === "rust" ? "rust" : ""}`}>{value}</span>
    </div>
  );
}
