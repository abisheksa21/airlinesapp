"""Check, clean, and load newly published monthly BTS T-100 data.

This is intentionally separate from ``pipeline.auto_update`` because T-100
is a monthly aggregate and must never be appended to the flight-level OTP
table.  A scheduled or manual run checks each T-100 dataset independently,
stops at the first month BTS has not published, and reloads only that
dataset's table and route-month view when a verified ZIP is available.

Run from the repository root::

    python -m pipeline.auto_update_bts

The script is safe when nothing new is available: it records the check and
leaves the warehouse untouched.  It never fabricates a missing month.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from config import DATA_DIR, DUCKDB_FILE, LOG_DIR, T100_PIPELINE_STATE_FILE
from pipeline.bts_sources import BtsDataset, get_dataset


TABLE_NAMES = {
    "t100_segment": "bts_t100_segment",
    "t100_market": "bts_t100_market",
}


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"auto_update_t100_{date.today().isoformat()}.log"
    logger = logging.getLogger("auto_update_t100")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def load_state() -> dict:
    try:
        payload = json.loads(T100_PIPELINE_STATE_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = T100_PIPELINE_STATE_FILE.with_name(f"{T100_PIPELINE_STATE_FILE.name}.part")
    temporary.write_text(json.dumps(state, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, T100_PIPELINE_STATE_FILE)


def next_period(period: tuple[int, int]) -> tuple[int, int]:
    year, month = period
    return (year + 1, 1) if month == 12 else (year, month + 1)


def periods_to_check(
    latest: tuple[int, int] | None,
    today: date | None = None,
) -> list[tuple[int, int]]:
    """Return months after ``latest`` through the last complete month.

    ``today`` is injectable for deterministic tests.  The current month is
    excluded because BTS cannot publish a complete monthly T-100 file for it.
    """
    today = today or date.today()
    cutoff = (today.year, today.month)
    cursor = (today.year, 1) if latest is None else next_period(latest)
    candidates: list[tuple[int, int]] = []
    while cursor < cutoff:
        candidates.append(cursor)
        cursor = next_period(cursor)
    return candidates


def latest_loaded_period(dataset_key: str, logger: logging.Logger | None = None) -> tuple[int, int] | None:
    """Read the source-of-truth latest period from the T-100 warehouse table."""
    table = TABLE_NAMES[dataset_key]
    if not DUCKDB_FILE.exists():
        return None
    try:
        connection = duckdb.connect(str(DUCKDB_FILE), read_only=True)
        try:
            exists = connection.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [table],
            ).fetchone()[0]
            if not exists:
                return None
            value = connection.execute(
                f"SELECT MAX(Year * 100 + Month) FROM {table}"
            ).fetchone()[0]
        finally:
            connection.close()
        if value is None:
            return None
        value = int(value)
        return value // 100, value % 100
    except Exception as exc:
        if logger:
            logger.error("Could not read latest %s period: %s: %s", dataset_key, type(exc).__name__, exc)
        raise


def _record_clean_manifest(result: dict, dataset_key: str) -> None:
    """Add one processed ZIP to the provenance manifest without re-cleaning history."""
    from pipeline.clean_bts import _load_manifest, _save_manifest

    manifest = _load_manifest()
    raw_file = result.get("raw_file")
    entries = [
        entry
        for entry in manifest.get("files", [])
        if not (entry.get("dataset") == dataset_key and entry.get("raw_file") == raw_file)
    ]
    entries.append(result)
    manifest["files"] = sorted(
        entries,
        key=lambda entry: (
            entry.get("dataset", ""),
            entry.get("period") or "",
            entry.get("raw_file", ""),
        ),
    )
    _save_manifest(manifest)


def _load_dataset(dataset_key: str, logger: logging.Logger) -> dict:
    from pipeline.load_bts import load_bts_tables

    if not DUCKDB_FILE.exists():
        raise RuntimeError(f"Warehouse not found at {DUCKDB_FILE}; build flights first.")
    connection = duckdb.connect(str(DUCKDB_FILE), read_only=False)
    try:
        connection.execute("BEGIN")
        summaries = load_bts_tables(connection, [dataset_key])
        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        connection.close()
    summary = summaries[0]
    logger.info(
        "Reloaded %s: %s (%s rows).",
        dataset_key,
        summary["status"],
        f"{summary.get('rows', 0):,}",
    )
    return summary


def check_dataset(
    dataset_key: str,
    logger: logging.Logger,
    today: date | None = None,
) -> dict:
    """Check one T-100 dataset and return a serializable run summary."""
    dataset: BtsDataset = get_dataset(dataset_key)
    latest_before = latest_loaded_period(dataset_key, logger)
    candidates = periods_to_check(latest_before, today)
    result = {
        "dataset": dataset_key,
        "latest_before": f"{latest_before[0]}-{latest_before[1]:02d}" if latest_before else None,
        "latest_after": None,
        "status": "up_to_date" if not candidates else "checked",
        "attempted_period": None,
        "months_added": [],
        "error": None,
    }
    if not candidates:
        result["latest_after"] = result["latest_before"]
        logger.info("%s is current through the last complete month.", dataset.label)
        return result

    # Heavy imports stay inside the operation so lightweight helper tests and
    # health checks do not require Selenium or pandas just to inspect periods.
    from pipeline.clean_bts import process_zip
    from pipeline.download_bts import download_dataset

    for year, month in candidates:
        period_label = f"{year}-{month:02d}"
        result["attempted_period"] = period_label
        logger.info("Checking %s for %s...", dataset.label, period_label)
        try:
            files = download_dataset(dataset, years=[year], months=[month])
        except TimeoutError as exc:
            result["status"] = "not_published"
            result["error"] = str(exc)
            logger.info("%s is not available yet: %s", period_label, exc)
            break
        except Exception as exc:
            result["status"] = "error"
            result["error"] = f"{type(exc).__name__}: {exc}"
            logger.error("T-100 check failed for %s: %s", period_label, exc)
            break

        if not files:
            result["status"] = "not_published"
            logger.info("%s is not published yet; stopping in order.", period_label)
            break

        try:
            cleaned = process_zip(files[0], dataset)
            _record_clean_manifest(cleaned, dataset_key)
        except Exception as exc:
            result["status"] = "clean_failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
            logger.error("T-100 cleaning failed for %s: %s", period_label, exc)
            break

        result["months_added"].append(period_label)
        result["status"] = "new_data"

    if result["months_added"]:
        try:
            _load_dataset(dataset_key, logger)
        except Exception as exc:
            result["status"] = "load_failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
            logger.error("T-100 warehouse load failed for %s: %s", dataset_key, exc)

    latest_after = latest_loaded_period(dataset_key, logger)
    result["latest_after"] = f"{latest_after[0]}-{latest_after[1]:02d}" if latest_after else None
    return result


def main() -> int:
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("AUTOMATED BTS T-100 DATA CHECK STARTING")
    logger.info("=" * 60)
    state = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "result": "running",
        "datasets": {},
        "months_added": [],
    }
    save_state(state)

    overall = "up_to_date"
    try:
        for dataset_key in ("t100_segment", "t100_market"):
            dataset_result = check_dataset(dataset_key, logger)
            state["datasets"][dataset_key] = dataset_result
            state["months_added"].extend(
                f"{dataset_key}:{period}" for period in dataset_result["months_added"]
            )
            if dataset_result["status"] in {"error", "clean_failed", "load_failed"}:
                overall = "error"
            elif dataset_result["status"] == "new_data" and overall != "error":
                overall = "success"
            elif dataset_result["status"] == "not_published" and overall == "up_to_date":
                overall = "not_published"
    except Exception as exc:
        logger.exception("T-100 update stopped unexpectedly: %s", exc)
        overall = "error"

    state["result"] = overall
    save_state(state)
    logger.info("T-100 check complete: %s. Added: %s", overall, state["months_added"] or "none")
    return 1 if overall == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
