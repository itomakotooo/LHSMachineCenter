# Auto-Inspect Sweep — Coupling Audit

**Date**: 2026-05-26
**Auditor**: arch-coupling-auditor
**Scope**: `src/web_console/backend/app.py` (11,731 lines), `src/web_console/backend/fleet_refresh.py`, `src/web_console/backend/cell_lock_registry.py`, `src/web_console/backend/rate_limiter.py`, `fresh_slotlab/machine_md5.py`, `src/web_console/frontend/app.js` (8,638 lines), `src/web_console/frontend/index.html`

Ground-truth callers verified by grep across all production Python and JS files. No assumptions.

---

## Reuse — code we MUST call into

These are existing symbols the sweep feature must invoke correctly. Calling them wrong is the primary regression surface.

---

### `check_rawdata_status(machine, mode, rawdata_root, machines_config)` — app.py:721

**What it does**: Read-only scan of `rawdata/<machine>/mode_<N>/`. Returns `{usable_chunks, mismatch_chunks, total_size_mb, upstream_config_md5, ...}`. Hot path hits `rawdata/_index.json`; cold path globs `chunk_*.json` and reads `_chunks.json` sidecar.

**Sweep's need**: The sweep must decide "does this cell need sampling?" by comparing `usable_chunks` count and existing CI against a target threshold. This is the single authoritative oracle.

**Touch points**: Called at `BatchRunManager.start_batch` (app.py:4369) per item, at `GET /api/batch-run` status (app.py:7791), and inside `_fleet_batch_item_runner` indirectly via RunManager.

**Breakage risk**: If the sweep calls `check_rawdata_status` with a stale `machines_config` path (e.g., module-global `MACHINES_CONFIG` instead of the injected `mc`), it classifies chunks against the wrong upstream md5 — the same virtual-console bug fixed in memory `feedback_subprocess_import_suicide_and_module_globals.md`. Must always pass the injected `mc` from `create_app`.

---

### `_get_machine_md5(machine, machines_config, mode)` — app.py:598

**What it does**: Returns `(config_md5, code_md5)` for a `(machine, mode)` pair by reading `machines.json`. Handles both real-machine flat schema (`configSummaryMd5`/`codeSummaryMd5`) and virtual-machine per-mode `modesMd5` block. Delegates to `fresh_slotlab.machine_md5.lookup_machine_md5` (machine_md5.py:51) for the real-machine path.

**Sweep's need**: Every work unit must compute the current upstream md5 so the sweep can compare it to the report's stored `config_md5`/`code_md5` to determine staleness. This is the identical lookup `BatchRunManager._run_batch._run_one` performs at app.py:4853.

**Downstream fan-out**: Called from at least 9 sites in app.py (lines 446, 598, 768, 1302, 3746, 4853, 5014, 9495, 10664). Any sweep that introduces a parallel call path must pass `mc` consistently.

**Breakage risk**: Passing `mode=None` returns the flat-schema md5, which is wrong for virtual machines. The sweep must always pass `mode` explicitly.

---

### `_build_machines_summary(reports_root, _cs)` — app.py:3639

**What it does**: Scans `reports/<machine>/mode_<N>/versions/*/player_impact_summary.json`, picks the best-CI report per (machine, mode), and returns `{md5_status: "match"|"outdated"|"untagged"|"unverifiable", ci_halfwidth_pp, ...}`. Results are mtime-fingerprinted and cached in `AppCacheState.machines_summary_cache`.

**Sweep's need**: The "which cells need a new report?" predicate. A cell is a sweep candidate when `md5_status == "outdated"` (rawdata is stale — needs resampling) or when the cell has no report at all (the directory `reports/<machine>/mode_<N>/versions/` is empty or missing). No separate "no-report check" is needed: absence from `_build_machines_summary` result for a (machine, mode) key that is present in `machines.json` is the "no report" signal.

**Touch points**: app.py:7521 (`GET /api/machines/summary`), app.py:7044 (startup prewarm thread), app.py:10946 (post-import rebuild).

**Breakage risk**: The cache is `AppCacheState`-scoped (per `create_app` instance). A sweep that calls this in a background thread sees the same cache as the foreground. The fingerprint is based on `reports/` mtime-sum, not SQLite. If the sweep submits a batch-generate and then immediately polls this for completion, the cache will not have updated yet — the sweep must call `_build_machines_summary` with `_cs=app_cache` (the per-instance cache passed in `create_app`), not the module-level `_MODULE_CACHE_STATE` fallback.

---

### `BatchRunManager.start_batch(req, reports_root)` — app.py:4344

**What it does**: Creates a new sampling batch. Accepts `BatchRunRequest` with a list of `BatchRunItem(machine, mode, chunk_spin_times)`. Acquires SAMPLING locks per item via `CellLockRegistry`. Drives sampling via `RunManager.start_run`. Persists state to SQLite `batches` table with `kind='sampling'` (L2).

**Sweep's need**: If the sweep creates sampling work units via this path (Option A in the designer question), it gets: disk-pressure loop, md5-filter, resume-from-cache, per-item CellLockRegistry coordination, and the A1 resume button for free.

**BatchRunRequest schema** (app.py:1805): `items`, `concurrency`, `server_id`, `chunk_spin_times`, `chunk_robot_count`, `batch_concurrency`, `max_chunks`, `timeout`, `target_halfwidth_pp`, `sampling_strategy`, `skip_md5_refresh`.

**Breakage risk**: `start_batch` calls `_detect_machine_cycle` (app.py:1599) per item to infer `chunk_spin_times`. If `chunk_spin_times=None` is passed in `BatchRunItem`, the cycle-detection path fires; if a non-None value is passed, it bypasses cycle detection. The sweep should pass `chunk_spin_times=None` to preserve the existing per-machine heuristic, unless the operator override specifies a per-mode value.

---

### `BatchGenerateManager` + `_prepare_batch_gen_item` — app.py:3788, 9429

**What it does**: Background batch driver for `POST /api/rawdata/batch-generate-report`. Acquires GENERATING per item via CellLockRegistry. Runs analyzer subprocess in ProcessPoolExecutor. Persists to SQLite `batches` table with `kind='generate'` (L3).

**Sweep's need**: After sampling completes, the sweep needs to generate reports. It can either reuse `batch_gen_mgr` (by calling `POST /api/rawdata/batch-generate-report`) or trigger the per-cell `POST /api/rawdata/{machine}/generate-report?async=true`. The batch path is better for large-scale sweeps because it uses the ProcessPoolExecutor pool without spawning a thread per machine.

**Touch points**: `batch_gen_mgr` is assigned at app.py:9673 and exposed as a closure captured by the batch-generate-report routes.

**Breakage risk**: `_prepare_batch_gen_item` raises HTTPException (404) when `no rawdata for {machine} mode {mode}` or `no usable chunks`. If the sweep submits a generate batch for a cell that just had sampling started (but not yet completed), `_prepare_batch_gen_item` will find 0 usable chunks and fail the item. The sweep must wait for sampling to reach `status=completed` before queuing generate work for that cell.

---

### `FleetRefreshManager.start_queue(machines)` — fleet_refresh.py:255

**What it does**: Creates a SQLite-backed queue in `fleet_refresh_queue` + `fleet_refresh_items`. Spawns a daemon thread that processes items sequentially via `_start_batch_item_fn` (wired to `_fleet_batch_item_runner` in create_app). Uses `CellLockRegistry.try_acquire_cell(SAMPLING)` and `ConcurrencyLimiter.acquire("background")` per item.

**Sweep's need**: The sweep is architecturally very similar to FleetRefreshManager — sequential queue, per-item SAMPLING lock, background priority. The designer question is whether to extend this manager or build parallel to it.

**Key constraint**: `start_queue` enforces single-instance via `get_running_queue_id()` (app.py:11621). A sweep that creates its own parallel queue to FleetRefreshManager is not blocked by this check, but **both would compete for SAMPLING locks**.

**Wiring in create_app** (app.py:11591): `FleetRefreshManager` receives the shared `registry`, `limiter`, and `start_batch_item_fn=_fleet_batch_item_runner`. The runner hardcodes `chunk_spin_times=1000, chunk_robot_count=8, batch_concurrency=8, max_chunks=120, target_halfwidth_pp=0.5` (app.py:11543-11548). These are the fleet-refresh defaults — not user-tunable through any current settings.json key.

---

### `StateStore.upsert_batch` / `list_recent_batches` / `list_batches_by_status` — app.py:2268, 2381, 2349

**What it does**: The `batches` SQLite table (L2+L3) stores all batch state. Schema: `batch_id, status, created_at, finished_at, concurrency, params_json, items_json, events_json, reports_root, kind`. `kind` discriminates `'sampling'` vs `'generate'`.

**Sweep's need**: If the sweep creates new batches (sampling + generate), they land in this table. The `GET /api/batches` history panel (B1+B2) automatically surfaces them because it queries `list_recent_batches` with no kind filter. A sweep batch with `kind='sweep'` would need a new kind discriminator if the operator wants to filter it separately.

**Breakage risk**: If the sweep reuses `BatchRunManager.start_batch`, the resulting rows have `kind='sampling'` and appear in the B2 history panel indistinguishable from operator-initiated batches. The history panel's click handler routes to `/api/batch-run/{id}` for kind=sampling. A third kind value (`'sweep'`) would require adding it to `list_recent_batches`'s kind filter validation (app.py:8450) and to the frontend's `kindIcon`/`kindLabel` maps (app.js:8562, 8577).

---

### `_load_settings(settings_path)` — app.py:885

**What it does**: Reads `state/console/settings.json`. Known keys: `min_retention_spins`, `default_server`, `server_tuning`, `auto_resume_orphan_runs`. The function returns defaults for unknown keys — adding new keys to the JSON does not break existing reads, but existing code ignores them entirely.

**Sweep's need**: Per-mode granularity settings (`chunk_spin_times`, `chunk_robot_count`, `batch_concurrency`, `target_halfwidth_pp`, `max_chunks` per mode 1/2/5/7) must be persisted somewhere. `settings.json` is the operator-tunable, restart-durable store that fits this purpose.

**Breakage risk**: `_load_settings` does per-key type validation (app.py:930-958). Any new key the sweep adds will be silently ignored by existing callers unless a corresponding read path is added. This is safe but means the new keys must be explicitly wired into both `_load_settings` and `PUT /api/settings` (app.py:line ~10800).

---

### `CellLockRegistry.try_acquire_cell` / `release_cell` — cell_lock_registry.py:93, 167

**What it does**: Thread-safe per-(machine, mode) mutex. Enforces: INV-1 (SAMPLING+DELETING exclusive), INV-2 (GENERATING+DELETING exclusive), INV-3 (GENERATING blocks if `block_if_sampling_active=True`), INV-4 (at most one SAMPLING), INV-5 (at most one GENERATING).

**Sweep's need**: Every sampling work unit must acquire SAMPLING before starting. The registry is the single source of truth. The sweep cannot bypass it.

**Attach semantics** (app.py:4879-4907): If `try_acquire_cell` returns False for SAMPLING, BatchRunManager checks whether the existing SAMPLING has the same `(config_id, upstream_md5)`. If so, the item is marked `attached` and the caller polls the existing run_id. If not, the item is marked `failed` (different config). The sweep inherits these semantics if it uses BatchRunManager.

**Breakage risk**: The sweep must call `release_cell` in a `finally` block. Leaking a SAMPLING lock permanently blocks that cell for the process lifetime. Current code (FleetRefreshManager.run_queue:511) and BatchRunManager._run_one both have correct `finally` blocks.

---

### `ConcurrencyLimiter.acquire("background" | "foreground")` — rate_limiter.py:72

**What it does**: Global semaphore capped at `n_slots=5`. Background callers can only use `n_slots - foreground_reserve` (3 background slots when reserve=2). Background acquire polls with cancel flag; foreground acquire blocks up to `timeout=30s`.

**Sweep's need**: If the sweep runs as background (it should, per design — it is lower priority than operator-triggered runs), it must call `limiter.acquire("background", cancel_flag=...)`. This is what FleetRefreshManager.run_queue does (fleet_refresh.py:417).

**Breakage risk**: If the sweep uses `"foreground"` priority it competes with operator-initiated generate-report (which also uses foreground). If it uses `"background"` and 3 background slots are already consumed by FleetRefreshManager items, the sweep blocks until a slot is available. This is correct behavior but means sweep progress is throttled when FleetRefreshManager is active. The two are not de-conflicted by the limiter — they race for background slots.

---

## Coordinate — code with established interaction rules (just follow them)

These components have documented protocols. The sweep must follow them, not rewrite them.

---

### A2 + R1 — RunManager orphan-resume yielding to queue owners

**Rule** (app.py:6031-6053): On startup, `_recover_orphan_running_runs` calls `_is_cell_owned_by_active_queue(machine, mode)` for each orphan. If the cell is claimed by a `fleet_refresh_queue` row with `status IN ('pending', 'running')`, or by a `batches` row with matching `(machine, mode)` in the items list, A2 skips auto-resume and leaves the orphan marked `failed`. The queue's own resume path handles it.

**Sweep interaction**: If the sweep has its own queue table (Option C — new manager), `_is_cell_owned_by_active_queue` will not check it — it only scans `fleet_refresh_items` and `batches`. The sweep must either register its active cells in one of those tables, or add a check for its own table in `_is_cell_owned_by_active_queue` (app.py:6085-6141).

**If sweep reuses BatchRunManager** (Option A): The batch's items appear in the `batches` table. The check at app.py:6127-6138 scans `list_batches_by_status(("pending", "running"))` and checks `items_json` membership. The sweep batch is automatically covered.

**If sweep reuses FleetRefreshManager** (Option B): The queue appears in `fleet_refresh_items`. The check at app.py:6107-6120 queries that table directly. Covered.

**If sweep is a new manager** (Option C): Must add a third branch to `_is_cell_owned_by_active_queue`.

---

### L2 + L3 restart recovery — BatchRunManager and BatchGenerateManager both restore on `__init__`

**Rule** (app.py:4243, 3879): On startup, both managers call `list_batches_by_status(("pending", "running"), kind=...)` and force-mark non-terminal batches as `cancelled`. In-memory state is repopulated. A1 resume button picks up these cancelled batches.

**Sweep interaction**: If the sweep creates sampling+generate batches via these managers, restart recovery is automatic. If the sweep creates its own batch kind (e.g., `kind='sweep'`), it must add its own restore logic in `__init__` (or a new sweep manager's `__init__`).

---

### FleetRefreshManager single-instance enforcement

**Rule** (app.py:11621): `POST /api/fleet/refresh` returns 409 if `get_running_queue_id()` returns a non-null queue_id. The check only scans `fleet_refresh_queue WHERE status='running'`.

**Sweep interaction**: A sweep that creates new rows in `fleet_refresh_queue` competes with this check — if FleetRefresh is running, auto-inspect cannot start a new fleet queue. If the sweep has a separate table, it does not interfere with the 409 check. The designer must decide whether auto-inspect should be blocked by a running FleetRefresh or should coexist.

---

### md5 refresh before batch — async pre-batch refresh

**Rule** (app.py:7559-7579): `POST /api/batch-run` spawns a daemon thread to call `_do_refresh_machines_md5` before the batch begins. This is non-blocking — the batch starts with whatever md5 is in machines.json; the refresh lands concurrently. The sweep should follow the same pattern: call `_do_refresh_machines_md5(raise_on_error=False)` in a daemon thread before building the cell list, so that the md5 comparison uses fresh data.

**Risk if skipped**: The sweep uses stale machines.json md5s → classifies cells as "stale" or "fresh" based on old data → may sample unnecessarily or miss newly stale cells.

---

### `_detect_machine_cycle(machine, reports_root)` — app.py:1599

**Rule**: When `BatchRunItem.chunk_spin_times=None`, `start_batch` calls this to infer the chunk size from the best existing report. It returns `recommended_chunk_size` based on `cycle_peaks` from `player_impact_summary.json`.

**Sweep interaction**: The sweep should pass `chunk_spin_times=None` for all items unless the operator has set a per-mode override. This preserves the machine-specific heuristic that existing batch runs use.

---

## Compete — code that races us (new conflict surfaces)

These are scenarios where the sweep and existing code want the same resource simultaneously.

---

### SAMPLING lock: auto-sweep vs operator-initiated batch run

**Conflict**: Both create `BatchRunItem` entries that call `registry.try_acquire_cell(SAMPLING)`. INV-4 (at most one SAMPLING per cell) means only one wins. The other receives the attach-or-reject response.

**How the registry resolves it today**: `try_acquire_cell` returns False if SAMPLING is already held. BatchRunManager then checks `get_active_sampling_info` to decide attach (same config) vs reject (different config). The rejected item is marked `status='failed'`. The sweep batch item would be failed, not paused.

**Is that good enough for the sweep?** No. The sweep wants "yield and retry" semantics, not "fail permanently". Options:
  - The sweep could mark its items `status='skipped'` instead of `failed` and re-queue them after a delay, using the same `attempt_count < max_retries` loop that FleetRefreshManager uses for its items.
  - Alternatively, the sweep should run at a lower priority than operator batches: if the cell is SAMPLING and the sweep is the initiator, the sweep skips (not fails) and dequeues it.

**Current code with this "yield" pattern**: FleetRefreshManager.run_queue polls `try_acquire_cell` every 5s for up to 30 min (fleet_refresh.py:344-403). This is the proven pattern.

---

### GENERATING lock: auto-sweep's generate phase vs operator-triggered generate-report

**Conflict**: `POST /api/rawdata/{machine}/generate-report` (single-cell) uses `block_if_sampling_active=True` (app.py:8804-8806). The sweep's batch generate phase uses `_prepare_batch_gen_item_wrapper` (app.py:9538) which calls `try_acquire_cell(GENERATING)` without `block_if_sampling_active`.

**How the registry resolves it today**: INV-5 (at most one GENERATING). If the sweep holds GENERATING and the operator triggers single-cell generate-report, the operator's request gets a 409. The reverse is also true. The two paths are exclusive.

**Is that good enough?** Yes — the 409 is surfaced to the operator immediately. The sweep's batch-generate finalize_fn releases GENERATING after each item, so the window is bounded to one analyzer subprocess duration (~30-120s per item).

---

### Background ConcurrencyLimiter slots: auto-sweep vs FleetRefreshManager

**Conflict**: Both use `limiter.acquire("background")`. With `n_slots=5, foreground_reserve=2`, exactly 3 background slots are available. If FleetRefreshManager runs concurrently with the sweep's generate phase and both have items in flight, they fight over the same 3 slots.

**Current resolution**: First-come-first-served. No priority between background callers. A sweep with 393 pending items and a FleetRefresh with 393 pending items interleave. No starvation (each item eventually gets a slot) but throughput is halved.

**Impact**: If the sweep runs exclusively in the background (not blocking FleetRefresh), this is acceptable. But if the operator also triggers foreground sampling runs (which use `limiter.acquire("foreground")`), the foreground jobs are protected by the 2-slot reserve.

---

### `batches` table `kind` column: sweep needs a new kind value

**Conflict**: The B2 history panel (`GET /api/batches`) has a `kind` filter accepting only `'sampling'` or `'generate'` (app.py:8450). If the sweep uses a new `kind='sweep'`, the 400 guard at app.py:8451 rejects filter requests for it. The history panel's frontend `kindIcon` map (app.js:8562) has no entry for `'sweep'` — it would display as `·` (the fallback).

**Resolution needed**: Either (a) the sweep reuses `kind='sampling'` for its sampling phase and `kind='generate'` for its generate phase, making sweep batches visually identical to operator batches in the history panel; or (b) add `'sweep'` to the whitelist at app.py:8450 and to the frontend maps. Option (a) requires no code changes but loses sweep-specific filtering. Option (b) is a one-line backend + two-line frontend change.

---

### `_is_cell_owned_by_active_queue` blind spot for a new sweep manager

**Conflict** (see Coordinate section above): If the sweep is implemented as a third manager (Option C) with its own SQLite table, the R1 safety check at app.py:6085-6141 does not scan that table. On console restart, A2 would auto-resume orphan runs for cells that the sweep's recovery path should handle — creating duplicate sampling runs.

**Resolution needed**: Add a fourth branch to `_is_cell_owned_by_active_queue` that queries the sweep's table, OR ensure the sweep registers its active cells in one of the existing tables (`batches` or `fleet_refresh_items`).

---

## Risk register — top 5 most likely breakage points

**RISK-1: Wrong rawdata_root / machines_config path in sweep manager**
- **Mechanism**: If the sweep manager is constructed outside `create_app`'s injection chain, or if a new sweep-specific function calls `RAWDATA_ROOT` (module global) instead of the injected `rd_root`, virtual-console and multi-app-instance tests break. This is the exact bug class documented in `feedback_subprocess_import_suicide_and_module_globals.md` and fixed twice before.
- **Detection**: Any test that creates a `create_app(rawdata_root=tmpdir)` and then triggers a sweep — if rawdata is read from `RAWDATA_ROOT`, the test tree is bypassed and the real console's data is read.
- **Affected code**: Every new function that reads rawdata must accept `rawdata_root: Path` as a parameter and never fall back to the module global `RAWDATA_ROOT` in production paths.

**RISK-2: AppCacheState race — sweep triggers generate, then reads stale summary**
- **Mechanism**: `_build_machines_summary` returns cached data until the `reports/` mtime fingerprint changes (app.py:3649-3651). After `BatchGenerateManager` writes a new report, the fingerprint changes — but only after `_finalize_batch_gen_item` writes `index.json`/`latest.json` (app.py:9632-9633). If the sweep polls `_build_machines_summary` within the same process tick as `_finalize_batch_gen_item`, the fingerprint may or may not have updated. The sweep must add a deliberate delay or re-poll until `md5_status` changes to `'match'`.
- **Affected code**: Any sweep polling loop that uses `_build_machines_summary` to check completion.

**RISK-3: CellLockRegistry SAMPLING leak if sweep crashes mid-item**
- **Mechanism**: If a sweep work item acquires SAMPLING via `try_acquire_cell` but an unhandled exception exits the worker function before the `finally: release_cell` block, the lock is never released. The cell becomes permanently blocked for the process lifetime. All subsequent attempts to sample that cell (operator-initiated or sweep-initiated) fail with "another batch is sampling this machine+mode".
- **Prevention**: Every acquire-path must be in a try/finally. Review every new code path that calls `try_acquire_cell`.
- **Affected code**: New sweep manager's per-item runner.

**RISK-4: A2 spawns duplicate orphan run for sweep-owned cells (if Option C)**
- **Mechanism**: On console restart, `RunManager._recover_orphan_running_runs` scans all `status='running'` rows and calls `_is_cell_owned_by_active_queue` (app.py:6045). If the sweep has a new table not covered by that function's checks (app.py:6107-6140), A2 treats the cell as unowned and spawns a new resume run, racing the sweep's own restart-recovery. Two runs now sample the same cell simultaneously — the second to acquire SAMPLING is rejected, but the first may produce a report from partial (pre-crash) chunks.
- **Prevention**: Either use an existing table that `_is_cell_owned_by_active_queue` already checks, or add the sweep table check there.

**RISK-5: Per-mode settings bypass `_load_settings` validation → silent corruption**
- **Mechanism**: `_load_settings` only validates known keys (app.py:930-958). If the sweep adds new per-mode keys to settings.json but does not add the corresponding validation in `_load_settings`, a typo in the JSON (e.g., `"chunk_spin_times": "1000"` as string instead of int) silently returns the raw string. Downstream code that passes the value to `RunCreateRequest.chunk_spin_times` (which is typed `int`) would raise a Pydantic validation error, crashing the sweep item.
- **Prevention**: All new settings keys must have explicit int/float/bool type validation in `_load_settings`, with fallback to the default value on type mismatch, matching the pattern at app.py:930-958.

---

## Settings schema additions needed

The following keys are not present in the current `settings.json` / `_load_settings`. All are needed to satisfy the "operator-tunable per-mode granularity" requirement.

**New top-level key: `auto_sweep`** (dict)
Contains all sweep-specific settings so they are namespaced and do not conflict with existing flat keys.

```
"auto_sweep": {
    "enabled": bool,           // default false — sweep does not auto-start; operator triggers it
    "schedule_cron": str,      // default "" — empty = no scheduled auto-start; ISO cron if set
    "modes": {                 // per-mode granularity overrides
        "1": {
            "chunk_spin_times": int,          // default 10000 (matches RunCreateRequest default)
            "chunk_robot_count": int,         // default 8
            "batch_concurrency": int,         // default 8
            "target_halfwidth_pp": float,     // default 0.5
            "max_chunks": int                 // default 120
        },
        "2": { ... },
        "5": { ... },
        "7": { ... }
    },
    "sweep_concurrency": int,  // default 3 — parallel (machine,mode) items in the sweep batch
    "skip_fresh_cells": bool,  // default true — skip cells where md5_status=='match' AND ci meets target
    "sampling_priority": str   // default "background" — passed to ConcurrencyLimiter.acquire()
}
```

**Addition to existing `server_tuning` dict**: No change needed. The sweep uses per-server tuning already stored under `server_tuning[server_id]` for `chunk_robot_count`/`batch_concurrency` defaults. Per-mode overrides in `auto_sweep.modes` take precedence over server_tuning defaults when both are set.

**Validation location**: `_load_settings` at app.py:885. Must add a parse block for the `auto_sweep` dict, validating each sub-key's type and clamping to sane ranges (e.g., `max_chunks` in [1, 1000]).

**`PUT /api/settings`** (app.py:~line 10800): Must be extended to accept and persist the `auto_sweep` key. Existing implementation does a full-document overwrite (app.py: `_save_settings`), which is safe as long as the frontend sends the full document.

---

## API endpoints affected

### New endpoints (sweep feature needs these)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/auto-inspect/start` | Trigger a sweep. Body: `{server_id?, modes?, machines?}`. Builds cell list from `_build_machines_summary` + `check_rawdata_status`, creates a batch. |
| `GET` | `/api/auto-inspect/status` | Poll current sweep state (in-flight batch IDs, per-cell status). |
| `DELETE` | `/api/auto-inspect` | Cancel the running sweep. |

### Existing endpoints the sweep REUSES (no change to signature)

| Method | Path | Reuse path |
|--------|------|-----------|
| `POST` | `/api/batch-run` | Option A: sweep creates sampling batch via this endpoint. |
| `POST` | `/api/rawdata/batch-generate-report` | Option A: sweep creates generate batch via this endpoint. |
| `POST` | `/api/fleet/refresh` | Option B: sweep is implemented by extending FleetRefreshManager (changes internal wiring, not the API path). |
| `GET` | `/api/machines/summary` | Sweep reads cell freshness from `_build_machines_summary` (this endpoint). |
| `GET` | `/api/batches` | B2 history panel surfaces sweep batches if they land in the `batches` table. |
| `GET` | `/api/batch-run/{id}` | Frontend click-handler for history row (sampling kind). |
| `GET` | `/api/rawdata/batch-generate-report/{id}` | Frontend click-handler for history row (generate kind). |

### Existing endpoints affected by settings changes

| Method | Path | Change |
|--------|------|--------|
| `GET` | `/api/settings` | Must return the new `auto_sweep` key. |
| `PUT` | `/api/settings` | Must accept and persist `auto_sweep` key. |

---

## Open questions for designer

**OQ-1: Routing option — BatchRunManager (A), FleetRefreshManager (B), or new manager (C)?**

Quantified trade-offs:

- **Option A — BatchRunManager**: Sampling work units go through `start_batch`. Generate work units go through `batch_generate_report`. Two separate batch IDs per sweep. Gets A1 resume, L2+L3 persistence, and `_is_cell_owned_by_active_queue` coverage for free. The sweep is visible in the B2 history panel as ordinary sampling+generate batches. No new table. Operator has no way to filter "sweep batches" from "manual batches" in the history. **Adds coupling**: `start_batch` does not expose a "skip if already fresh" predicate — the sweep must pre-filter the cell list before calling it.

- **Option B — FleetRefreshManager extended**: Add sampling parameters and a post-sampling generate step to the existing fleet queue. One queue covers both phases. Existing `POST /api/fleet/refresh` body would need new fields (`include_generate: bool`, `per_mode_params: dict`). The single-instance 409 guard means the sweep and FleetRefresh cannot coexist. `_fleet_batch_item_runner` hardcodes params (app.py:11543-11548) — these must be parameterized. **R1 coverage is automatic** (fleet_refresh_items is already checked). Least new code but tightest coupling to FleetRefreshManager's sequential, single-instance model.

- **Option C — New manager**: Full decoupling. New SQLite tables (`auto_inspect_queue`, `auto_inspect_items`). Can coexist with FleetRefreshManager. Can implement "lower priority than operator batches" natively. Must add a branch to `_is_cell_owned_by_active_queue` (one SQL query). Most code but cleanest boundaries. B2 history panel would not show sweep progress unless a new row is added to the `batches` table alongside.

**OQ-2: Does auto-sweep create sampling batches, generate batches, or both?**

If sweep = "sample to target CI then generate report", it needs both phases. Current FleetRefreshManager only does sampling (via `_fleet_batch_item_runner` → `RunManager.start_run`; no generate step). BatchRunManager also only does sampling. The generate step is a separate call to `BatchGenerateManager`. A sweep that does both needs to sequence them per cell: wait for sampling `status=completed`, then queue generate. Does the designer want single-batch orchestration of both phases, or two sequential batches?

**OQ-3: Should auto-sweep skip cells where a fresh report already exists?**

"Fresh" = `md5_status == 'match'` in `_build_machines_summary`. If the cell has a fresh report and CI is within `target_halfwidth_pp`, the sweep should skip it. This predicate must be evaluated at sweep-start time (using `_build_machines_summary`) and then per item (checking `check_rawdata_status` freshness). The predicate is not currently part of any manager — it would be new logic in the sweep's cell-list builder. Confirm the exact staleness definition: is "outdated md5" the only trigger, or is "missing report" also a trigger, or is "stale analyzer version" also a trigger?

**OQ-4: How does the sweep interact with a running FleetRefreshManager?**

Currently, both would compete for background ConcurrencyLimiter slots (3 available). If both run simultaneously, each machine gets sampled twice: once by FleetRefresh and once by the sweep's sampling batch. The second to acquire SAMPLING for a given cell is rejected (attach if same config, fail if different). Should the sweep check `fleet_mgr.get_running_queue_id()` and refuse to start if FleetRefresh is active? Or should it coexist and let CellLockRegistry handle the per-cell conflict?

**OQ-5: Where do per-mode granularity settings live — settings.json or request body?**

The audit proposes `settings.json` under `auto_sweep.modes`. An alternative is to pass per-mode params in the `POST /api/auto-inspect/start` request body every time. The settings.json approach is durable across restarts and survives browser swaps; the request-body approach lets operators tune per-sweep without touching JSON files. The settings.json approach aligns with `server_tuning` precedent. Either works technically. Choose one for the implementation.

**OQ-6: Should the sweep register as a "queue owner" in the R1 sense?**

If the sweep uses Option A (BatchRunManager) or Option B (FleetRefreshManager), R1 coverage is automatic. If Option C, the designer must decide: add a new branch to `_is_cell_owned_by_active_queue`, or accept that A2 may double-spawn on crash recovery (bounded by SAMPLING lock reject — at worst one duplicate run per cell per restart).

**OQ-7: New UI tab vs. sub-panel in existing manage tab?**

The current tab structure is `机台管理` (manage) and `调试机台` (debug). A new "auto inspect" tab requires adding a third `<button data-tab="inspect">` and `<section id="tab-inspect">` pair to `index.html` and a new `switchTab` case wired in `boot()` (app.js:8638). A sub-panel inside the manage tab avoids the tab addition but reduces discoverability. The coupling is purely to `switchTab` (app.js:304) and `boot()` (app.js:8638) — both are trivially extensible.
