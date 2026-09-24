"""Regression coverage for the compact public profile layer."""

import duckdb
import pytest

from api.analytics import airport_public_profile, carrier_public_profile
from pipeline.materialize_analytics import build_profile_summary_tables


@pytest.fixture
def profile_connection():
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE flights (
            FlightDate DATE,
            Marketing_Airline_Network VARCHAR,
            Origin VARCHAR,
            Dest VARCHAR,
            Cancelled INTEGER,
            Diverted INTEGER,
            ArrDelay DOUBLE,
            ArrDel15 INTEGER
        )
        """
    )
    connection.executemany(
        "INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("2024-01-01", "AA", "ORD", "LAX", 0, 0, 5.0, 0),
            ("2024-01-02", "AA", "LAX", "ORD", 0, 0, 65.0, 1),
            ("2024-02-01", "AA", "ORD", "DFW", 1, 0, None, None),
        ],
    )
    # Carrier-month is an existing dashboard aggregate. The one-off profile
    # refresh deliberately leaves it untouched, so model that production
    # dependency here rather than making the helper silently use raw rows.
    connection.execute(
        """
        CREATE TABLE analytics_carrier_month (
            carrier VARCHAR,
            year_month VARCHAR,
            total_flights BIGINT,
            completed_flights BIGINT,
            on_time_rate DOUBLE,
            avg_arrival_delay_minutes DOUBLE,
            cancellation_rate DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO analytics_carrier_month VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("AA", "2024-01", 2, 2, 0.5, 35.0, 0.0),
            ("AA", "2024-02", 1, 0, None, None, 1.0),
        ],
    )
    build_profile_summary_tables(connection)
    # The fast public airport profile gets its top connections from the
    # already-materialized route-month aggregate, never from a fresh scan of
    # the raw flight table.
    connection.execute(
        """
        CREATE TABLE analytics_route_month (
            origin VARCHAR,
            dest VARCHAR,
            year_month VARCHAR,
            total_flights BIGINT,
            on_time_rate DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO analytics_route_month VALUES (?, ?, ?, ?, ?)",
        [
            ("ORD", "LAX", "2024-01", 20, 0.90),
            ("ORD", "LAX", "2024-02", 10, 0.80),
            ("LAX", "ORD", "2024-01", 8, 0.75),
            ("ORD", "DFW", "2024-02", 5, 0.60),
        ],
    )
    yield connection
    connection.close()


def test_carrier_public_profile_uses_compact_tables(profile_connection):
    profile = carrier_public_profile(profile_connection, "AA")

    assert profile is not None
    assert profile["total_flights"] == 3
    assert profile["on_time_rate"] == pytest.approx(0.5)
    assert len(profile["months"]) == 2
    assert profile["health"]["sample"]["completed_flights"] == 2


def test_airport_public_profile_counts_an_airport_once_per_flight(profile_connection):
    profile = airport_public_profile(profile_connection, "ORD")

    assert profile is not None
    assert profile["total_flights"] == 3
    assert profile["on_time_rate"] == pytest.approx(0.5)
    assert [month["month"] for month in profile["months"]] == ["2024-01", "2024-02"]
    assert profile["top_routes"][0]["route"] == "ORD → LAX"
    assert profile["top_routes"][0]["total_flights"] == 30
