# 04 Deploy Architecture Proposal

> Wave 2 — Deploy Review (2026-05-15)
> Agent: arch-designer
> Input: 01_deploy_pipeline_map.md + 02_deploy_surface_taxonomy.md + 03_deploy_concurrency_blast_radius.md
> User guidance: "继续。补充需求，现框架需要重构的话就做，不要保守。"
> Stack constraint: FastAPI + uvicorn + SQLite (WAL) + ProcessPoolExecutor + subprocess.Popen + threading.Lock. No Postgres, Redis, Celery, Docker, NSSM, nginx.

---

## §1 Executive Summary

The existing console is a correctly-structured single-process FastAPI/uvicorn server with one critical data-corruption hazard (`machines.json` non-atomic write, `03_deploy_concurrency_blast_radius.md §2 Scenario 16`), five High-severity concurrency gaps, and a cluster of write-unprotected config file endpoints — all invisible in single-user operation but collectively dangerous under <10 concurrent planners. The proposal addresses these through three unified architectural mechanisms: (1) a `CellLockRegistry` that subsumes all existing in-memory and file-level per-cell locking into a single authoritative registry; (2) a `ConfigFileWriter` that wraps every JSON config file in atomic tmp+replace plus a per-file `threading.Lock`; and (3) a `FleetRefreshQueue` — a crash-recoverable SQLite-backed persistent queue for the 393-machine full-refresh long-run. New features (config upload, 4-tuple dedup, rate-limit shared bucket, report stale-tagging, service wrapper) are layered on top of this corrected foundation in four migration phases. No process model changes, no framework replacement, no user concept introduced.

---

## §2 Current State Confirmation

The server (`src/web_console/backend/main.py:15`, `app.py:5286`) runs as a single uvicorn process on `127.0.0.1:8877`, serving a no-build static frontend from `src/web_console/frontend/` and a FastAPI backend with 49 HTTP endpoints (`01_deploy_pipeline_map.md §4`). All stateful singletons — `StateStore` (SQLite), `RunManager` (subprocess orchestration), `BatchRunManager` (per-cell sampling), `BatchGenerateManager` (ProcessPoolExecutor report regen), `OperationCoordinator` (single-flag ops mutex) — are instantiated once per `create_app()` call and live in-process. Three classes of sub-process are spawned: (a) analyzer subprocesses via `subprocess.Popen` for sampling and from-cache report generation; (b) `ProcessPoolExecutor(spawn)` workers for batch-regen; (c) post-hook inference subprocesses per run. In-memory concurrency is handled by `threading.Lock` and `threading.Semaphore`; file atomicity is handled by `os.replace(tmp, target)` on most JSON files — but NOT on `configs/machines.json` (`app.py:8216`) and NOT on `configs/servers.json` (`app.py:513`). There is no auth, no user concept, no LAN binding (`127.0.0.1` only), and no crash-recoverable long-run queue. See `01_deploy_pipeline_map.md §1-§10` for the full process topology, persistence schema, and module-global hazard list.

---

## §3 Real Gaps (Synthesized from 02/03)

### 3.1 Critical (1)

**C1 — `machines.json` non-atomic write (Scenario 16)**

`_do_refresh_machines_md5()` at `app.py:8216` calls `Path(mc).write_text(...)` — plain file truncation + write, no temp file, no process-level mutex. Two concurrent callers (pre-batch async refresh thread from `app.py:5834` + explicit `POST /api/machines/refresh-md5`) race to truncate-then-write the same file. If write_1 truncates while write_2 is mid-`json.loads`, write_2 reads partial JSON, falls back to `{"machines": []}` at `app.py:8213`, then writes an empty machines list — silently wiping all 393 machine entries from the fleet registry. No error is logged; the backend continues serving an empty fleet until a manual fix.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 16`; `app.py:8210-8220`; `memory/feedback_md5_granularity_and_stamping.md`.

---

### 3.2 High (6)

**H1 — `BatchGenerateManager` missing `_acquire_in_use`**

Batch-generate-report workers run in `ProcessPoolExecutor` subprocesses and read chunk files from `rawdata/<M>/mode_<N>/`. They do NOT call `_acquire_in_use()` before starting (`app.py:2862-3158`, no such call found). If `_auto_cleanup_for_space` fires concurrently (triggered from any active `BatchRunManager._run_one`), it checks `_get_in_use_snapshot()` — which returns only modes registered by sampling runs — and may delete chunks currently being read by the generate-report subprocess. On Windows with NTFS, an open file handle prevents immediate deletion but `shutil.rmtree` raises `PermissionError`, leaving the chunk tree in a partially deleted state.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 2`; `02_deploy_surface_taxonomy.md §3.3 item 9`.

**H2 — `delete_rawdata` does not check `_IN_USE_MODES`**

`delete_rawdata()` at `app.py:1040` proceeds to unlink chunk files without consulting `_IN_USE_MODES`. The sampling path registers in `_IN_USE_MODES` (via `_acquire_in_use` called at `app.py:3761`), but the delete path ignores it. Concurrent delete + active sampling for the same cell results in the analyzer finding its `--resume-from-cache` chunks partially deleted mid-run.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 6`; `02_deploy_surface_taxonomy.md §3.3 item 10`.

**H3 — `rawdata/_index.json` global index lost-update under N concurrent writers**

`rawdata_index.py:update_entry()` does read-modify-write + `os.replace`. The file contains all (machine, mode) entries. Two concurrent writers for different cells both read `{M14|1, M15|1}`, both merge their own new entry, both write — the second write overwrites the first, silently dropping one entry. This is a realistic race under the 4-worker `ProcessPoolExecutor` completing items simultaneously.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 2`; `02_deploy_surface_taxonomy.md §3.3 item 3`; `rawdata_index.py:182-203`.

**H4 — No rate-limit shared bucket across concurrent analyzer subprocesses**

5 planners × 3 batch concurrency × 8 analyzer concurrency = 120 concurrent upstream HTTP requests from the same server IP. The upstream can sustain ~3.7k/s fresh but drops to ~0.7k/s throttled; once throttled it stays throttled for hours. No token bucket exists in the codebase. Each subprocess fires independently.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 9`; `02_deploy_surface_taxonomy.md §3.3 item 11`; `memory/feedback_upstream_throttle_ceiling.md`.

**H5 — Long-run crash recovery: no persisted queue, no resume**

`BatchRunManager._batches` is in-memory (`app.py:3190`). On process death, all batch state is lost. Orphaned analyzer subprocesses continue writing chunks but no watcher thread picks up results; run rows stay `failed` in SQLite; completed chunk files are unclaimed. A 393-machine full-refresh losing 6 hours of progress on a server restart is unacceptable per brief §5.8.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 5`; `02_deploy_surface_taxonomy.md §3.4 (fleet refresh gap)`.

**H6 — Disk pressure: background daemon absent; per-fleet chunk budget not enforced**

`_auto_cleanup_for_space` fires only inside `BatchRunManager._run_one` pre-flight (`app.py:3719`). During a full-fleet-refresh (393 machines), disk can fill between cleanup invocations. A failed `os.replace` inside the analyzer subprocess leaves a `.tmp` orphan and the analyzer exits non-zero, silently corrupting the chunk set.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 10`; `02_deploy_surface_taxonomy.md §3.3 item 10`.

---

### 3.3 Unsafe-Today Clusters (44 surfaces → 5 clusters)

**Cluster A — Config file write races (10 surfaces, 3.3 items 5/6/7)**

All 10 surfaces share one pattern: a JSON config file written by multiple endpoints without a per-file mutex.

Files affected: `configs/machines.json`, `configs/servers.json`, `configs/rawdata_locks.json`, `configs/machine_halls.json`, `configs/machines_static.json`, `state/console/settings.json`.

Why they fail: some (e.g. `rawdata_locks.json`, `settings.json`) already use `os.replace(tmp, target)` for atomic write, but the read-modify-write cycle has no mutex. `servers.json` and `machines.json` lack even the atomic write. Two concurrent callers each read, each compute the merged state, and one's changes are silently overwritten.

Writers: `POST /api/servers`, `PUT /api/servers/{id}`, `PUT /api/servers/{id}/set-default`, `DELETE /api/servers/{id}`, `POST /api/rawdata/{machine}/mode/{mode}/lock`, `DELETE /api/rawdata/{machine}/mode/{mode}/lock`, `PUT /api/settings`, `POST /api/machines/halls/refresh`, `POST /api/machines/refresh-md5`, pre-batch MD5 refresh async thread.

Single fix: `ConfigFileWriter` (§4.2 below) — one `threading.Lock` per logical config file + `tmp+os.replace` write for all.

**Cluster B — `OperationCoordinator` single-slot bottleneck (7 surfaces, 02 §3.3 item 1)**

`OperationCoordinator` is a single boolean (`app.py:4000`). All of: `generate_report` (async), `batch_generate_report`, `delete_run`, `delete_report_version`, `cache_cleanup`, `prune_versions`, `reports_cleanup`, `import_reports` share this one slot. Under multi-user, planner A's `batch_generate_report` for M14 blocks planner B's `delete_rawdata` for M99 — even though they share no data.

The bottleneck is `OperationCoordinator`'s global granularity. The correct granularity is per-cell for operations that are cell-scoped, and global only for truly global operations (disk-wide cleanup).

Single fix: Expand `CellLockRegistry` (§4.1 below) to handle cell-scoped operations at per-cell granularity; retain global flag only for disk-wide cleanup and `prune_versions`/`reports_cleanup` that scan all cells.

**Cluster C — `_IN_USE_MODES` scope gaps (5 surfaces, 02 §3.3 items 2/3/4)**

`_IN_USE_MODES` correctly blocks auto-cleanup from sampling's mode dirs (`app.py:2152-2168`). But four callers bypass it: `BatchGenerateManager` workers (H1 above), `delete_rawdata` endpoint (H2 above), `DELETE /api/rawdata/{machine}` (no check), `DELETE /api/machines/{machine}/all-data` (no check). The `_IN_USE_MODES` concept is sound; the problem is incomplete enrollment.

Single fix: `CellLockRegistry` makes enrollment mandatory and complete (§4.1 below) — every mutating access to a (machine, mode) cell goes through the registry.

**Cluster D — Report index/latest.json non-atomic concurrent writes (5 surfaces)**

`reports/<M>/mode_<N>/index.json` and `latest.json` are written by `_run_generate_report` and `_finalize_batch_gen_item`. These are `path.write_text()` calls (not `tmp+os.replace`). Source: `app.py:7031-7033`, `app.py:7312-7314`. If two concurrent generate-report jobs finalize for the same cell (possible when `OperationCoordinator` is made per-cell scoped), both finalize paths race on these two files.

Single fix: wrap all report index writes in `tmp+os.replace` (same `ConfigFileWriter` pattern, or inline fix in `_update_report_index`).

**Cluster E — `chart.js` CDN dependency (1 surface, 01 §10 item 8)**

`frontend/index.html:8` loads `chart.js` from `cdn.jsdelivr.net`. An intranet server without internet access will fail to load the chart library on first page load, silently breaking all chart panels.

Single fix: vendor `chart.js` into `src/web_console/frontend/vendor/chart.min.js` and update the `<script>` tag to the local path. One-time file add; no architecture change.

---

### 3.4 New Surfaces Required (9)

Per `02_deploy_surface_taxonomy.md §2.7` and `00_deploy_brief.md §2`:

1. `POST /api/configs/upload` — config upload endpoint
2. `GET /api/configs` — list uploaded configs
3. `GET /api/configs/{config_id}` — get specific config
4. `POST /api/fleet/refresh` — trigger full-fleet sampling
5. `GET /api/fleet/refresh` — poll fleet refresh progress
6. `DELETE /api/fleet/refresh` — cancel fleet refresh (sets cancel flag in queue)
7. Fleet refresh crash-recovery (startup background task)
8. Report stale-tagging on rawdata delete (extension to `delete_rawdata`)
9. Dedup key `(config_id, machine, mode, upstream_md5)` registry

---

## §4 Architectural Decisions

### 4.1 Cell-Level Concurrency — Unified `CellLockRegistry`

#### Problem

Today: `_IN_USE_MODES` (set, app.py:2152), `BatchRunManager._busy_keys` (set, app.py:3198), `OperationCoordinator` (single bool, app.py:4000), and `_sidecar_lock_for` (per-path dict, chunk_index.py:91) are four independent systems tracking overlapping concerns. `_IN_USE_MODES` is missing from delete paths (H2). `OperationCoordinator` is too coarse (Cluster B). `_busy_keys` is only within one `BatchRunManager` instance. No single source of truth exists for "who owns a (machine, mode) cell right now."

Source: `03_deploy_concurrency_blast_radius.md §2 Scenarios 2, 6, 13`; `02_deploy_surface_taxonomy.md §3.3 items 1-4`.

#### Design

Introduce `CellLockRegistry` as the single authoritative gatekeeper for all mutating operations on a `(machine, mode)` cell.

```
src/web_console/backend/cell_lock_registry.py
```

**Schema (in-memory, process-local):**

```python
# Pseudocode — not a real file
class CellOperation(Enum):
    SAMPLING    = "sampling"     # BatchRunManager: analyzer subprocess writing chunks
    GENERATING  = "generating"   # RunManager or BatchGenerateManager: reading chunks + writing report
    DELETING    = "deleting"     # delete_rawdata: unlinking chunks + updating index

class CellLockRegistry:
    _registry: dict[tuple[str, int], set[CellOperation]]
    _lock: threading.Lock
    # Global-scope flags (not per-cell):
    _global_lock: dict[str, threading.Lock]  # keyed by global op name
    _global_busy: dict[str, bool]            # "disk_cleanup", "prune_all", etc.
```

**Invariants:**

1. `SAMPLING` and `DELETING` are mutually exclusive per cell. `_try_acquire(cell, DELETING)` returns `False` if any `SAMPLING` is active for that cell, and vice versa.
2. `SAMPLING` and `GENERATING` can coexist for different cells but NOT for the same cell (analyzer reading from-cache + generator reading same chunks race on sidecar). Actually: they CAN coexist if the generator uses `--from-cache` and reads a snapshot (atomic sidecar read). The sidecar's `os.replace` ensures a consistent read. Review: scenario 2 audit found this safe (`03_deploy_concurrency_blast_radius.md §2 Scenario 2: "planner B triggers new chunk write; planner A's generate-report sees an atomically-named file or not yet"`). **Conclusion: SAMPLING + GENERATING on same cell: allowed (sidecar read is atomic, new chunks are beyond the generator's snapshot).**
3. `DELETING` and `GENERATING` are mutually exclusive per cell — deletion removes files the generator depends on.
4. Multiple simultaneous `SAMPLING` registrations for the same cell are prohibited (per existing `_busy_keys` behavior).
5. Multiple simultaneous `GENERATING` registrations for the same cell are prohibited (race on `index.json`/`latest.json`).
6. Global ops (`disk_cleanup`, `prune_all`, `reports_cleanup`) acquire the global flag, not per-cell. They respect the cell registry's `_get_all_active_cells()` snapshot to skip cells in use.

**API:**

```python
# Pseudocode
class CellLockRegistry:
    def try_acquire_cell(self, machine: str, mode: int,
                         op: CellOperation) -> bool:
        # Returns True + registers op if allowed; False if blocked.
        ...

    def release_cell(self, machine: str, mode: int, op: CellOperation) -> None:
        ...

    def get_active_cells(self, op: CellOperation | None = None
                         ) -> set[tuple[str, int]]:
        # Snapshot for auto-cleanup to skip in-use cells.
        ...

    def try_acquire_global(self, name: str) -> bool:
        # For disk_cleanup, prune_all, etc. Returns False if busy.
        ...

    def release_global(self, name: str) -> None:
        ...

    def snapshot(self) -> dict:
        # For GET /api/system-state to report active ops.
        ...
```

**Callers that MUST be updated to use `CellLockRegistry`:**

| Caller | Current mechanism | New mechanism |
|--------|-------------------|---------------|
| `BatchRunManager._run_one` | `_busy_keys` + `_acquire_in_use` | `registry.try_acquire_cell(..., SAMPLING)` |
| `RunManager.start_run` (ad-hoc generate-report, from cache) | `OperationCoordinator.acquire` (global!) | `registry.try_acquire_cell(..., GENERATING)` |
| `BatchGenerateManager._run` workers | `OperationCoordinator.acquire` (global!) + NO `_acquire_in_use` | `registry.try_acquire_cell(..., GENERATING)` per item |
| `delete_rawdata` function | Nothing | `registry.try_acquire_cell(..., DELETING)` before unlinking |
| `DELETE /api/rawdata/{machine}` | `OperationCoordinator.acquire` | `registry.try_acquire_cell(..., DELETING)` |
| `DELETE /api/machines/{machine}/all-data` | `OperationCoordinator.acquire` (global) | `registry.try_acquire_cell(..., DELETING)` for each mode |
| `DELETE /api/runs/{run_id}` | `OperationCoordinator.acquire` (global) | `registry.try_acquire_cell(..., GENERATING)` for the cell |
| `DELETE /api/reports/{machine}/{mode}/{version}` | `OperationCoordinator.acquire` (global) | `registry.try_acquire_cell(..., GENERATING)` for cell |
| `_auto_cleanup_for_space` | `_get_in_use_snapshot()` | `registry.get_active_cells()` |
| `POST /api/cache/cleanup` | `OperationCoordinator.acquire` (global) | `registry.try_acquire_global("disk_cleanup")` |
| `POST /api/maintenance/prune-versions` | `OperationCoordinator.acquire` (global) | `registry.try_acquire_global("prune_versions")` |
| `POST /api/reports/cleanup` | `OperationCoordinator.acquire` (global) | `registry.try_acquire_global("reports_cleanup")` |
| `POST /api/reports/import` | `OperationCoordinator.acquire` (global) | `registry.try_acquire_global("import_reports")` |
| `POST /api/autotune` | `OperationCoordinator.acquire` (global) | `registry.try_acquire_global("autotune")` |

**OperationCoordinator fate:** Retained as-is for backward compat during Phase 2 migration. After full migration, it is deprecated and can be removed in a later cleanup pass. No callers break if it is retained alongside `CellLockRegistry` since the new code uses the registry instead.

**Response to 409:** All callers that fail `try_acquire*` return HTTP 409 with `{"error": "cell_busy", "cell": "M14|1", "op": "sampling"}` or `{"error": "global_busy", "op": "disk_cleanup"}`. Frontend shows this as a transient "system busy" notice, not a permanent error.

---

#### Alternatives for §4.1

**Alt A (recommended above): Single-class `CellLockRegistry` subsuming all existing primitives**

Pros: One place to reason about cell ownership; `_IN_USE_MODES` and `_busy_keys` are deleted (no stale paths); `OperationCoordinator` becomes per-cell where appropriate; audit-friendly (`snapshot()` gives full visibility).

Cons: Requires touching every caller in a single phase (Phase 2); more code to change.

**Alt B: Patch individual gaps without unified registry**

Add `_acquire_in_use` call to `BatchGenerateManager._run` workers; add `_IN_USE_MODES` check to `delete_rawdata`. Leave `OperationCoordinator` global. Leave `_busy_keys` separate.

Pros: Minimal diff; no refactor risk.

Cons: Five separate systems remain; future callers may miss one; the `OperationCoordinator` bottleneck (Cluster B) is not solved — planners still queue globally. This is the "conservative" option explicitly rejected by user ("不要保守").

**Alt C: Per-cell SQLite row for lock state**

Store lock state in `console.db` — a `cell_locks` table with `(machine, mode, op, acquired_at, pid)`. Every acquire/release is a DB write.

Pros: Cross-restart durable; visible in DB tooling.

Cons: Adds DB roundtrips on every chunk write (thousands during full-refresh); SQLite WAL handles concurrent reads but serializes writes — creating a write bottleneck that defeats the concurrency model. The comment at `app.py:2151` correctly says "on crash, restart clears it — safer than persisting a stale lock." A crashed process cannot release a DB lock; manual intervention needed. Not worth the cost.

**Decision: Alt A.** The `CellLockRegistry` is a pure in-memory Python object, replacing fragmented primitives without adding any storage layer. The refactor is bounded (one module, ~15 call sites). Phase 2 delivers this.

---

### 4.2 Atomic Config File Writes — `ConfigFileWriter`

#### Problem

`configs/machines.json` uses `write_text` (non-atomic, Critical C1). `configs/servers.json` uses `write_text` (non-atomic). `configs/rawdata_locks.json` uses `tmp+os.replace` but no mutex over the read-modify-write cycle. Seven other config files have similar patterns (Cluster A).

Source: `03_deploy_concurrency_blast_radius.md Scenario 16, Scenario 1b`; `app.py:8216`, `app.py:513`, `app.py:2213-2228`.

#### Design

Introduce a lightweight module-level registry of per-file `threading.Lock` objects, plus a helper that enforces `tmp+os.replace`:

```
src/web_console/backend/config_writer.py
```

```python
# Pseudocode — algorithm sketch
_FILE_LOCKS: dict[str, threading.Lock] = {}
_REGISTRY_GUARD = threading.Lock()

def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _REGISTRY_GUARD:
        if key not in _FILE_LOCKS:
            _FILE_LOCKS[key] = threading.Lock()
        return _FILE_LOCKS[key]

def atomic_json_write(path: Path, data: dict) -> None:
    """Thread-safe atomic JSON write: lock -> serialize -> tmp -> os.replace."""
    lock = _lock_for(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise

def atomic_json_read_modify_write(path: Path, modifier: Callable[[dict], dict]) -> dict:
    """Thread-safe read-modify-write. Lock held across read+modify+write."""
    lock = _lock_for(path)
    with lock:
        # Read under lock — no concurrent write can observe partial state
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            existing = {}
        updated = modifier(existing)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise
        return updated
```

**Migration for Critical C1 (machines.json):**

Replace in `_do_refresh_machines_md5()` at `app.py:8210-8220`:

```python
# Before (non-atomic, Critical C1):
existing = json.loads(Path(mc).read_text(encoding="utf-8"))
existing, stats = apply_md5_refresh(existing, data, variants_map)
Path(mc).write_text(json.dumps(existing, ...) + "\n", encoding="utf-8")

# After (atomic_json_read_modify_write):
def _modifier(existing):
    return apply_md5_refresh(existing or {"machines": []}, data, variants_map)[0]
result = atomic_json_read_modify_write(Path(mc), _modifier)
stats = apply_md5_refresh(json.loads(Path(mc).read_text()), data, variants_map)[1]
# Note: stats computation is a separate pure read after write — acceptable;
# stats are observability-only, not write-critical.
```

**Migration for `save_servers()` at `app.py:510-515`:**

```python
# Before:
target.write_text(json.dumps(data, indent=2, ...) + "\n", encoding="utf-8")

# After:
atomic_json_write(target, data)
```

**Files that need `atomic_json_write` migration:**

| File | Current writer | Current atomic? | Fix needed |
|------|---------------|----------------|------------|
| `configs/machines.json` | `_do_refresh_machines_md5` | No (write_text) | read-modify-write + lock |
| `configs/servers.json` | `save_servers()` | No (write_text) | atomic_json_write |
| `configs/rawdata_locks.json` | `_save_rawdata_locks()` | write+replace but no lock | read-modify-write + lock |
| `configs/machine_halls.json` | `halls/refresh` | No (write_text) | atomic_json_write |
| `configs/machines_static.json` | `_save_static_attrs()` | tmp+replace | Add lock |
| `state/console/settings.json` | `_save_settings()` | os.replace | Add lock |
| `reports/<M>/mode_<N>/index.json` | `_update_report_index` | write_text | atomic_json_write |
| `reports/<M>/mode_<N>/latest.json` | `_update_report_index` | write_text | atomic_json_write |

**`_rawdata_index.py` concurrent writer problem (H3):**

`rawdata_index.update_entry()` does read-modify-write on the global `_index.json`. The file is read, one entry is updated, and the full file is written back. Under N concurrent ProcessPoolExecutor workers completing simultaneously, this races.

Solution: add a module-level `_INDEX_LOCK = threading.Lock()` to `rawdata_index.py` and wrap `update_entry()` and `remove_entry()` with it. This is process-local (all workers in `ProcessPoolExecutor(spawn)` have their own process, so the lock only helps within-process callers). For cross-process workers: the `_save_index` already uses `os.replace` atomicity. The `update_entry` implementation does read-modify-write + replace — if two spawned processes race, one's update is lost. Solution for cross-process: make each worker's `update_entry` retry on mtime-change (read again if mtime changed since we started), up to 3 retries with 10ms backoff. This makes the index eventually consistent under concurrent workers, which is acceptable since `rawdata_index` is explicitly documented as a "derived cache" (`rawdata_index.py:28-35`).

```python
# Pseudocode retry in update_entry():
def update_entry(rawdata_root, machine, mode, chunk_dir):
    for attempt in range(3):
        pre_mtime = _index_mtime(rawdata_root)
        entry = _scan_mode_dir(chunk_dir)
        data = load_index(rawdata_root)
        post_mtime = _index_mtime(rawdata_root)
        if post_mtime != pre_mtime and attempt < 2:
            time.sleep(0.01 * (attempt + 1))
            continue  # retry: someone else updated between our read and write
        key = entry_key(machine, mode)
        data["entries"][key] = entry if entry else data["entries"].pop(key, None)
        _save_index(rawdata_root, data)
        break
```

This handles the ProcessPoolExecutor cross-process race without adding any new mechanism.

---

### 4.3 Config Upload + 4-Tuple Dedup

#### Problem

No config upload endpoint exists. Current dedup key is `(machine, mode, cfg_md5, code_md5)`. Brief requires `(config_id, machine, mode, upstream_md5)` where `config_id = hash(file_content)` and `upstream_md5 = server-side config md5` (the current `cfg_md5`). `_derive_local_cfg_md5()` at `app.py:426` already computes `sha1(content)[:8]` — this is the seed.

Source: `02_deploy_surface_taxonomy.md §2.7`; `03_deploy_concurrency_blast_radius.md Scenario 11`; `00_deploy_brief.md §5.5-5.7`.

#### Config Object Design

```
configs/uploaded_configs/
    <config_id>.json          # Content file (the actual machine config)
    _registry.json            # Metadata registry
```

`_registry.json` schema:
```json
{
  "_version": 1,
  "configs": {
    "<config_id>": {
      "config_id": "<sha1_16hex>",
      "display_name": "M14_custom_v2",
      "uploaded_at": "2026-05-15T...",
      "content_sha1": "<sha1_40hex>",
      "size_bytes": 4096,
      "rawdata_count": 3
    }
  }
}
```

`config_id` computation:
```python
config_id = sha1(file_content.encode("utf-8")).hexdigest()  # 40 hex chars
```

Full SHA-1 (40 chars), not truncated — avoids collision risk across large fleets. `display_name` is provided by the caller and stored as-is (duplicates allowed per brief §5.5).

**Upload algorithm (pseudocode):**

```python
@app.post("/api/configs/upload")
async def upload_config(request: Request) -> dict:
    body = await request.body()
    content_str = body.decode("utf-8")
    config_id = hashlib.sha1(content_str.encode("utf-8")).hexdigest()

    def _upsert_registry(registry: dict) -> dict:
        if config_id in registry.get("configs", {}):
            # Already exists — dedup: return existing without writing file again
            return registry  # no-op modification
        # New config — write content file first
        content_path = CONFIGS_UPLOAD_DIR / f"{config_id}.json"
        atomic_json_write(content_path, json.loads(content_str))
        registry.setdefault("configs", {})[config_id] = {
            "config_id": config_id,
            "display_name": display_name,  # from query param or body field
            "uploaded_at": utc_now(),
            "content_sha1": config_id,
            "size_bytes": len(body),
            "rawdata_count": 0,
        }
        return registry

    # atomic_json_read_modify_write holds the lock across check + write:
    atomic_json_read_modify_write(CONFIGS_REGISTRY_PATH, _upsert_registry)
    return {"config_id": config_id, "status": "ok"}
```

This uses `atomic_json_read_modify_write` from §4.2, which holds `_lock_for(CONFIGS_REGISTRY_PATH)` across the full check-and-write. Two concurrent uploads of the same content: one wins the lock, writes the file + registry entry; the other acquires the lock, reads the registry, finds the entry already exists, returns without double-writing.

**4-Tuple dedup integration with `BatchRunItem`:**

Today `BatchRunItem` has `machine_config: str | None` (inline JSON at `app.py:1351`). New field: `config_id: str | None`. When `config_id` is set, the backend looks up `CONFIGS_UPLOAD_DIR / f"{config_id}.json"` and passes it as `--machine-config-file` to the analyzer. The dedup check before starting a new batch-run:

```python
dedup_key = (config_id or "default", machine, mode, upstream_md5)
# Check rawdata bucket: chunks with matching config_id in sidecar's by_config_id index
# If sufficient matching chunks exist: skip upstream sampling, use cache
```

**Chunk sidecar extension:**

Add `config_id` field to each chunk entry in `_chunks.json`:

```json
{
  "chunks": {
    "chunk_0001.json": {
      "idx": 1, "cfg_md5": "...", "code_md5": "...",
      "config_id": "null",          // "null" for server-default config
      "spin_times": 1000, ...
    }
  },
  "by_config_id": {
    "null": ["chunk_0001.json"],
    "<config_id_sha1>": ["chunk_0002.json"]
  }
}
```

`"null"` (string literal) represents "server-default config, no upload". This preserves backward compat — existing chunks that lack `config_id` are treated as `"null"`.

**Config persistence rule (brief §5.5):** Config metadata in `_registry.json` is never deleted by any backend operation. The `rawdata_count` field is updated by `delete_rawdata` (decrement) and by new-chunk commits (increment). When `rawdata_count` drops to 0, the config_id entry remains in the registry (the display_name and history are kept). Physical config file remains at `CONFIGS_UPLOAD_DIR/<config_id>.json`. No `DELETE /api/configs` endpoint is exposed.

---

### 4.4 Fleet Refresh Persistent Queue + Resume

#### Problem

No fleet refresh endpoint. No crash-recoverable long-run queue. `BatchRunManager` state is in-memory only. Brief requires: on-demand one-shot, crash-recoverable, per-machine retry, foreground-priority < ad-hoc, progress visible to all planners.

Source: `03_deploy_concurrency_blast_radius.md Scenario 5`; `02_deploy_surface_taxonomy.md §2.7`; `00_deploy_brief.md §5.8`.

#### Alternatives for Fleet Refresh Queue Persistence

**Alt Q1 (recommended): SQLite table `fleet_refresh_queue`**

Use the existing `console.db` with a new table. Fits the stack constraint. SQLite WAL handles concurrent reads (all planners polling status) with single-writer serialization.

Schema:
```sql
CREATE TABLE IF NOT EXISTS fleet_refresh_queue (
    queue_id TEXT PRIMARY KEY,         -- uuid per refresh session
    started_at TEXT NOT NULL,
    status TEXT NOT NULL,              -- "running" | "completed" | "cancelled" | "failed"
    total_items INTEGER NOT NULL,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    config_source TEXT NOT NULL DEFAULT "server_default",  -- or config_id
    server_id TEXT,
    cancelled_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS fleet_refresh_items (
    queue_id TEXT NOT NULL REFERENCES fleet_refresh_queue(queue_id),
    machine TEXT NOT NULL,
    mode INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT "pending",  -- "pending" | "running" | "completed" | "failed" | "skipped"
    run_id TEXT,                             -- links to existing `runs` table
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (queue_id, machine, mode)
);
```

**Alt Q2: JSON file `state/console/fleet_refresh_queue.json`**

Single JSON file with full queue state. Write-on-every-status-change. Simple but: (a) file grows large (393 items × status updates); (b) concurrent status reads (all planners polling) compete with status writes (worker completions) — requires a global lock that serializes all 393 status updates; (c) no indexing, so resuming requires full-file parse.

Cons outweigh pros — SQLite is already in the stack and handles exactly this pattern better.

**Alt Q3: In-memory with periodic JSON snapshot**

Keep `BatchRunManager._batches` in-memory, add a background thread writing a JSON snapshot every 30 seconds. On restart, read the snapshot.

Cons: Up to 30s of progress lost on crash; JSON snapshot races with concurrent updates (same Cluster A problem); the snapshot thread is another moving part. Not recommended.

**Decision: Alt Q1 (SQLite).**

#### Resume Algorithm (Pseudocode)

```python
# On startup: StateStore.__init__ runs _recover_fleet_refresh()
def _recover_fleet_refresh(db_path: Path) -> None:
    """On restart: find any queue_id in status='running'; resume it."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT queue_id FROM fleet_refresh_queue WHERE status='running' LIMIT 1"
        ).fetchone()
        if row:
            queue_id = row[0]
            # Mark all items that were 'running' at crash time as 'pending' again:
            conn.execute(
                "UPDATE fleet_refresh_items SET status='pending', run_id=NULL "
                "WHERE queue_id=? AND status='running'",
                (queue_id,)
            )
            conn.commit()
            # Signal the FleetRefreshManager to resume from this queue_id:
            fleet_mgr.schedule_resume(queue_id)
    finally:
        conn.close()

# FleetRefreshManager.run_queue(queue_id):
def run_queue(queue_id: str) -> None:
    """Background daemon thread. Consumes pending items from DB queue."""
    while True:
        item = _next_pending_item(queue_id)  # SELECT ... WHERE status='pending' LIMIT 1
        if item is None:
            _mark_queue_completed(queue_id)
            return

        machine, mode = item["machine"], item["mode"]

        # Priority check: if an ad-hoc planner fetch is active for this cell,
        # skip (yield) and come back to it later (put at back of iteration)
        if cell_registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING):
            _mark_item_running(queue_id, machine, mode)
            run_id = _start_batch_run_item(machine, mode, queue_id)
            _wait_for_run(run_id)
            result = _get_run_result(run_id)
            if result["status"] == "completed":
                _mark_item_completed(queue_id, machine, mode, run_id)
            else:
                attempt = _increment_attempt(queue_id, machine, mode)
                if attempt >= MAX_RETRIES:
                    _mark_item_skipped(queue_id, machine, mode, result["error"])
                else:
                    _mark_item_pending(queue_id, machine, mode)  # retry
            cell_registry.release_cell(machine, mode, CellOperation.SAMPLING)
        else:
            # Cell busy (ad-hoc fetch active) — yield and retry later
            time.sleep(YIELD_SLEEP_S)  # e.g. 5 seconds

        # Rate-limit: apply token bucket between items (§4.5)
        rate_limiter.wait_for_token(priority=PRIORITY_LOW)
```

**Single-instance enforcement:** Only one `fleet_refresh_queue` row with `status='running'` is allowed. The `POST /api/fleet/refresh` endpoint checks for this before creating a new queue:
```python
running = conn.execute(
    "SELECT queue_id FROM fleet_refresh_queue WHERE status='running' LIMIT 1"
).fetchone()
if running:
    return {"status": "already_running", "queue_id": running[0]}
```

Additional planners who hit `POST /api/fleet/refresh` while one is running receive `{"status": "already_running", "queue_id": "..."}` — they can use `GET /api/fleet/refresh` to attach to the running progress.

**Per-machine failure + retry:** `MAX_RETRIES = 3`. After 3 failed attempts, item is `skipped`. The final summary reports all skipped items so the operator can investigate.

---

### 4.5 Rate-Limit Shared Bucket + Priority

#### Problem

120 concurrent upstream requests from 5 planners can self-DoS the server into throttled mode (~0.7k/s vs. ~3.7k/s). No shared token bucket exists. Source: `03_deploy_concurrency_blast_radius.md Scenario 9`.

#### Design

A token bucket implemented as a parent-process module-level singleton, consumed by all callers that start analyzer subprocesses. The bucket is NOT in the subprocess — it is in the parent FastAPI process, governing how many new analyzer subprocesses (or new batch-run items) can be started per second.

**Why parent-process, not subprocess?**

Subprocesses have no shared memory. Inter-process token buckets require IPC (pipe, socket, shared memory). The simplest approach on the existing stack: throttle at the subprocess-launch level (parent controls the rate at which it spawns new batch items), not at the HTTP-request level within the subprocess. The upstream's actual concurrency is `batch_concurrency × N_running_analyzers`. By limiting N_running_analyzers (through the token bucket that governs item dispatch), we indirectly cap the upstream load.

**Token bucket algorithm:**

```python
# src/web_console/backend/rate_limiter.py  (new module)
class TokenBucket:
    """Thread-safe token bucket for upstream sampling item dispatch.

    capacity:     max burst tokens (items that can start simultaneously)
    refill_rate:  tokens per second added back (sustained throughput cap)
    priority lanes:
        FOREGROUND (ad-hoc planner): consumes 1 token; waits up to wait_s
        BACKGROUND (fleet refresh):  consumes 1 token; waits indefinitely
    """
    _tokens: float
    _capacity: int
    _refill_rate: float         # tokens / second
    _last_refill: float         # time.monotonic()
    _lock: threading.Lock

    def wait_for_token(self, priority: str = "foreground",
                       timeout: float | None = None) -> bool:
        """Block until a token is available (or timeout).
        Returns True if token acquired; False if timed out."""
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
            sleep_s = 1.0 / self._refill_rate if self._refill_rate > 0 else 1.0
            if deadline and time.monotonic() + sleep_s > deadline:
                return False  # timeout
            time.sleep(min(sleep_s, 0.2))

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now
```

**Default parameters:**

- `capacity = 10` — burst: up to 10 items can be dispatched before throttle kicks in
- `refill_rate = 3.0` — 3 new items per second sustained (3 new analyzers launching per second; each adds ~8 upstream connections at peak, so 24 connections/s peak, within the ~1k/s outer limit)
- Foreground `timeout = 30.0` seconds — ad-hoc planner waits up to 30s for a token, then gets 503 with "upstream rate limit; retry in {N}s"
- Background (fleet refresh) `timeout = None` — fleet refresh item dispatch waits indefinitely

**Foreground priority over background:**

The foreground caller calls `wait_for_token(priority="foreground", timeout=30.0)`. The background (fleet refresh) loop calls `wait_for_token(priority="background")` with no timeout. Since foreground has a deadline and background does not, foreground is more time-sensitive. Priority is implemented by giving foreground callers a separate "fast lane" token reservation:

```python
# Variant with priority lanes:
# Keep 2 tokens reserved for foreground. Background only consumes tokens
# above the foreground_reserve threshold.
_FOREGROUND_RESERVE = 2  # tokens reserved for ad-hoc callers

def wait_for_token(self, priority="background"):
    threshold = 1.0 if priority == "foreground" else self._foreground_reserve + 1.0
    while True:
        with self._lock:
            self._refill()
            if self._tokens >= threshold:
                self._tokens -= 1.0
                return True
        time.sleep(0.1)
```

Background items wait until tokens exceed `FOREGROUND_RESERVE + 1`, ensuring foreground callers always have `FOREGROUND_RESERVE` tokens available without waiting.

**Integration points:**

- `BatchRunManager._run_one`: call `rate_limiter.wait_for_token("foreground")` before `RunManager.start_run()`
- `FleetRefreshManager.run_queue`: call `rate_limiter.wait_for_token("background")` before each item dispatch

Token bucket is a module-level singleton (like `_IN_USE_MODES`) initialized in `create_app()` and injected into `BatchRunManager` and `FleetRefreshManager`.

---

### 4.6 Report Stale-Tagging

#### Problem

`delete_rawdata` removes chunks but does not tag surviving reports as `underlying_removed=True`. Reports appear valid indefinitely after rawdata deletion.

Source: `03_deploy_concurrency_blast_radius.md Scenario 12`; `02_deploy_surface_taxonomy.md §3.4`; `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md`.

#### Design

Add `underlying_removed` flag to two locations on rawdata delete:

**Location 1: `reports/<M>/mode_<N>/index.json`**

Each entry in `index.json` (a list) gains: `"underlying_removed": false` (new field, default false). When rawdata for `(machine, mode)` is deleted, walk `reports/<machine>/mode_<N>/index.json`, set `underlying_removed: true` on all entries, write atomically. No report files are deleted.

**Location 2: SQLite `runs` table**

Add a new column: `ALTER TABLE runs ADD COLUMN underlying_removed INTEGER NOT NULL DEFAULT 0`. When rawdata is deleted, update all `runs` rows where `machine=<M> AND mode=<N>` and `status='completed'` to `underlying_removed=1`.

**Implementation in `delete_rawdata()`:**

```python
# After existing chunk deletion logic (inside delete_rawdata), append:
def _tag_reports_stale(machine: str, mode: int, reports_root: Path, store: StateStore) -> None:
    """Tag all reports for (machine, mode) as underlying_removed=True."""
    index_path = reports_root / machine / f"mode_{mode}" / "index.json"
    if index_path.exists():
        def _mark_stale(data):
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict):
                        entry["underlying_removed"] = True
            return data
        try:
            atomic_json_read_modify_write(index_path, _mark_stale)
        except Exception:
            pass  # best-effort; report stale tag is informational
    # Tag SQLite rows
    store.mark_runs_underlying_removed(machine, mode)
```

`_tag_reports_stale` is called from `delete_rawdata` (both the force and non-force paths), and from `DELETE /api/rawdata/{machine}` and `DELETE /api/machines/{machine}/all-data`. Per `memory/feedback_enumerate_safety_paths.md`, all three delete paths must be updated — not just one.

**Frontend impact:**

`GET /api/reports/{machine}/{mode}` reads `index.json`. Entries with `underlying_removed: true` are returned as-is. The frontend renders a visual indicator ("历史快照 — 原始数据已删除") on those entries. This is a read-path-only change; no new endpoint needed.

**Invariant:** `delete_rawdata` always calls `_tag_reports_stale` regardless of whether any report exists. The function is idempotent (setting `true` on an already-`true` entry is a no-op).

---

### 4.7 Service Wrapper + Intranet Binding

#### Problem

uvicorn binds to `127.0.0.1` (single-user loopback). LAN planners cannot reach it. No auto-restart on terminal close. Source: `01_deploy_pipeline_map.md §2`, `§9`; `01_deploy_pipeline_map.md §10 items 9-10`.

#### Alternatives for Service Wrapper

**Alt S1 (recommended): PowerShell `start_console.ps1` extended + Windows Task Scheduler**

No new software. `start_console.ps1` already exists and starts uvicorn. The Task Scheduler is built into every Windows machine.

Task Scheduler setup: one task, trigger = "At system startup" or "On user logon", action = `powershell.exe -ExecutionPolicy Bypass -File "C:\...\scripts\start_console.ps1"`, run as a specific Windows user (the server machine's service account or the user who owns the project directory).

`start_console.ps1` changes:
1. Change `--host 127.0.0.1` to `--host 0.0.0.0` (or `$env:SLOT_BIND_HOST` with default `0.0.0.0`)
2. Add `--port $env:SLOT_BIND_PORT` (default `8877`)
3. Add stdout/stderr redirect to a rotating log file: `| Tee-Object -FilePath $LOG_FILE -Append`
4. Add a restart loop: if uvicorn exits with non-zero, sleep 5s and relaunch (up to 5 restarts before giving up)

```powershell
# Pseudocode for restart loop in start_console.ps1
$MAX_RESTARTS = 5
$restarts = 0
while ($restarts -lt $MAX_RESTARTS) {
    python -m uvicorn src.web_console.backend.main:app `
        --host ($env:SLOT_BIND_HOST ?? "0.0.0.0") `
        --port ($env:SLOT_BIND_PORT ?? "8877") `
        --log-level info `
        2>&1 | Tee-Object -FilePath $LOG_FILE -Append
    if ($LASTEXITCODE -eq 0) { break }  # graceful stop
    $restarts++
    Start-Sleep -Seconds 5
}
```

**Alt S2: Python `subprocess.Popen` watchdog script**

A separate Python script (e.g. `scripts/watchdog.py`) that runs `subprocess.Popen(["python", "-m", "uvicorn", ...])`, monitors the subprocess, and restarts it on non-zero exit. Task Scheduler runs the watchdog, not uvicorn directly. Adds a Python layer for slightly better control (exponential backoff, health check before restart).

Pros: Portable to non-Windows; programmatic restart logic easier than PowerShell.
Cons: One more script to maintain; PowerShell restart loop is sufficient for simple case.

**Alt S3: NSSM or WinSW**

Third-party service wrappers that register uvicorn as a Windows service. 

Status: **explicitly excluded by stack constraint** ("No NSSM" per user guidance in brief preamble).

**Decision: Alt S1 (PowerShell restart loop + Task Scheduler).**

**`chart.js` CDN fix (Cluster E):**

Download `chart.min.js` (current version used by the codebase, from `cdn.jsdelivr.net`) into `src/web_console/frontend/vendor/chart.min.js`. Update `index.html:8`:

```html
<!-- Before: -->
<script src="https://cdn.jsdelivr.net/...chart.min.js"></script>
<!-- After: -->
<script src="/console/vendor/chart.min.js"></script>
```

The `StaticFiles` mount at `app.py:5392` already serves everything under `frontend/` at `/console/`, so `vendor/chart.min.js` is served automatically.

**SQLite WAL mode (observation, `03_deploy_concurrency_blast_radius.md §5`):**

`StateStore._connect()` opens SQLite without WAL mode. Enable WAL at first connection in `StateStore._init_db()`:

```python
def _init_db(self) -> None:
    conn = self._connect()
    conn.execute("PRAGMA journal_mode=WAL")  # Add this line
    conn.execute("PRAGMA busy_timeout=5000") # 5 second busy timeout
    # ... existing table creation ...
```

WAL mode allows concurrent reads + serialized writes, which is exactly the multi-user read-heavy pattern (10 planners × 3 poll timers each = 30 reads/s on SQLite).

---

### 4.8 Background Disk Monitor

**Problem:** `_auto_cleanup_for_space` fires only in `BatchRunManager._run_one` pre-flight. During a full-fleet-refresh (393 machines), disk fills between per-item checks. Source: `03_deploy_concurrency_blast_radius.md Scenario 10`.

**Design:** Add a background daemon thread started in `create_app()` alongside the existing `_prewarm_machines_summary()` thread:

```python
# In create_app():
def _disk_monitor_daemon(rawdata_root, machines_config, state_dir):
    """Background daemon: check disk every 60 seconds.
    Fires cleanup if below SLOT_DISK_LOW_WATER_GB."""
    while True:
        time.sleep(60)
        try:
            usage = shutil.disk_usage(str(rawdata_root))
            free_gb = usage.free / (1024**3)
            if free_gb < SLOT_DISK_LOW_WATER_GB:
                result = _auto_cleanup_for_space(
                    rawdata_root=rawdata_root,
                    machines_config=machines_config,
                    retention=_load_settings(state_dir / "settings.json").get(
                        "min_retention_spins", _RAWDATA_MIN_RETENTION_SPINS_DEFAULT
                    ),
                    target_free_gb=SLOT_DISK_TARGET_FREE_GB,
                )
                # Persist outcome (per memory/feedback_no_silent_swallow.md):
                diag = state_dir / "disk_monitor_last.json"
                diag.write_text(json.dumps({
                    "ts": utc_now(), **result
                }), encoding="utf-8")
        except Exception as exc:
            diag = state_dir / "disk_monitor_error.json"
            try:
                diag.write_text(json.dumps({
                    "ts": utc_now(), "error": str(exc)
                }), encoding="utf-8")
            except Exception:
                pass

_threading.Thread(
    target=_disk_monitor_daemon,
    args=(RAWDATA_ROOT, MACHINES_CONFIG, STATE_DIR),
    daemon=True,
    name="disk-monitor",
).start()
```

The 60-second interval is configurable via `SLOT_DISK_MONITOR_INTERVAL_S` env var. Outcome is persisted to `state/console/disk_monitor_last.json` and `disk_monitor_error.json` (satisfying `memory/feedback_no_silent_swallow.md`). `GET /api/system-state` reads and includes the last disk monitor outcome in its response.

---

## §5 Test Plan (5 Dimensions)

### 5.1 Design-Level Invariants

These invariants must hold at all times under concurrent multi-user operation. W3 validator can walk each one per the hazard scenarios in 03.

| Invariant ID | Statement | Source hazard |
|---|---|---|
| **INV-1** | For any `(machine, mode)`, at most ONE `SAMPLING` and ONE `GENERATING` registration can be active simultaneously; `DELETING` is exclusive with both | Scenario 1a, 2, 6 |
| **INV-2** | `delete_rawdata(machine, mode)` returns 409 (not proceeds) when `CellLockRegistry` has any active registration for `(machine, mode)` | Scenario 6, H2 |
| **INV-3** | `configs/machines.json` write is always atomic (tmp+os.replace) and serialized (per-file lock) | Scenario 16, C1 |
| **INV-4** | `rawdata/_index.json` write is retried on concurrent-write detection (mtime changed between read and write) | Scenario 2, H3 |
| **INV-5** | For any `config_id`, concurrent uploads of the same content produce exactly one registry entry and one content file | Scenario 11 |
| **INV-6** | `(config_id, machine, mode, upstream_md5)` 4-tuple uniquely identifies a rawdata bucket; two concurrent batch-runs with the same 4-tuple produce at most one active fetch | Brief §5.7 |
| **INV-7** | Deleting rawdata for `(machine, mode)` always sets `underlying_removed=true` on all index entries for that cell | Scenario 12, brief §5.6 |
| **INV-8** | Fleet refresh has at most one `status='running'` queue at any time | Brief §5.8 |
| **INV-9** | Fleet refresh resumes after process death: all items that were `running` at crash are re-queued as `pending` | Scenario 5 |
| **INV-10** | Foreground (ad-hoc) token bucket callers wait at most 30s; background (fleet refresh) callers never starve but wait when foreground reserve < 2 tokens | §4.5 |
| **INV-11** | `BatchGenerateManager` registers `GENERATING` in `CellLockRegistry` before each worker's `_acquire_in_use` equivalent | Scenario 2, H1 |
| **INV-12** | `_auto_cleanup_for_space` always skips cells with any active `CellLockRegistry` registration | Scenario 2, 6 |
| **INV-13** | report `index.json` and `latest.json` writes are always atomic (tmp+os.replace) | Cluster D |
| **INV-14** | `configs/servers.json` write is always atomic (tmp+os.replace, per-file lock) | Cluster A |
| **INV-15** | SQLite `console.db` is opened with `journal_mode=WAL` and `busy_timeout=5000` | §4.7 |

---

### 5.2 Impl-Level Tests (Unit / Integration / E2E)

Each test group follows the inject-bug → red → revert → green verification per `memory/feedback_enumerate_safety_paths.md` and `memory/feedback_perf_claim_needs_e2e_event_stream.md`.

**Group T1 — `CellLockRegistry` unit tests** (`tests/backend/test_cell_lock_registry.py`)

```
test_acquire_sampling_blocks_deleting_same_cell
    # Inject bug: remove mutual-exclusion check → test fails
test_acquire_generating_blocks_deleting_same_cell
test_two_sampling_same_cell_rejected
test_sampling_and_generating_different_cells_both_allowed
test_global_acquire_disk_cleanup_blocks_second
test_snapshot_reflects_active_registrations
test_release_clears_registration
test_acquire_after_release_succeeds
```

**Group T2 — `ConfigFileWriter` atomic write tests** (`tests/backend/test_config_writer.py`)

```
test_atomic_json_write_produces_correct_file
test_concurrent_writes_no_torn_file
    # Spawn 10 threads each calling atomic_json_write; assert final file parseable
    # Inject bug: replace os.replace with write_text → race → torn file detected
test_read_modify_write_concurrent_no_lost_update
    # Two threads each add a key to a dict; both keys must appear in final file
test_read_modify_write_handles_missing_file
test_atomic_write_cleans_up_tmp_on_error
```

**Group T3 — `machines.json` atomic write (Critical C1)** (`tests/backend/test_machines_json_atomic.py`)

```
test_refresh_machines_md5_atomic_under_concurrent_calls
    # POST /api/machines/refresh-md5 called from 3 concurrent threads
    # Assert: machines.json always parseable; no entry count regression
    # Inject bug: revert to write_text → corrupted JSON detected in ≤3 calls
test_pre_batch_md5_thread_does_not_race_with_explicit_refresh
```

**Group T4 — `rawdata_index.py` concurrent write** (`tests/backend/test_rawdata_index_concurrent.py`)

```
test_concurrent_update_entry_no_lost_entries
    # 4 threads each update a different (machine, mode) entry concurrently
    # Assert: all 4 entries present in final index
    # Inject bug: remove retry loop → flaky test catches ~1 lost entry per 10 runs
test_update_entry_retry_on_mtime_change
test_remove_entry_concurrent_with_update_entry
```

**Group T5 — `delete_rawdata` + `CellLockRegistry`** (`tests/backend/test_delete_rawdata_cell_lock.py`)

```
test_delete_blocked_when_sampling_active
    # Register SAMPLING for M14|1; call delete_rawdata(M14, 1); assert 409
    # Inject bug: remove _IN_USE_MODES check from delete_rawdata → test passes without 409 (fail)
test_delete_proceeds_when_no_active_registration
test_delete_tags_reports_stale
    # After delete, assert index.json entries have underlying_removed=True
    # Assert SQLite runs rows have underlying_removed=1
    # Inject bug: remove _tag_reports_stale call → fields stay False (test red)
test_delete_tags_all_three_paths
    # Path 1: delete_rawdata(force=False)
    # Path 2: delete_rawdata(force=True)
    # Path 3: DELETE /api/machines/{machine}/all-data
    # Each path must tag reports stale (per memory/feedback_enumerate_safety_paths.md)
```

**Group T6 — Config upload dedup** (`tests/backend/test_config_upload.py`)

```
test_upload_same_content_twice_returns_same_config_id
test_concurrent_upload_same_content_produces_single_file
    # 5 concurrent POST /api/configs/upload with identical body
    # Assert: exactly 1 file in configs/uploaded_configs/
    # Assert: registry has exactly 1 entry for that config_id
    # Inject bug: remove lock from _upsert_registry → 5 writes, duplicate file
test_upload_different_content_produces_different_config_ids
test_config_id_is_full_sha1_of_content
test_config_persists_after_rawdata_deletion
```

**Group T7 — Fleet refresh queue (SQLite-based)** (`tests/backend/test_fleet_refresh_queue.py`)

```
test_start_fleet_refresh_creates_queue_and_items
test_second_start_while_running_returns_already_running
test_resume_after_simulated_crash
    # Create queue with 3 items: 1 completed, 1 running-at-crash, 1 pending
    # Simulate crash: directly update DB to leave 1 item as "running"
    # Call _recover_fleet_refresh()
    # Assert: the "running" item is now "pending"
    # Assert: the "completed" item remains "completed"
    # Inject bug: remove _recover_fleet_refresh() call → running item never resumes
test_fleet_refresh_marks_item_completed_on_success
test_fleet_refresh_retries_item_up_to_MAX_RETRIES
test_fleet_refresh_skips_item_after_max_retries
test_cancel_sets_queue_status_cancelled
```

**Group T8 — Token bucket rate limiter** (`tests/backend/test_rate_limiter.py`)

```
test_foreground_token_acquired_within_timeout
test_background_waits_when_foreground_reserve_held
    # Fill bucket to foreground_reserve tokens only
    # Background caller should block; foreground should not
test_background_proceeds_when_tokens_above_reserve
test_concurrent_foreground_callers_all_get_tokens_eventually
test_timeout_returns_false_not_exception
```

**Group T9 — E2E subprocess test** (`tests/backend/test_e2e_multi_user.py`)

```
test_two_concurrent_batch_runs_different_cells_both_complete
    # Spawn real uvicorn; POST /api/batch-run for M14|1 and M15|1 simultaneously
    # Both must reach status="completed" without corrupting each other's sidecars
    # Per memory/feedback_perf_claim_needs_e2e_event_stream.md
test_delete_rawdata_blocked_during_active_sampling
    # Spawn batch-run for M14|1; immediately DELETE /api/rawdata/M14
    # Assert 409 response (not successful delete)
test_machines_json_parseable_after_concurrent_md5_refresh
    # 3 concurrent POST /api/machines/refresh-md5; assert machines.json always parseable
```

---

### 5.3 Deploy-Smoke Tests

**Boot smoke** (runs after `start_console.ps1` on the server, before handing to planners):

```
smoke_01_health_check
    # GET http://localhost:8877/api/health returns 200
smoke_02_frontend_loads
    # GET http://localhost:8877/console/ returns 200; body contains <html>
smoke_03_chart_js_loads_locally
    # GET http://localhost:8877/console/vendor/chart.min.js returns 200
    # (Verifies CDN dependency removed — key intranet requirement)
smoke_04_machines_list_non_empty
    # GET /api/machines returns list with len > 0
smoke_05_sqlite_wal_mode
    # GET /api/health or direct DB check; PRAGMA journal_mode returns "wal"
smoke_06_lan_reachable
    # From a second machine on LAN: curl http://<server-ip>:8877/api/health
```

**Rolling upgrade drill (for continuous update deployments):**

1. Download new code version to server.
2. Run `install.bat` (deps update).
3. `SLOT_RAWDATA_ROOT` env var points to the stable shared rawdata directory.
4. Stop existing uvicorn (Task Scheduler stop, or CTRL+C on console).
5. Start new uvicorn via Task Scheduler.
6. Verify: `smoke_01` through `smoke_06` pass.
7. Verify: `GET /api/versions/current` returns updated analyzer version.

**Rollback drill:**

1. Stop new uvicorn.
2. `git checkout <previous-tag>` or restore from backup `.tar`.
3. Restart uvicorn.
4. Verify `smoke_01` through `smoke_06`.
5. SQLite schema migrations are forward-only (ALTER TABLE ADD COLUMN with DEFAULT); rollback leaves extra columns which are ignored by the older code.

**Windows-specific failure modes to verify:**

- `PermissionError` on `os.replace` when Windows Defender or antivirus has the `.tmp` file open: `ConfigFileWriter` retries up to 5× with 50ms backoff (same pattern as `chunk_index.py:221-230`).
- Task Scheduler running uvicorn under a different user than the file owner: verify `SLOT_RAWDATA_ROOT` path accessible by the scheduler user.
- Port 8877 already in use after reboot (port guard in `start_console.ps1` still needed): keep existing `Get-NetTCPConnection` check.

---

### 5.4 Runtime Monitoring (Silent Failure Surfacing)

Per `memory/feedback_no_silent_swallow.md`, every background task failure must persist diagnostic to disk AND surface to UI.

| Task | Failure persisted to | Surfaced in UI via |
|------|---------------------|-------------------|
| Pre-batch MD5 refresh thread | `state/console/md5_refresh_error.json` | `GET /api/system-state` includes `md5_refresh_error` field |
| Disk monitor daemon | `state/console/disk_monitor_last.json`, `disk_monitor_error.json` | `GET /api/system-state` includes `disk_monitor` field |
| Fleet refresh item failure | SQLite `fleet_refresh_items.last_error` | `GET /api/fleet/refresh` returns `{failed_items: [{machine, mode, error}]}` |
| Post-analyzer inference failure | `reports/<M>/mode_<N>/versions/<rv>/_post_hook.json` | `GET /api/runs/{run_id}` includes `post_hook_error` field |
| `_auto_cleanup_for_space` failure | `state/console/cleanup_error.json` | `GET /api/system-state` includes `cleanup_error` |

**Pre-batch MD5 thread error surfacing (fixes current `except Exception: pass` at `app.py:5830`):**

```python
def _refresh_md5_async() -> None:
    try:
        _do_refresh_machines_md5(server_id=_refresh_sid, raise_on_error=False)
    except Exception as exc:
        diag = STATE_DIR / "md5_refresh_error.json"
        try:
            diag.write_text(json.dumps({
                "ts": utc_now(),
                "error": str(exc),
                "server_id": _refresh_sid
            }), encoding="utf-8")
        except Exception:
            pass
```

---

### 5.5 Regression防再踩 — Memory Feedback → Test Mapping

| Memory file | Root cause | Corresponding test |
|---|---|---|
| `feedback_subprocess_import_suicide_and_module_globals.md` | Module-global `RAWDATA_ROOT` / `build_virtual_app()` self-kill | `test_e2e_multi_user.py::test_virtual_app_import_does_not_trigger_build`; validate `main.py` still safe to import by subprocess |
| `feedback_md5_granularity_and_stamping.md` | Per-mode md5 hash granularity; delegate path re-stamps | `test_cell_lock_registry.py` + machines.json atomic tests verify md5 writes are per-mode-consistent after concurrent refresh |
| `feedback_md5_is_a_tag_not_a_destruction_signal.md` | md5 must not trigger auto-delete | `test_delete_rawdata_cell_lock.py::test_delete_tags_reports_stale`; assert reports survive rawdata delete with `underlying_removed` flag |
| `feedback_no_silent_swallow.md` | Post-hook silent failure | `test_backend_post_hook_failure_persisted.py`: inject post-hook failure, assert `_post_hook.json` written with `rc` + `stderr_tail` |
| `feedback_error_branch_resets_all_state.md` | 404 path clears run ID but not derived panels | `test_frontend_error_branch_reset.js`: simulate 404 from `/api/runs/{id}`; assert KPI tiles + rawdata panel + payIdOverview all clear |
| `feedback_fasttimer_overlap_needs_oneshot.md` | `setInterval` polling overlap; duplicate transition fire | `test_frontend_fasttimer.js`: simulate 3 concurrent fast-timer ticks during running→completed transition; assert tree-refresh fires exactly once |
| `feedback_enumerate_safety_paths.md` | Missing lock guard on third delete path | `test_delete_rawdata_cell_lock.py::test_delete_tags_all_three_paths` verifies all 3 delete paths tag reports |
| `feedback_no_parallel_panel_impl.md` | New panel reimplements sibling renderer | New fleet-refresh UI panel must reuse the existing `batchRunProgress` renderer; code review gate: no new `<td>` builder, no new i18n keys |
| `feedback_invariant_with_fallback_hides_drift.md` | Fallback bucket hides attribution drift | Not directly relevant to deploy; relevant to analyzer — existing verifier tests cover this |
| `reference_chunk_index_inverted_md5.md` | Per-mode threading lock; cross-process gap | `test_rawdata_index_concurrent.py::test_concurrent_update_entry_no_lost_entries`; inject bug by removing retry → flaky failure confirms test catches race |

---

## §6 Migration Phases

### Phase 1: Critical Fix + Atomic Writes Cluster (Backward-Compatible)

**Deliverables:**

1. `ConfigFileWriter` module (`src/web_console/backend/config_writer.py`) with `atomic_json_write` and `atomic_json_read_modify_write`.
2. Migrate `_do_refresh_machines_md5()` to use `atomic_json_read_modify_write` (fixes Critical C1, `app.py:8216`).
3. Migrate `save_servers()` to use `atomic_json_write` (`app.py:510-515`).
4. Migrate `_save_rawdata_locks()` to use `atomic_json_read_modify_write` (fixes race on read-modify-write cycle).
5. Migrate `_update_report_index` to use `atomic_json_write` for `index.json` and `latest.json` (fixes Cluster D).
6. Migrate `machines_static.json`, `machine_halls.json`, `settings.json` writes to `atomic_json_write`.
7. Add retry logic to `rawdata_index.update_entry()` for cross-process concurrent write (H3).
8. Add `_LOCK_CACHE` threading.Lock (minor TOCTOU fix, `03_deploy_concurrency_blast_radius.md Scenario 8`).
9. Vendor `chart.min.js` into `frontend/vendor/` (Cluster E).
10. Enable SQLite WAL mode + busy_timeout in `StateStore._init_db()`.
11. Add pre-batch MD5 thread error persisting to `state/console/md5_refresh_error.json`.

**Revert plan:** All changes are additive (new module + migrated function bodies). Revert = `git revert <phase-1-commit>`. No schema changes in Phase 1 — SQLite WAL pragma is safe to revert (WAL files are cleaned up by SQLite on next EXCLUSIVE connection). `rawdata/` and `reports/` are unmodified.

**Verification step:** Run `smoke_01` through `smoke_05` (excluding `smoke_06` LAN binding not yet done). Run Group T2 (`ConfigFileWriter` unit tests) and Group T3 (machines.json atomic tests). All must be green.

**Acceptance criteria:**

- `smoke_03_chart_js_loads_locally` green (chart.js served locally)
- `test_machines_json_parseable_after_concurrent_md5_refresh` green with inject-bug→red→revert→green verified
- `test_concurrent_update_entry_no_lost_entries` green
- Single-user dev workflow: `start.bat` still works unchanged; no regressions from `make test`

---

### Phase 2: Cell Concurrency Unified Refactor

**Deliverables:**

1. `CellLockRegistry` module (`src/web_console/backend/cell_lock_registry.py`) with `try_acquire_cell`, `release_cell`, `get_active_cells`, `try_acquire_global`, `release_global`, `snapshot`.
2. Wire `CellLockRegistry` into `create_app()` as a singleton; inject into `BatchRunManager`, `RunManager`, `BatchGenerateManager`.
3. Replace `BatchRunManager._busy_keys` + `_try_acquire_key` / `_release_key` with `registry.try_acquire_cell(..., SAMPLING)`.
4. Replace `BatchRunManager._acquire_in_use` / `_release_in_use` calls with registry calls (eliminating direct calls to `_IN_USE_MODES`).
5. Replace `RunManager.start_run` (from-cache generate path) `OperationCoordinator.acquire` with `registry.try_acquire_cell(..., GENERATING)`.
6. Add `registry.try_acquire_cell(..., GENERATING)` to `BatchGenerateManager` per-item before worker submission (fixes H1).
7. Add `registry.try_acquire_cell(..., DELETING)` to all delete paths in `delete_rawdata()` and the two DELETE endpoints (fixes H2).
8. Replace all remaining `OperationCoordinator` uses with appropriate `try_acquire_global` calls (Cluster B refactor).
9. Add `registry.get_active_cells()` call to `_auto_cleanup_for_space` replacing `_get_in_use_snapshot()` (extends to cover GENERATING and DELETING too, not just SAMPLING).
10. `GET /api/system-state` returns `registry.snapshot()` for full visibility.
11. Add disk monitor daemon thread (§4.8).

**`OperationCoordinator` retained** (deprecated) alongside `CellLockRegistry` during Phase 2 for callers not yet migrated. Both can coexist — they protect independent claims. Remove `OperationCoordinator` only after all callers migrated (optional cleanup pass after Phase 2).

**Revert plan:** Phase 2 is an in-place refactor of existing call sites. Revert = `git revert <phase-2-commits>`. `CellLockRegistry` is additive. Removing per-cell registry calls restores the old `_busy_keys` + `_IN_USE_MODES` behavior. Data on disk (`rawdata/`, `reports/`, SQLite) is unmodified.

**Verification step:** Run T1 (CellLockRegistry), T5 (delete + lock), T9 (E2E multi-user), T8 (disk monitor). Inject bug: remove DELETING check from `delete_rawdata` → T5's `test_delete_blocked_when_sampling_active` must go red → revert → green.

**Acceptance criteria:**

- All Group T1 + T5 + T9 tests green with inject-bug verification
- `smoke_01-05` still green (single-user unaffected)
- `GET /api/system-state` response includes `cell_registry` snapshot field

---

### Phase 3: New Features

**Deliverables:**

1. `POST /api/configs/upload`, `GET /api/configs`, `GET /api/configs/{config_id}` endpoints.
2. Config registry at `configs/uploaded_configs/_registry.json` + content files.
3. `config_id` field added to `_chunks.json` sidecar entries + `by_config_id` index.
4. `BatchRunItem.config_id` field; plumbed to `--machine-config-file` CLI arg in `RunManager.start_run()`.
5. SQLite `fleet_refresh_queue` + `fleet_refresh_items` tables (via `ALTER TABLE` / `CREATE TABLE IF NOT EXISTS` in `StateStore._init_db()`).
6. `FleetRefreshManager` class with `run_queue()` background daemon.
7. `_recover_fleet_refresh()` called from `StateStore.__init__`.
8. `POST /api/fleet/refresh`, `GET /api/fleet/refresh`, `DELETE /api/fleet/refresh` endpoints.
9. `TokenBucket` rate limiter singleton; wired into `BatchRunManager._run_one` and `FleetRefreshManager.run_queue`.
10. `_tag_reports_stale()` added to all three `delete_rawdata` paths (brief §5.6, fixes Scenario 12).
11. `underlying_removed` field in SQLite `runs` table (`ALTER TABLE runs ADD COLUMN underlying_removed INTEGER NOT NULL DEFAULT 0`).
12. Frontend: config upload panel (reusing existing file-upload pattern from `POST /api/reports/import`); fleet refresh progress panel (reusing existing `batchRunProgress` renderer — per `memory/feedback_no_parallel_panel_impl.md`).

**Backward compat:** Existing rawdata/reports/configs unmodified. `config_id="null"` is the default for all existing chunks. `underlying_removed=0` default covers all existing runs. No existing endpoint changes meaning.

**Revert plan:** SQLite schema additions (ALTER TABLE) are forward-only. Rollback = `git revert <phase-3-commits>` + manually `ALTER TABLE runs DROP COLUMN underlying_removed` (SQLite 3.35+ supports this). Or: if on SQLite < 3.35, the old code simply ignores the new column. Fleet refresh tables can be dropped (`DROP TABLE IF EXISTS fleet_refresh_queue; fleet_refresh_items`). Config uploads dir can be left in place (inert without endpoints).

**Verification step:** Run T6 (config upload), T7 (fleet refresh queue), T8 (rate limiter). Run full `smoke` suite. Verify inject-bug→red→revert→green for T6 `test_concurrent_upload_same_content_produces_single_file` and T7 `test_resume_after_simulated_crash`.

**Acceptance criteria:**

- `POST /api/configs/upload` returns same `config_id` for same content regardless of concurrency
- `GET /api/fleet/refresh` shows correct progress during a 5-machine test refresh
- Fleet refresh resumes after simulated restart with 50% complete queue
- Report stale-tagging: `GET /api/reports/{M}/{mode}` returns `underlying_removed=true` on entries after rawdata deletion
- All T6 + T7 + T8 tests green

---

### Phase 4: Deploy + Service Wrapper

**Deliverables:**

1. `start_console.ps1` extended: `--host 0.0.0.0`, restart loop (5 restarts), stdout/stderr log redirect.
2. `SLOT_BIND_HOST` and `SLOT_BIND_PORT` env var support in `main.py` (passed to `uvicorn.run()`).
3. Task Scheduler `.xml` export file (committed to `scripts/deploy/task_scheduler_setup.xml`) for one-command task creation: `schtasks /Create /XML scripts\deploy\task_scheduler_setup.xml /TN "SlotConsole"`.
4. `scripts/deploy/README_DEPLOY.md` with step-by-step: (a) install deps; (b) set env vars in system env or `.env` file; (c) run Task Scheduler setup; (d) verify smoke tests.
5. Smoke test suite runnable from LAN: `scripts/deploy/run_smoke.ps1` that hits `http://<server-ip>:8877/api/health` and other smoke endpoints.
6. `scripts/deploy/rollback.ps1`: stops Task Scheduler task, restores previous code version from backup tag, restarts.

**Revert plan:** Task Scheduler task can be deleted (`schtasks /Delete /TN "SlotConsole" /F`). Bind host change: revert to `127.0.0.1` in `start_console.ps1` or via env var. No data changes.

**Verification step:** Run full smoke suite (`smoke_01` through `smoke_06`) from a second LAN machine. Verify Task Scheduler restarts uvicorn after manual process kill.

**Acceptance criteria:**

- `smoke_06_lan_reachable` green from 3 different LAN client machines
- Task Scheduler task auto-restarts after `taskkill /PID <uvicorn_pid> /F`
- `scripts/deploy/rollback.ps1` exits with code 0 and smoke tests green after rollback

---

## §7 Alternatives Considered

### Alt 7.1: Concurrency Model Alternatives (§4.1)

**Alt A (chosen): `CellLockRegistry` unified in-memory class**

Subsumes `_IN_USE_MODES`, `_busy_keys`, `OperationCoordinator` into one auditable object with typed operations and per-cell granularity. Blast radius of refactor: ~15 call sites in `app.py`. Risk: regression if any call site is missed. Mitigation: CI group T1+T5+T9 validates all paths; inject-bug verification required.

**Alt B: Minimal individual patches**

Patch each gap individually (H1: add `_acquire_in_use` to `BatchGenerateManager`; H2: add `_IN_USE_MODES` check to `delete_rawdata`; Cluster B: left as-is with global lock). No architectural change.

Trade-off: Lower refactor risk. But `OperationCoordinator` global bottleneck remains — under multi-user, planner A's batch-generate blocks planner B's unrelated report delete. The user explicitly said "不要保守." This option is rejected for Cluster B specifically.

**Alt C: Per-cell SQLite lock rows**

Store cell locks in `console.db`. Cross-restart durable.

Trade-off: Adds DB roundtrip on every chunk write; crashed processes leave stale locked rows requiring manual cleanup. Not recommended per §4.1 analysis.

---

### Alt 7.2: Fleet Refresh Queue Persistence Alternatives (§4.4)

**Alt Q1 (chosen): SQLite tables `fleet_refresh_queue` + `fleet_refresh_items`**

Fits existing stack (SQLite WAL already planned). Concurrent reads (10 planners polling status) are free in WAL mode. Recovery is straightforward SQL. No new files, no new format.

**Alt Q2: JSON file `state/console/fleet_refresh_queue.json`**

Simpler to inspect by hand. But a 393-item queue file written on every status change creates write contention between item completions (serialized through ConfigFileWriter lock) and status reads. On a 4-worker batch, 4 concurrent completions all want to write the same file — they serialize correctly (via lock) but each write is a full-file rewrite of the 393-entry JSON.

Reject because: SQLite handles this naturally with row-level updates; JSON file does not benefit from row-level atomicity.

**Alt Q3: Periodic JSON snapshot of in-memory state**

Up to 30s progress loss on crash; snapshot thread race; additional failure mode. Rejected.

---

### Alt 7.3: Rate Limiter Alternatives (§4.5)

**Alt R1 (chosen): Parent-process token bucket, throttles at subprocess-launch level**

No IPC needed. All launch decisions are in the parent process (single-threaded event loop decisions are serialized by GIL when holding the token bucket lock). Simple to implement, simple to reason about.

**Alt R2: Shared upstream HTTP proxy (parent process receives all upstream calls)**

All analyzer subprocesses send their upstream API calls to a proxy endpoint in the parent process (`http://localhost:9876/upstream-proxy`), which applies the token bucket before forwarding. Fine-grained control (can rate-limit per HTTP request, not per subprocess launch). 

Trade-off: Requires an HTTP server socket inside the parent; significant refactor to analyzer subprocess (replace `post_json` with proxy call); adds a single point of failure. Too invasive for the stack constraint.

**Alt R3: No rate limiter (rely on upstream AIMD)**

The analyzer already has an AIMD circuit breaker (`player_impact_analyzer.py:378-395`) that halves `batch_concurrency` on failure. Under self-DoS, AIMD kicks in reactively and reduces throughput. But per Scenario 9: once throttled, throughput stays at 0.7k/s for hours — AIMD cannot recover the IP reputation fast enough. Reactive throttling is insufficient.

---

## §8 Risk Register

| Risk | Likelihood | Impact | Monitor / Mitigation |
|------|-----------|--------|---------------------|
| Phase 2 refactor misses a `delete_rawdata` call site | Medium | High (H2 persists) | `grep -rn "shutil.rmtree\|\.unlink()" src/web_console/` in CI; require T5 inject-bug verification |
| Windows antivirus scanner holds `.tmp` file open during `os.replace` retry | Medium | Low (retry with backoff handles it) | `ConfigFileWriter` retries 5× with 50ms backoff; `disk_monitor_error.json` captures persistent failures |
| SQLite WAL journaling breaks on network share rawdata path | Low (rawdata on local disk, not network share) | High | Brief §9: single Windows host — local disk assumed; document restriction in deploy README |
| Fleet refresh 393-machine run exceeds upstream rate even with token bucket | Medium | Medium (throttled but functional) | Monitor `state/console/disk_monitor_last.json` for analyzer timeout patterns; tune `TokenBucket.refill_rate` down if needed |
| `config_id` not plumbed to chunk envelope (analyzer subprocess can't write it to chunk) | High (requires analyzer code change in Phase 3) | Medium (dedup still works via sidecar annotation; config_id written by parent after chunk lands) | Parent process annotates chunk in sidecar after subprocess completes; suboptimal but correct |
| Task Scheduler runs under different user; rawdata dir permission denied | Medium | High (server won't start) | Document in deploy README: Task Scheduler user must match rawdata directory owner; smoke_01 catches on first boot |
| Phase 3 frontend config-upload panel reuses wrong sibling renderer | Medium | Low (UI-only) | Reviewer checklist: grep existing file-upload handler before writing panel; per `memory/feedback_no_parallel_panel_impl.md` |

---

## §9 Open Questions for W3 Validator

1. **`GENERATING` + `SAMPLING` coexistence per cell:** The proposal allows concurrent `SAMPLING` (new chunk writes) and `GENERATING` (read-from-cache report) on the same cell, based on `03_deploy_concurrency_blast_radius.md Scenario 2`'s conclusion that sidecar reads are atomic. W3 should validate: is there any window where the generator's chunk enumeration (glob of `chunk_*.json`) races with a new chunk being `os.replace`d into existence, such that the generator reads a partial set and produces a report with incorrect spin count?

2. **`rawdata_index` retry sufficient for cross-process correctness?** The proposed retry in `update_entry()` checks mtime before and after read. On Windows NTFS, mtime granularity is 100ns — two writes within 100ns have the same mtime. Is this granularity sufficient for the 4-worker ProcessPoolExecutor case, or is a file-level exclusive lock needed despite the cost?

3. **`config_id` plumbing to analyzer subprocess:** The proposal has the parent annotate `config_id` in the sidecar after the analyzer subprocess completes a chunk. This means the analyzer itself has no `config_id` awareness — it receives `--machine-config-file <path>` but does not write `config_id` to the chunk envelope. The sidecar annotation is done by the parent's `_watch_run` hook. W3 should validate: does this sidecar-only annotation approach correctly handle the case where the parent crashes after the chunk is written but before the sidecar is updated? (The chunk would be orphaned — not associated with any config_id in the sidecar.)

4. **`FleetRefreshManager` + `CellLockRegistry` interaction:** When fleet refresh's `run_queue` finds a cell busy (ad-hoc fetch active), it sleeps `YIELD_SLEEP_S` and retries. W3 should validate: if ad-hoc planners continuously keep a cell busy for hours, the fleet refresh item for that cell will never proceed. Is a maximum wait timeout per item needed? And what is the correct behavior — skip or keep retrying indefinitely?

5. **Token bucket parameter values:** `capacity=10, refill_rate=3.0, foreground_reserve=2`. These are estimates from Scenario 9's analysis. W3 should validate whether `refill_rate=3.0` (3 new analyzers/second) combined with `batch_concurrency=8` per analyzer actually keeps total upstream below the ~1k/s throttle threshold in the worst-case (5 planners + fleet refresh all active simultaneously).

6. **`OperationCoordinator` deprecation path:** Phase 2 retains `OperationCoordinator` alongside `CellLockRegistry`. W3 should flag whether any `OperationCoordinator.acquire` calls remain active in Phase 2 that could produce false 409 responses when `CellLockRegistry` has already allowed the operation. Specifically: if `BatchGenerateManager` is migrated to `registry.try_acquire_cell(GENERATING)` but `OperationCoordinator.acquire("batch_generate_report")` is still called, the global lock still blocks concurrency. The Phase 2 deliverable must either remove the `OperationCoordinator` call or make the migration atomic.

7. **`DELETE /api/machines/{machine}/all-data` scope:** This endpoint deletes both rawdata and reports dirs (`app.py:6300-6370` area). The proposal requires `_tag_reports_stale` to run before rawdata is deleted. But this endpoint deletes reports too (not just rawdata). Should `_tag_reports_stale` be skipped here (since the reports are being deleted anyway), or should it run and then the delete proceeds? Brief §5.6 says "reports stay but get tagged" — but this endpoint explicitly nukes reports. W3 should clarify the intended behavior of `DELETE /api/machines/{machine}/all-data` vs. the stale-tag invariant.

8. **Frontend fleet-refresh progress panel:** The proposal says it must reuse the existing `batchRunProgress` renderer per `memory/feedback_no_parallel_panel_impl.md`. But fleet refresh has 393-item progress (machine-level) while `batchRunProgress` shows per-run-id progress. W3 should validate whether the existing renderer is extensible to a two-level hierarchy (queue-level + item-level), or whether a sibling renderer from a different panel must be the reuse target.

---

## §10 Out of Scope

This proposal explicitly does NOT solve:

1. **Multi-worker uvicorn (`workers=N`):** Adding `workers` would require making all singletons (`_IN_USE_MODES`, `CellLockRegistry`, `BatchRunManager._batches`, etc.) cross-process. This would require shared memory or Redis. Stack constraint prohibits Redis. Not needed for <10 users with a single-worker server. Documented but not designed.

2. **Authentication / authorization / role-based access control:** Brief §5.3 explicitly prohibits user concept. No change.

3. **SSE / WebSocket for live status push:** Frontend polling at 1-4.5s is sufficient for <10 users per `03_deploy_concurrency_blast_radius.md Scenario 14`. SSE would require significant frontend refactor. Not in scope.

4. **Auto-detect "rawdata全部失效":** Brief §7 explicitly out of scope. Planner manually triggers full refresh.

5. **L3 staging environment:** Brief §7 out of scope.

6. **`slot_designer/` virtual console changes:** The virtual console (`port 8878`) uses the same `create_app()`. Phase 1-2 changes to `ConfigFileWriter`, `CellLockRegistry`, etc. are available to the virtual console automatically since it calls `create_app()`. No separate work needed for virtual console.

7. **Upstream API changes:** The upstream `MultiRobotTestSpinVariant` endpoint is not under this team's control. Rate limiting (§4.5) governs the client side only.

8. **Replacing `BatchGenerateManager` `ProcessPoolExecutor` with `subprocess.Popen` for consistency:** The ProcessPoolExecutor serves a specific purpose (importing the analyzer once per worker, not re-spawning Python interpreter per item). The cross-process sidecar race (H3) is addressed by the retry loop in §4.2, not by changing the executor model.

9. **Max chunk count / data retention policy redesign:** The existing `min_retention_spins` + tiered delete classification is retained as-is. No policy changes. The disk monitor (§4.8) enforces the same policy as `_auto_cleanup_for_space`, just continuously.

---

*Proposal complete. Wave 3 (critic + validator) to review §9 open questions and §8 risk register.*
