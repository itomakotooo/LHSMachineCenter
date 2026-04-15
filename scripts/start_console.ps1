param(
  [int]$Port = 8877
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Starting Slot Console at http://127.0.0.1:$Port/console/"
python -m uvicorn src.web_console.backend.main:app --host 127.0.0.1 --port $Port --log-level info
