from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb

from config import DUCKDB_FILE


CORE_FLIGHT_TABLE = "analytics_flight_core"


def best_flight_table(connection: duckdb.DuckDBPyConnection, required_columns: set[str] | None = None) -> str:
    """Choose the compact OTP projection when it can answer a query.

    ``flights`` stays the source of truth and remains the fallback for older
    warehouses or specialist queries that need a column not retained in the
    explicit core projection. Keeping this decision in one place prevents
    individual endpoints from silently drifting between data contracts.
    """
    required = required_columns or set()
    table_exists = connection.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = ?
        """,
        [CORE_FLIGHT_TABLE],
    ).fetchone()[0] > 0
    if not table_exists:
        return "flights"

    if not required:
        return CORE_FLIGHT_TABLE

    core_columns = {
        row[0] for row in connection.execute(f"DESCRIBE {CORE_FLIGHT_TABLE}").fetchall()
    }
    return CORE_FLIGHT_TABLE if required.issubset(core_columns) else "flights"


def database_path() -> Path:
    return Path(DUCKDB_FILE)


def connect_readonly() -> duckdb.DuckDBPyConnection:
    """Return a read-only DuckDB connection to the warehouse."""
    return duckdb.connect(str(database_path()), read_only=True)


@contextmanager
def open_readonly_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = connect_readonly()
    try:
        yield connection
    finally:
        connection.close()
