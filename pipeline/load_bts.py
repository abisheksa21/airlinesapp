"""Load cleaned BTS enrichment datasets into the DuckDB warehouse.

The loader keeps enrichment tables independent from ``flights``.  In
particular, T-100 rows are monthly aggregates and are never joined directly
to flight rows in this module.  Consumers can join at a matching
carrier/route/month grain or query the supplied route-month views.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from config import DUCKDB_FILE
from pipeline.bts_sources import DATASETS, BtsDataset, get_dataset


TABLE_NAMES = {
    "t100_segment": "bts_t100_segment",
    "t100_market": "bts_t100_market",
    "carrier_decode": "bts_carrier_decode",
    "master_coordinate": "bts_master_coordinate",
    "aircraft_types": "bts_aircraft_types",
}


def _sql_table_name(dataset: BtsDataset) -> str:
    return TABLE_NAMES[dataset.key]


def _available(dataset: BtsDataset) -> bool:
    return dataset.clean_dir.exists() and any(dataset.clean_dir.glob("*.csv"))


def _sql_path(path: Path) -> str:
    """Return a safe SQL string literal for a local CSV path."""
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _configure_connection(connection: duckdb.DuckDBPyConnection) -> None:
    """Keep large BTS imports bounded on laptops with an existing warehouse."""
    memory_limit = os.getenv("BTS_DUCKDB_MEMORY_LIMIT", "1GB").replace("'", "''")
    connection.execute(f"SET memory_limit = '{memory_limit}'")
    connection.execute("SET threads = 1")
    connection.execute("SET preserve_insertion_order = false")


def _load_one(connection: duckdb.DuckDBPyConnection, dataset: BtsDataset) -> dict:
    if not _available(dataset):
        return {"dataset": dataset.key, "status": "not_available", "rows": 0}

    table = _sql_table_name(dataset)
    clean_files = sorted(dataset.clean_dir.glob("*.csv"))
    # Reading a glob in one statement makes DuckDB infer and buffer every
    # monthly file at once.  That is fine for a small pilot, but can exceed
    # laptop memory when the warehouse already contains the flight history.
    # Import one cleaned file at a time instead; BY NAME also protects against
    # harmless column-order differences between BTS releases.
    first_file, *remaining_files = clean_files
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE {table} AS
        SELECT *
        FROM read_csv_auto(
            '{_sql_path(first_file)}',
            header = true,
            strict_mode = false,
            null_padding = true
        )
        """
    )
    for clean_file in remaining_files:
        connection.execute(
            f"""
            INSERT INTO {table} BY NAME
            SELECT *
            FROM read_csv_auto(
                '{_sql_path(clean_file)}',
                header = true,
                strict_mode = false,
                null_padding = true
            )
            """
        )
    row_count = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    schema = [row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()]
    return {
        "dataset": dataset.key,
        "label": dataset.label,
        "table_name": table,
        "status": "loaded",
        "rows": row_count,
        "columns": schema,
    }


def _create_derived_views(connection: duckdb.DuckDBPyConnection, loaded: set[str]) -> None:
    if "t100_segment" in loaded:
        connection.execute(
            """
            CREATE OR REPLACE VIEW bts_t100_segment_route_month AS
            SELECT
                Year,
                Month,
                UniqueCarrier,
                AirlineID,
                OriginAirportID,
                DestAirportID,
                Origin,
                Dest,
                SUM(DepScheduled) AS departures_scheduled,
                SUM(DepPerformed) AS departures_performed,
                SUM(Seats) AS seats_available,
                SUM(Passengers) AS passengers,
                SUM(Freight) AS freight,
                SUM(Mail) AS mail,
                SUM(Distance * DepPerformed) / NULLIF(SUM(DepPerformed), 0) AS distance_miles,
                SUM(Passengers) / NULLIF(SUM(Seats), 0) AS load_factor,
                SUM(DepPerformed) / NULLIF(SUM(DepScheduled), 0) AS completion_rate,
                COUNT(*) AS source_rows
            FROM bts_t100_segment
            GROUP BY ALL
            """
        )

    if "t100_market" in loaded:
        connection.execute(
            """
            CREATE OR REPLACE VIEW bts_t100_market_route_month AS
            SELECT
                Year,
                Month,
                UniqueCarrier,
                AirlineID,
                OriginAirportID,
                DestAirportID,
                Origin,
                Dest,
                SUM(Passengers) AS passengers,
                SUM(Freight) AS freight,
                SUM(Mail) AS mail,
                SUM(Distance * Passengers) / NULLIF(SUM(Passengers), 0) AS distance_miles,
                COUNT(*) AS source_rows
            FROM bts_t100_market
            GROUP BY ALL
            """
        )


def _write_manifest_table(connection: duckdb.DuckDBPyConnection, summaries: list[dict]) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS bts_dataset_manifest (
            dataset VARCHAR PRIMARY KEY,
            label VARCHAR,
            table_name VARCHAR,
            grain VARCHAR,
            source_url VARCHAR,
            status VARCHAR,
            row_count BIGINT,
            columns_json VARCHAR,
            loaded_at_utc TIMESTAMP
        )
        """
    )
    loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for summary in summaries:
        dataset = DATASETS[summary["dataset"]]
        connection.execute(
            "DELETE FROM bts_dataset_manifest WHERE dataset = ?",
            [dataset.key],
        )
        connection.execute(
            """
            INSERT INTO bts_dataset_manifest
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                dataset.key,
                dataset.label,
                summary.get("table_name"),
                dataset.grain,
                dataset.url,
                summary["status"],
                summary.get("rows", 0),
                json.dumps(summary.get("columns", [])),
                loaded_at,
            ],
        )


def load_bts_tables(
    connection: duckdb.DuckDBPyConnection,
    dataset_keys: list[str] | None = None,
) -> list[dict]:
    """Load available cleaned datasets into an open DuckDB connection.

    This function does not commit or roll back.  Callers can include it in a
    larger atomic warehouse build, which is how ``build_warehouse`` uses it.
    """
    _configure_connection(connection)
    keys = dataset_keys or sorted(DATASETS)
    datasets = [get_dataset(key) for key in keys]
    summaries = [_load_one(connection, dataset) for dataset in datasets]
    loaded = {summary["dataset"] for summary in summaries if summary["status"] == "loaded"}
    _create_derived_views(connection, loaded)
    _write_manifest_table(connection, summaries)
    return summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load cleaned BTS datasets into DuckDB")
    parser.add_argument(
        "datasets",
        nargs="*",
        choices=sorted(DATASETS),
        help="datasets to load; omit to load every dataset that has clean CSVs",
    )
    args = parser.parse_args(argv)
    if not DUCKDB_FILE.exists():
        raise RuntimeError(f"Warehouse not found at {DUCKDB_FILE}; build flights first.")

    connection = duckdb.connect(str(DUCKDB_FILE), read_only=False)
    try:
        connection.execute("BEGIN")
        summaries = load_bts_tables(connection, args.datasets or None)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    for summary in summaries:
        print(
            f"{summary['dataset']}: {summary['status']} "
            f"({summary.get('rows', 0):,} rows)"
        )
    print(f"Warehouse updated: {DUCKDB_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
