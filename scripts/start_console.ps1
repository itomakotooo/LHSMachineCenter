param(
  [int]$Port = 8877,
  [switch]$Install,
  [switch]$OpenBrowser,
  [switch]$NoBanner
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$url = "http://127.0.0.1:$Port/console/"

if (-not $NoBanner) {
  Write-Host "================================================"
  Write-Host " Slot Console"
  Write-Host " URL : $url"
  Write-Host " Root: $root"
  Write-Host "================================================"
}

# --- Port guard: bail early if something else already owns the port ---
$existing = $null
try {
  $existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
} catch {
  # Get-NetTCPConnection may be unavailable on older systems; silently skip.
}
if ($existing) {
  $pidList = ($existing | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique) -join ", "
  Write-Host ""
  Write-Host "FAIL: port $Port is already in use (pid(s): $pidList)."
  Write-Host "      Either stop the other process, or rerun with -Port <other>."
  exit 1
}

# --- Optional one-shot install of runtime deps ---
if ($Install) {
  Write-Host ""
  Write-Host "=== Installing runtime dependencies ==="
  python -m pip install -r src/web_console/requirements.txt
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# --- Probe that fastapi + uvicorn are importable before spawning uvicorn ---
python -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "FAIL: fastapi / uvicorn not installed."
  Write-Host "      Run once: powershell -ExecutionPolicy Bypass -File scripts\start_console.ps1 -Install"
  Write-Host "      (or manually: python -m pip install -r src\web_console\requirements.txt)"
  exit 1
}

# --- Schedule a background browser-open ~2s after uvicorn starts listening ---
if ($OpenBrowser) {
  Start-Job -ScriptBlock {
    param($openUrl)
    Start-Sleep -Seconds 2
    try { Start-Process $openUrl } catch { }
  } -ArgumentList $url | Out-Null
}

Write-Host ""
Write-Host "Starting uvicorn (Ctrl+C to stop)..."
python -m uvicorn src.web_console.backend.main:app --host 127.0.0.1 --port $Port --log-level info
