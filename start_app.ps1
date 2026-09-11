$ErrorActionPreference = "Stop"

# AirlinesApp uses a dedicated local API port so it cannot collide with other
# projects running on 8000/8002/8003/8100. AirlinesApp uses frontend port 3100.
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$database = Join-Path $project "Data\Warehouse\airline.duckdb"
$backendPort = 8200
$frontendPort = 3100

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
`$env:CORS_ALLOWED_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100'
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port $backendPort
"@

Start-Process powershell.exe -WorkingDirectory $project -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command", $backendCommand
)

Set-Location (Join-Path $project "frontend")
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:$backendPort"
$env:NEXT_DIST_DIR = ".next-airlinesapp"
npm run dev -- --hostname 127.0.0.1 --port $frontendPort
