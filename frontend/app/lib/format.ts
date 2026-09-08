function asFiniteNumber(value: unknown): number | null {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function formatNumber(value: unknown, digits = 1, fallback = "—"): string {
  const numeric = asFiniteNumber(value);
  return numeric === null ? fallback : numeric.toFixed(digits);
}

export function formatInteger(value: unknown, fallback = "—"): string {
  const numeric = asFiniteNumber(value);
  return numeric === null ? fallback : numeric.toLocaleString();
}

/** Format a ratio such as 0.8043 as a percentage. */
export function formatPercent(value: unknown, digits = 1, fallback = "—"): string {
  const numeric = asFiniteNumber(value);
  return numeric === null ? fallback : (numeric * 100).toFixed(digits) + "%";
}
