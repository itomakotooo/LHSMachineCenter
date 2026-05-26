# Auto-Inspect Architecture Validation
> Validator output — Wave 3
> Date: 2026-05-26
> Input: `04_architecture_proposal.md` (Option C), `02_taxonomy.md`, `01_pipeline_map.md`, `03_coupling_audit.md`

---

## Verdict: APPROVE-WITH-REVISIONS

Three issues require designer iteration before implementation proceeds. One is a correctness bug that would corrupt multi-worker item dispatch (S4-G1). One is an internal schema inconsistency that makes the mid-sweep drift detection impossible to implement as written (S5-G1). One is an interface gap that breaks the auto-resume wiring path (S3-G1). All other findings are awkward edge cases or acknowledged open questions; none block approval by themselves.

The core architecture is sound. Option C's isolation, explicit failure modes, R1/A2 extension, and binary-group semaphore model all verify as correct in principle.

---

## Per-Scenario Walkthrough

---

### Scenario 1 — Happy path: fresh deploy, fresh sweep

**Setup:** 422 machines x 4 modes = 1,688 cells. No rawdata. No reports. Operator opens 自动巡检, accepts defaults, clicks 开始巡检.

#### Step-by-step trace

**Scanning phase (< 1 minute):**

1. `POST /api/auto-inspect/start` -> `AutoInspectManager.start_sweep(trigger="manual")`.
2. Status transitions from `idle` -> `scanning`.
3. `_do_refresh_machines_md5(raise_on_error=False)` called synchronously (30s timeout). Fetches current `(configSummaryMd5, codeSummaryMd5)` for all 422 machines and atomically rewrites `configs/machines.json`. On fresh deploy this is a no-op if machines.json is already current.
4. For each of 1,688 `(machine, mode)` pairs:
   - `_get_machine_md5(machine, mc, mode)` — with explicit `mode` per RISK-1 rule.
   - `check_rawdata_status(machine, mode, rawdata_root, machines_config)` — returns `usable_chunks=0, mismatch_chunks=0` (no rawdata yet).
   - `_build_machines_summary` result — no entry exists (no reports) -> `needs_sample=True` for all 1,688.
5. Cell-class assignment runs against the hardcoded rosters:
   - `bcm_hard` (7 machines, 28 cells): M250, M260, M264, M268, M279, M99, M274. These get `status='structural_skip'` immediately. Run count for pending items: 1,688 - 28 = 1,660.
   - `trigger_session` (52+100=152 underlying/variant machines, 596 cells across modes): Type-1 (M12, M15, M32, M90, M132, M206, M39, M86, M116, M210, M123 + variants) and Type-2 (M201, M257, M273 + variants).
   - `bcm_moderate`: M147, M163.
   - `bcm_uncharted`: M278, M280, M281.
   - `easy`: remaining 1,024 cells.
6. Queue positions assigned:
   - tier 0 (easy): `0*10000 + within_tier_index` = 0..1023
   - tier 1 (trigger_session): `1*10000 + 0..595` = 10000..10595
   - tier 2 (bcm_moderate + uncharted): `2*10000 + 0..19` = 20000..20019
   - tier 3 (bcm_hard): `3*10000 + 0..27` = 30000..30027. These rows are written with `status='structural_skip'` (never become pending).
7. Binary-group semaphores initialized:
   - `c2a4e3be` (M273 family, 86 machines): cap = `_LARGE_GROUP_CAP` = 2 (>= 20 threshold).
   - `f7a4cefd` (45-machine standard large group including M14): cap = 2 (>= 20 threshold). **See gap C1 below.**
   - All other groups: cap = `_BINARY_GROUP_DEFAULT_CAP` = 4.
8. `auto_inspect_sweeps` row written: `status='scanning'`. 1,660 `auto_inspect_items` rows written as `pending`, 28 as `structural_skip`. Status transitions to `sampling`.

**Sampling phase:**

3 worker threads start. Each worker loops:

1. `SELECT ... WHERE status='pending' ORDER BY queue_position LIMIT 1` -> first item: some easy-tier mode-1 cell.
2. **[GAP S4-G1]** No atomic claim step (see Scenario 4). All 3 workers risk picking the same item. With correct claim mechanism: W1 picks M1 mode 1 (queue_position=0), W2 picks M2 mode 1 (position=1), W3 picks M13 mode 1 (position=2).
3. `binary_group_semas['f7a4cefd'].acquire()` — cap=2 for this group. W1 and W2 acquire. **W3 is blocked here** because f7a4cefd cap=2 is already full.
4. Once W3 gets past sema (after W1 or W2 finishes): `registry.try_acquire_cell(M13, 1, SAMPLING)` -> acquired.
5. `limiter.acquire("background")` — 3 background slots. With sweep_concurrency=3 and cap=2 on binary group, at most 2 cells in the f7a4cefd group run concurrently. The 3rd background slot could be taken by a non-f7a4cefd cell if the worker thread picks one while waiting — but the proposal's per-item flow blocks the worker at the binary sema BEFORE it can pick a different item.
6. `RunManager.start_run(RunCreateRequest)` -> analyzer subprocess spawned.

**Wall time estimate:**

Per cell at defaults: chunk_spin_times=10000, loopback ~3,700 spins/s: ~2.7s per chunk. Max 120 chunks = 324s = 5.4 min/cell (if CI target met). With 3 workers but binary_group cap=2 for the 45-machine easy tier: effective parallelism for f7a4cefd is 2 cells at a time. For 1,660 pending cells at ~2 effective concurrent: ~1,660 / 2 * 5.4 min = ~4,470 min = ~74 hours worst case. This is the fresh deploy wall time; steady-state sweeps will only process stale cells.

**Generate phase:**

Runs AFTER all 1,660 cells reach terminal state. For easy-tier cells this means operators wait the full ~74 hours before any report appears. This is acknowledged in OQ-B but operationally severe for a fresh deploy.

**What the proposal handles cleanly:**

- Cell discovery logic (§3): md5 refresh + `_build_machines_summary` + `check_rawdata_status` correctly identifies all 1,688 as needing sample on fresh deploy (§3 steps 1-3).
- Structural skip at scan time (§5c): M250/M260/M264/M268/M99 never enter the pending queue.
- Easy-first ordering (§3 step 5): tier-0 cells always have lower queue_position than tier-3, ensuring operators see easy results first.
- Fully injected paths (§3 construction): no `RAWDATA_ROOT` module-global reads. RISK-1 addressed.

**Gaps / ambiguities this scenario surfaces:**

- **C1 (cross-scenario):** The 45-machine f7a4cefd binary group (M1, M2, M14, M13, M101, M105...) hits the `>= 20 machines` threshold and gets `binary_group_large_cap=2`. This caps easy-tier throughput to 2 concurrent cells from the largest easy cluster. The DoS rationale for M273 (same game config across all 86 variants) does not apply to f7a4cefd (45 machines with distinct configs — per 02:§6 Pattern A). **The threshold applies uniformly but the risk is not uniform.** Effective sweep_concurrency is 2 not 3 for the first ~512 cell-pairs in tier 0.

- **S1-G1 (OQ-B, acknowledged):** Generate phase waits for ALL 1,660 cells before starting. On fresh deploy, no operator-visible reports appear for ~50-74 hours. The proposal lists this as OQ-B without resolution. For a fresh deploy this is operationally blocking.

**Concrete suggestion:** For C1, the designer should add a second condition to the large-cap threshold: only apply cap=`_LARGE_GROUP_CAP` when the group has `>=20 machines AND the machines within the group share an identical configSummaryMd5` (i.e., true single-config groups like M273). The f7a4cefd group has 45 distinct configs and should use `_BINARY_GROUP_DEFAULT_CAP=4` or `sweep_concurrency`. For S1-G1, the designer should resolve OQ-B before implementation (per-cell-immediate generate vs sequential); this is a product decision that affects operator UX on every deploy.

**Verdict: APPROVED-WITH-CONCERN** — core flow is clean; C1 is a correctness-of-rate-limit-design issue and S1-G1 is an OQ the designer left open.

---

### Scenario 2 — Hard case mid-sweep: M250

**Setup:** Sweep is running. M250 mode 1 enters consideration during scanning phase.

#### Step-by-step trace

**At scan time (before any worker threads start):**

1. `_get_machine_md5("M250", mc, 1)` -> `("048380c8...", "771536a9...")`. M250's binary is unique — not in any large binary group.
2. `check_rawdata_status("M250", 1, ...)` -> `usable_chunks=0` (no rawdata, or all mismatch).
3. `_build_machines_summary` -> no M250 mode 1 entry -> `needs_sample=True`.
4. Cell-class assignment: M250 is in the hardcoded `bcm_hard` roster (02:§7 Tier 1). `cell_class = 'bcm_hard'`.
5. §5c trigger: `cell_class == 'bcm_hard'` -> `status = 'structural_skip'`, `terminal_reason = "结构性问题需人工审查: M250 (BCM anchor gap)"`. Written to `auto_inspect_items`. No run started. No rawdata written.
6. M250 mode 1's `queue_position = 3*10000 + within_tier_index` (tier 3). But since status is already `structural_skip`, it is not in the pending queue for workers.

**Worker thread behavior:**

Workers only `SELECT WHERE status='pending'`. M250 rows have `status='structural_skip'` — workers never touch them. No SAMPLING lock acquired for M250. No binary-group sema acquired.

**Next cell after M250 (e.g., M14 mode 7):**

M14 mode 7 is at tier 0 (easy), queue_position ~3 (within easy tier, mode 7 ordering). This was already dispatched to a worker during tier-0 processing, long before the scanning phase even evaluated M250 (tier 3). No delay for M14 mode 7 due to M250.

**What operator sees:**

UI drill-down table row for M250 mode 1: grey/orange dot, terminal_reason = "结构性问题需人工审查: M250 (BCM anchor gap)". This appears immediately in the UI since it is set at scan time.

**How the design detects "structural" vs "just slow":**

Detection is static classification, not runtime observation. The `bcm_hard` roster is a hardcoded list in `auto_inspect_manager.py`. The proposal does NOT detect structural failure dynamically (e.g., by sampling 10 chunks and observing 100% unattributed win). Detection is: "is this machine in the hardcoded list?"

**What the proposal handles cleanly:**

- §5c structural_skip: immediate classification, no wasted spin budget on M250. Clean.
- Tier ordering (§3 step 5): M250 is tier 3, M14 is tier 0. M14 is processed first by design.
- M274 exception correctly specified: `cell_class='bcm_hard_monitored'` not `structural_skip` — M274 runs with full budget and regression tripwire check (§5). M279 also excluded from structural_skip per §5c note.

**Gaps / ambiguities:**

- **S2-G1 (awkward):** When M250's BCM anchor rule ships (§10 point 4), auto_inspect_manager.py must be manually updated to remove M250 from the `bcm_hard` hardcode list. The proposal notes this but there is no runtime mechanism (e.g., a config-driven list in settings.json or machines.json) that would allow unblocking M250 without a code deployment. This is a maintenance coupling between analyzer fix and sweep manager code.

**Concrete suggestion:** The designer should move the `bcm_hard` machine roster from a hardcode in `auto_inspect_manager.py` to a JSON config key (e.g., `auto_sweep.structural_skip_machines` in settings.json or a separate `configs/sweep_overrides.json`). The operator or deployer can then update the list without a code deploy when the BCM fix ships.

**Verdict: APPROVED** — handles M250 cleanly. S2-G1 is a maintenance concern, not a runtime failure.

---

### Scenario 3 — Console restart mid-sweep

**Setup:** 600/1,688 cells processed. 50 cells `status='running'`. 30 cells `status='completed'`. 520 cells `status='pending'`. Console crashes. Restarts 60s later.

#### Step-by-step trace

**On crash:**

- `auto_inspect_sweeps` row has `status='sampling'`.
- 50 `auto_inspect_items` rows have `status='running'` with valid `run_id` values.
- 30 rows are `status='completed'`.
- 520 rows are `status='pending'`.
- The 50 RunManager run rows in the `runs` table have `status='running'` (subprocess PIDs are dead).

**On restart (StateStore.__init__):**

1. `StateStore._init_db()` — `CREATE TABLE IF NOT EXISTS` for all three new tables. No-op (tables exist).
2. `StateStore._recover_fleet_refresh()` — checks `fleet_refresh_queue WHERE status='running'`. None found (sweep uses different tables). No-op.

**On restart (AutoInspectManager.__init__):**

3. `_restore_on_startup()`:
   - `SELECT sweep_id FROM auto_inspect_sweeps WHERE status IN ('scanning','sampling','generating')` -> finds the running sweep.
   - `UPDATE auto_inspect_items SET status='pending', run_id=NULL WHERE sweep_id=X AND status='running'` -> 50 rows reset to pending.
   - `self._pending_resume_sweep_id = sweep_id`.

**On create_app (after AutoInspectManager constructed):**

4. `if auto_inspect_mgr._pending_resume_sweep_id:` -> True -> spawns daemon thread calling `auto_inspect_mgr.resume_sweep(sweep_id)`.

**Gap: `resume_sweep()` is not in the public interface (§1).**

The public interface (§1) lists: `start_sweep`, `cancel`, `get_status`, `list_history`, `get_cell_status`. There is no `resume_sweep` method defined. The auto-resume path (`create_app` spawning a thread) needs to call something. The proposal says `resume_sweep(sweep_id)` in §4 but omits it from §1. Without this method, the wiring in `create_app` has no target.

**On restart (RunManager._recover_orphan_running_runs, A2):**

5. Finds 50 `runs` rows with `status='running'` and dead PIDs.
6. For each: calls `_is_cell_owned_by_active_queue(machine, mode)`.
7. **§4 extension is critical here:** the new fourth branch queries `auto_inspect_items WHERE status IN ('pending','running') AND sweep_id IN (SELECT sweep_id FROM auto_inspect_sweeps WHERE status IN (...))`.
8. After step 3 above, those 50 items have `status='pending'` (reset), so the fourth branch returns a non-None owner string -> A2 skips auto-resume for all 50 cells. Correct.

**Does the sweep resume automatically or require operator click?**

§4 says create_app auto-spawns the resume thread. §2 says "On page load, GET /api/auto-inspect/status -> has_resumable: true. Resume button visible. Clicking it calls POST /api/auto-inspect/resume."

These two descriptions conflict. The fleet_refresh analogue at app.py:11600 IS automatic (no operator click). If the sweep also auto-resumes, the "Resume button" in §2 is informational UI only — confirming the auto-resume is in progress. If it requires operator click, create_app does nothing and the button at POST /api/auto-inspect/resume triggers the thread. The proposal does not state which behavior is authoritative.

**Scanning phase re-runs on resume:**

§4 says "The scanning phase is NOT resumed — it is re-run from scratch on resume." This means on restart, the sweep re-calls `_do_refresh_machines_md5` and re-evaluates all cells. The 30 `completed` rows are unaffected (not reset). The 50 newly-pending rows get re-evaluated; if their md5 is still valid, they proceed as before. This is correct behavior and matches the FleetRefresh pattern.

**What the proposal handles cleanly:**

- §4 restart recovery: reset `running` -> `pending` is correct pattern (matches FleetRefresh at app.py:2132).
- A2 protection (§4 `_is_cell_owned_by_active_queue` extension): correctly prevents double-spawn for sweep-owned cells.
- Completed cells preserved across restart: not re-enqueued.

**Gaps:**

- **S3-G1 (gap):** `resume_sweep()` is not in the public interface (§1). The method is needed for the `create_app` wiring path. Without it, Phase 1 implementation cannot wire the auto-resume.
- **S3-G2 (ambiguity):** §4 implies auto-resume (create_app spawns thread). §2 implies manual-resume (operator clicks button). One must be authoritative. The FleetRefresh analogue is automatic.

**Concrete suggestions:**
- S3-G1: Add `resume_sweep(sweep_id: str) -> None` to the public interface in §1. This is the internal method called by create_app; POST /api/auto-inspect/resume also calls it.
- S3-G2: Clarify in §4 whether auto-resume is the default. Recommendation: match FleetRefresh (auto-resume). The UI Resume button becomes a "Resuming..." status indicator, not a trigger.

**Verdict: APPROVED-WITH-REVISIONS** — two concrete gaps (S3-G1 interface missing, S3-G2 ambiguity).

---

### Scenario 4 — M273 binary-group concurrency

**Setup:** Sweep dispatches M273 parent (M273, upstream_key=M273) and its 85 variants. Total: 86 machines × 4 modes = 344 cells. Binary group codeSummaryMd5 = `c2a4e3be...`. `binary_group_large_cap=2`.

**Verified facts from machines.json:**

- All 86 M273 machines (parent + 85 variants named `M273$WheelSelector$*`) share codeSummaryMd5 = `c2a4e3be71b798a8...` AND configSummaryMd5 = `070d2f9ee1c256dd...`. This is Pattern B from 02:§6 — all variants share the same (cfg, code) pair as the parent. 85/85 variants confirmed identical.
- Each variant has a distinct upstream_key (e.g., `M273$0$`, `M273$1$1-2-3`, etc.) and distinct machine id. No storage collision.

#### Which 2 cells go first?

M273 family is `trigger_session` (Type-2), tier 1. Queue positions: `1*10000 + 0..343`. The first items by queue_position within this tier are ordered by "Mode 1 first, then 2, 5, 7" (per §3 step 5). The M273 parent (machine=M273, mode=1) likely gets the lowest within-tier position among M273 cells. The first variant (M273$WheelSelector$0$, mode=1) gets the next. So the first 2 pending cells are M273 mode 1 and M273$WheelSelector$0$ mode 1.

#### Who picks them?

With sweep_concurrency=3 workers, subject to the atomic claim issue below: W1 picks M273 mode 1, W2 picks M273$WheelSelector$0$ mode 1.

#### Binary-group sema acquisition:

W1: `binary_group_semas['c2a4e3be'].acquire()` -> slot 1 taken.
W2: `binary_group_semas['c2a4e3be'].acquire()` -> slot 2 taken.
W3: `binary_group_semas['c2a4e3be'].acquire()` -> **blocked** (cap=2 full).

W3 cannot pick a different item while blocked at step 2 of the per-item loop. W3 waits until W1 or W2 finishes. When one releases, W3 acquires and picks the next pending M273 item.

#### Who picks the next when one finishes?

When W1 finishes M273 mode 1 and releases the sema, W3 unblocks. W3 then does `SELECT WHERE status='pending' ORDER BY queue_position ASC LIMIT 1` — this returns M273$WheelSelector$1$1-2-3 mode 1 (next in tier-1 queue). W3 acquires the sema slot just released by W1.

#### Does the semaphore release/acquire correctly across worker threads?

The sema is `threading.Semaphore` in-memory within the AutoInspectManager instance. The `finally` block in the per-item flow releases it. Threading semaphores are thread-safe. Release/acquire protocol is correct as described.

#### Could the cap deadlock with a non-M273 cell competing for the same global ConcurrencyLimiter slot?

Acquisition order: `binary_group_sema -> SAMPLING_lock -> limiter`. For deadlock, need: W1 holds sema + waits for limiter; W2 holds limiter + waits for sema. But W2 cannot hold a limiter slot while waiting for sema — W2 must acquire sema BEFORE limiter (per the specified order). Therefore **no deadlock is possible**. The ordering prevents circular wait.

#### What about the global ConcurrencyLimiter competition?

With sweep_concurrency=3 and background slot count=3 (n_slots=5, foreground_reserve=2), the sweep saturates all background slots. If FleetRefreshManager is also running, it tries `limiter.acquire("background")` and blocks. This is acknowledged in OQ-E but not resolved.

**What the proposal handles cleanly:**

- Binary-group sema keyed by codeSummaryMd5 correctly groups all 86 M273 machines.
- Deadlock impossibility verified: acquisition order prevents circular wait.
- Cap=2 correctly limits concurrent M273 cells to 2 at once.
- Release in `finally` block prevents lock leak.

**Gaps:**

- **S4-G1 (bug):** No atomic claim mechanism. With 3 workers all doing `SELECT WHERE status='pending' ORDER BY queue_position ASC LIMIT 1` concurrently, all 3 workers can select the same item (the one with the lowest queue_position). The item's status remains `pending` in the DB until step 7 (after sema + SAMPLING lock acquired). Workers W2 and W3 both pick the same item as W1:
  - W2 acquires sema (if a slot is available), then tries `try_acquire_cell(SAMPLING)` for the same cell W1 already holds -> False -> enters yield-and-retry loop (30 min). Burns one sema slot and one worker thread on a cell that is already being processed.
  - This wastes sweep capacity proportionally to `sweep_concurrency - 1` whenever multiple workers simultaneously pick the same item.
  - The SAMPLING lock (INV-4) prevents actual duplicate runs, but the wasted worker threads and sema slots reduce effective throughput.

**Concrete suggestion:** Add an atomic claim step between steps 1 and 2 of the per-item flow. Pattern: within a single DB transaction, `UPDATE auto_inspect_items SET status='claimed' WHERE status='pending' AND sweep_id=X ORDER BY queue_position LIMIT 1; SELECT machine, mode, cell_class FROM auto_inspect_items WHERE status='claimed' AND sweep_id=X AND machine=? AND mode=?`. A Python-level mutex around this select+update is simpler than SQL atomics and consistent with the existing threading model. The `claimed` status reverts to `pending` on cancel; on crash recovery, `claimed` resets to `pending` alongside `running`.

**Verdict: APPROVED-WITH-REVISIONS** — gap S4-G1 is a correctness bug requiring design fix.

---

### Scenario 5 — md5 drift mid-sweep

**Setup:** Sweep completes M14 mode 1 at T=30min. At T=60min upstream pushes new M14 binary (codeSummaryMd5 changes). Sweep is still running other cells.

**Verified M14 identity:** M14 codeSummaryMd5 = `f7a4cefda016a028...`, configSummaryMd5 = `4fcf00c48b3d6979...` (from machines.json). M14 is in the 45-machine f7a4cefd standard large group.

#### Does the sweep detect the md5 change?

§5i specifies: "Check happens at the start of each item's sampling step, before RunManager.start_run. Detected when `_get_machine_md5(machine, mc, mode)` returns a different value than what was snapshotted at sweep-start time (stored in settings_snapshot_json)."

**Gap: `settings_snapshot_json` stores the wrong data.**

From the `auto_inspect_sweeps` schema (§4): `settings_snapshot_json TEXT — snapshot of auto_sweep settings at sweep start`. The `auto_sweep` settings block contains `chunk_spin_times`, `chunk_robot_count`, `target_halfwidth_pp`, etc. — not per-machine md5 values.

The `auto_inspect_items` schema has no columns for `cfg_md5_at_enqueue` or `code_md5_at_enqueue`. There is no place in the schema to store the per-machine md5 values recorded at scan time for later comparison.

Two implementation paths exist:
- **In-memory dict:** Manager keeps `{(machine, mode): (cfg_md5, code_md5)}` from scan time. Lost on restart; drift that occurred before restart is undetectable after resume. This works for the common case.
- **Per-item columns:** `auto_inspect_items` gains `cfg_md5_at_enqueue TEXT` and `code_md5_at_enqueue TEXT`. Survives restart. Drift is detectable across crashes.

The proposal implies the in-memory approach but cites `settings_snapshot_json` as the storage location, which is wrong.

#### What happens to M14 mode 1's completed item?

M14 mode 1 reached `status='completed'` at T=30min. It will not be re-checked for drift (workers only process pending items). It is included in the generate phase's `completed_items` list.

At generate time (after ALL sampling completes), `batch_gen_mgr.start([M14 mode 1, ...])` runs. The worker calls `_get_machine_md5(M14, mc, 1)` via `patch_summary_md5` — at this point machines.json has the NEW code_md5. The rawdata chunks in `rawdata/M14/mode_1/` carry the OLD code_md5 in their envelopes. `patch_summary_md5` has rule C4: "fill if empty, never overwrite." If the analyzer wrote old md5 into the summary, it stays. The generated report carries old rawdata md5. `_build_machines_summary` reads this report and marks `md5_status='outdated'`. The next sweep call re-samples M14 mode 1. This is acceptable two-sweep correction behavior.

#### Does the next sweep auto-detect and re-queue M14 mode 1?

Yes. On the next `start_sweep`, `_get_machine_md5(M14, mc, 1)` returns the new code_md5. `_build_machines_summary` returns `md5_status='outdated'` for the existing M14 mode 1 report. `needs_sample=True`. M14 mode 1 is enqueued.

**What the proposal handles cleanly:**

- §5i: pending items at the time of drift get `status='md5_mid_sweep_drift'`, not re-sampled. Correct.
- Terminal reason string is specific and operator-readable.
- Next sweep re-evaluates drifted cells automatically.

**Gaps:**

- **S5-G1 (inconsistency):** `settings_snapshot_json` is cited as the storage for per-machine md5 values at sweep start. This column stores auto_sweep settings, not machine md5 values. The `auto_inspect_items` schema has no md5 columns for the sweep-start values. The implementation cannot use `settings_snapshot_json` for this purpose as described.
- **S5-G2 (acceptable):** Completed-before-drift items generate reports with old rawdata. The generate phase at end-of-sweep uses machines.json's new md5. The report gets old rawdata but potentially a new md5 stamp (depends on patch_summary_md5 timing). `_build_machines_summary` catches this as outdated. Next sweep corrects it. This is the expected two-sweep lag for mid-sweep drift.

**Concrete suggestions:**
- S5-G1: Replace the `settings_snapshot_json` reference in §5i with either: (a) "in-memory dict keyed by `(machine, mode)` initialized at scan time" (simplest, lost on restart) or (b) "per-item columns `cfg_md5_at_enqueue` and `code_md5_at_enqueue` added to `auto_inspect_items`" (survives restart). Choose one and update the schema accordingly.

**Verdict: APPROVED-WITH-REVISIONS** — S5-G1 is a schema inconsistency that blocks implementation.

---

### Scenario 6 — Operator does manual work during sweep

**Setup:** Sweep is running. Operator opens 数据分析 tab and triggers manual generate-report on M99 mode 2.

**M99 identity:** M99 is `bcm_hard` (Tier 1, ST=97+ST=98 dedup bug). Per §5c, M99 gets `status='structural_skip'` at scan time. No sampling run is started for M99 mode 2.

**Two sub-cases:**

**Sub-case A: Sweep has M99 mode 2 as structural_skip (the designed behavior).**

M99 is in the `bcm_hard` roster. At scan time, all M99 cells get `structural_skip`. No SAMPLING lock is held on M99 mode 2. No rawdata is written. The operator triggers `POST /api/rawdata/M99/generate-report?mode=2` (single-item endpoint).

`_prepare_batch_gen_item` -> `try_acquire_cell("M99", 2, GENERATING)`. No SAMPLING lock is active (sweep skipped M99). No GENERATING lock active. Acquire succeeds. The generate-report runs against existing rawdata (if any exists from a previous manual run). This works normally. The sweep has no interaction with M99 mode 2.

**Sub-case B (hypothetical): If M99 were NOT structural_skip (e.g., a different machine).**

If the sweep were actively SAMPLING M99 mode 2 and the operator triggers single-item generate:

`_prepare_batch_gen_item` -> `try_acquire_cell("M99", 2, GENERATING, block_if_sampling_active=True)`. The registry sees SAMPLING active on (M99, 2) (held by the sweep's worker). `block_if_sampling_active=True` -> returns False. `_prepare_batch_gen_item` raises HTTPException(409). The operator gets a 409.

**What the 409 message says:**

The CellLockRegistry's `try_acquire_cell` returns `False` when blocked. The 409 is raised by `_prepare_batch_gen_item` (app.py:~9538). The error message is generated by `_prepare_batch_gen_item` — likely something like "M99 mode 2 is currently being sampled." The proposal's §4 `_is_cell_owned_by_active_queue` extension is for RunManager A2 (orphan recovery), NOT for the generate-report 409. The 409 message does not have access to the sweep context and cannot say "being sampled by auto-inspect sweep ai_abc123."

**Who wins the cell lock?**

The sweep (holding SAMPLING). The operator's generate request is rejected with 409. The sweep does NOT yield to the manual action (§5g yield-and-retry only applies when the SWEEP is waiting for a manually-held lock, not the reverse).

**Sweep yielding to manual operator action (§5g):**

§5g applies when the SWEEP tries to SAMPLE a cell that the OPERATOR is already sampling (manually). The 30-min yield-and-retry is the sweep waiting for the operator's run to finish. The scenario in the brief is the reverse: operator trying to GENERATE while sweep is SAMPLING. This gets a 409 to the operator, not a yield.

**What the proposal handles cleanly:**

- CellLockRegistry INV-3 + `block_if_sampling_active=True` correctly enforces mutual exclusion.
- §5g handles the correct direction (sweep yields to manual SAMPLING).
- The A2/R1 extension (§4) correctly identifies sweep-owned cells to prevent orphan spawning.

**Gaps:**

- **S6-G1 (awkward):** The 409 message for single-item generate conflicts does not tell the operator that the auto-inspect sweep is the sampling owner. The operator sees "cell is being sampled" without context. If the operator is not aware a sweep is running, they may be confused. The sweep ownership is identifiable via the 自动巡检 tab's status panel, but there is no cross-tab UX link from the 409 to the sweep status.

**Concrete suggestion:** The 409 body from `_prepare_batch_gen_item` should include owner context. The `_is_cell_owned_by_active_queue` function (extended per §4) can provide this: when it returns `{"kind": "auto_inspect", "sweep_id": "ai_abc123"}`, the 409 body can carry "被自动巡检 ai_abc123 占用". This requires passing the owner info to the generate-report 409 response, not just using it for A2 orphan recovery.

**Verdict: APPROVED** — design correctly handles the conflict. S6-G1 is a UX improvement, not a correctness failure.

---

## Cross-Scenario Themes

**Theme 1: Multi-worker item dispatch needs claim semantics (S4-G1, touches S1/S3).**

The FleetRefreshManager is serial (one thread). BatchRunManager pre-assigns items to threads at start time. AutoInspectManager's proposed model (N workers, each picking the next pending item) is a third pattern that neither existing manager uses. Without an atomic claim step, multiple workers select the same item. The SAMPLING registry invariant prevents duplicate runs but wastes worker threads. The designer must specify the claim mechanism for the multi-worker model. This is the only correctness bug found.

**Theme 2: The f7a4cefd standard large group (45 machines including M14) is incorrectly classified as a high-risk binary group (S1-C1, touches S5).**

The `>= 20 machines` threshold for `binary_group_large_cap=2` applies to f7a4cefd (45 machines with DISTINCT configs — Pattern A per 02:§6) the same as M273 (86 machines with IDENTICAL configs — Pattern B). The self-DoS risk is fundamentally different between these groups: M273 has 86 variants all hitting the same game binary with the same config parameters; f7a4cefd has 45 machines with completely different config parameters sharing only the code binary. Capping f7a4cefd to 2 reduces easy-tier sweep throughput by 33% without corresponding DoS protection benefit.

**Theme 3: Storage references are ambiguous for in-memory vs persisted state (S5-G1, touches S3).**

The proposal describes two pieces of state as "stored in settings_snapshot_json" (per-machine md5 values at scan time) and "self._pending_resume_sweep_id" (in AutoInspectManager). Neither is fully specified. The schema is internally inconsistent on the first point. The second point is correctly modeled after FleetRefresh but the attribute name does not appear in the public interface.

**Theme 4: Resume semantics are split between §2 (manual) and §4 (automatic), contradicting each other (S3-G2).**

The FleetRefresh analogue is fully automatic. The proposal describes both a create_app auto-spawn (§4) and an operator Resume button (§2). For an "always-on intranet server" with no overnight monitoring, automatic resume is the correct behavior. The button is useful as a recovery confirmation indicator but should not be the only trigger.

**Theme 5: Structural skip is a static list requiring code deployment to change (S2-G1).**

Moving the `bcm_hard` roster to a config file decouples analyzer fix deployments from sweep behavior changes.

---

## What I Did NOT Walk

1. **M274 regression tripwire threshold calibration (OQ-A):** The proposal says "alert if RTP differs > 2 pp from baseline." I did not exercise this check against actual M274 data. The 2 pp threshold calibration requires empirical M274 RTP data, which is in `reports/M274/mode_1/latest.json` and was not read for this validation.

2. **Cron scheduler (Phase 5):** OQ-G (stdlib cron parsing) was not walked. This is an implementation decision for Phase 5, not an architecture gap.

3. **M278/M280/M281 uncharted BCM convergence behavior (OQ-D):** These three machines have no sweep history. I confirmed they are classified as `bcm_uncharted` in the proposal and processed in tier 2. Whether they actually converge within max_chunks cannot be determined without a real run.

4. **All 9 failure modes in isolation:** I traced structural_skip (§5c), convergence_timeout (§5b via max_chunks stop_reason), and md5_mid_sweep_drift (§5i). I did not walk network_error (§5a), consecutive_chunk_failure (§5e), whole_fleet_abort (§5f), or wall_time_exceeded (§5d) as end-to-end traces.

5. **Frontend tab implementation details (Phase 4):** I did not verify `fInt`/`fRate`/`fmtMult` formatter reuse, i18n key collisions, or the paginated drill-down table implementation.

6. **M99 structural_skip correctness in context of sub-round dedup bug:** The open ST=97+ST=98 dedup bug for M99 means the sweep correctly skips it, but if the bug is ever fixed, the bcm_hard roster update (S2-G1) applies here too.

---

## Summary of Issues Found

| ID | Severity | Scenario | Issue |
|---|---|---|---|
| S4-G1 | BUG | Scenario 4 | Multi-worker item selection has no atomic claim step; multiple workers can pick the same item, wasting sema slots and worker threads in 30-min yield loops |
| S5-G1 | SCHEMA INCONSISTENCY | Scenario 5 | `settings_snapshot_json` cited as storage for per-machine md5 snapshot values, but that column stores auto_sweep settings; `auto_inspect_items` schema has no md5 columns; implementation is impossible as written |
| S3-G1 | INTERFACE GAP | Scenario 3 | `resume_sweep(sweep_id)` needed by `create_app` wiring path is not in the public interface (§1) |
| S3-G2 | AMBIGUITY | Scenario 3 | §4 implies auto-resume on startup; §2 implies operator-click Resume button is required; one must be authoritative |
| S1-C1 | DESIGN CONCERN | Scenario 1 (cross-cutting) | f7a4cefd 45-machine standard large group (easy tier, M1/M2/M14/M13...) gets `binary_group_large_cap=2` same as M273, despite having distinct configs; reduces easy-tier sweep throughput by 33% with no corresponding DoS benefit |
| S2-G1 | MAINTENANCE | Scenario 2 | bcm_hard machine roster is hardcoded; removing M250/M268/M260/M264 from structural_skip when BCM anchor fix ships requires a code deployment |
| S1-G1 | UX GAP (OQ-B) | Scenario 1 | Generate phase runs after ALL sampling completes; on fresh 1,688-cell deploy operators see no reports for ~50-74 hours; OQ-B is unresolved |
| S6-G1 | UX IMPROVEMENT | Scenario 6 | 409 message from generate-report conflict does not identify sweep as the sampling owner; operator cannot distinguish sweep-vs-manual conflict without navigating to 自动巡检 tab |

**Required fixes before implementation (block approval):** S4-G1, S5-G1, S3-G1.
**Required designer clarification (does not block Phase 1 but must be resolved before Phase 2):** S3-G2.
**Optional improvements:** S1-C1 (recommend), S2-G1 (recommend), S1-G1 (resolve OQ-B), S6-G1 (nice-to-have).
