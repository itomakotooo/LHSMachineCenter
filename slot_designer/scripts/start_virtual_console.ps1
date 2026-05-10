param(
  [int]$Port = 8878,
  [switch]$Install,
  [switch]$OpenBrowser,
  [switch]$NoBanner
)

# Virtual-machine console launcher. Mirrors scripts/start_console.ps1
# but loads slot_designer.core.backend.virtual_app which injects slot_designer/
# paths into create_app() so this instance operates on virtual rawdata /
# reports / state in full isolation from the real console (port 8877).

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$url = "http://127.0.0.1:$Port/console/"

if (-not $NoBanner) {
  Write-Host "================================================"
  Write-Host " Slot Designer — Virtual Machine Console"
  Write-Host " URL : $url"
  Write-Host " Root: $root"
  Write-Host " Data: slot_designer/{rawdata,reports,state}/"
  Write-Host "================================================"
}

$existing = $null
try {
  $existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
} catch { }
if ($existing) {
  $pidList = ($existing | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique) -join ", "
  Write-Host ""
  Write-Host "FAIL: port $Port is already in use (pid(s): $pidList)."
  Write-Host "      Either stop the other process, or rerun with -Port <other>."
  exit 1
}

if ($Install) {
  Write-Host ""
  Write-Host "=== Installing runtime dependencies ==="
  python -m pip install -r src/web_console/requirements.txt
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

python -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "FAIL: fastapi / uvicorn not installed."
  Write-Host "      Run once: powershell -ExecutionPolicy Bypass -File slot_designer\scripts\start_virtual_console.ps1 -Install"
  exit 1
}

if ($OpenBrowser) {
  Start-Job -ScriptBlock {
    param($openUrl)
    Start-Sleep -Seconds 2
    try { Start-Process $openUrl } catch { }
  } -ArgumentList $url | Out-Null
}

Write-Host ""
Write-Host "Starting virtual uvicorn (Ctrl+C to stop)..."
python -m uvicorn slot_designer.core.backend.virtual_app:app --host 127.0.0.1 --port $Port --log-level info
