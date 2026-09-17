"""Read helpers for the compact dashboard aggregate tables."""

from __future__ import annotations

from typing import Any

from api.health_score import score_from_row


def table_exists(connection: Any, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and row[0])


def network_summary(connection: Any) -> dict[str, Any] | None:
    if not table_exists(connection, "analytics_network_month"):
        return None
    row = connection.execute(
        """
        SELECT
            SUM(total_flights),
            MIN(year_month) || '-01',
            last_day(CAST(MAX(year_month) || '-01' AS DATE)),
            SUM(completed_flights * on_time_rate) / NULLIF(SUM(completed_flights), 0),
            SUM(completed_flights * avg_arrival_delay_minutes) / NULLIF(SUM(completed_flights), 0),
            SUM(total_flights * cancellation_rate) / NULLIF(SUM(total_flights), 0),
            SUM(unique_routes)
        FROM analytics_network_month
        """
    ).fetchone()
    if not row or not row[0]:
        return None
    unique_routes = connection.execute(
        "SELECT COUNT(DISTINCT origin || '-' || dest) FROM analytics_route_month"
    ).fetchone()[0]
    unique_airports = connection.execute(
        "SELECT COUNT(DISTINCT airport) FROM analytics_airport_month"
    ).fetchone()[0]
    carrier_count = connection.execute(
        "SELECT COUNT(DISTINCT carrier) FROM analytics_carrier_month"
    ).fetchone()[0]
    return {
        "total_flights": int(row[0]),
        "start_date": str(row[1]),
        "end_date": str(row[2]),
        "on_time_rate": row[3],
        "avg_arrival_delay_minutes": row[4],
        "cancellation_rate": row[5],
        "unique_routes": int(unique_routes or 0),
        "unique_airports": int(unique_airports or 0),
        "carrier_count": int(carrier_count or 0),
    }


def network_trend(connection: Any, carrier: str | None = None) -> list[dict[str, Any]] | None:
    table = "analytics_carrier_month" if carrier else "analytics_network_month"
    if not table_exists(connection, table):
        return None
    if carrier:
        rows = connection.execute(
            """
            SELECT
                year_month,
                SUM(total_flights),
                SUM(completed_flights * on_time_rate) / NULLIF(SUM(completed_flights), 0)
            FROM analytics_carrier_month
            WHERE carrier = ?
            GROUP BY year_month
            ORDER BY year_month
            """,
            [carrier.upper()],
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT year_month, total_flights, on_time_rate
            FROM analytics_network_month
            ORDER BY year_month
            """
        ).fetchall()
    return [
        {"month": str(row[0]), "total_flights": int(row[1]), "on_time_rate": row[2]}
        for row in rows
    ]


def carrier_ranking(connection: Any) -> list[dict[str, Any]] | None:
    if not table_exists(connection, "analytics_carrier_month"):
        return None
    rows = connection.execute(
        """
        SELECT
            carrier,
            SUM(total_flights),
            SUM(completed_flights * on_time_rate) / NULLIF(SUM(completed_flights), 0),
            SUM(completed_flights * avg_arrival_delay_minutes) / NULLIF(SUM(completed_flights), 0),
            SUM(total_flights * cancellation_rate) / NULLIF(SUM(total_flights), 0)
        FROM analytics_carrier_month
        GROUP BY carrier
        ORDER BY SUM(completed_flights * on_time_rate) / NULLIF(SUM(completed_flights), 0) DESC
        """
    ).fetchall()
    return [
        {
            "carrier": row[0],
            "total_flights": int(row[1]),
            "on_time_rate": row[2],
            "avg_arrival_delay_minutes": row[3],
            "cancellation_rate": row[4],
        }
        for row in rows
    ]


def route_ranking(connection: Any, limit: int) -> list[dict[str, Any]] | None:
    if not table_exists(connection, "analytics_route_month"):
        return None
    rows = connection.execute(
        """
        SELECT
            origin || ' → ' || dest AS route,
            SUM(total_flights),
            SUM(completed_flights * on_time_rate) / NULLIF(SUM(completed_flights), 0)
        FROM analytics_route_month
        GROUP BY origin, dest
        ORDER BY SUM(total_flights) DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [
        {"route": row[0], "total_flights": int(row[1]), "on_time_rate": row[2]}
        for row in rows
    ]


def airport_ranking(connection: Any, limit: int) -> list[dict[str, Any]] | None:
    if not table_exists(connection, "analytics_airport_month"):
        return None
    rows = connection.execute(
        """
        SELECT airport, SUM(total_flights)
        FROM analytics_airport_month
        GROUP BY airport
        ORDER BY SUM(total_flights) DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [{"airport": row[0], "total_flights": int(row[1])} for row in rows]


def airport_list(connection: Any) -> list[str] | None:
    if not table_exists(connection, "analytics_airport_month"):
        return None
    rows = connection.execute(
        "SELECT DISTINCT airport FROM analytics_airport_month ORDER BY airport"
    ).fetchall()
    return [row[0] for row in rows]


def route_hour_baseline(
    connection: Any,
    origin: str,
    dest: str,
    carrier: str,
    departure_hour: int,
) -> dict[str, Any] | None:
    """Read the exact route/carrier/hour baseline from the compact table."""
    if not table_exists(connection, "analytics_route_hour"):
        return None
    row = connection.execute(
        """
        SELECT total_flights, completed_flights, on_time_rate,
               avg_arrival_delay_minutes, median_arrival_delay_minutes,
               p90_arrival_delay_minutes, cancellation_rate
        FROM analytics_route_hour
        WHERE origin = ? AND dest = ? AND carrier = ? AND departure_hour = ?
        """,
        [origin, dest, carrier, departure_hour],
    ).fetchone()
    if not row:
        return None
    return {
        "total_flights": int(row[0] or 0),
        "completed_flights": int(row[1] or 0),
        "on_time_rate": row[2],
        "avg_arrival_delay_minutes": row[3],
        "median_arrival_delay_minutes": row[4],
        "p90_arrival_delay_minutes": row[5],
        "cancellation_rate": row[6],
    }


# The profile tables are deliberately explicit.  They are a small, stable
# contract between the refresh pipeline and the public profile pages; the
# researcher endpoints continue to use their richer raw-flight path.
PROFILE_STAT_COLUMNS = (
    "total_flights",
    "completed_flights",
    "avg_arrival_delay",
    "var_arrival_delay",
    "on_time_percentage",
    "var_on_time_indicator",
    "severe_delay_percentage",
    "var_severe_indicator",
    "cancellation_percentage",
    "var_cancelled_indicator",
    "diversion_percentage",
    "var_diverted_indicator",
)


def _has_columns(connection: Any, table_name: str, required: set[str]) -> bool:
    if not table_exists(connection, table_name):
        return False
    columns = {row[0] for row in connection.execute(f"DESCRIBE {table_name}").fetchall()}
    return required.issubset(columns)


def _public_profile_health(connection: Any, table_name: str, key_column: str, key: str) -> dict | None:
    if not _has_columns(connection, table_name, set(PROFILE_STAT_COLUMNS) | {key_column}):
        return None
    row = connection.execute(
        f"SELECT {', '.join(PROFILE_STAT_COLUMNS)} FROM {table_name} WHERE {key_column} = ?",
        [key],
    ).fetchone()
    return score_from_row(row) if row else None


def carrier_public_profile(connection: Any, carrier: str) -> dict[str, Any] | None:
    """Return the compact, full-history payload needed by the public carrier page."""
    if not _has_columns(connection, "analytics_carrier_month", {"carrier", "year_month", "total_flights", "completed_flights", "on_time_rate", "avg_arrival_delay_minutes", "cancellation_rate"}):
        return None
    health = _public_profile_health(connection, "analytics_carrier_profile", "carrier", carrier)
    if health is None:
        return None
    row = connection.execute(
        """
        SELECT SUM(total_flights),
               SUM(completed_flights * on_time_rate) / NULLIF(SUM(completed_flights), 0),
               SUM(completed_flights * avg_arrival_delay_minutes) / NULLIF(SUM(completed_flights), 0),
               SUM(total_flights * cancellation_rate) / NULLIF(SUM(total_flights), 0)
        FROM analytics_carrier_month
        WHERE carrier = ?
        """,
        [carrier],
    ).fetchone()
    if not row or not row[0]:
        return None
    months = connection.execute(
        """
        SELECT year_month, total_flights, on_time_rate
        FROM analytics_carrier_month
        WHERE carrier = ?
        ORDER BY year_month
        """,
        [carrier],
    ).fetchall()
    return {
        "carrier": carrier,
        "total_flights": int(row[0]),
        "on_time_rate": row[1],
        "avg_arrival_delay_minutes": row[2],
        "cancellation_rate": row[3],
        "health": health,
        "months": [{"month": r[0], "total_flights": int(r[1]), "on_time_rate": r[2]} for r in months],
        "causes": [],
        "top_routes": [],
        "top_airports": [],
    }


def airport_public_profile(connection: Any, airport: str) -> dict[str, Any] | None:
    """Return the compact, full-history payload needed by the public airport page."""
    required_month_columns = {
        "airport", "year_month", "total_flights", "completed_flights", "on_time_rate",
        "avg_arrival_delay_minutes", "cancellation_rate",
    }
    if not _has_columns(connection, "analytics_airport_profile_month", required_month_columns):
        return None
    health = _public_profile_health(connection, "analytics_airport_profile", "airport", airport)
    if health is None:
        return None
    row = connection.execute(
        """
        SELECT SUM(total_flights),
               SUM(completed_flights * on_time_rate) / NULLIF(SUM(completed_flights), 0),
               SUM(completed_flights * avg_arrival_delay_minutes) / NULLIF(SUM(completed_flights), 0),
               SUM(total_flights * cancellation_rate) / NULLIF(SUM(total_flights), 0)
        FROM analytics_airport_profile_month
        WHERE airport = ?
        """,
        [airport],
    ).fetchone()
    if not row or not row[0]:
        return None
    months = connection.execute(
        """
        SELECT year_month, total_flights, on_time_rate
        FROM analytics_airport_profile_month
        WHERE airport = ?
        ORDER BY year_month
        """,
        [airport],
    ).fetchall()
    return {
        "airport": airport,
        "city": None,
        "state": None,
        "total_flights": int(row[0]),
        "on_time_rate": row[1],
        "avg_arrival_delay_minutes": row[2],
        "cancellation_rate": row[3],
        "health": health,
        "outbound": None,
        "inbound": None,
        "months": [{"month": r[0], "total_flights": int(r[1]), "on_time_rate": r[2]} for r in months],
        "causes": [],
        "top_routes": [],
    }
