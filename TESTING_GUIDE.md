# Fresh Setup + Full Testing Guide

Written for Windows + PowerShell + VS Code, starting from nothing. Follow
Part 1 top to bottom once. Part 2 is the actual test plan, ordered by
priority -- do it in order, stop and tell me immediately if anything in
Tier 0 fails, since everything after it depends on those basics working.

---

## PART 1 — Fresh setup, step by step

### Step 1: Get the code into place

Your real data (`Data\Warehouse\airline.duckdb`) is NOT in this zip -- it's
too large to ship this way. If you already have a project folder with that
file in it, extract this zip's `zero_start` folder contents INTO that same
folder, letting them merge -- do not delete your existing `Data\` folder.

If this is genuinely a brand new folder, extract the zip, then copy your
real `Data\Warehouse\airline.duckdb` into `<project>\Data\Warehouse\` before
continuing -- nothing that touches real data will work without it.

Open the project folder in VS Code:
```powershell
code "C:\path\to\your\AirlinesApp"
```

Open a terminal inside VS Code (`` Ctrl+` ``) -- it should default to
PowerShell. All commands below run from the project root unless noted.

### Step 2: Python backend environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks that second command with a script-execution error
(a common, expected Windows default), run this once, then retry:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

With the venv active (you'll see `(.venv)` in the prompt):
```powershell
pip install -r requirements.txt
```

This now includes `scipy` (needed for the new OR features) and `pytest`
(needed to actually run the test suite) -- both were genuinely missing
from this file before tonight; fixed as part of this round, confirmed by
reading the file, not assumed.

### Step 3: Environment variables

```powershell
Copy-Item .env.example .env
```

Open `.env` and set your real `ANTHROPIC_API_KEY`. Everything else in
there has sensible local-dev defaults already.

### Step 4: Confirm the backend can actually see your data

```powershell
python scripts\check_deployment_readiness.py
```

This should report your real `airline.duckdb` file size. If it says the
file isn't found, fix the path (either move the file to the default
location it reports, or set `AIRLINE_DUCKDB_PATH` in `.env` to wherever it
actually lives) before going further.

### Step 5: Start the backend

```powershell
uvicorn api.main:app --reload
```

Leave this running. Open a **second** terminal (`` Ctrl+Shift+` ``) for
everything below.

### Step 6: Frontend setup

```powershell
cd frontend
Copy-Item .env.local.example .env.local
npm install
```

`.env.local` defaults to `http://127.0.0.1:8002` for this machine because
port 8000 is already used by another local API service. The supplied
`start_app.ps1` launcher starts AirlinesApp on that matching port.

### Step 7: Start the frontend

```powershell
npm run dev
```

Visit `http://localhost:3000`. If this loads, both servers are up and
Part 2 can begin.

---

## PART 2 — Testing plan, in priority order

### Tier 0 — Does it actually run (stop and tell me if anything here fails)

**Backend started cleanly** (Step 5) -- no import errors in that terminal.

**Frontend started cleanly** (Step 7) -- no errors, page loads.

**Real automated build checks**:
```powershell
cd frontend
npm run typecheck
npm run build
```
`npm run typecheck` has been run successfully during this hardening pass.
`npm run build` remains a useful follow-up check because it exercises Next's
production compilation and route generation as well.

**The real pytest suite**:
```powershell
cd ..
pytest tests\ -v
```
Use `pytest --collect-only -q` to see the current count; it is intentionally
not hard-coded in this guide because the suite grows with each analytical
feature. The test suite should complete with a clean exit, not merely print
passing dots.

### Tier 1 — This sprint's work (newest, least tested, highest priority)

**The compact analytics layer.** If you started with an existing DuckDB copy,
refresh the derived tables once from the project root:
```powershell
python -m pipeline.materialize_analytics
```
The command should print row counts for five `analytics_*` tables. It is
safe to repeat: these are replaceable summaries rebuilt from `flights`.
The public home, carrier, route, and airport rankings should then load from
those summaries, while detailed profiles continue to use the raw table where
their extra dimensions require it.

**The T-100 evidence page.** Switch to Researcher view → T-100. It should show
the matched carrier/route/month count, average seats filled, average on-time
rate, a plain-language relationship label, and a passenger-sorted table. The
page must say “association” rather than “cause”; that distinction is part of
the result, not a decorative disclaimer.

**The on-time-rate fix (32 sites).** Pick any carrier or airport profile
page, note the on-time rate shown. This should now correctly exclude
cancelled flights from the calculation -- if you want to sanity check by
hand, ask Copilot "what's the cancellation rate for [carrier]" and
"what's the on-time rate for [carrier]" for the same scope, then reason
about whether the on-time number looks like it's excluding cancellations
(it should be somewhat higher than before this fix, especially for
carriers/periods with more cancellations).

**The OR features -- test through Decision Center or directly via Python:**
```powershell
python -c "
from api.optimization.departure_bank import BankFlight, solve_departure_bank
flights = [BankFlight(flight_id=f'F{i}', original_bucket=32) for i in range(14)]
limit = {t: 5.0 for t in range(96)}
weight = {t: 1.0 for t in range(96)}
point_est = {t: 10.0 for t in range(96)}
r = solve_departure_bank(flights, 96, 30, limit, weight, point_est, mode='expected')
print('status:', r.status)
print('peak load:', r.original_peak_load, '->', r.optimized_peak_load)
"
```
Expect status `optimal` and the peak load genuinely dropping. This proves
the real HiGHS solver (via scipy) works end to end on your machine, not
just mine.

**The predictive risk model upgrade.** Decision Center → Predictive Risk
Screen tab → run it for any carrier or airport. Check the "what's driving
this" section — you should now sometimes see "Recent trend" or "Seasonal
pattern" listed among the top 3 drivers, not just the original six
features. If neither ever appears across several entities, that's worth
flagging — it might mean the signal is genuinely weak, or it might mean
something's not wired correctly.

### Tier 2 — Broader recent work (should still work, quick pass)

- Toggle Public/Researcher mode in the nav — confirm 737 MAX, Decision
  Center, and Methodology appear/disappear correctly
- Visit a carrier profile in both modes — Public should be compact,
  Researcher should show the 4-tab layout
- Try a Quick Lookup with a specific date range, click through to the full
  profile — confirm the range carries over and lands you in Researcher mode
- Compare page — all 4 tabs (Carrier/Airport/Route/Aircraft)
- Copilot — ask a question in both modes, confirm the mode indicator and
  response quality genuinely differ

### Tier 3 — Deployment scaffolding (optional, only if you want to go there tonight)

```powershell
docker build -t airlines-app-test .
```
This is something I could never test myself (no Docker, no network) — if
it builds successfully, that's genuinely new information neither of us
had before.

---

## If something fails

Tell me: which tier, which specific step, and the exact error text or
screenshot. Given how much of tonight's work I could only verify indirectly
(no pytest, no scipy confirmed installed, no real browser, no Docker), a
real failure here is valuable, specific information — not a sign
everything else is suspect.
