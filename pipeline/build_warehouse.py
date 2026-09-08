import os
import uuid
from pathlib import Path

import duckdb

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import CLEAN_DIR, DUCKDB_FILE
from pipeline.load_bts import load_bts_tables
from pipeline.materialize_analytics import build_analytics_tables


def main() -> None:
    print("=" * 60)
    print("BUILDING DUCKDB WAREHOUSE")
    print("=" * 60)

    clean_files = sorted(CLEAN_DIR.glob("OTP_*.csv"))
    if not clean_files:
        raise RuntimeError(f"No cleaned CSV files found in {CLEAN_DIR}. Run pipeline.clean first.")

    clean_pattern = str(CLEAN_DIR / "OTP_*.csv")

    print(f"Source files : {clean_pattern}")
    print(f"Database     : {DUCKDB_FILE}")

    DUCKDB_FILE.parent.mkdir(parents=True, exist_ok=True)
    staging_path = DUCKDB_FILE.with_name(
        f"{DUCKDB_FILE.stem}.staging-{os.getpid()}-{uuid.uuid4().hex[:10]}{DUCKDB_FILE.suffix}"
    )
    connection = duckdb.connect(str(staging_path))
    row_count = 0
    column_count = 0

    try:
        connection.execute(
            """
            CREATE TABLE flights AS
            SELECT *
            FROM read_csv_auto(
                ?,
                union_by_name = true,
                header = true
            )
            """,
            [clean_pattern],
        )

        row_count = connection.execute(
            "SELECT COUNT(*) FROM flights"
        ).fetchone()[0]

        schema_rows = connection.execute("DESCRIBE flights").fetchall()
        columns = {row[0] for row in schema_rows}
        column_count = len(schema_rows)

        if row_count <= 0 or column_count <= 0:
            raise RuntimeError("Warehouse validation failed: the staged flights table is empty.")
        required_columns = {"FlightDate", "Origin", "Dest", "Cancelled", "Diverted", "ArrDel15"}
        missing_columns = required_columns - columns
        if missing_columns:
            raise RuntimeError(
                "Warehouse validation failed: missing required columns "
                + ", ".join(sorted(missing_columns))
            )

        # Enrichment tables are included in the same staged database when
        # cleaned BTS files are present. They remain separate from flights so
        # monthly T-100 aggregates cannot be mistaken for flight-level rows.
        enrichment_summaries = load_bts_tables(connection)
        loaded_enrichment = [
            summary for summary in enrichment_summaries if summary["status"] == "loaded"
        ]
        if loaded_enrichment:
            print(
                "Enrichment tables loaded: "
                + ", ".join(summary["dataset"] for summary in loaded_enrichment)
            )

        analytics_counts = build_analytics_tables(connection)
        print(
            "Analytics tables materialized: "
            + ", ".join(f"{table}={count:,}" for table, count in analytics_counts.items())
        )

        print(f"Rows loaded  : {row_count:,}")
        print(f"Columns      : {column_count}")

    except Exception:
        connection.close()
        if staging_path.exists():
            staging_path.unlink()
        raise
    finally:
        connection.close()

    # The old warehouse remains available until the staged file has loaded and
    # passed basic validation. os.replace is atomic on the same filesystem,
    # which prevents a failed rebuild from leaving the application without a
    # flights table.
    try:
        os.replace(staging_path, DUCKDB_FILE)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    print("Warehouse build complete. Staged database promoted atomically.")


if __name__ == "__main__":
    main()
