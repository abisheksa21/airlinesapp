$ErrorActionPreference = "Stop"

# AirlinesApp uses 8002 because port 8000 is occupied by another local API
# service on this machine. The frontend remains on the usual Next.js port.
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$database = Join-Path $project "Data\Warehouse\airline.duckdb"
$backendPort = 8002
$frontendPort = 3000

foreach ($port in @($frontendPort, $backendPort)) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 2

$backendCommand = @"
Set-Location '$project'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& '.\.venv\Scripts\Activate.ps1'
`$env:AIRLINE_DUCKDB_PATH = '$database'
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port $backendPort
"@

Start-Process powershell.exe -WorkingDirectory $project -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command", $backendCommand
)

Set-Location (Join-Path $project "frontend")
npm run dev -- --hostname 127.0.0.1 --port $frontendPort
