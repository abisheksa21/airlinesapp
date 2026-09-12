# Airline Operations Lab — Run Guide

This is the canonical setup and run manual for the AirlinesApp project on
Windows and macOS. It covers a clean machine, a fresh data build, optional
BTS T-100 enrichment, and the normal two-service development run.

## 1. What the project contains

The application has two processes:

| Process | Purpose | Local address |
|---|---|---|
| FastAPI backend | Reads the DuckDB warehouse and serves analysis endpoints | http://127.0.0.1:8200 |
| Next.js frontend | Public brief and researcher workspace | http://127.0.0.1:3100 |

The warehouse is local and is not stored in GitHub. The normal path is:

~~~
BTS downloads → Data/Raw → cleaned files → Data/Clean → DuckDB warehouse
~~~

Do not copy a DuckDB file from another computer as the normal setup. Build it
from the raw files on the machine where the application will run. This keeps
the data, pipeline state, and database consistent.

## 2. Prerequisites

Install these once:

- Git
- Python 3.11 or newer
- Node.js 20.9 or newer and npm
- Google Chrome (required by the Selenium-based BTS downloader)
- Enough free disk space for the selected history; a multi-year OTP warehouse
  can require tens of gigabytes and several hours

Check versions.

### Windows PowerShell

~~~
git --version
python --version
node --version
npm --version
~~~

### macOS Terminal

~~~
git --version
python3 --version
node --version
npm --version
~~~

If python is not available on macOS, use python3 in every Python command
below. If Node is older than 20.9, update Node before installing the frontend.

## 3. Get the code

For a new machine, clone the private repository after signing in to GitHub:

~~~
git clone https://github.com/abisheksa21/airlinesapp.git
cd airlinesapp
~~~

If the project already exists, do not clone it again. Open a terminal in the
existing project directory instead:

~~~
C:\Users\<you>\OneDrive\Desktop\AirlinesApp    (Windows example)
/Users/<you>/Projects/AirlinesApp                 (macOS example)
~~~

## 4. Create the Python environment

### Windows PowerShell

Run these commands from the repository root:

~~~
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
py -3 -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
~~~

If py is unavailable, use python -m venv .venv instead.

### macOS Terminal

Run these commands from the repository root:

~~~
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
~~~

The .env file is optional for the core dashboard. Add ANTHROPIC_API_KEY only
if the Copilot feature is being used. Never commit secrets to GitHub.

## 5. Install the frontend

Open a second terminal, move to the repository's frontend directory, and
install the locked JavaScript dependencies.

### Windows PowerShell

~~~
Set-Location "C:\path\to\AirlinesApp\frontend"
npm install
Copy-Item .env.local.example .env.local
~~~

### macOS Terminal

~~~
cd /path/to/AirlinesApp/frontend
npm install
cp .env.local.example .env.local
~~~

The frontend environment should contain:

~~~
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8200
~~~

If the file already exists, inspect it rather than overwriting it.

## 6. Build the main OTP warehouse from scratch

Use this procedure when the machine does not have the warehouse yet, or when
you intentionally want a clean rebuild. Run it from the repository root with
the Python virtual environment activated.

### Step 6.1 — Download BTS on-time files

~~~
python -m pipeline.download
~~~

The command is interactive. Enter the year or year range you want. It opens
Chrome through Selenium and downloads one monthly ZIP per selected month into
Data/Raw/. BTS may publish the latest month later than the current calendar
month, so choose the latest range that is actually available when you run it.

The downloader skips files already present, so it is safe to rerun after an
interruption.

### Step 6.2 — Clean the monthly files

~~~
python -m pipeline.clean
~~~

This extracts and normalizes the monthly files into Data/Clean/.

### Step 6.3 — Build DuckDB and analytics tables

~~~
python -m pipeline.build_warehouse
~~~

The resulting database is:

~~~
Data/Warehouse/airline.duckdb
~~~

This is a full rebuild. It promotes a completed staged database only after
validation, so an unsuccessful build should not replace a working warehouse.

## 7. Add the real BTS T-100 data

T-100 is an enrichment layer, not a replacement for OTP. OTP describes flight
outcomes; T-100 describes scheduled traffic, seats, and passengers at its own
monthly route/carrier grain. Keep the tables separate so one traffic row is
never incorrectly duplicated across many individual flights.

For the complete enrichment procedure, run each download and cleaning pair
from the repository root:

~~~
python -m pipeline.download_bts t100_segment --years 2018-2026
python -m pipeline.clean_bts t100_segment

python -m pipeline.download_bts t100_market --years 2018-2026
python -m pipeline.clean_bts t100_market

python -m pipeline.download_bts carrier_decode
python -m pipeline.clean_bts carrier_decode

python -m pipeline.download_bts master_coordinate
python -m pipeline.clean_bts master_coordinate

python -m pipeline.download_bts aircraft_types
python -m pipeline.clean_bts aircraft_types
~~~

Change the ending year 2026 to the latest year published by BTS when this guide
is reused. The downloader skips validated files already in Data/Raw/bts/, so
rerunning the commands is the intended recovery method.

After downloads and cleaning finish:

~~~
python -m pipeline.load_bts
python -m pipeline.materialize_analytics
python scripts/check_deployment_readiness.py
~~~

For a later freshness check:

~~~
python -m pipeline.auto_update_bts
~~~

The update process records its state and does not invent an unpublished month.
The latest date shown by the app therefore depends on BTS publication, not on a
hard-coded promise in the UI.

## 8. Start the application

The project uses backend port 8200 and frontend port 3100. Keep these ports
consistent with the environment files and the commands below.

### Option A — Windows one-command start

From the repository root in PowerShell:

~~~
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\.venv\Scripts\Activate.ps1
.\start_app.ps1
~~~

This script stops stale listeners on ports 8200 and 3100, sets the local
warehouse path, starts FastAPI in a separate PowerShell window, and runs the
Next.js frontend in the current window.

Open:

~~~
http://127.0.0.1:3100
~~~

### Option B — macOS one-command start

From the repository root in Terminal, make the launcher executable once and
run it:

~~~
chmod +x start_app.sh
./start_app.sh
~~~

Open:

~~~
http://127.0.0.1:3100
~~~

The script stops stale listeners on ports 8200 and 3100, starts FastAPI in the
background, starts Next.js in the current terminal, and stops the backend when
you press Ctrl+C.

### Option C — Two terminals on Windows or macOS

Terminal 1: backend, from the repository root with .venv activated.

#### Windows PowerShell

~~~
Set-Location "C:\path\to\AirlinesApp"
& .\.venv\Scripts\Activate.ps1
$env:AIRLINE_DUCKDB_PATH = (Join-Path (Get-Location) "Data\Warehouse\airline.duckdb")
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8200
~~~

#### macOS Terminal

~~~
cd /path/to/AirlinesApp
source .venv/bin/activate
export AIRLINE_DUCKDB_PATH="$PWD/Data/Warehouse/airline.duckdb"
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8200
~~~

Terminal 2: frontend.

#### Windows PowerShell

~~~
Set-Location "C:\path\to\AirlinesApp\frontend"
npm run dev -- --hostname 127.0.0.1 --port 3100
~~~

#### macOS Terminal

~~~
cd /path/to/AirlinesApp/frontend
npm run dev -- --hostname 127.0.0.1 --port 3100
~~~

Then use the public view at http://127.0.0.1:3100. The backend API and
interactive API documentation are available at:

- Health check: http://127.0.0.1:8200/api/health
- API docs: http://127.0.0.1:8200/docs

## 9. Verify the run before a demo

Check these in order:

1. /api/health returns a healthy response.
2. /api/summary returns JSON rather than 404.
3. http://127.0.0.1:3100 loads the public overview.
4. Public pages for Airlines, Airports, Routes, and Glossary open.
5. The Research workspace opens from the top-right switch.
6. A researcher page can load data and does not show “data service could not
   be reached.”
7. The warehouse readiness check reports a real file and a non-zero row count:

~~~
python scripts/check_deployment_readiness.py
~~~

## 10. Stop the application

Press Ctrl+C in the terminal running Next.js. Then stop the backend terminal
with Ctrl+C. If the Windows helper left a separate backend window open, close
that window after stopping the server.

If a stale process is holding a port on Windows, identify it:

~~~
Get-NetTCPConnection -LocalPort 8200,3100 -ErrorAction SilentlyContinue |
  Select-Object LocalPort,OwningProcess
~~~

Then stop only the reported process if it is one of your app processes:

~~~
Stop-Process -Id <PID> -Force
~~~

On macOS:

~~~
lsof -nP -iTCP:8200 -sTCP:LISTEN
lsof -nP -iTCP:3100 -sTCP:LISTEN
kill <PID>
~~~

## 11. Troubleshooting

### 404 Not Found at /api/summary

Check the port first. This project uses 8200, not 8000:

~~~
http://127.0.0.1:8200/api/summary
~~~

Also make sure the process was started from the repository root, so
api.main:app resolves to this project.

### “The data service could not be reached” in the frontend

Confirm the backend is running on 8200 and that frontend/.env.local points to
http://127.0.0.1:8200. Restart Next.js after changing .env.local.

### EADDRINUSE

Another process already owns the port. Stop the stale process using Section
10, or close the old terminal. Starting another Next.js server on 3001 or 3020
does not fix a backend/frontend port mismatch.

### PowerShell errors involving cd /d or call

Those are Command Prompt commands. In PowerShell use:

~~~
Set-Location "C:\path\to\AirlinesApp"
& .\.venv\Scripts\Activate.ps1
~~~

### Fatal error in launcher points to an old folder

The virtual environment was copied from another path. Delete only the
project's .venv folder and recreate it using Section 4; do not copy .venv
between computers.

### DuckDB file not found

Run the warehouse build in Section 6, then confirm this exact file exists:

~~~
Data/Warehouse/airline.duckdb
~~~

### OneDrive or Windows file-lock errors during npm run build

Use a separate Next.js output directory for the check:

~~~
$env:NEXT_DIST_DIR = ".next-airlinesapp"
npm run build
Remove-Item -Recurse -Force .next-airlinesapp
~~~

Do not delete the warehouse or raw data to solve a frontend build lock.

### BTS download stops or Chrome closes

Rerun the same download command. Existing validated ZIPs are skipped. Check
that Chrome is installed, the machine has internet access, and enough disk
space remains. Clean only after the download step has produced the files you
intend to use.

### database is locked or a busy DuckDB connection

Stop the backend before rebuilding or loading data. Complete the pipeline, then
restart the backend and frontend.

## 12. Useful development checks

From the repository root with the virtual environment active:

~~~
python scripts/check_deployment_readiness.py
pytest -q
~~~

From frontend/:

~~~
npm run typecheck
~~~

For a production build on Windows/OneDrive:

~~~
$env:NEXT_DIST_DIR = ".next-airlinesapp"
npm run build
Remove-Item -Recurse -Force .next-airlinesapp
~~~

## 13. The short daily start checklist

1. Open the repository root.
2. Activate .venv.
3. Confirm Data/Warehouse/airline.duckdb exists.
4. Start the backend on 8200.
5. Start the frontend on 3100.
6. Check /api/health.
7. Open http://127.0.0.1:3100.

Only rerun the data pipeline when new BTS data is needed or the warehouse is
being rebuilt. Do not rebuild the multi-year warehouse for every demo.
