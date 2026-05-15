# 04 Deploy Architecture Proposal — v2

> Wave 2 (revision) — Deploy Review (2026-05-15)
> Agent: arch-designer
> Input: W3 verdicts — `05_deploy_critique.md` (APPROVE-WITH-REVISIONS, 5 top concerns + 7 required revisions) + `06_deploy_validation.md` (APPROVE-WITH-REVISIONS, 13 cases, 5 pass / 7 pass-with-concern / 1 FAIL)
> v1 preserved at: `04_deploy_architecture_proposal.md`
> Stack constraint: FastAPI + uvicorn + SQLite (WAL) + ProcessPoolExecutor + subprocess.Popen + threading.Lock. No Postgres, Redis, Celery, Docker, NSSM, nginx.

---

## §1 Executive Summary

v2 incorporates all 12 required revisions from the W3 review, plus 4 additional corrections from critic/validator evidence. The architecture direction — `CellLockRegistry`, `ConfigFileWriter`, `FleetRefreshQueue`, `TokenBucket` — is unchanged and approved. The revisions address:

1. A factual error (H1 was already fixed in baseline — `app.py:7212`); the `CellLockRegistry` rationale is reframed as unification, not bug-fix.
2. A mechanism failure in the token bucket (capacity=10 governs launch rate, not steady-state concurrency; replaced with `Semaphore(N)` approach).
3. A reliability gap in `rawdata/_index.json` cross-process writes (NTFS 100ns mtime granularity makes retry-on-mtime unreliable; replaced with file-level exclusive lock `msvcrt.locking`).
4. A punted behavioral contract (fleet refresh cell-busy stall timeout is now specified: 30-minute configurable timeout, then log+skip).
5. A contradiction in Phase 2 (OperationCoordinator dual-active "retained but replaced" resolved by atomic cutover table).
6. A scoping error on INV-7 (`all-data` delete correctly carves out of stale-tag invariant).
7. A missing fourth rawdata delete path for stale-tag enumeration (`DELETE /api/rawdata/{machine}/mode/{mode}/version`).
8. A crash-window dedup invariant gap for config_id sidecar annotation (write-config-first ordering).
9. A UX gap between "reject" and "attach" semantics for same-cell concurrent fetch.
10. A sidecar key granularity gap for same-machine different-config serialization.
11. A missing frontend one-shot guard for fleet refresh polling.

No process model changes, no framework replacement, no user concept introduced.

---

## §2 Current State Confirmation

Unchanged from v1. The server (`src/web_console/backend/main.py:15`, `app.py:5286`) runs as a single uvicorn process on `127.0.0.1:8877`, serving a no-build static frontend from `src/web_console/frontend/` and a FastAPI backend with 49 HTTP endpoints (`01_deploy_pipeline_map.md §4`). All stateful singletons — `StateStore` (SQLite), `RunManager` (subprocess orchestration), `BatchRunManager` (per-cell sampling), `BatchGenerateManager` (ProcessPoolExecutor report regen), `OperationCoordinator` (single-flag ops mutex) — are instantiated once per `create_app()` call and live in-process. Three classes of sub-process are spawned: (a) analyzer subprocesses via `subprocess.Popen` for sampling and from-cache report generation; (b) `ProcessPoolExecutor(spawn)` workers for batch-regen; (c) post-hook inference subprocesses per run. In-memory concurrency is handled by `threading.Lock` and `threading.Semaphore`; file atomicity is handled by `os.replace(tmp, target)` on most JSON files — but NOT on `configs/machines.json` (`app.py:8216`) and NOT on `configs/servers.json` (`app.py:513`). There is no auth, no user concept, no LAN binding (`127.0.0.1` only), and no crash-recoverable long-run queue. See `01_deploy_pipeline_map.md §1-§10` for the full process topology, persistence schema, and module-global hazard list.

---

## §3 Real Gaps (Synthesized from 02/03) — v2 Corrections

### 3.1 Critical (1)

**C1 — `machines.json` non-atomic write (Scenario 16)**

`_do_refresh_machines_md5()` at `app.py:8216` calls `Path(mc).write_text(...)` — plain file truncation + write, no temp file, no process-level mutex. Two concurrent callers (pre-batch async refresh thread from `app.py:5834` + explicit `POST /api/machines/refresh-md5`) race to truncate-then-write the same file. If write_1 truncates while write_2 is mid-`json.loads`, write_2 reads partial JSON, falls back to `{"machines": []}` at `app.py:8213`, then writes an empty machines list — silently wiping all 393 machine entries from the fleet registry. No error is logged; the backend continues serving an empty fleet until a manual fix.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 16`; `app.py:8210-8220`; `memory/feedback_md5_granularity_and_stamping.md`.

---

### 3.2 High (5) — v2 recount

**H1 removed (R1 revision):** v1 claimed `BatchGenerateManager` was missing `_acquire_in_use`. This is factually incorrect. `_prepare_batch_gen_item_wrapper` at `app.py:7208-7222` explicitly calls `_acquire_in_use(machine, mode)` at line `app.py:7212`, and `_finalize_batch_gen_item_wrapper` calls `_release_in_use` in its `finally` block. The `BatchGenerateManager` is instantiated with these as `prepare_fn`/`finalize_fn` at `app.py:3331`. The gap in v1 §3.2 H1 does not exist. The `CellLockRegistry` migration still replaces `_acquire_in_use` and `_busy_keys` as a **unification refactor** (one auditable object replacing two independent systems), not a bug-fix.

Source: `05_deploy_critique.md §2 CI-1`; `app.py:7208-7222` (confirmed by grep).

**H2 — `delete_rawdata` does not check `_IN_USE_MODES`**

`delete_rawdata()` at `app.py:1040` proceeds to unlink chunk files without consulting `_IN_USE_MODES`. The sampling path registers in `_IN_USE_MODES` (via `_acquire_in_use` called at `app.py:3761`), but the delete path ignores it. Concurrent delete + active sampling for the same cell results in the analyzer finding its `--resume-from-cache` chunks partially deleted mid-run.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 6`; `02_deploy_surface_taxonomy.md §3.3 item 10`.

**H3 — `rawdata/_index.json` global index lost-update under N concurrent writers**

`rawdata_index.py:update_entry()` does read-modify-write + `os.replace`. The file contains all (machine, mode) entries. Two concurrent writers for different cells both read `{M14|1, M15|1}`, both merge their own new entry, both write — the second write overwrites the first, silently dropping one entry. This is a realistic race under the 4-worker `ProcessPoolExecutor` completing items simultaneously. The mtime-retry approach proposed in v1 is **insufficient on Windows NTFS** where mtime granularity is 100ns — four workers completing within 100ns have identical mtimes and the retry does not detect the race. See §4.2 (R3) for the replacement mechanism.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 2`; `05_deploy_critique.md §2 CI-3`; `rawdata_index.py:182-203`.

**H4 — No rate-limit shared bucket across concurrent analyzer subprocesses**

5 planners × 3 batch concurrency × 8 analyzer concurrency = 120 concurrent upstream HTTP requests from the same server IP. The upstream can sustain ~3.7k/s fresh but drops to ~0.7k/s throttled; once throttled it stays throttled for hours. No token bucket exists in the codebase. See §4.5 (R2) for the revised mechanism.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 9`; `02_deploy_surface_taxonomy.md §3.3 item 11`; `memory/feedback_upstream_throttle_ceiling.md`.

**H5 — Long-run crash recovery: no persisted queue, no resume**

`BatchRunManager._batches` is in-memory (`app.py:3190`). On process death, all batch state is lost. Orphaned analyzer subprocesses continue writing chunks but no watcher thread picks up results; run rows stay `failed` in SQLite; completed chunk files are unclaimed. A 393-machine full-refresh losing 6 hours of progress on a server restart is unacceptable per brief §5.8.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 5`; `02_deploy_surface_taxonomy.md §3.4 (fleet refresh gap)`.

**H6 — Disk pressure: background daemon absent; per-fleet chunk budget not enforced**

`_auto_cleanup_for_space` fires only inside `BatchRunManager._run_one` pre-flight (`app.py:3719`). During a full-fleet-refresh (393 machines), disk can fill between cleanup invocations.

Source: `03_deploy_concurrency_blast_radius.md §2 Scenario 10`; `02_deploy_surface_taxonomy.md §3.3 item 10`.

---

### 3.3 Unsafe-Today Clusters (unchanged)

**Cluster A — Config file write races** (10 surfaces): `configs/machines.json`, `configs/servers.json`, `configs/rawdata_locks.json`, `configs/machine_halls.json`, `configs/machines_static.json`, `state/console/settings.json`. Fix: `ConfigFileWriter` (§4.2).

**Cluster B — `OperationCoordinator` single-slot bottleneck** (7 surfaces): global boolean; per-cell operations should be per-cell granularity. Fix: `CellLockRegistry` (§4.1).

**Cluster C — `_IN_USE_MODES` scope gaps** (5 surfaces, delete paths bypass it). Fix: `CellLockRegistry` mandatory enrollment.

**Cluster D — Report index/latest.json non-atomic concurrent writes** (5 surfaces). Fix: `atomic_json_write` from `ConfigFileWriter`.

**Cluster E — `chart.js` CDN dependency** (1 surface): fails in intranet. Fix: vendor into `frontend/vendor/`.

---

### 3.4 New Surfaces Required (9)

Per `02_deploy_surface_taxonomy.md §2.7` and `00_deploy_brief.md §2`:

1. `POST /api/configs/upload` — config upload endpoint
2. `GET /api/configs` — list uploaded configs
3. `GET /api/configs/{config_id}` — get specific config
4. `POST /api/fleet/refresh` — trigger full-fleet sampling
5. `GET /api/fleet/refresh` — poll fleet refresh progress
6. `DELETE /api/fleet/refresh` — cancel fleet refresh
7. Fleet refresh crash-recovery (startup background task)
8. Report stale-tagging on rawdata delete (extension to `delete_rawdata` and related paths)
9. Dedup key `(config_id, machine, mode, upstream_md5)` registry

---

## §4 Architectural Decisions

### 4.1 Cell-Level Concurrency — Unified `CellLockRegistry`

#### Problem

Today: `_IN_USE_MODES` (set, `app.py:2152`), `BatchRunManager._busy_keys` (set, `app.py:3198`), `OperationCoordinator` (single bool, `app.py:4000`), and `_sidecar_lock_for` (per-path dict, `chunk_index.py:91`) are four independent systems tracking overlapping concerns. `delete_rawdata` ignores `_IN_USE_MODES` (H2). `OperationCoordinator` is too coarse (Cluster B). `_busy_keys` is only within one `BatchRunManager` instance. No single source of truth exists for "who owns a (machine, mode) cell right now."

Source: `03_deploy_concurrency_blast_radius.md §2 Scenarios 2, 6, 13`; `02_deploy_surface_taxonomy.md §3.3 items 1-4`.

#### Design

```
src/web_console/backend/cell_lock_registry.py
```

```python
# Pseudocode — not a real file
class CellOperation(Enum):
    SAMPLING    = "sampling"     # BatchRunManager: analyzer subprocess writing chunks
    GENERATING  = "generating"   # RunManager or BatchGenerateManager: reading chunks + writing report
    DELETING    = "deleting"     # delete_rawdata: unlinking chunks + updating index

class CellLockRegistry:
    _registry: dict[tuple[str, int], set[CellOperation]]
    _lock: threading.Lock
    _global_lock: dict[str, threading.Lock]
    _global_busy: dict[str, bool]
```

**Invariants:**

1. `SAMPLING` and `DELETING` are mutually exclusive per cell.
2. `GENERATING` and `DELETING` are mutually exclusive per cell.
3. `SAMPLING` + `GENERATING` on the same cell: allowed (sidecar `os.replace` ensures atomic read snapshot; new chunks not included in generator's snapshot is expected/benign per `05_deploy_critique.md §8 OQ-1`).
4. At most ONE `SAMPLING` registration per cell.
5. At most ONE `GENERATING` registration per cell.
6. Global ops (`disk_cleanup`, `prune_all`, `reports_cleanup`) acquire the global flag; respect `get_active_cells()` snapshot to skip cells in use.

**R1 Correction — CellLockRegistry is a unification refactor, not H1 bug-fix:**

The `BatchGenerateManager` already calls `_acquire_in_use` correctly (`app.py:7212`). The CellLockRegistry migration for `BatchGenerateManager` replaces the existing `_acquire_in_use` call with `registry.try_acquire_cell(..., GENERATING)` as a unification, giving a single auditable source of truth. This is the correct framing. Phase 2 deliverable #6 below reflects this.

Source: `05_deploy_critique.md §2 CI-1`; `app.py:7208-7222`.

**R5 — Atomic cutover table (replacing v1's "retained + replace" contradiction):**

The following table is the single source of truth for Phase 2. ALL `OperationCoordinator.acquire` call sites are resolved in one atomic Phase 2 commit. After that commit, `OperationCoordinator` is deleted from the codebase. There is no intermediate "retained for compat" state.

| `ops.acquire` call site | Location | Phase 2 action |
|---|---|---|
| `"batch_generate_report"` | `app.py:2970` (BatchGenerateManager._run) | **Removed** — replaced by `registry.try_acquire_cell(..., GENERATING)` per item |
| `"generate_report"` (async path) | `app.py:6772` (_run_generate_report) | **Removed** — replaced by `registry.try_acquire_cell(..., GENERATING)` |
| `"start_run"` (from-cache) | Inside `RunManager.start_run` ops path | **Removed** — replaced by `registry.try_acquire_cell(..., GENERATING)` |
| `"delete_rawdata"` | `app.py:6269` (DELETE /api/rawdata/{machine}) | **Removed** — replaced by `registry.try_acquire_cell(..., DELETING)` |
| `"delete_machine_all_data"` | `app.py:6308` area | **Removed** — replaced by `registry.try_acquire_cell(..., DELETING)` per mode |
| `"delete_run"` | `app.py:8650` area (DELETE /api/runs/{run_id}) | **Removed** — replaced by `registry.try_acquire_cell(..., GENERATING)` |
| `"delete_report_version"` | `app.py:7447` area (DELETE /api/reports/{m}/{mode}/{v}) | **Removed** — replaced by `registry.try_acquire_cell(..., GENERATING)` |
| `"disk_cleanup"` | `app.py:6185` area (POST /api/cache/cleanup) | **Migrated to** `registry.try_acquire_global("disk_cleanup")` |
| `"prune_versions"` | `app.py:8730` area (POST /api/maintenance/prune-versions) | **Migrated to** `registry.try_acquire_global("prune_versions")` |
| `"reports_cleanup"` | `app.py:7511` area (POST /api/reports/cleanup) | **Migrated to** `registry.try_acquire_global("reports_cleanup")` |
| `"import_reports"` | `app.py:7584` area (POST /api/reports/import) | **Migrated to** `registry.try_acquire_global("import_reports")` |
| `"autotune"` | `app.py:8878` area (POST /api/autotune) | **Migrated to** `registry.try_acquire_global("autotune")` |
| `"refresh_machine_halls"` | `app.py:5625` area | **Migrated to** `registry.try_acquire_global("refresh_halls")` |

**OperationCoordinator is removed entirely at end of Phase 2.** No partial state, no coexistence window.

Source: `05_deploy_critique.md §3 M3`; `06_deploy_validation.md §4 EC-2`.

**API:**

```python
# Pseudocode
class CellLockRegistry:
    def try_acquire_cell(self, machine: str, mode: int,
                         op: CellOperation) -> bool: ...
    def release_cell(self, machine: str, mode: int, op: CellOperation) -> None: ...
    def get_active_cells(self, op: CellOperation | None = None
                         ) -> set[tuple[str, int]]: ...
    def try_acquire_global(self, name: str) -> bool: ...
    def release_global(self, name: str) -> None: ...
    def snapshot(self) -> dict: ...
```

**R9 — "Attach" semantics for same-cell concurrent fetch:**

v1 and the validator (Case 1) identified a UX gap: the second planner gets `status='failed'` instead of an "attaching" experience. The brief §5.7 implies dedup to one upstream call and shared visibility.

Design: when `registry.try_acquire_cell(machine, mode, SAMPLING)` returns False because another SAMPLING is active for the same cell with the same `(config_id, upstream_md5)`, return an **attach response** instead of a failure:

```python
# POST /api/batch-run, inside _run_one:
if not registry.try_acquire_cell(machine, mode, SAMPLING):
    active = registry.get_active_sampling_info(machine, mode)
    if active and active["config_id"] == req_config_id and active["upstream_md5"] == req_upstream_md5:
        # Same 4-tuple already in flight: attach to it
        return {
            "status": "attached",
            "attached_to_run_id": active["run_id"],
            "message": "Another fetch for this cell is in progress; your request is attached."
        }
    else:
        # Different config or md5: reject
        return {"status": "failed", "error": "another batch is sampling this machine+mode"}
```

`CellLockRegistry` stores `run_id`, `config_id`, and `upstream_md5` alongside each active SAMPLING registration to enable this lookup.

Frontend: an item with `status='attached'` shows the attached `run_id`'s progress instead of a failure indicator. This reuses the existing per-run progress polling (no new endpoint needed).

Source: `06_deploy_validation.md §2 Case 1`; `00_deploy_brief.md §5.7`.

**R10 — Same-machine different-config serialization (sidecar key granularity):**

The validator (Case 10) identified that different config_ids for the same `(machine, mode)` are forced to serialize because `CellLockRegistry` key is `(machine, mode)`. The root cause is the sidecar `_chunks.json` being a single file per mode_dir regardless of config_id.

The conceptually correct fix is a per-config-id sidecar. However, this is architecturally expensive (requires restructuring the rawdata directory and all sidecar read/write paths). The minimum-delta alternative is to accept the current serialization constraint and **document it explicitly** rather than hide it:

Design decision: `CellLockRegistry` key remains `(machine, mode)`. Different config_ids for the same `(machine, mode)` must serialize. This is safe (no data corruption possible) but suboptimal for power users. Documented as explicit behavioral contract:

> **INV-1 scope**: "At most one SAMPLING per `(machine, mode)` regardless of config_id. Fetches for different config_ids on the same machine+mode serialize. This prevents cross-process sidecar corruption. Power users who need concurrent multi-config sampling on the same machine must run separate batches sequentially."

The sidecar directory restructuring (per-config-id sharding) is deferred to a future architecture review as a known limitation, not a bug. It requires its own W1/W2/W3 cycle.

Source: `06_deploy_validation.md §2 Case 10`; `06_deploy_validation.md §4 EC-2`.

**Alternatives for §4.1:**

**Alt A (recommended): `CellLockRegistry` unified in-memory class** — Pros: one auditable object, typed operations, per-cell granularity. Cons: ~15 call sites to touch; requires atomic cutover.

**Alt B: Minimal patches** — Patch each gap individually. Pros: minimal diff. Cons: five independent systems remain; `OperationCoordinator` global bottleneck (Cluster B) unsolved.

**Alt C: Per-cell SQLite lock rows** — Cross-restart durable but adds DB roundtrips on every chunk write. Crashed processes leave stale locks. Rejected.

**Decision: Alt A.** User instruction: "不要保守."

---

### 4.2 Atomic Config File Writes — `ConfigFileWriter` + H3 Fix

#### Problem

`configs/machines.json` uses `write_text` (non-atomic, Critical C1). `configs/servers.json` uses `write_text`. `configs/rawdata_locks.json` uses `tmp+os.replace` but no mutex over the read-modify-write cycle. `rawdata/_index.json` has a cross-process concurrent writer race that **cannot be fixed by mtime-retry on Windows NTFS** (mtime granularity 100ns, four workers may complete within 100ns).

Source: `03_deploy_concurrency_blast_radius.md Scenario 16, Scenario 2`; `05_deploy_critique.md §2 CI-3`.

#### `ConfigFileWriter` Design (unchanged from v1)

```
src/web_console/backend/config_writer.py
```

```python
# Pseudocode
_FILE_LOCKS: dict[str, threading.Lock] = {}
_REGISTRY_GUARD = threading.Lock()

def _lock_for(path: Path) -> threading.Lock: ...

def atomic_json_write(path: Path, data: dict) -> None:
    """Thread-safe atomic JSON write: lock -> serialize -> tmp -> os.replace."""
    ...

def atomic_json_read_modify_write(path: Path, modifier: Callable[[dict], dict]) -> dict:
    """Thread-safe read-modify-write. Lock held across read+modify+write."""
    ...
```

**Files requiring migration:**

| File | Current writer | Current atomic? | Fix needed |
|------|---------------|----------------|------------|
| `configs/machines.json` | `_do_refresh_machines_md5` | No (`write_text`) | `read_modify_write` + lock |
| `configs/servers.json` | `save_servers()` | No (`write_text`) | `atomic_json_write` |
| `configs/rawdata_locks.json` | `_save_rawdata_locks()` | write+replace, no lock | `read_modify_write` + lock |
| `configs/machine_halls.json` | `halls/refresh` | No (`write_text`) | `atomic_json_write` |
| `configs/machines_static.json` | `_save_static_attrs()` | `tmp+replace` | Add lock |
| `state/console/settings.json` | `_save_settings()` | `os.replace` | Add lock |
| `reports/<M>/mode_<N>/index.json` | `_update_report_index` | `write_text` | `atomic_json_write` |
| `reports/<M>/mode_<N>/latest.json` | `_update_report_index` | `write_text` | `atomic_json_write` |

#### R3 — `rawdata/_index.json` H3 Fix: File-Level Exclusive Lock

**Problem (from v1 mtime-retry replacement):** The mtime-retry approach in v1 §4.2 is unreliable on Windows NTFS because mtime resolution is 100ns. Four ProcessPoolExecutor workers completing near-simultaneously can produce identical mtimes, causing both workers to proceed with their read-modify-write and one update to be silently lost.

**Chosen approach: (a) `msvcrt.locking` for Windows exclusive file lock**

```
fresh_slotlab/rawdata_index.py  — modify update_entry() and remove_entry()
```

```python
# Pseudocode for cross-process exclusive lock on Windows
import msvcrt

_INDEX_THREAD_LOCK = threading.Lock()  # within-process serialization

def _exclusive_lock_index(index_path: Path):
    """Context manager: holds both threading.Lock (within-process) and
    msvcrt file lock (cross-process) for the duration of a read-modify-write."""
    ...

def update_entry(rawdata_root: Path, machine: str, mode: int, chunk_dir: Path) -> None:
    index_path = rawdata_root / "_index.json"
    with _exclusive_lock_index(index_path):
        data = _load_index_no_lock(rawdata_root)
        entry = _scan_mode_dir(chunk_dir)
        key = entry_key(machine, mode)
        if entry:
            data["entries"][key] = entry
        else:
            data["entries"].pop(key, None)
        _save_index_no_lock(rawdata_root, data)
```

**Worker count vs. lock contention:** With 4 `ProcessPoolExecutor` workers, at most 4 processes compete for this lock. On a filesystem update (writing a completed chunk), the critical section is: read ~10KB JSON + update one entry + write ~10KB JSON = approximately 1-5ms. With 4 workers, maximum lock wait = 3 × 5ms = 15ms per worker. This is negligible compared to the seconds-long chunk analysis.

The `msvcrt.locking` approach is Windows-only (correct for the deployment target per `00_deploy_brief.md §9`). For non-Windows fallback (dev on other platforms): wrap in `try msvcrt.locking ... except AttributeError: pass` so the function degrades to within-process locking only. In the single-uvicorn-process model, within-process `threading.Lock` is sufficient for all non-ProcessPoolExecutor callers.

Source: `05_deploy_critique.md §2 CI-3`; `06_deploy_validation.md §2 Case 4`.

**Why not SQLite-mediated registry (option b from the revision spec)?**

SQLite WAL is already planned in Phase 1. Using it for index updates would add DB roundtrips on every chunk completion (hundreds per fleet refresh). The `rawdata_index.py` is documented as a "derived cache" — keeping it as a file with proper cross-process locking avoids coupling it to the DB. The `msvcrt.locking` approach is the minimum-delta fix.

---

### 4.3 Config Upload + 4-Tuple Dedup

#### Problem

No config upload endpoint exists. Current dedup key is `(machine, mode, cfg_md5, code_md5)`. Brief requires `(config_id, machine, mode, upstream_md5)` where `config_id = sha1(file_content)` as a 40-hex string.

Source: `02_deploy_surface_taxonomy.md §2.7`; `03_deploy_concurrency_blast_radius.md Scenario 11`; `00_deploy_brief.md §5.5-5.7`.

#### Config Object Design (unchanged from v1)

```
configs/uploaded_configs/
    <config_id>.json          # Content file (the actual machine config)
    _registry.json            # Metadata registry
```

`config_id` computation:
```python
config_id = sha1(file_content.encode("utf-8")).hexdigest()  # 40 hex chars
```

#### R8 — Write-Config-First Ordering (crash-window fix)

v1 annotated `config_id` in the sidecar **after** the chunk was written by the subprocess. If the parent crashed between chunk write and sidecar annotation, the chunk existed without a config_id association, breaking the dedup invariant silently.

**Chosen approach: (b) write-config-first-then-rawdata ordering**

```python
# In BatchRunManager._run_one, BEFORE calling RunManager.start_run():

# 1. Ensure config is persisted to disk first:
if config_id and config_id != "null":
    config_path = CONFIGS_UPLOAD_DIR / f"{config_id}.json"
    if not config_path.exists():
        raise ValueError(f"config_id={config_id} not found in uploaded_configs; "
                         "cannot start fetch")

# 2. Write a "pending batch record" to SQLite or a sidecar file that
#    records: (config_id, machine, mode, batch_run_id) BEFORE start_run().
#    This serves as the recovery anchor.
store.record_pending_batch_config(batch_run_id, machine, mode, config_id)

# 3. Only then launch the analyzer subprocess:
run_id = manager.start_run(machine, mode, config_id=config_id, ...)
```

On startup, `_recover_fleet_refresh()` and `_recover_orphan_running_runs()` can use `pending_batch_configs` to re-associate orphaned chunks with their config_id on restart. A startup scan that finds chunks in `rawdata/<M>/mode_<N>/` whose `config_id` field is missing from the sidecar's `by_config_id` index can assign them from the `pending_batch_config` record.

This eliminates the crash window: if the parent crashes after `record_pending_batch_config` but before the chunk is written, no chunk exists to orphan. If it crashes after the chunk is written, the startup scan re-associates it.

**Why not startup GC pass (option a)?**

A startup GC scan is reactive (requires each restart to scan all rawdata), is complex to reason about, and adds startup latency proportional to rawdata size. Write-config-first is a simpler invariant: no config_id can reach a chunk without being recorded first.

Source: `05_deploy_critique.md §8 OQ-3`.

#### Chunk Sidecar Extension (unchanged from v1)

Add `config_id` field to each chunk entry in `_chunks.json` and a `by_config_id` inverted index:

```json
{
  "chunks": {
    "chunk_0001.json": {
      "idx": 1, "cfg_md5": "...", "code_md5": "...",
      "config_id": "null",
      "spin_times": 1000, ...
    }
  },
  "by_config_id": {
    "null": ["chunk_0001.json"],
    "<config_id_sha1>": ["chunk_0002.json"]
  }
}
```

**Migration for existing chunks (R10 / critic m3):**

Existing `_chunks.json` files have no `config_id` field and no `by_config_id` key. The lazy-rebuild approach in v1 would produce an empty `by_config_id["null"]` list, breaking dedup for all pre-migration rawdata.

Fix: when `chunk_index.py:load_chunks_index` detects a sidecar without `by_config_id`, it runs an explicit migration step:

```python
# Migration in load_chunks_index():
if "by_config_id" not in data:
    # Assign all existing chunks to config_id="null"
    data["by_config_id"] = {"null": list(data["chunks"].keys())}
    # Also backfill config_id="null" on each chunk entry that lacks it:
    for chunk_name, entry in data["chunks"].items():
        entry.setdefault("config_id", "null")
    _write_sidecar_atomic(mode_dir, data)  # persist the v3 layout
```

This is a one-time migration per mode_dir, triggered on first read after Phase 3 deployment. All existing chunks become part of the `"null"` config bucket, preserving backward compat and enabling correct dedup for default-config fetches.

---

### 4.4 Fleet Refresh Persistent Queue + Resume

#### Problem

No fleet refresh endpoint. No crash-recoverable long-run queue. `BatchRunManager` state is in-memory only. Brief requires: on-demand one-shot, crash-recoverable, per-machine retry, foreground-priority, progress visible to all planners.

Source: `03_deploy_concurrency_blast_radius.md Scenario 5`; `02_deploy_surface_taxonomy.md §2.7`; `00_deploy_brief.md §5.8`.

#### Design: SQLite table `fleet_refresh_queue` + `fleet_refresh_items`

```sql
CREATE TABLE IF NOT EXISTS fleet_refresh_queue (
    queue_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL,             -- "running" | "completed" | "cancelled" | "failed"
    total_items INTEGER NOT NULL,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    skipped_items INTEGER NOT NULL DEFAULT 0,
    config_source TEXT NOT NULL DEFAULT "server_default",
    server_id TEXT,
    cancelled_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS fleet_refresh_items (
    queue_id TEXT NOT NULL REFERENCES fleet_refresh_queue(queue_id),
    machine TEXT NOT NULL,
    mode INTEGER NOT NULL,
    queue_position INTEGER NOT NULL,      -- for deterministic ORDER BY (R validator EC-3)
    status TEXT NOT NULL DEFAULT "pending",
    run_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (queue_id, machine, mode)
);
```

#### R4 — Cell-Busy Stall Timeout (behavioral contract, not open question)

v1 punted this as an open question. Per `05_deploy_critique.md §3 M1` and `06_deploy_validation.md §2 Case 4`, this is a behavioral contract that must be specified.

**Decision:**

- Fleet refresh cell-busy timeout: **30 minutes** (configurable via `SLOT_FLEET_CELL_BUSY_TIMEOUT_S` env var, default 1800).
- If `registry.try_acquire_cell(machine, mode, SAMPLING)` returns False for a total accumulated wait exceeding 30 minutes, the item is logged as `status='skipped'` with reason `"cell_busy_timeout"` and `attempt_count` is NOT incremented (timeout skip is not a failure retry).
- `GET /api/fleet/refresh` response includes `skipped_items` count and per-item reasons. The operator can re-trigger a fleet refresh to pick up any skipped items.
- This is **INV-X** (new invariant): "fleet refresh never permanently stalls; cells busy longer than `SLOT_FLEET_CELL_BUSY_TIMEOUT_S` are skipped and recorded."

Per brief §5.8: "per-machine failure auto-retry + final skip, doesn't block remaining 392." The same policy applies to cell-busy stall: it doesn't block the remaining machines.

Source: `05_deploy_critique.md §3 M1`; `00_deploy_brief.md §5.8`.

#### Resume Algorithm

```python
# On startup: StateStore.__init__ runs _recover_fleet_refresh()
def _recover_fleet_refresh(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute(
            "SELECT queue_id FROM fleet_refresh_queue WHERE status='running' LIMIT 1"
        ).fetchone()
        if row:
            queue_id = row[0]
            conn.execute(
                "UPDATE fleet_refresh_items SET status='pending', run_id=NULL "
                "WHERE queue_id=? AND status='running'",
                (queue_id,)
            )
            conn.commit()
            fleet_mgr.schedule_resume(queue_id)
    except sqlite3.OperationalError:
        pass  # Tables don't exist yet (pre-Phase-3 database) — safe to ignore
    finally:
        conn.close()

def _next_pending_item(queue_id: str) -> dict | None:
    # ORDER BY queue_position ASC for deterministic, testable resume order (EC-3 fix)
    return conn.execute(
        "SELECT machine, mode, attempt_count FROM fleet_refresh_items "
        "WHERE queue_id=? AND status='pending' "
        "ORDER BY queue_position ASC LIMIT 1",
        (queue_id,)
    ).fetchone()

# FleetRefreshManager.run_queue():
def run_queue(queue_id: str) -> None:
    while True:
        if _is_cancelled(queue_id):  # poll cancel flag (also checked in token wait loop)
            _mark_queue_cancelled(queue_id)
            return
        item = _next_pending_item(queue_id)
        if item is None:
            _mark_queue_completed(queue_id)
            return

        machine, mode = item["machine"], item["mode"]
        cell_busy_start = time.monotonic()

        while True:
            if _is_cancelled(queue_id):
                _mark_queue_cancelled(queue_id)
                return
            if registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING):
                break  # acquired
            elapsed = time.monotonic() - cell_busy_start
            if elapsed >= CELL_BUSY_TIMEOUT_S:
                _mark_item_skipped(queue_id, machine, mode, "cell_busy_timeout")
                break
            time.sleep(YIELD_SLEEP_S)  # 5 seconds between retry attempts
        else:
            continue  # timed out, move to next item

        # Rate-limit: acquire token before launching (see §4.5)
        acquired = rate_limiter.wait_for_token(priority="background",
                                                cancel_flag=lambda: _is_cancelled(queue_id))
        if not acquired:  # cancel fired
            registry.release_cell(machine, mode, CellOperation.SAMPLING)
            _mark_queue_cancelled(queue_id)
            return

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
                _mark_item_pending(queue_id, machine, mode)

        registry.release_cell(machine, mode, CellOperation.SAMPLING)
```

**Single-instance enforcement** (unchanged from v1): `POST /api/fleet/refresh` checks for existing `status='running'` row before creating a new one.

---

### 4.5 Rate-Limit Shared Bucket + Priority

#### Problem

120 concurrent upstream requests from 5 planners can self-DoS the server. No shared rate limiter exists.

Source: `03_deploy_concurrency_blast_radius.md Scenario 9`.

#### R2 — Revised Mechanism: `Semaphore(N)` as Max-Concurrent-Items Cap

**Why the v1 token-bucket mechanism was wrong:**

The v1 token bucket (capacity=10, refill_rate=3/s) governed item **launch rate**, not steady-state concurrency. An analyzer subprocess, once launched, maintains up to `batch_concurrency=8` concurrent upstream HTTP connections for its entire lifetime (potentially 15-60 minutes for large `max_chunks`). With capacity=10, the burst immediately launches 10 items = 80 concurrent connections. At refill_rate=3/s, 10 more items launch in 3.3 seconds = 80 more connections. The token bucket did not limit concurrent connections at all.

Source: `05_deploy_critique.md §2 CI-2`; `06_deploy_validation.md §4 EC-1`.

**Revised design: `threading.Semaphore(N)` caps max concurrent running analyzers**

```
src/web_console/backend/rate_limiter.py
```

```python
# Pseudocode
class ConcurrencyLimiter:
    """Controls total concurrent running analyzer subprocesses across all callers.

    N_SLOTS = max concurrent analyzers (both foreground + background combined).
    FOREGROUND_RESERVE = slots always available to foreground (ad-hoc) callers.
    Background callers may only use slots above foreground_reserve.

    Mathematical guarantee:
        total concurrent analyzers <= N_SLOTS
        total upstream HTTP connections <= N_SLOTS * batch_concurrency
        e.g. N_SLOTS=5, batch_concurrency=8 → max 40 concurrent upstream connections
    """
    def __init__(self, n_slots: int = 5, foreground_reserve: int = 2):
        self._semaphore = threading.Semaphore(n_slots)
        self._n_slots = n_slots
        self._foreground_reserve = foreground_reserve
        self._active_count = 0
        self._lock = threading.Lock()

    def acquire(self, priority: str = "foreground",
                timeout: float | None = 30.0,
                cancel_flag: Callable[[], bool] | None = None) -> bool:
        """Block until a slot is available.
        Foreground: may consume down to slot 0; timeout=30s default.
        Background: may only consume slots above foreground_reserve; waits indefinitely
                    unless cancel_flag fires.
        Returns True if slot acquired; False on timeout or cancel."""
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            if cancel_flag and cancel_flag():
                return False
            with self._lock:
                available = self._n_slots - self._active_count
                threshold = 1 if priority == "foreground" else self._foreground_reserve + 1
                if available >= threshold:
                    self._semaphore.acquire(blocking=False)
                    self._active_count += 1
                    return True
            if deadline and time.monotonic() >= deadline:
                return False
            time.sleep(0.2)

    def release(self) -> None:
        with self._lock:
            self._active_count -= 1
        self._semaphore.release()
```

**Default parameters:**

- `n_slots = 5` — at most 5 concurrent analyzer subprocesses (5 × 8 = 40 concurrent upstream connections; well within ~1k/s limit)
- `foreground_reserve = 2` — 2 slots always available to foreground callers; background waits until active_count < 3
- Foreground `timeout = 30.0` seconds — ad-hoc planner waits up to 30s, then 503
- Background `cancel_flag` — fleet refresh passes a lambda that checks `_is_cancelled(queue_id)`

**Why `Semaphore(N)` over token bucket:**

The token bucket governs launch rate; the semaphore governs concurrency count. For the target scenario, concurrency count is the correct lever — we want to cap total concurrent upstream connections, not limit how fast new items launch. A simple semaphore directly models this and is trivially correct to reason about.

**Foreground priority mechanism:**

Background callers check `active_count < n_slots - foreground_reserve` before acquiring. This ensures that if 3 background items are running (active_count=3, with foreground_reserve=2), background cannot start a 4th item (would need active_count < 3, but it equals 3). Foreground callers check `active_count < n_slots` (any free slot).

**Integration points:**

- `BatchRunManager._run_one`: `rate_limiter.acquire("foreground", timeout=30)` before `RunManager.start_run()`, `rate_limiter.release()` in finally block after run completes.
- `FleetRefreshManager.run_queue`: `rate_limiter.acquire("background", cancel_flag=lambda: _is_cancelled(queue_id))` before each item dispatch.

The limiter is a singleton initialized in `create_app()` and injected into `BatchRunManager` and `FleetRefreshManager`.

**Minor: cancel-flag in wait loop (critic m1 fix):**

The `cancel_flag` parameter in `acquire()` allows `FleetRefreshManager` to exit the wait loop promptly when the fleet refresh is cancelled, rather than waiting the full `YIELD_SLEEP_S` per iteration.

---

### 4.6 Report Stale-Tagging

#### Problem

`delete_rawdata` removes chunks but does not tag surviving reports as `underlying_removed=True`. Reports appear valid indefinitely after rawdata deletion.

Source: `03_deploy_concurrency_blast_radius.md Scenario 12`; `00_deploy_brief.md §5.6`; `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md`.

#### R6 — `all-data` delete carve-out from INV-7

The validator (Case 13 — FAIL) confirmed that `DELETE /api/machines/{machine}/all-data` deletes BOTH rawdata AND reports. Calling `_tag_reports_stale` in step 1 and `shutil.rmtree(reports/M)` in step 2 produces a meaningless write-then-delete sequence.

**Resolution:** INV-7 is scoped to rawdata-only delete paths. The `all-data` endpoint is explicitly exempt.

Updated invariant:

> **INV-7 (v2)**: "Deleting rawdata via `DELETE /api/rawdata/{machine}`, `DELETE /api/rawdata/{machine}/mode/{mode}`, `DELETE /api/rawdata/{machine}/mode/{mode}/version`, or via `delete_rawdata()` force=True always sets `underlying_removed=true` on all surviving report index entries for the affected (machine, mode). The `DELETE /api/machines/{machine}/all-data` endpoint deletes both rawdata and reports entirely; reports do not survive to be tagged; this endpoint is explicitly exempt from INV-7."

**Rationale (brief §5.6 intent):** Brief §5.6 states "Reports based on deleted rawdata stay but tag `underlying_removed=true`." The key word is "stay" — reports survive. The `all-data` endpoint is the "catastrophic reset" button (code comment at `app.py:6283`); it explicitly nukes everything. The brief's constraint applies to rawdata-only deletion, not to full machine reset. Source: `05_deploy_critique.md §3 M4`; `06_deploy_validation.md §2 Case 13`.

#### R7 — Fourth rawdata delete path added

v1 §4.6 enumerated 3 delete paths: `delete_rawdata(force=False)`, `delete_rawdata(force=True)`, and `DELETE /api/machines/{machine}/all-data`. The validator (EC-4) and the `app.py:6043` grep confirm a fourth path: `DELETE /api/rawdata/{machine}/mode/{mode}/version`.

This endpoint deletes individual version files. If all versions for a mode are deleted via repeated version deletes, the mode's rawdata is effectively empty but stale tagging was never triggered.

**Fix:** Add `_tag_reports_stale` call to `DELETE /api/rawdata/{machine}/mode/{mode}/version` at `app.py:6043`, triggered when the delete empties the mode's rawdata directory (i.e., the last chunk for that mode is removed). Condition: after version delete, if `len(remaining_chunks_for_mode) == 0`, call `_tag_reports_stale(machine, mode, ...)`.

**Complete `_tag_reports_stale` call site list (4 paths):**

1. `delete_rawdata(machine, mode, force=False)` — `app.py:1040`
2. `delete_rawdata(machine, mode, force=True)` — same function, force path
3. `DELETE /api/rawdata/{machine}` — `app.py:6253`
4. `DELETE /api/rawdata/{machine}/mode/{mode}/version` — `app.py:6043`, when delete empties the mode

(5th path `DELETE /api/machines/{machine}/all-data` — **exempt per INV-7 v2 above**)

Source: `06_deploy_validation.md §4 EC-4`.

#### `_tag_reports_stale` implementation — fixing M2 (no silent swallow)

v1 used `except Exception: pass`. This violates `memory/feedback_no_silent_swallow.md`. If the stale-tag write fails, the rawdata is deleted but reports appear valid — exactly the scenario `03_deploy_concurrency_blast_radius.md Scenario 12` identified.

```python
def _tag_reports_stale(machine: str, mode: int, reports_root: Path,
                        store: StateStore, state_dir: Path) -> None:
    """Tag all reports for (machine, mode) as underlying_removed=True.
    Failure is persisted to disk and surfaced via GET /api/system-state."""
    index_path = reports_root / machine / f"mode_{mode}" / "index.json"
    error_detail = None
    try:
        if index_path.exists():
            def _mark_stale(data):
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict):
                            entry["underlying_removed"] = True
                return data
            atomic_json_read_modify_write(index_path, _mark_stale)
        store.mark_runs_underlying_removed(machine, mode)
    except Exception as exc:
        error_detail = {"machine": machine, "mode": mode, "error": str(exc),
                        "ts": utc_now()}
        # Persist diagnostic (per memory/feedback_no_silent_swallow.md):
        diag = state_dir / "stale_tag_error.json"
        try:
            atomic_json_write(diag, error_detail)
        except Exception:
            pass  # last-resort — can't write diagnostic; log to stderr
        import sys
        print(f"[ERROR] _tag_reports_stale failed: {error_detail}", file=sys.stderr)
        raise  # re-raise so callers can return 500 rather than silently continue
```

`GET /api/system-state` includes `stale_tag_error` field read from `state/console/stale_tag_error.json`.

Source: `05_deploy_critique.md §3 M2`.

---

### 4.7 Service Wrapper + Intranet Binding

(Mostly unchanged from v1, with PowerShell version fix from critic S1.)

**Intranet binding:** Change uvicorn `--host 127.0.0.1` to `--host 0.0.0.0` (or `$env:SLOT_BIND_HOST` with default `0.0.0.0`).

**Service wrapper: PowerShell restart loop + Windows Task Scheduler**

No new software. `start_console.ps1` extended with a restart loop.

**S1 fix — PowerShell version compatibility:**

v1 used the `??` null-coalescing operator which requires PowerShell 7.0. Windows Server/10 may ship PowerShell 5.1 by default (Task Scheduler fails silently).

Replace `??` with explicit `if`/`else` for PowerShell 5.1 compat:

```powershell
# Instead of:  $env:SLOT_BIND_HOST ?? "0.0.0.0"
# Use:
$bindHost = if ($env:SLOT_BIND_HOST) { $env:SLOT_BIND_HOST } else { "0.0.0.0" }
$bindPort = if ($env:SLOT_BIND_PORT) { $env:SLOT_BIND_PORT } else { "8877" }

$MAX_RESTARTS = 5
$restarts = 0
while ($restarts -lt $MAX_RESTARTS) {
    python -m uvicorn src.web_console.backend.main:app `
        --host $bindHost `
        --port $bindPort `
        --log-level info `
        2>&1 | Tee-Object -FilePath $LOG_FILE -Append
    if ($LASTEXITCODE -eq 0) { break }
    $restarts++
    Write-Host "uvicorn exited with $LASTEXITCODE; restart $restarts/$MAX_RESTARTS in 5s"
    Start-Sleep -Seconds 5
}
# After exhausting restart budget: write event to Windows Event Log so
# monitoring can detect it (no silent failure per feedback_no_silent_swallow.md):
if ($restarts -ge $MAX_RESTARTS) {
    Write-EventLog -LogName Application -Source "SlotConsole" `
        -EntryType Error -EventId 1001 `
        -Message "SlotConsole uvicorn exhausted restart budget ($MAX_RESTARTS restarts)"
}
```

This is PowerShell 5.1-compatible. The `Write-EventLog` call also surfaces the "exhausted restart budget" state to Windows Event Viewer, addressing critic FA-4 (no alert for permanent-down server).

**chart.js CDN fix, SQLite WAL mode:** Unchanged from v1.

---

### 4.8 Background Disk Monitor

Unchanged from v1. Added note per critic m2:

The disk monitor daemon (Phase 2 deliverable) calls `_auto_cleanup_for_space`. This function must be migrated to use `registry.get_active_cells()` (Phase 2 deliverable #9) BEFORE the disk monitor daemon starts. These two deliverables are explicitly sequenced: deliverable #9 (cleanup function migration) must complete in the same commit as or before deliverable #11 (disk monitor daemon start). They are a single atomic unit within Phase 2.

---

## §5 Test Plan (5 Dimensions) — v2 Updates

### 5.1 Design-Level Invariants — v2

| Invariant ID | Statement | Source hazard |
|---|---|---|
| **INV-1** | For any `(machine, mode)`, at most ONE `SAMPLING` and ONE `GENERATING` registration can be active simultaneously; `DELETING` is exclusive with both (regardless of config_id — same machine+mode serializes) | Scenario 1a, 2, 6 |
| **INV-2** | `delete_rawdata(machine, mode)` returns 409 when `CellLockRegistry` has any active registration for `(machine, mode)` | Scenario 6, H2 |
| **INV-3** | `configs/machines.json` write is always atomic (tmp+os.replace) and serialized (per-file lock) | Scenario 16, C1 |
| **INV-4** | `rawdata/_index.json` write is serialized via `msvcrt.locking` (cross-process exclusive file lock on Windows) + `threading.Lock` (within-process) | Scenario 2, H3 |
| **INV-5** | For any `config_id`, concurrent uploads of the same content produce exactly one registry entry and one content file | Scenario 11 |
| **INV-6** | `(config_id, machine, mode, upstream_md5)` 4-tuple uniquely identifies a rawdata bucket; concurrent same-4-tuple fetches: second planner attaches to first (not rejected) | Brief §5.7 |
| **INV-7 (v2)** | Deleting rawdata via `DELETE /api/rawdata/{machine}`, `DELETE /api/rawdata/{machine}/mode/{mode}`, `DELETE /api/rawdata/{machine}/mode/{mode}/version` (when empties mode), or `delete_rawdata()` always sets `underlying_removed=true` on surviving reports. `DELETE /api/machines/{machine}/all-data` is exempt (deletes reports entirely) | Scenario 12, brief §5.6, Case 13 |
| **INV-8** | Fleet refresh has at most one `status='running'` queue at any time | Brief §5.8 |
| **INV-9** | Fleet refresh resumes after process death: all items that were `running` at crash are re-queued as `pending` | Scenario 5 |
| **INV-10** | `ConcurrencyLimiter` maintains `active_count <= n_slots` at all times; foreground callers can always consume if `active_count < n_slots`; background waits until `active_count < n_slots - foreground_reserve` | §4.5 |
| **INV-11** | `BatchGenerateManager` registers `GENERATING` in `CellLockRegistry` before each worker's execution (replaces existing `_acquire_in_use` pattern — unification, not bug-fix) | Scenario 2, `app.py:7212` |
| **INV-12** | `_auto_cleanup_for_space` always skips cells with any active `CellLockRegistry` registration | Scenario 2, 6 |
| **INV-13** | `reports/<M>/mode_<N>/index.json` and `latest.json` writes are always atomic (tmp+os.replace) | Cluster D |
| **INV-14** | `configs/servers.json` write is always atomic (tmp+os.replace, per-file lock) | Cluster A |
| **INV-15** | SQLite `console.db` is opened with `journal_mode=WAL` and `busy_timeout=5000` | §4.7 |
| **INV-X** | Fleet refresh never permanently stalls; cells busy longer than `SLOT_FLEET_CELL_BUSY_TIMEOUT_S` (default 1800s) are skipped with `"cell_busy_timeout"` reason | §4.4 R4 |

---

### 5.2 Impl-Level Tests — v2 changes

Changes from v1:

**Group T1 — `CellLockRegistry` unit tests:** Add `test_attach_response_when_same_4_tuple_in_flight` (tests R9 attach semantics).

**Group T4 — `rawdata_index.py` concurrent write (R3 replacement):**

```
test_concurrent_update_entry_no_lost_entries_cross_process
    # Spawn 4 separate Python subprocesses each calling update_entry() concurrently
    # Assert: all 4 entries present in final index
    # Inject bug: remove msvcrt.locking → cross-process race → ~1 lost entry per 10 runs
    # (replaces mtime-retry test from v1 which was testing an insufficient mechanism)
test_update_entry_within_process_threading_lock
test_remove_entry_concurrent_with_update_entry_cross_process
```

**Group T5 — delete_rawdata + stale-tag (R6, R7, M2 fixes):**

```
test_delete_tags_all_four_paths
    # Path 1: delete_rawdata(force=False)
    # Path 2: delete_rawdata(force=True)
    # Path 3: DELETE /api/rawdata/{machine}
    # Path 4: DELETE /api/rawdata/{machine}/mode/{mode}/version (when last chunk removed)
    # Each path must tag reports stale (INV-7 v2)
test_all_data_delete_removes_reports_not_tags
    # DELETE /api/machines/{machine}/all-data
    # Assert: reports directory is DELETED (not tagged) — correct per INV-7 v2 carve-out
    # Assert: no stale_tag_error.json written (not an error, intentional delete)
test_stale_tag_failure_persists_diagnostic
    # Mock atomic_json_read_modify_write to raise IOError
    # Call delete_rawdata
    # Assert: stale_tag_error.json written with machine/mode/error/ts
    # Assert: GET /api/system-state includes stale_tag_error field
    # Inject bug: remove persist-to-disk in _tag_reports_stale → diagnostic not written → test red
```

**Group T5 addition: `test_delete_tags_version_delete_empties_mode`:**

```
test_version_delete_triggers_stale_tag_on_last_chunk
    # Create mode with 2 version chunks
    # Delete version 1 → no stale tag (1 chunk remains)
    # Delete version 2 → stale tag fires (mode now empty)
    # Assert index.json entries have underlying_removed=True after 2nd delete
    # Inject bug: remove stale-tag from version delete → remains False → test red
```

**Group T7 — Fleet refresh (R4 addition):**

```
test_fleet_refresh_cell_busy_timeout_skips_item
    # Register SAMPLING for M14|1 for duration > CELL_BUSY_TIMEOUT_S
    # Assert: fleet refresh marks item as status='skipped', reason='cell_busy_timeout'
    # Assert: fleet refresh moves to next item (not permanently stalled)
    # Inject bug: remove timeout check → fleet refresh loops forever → test hangs
test_fleet_refresh_cancel_exits_token_wait_promptly
    # Background caller in acquire() wait loop; fire cancel_flag
    # Assert: returns within 0.5s (not after full timeout)
```

**Group T8 — Rate limiter (R2 replacement):**

```
test_semaphore_caps_concurrent_items_at_n_slots
    # Spawn n_slots+2 concurrent acquire() calls
    # Assert: at most n_slots succeed simultaneously (counted by release)
    # Inject bug: remove semaphore.acquire check → >n_slots concurrent → test red
test_foreground_can_consume_all_slots
test_background_waits_when_only_foreground_reserve_available
    # active_count = n_slots - foreground_reserve (background threshold not met)
    # foreground acquires immediately; background waits
test_foreground_timeout_returns_false
```

**Group T9 — E2E (R2/R9 updates):**

```
test_two_concurrent_batch_runs_different_cells_both_complete
    # Uses --from-cache with existing M14/M15 cached chunks
    # Per memory/feedback_no_proactive_fetch.md and feedback_perf_claim_needs_e2e_event_stream.md
    # NOT real upstream fetch
test_same_cell_second_planner_attaches_not_fails
    # Planner A submits batch-run M14|1 (cache-based)
    # Before A completes: Planner B submits same M14|1 same config_id
    # Assert: B's item shows status='attached' with run_id pointing to A's run
    # Inject bug: remove attach check → B gets status='failed'
```

**Group T10 — Sidecar migration (new, R10):**

```
test_load_chunks_index_migrates_missing_by_config_id
    # Create a v1 _chunks.json without by_config_id field
    # Call load_chunks_index()
    # Assert: by_config_id = {"null": [all existing chunk names]}
    # Assert: each chunk entry has config_id="null"
    # Assert: migrated sidecar written to disk (v3 layout)
    # Inject bug: remove migration step → by_config_id stays missing → dedup returns empty
```

**Frontend test correction (critic T7.5 fix):**

Frontend tests `test_frontend_error_branch_reset.js` and `test_frontend_fasttimer.js` require a browser test runner. Since the current frontend has no build tooling, these are specified for **Playwright** running against a live uvicorn instance (same pattern as the E2E tests in Group T9). No new build tooling required — Playwright can run headless against a `http://localhost:8877` URL. The test installs Playwright as a dev dependency in `requirements-dev.txt`.

**Group T11 — Frontend fleet refresh one-shot guard (R11, new):**

```
test_fleet_refresh_panel_uses_one_shot_guard_on_completion
    # Using Playwright: open fleet refresh panel in 2 simulated tabs
    # Both tabs poll GET /api/fleet/refresh
    # Simulate running → completed transition on server
    # Assert: each tab fires its own side-effect exactly once (one-shot flag per tab)
    # Assert: each tab does NOT fire the side-effect more than once per transition
    # Inject bug: remove _autoRefreshedForFleetRefreshId guard → 2 side-effects per tab
    # (per memory/feedback_fasttimer_overlap_needs_oneshot.md)
```

---

### 5.3 Deploy-Smoke Tests (unchanged)

Same 6 smoke tests as v1. Added:

```
smoke_07_powershell_version_check
    # Verify PowerShell version >= 5.1 on server
    # (7.0+ not required after S1 fix; 5.1 sufficient)
    $PSVersionTable.PSVersion.Major -ge 5
```

---

### 5.4 Runtime Monitoring (v2 additions)

| Task | Failure persisted to | Surfaced in UI via |
|------|---------------------|-------------------|
| `_tag_reports_stale` failure | `state/console/stale_tag_error.json` | `GET /api/system-state` `stale_tag_error` field |
| Pre-batch MD5 refresh thread | `state/console/md5_refresh_error.json` | `GET /api/system-state` `md5_refresh_error` field |
| Disk monitor daemon | `state/console/disk_monitor_last.json` | `GET /api/system-state` `disk_monitor` field |
| Fleet refresh item failure | SQLite `fleet_refresh_items.last_error` | `GET /api/fleet/refresh` `failed_items` list |
| Uvicorn restart budget exhausted | Windows Event Log (EventId 1001) | Admin checks Event Viewer or monitoring tool |
| `config_id` sidecar annotation failure | SQLite `pending_batch_configs` allows restart recovery | Startup log + restart re-association |

---

### 5.5 Regression Memory Mapping (updated)

Additions from v2:

| Memory file | Root cause | Corresponding test |
|---|---|---|
| `feedback_fasttimer_overlap_needs_oneshot.md` | Duplicate side-effect fire on transition | `test_fleet_refresh_panel_uses_one_shot_guard_on_completion` (Group T11); explicitly specifies `_autoRefreshedForFleetRefreshId` one-shot pattern |
| `reference_chunk_index_inverted_md5.md` | Cross-process sidecar race | `test_concurrent_update_entry_no_lost_entries_cross_process` (Group T4); uses `msvcrt.locking` instead of v1's insufficient mtime-retry |

---

## §6 Migration Phases — v2

### Phase 1: Critical Fix + Atomic Writes Cluster (Backward-Compatible)

**Deliverables (same as v1):**

1. `ConfigFileWriter` module (`src/web_console/backend/config_writer.py`).
2. Migrate `_do_refresh_machines_md5()` to `atomic_json_read_modify_write` (Critical C1).
3. Migrate `save_servers()` to `atomic_json_write`.
4. Migrate `_save_rawdata_locks()` to `atomic_json_read_modify_write`.
5. Migrate `_update_report_index` to `atomic_json_write` for `index.json` and `latest.json`.
6. Migrate `machines_static.json`, `machine_halls.json`, `settings.json` to `atomic_json_write`.
7. Add `msvcrt.locking`-based cross-process lock to `rawdata_index.update_entry()` (R3 — replaces v1 mtime-retry).
8. Add `_LOCK_CACHE` threading.Lock (minor TOCTOU fix).
9. Vendor `chart.min.js` into `frontend/vendor/`.
10. Enable SQLite WAL mode + `busy_timeout=5000` in `StateStore._init_db()`.
11. Add pre-batch MD5 thread error persisting to `state/console/md5_refresh_error.json`.

**Revert plan:** `git revert <phase-1-commit>`. No schema changes in Phase 1. SQLite WAL pragma is idempotent on re-application. Note: after WAL enable, `console.db` has `-wal` and `-shm` sidecars; reverting Phase 1 code leaves these files but SQLite handles them on next EXCLUSIVE connection. No data loss risk.

**Verification:** Run T2, T3, T4 (updated with cross-process test), Group smoke 01-05 + 07.

---

### Phase 2: Cell Concurrency Unified Refactor (Atomic Cutover)

**Key constraint (R5/R12):** `OperationCoordinator` is removed entirely in one atomic Phase 2 commit. No intermediate "retained for compat" state. All callers from the cutover table in §4.1 must be migrated in the same commit.

**Deliverables:**

1. `CellLockRegistry` module (`src/web_console/backend/cell_lock_registry.py`).
2. Wire `CellLockRegistry` into `create_app()` as singleton; inject into `BatchRunManager`, `RunManager`, `BatchGenerateManager`.
3. Replace `BatchRunManager._busy_keys` + `_try_acquire_key` / `_release_key` with `registry.try_acquire_cell(..., SAMPLING)`.
4. Replace `BatchRunManager._acquire_in_use` / `_release_in_use` calls with registry calls (eliminates `_IN_USE_MODES`).
5. Replace `RunManager.start_run` (from-cache generate path) ops call with `registry.try_acquire_cell(..., GENERATING)`.
6. Replace `BatchGenerateManager` per-item `_acquire_in_use` call (at `app.py:7212`) with `registry.try_acquire_cell(..., GENERATING)` (unification refactor — existing behavior preserved, new code path used).
7. Add `registry.try_acquire_cell(..., DELETING)` to all delete paths in `delete_rawdata()` and DELETE endpoints (H2 fix).
8. Implement `ConcurrencyLimiter` (`src/web_console/backend/rate_limiter.py`) with `Semaphore(N)` + foreground-reserve (R2). Wire into `BatchRunManager._run_one`.
9. **Migrate all `OperationCoordinator.acquire` calls per cutover table in §4.1. DELETE `OperationCoordinator` class and all imports. This is a single atomic commit.**
10. Migrate `_auto_cleanup_for_space` to use `registry.get_active_cells()` (replaces `_get_in_use_snapshot()`).
11. Add disk monitor daemon thread (§4.8). **This deliverable is sequenced AFTER deliverable #10** (cleanup function must be registry-aware before daemon starts).
12. Add attach-response logic to `BatchRunManager._run_one` (R9).
13. `GET /api/system-state` returns `registry.snapshot()`.

**Revert plan:** `git revert <phase-2-commits>`. Restores old `_busy_keys` + `_IN_USE_MODES` + `OperationCoordinator`. Data on disk unmodified.

**Verification:** T1, T5, T8, T9. Grep check: `grep -rn "OperationCoordinator" src/web_console/` must return 0 results after Phase 2 commit. Also: `grep -rn "_acquire_in_use\|_busy_keys" src/web_console/` must return 0 results.

---

### Phase 3: New Features

**Deliverables (v2 additions):**

1. `POST /api/configs/upload`, `GET /api/configs`, `GET /api/configs/{config_id}` endpoints.
2. Config registry + content files in `configs/uploaded_configs/`.
3. Write-config-first ordering + `pending_batch_configs` SQLite table (R8).
4. `config_id` field + `by_config_id` index added to `_chunks.json`; lazy migration step in `load_chunks_index` for existing sidecars (R10 / critic m3 fix).
5. SQLite `fleet_refresh_queue` + `fleet_refresh_items` tables.
6. `FleetRefreshManager` with `run_queue()` daemon + cell-busy timeout (R4).
7. `_recover_fleet_refresh()` in `StateStore.__init__` (with `sqlite3.OperationalError` guard for pre-Phase-3 databases).
8. `POST /api/fleet/refresh`, `GET /api/fleet/refresh`, `DELETE /api/fleet/refresh` endpoints.
9. `ConcurrencyLimiter` wired into `FleetRefreshManager.run_queue` (complement to Phase 2 which wired it for foreground callers).
10. `_tag_reports_stale()` added to all four rawdata delete paths (INV-7 v2, R6, R7). `all-data` endpoint remains exempt.
11. `underlying_removed` column in SQLite `runs` table.
12. Frontend: config upload panel (reusing existing file-upload pattern); fleet refresh progress panel with `_autoRefreshedForFleetRefreshId` one-shot guard (R11, per `memory/feedback_fasttimer_overlap_needs_oneshot.md`).

**Backward compat:** Existing rawdata/reports/configs unmodified. `config_id="null"` default for all existing chunks via lazy sidecar migration. `underlying_removed=0` default for existing runs.

**Revert plan:** SQLite additions via `ALTER TABLE ADD COLUMN DEFAULT` are forward-only. Old code ignores new columns. New tables (`fleet_refresh_queue`, `fleet_refresh_items`, `pending_batch_configs`) can be dropped if needed but are inert if left. Config uploads dir is inert without endpoints.

**Verification:** T6, T7, T10, T11. Full smoke suite.

---

### Phase 4: Deploy + Service Wrapper

**Deliverables (v2 additions):**

1. `start_console.ps1` extended: `--host 0.0.0.0`, restart loop with PowerShell 5.1-compatible syntax (S1 fix), Windows Event Log entry on restart budget exhaustion.
2. `SLOT_BIND_HOST` and `SLOT_BIND_PORT` env var support in `main.py`.
3. Task Scheduler `.xml` with **dynamic repo path substitution** (not hardcoded `C:\...`; uses `%~dp0` or runtime variable to derive repo root).
4. `scripts/deploy/README_DEPLOY.md`: step-by-step including PowerShell version check, Event Viewer monitoring note, Task Scheduler user account requirement.
5. Smoke test suite runnable from LAN: `scripts/deploy/run_smoke.ps1`.
6. `scripts/deploy/rollback.ps1`.

**Revert plan:** Task Scheduler task delete (`schtasks /Delete /TN "SlotConsole" /F`). Revert bind host via env var. No data changes.

**Verification:** `smoke_01-07` from LAN. Task Scheduler restart test. Windows Event Log event on restart budget exhaustion.

---

## §7 Alternatives Considered

### Alt 7.1: Concurrency Model (§4.1)

**Alt A (chosen): `CellLockRegistry` unified in-memory class.** Per-cell granularity; atomic cutover; OperationCoordinator removed.

**Alt B: Minimal patches.** Each gap patched individually. `OperationCoordinator` bottleneck remains. Rejected ("不要保守").

**Alt C: Per-cell SQLite lock rows.** DB roundtrips on every chunk write; stale lock risk on crash. Rejected.

### Alt 7.2: Fleet Refresh Queue Persistence (§4.4)

**Alt Q1 (chosen): SQLite tables.** Fits existing stack, concurrent reads free in WAL mode, row-level atomicity for status updates.

**Alt Q2: JSON file.** 393-item file rewritten on every status change; write contention. Rejected.

**Alt Q3: Periodic JSON snapshot.** Up to 30s loss on crash. Rejected.

### Alt 7.3: Rate Limiter (§4.5) — v2 replaces v1 analysis

**Alt R1: Token bucket (v1 choice — rejected in v2).** Governs launch rate, not steady-state concurrency. With long-lived analyzers, burst capacity immediately saturates upstream. See CI-2 in `05_deploy_critique.md`.

**Alt R2 (chosen): `threading.Semaphore(N)` as max-concurrent-items cap.** Directly models the constraint (total concurrent connections = N × batch_concurrency). Simple, correct. Foreground reserve implemented via active_count threshold.

**Alt R3: No rate limiter.** Rely on upstream AIMD. Once throttled, stays throttled for hours. Rejected.

### Alt 7.4: H3 Fix Alternatives (§4.2) — new in v2

**Alt F1 (chosen): `msvcrt.locking` file-level exclusive lock.** Cross-process, Windows-specific (correct for deployment target), minimum code change.

**Alt F2: SQLite-mediated index registry.** Move `rawdata_index` to SQLite. Adds DB roundtrips per chunk write. Unnecessarily couples the derived cache to the DB.

**Alt F3: Per-cell index sharding (no global `_index.json`).** No shared file = no cross-process race. High migration cost (all sidecar read paths change). Deferred as future improvement.

---

## §8 Risk Register — v2

| Risk | Likelihood | Impact | Monitor / Mitigation |
|------|-----------|--------|---------------------|
| Phase 2 refactor misses a `delete_rawdata` call site | Medium | High (H2 persists) | grep CI check: `grep -rn "shutil.rmtree\|\.unlink()" src/web_console/` must show no unguarded path; T5 inject-bug required |
| `msvcrt.locking` unavailable on non-Windows dev machine | Low (dev may use Mac/Linux) | Low (function degrades to within-process lock, cross-process safety not needed on single-process dev) | `try/except AttributeError` wrapper; documented in code comment |
| SQLite WAL incompatible with network share for `state/console/` | Low (deploy target is local disk) | High (SQLite WAL unsupported on network shares) | README_DEPLOY.md explicitly: "state/console/ MUST be on local disk, not a network share" |
| `config_id` sidecar lazy migration misses some existing sidecars | Low | Medium (existing chunks not found in by_config_id lookup — triggers re-fetch) | T10 covers this; startup log should emit count of sidecars migrated |
| Fleet refresh 393-machine run exceeds concurrent slots | Low (n_slots=5 is conservative) | Low (throttled throughput, not data corruption) | Monitor via `registry.snapshot()` in GET /api/system-state |
| Task Scheduler running under SYSTEM account; file permission denied | Medium | High (server won't start) | README_DEPLOY.md: Task Scheduler user must own rawdata dir; smoke_01 catches on first boot |
| PowerShell 5.1 on target machine | Medium | Low (all ?? replaced; no PS7 requirement after S1 fix) | smoke_07 checks PS version |
| Phase 3 `_recover_fleet_refresh` crashes on pre-Phase-3 database | Low (with `OperationalError` guard) | High (creates_app fails) | Guard documented in §4.4; T7 covers fresh install |

---

## §9 Open Questions for Wave 3 (reduced from v1)

Revisions R1-R12 resolved the blocking open questions from v1. Remaining:

1. **`GENERATING` + `SAMPLING` coexistence per cell (OQ-1 from v1) — resolved by W3:** The critic confirmed (§8 OQ-1): "The coexistence is safe. The generator globs at startup; a new chunk renamed after that glob is simply not included in the generator's snapshot." No design change needed. Recorded here for implementer awareness.

2. **`FleetRefreshManager` virtual console injection:** `FleetRefreshManager` is a new singleton (Phase 3). The virtual console (`virtual_app.py:build_virtual_app`) calls `create_app()` with injected paths. If `FleetRefreshManager` is constructed inside `create_app()`, it must receive the same path overrides. Decision: `FleetRefreshManager` should NOT be constructed in `create_app()` if `build_virtual_app` does not need fleet refresh (the virtual console is for slot design, not fleet sampling). `create_app()` gains an optional `fleet_refresh_enabled: bool = True` parameter; `build_virtual_app()` passes `fleet_refresh_enabled=False`. Wave 3 implementer team to confirm this is the correct isolation strategy.

3. **`DELETE /api/machines/{machine}/all-data` — does the registry check iterate modes correctly?** The endpoint deletes all modes under a machine. `registry.try_acquire_cell(machine, mode, DELETING)` must be called for each mode. If mode 1 succeeds but mode 2 fails (another op active), should the whole-machine delete abort (releasing mode 1 lock) or proceed on mode 1 only? Decision here: **abort-and-rollback** — if any mode acquisition fails, release all successfully acquired DELETING locks and return 409. Partial mode deletion is confusing to operators. This should be confirmed before implementation.

---

## §10 Out of Scope

Same as v1 with one addition:

1. **Multi-worker uvicorn (`workers=N`):** Not needed for <10 users; would require shared-memory concurrency primitives. Out of scope.
2. **Authentication / authorization / RBAC:** Brief §5.3 prohibits user concept. No change.
3. **SSE / WebSocket for live status push:** Polling is sufficient for <10 users.
4. **Auto-detect "rawdata全部失效":** Brief §7 explicit OOS.
5. **L3 staging environment:** Brief §7 OOS.
6. **`slot_designer/` virtual console changes:** Phase 1-2 changes available automatically; fleet refresh disabled in virtual console via `fleet_refresh_enabled=False` parameter (OQ-2 above).
7. **Upstream API changes:** Rate limiting governs client side only.
8. **Replacing `BatchGenerateManager` `ProcessPoolExecutor`:** Cross-process sidecar race addressed by H3 fix; no executor model change.
9. **Max chunk count / data retention policy redesign:** Existing policy retained.
10. **Per-config-id sidecar sharding (allowing concurrent multi-config sampling on same machine):** The serialization constraint documented in INV-1 is a known limitation. Fixing it requires per-`(config_id, machine, mode)` sidecar sharding — a separate architecture review cycle. Explicitly deferred.

---

## §10 (v2) Revision Log v1 → v2

| R# | Source | v1 location | v2 location | Resolution |
|---|---|---|---|---|
| R1 | critic CI-1 | §3.2 H1 (factual error: BatchGenerateManager missing _acquire_in_use) | §3.2 (H1 removed; only 5 High hazards now); §4.1 (reframed as unification) | H1 removed from hazard list; confirmed `app.py:7212` already calls `_acquire_in_use`; Phase 2 deliverable #6 reworded to "unification refactor, not bug-fix" |
| R2 | critic CI-2 + validator EC-1 | §4.5 (token bucket capacity=10, refill_rate=3.0) | §4.5 (Semaphore(N) mechanism; n_slots=5) | Token bucket replaced entirely; `ConcurrencyLimiter` with `threading.Semaphore(5)` directly caps concurrent analyzers; math: 5 × 8 = 40 concurrent connections max |
| R3 | critic CI-3 | §4.2 (mtime-retry for rawdata_index H3) | §4.2 (msvcrt.locking exclusive file lock) | mtime-retry removed; `msvcrt.locking` cross-process exclusive lock on `_index.json` with within-process `threading.Lock` fallback |
| R4 | critic M1 + OQ-4 | §9 OQ-4 (punted as open question) | §4.4 (30-min configurable timeout, SLOT_FLEET_CELL_BUSY_TIMEOUT_S, skip with reason "cell_busy_timeout"); INV-X added | Cell-busy stall is now a specified behavioral contract, not a tuning question |
| R5 | critic M3 + validator EC-2 | §4.1 "OperationCoordinator retained + replaced" contradiction; §6 Phase 2 | §4.1 (atomic cutover table listing all 13 ops.acquire call sites); §6 Phase 2 (atomic cutover as single commit; OperationCoordinator deleted entirely) | Dual-active coexistence eliminated; explicit per-call-site disposition table |
| R6 | critic M4 + OQ-7 + validator Case 13 FAIL | §4.6 INV-7 applied to all delete paths including all-data; §9 OQ-7 punted | §4.6 INV-7 v2 scoped to rawdata-only paths; all-data carve-out explicit; _tag_reports_stale removed from all-data endpoint | INV-7 v2 scoping resolves the Case 13 FAIL verdict |
| R7 | validator EC-4 + Case 2 | §4.6 enumerated 3 delete paths | §4.6 (4th path: DELETE /api/rawdata/{machine}/mode/{mode}/version at app.py:6043); T5 test_delete_tags_all_four_paths | Version-specific delete path added to stale-tag call site list; triggers on last-chunk-removed condition |
| R8 | OQ-3 | §9 OQ-3 (config_id sidecar annotation crash window acknowledged as risk) | §4.3 (write-config-first ordering; pending_batch_configs SQLite table; startup re-association scan) | Simpler invariant than GC scan; no crash window for new fetches |
| R9 | validator Case 1 + EC-6 | §4.1 (second planner gets status='failed') | §4.1 (attach semantics: same 4-tuple in-flight → status='attached' with attached run_id) | INV-6 now specifies attach behavior; CellLockRegistry stores run_id/config_id/upstream_md5 per active SAMPLING |
| R10 | validator Case 10 | Not explicitly addressed in v1 | §4.1 (INV-1 scope documented: different config_ids on same machine+mode serialize; known limitation); §4.3 (lazy sidecar migration for by_config_id, T10 test group) | Serialization constraint documented as design choice; sidecar migration fix prevents empty by_config_id on existing data |
| R11 | validator Case 12 + EC-6 | Not specified in v1 | §4.5 (cancel_flag in acquire loop); §5.2 T11 (fleet refresh one-shot guard test); §6 Phase 3 deliverable #12 | _autoRefreshedForFleetRefreshId one-shot guard specified; Playwright test added; references memory/feedback_fasttimer_overlap_needs_oneshot.md |
| R12 | critic OQ-6 + R5 | §9 OQ-6 | Covered by R5 (atomic cutover table) | Phase 2 explicitly specifies single atomic commit removing OperationCoordinator entirely |
| R-A | critic m1 (cancel flag in token wait) | §4.5 (no cancel mechanism in wait loop) | §4.4 (cancel_flag parameter in ConcurrencyLimiter.acquire) | Background callers can exit wait promptly on fleet refresh cancellation |
| R-B | critic m2 (disk monitor before _auto_cleanup migration) | §6 Phase 2 (deliverables not sequenced) | §4.8 + §6 Phase 2 (deliverable #10 before #11 explicit sequencing) | Disk monitor start explicitly ordered after cleanup function migration |
| R-C | critic m3 (existing sidecars missing by_config_id) | §4.3 (backward compat via "treat missing as null") | §4.3 (explicit lazy migration step in load_chunks_index; T10 test group) | Lazy rebuild explicitly migrates existing chunks to by_config_id={"null": all_chunks} |
| R-D | validator Case 4 / Case 11 (ORDER BY missing in _next_pending_item) | §4.4 pseudocode (no ORDER BY) | §4.4 (ORDER BY queue_position ASC; queue_position column added to fleet_refresh_items schema) | Deterministic resume order for testing and operational predictability |

---

*Proposal v2 complete. All R1-R12 required revisions addressed. Wave 3 v2 review not required per brief §9 unless new structural issues are identified. Main session coordinator to consolidate into `07_deploy_decision.md`.*
