# config.py
# Central configuration for the Airline Operations Decision Intelligence Platform.

from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else (BASE_DIR / candidate).resolve()


# Runtime paths can be overridden without modifying source code. Relative overrides
# are resolved from the repository root so scheduled jobs and shells behave alike.
DATA_DIR = _path_from_env("AIRLINE_DATA_DIR", BASE_DIR / "Data")
RAW_DIR = DATA_DIR / "Raw"
CLEAN_DIR = DATA_DIR / "Clean"
# Additional BTS datasets live in their own namespaces. Keeping them separate
# from the flight-level On-Time files prevents a monthly aggregate from being
# accidentally treated as one row per flight.
BTS_RAW_DIR = RAW_DIR / "bts"
BTS_CLEAN_DIR = CLEAN_DIR / "bts"
BTS_MANIFEST_FILE = DATA_DIR / "bts_manifest.json"
OUTPUT_DIR = _path_from_env("AIRLINE_OUTPUT_DIR", BASE_DIR / "Outputs")
LOG_DIR = _path_from_env("AIRLINE_LOG_DIR", BASE_DIR / "Logs")
NOTEBOOK_DIR = BASE_DIR / "Notebooks"

APRIL_2026_FILE = DATA_DIR / "OTP_APR2026.csv"
PIPELINE_STATE_FILE = DATA_DIR / "pipeline_state.json"
T100_PIPELINE_STATE_FILE = DATA_DIR / "t100_pipeline_state.json"
# A single, human-readable record for the coordinated monthly refresh.  This
# stays under Data/ (which is intentionally ignored by Git) because it
# describes the local warehouse, not portable source code.
REFRESH_STATE_FILE = DATA_DIR / "refresh_state.json"
CONSOLIDATED_FILE = DATA_DIR / "OTP_CONSOLIDATED_ALL.csv"
WAREHOUSE_DIR = DATA_DIR / "Warehouse"
DUCKDB_FILE = _path_from_env(
    "AIRLINE_DUCKDB_PATH",
    WAREHOUSE_DIR / "airline.duckdb",
)

# Preserve the established local workflow while allowing read-only deployments to
# opt out of directory creation.
if os.getenv("AIRLINE_CREATE_RUNTIME_DIRS", "1").strip().lower() not in {"0", "false", "no"}:
    for folder in [
        DATA_DIR,
        RAW_DIR,
        CLEAN_DIR,
        BTS_RAW_DIR,
        BTS_CLEAN_DIR,
        WAREHOUSE_DIR,
        OUTPUT_DIR,
        LOG_DIR,
        NOTEBOOK_DIR,
    ]:
        folder.mkdir(parents=True, exist_ok=True)


ON_TIME_THRESHOLD = 15
TIGHT_TURNAROUND = 25
TARGET_TURNAROUND = 45
MAJOR_DELAY = 60

# Operational safeguards. These are deliberately environment-configurable so a
# small local machine and a larger deployment can use different limits without
# changing the analytical formulas.
DEFAULT_HEAVY_LOOKBACK_DAYS = int(os.getenv("AIRLINE_DEFAULT_HEAVY_LOOKBACK_DAYS", "365"))
DEFAULT_MODEL_LOOKBACK_DAYS = int(os.getenv("AIRLINE_DEFAULT_MODEL_LOOKBACK_DAYS", "1825"))
PIPELINE_ADMIN_TOKEN = os.getenv("PIPELINE_ADMIN_TOKEN", "").strip()
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()

BG_COLOR = "#0f1117"
GRID_COLOR = "#222233"
SPINE_COLOR = "#333344"
TEXT_COLOR = "#aaaaaa"
WHITE = "white"

COLOR_GOOD = "#00cc88"
COLOR_WARN = "#ffcc00"
COLOR_BAD = "#ff8800"
COLOR_CRITICAL = "#ff4444"
COLOR_ACCENT = "#4488ff"
COLOR_HIGHLIGHT = "#ff8800"

SOURCE_NOTE = "Source: BTS Marketing Carrier On-Time Performance"
