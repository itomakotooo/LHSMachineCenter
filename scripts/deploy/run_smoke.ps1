<#
.SYNOPSIS
  LAN smoke test for SlotConsole. Probes 5 endpoints and reports pass/fail.

.PARAMETER BaseUrl
  Base URL of the SlotConsole server. Default: http://localhost:8877

.PARAMETER Timeout
  Per-request timeout in seconds. Default: 10

.PARAMETER Verbose
  Print per-request detail (status code, elapsed time).

.PARAMETER DryRun
  Print the URLs that would be probed and exit 0 without making any requests.

.EXAMPLE
  # Probe local server:
  pwsh -NoProfile -File scripts\deploy\run_smoke.ps1

  # Probe server on LAN:
  pwsh -NoProfile -File scripts\deploy\run_smoke.ps1 -BaseUrl http://192.168.1.100:8877

  # Dry run (print URLs only):
  pwsh -NoProfile -File scripts\deploy\run_smoke.ps1 -DryRun
#>
param(
  [string]$BaseUrl  = "http://localhost:8877",
  [int]$Timeout     = 10,
  [switch]$Verbose,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Strip trailing slash for consistency.
$BaseUrl = $BaseUrl.TrimEnd("/")

# --- Define probes ---
# Each probe is a hashtable: Url, Description, AcceptCodes (list of acceptable HTTP status codes).
$probes = @(
  @{
    Url         = "$BaseUrl/console/"
    Description = "Frontend served"
    AcceptCodes = @(200, 301, 302)
  },
  @{
    Url         = "$BaseUrl/api/machines"
    Description = "Machine list responds"
    AcceptCodes = @(200)
  },
  @{
    Url         = "$BaseUrl/api/system-state"
    Description = "System state JSON parses"
    AcceptCodes = @(200)
  },
  @{
    # Fleet refresh may return 404 if no queue has ever been started — that is OK.
    Url         = "$BaseUrl/api/fleet/refresh"
    Description = "Fleet endpoint reachable (200 or 404 OK)"
    AcceptCodes = @(200, 404)
  },
  @{
    Url         = "$BaseUrl/api/configs"
    Description = "Config endpoint reachable"
    AcceptCodes = @(200)
  }
)

# --- DryRun: just list the URLs ---
if ($DryRun) {
  Write-Host "DRY-RUN — would probe:"
  foreach ($p in $probes) {
    Write-Host "  $($p.Url)  ($($p.Description))"
  }
  exit 0
}

# --- Run probes ---
$results  = @()
$anyFail  = $false

foreach ($p in $probes) {
  $status    = $null
  $elapsed   = $null
  $pass      = $false
  $error_msg = $null

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    # Invoke-WebRequest throws on non-2xx; use -UseBasicParsing for PS 5.1 compat.
    $resp = Invoke-WebRequest -Uri $p.Url `
                -Method GET `
                -TimeoutSec $Timeout `
                -UseBasicParsing `
                -ErrorAction SilentlyContinue
    $status = [int]$resp.StatusCode
  } catch [System.Net.WebException] {
    # WebException wraps HTTP error responses (e.g. 4xx/5xx from Invoke-WebRequest) and
    # network-level failures (timeout, connection refused, unroutable).
    $webEx = $_.Exception
    if ($webEx.Response -ne $null) {
      $status = [int]$webEx.Response.StatusCode
    } else {
      # Network-level failure (timeout, unreachable, etc.)
      $error_msg = $webEx.Message
      $status = $null
    }
  } catch {
    $error_msg = $_.Exception.Message
    $status = $null
  }
  $sw.Stop()
  $elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 2)

  if ($status -ne $null -and $p.AcceptCodes -contains $status) {
    $pass = $true
  } else {
    $anyFail = $true
  }

  $results += @{
    Description = $p.Description
    Url         = $p.Url
    Status      = $status
    Elapsed     = $elapsed
    Pass        = $pass
    Error       = $error_msg
  }

  if ($Verbose) {
    $mark = if ($pass) { "PASS" } else { "FAIL" }
    $statusStr = if ($status -ne $null) { "$status" } else { "ERR" }
    Write-Host "  [$mark] $($p.Description) — HTTP $statusStr in ${elapsed}s"
    if ($error_msg) {
      Write-Host "         Error: $error_msg"
    }
  }
}

# --- Summary table ---
Write-Host ""
Write-Host "SlotConsole Smoke Results — $BaseUrl"
Write-Host ("=" * 60)

$width = 40
foreach ($r in $results) {
  $mark    = if ($r.Pass) { "PASS" } else { "FAIL" }
  $desc    = $r.Description.PadRight($width)
  $statusStr = if ($r.Status -ne $null) { "HTTP $($r.Status)" } else { "TIMEOUT/ERR" }
  Write-Host "  [$mark]  $desc  $statusStr  ($($r.Elapsed)s)"
  if (-not $r.Pass -and $r.Error) {
    Write-Host "          Error: $($r.Error)"
  }
}

Write-Host ("=" * 60)

if ($anyFail) {
  Write-Host "RESULT: FAIL — one or more probes did not pass."
  exit 1
} else {
  Write-Host "RESULT: PASS — all probes OK."
  exit 0
}
