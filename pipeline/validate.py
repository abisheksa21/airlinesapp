import duckdb

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import DATA_DIR, DUCKDB_FILE


def main() -> None:
    print("=" * 60)
    print("VALIDATING DUCKDB WAREHOUSE")
    print("=" * 60)

    connection = duckdb.connect(str(DUCKDB_FILE), read_only=True)

    try:
        # The duplicate-key audit groups the full flight history.  Keep it
        # usable on the same laptop that stores the warehouse by allowing
        # DuckDB to spill intermediate state to a project-local temp folder.
        validation_temp = DATA_DIR / "Warehouse" / ".validate_tmp"
        validation_temp.mkdir(parents=True, exist_ok=True)
        temp_path = str(validation_temp.resolve()).replace("\\", "/").replace("'", "''")
        connection.execute(f"SET temp_directory = '{temp_path}'")
        connection.execute("SET memory_limit = '1GB'")
        connection.execute("SET threads = 1")
        connection.execute("SET preserve_insertion_order = false")

        schema = {
            row[0]
            for row in connection.execute("DESCRIBE flights").fetchall()
        }
        required_columns = {"FlightDate", "Origin", "Dest", "Cancelled", "Diverted", "ArrDel15"}
        missing_columns = required_columns - schema
        if missing_columns:
            raise RuntimeError(
                "Missing required warehouse columns: " + ", ".join(sorted(missing_columns))
            )

        row_count = connection.execute(
            "SELECT COUNT(*) FROM flights"
        ).fetchone()[0]

        column_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'flights'
            """
        ).fetchone()[0]

        date_range = connection.execute(
            """
            SELECT
                MIN(FlightDate),
                MAX(FlightDate)
            FROM flights
            """
        ).fetchone()

        carrier_count = connection.execute(
            """
            SELECT COUNT(DISTINCT Marketing_Airline_Network)
            FROM flights
            WHERE Marketing_Airline_Network IS NOT NULL
            """
        ).fetchone()[0]

        month_count = connection.execute(
            """
            SELECT COUNT(
                DISTINCT STRFTIME(FlightDate, '%Y-%m')
            )
            FROM flights
            WHERE FlightDate IS NOT NULL
            """
        ).fetchone()[0]

        null_date_count = connection.execute(
            "SELECT COUNT(*) FROM flights WHERE FlightDate IS NULL"
        ).fetchone()[0]
        invalid_flag_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM flights
            WHERE Cancelled IS NULL OR Cancelled NOT IN (0, 1)
               OR Diverted IS NULL OR Diverted NOT IN (0, 1)
            """
        ).fetchone()[0]
        marketing_flight_number = (
            "Flight_Number_Marketing_Airline"
            if "Flight_Number_Marketing_Airline" in schema
            else "Mkt_Carrier_Fl_Num"
        )
        duplicate_business_keys = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT FlightDate, Marketing_Airline_Network, {marketing_flight_number},
                       Origin, Dest, CRSDepTime, Tail_Number
                FROM flights
                GROUP BY ALL
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        tail_count = connection.execute(
            """
            SELECT COUNT(DISTINCT Tail_Number)
            FROM flights
            WHERE Tail_Number IS NOT NULL
            """
        ).fetchone()[0]

        cancellation_count = connection.execute(
            """
            SELECT SUM(Cancelled)
            FROM flights
            """
        ).fetchone()[0]

        diversion_count = connection.execute(
            """
            SELECT SUM(Diverted)
            FROM flights
            """
        ).fetchone()[0]

        print(f"Rows              : {row_count:,}")
        print(f"Columns           : {column_count}")
        print(f"Date range        : {date_range[0]} to {date_range[1]}")
        print(f"Year-month periods: {month_count}")
        print(f"Null FlightDate   : {null_date_count:,}")
        print(f"Invalid flags     : {invalid_flag_count:,}")
        print(f"Duplicate keys    : {duplicate_business_keys:,} groups (review if non-zero)")
        print(f"Unique carriers   : {carrier_count}")
        print(f"Unique tail nums  : {tail_count:,}")
        print(f"Cancelled flights : {int(cancellation_count):,}")
        print(f"Diverted flights  : {int(diversion_count):,}")

        print("\nTop 10 carriers:")
        carriers = connection.execute(
            """
            SELECT
                Marketing_Airline_Network,
                COUNT(*) AS flights
            FROM flights
            WHERE Marketing_Airline_Network IS NOT NULL
            GROUP BY Marketing_Airline_Network
            ORDER BY flights DESC
            LIMIT 10
            """
        ).fetchall()

        for carrier, flights in carriers:
            print(f"  {carrier:<5} {flights:>10,}")

        if null_date_count or invalid_flag_count:
            raise RuntimeError("Warehouse validation failed: critical data-quality checks are non-zero.")
        print("\nWarehouse validation passed.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
