"""Tests for the explicit OTP core feature layer."""

import duckdb
import pytest

from pipeline.otp_core import CORE_TABLE_NAME, OTP_CORE_COLUMNS, build_otp_core_table


def _source_columns_sql() -> str:
    columns = []
    for name in OTP_CORE_COLUMNS:
        if name == "FlightDate":
            dtype = "DATE"
        elif name in {"Marketing_Airline_Network", "Operating_Airline", "Tail_Number", "Origin", "Dest"}:
            dtype = "VARCHAR"
        else:
            dtype = "DOUBLE"
        columns.append(f'"{name}" {dtype}')
    columns.append('"unused_source_column" VARCHAR')
    return ", ".join(columns)


def test_core_projection_is_explicit_and_drops_unneeded_source_columns():
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"CREATE TABLE flights ({_source_columns_sql()})")
        placeholders = ", ".join(["?"] * (len(OTP_CORE_COLUMNS) + 1))
        values = [None] * len(OTP_CORE_COLUMNS) + ["should not be copied"]
        values[0] = "2025-01-01"
        values[9] = "AAA"
        values[10] = "BBB"
        values[6] = "ZZ"
        connection.execute(f"INSERT INTO flights VALUES ({placeholders})", values)

        assert build_otp_core_table(connection) == 1
        columns = [row[0] for row in connection.execute(f"DESCRIBE {CORE_TABLE_NAME}").fetchall()]
        assert columns == list(OTP_CORE_COLUMNS)
        assert connection.execute(
            f"SELECT COUNT(*) FROM {CORE_TABLE_NAME} WHERE Origin = 'AAA' AND Dest = 'BBB'"
        ).fetchone()[0] == 1
    finally:
        connection.close()

def test_core_projection_fails_loudly_when_source_schema_is_incomplete():
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE flights (FlightDate DATE)")
        with pytest.raises(RuntimeError, match="source columns are missing"):
            build_otp_core_table(connection)
    finally:
        connection.close()
