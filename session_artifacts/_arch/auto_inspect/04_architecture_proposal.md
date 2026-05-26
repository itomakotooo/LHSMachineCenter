# Architecture Proposal: 自动巡检 / Auto-Inspect Sweep
> Wave 2 — Designer output  
> Date: 2026-05-26  
> Input sources: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`  
> All section numbers refer to the required deliverables in the task brief.

---

## §0 Problem Statement

The current backend exposes three manager-class systems (BatchRunManager, BatchGenerateManager, FleetRefreshManager) that are all manually triggered by the operator. There is no mechanism that automatically discovers which of the 1,688 cells (422 machines × 4 modes) need fresh sampling, schedules them, handles failures per cell type, and surfaces progress without operator intervention. This forces the operator to watch for md5 drift manually and construct batch-run requests by hand.

**Five concrete pain points (all cited from Wave 1):**

1. **No "needs sample" oracle driving action.** `_build_machines_summary` computes `md5_status` on-read but nothing consumes it to build a work queue. (01:§6-B, 03:OQ-3)
2. **FleetRefreshManager is serial and has hardcoded parameters.** `chunk_spin_times=1000, max_chunks=120` are fixed in `_fleet_batch_item_runner` at app.py:11543-11548, not operator-tunable and too small for adequate CI. (01:§8, 03:FleetRefreshManager section)
3. **1,688-cell fleet has hard failure modes that need explicit routing.** 28 Tier-1 cells (M250/M260/M264/M268/M279/M99/M274) are structurally non-convergent. 344 M273-family cells share one game binary and must be rate-capped to avoid self-DoS. Random or naive ordering burns rate-limit budget on hard cases. (02:§7, 02:§8)
4. **No per-mode granularity storage.** `settings.json` has no schema for per-mode parameters. There is no existing mechanism to say "mode 7 needs larger chunk_spin_times than mode 1". (01:OQ-1, 01:OQ-8, 03:Settings section)
5. **R1 orphan-recovery has a blind spot for any new manager class.** `_is_cell_owned_by_active_queue` (app.py:6085-6141) only checks `fleet_refresh_items` and `batches` tables. A new manager with its own table would cause A2 to double-spawn orphan runs. (03:Coordinate section, 03:RISK-4)

---

## §1 Decision: Which Manager

### The three options

**Option A — BatchRunManager wrapper**: Build the sweep by calling `BatchRunManager.start_batch` with a pre-filtered list of 1,688 cells. Generate phase calls `BatchGenerateManager`.

**Option B — FleetRefreshManager extended**: Add per-mode granularity parameters, a post-sampling generate step, and a "needs-sample" predicate to the existing `FleetRefreshManager`.

**Option C — New AutoInspectManager (recommended)**: A parallel fourth manager class with its own SQLite tables, its own per-item state machine, and clean injection from `create_app`. Delegates actual sampling work to `RunManager.start_run` directly (same pattern as `_fleet_batch_item_runner`) and generate work to the `batch_gen_mgr` reference captured in `create_app`.

---

### Option A — BatchRunManager wrapper

**Sketch:**
```
POST /api/auto-inspect/start
  -> build cell_list from _build_machines_summary (03:§3)
  -> call batch_mgr.start_batch(BatchRunRequest(items=cell_list, ...))
  -> record returned batch_id in a lightweight auto_inspect_run row
  -> after sampling done, call batch_gen_mgr.start(generate_items)
```

**Pros:**
- R1 / A2 coverage is automatic: the `batches` table check at app.py:6127-6138 covers all items. (03:Coordinate — A2+R1)
- No new SQLite table needed.
- Resume button works for free via `POST /api/batch-run/{id}/resume`.

**Cons:**
- `BatchRunManager._run_batch` launches ALL item threads simultaneously and uses a semaphore cap (01:§2). A 1,688-item all-at-once launch with a semaphore is not the same as a sweep that yields per-cell, checks failure budgets, applies M273 binary-group caps, or defers on lock conflict. Emulating sweep semantics requires patching `_run_batch`, coupling the sweep logic into the manager's internals.
- No per-codeSummaryMd5 concurrency cap. The M273 344-cell risk (02:§8) cannot be enforced from outside `start_batch` — the semaphore is global, not per-binary-group.
- Sweep history is mixed in with operator-initiated batches in `GET /api/batches`. The `kind` column would need `'sweep'` (03:batches-kind section), but BatchRunManager always writes `'sampling'`.
- Two batch IDs per sweep (one sampling, one generate) with no parent-child link. The UI must correlate them, which is not designed.
- `start_batch` calls `_detect_machine_cycle` per item (app.py:1599) and does a pre-batch async md5 refresh (app.py:7559). Both are useful but create coupling between the sweep's pre-flight and BatchRunManager's pre-flight — each will conflict if the sweep also does its own md5 refresh.

**Migration cost:** Low in code written, high in behavioral compromise. The 9 failure modes (§5) cannot be spec'd cleanly into BatchRunManager's two terminal states per item (completed/failed).

---

### Option B — FleetRefreshManager extended

**Sketch:**
```
POST /api/fleet/refresh  (extended body)
  body: {modes: [1,2,5,7], include_auto_generate: true,
         per_mode_params: {1: {chunk_spin_times: 10000, ...}, ...},
         failure_budget: {max_consecutive_failures: 3, ...}}
  -> FleetRefreshManager.start_queue(machines, config)
     now reads per_mode_params and calls _fleet_batch_item_runner with them
     adds generate step after each sampling completion
```

**Pros:**
- Smallest net-new code surface.
- R1 / A2 coverage automatic (fleet_refresh_items already checked).
- Sequential model naturally applies per-codeSummaryMd5 ordering if the cell-ordering tier logic (02:§9) is baked into the queue-position assignment.

**Cons:**
- `start_queue` is single-instance (409 if running, app.py:11621). The sweep cannot coexist with a manually triggered fleet refresh. (03:FleetRefreshManager single-instance section). User requirement says auto trigger (cron-like), which may fire while an operator-triggered fleet refresh is also running.
- The existing serial model (one item at a time) means 1,688 cells with target CI of 0.5 pp could take tens of hours on the loopback; the new design needs a per-mode concurrency cap independent of FleetRefreshManager's single-thread model. Adding parallelism to FleetRefreshManager changes its threading model, which is a significant internal refactor.
- `_fleet_batch_item_runner` is a closure in `create_app` (app.py:11525-11558), not a class method. Parameterizing it to accept per-mode config requires either making the closure stateful (a dict captured from the outer scope) or converting it into a class — both introduce coupling to `create_app`'s wiring.
- All 9 failure modes (§5) must be mapped into FleetRefreshManager's existing three terminal states (`completed / failed / skipped`). Structural give-up, convergence timeout, and binary-group cap are conceptually different but would all resolve to `skipped`. Operators cannot distinguish them.
- The "needs-sample" predicate and the generate phase are both fundamentally new logic; adding them to FleetRefreshManager turns a simple queue runner into a multi-phase orchestrator.

**Migration cost:** Medium. Requires a refactor of `_fleet_batch_item_runner`, a threading model change, and an extension of FleetRefreshManager's item state vocabulary.

---

### Option C — New AutoInspectManager (RECOMMENDED)

**Sketch (file structure):**
```
src/web_console/backend/
  auto_inspect_manager.py          # AutoInspectManager class
  auto_inspect_state.py            # SQLite table helpers (new tables)
  # No changes to fleet_refresh.py, BatchRunManager, BatchGenerateManager
```

**Key interfaces:**
```python
class AutoInspectManager:
    def __init__(self, store: StateStore, run_manager: RunManager,
                 batch_gen_mgr: BatchGenerateManager,
                 registry: CellLockRegistry, limiter: ConcurrencyLimiter,
                 machines_config: Path, rawdata_root: Path,
                 reports_root: Path, settings_path: Path): ...

    def start_sweep(self, trigger: str = "manual",
                    modes: list[int] | None = None) -> str:
        """Returns sweep_id. 409 if already running."""

    def cancel(self, sweep_id: str) -> None: ...

    def get_status(self, sweep_id: str) -> dict: ...

    def list_history(self, limit: int = 20) -> list[dict]: ...

    def get_cell_status(self, sweep_id: str,
                        machine: str, mode: int) -> dict: ...
```

**Pros:**
- Full isolation: FleetRefreshManager and AutoInspectManager can coexist. A manual fleet refresh does not block or race the sweep.
- All 9 failure modes (§5) get their own named terminal status (structural_skip / convergence_timeout / wall_time_exceeded / consecutive_failures / fleet_abort / deferred_lock_conflict / md5_mid_sweep_drift / network_error / completed).
- M273 binary-group cap (02:§8) is implemented as a per-codeSummaryMd5 semaphore dict maintained within the sweep manager — this is not possible with Option A or B without refactoring the existing managers.
- Cell ordering tiers from 02:§9 (easy-first, hard-last) can be baked into the sweep's queue-position assignment at `start_sweep` time.
- No interference with `GET /api/batches` / B2 history panel — the sweep has its own status endpoints.
- RISK-1 (module-global path leak, 03:RISK-1) is fully controlled: the manager is constructed exclusively by `create_app` with injected paths.

**Cons:**
- R1 / A2 blind spot: `_is_cell_owned_by_active_queue` (app.py:6085-6141) does not know about `auto_inspect_items`. Requires a one-function addition: a fourth branch querying `auto_inspect_items WHERE status IN ('pending','running') AND sweep_id = (SELECT sweep_id FROM auto_inspect_sweeps WHERE status='running')`. This is a targeted 5-line change in one function.
- More new code: approximately 400 lines for the manager class + 80 lines for the SQLite helpers.
- Sweep progress is not in `GET /api/batches`; the frontend needs new endpoints (`/api/auto-inspect/*`).

**Migration cost:** Highest in net-new lines, lowest in coupling risk. No existing manager is modified. All new code is reviewable in isolation.

**Why Option C is chosen:**

The core user requirement is "operator-tunable per-mode granularity + explicit failure modes + M273 binary-group cap + per-cell status reason + cron trigger." Every one of these requires state and logic that does not fit cleanly into the existing managers' APIs without patching their internals. The Auditor's OQ-1 (03:OQ-1) explicitly lists all three options with pros/cons; the analysis there shows Option A and B both require internal changes to existing code to meet the full spec. Option C limits changes to existing code to:
- One function addition in `_is_cell_owned_by_active_queue` (5 lines)
- `_load_settings` extended with `auto_sweep` key validation
- `PUT /api/settings` accepting the new key
- Three new API routes in `app.py` (50 lines)
- SQLite schema additions (new tables, `StateStore._init_db`)

All other changes are in the new file `auto_inspect_manager.py`.

---

## §2 UI Tab Specification

### Tab structure

New third tab in the header row, after `机台管理` and `数据分析`. In `index.html`, add `<button data-tab="inspect">自动巡检</button>` and `<section id="tab-inspect">`. In `app.js`, wire a `switchTab("inspect")` case in `boot()` at app.js:8638 (per 03:OQ-7 which confirms this is the trivially extensible extension point).

### Top-level layout (two columns)

```
+----------------------------------------------------+
|  [Settings Panel — left ~35%] [Status Panel — right ~65%]  |
+----------------------------------------------------+

Settings Panel:
  - Auto-sweep on/off toggle  (persists to auto_sweep.enabled)
  - Schedule cron expression  (persists to auto_sweep.schedule_cron)
  - Per-mode granularity table (4 rows × 5 fields — see below)
  - Concurrency override
  - [Save Settings] [Preview Needs-Sample] [Start Sweep Now]

Status Panel:
  - Current sweep progress (or "idle" if none running)
  - Recent sweep history table (last 10)
  - Per-cell drill-down panel (appears on row click)
```

### Per-mode granularity form

4 rows (Mode 1, Mode 2, Mode 5, Mode 7), 5 fields each:

| Field | Type | Validation |
|---|---|---|
| chunk_spin_times | int | 1,000 – 100,000 |
| chunk_robot_count | int | 1 – 16 |
| batch_concurrency | int | 1 – 32 |
| target_halfwidth_pp | float | 0.0 – 5.0 |
| max_chunks | int | 1 – 1,000 |

Submitted via `PUT /api/settings` as part of the full `auto_sweep.modes` block (03:Settings section confirms `PUT /api/settings` does a full-document overwrite which is safe).

### "Preview Needs-Sample" button

Before launching a sweep, the operator can click "Preview Needs-Sample" which calls `GET /api/auto-inspect/preview`. The backend runs the cell-discovery logic (md5 comparison + report existence check — see §3 internal state) synchronously and returns a summary:

```json
{
  "total_cells": 1688,
  "needs_sample": 342,
  "no_report": 45,
  "md5_outdated": 297,
  "fresh_skip": 1346,
  "tier_breakdown": {
    "easy": {"count": 280, "cells": [...]},
    "trigger_session": {"count": 52, "cells": [...]},
    "bcm_hard": {"count": 7, "cells": [...]},
    "bcm_moderate": {"count": 3, "cells": [...]}
  }
}
```

The UI renders this as a bar chart by tier + a collapsible table of the specific cells. The operator can then decide to launch or abort.

### Running sweep — progress surface

The UI polls `GET /api/auto-inspect/status` every 5 seconds (same interval as FleetRefreshManager's frontend poll). Response schema:

```json
{
  "sweep_id": "ai_abc123",
  "status": "sampling",
  "trigger": "manual",
  "started_at": "...",
  "total_cells": 342,
  "completed": 120,
  "skipped": 5,
  "failed": 3,
  "in_progress": 4,
  "pending": 210,
  "elapsed_s": 3600,
  "phase": "sampling",
  "binary_group_caps": {
    "c2a4e3be": {"inflight": 2, "cap": 4}
  }
}
```

The aggregate is shown as a progress bar with counts per status. Because 1,688 cells cannot all be listed in a single response without bloating the poll, the per-cell list is not included in the status response. Instead, the UI shows the aggregate plus a "View all cells" button.

### Per-cell drill-down

"View all cells" opens a paginated table (50 rows/page) populated by `GET /api/auto-inspect/status?sweep_id=X&page=N`. Each row shows:

```
| Machine | Mode | Status | Terminal Reason | Spins | CI | Duration |
| M14     | 1    | completed | - | 1.2M | 0.31 pp | 4m 12s |
| M250    | 1    | structural_skip | BCM anchor gap — manual review required | - | - | 0s |
| M279    | 2    | convergence_timeout | 未收敛: 1.2M spins budget exhausted | 1.2M | 1.4 pp | 82m |
```

Terminal reason strings per failure mode are defined in §5. Each row is clickable and opens the report (if one exists) in the existing debug panel.

### Cancel mid-sweep

`DELETE /api/auto-inspect` sets a cancel flag in the sweep manager. In-flight items run to completion (same pattern as FleetRefreshManager cancel, fleet_refresh.py:cancel_queue). Pending items are marked `cancelled`. The UI shows "Cancelling..." and updates when all in-flight items drain.

### Resume button after restart

On page load, the frontend calls `GET /api/auto-inspect/status` with no sweep_id. If the backend reports `has_resumable: true` (a sweep was in progress when the console restarted), a "Resume Sweep" button appears. Clicking it calls `POST /api/auto-inspect/resume` which restarts the sweep's daemon thread against the existing `auto_inspect_items` rows that are still `pending` (after the crash-recovery reset described in §4).

---

## §3 Backend Manager Structure

### Construction (wired in `create_app`)

```python
auto_inspect_mgr = AutoInspectManager(
    store=store,                    # injected StateStore (db path)
    run_manager=manager,            # injected RunManager
    batch_gen_mgr=batch_gen_mgr,   # injected BatchGenerateManager reference
    registry=registry,              # shared CellLockRegistry
    limiter=limiter,                # shared ConcurrencyLimiter
    machines_config=mc,             # injected Path — NEVER module-global
    rawdata_root=rd_root,           # injected Path — NEVER module-global
    reports_root=rp_root,           # injected Path
    settings_path=settings_path,    # injected Path
)
# On construction: _restore_on_startup() — see §4 restart recovery
```

Critical: every path parameter is injected, never read from the module-global `RAWDATA_ROOT` / `MACHINES_CONFIG`. This directly addresses RISK-1 (03:RISK-1) and the pattern documented in `feedback_subprocess_import_suicide_and_module_globals.md`.

### Internal state machine

```
idle
  -> start_sweep() called
scanning
  -> _build_machines_summary() + check_rawdata_status() per cell
  -> builds ordered cell list (see Cell ordering below)
  -> writes auto_inspect_items rows
  -> starts per-mode semaphore threads
sampling           <-- main phase; per-item loop across tiers
  -> per item: SAMPLING acquire -> RunManager.start_run -> poll -> release
  -> failure routing per §5
  -> binary-group cap enforced via per-codeSummaryMd5 semaphore
generating
  -> after all sampling items reach terminal state
  -> calls batch_gen_mgr.start(items_with_rawdata)
  -> polls BatchGenerateManager batch until terminal
done
  -> writes finished_at, final tallies to auto_inspect_sweeps row
  -> returns to idle; keeps history
```

Transitions are logged to `auto_inspect_events` table (see §4). An explicit `cancelled` state is reachable from any non-idle state via `cancel()`.

### Cell discovery logic

Called during `scanning` phase:

1. **Synchronous md5 refresh** (per 03:md5-refresh section — the Auditor flags this as a risk if skipped): call `_do_refresh_machines_md5(raise_on_error=False)` synchronously before building the cell list. Not async — the sweep cannot begin with stale machines.json. Timeout: 30 seconds. If the refresh fails, log a warning and continue with the cached machines.json; cells that appear fresh may be stale, which is acceptable (they will be swept next run).

2. **Build candidate set**: iterate all machines in `machines_config` × modes `[1, 2, 5, 7]`. For each `(machine, mode)`:
   - Call `_get_machine_md5(machine, machines_config, mode)` — ALWAYS with explicit `mode`, never `mode=None`. This is the single most important call-site rule derived from 03:RISK-1 and the auditor's footgun note.
   - Call `check_rawdata_status(machine, mode, rawdata_root, machines_config)` to get `usable_chunks`, `mismatch_chunks`.
   - Check `_build_machines_summary` result for this (machine, mode): get `md5_status`, `ci_halfwidth_pp`.

3. **"Needs sample" predicate** (answers 01:OQ-4):
   - `needs_sample = True` if any of:
     - No report exists for this (machine, mode) at all (absent from `_build_machines_summary` result)
     - `md5_status == "outdated"` (report was generated against a different upstream md5 than current)
     - `usable_chunks == 0` (all rawdata chunks are from an old md5 — no reusable data)
   - `needs_sample = False` if `md5_status == "match"` AND `ci_halfwidth_pp <= target_halfwidth_pp_for_mode`
   - The "no report" signal comes from absence in `_build_machines_summary`, not a separate check (per 03:§2 note: absence from the result dict is the signal).
   - Per-mode `target_halfwidth_pp` is read from `auto_sweep.modes[mode].target_halfwidth_pp` in settings.

4. **Hard-case classification** (per 02:§7): for each candidate cell, assign a `cell_class` tag:
   - `easy`: not in any hard-case roster (02:§5 — 1,024 cells, 60.7%)
   - `trigger_session`: Type-1 or Type-2 family (02:§3 Axis B)
   - `bcm_hard`: Tier-1 hard case M250/M260/M264/M268/M279/M99/M274 (02:§7 Tier 1)
   - `bcm_moderate`: M147, M163 (02:§7 BCM moderate)
   - `bcm_uncharted`: M278, M280, M281 (02:§7 new uncharted)

5. **Queue ordering** (per 02:§9 — easy-first principle):
   ```
   queue_position = (tier * 10000) + within_tier_index
   where tier:
     0 = easy (modes 1 first, then 2, 5, 7)
     1 = trigger_session
     2 = bcm_moderate + bcm_uncharted
     3 = bcm_hard
   ```
   Mode 1 within each tier is processed before modes 2, 5, 7 per the operator's primary verification mode (`user_testing_machine.md` memory: M14 mode 1 is the operator's verification machine).

6. **Skip conditions** (applied before enqueue):
   - `rawdata_locks.json` marks the directory locked (02:§8)
   - Cell is currently SAMPLING or GENERATING (registry check) — defer, not skip (see failure mode g, §5)

### Work dispatch — sampling phase

The sweep does NOT call `BatchRunManager.start_batch`. It calls `RunManager.start_run` directly, the same pattern as `_fleet_batch_item_runner` (01:§4, app.py:11554). This avoids the double-SAMPLING-lock problem noted in 01:OQ-7 and gives the sweep direct control over the `RunCreateRequest` parameters.

Per-item flow:
```
1. Cancel check
2. Check per-codeSummaryMd5 semaphore (binary-group cap — see below)
3. registry.try_acquire_cell(machine, mode, SAMPLING, info={...})
   if fails: "yield-and-retry" loop (5s poll, up to CELL_BUSY_TIMEOUT_S=1800)
             on timeout: mark cell status='deferred_lock_conflict' (failure mode g)
4. limiter.acquire("background", cancel_flag=...)
5. Build RunCreateRequest:
   - chunk_spin_times: settings.auto_sweep.modes[mode].chunk_spin_times
     (or None to trigger _detect_machine_cycle heuristic — see §6 defaults)
   - chunk_robot_count: settings.auto_sweep.modes[mode].chunk_robot_count
   - batch_concurrency: settings.auto_sweep.modes[mode].batch_concurrency
   - max_chunks: settings.auto_sweep.modes[mode].max_chunks
   - target_halfwidth_pp: settings.auto_sweep.modes[mode].target_halfwidth_pp
   - resume_from_cache_dir: rawdata_root / machine / f"mode_{mode}"
   - upstream_config_md5, upstream_code_md5: from _get_machine_md5(machine, mc, mode)
   - timeout: per-cell wall-time cap (failure mode d)
6. run_manager.start_run(req) -> run_id
7. Update auto_inspect_items: run_id=run_id, status='running'
8. Poll store.get_run(run_id) every 5s up to wall_time_cap
9. On completion:
   - Read summary.json: extract stop_reason, achieved_halfwidth_pp, total_spins
   - Route to appropriate terminal status (§5)
10. finally: registry.release_cell(SAMPLING)
             limiter.release()
             release per-codeSummaryMd5 semaphore slot
             increment consecutive_failure_count if failed
             check fleet abort threshold (failure mode f)
             _persist_item()
```

### Work dispatch — generate phase

After all sampling items reach terminal state, the sweep calls:
```python
generate_items = [
    {"machine": m, "mode": mo}
    for (m, mo, status) in completed_items
    if status in ("completed", "convergence_timeout")
    # convergence_timeout still has partial data worth generating
]
batch_gen_mgr.start(generate_items)
# Poll batch_gen_mgr.get_status(batch_id) every 10s until terminal
```

This reuses the existing `BatchGenerateManager` pool (ProcessPoolExecutor). The batch-gen items are enqueued after all sampling is done; generating from partial data (convergence_timeout) is intentional — operators see "未收敛" in the report rather than no report. Cells with `structural_skip` are excluded from generate because no rawdata was written.

### Per-codeSummaryMd5 concurrency cap

Per 02:§8, the M273 86-machine family (codeSummaryMd5 = c2a4e3be) shares one game binary. Launching all 344 M273 cells concurrently is a self-DoS risk.

Design: the sweep manager maintains a dict of `threading.Semaphore` instances keyed by codeSummaryMd5:

```python
_binary_group_semas: dict[str, threading.Semaphore] = {}
_BINARY_GROUP_DEFAULT_CAP = 4  # see §6 for rationale
_LARGE_GROUP_CAP = 2           # M273 with 86 machines
```

At `start_sweep` time, after building the cell list, scan all `codeSummaryMd5` values. If a binary group has >= 20 machines sharing it (current threshold: M273 with 86, standard-large with 45), assign `cap = _LARGE_GROUP_CAP`. Otherwise `cap = _BINARY_GROUP_DEFAULT_CAP`.

The per-item flow acquires the binary-group semaphore BEFORE the SAMPLING lock (step 2 above). This prevents overload at the binary level while still allowing the SAMPLING lock to serialize within a single (machine, mode) cell.

Binary-group semaphore acquisition uses a cancel-aware poll (same pattern as `limiter.acquire("background", cancel_flag=...)`). If the sweep is cancelled, blocked binary-group acquires are unblocked.

### Concurrency model summary

```
AutoInspectManager._run_sweep_thread
  spawns N worker threads (N = settings.auto_sweep.sweep_concurrency, default 3)
  each worker thread loops:
    pick next pending item (ORDER BY queue_position ASC)
    acquire binary-group semaphore (keyed by codeSummaryMd5)
    registry.try_acquire_cell(SAMPLING) [yield-and-retry loop]
    limiter.acquire("background")
    RunManager.start_run -> poll
    finally: release all three (semaphore, SAMPLING, limiter)
```

Three layers of concurrency control:
1. `sweep_concurrency` threads (coarse cap — total sweep parallelism)
2. `binary_group_semas[code_md5]` (per-binary-group cap — prevents M273 DoS)
3. `ConcurrencyLimiter("background")` (shared with FleetRefreshManager — 3 slots)

---

## §4 Persistence

### New SQLite tables

**`auto_inspect_sweeps`** — one row per sweep run:

```sql
CREATE TABLE IF NOT EXISTS auto_inspect_sweeps (
    sweep_id       TEXT PRIMARY KEY,
    trigger        TEXT NOT NULL,          -- 'manual' | 'cron'
    status         TEXT NOT NULL,          -- scanning | sampling | generating | done | cancelled | failed
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    total_cells    INTEGER NOT NULL DEFAULT 0,
    completed      INTEGER NOT NULL DEFAULT 0,
    structural_skip INTEGER NOT NULL DEFAULT 0,
    convergence_timeout INTEGER NOT NULL DEFAULT 0,
    wall_time_exceeded  INTEGER NOT NULL DEFAULT 0,
    consecutive_fail    INTEGER NOT NULL DEFAULT 0,
    fleet_aborted       INTEGER NOT NULL DEFAULT 0,
    deferred_lock       INTEGER NOT NULL DEFAULT 0,
    md5_drift_skip      INTEGER NOT NULL DEFAULT 0,
    other_failed        INTEGER NOT NULL DEFAULT 0,
    modes_json     TEXT NOT NULL DEFAULT '[]',   -- JSON array of modes included
    settings_snapshot_json TEXT NOT NULL DEFAULT '{}'  -- snapshot of auto_sweep settings at sweep start
);
```

**`auto_inspect_items`** — one row per (sweep, machine, mode):

```sql
CREATE TABLE IF NOT EXISTS auto_inspect_items (
    sweep_id       TEXT NOT NULL REFERENCES auto_inspect_sweeps(sweep_id),
    machine        TEXT NOT NULL,
    mode           INTEGER NOT NULL,
    queue_position INTEGER NOT NULL,
    cell_class     TEXT NOT NULL,          -- easy | trigger_session | bcm_hard | bcm_moderate | bcm_uncharted
    status         TEXT NOT NULL DEFAULT 'pending',
    -- terminal statuses: completed | structural_skip | convergence_timeout |
    --                    wall_time_exceeded | consecutive_failures | fleet_aborted |
    --                    deferred_lock_conflict | md5_mid_sweep_drift | cancelled | failed
    run_id         TEXT,                   -- RunManager run_id (null until sampling starts)
    generate_run_id TEXT,                  -- BatchGenerateManager run_id (null until generate starts)
    attempt_count  INTEGER NOT NULL DEFAULT 0,
    terminal_reason TEXT,                  -- human-readable reason string (§5)
    started_at     TEXT,
    finished_at    TEXT,
    total_spins    INTEGER,
    achieved_halfwidth_pp REAL,
    PRIMARY KEY (sweep_id, machine, mode)
);
CREATE INDEX IF NOT EXISTS idx_aii_sweep_status ON auto_inspect_items(sweep_id, status);
CREATE INDEX IF NOT EXISTS idx_aii_sweep_pos    ON auto_inspect_items(sweep_id, queue_position);
```

**`auto_inspect_events`** — append-only event log per sweep (capped at 500 entries per sweep, same pattern as `events_json` in `batches` but normalized):

```sql
CREATE TABLE IF NOT EXISTS auto_inspect_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sweep_id       TEXT NOT NULL,
    ts             TEXT NOT NULL,
    machine        TEXT,
    mode           INTEGER,
    event_type     TEXT NOT NULL,   -- 'cell_started' | 'cell_done' | 'cell_skipped' | 'phase_change' | 'cancelled' | 'error'
    detail         TEXT
);
CREATE INDEX IF NOT EXISTS idx_aie_sweep ON auto_inspect_events(sweep_id, id);
```

### Interaction with existing tables

| Existing table | Interaction |
|---|---|
| `batches` (kind='sampling'/'generate') | NOT used by AutoInspectManager for its own sweep rows. The generate phase calls `batch_gen_mgr.start()` which DOES write to `batches` with kind='generate'. These generate batches are visible in `GET /api/batches` as ordinary generate batches (operator can see them; they are not tagged as sweep-initiated, but this is acceptable per 03:batches-kind discussion). |
| `fleet_refresh_queue` / `fleet_refresh_items` | No interaction. AutoInspectManager is a separate manager. They share `CellLockRegistry` and `ConcurrencyLimiter` but not SQLite tables. |
| `runs` | Written by `RunManager.start_run` as usual. AutoInspectManager stores the `run_id` in `auto_inspect_items.run_id`. |
| `pending_batch_configs` (D2 anchor) | NOT used. AutoInspectManager calls `RunManager.start_run` directly (same as `_fleet_batch_item_runner`). FleetRefreshManager also does not use this anchor (01:OQ-7 confirms this is an intentional pattern for queue-driven sampling). |

### `_is_cell_owned_by_active_queue` extension

In `app.py`, function `_is_cell_owned_by_active_queue(machine, mode)` (app.py:6085-6141) must gain a fourth branch:

```python
# Branch 4 — auto_inspect_items (NEW)
row = store.db.execute(
    """SELECT aii.sweep_id FROM auto_inspect_items aii
       JOIN auto_inspect_sweeps ais ON ais.sweep_id = aii.sweep_id
       WHERE aii.machine = ? AND aii.mode = ?
         AND aii.status IN ('pending','running')
         AND ais.status IN ('scanning','sampling','generating')
       LIMIT 1""",
    (machine, mode)
).fetchone()
if row:
    return {"kind": "auto_inspect", "sweep_id": row[0]}
```

This eliminates RISK-4 (03:RISK-4) and ensures A2 (orphan-resume) yields correctly to the sweep's own restart recovery.

### Settings schema additions

New top-level key `auto_sweep` in `state/console/settings.json`, validated in `_load_settings` (app.py:885):

```json
"auto_sweep": {
    "enabled": false,
    "schedule_cron": "",
    "sweep_concurrency": 3,
    "skip_fresh_cells": true,
    "wall_time_cap_per_cell_s": 7200,
    "max_consecutive_failures": 3,
    "fleet_abort_failure_threshold": 50,
    "binary_group_large_cap": 2,
    "modes": {
        "1": {
            "chunk_spin_times": 10000,
            "chunk_robot_count": 8,
            "batch_concurrency": 8,
            "target_halfwidth_pp": 0.5,
            "max_chunks": 120
        },
        "2": { "chunk_spin_times": 10000, "chunk_robot_count": 8, "batch_concurrency": 8, "target_halfwidth_pp": 0.5, "max_chunks": 120 },
        "5": { "chunk_spin_times": 10000, "chunk_robot_count": 8, "batch_concurrency": 8, "target_halfwidth_pp": 0.5, "max_chunks": 120 },
        "7": { "chunk_spin_times": 10000, "chunk_robot_count": 8, "batch_concurrency": 8, "target_halfwidth_pp": 0.5, "max_chunks": 120 }
    }
}
```

`_load_settings` must validate each numeric field with the same pattern used at app.py:930-958: `int(v) if isinstance(v, (int,str)) else default` with explicit range clamping (per RISK-5, 03:RISK-5). All 20 per-mode fields + 6 top-level sweep fields need explicit validation blocks.

### Restart recovery

`AutoInspectManager.__init__` calls `_restore_on_startup()`:

1. Query `auto_inspect_sweeps WHERE status IN ('scanning','sampling','generating')`.
2. For each found row: reset `auto_inspect_items WHERE status='running'` back to `status='pending'` (same pattern as `StateStore._recover_fleet_refresh`, app.py:2132).
3. Set `self._pending_resume_sweep_id = sweep_id`.
4. `create_app` reads this and spawns `auto_inspect_mgr.resume_sweep(sweep_id)` in a daemon thread (same pattern as fleet_refresh recovery at app.py:11591-11598).

The `scanning` phase is NOT resumed — it is re-run from scratch on resume. This is safe because scanning is read-only (no side effects). Items that were already `completed` before the crash remain `completed` (they are not reset). Only `running` items are reset to `pending`.

---

## §5 Failure-Handling State Machine

All 9 operator-stated failure modes. Every terminal status is an explicit named string (per `feedback_invariant_with_fallback_hides_drift.md` — no silent `_other` bucket). Every failure is persisted to `auto_inspect_items.terminal_reason` and `auto_inspect_events` (per `feedback_no_silent_swallow.md`).

---

### (a) Network error

| Property | Value |
|---|---|
| Trigger | `RunManager.start_run` raises an exception, or the subprocess exits non-zero with a network-shaped error message, or the poll timeout fires with `error_message` containing "connection refused" / "timeout". |
| Cell terminal status | `failed` |
| `terminal_reason` | `"网络错误: {error_message[:200]}"` |
| Retry | `attempt_count < 2` → re-queue as `pending`. Third failure → permanent `failed`. |
| Operator UI | Row shows red dot, reason string. Aggregate counter `other_failed` increments. |
| Persisted | Written to `auto_inspect_items` + `auto_inspect_events`. |
| Note | User requirement (5a) says loopback, won't happen — but the spec still handles it to avoid silent failure. |

---

### (b) Numerical non-convergence

| Property | Value |
|---|---|
| Trigger | Run completes (exit 0, summary.json exists) but `achieved_halfwidth_pp > target_halfwidth_pp` after consuming `max_chunks` chunks (i.e. `stop_reason = "max_chunks"` in the summary). |
| Cell terminal status | `convergence_timeout` |
| `terminal_reason` | `"未收敛: {total_spins}次spin预算耗尽, CI={achieved_halfwidth_pp:.3f}pp > 目标{target_halfwidth_pp:.3f}pp"` |
| Retry | No retry. The spin budget was the agreed ceiling. |
| Operator UI | Yellow dot. Reason string. The cell IS enqueued for generate (partial data is better than no report). |
| Report | Generated with a "未收敛" annotation in the summary (the analyzer's stop_reason already carries this; the report renderer reads it). |
| Persisted | `auto_inspect_items.status = 'convergence_timeout'`, terminal_reason, total_spins, achieved_halfwidth_pp. |

---

### (c) Structural BCM / M250-class non-convergence

| Property | Value |
|---|---|
| Trigger | `cell_class == 'bcm_hard'` at queue build time. For M250/M260/M264/M268: these machines are known to have 70-100% of win in an unattributed bucket regardless of spin count. For M99: open dedup bug. Per taxonomy 02:§7 Tier 1 and the Taxonomist's explicit note "no spin budget fixes — give up immediately." |
| Cell terminal status | `structural_skip` |
| `terminal_reason` | `"结构性问题需人工审查: {machine} (BCM anchor gap / open dedup bug)"` |
| Retry | No retry, no sampling attempted. |
| Operator UI | Grey/orange dot labeled "需人工". No run spawned, no rawdata written. |
| Generate | NOT enqueued. No point generating a report that is known to be structurally wrong. Exception: M274 (BCM baseline regression tripwire) is NOT structural_skip — it is processed with full spin budget and the result verified against the known-good baseline. M279 is also NOT structural_skip — it converges with enough spins (02:§7: "4 iterations" means it is hard, not permanently broken). |
| Persisted | `auto_inspect_items.status = 'structural_skip'`, terminal_reason. No run_id. |
| Note | M274 exception: `cell_class = 'bcm_hard'` but `structural_skip_override = False` because it is the regression tripwire. Implemented as a hardcoded exception in the cell-class assignment: `if machine == "M274": class = 'bcm_hard_monitored'` and the sweep processes it normally. |

---

### (d) Per-cell wall-time cap

| Property | Value |
|---|---|
| Trigger | `time.monotonic() - item_started_at > wall_time_cap_per_cell_s` (default 7200s = 2 hours). The poll loop checks this condition between polls. |
| Cell terminal status | `wall_time_exceeded` |
| `terminal_reason` | `"超过单机台时间上限 {wall_time_cap_per_cell_s}s"` |
| Action | Write `.stop` flag to `state/console/progress/{run_id}.stop` (same pattern as BatchRunManager cancel, app.py:8419). The analyzer subprocess exits on next chunk boundary. Wait up to 30s for clean exit, then tree-kill. |
| Retry | No retry. |
| Operator UI | Yellow dot. If rawdata was partially written, the cell IS enqueued for generate (partial data). |
| Persisted | `auto_inspect_items.status = 'wall_time_exceeded'`, terminal_reason, total_spins (whatever was written). |

---

### (e) Consecutive chunk failure cap

| Property | Value |
|---|---|
| Trigger | `RunManager._watch_run` reports `status='failed'` for a run (exit non-zero or incomplete summary). The sweep tracks `consecutive_failure_count` globally (across all cells, not per-cell). When `consecutive_failure_count >= max_consecutive_failures` (default 3), stop launching new items. |
| Cell terminal status | For the triggering item: `failed`. For items not yet started when the cap fires: their status changes from `pending` to `consecutive_failures`. |
| `terminal_reason` | `"连续{N}次失败后暂停; 触发机台: {last_failed_machine}"` |
| Retry | The sweep pauses (does not cancel — in-flight items drain). Operator can resume after investigating. |
| Operator UI | Warning banner: "连续{N}次失败，巡检已暂停". Resume button available. |
| Persisted | `auto_inspect_sweeps.consecutive_fail` counter. All pending items marked `consecutive_failures`. |

---

### (f) Whole-fleet abort

| Property | Value |
|---|---|
| Trigger | `total_failed_or_skipped_cells > fleet_abort_failure_threshold` (default 50). This is a percentage-of-total-cells threshold evaluated periodically. |
| Cell terminal status | In-flight: allowed to drain. Remaining pending: `fleet_aborted`. |
| `terminal_reason` | `"机群失败率过高({N}/{total}), 巡检终止"` |
| Action | Equivalent to cancel. Sweep status → `failed`. |
| Operator UI | Error banner. History row shows red status. |
| Persisted | `auto_inspect_sweeps.status = 'failed'`. |

---

### (g) Yield to manual operator action (cell-lock conflict)

| Property | Value |
|---|---|
| Trigger | `registry.try_acquire_cell(SAMPLING)` returns False AND `elapsed > CELL_BUSY_TIMEOUT_S` (default 1800s = 30 minutes). During the 30-minute window, the item is in status `pending` (not `running`) with a note that it is waiting for the lock. |
| Cell terminal status | `deferred_lock_conflict` |
| `terminal_reason` | `"单元格被占用超过30分钟, 跳过; 已存在的采样: {active_run_id}"` |
| Retry | NOT retried in the same sweep. Appears as a deferred item in next scheduled sweep. |
| Operator UI | Grey dot, reason string. The operator can see which run holds the lock. |
| Persisted | `auto_inspect_items.status = 'deferred_lock_conflict'`. |

---

### (h) Resume across console restart

| Property | Value |
|---|---|
| Trigger | Console process exits while sweep is in `sampling` or `generating` phase. |
| Recovery | On `__init__`: `_restore_on_startup()` resets `running` items to `pending`. Sweep resumes from the next `pending` item in queue_position order. Completed items are not re-processed. |
| Cell terminal status | No new terminal status — recovery is transparent. |
| Operator UI | After restart, `GET /api/auto-inspect/status` shows `has_resumable: true`. Resume button visible. |
| Interaction with A2 | `_is_cell_owned_by_active_queue` now checks `auto_inspect_items` (§4 extension). A2 skips spawning orphan runs for cells owned by the sweep's queue. |

---

### (i) md5 mid-sweep drift

| Property | Value |
|---|---|
| Trigger | Upstream pushes a new machine version during an active sweep. Detected when `_get_machine_md5(machine, mc, mode)` returns a different value than what was snapshotted at sweep-start time (stored in `settings_snapshot_json`). Check happens at the start of each item's sampling step, before RunManager.start_run. |
| Cell terminal status | `md5_mid_sweep_drift` |
| `terminal_reason` | `"巡检中上游md5变更: cfg {old_cfg[:8]}..→{new_cfg[:8]}.. ; 跳过本次, 下次巡检重新评估"` |
| Action | Do NOT sample. The cell's stale status will be re-evaluated on the next sweep with the updated md5. |
| Operator UI | Yellow dot, reason string. A banner informs the operator that md5 changed mid-sweep and some cells were skipped. |
| Persisted | `auto_inspect_items.status = 'md5_mid_sweep_drift'`. |
| Note | This does NOT trigger a new sweep. The sweep continues for other cells. The drifted cells get a fresh evaluation next time `start_sweep` is called. |

---

## §6 Defaults

All 20 per-mode values (4 modes × 5 fields) plus 6 sweep-level settings.

### Rationale basis

The `_LOOPBACK_HARDCODED_TUNING` reference gives `chunk_robot_count: 2, batch_concurrency: 16` for loopback. The existing `FleetRefreshManager` hardcoded tuning (01:§8) gives `chunk_spin_times: 1000, chunk_robot_count: 8, batch_concurrency: 8, max_chunks: 120, target_halfwidth_pp: 0.5`. The operator's BatchRunRequest defaults (01:§8) give `chunk_spin_times: 10000, chunk_robot_count: 8, batch_concurrency: 8, max_chunks: 120`. The loopback throughput is ~3,700 spins/second on a fresh connection (from `reference_sampling_api.md`).

The sweep uses the BatchRunRequest defaults (not the FleetRefreshManager hardcoded values) because FleetRefresh's `chunk_spin_times=1000` was intentionally small for a "refresh" pass, not for reaching CI targets. For the auto-inspect sweep, we want to actually achieve CI targets.

### Per-mode defaults table

| Field | Mode 1 | Mode 2 | Mode 5 | Mode 7 | Rationale |
|---|---|---|---|---|---|
| chunk_spin_times | 10,000 | 10,000 | 10,000 | 10,000 | Matches BatchRunRequest default (01:§8). Gives ~2.7s per chunk at 3.7k/s loopback. |
| chunk_robot_count | 8 | 8 | 8 | 8 | Matches BatchRunRequest default. `_LOOPBACK_HARDCODED_TUNING` says 2 for loopback but that tuning is not yet authoritative for the full fleet. |
| batch_concurrency | 8 | 8 | 8 | 8 | Matches BatchRunRequest default. |
| target_halfwidth_pp | 0.5 | 0.5 | 0.5 | 0.5 | Matches BatchRunRequest default and FleetRefreshManager hardcoded value (01:§8). At ~3.7k spins/s and 10k/chunk, roughly 200 chunks = 2M spins typically needed for 0.5 pp; max_chunks=120 means some cells may not reach this — acceptable. |
| max_chunks | 120 | 120 | 120 | 120 | Matches BatchRunRequest default and FleetRefreshManager hardcoded value. |

All four modes start identical because the operator does not yet have empirical data to differentiate mode-specific budgets. The per-mode form exists specifically so the operator can tune after observing actual convergence behavior by mode.

### Sweep-level defaults

| Setting | Default | Rationale |
|---|---|---|
| `sweep_concurrency` | 3 | Matches `ConcurrencyLimiter` background slot count (n_slots=5, foreground_reserve=2 → 3 background). Setting to 3 ensures the sweep can saturate background capacity without starving foreground ops. |
| `wall_time_cap_per_cell_s` | 7200 | 2 hours. Long enough for any mode at max_chunks=120 with chunk_spin_times=10000. At 3.7k spins/s, 120 × 10000 = 1.2M spins ≈ 5.4 minutes. The 2-hour cap is extremely generous and only fires for pathological cases. |
| `max_consecutive_failures` | 3 | Conservative. Three consecutive failures suggests a systemic issue (network down, simulator crashed) rather than per-machine anomalies. |
| `fleet_abort_failure_threshold` | 50 | Out of 1,688 cells, 50 failures (3%) before aborting. Aggressive enough to stop a runaway sweep. |
| `binary_group_large_cap` | 2 | For M273 (86 machines, 344 cells): at most 2 concurrent samples of machines sharing the c2a4e3be binary. Combined with sweep_concurrency=3, the third background slot may be used by a non-M273 machine simultaneously. |
| `skip_fresh_cells` | true | Default true. No reason to re-sample a cell where `md5_status == 'match'` and CI is already met. |

---

## §7 Phase Plan

### Phase 1 — Foundation (no user-visible change)

**Deliverables:**
- `auto_inspect_manager.py`: `AutoInspectManager` class skeleton with `__init__`, `_restore_on_startup`, empty `start_sweep` / `cancel` / `get_status` / `list_history` stubs.
- `StateStore._init_db`: add the three new tables (`auto_inspect_sweeps`, `auto_inspect_items`, `auto_inspect_events`) using `CREATE TABLE IF NOT EXISTS`. Idempotent. No migration needed (single-server SQLite).
- `_is_cell_owned_by_active_queue`: add fourth branch for `auto_inspect_items` (5-line SQL addition at app.py:6085-6141).
- `_load_settings` / `PUT /api/settings`: add `auto_sweep` key validation with full type-check for all 26 sub-keys.
- `create_app`: construct `auto_inspect_mgr` with injected paths; call `_restore_on_startup`.
- Unit tests: (a) `_is_cell_owned_by_active_queue` with sweep-owned cell returns non-None; (b) `_load_settings` with mangled `auto_sweep` values returns correct defaults; (c) `_restore_on_startup` resets `running` items to `pending`.

**No new API endpoints, no frontend changes.**

**Rollback:** Drop three tables (no-op schema additions to SQLite). Remove the fourth branch from `_is_cell_owned_by_active_queue`. Remove `auto_sweep` from `_load_settings`.

---

### Phase 2 — Cell discovery + sweep state machine (backend-only)

**Deliverables:**
- `start_sweep`: full scanning phase implementation (md5 refresh + `_build_machines_summary` + `check_rawdata_status` per cell + needs-sample predicate + cell-class assignment + queue-position ordering).
- Sweep threading model: `sweep_concurrency` worker threads + binary-group semaphore dict.
- Per-item sampling flow: `_get_machine_md5(machine, mc, mode)` — ALWAYS with explicit mode — + `try_acquire_cell(SAMPLING)` yield-retry loop + `RunManager.start_run` + poll + all 9 failure-mode routing.
- `cancel`: sets cancel flag; drains in-flight items.
- `GET /api/auto-inspect/status`: returns aggregate + paginated item list.
- `GET /api/auto-inspect/preview`: dry-run scanning phase, returns cell breakdown without writing to DB.
- `POST /api/auto-inspect/start`, `DELETE /api/auto-inspect`, `POST /api/auto-inspect/resume`.
- Integration test: inject `create_app(rawdata_root=tmpdir)`, POST start, verify item rows written; verify no module-global `RAWDATA_ROOT` read (grep the new manager file for the string `RAWDATA_ROOT` — must be zero occurrences).

**Rollback:** Remove three API endpoints. The schema additions from Phase 1 remain.

---

### Phase 3 — Generate phase + failure-mode surface (backend complete)

**Deliverables:**
- Generate phase: after all sampling items drain, call `batch_gen_mgr.start(items)` for cells with `status in ('completed', 'convergence_timeout')`. Poll until done. Store `generate_run_id` per item.
- Failure modes (b) through (i): full implementation of terminal status routing (§5). Each failure mode covered by at least one pytest: `inject_stop_reason("max_chunks") -> assert status='convergence_timeout'`, `cell_class='bcm_hard' -> assert status='structural_skip'`, etc.
- `auto_inspect_events` writer: log phase transitions and per-cell events.
- `GET /api/auto-inspect/status` extended: include generate-phase progress.
- `list_history` endpoint: `GET /api/auto-inspect/history?limit=10`.
- Subprocess persistence test (per `feedback_no_silent_swallow.md`): trigger a post-hook failure in the generate step and assert it is written to `auto_inspect_events` with `event_type='error'`.

**Rollback:** Remove generate-phase code path. Sampling still works from Phase 2.

---

### Phase 4 — Frontend tab + settings form (user-visible)

**Deliverables:**
- `index.html`: third tab button + `<section id="tab-inspect">` with two-column layout (settings panel + status panel).
- `app.js`:
  - `switchTab("inspect")` case in `boot()`.
  - Per-mode granularity form: 4 rows × 5 fields, wired to `PUT /api/settings`.
  - "Preview Needs-Sample" button: calls `GET /api/auto-inspect/preview`, renders tier breakdown.
  - "Start Sweep Now" button: calls `POST /api/auto-inspect/start`, switches to status view.
  - Status panel: 5-second poll of `GET /api/auto-inspect/status`, progress bar, aggregate counts.
  - Per-cell drill-down: paginated table, clickable rows opening existing debug panel.
  - Cancel button + "Cancelling..." state.
  - Resume button when `has_resumable: true`.
- Frontend verification: `node --check`, `preview_start`, visual parity check (per `feedback_frontend_verify_before_commit.md`). Specifically: per-cell status rows must use existing `fInt` / `fRate` / `fmtMult` helpers, not raw `<td>` strings; icon map must include all terminal status strings from §5.
- No new i18n keys that duplicate existing ones; grep sibling renderers for reusable formatters first (per `feedback_no_parallel_panel_impl.md`).

**Rollback:** Remove the tab and section from `index.html`. Remove the inspect-specific JS blocks. Backend remains.

---

### Phase 5 — Cron trigger + production hardening

**Deliverables:**
- Cron scheduler: a lightweight `threading.Timer`-based scheduler that reads `auto_sweep.schedule_cron`, parses it, and calls `start_sweep(trigger="cron")` at the scheduled time. No external dependency (Python stdlib `datetime` arithmetic). If `auto_sweep.enabled = false`, the timer fires but immediately returns without starting a sweep. This prevents the cron from needing to be disabled separately from the `enabled` flag.
- On/off toggle in the UI: writes `auto_sweep.enabled` via `PUT /api/settings`. The scheduled sweep checks this flag at fire-time.
- M273 binary-group cap telemetry: `binary_group_caps` dict in `GET /api/auto-inspect/status` (already in §2 status schema; wired here).
- `M274` regression tripwire alert: after M274's sweep item completes, compare `achieved_halfwidth_pp` against the stored baseline in `reports/M274/mode_1/latest.json`. If RTP differs by > 2 pp from baseline, emit an `auto_inspect_events` row with `event_type='regression_alert'` and surface it in the UI as a warning banner.
- Load test: a test that creates 50 fake cells in `auto_inspect_items`, runs the sweep against stub `RunManager`, verifies all 9 failure mode paths are reached, verifies binary-group cap is enforced (M273-class stub: verify no more than `large_cap` concurrent runs in the binary group).

**Rollback:** Remove the cron scheduler. The manual trigger from Phase 4 remains.

---

## §8 Alternatives Considered and Rejected

### §1 Decision alternatives

**Option A (BatchRunManager wrapper) rejected because:**
- `BatchRunManager._run_batch` launches all threads simultaneously (01:§2, `for each item: t.start(); t.join()`). Filtering to only stale cells still launches all threads at once, with a semaphore cap being the only throttle. The per-codeSummaryMd5 binary-group cap (required for M273's 344 cells, 02:§8) cannot be implemented as an outer semaphore on BatchRunManager without patching its internals.
- The 9 failure modes cannot be expressed cleanly in BatchRunManager's `completed / failed / rate_limited / attached` vocabulary.
- Sweep batches are indistinguishable from operator batches in the history panel.

**Option B (FleetRefreshManager extended) rejected because:**
- The 409 single-instance guard (`get_running_queue_id()` at app.py:11621) means auto-inspect cannot coexist with a manually triggered fleet refresh. For a cron-scheduled sweep (user requirement 6), this is a blocking limitation.
- The serial model (one item at a time, fleet_refresh.py:run_queue) means sweep_concurrency > 1 requires a threading refactor of an existing production manager, a regression surface.
- `_fleet_batch_item_runner` is a closure in `create_app`, not a class method, making parameterization awkward.

### §3 Dispatch decision alternatives

**Alternative: delegate sampling through BatchRunManager.start_batch (rejected)**

Instead of calling `RunManager.start_run` directly, the sweep could call `BatchRunManager.start_batch` with a per-cell BatchRunRequest. This would get the disk-pressure loop, md5-filter, and pending_batch_configs anchor for free.

Rejected because: (a) `start_batch` acquires SAMPLING via the registry and the sweep's outer sweep-item loop would need to avoid pre-acquiring SAMPLING itself, creating a two-level acquisition chain that is harder to audit for leak-safety; (b) `start_batch` does not support a "yield-and-retry" model for cells that are already SAMPLING — it marks them as `attached` or `failed` on first try (01:§2 D12 logic, app.py:4879); (c) the resulting batch rows are visible in `GET /api/batches` as ordinary sampling batches, hiding the sweep relationship.

**Alternative: make AutoInspectManager a sub-class of FleetRefreshManager (rejected)**

Adding `class AutoInspectManager(FleetRefreshManager)` and overriding `_start_batch_item_fn` to be parameterized. This shares the SQLite table structure.

Rejected because: FleetRefreshManager's SQLite schema (`fleet_refresh_queue`, `fleet_refresh_items`) has no columns for `cell_class`, `terminal_reason`, `generate_run_id`, or `achieved_halfwidth_pp` — all of which are needed for §5 failure-mode surface. Altering the existing tables risks breaking FleetRefreshManager's own recovery path. Separate tables with a new manager class are cleaner.

---

## §9 Open Questions for Wave 3

**OQ-A: M274 regression tripwire threshold.** The proposal says "alert if RTP differs > 2 pp from baseline." What is the baseline? M274 mode 1's current `latest.json` RTP at time of Phase 5 implementation. Is 2 pp the right threshold? The critic / validator should confirm whether this threshold is tight enough to catch regressions without false-alarming on sampling variance.

**OQ-B: Generate phase timing.** The proposal sequences generate AFTER all sampling items drain. This means no report is generated until the entire sampling sweep is done. For a 1,688-cell fleet, this could mean operators see no new reports for hours. Alternative: generate per-cell as soon as that cell's sampling completes. The downside is more complex orchestration (sampling and generate phases interleaved per cell). The validator should assess whether the sequential model is acceptable or whether per-cell-immediate generation is needed.

**OQ-C: `skip_fresh_cells` scope — what counts as "fresh enough" for CI?** The current predicate is `md5_status == 'match' AND ci_halfwidth_pp <= target_halfwidth_pp`. But `ci_halfwidth_pp` in `_build_machines_summary` reflects the BEST existing report version, which may be months old. If the operator changes `target_halfwidth_pp` between sweeps, existing reports that previously passed may now fail the new threshold. The validator should confirm whether this edge case needs an explicit "always re-evaluate CI against current settings" sub-check.

**OQ-D: M278/M280/M281 uncharted BCM classification.** The proposal puts them in `bcm_uncharted`, processes them in tier 2 (same as bcm_moderate), and does NOT apply `structural_skip`. If these machines turn out to have the same BCM anchor gap as M250/M260/M264/M268, the sweep will run to max_chunks and produce misleading reports. The critic should assess whether uncharted BCM machines should be flagged earlier or deferred until they are classified.

**OQ-E: `sweep_concurrency=3` vs. ConcurrencyLimiter slots.** With `sweep_concurrency=3` and `ConcurrencyLimiter` having 3 background slots, the sweep saturates all background slots — leaving zero capacity for FleetRefreshManager to make progress if both run simultaneously. The validator should confirm whether FleetRefreshManager should be blocked (409) when the sweep is running, or whether `sweep_concurrency` should default to 2 to leave one slot for FleetRefreshManager.

**OQ-F: Per-mode generate vs. unified generate.** The sweep's generate phase calls `batch_gen_mgr.start(items)` for all completed sampling items at once. `BatchGenerateManager.start` discovers chunks via `rawdata/{machine}/mode_{mode}/`, which will contain chunks from ALL modes that have ever been sampled — not just the modes swept in this sweep run. If the operator runs a mode-1-only sweep, the generate phase should only regenerate mode-1 reports. The validator should confirm that the `items` list is correctly filtered to only the modes included in this sweep.

**OQ-G: cron expression parsing.** The proposal says "Python stdlib datetime arithmetic, no external dependency." Standard Python has no cron parser in stdlib. Options: (a) restrict `schedule_cron` to a simpler format (`HH:MM` daily, `*/N hours`); (b) add a dependency on `croniter` or equivalent. The critic should decide the scope.

---

## §10 Out of Scope

**1. Per-machine (not per-mode) granularity overrides.** The requirement says "settings applied uniformly across all machines for that mode." Per-machine overrides (e.g., M250 gets its own max_chunks) are deliberately excluded. The failure-mode routing in §5 handles machine-specific behavior through `cell_class` classification and terminal status, not through per-machine parameter tables. Adding per-machine overrides would require a 422-row config table and a UI to manage it — a separate feature.

**2. Automatic upstream md5 polling on a schedule.** The sweep refreshes machines.json once at sweep-start time. It does not implement a continuous background poller that triggers a sweep whenever machines.json changes. The `_do_refresh_machines_md5` + cron sweep combination achieves the desired effect with two simpler components.

**3. Per-variant grouping in the UI.** The taxonomy (02:§3 Axis A) distinguishes underlying parents from their 166 variants. The sweep UI shows all 422 machines as individual rows. A "parent + variants" tree view with collapsed variant rows is excluded from this proposal — it adds UI complexity without changing the sweep logic.

**4. Automatic BCM anchor-gap repair.** M250/M260/M264/M268 are flagged `structural_skip` in this proposal. Fixing the BCM cycle anchor rule for these machines is an analyzer change, not an infrastructure change. That work is tracked in the hard-case machine roster in `09_architecture_as_built.md §3`. The auto-inspect sweep will automatically re-sweep these machines once the analyzer fix ships (their cell_class will change from `bcm_hard` to `easy` or `bcm_moderate` once the anchor rule is implemented).

**5. Multi-server (multi-endpoint) sweep.** The current console is single-Windows-server, loopback (per `project_internal_deploy_intent.md`). The sweep uses `_resolve_active_server_id` to find the single active server. Multi-server fan-out (sweeping different machines against different upstream endpoints) is out of scope.

**6. Sweep result export / CSV.** The existing `GET /api/fleet/export-csv` (app.py:10941) exports fleet status. Extending that export to include auto-inspect sweep history is out of scope; operators can drill down via the UI.
