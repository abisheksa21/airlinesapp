"""Tests for the source-backed BTS enrichment pipeline."""

import json
import sys
import zipfile
from pathlib import Path

import duckdb
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline.bts_sources as bts_sources
import pipeline.clean_bts as clean_bts
from pipeline.bts_sources import T100_SEGMENT, validate_enrichment_download_file
from pipeline.clean_bts import clean_dataframe, parse_period, process_zip, validate_dataframe
from pipeline.load_bts import load_bts_tables


def _segment_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Year": 2025,
                "Month": 1,
                "UniqueCarrier": "ZZ",
                "AirlineID": 999,
                "OriginAirportID": 1,
                "DestAirportID": 2,
                "Origin": "AAA",
                "Dest": "BBB",
                "DepScheduled": 10,
                "DepPerformed": 9,
                "Seats": 900,
                "Passengers": 720,
                "Distance": 500,
                "Class": "F",
                "AircraftType": 123,
                "Freight": 10,
                "Mail": 2,
            }
        ]
    )


def test_catalog_uses_official_native_grains_and_separate_namespaces():
    assert T100_SEGMENT.url.startswith("https://www.transtats.bts.gov/DL_SelectFields.aspx")
    assert "aircraft type" in T100_SEGMENT.grain
    assert T100_SEGMENT.raw_dir != T100_SEGMENT.clean_dir
    assert set(("t100_segment", "t100_market", "master_coordinate")) <= set(bts_sources.DATASETS)


def test_period_parser_accepts_canonical_and_chrome_suffixes():
    assert parse_period("t100_segment_2025_01.zip") == (2025, 1)
    assert parse_period("T100_2025_12 (1).zip") == (2025, 12)
    assert parse_period("t100_segment.zip") is None


def test_cleaner_preserves_native_rows_and_validates_required_fields():
    frame = clean_dataframe(_segment_frame(), T100_SEGMENT)
    validate_dataframe(frame, T100_SEGMENT, "fixture.csv")
    assert len(frame) == 1
    assert frame["Seats"].dtype.kind in "iu"
    with pytest.raises(ValueError, match="missing required"):
        validate_dataframe(frame.drop(columns=["Passengers"]), T100_SEGMENT, "fixture.csv")


def test_process_zip_writes_provenance_and_atomic_clean_file(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    clean_dir = tmp_path / "clean"
    manifest_path = tmp_path / "bts_manifest.json"
    raw_dir.mkdir()
    monkeypatch.setattr(bts_sources, "BTS_RAW_DIR", raw_dir)
    monkeypatch.setattr(bts_sources, "BTS_CLEAN_DIR", clean_dir)
    monkeypatch.setattr(clean_bts, "BTS_MANIFEST_FILE", manifest_path)

    source_csv = "\n".join(
        [
            "DEPARTURES_SCHEDULED,DEPARTURES_PERFORMED,SEATS,PASSENGERS,DISTANCE,UNIQUE_CARRIER,AIRLINE_ID,ORIGIN_AIRPORT_ID,DEST_AIRPORT_ID,ORIGIN,DEST,AIRCRAFT_TYPE,YEAR,MONTH,CLASS",
            "10,9,900,720,500,ZZ,999,1,2,AAA,BBB,123,2025,1,F",
        ]
    )
    zip_path = raw_dir / "t100_segment_2025_01.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("source.csv", source_csv)
        archive.writestr("Documentation.csv", "field,description\nPassengers,example\n")

    assert validate_enrichment_download_file(zip_path)
    result = process_zip(zip_path, T100_SEGMENT)
    clean_path = Path(result["clean_file"])
    assert clean_path.exists()
    assert result["row_count"] == 1
    assert len(result["raw_sha256"]) == 64
    assert "DepScheduled" in result["columns"]

    manifest = {"version": 1, "files": [result]}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["files"][0]["dataset"] == "t100_segment"


def test_loader_builds_route_month_view_without_flight_duplication(tmp_path, monkeypatch):
    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    monkeypatch.setattr(bts_sources, "BTS_CLEAN_DIR", clean_root)
    T100_SEGMENT.clean_dir.mkdir(parents=True, exist_ok=True)
    T100_SEGMENT.clean_dir.joinpath("t100_segment_2025_01.csv").write_text(
        _segment_frame().to_csv(index=False), encoding="utf-8"
    )

    db_path = tmp_path / "warehouse.duckdb"
    connection = duckdb.connect(str(db_path))
    try:
        summaries = load_bts_tables(connection, ["t100_segment"])
        row = connection.execute(
            """
            SELECT Year, Month, Origin, Dest, seats_available, passengers,
                   load_factor, completion_rate, source_rows
            FROM bts_t100_segment_route_month
            """
        ).fetchone()
    finally:
        connection.close()

    assert summaries[0]["status"] == "loaded"
    assert row[:6] == (2025, 1, "AAA", "BBB", 900, 720)
    assert row[6] == pytest.approx(0.8)
    assert row[7] == pytest.approx(0.9)
    assert row[8] == 1
