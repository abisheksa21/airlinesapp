"""Check the portable source contract of a freshly cloned repository.

This intentionally does *not* require a multi-gigabyte DuckDB warehouse.  A
clean clone should contain source, dependency manifests, run instructions, and
no tracked local warehouse.  If ``--warehouse`` is supplied, the script also
opens that external local database and checks the app's expected base table.
"""

from __future__ import annotations

import argparse
import compileall
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = (
    "README.md",
    "RUNNING_GUIDE.md",
    "requirements.txt",
    "frontend/package.json",
    "api/main.py",
    "pipeline/refresh_all.py",
    "start_app.ps1",
    "start_app.sh",
)
# A few small, documented reference fixtures may be intentionally tracked at
# the repository root. The portability problem is the local pipeline output:
# raw/clean BTS files, generated warehouse files, logs, and other runtime
# artifacts. Keep the rule scoped to those locations so a legitimate source
# fixture is not mistaken for a copy of the warehouse.
FORBIDDEN_TRACKED_PREFIXES = ("Data/", "Outputs/", "Logs/", ".venv/", "frontend/.next/")
FORBIDDEN_TRACKED_SUFFIXES = (".duckdb", ".zip", ".parquet")


def _git_files() -> list[str] | None:
    try:
        completed = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def _warehouse_status(path: Path) -> dict:
    if not path.exists():
        return {"available": False, "path": str(path), "reason": "file not found"}
    try:
        import duckdb

        connection = duckdb.connect(str(path), read_only=True)
        try:
            flights = int(connection.execute("SELECT COUNT(*) FROM flights").fetchone()[0])
        finally:
            connection.close()
        return {"available": True, "path": str(path), "flights": flights}
    except Exception as exc:
        return {"available": False, "path": str(path), "reason": f"{type(exc).__name__}: {exc}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", type=Path, help="Optional external DuckDB file to open read-only.")
    parser.add_argument("--run-tests", action="store_true", help="Run the backend test suite after static checks.")
    args = parser.parse_args(argv)

    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).is_file()]
    compilation_ok = compileall.compile_dir(ROOT / "api", quiet=1) and compileall.compile_dir(ROOT / "pipeline", quiet=1)
    tracked_files = _git_files()
    forbidden_tracked: list[str] = []
    data_paths_tracked: list[str] = []
    if tracked_files is not None:
        forbidden_tracked = [
            path for path in tracked_files
            if path.startswith(FORBIDDEN_TRACKED_PREFIXES) or path.lower().endswith(FORBIDDEN_TRACKED_SUFFIXES)
        ]
        data_paths_tracked = [path for path in tracked_files if path.startswith("Data/")]

    tests_ok: bool | None = None
    if args.run_tests:
        tests_ok = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT).returncode == 0

    warehouse = _warehouse_status(args.warehouse) if args.warehouse else {
        "available": False,
        "reason": "not requested; expected for a clean source clone",
    }
    report = {
        "repository": str(ROOT),
        "required_paths_missing": missing,
        "python_compilation_ok": bool(compilation_ok),
        "git_inventory_available": tracked_files is not None,
        "tracked_data_paths": data_paths_tracked,
        "tracked_large_data_files": forbidden_tracked,
        "tests_ok": tests_ok,
        "warehouse": warehouse,
        "next_step": "Follow RUNNING_GUIDE.md to build or attach a local BTS DuckDB warehouse.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    passed = not missing and compilation_ok and not forbidden_tracked and not data_paths_tracked
    if tests_ok is False:
        passed = False
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
