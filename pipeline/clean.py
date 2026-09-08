# pipeline/clean.py
# BTS On-Time Performance — Process Raw Downloads
# Unzips each monthly file, cleans data, saves as CSV to Data/Clean/ (keeps all BTS columns)

import os
import re
import zipfile
import pandas as pd
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import RAW_DIR, CLEAN_DIR

# ── CONFIG ────────────────────────────────────────────────────────────────────

# Paths are provided by config.py.

# NOTE: full raw BTS schema is kept (no field subsetting).
# clean_dataframe() below cleans types generically by column-name pattern
# instead of selecting/renaming a fixed field list.

MONTH_NAMES = {
    1: "January",   2: "February",  3: "March",
    4: "April",     5: "May",       6: "June",
    7: "July",      8: "August",    9: "September",
    10: "October",  11: "November", 12: "December"
}


# ── HELPERS ───────────────────────────────────────────────────────────────────

def find_zip_files(raw_dir):
    """Find all BTS zip files in Raw folder."""
    zips = []
    for f in sorted(os.listdir(raw_dir)):
        if f.endswith('.zip') and 'On_Time' in f:
            zips.append(os.path.join(raw_dir, f))
    return zips


def parse_year_month(filename):
    """Extract year and month from BTS filename."""
    # Pattern: ...2025_1.zip, ...2025_12.zip, or Chrome's ...2025_1 (1).zip
    name = Path(filename).stem
    match = re.search(r"_(\d{4})_(\d{1,2})(?: \(\d+\))?$", name)
    if not match:
        return None, None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None, None
    return year, month


def unzip_file(zip_path, extract_dir):
    """Unzip a BTS file and return path to the CSV inside."""
    os.makedirs(extract_dir, exist_ok=True)
    extract_root = Path(extract_dir).resolve()
    with zipfile.ZipFile(zip_path, 'r') as z:
        csv_files = [f for f in z.namelist() if f.lower().endswith('.csv')]
        if len(csv_files) != 1:
            print(f"    Expected exactly one CSV inside {Path(zip_path).name}; found {len(csv_files)}")
            return None
        csv_name = csv_files[0]
        extracted_path = (extract_root / csv_name).resolve()
        if extract_root not in extracted_path.parents:
            print(f"    Unsafe archive path rejected: {csv_name}")
            return None
        z.extract(csv_name, extract_dir)
        return str(extracted_path)


def clean_dataframe(df):
    """Clean types across whatever columns BTS actually provided. No column dropping."""

    # Strip column name whitespace - BTS has trailing spaces on some columns
    df.columns = df.columns.str.strip()

    # Drop the trailing "Unnamed: N" artifact column BTS CSVs commonly include
    unnamed = [c for c in df.columns if c.startswith("Unnamed:")]
    if unnamed:
        df = df.drop(columns=unnamed)

    # Parse any date-like column
    for col in df.columns:
        if "Date" in col:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Numeric-clean anything that looks like a delay, time, distance, or duration field
    numeric_markers = ("Delay", "Time", "Distance", "Elapsed", "Taxi", "AirTime")
    for col in df.columns:
        if any(marker in col for marker in numeric_markers) and df[col].dtype == object:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Cancelled/Diverted flags to int where present
    for col in ["Cancelled", "Diverted"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Strip whitespace from remaining string columns. Deliberately NOT doing
    # .astype(str).str.strip() -- on pandas <3.0, .astype(str) on a column
    # containing NaN/None turns it into the literal string "nan"/"None",
    # a long-documented pandas gotcha. .str.strip() alone is null-aware and
    # correctly preserves true nulls on every pandas version (verified
    # against the actual installed pandas here, and this pins requirements
    # >=2.1.0 -- a wide range where the old, broken behavior is real).
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    # Drop rows where FlightDate is null, if that column exists
    if "FlightDate" in df.columns:
        before = len(df)
        df = df.dropna(subset=["FlightDate"])
        dropped = before - len(df)
        if dropped > 0:
            print(f"    Dropped {dropped} rows with null FlightDate")

    return df


def process_zip(zip_path, clean_dir, temp_dir):
    """Full pipeline for one zip file."""
    year, month = parse_year_month(zip_path)
    if year is None:
        print(f"  Could not parse year/month from {Path(zip_path).name}")
        return False

    month_name  = MONTH_NAMES.get(month, str(month))
    output_name = f"OTP_{year}_{month:02d}_{month_name}.csv"
    output_path = os.path.join(clean_dir, output_name)

    if os.path.exists(output_path):
        print(f"  [{month:02d}/12] {month_name} {year} — already processed, skipping")
        return True

    print(f"\n  [{month:02d}/12] Processing {month_name} {year}...")
    print(f"    Unzipping {Path(zip_path).name}...")

    csv_path = unzip_file(zip_path, temp_dir)
    if csv_path is None:
        return False

    print(f"    Reading CSV...")
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except UnicodeDecodeError:
        print(f"    UTF-8 failed, trying latin1...")
        df = pd.read_csv(csv_path, low_memory=False, encoding='latin1')

    raw_rows = len(df)
    raw_cols = len(df.columns)
    print(f"    Raw: {raw_rows:,} rows x {raw_cols} columns")

    print(f"    Cleaning fields...")
    df = clean_dataframe(df)

    print(f"    Clean: {len(df):,} rows x {len(df.columns)} columns")

    # Save clean file
    os.makedirs(clean_dir, exist_ok=True)
    # Write to a sibling part-file first so an interrupted write cannot look
    # like a complete clean month on the next run.
    temp_output_path = f"{output_path}.part"
    try:
        df.to_csv(temp_output_path, index=False)
        os.replace(temp_output_path, output_path)
    except Exception:
        try:
            if os.path.exists(temp_output_path):
                os.remove(temp_output_path)
        except OSError:
            pass
        raise
    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"    Saved → {output_name} ({size_mb:.1f} MB)")

    # Remove temp CSV to save space
    try:
        os.remove(csv_path)
    except:
        pass

    return True


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 60)
    print("  BTS ON-TIME PERFORMANCE — PROCESS PIPELINE")
    print("=" * 60)

    os.makedirs(CLEAN_DIR, exist_ok=True)
    temp_dir = os.path.join(RAW_DIR, "_temp")

    # Find all zip files
    zip_files = find_zip_files(RAW_DIR)

    if not zip_files:
        print(f"\n  No zip files found in {RAW_DIR}")
        print("  Run python -m pipeline.download first.")
        return

    print(f"\n  Found {len(zip_files)} zip files in Raw folder")
    print(f"  Output folder: {CLEAN_DIR}")
    print()

    # Group by year for display
    by_year = {}
    for z in zip_files:
        year, month = parse_year_month(z)
        if year:
            by_year.setdefault(year, []).append(month)

    for year, months in sorted(by_year.items()):
        print(f"  {year}: {len(months)} months — "
              f"{[MONTH_NAMES[m] for m in sorted(months)]}")

    print()
    confirm = input("  Process all files? (y/n): ").strip().lower()
    if confirm != 'y':
        print("  Cancelled.")
        return

    print()
    results = {}
    for zip_path in zip_files:
        year, month = parse_year_month(zip_path)
        success = process_zip(zip_path, CLEAN_DIR, temp_dir)
        results[(year, month)] = success

    # Clean up temp folder
    try:
        if os.path.exists(temp_dir) and not os.listdir(temp_dir):
            os.rmdir(temp_dir)
    except:
        pass

    # Summary
    print()
    print("=" * 60)
    print("  PROCESSING SUMMARY")
    print("=" * 60)
    success_count = sum(1 for v in results.values() if v)
    fail_count    = sum(1 for v in results.values() if not v)
    print(f"\n  Successful : {success_count}")
    print(f"  Failed     : {fail_count}")
    if fail_count > 0:
        failed = [(y, m) for (y, m), v in results.items() if not v]
        print(f"  Failed files: {failed}")

    print(f"\n  Clean files saved to: {CLEAN_DIR}")

    # Quick stats on clean files
    print()
    print("  Clean file summary:")
    total_rows = 0
    for f in sorted(os.listdir(CLEAN_DIR)):
        if f.endswith('.csv'):
            path = os.path.join(CLEAN_DIR, f)
            size_mb = os.path.getsize(path) / 1024 / 1024
            try:
                row_count = sum(1 for _ in open(path)) - 1
                total_rows += row_count
                print(f"    {f}  ({row_count:,} rows, {size_mb:.1f} MB)")
            except:
                print(f"    {f}  ({size_mb:.1f} MB)")

    print(f"\n  Total rows across all clean files: {total_rows:,}")
    print("\n  Next: python -m pipeline.build_warehouse")
    print()


if __name__ == '__main__':
    main()
