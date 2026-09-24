# Frontend rebuild report

## Purpose

This rebuild turns the application into two deliberately different products over the same FastAPI and DuckDB evidence layer:

- **Public** is a calm, editorial explorer for answering a travel or network question in plain language.
- **Research** is a dark operational workspace for scoped investigation, evidence, forecasts, and bounded decision experiments.

The browser URL is the source of truth for product mode and research scope. Saved investigations are persisted by the local FastAPI instance; they never alter an analysis or hide filters in browser storage.

## What changed

### Application architecture

- Replaced the shared navigation shell with `AppShell`, which selects the public or research product from the current URL.
- Removed the previous local-storage mode switch as application state. Public routes and `/research/*` now determine the view directly.
- Added a public header with object navigation and command search; the research product now uses a left rail, top bar, and persistent URL-backed context strip.
- Added a compact evidence drawer to the research shell and evidence/caveat frames around analytical charts.

### Public product

- Rebuilt `/` as an editorial network brief with a real BTS snapshot, movement, carrier/airport concentration, route comparison, and a plain-language question desk.
- Rebuilt carrier, airport, and route directories and object profiles. Each profile uses the real detail endpoint, measured period, sample, chart interpretation, and a boundary statement.
- Added `/explore`, `/network`, and `/insights` as public discovery routes.
- Added an actual-coordinate network view served by `/api/network-map`; airport nodes lead to the corresponding public airport profile.
- Added global `Ctrl/Cmd + K` search for carriers, airports, routes, tail-number prefixes, and an optional contextual Copilot handoff.
- Rebuilt Methodology and Glossary as public reference pages instead of generic legacy panels.

### Research product

- Added the researcher route family: `/research`, `/research/explore`, `/research/diagnose`, `/research/network`, `/research/capacity`, `/research/forecast`, `/research/decisions`, `/research/evidence`, `/research/data`, and `/research/copilot`.
- Preserved the existing validated analytical tool bodies behind the new research shell: delay diagnosis, capacity/T-100 work, forecasts/model evidence, data health, decisions, and Copilot.
- Added research context fields (`from`, `to`, `carrier`, `airport`, `route`, `metric`) stored in the URL so a scoped investigation can be copied and reopened. The Context Bar stages edits until blur/Enter rather than firing a route change for every keystroke.
- Connected the context to real contracts where it is methodologically valid: delay diagnostics apply carrier, airport, and date scope; the T-100 Capacity workspace applies carrier, directional route, and calendar-month scope; Decision Center pre-fills compatible carrier/airport objects and applies route/month scope to its T-100 comparison. Forecast validation explicitly states why it remains global rather than silently pretending a small scoped sample has been tested.
- Added `ChartFrame` evidence metadata to the Capacity trend, all Delay Diagnostics charts (network-wide and scoped), and chart-compatible Copilot evidence, including source, period, sample/method when available, and caveat.
- Replaced browser-local Saved Investigations with durable local-server records at `Data/State/research_investigations.json`. The file is ignored by Git; it stores URL bookmarks only and exposes save/list/delete through FastAPI.
- Copilot now receives the active research context with each question and tells the analyst that a tool must disclose when it cannot apply part of that scope.
- Strengthened the Model Evidence contract: repeated route-panel checks now use non-overlapping later outcome windows and label an added source as supported only when it lowers aggregate MAE and wins more future windows than it loses against the historical baseline.
- Added a Decision Center **Historical priority check** for the portfolio optimizer. It replays the unchanged shortlist formulation on an earlier 12-month reference window and measures whether its selected targets still concentrate the declared metric in later, disjoint three-month windows. It is explicitly a prioritization-stability check, not an intervention-effect estimate.

## Real data contracts retained or added

All public numbers remain backend-aggregated from the local warehouse; raw flight rows are not sent to the browser.

| User surface | Backend contract | Evidence boundary |
| --- | --- | --- |
| Network snapshot | `/api/summary`, `/api/trend` | Historical BTS on-time record |
| Object directories | `/api/carriers`, `/api/airports`, `/api/routes` | Compact historical rankings |
| Carrier/airport/route profiles | `/api/*-detail` | Aggregated object history and BTS-coded causes |
| Network map | `/api/network-map` | Actual airport coordinates in the local high-volume subset; volume-ranked BTS routes |
| Aircraft command search | `/api/aircraft/search` | Tail-number prefix search across stored flight records |
| Capacity/T-100 research | `/api/capacity/*` | Grain-matched historical traffic context, not live demand or causality |
| Forecast/model evidence | `/api/route-*`, model-evidence endpoints | Held-out historical evaluation; the ML candidate is not silently promoted over the baseline |
| Portfolio historical replay | `/api/decision/network-protection-validation` | Earlier shortlist versus later exposure; no intervention or causal-effect claim |
| Saved investigations | `/api/investigations` | Local-server URL bookmarks; no hidden query state and no team/account semantics |

`/api/network-map` uses the compact route aggregation whenever it exists and returns the source, period, coordinate source, and coverage with every response. The fallback is still aggregated—not an invented display network.

## Design references

The rebuild takes product-level lessons rather than copying any product's code or visual identity:

- Search-first object discovery and clear historical-status boundaries: [Flightradar24 data explorer](https://www.flightradar24.com/data) and [FlightAware commercial products](https://www.flightaware.com/commercial/).
- Public data provenance and release transparency: [BTS TranStats](https://www.transtats.bts.gov/).
- Object-first operational modelling and analyst workspace patterns: [Palantir Ontology](https://www.palantir.com/docs/foundry/ontology/overview) and [Palantir Workshop](https://www.palantir.com/docs/foundry/workshop/overview).
- Analytical narratives that reveal method and caveat alongside interaction: [Observable Framework](https://observablehq.com/framework/getting-started).
- Aviation data/product taxonomy: [Cirium](https://www.cirium.com/).

## Verification completed

On the local project machine:

- `npm run typecheck` passed.
- `npm run build` passed and generated all 31 App Router routes.
- FastAPI health check returned `{"status":"ok"}` on port 8200.
- `/api/network-map?limit=12` returned real mapped coverage, a 2018-01-01 to 2026-06-30 period, and the local FAA-coordinate reference label.
- Aircraft prefix search returned real tail records; global search was tested through the browser and verified to display those results after a debounce.
- Browser smoke checks confirmed a data-backed public home, public carrier profile, public methodology, research workspace, saved-investigation menu, and research Decision Center.
- Scoped Capacity browser test confirmed that `carrier=AA`, `route=DFW → LAX`, and `from/to=2024-01/2024-12` reach both the summary cards and the evidence-framed monthly trend. The result contained 12 real matched route-months.
- Scoped Delay Diagnostics browser test confirmed that `carrier=AA`, `airport=DFW`, and `from/to=2024-01` populate the page controls and rerun real BTS cause/cancellation/distance aggregations.
- Browser accessibility inspection confirmed that each diagnostic chart now exposes its evidence title, interpretation, source, period, sample, and method in the rendered page.
- Verified `/api/investigations` create/list/delete end to end and verified scoped `/api/capacity/correlation` and `/api/capacity/trend` requests against the local warehouse.

## Known boundaries and next work

- The platform is historical decision support, not a live flight-status, booking, or certified airport-capacity system.
- T-100 and operational context are explanatory/predictive research signals only. They remain distinct from causal claims.
- Saved investigations are durable only for this local app instance. A team-shared library still requires authentication, user ownership, access rules, and a database-backed collaboration model; those are intentionally not faked in a local project.
- The research shell is rebuilt and key calculators now consume compatible URL scope, while some mature legacy tool bodies still retain their original internal chart components. They should be migrated one by one to the shared `ChartFrame` rather than rewritten wholesale and risk changing validated calculations.
- A context field is never silently treated as applied: each deep page either maps it to a supported endpoint parameter or states the boundary. The next recommended work is endpoint-by-endpoint coverage for the remaining specialist tools, then automated browser checks for all key public and research flows.
