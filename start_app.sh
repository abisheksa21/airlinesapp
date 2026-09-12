#!/usr/bin/env bash
set -euo pipefail

# Start the AirlinesApp backend and frontend together on macOS.
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project="$script_dir"
database="$project/Data/Warehouse/airline.duckdb"
backend_port="${AIRLINE_BACKEND_PORT:-8200}"
frontend_port="${AIRLINE_FRONTEND_PORT:-3100}"
backend_pid=""

if [[ ! -f "$project/.venv/bin/activate" ]]; then
  echo "Missing Python environment: $project/.venv"
  echo "Create it first with: python3 -m venv .venv"
  exit 1
fi

if [[ ! -f "$database" ]]; then
  echo "Missing DuckDB warehouse: $database"
  echo "Build it first; see RUNNING_GUIDE.md Section 6."
  exit 1
fi

stop_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    while IFS= read -r pid; do
      [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
    done <<< "$pids"
  fi
}

cleanup() {
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

stop_port "$backend_port"
stop_port "$frontend_port"
sleep 1

cd "$project"
source .venv/bin/activate
export AIRLINE_DUCKDB_PATH="$database"
export CORS_ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000,http://localhost:$frontend_port,http://127.0.0.1:$frontend_port"

python -m uvicorn api.main:app --reload --host 127.0.0.1 --port "$backend_port" &
backend_pid="$!"

cd "$project/frontend"
export NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:$backend_port"
export NEXT_DIST_DIR=".next-airlinesapp"

echo "Backend:  http://127.0.0.1:$backend_port"
echo "Frontend: http://127.0.0.1:$frontend_port"
echo "Press Ctrl+C to stop both services."

npm run dev -- --hostname 127.0.0.1 --port "$frontend_port"
