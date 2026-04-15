param(
  [switch]$Fix,
  [switch]$AllowMissingNode
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "=== Python syntax compile check ==="
python -m compileall -q src tests scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Module-global guard (AST self-test) ==="
python scripts/check_no_global_state.py --self-test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Module-global guard (backend/app.py is side-effect free) ==="
python scripts/check_no_global_state.py src/web_console/backend/app.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Ruff (if installed) ==="
$ruff = Get-Command ruff -ErrorAction SilentlyContinue
if ($ruff) {
  if ($Fix) {
    ruff check --fix src tests scripts
  } else {
    ruff check src tests scripts
  }
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  ruff format --check src tests scripts
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
  Write-Host "ruff not installed, skipping (optional)"
}

Write-Host "=== JS syntax check ==="
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  if ($AllowMissingNode) {
    Write-Host "WARN: node not installed; skipping JS syntax check (-AllowMissingNode set)"
  } else {
    Write-Host "FAIL: node is required for JS syntax check."
    Write-Host "      Install Node 18+ (https://nodejs.org) or pass -AllowMissingNode to skip."
    exit 1
  }
} else {
  node --check src/web_console/frontend/pure.js
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  node --check src/web_console/frontend/app.js
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "=== Lint OK ==="
