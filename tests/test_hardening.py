"""Regression tests for the data-safety and operational hardening pass."""

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.metrics import COMPLETED_FLIGHT_SQL, ON_TIME_FLAG_SQL, SEVERE_DELAY_SQL
from api.optimization.departure_bank import BankFlight, solve_departure_bank
from api.optimization.network_protection import InterventionCandidate, solve_portfolio
from pipeline.clean import parse_year_month
from pipeline.download import validate_download_file


def test_canonical_metrics_are_explicit_and_completed_scoped():
    assert ON_TIME_FLAG_SQL == "ArrDel15 = 0"
    assert "Cancelled = 0" in COMPLETED_FLIGHT_SQL
    assert "Diverted = 0" in COMPLETED_FLIGHT_SQL
    assert "ArrDelay IS NOT NULL" in COMPLETED_FLIGHT_SQL
    assert COMPLETED_FLIGHT_SQL in SEVERE_DELAY_SQL


def test_download_validator_rejects_non_zip_and_accepts_one_csv(tmp_path):
    invalid = tmp_path / "download.zip"
    invalid.write_text("not a zip")
    assert not validate_download_file(str(invalid))

    valid = tmp_path / "On_Time_2026_6.zip"
    with zipfile.ZipFile(valid, "w") as archive:
        archive.writestr("On_Time_2026_6.csv", "FlightDate,Cancelled\n2026-06-01,0\n")
    assert validate_download_file(str(valid), expected_year=2026, expected_month=6)
    assert not validate_download_file(str(valid), expected_year=2026, expected_month=5)


def test_cleaner_parses_chrome_duplicate_suffix():
    assert parse_year_month("On_Time_2026_6 (1).zip") == (2026, 6)
    assert parse_year_month("On_Time_2026_13.zip") == (None, None)


def test_departure_bank_respects_max_moved_flights():
    flights = [BankFlight(f"F{i}", original_bucket=20) for i in range(8)]
    limit = {bucket: 2.0 for bucket in range(96)}
    weights = {bucket: 1.0 for bucket in range(96)}
    delays = {bucket: 10.0 for bucket in range(96)}

    result = solve_departure_bank(
        flights,
        n_buckets=96,
        allowed_shift_minutes=30,
        preferred_bank_limit=limit,
        congestion_weight_by_bucket=weights,
        bucket_delay_point_estimate=delays,
        max_moved_flights=1,
    )
    assert result.status == "optimal"
    assert result.flights_moved <= 1


def test_portfolio_rejects_invalid_budget_and_cost():
    candidate = InterventionCandidate("A", "airport", 1.0, {"metric": 1.0})
    with pytest.raises(ValueError, match="budget"):
        solve_portfolio([candidate], budget=-1, primary_metric="metric")

    bad_cost = InterventionCandidate("B", "airport", 0.0, {"metric": 1.0})
    with pytest.raises(ValueError, match="positive cost"):
        solve_portfolio([bad_cost], budget=1, primary_metric="metric")
