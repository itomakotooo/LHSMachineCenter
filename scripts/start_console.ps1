param(
  [int]$Port = 0,
  [switch]$Install,
  [switch]$OpenBrowser,
  [switch]$NoBanner,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- Resolve bind host and port (env vars win when no explicit -Port given) ---
# PowerShell 5.1-compat: no ?? operator; use explicit if/else.
$bindHost = if ($env:SLOT_BIND_HOST) { $env:SLOT_BIND_HOST } else { "0.0.0.0" }

if ($Port -ne 0) {
  # Explicit -Port param takes priority over env var.
  $bindPort = $Port
} else {
  $bindPort = if ($env:SLOT_BIND_PORT) { [int]$env:SLOT_BIND_PORT } else { 8877 }
}

# Keep the $Port variable in sync so downstream references (port guard, browser URL) use the
# resolved value throughout the script.
$Port = $bindPort

# Server listens on $bindHost (typically 0.0.0.0 for LAN access), but the
# browser opens the LOOPBACK URL — 0.0.0.0 is a server-side "bind to all
# interfaces" sentinel and is NOT a client-reachable address. Hard-bug
# 2026-05-18: P4 set $url to ${bindHost} and start.bat → -OpenBrowser
# launched chrome at http://0.0.0.0:8877/console/ → HTTP ERROR 502.
$url = "http://127.0.0.1:${bindPort}/console/"
if ($bindHost -ne "127.0.0.1" -and $bindHost -ne "0.0.0.0") {
  # Custom bind (e.g. specific NIC) — show that exact host in the banner so
  # the operator knows what to type from another machine.
  $lanUrl = "http://${bindHost}:${bindPort}/console/"
} else {
  $lanUrl = $null
}

if (-not $NoBanner) {
  Write-Host "================================================"
  Write-Host " Slot Console"
  Write-Host " URL (this machine)        : $url"
  if ($lanUrl) {
    Write-Host " URL (other LAN clients)   : $lanUrl"
  } elseif ($bindHost -eq "0.0.0.0") {
    Write-Host " URL (other LAN clients)   : http://<this-machine-ip>:${bindPort}/console/"
  }
  Write-Host " Root: $root"
  Write-Host "================================================"
}

# --- DryRun: print resolved bind settings; optionally exercise the restart loop ---
# with SLOT_DEPLOY_INJECT_UVICORN_FAIL=N to simulate N failures (for CI testability).
# In DryRun mode, uvicorn is NEVER spawned; the inject seam ONLY fires in DryRun mode
# so production runs cannot accidentally trigger it (per brief §10).
if ($DryRun) {
  Write-Host ""
  Write-Host "DRY-RUN mode — uvicorn will NOT be started."
  Write-Host "  Resolved bind: ${bindHost}:${bindPort}"

  # If SLOT_DEPLOY_INJECT_UVICORN_FAIL is set, simulate the restart loop with injected
  # failures to exercise the exhaustion + Event Log / JSON diagnostic path.
  $injectFail = if ($env:SLOT_DEPLOY_INJECT_UVICORN_FAIL) { [int]$env:SLOT_DEPLOY_INJECT_UVICORN_FAIL } else { 0 }
  if ($injectFail -gt 0) {
    Write-Host "  Inject mode: simulating $injectFail uvicorn failure(s) in dry-run loop..."
    $MAX_RESTARTS = 5
    $restarts = 0
    while ($restarts -lt $MAX_RESTARTS) {
      if ($restarts -lt $injectFail) {
        Write-Host "  (inject) simulating uvicorn failure (iteration $restarts)"
        $restarts++
        if ($restarts -ge $MAX_RESTARTS) { break }
        $backoff = [Math]::Min(5 * [Math]::Pow(2, $restarts - 1), 60)
        Write-Host "  uvicorn exited with 1; restart $restarts/$MAX_RESTARTS in ${backoff}s (skipped in dry-run)"
      } else {
        Write-Host "  (inject) simulating uvicorn success (iteration $restarts)"
        break
      }
    }
    if ($restarts -ge $MAX_RESTARTS) {
      $msg = "SlotConsole uvicorn exhausted restart budget ($MAX_RESTARTS restarts). Manual intervention required."
      Write-Host ""
      Write-Host "ALERT: $msg"
      $eventLogOk = $false
      try {
        Write-EventLog -LogName Application -Source "SlotConsole" `
            -EntryType Error -EventId 1001 `
            -Message $msg
        $eventLogOk = $true
      } catch {
        # Fall through to JSON diagnostic.
      }
      if (-not $eventLogOk) {
        $diagDir = Join-Path $root "state\console"
        if (-not (Test-Path $diagDir)) {
          try {
            New-Item -ItemType Directory -Path $diagDir -Force | Out-Null
          } catch {
            Write-Host "WARN: could not create diagnostic directory ${diagDir}: $_"
          }
        }
        $diagFile = Join-Path $diagDir "restart_exhausted.json"
        $diagObj = @{
          timestamp    = (Get-Date -Format "o")
          restarts     = $restarts
          max_restarts = $MAX_RESTARTS
          message      = $msg
          event_log_ok = $false
          dry_run      = $true
        }
        try {
          $diagJson = $diagObj | ConvertTo-Json -Compress
          [System.IO.File]::WriteAllText($diagFile, $diagJson, [System.Text.Encoding]::UTF8)
          Write-Host "Diagnostic written to: $diagFile"
        } catch {
          Write-Host "WARNING: could not write diagnostic JSON to $diagFile : $_"
        }
      }
      exit 1
    }
  }
  exit 0
}

# --- Port guard: bail early if something else already owns the port ---
# Runs ONCE before the restart loop; intra-loop port reuse race is uvicorn's problem.
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
    # Fire-and-forget UI convenience — not a data/diagnostic path. If launching
    # the default browser fails (no browser registered, etc.), the only impact
    # is that the operator must open the URL manually. No diagnostic warranted.
    try { Start-Process $openUrl } catch { }
  } -ArgumentList $url | Out-Null
}

# --- Restart loop with exponential backoff (capped at 60s) ---
$MAX_RESTARTS = 5
$restarts = 0

while ($restarts -lt $MAX_RESTARTS) {
  Write-Host ""
  Write-Host "Starting uvicorn (Ctrl+C to stop)..."

  python -m uvicorn src.web_console.backend.main:app `
      --host $bindHost `
      --port $bindPort `
      --log-level info

  if ($LASTEXITCODE -eq 0) {
    # Clean exit (operator pressed Ctrl+C or uvicorn exited normally).
    break
  }

  $restarts++
  if ($restarts -ge $MAX_RESTARTS) {
    break
  }

  # Exponential backoff: 5s, 10s, 20s, 40s, 60s (capped).
  $backoff = [Math]::Min(5 * [Math]::Pow(2, $restarts - 1), 60)
  Write-Host "uvicorn exited with $LASTEXITCODE; restart $restarts/$MAX_RESTARTS in ${backoff}s"
  Start-Sleep -Seconds $backoff
}

# --- Restart budget exhausted: alert operator ---
if ($restarts -ge $MAX_RESTARTS) {
  $msg = "SlotConsole uvicorn exhausted restart budget ($MAX_RESTARTS restarts). Manual intervention required."
  Write-Host ""
  Write-Host "ALERT: $msg"

  # Try Windows Event Log (requires Source pre-registration via New-EventLog; needs admin once).
  $eventLogOk = $false
  try {
    Write-EventLog -LogName Application -Source "SlotConsole" `
        -EntryType Error -EventId 1001 `
        -Message $msg
    $eventLogOk = $true
  } catch {
    # Event Log write failed (Source not registered, or insufficient permissions).
    # Fall through to JSON diagnostic below (per feedback_no_silent_swallow.md).
  }

  if (-not $eventLogOk) {
    # Persist diagnostic to disk so the operator can find it even without Event Viewer.
    $diagDir = Join-Path $root "state\console"
    if (-not (Test-Path $diagDir)) {
      try {
        New-Item -ItemType Directory -Path $diagDir -Force | Out-Null
      } catch {
        Write-Host "WARN: could not create diagnostic directory ${diagDir}: $_"
      }
    }
    $diagFile = Join-Path $diagDir "restart_exhausted.json"
    $diagObj = @{
      timestamp   = (Get-Date -Format "o")
      restarts    = $restarts
      max_restarts = $MAX_RESTARTS
      message     = $msg
      event_log_ok = $false
    }
    try {
      $diagJson = $diagObj | ConvertTo-Json -Compress
      [System.IO.File]::WriteAllText($diagFile, $diagJson, [System.Text.Encoding]::UTF8)
      Write-Host "Diagnostic written to: $diagFile"
    } catch {
      Write-Host "WARNING: could not write diagnostic JSON to $diagFile : $_"
    }
  }

  exit 1
}
