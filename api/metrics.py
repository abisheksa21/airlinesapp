"""Canonical metric definitions shared by API and model code.

Keep the business meaning of a flight in one place. BTS exposes the
``ArrDel15`` indicator, so the application uses that official flag for the
on-time metric everywhere rather than mixing it with hand-written delay
comparisons at the exact 15-minute boundary.
"""

from __future__ import annotations

from config import MAJOR_DELAY


# SQL fragments are intentionally small and contain no user input. Callers
# still bind all dates, codes, and other request values separately.
ON_TIME_FLAG_SQL = "ArrDel15 = 0"
COMPLETED_FLIGHT_SQL = "Cancelled = 0 AND Diverted = 0 AND ArrDelay IS NOT NULL"
SEVERE_DELAY_SQL = f"{COMPLETED_FLIGHT_SQL} AND ArrDelay > {MAJOR_DELAY}"


def on_time_indicator_sql() -> str:
    """Return the canonical 0/1 on-time indicator expression."""
    return f"CASE WHEN {ON_TIME_FLAG_SQL} THEN 1.0 ELSE 0.0 END"


def completed_on_time_case_sql() -> str:
    """Return an indicator that is NULL for non-completed flights."""
    return f"CASE WHEN {COMPLETED_FLIGHT_SQL} THEN {on_time_indicator_sql()} END"


def severe_delay_indicator_sql() -> str:
    """Return an indicator that is NULL for non-completed flights."""
    return f"CASE WHEN {SEVERE_DELAY_SQL} THEN 1.0 WHEN {COMPLETED_FLIGHT_SQL} THEN 0.0 END"
