# Auto-Inspect Feature — Operator Smoke Test Guide

Use this guide after deploying a build that includes the auto-inspect feature
(Phase 5 final).  Each step is copy-pasteable or points to a specific UI element.

---

## Prerequisites

- Console server is running and reachable at `http://localhost:8000` (or the
  configured host).
- `configs/machines.json` is populated (the fleet).
- At least one upstream server snapshot exists under `.probe/server_snapshots/`.
  (Run a fleet refresh via the UI first if this directory is empty.)

---

## Step 1 — Pull and restart

```powershell
# 1a. Pull latest changes.
git pull origin collab/dev

# 1b. Stop the running server (Windows Task Scheduler).
schtasks /End /TN "SlotConsole"

# 1c. Wait ~5 seconds for uvicorn to shut down, then start.
schtasks /Run /TN "SlotConsole"
```

Verify the server is up:

```powershell
Invoke-WebRequest -Uri http://localhost:8000/api/system-state | Select-Object StatusCode
# Expected: StatusCode 200
```

---

## Step 2 — Open the UI and switch to the 自动巡检 tab

1. Open a browser to `http://localhost:8000`.
2. Click the **自动巡检** tab in the main navigation.
3. The settings panel should appear (sweep concurrency, target CI, cron picker,
   schedule mode/value fields).

Expected: no console errors in the browser DevTools.

---

## Step 3 — Hit 预览 (Preview)

Click the **预览巡检范围** button (or the preview button at the top of the form).

Expected response (within ~30 seconds):
- `total` shows the number of cells to be swept (typically ~1688 for a full
  fleet with 4 modes).
- `by_mode` breaks down by mode (1 / 2 / 5 / 7).
- `by_cell_class` shows `easy`, `trigger_session`, `manifest_override`, etc.
- No error toast.

If you see "preview unavailable: scan timed out", the upstream snapshot may be
stale or the server's disk is very slow.  Run a fleet refresh first, then retry.

---

## Step 4 — Hit 开始巡检 (Start sweep)

Click **开始巡检**.

Expected:
- The UI switches to a progress view.
- The aggregate counters (total / completed / failed / skipped) appear.
- The per-cell table starts populating within a few seconds.

Verify via API:

```powershell
$r = Invoke-RestMethod http://localhost:8000/api/auto-inspect
$r.sweeps[0].status
# Expected: "sampling" (or "scanning" if the fleet is large)
```

---

## Step 5 — Watch ~5 cells complete

Wait for at least 5 cells to show `status: completed` in the per-cell table.
This typically takes 2-5 minutes per cell (10k-spin chunks × 2 workers).

Expected:
- `completed_items` counter increments.
- Per-cell rows update from `running` to `completed`.
- No `failed` rows appear unless the upstream simulator is unreachable.

---

## Step 6 — Cancel; verify graceful stop

Click **取消巡检** (Cancel sweep).

Expected (within ~10 seconds):
- Sweep status changes to `cancelled`.
- Any `running` items finish naturally (they are not killed mid-run).
- Pending items immediately flip to `cancelled`.

Verify:

```powershell
$r = Invoke-RestMethod http://localhost:8000/api/auto-inspect
$r.sweeps[0].status
# Expected: "cancelled"
```

---

## Step 7 — Restart server; verify resume kicks in

Start a sweep (Step 4 again) and let 2-3 cells reach `running` status.
Then stop and restart the server immediately:

```powershell
schtasks /End /TN "SlotConsole"
# wait 5s
schtasks /Run /TN "SlotConsole"
```

Expected:
- After restart, within ~10 seconds the sweep resumes automatically.
- The progress panel shows the same sweep_id; counters continue from where
  they left off.
- `claimed` items from before the crash are reset to `pending` and retried.

Verify:

```powershell
$r = Invoke-RestMethod http://localhost:8000/api/auto-inspect
$r.sweeps[0].status
# Expected: "sampling" (still running, not "failed")
```

---

## Step 8 — Cron scheduler smoke

Enable scheduled sweeps via the UI settings form:

1. Set **Schedule mode** to **每 N 小时** (interval).
2. Set N to `1` (fire every 1 hour).
3. Click **Save settings**.

Verify the scheduler is armed (optional — requires log access):

```powershell
Get-Content state\console\uvicorn.err.log -Tail 20 | Select-String "AutoInspectScheduler"
# Expected: "_AutoInspectScheduler: next sweep in 3600s (mode=interval value=1)"
```

Disable the scheduler again before leaving:

1. Uncheck **启用自动巡检** (enabled).
2. Save settings.

---

## Step 9 — M274 RTP-drift alert (first run creates baseline)

After the sweep completes M274 mode 1, check for the baseline file:

```powershell
Get-Item state\console\m274_baseline.json | Select-Object FullName
Get-Content state\console\m274_baseline.json
```

Expected: file exists with `baseline_rtp_pct` set to the observed RTP.

If the RTP drifts by more than 2pp in a future sweep, a `m274_alert_*.json`
file will appear in `state/console/` and a WARN event will show in the
per-cell events panel for M274 mode 1.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Preview returns 503 | Upstream snapshot missing or very slow disk | Run fleet refresh first |
| Sweep stuck in `scanning` >2 min | Large fleet + slow NTFS | Wait; `phase=scanning` is normal for ~5-10s |
| All items `structural_skip` | `structural_skip_machines` list too broad in settings | Check `auto_sweep.structural_skip_machines` in settings.json |
| Sweep not resuming after restart | DB lock (another process has console.db open) | Close all other SQLite tools and restart server |
| `m274_alert_*.json` appears | M274 RTP drifted >2pp from baseline | Investigate M274 config or upstream data |

---

*Generated for auto-inspect Phase 5. See `session_artifacts/_arch/auto_inspect/07_decision.md` for design rationale.*
