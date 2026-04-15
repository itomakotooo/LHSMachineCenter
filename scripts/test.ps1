param(
  [switch]$E2E,
  [switch]$Install,
  [switch]$AllowMissingNode
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Install) {
  Write-Host "=== Installing dependencies ==="
  python -m pip install -r src/web_console/requirements.txt
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  python -m pip install -r requirements-dev.txt
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  python -m playwright install chromium
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "=== Backend tests ==="
$backendTests = Test-Path "tests/backend"
if ($backendTests) {
  python -m pytest tests/backend -q
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
  Write-Host "tests/backend not present yet; skipping (will be added by Commit 5+)."
}

Write-Host "=== Frontend pure tests (cjs) ==="
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  if ($AllowMissingNode) {
    Write-Host "WARN: node not installed; skipping pure-fn tests (-AllowMissingNode set)"
  } else {
    Write-Host "FAIL: node is required for frontend pure tests."
    Write-Host "      Install Node 18+ (https://nodejs.org) or pass -AllowMissingNode to skip."
    exit 1
  }
} else {
  node --test tests/frontend/pure.test.cjs
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($E2E) {
  Write-Host "=== Playwright browser readiness probe ==="
  python -c "from playwright.sync_api import sync_playwright; pw = sync_playwright().start(); b = pw.chromium.launch(headless=True); b.close(); pw.stop()" 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Playwright chromium not installed or unavailable."
    Write-Host "      Run: python -m playwright install chromium"
    Write-Host "      Or pass -Install on first run: scripts\test.ps1 -E2E -Install"
    exit 1
  }
  Write-Host "=== Playwright e2e tests ==="
  $e2eTests = Test-Path "tests/e2e"
  if ($e2eTests) {
    python -m pytest tests/e2e -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  } else {
    Write-Host "tests/e2e not present yet; skipping (will be added by Commit 7)."
  }
}

Write-Host "=== Test run OK ==="
