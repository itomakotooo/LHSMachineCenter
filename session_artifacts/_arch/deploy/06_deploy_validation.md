# 06 Deploy Validation

> Wave 3 — Deploy Review (2026-05-15)
> Agent: arch-validator
> Inputs: 00_deploy_brief.md, 01_deploy_pipeline_map.md, 02_deploy_surface_taxonomy.md, 03_deploy_concurrency_blast_radius.md, 04_deploy_architecture_proposal.md
> Method: concrete case walks against actual codebase + proposal pseudocode; cited by file:line and proposal §

---

## §1 Methodology

**Case selection rationale.** Twelve cases from the task brief are walked, plus one additional case discovered during the walk (Case 13: `DELETE /api/machines/{machine}/all-data` vs stale-tag invariant). Together they cover:

- Concurrent same-cell fetch (same and different configs): Cases 1, 9, 10
- Concurrent read vs delete: Case 2
- Fleet refresh priority + token bucket: Cases 3, 12
- Crash recovery: Cases 4, 11
- Config upload dedup: Case 5
- Multi-planner concurrency: Case 6
- Delete during in-flight: Case 7
- Future extensibility: Case 8
- Backward compat: Cases 9, 10 + §5

**Codebase verification.** For each case, the concrete current code behavior is confirmed by reading `app.py`, `chunk_index.py`, `rawdata_index.py` directly (via grep and Read). All claims about current code behavior are confirmed against the actual file.

**Key confirmed facts from code:**

- `machines.json` uses `Path(mc).write_text(...)` at `app.py:8216` (non-atomic, Critical C1 confirmed)
- `delete_rawdata()` at `app.py:1040` has **no** `_IN_USE_MODES` check (H2 confirmed)
- `BatchGenerateManager._run()` acquires `ops.acquire('batch_generate_report')` but has **no** `_acquire_in_use` call (H1 confirmed)
- `BatchRunManager` **never** acquires the ops mutex (confirmed: sampling + delete can race)
- `_try_acquire_key` is called at `app.py:3675` inside `_run_one` (which is the daemon thread), NOT at `start_batch()` submit time (race window confirmed)
- `rawdata_index.update_entry()` has **no** retry logic (H3 confirmed)
- SQLite `_init_db()` has **no** WAL pragma (confirmed)
- No `FleetRefreshManager`, `CellLockRegistry`, `TokenBucket`, `ConfigFileWriter`, or config upload endpoint exists in the codebase yet (all are proposal additions)

---

## §2 Case Walks

---

### Case 1: Two planners fetch M14|1 simultaneously, same config_id + same upstream_md5

**Setup:** Planner A and Planner B both submit `POST /api/batch-run` for `(config_X, M14, mode 1)` with the same upstream_md5. Both requests arrive within milliseconds of each other.

**Step-by-step walk:**

1. Planner A: `POST /api/batch-run` → `start_batch()` creates `batch_id_A`, spawns daemon thread A (`app.py:3242`; proposal §4.1).
2. Planner B: `POST /api/batch-run` → `start_batch()` creates `batch_id_B`, spawns daemon thread B. **Both HTTP responses return immediately before either thread has run `_run_one`.**
3. Thread A runs `_run_batch` → `_run_one` for M14|1. Under proposal: `registry.try_acquire_cell(M14, 1, SAMPLING)` → `True` (registry empty). `rate_limiter.wait_for_token('foreground', timeout=30)` → `True` (burst capacity=10 > 1). `RunManager.start_run()` launches analyzer subprocess A (proposal §4.1, §4.5).
4. Thread B runs `_run_batch` → `_run_one` for M14|1. Under proposal: `registry.try_acquire_cell(M14, 1, SAMPLING)` → **False** (A holds SAMPLING). Item B marked `status='failed'` with message `'another batch is sampling this machine+mode'` (INV-1, §4.1).
5. Planner B's frontend polls `GET /api/batch-run/{batch_id_B}` → sees item failed.

**Expected result per task brief:** Single upstream call; second planner attaches to first.

**Actual result under proposal:** Second planner gets **rejection** (item status = failed), not attach. Only one upstream call proceeds (INV-6 satisfied). No upstream dedup mechanism provides attach behavior.

**Edge cases:**

- The timing race window between steps 2 and 3 is real: both threads are spawned before either checks `_try_acquire_key`. Under the current `_busy_keys` mechanism (pre-proposal), this race is already serialized by `self._lock` inside `_try_acquire_key`. Under the proposed `CellLockRegistry`, the same serialization applies via `threading.Lock`. The first thread to reach `registry.try_acquire_cell` wins. No double upstream call possible.
- The 4-tuple dedup (same config_id, same upstream_md5) does NOT trigger cache-reuse before attempting the fetch. The dedup check is at rawdata bucket level (already-cached chunks → skip upstream). If both planners submit before any chunks exist, both threads race to acquire the cell, and only one proceeds.

**Verdict:** Pass-with-concern

The concurrency safety requirement (INV-6: at most one active fetch) is met. However, the task brief explicitly expected "second planner attaches." The proposal provides rejection-not-attachment. This is a design scope gap, not a correctness defect: INV-6 is satisfied, raw data will not be corrupted. But planners see a misleading `failed` status when the correct UX would be "this machine is being fetched; your request will reuse the cache when it completes." Designer needs to address whether this UX gap is acceptable.

**Refs:** Proposal §4.1 INV-1, INV-6; `app.py:3675` (`_try_acquire_key` call site); 03 §2 Scenario 1a.

---

### Case 2: Planner A views report; Planner B triggers cache delete same instant

**Setup:** Planner A has `GET /api/reports/M14/1/<rv_version>/` open in browser (polling or active view). Planner B clicks "Delete rawdata" for M14 mode 1.

**Step-by-step walk:**

**Sub-case A: A viewing static report (pure read).**

1. Planner A's browser has already received `player_impact_summary.json` from a prior `GET /api/reports/M14/1/<version>` call. The JSON is in A's browser memory.
2. Planner B: `DELETE /api/rawdata/M14/mode/1`. Under proposal: `registry.try_acquire_cell(M14, 1, DELETING)`. No active SAMPLING or GENERATING → True. `delete_rawdata()` proceeds, unlinks chunks, updates rawdata index (proposal §4.1 INV-2, §4.6).
3. `_tag_reports_stale(M14, 1, reports_root, store)` runs (proposal §4.6): `atomic_json_read_modify_write(index_path, _mark_stale)` sets `underlying_removed=true` on all index entries. `store.mark_runs_underlying_removed(M14, 1)` updates SQLite.
4. Planner A's UI next polls `GET /api/reports/M14/1` (slow timer, 4500ms). Response now includes `underlying_removed: true` on the report entry. Frontend renders "历史快照 — 原始数据已删除" indicator.
5. Planner A's already-loaded report page remains visible unchanged until next refresh.

**Sub-case B: A is generating a report (GENERATING active).**

1. Planner A: `POST /api/rawdata/M14/generate-report` → `registry.try_acquire_cell(M14, 1, GENERATING)` → True.
2. Planner B: `DELETE /api/rawdata/M14/mode/1` → `registry.try_acquire_cell(M14, 1, DELETING)` → **False** (GENERATING active, INV-3). Returns HTTP 409.
3. Planner A's generate completes → `registry.release_cell(M14, 1, GENERATING)`.
4. Planner B retries delete → DELETING acquires → `_tag_reports_stale` runs → reports tagged.

**Edge cases:**

- `_tag_reports_stale` uses `except Exception: pass` (proposal §4.6 line "best-effort"). If `atomic_json_read_modify_write` fails (disk full, NTFS lock), the delete succeeds but stale flag is not set. Reports appear valid after rawdata deleted. This is a silent failure path the proposal acknowledges but leaves as best-effort. Per `memory/feedback_no_silent_swallow.md`, this should persist a diagnostic, not silently pass.
- `DELETE /api/rawdata/{machine}/mode/{mode}/version` (version-specific delete at `app.py:6043`) checks `_get_in_use_snapshot()` at `app.py:6082`. Under the proposal, this must be migrated to `registry.get_active_cells()` too. The proposal §4.1 caller table lists this endpoint but the proposal pseudocode for `_tag_reports_stale` (§4.6) only mentions "both force and non-force paths of `delete_rawdata()`" and the two DELETE endpoints. Version-specific delete path may be missed.

**Verdict:** Pass-with-concern

Core flow works correctly. Two concerns: (1) best-effort stale-tag silently fails on I/O error — should write diagnostic per `feedback_no_silent_swallow.md`; (2) version-specific delete path (`DELETE /api/rawdata/{machine}/mode/{mode}/version`) needs explicit `_tag_reports_stale` call verified — the proposal §4.6 enumeration may undercount delete paths (same risk as `feedback_enumerate_safety_paths.md` M1|1 incident).

**Refs:** Proposal §4.1 INV-2, INV-3; §4.6; `app.py:6043-6132` (version delete path); `memory/feedback_enumerate_safety_paths.md`.

---

### Case 3: Fleet refresh running, planner triggers ad-hoc fetch on different machine

**Setup:** Fleet refresh daemon is running, currently sampling M50|1. Planner A submits `POST /api/batch-run` for M99|1 (a different machine).

**Step-by-step walk:**

1. Fleet refresh `run_queue()` daemon: currently running M50|1. `rate_limiter.wait_for_token('background')` was called for M50, consuming a token. M50|1 analyzer subprocess is running.
2. Planner A: `POST /api/batch-run` for M99|1 → `start_batch()` → thread spawned.
3. Thread A `_run_one` M99|1: `registry.try_acquire_cell(M99, 1, SAMPLING)` → True (M50|1 holds SAMPLING, but M99|1 is a different key). `rate_limiter.wait_for_token('foreground', timeout=30)` (proposal §4.5).
4. Token bucket state: M50 item consumed a token at launch. Refill at 3/s. With `foreground_reserve=2`, foreground callers can consume tokens down to 0 (threshold = 1). Background callers need tokens > 3. If bucket currently has ≥1 token, foreground proceeds immediately. If near-empty, foreground waits at most `1/refill_rate = 0.33s` before one token refills.
5. Planner A's M99|1 analyzer subprocess starts. Both M50|1 (fleet refresh) and M99|1 (ad-hoc) run concurrently. No cell lock conflict (different machines).
6. Fleet refresh `run_queue()` advances to M51|1: `rate_limiter.wait_for_token('background')`. Bucket may be low (ad-hoc consumed a token). Fleet refresh waits until tokens > `foreground_reserve + 1 = 3`. This effectively yields to any pending foreground requests.

**Expected result:** Ad-hoc preempts; fleet refresh yields or waits.

**Actual result:** Ad-hoc M99|1 starts within at most `1/3 s` of token acquisition. Fleet refresh M51 waits for token count to exceed 3. Foreground priority achieved via reserve mechanism.

**Edge cases:**

- If 2 foreground callers simultaneously hit `wait_for_token`, `foreground_reserve=2` ensures both can get tokens before background. With 5 planners simultaneously submitting ad-hoc fetches: tokens 1-2 → foreground callers 1-2 proceed immediately; callers 3-5 wait 0.33s each for refill. Background (fleet refresh) waits until all foreground reserve is used up.
- Fleet refresh and ad-hoc on SAME machine: ad-hoc `registry.try_acquire_cell(M50, 1, SAMPLING)` → False (fleet refresh holds SAMPLING). Ad-hoc item rejected with 409. Token is NOT consumed (token consumed only on successful `start_run`). Foreground wait_for_token call still fires, but the subsequent cell lock rejection means the token is wasted. **Token wasted on rejected item** — this is a minor efficiency issue but not a correctness defect.

**Verdict:** Pass

Priority mechanism works as designed. Token wasted on cell-lock rejection is a minor inefficiency.

**Refs:** Proposal §4.4 (run_queue pseudocode), §4.5 (token bucket), INV-10; 03 §2 Scenario 4.

---

### Case 4: Backend dies at T during fleet refresh (cell 200/393 in-flight)

**Setup:** Fleet refresh is at cell 200/393. `fleet_refresh_items` table has: cells 1-199 `completed`, cell 200 `running`, cells 201-393 `pending`. Analyzer subprocess for M200|1 is running (its `run_id` stored in `fleet_refresh_items.run_id`, its PID stored in `runs.process_pid`). Backend process dies.

**Step-by-step walk:**

1. **Process death.** All in-memory state (`CellLockRegistry`, `BatchRunManager._batches`, `OperationCoordinator`) lost. SQLite database survives intact on disk.
2. **PowerShell restart loop** detects non-zero exit code → sleeps 5 seconds → relaunches uvicorn (proposal §4.7 Alt S1). For intentional upgrade: CTRL+C gives exit code 0 → loop breaks → admin restarts manually.
3. **`StateStore.__init__`** (constructed at `create_app()` position 1748 in function body) calls `_recover_fleet_refresh()` (proposal §4.4 resume algorithm):
   - `SELECT queue_id FROM fleet_refresh_queue WHERE status='running'` → returns Q1.
   - `UPDATE fleet_refresh_items SET status='pending', run_id=NULL WHERE queue_id=Q1 AND status='running'` → M200|1 reset to `pending`. Cells 1-199 `completed` unchanged.
4. **`RunManager.__init__`** (constructed at position 2669, AFTER StateStore) calls `_recover_orphan_running_runs()`:
   - `SELECT run_id, process_pid FROM runs WHERE status='running'` → finds M200's run_id and PID.
   - `_terminate_pid_if_running(pid)` → kills orphaned M200 analyzer subprocess via `taskkill /PID /T /F`.
   - Run row for M200 marked `failed`.
5. **`fleet_mgr.schedule_resume(Q1)`** starts `run_queue(Q1)` daemon thread.
6. `_next_pending_item(Q1)` → returns some pending item (M200 or M201, depending on SQLite scan order — no explicit ORDER BY in pseudocode).
7. Cell 200 is eventually processed (along with 201-393). Cells 1-199 remain `completed`.
8. Fleet refresh completes with all 393 cells processed.

**Expected result:** Cell 200 resumes; 201-393 queued; 1-199 done.

**Actual result under proposal:** Correct — but with a caveat.

**Race windows:**

- **PID kill timing:** Steps 3 and 4 happen at startup, before the fleet refresh daemon thread starts (step 5). `StateStore` constructs before `RunManager`, which constructs before `FleetRefreshManager` starts its daemon. So the orphaned PID is killed BEFORE the new analysis for M200 starts. Race window is effectively closed for the normal case.
- **PID kill failure:** If `taskkill` fails (Windows permission issue, zombie process), the orphaned M200 subprocess continues writing chunks. When the new parent starts a second M200|1 analysis, two subprocesses write to `rawdata/M200/mode_1/`. Each has its own process-local `_SIDECAR_LOCKS` dict. Cross-process sidecar writes race on `_chunks.json`. This is the pre-existing cross-process hazard (03 §2 Scenario 1b), made relevant by restart. The `os.replace` atomicity prevents torn reads but does not prevent lost sidecar updates.
- **Missing ORDER BY in `_next_pending_item`:** Pseudocode (proposal §4.4) shows `SELECT ... WHERE status='pending' LIMIT 1` without `ORDER BY`. SQLite returns rows in undefined order when no ORDER BY is given. Items will all be processed eventually, but M200 might not be the first item resumed. Correctness is preserved (all items eventually processed), but the spec is underspecified.

**Verdict:** Pass-with-concern

The main flow is correct: startup recovery cleanly re-queues item 200 and kills the orphan PID. Two concerns: (1) cross-process sidecar race on PID kill failure (existing hazard, not proposal-introduced); (2) `_next_pending_item` needs `ORDER BY machine, mode` to make behavior deterministic and testable.

**Refs:** Proposal §4.4 (resume algorithm pseudocode), §4.7 (S1 restart loop); `app.py:4686-4725` (`_recover_orphan_running_runs`); `app.py:5286-5415` (`create_app` construction order).

---

### Case 5: Planner uploads config A; another planner uploads same content as "config B"

**Setup:** Planner A uploads config content X with display name "config A". Planner B uploads the identical byte-for-byte content X with display name "config B". Both uploads may arrive simultaneously.

**Step-by-step walk:**

1. Planner A: `POST /api/configs/upload` with body = content X, display_name = "config A".
2. `config_id = sha1(content_X.encode()).hexdigest()` → `config_id_X` (40 hex chars, proposal §4.3).
3. `atomic_json_read_modify_write(CONFIGS_REGISTRY_PATH, _upsert_registry)` acquires `_lock_for(CONFIGS_REGISTRY_PATH)`. Inside `_modifier`: registry has no `config_id_X` entry → writes content file `uploaded_configs/config_id_X.json` via `atomic_json_write` → adds registry entry with display_name="config A" → returns updated registry. Lock released. Response: `{"config_id": config_id_X, "status": "ok"}`.
4. Planner B: `POST /api/configs/upload` with same body = content X, display_name = "config B".
5. `config_id = sha1(content_X.encode()).hexdigest()` → same `config_id_X`.
6. `atomic_json_read_modify_write` acquires `_lock_for(CONFIGS_REGISTRY_PATH)`. Inside `_modifier`: registry NOW has `config_id_X` entry (written in step 3). `if config_id in registry.get("configs", {}): return registry` (no-op). Lock released. Response: `{"config_id": config_id_X, "status": "ok"}`.
7. Result: one content file, one registry entry (display_name = "config A" from first write). "config B" display_name is silently dropped.

**Concurrent upload edge case:**

Both A and B arrive simultaneously (steps 1 and 4 overlap). `_lock_for(CONFIGS_REGISTRY_PATH)` serializes them. One acquires first, writes; the other acquires second, finds entry exists, returns. No double write, no duplicate file. INV-5 satisfied.

**Upload-in-flight when second upload starts:**

If A's content file write (`atomic_json_write` inside `_modifier`) is in progress when B arrives: B waits on `_lock_for(CONFIGS_REGISTRY_PATH)`. A completes both the content write AND the registry write atomically (both happen under the same lock). B then acquires, finds entry exists, returns. Correct.

**Edge case discovered — display_name dedup silently drops second name:**

Per brief §5.5: "Display name can duplicate; internal id = hash(content)." The proposal correctly makes `config_id = hash(content)` so duplicates map to same id. But the registry stores only ONE display_name (from first upload). "config B" is not stored anywhere. If a planner wants to see their upload reflected by display name, they won't find "config B" in the registry. The proposal does not specify whether multiple display names should be recorded per config_id. This is an UX gap, not a correctness defect.

**Verdict:** Pass

INV-5 satisfied: concurrent uploads of same content produce exactly one registry entry and one content file. Display name dedup behavior (first-write-wins) is an accepted design choice per brief §5.5.

**Refs:** Proposal §4.3 (upload algorithm pseudocode, `_upsert_registry`), §4.2 (`atomic_json_read_modify_write`); INV-5; `00_deploy_brief.md §5.5`.

---

### Case 6: 5 planners spawn 5 different batch analyses concurrently

**Setup:** 5 planners simultaneously submit `POST /api/batch-run` for 5 different machines (M1|1, M2|1, M3|1, M4|1, M5|1). Sub-case: 3 of the 5 target M14|1.

**Step-by-step walk (5 different machines):**

1. All 5 `POST /api/batch-run` calls return immediately. 5 daemon threads spawned.
2. Each thread calls `registry.try_acquire_cell(Mx, 1, SAMPLING)`. All 5 cells are different → all 5 acquire SAMPLING. No cell conflict (proposal §4.1 Invariant 2 only applies to same-cell concurrent SAMPLING).
3. All 5 threads call `rate_limiter.wait_for_token('foreground', timeout=30)`. Burst capacity=10 > 5 → all 5 acquire tokens immediately. 5 analyzer subprocesses launch concurrently.
4. Upstream: 5 analyzers × 8 batch_concurrency = 40 concurrent HTTP connections. Within the ~1k/s limit sustained threshold (03 §2 Scenario 9 analysis).

**Sub-case: 3 of 5 target M14|1.**

1. 3 threads for M14|1 race on `registry.try_acquire_cell(M14, 1, SAMPLING)`. Under `threading.Lock`, first thread wins → `True`. Threads 2 and 3 → `False`. Items 2 and 3 marked `status='failed'` (proposal §4.1 INV-1). Threads 4 and 5 (for different cells) proceed normally.
2. Net: 3 total analyzers run (M14|1 × 1, Mx|1 × 2). Cells 2 and 3 see failed status.

**What if 3 of 5 use ProcessPoolExecutor (batch-generate-report, not sampling)?**

- `BatchGenerateManager` acquires `registry.try_acquire_cell(machine, mode, GENERATING)` per item (Phase 2 deliverable #6, proposal §4.1).
- Two concurrent `GENERATING` registrations for the same cell are prohibited (INV-5 equivalent). Second planner's batch-generate for M14|1 would get 409 for that item.
- Different cells proceed in parallel (multiple `GENERATING` for different cells allowed). Per-cell granularity resolves the `OperationCoordinator` global bottleneck (Cluster B).

**Verdict:** Pass

Both sampling and generate cases handled correctly by `CellLockRegistry`. Cell-scoped granularity replaces global `OperationCoordinator` bottleneck for per-cell operations. Concurrent analyses on 5 different cells proceed in parallel.

**Refs:** Proposal §4.1 (INV-1, INV-5 equivalent), §4.5; 02 §3.3 item 1 (OperationCoordinator bottleneck).

---

### Case 7: Planner triggers delete on rawdata while fetch is in-flight for same config + cell

**Setup:** Planner A is sampling M14|1 (active SAMPLING registration in `CellLockRegistry`). Planner B triggers `DELETE /api/rawdata/M14/mode/1`.

**Step-by-step walk:**

1. Planner A: sampling running, `registry` has `{(M14, 1): {SAMPLING}}`.
2. Planner B: `DELETE /api/rawdata/M14/mode/1` → `delete_rawdata_endpoint()` → `registry.try_acquire_cell(M14, 1, DELETING)` → **False** (SAMPLING active, INV-2). Returns HTTP 409 `{"error": "cell_busy", "cell": "M14|1", "op": "sampling"}`.
3. Planner A's sampling completes → `registry.release_cell(M14, 1, SAMPLING)`.
4. Planner B can now retry delete → `registry.try_acquire_cell(M14, 1, DELETING)` → True → delete proceeds.

**Expected result per proposal:** Delete returns 409 (not waits, not aborts the fetch).

**Actual result:** 409 returned immediately. This is the correct behavior per INV-2.

**Edge cases:**

- **How long must Planner B wait?** The proposal has no "retry after" header or estimated completion time in the 409 response. A sampling run can take many minutes for 393 machines. Planner B's only option is to manually retry. The proposal §4.1 says "Frontend shows this as a transient 'system busy' notice, not a permanent error." But without a `Retry-After` hint, the frontend cannot give an accurate wait estimate. This is an UX concern.
- **What if Planner B triggers `DELETE /api/machines/{machine}/all-data`?** Same path: `ops.acquire("delete_machine_all_data")` (current) → under proposal: `registry.try_acquire_cell(M14, mode, DELETING)` for each mode. If any mode has SAMPLING → 409. Correct.
- **What if the fetch is a fleet refresh item?** Fleet refresh registers SAMPLING via `CellLockRegistry`. Ad-hoc delete gets 409 until fleet refresh item completes. Correct — fleet refresh items are protected from deletion.

**Verdict:** Pass

Proposal correctly uses `CellLockRegistry` mutual exclusion to reject delete during active fetch. Behavior is: **reject** (not wait, not abort). This is explicitly stated in proposal §4.1.

**Refs:** Proposal §4.1 INV-2, CellLockRegistry invariants; `app.py:1040` (`delete_rawdata` current code confirms no IN_USE check).

---

### Case 8: Hypothetical future — per-machine rate-limit override (M999 at 0.5x normal rate)

**Setup:** Future requirement: M999 has a known slower upstream response and should only consume half the normal token rate (or the server operator wants to throttle it specifically).

**Analysis of proposal extensibility:**

The `TokenBucket.wait_for_token()` signature in §4.5 pseudocode is:
```python
def wait_for_token(self, priority: str = "background", timeout: float | None = None) -> bool:
```

No `machine` parameter. No `cost` parameter. No per-machine override lookup.

To support per-machine rate override, the implementation would need:
- A `cost` parameter: `wait_for_token(priority, cost=1.0)` where M999 passes `cost=2.0` (consumes 2 tokens).
- A per-machine override table: `{"M999": 2.0, "default": 1.0}` (could live in `machines.json` or `servers.json`).
- `BatchRunManager._run_one` would look up the machine's cost before calling `wait_for_token(cost=machine_cost)`.

The token bucket math already supports fractional tokens (line `self._tokens -= 1.0` in pseudocode can become `self._tokens -= cost`). The extension requires:
1. Add `cost: float = 1.0` parameter to `wait_for_token`.
2. Adjust the threshold comparison: `if self._tokens >= cost * threshold_multiplier`.
3. A lookup source for per-machine cost (no breaking schema changes needed; `machines.json` already has per-machine entries).

**How cleanly?** The token bucket module (`rate_limiter.py`) is a new file (Phase 3). Adding `cost` parameter is a trivial extension. No other code needs changing except the `_run_one` call site. This is an approx 5-line change.

**What would need to change?** Only `rate_limiter.py` (the new module) and `BatchRunManager._run_one` lookup of per-machine cost. No impact on `FleetRefreshManager` (fleet refresh always uses background priority with cost=1.0 by design).

**Verdict:** Pass

The token bucket design is cleanly extensible to per-machine cost via a `cost` parameter. The extension is not in scope but the architecture does not block it.

**Refs:** Proposal §4.5 (TokenBucket pseudocode); `memory/feedback_no_hardcode.md` (don't hardcode machine semantics).

---

### Case 9: Concurrent same-config different-machine fetch

**Setup:** Planner A fetches `(config_X, M14, mode 1)`. Planner B fetches `(config_X, M99, mode 1)`. Same config, different machine.

**Step-by-step walk:**

1. A: `registry.try_acquire_cell(M14, 1, SAMPLING)` → True. B: `registry.try_acquire_cell(M99, 1, SAMPLING)` → True. `CellLockRegistry` key is `(machine, mode)` — M14|1 ≠ M99|1. No conflict (proposal §4.1).
2. Both get tokens from `rate_limiter` (2 of 10 burst capacity consumed).
3. A writes chunks to `rawdata/M14/mode_1/`. B writes to `rawdata/M99/mode_1/`. Different directories. No path collision. No sidecar conflict.
4. 4-tuple dedup: `(config_X, M14, 1, upstream_md5)` vs `(config_X, M99, 1, upstream_md5)`. Different machine → different rawdata bucket. `by_config_id` index in each mode_dir's `_chunks.json` is independent.
5. Both complete. Config X is recorded as `config_id=config_X` in both cells' sidecar `by_config_id` index.

**Verdict:** Pass

Different machines never conflict at cell or sidecar level, even with the same config_id. No issue.

**Refs:** Proposal §4.1 (CellLockRegistry key is `(machine, mode)`); §4.3 (4-tuple dedup); `chunk_index.py:91` (per-mode-dir sidecar lock).

---

### Case 10: Same-machine different-config fetch

**Setup:** Planner A fetches `(config_X, M14, mode 1)`. Planner B fetches `(config_Y, M14, mode 1)`. Same machine+mode, different config.

**Step-by-step walk:**

1. A: `registry.try_acquire_cell(M14, 1, SAMPLING)` → True. A's analyzer subprocess starts, writing to `rawdata/M14/mode_1/`.
2. B: `registry.try_acquire_cell(M14, 1, SAMPLING)` → **False** (A holds SAMPLING, INV-1). B's item marked `status='failed'`.
3. Result: only one fetch runs (config_X). config_Y fetch is rejected.

**Gap identified:**

The 4-tuple dedup key is `(config_id, machine, mode, upstream_md5)`. Two different config_ids for the same machine+mode are **independent rawdata buckets** — they write to the same directory but are separated by the `by_config_id` sidecar index. There is no fundamental reason they cannot run concurrently from a **data-correctness** standpoint, IF the cross-process sidecar write race is handled.

However, two concurrent analyzer subprocesses writing to the same `rawdata/M14/mode_1/` directory DO race on `_chunks.json` at the process level:
- Subprocess A updates sidecar (acquires its own process-local `_sidecar_lock_for(mode_dir)`, which is **independent** of subprocess B's lock dict).
- Subprocess B updates sidecar concurrently.
- Each does `os.replace(tmp, _chunks.json)` atomically. But if both read the same `_chunks.json` before either writes, one write overwrites the other — losing entries (the same H3 problem as `rawdata_index`, but for sidecar).

The `CellLockRegistry` prevents this cross-process sidecar race by only allowing ONE SAMPLING per cell. This is correct behavior from a safety standpoint, but it is more restrictive than necessary for different config_ids.

**Root cause of restriction:** The CellLockRegistry key is `(machine, mode)`, not `(config_id, machine, mode)`. The reason for this coarseness is that the sidecar (single file per mode_dir) is shared regardless of config_id. Allowing concurrent sampling for different config_ids would require a per-`(config_id, machine, mode)` lock AND per-`(machine, mode)` sidecar coordination — adding significant complexity.

**Verdict:** Pass-with-concern

The behavior (only one concurrent SAMPLING per cell, regardless of config_id) is safe and correct. However, it is more restrictive than the 4-tuple dedup conceptually suggests. Two planners with different configs for the same machine must serialize. This is a performance concern for power users who want concurrent multi-config sampling on the same machine. The designer should document this limitation explicitly. The root cause is that the sidecar file is per-(machine, mode), not per-(config_id, machine, mode).

**Refs:** Proposal §4.1 INV-1; §4.3 (4-tuple dedup); `chunk_index.py:91` (per-mode sidecar lock); 03 §2 Scenario 1b.

---

### Case 11: Rolling upgrade with in-flight job

**Setup:** Fleet refresh is at cell 150/393. Admin stops uvicorn (for upgrade). New version of uvicorn is started. Expected: cell 150 is retried; 151-393 proceed; 1-149 remain done.

**Step-by-step walk:**

1. Admin stops uvicorn via Task Scheduler stop command (or CTRL+C). Exit code = 0.
2. PowerShell restart loop: `if ($LASTEXITCODE -eq 0) { break }` → loop exits. Uvicorn is stopped. (Proposal §4.7 Alt S1 pseudocode.)
3. Admin deploys new code, runs `install.bat`.
4. Admin starts new uvicorn via Task Scheduler start.
5. New process: `StateStore.__init__` → `_recover_fleet_refresh()`:
   - `SELECT queue_id ... WHERE status='running'` → Q1.
   - `UPDATE fleet_refresh_items SET status='pending' WHERE queue_id=Q1 AND status='running'` → item 150 → pending. Items 1-149 remain `completed`.
6. `RunManager.__init__` → `_recover_orphan_running_runs()`:
   - Finds run_id for item 150 in SQLite `runs` table (status='running', process_pid=<PID150>).
   - `_terminate_pid_if_running(PID150)` → `taskkill /PID PID150 /T /F`.
   - Item 150's run row → `status='failed'`.
7. `fleet_mgr.schedule_resume(Q1)` starts `run_queue(Q1)` daemon.
8. `_next_pending_item(Q1)` → returns M150|1 (or M151 depending on scan order — no ORDER BY specified).
9. M150|1 is sampled fresh (with `--resume-from-cache` it reuses any already-completed chunks on disk from the prior run). Items 151-393 follow.

**Race window analysis:**

- Steps 5 (StateStore init) and 6 (RunManager init) happen sequentially at startup, before FleetRefreshManager's daemon thread starts. The orphan PID is killed at step 6 before any new analysis starts at step 7-9. Race window is closed provided `taskkill` succeeds.
- If `taskkill` fails (PID already dead, or permission denied): `_terminate_pid_if_running` returns False, logs warning. No new subprocess is started yet — the daemon thread hasn't started. When `run_queue` later starts M150|1, the orphaned subprocess (if still running) and the new subprocess will write to the same mode_dir. Cross-process sidecar race. This is a pre-existing hazard, not introduced by the proposal. Probability: low (taskkill almost always succeeds on Windows for a child process).

**PowerShell restart loop for crash recovery (not intentional upgrade):**

If uvicorn crashes (exit code ≠ 0), the loop waits 5 seconds and relaunches the SAME version. Same recovery sequence applies. The 5-second sleep before relaunch means the orphan analyzer subprocess has 5 seconds to complete its current chunk write before the new parent tries to re-analyze the same cell. Reduces (but does not eliminate) the race window.

**Verdict:** Pass-with-concern

Main flow is correct for intentional upgrade and for crash recovery. Concern: `_next_pending_item` lacks `ORDER BY`, making resume order undefined. Recommend `ORDER BY machine, mode ASC` for deterministic and testable behavior.

**Refs:** Proposal §4.4 (resume algorithm), §4.7 (Alt S1); `app.py:4686-4725` (`_recover_orphan_running_runs`).

---

### Case 12: Multi-user UI live status during full-refresh (5 planners watching)

**Setup:** 5 planners all have the fleet refresh progress panel open in their browsers. All 5 poll `GET /api/fleet/refresh` to see progress.

**Step-by-step walk:**

1. Fleet refresh running: `fleet_refresh_queue` table has Q1 with `status='running'`, `completed_items=N`.
2. Each planner's browser polls `GET /api/fleet/refresh`. The proposal defines this endpoint (§3.4) as reading `fleet_refresh_queue` + `fleet_refresh_items` from SQLite. With WAL mode (Phase 1), concurrent reads do not block each other. 5 planners × ~4s polling interval = ~1.25 req/s on SQLite. Trivially handled (03 §2 Scenario 14 confirmed: 5 users, read-only, safe).
3. Fleet refresh completes: `fleet_refresh_queue` row transitions `status: 'running' → 'completed'`.
4. Each planner's browser detects the transition on their next poll.

**Polling overlap risk (per `memory/feedback_fasttimer_overlap_needs_oneshot.md`):**

The original overlap issue was: `setInterval` fires at 1s, multiple concurrent `refreshCurrentRun()` calls each snapshot `prevStatus` AFTER their own `await`, all observing the same `running → completed` transition, each firing a side-effect (rwtree refresh) separately.

For fleet refresh: 5 planners each detect `running → completed` in their own polling tick. Each tab independently fires side-effects (e.g., refresh machine summary panel, show completion notification). Unlike the per-run case, the one-shot flag `state._autoRefreshedForRunId` guards against overlap within a SINGLE tab but not across tabs. 5 tabs = 5 independent one-shot flags → 5 side-effects fire. This is expected multi-user behavior: each planner gets notified once in their own tab.

**The proposal does NOT specify a fleet-refresh-specific polling interval or one-shot guard.** The proposal says "reusing `batchRunProgress` renderer" (Phase 3 deliverable #12), which polls `GET /api/batch-run/{batch_id}` at ~2s. For fleet refresh, the equivalent would be `GET /api/fleet/refresh`. No explicit timer specified.

**Potential issue:** If fleet refresh is polled at 1s (via `fastTimer`) instead of 2-4s, and 5 planners are watching, that is 5 req/s → 300 SQLite reads/min. Still trivially safe. But the `fastTimer` one-shot guard `state._autoRefreshedForRunId` only applies to per-run polling — it does NOT automatically apply to fleet refresh. If fleet refresh completion triggers a tree-refresh side-effect inside the fast poll handler, 5 planners trigger 5 tree-refreshes simultaneously. This is the overlap pattern from `feedback_fasttimer_overlap_needs_oneshot.md`.

**Verdict:** Pass-with-concern

Server-side fleet refresh polling is safe for 5 users (SQLite WAL, read-only). Client-side: the proposal does not specify the polling timer for fleet refresh, nor does it explicitly apply the one-shot guard to fleet-refresh completion. Implementer must: (a) use a separate `setInterval` for fleet refresh polling (not `fastTimer`); (b) apply a `state._autoRefreshedForFleetRefreshId` one-shot guard on the `running → completed` transition to prevent 5 simultaneous side-effect fires per tab. This is not a proposal defect — it is a detail left to implementer — but the proposal should have explicitly called it out given the `feedback_fasttimer_overlap_needs_oneshot.md` lesson.

**Refs:** Proposal §3.4 (`GET /api/fleet/refresh`), Phase 3 deliverable #12; `memory/feedback_fasttimer_overlap_needs_oneshot.md`; `app.js:7891` (fastTimer); 03 §2 Scenario 14.

---

### Case 13 (Discovered): `DELETE /api/machines/{machine}/all-data` vs stale-tag invariant

**Setup:** Planner triggers `DELETE /api/machines/M14/all-data`, which deletes both rawdata AND reports.

**Step-by-step walk:**

1. Under proposal: `registry.try_acquire_cell(M14, mode, DELETING)` for each mode (proposal §4.1 caller table). All modes acquire DELETING.
2. `delete_rawdata(M14, mode=None, force=True)` → inside this call, `_tag_reports_stale(M14, mode, reports_root, store)` runs (proposal §4.6).
3. `_tag_reports_stale` calls `atomic_json_read_modify_write(index_path, _mark_stale)` → sets `underlying_removed=true` on all index entries.
4. Execution returns to the endpoint. Step 2 in the endpoint: `shutil.rmtree(reports/M14)` at `app.py:6355`. **The entire reports directory is deleted**, including the now-stale-tagged `index.json` files.

**Result:** `_tag_reports_stale` runs in step 2 and writes `underlying_removed=true` to `index.json`. Step 4 then deletes `index.json` entirely. The stale tag survives for ~0ms. From any external observer's perspective, the reports simply vanish.

**INV-7 conflict:** INV-7 states "Deleting rawdata for (machine, mode) always sets `underlying_removed=true` on all index entries for that cell." For `delete_rawdata`-only paths, INV-7 holds. For `DELETE /api/machines/{machine}/all-data`, INV-7 cannot hold because the reports are also deleted.

**The proposal correctly flags this in Open Question 7** (§9 Q7): "Should `_tag_reports_stale` be skipped here, or should it run and then the delete proceeds?" But provides no resolution.

**Brief constraint 6** says: "rawdata is deletable. Reports based on deleted rawdata stay but tag `underlying_removed=true`." This constraint is for rawdata-only deletion. The `all-data` endpoint explicitly deletes both. The brief (§5) does not address this specific case.

**Verdict:** Fail

INV-7 cannot be satisfied by `DELETE /api/machines/{machine}/all-data` because this endpoint also deletes reports. The proposal identifies the ambiguity but does not resolve it. The designer must explicitly document this as an exception to INV-7: when using the `all-data` endpoint, reports are deleted (not stale-tagged). INV-7 should be scoped to rawdata-only delete paths. The `_tag_reports_stale` call in the `all-data` endpoint should be removed to avoid misleading write-then-immediately-delete behavior.

**Refs:** Proposal §4.6, §9 Q7, INV-7; `app.py:6283-6360` (`delete_machine_all_data`); `00_deploy_brief.md §5.6`.

---

## §3 Overall Verdict

**APPROVE-WITH-REVISIONS**

The proposal correctly identifies all critical and high hazards from W1 and provides architecturally sound solutions for most. The `CellLockRegistry` unified model, `ConfigFileWriter` atomic writes, SQLite-backed fleet queue, and PowerShell restart loop are all well-reasoned choices that fit the stack constraint. No case results in a fundamental architectural failure.

**Cases that pass cleanly:** 5 (config upload dedup), 6 (5-planner concurrent analysis), 7 (delete during in-flight), 8 (extensibility), 9 (same-config different-machine).

**Cases that pass with concerns:** 1 (attach vs reject gap), 2 (stale-tag best-effort failure silent, version-delete path may be missed), 3 (token waste on cell-lock rejection — trivial), 4 (ORDER BY missing in resume query), 10 (different-config same-cell serialization constraint undocumented), 11 (ORDER BY missing, same as 4), 12 (fleet refresh polling timer and one-shot guard not specified).

**One case fails:** 13 (`DELETE /api/machines/{machine}/all-data` violates INV-7). This is a localized scoping issue with the stale-tag invariant, not an architectural failure. Resolution: scope INV-7 to rawdata-only delete paths; document `all-data` delete as an explicit carve-out that deletes reports rather than tagging them.

---

## §4 Edge Cases Discovered

**EC-1: Token bucket throttles launch rate, not concurrent item count.**

The proposal §4.5 states `refill_rate=3.0` means "3 new analyzers launching per second; each adds ~8 upstream connections at peak, so 24 connections/s peak." This conflates connection launch rate with concurrent connections. If items take 60 seconds to complete and 3 new items launch per second, steady-state concurrent items = 3/s × 60s = 180 items, each with 8 upstream connections = 1440 concurrent connections — far above the ~1k/s upstream limit. The burst capacity=10 alone already puts 80 concurrent connections in flight immediately.

The token bucket correctly caps the item launch rate but does not cap total concurrent upstream connections (which depends on item duration). The proposal's own Scenario 9 analysis concluded "120 concurrent upstream requests" from 5 planners causes self-DoS. The token bucket as designed with capacity=10 and refill_rate=3 does NOT prevent 80+ concurrent connections from a burst of 10 items. Designer needs to address whether `capacity` should be dramatically reduced (e.g., 3) or whether a separate concurrent-item cap is needed alongside the token bucket.

**EC-2: `OperationCoordinator` deprecation is internally contradictory in Phase 2.**

Proposal §4.1 states: "OperationCoordinator retained as-is for backward compat during Phase 2." Phase 2 deliverable #8 states: "Replace all remaining OperationCoordinator uses with appropriate `try_acquire_global` calls." These cannot both be true simultaneously. If `BatchGenerateManager._run()` still calls `ops.acquire('batch_generate_report')` AND also calls `registry.try_acquire_cell(GENERATING)`, the result is double-locking — the global ops still serializes all batch-generate operations globally, eliminating the per-cell benefit of `CellLockRegistry`. The implementation phase must explicitly choose: remove `ops.acquire` from `BatchGenerateManager` (keeping only the registry call), OR retain the ops call (but then Cluster B bottleneck is not solved). Designer should clarify which ops calls are removed in Phase 2 vs retained for Phase 2 cleanup.

**EC-3: `_next_pending_item` lacks ORDER BY.**

The `run_queue` pseudocode (proposal §4.4) does `SELECT ... WHERE status='pending' LIMIT 1` without ORDER BY. SQLite's undefined scan order means the resume sequence is non-deterministic. This makes testing difficult (T7 `test_resume_after_simulated_crash` cannot assert which item is processed next) and makes the behavior surprising to operators (they may expect sequential machine order). Recommend `ORDER BY machine, mode ASC` or a per-item `queue_position` column.

**EC-4: Version-specific delete path (`DELETE /api/rawdata/{machine}/mode/{mode}/version`) may be missing from stale-tag enumeration.**

Proposal §4.6 says "`_tag_reports_stale` is called from `delete_rawdata` (both force and non-force paths), and from `DELETE /api/rawdata/{machine}` and `DELETE /api/machines/{machine}/all-data`." The version-specific delete endpoint (`app.py:6043`) is a fourth path that deletes individual chunk files. If all chunks for a mode are deleted via repeated version deletes, the mode's rawdata is effectively empty but `_tag_reports_stale` was never called. Per `memory/feedback_enumerate_safety_paths.md`, ALL delete paths must be enumerated. This path is missing from the §4.6 caller list.

**EC-5: `DELETE /api/machines/{machine}/all-data` runs a SQLite query to check for running runs (`app.py:6311-6326`) but the CellLockRegistry check (under proposal) might fire BEFORE the running-runs check.**

Under proposal Phase 2, `delete_machine_all_data` would call `registry.try_acquire_cell(M14, mode, DELETING)` for each mode. If M14|1 has SAMPLING registered, DELETING fails → 409. The existing running-runs check in the current code at `app.py:6311` is therefore redundant with the CellLockRegistry check. However, if the registry only covers modes that have registered cells, a mode with a running SQLite run but no CellLockRegistry entry (e.g., a run from a previous process that survived `_recover_orphan_running_runs`) could slip through. The belt-and-suspenders approach (both checks) is safer. The proposal should explicitly retain the running-runs DB check in `delete_machine_all_data` even after Phase 2.

**EC-6: Case 1 "attach" vs "reject" gap not addressed by INV-6.**

INV-6 states: "two concurrent batch-runs with the same 4-tuple produce at most one active fetch." This invariant is satisfied (CellLockRegistry ensures only one SAMPLING per cell). But the brief implied "second planner attaches" (observes the first run's progress). The proposal provides no attach mechanism — only rejection. This is a user experience gap that should be explicitly documented as a design decision.

---

## §5 Test Cases Derived from Walks

The following test names map cases to the proposal's Group T tests. Each should follow inject-bug → red → revert → green per `memory/feedback_enumerate_safety_paths.md`.

| Case | Derived Test | Group | Inject Bug |
|---|---|---|---|
| 1 (dedup/reject) | `test_concurrent_same_cell_second_gets_409_not_double_run` | T9 (E2E) | Remove CellLock check → second analyzer launches → both subprocesses write same sidecar |
| 2 (stale-tag) | `test_stale_tag_survives_rawdata_delete` | T5 | Remove `_tag_reports_stale` call → index.json unchanged after delete |
| 2 (version delete path) | `test_stale_tag_on_version_delete_path` | T5 | Version delete without stale-tag → reports appear valid after all chunks deleted |
| 3 (priority) | `test_foreground_gets_token_before_background` | T8 | Set `foreground_reserve=0` → foreground and background compete equally |
| 4 (resume ORDER) | `test_resume_processes_items_in_deterministic_order` | T7 | Remove ORDER BY → item order non-deterministic (flaky) |
| 5 (upload dedup) | `test_concurrent_upload_same_content_produces_single_file` | T6 | Remove registry lock → concurrent uploads write duplicate content file |
| 7 (delete blocked) | `test_delete_rawdata_409_when_sampling_active` | T5 | Remove DELETING check → delete proceeds during sampling |
| 10 (same-cell different-config) | `test_different_config_same_cell_serialized_not_parallel` | T9 (E2E) | Document that second config rejected: assert item_B.status == 'failed' |
| 11 (resume after upgrade) | `test_fleet_refresh_resume_after_restart_completes_all_items` | T7 | Remove `_recover_fleet_refresh()` → item 150 stays 'running' → never retried |
| 12 (polling) | `test_fleet_refresh_panel_uses_one_shot_guard_on_completion` | frontend JS test | Remove one-shot guard → 5 simulated tabs each fire side-effect on same transition |
| 13 (all-data vs INV-7) | `test_all_data_delete_removes_reports_not_tags_them` | T5 | Verify reports dir is deleted (not INV-7 violation — this IS the correct behavior) |
| EC-1 (token math) | `test_token_bucket_burst_does_not_exceed_80_concurrent_connections` | T8 | Set capacity=10 → measure concurrent items in flight → assert <= N |

---

## §6 Hash Composition Trace (Deploy Context)

This section is not applicable in the deploy architecture review. The hash composition trace pertains to the fleet onboarding architecture (prior review `session_artifacts/_arch/04_proposal.md`). The deploy architecture uses `config_id = sha1(content)` (40 hex chars) as a stable identity key, not a hash-based invalidation signal. The relevant invariant is that `config_id` is computed deterministically from file content and never changes once assigned — this is correctly specified in §4.3 and confirmed by the upload dedup walk (Case 5).

---

## §7 Backward-Compat Check Summary

| Phase | Schema changes | Existing rawdata | Existing reports | Existing runs (SQLite) | Single-user dev workflow |
|---|---|---|---|---|---|
| Phase 1 (atomic writes + chart.js) | None | Unmodified | Unmodified | Unmodified (WAL enable is transparent) | Unchanged |
| Phase 2 (CellLockRegistry) | None | Unmodified | Unmodified | Unmodified | Behavior change: concurrent conflicts return explicit 409 instead of silent race. Non-breaking. |
| Phase 3 (config upload, fleet refresh, stale-tag) | `ALTER TABLE runs ADD COLUMN underlying_removed INTEGER DEFAULT 0` | `config_id` field added to future chunks; existing chunks treated as `"null"` (lazy migration, backward compat) | `underlying_removed` field added by stale-tag on future deletes; existing index entries missing field treated as `false` | Existing rows get `underlying_removed=0` (default). New tables `fleet_refresh_queue` + `fleet_refresh_items` don't affect existing rows. | Unchanged |
| Phase 4 (deploy wrapper) | None | None | None | None | `SLOT_BIND_HOST=127.0.0.1` env var restores loopback binding for dev |

**Conclusion:** All existing reports can continue to be served without regeneration across all phases. SQLite migrations use `ALTER TABLE ADD COLUMN WITH DEFAULT` — existing rows receive safe defaults. No re-indexing or re-processing of rawdata required.

---

## §8 Cases That Break

**Verdict: one hard break, three design-level gaps requiring designer revision.**

### Case 13 — Stale-tag invariant vs. all-data delete (HARD BREAK)

`DELETE /api/machines/{machine}/all-data` deletes both rawdata and reports. INV-7 ("deleting rawdata always tags reports `underlying_removed=true`") cannot be satisfied when reports are also deleted. The proposal acknowledges this in Open Question 7 but does not resolve it.

**Root cause:** INV-7 was designed for rawdata-only delete paths. The `all-data` endpoint is a separate contract that nukes everything.

**Designer needs:** Explicitly scope INV-7 to rawdata-only delete paths. Remove `_tag_reports_stale` from the `all-data` endpoint. Document the carve-out: `all-data` delete removes reports permanently (no stale tagging) and is explicitly exempt from INV-7. Update the invariant statement to: "Deleting rawdata via `DELETE /api/rawdata/{machine}` or `DELETE /api/rawdata/{machine}/mode/{mode}` always tags surviving reports `underlying_removed=true`. The `all-data` endpoint removes all data including reports and is exempt."

### EC-1 — Token bucket math inconsistency (DESIGN GAP)

The token bucket throttles item launch rate but not concurrent upstream connections. With burst capacity=10, the first 10 items launch simultaneously, creating 80 concurrent upstream connections — the exact self-DoS condition H4 was meant to prevent.

**Designer needs:** Either (a) reduce burst capacity to ~3 (matching the actual safe concurrent analyzer count) and document that `capacity` is the max concurrent items (not just burst), OR (b) add a separate `max_concurrent_items` cap enforced by a semaphore alongside the token bucket. The `refill_rate` alone does not cap peak concurrency.

### EC-2 — OperationCoordinator Phase 2 deprecation contradicts concurrent benefit claim (SPEC AMBIGUITY)

Phase 2 says "OperationCoordinator retained" AND "Replace all remaining OperationCoordinator uses." If `BatchGenerateManager._run()` retains `ops.acquire('batch_generate_report')`, Cluster B global bottleneck is NOT resolved despite Phase 2 deliverable claiming it is.

**Designer needs:** Explicitly list which `OperationCoordinator.acquire` calls are REMOVED in Phase 2 (at minimum: `batch_generate_report`, `generate_report`, `delete_rawdata`, `delete_run`, `delete_report_version`) vs which are retained/migrated to `try_acquire_global` (at minimum: `disk_cleanup`, `prune_versions`, `reports_cleanup`, `import_reports`, `autotune`). This list is the single source of truth for Phase 2 scope.

### EC-4 — Version-specific delete path missing from stale-tag enumeration (INCOMPLETE COVERAGE)

`DELETE /api/rawdata/{machine}/mode/{mode}/version` (`app.py:6043`) is a fourth rawdata delete path not listed in proposal §4.6's `_tag_reports_stale` call-site enumeration. If all chunks are deleted via repeated version deletes, no stale tag is written.

**Designer needs:** Add `_tag_reports_stale` call to the version-specific delete path and add it to §4.6's enumeration. Add a corresponding test in Group T5: `test_delete_tags_all_four_paths`.

---

## §9 Validator Summary

```
arch-validator complete.
- Cases walked: 13 (12 assigned + 1 discovered)
- Verdicts: 5 pass / 7 pass-with-concern / 1 fail
- Cases that break: 1 hard (Case 13: INV-7 scoping vs all-data delete)
                    3 design gaps: EC-1 (token bucket math), EC-2 (ops deprecation spec),
                                   EC-4 (version delete path missing)
- Backward-compat: fully maintained across all 4 phases
- Verdict: APPROVE-WITH-REVISIONS
```
