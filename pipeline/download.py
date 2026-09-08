# pipeline/download.py
# BTS On-Time Performance — Automated Downloader
# Uses Selenium to control Chrome and download all 12 monthly files for a given year
# Run this script, enter a year, walk away — files appear in Data/Raw/

import os
import re
import time
import sys
import zipfile
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import UnexpectedAlertPresentException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import BASE_DIR, RAW_DIR

# ── CONFIG ────────────────────────────────────────────────────────────────────

# RAW_DIR is provided by config.py.

BTS_URL = "https://transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FGK&QO_fu146_anzr=b0-gvzr"

MONTH_NAMES = {
    1: "January",   2: "February",  3: "March",
    4: "April",     5: "May",       6: "June",
    7: "July",      8: "August",    9: "September",
    10: "October",  11: "November", 12: "December"
}

# Confirmed via live-page diagnostic: all 119 real field checkbox IDs
# (excludes chkAllVars/chkAllGroups/chkDownloadZip/chkshowNull/chkMergeSub/chkDocument/chkTermDef,
# which are page controls, not data fields)
FIELDS_ALL = [
    "YEAR",
    "QUARTER",
    "MONTH",
    "DAY_OF_MONTH",
    "DAY_OF_WEEK",
    "FL_DATE",
    "MKT_UNIQUE_CARRIER",
    "BRANDED_CODE_SHARE",
    "MKT_CARRIER_AIRLINE_ID",
    "MKT_CARRIER",
    "MKT_CARRIER_FL_NUM",
    "SCH_OP_UNIQUE_CARRIER",
    "SCH_OP_CARRIER_AIRLINE_ID",
    "SCH_OP_CARRIER",
    "SCH_OP_CARRIER_FL_NUM",
    "OP_UNIQUE_CARRIER",
    "OP_CARRIER_AIRLINE_ID",
    "OP_CARRIER",
    "TAIL_NUM",
    "OP_CARRIER_FL_NUM",
    "ORIGIN_AIRPORT_ID",
    "ORIGIN_AIRPORT_SEQ_ID",
    "ORIGIN_CITY_MARKET_ID",
    "ORIGIN",
    "ORIGIN_CITY_NAME",
    "ORIGIN_STATE_ABR",
    "ORIGIN_STATE_FIPS",
    "ORIGIN_STATE_NM",
    "ORIGIN_WAC",
    "DEST_AIRPORT_ID",
    "DEST_AIRPORT_SEQ_ID",
    "DEST_CITY_MARKET_ID",
    "DEST",
    "DEST_CITY_NAME",
    "DEST_STATE_ABR",
    "DEST_STATE_FIPS",
    "DEST_STATE_NM",
    "DEST_WAC",
    "CRS_DEP_TIME",
    "DEP_TIME",
    "DEP_DELAY",
    "DEP_DELAY_NEW",
    "DEP_DEL15",
    "DEP_DELAY_GROUP",
    "DEP_TIME_BLK",
    "TAXI_OUT",
    "WHEELS_OFF",
    "WHEELS_ON",
    "TAXI_IN",
    "CRS_ARR_TIME",
    "ARR_TIME",
    "ARR_DELAY",
    "ARR_DELAY_NEW",
    "ARR_DEL15",
    "ARR_DELAY_GROUP",
    "ARR_TIME_BLK",
    "CANCELLED",
    "CANCELLATION_CODE",
    "DIVERTED",
    "DUP",
    "CRS_ELAPSED_TIME",
    "ACTUAL_ELAPSED_TIME",
    "AIR_TIME",
    "FLIGHTS",
    "DISTANCE",
    "DISTANCE_GROUP",
    "CARRIER_DELAY",
    "WEATHER_DELAY",
    "NAS_DELAY",
    "SECURITY_DELAY",
    "LATE_AIRCRAFT_DELAY",
    "FIRST_DEP_TIME",
    "TOTAL_ADD_GTIME",
    "LONGEST_ADD_GTIME",
    "DIV_AIRPORT_LANDINGS",
    "DIV_REACHED_DEST",
    "DIV_ACTUAL_ELAPSED_TIME",
    "DIV_ARR_DELAY",
    "DIV_DISTANCE",
    "DIV1_AIRPORT",
    "DIV1_AIRPORT_ID",
    "DIV1_AIRPORT_SEQ_ID",
    "DIV1_WHEELS_ON",
    "DIV1_TOTAL_GTIME",
    "DIV1_LONGEST_GTIME",
    "DIV1_WHEELS_OFF",
    "DIV1_TAIL_NUM",
    "DIV2_AIRPORT",
    "DIV2_AIRPORT_ID",
    "DIV2_AIRPORT_SEQ_ID",
    "DIV2_WHEELS_ON",
    "DIV2_TOTAL_GTIME",
    "DIV2_LONGEST_GTIME",
    "DIV2_WHEELS_OFF",
    "DIV2_TAIL_NUM",
    "DIV3_AIRPORT",
    "DIV3_AIRPORT_ID",
    "DIV3_AIRPORT_SEQ_ID",
    "DIV3_WHEELS_ON",
    "DIV3_TOTAL_GTIME",
    "DIV3_LONGEST_GTIME",
    "DIV3_WHEELS_OFF",
    "DIV3_TAIL_NUM",
    "DIV4_AIRPORT",
    "DIV4_AIRPORT_ID",
    "DIV4_AIRPORT_SEQ_ID",
    "DIV4_WHEELS_ON",
    "DIV4_TOTAL_GTIME",
    "DIV4_LONGEST_GTIME",
    "DIV4_WHEELS_OFF",
    "DIV4_TAIL_NUM",
    "DIV5_AIRPORT",
    "DIV5_AIRPORT_ID",
    "DIV5_AIRPORT_SEQ_ID",
    "DIV5_WHEELS_ON",
    "DIV5_TOTAL_GTIME",
    "DIV5_LONGEST_GTIME",
    "DIV5_WHEELS_OFF",
    "DIV5_TAIL_NUM",
]

DOWNLOAD_WAIT = 180


def _matches_period(filename, year, month):
    """Accept Chrome conflict suffixes such as (1).zip."""
    return bool(re.search(rf"_{year}_{month}(?: \(\d+\))?\.zip$", filename, re.IGNORECASE))


# ── SETUP ─────────────────────────────────────────────────────────────────────

def get_year():
    print()
    print("=" * 60)
    print("  BTS ON-TIME PERFORMANCE — AUTO DOWNLOADER")
    print("=" * 60)
    print()
    while True:
        year_input = input("  Enter year to download (2018-2026): ").strip()
        if year_input.isdigit() and 2018 <= int(year_input) <= 2026:
            return int(year_input)
        print("  Please enter a valid year between 2018 and 2026.")


def check_existing(year):
    os.makedirs(RAW_DIR, exist_ok=True)
    existing, missing = [], []
    for month in range(1, 13):
        found = any(
            _matches_period(f, year, month) and validate_download_file(
                os.path.join(RAW_DIR, f), expected_year=year, expected_month=month
            )
            for f in os.listdir(RAW_DIR)
        )
        if found:
            existing.append(month)
        else:
            missing.append(month)
    return existing, missing


def setup_driver():
    os.makedirs(RAW_DIR, exist_ok=True)
    options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": str(RAW_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)
    if os.getenv("BTS_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
    cache_dir = _Path(os.getenv("BTS_WEBDRIVER_CACHE_DIR", str(BASE_DIR / ".wdm")))
    cache_dir.mkdir(parents=True, exist_ok=True)
    driver_manager = ChromeDriverManager(
        cache_manager=DriverCacheManager(root_dir=str(cache_dir))
    )
    driver = webdriver.Chrome(
        service=Service(driver_manager.install()),
        options=options
    )
    driver.maximize_window()
    return driver


# ── DOWNLOAD LOGIC ────────────────────────────────────────────────────────────

def validate_download_file(path, expected_year=None, expected_month=None):
    """Return True only for a readable ZIP containing a BTS CSV.

    Chrome can create auxiliary files in the download directory, and a
    partially-written ZIP may briefly exist after the browser renames it. The
    pipeline must not treat either as a valid monthly source file.
    """
    if not os.path.isfile(path) or not path.lower().endswith(".zip"):
        return False
    try:
        with zipfile.ZipFile(path, "r") as archive:
            if archive.testzip() is not None:
                return False
            csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(csv_members) != 1:
                return False
            if expected_year is not None and expected_month is not None:
                name = os.path.basename(path)
                if not _matches_period(name, expected_year, expected_month):
                    return False
            return True
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return False


def wait_for_download(raw_dir, existing_files, expected_year=None, expected_month=None, timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        current_files = set(os.listdir(raw_dir))
        new_files = current_files - existing_files
        for filename in sorted(new_files):
            if filename.endswith('.crdownload') or filename.endswith('.tmp') or filename.startswith('.'):
                continue
            path = os.path.join(raw_dir, filename)
            if validate_download_file(path, expected_year=expected_year, expected_month=expected_month):
                return filename
        time.sleep(2)
    return None


def set_filters(driver, wait, year, month):
    """Set year and month dropdowns."""
    # Year
    try:
        year_select = Select(wait.until(
            EC.presence_of_element_located((By.ID, "cboYear"))
        ))
        year_select.select_by_visible_text(str(year))
        print(f"    Year set to {year}")
    except Exception as e:
        print(f"    Warning - year filter failed: {e}")
    time.sleep(1)

    # Month
    try:
        period_select = Select(driver.find_element(By.ID, "cboPeriod"))
        period_select.select_by_index(month - 1)
        print(f"    Month set to {MONTH_NAMES[month]}")
    except Exception as e:
        print(f"    Warning - month filter failed: {e}")
    time.sleep(1)


def select_all_fields(driver):
    """Check all 119 confirmed field checkboxes, using a fresh find_element(By.ID, ...)
    lookup per field rather than a cached list — this is the pattern the original
    15-field version used successfully, and avoids stale-element issues if a click
    triggers a postback.
    """
    checked = 0
    missing = []
    for field_id in FIELDS_ALL:
        try:
            cb = driver.find_element(By.ID, field_id)
            if not cb.is_selected():
                driver.execute_script("arguments[0].click();", cb)
            checked += 1
        except Exception:
            missing.append(field_id)
    print(f"    {checked}/{len(FIELDS_ALL)} fields selected"
          + (f" (not found: {missing})" if missing else ""))
    time.sleep(0.5)


def check_prezipped(driver):
    """Check the Prezipped File checkbox."""
    try:
        cb = driver.find_element(By.ID, "chkDownloadZip")
        if not cb.is_selected():
            driver.execute_script("arguments[0].click();", cb)
        print(f"    Prezipped File checked")
    except Exception as e:
        print(f"    Warning - could not check Prezipped: {e}")
    time.sleep(0.5)


def click_download(driver, wait):
    """Click the Download button."""
    try:
        btn = wait.until(EC.element_to_be_clickable((By.ID, "btnDownload")))
        driver.execute_script("arguments[0].click();", btn)
        print(f"    Download clicked")
    except Exception as e:
        print(f"    Warning - could not click Download: {e}")


def safe_get(driver, url):
    """Navigate to url, dismissing any leftover alert from a previous month first."""
    try:
        driver.get(url)
    except UnexpectedAlertPresentException:
        try:
            alert = driver.switch_to.alert
            print(f"    Dismissing leftover alert: {alert.text}")
            alert.accept()
        except Exception:
            pass
        driver.get(url)


def download_month(driver, wait, year, month):
    print(f"\n  [{month}/12] Downloading {MONTH_NAMES[month]} {year}...")

    existing_files = set(os.listdir(RAW_DIR))

    safe_get(driver, BTS_URL)
    wait.until(EC.presence_of_element_located((By.ID, "cboYear")))
    time.sleep(3)

    set_filters(driver, wait, year, month)
    select_all_fields(driver)
    check_prezipped(driver)
    click_download(driver, wait)

    # BTS shows a JS alert instead of downloading when the month isn't published yet.
    # Check for it before burning the full download timeout waiting for a file
    # that will never appear.
    try:
        WebDriverWait(driver, 5).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        alert_text = alert.text
        alert.accept()
        print(f"    Not available — {MONTH_NAMES[month]} {year}: {alert_text}")
        return False
    except TimeoutException:
        pass  # no alert; proceed normally

    print(f"    Waiting for download...")
    filename = wait_for_download(
        RAW_DIR,
        existing_files,
        expected_year=year,
        expected_month=month,
        timeout=DOWNLOAD_WAIT,
    )

    if filename:
        size_mb = os.path.getsize(os.path.join(RAW_DIR, filename)) / 1024 / 1024
        print(f"    Done — validated {filename} ({size_mb:.1f} MB)")
        return True
    else:
        print(f"    Timed out — {MONTH_NAMES[month]} {year} may have failed")
        return False


# ── MAIN ──────────────────────────────────────────────────────────────────────

def get_year_range():
    print()
    print("=" * 60)
    print("  BTS ON-TIME PERFORMANCE — AUTO DOWNLOADER")
    print("=" * 60)
    print()
    print("  Enter a single year (e.g. 2025) or a range (e.g. 2018-2025)")
    print("  Data available from 2018 to present.")
    print()
    while True:
        year_input = input("  Year or range: ").strip()
        if '-' in year_input:
            parts = year_input.split('-')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                start, end = int(parts[0]), int(parts[1])
                if 2018 <= start <= end <= 2026:
                    return list(range(start, end + 1))
        elif year_input.isdigit() and 2018 <= int(year_input) <= 2026:
            return [int(year_input)]
        print("  Please enter a valid year or range (e.g. 2018-2025).")


def main():
    years = get_year_range()

    all_missing = []
    for year in years:
        existing, missing = check_existing(year)
        for month in missing:
            all_missing.append((year, month))

    print()
    print("=" * 60)
    print(f"  DOWNLOAD PLAN FOR {years[0]}-{years[-1]}")
    print("=" * 60)
    print(f"\n  Years requested  : {years}")
    print(f"  Files to download: {len(all_missing)}")

    if len(all_missing) == 0:
        print("  All months already downloaded.")
        return

    for year in years:
        existing, missing = check_existing(year)
        if missing:
            print(f"  {year} — have {len(existing)}, need {len(missing)}")

    confirm = input(f"\n  Download {len(all_missing)} files automatically? (y/n): ").strip().lower()
    if confirm != 'y':
        print("  Cancelled.")
        return

    print("\n  Starting Chrome...")
    driver = setup_driver()
    wait   = WebDriverWait(driver, 30)

    results = {}
    total = len(all_missing)
    try:
        for i, (year, month) in enumerate(all_missing, 1):
            print(f"\n  [{i}/{total}]", end=" ")
            try:
                success = download_month(driver, wait, year, month)
            except UnexpectedAlertPresentException:
                try:
                    alert = driver.switch_to.alert
                    print(f"    Unexpected alert: {alert.text}")
                    alert.accept()
                except Exception:
                    pass
                success = False
            results[(year, month)] = success
            if i < total:
                print(f"    Pausing 5 seconds...")
                time.sleep(5)
    finally:
        driver.quit()

    print()
    print("=" * 60)
    print("  DOWNLOAD SUMMARY")
    print("=" * 60)
    success_count = sum(1 for v in results.values() if v)
    fail_count    = sum(1 for v in results.values() if not v)
    print(f"\n  Successful : {success_count}")
    print(f"  Failed     : {fail_count}")
    if fail_count > 0:
        failed = [f"{MONTH_NAMES[m]} {y}" for (y, m), v in results.items() if not v]
        print(f"  Retry      : {failed}")
    print(f"\n  Files saved to: {RAW_DIR}")
    print("\n  Next: python -m pipeline.clean")
    print()


if __name__ == '__main__':
    main()
