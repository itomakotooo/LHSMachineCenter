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

# --- One-click update handler (invoked by the restart loop when the console ---
# --- requests it via POST /api/system/update-restart -> sentinel file) --------
# A process can't reliably restart itself, so the running console writes the
# sentinel + self-exits; THIS launcher (which owns the restart loop) is what
# actually pulls + relaunches. Defined here (before DryRun + the loop) so the
# DryRun inject seam can exercise it with -Simulate.
function Invoke-PipTimed {
  # Non-interactive, time-boxed pip so a credential prompt / stalled mirror /
  # sdist build can NEVER hang the launcher (which would strand the console
  # down). Returns $true on success, $false on failure OR timeout-kill.
  param([string]$ReqPath, [int]$TimeoutSec = 240)
  $env:PIP_NO_INPUT = "1"
  try {
    $p = Start-Process -FilePath "python" -NoNewWindow -PassThru -ArgumentList @(
      "-m", "pip", "install", "--no-input", "--timeout", "30", "--retries", "2", "-r", $ReqPath)
  } catch {
    Write-Host "pip could not start: $_"
    return $false
  }
  if (-not $p.WaitForExit($TimeoutSec * 1000)) {
    Write-Host "pip install exceeded ${TimeoutSec}s -- killing; relaunch will use existing deps."
    try { $p.Kill() } catch {}
    return $false
  }
  return ($p.ExitCode -eq 0)
}

function Invoke-ConsoleUpdate {
  param([string]$Root, [string]$ResultPath, [switch]$Simulate)
  # CRITICAL: native commands (git) write progress to STDERR. With the script-
  # level $ErrorActionPreference="Stop" + `2>&1`, that stderr is wrapped as a
  # NativeCommandError and THROWS, killing the launcher mid-update -> console
  # left DOWN with nothing to relaunch it (the 2026-06-23 brick). Force Continue
  # for THIS function (function-scoped, restored on return) so stderr is captured
  # as output, not fatal.
  $ErrorActionPreference = "Continue"
  Write-Host ""
  Write-Host "=== Update requested -- git pull --ff-only + restart ==="
  Push-Location $Root
  $fromCommit = ""
  try { $fromCommit = (git rev-parse --short HEAD 2>$null) } catch {}
  $reqPath = "src\web_console\requirements.txt"
  $reqBefore = ""
  if (Test-Path $reqPath) { try { $reqBefore = (Get-FileHash $reqPath).Hash } catch {} }

  $pullOut = ""
  $pullOk = $false
  if ($Simulate) {
    # Exercise the SAME native-stderr + 2>&1 capture the real pull uses, so the
    # DryRun test catches an ErrorActionPreference regression (the brick bug).
    $pullOut = (& cmd /c "echo (simulate) pull progress 1>&2 & exit /b 0" 2>&1 | Out-String)
    $pullOk = $true
  } else {
    # GIT_TERMINAL_PROMPT=0 -> a credential-less pull FAILS FAST instead of
    # hanging on a prompt (which would strand the console down). http.lowSpeed*
    # aborts a stalled transfer after ~15s. --ff-only never writes a merge
    # commit on the server checkout: a stray local commit there fails the pull
    # (logged) and we relaunch on the OLD code rather than half-merging.
    $env:GIT_TERMINAL_PROMPT = "0"
    $pullOut = (& git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=15 pull --ff-only 2>&1 | Out-String)
    $pullOk = ($LASTEXITCODE -eq 0)
  }

  $toCommit = ""
  try { $toCommit = (git rev-parse --short HEAD 2>$null) } catch {}
  $reqAfter = ""
  if (Test-Path $reqPath) { try { $reqAfter = (Get-FileHash $reqPath).Hash } catch {} }

  $pipRan = $false
  $pipOk = $true
  if ($pullOk -and ($reqBefore -ne $reqAfter) -and -not $Simulate) {
    Write-Host "requirements.txt changed -- pip install (non-interactive, <=240s)..."
    $pipRan = $true
    $pipOk = Invoke-PipTimed -ReqPath $reqPath -TimeoutSec 240
  }

  # Don't commit to the new code if its core deps don't import (pip failed /
  # was killed, or the pull broke the base import). Roll back to the known-good
  # pre-pull commit so the console stays BOOTABLE instead of crash-looping.
  $rolledBack = $false
  if (-not $Simulate -and $pullOk -and ("$fromCommit" -ne "$toCommit")) {
    $depsBroken = $false
    if ($pipRan -and -not $pipOk) {
      $depsBroken = $true
    } else {
      python -c "import fastapi, uvicorn" 2>$null
      if ($LASTEXITCODE -ne 0) { $depsBroken = $true }
    }
    if ($depsBroken) {
      Write-Host "Post-update deps check FAILED -- rolling back to $fromCommit (console stays bootable)."
      & git reset --hard $fromCommit 2>&1 | Out-Null
      $rolledBack = $true
      $toCommit = $fromCommit
    }
  }

  $tail = (($pullOut.Trim() -split "`r?`n") | Select-Object -Last 8) -join "`n"
  $result = [ordered]@{
    ts          = (Get-Date -Format "o")
    ok          = [bool]$pullOk
    pip_ran     = [bool]$pipRan
    pip_ok      = [bool]$pipOk
    rolled_back = [bool]$rolledBack
    from_commit = "$fromCommit"
    to_commit   = "$toCommit"
    changed     = (("$fromCommit" -ne "$toCommit") -and -not $rolledBack)
    output      = $tail
    simulate    = [bool]$Simulate
  }
  try {
    $json = $result | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText($ResultPath, $json, [System.Text.Encoding]::UTF8)
  } catch {
    Write-Host "WARN: could not write update result to ${ResultPath}: $_"
  }
  Pop-Location

  if ($rolledBack) {
    Write-Host "Update: rolled back to $fromCommit (deps broken). Relaunching old code."
  } elseif ($pullOk) {
    Write-Host "Update: $fromCommit -> $toCommit (pip_ran=$pipRan, pip_ok=$pipOk). Relaunching uvicorn..."
  } else {
    Write-Host "Update: git pull FAILED -- relaunching on EXISTING code. Tail:"
    Write-Host $tail
  }
}

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
# browser opens the LOOPBACK URL -- 0.0.0.0 is a server-side "bind to all
# interfaces" sentinel and is NOT a client-reachable address. Hard-bug
# 2026-05-18: P4 set $url to ${bindHost} and start.bat -> -OpenBrowser
# launched chrome at http://0.0.0.0:8877/console/ -> HTTP ERROR 502.
$url = "http://127.0.0.1:${bindPort}/console/"
if ($bindHost -ne "127.0.0.1" -and $bindHost -ne "0.0.0.0") {
  # Custom bind (e.g. specific NIC) -- show that exact host in the banner so
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
# so production runs cannot accidentally trigger it (per brief sec 10).
if ($DryRun) {
  Write-Host ""
  Write-Host "DRY-RUN mode -- uvicorn will NOT be started."
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

  # Inject: exercise the one-click update hand-off in -Simulate mode (no real
  # git pull, no uvicorn) -- proves Invoke-ConsoleUpdate runs and writes a valid
  # result file. Set SLOT_DEPLOY_INJECT_UPDATE=1 with -DryRun.
  if ($env:SLOT_DEPLOY_INJECT_UPDATE -eq "1") {
    $simResult = Join-Path $root "state\console\update_result.json"
    Invoke-ConsoleUpdate -Root $root -ResultPath $simResult -Simulate
    if (Test-Path $simResult) {
      Write-Host "  (inject) update simulate OK -- result at $simResult"
      exit 0
    } else {
      Write-Host "  (inject) update simulate FAILED -- no result file"
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
    # Fire-and-forget UI convenience -- not a data/diagnostic path. If launching
    # the default browser fails (no browser registered, etc.), the only impact
    # is that the operator must open the URL manually. No diagnostic warranted.
    try { Start-Process $openUrl } catch { }
  } -ArgumentList $url | Out-Null
}

# --- Restart loop with exponential backoff (capped at 60s) ---
# Also handles operator-requested update/restart: when the console writes the
# update sentinel and self-exits (POST /api/system/update-restart), we pull +
# relaunch on the new code, NOT counting it against the crash budget.
# SLOT_CONSOLE_SUPERVISED tells the backend it's safe to OFFER the button -- a
# manually started `uvicorn` (no launcher loop) would self-exit and never come
# back, so the endpoint refuses unless this is set.
$env:SLOT_CONSOLE_SUPERVISED = "1"
$MAX_RESTARTS = 5
$restarts = 0
$updateSentinel = Join-Path $root "state\console\update_request.json"
$updateResult   = Join-Path $root "state\console\update_result.json"

while ($true) {
  Write-Host ""
  Write-Host "Starting uvicorn (Ctrl+C to stop)..."

  python -m uvicorn src.web_console.backend.main:app `
      --host $bindHost `
      --port $bindPort `
      --log-level info
  $code = $LASTEXITCODE

  if (Test-Path $updateSentinel) {
    # Honor the update sentinel ONLY if it's fresh (written in the last ~120s by
    # the console that just self-exited). A stale one -- left from a Ctrl+C /
    # power-loss AFTER the console wrote it but BEFORE its self-exit, or from a
    # crash mid-write -- must NOT silently trigger a surprise pull on an
    # unrelated restart. Consume it first either way so it can't wedge a re-pull.
    $sentAgeSec = 999999
    try { $sentAgeSec = ((Get-Date) - (Get-Item $updateSentinel).LastWriteTime).TotalSeconds } catch {}
    Remove-Item $updateSentinel -Force -ErrorAction SilentlyContinue
    if ($sentAgeSec -le 120) {
      # The update handler must NEVER kill the launcher (else the console is left
      # DOWN with nothing to relaunch it). Swallow any throw and relaunch anyway.
      try {
        Invoke-ConsoleUpdate -Root $root -ResultPath $updateResult
      } catch {
        Write-Host "Update handler threw -- relaunching on existing code: $_"
      }
      $restarts = 0        # an update is not a crash -- reset the failure budget
      continue
    }
    Write-Host "Ignoring stale update sentinel (age $([int]$sentAgeSec)s > 120s) -- normal exit handling."
    # fall through to the exit-code logic below (clean stop / crash backoff)
  }

  if ($code -eq 0) {
    # Clean exit (operator pressed Ctrl+C or uvicorn exited normally) and NO
    # update was requested -> stop.
    break
  }

  $restarts++
  if ($restarts -ge $MAX_RESTARTS) {
    break
  }

  # Exponential backoff: 5s, 10s, 20s, 40s, 60s (capped).
  $backoff = [Math]::Min(5 * [Math]::Pow(2, $restarts - 1), 60)
  Write-Host "uvicorn exited with $code; restart $restarts/$MAX_RESTARTS in ${backoff}s"
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
