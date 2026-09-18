"""Run the local BTS refresh as one explicit, reproducible sequence.

The two BTS source families publish on independent schedules.  This wrapper
checks OTP first, then T-100, then rebuilds compact derived tables exactly
once.  It records the local outcome in ``Data/refresh_state.json`` so a
researcher can tell whether a dashboard reflects a successful refresh, a
normal "not published yet" stop, or a failure that needs attention.

Examples
--------
    python -m pipeline.refresh_all
    python -m pipeline.refresh_all --skip-otp
    python -m pipeline.refresh_all --materialize-only
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

import duckdb

from config import DUCKDB_FILE, REFRESH_STATE_FILE
from pipeline.materialize_analytics import build_analytics_tables


def _write_state(state: dict) -> None:
    REFRESH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = REFRESH_STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(REFRESH_STATE_FILE)


def _run_step(name: str, operation: Callable[[], int]) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        exit_code = int(operation())
        status = "ok" if exit_code == 0 else "error"
        return {
            "status": status,
            "exit_code": exit_code,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # each source updater has its own detailed log
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }


def _materialize() -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    if not DUCKDB_FILE.exists():
        return {
            "status": "skipped",
            "reason": f"Warehouse not found: {DUCKDB_FILE}",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    connection = duckdb.connect(str(DUCKDB_FILE), read_only=False)
    try:
        counts = build_analytics_tables(connection)
        return {
            "status": "ok",
            "tables": counts,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh OTP, T-100, and compact analytical tables in order."
    )
    parser.add_argument("--skip-otp", action="store_true", help="Do not check the OTP source.")
    parser.add_argument("--skip-t100", action="store_true", help="Do not check T-100 sources.")
    parser.add_argument(
        "--materialize-only",
        action="store_true",
        help="Rebuild compact analytical tables without downloading BTS data.",
    )
    args = parser.parse_args(argv)

    if args.materialize_only:
        args.skip_otp = True
        args.skip_t100 = True

    state: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "warehouse": str(DUCKDB_FILE),
        "steps": {},
        "result": "running",
    }
    _write_state(state)

    if not args.skip_otp:
        from pipeline import auto_update

        state["steps"]["otp"] = _run_step("otp", auto_update.main)
        _write_state(state)

    if not args.skip_t100:
        from pipeline import auto_update_bts

        state["steps"]["t100"] = _run_step("t100", auto_update_bts.main)
        _write_state(state)

    state["steps"]["analytics"] = _materialize()
    errors = [step for step in state["steps"].values() if step.get("status") == "error"]
    state["result"] = "error" if errors else "ok"
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_state(state)
    print(json.dumps(state, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
