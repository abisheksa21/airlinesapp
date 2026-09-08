"""
pipeline/auto_update.py

Automated, unattended check for newly-published BTS monthly data. Designed
to run on a schedule (Windows Task Scheduler, cron, etc.) with no one
watching -- no input() prompts, headless browser, everything logged.

What it does:
1. Finds the latest month already in the warehouse (source of truth --
   not the Raw/Clean folders, which could be stale or manually touched).
2. Checks BTS for the next month(s) after that, one at a time, stopping as
   soon as one isn't published yet (BTS publishes in order, so there's no
   point checking further months once one comes back unavailable).
3. Downloads and cleans anything new (reusing the exact tested logic from
   pipeline/download.py and pipeline/clean.py -- not reimplemented here).
4. Only if something new was actually added: appends it to the
   warehouse incrementally (INSERT just the new rows), not a full
   rebuild -- a full rebuild re-reads every historical file just to add
   one new month, which is why an earlier version of this script took
   ~55 minutes for a single new month. A normal "nothing new today" run
   costs almost nothing either way.
5. Logs everything with timestamps to Logs/auto_update_YYYY-MM-DD.log, and
   updates pipeline_state.json with what happened.

Run manually any time with: python -m pipeline.auto_update
Exit code 0 = ran fine (whether or not new data was found), 1 = error.

KNOWN FRAGILITY, worth knowing: this drives a real headless Chrome session
against the live BTS website, reusing download.py's existing field-by-ID
selectors. If BTS ever changes their page layout, this breaks the same way
the interactive download.py would -- that's an inherent risk of browser
automation against a page not designed for it, not something this script
can fully protect against. The logging is deliberately verbose so a
failure is diagnosable rather than a silent no-op.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import RAW_DIR, CLEAN_DIR, LOG_DIR, DUCKDB_FILE, PIPELINE_STATE_FILE
from pipeline.download import download_month, MONTH_NAMES
from pipeline.clean import process_zip, parse_year_month, find_zip_files
from pipeline import build_warehouse
from pipeline.materialize_analytics import build_analytics_tables


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"auto_update_{date.today().isoformat()}.log"
    logger = logging.getLogger("auto_update")
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
    if PIPELINE_STATE_FILE.exists():
        try:
            return json.loads(PIPELINE_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state: dict) -> None:
    PIPELINE_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def latest_warehouse_month(logger: logging.Logger) -> tuple[int, int] | None:
    """(year, month) of the most recent flight already in the warehouse, or
    None if the warehouse doesn't exist yet / has no data."""
    if not DUCKDB_FILE.exists():
        logger.warning("Warehouse file not found at %s -- treating as empty.", DUCKDB_FILE)
        return None
    try:
        connection = duckdb.connect(str(DUCKDB_FILE), read_only=True)
        try:
            row = connection.execute("SELECT MAX(FlightDate) FROM flights").fetchone()
        finally:
            connection.close()
        if row is None or row[0] is None:
            return None
        max_date = row[0]
        return (max_date.year, max_date.month)
    except Exception as exc:
        logger.error("Could not read warehouse's latest month: %s: %s", type(exc).__name__, exc)
        return None


def months_to_check(start_after: tuple[int, int] | None, logger: logging.Logger) -> list[tuple[int, int]]:
    """(year, month) pairs from the month after `start_after` up to (but not
    including) the current month -- BTS won't have the current month ready,
    so there's no point checking it."""
    today = date.today()
    if start_after is None:
        # No warehouse data at all -- fall back to checking from the start
        # of this year, a reasonable default rather than guessing further
        # back with no real signal.
        year, month = today.year, 1
    else:
        year, month = start_after
        month += 1
        if month > 12:
            month = 1
            year += 1

    candidates = []
    while (year, month) < (today.year, today.month):
        candidates.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    logger.info("Checking %d candidate month(s): %s", len(candidates), candidates)
    return candidates


def setup_headless_driver():
    """Same Chrome options as download.py's setup_driver(), plus headless
    mode -- separate function rather than modifying the existing one, so
    manual/interactive use of download.py is untouched."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    prefs = {
        "download.default_directory": str(RAW_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )
    return driver


def append_new_months_to_warehouse(cleaned_ok: list[tuple[int, int]], logger: logging.Logger) -> bool:
    """Appends just the newly-cleaned month(s) to the existing warehouse
    instead of rebuilding it from scratch. The first automated run took
    ~55 minutes almost entirely because build_warehouse.main() re-reads
    ALL ~100+ historical clean files every time, even to add one new
    month -- this fixes that by inserting only the new rows. Falls back to
    a full rebuild only if the warehouse doesn't exist yet at all (nothing
    to append to)."""
    if not DUCKDB_FILE.exists():
        logger.info("No existing warehouse -- doing a full build instead of an incremental append.")
        build_warehouse.main()
        return True

    connection = duckdb.connect(str(DUCKDB_FILE))
    transaction_open = False
    try:
        connection.execute("BEGIN TRANSACTION")
        transaction_open = True
        for year, month in cleaned_ok:
            month_name = MONTH_NAMES.get(month, str(month))
            clean_path = CLEAN_DIR / f"OTP_{year}_{month:02d}_{month_name}.csv"
            if not clean_path.exists():
                logger.error("Expected clean file not found: %s -- skipping this month.", clean_path)
                continue

            # Guard against double-appending the same month (e.g. a re-run
            # after a partial failure) -- would silently duplicate rows
            # otherwise.
            already_present = connection.execute(
                "SELECT COUNT(*) FROM flights WHERE strftime(FlightDate, '%Y-%m') = ?",
                [f"{year}-{month:02d}"],
            ).fetchone()[0]

            expected_count = connection.execute(
                "SELECT COUNT(*) FROM read_csv_auto(?, union_by_name=true, header=true)",
                [str(clean_path)],
            ).fetchone()[0]
            if expected_count <= 0:
                raise RuntimeError(f"Cleaned {year}-{month:02d} file is empty; refusing to update the warehouse.")
            if already_present == expected_count:
                logger.warning(
                    "%s %d already has %d rows in the warehouse -- skipping append to avoid duplicates.",
                    month_name, year, already_present,
                )
                continue
            if already_present > 0:
                raise RuntimeError(
                    f"Warehouse contains a partial {year}-{month:02d} month "
                    f"({already_present:,} rows vs {expected_count:,} cleaned rows); "
                    "refusing to append duplicates. Rebuild or repair the warehouse first."
                )

            connection.execute(
                "INSERT INTO flights BY NAME SELECT * FROM read_csv_auto(?, union_by_name=true, header=true)",
                [str(clean_path)],
            )
            new_row_count = connection.execute(
                "SELECT COUNT(*) FROM flights WHERE strftime(FlightDate, '%Y-%m') = ?",
                [f"{year}-{month:02d}"],
            ).fetchone()[0]
            logger.info("Appended %s %d: %s rows.", month_name, year, f"{new_row_count:,}")

        total = connection.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
        analytics_counts = build_analytics_tables(connection)
        connection.execute("COMMIT")
        transaction_open = False
        logger.info("Warehouse now has %s total rows.", f"{total:,}")
        logger.info("Analytics tables refreshed: %s", analytics_counts)
        return True
    except Exception as exc:
        if transaction_open:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
        logger.error(
            "Incremental append failed: %s: %s -- transaction rolled back; "
            "consider running python -m pipeline.build_warehouse to do a clean full rebuild.",
            type(exc).__name__, exc,
        )
        return False
    finally:
        connection.close()


def main() -> int:
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("AUTOMATED BTS DATA CHECK STARTING")
    logger.info("=" * 60)

    state = load_state()
    state["last_checked"] = datetime.now().isoformat()

    latest = latest_warehouse_month(logger)
    if latest:
        logger.info("Warehouse currently has data through %s %d.", MONTH_NAMES[latest[1]], latest[0])
    else:
        logger.info("Warehouse has no usable data yet.")

    candidates = months_to_check(latest, logger)
    if not candidates:
        logger.info("Nothing to check -- warehouse is already current through last month.")
        state["last_result"] = "up_to_date"
        save_state(state)
        return 0

    logger.info("Starting headless Chrome...")
    try:
        driver = setup_headless_driver()
    except Exception as exc:
        logger.error("Could not start Chrome: %s: %s", type(exc).__name__, exc)
        state["last_result"] = "error_starting_browser"
        save_state(state)
        return 1

    wait = WebDriverWait(driver, 30)
    newly_downloaded: list[tuple[int, int]] = []

    try:
        for year, month in candidates:
            logger.info("Checking %s %d...", MONTH_NAMES[month], year)
            try:
                success = download_month(driver, wait, year, month)
            except Exception as exc:
                logger.error(
                    "Unexpected error checking %s %d: %s: %s -- stopping here.",
                    MONTH_NAMES[month], year, type(exc).__name__, exc,
                )
                break
            if success:
                logger.info("New data found and downloaded: %s %d", MONTH_NAMES[month], year)
                newly_downloaded.append((year, month))
            else:
                logger.info(
                    "%s %d not published yet -- BTS publishes in order, so stopping here "
                    "rather than checking further months.",
                    MONTH_NAMES[month], year,
                )
                break
    finally:
        driver.quit()

    if not newly_downloaded:
        logger.info("No new months found. Warehouse is already current.")
        state["last_result"] = "no_new_data"
        save_state(state)
        return 0

    logger.info("Cleaning %d newly-downloaded file(s)...", len(newly_downloaded))
    temp_dir = RAW_DIR / "_temp"
    zip_files = find_zip_files(str(RAW_DIR))
    cleaned_ok = []
    for zip_path in zip_files:
        year, month = parse_year_month(zip_path)
        if (year, month) not in newly_downloaded:
            continue
        try:
            success = process_zip(zip_path, str(CLEAN_DIR), str(temp_dir))
        except Exception as exc:
            logger.error("Cleaning failed for %s: %s: %s", zip_path, type(exc).__name__, exc)
            success = False
        if success:
            cleaned_ok.append((year, month))
        else:
            logger.error("Cleaning failed for %s %d -- will not be included in this rebuild.", MONTH_NAMES[month], year)

    if not cleaned_ok:
        logger.error("All newly-downloaded files failed to clean -- not rebuilding the warehouse.")
        state["last_result"] = "download_ok_clean_failed"
        save_state(state)
        return 1

    logger.info("Appending %d new month(s) to the warehouse...", len(cleaned_ok))
    try:
        ok = append_new_months_to_warehouse(cleaned_ok, logger)
    except Exception as exc:
        logger.error("Warehouse update failed: %s: %s", type(exc).__name__, exc)
        ok = False
    if not ok:
        state["last_result"] = "rebuild_failed"
        state["months_downloaded_not_incorporated"] = [f"{y}-{m:02d}" for y, m in cleaned_ok]
        save_state(state)
        return 1

    logger.info("Done. Added: %s", [f"{MONTH_NAMES[m]} {y}" for y, m in cleaned_ok])
    state["last_result"] = "success"
    state["last_months_added"] = [f"{y}-{m:02d}" for y, m in cleaned_ok]
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
