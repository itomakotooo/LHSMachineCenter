# Pipeline Map: Three Batch/Queue Managers
## SlotConsole backend — state as of 2026-05-26

---

## 1. Three managers, side-by-side comparison table

| Dimension | BatchRunManager | BatchGenerateManager | FleetRefreshManager |
|---|---|---|---|
| **File** | `app.py:4190` | `app.py:3788` | `fleet_refresh.py:65` |
| **Primary purpose** | Operator-triggered multi-machine upstream sampling | Batch report regeneration from existing rawdata chunks | Full-fleet background refresh (cron-like sweep) |
| **Entry endpoint** | `POST /api/batch-run` (app.py:7523) | `POST /api/rawdata/batch-generate-report` (app.py:9810) | `POST /api/fleet/refresh` (app.py:11609) |
| **Work unit** | `(machine, mode)` pair per `BatchRunItem` | `(machine, mode)` pair from explicit list or `scope=all_with_rawdata` | `(machine, mode)` pair per `fleet_refresh_items` row |
| **Concurrency model** | `threading.Semaphore(concurrency)` — one thread per item, semaphore caps | `ProcessPoolExecutor(max_workers=concurrency)` — subprocess pool | Single serial `while` loop in a daemon thread; one item at a time |
| **Work spawned** | `RunManager.start_run()` → analyzer subprocess (Python child process) | `run_analyzer_job()` in pool worker subprocess | `_fleet_batch_item_runner()` → `RunManager.start_run()` → analyzer subprocess |
| **CellOperation acquired** | `SAMPLING` per item, before semaphore | `GENERATING` per item, in `_prepare_batch_gen_item_wrapper` | `SAMPLING` per item, in `fleet_refresh.py:run_queue` |
| **ConcurrencyLimiter priority** | `foreground` (30 s timeout) | Not directly (pool workers don't acquire the shared limiter) | `background` (cancel-aware, no timeout) |
| **Persistence layer** | L2: `batches` table, `kind='sampling'` | L3: `batches` table, `kind='generate'` | Own tables: `fleet_refresh_queue` + `fleet_refresh_items` |
| **Crash recovery** | `_restore_persisted_batches()` at `__init__` — marks non-terminal as `cancelled`, loads into memory | `_restore_persisted()` at `__init__` — same pattern | `StateStore._recover_fleet_refresh()` at `StateStore.__init__` — resets in-flight items to `pending`; resume thread started by `create_app` |
| **Cancel mechanism** | Sets `batch["cancel_requested"]=True`; writes `.stop` flag file; tree-kills subprocess | Sets `state["_cancel_requested"]=True`; futures already submitted are `.cancel()`-ed | Sets `_cancel_flags[queue_id]=True`; checked in `run_queue` loop and inside `_fleet_batch_item_runner` |
| **Resume mechanism** | `POST /api/batch-run/{id}/resume` (app.py:8482) — rebuilds `BatchRunRequest` from saved params, resubmits incomplete items | No resume endpoint (batch is terminal after cancel; re-POST `/batch-generate-report`) | On startup: `fleet_mgr.run_queue(existing_queue_id)` in a new daemon thread; retry policy: up to `MAX_RETRIES=3` per item |
| **Item states** | `pending → running → completed / failed / cancelled / attached / rate_limited` | `pending → running → completed / failed / cancelled` | `pending → running → completed / failed / skipped` |
| **Batch terminal states** | `running → completed / cancelled` (never partial in _run_batch; items track individual failures) | `running → completed / partial / cancelled / failed` | `running → completed / cancelled` |
| **Item retry** | None — failed items need a resume batch | None — re-POST the full batch | Up to `MAX_RETRIES` (default 3) before `skipped` |
| **Queue ordering** | Parallel (all items launched as threads simultaneously) | Parallel (all prepared items submitted to pool simultaneously) | Serial (FIFO by `queue_position`) |

---

## 2. BatchRunManager — detailed flow

**Location:** `src/web_console/backend/app.py:4190`

### Construction (app.py:7072)

```
create_app()
  store = StateStore(db_path)          # app.py:6922
  manager = RunManager(store, ...)     # app.py:7056
  registry = CellLockRegistry()        # app.py:7069
  limiter = ConcurrencyLimiter(n_slots=5, foreground_reserve=2)  # app.py:7070
  batch_mgr = BatchRunManager(store, manager, cr,
      state_dir=sd, machines_config=mc, rawdata_root=rd_root,
      registry=registry, limiter=limiter)   # app.py:7072
    → _restore_persisted_batches()     # app.py:4243
```

### Entry: POST /api/batch-run (app.py:7523)

1. **Pre-batch async md5 refresh** (unless `skip_md5_refresh=True`): daemon thread calls `_do_refresh_machines_md5()` (app.py:10499) — fetches `MachineConfigMd5` from the active server endpoint and atomically rewrites `configs/machines.json`. Does not block the response.

2. **`batch_mgr.start_batch(req, rr)`** (app.py:4344):
   - Generates `batch_id = uuid.uuid4().hex[:12]`
   - For each `BatchRunItem`:
     - Calls `_detect_machine_cycle(machine, rr)` (app.py:1599) — reads newest `player_impact_summary.json` to infer `chunk_spin_times` if not provided
     - Calls `check_rawdata_status(machine, mode, ...)` (app.py:721) — fast path via `_index.json`, cold path via per-chunk envelope scan → returns `{usable_chunks, mismatch_chunks, total_size_mb, ...}`
     - Resolves `resume_cache=True` always (since v2, 2026-04-21)
     - Applies `sampling_strategy` ("total" vs "incremental") to compute `item_max_chunks`
     - Resolves per-item `machine_config` from inline string or local `machineconfig/<underlying>Cfg.txt`
     - Emits events for cache state (♻ resume / 📥 fresh start / ⚠ mismatch)
   - Resolves `server_id` via `_resolve_active_server_id(settings_path)` (app.py:1726)
   - Persists initial state: `_persist_batch(batch_id)` → `store.upsert_batch(...)` (app.py:2268)
   - Spawns daemon thread: `threading.Thread(target=_run_batch, args=(batch_id,))`
   - Returns `{batch_id, status:"running", total:N}`

### _run_batch (app.py:4821)

```
_run_batch(batch_id)
  semaphore = threading.Semaphore(concurrency)   # from req.concurrency
  for each item:
      t = threading.Thread(target=_run_one, args=(item,))
      t.start()
  for t in threads: t.join()
  batch["status"] = "completed"
  _persist_batch(batch_id)
```

All item threads start simultaneously — the semaphore caps how many execute concurrently.

### _run_one (app.py:4840) — per-item thread

1. **Cancel check** — returns immediately if `batch["cancel_requested"]`
2. **Registry SAMPLING acquire** — `registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING, info={config_id, upstream_md5, run_id:""})` (app.py:4875). If fails: check attach vs reject (D12 logic, app.py:4879).
3. **Disk pressure loop** (app.py:4925) — if free < `SLOT_DISK_LOW_WATER_GB` (default 5 GB): call `_auto_cleanup_for_space(...)`, retry up to `SLOT_DISK_WAIT_RETRIES` (default 30) × 10s. If still below `SLOT_DISK_HARD_STOP_GB` (default 2 GB): fail this item only.
4. **ConcurrencyLimiter acquire** — `limiter.acquire("foreground", timeout=30.0)` (app.py:5085). If times out: item → `rate_limited`.
5. **D2 write-config-first** — `store.insert_pending_batch_config(batch_id, machine, mode, config_id)` (app.py:5100) before spawning subprocess.
6. **`RunManager.start_run(req)`** (app.py:5112) → returns `{run_id}` immediately (subprocess already running).
7. **Registry run_id update** — `registry.update_sampling_run_id(machine, mode, run_id)` (app.py:5124).
8. **`_wait_for_run(run_id)`** (app.py:5299) — polls `store.get_run(run_id)` every 1s, up to 7200s.
9. **On completion**: reads summary file → sets `stop_reason`, `ci_target_met`, logs result. Item status → `completed` or `failed`.
10. **Auto-cleanup** — if `auto_cleanup_cache=True`: `shutil.rmtree(cache_root / run_id)` (app.py:5254).
11. **Finally block** — `registry.release_cell(SAMPLING)` then `semaphore.release()` then `limiter.release()`.
12. **`_persist_batch(batch_id)`** — after every item terminal state.

### HTTP API surface

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/api/batch-run` | `start_batch_run` app.py:7523 | Starts batch; async md5 refresh |
| GET | `/api/batch-run/{batch_id}` | `get_batch_run` app.py:8371 | In-memory first, falls back to DB row |
| POST | `/api/batch-run/{batch_id}/cancel` | `cancel_batch_run` app.py:8419 | Sets cancel flag + kills subprocesses |
| POST | `/api/batch-run/{batch_id}/resume` | `resume_batch_run` app.py:8482 | Rebuilds request from saved params, resubmits incomplete items as new batch |
| GET | `/api/sampling-status` | `sampling_status_endpoint` app.py:8412 | Active batches + busy `(machine, mode)` cells |
| GET | `/api/batches` | `list_batches` app.py:8425 | Unified history: sampling + generate, from DB |

---

## 3. BatchGenerateManager — detailed flow

**Location:** `src/web_console/backend/app.py:3788`

### Construction (app.py:9673)

```
create_app()
  _batch_gen_concurrency = int(os.environ.get("SLOT_BATCH_GEN_WORKERS", "4"))
  batch_gen_mgr = BatchGenerateManager(
      prepare_fn=_prepare_batch_gen_item_wrapper,   # app.py:9538
      finalize_fn=_finalize_batch_gen_item_wrapper, # app.py:9552
      concurrency=_batch_gen_concurrency,
      root_path=str(ROOT),
      store=store,
  )
    → _restore_persisted()     # app.py:3879
```

### Entry: POST /api/rawdata/batch-generate-report (app.py:9810)

1. Body: `{"items": [{machine, mode}, ...]}` or `{"scope": "all_with_rawdata"}`
2. `scope=all_with_rawdata`: walks `rawdata/` directory tree, collects all `(machine, mode)` pairs with at least one `chunk_*.json` file.
3. Explicit items: pre-checks registry for busy cells (409 if any busy).
4. Calls `batch_gen_mgr.start(parsed_items)` (app.py:3925).

### start (app.py:3925)

```
batch_id = f"bgen_{uuid.uuid4().hex[:12]}"
state = {status:"pending", items:[...]}
_persist(batch_id)                 # L3: initial snapshot
thread = Thread(target=_run, args=(batch_id,))
thread.start()
return {batch_id, total, status:"running"}
```

### _run (app.py:4000)

**Phase A — prepare** (serial, parent thread):
```
for idx, item in enumerate(items_snapshot):
    cancel check
    pre = prepare_fn(item["machine"], item["mode"])
        → _prepare_batch_gen_item_wrapper(machine, mode)
              → _prepare_batch_gen_item(machine, mode)   # creates run row, output dir, discovers chunks
              → registry.try_acquire_cell(machine, mode, GENERATING)
              → raises HTTPException if busy
    _set_item(idx, status="running", run_id=pre["run_id"])
    prepared.append((idx, pre))
```

**Phase B — pool execution** (parallel, subprocess workers):
```
ctx = multiprocessing.get_context("spawn")
with ProcessPoolExecutor(max_workers=concurrency, mp_context=ctx,
                         initializer=_pool_worker_init,
                         initargs=(root_path,)) as pool:
    for idx, pre in prepared:
        fut = pool.submit(run_analyzer_job, pre["job"])
    for fut in as_completed(futures):
        result = fut.result()
        if result["ok"]:
            final = finalize_fn(pre, result)
                → _finalize_batch_gen_item_wrapper(pre, result)
                      → _finalize_batch_gen_item(pre, result)   # reads summary.json, updates runs row, writes index.json/latest.json
                      → registry.release_cell(machine, mode, GENERATING)
```

**Phase C — pending cleanup**:
If cancel was requested during Phase A, remaining `pending` items flip to `cancelled`.

### Worker process: `run_analyzer_job` (_batch_gen_worker.py:80)

```
_pool_worker_init(root_path):
    import fresh_slotlab.player_impact_analyzer as _analyzer_mod
    import fresh_slotlab.summary_md5_patch.patch_summary_md5
    import fresh_slotlab.post_inference.run_post_analyzer_inference
    import fresh_slotlab.machine_md5.lookup_machine_md5

run_analyzer_job(job):
    argv = ["--machine", machine, "--rtp-mode", mode,
            "--from-cache", chunk_dir, "--output-dir", output_dir, ...]
    sys.argv = argv
    stdout captured to StringIO
    _analyzer_mod.main()             # runs in-process (no new subprocess)
    patch_summary_md5(output_dir, machines_config)
    run_post_analyzer_inference(output_dir, ...)
    return {ok, elapsed_s, post_hook}
```

Key distinction: `BatchGenerateManager` workers run `analyzer.main()` **in-process** within each pool worker (not as a child subprocess). This is why `spawn` context is required — each worker gets its own Python interpreter to isolate the `sys.argv` / monkey-patch state.

### _prepare_batch_gen_item (app.py:~9430, referenced at 9538)

Reads `rawdata/{machine}/mode_{mode}/` for chunks, discovers `chunk_dir`, creates output dir under `reports/{machine}/mode_{mode}/versions/rv_{ts}_{run_id[:8]}/`, inserts `runs` row with `status="running"`. Returns `job` dict for worker.

### HTTP API surface

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/api/rawdata/batch-generate-report` | `batch_generate_report` app.py:9810 | explicit items or `scope=all_with_rawdata` |
| GET | `/api/rawdata/batch-generate-report/{batch_id}` | `get_batch_generate_report` app.py:9905 | in-memory only (no DB fallback for generate batches) |
| POST | `/api/rawdata/batch-generate-report/{batch_id}/cancel` | `cancel_batch_generate` app.py:9892 | next-item-boundary cancel |
| POST | `/api/rawdata/{machine}/generate-report` | `generate_report_from_rawdata` app.py:9684 | single-item, sync or async; NOT via BatchGenerateManager |

---

## 4. FleetRefreshManager — detailed flow

**Location:** `src/web_console/backend/fleet_refresh.py:65`

### Construction (app.py:11591)

```
create_app() [if fleet_refresh_enabled=True]:
    def _fleet_batch_item_runner(machine, mode, queue_id) -> dict:
        # Runs synchronously; called inside run_queue daemon thread
        # Bypasses BatchRunManager's lock-acquire (FleetRefreshManager
        # already holds SAMPLING lock for this cell)
        up_cfg, up_code = _get_machine_md5(machine, mc, mode)
        run_req = RunCreateRequest(
            chunk_spin_times=1000, chunk_robot_count=8,
            batch_concurrency=8, max_chunks=120,
            timeout=300.0, target_halfwidth_pp=0.5,
            resume_from_cache_dir=str(rd_root/machine/f"mode_{mode}"),
            upstream_config_md5=up_cfg, upstream_code_md5=up_code,
        )
        result = manager.start_run(run_req)    # spawns analyzer subprocess
        run_id = result["run_id"]
        # Poll until done (5s intervals, max 7200s)
        while True:
            if fleet_mgr._is_cancelled(queue_id): return cancelled
            row = store.get_run(run_id)
            if row["status"] not in ("running","pending"): break
            sleep(5)
        return {run_id, status, error}

    fleet_mgr = FleetRefreshManager(
        db_path=db_path, registry=registry, limiter=limiter,
        start_batch_item_fn=_fleet_batch_item_runner,
    )

    if store._pending_resume_queue_id:
        Thread(target=fleet_mgr.run_queue, args=(queue_id,)).start()
```

Note: `fleet_refresh_enabled=False` for the virtual console — `app.state.fleet_refresh_manager = None`.

### Entry: POST /api/fleet/refresh (app.py:11609)

1. Single-instance check: `fleet_mgr.get_running_queue_id()` → 409 if already running.
2. Build machine list: if `machines` omitted in body, reads `configs/machines.json` and for each machine walks `rawdata/{machine}/mode_*/` to discover existing modes (defaults to `[1]` if no rawdata).
3. `fleet_mgr.start_queue(machines_list, config_source, server_id)` (fleet_refresh.py:255).

### start_queue (fleet_refresh.py:255)

```
queue_id = uuid.uuid4().hex
INSERT INTO fleet_refresh_queue (queue_id, total_items, status='running', ...)
INSERT INTO fleet_refresh_items (queue_id, machine, mode, queue_position, status='pending', attempt_count=0) × N
Thread(target=self.run_queue, args=(queue_id,)).start()
return queue_id
```

### run_queue (fleet_refresh.py:314) — serial daemon thread

```
while True:
    if _is_cancelled(queue_id): mark 'cancelled'; return

    next_item = _next_pending_item(queue_id)   # ORDER BY queue_position ASC LIMIT 1
    if next_item is None: break  # all done

    machine, mode, attempt_count = next_item

    # Step 1: wait for SAMPLING cell to become available
    cell_wait_start = time.monotonic()
    while True:
        if _is_cancelled: ...
        if registry.try_acquire_cell(machine, mode, SAMPLING, info={...}):
            cell_acquired = True; break
        if elapsed >= cell_busy_timeout_s (default 1800s):
            _mark_item("skipped", last_error="cell_busy_timeout")
            break
        sleep(_CELL_BUSY_POLL_INTERVAL_S=5.0)

    if not cell_acquired: continue

    # Step 2: acquire ConcurrencyLimiter background slot
    limiter_acquired = limiter.acquire("background", cancel_flag=lambda: _is_cancelled)
    if not limiter_acquired:
        registry.release_cell(SAMPLING)
        mark 'cancelled'; return

    # Step 3: run the item
    try:
        _mark_item("running")
        result = start_batch_item_fn(machine, mode, queue_id)
        if result["status"] == "completed":
            _mark_item("completed"); _update_completed_items("completed_items", +1)
        else:
            # retry or skip
            new_attempt = attempt_count + 1
            if new_attempt >= max_retries (default 3):
                _mark_item("skipped", last_error="max_retries_exceeded")
            else:
                _mark_item("pending", ...)   # re-queue
    except:
        # same retry/skip logic
    finally:
        registry.release_cell(SAMPLING)
        if limiter_acquired: limiter.release()

_mark_queue_status("completed")
```

### Crash recovery (StateStore._recover_fleet_refresh, app.py:2132)

Called during `StateStore.__init__` after `_init_db`:
- Finds a `fleet_refresh_queue` row with `status='running'`
- Resets its `fleet_refresh_items` rows from `status='running'` back to `status='pending'`
- Sets `self._pending_resume_queue_id = queue_id`
- `create_app` reads this and spawns `fleet_mgr.run_queue(queue_id)` in a new daemon thread

### HTTP API surface

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/api/fleet/refresh` | `start_fleet_refresh` app.py:11609 | 409 if already running |
| GET | `/api/fleet/refresh` | `get_fleet_refresh` app.py:11681 | Returns running queue or latest completed |
| DELETE | `/api/fleet/refresh` | `cancel_fleet_refresh` app.py:11713 | Sets cancel flag |

---

## 5. Shared infrastructure

### CellLockRegistry (cell_lock_registry.py:50)

Single instance per `create_app()` call. In-memory only. Guards all concurrent access to `(machine, mode)` cells.

**Operations:**
- `SAMPLING` — BatchRunManager items + FleetRefreshManager items
- `GENERATING` — BatchGenerateManager items + single-item `generate-report` endpoint
- `DELETING` — `delete_rawdata` paths

**Invariants enforced by `try_acquire_cell` (cell_lock_registry.py:93):**
- INV-1: SAMPLING ↔ DELETING mutually exclusive
- INV-2: GENERATING ↔ DELETING mutually exclusive
- INV-3: SAMPLING + GENERATING coexist by default (batch generate uses this); user-facing single generate can opt in to `block_if_sampling_active=True` (409 if sampling active)
- INV-4: at most ONE SAMPLING per cell
- INV-5: at most ONE GENERATING per cell

**Attach response (D12):** when SAMPLING acquire fails, `get_active_sampling_info(machine, mode)` is checked. If the active SAMPLING has the same `(config_id, upstream_md5)`, the new item is marked `attached` (not failed), and the existing `run_id` is returned. Used only in BatchRunManager `_run_one` (app.py:4879).

**`_sampling_info` dict** stores `{run_id, config_id, upstream_md5}` per cell while SAMPLING is active. Updated after `start_run` returns the real `run_id` via `update_sampling_run_id` (app.py:5124).

### ConcurrencyLimiter (rate_limiter.py:27)

Single instance per `create_app()`. Caps total concurrent analyzer subprocesses.

- `n_slots=5, foreground_reserve=2`
- `foreground` (BatchRunManager): can use all 5 slots
- `background` (FleetRefreshManager): can only use 3 slots (5 - 2 foreground_reserve)
- BatchGenerateManager uses a `ProcessPoolExecutor` instead of going through the limiter directly (the pool is sized independently via `SLOT_BATCH_GEN_WORKERS`)

### runs table (SQLite: state/console/console.db)

Created by `StateStore._init_db` (app.py:1940). Schema:

| Column | Type | Populated by |
|---|---|---|
| `run_id` | TEXT PK | `RunManager.start_run` |
| `machine`, `mode` | TEXT, INTEGER | `start_run` |
| `status` | TEXT | `start_run` ("running") → `_watch_run` (completed/failed/cancelled) |
| `created_at`, `started_at`, `finished_at` | TEXT | `start_run`, `_watch_run` |
| `process_pid` | INTEGER | `start_run` |
| `output_dir`, `progress_file`, `summary_file`, `report_file` | TEXT | `start_run` |
| `chunk_spin_times`, `chunk_robot_count`, `batch_concurrency`, `max_chunks`, `timeout`, `target_halfwidth_pp` | various | `start_run` |
| `achieved_rtp_pct`, `achieved_halfwidth_pp` | REAL | `_update_report_index` (RunManager, app.py:6484) |
| `rawdata_config_md5`, `rawdata_code_md5` | TEXT | `_update_report_index` |
| `analyzer_version`, `effective_analyzer_version` | TEXT | `_update_report_index` |
| `total_spins` | INTEGER | `_update_report_index` |
| `quality_label` | TEXT | `_update_report_index` |
| `underlying_removed` | INTEGER | `mark_runs_underlying_removed` |
| `error_message` | TEXT | `_watch_run` on failure |
| `report_version` | TEXT | `start_run` — format `rv_{ts}_{run_id[:8]}` |

**Who creates runs rows:**
- `RunManager.start_run` (app.py:6212): all sampling runs (called by BatchRunManager, FleetRefreshManager's runner, and single `/api/runs` endpoint)
- `_prepare_batch_gen_item` (called by BatchGenerateManager's prepare wrapper): generate-report runs

**Orphan recovery (A2):** `RunManager._recover_orphan_running_runs` (app.py:5979) runs at construction. Finds `status='running'` rows. If `_is_cell_owned_by_active_queue` returns non-None, skips auto-resume (lets the queue handle it). Otherwise terminates stale PID and calls `_spawn_resume_for_orphan` to restart with `--resume-from-cache`.

### batches table (SQLite: state/console/console.db)

Created by `StateStore._init_db` (app.py:2052). Schema:

| Column | Type | Notes |
|---|---|---|
| `batch_id` | TEXT PK | Hex string; `bgen_` prefix for generate batches |
| `status` | TEXT | pending / running / completed / partial / cancelled / failed |
| `kind` | TEXT | 'sampling' (BatchRunManager) or 'generate' (BatchGenerateManager) |
| `created_at`, `finished_at` | TEXT | |
| `concurrency` | INTEGER | |
| `params_json` | TEXT | JSON: sampling params or generate counter fields |
| `items_json` | TEXT | JSON: per-item status snapshots |
| `events_json` | TEXT | JSON: batch-level event log (capped at 200 entries) |
| `reports_root` | TEXT | Only used for sampling batches |

**Upserted by:** `StateStore.upsert_batch` (app.py:2268) — INSERT OR REPLACE.
**Read for restore:** `list_batches_by_status(("pending","running"), kind=...)` on manager `__init__`.
**Read for history:** `list_recent_batches` / `get_batch_row` — used by `GET /api/batches` and `GET /api/batch-run/{id}` DB fallback.

### fleet_refresh_queue table

```sql
CREATE TABLE fleet_refresh_queue (
    queue_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL,          -- running / completed / cancelled
    total_items INTEGER NOT NULL,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    skipped_items INTEGER NOT NULL DEFAULT 0,
    config_source TEXT NOT NULL DEFAULT 'server_default',
    server_id TEXT,
    cancelled_at TEXT,
    finished_at TEXT
)
```

### fleet_refresh_items table

```sql
CREATE TABLE fleet_refresh_items (
    queue_id TEXT NOT NULL REFERENCES fleet_refresh_queue(queue_id),
    machine TEXT NOT NULL,
    mode INTEGER NOT NULL,
    queue_position INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    run_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (queue_id, machine, mode)
)
```

### pending_batch_configs table (D2 crash anchor)

```sql
CREATE TABLE pending_batch_configs (
    batch_run_id TEXT NOT NULL,
    machine TEXT NOT NULL,
    mode INTEGER NOT NULL,
    config_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (batch_run_id, machine, mode)
)
```

Written before analyzer subprocess starts in `_run_one` (app.py:5100); deleted after subprocess completes (app.py:5132). On startup, `create_app` scans orphaned rows and re-associates chunks in `_chunks.json:by_config_id` (daemon thread, app.py:6939).

### Directory structure

**Rawdata:** `rawdata/{machine}/mode_{mode}/`
```
rawdata/M14/mode_1/
  _chunks.json          # per-mode chunk sidecar: {chunks: {fname→meta}, by_md5: {cfg|code→[fnames]}}
  chunk_0001.json       # raw spin data, envelope: {config_md5, code_md5, saved_at, ...}
  chunk_0002.json
  ...
```

**Reports:** `reports/{machine}/mode_{mode}/`
```
reports/M14/mode_1/
  index.json            # list of all report version summaries (array), latest entry appended on each generate
  latest.json           # single entry: most recently generated report
  versions/
    rv_20260521T011344Z_12f41ee1/
      player_impact_summary.json
      player_impact_report.md
      machine_config.json     # (only if local cfg override was used)
      _post_hook.json         # (only for BatchGenerateManager runs)
```

**Progress files:** `state/console/progress/{run_id}.jsonl`

**Stop flags:** `state/console/progress/{run_id}.stop`

**Server snapshots:** `.probe/server_snapshots/{server_id}.json`

**Settings:** `state/console/settings.json`

### RunManager.start_run → analyzer subprocess CLI (app.py:6242)

```python
cmd = [
    sys.executable, str(analyzer),
    "--machine", machine,
    "--rtp-mode", str(mode),
    "--target-halfwidth-pp", str(effective_halfwidth_pp),
    "--chunk-spin-times", str(chunk_spin_times),
    "--chunk-robot-count", str(chunk_robot_count),
    "--batch-concurrency", str(batch_concurrency),
    "--max-chunks", str(effective_max_chunks),
    "--timeout", str(timeout),
    "--output-dir", str(output_dir),
    "--run-id", run_id,
    "--progress-file", str(progress_file),
    "--stop-flag-file", str(stop_flag_file),
    "--chunk-cache-dir", str(cache_root / run_id),    # legacy scratch; new chunks land in rawdata/
    # conditionally:
    "--endpoint-url", endpoint,                        # if server_id provided
    "--from-cache", from_cache_dir,                    # if from_cache_dir set
    "--resume-from-cache", resume_from_cache_dir,      # if resume_from_cache_dir set
    "--upstream-config-md5", effective_cfg_md5,        # if non-empty
    "--upstream-code-md5", upstream_code_md5,          # if non-empty
    "--upstream-machine-name", upstream_machine_name,  # for variant rows
    "--machine-config-file", str(cfg_path),            # if machine_config override
]
```

The analyzer subprocess writes chunks to `rawdata/{machine}/mode_{mode}/` (via `--resume-from-cache`), writes summary/report to `--output-dir` (`reports/.../versions/rv_.../`), and emits progress events as JSONL to `--progress-file`.

---

## 6. How "machine needs sample" decision is made TODAY

There is no automated "needs sample" detector running in the existing three managers. The decisions are manual and reactive:

### A. md5 mismatch detection (per batch item, BatchRunManager)

At `start_batch` time (app.py:4369), for each item:

```
check_rawdata_status(machine, mode) → {usable_chunks, mismatch_chunks}
_get_machine_md5(machine, machines_config, mode) → (cfg_md5, code_md5)
```

`check_rawdata_status` (app.py:721) compares each chunk's envelope `config_md5` / `code_md5` against the current value from `machines.json`:
- **usable_chunks**: chunks whose md5 matches current upstream
- **mismatch_chunks**: chunks with non-current md5 (historical)

If `mismatch_chunks > 0` and `usable_chunks == 0`: all local data is from an old version. Analyzer still resumes into the same `rawdata/` dir with `--upstream-config-md5` filter so new chunks are written and only the new-md5 ones are merged into stats.

### B. "No report" detection (via _build_machines_summary, app.py:3639)

`_build_machines_summary(reports_root)` scans `reports/{machine}/mode_*/versions/*/player_impact_summary.json` and returns a dict keyed by machine → mode → best-CI report metadata. Each entry includes `md5_status` field:

- `"match"` — report's `config_md5` / `code_md5` matches current `machines.json`
- `"outdated"` — report was generated against an old version
- `"untagged"` — report predates md5 stamping
- `"unverifiable"` — upstream md5 unknown (empty string in `machines.json`)

A machine with **no entry at all** in the result dict has no report at all. This summary is surfaced via `GET /api/fleet/export-csv` (app.py:10941) and the fleet tab UI — but it is not currently consumed by any of the three managers to auto-trigger sampling.

### C. upstream md5 snapshot comparison (manual)

`POST /api/servers/{id}/scan` (app.py:8666) calls `_fetch_machine_config_md5(endpoint)` → POSTs to `{endpoint}/MachineTest/MachineConfigMd5` → saves to `.probe/server_snapshots/{server_id}.json`.

`POST /api/servers/{id}/check-changes` (app.py:8708) calls scan + compares with the previous snapshot via `_compare_snapshots` → returns `changed_machines`, `config_changed`, `code_changed` lists.

`_do_refresh_machines_md5(server_id)` (app.py:10499) fetches `MachineConfigMd5` and atomically rewrites `configs/machines.json` with updated `configSummaryMd5` / `codeSummaryMd5` per machine, fanning out to variant rows.

**Current local md5 source:** `configs/machines.json` — fields `configSummaryMd5` / `codeSummaryMd5` per machine row. For virtual machines: `modesMd5[mode].configSummaryMd5` / `modesMd5[mode].codeSummaryMd5`.

**There is no persistent "last known upstream md5 at time of report generation vs current" diff that drives automated re-sampling.** The `md5_status` field in `_build_machines_summary` captures report-level staleness, but it is computed on-read from the current `machines.json` state and is not compared against when the data was last sampled.

---

## 7. How rawdata sampling produces chunks → reports TODAY

### Full pipeline: operator-triggered single machine

```
1. Operator: POST /api/batch-run
      body: {items:[{machine, mode}], concurrency, chunk_spin_times, ...}

2. BatchRunManager.start_batch (app.py:4344)
      check_rawdata_status → {usable_chunks, mismatch_chunks}
      resolve server_id via _resolve_active_server_id (app.py:1726)
          reads state/console/settings.json → configs/servers.json → first active

3. BatchRunManager._run_one (app.py:4840)
      registry.try_acquire_cell(SAMPLING)
      RunManager.start_run(RunCreateRequest) → spawns analyzer subprocess

4. Analyzer subprocess (fresh_slotlab/player_impact_analyzer.py)
      --resume-from-cache rawdata/M{N}/mode_{mode}/
          reads existing chunk_*.json (filter by --upstream-config-md5/code-md5)
          merges matching chunks into running stats
          counts usable = N existing chunks → starts from chunk_{N+1}
      for each new chunk:
          POST {endpoint}/MachineTest/MultiRobotTestSpinVariant
          writes chunk_{N+1}.json to rawdata/M{N}/mode_{mode}/
          updates rawdata/M{N}/mode_{mode}/_chunks.json sidecar
          writes chunk_progress event to state/console/progress/{run_id}.jsonl
          checks --stop-flag-file between chunks
      when done (target CI / max_chunks / stop flag):
          writes player_impact_summary.json → reports/M{N}/mode_{mode}/versions/rv_.../
          writes player_impact_report.md → same dir
          exit 0

5. RunManager._watch_run (app.py:6387)
      proc.communicate() → waits for subprocess exit
      if exit_code==0 and summary+report exist and total_spins>0:
          _update_report_index(managed) (app.py:6484)
              reads summary.json → extracts rtp_point_pct, achieved_halfwidth_pp, md5s
              appends entry to reports/M{N}/mode_{mode}/index.json
              overwrites reports/M{N}/mode_{mode}/latest.json
              updates runs row: achieved_rtp_pct, achieved_halfwidth_pp, quality_label, ...
          store.update_run(run_id, {status:"completed"})
      else: store.update_run(run_id, {status:"failed", error_message:...})
      _running.pop(run_id)

6. BatchRunManager._run_one continues after _wait_for_run
      reads runs row → extracts stop_reason, ci_target_met
      item["status"] = "completed"
      registry.release_cell(SAMPLING)
      semaphore.release()
      limiter.release()
      _persist_batch(batch_id)
```

### Alternate: report regeneration (BatchGenerateManager)

```
POST /api/rawdata/batch-generate-report
    body: {scope: "all_with_rawdata"}

BatchGenerateManager.start → _run:
    Phase A: _prepare_batch_gen_item(machine, mode)
        discovers chunk_dir = rawdata/M{N}/mode_{mode}/
        creates output_dir = reports/M{N}/mode_{mode}/versions/rv_.../
        inserts runs row (status="running")
        GENERATING lock acquired

    Phase B: pool.submit(run_analyzer_job, job)
        worker calls analyzer.main() IN-PROCESS:
            --from-cache rawdata/M{N}/mode_{mode}/  (reads all matching chunks)
            writes summary.json + report.md to output_dir
        patch_summary_md5(output_dir, machines_config)
        run_post_analyzer_inference(output_dir, ...)

    finalize_fn: _finalize_batch_gen_item(pre, worker_result)
        reads summary.json
        updates runs row (status="completed", rtp, ci, ...)
        appends to index.json, overwrites latest.json
        GENERATING lock released
```

---

## 8. Tunable parameters TODAY

### BatchRunRequest fields (app.py:1805) — operator sets per-batch

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `items` | list[BatchRunItem] | required | machines + modes to sample |
| `concurrency` | int | 3 | parallel item threads (semaphore cap); range [1,10] |
| `server_id` | str | "" | upstream server; "" → `_resolve_active_server_id` |
| `chunk_spin_times` | int | 10000 | spins per upstream request chunk |
| `chunk_robot_count` | int | 8 | concurrent robot threads per chunk request |
| `batch_concurrency` | int | 8 | upstream HTTP parallelism per robot |
| `max_chunks` | int | 120 | total chunk budget (strategy-dependent) |
| `timeout` | float | 60.0 | per-chunk HTTP timeout in seconds |
| `target_halfwidth_pp` | float | 0.5 | CI half-width target in pp; 0 = fuzzy (~1M spins) |
| `auto_cleanup_cache` | bool | True | rmtree scratch cache after item completes |
| `sampling_strategy` | str | "total" | "total" (max_chunks is ceiling) or "incremental" (delta) |
| `skip_md5_refresh` | bool | False | skip pre-batch async md5 refresh |

### Per-item overrides in BatchRunItem (app.py:1786)

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `chunk_spin_times` | int \| None | None | per-item override; None → `_detect_machine_cycle` heuristic |
| `machine_config` | str \| None | None | inline MachineConfig JSON override |
| `use_local_machine_config` | bool | False | read `machineconfig/{underlying}Cfg.txt` at submit time |

### RunCreateRequest fields (app.py:320) — set by BatchRunManager._run_one

| Parameter | Default | Notes |
|---|---|---|
| `from_cache_dir` | "" | read-only; empty in current batch flow |
| `resume_from_cache_dir` | str | always `rawdata/{machine}/mode_{mode}/` in batch flow |
| `upstream_config_md5` / `upstream_code_md5` | from machines.json | filter resume-read to current-md5 chunks |
| `bankruptcy_session_spins` | 10000 | |
| `bankruptcy_bankroll_multipliers` | "10,100,200,500" | |
| `model_id` | "gpt-5.4-mini" | for interpretation; not relevant to sampling |

### FleetRefreshManager fixed parameters (app.py:11540)

These are **hardcoded** in `_fleet_batch_item_runner`, not operator-configurable:

| Parameter | Value | Notes |
|---|---|---|
| `chunk_spin_times` | 1000 | intentionally small per original spec |
| `chunk_robot_count` | 8 | |
| `batch_concurrency` | 8 | |
| `max_chunks` | 120 | |
| `timeout` | 300.0 | |
| `target_halfwidth_pp` | 0.5 | |
| `server_id` | "" → `_resolve_active_server_id` | resolved at runner call time |

### Environment-variable overrides

| Env var | Default | Consumed by |
|---|---|---|
| `SLOT_RAWDATA_ROOT` | `rawdata/` | `RAWDATA_ROOT` global (app.py:568) |
| `SLOT_DISK_LOW_WATER_GB` | 5.0 | disk pressure trigger in `_run_one` |
| `SLOT_DISK_TARGET_FREE_GB` | 10.0 | disk cleanup goal |
| `SLOT_DISK_HARD_STOP_GB` | 2.0 | bail item if can't reach this free |
| `SLOT_DISK_WAIT_RETRIES` | 30 | retries × 10s before hard stop |
| `SLOT_BATCH_GEN_WORKERS` | 4 | BatchGenerateManager pool size |
| `SLOT_FLEET_MAX_RETRIES` | 3 | FleetRefreshManager per-item retries |
| `SLOT_FLEET_CELL_BUSY_TIMEOUT_S` | 1800 | FleetRefreshManager cell-busy timeout |

### state/console/settings.json operator keys

| Key | Default | Consumed by |
|---|---|---|
| `default_server` | "" | `_resolve_active_server_id` (overrides configs/servers.json) |
| `min_retention_spins` | 100000 | `_auto_cleanup_for_space` retention carve-out |
| `auto_resume_orphan_runs` | True | `RunManager` at construction |
| `server_tuning` | {} | per-server robot/concurrency tuning (referenced, not yet detailed) |

---

## 9. Open questions for designer

**OQ-1: FleetRefreshManager uses hardcoded sampling params.**
`_fleet_batch_item_runner` (app.py:11540) uses `chunk_spin_times=1000`, `max_chunks=120`, `target_halfwidth_pp=0.5` — not the same defaults as `BatchRunRequest` (chunk_spin_times=10000). The new auto-sweep feature requires per-mode configurable params. The designer must decide: do these live in a new settings key, in a per-mode config table, or in the POST /api/auto-inspect/start body? There is no existing mechanism to store "per-mode granularity presets" persistently.

**OQ-2: "Machine needs sample" has no persistent staleness tracking.**
`_build_machines_summary` (app.py:3639) computes `md5_status` on read from current `machines.json`. There is no stored "last sampled at upstream_md5 = X" record. If `machines.json` changes (via `_do_refresh_machines_md5`) after a report was generated, the report's `md5_status` flips to `"outdated"` automatically on the next summary read. However, the auto-sweep would need to compare current upstream md5 to the md5 that rawdata chunks were sampled against — that data IS in `rawdata/{m}/mode_{n}/_chunks.json` (via `by_md5`) and in `reports/.../index.json` (via `rawdata_config_md5` / `rawdata_code_md5` per index entry). The designer must clarify which comparison point is authoritative: rawdata md5, report md5, or both.

**OQ-3: FleetRefreshManager is strictly serial (one item at a time).**
It acquires SAMPLING, waits for one run to complete, releases, then moves to the next. This is intentional per the current design to avoid overloading the upstream server. The new auto-sweep feature may need a different concurrency model (parallel per some cap) but the existing manager infrastructure doesn't support this without modification. The designer must decide whether to extend FleetRefreshManager with parallelism or build a new manager that parallels like BatchRunManager.

**OQ-4: No "has any report at all" shortcut in current check_rawdata_status.**
`check_rawdata_status` (app.py:721) tells whether rawdata chunks exist and what md5 they carry. It does NOT check whether a report exists. The "no report" detection requires a separate `reports/{machine}/mode_{mode}/index.json` existence check or a call to `_build_machines_summary`. The designer must specify which signal drives the "needs sample" decision: no rawdata, no report, outdated report md5, or outdated rawdata md5.

**OQ-5: FleetRefreshManager scope is fixed at POST time.**
`POST /api/fleet/refresh` without a `machines` body defaults to ALL machines in `machines.json` × their existing rawdata modes. There is no "only sample modes 1, 2, 5, 7" filter (the new feature's stated requirement). The current code at app.py:11645 infers modes from `rawdata/` directory existence, defaulting to `[1]`. The designer must decide whether the new auto-sweep reuses `FleetRefreshManager.start_queue` with an explicit `machines` body, or needs a new entry point.

**OQ-6: Upstream md5 refresh is best-effort and async; timing relative to sweep start is unclear.**
`POST /api/batch-run` triggers an async `_do_refresh_machines_md5` daemon thread (app.py:7559) that may not complete before `check_rawdata_status` is called in `start_batch`. The sweep's md5 comparison would need to either synchronously refresh before building the machine list, or use the most recent snapshot in `.probe/server_snapshots/{server_id}.json`. There is no guarantee these are up-to-date at sweep start. The designer must specify whether the auto-sweep is allowed to use stale local md5 or must do a synchronous refresh before deciding which machines to enqueue.

**OQ-7: FleetRefreshManager's `_fleet_batch_item_runner` bypasses BatchRunManager.**
It calls `manager.start_run(RunCreateRequest)` directly (app.py:11554), skipping the disk-pressure loop, the `pending_batch_configs` anchor, the attach-response logic, and the `SAMPLING` lock acquire (which FleetRefreshManager already did before calling the runner). The auto-sweep designer needs to decide whether to follow the same pattern (direct RunManager call) or route through BatchRunManager's `_run_one` logic (which would double-acquire the SAMPLING lock, currently a bug since the registry would reject the second acquire with the same CellOperation).

**OQ-8: per-mode granularity storage is not yet designed.**
The user brief says "Operator sets per-mode granularity once; all machines for that mode use those values." There is no existing settings schema for this. The closest thing is `BatchRunRequest` fields which are per-batch, not persistent. The designer must define the storage location (settings.json extension? new DB table?) and the API (separate PUT endpoint? part of the POST /auto-inspect/start?).
