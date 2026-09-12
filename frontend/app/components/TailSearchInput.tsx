"use client";

import { useState, useEffect, useRef } from "react";
import { CARRIER_NAMES, carrierName } from "../lib/carriers";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";
const CARRIER_CODES = Object.keys(CARRIER_NAMES);

type SearchResult = { tail: string; total_flights: number; carrier: string };

export default function TailSearchInput({
  value,
  onChange,
  label = "Tail number",
}: {
  value: string;
  onChange: (tail: string) => void;
  label?: string;
}) {
  const [carrierFilter, setCarrierFilter] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [sortMode, setSortMode] = useState<"flights" | "alpha">("flights");
  const searchAbortRef = useRef<AbortController | null>(null);
  const isFirstSearch = useRef(true);

  useEffect(() => {
    if (isFirstSearch.current) {
      isFirstSearch.current = false;
      return;
    }
    if (!value.trim()) {
      setSearchResults([]);
      setShowDropdown(false);
      return;
    }
    const timer = setTimeout(async () => {
      searchAbortRef.current?.abort();
      const controller = new AbortController();
      searchAbortRef.current = controller;
      setSearchLoading(true);
      try {
        const params = new URLSearchParams({ q: value.trim(), sort: sortMode, limit: "300" });
        if (carrierFilter) params.set("carrier", carrierFilter);
        const res = await fetch(`${API_BASE}/api/aircraft/search?${params.toString()}`, {
          signal: controller.signal,
        });
        const data = await res.json();
        setSearchResults(data.results ?? []);
        setShowDropdown(true);
      } catch (err) {
        if ((err as Error).name !== "AbortError") setSearchResults([]);
      } finally {
        if (searchAbortRef.current === controller) setSearchLoading(false);
      }
    }, 200);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, sortMode, carrierFilter]);

  function selectTail(tail: string) {
    onChange(tail);
    setShowDropdown(false);
  }

  return (
    <div className="tail-search-group">
      <label className="filter-field">
        <span className="filter-label">Carrier (optional, narrows search)</span>
        <select value={carrierFilter} onChange={(e) => setCarrierFilter(e.target.value)}>
          <option value="">All carriers</option>
          {CARRIER_CODES.map((code) => (
            <option key={code} value={code}>{code} &mdash; {carrierName(code)}</option>
          ))}
        </select>
      </label>

      <label className="filter-field tail-search-field">
        <span className="filter-label-row">
          <span className="filter-label">{label}</span>
          <span className="sort-toggle">
            <button
              type="button"
              className={sortMode === "flights" ? "sort-toggle-active" : ""}
              onClick={() => setSortMode("flights")}
            >
              Flights
            </button>
            <button
              type="button"
              className={sortMode === "alpha" ? "sort-toggle-active" : ""}
              onClick={() => setSortMode("alpha")}
            >
              A&ndash;Z
            </button>
          </span>
        </span>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          onFocus={() => searchResults.length > 0 && setShowDropdown(true)}
          onBlur={() => setTimeout(() => setShowDropdown(false), 150)}
          placeholder="Start typing, e.g. N"
          className="tail-input"
          autoComplete="off"
        />
        {showDropdown && (
          <div className="tail-dropdown">
            {searchLoading && <div className="tail-dropdown-status">Searching...</div>}
            {!searchLoading && searchResults.length === 0 && (
              <div className="tail-dropdown-status">No matches</div>
            )}
            {!searchLoading &&
              searchResults.map((r) => (
                <button
                  type="button"
                  key={r.tail}
                  className="tail-dropdown-item"
                  onMouseDown={() => selectTail(r.tail)}
                >
                  <span className="tail-dropdown-tail">{r.tail}</span>
                  <span className="tail-dropdown-carrier">{carrierName(r.carrier)}</span>
                  <span className="tail-dropdown-flights">{r.total_flights.toLocaleString()}</span>
                </button>
              ))}
          </div>
        )}
      </label>
    </div>
  );
}
