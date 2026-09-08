"""
calibrate_health_score.py

Derives health-score component weights from real predictive power instead
of hand-picked numbers.

Methodology: split each route's flight history chronologically into an
"early" period and a "late" period. Compute the 5 raw component metrics
(on-time rate, avg delay, severe-delay rate, cancellation rate, diversion
rate) from the EARLY period only. Compute the actual on-time rate the same
route went on to have in the LATE period -- this is the real-world outcome
we're trying to predict.

For each component, compute its correlation with that real future outcome.
A component that strongly predicts future performance gets a high weight;
one that doesn't gets a low weight. This directly tests "does knowing this
about a route's past actually tell you something about its future" rather
than assuming a formula is right because it looks reasonable.

Run from the repo root: python calibrate_health_score.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb
import numpy as np
import pandas as pd

from config import DUCKDB_FILE
from api.metrics import COMPLETED_FLIGHT_SQL, ON_TIME_FLAG_SQL, SEVERE_DELAY_SQL

MIN_FLIGHTS_PER_PERIOD = 100  # only include routes with enough data in both periods
EARLY_PERIOD_FRACTION = 0.70  # first 70% of the calendar range = "early"


def main():
    print("=" * 60)
    print("  HEALTH SCORE WEIGHT CALIBRATION")
    print("=" * 60)

    conn = duckdb.connect(str(DUCKDB_FILE), read_only=True)

    date_range = conn.execute("SELECT MIN(FlightDate), MAX(FlightDate) FROM flights").fetchone()
    start_date, end_date = date_range
    total_days = (end_date - start_date).days
    split_date = start_date + pd.Timedelta(days=int(total_days * EARLY_PERIOD_FRACTION))

    print(f"\n  Full range: {start_date} to {end_date}")
    print(f"  Early period: {start_date} to {split_date}")
    print(f"  Late period:  {split_date} to {end_date}")

    def period_stats(where_extra: str, params: list) -> pd.DataFrame:
        query = f"""
            SELECT
                Origin, Dest,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN {COMPLETED_FLIGHT_SQL}
                    THEN CASE WHEN {ON_TIME_FLAG_SQL} THEN 1.0 ELSE 0.0 END END) * 100 AS on_time_pct,
                AVG(CASE WHEN {COMPLETED_FLIGHT_SQL}
                    THEN ArrDelay END) AS avg_delay,
                AVG(CASE WHEN {SEVERE_DELAY_SQL} THEN 1.0
                    WHEN {COMPLETED_FLIGHT_SQL} THEN 0.0 END) * 100 AS severe_delay_pct,
                AVG(Cancelled) * 100 AS cancellation_pct,
                AVG(Diverted) * 100 AS diversion_pct
            FROM flights
            WHERE Origin IS NOT NULL AND Dest IS NOT NULL {where_extra}
            GROUP BY Origin, Dest
            HAVING COUNT(*) >= {MIN_FLIGHTS_PER_PERIOD}
        """
        return conn.execute(query, params).fetchdf()

    print("\n  Computing early-period component metrics per route...")
    early = period_stats("AND FlightDate < CAST(? AS DATE)", [split_date])

    print("  Computing late-period actual outcomes per route...")
    late = period_stats("AND FlightDate >= CAST(? AS DATE)", [split_date])

    merged = early.merge(
        late[["Origin", "Dest", "on_time_pct"]],
        on=["Origin", "Dest"],
        suffixes=("_early", "_future"),
    )
    print(f"\n  Routes with sufficient data in both periods: {len(merged)}")

    if len(merged) < 30:
        print("  WARNING: very few qualifying routes -- results may be unstable.")
        print("  Consider lowering MIN_FLIGHTS_PER_PERIOD if this looks too small.")

    # Convert each early-period raw metric into the same 0-100 component-score
    # shape the current formula uses, so weights stay comparable to before.
    def clamp(s):
        return s.clip(0, 100)

    components = pd.DataFrame({
        "reliability": clamp(merged["on_time_pct_early"]),
        "delay_severity": clamp(100 - merged["avg_delay"].clip(lower=0) * 2),
        "severe_delay_exposure": clamp(100 - merged["severe_delay_pct"] * 5),
        "cancellation_resilience": clamp(100 - merged["cancellation_pct"] * 10),
        "diversion_resilience": clamp(100 - merged["diversion_pct"] * 20),
    })
    future_outcome = merged["on_time_pct_future"]

    print("\n" + "=" * 60)
    print("  CORRELATION WITH ACTUAL FUTURE ON-TIME RATE")
    print("=" * 60)

    correlations = {}
    for col in components.columns:
        valid = components[col].notna() & future_outcome.notna()
        corr = np.corrcoef(components.loc[valid, col], future_outcome[valid])[0, 1]
        correlations[col] = corr
        print(f"  {col:28s}  r = {corr:+.3f}")

    # Weight each component by its correlation strength (only positive
    # correlations count as genuine predictive signal; a component that's
    # uncorrelated or negatively correlated with future performance
    # shouldn't get positive weight).
    positive = {k: max(v, 0) for k, v in correlations.items()}
    total = sum(positive.values())

    if total == 0:
        print("\n  No component showed positive predictive correlation. Keeping equal weights.")
        weights = {k: 0.20 for k in components.columns}
    else:
        weights = {k: round(v / total, 3) for k, v in positive.items()}

    print("\n" + "=" * 60)
    print("  CALIBRATED WEIGHTS (normalized to sum to 1.0)")
    print("=" * 60)
    for k, v in weights.items():
        print(f"  {k:28s}  {v:.3f}  ({v*100:.1f}%)")
    print(f"\n  Sum check: {sum(weights.values()):.3f}")

    conn.close()

    print("\n  Done. Report these weights back -- they'll be used to update")
    print("  api/health_score.py with data-derived weights instead of the")
    print("  original hand-picked 35/25/15/15/10 split.")


if __name__ == "__main__":
    main()
