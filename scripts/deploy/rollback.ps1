<#
.SYNOPSIS
  Atomic rollback of the SlotConsole server to a previous git commit.

.DESCRIPTION
  Stops the Task Scheduler task, waits for uvicorn to exit, verifies there
  are no uncommitted changes (to avoid destroying operator work), shows the
  target commit, and performs git reset --hard. Requires explicit operator
  confirmation unless -Force is given.

  This script ONLY performs rollback operations that the operator explicitly
  authorized. git reset --hard is destructive; that is why -Force and
  confirmation prompts exist.

.PARAMETER To
  Target commit ref to roll back to. Default: HEAD~1 (the previous commit).

.PARAMETER Force
  Skip the confirmation prompt before git reset --hard.

.PARAMETER DryRun
  Print the operations that would be performed without modifying the repo.

.EXAMPLE
  # Dry run — see what would happen:
  pwsh -NoProfile -File scripts\deploy\rollback.ps1 -DryRun

  # Roll back to HEAD~1 (interactive confirmation):
  pwsh -NoProfile -File scripts\deploy\rollback.ps1

  # Roll back to a specific commit without prompting:
  pwsh -NoProfile -File scripts\deploy\rollback.ps1 -To abc1234 -Force
#>
param(
  [string]$To      = "HEAD~1",
  [switch]$Force,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# --- Resolve bind port (same pattern as start_console.ps1) ---
$bindPort = if ($env:SLOT_BIND_PORT) { [int]$env:SLOT_BIND_PORT } else { 8877 }

# --- Derive repo root: two levels up from scripts\deploy\ ---
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

Write-Host "SlotConsole Rollback"
Write-Host "  Repo root : $repoRoot"
Write-Host "  Target ref: $To"
if ($DryRun) {
  Write-Host "  Mode      : DRY-RUN (no changes will be made)"
}
Write-Host ""

# --- Step 1: Sanity check — must be inside a git repo ---
if (-not (Test-Path (Join-Path $repoRoot ".git"))) {
  Write-Host "ERROR: .git directory not found at $repoRoot"
  Write-Host "       Run this script from the repo root or via its full path."
  exit 1
}

# --- Step 2: Stop the scheduled task (best-effort) ---
Write-Host "Step 1: Stopping scheduled task 'SlotConsole'..."
if ($DryRun) {
  Write-Host "  [DRY-RUN] Would run: Stop-ScheduledTask -TaskName SlotConsole"
} else {
  try {
    Stop-ScheduledTask -TaskName SlotConsole -ErrorAction Stop
    Write-Host "  Task stopped."
  } catch {
    Write-Host "  WARN: Could not stop task (may not be registered): $_"
    Write-Host "        Continuing — ensure uvicorn is not running before proceeding."
  }
}

# --- Step 3: Wait for uvicorn process to exit (up to 30s) ---
Write-Host "Step 2: Waiting for uvicorn to exit (up to 30s)..."
if ($DryRun) {
  Write-Host "  [DRY-RUN] Would poll Get-Process python / port $bindPort for up to 30s."
} else {
  $waited = 0
  while ($waited -lt 30) {
    $portInUse = Get-NetTCPConnection -LocalPort $bindPort -State Listen -ErrorAction SilentlyContinue
    if (-not $portInUse) { break }
    Start-Sleep -Seconds 2
    $waited += 2
    Write-Host "  Still listening on $bindPort ... ${waited}s elapsed"
  }
  if ($waited -ge 30) {
    Write-Host "  WARN: uvicorn still appears to be running after 30s. Proceeding anyway."
    Write-Host "        If rollback fails due to locked files, kill the python process first."
  } else {
    Write-Host "  Port $bindPort is free."
  }
}

# --- Step 4: Check for uncommitted changes ---
Write-Host "Step 3: Checking for uncommitted changes..."
if ($DryRun) {
  Write-Host "  [DRY-RUN] Would run: git status --porcelain"
} else {
  $gitStatus = git status --porcelain 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: git status failed. Are you in a valid git repo?"
    exit 1
  }
  if ($gitStatus) {
    Write-Host ""
    Write-Host "ERROR: Uncommitted changes detected. Rolling back over unsaved work"
    Write-Host "       would permanently destroy those changes."
    Write-Host ""
    Write-Host "  Uncommitted files:"
    $gitStatus | ForEach-Object { Write-Host "    $_" }
    Write-Host ""
    Write-Host "  Options:"
    Write-Host "    git stash       — save changes temporarily"
    Write-Host "    git commit ...  — commit before rolling back"
    Write-Host "    git checkout -- . + git clean -fd — DISCARD changes (destructive)"
    Write-Host ""
    Write-Host "Rollback aborted. No changes made."
    exit 1
  }
  Write-Host "  Working tree is clean."
}

# --- Step 5: Show target commit ---
Write-Host "Step 4: Target commit..."
if ($DryRun) {
  Write-Host "  [DRY-RUN] Would run: git log --oneline -1 $To"
} else {
  $targetLog = git log --oneline -1 $To 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Cannot resolve ref '$To': $targetLog"
    exit 1
  }
  Write-Host "  Rolling back to: $targetLog"
}

# --- Step 6: Confirm with operator unless -Force ---
if (-not $Force -and -not $DryRun) {
  Write-Host ""
  Write-Host "WARNING: git reset --hard $To will discard all commits after the target."
  Write-Host "         This is irreversible unless you have the commit SHAs saved."
  Write-Host ""
  Write-Host "Type 'yes' to continue, anything else to abort: " -NoNewline
  $answer = Read-Host
  if ($answer -ne "yes") {
    Write-Host "Rollback aborted by operator."
    exit 1
  }
}

# --- Step 7: git reset --hard ---
Write-Host "Step 5: Performing git reset --hard $To ..."
if ($DryRun) {
  Write-Host "  [DRY-RUN] Would run: git reset --hard $To"
} else {
  git reset --hard $To
  if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: git reset --hard failed (exit $LASTEXITCODE)."
    exit $LASTEXITCODE
  }
  Write-Host "  Reset complete."
}

# --- Step 8: Next steps ---
Write-Host ""
Write-Host "Rollback complete."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Update dependencies if requirements changed:"
Write-Host "       python -m pip install -r src\web_console\requirements.txt"
Write-Host "  2. Start the server:"
Write-Host "       Start-ScheduledTask -TaskName SlotConsole"
Write-Host "  3. Verify with smoke script:"
Write-Host "       pwsh -NoProfile -File scripts\deploy\run_smoke.ps1"
