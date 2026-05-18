# P2 Implementation Brief: Cell Concurrency Unified Refactor (Atomic Cutover)

> **Date**: 2026-05-17
> **Phase**: 2 of 4 (per `session_artifacts/_arch/deploy/07_deploy_decision.md`)
> **Design source**: `session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md` §4.1 + §4.5 + §6 Phase 2
> **Baseline**: commit `c4d4e4a` (P1 + P1-fix)
> **Coordinator**: main session
> **Agent flow**: `impl-implementer` → `impl-tester` → `impl-verifier` → `impl-critic` (per `docs/ARCH_TEAM_PROCESS.md` §9)
> **Commit boundary**: **single atomic commit** (per 04_v2 §6 Phase 2 hard rule)

---

## §1 Context

P2 is the architecture-level refactor of cell-level concurrency. It replaces 4 independent in-memory primitives (`_IN_USE_MODES` set, `BatchRunManager._busy_keys`, `OperationCoordinator` single-flag, `_sidecar_lock_for` per-path dict) with one unified `CellLockRegistry` class. In the same atomic commit, the `OperationCoordinator` class is **deleted entirely** with all 13 of its `acquire` call sites migrated. Also adds `ConcurrencyLimiter` (Semaphore(N) cap on concurrent analyzer subprocesses replacing the v1 token bucket which had a wrong mechanism — see W3 critic CI-2).

P1 + P1-fix established the atomic-write groundwork. P2 builds on it. P3 (new features: config upload + fleet refresh queue) will build on P2.

**Atomic cutover rationale**: per 04_v2 §4.1 R5, having `OperationCoordinator` and `CellLockRegistry` coexist for ANY commit window produces inconsistent admission semantics (double-blocking or partial admission depending on call order). One commit replaces all 13 call sites + deletes the class.

---

## §2 Scope — 13 deliverables (per 04_v2 §6 Phase 2)

### D1 — Create `CellLockRegistry` module

File: `src/web_console/backend/cell_lock_registry.py` (NEW)

Design: 04_v2 §4.1 (read carefully before implementing). Key elements:

- `CellOperation` enum with values: `SAMPLING`, `GENERATING`, `DELETING`
- `CellLockRegistry` class with internal state:
  - `_registry: dict[tuple[str, int], set[CellOperation]]` — active operations per cell
  - `_sampling_info: dict[tuple[str, int], dict]` — per-active-SAMPLING: `{"run_id", "config_id", "upstream_md5"}` for attach lookup (R9)
  - `_lock: threading.Lock` — protects all registry mutations
  - `_global_ops: dict[str, bool]` — global ops (disk_cleanup, prune_versions, autotune, etc.)
- API:
  - `try_acquire_cell(machine: str, mode: int, op: CellOperation, info: dict | None = None) -> bool`
  - `release_cell(machine: str, mode: int, op: CellOperation) -> None`
  - `get_active_cells(op: CellOperation | None = None) -> set[tuple[str, int]]`
  - `get_active_sampling_info(machine: str, mode: int) -> dict | None` — for R9 attach
  - `try_acquire_global(name: str) -> bool`
  - `release_global(name: str) -> None`
  - `snapshot() -> dict` — for `GET /api/system-state`

Invariants (must enforce):

1. `SAMPLING` + `DELETING` mutually exclusive per cell (return False if other op present)
2. `GENERATING` + `DELETING` mutually exclusive per cell
3. `SAMPLING` + `GENERATING` on same cell: **allowed** (concurrent — sidecar atomic writes handle this safely)
4. At most ONE `SAMPLING` per cell
5. At most ONE `GENERATING` per cell
6. Global ops: at most ONE of each named global op at a time

### D2 — Create `ConcurrencyLimiter` module

File: `src/web_console/backend/rate_limiter.py` (NEW)

Design: 04_v2 §4.5 (read carefully). Key elements:

- `ConcurrencyLimiter` class with:
  - `_semaphore: threading.Semaphore(n_slots)` where `n_slots=5` default
  - `_active_count: int`
  - `_foreground_reserve: int = 2`
  - `_lock: threading.Lock`
- API:
  - `acquire(priority: str = "foreground", timeout: float | None = 30.0, cancel_flag: Callable[[], bool] | None = None) -> bool`
  - `release() -> None`
  - `active_count` property (for monitoring)

Foreground priority mechanism:
- Foreground: can consume any slot up to `active_count == n_slots`
- Background: can consume only when `active_count < n_slots - foreground_reserve` (so 2 slots are always reserved for foreground)
- Background uses `cancel_flag` to exit wait loop on fleet-refresh cancellation

Defaults from 04_v2 §4.5: `n_slots=5`, `foreground_reserve=2`, foreground `timeout=30.0`, background no timeout (cancel-driven).

### D3 — Wire registry + limiter into `create_app()`

`src/web_console/backend/app.py`:`create_app()`:

- Construct `CellLockRegistry()` singleton (one per `create_app` call)
- Construct `ConcurrencyLimiter(n_slots=5, foreground_reserve=2)` singleton
- Inject both into `BatchRunManager.__init__` + `RunManager.__init__` + `BatchGenerateManager.__init__`
- Store references on `app.state` for endpoints that need access (e.g. `GET /api/system-state`)

### D4 — Replace `BatchRunManager._busy_keys` with `CellLockRegistry`

`src/web_console/backend/app.py`:`BatchRunManager`:

- Remove `_busy_keys: set` instance attribute
- Remove `_try_acquire_key` / `_release_key` methods
- Replace all usages with `registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING, info={"run_id": ..., "config_id": ..., "upstream_md5": ...})` / `registry.release_cell(machine, mode, CellOperation.SAMPLING)`

### D5 — Eliminate `_IN_USE_MODES`

`src/web_console/backend/app.py`:

- Replace all `_IN_USE_MODES` reads with `registry.get_active_cells()` (returns set of (machine, mode) where ANY operation is active) — or `registry.get_active_cells(CellOperation.SAMPLING)` if only sampling is the concern
- Replace `_acquire_in_use` / `_release_in_use` with registry calls (matching the operation type — usually SAMPLING for batch worker contexts, GENERATING for from-cache contexts)
- Delete `_IN_USE_MODES` global set + `_IN_USE_LOCK` after all call sites migrated
- Delete `_acquire_in_use` / `_release_in_use` / `_get_in_use_snapshot` functions

### D6 — Replace `RunManager.start_run` ops call

`src/web_console/backend/app.py`:`RunManager.start_run`:

- Replace `ops.acquire("start_run")` with `registry.try_acquire_cell(machine, mode, CellOperation.GENERATING)`
- Release in same flow

### D7 — Replace `BatchGenerateManager` per-item `_acquire_in_use` with registry call

`src/web_console/backend/app.py`:`BatchGenerateManager` (around app.py:7212):

- The existing `_prepare_batch_gen_item_wrapper` calls `_acquire_in_use(machine, mode)`
- Replace with `registry.try_acquire_cell(machine, mode, CellOperation.GENERATING)`
- Release in `_finalize_batch_gen_item_wrapper`'s `finally` block

**Per critique CI-1**: this is a **unification refactor**, NOT a bug-fix. The existing call ALREADY guards correctly via `_IN_USE_MODES`; we're swapping in the registry.

### D8 — Add `DELETING` lock to all delete paths

For each rawdata delete path, acquire `CellOperation.DELETING` BEFORE the delete; release in finally:

- `delete_rawdata()` at `app.py:1040` — both `force=False` and `force=True` branches
- `DELETE /api/rawdata/{machine}` at `app.py:6253` — for each mode in the machine
- `DELETE /api/rawdata/{machine}/mode/{mode}` — if a separate endpoint exists
- `DELETE /api/rawdata/{machine}/mode/{mode}/version` at `app.py:6043` — per-version delete

If acquire fails (cell busy with SAMPLING or GENERATING), return HTTP 409 Conflict with message.

### D9 — `OperationCoordinator` atomic cutover (13 call sites)

Per 04_v2 §4.1 R5 cutover table. Each `ops.acquire(...)` is either:

- **Removed** (replaced by `registry.try_acquire_cell(..., GENERATING|DELETING)` per item):
  1. `"batch_generate_report"` at `app.py:2970` (BatchGenerateManager._run) — per-item GENERATING
  2. `"generate_report"` at `app.py:6772` (_run_generate_report) — GENERATING
  3. `"start_run"` (from-cache) inside RunManager.start_run — GENERATING (D6)
  4. `"delete_rawdata"` at `app.py:6269` — DELETING
  5. `"delete_machine_all_data"` at `app.py:6308` — DELETING per mode
  6. `"delete_run"` at `app.py:8650` — GENERATING (run is per-machine/mode)
  7. `"delete_report_version"` at `app.py:7447` — GENERATING

- **Migrated to `registry.try_acquire_global(name)`**:
  8. `"disk_cleanup"` at `app.py:6185`
  9. `"prune_versions"` at `app.py:8730`
  10. `"reports_cleanup"` at `app.py:7511`
  11. `"import_reports"` at `app.py:7584`
  12. `"autotune"` at `app.py:8878`
  13. `"refresh_machine_halls"` at `app.py:5625`

**After ALL 13 sites are migrated**: `DELETE` the `OperationCoordinator` class. `grep -rn OperationCoordinator src/web_console/` MUST return 0 results.

### D10 — `_auto_cleanup_for_space` uses registry

`src/web_console/backend/app.py`:`_auto_cleanup_for_space`:

- Replace `_get_in_use_snapshot()` with `registry.get_active_cells()` (cells with any active op should NOT have their chunks deleted)
- This deliverable MUST land in the same commit as D5 (since `_IN_USE_MODES` is deleted)

### D11 — Disk monitor daemon thread

Per 04_v2 §4.8. Add a daemon thread that periodically (e.g. every 60s) checks disk usage and triggers `_auto_cleanup_for_space` if above thresholds. This deliverable is **sequenced AFTER D10** (cleanup function must be registry-aware before daemon starts). Within the same commit but ordered: ensure D10 lines execute before the daemon-thread spawn.

### D12 — Attach-response semantics in `BatchRunManager._run_one` (R9)

When `registry.try_acquire_cell(machine, mode, SAMPLING)` returns False AND the existing SAMPLING info matches the requested `(config_id, upstream_md5)`:

- Return `{"status": "attached", "attached_to_run_id": active_run_id, "message": "..."}`
- Frontend reuses existing per-run progress polling on `attached_to_run_id`

When the existing SAMPLING info has different `(config_id, upstream_md5)`:

- Return `{"status": "failed", "error": "another batch is sampling this machine+mode"}`

Implementation requires `CellLockRegistry` to track `run_id` + `config_id` + `upstream_md5` per active SAMPLING (D1 `_sampling_info` field).

### D13 — `GET /api/system-state` exposes `registry.snapshot()`

`src/web_console/backend/app.py`:`GET /api/system-state` endpoint:

- Include `registry.snapshot()` output as `concurrency` field (or similar) in the response
- Shows: active SAMPLING cells, active GENERATING cells, active DELETING cells, active global ops
- Used by Phase 3 fleet refresh UI + by impl-verifier / impl-critic for sanity

---

## §3 Out of scope for P2

- **Phase 3 features**: config upload endpoint, fleet refresh queue, report stale-tagging, sidecar `by_config_id` migration. These are P3.
- **Phase 4**: deploy script, Task Scheduler integration, LAN binding. P4.
- **Same-machine different-config concurrent SAMPLING**: documented as INV-1 limitation per 04_v2 §4.1 R10. Sidecar restructuring is a future arch review, NOT P2.
- **`_MACHINES_SUMMARY_CACHE` / `_RAWDATA_OVERVIEW_CACHE` TOCTOU**: different access pattern from `_LOCK_CACHE` / `_STATIC_ATTRS_CACHE`. Deferred unless trivially included.
- **HTTP-level integration tests for `_refresh_md5_async` helper wiring**: P1-fix Not Verified item; can be added in P2 test suite if helpful but not required.

---

## §4 Constraints (must hold)

1. **Backward-compat existing single-user dev workflow**: same as P1-fix. The cutover from `OperationCoordinator` to registry should be transparent to single-user (same admission semantics — one global op at a time, one SAMPLING per cell). New: `DELETING` lock added; explicit 409 on cell-busy delete.
2. **No tech stack replacement**: FastAPI + uvicorn + SQLite + ProcessPoolExecutor stays. Only `threading` primitives.
3. **No silent failures**: any new `except: pass` must be documented per `memory/feedback_no_silent_swallow.md`.
4. **Atomic cutover**: P2 is ONE commit. No partial state. `grep OperationCoordinator src/web_console/backend/` must return 0 after this commit.
5. **Memory feedback adherence**: see §5 below.

---

## §5 Memory feedback files to honor

- `memory/feedback_enumerate_safety_paths.md` — inject-bug verification for each new lock (cell + global)
- `memory/feedback_no_silent_swallow.md` — any new failure paths persist diagnostic
- `memory/feedback_subprocess_import_suicide_and_module_globals.md` — `CellLockRegistry` is module-importable from `cell_lock_registry.py`; verify no side-effects on subprocess import
- `memory/feedback_respect_existing_codebase.md` — minimum-delta extension to existing primitives; rename `_busy_keys` → `_sampling_info` mental model, don't rewrite the world
- `memory/feedback_adversarial_self_review.md` — full impl-* loop required, no solo work
- `memory/feedback_perf_claim_needs_e2e_event_stream.md` — verifier runs real subprocess against cached fixtures
- `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md` — `DELETING` lock prevents delete races; no md5-based destruction
- `memory/feedback_arch_team_process.md` — workflow root
- `memory/feedback_impl_team_required.md` — impl-* team mandate

---

## §6 Test plan (impl-tester deliverables)

### Group P2-T1: `CellLockRegistry` unit tests

File: `tests/backend/test_cell_lock_registry.py` (NEW)

Tests:
- `test_sampling_acquire_release_basic` — acquire SAMPLING, verify present in `get_active_cells`, release, verify absent
- `test_sampling_and_deleting_mutually_exclusive` — INV-1: acquire SAMPLING then DELETING → returns False
- `test_generating_and_deleting_mutually_exclusive` — INV-2
- `test_sampling_and_generating_coexist` — INV-3: both succeed on same cell
- `test_one_sampling_per_cell` — INV-4: second SAMPLING acquire on same cell returns False (different config OR same config — both False at registry level; attach logic is upstream in BatchRunManager)
- `test_one_generating_per_cell` — INV-5
- `test_global_op_one_at_a_time` — INV-6
- `test_get_active_sampling_info_returns_stored_info` — R9 lookup
- `test_snapshot_serializable` — returns JSON-serializable dict
- `test_concurrent_acquire_release_thread_safety` — N threads alternating acquire/release on different cells; no torn state
- `test_release_unknown_cell_is_safe` — defensive: releasing what was never acquired doesn't crash

### Group P2-T2: `ConcurrencyLimiter` unit tests

File: `tests/backend/test_rate_limiter.py` (NEW)

Tests:
- `test_foreground_can_consume_all_slots` — N=5 foreground acquires succeed
- `test_background_blocked_when_only_foreground_reserve_available` — 3 foreground acquires (active=3, n_slots=5, reserve=2; available=2 = foreground_reserve+1, threshold for background); a 4th background acquire blocks
- `test_background_succeeds_when_above_threshold` — 1 foreground, then background can take 2 more (active=3 still below threshold)
- `test_foreground_timeout_returns_false` — slots all full + foreground waits 30s + timeout fires
- `test_background_cancel_flag_breaks_wait_loop` — background blocks; cancel_flag fires; returns False promptly (within 1s)
- `test_release_decrements_active_count` — basic
- `test_concurrent_acquire_release_thread_safety` — N threads each acquiring + releasing; final state consistent

### Group P2-T3: Cutover regression tests

File: `tests/backend/test_p2_cutover.py` (NEW)

Tests:
- `test_no_surviving_operation_coordinator_references` — grep app.py for `OperationCoordinator` → 0 hits
- `test_no_surviving_in_use_modes_references` — grep app.py for `_IN_USE_MODES`, `_acquire_in_use`, `_release_in_use`, `_get_in_use_snapshot` → 0 hits
- `test_no_surviving_busy_keys_references` — grep app.py for `_busy_keys`, `_try_acquire_key`, `_release_key` → 0 hits
- `test_delete_rawdata_returns_409_when_cell_busy` — acquire SAMPLING; attempt delete_rawdata for same cell; assert HTTP 409
- `test_delete_rawdata_succeeds_when_cell_free` — happy path
- `test_attach_response_when_same_4_tuple_sampling_in_flight` — R9: planner A acquires SAMPLING with (config_id=X, upstream_md5=Y); planner B requests same (X, Y); planner B sees `status='attached'` with A's run_id
- `test_reject_response_when_different_4_tuple_sampling_in_flight` — planner A acquires; planner B requests with different config_id; planner B sees `status='failed'`

### Group P2-T4: E2E concurrency tests

File: `tests/backend/test_p2_cutover.py` (continued)

Tests:
- `test_concurrent_generate_report_on_different_cells_both_succeed` — uses cached chunks; 2 generate-reports on M14|1 + M14|2 in parallel, both complete
- `test_concurrent_generate_report_on_same_cell_serialize` — M14|1 + M14|1; INV-5: only one at a time
- `test_disk_cleanup_skips_active_cells` — register SAMPLING for M14|1; trigger disk cleanup; assert M14|1 chunks NOT deleted

### Group P2-T5: Inject-bug for each new lock

Per `memory/feedback_enumerate_safety_paths.md`. Document recipes in test file docstrings:

- **CellLockRegistry SAMPLING lock**: temporarily replace registry's `_lock = threading.Lock()` with a no-op DummyLock → `test_one_sampling_per_cell` should fail (race produces 2 active SAMPLINGs).
- **CellLockRegistry global lock**: same → `test_global_op_one_at_a_time` should fail.
- **ConcurrencyLimiter semaphore**: remove `_semaphore.acquire(blocking=False)` line → `test_foreground_can_consume_all_slots` still passes (we don't acquire), but a concurrent N=10 acquire test would observe active_count > n_slots → that test should fail.
- **DELETING lock**: remove `try_acquire_cell(..., DELETING)` from delete_rawdata → `test_delete_rawdata_returns_409_when_cell_busy` should fail (delete proceeds even when sampling is active).

---

## §7 Verification plan (impl-verifier deliverables)

1. **Full P2-related test sweep**: P2-T1 to P2-T5 + all P1-fix tests + all `tests/backend/test_run_lifecycle.py` + `test_delete_report_version.py` + `test_safety_interlock.py` + any other suite that touched the migrated ops paths.
2. **Full broader sweep**: `python -m pytest tests/backend/` to catch any regression beyond explicit P2-related suites. Target: >= 977 passed (the P1-fix baseline).
3. **Grep audits** (claim D9): `grep -rn "OperationCoordinator" src/web_console/` → 0 matches. `grep -rn "_IN_USE_MODES\|_busy_keys\|_acquire_in_use\|_release_in_use" src/web_console/backend/app.py` → 0 matches.
4. **Smoke**: `python -c "from src.web_console.backend.app import create_app; app = create_app(); print(f'{len(app.routes)} routes')"` → expect 73 routes (same as P1-fix; no new endpoints added in P2; D13 modifies an existing endpoint).
5. **Module imports**: `python -c "from src.web_console.backend.cell_lock_registry import CellLockRegistry, CellOperation; from src.web_console.backend.rate_limiter import ConcurrencyLimiter; print('OK')"`
6. **Silent-swallow audit**: `git diff c4d4e4a -- src/ | grep -B 2 -A 1 "except.*:\s*pass"` → each new instance has explicit comment justification.
7. **Failure injection** (think-through, not necessarily run):
   - What if 2 threads simultaneously call `try_acquire_cell` for the same cell? Lock serializes; only one wins.
   - What if `release_cell` is called for an op that was never acquired? Defensive: no-op.
   - What if `OperationCoordinator` was being used by a thread that started before the cutover? It can't — cutover is atomic within one commit; no in-flight requests survive the deploy.
   - What if `BatchGenerateManager._run` is iterating items when one item's `registry.release_cell` raises? The finally must still execute.
   - What if all 5 ConcurrencyLimiter slots are taken by background full-refresh items and a foreground request comes in? Background should yield (foreground_reserve=2 always available) — verify.

---

## §8 Commit message draft (for impl-critic to fact-check)

```
refactor(phase2-deploy): unified CellLockRegistry + atomic OperationCoordinator cutover

Phase 2 of 4-phase deploy migration per 07_deploy_decision.md.
Architecture-layer refactor (no tech-stack change) replacing 4 independent
concurrency primitives (_IN_USE_MODES + BatchRunManager._busy_keys +
OperationCoordinator + _sidecar_lock_for) with one CellLockRegistry +
ConcurrencyLimiter.

Atomic cutover: all 13 OperationCoordinator.acquire call sites migrated;
class deleted in this commit. grep OperationCoordinator -> 0 matches.

New modules:
- src/web_console/backend/cell_lock_registry.py: CellOperation enum
  (SAMPLING / GENERATING / DELETING) + CellLockRegistry with mutual-
  exclusion invariants per 04_v2 §4.1
- src/web_console/backend/rate_limiter.py: ConcurrencyLimiter(n_slots=5,
  foreground_reserve=2) Semaphore-based replacing v1 token bucket
  (which had wrong mechanism per W3 critic CI-2)

Migrations:
- BatchRunManager: _busy_keys -> registry SAMPLING
- _IN_USE_MODES + _acquire_in_use + _release_in_use -> registry calls,
  all deleted
- RunManager.start_run: ops.acquire("start_run") -> registry GENERATING
- BatchGenerateManager per-item: _acquire_in_use -> registry GENERATING
  (unification refactor, not bug-fix per CI-1)
- 7 ops.acquire sites -> removed (replaced by per-cell registry calls)
- 6 ops.acquire sites -> migrated to registry.try_acquire_global

New behavior:
- DELETING lock added to delete_rawdata + DELETE /api/rawdata/* (H2 fix)
- Concurrent same-(config_id, upstream_md5) fetch -> attach response (R9)
- Concurrent different-config_id fetch on same (machine, mode) -> serialize
  (INV-1 documented limitation per R10)
- ConcurrencyLimiter caps 5 concurrent analyzer subprocesses (5 × 8 = 40
  upstream connections max)
- GET /api/system-state includes registry.snapshot()
- Disk monitor daemon thread spawned in create_app (sequenced after
  _auto_cleanup_for_space migration to registry-aware)

## Verified happy path
- N tests green (P2-T1 [11], P2-T2 [7], P2-T3 [7], P2-T4 [3], P2-T5
  documented in docstrings) + existing P1-fix/P1 suites + full backend
  sweep N passed / N skipped.
- grep OperationCoordinator src/web_console/ -> 0 matches.
- grep _IN_USE_MODES + _busy_keys + _acquire_in_use src/web_console/
  backend/app.py -> 0 matches.
- Module imports OK: cell_lock_registry, rate_limiter.
- Smoke create_app() -> 73 routes unchanged.

## Verified failure paths
- Inject-bug for each new lock (4+ exercises): documented in test
  docstrings per memory/feedback_enumerate_safety_paths.md.
- HTTP 409 on delete attempt against busy cell (test_delete_rawdata_
  returns_409_when_cell_busy).
- Attach vs reject for same-cell concurrent SAMPLING (R9 tests).

## Not verified
- ...

## Tests added
- ...
```

---

## §9 Out-of-loop after this commit

After P2 commits cleanly:

- P3 starts: config upload + fleet refresh queue + report stale-tagging + sidecar by_config_id migration
- The impl-* 4-agent loop runs again for P3
- session_artifacts/_impl/p3/ artifacts created

---

## §10 Pre-flight check

Before spawning impl-implementer, coordinator should:
- [x] Confirm baseline commit (`c4d4e4a` after P1-fix)
- [x] Confirm working tree clean (no leftover artifacts)
- [x] Confirm `cell_lock_registry.py` + `rate_limiter.py` paths don't already exist (they shouldn't; new modules)
- [x] Confirm test files `test_cell_lock_registry.py` / `test_rate_limiter.py` / `test_p2_cutover.py` don't exist
