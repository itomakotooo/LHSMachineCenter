# 05 Deploy Critique

> Wave 3 — Deploy Review (2026-05-15)
> Agent: arch-critic
> Target: `04_deploy_architecture_proposal.md`

---

## §1 Overall Verdict

**APPROVE-WITH-REVISIONS**

The proposal correctly identifies all major concurrency hazards from W1 and addresses them with sound mechanisms. However it contains one factual error in the hazard baseline that corrupts the Phase 2 scope, three design gaps that could silently fail in production (token-bucket process-boundary mismatch, cross-process rawdata_index under ProcessPoolExecutor, fleet refresh infinite stall), and two punted open questions that are critical-path blockers rather than reasonable punts. These must be resolved in the decision document before implementation begins; they do not invalidate the overall architecture direction.

---

## §2 Critical Issues (block approval; v2 must address)

### CI-1: H1 claim is factually wrong — `BatchGenerateManager` already calls `_acquire_in_use`

The proposal states at §3.2 H1: "Batch-generate-report workers run in `ProcessPoolExecutor` subprocesses and read chunk files from `rawdata/<M>/mode_<N>/`. They do NOT call `_acquire_in_use()` before starting (`app.py:2862-3158`, no such call found)."

This is false. The code at `app.py:7208-7222` shows `_prepare_batch_gen_item_wrapper` explicitly calls `_acquire_in_use(machine, mode)` before submitting the worker, and `_finalize_batch_gen_item_wrapper` calls `_release_in_use` in its `finally` block. The `BatchGenerateManager` is instantiated with these wrapper functions as `prepare_fn` and `finalize_fn` (`app.py:3016` calls `self._prepare_fn(item["machine"], item["mode"])`).

Why it matters: Phase 2 deliverable 6 ("Add `registry.try_acquire_cell(..., GENERATING)` to `BatchGenerateManager` per-item before worker submission (fixes H1)") is premised on H1 being an unfixed gap. If H1 is already fixed in the baseline, Phase 2 scope is inflated by at least one deliverable and the H1 gap evidence cited for INV-11 is unreliable. This also calls into question the W1 coupling-auditor's accuracy for other gap claims — if one observable call at `app.py:7212` was missed, what else was missed in the 8928-line file?

The CellLockRegistry migration still makes sense as a unification effort, but the "fixes H1" justification must be removed and the deliverable re-scoped to "replaces existing `_acquire_in_use` pattern in BatchGenerateManager with registry call."

### CI-2: Token bucket governs subprocess-launch rate, not actual upstream concurrency — the math does not hold

The proposal at §4.5 argues: "throttle at the subprocess-launch level (parent controls the rate at which it spawns new batch items), not at the HTTP-request level." Default `refill_rate=3.0` means 3 new analyzers launching per second.

The problem: each analyzer subprocess runs its own `ThreadPoolExecutor(max_workers=batch_concurrency)` (default 8) making concurrent HTTP calls. The token bucket governs how fast NEW items start, not how many concurrent HTTP requests the RUNNING analyzers make. A single analyzer, once launched, generates 8 concurrent HTTP requests for its entire lifetime (potentially hours for a 10k-spin run). After the bucket refills 10 tokens (10 new items launched), there are up to 10 × 8 = 80 concurrent upstream connections, each persisting for the full item duration.

Open question §4.5 (OQ-5) asks W3 to validate the `refill_rate=3.0` value. The designer's answer assumes each analyzer has a brief life span. In practice, a 393-machine full-refresh with `max_chunks` set high results in analyzers that each run for 15-30 minutes. After 4 items (the ProcessPoolExecutor limit), all 4 workers are alive simultaneously and each maintains 8 upstream connections = 32 concurrent upstream HTTP requests. Adding 5 ad-hoc planners on top brings this to 32 + 40 = 72 concurrent connections. This is above the ~1k/s outer limit documented in `memory/feedback_upstream_throttle_ceiling.md` at the observed per-source ceiling.

The token bucket as designed governs peak launch rate but not steady-state concurrency. The proposal does not address this. The open question cannot be answered without changing the design — it is a critical flaw, not a tuning question.

### CI-3: `rawdata/_index.json` mtime retry is insufficient on Windows NTFS under ProcessPoolExecutor

The proposal at §4.2 resolves H3 (concurrent `rawdata/_index.json` writes under ProcessPoolExecutor) with an mtime-based retry: read mtime, read file, re-read mtime, retry if different.

Open question OQ-2 flags this: "On Windows NTFS, mtime granularity is 100ns — two writes within 100ns have the same mtime. Is this granularity sufficient?"

The designer punts this to W3. But the analysis already shows the risk: 4 ProcessPoolExecutor workers completing near-simultaneously (common during batch-generate on a fleet of 393 machines with similar run durations) will have mtime differences potentially below 100ns. When two workers both see `pre_mtime == post_mtime` after their read (because the concurrent write landed in the same 100ns window), both proceed to write, and one's update is lost — exactly the H3 race the retry was meant to prevent.

The proposed retry is not a solution, it is a probabilistic mitigation that fails precisely in the high-concurrency scenario it was designed for. The mtime check cannot reliably detect concurrent writes on Windows. The proposal acknowledges this in OQ-2 but treats it as a W3 question rather than a design gap. It is a design gap.

---

## §3 Major Concerns (should address before implementation)

### M1: Open question OQ-4 (fleet refresh infinite cell-busy stall) is not a reasonable punt

The proposal at §4.4 `run_queue` pseudocode shows: when `cell_registry.try_acquire_cell(machine, mode, SAMPLING)` returns False (ad-hoc fetch active), the fleet refresh sleeps `YIELD_SLEEP_S` and retries. OQ-4 asks: "if ad-hoc planners continuously keep a cell busy for hours, the fleet refresh item for that cell will never proceed."

This is not a corner case. The deployment scenario is exactly "planners running ad-hoc fetches" + "fleet refresh running in background." A planner who keeps M14|1 in a continuous fetch loop (which is a valid use case — repeatedly sampling to accumulate spin counts) will permanently block the fleet refresh item for M14|1. The fleet refresh then has a "permanent pending" item that its per-machine-failure retry does not address (retry is for failed runs, not busy-blocked items). The queue never completes. `GET /api/fleet/refresh` shows perpetual `status=running`.

The proposal says "maximum wait timeout per item needed?" and defers. This is a behavioral question that changes the UX contract: does fleet refresh skip-after-timeout, or does it never skip? If it skips, what is the timeout? These choices must be in the proposal, not punted.

### M2: `_tag_reports_stale` uses `except: pass` — violates `feedback_no_silent_swallow.md`

The proposal at §4.6 shows:
```python
try:
    atomic_json_read_modify_write(index_path, _mark_stale)
except Exception:
    pass  # best-effort; report stale tag is informational
```

Per `memory/feedback_no_silent_swallow.md`, this pattern is explicitly prohibited: "任何 best-effort post-hook 都必须把 outcome 落盘（rc + stderr tail + 解析路径），不能靠 `except: pass`."

The stale-tag write failing silently is dangerous: the rawdata is deleted, the report remains, but the UI shows it as valid (not stale). The planner sees a valid-looking report whose underlying data is gone, attempts to re-generate, and gets a failed run with no explanation — exactly the silent-fail scenario documented in `03_deploy_concurrency_blast_radius.md Scenario 12`. The "best-effort; report stale tag is informational" rationale contradicts the brief §5 constraint 6 which lists this as an invariant, not a best-effort goal.

### M3: Phase 2 `OperationCoordinator` dual-active creates a deadlock window

The proposal at Phase 2 states: "`OperationCoordinator` retained (deprecated) alongside `CellLockRegistry` during Phase 2 for callers not yet migrated. Both can coexist."

OQ-6 flags this: "if `BatchGenerateManager` is migrated to `registry.try_acquire_cell(GENERATING)` but `OperationCoordinator.acquire("batch_generate_report")` is still called, the global lock still blocks concurrency."

This is more specific than OQ-6 describes. Consider the migration sequence in Phase 2 deliverable 8 ("Replace all remaining `OperationCoordinator` uses with appropriate `try_acquire_global` calls"). If this deliverable is partial — some callers migrated, others not — there is a window where:

- `delete_rawdata` endpoint acquires `registry.try_acquire_cell(M14, 1, DELETING)` (migrated in deliverable 7)
- `BatchGenerateManager._run` still holds `ops.acquire("batch_generate_report")` (not yet migrated)
- A new call to `RunManager.start_run` for from-cache generate now uses `registry.try_acquire_cell(M14, 1, GENERATING)` (migrated in deliverable 5)

The `OperationCoordinator` is now not held for the generate-report path, but the `BatchGenerateManager` still holds it globally. Any other operation that checks `ops.acquire` will get blocked, while the registry has already admitted the GENERATING operation for M14|1. Two concurrent GENERATING registrations for M14|1 are prohibited by INV-5, but nothing prevents them when one path is still through the old `ops` and one is through the new registry.

Phase 2 must have an atomic cutover, not a per-deliverable migration. The "retained for backward compat" approach is the source of the race.

### M4: `DELETE /api/machines/{machine}/all-data` vs. stale-tag invariant — open question OQ-7 is a design gap

OQ-7 asks: "this endpoint deletes reports too. Should `_tag_reports_stale` be skipped here (since reports are being deleted anyway), or should it run and then delete proceeds?"

The brief §5 constraint 6 says: "rawdata is deletable: ... Reports based on deleted rawdata stay but tag `underlying rawdata removed`." The word "stay" implies reports are preserved. But `DELETE /api/machines/{machine}/all-data` at `app.py:6283-6360` uses `shutil.rmtree` on the reports directory. This endpoint violates brief §5 constraint 6 as written. Either the brief allows this endpoint as an exception (it is the "catastrophic reset" button per the code comment), or the endpoint needs to be changed to preserve-and-tag instead of delete. This is a product decision that must be resolved before implementation of `_tag_reports_stale`, because the implementation path diverges depending on the answer.

### M5: Config upload endpoint writes content file INSIDE the registry lock

The proposal at §4.3 shows the upload algorithm calling `atomic_json_write(content_path, ...)` inside the `_upsert_registry` modifier, which runs while `atomic_json_read_modify_write` holds the file lock for `CONFIGS_REGISTRY_PATH`. This means the file lock is held across a potentially slow disk write (the config file itself). For large config files, this serializes all concurrent uploads behind a single write — not a correctness issue, but a latency issue that could cause the upload to time out under concurrent use.

More critically: `atomic_json_write(content_path, json.loads(content_str))` parses the content as JSON inside the modifier. If the uploaded content is not valid JSON (it is supposed to be a machine config file, but validation is not shown), `json.loads` raises `JSONDecodeError` inside the modifier, propagating through `atomic_json_read_modify_write` while the file lock is held. The lock is a `threading.Lock()` (not a context manager for exceptions in the modifier), so `JSONDecodeError` would unwind through `atomic_json_read_modify_write`. Looking at the proposed pseudocode, the outer `with lock` block does handle this correctly (lock is released on exception). But the content file write failure leaves no diagnostic. The `except Exception: raise` path at the end of `atomic_json_read_modify_write` does not write any error to disk, violating `memory/feedback_no_silent_swallow.md`.

---

## §4 Minor Concerns (improvements suggested)

### m1: Token bucket `wait_for_token` busy-poll interval is 200ms — not interruptible

The `wait_for_token` implementation at §4.5 uses `time.sleep(min(sleep_s, 0.2))`. Background fleet refresh callers block indefinitely with no way to cancel except process death. If the fleet refresh is cancelled via `DELETE /api/fleet/refresh`, the cancel sets `status=cancelled` in SQLite, but the `run_queue` loop only checks this after acquiring a token. If the bucket is empty and refilling at 3 tokens/s, the cancel check is delayed up to (capacity/refill_rate) + 0.2s per sleep = multiple seconds. For a responsive cancel, the wait loop should also check a cancel flag.

### m2: Disk monitor daemon at §4.8 calls `_auto_cleanup_for_space` which is not registry-aware

The disk monitor calls `_auto_cleanup_for_space(rawdata_root=rawdata_root, machines_config=machines_config, ...)`. At the time of the Phase 2 migration, `_auto_cleanup_for_space` is supposed to use `registry.get_active_cells()` instead of `_get_in_use_snapshot()` (Phase 2 deliverable 9). But the disk monitor is also introduced in Phase 2 (deliverable 11). If the disk monitor starts before deliverable 9 completes `_auto_cleanup_for_space` migration, it will call the old version which only checks `_IN_USE_MODES` (SAMPLING only), not GENERATING cells. This is exactly the Scenario 2 hazard that Phase 2 was meant to fix.

The disk monitor implementation in §4.8 also references `_auto_cleanup_for_space` directly, not through the registry. No explicit notation that these two deliverables must be atomic.

### m3: `stat` note in `_chunks.json` migration — existing chunks lack `config_id` field

The proposal adds `config_id` field to new chunk entries in `_chunks.json`. Existing chunks (all current rawdata) lack this field. The `by_config_id` index would not have a `"null"` entry for existing chunks unless a migration step rebuilds all sidecars. The proposal states backward compat via treating missing `config_id` as `"null"`, but `by_config_id` index won't have these chunks listed unless the sidecar is rebuilt. Attempting a dedup lookup via `by_config_id["null"]` on an existing sidecar will return `[]`, causing the system to fetch fresh data instead of reusing the existing chunks — silently breaking the dedup invariant for all pre-migration rawdata.

### m4: `chart.js` version pinning absent

The proposal says "download `chart.min.js` (current version used by the codebase, from `cdn.jsdelivr.net`)." It does not pin the version in the script tag (the `src` after vendoring is `/console/vendor/chart.min.js` with no version identifier). When the developer upgrades the codebase and runs the deploy setup again, the `chart.min.js` in `vendor/` is whatever was downloaded at initial setup. There is no mechanism to detect or update the vendored version. Minor for now; becomes a maintenance debt.

### m5: SQLite WAL mode migration — existing `console.db` is in DELETE journal mode

Enabling WAL via `PRAGMA journal_mode=WAL` on an existing database is safe and automatic (SQLite converts in-place). But the proposal says WAL is enabled in `StateStore._init_db()`. This method is called from `StateStore.__init__`, which is called every time `create_app()` runs. The PRAGMA runs on the first connection after restart, converting any existing DELETE-mode database. This is correct. However, the proposal also notes "SQLite WAL journaling breaks on network share rawdata path" in the risk register — but the `PRAGMA journal_mode=WAL` is on `console.db`, not on `rawdata/`. The WAL warning applies to the wrong file in the risk register. The actual risk is: `console.db` in WAL mode on a network share is unsupported by SQLite. If the user decides to move `state/console/` to a network share (not the rawdata), WAL breaks. The deploy README must explicitly document that `state/console/` must be local.

---

## §5 Particularly Fragile Assumptions

**FA-1: "Subprocess launch rate caps upstream concurrency" (§4.5)**

The design assumes that controlling the rate of new subprocess launches via the token bucket is equivalent to controlling the total upstream HTTP load. This holds only if each analyzer subprocess's lifetime is short relative to the token refill rate. For a full-fleet refresh with large `max_chunks`, analyzer subprocesses live for 15-60 minutes each. The steady-state upstream concurrency is `active_analyzers × batch_concurrency`, not governed by the launch rate after the initial ramp. See CI-2.

**FA-2: "Phase 1 is fully backward-compatible with single-user dev workflow" (§6 Phase 1)**

Phase 1 deliverable 10 enables SQLite WAL mode. This changes `console.db` permanently (WAL leaves `-wal` and `-shm` sidecar files in `state/console/`). A developer who runs Phase 1 on their machine and then reverts via `git revert` will have a WAL-mode database that the old code does not know to close properly (it does not call `PRAGMA wal_checkpoint(FULL)` or `PRAGMA journal_mode=DELETE` on exit). The `-wal` file grows unbounded until the checkpoint fires. For long-running dev sessions, this causes `console.db` plus its `-wal` sidecar to grow to multiple GB. The revert plan says "WAL files are cleaned up by SQLite on next EXCLUSIVE connection" — this is true but depends on a clean shutdown, which the PowerShell restart loop does not guarantee (it kills uvicorn on crash).

**FA-3: "Cross-process rawdata_index writes are eventually consistent via mtime retry" (§4.2)**

See CI-3. The assumption that NTFS mtime granularity (100ns) is sufficient to detect concurrent writes within 4-worker ProcessPoolExecutor is not validated by evidence.

**FA-4: "Task Scheduler restart loop is equivalent to a process manager" (§4.7 Alt S1)**

The PowerShell restart loop has `MAX_RESTARTS = 5`. After 5 crashes within a short window (e.g., uvicorn crashes due to repeated OOM from large chunk files), the restart loop exits and the server goes down permanently until manual intervention. Task Scheduler does not restart the PowerShell script itself — if the script exits with 0 (because `restarts >= MAX_RESTARTS`), the scheduled task is marked complete. There is no auto-recovery from the "exhausted restart budget" state. The proposal does not document what the operator should do in this case, nor does any monitoring surface alert on it. Combined with `memory/feedback_no_silent_swallow.md`, a permanently-down server with no alert is a production failure mode.

**FA-5: "OOS: multi-worker uvicorn not needed for <10 users" (§10 item 1)**

This is a reasonable OOS call, but the justification ("not needed for <10 users") hides a real capacity assumption. The single uvicorn worker model means all 10 planners' requests are handled sequentially by one event loop thread. FastAPI's async handlers are non-blocking for I/O, but `sqlite3.connect()` is a blocking synchronous call (per `01_deploy_pipeline_map.md §3 observation`). Under 10 concurrent planners each polling 3 timers at 1s/1.2s/4.5s intervals, the SQLite call rate is ~75 reads/minute. A slow disk (HDD vs. SSD) or a large `console.db` can produce 50-100ms blocking calls, visibly degrading UI responsiveness. This is not a breaking issue, but the OOS call is made without any measurement of actual SQLite call latency on the target Windows hardware.

---

## §6 Stack-Constraint Audit

### S1: PowerShell version dependency (implicit)

`start_console.ps1` uses the null-coalescing operator `??` (`$env:SLOT_BIND_HOST ?? "0.0.0.0"` in the pseudocode at §4.7). This operator was introduced in PowerShell 7.0. Windows Server / Windows 10 ships with PowerShell 5.1 by default. On a system with only PowerShell 5.1, the restart loop fails with a parse error on first execution, and Task Scheduler marks the task as failed silently (no alert). The proposal does not specify the minimum PowerShell version required and does not include a version check.

This is a hidden runtime requirement that could block deployment on the target "internal Windows machine" depending on its PowerShell version. It violates the spirit of "no new deps" — it implicitly requires a PowerShell upgrade if the target is not already on 7.0+.

### S2: SQLite 3.35+ for `DROP COLUMN` in rollback

Phase 3 rollback plan mentions "`ALTER TABLE runs DROP COLUMN underlying_removed` (SQLite 3.35+ supports this)." Windows ships SQLite with Python; the version depends on the Python installation. Python 3.10 ships with SQLite 3.39.2 (supports `DROP COLUMN`). Python 3.10 is the minimum per `01_deploy_pipeline_map.md §2`. This is technically within spec. However the rollback documentation should explicitly note the Python version requirement for `DROP COLUMN` since it is version-gated.

### S3: No new dependencies introduced

The three new modules (`cell_lock_registry.py`, `config_writer.py`, `rate_limiter.py`) use only stdlib (`threading`, `time`, `pathlib`, `os`, `json`, `hashlib`). SQLite changes are to the existing `console.db` via the existing `sqlite3` stdlib module. No new packages. No new processes. Stack constraint is satisfied.

---

## §7 Test Plan Adequacy

### T7.1: H1 test group premised on already-fixed bug

Group T1 test `test_acquire_generating_blocks_deleting_same_cell` and deliverable "inject bug: remove `_IN_USE_MODES` check from delete_rawdata" correspond to fixing H1. Per CI-1, H1 is already present in the codebase (`app.py:7212`). The inject-bug test for H1 will pass even WITHOUT the CellLockRegistry migration (the existing `_acquire_in_use` already blocks cleanup). This means the inject-bug test does not prove the CellLockRegistry migration works — it proves the existing mechanism works. The test group must be redesigned to inject the bug into the registry path (remove `try_acquire_cell(GENERATING)` check), not into `_acquire_in_use`.

### T7.2: Group T9 E2E tests require real upstream access

`test_two_concurrent_batch_runs_different_cells_both_complete` spawns "real uvicorn" and POST /api/batch-run for M14|1 and M15|1 simultaneously. Per `memory/feedback_no_proactive_fetch.md`: "dev 永远走 --from-cache / --resume-from-cache; 只有 envelope 版本 / API schema 变了才重采." The E2E test as described triggers real upstream fetches. This violates the dev caching policy and may fail in CI environments without network access to `192.168.10.21:15060`. The test should use `--from-cache` with the existing M14/M15 cached chunks, consistent with `memory/feedback_perf_claim_needs_e2e_event_stream.md` which requires "real subprocess against real fixture (M15 cached chunks)."

### T7.3: No test for CellLockRegistry release-on-crash

The proposal's `CellLockRegistry` is in-memory only. Its invariant is "on crash, restart clears it." The test plan has no test verifying that a restarted process correctly starts with an empty registry and does not carry over stale SAMPLING registrations from the previous process. The restart scenario is not covered by any Group T1-T9 test. For the fleet refresh crash-recovery (INV-9), Group T7 tests `test_resume_after_simulated_crash` — but this tests the SQLite queue, not the in-memory registry. After restart, the resumed items attempt `registry.try_acquire_cell(..., SAMPLING)` on a fresh registry — this should always succeed. But there is no explicit test confirming that the fresh-start registry does not inherit any state from the previous process's SQLite `fleet_refresh_items` table (where items were in `running` status before the crash).

### T7.4: Memory-file test mapping has one genuine tautology

The mapping for `feedback_subprocess_import_suicide_and_module_globals.md` maps to `test_virtual_app_import_does_not_trigger_build`. This test validates that the already-fixed import-suicide pattern remains fixed. Per `03_deploy_concurrency_blast_radius.md Scenario 8`, the import-suicide is already resolved in the baseline. The test is a regression guard for a fixed bug, not a test of the new proposal. This is correct per `memory/feedback_enumerate_safety_paths.md`'s inject-bug policy, but the mapping should be explicit that this is a baseline-preservation test, not a proposal-validation test.

### T7.5: Frontend tests are not specified with tooling

Groups `test_frontend_error_branch_reset.js` and `test_frontend_fasttimer.js` are listed in §5.5 but the test runner and framework are not specified. The existing codebase has no frontend test framework (`01_deploy_pipeline_map.md §3` confirms "no build tool, no Webpack, no compilation step"). These tests require Playwright, Puppeteer, or a mock DOM environment — none of which are in the current stack. Listing them without specifying the tooling is aspirational, not actionable.

---

## §8 Designer's 8 Open Questions — Analysis

**OQ-1: GENERATING + SAMPLING coexistence per cell**

The proposal allows concurrent SAMPLING (new chunks) + GENERATING (read from cache) on the same cell. The specific question: can the generator's chunk glob race with a new chunk being `os.replace`d into existence?

Analysis: Yes, this race exists but is benign. The generator globs `chunk_*.json` at startup. A new chunk atomically renamed after that glob is simply not included in the generator's snapshot — the generator produces a report on slightly fewer spins than actually available. This is not a correctness violation; it is the documented "snapshot" behavior. The generator does NOT re-glob mid-run.

Verdict: ADEQUATELY ADDRESSED. The coexistence is safe. No design change needed.

**OQ-2: rawdata_index mtime retry sufficient?**

Analysis: Not sufficient. Per CI-3, NTFS mtime granularity is 100ns. Four workers completing near-simultaneously can have identical mtimes. The retry does not detect this and proceeds with a lost update. A file-level exclusive lock (Windows `msvcrt.locking` or a separate lock file) or a redesign to per-cell index sharding is needed.

Verdict: NOT ADEQUATELY ADDRESSED. This is a critical design gap (CI-3 above). W3 cannot approve until the mechanism is hardened.

**OQ-3: config_id sidecar-only annotation — orphan on parent crash**

If the parent crashes after the chunk is written but before the sidecar is updated with `config_id`, the chunk exists with no `config_id` association. Subsequent dedup via `by_config_id` would not find this chunk. The chunk is effectively orphaned from the uploaded config.

The designer's mitigation: "parent annotates chunk in sidecar after subprocess completes; suboptimal but correct." The "correct" claim is not correct in the crash window. The orphaned chunk still has `cfg_md5` / `code_md5` in its sidecar entry (written by the subprocess) — it is not invisible, just not attributed to the config_id. The dedup invariant `(config_id, machine, mode, upstream_md5)` would be broken: two fetches with the same 4-tuple would produce duplicate upstream calls because the first fetch's chunks are not associated with the config_id in `by_config_id`.

Verdict: PARTIALLY ADDRESSED. The crash case creates a genuine dedup invariant violation. The designer acknowledges this in the risk register but marks it "Medium" impact. For a production system, undetectable dedup failures (no alert, no UI signal) should be Higher. At minimum, a startup recovery scan for `config_id`-less chunks belonging to active configs is needed.

**OQ-4: Fleet refresh infinite cell-busy stall**

Analysis per M1 above: this is a behavioral gap, not a tuning question. A maximum wait timeout with a specific UX response (skip vs. hold indefinitely) must be defined before implementation.

Verdict: NOT ADEQUATELY ADDRESSED. Requires designer decision, not W3 validation.

**OQ-5: Token bucket parameter validation**

Per CI-2: the parameters cannot be validated by inspection because the model is wrong (controls launch rate, not steady-state concurrency). Even if the parameters are numerically correct, the mechanism does not achieve the stated goal.

Verdict: NOT ADEQUATELY ADDRESSED. The mechanism itself needs redesign before parameters can be validated.

**OQ-6: OperationCoordinator deprecation path**

The concern is valid: if Phase 2 migration is partial, old `ops.acquire` calls coexist with new registry calls, producing potential double-blocking or inconsistent state. The designer correctly identifies this but leaves the ordering unresolved.

Verdict: PARTIALLY ADDRESSED. The solution exists (make Phase 2 an atomic cutover, not a per-caller migration), but the proposal does not commit to this. The deliverable list in Phase 2 must be re-ordered to make the cutover atomic.

**OQ-7: DELETE /api/machines/{machine}/all-data vs. stale-tag**

Per M4 above: this is a product decision that changes the implementation path for `_tag_reports_stale`. The brief §5 constraint 6 implies reports are preserved ("stay but tag"), but this endpoint deletes them. The conflict must be resolved.

Verdict: NOT ADEQUATELY ADDRESSED. Requires product decision from the coordinator/user.

**OQ-8: Fleet refresh progress panel — renderer reuse**

The proposal says reuse `batchRunProgress` renderer per `memory/feedback_no_parallel_panel_impl.md`. The 393-item fleet refresh has a two-level hierarchy (queue-level + machine-item-level) that the single-level `batchRunProgress` renderer does not support.

Looking at the existing code: `batchRunProgress` renders a flat list of per-machine items with progress bars. The fleet refresh needs the same list view but at a larger scale with queue-level metadata. The renderer IS extensible — it would need a new queue-header section above the existing items list. This is a sibling extension, not a parallel implementation. The concern is manageable but requires explicit design of the extension points before frontend implementation.

Verdict: PARTIALLY ADDRESSED. The answer is "yes, extensible," but the extension design must be specified to avoid a parallel implementation regression.

---

## §9 Migration Risk Inventory

### Phase 1 risks

**R1.1: SQLite WAL mode is permanent for the database file**

`console.db` converted to WAL cannot easily be reverted without an EXCLUSIVE connection. The Phase 1 revert plan says "WAL files are cleaned up by SQLite on next EXCLUSIVE connection" — this requires the old code (pre-Phase-1) to connect in EXCLUSIVE mode, which it does not do. A developer who reverts Phase 1 mid-way may have a WAL-mode database that the reverted code leaves in inconsistent checkpoint state.

**R1.2: `atomic_json_read_modify_write` for `machines.json` calls `apply_md5_refresh` twice**

The proposal's migration snippet for Critical C1 calls `apply_md5_refresh` twice: once inside the modifier, and once again after the write to compute stats. The second call re-reads `machines.json` from disk. If another writer has since modified `machines.json` (which is now protected by the file lock), the stats are computed against a different state than what was written. This is observability-only (per the proposal comment), so it cannot corrupt the data, but it is misleading and should be noted.

**R1.3: `_LOCK_CACHE` threading.Lock fix during Phase 1 may conflict with existing call sites**

Phase 1 deliverable 8 adds a `threading.Lock` to `_LOCK_CACHE`. The existing `_load_rawdata_locks` and `_save_rawdata_locks` functions (at `app.py:2185-2228`) must both be updated to acquire this lock. If the update is partial (lock added to one but not both), the single-process TOCTOU becomes worse — a thread that acquires the lock for read may now be blocked by a concurrent write that doesn't use the lock, defeating the purpose.

### Phase 2 risks

**R2.1: 15+ call sites for CellLockRegistry migration — one miss is a hazard**

The proposal table lists 15 callers that must be updated. Per `memory/feedback_enumerate_safety_paths.md`, missing one path is exactly how the M1 `check_rawdata_status(auto_delete_mismatched=True)` bug persisted. The CI grep check proposed ("grep -rn shutil.rmtree|\.unlink()") would catch delete-path omissions but NOT sampling or generating path omissions. A separate grep for `_acquire_in_use` call sites (to verify all have been replaced) is needed.

**R2.2: `OperationCoordinator` retained alongside `CellLockRegistry` — behavioral regression for ad-hoc generate-report**

`RunManager.start_run` (from-cache generate path) currently acquires `ops.acquire` (global). After Phase 2 migration to `registry.try_acquire_cell(..., GENERATING)`, it no longer acquires `ops`. If a `batch_generate_report` is still running (holding `ops` globally via the un-migrated `BatchGenerateManager`), the ad-hoc generate-report now proceeds without checking `ops`. But the `BatchGenerateManager`'s finalize thread is also running `_finalize_batch_gen_item` which writes `index.json`/`latest.json` for potentially the same cell. The `CellLockRegistry`'s GENERATING mutual exclusion should prevent this — but only if `BatchGenerateManager` has also been migrated to the registry. The Phase 2 deliverable ordering matters here and is not specified.

**R2.3: Disk monitor daemon uses `_auto_cleanup_for_space` which may not be registry-aware when daemon starts**

Per minor concern m2. The disk monitor starts in Phase 2 but `_auto_cleanup_for_space` may be migrated to use `registry.get_active_cells()` in a later deliverable of Phase 2. The daemon must not start until the cleanup function is registry-aware.

### Phase 3 risks

**R3.1: `config_id` field in `_chunks.json` — no migration for existing sidecars**

All existing `_chunks.json` files lack `config_id` and `by_config_id`. The proposal states existing chunks default to `config_id="null"`. But `by_config_id["null"]` in existing sidecars will be empty (the key does not exist). The lazy rebuild that adds `by_config_id` (per `memory/reference_chunk_index_inverted_md5.md` — "next write落盘 v2 layout") would add `by_md5` but not `by_config_id`. A separate migration that rebuilds all sidecars with `by_config_id` is needed, or the dedup lookup must handle missing `by_config_id` as "treat all existing chunks as config_id=null." The proposal does not specify which approach is taken.

**R3.2: Fleet refresh queue SQLite tables — no schema version guard**

Phase 3 adds two new tables via `CREATE TABLE IF NOT EXISTS` in `StateStore._init_db()`. If the operator rolls back to Phase 2 code (Phase 3 rollback plan), the tables remain in `console.db`. The Phase 2 code does not know about these tables and does not use them — they are inert. But if the operator then runs Phase 3 code again, `CREATE TABLE IF NOT EXISTS` is idempotent, so no migration failure. Low risk, but the rollback plan should confirm that stale tables do not affect Phase 2 behavior.

**R3.3: Fleet refresh `_recover_fleet_refresh` called from `StateStore.__init__` — blocks startup**

`StateStore.__init__` is called during `create_app()`. If `_recover_fleet_refresh` must query `fleet_refresh_queue` (which may not yet exist in older deployments), it must handle `sqlite3.OperationalError: no such table` gracefully. The proposal's pseudocode for `_recover_fleet_refresh` does not show this guard. On a fresh install (Phase 3 code with pre-Phase-3 database), this would crash `create_app()` on first startup.

### Phase 4 risks

**R4.1: Task Scheduler XML is environment-specific**

The `task_scheduler_setup.xml` contains hardcoded paths (`C:\...\scripts\start_console.ps1`). On a different deployment machine with a different repo path, the XML must be edited. The proposal says "one-command task creation" but this is only true if the path matches. The setup script must substitute the actual repo path dynamically (e.g., using `schtasks /Create /TR "powershell.exe -File {repo_root}\scripts\start_console.ps1"`).

**R4.2: PowerShell 7.0 requirement (per S1 above)**

See §6 S1. The `??` operator requires PowerShell 7.0. On Windows machines with PowerShell 5.1 (default for Windows Server 2016/2019, Windows 10 before manual upgrade), the script fails silently at Task Scheduler level.

---

## §10 Edge Cases Not Covered

**EC-1: Two planners cancel the same fleet refresh simultaneously**

`DELETE /api/fleet/refresh` presumably sets `status='cancelled'` in `fleet_refresh_queue`. Two concurrent DELETE calls both check `status='running'` and both proceed to write `status='cancelled'`. With `atomic_json_read_modify_write`-style logic on SQLite, this is safe (SQLite serializes writes), but the proposal does not describe what happens when both writes succeed — is the result idempotent? And if the `run_queue` loop checks the cancel flag between items, does it see the cancellation signal atomically with respect to item-status updates?

**EC-2: Fleet refresh starts on a 393-machine list that includes machines with no modes**

`POST /api/fleet/refresh` generates items from `configs/machines.json`. Some machines in the fleet may have only `mode_1` while others have `mode_1, mode_2, mode_7`. The queue item enumeration must handle variable mode sets per machine. The proposal says "393-machine full-refresh" but does not specify how modes are determined per machine or what happens if a machine's mode set is unknown (no rawdata, no machines.json mode spec).

**EC-3: Planner uploads the same config content with different display names simultaneously**

Two planners upload identical file content with different display names. The `_upsert_registry` modifier sees the `config_id` already in the registry (first write wins) and returns without updating the display name. The second planner's display name is silently discarded. The planner sees their upload succeed (same `config_id` returned) but their display name is gone. This is a UX gap not a correctness issue, but it is a predictable user-facing failure that should be documented.

**EC-4: Rawdata delete during fleet refresh of the same cell**

`DELETE /api/rawdata/{machine}/mode/{mode}` acquires `registry.try_acquire_cell(DELETING)`. Fleet refresh's `run_queue` acquires `registry.try_acquire_cell(SAMPLING)` for the same cell. These are mutually exclusive per INV-1. So the delete gets 409. But the fleet refresh item is now in `status='running'` in SQLite (it has already been acquired). If the planner deletes the rawdata via the force path (`DELETE /api/machines/{machine}/all-data`), which goes through `OperationCoordinator` not the registry (during Phase 2 transition), the delete succeeds while the registry shows SAMPLING active. Result: the fleet refresh item reads rawdata that was just deleted.

**EC-5: `min_retention_spins` setting changed mid-fleet-refresh**

`PUT /api/settings` can change `min_retention_spins` while a fleet refresh is running. The disk monitor uses this setting each time it fires. The fleet refresh items use the setting at the time `_auto_cleanup_for_space` is called pre-flight. If the setting is lowered mid-refresh (operator trying to free disk), the cleanup policy becomes more aggressive mid-run, potentially deleting chunks that earlier items relied on for `--resume-from-cache`. The proposal does not snapshot the settings value at fleet-refresh-start.

**EC-6: Task Scheduler running `start_console.ps1` under SYSTEM account**

Windows Task Scheduler defaults to running tasks under the SYSTEM account when "run whether user is logged on or not" is selected. SYSTEM account has restricted access to network shares and may not have write access to `rawdata/` and `state/console/` if they are owned by a specific user. The deploy README must specify the exact account setup, and the smoke test should verify file write access, not just HTTP reachability.

**EC-7: `FleetRefreshManager` is a new singleton not accounted for in virtual console path**

The proposal at OOS §10 item 6 says "Phase 1-2 changes to `ConfigFileWriter`, `CellLockRegistry`, etc. are available to the virtual console automatically since it calls `create_app()`." But `FleetRefreshManager` (Phase 3) is a new singleton that must be injected into `create_app()`. The virtual console's `build_virtual_app()` calls `create_app()` with specific injected paths. Does `FleetRefreshManager` need injection overrides for the virtual console (different rawdata, different machines config)? The proposal assumes the virtual console can use the real FleetRefreshManager unchanged, but the virtual console's rawdata root and machines config are different. A fleet refresh from the virtual console should not write to the real rawdata directory.

---

## §11 Hidden Assumptions Not Validated by Wave 1 Evidence

**HA-1: The internal upstream has no per-IP rate limit**

`01_deploy_pipeline_map.md §7.4` states: "The current internal upstream (`192.168.10.21:15060`) reportedly has no per-IP rate limit per code comments at `player_impact_analyzer.py:345-346`." This is a "reportedly" — not confirmed by measurement. If the internal upstream does have a rate limit (it is the same machine hosting the game engine; simultaneous 120 HTTP connections to a game simulation engine is not obviously safe), the rate-limit bucket design is vindicated, but its parameters may need recalibration.

**HA-2: All rawdata and state/console are on a single local disk**

The proposal's disk monitor at §4.8 uses `shutil.disk_usage(str(rawdata_root))` to check free space. This checks the disk partition where `rawdata/` lives. If `state/console/` (which contains `console.db`) is on a different partition (e.g., if the operator sets `SLOT_RAWDATA_ROOT` to a data drive `D:\` while the code lives on `C:\`), the disk monitor does not check the `C:` partition where SQLite writes. `console.db` growth (all runs, all interpretations) is not bounded. A fleet refresh with 393 machines × multiple retries could generate thousands of run rows. The disk monitor will not alert when `C:` is full.

**HA-3: Single uvicorn process can handle concurrent `proc.communicate()` waits**

`RunManager._watch_run` calls `proc.communicate()` which blocks the thread until the subprocess exits. With 10 planners each having active runs, there are up to 30 blocking threads (10 planners × 3 batch concurrency each). Python's threading model handles this fine (GIL released during OS blocking calls), but the uvicorn `asyncio` event loop is not involved — these are daemon threads. The assumption that this is safe is correct, but the total thread count is: 30 watch threads + 1 disk monitor + 1 prewarm + 1 fleet refresh manager + 4 ProcessPoolExecutor parent threads = ~37 threads. On Windows, thread creation cost is higher than Linux. This is within safe limits but should be noted.

**HA-4: `DELETE /api/rawdata/{machine}` (whole-machine delete) acquires `OperationCoordinator`, not per-cell lock**

During Phase 2 migration, `DELETE /api/rawdata/{machine}` is migrated to use `registry.try_acquire_cell(DELETING)` per-mode. But the endpoint deletes all modes under a machine. The proposal table shows this endpoint mapped to `registry.try_acquire_cell(..., DELETING)`. The implementation must iterate all modes and acquire the cell lock for each. If any mode acquisition fails (another op is active for that mode), the proposal does not specify whether the whole-machine delete should abort or proceed with the successfully-acquired modes. Partial deletion of modes on a machine is operationally confusing.

---

*Critique complete. All 10+ stress angles addressed per task specification.*
