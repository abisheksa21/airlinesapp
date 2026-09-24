"use client";

import { useEffect, useState } from "react";

type Mode = "all" | "year" | "month" | "occasion" | "custom";

const YEARS = [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018];

// Each occasion's window is a few days around the actual date, computed
// programmatically (not guessed) -- Easter in particular moves every year.
const OCCASIONS: Record<string, Record<number, { start: string; end: string }>> = {
  "Thanksgiving": {
    2026: { start: "2026-11-22", end: "2026-11-29" },
    2025: { start: "2025-11-23", end: "2025-11-30" },
    2024: { start: "2024-11-24", end: "2024-12-01" },
    2023: { start: "2023-11-19", end: "2023-11-26" },
    2022: { start: "2022-11-20", end: "2022-11-27" },
    2021: { start: "2021-11-21", end: "2021-11-28" },
    2020: { start: "2020-11-22", end: "2020-11-29" },
    2019: { start: "2019-11-24", end: "2019-12-01" },
    2018: { start: "2018-11-18", end: "2018-11-25" },
  },
  "Christmas / New Year": {
    2026: { start: "2026-12-20", end: "2027-01-02" },
    2025: { start: "2025-12-20", end: "2026-01-02" },
    2024: { start: "2024-12-20", end: "2025-01-02" },
    2023: { start: "2023-12-20", end: "2024-01-02" },
    2022: { start: "2022-12-20", end: "2023-01-02" },
    2021: { start: "2021-12-20", end: "2022-01-02" },
    2020: { start: "2020-12-20", end: "2021-01-02" },
    2019: { start: "2019-12-20", end: "2020-01-02" },
    2018: { start: "2018-12-20", end: "2019-01-02" },
  },
  "Easter": {
    2026: { start: "2026-04-02", end: "2026-04-06" },
    2025: { start: "2025-04-17", end: "2025-04-21" },
    2024: { start: "2024-03-28", end: "2024-04-01" },
    2023: { start: "2023-04-06", end: "2023-04-10" },
    2022: { start: "2022-04-14", end: "2022-04-18" },
    2021: { start: "2021-04-01", end: "2021-04-05" },
    2020: { start: "2020-04-09", end: "2020-04-13" },
    2019: { start: "2019-04-18", end: "2019-04-22" },
    2018: { start: "2018-03-29", end: "2018-04-02" },
  },
  "Memorial Day": {
    2026: { start: "2026-05-22", end: "2026-05-25" },
    2025: { start: "2025-05-23", end: "2025-05-26" },
    2024: { start: "2024-05-24", end: "2024-05-27" },
    2023: { start: "2023-05-26", end: "2023-05-29" },
    2022: { start: "2022-05-27", end: "2022-05-30" },
    2021: { start: "2021-05-28", end: "2021-05-31" },
    2020: { start: "2020-05-22", end: "2020-05-25" },
    2019: { start: "2019-05-24", end: "2019-05-27" },
    2018: { start: "2018-05-25", end: "2018-05-28" },
  },
  "July 4th": {
    2026: { start: "2026-07-01", end: "2026-07-07" },
    2025: { start: "2025-07-01", end: "2025-07-07" },
    2024: { start: "2024-07-01", end: "2024-07-07" },
    2023: { start: "2023-07-01", end: "2023-07-07" },
    2022: { start: "2022-07-01", end: "2022-07-07" },
    2021: { start: "2021-07-01", end: "2021-07-07" },
    2020: { start: "2020-07-01", end: "2020-07-07" },
    2019: { start: "2019-07-01", end: "2019-07-07" },
    2018: { start: "2018-07-01", end: "2018-07-07" },
  },
  "Labor Day": {
    2026: { start: "2026-09-04", end: "2026-09-07" },
    2025: { start: "2025-08-29", end: "2025-09-01" },
    2024: { start: "2024-08-30", end: "2024-09-02" },
    2023: { start: "2023-09-01", end: "2023-09-04" },
    2022: { start: "2022-09-02", end: "2022-09-05" },
    2021: { start: "2021-09-03", end: "2021-09-06" },
    2020: { start: "2020-09-04", end: "2020-09-07" },
    2019: { start: "2019-08-30", end: "2019-09-02" },
    2018: { start: "2018-08-31", end: "2018-09-03" },
  },
};

const OCCASION_NAMES = Object.keys(OCCASIONS);
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function monthValueForRange(startDate: string, endDate: string): string {
  if (!startDate || !endDate) return "";
  const [year, month] = startDate.split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  return startDate === `${year}-${String(month).padStart(2, "0")}-01` && endDate === `${year}-${String(month).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`
    ? `${year}-${String(month).padStart(2, "0")}`
    : "";
}

function yearsThrough(latestAvailableDate?: string): number[] {
  if (!latestAvailableDate) return YEARS;
  const latestYear = Number(latestAvailableDate.slice(0, 4));
  return YEARS.filter((year) => year <= latestYear);
}

function occasionYearsThrough(name: string, latestAvailableDate?: string): number[] {
  return yearsThrough(latestAvailableDate).filter((year) => {
    const window = OCCASIONS[name]?.[year];
    return Boolean(window && (!latestAvailableDate || window.end <= latestAvailableDate));
  });
}

function detectMode(startDate: string, endDate: string, publicModes: boolean, latestAvailableDate?: string): Mode {
  if (!startDate && !endDate) return publicModes ? "all" : "year";
  if (publicModes && monthValueForRange(startDate, endDate)) return "month";
  for (const year of yearsThrough(latestAvailableDate)) {
    const yearEnd = latestAvailableDate?.startsWith(`${year}-`) ? latestAvailableDate : `${year}-12-31`;
    if (startDate === `${year}-01-01` && endDate === yearEnd) return "year";
  }
  for (const name of OCCASION_NAMES) {
    for (const year of occasionYearsThrough(name, latestAvailableDate)) {
      const w = OCCASIONS[name][year];
      if (w && w.start === startDate && w.end === endDate) return "occasion";
    }
  }
  return "custom";
}

export default function DateRangePreset({
  startDate,
  endDate,
  onChange,
  onReadyChange,
  includeAllTimeAndMonth = false,
  latestAvailableDate,
}: {
  startDate: string;
  endDate: string;
  onChange: (start: string, end: string) => void;
  onReadyChange?: (ready: boolean) => void;
  includeAllTimeAndMonth?: boolean;
  latestAvailableDate?: string;
}) {
  const [mode, setMode] = useState<Mode>(() => detectMode(startDate, endDate, includeAllTimeAndMonth, latestAvailableDate));
  const [occasion, setOccasion] = useState<string>(OCCASION_NAMES[0]);
  const years = yearsThrough(latestAvailableDate);
  const withinCoverage = !latestAvailableDate || !endDate || endDate <= latestAvailableDate;
  const rangeReady = !includeAllTimeAndMonth || mode === "all" || Boolean(startDate && endDate && startDate <= endDate && withinCoverage);

  useEffect(() => {
    onReadyChange?.(rangeReady);
  }, [onReadyChange, rangeReady]);

  useEffect(() => {
    if (!includeAllTimeAndMonth || !latestAvailableDate) return;
    if (startDate && startDate > latestAvailableDate) onChange(latestAvailableDate, latestAvailableDate);
    else if (endDate && endDate > latestAvailableDate) onChange(startDate, latestAvailableDate);
  }, [endDate, includeAllTimeAndMonth, latestAvailableDate, onChange, startDate]);

  function selectMonth(value: string) {
    if (!value) {
      onChange("", "");
      return;
    }
    const [year, month] = value.split("-").map(Number);
    const lastDay = new Date(year, month, 0).getDate();
    onChange(`${year}-${String(month).padStart(2, "0")}-01`, `${year}-${String(month).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`);
  }

  function selectYear(year: string) {
    if (!year) {
      onChange("", "");
      return;
    }
    const yearEnd = latestAvailableDate?.startsWith(`${year}-`) ? latestAvailableDate : `${year}-12-31`;
    onChange(`${year}-01-01`, yearEnd);
  }

  function selectOccasionYear(occasionName: string, year: string) {
    const w = OCCASIONS[occasionName]?.[Number(year)];
    if (w) onChange(w.start, w.end);
  }

  const matchedYear = years.find((y) => {
    const yearEnd = latestAvailableDate?.startsWith(`${y}-`) ? latestAvailableDate : `${y}-12-31`;
    return startDate === `${y}-01-01` && endDate === yearEnd;
  });
  let matchedOccasionYear: number | undefined;
  for (const y of occasionYearsThrough(occasion, latestAvailableDate)) {
    const w = OCCASIONS[occasion]?.[y];
    if (w && w.start === startDate && w.end === endDate) matchedOccasionYear = y;
  }

  return (
    <>
      <label className="filter-field">
        <span className="filter-label">Filter by</span>
        <select
          value={mode}
          onChange={(e) => {
            const next = e.target.value as Mode;
            setMode(next);
            if (includeAllTimeAndMonth) {
              if (next === "all" || next === "month" || next === "occasion" || next === "custom") onChange("", "");
              if (next === "year") selectYear("");
            } else {
              if (next === "year") selectYear("");
              if (next === "custom") onChange("", "");
            }
          }}
        >
          {includeAllTimeAndMonth && <option value="all">All time</option>}
          <option value="year">Year</option>
          {includeAllTimeAndMonth && <option value="month">Month</option>}
          <option value="occasion">{includeAllTimeAndMonth ? "Holiday / occasion" : "Occasion"}</option>
          <option value="custom">{includeAllTimeAndMonth ? "Custom dates" : "Custom"}</option>
        </select>
      </label>

      {includeAllTimeAndMonth && mode === "all" && <span className="filter-field filter-period-note"><span className="filter-label">Selected period</span><strong>All available history</strong></span>}

      {mode === "year" && (
        <label className="filter-field">
          <span className="filter-label">Year</span>
          <select value={matchedYear ?? ""} onChange={(e) => selectYear(e.target.value)}>
            <option value="">{includeAllTimeAndMonth ? "Choose a year" : "All time"}</option>
            {years.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </label>
      )}

      {mode === "month" && (
        <label className="filter-field">
          <span className="filter-label">Month</span>
          <select value={monthValueForRange(startDate, endDate)} onChange={(e) => selectMonth(e.target.value)}>
            <option value="">Choose a month</option>
            {years.flatMap((year) => MONTH_NAMES.map((name, index) => {
              const month = String(index + 1).padStart(2, "0");
              if (latestAvailableDate && `${year}-${month}` > latestAvailableDate.slice(0, 7)) return [];
              return <option key={`${year}-${month}`} value={`${year}-${month}`}>{name} {year}</option>;
            }))}
          </select>
        </label>
      )}

      {mode === "occasion" && (
        <>
          <label className="filter-field">
            <span className="filter-label">Occasion</span>
            <select
              value={occasion}
              onChange={(e) => {
                setOccasion(e.target.value);
                onChange("", "");
              }}
            >
              {OCCASION_NAMES.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span className="filter-label">Year</span>
            <select
              value={matchedOccasionYear ?? ""}
              onChange={(e) => selectOccasionYear(occasion, e.target.value)}
            >
              <option value="">Select year</option>
              {occasionYearsThrough(occasion, latestAvailableDate).map((y) => (
                <option key={y} value={y}>
                  {occasion === "Christmas / New Year" ? `${y}\u2013${y + 1}` : y}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      {mode === "custom" && (
        <>
          <label className="filter-field">
            <span className="filter-label">From</span>
            <input
              type="date"
              value={startDate}
              min="2018-01-01"
              max={includeAllTimeAndMonth ? endDate || latestAvailableDate : undefined}
              onChange={(e) => onChange(e.target.value, endDate)}
            />
          </label>
          <label className="filter-field">
            <span className="filter-label">To</span>
            <input
              type="date"
              value={endDate}
              min={includeAllTimeAndMonth ? startDate || "2018-01-01" : "2018-01-01"}
              max={includeAllTimeAndMonth ? latestAvailableDate : undefined}
              onChange={(e) => onChange(startDate, e.target.value)}
            />
          </label>
        </>
      )}
    </>
  );
}
