# Airline Operations Decision Intelligence Platform

A FastAPI + Next.js platform for analyzing U.S. airline on-time performance:
carrier/airport/route rankings, delay analytics, and a "Decision Center" of
operations-research tools (MILP schedule optimization, queueing-theory
capacity analysis, Markov-chain delay propagation forecasting, network
resilience/centrality ranking, and a predictive risk model).

See [CLAUDE.md](CLAUDE.md) for architecture details, commands, and
conventions if you're developing on this codebase.

## The data is not in this repo

Everything here runs on U.S. DOT/BTS "Marketing Carrier On-Time Performance"
data, loaded into a local DuckDB warehouse file at
`Data/Warehouse/airline.duckdb`. That file is tens of gigabytes once built
from several years of monthly data — it is **not** included in this repo
and there is no hosted download for it. To use this app, you build your own
warehouse from BTS's public data using the scripts in `pipeline/`. This is
free (BTS data is public) but takes real time and disk space — expect a
multi-hour, multi-step process for a multi-year dataset, not something that
finishes in a minute.

### Step 1 — Download raw monthly data from BTS

```bash
python -m pipeline.download
```

This is interactive: it asks for a year or year range (data is available
from 2018 onward), then drives a real Chrome browser via Selenium against
BTS's public download form to fetch one zip file per month. You need Google
Chrome installed — `webdriver-manager` (already in `requirements.txt`)
downloads a matching driver automatically, no manual setup needed. It
pauses 5 seconds between each monthly file to avoid hammering BTS's server,
so a multi-year request can take a while (dozens of files, each with its
own wait). Files land in `Data/Raw/`. The script skips months it can see
are already downloaded, so it's safe to re-run if it gets interrupted.

### Step 2 — Clean and flatten into CSV

```bash
python -m pipeline.clean
```

Also interactive (confirms before processing). It unzips each file in
`Data/Raw/`, keeps the full BTS column set (no field subsetting), does
generic type cleanup (parses date columns, coerces delay/time/distance
columns to numeric, drops the stray `Unnamed:` artifact column BTS CSVs
tend to include, drops rows with a null `FlightDate`), and writes one CSV
per month to `Data/Clean/` as `OTP_<year>_<month>_<MonthName>.csv`. Already-
processed months are skipped on re-run.

### Step 3 — Build the DuckDB warehouse

```bash
python -m pipeline.build_warehouse
```

Not interactive. This loads every `Data/Clean/OTP_*.csv` file into a staged
DuckDB database, validates that the resulting `flights` table is non-empty,
then atomically promotes it to `Data/Warehouse/airline.duckdb`. This is a
full rebuild, not incremental, so run it once after Step 2 has produced all
the months you want. A failed build leaves the previous warehouse in place.

Once this finishes, the warehouse path defaults to
`Data/Warehouse/airline.duckdb`; override it with the `AIRLINE_DUCKDB_PATH`
environment variable if you want it elsewhere. From here, follow the
backend/frontend setup steps in [TESTING_GUIDE.md](TESTING_GUIDE.md)
(Step 2 onward — skip its Step 1, which assumes you're copying an existing
warehouse file rather than building one) to install dependencies, set your
`ANTHROPIC_API_KEY` (only needed for the Copilot chat feature), and run the
app.

### Step 4 — Materialize the dashboard analytics layer

The raw `flights` table is always the source of truth. After a full build, the
pipeline creates five compact, deterministic tables for the pages that are
visited most often: network-month, carrier-month, route-month, airport-month,
and route + carrier + departure-hour. They contain derived counts and rates,
not fabricated observations. They are rebuilt automatically by
`pipeline.build_warehouse` and refreshed by `pipeline.auto_update`.

To refresh them manually after importing an existing warehouse:

```bash
python -m pipeline.materialize_analytics
```

This makes the public rankings and the historical route baseline fast without
changing the underlying data or analytical definitions.

### Optional — add real BTS capacity and identity data

The app can be enriched with official BTS T-100 Segment/Market data and the
time-aware Carrier Decode, Master Coordinate, and AircraftTypes support tables.
These are kept in separate native-grain tables so monthly aggregate traffic is
never duplicated across individual flights. See [DATA_SOURCES.md](DATA_SOURCES.md)
for the verified source mapping, commands, validation rules, and limitations.

For a small first run:

```powershell
python -m pipeline.download_bts t100_segment --years 2025
python -m pipeline.clean_bts t100_segment
python -m pipeline.load_bts
```

For a full historical enrichment, replace `2025` with the desired range, for
example `2018-2026`. The downloader skips validated files already present in
`Data/Raw/bts/`, so an interrupted run can be resumed. The latest available
month depends on what BTS has published when the command is run; the local
warehouse used for this project currently contains T-100 through May 2026 and
OTP through June 2026.

The API exposes the resulting provenance through `/api/data-sources`, route-month
capacity context through `/api/capacity/summary`, a grain-matched T-100 vs.
on-time comparison through `/api/capacity/correlation`, and a simple monthly
trend through `/api/capacity/trend`. The Researcher view has both a dedicated
T-100 page and a Decision Center tab for that comparison. T-100 freshness can
be checked manually with `python -m pipeline.auto_update_bts`; the process
records its result in `Data/t100_pipeline_state.json`, reloads only the T-100
table when a verified BTS ZIP is available, and never fabricates an unpublished
month.
Before the enrichment tables are loaded, those endpoints report that state
explicitly; they do not substitute fabricated values.

### Verifying it worked

```bash
python scripts/check_deployment_readiness.py
```

should report your warehouse's real file size and row count instead of
"not found."
