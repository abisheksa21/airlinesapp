# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An airline on-time-performance analytics platform over real US DOT/BTS data (Jan 2018–present, ~60.7M flights, 11 carriers): a FastAPI backend querying a DuckDB warehouse, a Next.js frontend, and a "Decision Center" of real operations-research and statistics tools (MILP optimizers, queueing theory, Markov chains, graph centrality, a trained logistic regression model) — deliberately not an invented composite-score dashboard. See `DEPLOYMENT.md` for hosting, `TESTING_GUIDE.md` for a from-scratch setup walkthrough, `health-score-explained.md` for the Health Score methodology.

**The warehouse file is not in this repo.** `Data/Warehouse/airline.duckdb` (~9.7GB) is gitignored — nothing that touches real flight data works without it. If you have it, point `AIRLINE_DUCKDB_PATH` at it (or place it at the default `Data/Warehouse/airline.duckdb`). Without it, `pipeline/` can build one from scratch from public BTS data (see below), but that's a real download-and-process job, not instant.

## Commands

**Backend** (from repo root, Python 3.11+, venv recommended):
```
pip install -r requirements.txt          # full dev set (pipeline, tests, everything)
uvicorn api.main:app --reload            # dev server on :8000
pytest tests/ -v                         # full suite
pytest tests/test_or_departure_bank.py -v -k test_reduces_peak_load_on_a_clustered_bank  # single test
python scripts/check_deployment_readiness.py   # verifies warehouse path, env, deploy files — run before any deploy
python scripts/smoke_test.py http://127.0.0.1:8000   # hits the real endpoints against a running server, real timings
```
`requirements-deploy.txt` is the leaner set actually used in the deployed Docker image (no pipeline/Selenium/Streamlit/matplotlib) — keep both in sync when adding a real backend dependency; grep `api/*.py` for actual usage before deciding which file(s) need it.

**Frontend** (from `frontend/`):
```
npm install
npm run dev         # :3000, expects backend at NEXT_PUBLIC_API_BASE_URL (frontend/.env.local, defaults to :8000)
npm run typecheck   # tsc --noEmit
npm run build       # next build — this is the real compile check, typecheck alone misses some issues
```
If `next dev` 404s on every route except `/` after a prior `npm run build`, delete `frontend/.next` and restart — stale prod build artifacts left in `.next` can break dev mode (Turbopack-specific quirk, not a code bug).

**Data pipeline** (from repo root, not part of the deployed API — stays local only, see DEPLOYMENT.md §4):
```
python -m pipeline.auto_update    # incremental: finds the latest month in the warehouse, downloads/cleans/appends only what's new
```
`pipeline/download.py` drives BTS's site via Selenium, `pipeline/clean.py` normalizes into the schema `api/*.py` expects, and `pipeline/build_warehouse.py` performs a safe staged full rebuild. `pipeline/auto_update.py` performs the incremental append for new months.

The optional source-backed enrichment pipeline is separate and native-grain:
`pipeline.download_bts` downloads T-100 Segment/Market and BTS support tables,
`pipeline.clean_bts` validates and records SHA-256 provenance, and
`pipeline.load_bts` loads separate `bts_*` tables/views. T-100 is a monthly
aggregate and must not be copied onto each `flights` row. See
`DATA_SOURCES.md` for the source contracts and reproducible commands. Missing
enrichment data is surfaced as unavailable; the application does not invent a
capacity or demand fallback.

## Architecture

### Backend is a router entrypoint plus focused modules
`api/main.py` remains the route entrypoint while focused modules hold shared metrics, database access, optimization, and model logic. Two endpoint families with different intents:
- Plain `/api/*` (carriers, airports, routes, delays, ...) — descriptive queries/aggregates over the warehouse.
- `/api/decision/*` — the Decision Center: real optimizers/models, each backed by its own module under `api/` (not inline in main.py):
  - `api/optimization/departure_bank.py` — MILP, flight-to-15-min-bucket assignment (departure bank smoothing)
  - `api/optimization/network_protection.py` — 0/1 knapsack MILP (portfolio selection)
  - `api/optimization/backend.py` — solver abstraction; `PublicBackend` (HiGHS via `scipy.optimize.milp`) is the one actually used/tested, `GurobiBackend` is written but never executed in this environment — don't treat it as validated
  - `api/predictive_risk.py` — trained logistic regression + Platt calibration, retrained fresh per request (not persisted)
  - `api/queue_pressure.py` — empirical congestion proxy *plus* a real M/G/c queueing-theory estimate (Erlang-C + Allen-Cunneen), reported as two separate numbers, never blended
  - `api/delay_propagation_markov.py` — empirical Markov chain over 4 delay-severity states, multi-step forecasts via matrix power
  - `api/network_graph.py` — route network as a directed graph (`networkx`), degree + betweenness centrality
  - `api/health_score.py` / `api/metrics.py` / `api/rate_limit.py` / `api/copilot.py` — shared scoring, metric definitions, limits, and Copilot
  - `api/schemas.py` / `api/security.py` — request contracts and production protection for state-changing operations

**Project-wide discipline, not just a style preference**: components of any score/metric are always reported separately, never folded into one invented "priority" number (see Health Score's weights, Network Protection Portfolio's per-metric coverage, Network Resilience's separate degree/betweenness). New Decision Center features should follow this.

### DuckDB access
Always through `api.db.open_readonly_connection()` (a context manager, opens a fresh read-only connection per call and closes it) — there's no long-lived pooled connection. All connections are read-only; nothing in `api/` ever opens the warehouse for writing (only `pipeline/` does, and only locally).

### Decision Center frontend is a shared shell with typed tab contracts
`frontend/app/decision-center/page.tsx` is still the shared client shell, but its result contracts now live in `frontend/app/decision-center/types.ts`. The shell owns the common loading/error flow and tab requests; future extraction can move individual tab controls/results without duplicating those contracts.

Decision Center (and 737 MAX, Methodology) are hidden by default: the nav has a **Public View / Researcher View** toggle (`frontend/app/lib/mode.tsx`, `localStorage` key `site_mode_v1`) that gates which nav links render. Easy to forget when testing — visiting `/decision-center` directly still works, but the nav link and some page sections don't appear in Public View.

### Copilot: tiered models, tool-calling loop, one hard-won gotcha
`api/copilot.py` runs a Claude tool-calling loop (`ask_copilot` blocking, `stream_copilot` for SSE) against this project's own query functions as tools. `tier` selects the model: `"public"` → `CLAUDE_MODEL_PUBLIC` (cheaper/faster), `"researcher"` → `CLAUDE_MODEL_RESEARCHER` — same tools, same system prompt, only the model differs.

**If you touch the forced-final-answer path** (`force_final=True` in `_claude_request`/`_claude_stream_request`, used when `max_hops` is reached but the model still wants to call tools): it must keep `thinking: {"type": "disabled"}` alongside `tool_choice: {"type": "none"}`. Confirmed in production that with thinking left on, the model can end its turn (`stop_reason=end_turn`, not truncated) having produced *only* a thinking block and zero visible text — silently returning nothing. This is state-dependent, not per-call-random (identical retries reproduce the identical empty result), so the retry-on-empty logic perturbs the input (an explicit nudge restating the original question) rather than just resending the same request.

### Deployment topology
Three independently-deployed pieces (`DEPLOYMENT.md` has the full walkthrough): **backend** on Render (Docker, needs a persistent disk sized above the warehouse file — the file itself goes on via `scp` to the disk, not baked into the image or committed to git), **frontend** on Vercel, **data pipeline** stays local only (needs a real headless Chrome session BTS's site doesn't tolerate well in constrained containers). `render.yaml` at the repo root drives Render's Blueprint deploy.

**Known constraint, current as of this writing**: on Render's Standard tier (2GB RAM/1 vCPU), several data-heavy Decision Center endpoints hit in the same warm process within one session (e.g. departure-bank-smoothing → network-protection-portfolio → predictive-risk) can still exhaust memory and crash the process — confirmed each endpoint is fine in isolation, so this is cumulative pressure across a sequence, not one query being too expensive. Endpoints that scan the full unscoped warehouse are a known risk factor for this (see the `git log` around delay-propagation's date-scoping fix for the specific incident and fix pattern) — new endpoints querying `flights` without a bounded `start_date`/`end_date` should default to a bounded recent window, not the full ~60M-row history.
