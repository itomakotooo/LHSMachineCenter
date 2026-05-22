# 03 Deploy Concurrency Blast Radius

> Agent: arch-coupling-auditor (second use of arch-* team — deploy scope)
> Date: 2026-05-15
> Spec contract: `session_artifacts/_arch/deploy/00_deploy_brief.md`
> Read-only analysis — no code changes.

---

## §1 Methodology

Each scenario is walked against actual source code (`src/web_console/backend/app.py`, `fresh_slotlab/chunk_index.py`, `src/web_console/backend/reports_retention.py`, `src/web_console/backend/_batch_gen_worker.py`, `src/web_console/frontend/app.js`). All "current behavior" claims cite file:line.

Informing memory landmarks used:
- `memory/feedback_subprocess_import_suicide_and_module_globals.md` — module-global landmines
- `memory/reference_chunk_index_inverted_md5.md` — sidecar write concurrency
- `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md` — cache delete semantics
- `memory/feedback_upstream_throttle_ceiling.md` — rate limit ceiling
- `memory/reference_sampling_api.md` — upstream endpoint + throughput regime
- `memory/feedback_fasttimer_overlap_needs_oneshot.md` — polling overlap
- `memory/feedback_error_branch_resets_all_state.md` — UI state reset
- `memory/feedback_no_silent_swallow.md` — background task failure
- `memory/feedback_md5_granularity_and_stamping.md` — per-mode hash

One additional scenario (16) was discovered during analysis and is appended.

---

## §2 Scenario Walks

---

### Scenario 1: Concurrent same-cell fetch — 2 planners click "fetch M14|1" simultaneously

#### 1a — Same cell (same `(machine, mode)`)

**Current behavior:**

`POST /api/batch-run` calls `batch_mgr.start_batch()` (`app.py:3242`). Inside `start_batch`, each item calls `self._try_acquire_key(machine, mode)` (`app.py:3200-3206`), which uses `self._busy_keys` (a `set[tuple[str,int]]` on `BatchRunManager`, `app.py:3198`) protected by `self._lock` (`app.py:3189`).

If planner A's batch is already running M14|1, planner B's batch for the same cell hits `_try_acquire_key` which returns `False` at `app.py:3202`, causing the item to fail with `"another batch is sampling this machine+mode"` (`app.py:3678`).

However: `_try_acquire_key` is called *inside* `_run_one` which is the per-item thread (`app.py:3666`), not at `start_batch` submission time. The key is NOT acquired at HTTP request time. Between `start_batch()` returning `{"batch_id": X, "status": "running"}` and `_run_one` actually executing:

1. Both batches are created and both threads are spawned.
2. Both threads race to `_try_acquire_key`.
3. The first thread to arrive wins and proceeds; the second gets `False` and logs a warning-level skip, marking the item `"failed"`.

Consequence: One fetch wins, one fails with per-item failure (not a batch failure). No double upstream call, no chunk collision. The losing batch's item is marked failed but its other items (if multi-machine batch) continue.

For **upstream sampling dedup**: each winning batch spawns `RunManager.start_run()` which executes the analyzer subprocess (`app.py:4865`). The analyzer opens upstream HTTP to `MultiRobotTestSpinVariant`. Two concurrent batches for *different* cells do NOT share any upstream request—each spawns its own subprocess and its own HTTP connection pool.

For the upstream rate-limit axis: if planner A and B submit batches for different cells simultaneously, there is **no shared token bucket** across the two `BatchRunManager` invocations. Each analyzer subprocess independently fires concurrent HTTP requests up to its own `--batch-concurrency`. The two streams add up at the upstream server, potentially pushing combined throughput above the per-IP ceiling (~1k/s per source per `memory/reference_sampling_api.md`).

**Hazard level:** `safe` (same-cell dedup works via per-key lock) / `minor_perf` (distinct cells—no dedup on upstream rate)

**Mitigation type:** Same cell: already handled. Distinct cells under multi-user: needs rate-limit single bucket (brief §5.8, §6).

**Memory refs:** `memory/feedback_upstream_throttle_ceiling.md`, `memory/reference_sampling_api.md`

---

#### 1b — Sidecar write race (same cell, both batches win)

Even if the per-key lock prevents two batches from sampling the same cell *simultaneously*, consider the window between `_try_acquire_key` acquiring the key and `_acquire_in_use` being called (`app.py:3761`). The key is acquired in `_run_one` before the actual `start_run` call. `_acquire_in_use` is called inside `_run_one` after the disk-pressure check. Between those two points, a `POST /api/cache/cleanup` could race, since cleanup only checks `_get_in_use_snapshot()` (`app.py:2505`) not `_busy_keys`.

The sidecar `_chunks.json` is protected by `_sidecar_lock_for(mode_dir)`, a per-mode `threading.Lock` (`chunk_index.py:91-111`). This lock is **process-local** (a `dict[str, threading.Lock]`). All write paths through `update_chunk_entry` and `bulk_remove_chunk_entries` hold this lock. Within one process, sidecar writes are serialized per mode_dir. Safe single-process.

**Hazard level:** `safe` (within single process, per-mode lock correct)

**Mitigation type:** None within-process. Cross-process would require file lock — not needed today (single server process).

---

### Scenario 2: Concurrent fetch vs. analyze — Planner A analyzing M14|1 cached chunks; Planner B triggers fetch for same cell

**Current behavior:**

`BatchGenerateManager._run()` acquires `self._ops.acquire("batch_generate_report")` (`app.py:2970`) — the global `OperationCoordinator` lock. This lock is **single-slot** (`app.py:4007-4028`): only one named operation can hold it at a time.

`POST /api/batch-run` calls `batch_mgr.start_batch()` which does **NOT** acquire `ops` — it uses its own `_busy_keys` set. So fetch and analyze can run **concurrently** for the same cell.

The specific race:

1. Planner A's batch-generate starts reading chunks from `rawdata/M14/mode_1/*.json` via `run_analyzer_job` in a subprocess worker.
2. Planner B triggers `POST /api/batch-run` which spawns a new analyzer subprocess writing new chunks to `rawdata/M14/mode_1/`.
3. The `--resume-from-cache` analyzer (planner B) will glob `chunk_*.json` and enumerate filenames sequentially. Planner A's `BatchGenerateManager` is reading existing chunk files via `--from-cache` path.

Both operations touch the same mode_dir. The chunk files are written by planner B's sampler as `chunk_*.json.tmp` and then `os.replace` to `chunk_*.json`. Planner A's analyzer (which reads `.json` files) sees an atomically-named file or does not see it (no torn reads of individual chunk files). The issue is at the **index level**:

- Planner B's analyzer worker calls `update_chunk_entry` after each new chunk lands, which acquires `_sidecar_lock_for(mode_dir)` and rewrites `_chunks.json`.
- Planner A's `BatchGenerateManager` subprocess (`run_analyzer_job` → `_pool_worker_init` → `_analyzer_mod.main()`) runs `get_chunks_index(mode_dir)` to enumerate which chunks match the target md5. If A reads the sidecar while B is mid-write inside `_write_sidecar_atomic`, A either reads the old sidecar (tmp hasn't replaced yet) or the new one. The `os.replace` is atomic, so A never reads a torn file. A may read a sidecar that does not yet include B's latest chunk — which is fine for A (it doesn't need B's new chunks).

`_IN_USE_MODES` (`app.py:2152`) is set by `_acquire_in_use` called inside `_run_one` of `BatchRunManager` (fetch path, `app.py:3761`). This correctly prevents `_auto_cleanup_for_space` from touching the mode_dir while sampling is active. The `BatchGenerateManager` does NOT call `_acquire_in_use` (`app.py:2862-3158` — no such call). So if disk-pressure auto-cleanup fires while batch-generate-report is running, the cleanup logic will NOT see the generate-report job in `_IN_USE_MODES`, and could delete chunks that the analyzer subprocess is currently reading.

**Hazard level:** `data_corruption` (limited: if auto-cleanup fires during batch-generate-report for same cell, it may delete chunks being read; the analyzer subprocess reads open file handles so the OS may have already buffered the data — on Windows with NTFS, an open file handle prevents deletion via `unlink()` but `shutil.rmtree` uses a different code path that may still fail or leave partial reads)

**Mitigation type:** `BatchGenerateManager` needs to call `_acquire_in_use` / `_release_in_use` around its worker executions, same as `BatchRunManager._run_one` does.

**Memory refs:** `memory/feedback_subprocess_import_suicide_and_module_globals.md`, `memory/feedback_enumerate_safety_paths.md`

---

### Scenario 3: Concurrent cache delete vs. read — Planner A views report; Planner B deletes rawdata

**Current behavior:**

`DELETE /api/rawdata/{machine}` acquires `ops.acquire("delete_rawdata")` (`app.py:6269`). The `OperationCoordinator` is a single-slot boolean lock. If `batch_generate_report` currently holds `ops`, then `delete_rawdata` gets 409. But `BatchRunManager.start_batch()` (the fetch path, `/api/batch-run`) does NOT acquire `ops`. So a concurrent fetch and a rawdata delete can race.

The `delete_rawdata` function unlinks chunks (`app.py:1143-1148`). The analyzer subprocess launched by `BatchRunManager` reads chunk files via file handles. On Windows with `unlink()`, an open handle prevents deletion — so concurrent reads block concurrent deletes for the same file. However, the bulk delete also calls `shutil.rmtree` in the `force=True` path (`app.py:1076`) which on Windows may raise `PermissionError` for open files rather than blocking.

**Report files are NOT deleted by rawdata deletion.** `delete_rawdata` only touches `rawdata/` chunks and the `rawdata_index`. Report files (`reports/<M>/mode_<N>/versions/<rv_...>/`) are not touched. Planner A's report view reads from `reports/` which survives intact. The report is not tagged `underlying_removed=True` — there is no current code path that sets such a flag on reports when rawdata is deleted (audit of `delete_rawdata` at `app.py:1040-1176` and `reports_retention.py` confirms: no cross-write to reports/).

**Hazard level:** `minor_perf` (report view: safe; rawdata delete concurrent with fetch: PermissionError on Windows for force path; report stale tagging: not_implemented per brief §5.6)

**Mitigation type:** "needs report stale-tag on rawdata delete" (brief §5.6). Rawdata delete vs. active fetch: needs `_acquire_in_use` check before delete proceeds, or 409 if target (machine, mode) is in `_IN_USE_MODES`.

**Memory refs:** `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md`, `memory/feedback_enumerate_safety_paths.md`

---

### Scenario 4: Concurrent fetch vs. full-refresh — ad-hoc fetch priority over fleet-refresh

**Current behavior:**

There is **no full-fleet-refresh endpoint** in the current codebase. `POST /api/batch-run` supports multi-item batches (planner submits a list of `BatchRunItem`), but there is no dedicated endpoint for "run all 393 machines." The brief lists this as a requirement (§5.8, §6).

The current `BatchRunManager` accepts arbitrary item lists per batch. Two concurrent `POST /api/batch-run` calls create two independent `BatchRunManager` batch entries (each with its own `batch_id`, its own `_batches` state entry, and its own concurrency semaphore). Both run concurrently in separate daemon threads.

**Priority mechanism:** There is no priority queue. A "foreground ad-hoc fetch" and a "background full-refresh batch" compete for `_busy_keys` at the per-cell level. If the full-refresh is running M14|1, an ad-hoc planner fetch of M14|1 gets `"another batch is sampling this machine+mode"` — rejected, not prioritized.

**Rate-limit bucket:** No shared upstream rate limiter exists. Each analyzer subprocess opens its own connections. Multiple batches multiply upstream load independently.

**Hazard level:** `not_implemented` (ad-hoc priority over full-refresh), `minor_perf` (no rate-limit bucket — multiple batches add up at upstream)

**Mitigation type:** "needs priority queue / preemption mechanism for full-refresh vs. ad-hoc" and "needs rate-limit single bucket shared across all upstream fetch paths"

**Memory refs:** `memory/reference_sampling_api.md`, `memory/feedback_upstream_throttle_ceiling.md`

---

### Scenario 5: Long-run crash recovery — backend process dies mid full-refresh

**Current behavior:**

`RunManager.__init__` calls `_recover_orphan_running_runs()` at construction time (`app.py:4686`). This scans `store.list_runs_by_status("running")` and marks all such rows `"failed"` with message `"run interrupted by console restart; please rerun if needed"` (`app.py:4703-4718`). It also attempts `_terminate_pid_if_running(pid)` for any PID stored in the `process_pid` column.

**BatchRunManager state is in-memory only** (`self._batches: dict[str, dict[str, Any]]`, `app.py:3190`). On process death, all `_batches` state is lost. There is no persistence of batch-level queue.

**Chunk progress:** Chunks already written to `rawdata/` survive on disk (they are committed by `os.replace` inside the analyzer subprocess). The analyzer subprocess may still be running when the parent crashes (it's a separate OS process). On restart:
1. Parent marks the SQLite run row as `failed`.
2. Parent does not re-attach to the existing analyzer subprocess (no PID tracking after parent death).
3. The orphaned analyzer subprocess continues running, writing chunks and eventually writing `player_impact_summary.json` to `output_dir`. But no watcher thread (`_watch_run`) is alive to pick up the result.
4. The run row stays `failed` in SQLite; the partial summary.json sits on disk unclaimed.

**Resume from checkpoint:** The analyzer's `--resume-from-cache` flag causes it to read any already-completed chunks on restart. So a new operator-initiated batch for the same (machine, mode) will reuse those chunks. The progress (e.g., 147/393 machines) is NOT recoverable — the operator would need to restart the full-refresh manually, relying on per-machine cache reuse to fast-path already-completed machines.

**Hazard level:** `silent_fail` (orphaned analyzer subprocess; unclaimed summary.json) / `crash` if the batch progress state that planners are watching disappears

**Mitigation type:** "needs batch queue persistence to disk (e.g. queue JSON file)" and "needs resume-from-checkpoint logic for full-refresh (track completed machine set)"

**Memory refs:** `memory/feedback_no_silent_swallow.md`

---

### Scenario 6: In-flight fetch interrupted — planner deletes cache for cell X while fetch is in-flight

**Current behavior:**

The delete path at `DELETE /api/rawdata/{machine}` acquires `ops.acquire("delete_rawdata")` (`app.py:6269`). The sampling path (`POST /api/batch-run` → `BatchRunManager`) does NOT acquire `ops`. So they can run concurrently.

`_run_one` calls `_acquire_in_use(machine, mode)` at `app.py:3761`, which adds to `_IN_USE_MODES`. The `delete_rawdata` function checks `_load_rawdata_locks` but NOT `_IN_USE_MODES`. There is a comment at `app.py:2143-2151` that says `_IN_USE_MODES` is checked by `_auto_cleanup_for_space`, but `delete_rawdata` itself (`app.py:1040-1176`) does not check `_IN_USE_MODES`.

Therefore: if planner deletes rawdata for M14|1 while M14|1 is actively being sampled:
- The `delete_rawdata` function proceeds to call `_classify_chunks` and then `p.unlink()` for deletable+historical chunks.
- The analyzer subprocess writing new chunks to the same dir uses `os.replace(tmp, target)` for each chunk — atomic write. If a chunk was completed before the delete, it may get unlinked while the analyzer's resume-read hasn't cataloged it yet.
- New chunks being written (not yet `os.replace`d) are safe (they don't exist as final filenames yet).
- The sidecar `_chunks.json` may be updated by `bulk_remove_chunk_entries` during delete, while `update_chunk_entry` in the analyzer's worker is also trying to update the same sidecar — both hold `_sidecar_lock_for(mode_dir)`, so these serialize correctly within the process.

**Orphan locks:** If the process is killed mid-delete (not mid-fetch), no per-file lock is held after unlink. No orphan lock problem.

**Partial chunks:** If a chunk that was `os.replace`d successfully but not yet added to the sidecar is then unlinked by delete: the sidecar correctly reflects its absence (it was never added). The analyzer process, however, may have already loaded the chunk data into memory. The data is not lost from the sample (it's in memory), just the chunk file is gone.

**Hazard level:** `data_corruption` (delete during fetch can remove chunks the analyzer intends to resume from; the "usable_chunks" count becomes incorrect mid-flight; partial run data)

**Mitigation type:** "needs `_IN_USE_MODES` check in `delete_rawdata` before proceeding, same as `_auto_cleanup_for_space`"

**Memory refs:** `memory/feedback_enumerate_safety_paths.md`

---

### Scenario 7: Sidecar consistency — frontend opens at T while backend mid-write to `_chunks.json`

**Current behavior:**

`_write_sidecar_atomic` in `chunk_index.py:196-237` uses `tempfile.mkstemp + os.replace`. The `os.replace` is atomic on NTFS and ext4 — a reader either sees the old sidecar or the new one, never a partially-written file. The function retries `os.replace` up to 5 times with 50ms backoff if `PermissionError` is raised (Windows AV interference, `chunk_index.py:221-230`).

A frontend GET to `/api/rawdata/{machine}` calls `check_rawdata_status` → `get_chunks_index` → `load_chunks_index`. This reads the sidecar via `p.read_text(encoding="utf-8")`. On Windows, `read_text` holds the file handle open briefly. If `os.replace` fires at exactly that moment:
- Pre-replace: reader gets the old content (valid).
- Post-replace: reader gets the new content (valid).
- During replace: on NTFS, the replacement is atomic from the reader's perspective; the file descriptor points to the old inode until it's closed.

**`by_md5` index consistency:** When an older sidecar (no `by_md5` field) is loaded, `get_chunks_index` auto-rebuilds and persists. If two concurrent reads both hit the "stale, rebuild" path, they each call `build_chunks_index` which rescans the directory and calls `_write_sidecar_atomic` — both under `_sidecar_lock_for(mode_dir)` (`chunk_index.py:351`). The second writer wins (overwrites the first). Idempotent — both rebuilds from the same on-disk state produce the same result.

**Hazard level:** `safe` (atomic writes + lock serialize writes; reads see consistent snapshots)

**Mitigation type:** None required within single process.

**Memory refs:** `memory/reference_chunk_index_inverted_md5.md`

---

### Scenario 8: Subprocess / module-global landmines

**Current behavior per `memory/feedback_subprocess_import_suicide_and_module_globals.md`:**

#### Import-suicide pattern

`main.py:15` calls `create_app()` at module level. The comment at `main.py:1-16` explicitly notes this is intentional and tests should NOT import `main.py` — they import `app.py:create_app` directly. The historic `_recover_orphan_running_runs` / subprocess self-kill pattern is resolved: `RunManager._recover_orphan_running_runs` (`app.py:4686`) calls `_terminate_pid_if_running(pid)` on PIDs from the DB, not on `os.getpid()`. The comment in `main.py` confirms the `virtual_app.py` pattern (the original suicide) was fixed by separating `build_virtual_app()` from the import.

**Status: the import-suicide pattern is NOT present in `app.py` or `main.py`.** `main.py:15` `app = create_app()` is a top-level call, but `create_app()` does not call `_recover_orphan_running_runs` (that's in `RunManager.__init__`, called during `create_app`). The `_recover_orphan_running_runs` calls `_terminate_pid_if_running(pid)` on DB-stored PIDs — NOT on the current process.

#### Module-global `RAWDATA_ROOT`

`app.py:518`: `RAWDATA_ROOT = Path(os.getenv("SLOT_RAWDATA_ROOT", str(RAWDATA_ROOT_DEFAULT)))` — module-level global, set at import time from env.

`BatchRunManager.__init__` at `app.py:3181-3187` stores `self._rawdata_root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT`. When `create_app` calls `BatchRunManager(store, manager, cr, state_dir=sd, machines_config=mc, rawdata_root=rd_root)` at `app.py:3349-3352`, it passes `rd_root` explicitly, so `BatchRunManager` uses the injected path, not the module global. This matches the fix described in `memory/feedback_subprocess_import_suicide_and_module_globals.md`.

**However:** Several methods in `app.py` still reference the module-level `RAWDATA_ROOT` directly when called outside `BatchRunManager` context. For example `check_rawdata_status` at `app.py:695`: `root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` — callers that don't pass `rawdata_root` fall back to the module global. For the real console running as a single server with one `SLOT_RAWDATA_ROOT`, this is correct. Under multi-user deployment (single server, single `RAWDATA_ROOT`), this is consistent. **Not a bug in the deployment scenario.**

#### `_STATIC_ATTRS_CACHE`, `_MACHINES_SUMMARY_CACHE`, `_RAWDATA_OVERVIEW_CACHE`, `_LOCK_CACHE`

All four are module-level dicts (`app.py:1987`, `2030`, `2143`, `2178`). They are shared across all requests to the single `create_app()` instance. Under multi-user:
- Multiple concurrent reads to `_build_machines_summary` both check fingerprint and may both miss the cache and both run the rebuild. The rebuild is pure (reads files, doesn't mutate shared state until the final line `_MACHINES_SUMMARY_CACHE[cache_key] = ...`). Under GIL, dict assignment is atomic. Worst case: two concurrent rebuilds both compute and one overwrites the other. Idempotent — both produce identical results from the same file state.
- `_LOCK_CACHE` is read and written without a threading.Lock (`app.py:2185-2228`). `_load_rawdata_locks` reads `_LOCK_CACHE["data"]` without a lock; `_save_rawdata_locks` writes it without a lock. Under GIL, individual dict writes are atomic in CPython, but the check-then-write pattern (`if _LOCK_CACHE.get("mtime") == cur_mtime`) is not atomic. Two concurrent readers could both see a stale mtime and both reload — idempotent. One reader and one writer could conflict — writer sets new mtime + data, reader sees new mtime but not new data (reads happen in sequence under GIL). Extremely unlikely to cause real corruption, but technically a TOCTOU.

**Hazard level:** `safe` (import-suicide fixed; RAWDATA_ROOT correctly injected; cache module-globals have minor TOCTOU risk under GIL but practically idempotent)

**Mitigation type:** `_LOCK_CACHE` read-write could use a threading.Lock for correctness under high concurrency, but not urgent.

**Memory refs:** `memory/feedback_subprocess_import_suicide_and_module_globals.md`

---

### Scenario 9: Rate-limit shared bucket — 5 planners + full-refresh all calling upstream

**Current behavior:**

Each `POST /api/batch-run` spawns a `BatchRunManager` batch which starts N daemon threads (N = `req.concurrency`, default 3). Each thread calls `RunManager.start_run()` which spawns an analyzer subprocess (`app.py:4865`). Each analyzer subprocess runs its own `ThreadPoolExecutor(max_workers=batch_concurrency)` (default 8) making concurrent HTTP calls to `MultiRobotTestSpinVariant`.

Effective upstream concurrency from 5 planners × 3 batch_concurrency × 8 analyzer_concurrency = **120 concurrent upstream HTTP requests** against the same IP/endpoint.

Per `memory/reference_sampling_api.md`: upstream degrades from ~3.7k/s to ~0.7k/s under per-source rate limiting. Per `memory/feedback_upstream_throttle_ceiling.md`: once throttled, throughput stays at 5× below peak for hours.

There is **no shared rate-limit token bucket** anywhere in the current codebase. Each subprocess has its own connections and no awareness of other subprocesses' requests. There is no inter-process coordination.

**Additionally:** `POST /api/batch-run` fires an async pre-batch MD5 refresh thread (`app.py:5825-5838`): `_do_refresh_machines_md5()` which calls `_fetch_machine_config_md5()` — one additional upstream HTTP call per batch submission. With 5 planners submitting batches, this is 5 extra upstream calls that don't count against any budget.

**Hazard level:** `data_corruption` level effect: self-DoS — 5 concurrent planners can push all batches into the throttled regime (~0.7k/s combined), making a 1M-spin run that would take 5 minutes take 35 minutes, with timeout failures that look like upstream errors.

**Mitigation type:** "needs rate-limit single bucket shared across all fetch paths (all subprocesses + autotune) with foreground ad-hoc priority > full-refresh"

**Memory refs:** `memory/feedback_upstream_throttle_ceiling.md`, `memory/reference_sampling_api.md`

---

### Scenario 10: Disk pressure — long-run accumulating chunks

**Current behavior:**

`_auto_cleanup_for_space` (`app.py:2455`) is called inside `BatchRunManager._run_one` (`app.py:3719`) when `disk.free_gb < low_water` (default 5 GB). It deletes oldest-mtime deletable+historical chunks across all unlocked, not-in-use (machine, mode) pairs.

`_get_disk_space_info` uses `shutil.disk_usage` (`app.py:1234`). The disk-pressure check runs once per item's pre-flight (`app.py:3706-3746`), not continuously during the item's execution. A long-running chunk-write session can fill the disk between the pre-flight check and the actual writes.

Per the `app.py:3696-3705` thresholds:
- `SLOT_DISK_LOW_WATER_GB` (default 5): trigger cleanup
- `SLOT_DISK_TARGET_FREE_GB` (default 10): cleanup goal
- `SLOT_DISK_HARD_STOP_GB` (default 2): fail item if cleanup doesn't reach this

There is no background disk-pressure daemon. Cleanup only fires in the pre-flight of `_run_one`. If the backend is idle (no active batch), disk can fill without any cleanup.

No maximum chunk count limit per machine/mode — only the `min_retention_spins` guard (`_RAWDATA_MIN_RETENTION_SPINS_DEFAULT = 100_000`, `app.py:54`). A 393-machine full-refresh at 120 chunks × 5000 spins × 8 robots = 4.8M spins per mode per machine, across potentially multiple modes, can generate hundreds of GB before cleanup triggers.

**Hazard level:** `crash` (OS-level out-of-disk causes JSON write failures inside analyzer subprocess; analyzer exits non-zero; chunk integrity compromised)

**Mitigation type:** "needs continuous disk-pressure monitor / background daemon" and "needs explicit per-run or per-fleet chunk budget enforcement"

**Memory refs:** `memory/feedback_no_silent_swallow.md`

---

### Scenario 11: Config upload (new feature)

**Current behavior:**

No config upload endpoint exists. The brief defines a new dedup key `(config_id, machine, mode, upstream_md5)` (§5.7). Currently the dedup key is `(machine, mode, cfg_md5, code_md5)` — effectively `(machine, mode, upstream_md5_pair)`. No `config_id` axis.

What new surfaces are needed:
1. **Upload endpoint** (`POST /api/configs/upload`): accepts a config file, derives `config_id = hash(content)`, stores the file, returns `config_id`. Concurrent uploads of the same content must dedup to the same `config_id` — needs atomic "check-and-store" with a per-`config_id` lock.
2. **Config-to-rawdata association**: when a batch-run uses a config, the config_id must be recorded alongside the chunk's `cfg_md5`. Currently chunks record `_config_md5` (from upstream envelope) and `_code_md5`. Adding a new `_config_id` field requires either envelope-level changes (requires analyzer changes) or a sidecar-level annotation.
3. **Config persistence**: brief §5.5 says "config metadata persists as long as any related rawdata exists." Needs a config registry (JSON file or new SQLite table) that is not deleted when rawdata is deleted.
4. **Lock surfaces**: concurrent same-config upload from 2 planners → needs dedup at write time, not after.

**Hazard level:** `not_implemented`

**Mitigation type:** "needs new upload endpoint + config registry + per-config-id lock for dedup + config_id plumbed into chunk envelope or sidecar"

---

### Scenario 12: Report stale tagging — rawdata delete without report tag

**Current behavior:**

`delete_rawdata` (`app.py:1040-1176`) removes chunk files and updates `rawdata_index` entries. It does **not** read `reports/` or write any `underlying_removed=True` flag anywhere in the report directory tree. No such flag exists in the codebase.

`reports_retention.py:prune_versions` (`reports_retention.py:49`) deletes old version directories and rebuilds `index.json` + `latest.json`. No stale-tag writing here either.

The current stale-reporting mechanism is md5-based: `GET /api/reports/stale-count` (`app.py:5694`) compares each run row's `rawdata_config_md5` / `rawdata_code_md5` against the current `machines.json`. A report is flagged `stale_rawdata` if its md5 doesn't match current. But this flag means "sampled against an old server version" — not "the underlying chunks were deleted." These are different conditions.

When rawdata is deleted for M14|1:
- The existing reports under `reports/M14/mode_1/versions/` survive intact.
- The run rows in SQLite survive with `status=completed`.
- `rawdata_config_md5` / `rawdata_code_md5` in the run row still hold the md5 values from when sampling happened.
- Nothing marks these reports as "rawdata removed."
- Frontend would show them as valid historical reports indefinitely, even though re-generating them is now impossible without re-fetching.

**Hazard level:** `silent_fail` (reports appear valid when rawdata they depend on has been deleted; a planner attempting to re-generate a report from deleted rawdata gets a failed run, not a clear "underlying rawdata removed" message)

**Mitigation type:** "needs `underlying_removed` flag written to report summary/index when rawdata deleted; rawdata delete endpoint must walk `reports/<M>/mode_<N>/` and tag surviving reports"

**Memory refs:** `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md`

---

### Scenario 13: Concurrent batch analyze — 3 planners trigger different batch analyses simultaneously

**Current behavior:**

`POST /api/rawdata/batch-generate-report` calls `BatchGenerateManager.start()` which calls `self._ops.acquire("batch_generate_report")` (`app.py:2970`). `OperationCoordinator` is a **single-slot** boolean lock. Only one `batch_generate_report` operation can run at a time.

If planner B tries while planner A's batch-generate is running, B gets `{"status": "failed", "error": "system busy: batch_generate_report"}` immediately — the entire batch is rejected, not queued. This is intentional (current single-user design), but under multi-user it means only one planner at a time can regenerate reports.

`run_id` uniqueness: each item gets `uuid.uuid4().hex[:12]` as `run_id` (`app.py:2905`). Collision probability negligible.

`report_version` path: each item gets its own `rv_<ts>_<run_id[:8]>` directory (`app.py:4745`). Concurrent items for the same (machine, mode) write to different version directories. No path collision.

Worker processes: `ProcessPoolExecutor` with `max_workers=self._concurrency` (`app.py:3047-3053`). Each job runs `run_analyzer_job` in a separate process. The worker is initialized via `_pool_worker_init` which does `import fresh_slotlab.player_impact_analyzer as _mod` and caches it (`_batch_gen_worker.py:45-50`). The `sys.argv` swap (`_batch_gen_worker.py:104-106`) is per-job and guarded by `finally: sys.argv = orig_argv` (`_batch_gen_worker.py:249`). Since each job runs in its own spawned process (Windows uses `spawn` context, `app.py:3047`), `sys.argv` is process-local — no cross-job contamination.

**Hazard level:** `minor_perf` (second/third planner's batch-generate is rejected with 409 until the first completes; not queued)

**Mitigation type:** "needs queue or multi-slot for batch-generate so planners' analyses serialize without rejection"

---

### Scenario 14: Frontend live-status / polling — 5 planners watching status

**Current behavior:**

There is no SSE (Server-Sent Events) or WebSocket in the codebase. Status updates are delivered via **HTTP polling**. Each frontend instance polls independently:

- `GET /api/runs/{run_id}` — fetches run status
- `GET /api/batch-run/{batch_id}` — fetches batch status (sampling)
- A `fastTimer` (`app.js:7891`) fires `setInterval(() => { refreshCurrentRun().catch(() => {}); }, 1000)` every 1 second while a run is in `"running"` state.
- A `batchGeneratePollTimer` (`app.js:6559`) fires `setInterval` every ~2 seconds during batch-generate.

The `_autoRefreshedForRunId` one-shot flag (`app.js:6943-6959`) prevents duplicate tree-refreshes on transition from running → completed within a single browser tab. Per `memory/feedback_fasttimer_overlap_needs_oneshot.md`, this prevents overlap within one tab.

**Multi-user case:** 5 planners each have their own browser tab. Each tab independently fires `fastTimer` every 1 second if they have a running run to watch. 5 tabs × 1 req/s = 5 GET /api/runs/{id} requests/second to the uvicorn server. These are read-only SQLite reads (`StateStore.get_run` at `app.py:1543`). SQLite in WAL mode handles concurrent reads safely. Uvicorn default worker count is 1 (single worker for `reload=False`, `main.py:20-26`). All 5 GET requests are handled sequentially by the single async event loop. FastAPI + SQLite are not blocking IO calls — they use `sqlite3.connect()` which IS blocking and is called synchronously in the async handler, but it's fast (microseconds for a single row lookup).

**No broadcast mechanism:** If planner A's run completes, only planner A's tab detects this (they're watching their own `currentRunId`). Planner B watching the fleet via `/api/runs` list (if implemented) polls independently. There is no server-push. Fine for <10 users.

**Hazard level:** `safe` (5 planners × 1 req/s is easily handled; no shared mutable state from polling)

**Mitigation type:** None required for <10 users. For full-fleet-refresh broadcast: "needs a status endpoint that all planners poll for shared fleet-refresh progress"

**Memory refs:** `memory/feedback_fasttimer_overlap_needs_oneshot.md`

---

### Scenario 15: UI error-branch state reset — planner A's action changes server state; planner B's UI has stale view

**Current behavior:**

Per `memory/feedback_error_branch_resets_all_state.md`: error branches that do not reset all derived state cause the UI to display stale data. The fix cited (2026-04-20) was `_resetDebugPanelsToEmpty()` called in 404 and `!currentRunId` branches. This was a single-user fix.

Under multi-user: planner A triggers rawdata delete for M14|1. Planner B's browser has M14|1 loaded in the debug panel, showing KPI tiles computed from that rawdata. Planner B's UI does not know the rawdata was deleted — there is no server-push invalidation. On planner B's next polling tick (which polls `state.currentRunId`, not rawdata status), the polling does not re-fetch rawdata status. The KPI tiles remain showing data that no longer has underlying rawdata.

When planner B clicks "generate report," the backend returns 400 or 500 (no rawdata to analyze). The frontend error-branch resets the run panel but not the rawdata panel — planner B sees "failed" for the run but the rawdata panel still shows the deleted machine's metrics.

**Additionally:** `GET /api/rawdata/{machine}` is polled by the frontend on machine selection and when the rawdata panel is open. If planner B has the rawdata panel open but is not clicking anything, the panel is not refreshed unless B manually triggers a refresh or selects the machine again.

**Hazard level:** `minor_perf` (stale UI display, not data corruption; next user interaction forces re-fetch)

**Mitigation type:** "needs periodic rawdata-status invalidation when rawdata panel is open" or "needs server push (SSE) for rawdata delete events"

**Memory refs:** `memory/feedback_error_branch_resets_all_state.md`

---

### Scenario 16 (Discovered): Concurrent machines.json writes — md5 refresh race

**Current behavior (not covered by the 15 listed scenarios):**

`_do_refresh_machines_md5` at `app.py:8110` writes to `machines.json` via `Path(mc).write_text(...)` at `app.py:8216` — a **non-atomic write** (no tmp+replace pattern). If two concurrent MD5 refresh calls write simultaneously (one via explicit `POST /api/machines/refresh-md5`, one via the async pre-batch thread from `POST /api/batch-run`), the file may be corrupted (truncated or interleaved).

The pre-batch refresh fires a daemon thread (`app.py:5834`) that calls `_do_refresh_machines_md5(raise_on_error=False)`. This is NOT protected by the `ops` lock — it's explicitly made async to avoid blocking the batch-run response. The explicit `POST /api/machines/refresh-md5` is also not protected by `ops` — only `refresh_machine_halls` acquires `ops` (`app.py:5625`).

Concurrent `machines.json` writes from:
1. Pre-batch async thread (fires on every `POST /api/batch-run` that doesn't set `skip_md5_refresh=True`)
2. Explicit `POST /api/machines/refresh-md5`
3. Any future automated refresh path

These can race to `Path(mc).write_text(...)` simultaneously. On Windows, `write_text` uses `open(path, 'w')` which truncates the file before writing. If both calls have read the existing JSON and both are writing their updated version, the last write wins — the other's changes (updated md5 values) are lost silently. More dangerously, if write_1 truncates and starts writing while write_2 reads, write_2 reads a partial/empty JSON and `json.loads` raises `JSONDecodeError`, leading to `existing = {"machines": []}` fallback (`app.py:8213`). Then write_2 writes an empty machines list — all 393 machine rows are lost from `machines.json`.

**Hazard level:** `data_corruption` (concurrent md5 refresh can silently corrupt or truncate machines.json; 393 machine rows could be replaced with empty list)

**Mitigation type:** "needs atomic write (tmp+replace) for machines.json updates" and "needs per-file lock (or ops-coordinator gate) for all machines.json writers"

**Memory refs:** `memory/feedback_md5_granularity_and_stamping.md`

---

## §3 Hazard Summary Table

| # | Scenario | Hazard level | Mitigation type | Priority |
|---|----------|-------------|----------------|----------|
| 1a | Concurrent same-cell fetch (same cell) | `safe` | None needed | — |
| 1b | Distinct-cell concurrent fetch upstream rate | `minor_perf` | needs rate-limit single bucket | Medium |
| 2 | Fetch vs. analyze — auto-cleanup during batch-generate | `data_corruption` | `BatchGenerateManager` needs `_acquire_in_use` | High |
| 3a | Cache delete vs. report view | `safe` (reports survive) | None for reports | — |
| 3b | Cache delete vs. active fetch | `data_corruption` (Windows force path) | needs `_IN_USE_MODES` check in `delete_rawdata` | High |
| 3c | Report stale tagging missing | `not_implemented` | needs stale-tag write on rawdata delete | High |
| 4a | Ad-hoc fetch priority over full-refresh | `not_implemented` | needs priority queue / preemption | High |
| 4b | No upstream rate bucket across batches | `minor_perf` | needs rate-limit single bucket | Medium |
| 5 | Long-run crash recovery | `silent_fail` + `crash` | needs batch queue persistence + resume-from-checkpoint | High |
| 6 | In-flight fetch interrupted by delete | `data_corruption` | needs `_IN_USE_MODES` in `delete_rawdata` | High |
| 7 | Sidecar read during mid-write | `safe` | None needed | — |
| 8 | Module-global / import-suicide | `safe` (fixed) | Minor: `_LOCK_CACHE` could use threading.Lock | Low |
| 9 | Rate-limit shared bucket | `data_corruption` (self-DoS) | needs rate-limit single bucket fleet-wide | High |
| 10 | Disk pressure long-run | `crash` | needs background disk monitor + chunk budget | High |
| 11 | Config upload (new feature) | `not_implemented` | needs new endpoint + config registry + per-config-id lock | High |
| 12 | Report stale tagging (rawdata delete) | `silent_fail` | needs `underlying_removed` flag on rawdata delete | High |
| 13 | Concurrent batch analyze (3 planners) | `minor_perf` | needs queue for batch-generate | Medium |
| 14 | Frontend polling multi-user | `safe` | None for <10 users | — |
| 15 | UI error-branch stale view | `minor_perf` | needs rawdata-panel periodic refresh or SSE invalidation | Low |
| 16 | Concurrent machines.json writes | `data_corruption` | needs atomic write + single-writer gate for machines.json | Critical |

---

## §4 Items Deferred to W2 Designer

All mitigation designs are deferred to Wave 2. W1 identifies hazard type only.

**Types identified for W2 to design:**

1. **Rate-limit single bucket** — must be shared across: all `BatchRunManager` batches, all `run_auto_tune` parallel requests, pre-batch MD5 refresh, halls refresh. Must support foreground (ad-hoc planner) priority over background (full-refresh). Architecture question: token bucket in parent process with subprocess quota allocation, or proxy all upstream calls through a rate-limited parent-process sender.

2. **Per-cell `_IN_USE_MODES` enforcement in all delete paths** — `delete_rawdata` (explicit endpoint) and `force=True` path must both check `_IN_USE_MODES`. Same pattern as `_auto_cleanup_for_space`. W2 to enumerate all delete code paths (per `memory/feedback_enumerate_safety_paths.md`).

3. **`BatchGenerateManager` `_acquire_in_use` / `_release_in_use`** — batch-generate workers must register in `_IN_USE_MODES` so auto-cleanup skips their mode_dirs.

4. **Batch queue persistence** — full-fleet-refresh queue state must survive process death. Options include: JSON file with completed-machine set, SQLite batch-queue table. Must support resume from item N when restart happens at item N+k.

5. **Machines.json atomic write** — `_do_refresh_machines_md5` must use `tmp+os.replace` instead of `write_text`. Single writer must be enforced (ops lock, or dedicated mutex for machines.json).

6. **Report stale-tagging on rawdata delete** — `delete_rawdata` must walk `reports/<M>/mode_<N>/` for the affected mode and write `underlying_removed=True` into each surviving version's summary or a sidecar file (without deleting the report).

7. **Config upload endpoint + registry** — new endpoint, new storage layer (`config_id → file content`), plumbing `config_id` into the batch-run flow and chunk envelope or sidecar.

8. **Priority queue for ad-hoc vs. full-refresh** — `BatchRunManager` per-key lock currently rejects ad-hoc fetches for cells being processed by full-refresh. W2 to design preemption or priority-lane mechanism.

9. **Full-fleet-refresh endpoint** — does not exist. W2 to design as extension of `BatchRunManager.start_batch()` with 393-machine item list + crash-recoverable queue.

10. **Background disk monitor** — continuous check, not only pre-flight. W2 to decide: daemon thread vs. pre-flight check frequency increase vs. per-chunk disk check inside analyzer.

---

## §5 Observations Not in Scenarios

### Single uvicorn worker (not multi-worker)

`main.py:20-26` runs `uvicorn.run(..., reload=False)` with no `workers=` argument. Default is 1 worker process. All singletons (`StateStore`, `BatchRunManager`, `OperationCoordinator`, `_IN_USE_MODES`, `_SIDECAR_LOCKS`) live in one process. This is the correct architecture for the current design — all in-memory concurrency primitives assume single process. Adding `workers=N` would break everything (each worker would have its own `_IN_USE_MODES`, `OperationCoordinator`, etc.).

### SQLite WAL mode not explicitly enabled

`StateStore._connect()` at `app.py:1436-1438` calls `sqlite3.connect(self.db_path)` without enabling WAL mode (`PRAGMA journal_mode=WAL`). Default is DELETE mode. Under concurrent read+write from 10 planners, DELETE mode allows only one writer at a time and readers block during writes. For the current single-process asyncio model this is safe (GIL + single event loop), but adding true async SQLite support later would require WAL.

### `_do_refresh_machines_md5` called from daemon thread — no exception logging

`app.py:5825-5833`: the pre-batch async md5 refresh swallows all exceptions (`except Exception: pass`). Per `memory/feedback_no_silent_swallow.md`, this is a known anti-pattern. If the refresh fails (e.g., network timeout), the failure is invisible. The outcome is not logged to disk. Low severity for now (batch continues with stale md5); becomes higher severity when 5 planners are all triggering this.
