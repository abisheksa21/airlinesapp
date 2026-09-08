"""Validate and normalize downloaded BTS enrichment CSVs.

This is intentionally separate from ``pipeline.clean``.  The flight-level
cleaner produces the ``flights`` table schema; this module preserves the
official T-100/support-table fields and only normalizes types and whitespace.
It also writes a provenance manifest so every clean file can be traced back to
the exact ZIP that came from BTS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import BTS_MANIFEST_FILE
from pipeline.bts_sources import (
    DATASETS,
    BtsDataset,
    data_csv_members,
    get_dataset,
    validate_enrichment_download_file,
)


def find_raw_files(dataset: BtsDataset) -> list[Path]:
    if not dataset.raw_dir.exists():
        return []
    return sorted(
        path
        for path in dataset.raw_dir.glob("*.zip")
        if path.is_file() and validate_enrichment_download_file(path)
    )


def parse_period(filename: str | Path) -> tuple[int, int] | None:
    """Extract YYYY/MM from a canonical or Chrome-suffixed BTS filename."""
    stem = Path(filename).stem
    match = re.search(r"(?:^|_)(\d{4})_(\d{1,2})(?: \(\d+\))?$", stem)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    return (year, month) if 1 <= month <= 12 else None


def _extract_csv(zip_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        members = data_csv_members(zip_path)
        if len(members) != 1:
            raise ValueError(f"{zip_path.name} must contain exactly one data CSV; found {len(members)}")
        member = members[0]
        target = (root / member).resolve()
        if root not in target.parents:
            raise ValueError(f"Unsafe archive member rejected: {member}")
        archive.extract(member, destination)
        return target


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, low_memory=False)
    except UnicodeDecodeError:
        return pd.read_csv(path, low_memory=False, encoding="latin1")


def clean_dataframe(df: pd.DataFrame, dataset: BtsDataset) -> pd.DataFrame:
    """Normalize a BTS frame without changing its analytical grain."""
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()
    canonical_targets = set(dataset.required_columns) | set(dataset.numeric_columns)
    aliases = dict(dataset.special_column_aliases)
    aliases.update(
        {
            column: target
            for column in df.columns
            for target in canonical_targets
            if column.replace("_", "").upper() == target.replace("_", "").upper()
        }
    )
    rename = {
        column: target
        for column, target in aliases.items()
        if column in df.columns and target not in df.columns
    }
    if rename:
        df = df.rename(columns=rename)
    unnamed = [column for column in df.columns if column.startswith("Unnamed:")]
    if unnamed:
        df = df.drop(columns=unnamed)

    for column in df.columns:
        if "Date" in column:
            df[column] = pd.to_datetime(df[column], errors="coerce")
    for column in dataset.numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in df.columns:
        if df[column].dtype == object:
            df[column] = df[column].str.strip()

    return df


def validate_dataframe(df: pd.DataFrame, dataset: BtsDataset, source_name: str) -> None:
    if df.empty:
        raise ValueError(f"{source_name} produced an empty CSV")
    missing = set(dataset.required_columns) - set(df.columns)
    if missing:
        raise ValueError(
            f"{source_name} is missing required {dataset.key} columns: "
            + ", ".join(sorted(missing))
        )

    if dataset.monthly:
        periods = df[["Year", "Month"]].dropna().drop_duplicates()
        if len(periods) != 1:
            raise ValueError(f"{source_name} contains more than one Year/Month period")
        year, month = (int(periods.iloc[0][field]) for field in ("Year", "Month"))
        if not 1 <= month <= 12:
            raise ValueError(f"{source_name} has invalid Month={month}")

    nonnegative = {
        "DepScheduled",
        "DepPerformed",
        "Seats",
        "Passengers",
        "Freight",
        "Mail",
        "Distance",
    }
    for column in sorted(nonnegative & set(df.columns)):
        if (df[column].dropna() < 0).any():
            raise ValueError(f"{source_name} has negative values in {column}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest() -> dict:
    if not BTS_MANIFEST_FILE.exists():
        return {"version": 1, "files": []}
    try:
        payload = json.loads(BTS_MANIFEST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read BTS manifest {BTS_MANIFEST_FILE}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files", []), list):
        raise RuntimeError(f"Invalid BTS manifest shape: {BTS_MANIFEST_FILE}")
    return payload


def _save_manifest(manifest: dict) -> None:
    BTS_MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = BTS_MANIFEST_FILE.with_name(f"{BTS_MANIFEST_FILE.name}.part")
    temporary.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, BTS_MANIFEST_FILE)


def _output_path(dataset: BtsDataset, raw_path: Path, period: tuple[int, int] | None) -> Path:
    if dataset.monthly:
        if period is None:
            raise ValueError(f"Cannot derive a period from monthly file {raw_path.name}")
        year, month = period
        return dataset.clean_dir / f"{dataset.key}_{year}_{month:02d}.csv"
    return dataset.clean_dir / f"{dataset.key}.csv"


def _manifest_record(
    dataset: BtsDataset,
    zip_path: Path,
    output_path: Path,
    frame: pd.DataFrame,
    period: tuple[int, int] | None,
    status: str,
) -> dict:
    return {
        "dataset": dataset.key,
        "label": dataset.label,
        "source_url": dataset.url,
        "grain": dataset.grain,
        "raw_file": str(zip_path),
        "raw_sha256": _sha256(zip_path),
        "clean_file": str(output_path),
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": list(frame.columns),
        "period": f"{period[0]}-{period[1]:02d}" if period else None,
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }


def process_zip(zip_path: Path, dataset: BtsDataset) -> dict:
    """Process one verified raw ZIP and return its manifest record."""
    if not validate_enrichment_download_file(zip_path):
        raise ValueError(f"Refusing to process invalid ZIP: {zip_path}")
    period = parse_period(zip_path) if dataset.monthly else None
    output_path = _output_path(dataset, zip_path, period) if period else None

    dataset.raw_dir.mkdir(parents=True, exist_ok=True)
    dataset.clean_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{dataset.key}-", dir=dataset.raw_dir) as temp:
        csv_path = _extract_csv(zip_path, Path(temp))
        frame = clean_dataframe(_read_csv(csv_path), dataset)
        validate_dataframe(frame, dataset, zip_path.name)
        if dataset.monthly and period is None:
            periods = frame[["Year", "Month"]].dropna().drop_duplicates()
            period = (int(periods.iloc[0]["Year"]), int(periods.iloc[0]["Month"]))
        output_path = _output_path(dataset, zip_path, period)
        temporary = output_path.with_name(f"{output_path.name}.part")
        try:
            frame.to_csv(temporary, index=False)
            os.replace(temporary, output_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    return _manifest_record(dataset, zip_path, output_path, frame, period, "cleaned")


def process_dataset(dataset: BtsDataset) -> list[dict]:
    results = []
    manifest = _load_manifest()
    previous = {
        entry.get("raw_file"): entry
        for entry in manifest["files"]
        if entry.get("dataset") == dataset.key and entry.get("raw_file")
    }
    entries = [entry for entry in manifest["files"] if entry.get("dataset") != dataset.key]
    for zip_path in find_raw_files(dataset):
        result = process_zip(zip_path, dataset)
        if result.get("status") == "already_present" and str(zip_path) in previous:
            # A rerun must not replace a complete provenance record with the
            # small "already_present" status-only result.
            result = {**previous[str(zip_path)], "status": "already_present"}
        results.append(result)
        entries.append(result)
    manifest["files"] = sorted(
        entries,
        key=lambda entry: (entry.get("dataset", ""), entry.get("period") or "", entry.get("raw_file", "")),
    )
    _save_manifest(manifest)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean verified BTS enrichment downloads")
    parser.add_argument("dataset", choices=sorted(DATASETS))
    args = parser.parse_args(argv)
    dataset = get_dataset(args.dataset)
    results = process_dataset(dataset)
    cleaned = sum(result.get("status") == "cleaned" for result in results)
    print(f"Processed {len(results)} {dataset.key} file(s); cleaned {cleaned} new file(s).")
    print(f"Clean files: {dataset.clean_dir}")
    print(f"Manifest: {BTS_MANIFEST_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
