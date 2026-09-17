"""Tests for choosing the compact OTP layer without hiding fallbacks."""

import duckdb

from api.db import CORE_FLIGHT_TABLE, best_flight_table


def test_preferred_source_uses_compact_layer_when_columns_are_available():
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            f"CREATE TABLE {CORE_FLIGHT_TABLE} (FlightDate DATE, Cancelled INTEGER, ArrDelay DOUBLE)"
        )
        assert best_flight_table(connection, {"FlightDate", "Cancelled"}) == CORE_FLIGHT_TABLE
    finally:
        connection.close()


def test_preferred_source_falls_back_to_raw_flights_for_missing_columns():
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE flights (FlightDate DATE, Tail_Number VARCHAR)")
        connection.execute(f"CREATE TABLE {CORE_FLIGHT_TABLE} (FlightDate DATE)")
        assert best_flight_table(connection, {"Tail_Number"}) == "flights"
    finally:
        connection.close()
