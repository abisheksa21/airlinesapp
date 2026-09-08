"""Download BTS enrichment datasets through the TranStats download form.

TranStats is a JavaScript form rather than a stable public file URL.  This
downloader therefore uses the same Selenium approach as ``pipeline.download``
but makes the dataset explicit and stores each source under its own namespace.

Examples from the repository root::

    python -m pipeline.download_bts t100_segment --years 2018-2026
    python -m pipeline.download_bts t100_market --years 2025-2026
    python -m pipeline.download_bts carrier_decode
    python -m pipeline.download_bts master_coordinate
    python -m pipeline.download_bts aircraft_types

The downloader never treats a browser-created file as complete until it is a
readable ZIP containing exactly one CSV.  Monthly files are renamed to a
stable canonical name after validation, making reruns idempotent.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import time
import zipfile
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import UnexpectedAlertPresentException, TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager

from pipeline.bts_sources import (
    DATASETS,
    BtsDataset,
    data_csv_members,
    get_dataset,
    validate_enrichment_download_file,
)
from config import BASE_DIR


MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

DOWNLOAD_WAIT = int(os.getenv("BTS_ENRICHMENT_DOWNLOAD_WAIT", "180"))


def _canonical_filename(dataset: BtsDataset, year: int | None = None, month: int | None = None) -> str:
    if dataset.monthly:
        assert year is not None and month is not None
        return f"{dataset.key}_{year}_{month:02d}.zip"
    return f"{dataset.key}.zip"


def _is_temporary(filename: str) -> bool:
    return filename.endswith((".crdownload", ".tmp", ".part")) or filename.startswith(".")


def _wait_for_valid_zip(raw_dir: Path, existing_files: set[str], timeout: int) -> Path | None:
    started = time.time()
    while time.time() - started < timeout:
        for filename in sorted(set(os.listdir(raw_dir)) - existing_files):
            if _is_temporary(filename):
                continue
            candidate = raw_dir / filename
            if validate_enrichment_download_file(candidate):
                return candidate
        time.sleep(2)
    return None


def _zip_contains_period(path: Path, year: int, month: int) -> bool:
    """Inspect only the first data row to recognize timestamped BTS ZIPs."""
    try:
        member = data_csv_members(path)[0]
        with zipfile.ZipFile(path, "r") as archive:
            with archive.open(member, "r") as binary:
                text = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
                row = next(csv.DictReader(text), None)
        if not row:
            return False
        return int(float(row.get("YEAR", row.get("Year", "-1")))) == year and int(
            float(row.get("MONTH", row.get("Month", "-1")))
        ) == month
    except (OSError, ValueError, KeyError, IndexError, StopIteration, zipfile.BadZipFile):
        return False


def _zip_matches_dataset(path: Path, dataset: BtsDataset) -> bool:
    """Check a source ZIP header before reusing it for a dataset."""
    try:
        member = data_csv_members(path)[0]
        with zipfile.ZipFile(path, "r") as archive:
            with archive.open(member, "r") as binary:
                text = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
                header = next(csv.reader(text), [])
        normalized_header = {
            re.sub(r"[^A-Z0-9]", "", value.upper()) for value in header
        }
        candidates = {
            re.sub(r"[^A-Z0-9]", "", value.upper())
            for value in dataset.required_columns
        }
        candidates.update(
            re.sub(r"[^A-Z0-9]", "", source.upper())
            for source, target in dataset.special_column_aliases
            if target in dataset.required_columns
        )
        return len(normalized_header & candidates) >= min(3, len(dataset.required_columns))
    except (OSError, IndexError, StopIteration, zipfile.BadZipFile):
        return False


def setup_driver(download_dir: Path) -> webdriver.Chrome:
    download_dir.mkdir(parents=True, exist_ok=True)
    options = webdriver.ChromeOptions()
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    if os.getenv("BTS_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
    cache_dir = Path(os.getenv("BTS_WEBDRIVER_CACHE_DIR", str(BASE_DIR / ".wdm")))
    cache_dir.mkdir(parents=True, exist_ok=True)
    driver_manager = ChromeDriverManager(
        cache_manager=DriverCacheManager(root_dir=str(cache_dir))
    )
    driver = webdriver.Chrome(service=Service(driver_manager.install()), options=options)
    if not options.arguments:
        driver.maximize_window()
    return driver


def safe_get(driver: webdriver.Chrome, url: str) -> None:
    try:
        driver.get(url)
    except UnexpectedAlertPresentException:
        try:
            alert = driver.switch_to.alert
            alert.accept()
        except Exception:
            pass
        driver.get(url)


def _select_year_and_month(driver: webdriver.Chrome, wait: WebDriverWait, year: int, month: int) -> None:
    try:
        year_select = Select(wait.until(EC.presence_of_element_located((By.ID, "cboYear"))))
        year_select.select_by_visible_text(str(year))
    except TimeoutException:
        raise RuntimeError("BTS page did not expose the expected cboYear filter.")

    period = driver.find_elements(By.ID, "cboPeriod")
    if not period:
        raise RuntimeError("BTS page did not expose the expected cboPeriod filter.")

    period_select = Select(period[0])
    month_texts = {str(month), f"{month:02d}", MONTH_NAMES[month], MONTH_NAMES[month][:3]}
    option = next(
        (option for option in period_select.options if option.text.strip() in month_texts),
        None,
    )
    if option is not None:
        period_select.select_by_value(option.get_attribute("value"))
    else:
        # TranStats has used both numeric and month-name labels. The page is
        # ordered Jan..Dec, so index is a safe fallback after the exact match.
        period_select.select_by_index(month - 1)
    time.sleep(1)


def _select_all_fields(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    try:
        control = wait.until(EC.presence_of_element_located((By.ID, "chkAllVars")))
        if not control.is_selected():
            driver.execute_script("arguments[0].click();", control)
        return
    except Exception as exc:
        raise RuntimeError("BTS page did not expose the expected select-all-fields control.") from exc


def _select_prezipped(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    # Selecting all fields can trigger a small asynchronous form refresh.  On
    # older TranStats pages the ZIP checkbox briefly disappears during that
    # refresh, so querying it immediately makes a valid page look malformed.
    try:
        control = wait.until(EC.presence_of_element_located((By.ID, "chkDownloadZip")))
    except TimeoutException as exc:
        raise RuntimeError("BTS page did not expose the expected prezipped-file control.") from exc
    if not control.is_selected():
        driver.execute_script("arguments[0].click();", control)


def _click_download(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    button = wait.until(EC.element_to_be_clickable((By.ID, "btnDownload")))
    driver.execute_script("arguments[0].click();", button)


def _dismiss_unavailable_alert(driver: webdriver.Chrome) -> str | None:
    try:
        WebDriverWait(driver, 5).until(EC.alert_is_present())
    except TimeoutException:
        return None
    alert = driver.switch_to.alert
    text = alert.text
    alert.accept()
    return text


def _download_one(
    driver: webdriver.Chrome,
    dataset: BtsDataset,
    year: int | None = None,
    month: int | None = None,
) -> Path | None:
    destination = dataset.raw_dir
    destination.mkdir(parents=True, exist_ok=True)
    canonical = destination / _canonical_filename(dataset, year, month)
    if (
        canonical.exists()
        and validate_enrichment_download_file(canonical)
        and _zip_matches_dataset(canonical, dataset)
    ):
        print(f"  Already downloaded: {canonical.name}")
        return canonical

    # TranStats names some successful downloads with a server timestamp. If a
    # previous run was interrupted after the download but before promotion,
    # recognize and promote that file instead of downloading the same period
    # again.
    # Monthly downloads can leave a server-timestamped ZIP after an interrupted
    # promotion, so inspect those candidates by period and header.  Reference
    # downloads must never borrow another support table's filename/content;
    # their canonical filename is the only safe reusable location.
    existing_candidates = (
        sorted(
            path
            for path in destination.glob("*.zip")
            if validate_enrichment_download_file(path) and _zip_matches_dataset(path, dataset)
        )
        if dataset.monthly
        else []
    )
    for candidate in existing_candidates:
        if dataset.monthly and year is not None and month is not None:
            if not _zip_contains_period(candidate, year, month):
                continue
        os.replace(candidate, canonical)
        print(f"  Reusing validated download: {canonical.name}")
        return canonical

    existing_files = set(os.listdir(destination))
    wait = WebDriverWait(driver, 35)
    safe_get(driver, dataset.url)
    _select_all_fields(driver, wait)
    _select_prezipped(driver, wait)
    if dataset.monthly:
        assert year is not None and month is not None
        _select_year_and_month(driver, wait, year, month)
    _click_download(driver, wait)

    unavailable = _dismiss_unavailable_alert(driver)
    if unavailable:
        label = f"{year}-{month:02d}" if dataset.monthly else dataset.key
        print(f"  Not available for {label}: {unavailable}")
        return None

    print(f"  Waiting for {dataset.label} download...")
    source = _wait_for_valid_zip(destination, existing_files, DOWNLOAD_WAIT)
    if source is None:
        raise TimeoutError(f"Timed out waiting for a valid {dataset.label} ZIP in {destination}")

    # The source name is controlled by BTS/Chrome and can change. Once it has
    # passed validation, promote it to our stable, dataset-specific name.
    if source != canonical:
        os.replace(source, canonical)
    if not validate_enrichment_download_file(canonical):
        raise RuntimeError(f"Validated source became unreadable after promotion: {canonical}")
    print(f"  Saved: {canonical.name} ({canonical.stat().st_size / 1024 / 1024:.1f} MB)")
    return canonical


def _parse_years(raw: str) -> list[int]:
    match = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", raw.strip())
    if not match:
        raise argparse.ArgumentTypeError("years must look like 2025 or 2018-2026")
    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    if not 1990 <= start <= end <= 2100:
        raise argparse.ArgumentTypeError("year range is not valid")
    return list(range(start, end + 1))


def download_dataset(
    dataset: BtsDataset,
    years: list[int] | None = None,
    months: list[int] | None = None,
) -> list[Path]:
    """Download all requested periods for one catalogued dataset."""
    if dataset.monthly and not years:
        raise ValueError(f"{dataset.key} is monthly; provide at least one year.")
    if not dataset.monthly:
        years = [None]  # type: ignore[assignment]

    driver = setup_driver(dataset.raw_dir)
    downloaded: list[Path] = []
    try:
        if dataset.monthly:
            requested_months = months or list(range(1, 13))
            for year in years or []:
                for month in requested_months:
                    print(f"\n[{dataset.key}] {year}-{month:02d}")
                    result = _download_one(driver, dataset, year, month)
                    if result:
                        downloaded.append(result)
                    time.sleep(5)
        else:
            result = _download_one(driver, dataset)
            if result:
                downloaded.append(result)
    finally:
        driver.quit()
    return downloaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download a verified BTS enrichment dataset")
    parser.add_argument("dataset", choices=sorted(DATASETS))
    parser.add_argument(
        "--years",
        type=_parse_years,
        help="monthly year or range, for example 2025 or 2018-2026",
    )
    parser.add_argument(
        "--months",
        default=None,
        help="optional comma-separated monthly subset, for example 1 or 1,2,3",
    )
    args = parser.parse_args(argv)
    dataset = get_dataset(args.dataset)
    if dataset.monthly and not args.years:
        parser.error("--years is required for monthly datasets")
    if not dataset.monthly and args.months:
        parser.error("--months only applies to monthly datasets")
    months = None
    if args.months:
        try:
            months = [int(value.strip()) for value in args.months.split(",")]
        except ValueError as exc:
            parser.error("--months must be a comma-separated list of numbers from 1 to 12")
        if not months or any(month < 1 or month > 12 for month in months):
            parser.error("--months must be a comma-separated list of numbers from 1 to 12")
        if len(set(months)) != len(months):
            parser.error("--months cannot contain duplicates")
    downloaded = download_dataset(dataset, args.years, months)
    print(f"\nDownloaded/confirmed {len(downloaded)} file(s) for {dataset.label}.")
    print(f"Raw files: {dataset.raw_dir}")
    print(f"Next: python -m pipeline.clean_bts {dataset.key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
