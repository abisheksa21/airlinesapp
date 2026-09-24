"""Regression tests for public-directory date and entity filtering."""

from contextlib import contextmanager
from datetime import date

import duckdb
import pytest
from fastapi import HTTPException

from api import main


@pytest.fixture
def directory_connection(monkeypatch):
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
            (date(2024, 1, 1), "AA", "ORD", "LAX", 0, 0, 5.0, 0),
            (date(2024, 1, 2), "DL", "LAX", "ORD", 0, 0, 20.0, 1),
            # A same-airport record must count once, not once as origin and
            # again as destination, in the airport event directory.
            (date(2024, 1, 3), "AA", "ORD", "ORD", 0, 0, 0.0, 0),
            (date(2024, 2, 1), "AA", "ORD", "DFW", 1, 0, None, None),
        ],
    )

    @contextmanager
    def database_context():
        yield connection

    monkeypatch.setattr(main, "open_readonly_connection", lambda: database_context())
    yield connection
    connection.close()


def test_partial_date_carrier_filter_uses_exact_flights(directory_connection):
    result = main.public_directory_scope_endpoint(
        kind="carrier",
        carrier="AA",
        start_date="2024-01-01",
        end_date="2024-01-31",
        limit=50,
    )

    assert result["scope_method"] == "exact flight dates"
    assert result["rows"] == [
        {
            "carrier": "AA",
            "total_flights": 2,
            "completed_flights": 2,
            "on_time_rate": 1.0,
            "avg_arrival_delay_minutes": 2.5,
            "cancellation_rate": 0.0,
        }
    ]


def test_partial_date_airport_filter_deduplicates_same_airport_flight(directory_connection):
    result = main.public_directory_scope_endpoint(
        kind="airport",
        airport="ORD",
        start_date="2024-01-01",
        end_date="2024-01-31",
        limit=50,
    )

    ord_row = next(row for row in result["rows"] if row["airport"] == "ORD")
    assert ord_row["total_flights"] == 3
    assert ord_row["completed_flights"] == 3
    assert ord_row["on_time_rate"] == pytest.approx(2 / 3)


def test_partial_date_route_filter_keeps_direction(directory_connection):
    result = main.public_directory_scope_endpoint(
        kind="route",
        origin="ORD",
        dest="LAX",
        start_date="2024-01-01",
        end_date="2024-01-31",
        limit=50,
    )

    assert result["rows"] == [
        {
            "route": "ORD → LAX",
            "total_flights": 1,
            "completed_flights": 1,
            "on_time_rate": 1.0,
            "avg_arrival_delay_minutes": 5.0,
            "cancellation_rate": 0.0,
        }
    ]


def test_complete_month_range_uses_weighted_monthly_rates(directory_connection):
    directory_connection.execute(
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
    directory_connection.executemany(
        "INSERT INTO analytics_carrier_month VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("AA", "2024-01", 2, 1, 1.0, 10.0, 0.0),
            ("AA", "2024-02", 9, 8, 0.5, 20.0, 0.1),
        ],
    )

    result = main.public_directory_scope_endpoint(
        kind="carrier",
        carrier="AA",
        start_date="2024-01-01",
        end_date="2024-02-29",
        limit=50,
    )

    row = result["rows"][0]
    assert result["scope_method"] == "compact monthly aggregates"
    assert row["total_flights"] == 11
    assert row["completed_flights"] == 9
    assert row["on_time_rate"] == pytest.approx(5 / 9)
    assert row["avg_arrival_delay_minutes"] == pytest.approx(170 / 9)
    assert row["cancellation_rate"] == pytest.approx(0.9 / 11)


def test_date_filter_requires_both_bounds(directory_connection):
    with pytest.raises(HTTPException) as error:
        main.public_directory_scope_endpoint(
            kind="carrier", carrier="AA", start_date="2024-01-01", end_date=None, limit=50
        )

    assert error.value.status_code == 422
