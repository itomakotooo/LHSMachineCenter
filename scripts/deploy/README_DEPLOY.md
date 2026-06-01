# SlotConsole — Deploy / Upgrade / Rollback Guide

This guide is written for the operator who manages the SlotConsole server on the company intranet. It does not assume familiarity with FastAPI or uvicorn internals — every step is copy-pasteable.

---

## 1. Pre-flight Checks

Run these checks on the machine that will host the server **before** starting the deploy:

```powershell
# 1a. PowerShell version — must be 5.1 or later (Windows 10/11 default is 5.1).
$PSVersionTable.PSVersion.Major
# Expected: 5 or higher

# 1b. Python on PATH — must be 3.10+ (the codebase uses PEP 604 union types like `int | None`).
python --version
# Expected: Python 3.10.x or higher

# 1c. pip available.
python -m pip --version

# 1d. Free disk space — rawdata can be large; ensure at least 20 GB free on the data drive.
Get-PSDrive -Name C | Select-Object Used, Free

# 1e. IMPORTANT — state/console/ MUST be on a local NTFS volume, NOT on a network share (SMB/CIFS).
#     SQLite WAL mode (used by console.db) does not work correctly over SMB.
#     Verify the repo is on a local drive, not a mapped drive letter pointing to a NAS.
Get-Item "state\console\console.db" | Select-Object FullName
```

---

## 2. Initial Deploy

### 2a. Clone the repository

```powershell
git clone <repo-url> C:\SlotConsole
cd C:\SlotConsole
```

### 2b. Install Python dependencies

```powershell
python -m pip install -r src\web_console\requirements.txt
```

### 2c. Set the SLOT_REPO_ROOT machine-level environment variable

This variable tells Task Scheduler where the repo lives. It must be set once as a machine-level (system-wide) variable. **Requires an Admin PowerShell session.**

```powershell
# Replace C:\SlotConsole with the actual path to the repo.
[System.Environment]::SetEnvironmentVariable(
    "SLOT_REPO_ROOT", "C:\SlotConsole", "Machine")

# Verify (in a new PowerShell window, or restart the current session):
$env:SLOT_REPO_ROOT
# Expected: C:\SlotConsole
```

### 2d. Register the Event Log source (one-time, requires Admin)

This allows start_console.ps1 to write to the Windows Event Log when the restart budget is exhausted.

```powershell
New-EventLog -LogName Application -Source "SlotConsole"
```

If the source is already registered you will see a harmless "already exists" error. If you cannot run this with Admin rights, the script falls back to writing a diagnostic file at `state\console\restart_exhausted.json` instead (no silent failure).

### 2e. Register the Windows Defender / firewall inbound rule (requires Admin)

Planners on the intranet connect to port 8877. Add an inbound allow rule:

```powershell
New-NetFirewallRule `
    -DisplayName "SlotConsole" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 8877 `
    -Action Allow
```

Remove this rule when decommissioning the server.

### 2f. Register the Task Scheduler task (requires Admin)

The task XML uses `<LogonType>Password</LogonType>` so that it can run at boot **without** requiring an active interactive logon session. You must supply the operator account password at registration time; Windows stores it encrypted in Credential Manager (it is not visible in the XML):

```powershell
schtasks /Create /XML scripts\deploy\SlotConsole.xml /TN SlotConsole /RU "%USERNAME%" /RP <password>
```

Replace `<password>` with the operator's Windows account password. If you omit `/RP`, schtasks will prompt interactively for the password before registering.

**Troubleshooting — "XML format error — cannot deserialize" at registration:**

Some Windows builds require the Task Scheduler XML in UTF-16 LE encoding rather than UTF-8. The committed file is UTF-8 for diff-friendliness. If `schtasks /Create /XML` fails with an XML-format error at position `(1, ...)`, re-encode the file once and register that copy instead:

```powershell
Get-Content scripts\deploy\SlotConsole.xml | Set-Content -Encoding Unicode scripts\deploy\SlotConsole.xml.utf16
schtasks /Create /XML scripts\deploy\SlotConsole.xml.utf16 /TN SlotConsole /RU "%USERNAME%" /RP <password>
```

The `.utf16` artifact is local-only and does not need to be committed.

**Why `Password` and not `InteractiveToken`?**
`InteractiveToken` requires that the operator already be interactively logged in when the task fires. At boot, before anyone logs in, Windows cannot obtain an interactive token — the BootTrigger fires but the task is silently skipped. `Password` stores the credentials at registration time, so the task launches immediately after boot regardless of whether anyone has logged in. This is what makes the "self-healing server after reboot" promise work.

Verify registration:

```powershell
Get-ScheduledTaskInfo -TaskName SlotConsole
```

### 2g. Reboot or start the task manually

After a reboot the task will start automatically (60-second boot delay). To start it immediately without rebooting:

```powershell
Start-ScheduledTask -TaskName SlotConsole
```

### 2h. Verify the server is up

Wait 30 seconds, then run the smoke script from the server itself:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy\run_smoke.ps1
```

All 5 probes should pass. From another machine on the LAN, replace `localhost` with the server's IP:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy\run_smoke.ps1 -BaseUrl http://192.168.x.x:8877
```

---

## 3. Upgrade (updating to a new version)

```powershell
# 1. Stop the task gracefully.
Stop-ScheduledTask -TaskName SlotConsole

# 2. Wait for the uvicorn process to exit (usually < 5 seconds).
#    Poll until python processes using the configured port are gone.
#    Substitute your configured SLOT_BIND_PORT here if not 8877 (the default).
$upgradePort = if ($env:SLOT_BIND_PORT) { [int]$env:SLOT_BIND_PORT } else { 8877 }
while (Get-NetTCPConnection -LocalPort $upgradePort -State Listen -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 2
    Write-Host "Waiting for uvicorn to exit (port $upgradePort)..."
}

# 3. Pull the new code.
git pull

# 4. Update dependencies (handles new packages added in this version).
python -m pip install -r src\web_console\requirements.txt

# 5. Restart the task.
Start-ScheduledTask -TaskName SlotConsole

# 6. Smoke-test after restart.
Start-Sleep -Seconds 15
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy\run_smoke.ps1
```

---

## 4. Rollback

If the new version has a critical issue, roll back to the previous commit.

### Quick manual rollback

```powershell
# Stop the task.
Stop-ScheduledTask -TaskName SlotConsole

# Roll back to the previous commit.
git revert HEAD --no-edit
# OR, if you need to discard the bad commit entirely (destructive — asks for confirmation):
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy\rollback.ps1 -To HEAD~1

# Restart.
Start-ScheduledTask -TaskName SlotConsole
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy\run_smoke.ps1
```

### SQLite schema note

The database schema only adds columns via `ALTER TABLE ... ADD COLUMN`. Old code ignores new columns it does not know about — rollback does NOT require a database migration. Simply starting the old code version is safe.

---

## 5. LAN Access for Planners

Planners on the intranet open a browser and go to:

```
http://<server-ip>:8877/console/
```

Replace `<server-ip>` with the server's local IP address. Find it with:

```powershell
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch "^127\." })[0].IPAddress
```

**No login is required.** The console is accessible to anyone on the intranet who can reach port 8877.

To change the bind host or port without editing the script, set these environment variables on the server before starting the task:

| Variable | Default | Effect |
|---|---|---|
| `SLOT_BIND_HOST` | `0.0.0.0` | Bind interface (use `127.0.0.1` to restrict to localhost) |
| `SLOT_BIND_PORT` | `8877` | Listening port |

---

## 6. Monitoring

### Event Viewer

Open: Windows Logs > Application > filter by Source = SlotConsole.

- **EventId 1001** — restart budget exhausted. The start_console.ps1 restart loop tried MAX_RESTARTS (5) times and gave up. Manual action required: check the application logs, fix the root cause, then restart the task.

```powershell
Get-ScheduledTask -TaskName SlotConsole | Get-ScheduledTaskInfo
# Check LastRunTime, LastTaskResult (0 = success, non-zero = error)
```

### Diagnostic files

If Event Log write fails (e.g. Source not registered), diagnostics are written to:

- `state\console\restart_exhausted.json` — restart budget exhaustion details

Errors from other subsystems (disk cleanup, report reassociation) also persist diagnostic JSON files under `state\console\`. Check this directory if the UI shows stale data or errors.

### Health probe

```powershell
Invoke-WebRequest http://localhost:8877/api/system-state | Select-Object StatusCode
# 200 = server is up; connection refused = server is down
```

---

## 7. Known Limitations

The following gaps are known as of P4 (2026-05-17). They are tracked for future cleanup; none block normal operation.

| Gap | Impact | Workaround |
|---|---|---|
| `config_id` not threaded through sampling sidecar | Config upload works but `config_id` in per-chunk sidecar is recorded as `"null"` | No impact on RTP/display; follow-up needed for multi-config dedup |
| `/api/system-state` does not surface `restart_exhausted.json` | Operator must check Event Viewer or disk file manually | See §6 Monitoring above |
| Rollback script does not clean SQLite if schema changed | Schema rollback requires manual DB inspection | Schema changes are additive; old code ignores new columns |
| POSIX/Linux not supported | Windows-only deploy | By design (per project requirements) |
| No HTTPS / TLS | HTTP only over LAN | Acceptable for intranet; future: nginx reverse proxy or cert mgmt |
| Playwright e2e not in the deploy smoke | Visual regressions not caught by the single-box deploy smoke | A Playwright e2e suite exists under `tests/e2e/` (run via `scripts/test.ps1 -E2E`); it is a dev-time check, not part of the deploy smoke |
| `refreshConfigList` on the frontend silently swallows non-404 errors | Server errors during config list fetch may be invisible in the UI | Check browser console or `/api/configs` directly |

---

## 8. Uninstall

```powershell
# Stop and remove the task.
Stop-ScheduledTask -TaskName SlotConsole
Unregister-ScheduledTask -TaskName SlotConsole -Confirm:$false

# Remove the firewall rule.
Remove-NetFirewallRule -DisplayName "SlotConsole"

# Remove the Event Log source (optional; harmless to leave).
Remove-EventLog -Source "SlotConsole"
```
