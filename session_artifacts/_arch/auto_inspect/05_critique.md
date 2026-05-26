# Auto-Inspect Architecture Critique
> Wave 3 — Adversarial Critic output
> Date: 2026-05-26
> Source reviewed: `04_architecture_proposal.md`
> Wave 1 inputs: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`

---

## Verdict: APPROVE-WITH-REVISIONS

The Option C decision is sound and the failure-mode taxonomy is genuinely careful work. However, seven issues — four of which touch correctness in production — must be resolved before implementation begins. The proposal is implementable after the required revisions; it is not in a reject state.

---

## Must-fix issues

### MF-1 (BLOCKING): The `_restore_on_startup` scanning-re-run creates a correctness hole when the sweep crashes mid-scan

**The proposal says (§4 Restart recovery):** "The `scanning` phase is NOT resumed — it is re-run from scratch on resume. This is safe because scanning is read-only (no side effects). Items that were already `completed` before the crash remain `completed`."

**What the proposal misses:** The claim that scanning is "read-only" is only true if the crash happens before the sweep has written any `auto_inspect_items` rows. If the console crashes mid-scan — after writing, say, 400 of 1,688 item rows but before writing the rest — the re-scan will regenerate all 1,688 item rows from scratch. This means the 400 items that were previously written (and may already have `status='completed'` if some ran before the crash) will be re-evaluated for inclusion. Because `CREATE TABLE IF NOT EXISTS` + INSERT OR REPLACE semantics on `PRIMARY KEY (sweep_id, machine, mode)` means those 400 already-completed rows survive, the re-scan is harmless in normal operation.

The actual problem is different: the re-scan calls `_do_refresh_machines_md5()` synchronously. On restart, this is a blocking upstream HTTP call before the app has finished startup. If the upstream endpoint is unreachable (which is exactly the scenario that causes a long-running console restart), the 30-second timeout blocks `create_app` for 30 seconds before the resumed sweep can start. The proposal says the refresh is called "in the sweep manager's `__init__`" via `_restore_on_startup`, but then `create_app` spawns the resume thread after — the timing of the synchronous md5 call relative to `create_app`'s startup sequence is not specified and could block the HTTP server from starting.

**Designer's likely answer:** "The md5 refresh has `raise_on_error=False` so it can't crash the restart, and 30s is acceptable startup latency."

**Why that's insufficient:** The HTTP server (FastAPI/uvicorn) starts its socket listener inside `create_app` after the manager construction. If `_restore_on_startup` calls a synchronous 30-second HTTP request during `create_app`, the server is not accepting requests for those 30 seconds. On Windows (the deployment target), a 30-second black window during restart is not "acceptable latency" — it prevents the operator from even checking the console. The fix is to run the md5 refresh asynchronously in the resume thread, not in `_restore_on_startup`.

---

### MF-2 (BLOCKING): `BatchGenerateManager.get` returns in-memory only; `batch_gen_mgr.start()` is not pollable after restart

**The proposal says (§3 Work dispatch — generate phase):** "Poll `batch_gen_mgr.get_status(batch_id)` every 10s until terminal."

**What the proposal misses:** The method on `BatchGenerateManager` is `get(batch_id)`, not `get_status(batch_id)` (app.py:3962). More importantly, `get()` returns in-memory only: if the console restarts during the generate phase, the `_batches` in-memory dict is repopulated from SQLite (`_restore_persisted`, app.py:3879) — but `_restore_persisted` marks non-terminal generate batches as `cancelled`, NOT as `running`. After restart, `batch_gen_mgr.get(batch_id)` returns the generate batch as `cancelled`, not `running`. The sweep's resume logic (§4) resets sampling items from `running` to `pending` but there is NO corresponding reset of the generate phase. The sweep resumes sampling, completes sampling again, then calls `batch_gen_mgr.start()` a second time with the same items — generating duplicate reports.

**Designer's likely answer:** "The sweep detects that generate was already done by checking `auto_inspect_items.generate_run_id` is non-null."

**Why that's insufficient:** The proposal (§3) says generate phase is triggered AFTER all sampling items drain. If `generate_run_id` is non-null for some items and null for others (partial generate failure), the sweep would need to re-issue generate for only the null-`generate_run_id` items. This filtering logic is not described anywhere in §3, §4, or §7 Phase 3. The current proposal simply calls `batch_gen_mgr.start(items_with_rawdata)` with no check. The restart recovery path for the generate phase is a gap.

---

### MF-3 (HIGH): `sweep_concurrency=3` with `ConcurrencyLimiter` background slots=3 creates a zero-slot starvation, not a "saturation"

**The proposal says (§6 Defaults):** "`sweep_concurrency=3`. Matches `ConcurrencyLimiter` background slot count (n_slots=5, foreground_reserve=2 → 3 background). Setting to 3 ensures the sweep can saturate background capacity without starving foreground ops."

**And then in OQ-E (§9):** "With `sweep_concurrency=3` and `ConcurrencyLimiter` having 3 background slots, the sweep saturates all background slots — leaving zero capacity for FleetRefreshManager to make progress if both run simultaneously."

The proposal calls this "saturation" while also acknowledging it leaves zero slots for FleetRefreshManager. The proposal treats this as an open question (OQ-E) but simultaneously ships the default as 3. This is not an open question — it is a correctness issue with the chosen default.

**The real problem is worse than OQ-E acknowledges:** The `ConcurrencyLimiter` background slots are shared with `BatchGenerateManager`'s generate phase if the sweep uses `batch_gen_mgr.start()` directly. But per 01:§5, `BatchGenerateManager` uses a `ProcessPoolExecutor` and does NOT go through the `ConcurrencyLimiter` at all ("BatchGenerateManager uses a ProcessPoolExecutor instead of going through the limiter directly"). So the 3 background slots are shared between only AutoInspectManager (sampling) and FleetRefreshManager (sampling). If sweep=3 and FleetRefresh=1, total background demand is 4 > 3 available. FleetRefreshManager's single background acquire blocks indefinitely waiting for a slot. Proposal OQ-E acknowledges this but does NOT treat it as a blocker. It is a blocker because the default setting (`sweep_concurrency=3`) ships broken behavior.

**Designer's likely answer:** "OQ-E defers this to the validator. The operator can tune `sweep_concurrency` to 2."

**Why that's insufficient:** A default that silently starves an existing system component is a correctness issue, not a tuning issue. The default must be safe. The proposal must either (a) set the default to 2, (b) add a 409 guard that prevents both sweep and FleetRefresh from running simultaneously, or (c) reserve a background slot for FleetRefresh. All three are valid but one must be chosen before implementation.

---

### MF-4 (HIGH): M272 and M120 have no special handling in the sweep, but their scan-time classification is wrong

**The proposal's cell classification (§3, Cell discovery logic, step 4):**

The five `cell_class` values are: `easy`, `trigger_session`, `bcm_hard`, `bcm_moderate`, `bcm_uncharted`.

**What is missing:** Per 02:§7 Tier 2, M272 has paid spin type=140 (not 1). M120 has jackpot pay-id 666 attribution requiring special handling. Neither machine falls into any of the five cell_class values in the proposal. They would be classified as `easy` — because they are non-variant standalone machines with no BCM class in `logicClassNames` and are not in the Tier-1 hard roster.

M272 classified as `easy` means the sweep runs it with standard parameters and generates a report. That report uses the default paid_spin_type=1 manifest. Per 09 §3 Tier 2: "Paid spin type is 140, not 1. Bootstrap default is wrong for this machine." This means the sweep's report for M272 will have the wrong paid-round denominator — the same structural error that manifests as a 09-architecture as-built line item. M120 similarly will produce a report where pay-id 666 is misattributed.

**Designer's likely answer:** "M272 and M120 have manifests (written in the Phase 3 implementation, 09:§2) that override paid_spin_type. The sweep just calls the analyzer with standard params; the manifest handles the rest."

**Why this needs verification:** The proposal never explicitly states that manifest overrides are in effect during sweep-initiated sampling runs. Per 01:§7 pipeline, `RunManager.start_run` calls the analyzer subprocess with a fixed CLI argument set. The manifest is loaded inside `player_impact_analyzer.py:main()` — but only if the manifest loader has been wired into the analyzer path. Whether `auto_inspect_manager`'s `RunManager.start_run` calls pass the correct machine name to activate manifest-based paid_spin_type is not confirmed anywhere in the proposal. The proposal has zero mention of manifest loading in its sweep flow. This is a silent assumption that needs explicit confirmation in the design.

---

### MF-5 (HIGH): The consecutive-failure counter is global across all cells, but the easy-first ordering means hard cases are last — the counter will be wrong almost every time

**The proposal says (§5, failure mode e):** "The sweep tracks `consecutive_failure_count` globally (across all cells, not per-cell). When `consecutive_failure_count >= max_consecutive_failures` (default 3), stop launching new items."

**The problem:** With easy-first ordering (tier 0=easy, 3=bcm_hard), the hard cases are processed last. If all M250/M260/M264/M268 cells are classified `structural_skip` (no sampling attempted, no failure counted), then by the time the sweep reaches M99 (which has an open dedup bug and may produce a failed run), the consecutive failure counter may fire if M99's 4 cells all fail in sequence. But M99's 4 cells failing is *expected* — the failure is structural. The consecutive-failure counter conflates "network/infra down" (a real emergency) with "expected hard-case failure" (not an emergency). The default of 3 consecutive failures is dangerously low when the last 28 cells in the queue (Tier-1 hard) are expected to have high failure rates.

**Designer's likely answer:** "M250/M260/M264/M268 are `structural_skip` so they don't generate runs and don't fail. M99 will fail and could trip the counter."

**Why that's insufficient:** The designer's own §5(c) says "For M250/M260/M264/M268: give up immediately with `structural_skip`" — these don't trigger run failures. But M279 is NOT structural_skip (proposal says "M279 is also NOT structural_skip — it converges with enough spins"). If M279's 4 cells all produce `convergence_timeout` (which is a non-`failed` terminal status), that's fine. But if M279's sampling subprocess exits non-zero for some mode (a plausible BCM edge case), that IS a `failed` status — and M279 has 4 cells. 4 consecutive failures from M279 with `max_consecutive_failures=3` aborts the sweep. Meanwhile, M279 is at the END of the queue, so easy cells have already completed. But the abort at M279 would leave M99, M274, and M278/M280/M281 unprocessed. Since M274 is the regression tripwire, it would silently not run.

The counter needs to exclude expected failure classes OR use a window-based approach (e.g., "3 consecutive failures in the last 10 attempts") rather than a monotonic global counter. This design gap is not flagged anywhere in the OQs.

---

## Should-fix issues

### SF-1 (MEDIUM): The generate phase is a single global batch, not per-cell — this creates an 8-to-17-hour report blackout window

**The proposal says (OQ-B):** "The proposal sequences generate AFTER all sampling items drain. This means no report is generated until the entire sampling sweep is done."

The proposal correctly identifies this in OQ-B but marks it as "the validator should assess." At the fleet scale described (17.5 hours wall time per the question brief's estimate), "no new reports until the sweep is done" means the operator sees zero new reports for the first 8 hours of the sweep. This is a user-experience design choice that has product consequences, not merely a technical one. The proposal defers it entirely to W3 without providing a preferred direction or tradeoff analysis.

The gap: the proposal also doesn't define what happens to the generate-batch if it contains 1,680+ items. `BatchGenerateManager` uses a `ProcessPoolExecutor` with `max_workers=SLOT_BATCH_GEN_WORKERS` (default 4, env-configurable). Submitting 1,688 items to a pool of 4 workers at once creates a very large futures backlog. The `as_completed` loop in BatchGenerateManager will work correctly, but the memory overhead of 1,688 prepared-job dicts held in `prepared[]` (app.py:4000 phase A) before any are submitted to the pool — each containing a full job spec — is not discussed.

**Suggested direction for designer:** State explicitly whether per-cell-immediate generation is acceptable complexity. The current design could be trivially modified to call generate after each sampling completion if sweep_concurrency=1 for that cell; the global-batch approach is only simpler when not interleaving.

---

### SF-2 (MEDIUM): The `_LARGE_GROUP_CAP=2` applies to any group with >= 20 machines, which includes the 45-machine "standard large group" (f7a4cefd) — but these are low-risk

**The proposal says (§3 Per-codeSummaryMd5 concurrency cap):** "If a binary group has >= 20 machines sharing it (current threshold: M273 with 86, standard-large with 45), assign `cap = _LARGE_GROUP_CAP`."

Per 02:§8, the 45-machine standard large group "has 45 distinct game configs even though they share a binary. These are independent machines and concurrent sampling is lower risk than M273's 86-machine single-config group." Yet the proposal assigns the same `_LARGE_GROUP_CAP=2` to both. This is explicitly identified as lower risk in the taxonomy. Capping the 45-machine group to 2 concurrent means those 180 easy cells (which should be the fastest part of the sweep) are rate-limited as severely as the high-risk M273 family. At 2 concurrent and ~5 min/cell, those 180 cells alone take 450 minutes = 7.5 hours, even though they are the easiest cells in the fleet.

The taxonomy (02:§8) explicitly called these "Moderate" risk vs M273's "High." The proposal collapses them into the same cap, which contradicts the taxonomy's own risk tiering.

**The proposal's numbers are also internally inconsistent:** §6 says `binary_group_large_cap=2`, §3 says `_LARGE_GROUP_CAP=2` for groups >= 20 machines. But the settings key is `binary_group_large_cap` (a single value) while the threshold (>= 20) is hardcoded — there is no `binary_group_moderate_cap` for groups in the 8-45 range. The 8-machine M123 and M201 families get the default `_BINARY_GROUP_DEFAULT_CAP=4`, the 45-machine group and the 86-machine group both get 2. This coarseness is not justified by the taxonomy.

---

### SF-3 (MEDIUM): The "easy-first" claim and the resume correctness claim depend on each other in a way that breaks under a specific failure mode

**The proposal says (§4 Restart recovery):** "Sweep resumes from the next `pending` item in queue_position order. Completed items are not re-processed."

**The problem:** If the sweep crashes at hour 7 of an 8-hour run with 95% of easy cells complete, the resume re-runs the scanning phase from scratch. The scanning phase re-evaluates ALL 1,688 cells against the current md5 state. Between the crash and the restart, if an upstream push landed (md5 changed), some cells that were previously classified as `needs_sample=True` may now be... still `needs_sample=True` (fine), but some previously `completed` cells may now appear `needs_sample=True` again (their md5 is now outdated). The proposal says "Items that were already `completed` before the crash remain `completed`" — but that's only true if the sweep doesn't re-evaluate those cells. The scanning phase re-runs for ALL cells, not just the pending ones. The already-completed cells have `status='completed'` in the DB and are not re-enqueued. But the scan itself takes time (1,688 cells × `check_rawdata_status` calls) and holds a lock equivalent during that window. 

The proposal says scanning is safe because it's "read-only with no side effects." But 1,688 calls to `check_rawdata_status` is not free — each call hits the filesystem (reading `_chunks.json` sidecars). This could take significant time on a Windows filesystem with 1,688 mode directories. The phase plan has no timing estimate for the scan phase.

---

### SF-4 (MEDIUM): The "yield-and-retry" loop for SAMPLING lock conflict has an undetected category: operator sweep vs operator sweep

**The proposal says (§5, failure mode g):** Trigger: `registry.try_acquire_cell(SAMPLING)` returns False AND `elapsed > CELL_BUSY_TIMEOUT_S` (default 1800s = 30 minutes).

**The gap:** The proposal models cell-lock conflict as "operator manual sampling vs. sweep." But the 409 guard on `POST /api/auto-inspect/start` (implied by "Returns sweep_id. 409 if already running") only blocks a second sweep, not a second operator batch. If an operator starts a manual `POST /api/batch-run` for M14 mode 1 AND the sweep is running and the sweep hasn't reached M14 yet AND then the operator's batch completes AND then the sweep reaches M14 — the sweep tries to acquire SAMPLING for M14 mode 1. At this point, M14 mode 1 is free (operator batch finished), so the sweep acquires it normally. This is the happy path.

The unhappy path the proposal misses: **what happens when the sweep has acquired SAMPLING for M14 mode 1 and the operator clicks batch-run for M14 mode 1 via the UI?** BatchRunManager's D12 logic (app.py:4879) runs: it checks `get_active_sampling_info` for M14 mode 1. The sweep's sampling info has `upstream_md5` = current md5. The operator's batch request also has current md5 (presumably). D12 logic: if same config → `attached` status (returns existing run_id). The operator's batch row for M14 mode 1 shows `status='attached'` — this is correct and documented behavior. But the operator gets no clear indication that their manual batch is "riding" a sweep-initiated run, not a fresh one. Worse: the sweep's per-item timing and the BatchRunManager's item timing are now mixed — the sweep considers M14 done when `RunManager._watch_run` completes, and BatchRunManager's `_wait_for_run` will also complete at the same time. Both managers release their locks. No correctness issue, but the interaction is undocumented and could confuse the operator.

---

### SF-5 (LOW): The cron scheduler uses "Python stdlib datetime arithmetic" but no cron parser exists in stdlib

**The proposal says (§9 OQ-G):** "Standard Python has no cron parser in stdlib. Options: (a) restrict to `HH:MM` daily or `*/N hours`; (b) add a dependency on `croniter`."

This is correctly flagged in OQ-G but the proposal has already committed to "a lightweight `threading.Timer`-based scheduler that reads `auto_sweep.schedule_cron`, parses it" (§7 Phase 5) as a deliverable. The UI already shows `schedule_cron` as a string field. If the format is not defined before Phase 4 ships the UI, the operator will enter a cron string that the backend cannot parse. The OQ marks this as "the critic should decide the scope" — which is exactly what a critic will refuse to do. The designer must choose the format before Phase 4 ships the UI.

---

## Designer-raised OQs revisited

**OQ-A (M274 regression tripwire threshold: 2 pp):** NOT acceptable as deferred. The 2 pp threshold is compared against `achieved_halfwidth_pp` in the proposal (§7 Phase 5: "compare `achieved_halfwidth_pp` against the stored baseline"). But `achieved_halfwidth_pp` is a CI half-width, not an RTP point. Comparing a CI half-width to "2 pp from baseline RTP" conflates two different statistical quantities. The proposal's Phase 5 text says "If RTP differs by > 2 pp from baseline" — but the field it actually has available is `achieved_halfwidth_pp` (a precision metric, not an RTP metric). The RTP value is `achieved_rtp_pct` in the `runs` table. The alert must compare RTP, not CI. This is a correctness gap the designer must fix. Verdict: **Designer must provide concrete fix before approval.**

**OQ-B (Generate phase timing):** Acceptable as deferred to W3, but the proposal must acknowledge the memory consequence of a 1,688-item `prepared[]` list. The sequential-generate model is acceptable in principle if the designer explicitly chooses it. Verdict: **Deferred is acceptable IF designer explicitly chooses sequential and documents the memory bound.**

**OQ-C (skip_fresh_cells CI re-evaluation):** NOT acceptable as deferred. The gap is concrete: if the operator tightens `target_halfwidth_pp` from 0.5 to 0.3 between sweeps, cells with reports at 0.45 pp would appear fresh (md5 matches) but would not meet the new CI threshold. The `needs_sample` predicate as written (`md5_status == 'match' AND ci_halfwidth_pp <= target_halfwidth_pp`) would correctly catch these only if `ci_halfwidth_pp` is re-evaluated against the CURRENT setting at scan time. The proposal does not explicitly state whether `target_halfwidth_pp` in the predicate comes from settings at scan time or from the setting at report-generation time. Since the proposal reads settings at scan time (§3 step 3: "per-mode `target_halfwidth_pp` is read from `auto_sweep.modes[mode].target_halfwidth_pp` in settings"), the predicate is correct — but the proposal should explicitly confirm this is re-read per scan, not cached from the previous sweep. Verdict: **Designer should add one explicit line confirming this, not a full rework.**

**OQ-D (M278/M280/M281 uncharted BCM):** Acceptable as deferred. The proposal puts them in `bcm_uncharted` and processes them with full spin budget. The risk of misleading reports is acknowledged. The designer's note "if these machines turn out to have the same BCM anchor gap as M250/M260/M264/M268, the sweep will run to max_chunks and produce misleading reports" is precisely correct — but the alternative (treating them as `structural_skip`) would generate no report at all, which is worse information for operators trying to classify them. Verdict: **Deferred is acceptable. The `bcm_uncharted` class correctly reflects epistemic state.**

**OQ-E (sweep_concurrency=3 saturating background slots):** NOT acceptable as deferred per MF-3 above. The default ships broken. The designer must choose a safe default and document whether AutoInspectManager and FleetRefreshManager are blocked from coexisting or not. Verdict: **Must be resolved before Phase 1.**

**OQ-F (Per-mode generate filtering):** NOT acceptable as deferred. The scenario is concrete and has a correctness consequence: if the sweep runs mode-1-only, the generate phase must not regenerate mode-2/5/7 reports. The proposal says "The validator should confirm that the `items` list is correctly filtered to only the modes included in this sweep." This is not a validation question — the filtering must be specified in the proposal. The modes in scope are known at scan time (stored in `auto_inspect_sweeps.modes_json`). The generate phase must filter the completed-items list against `modes_json`. Without this specification, Phase 3 implementers will omit the filter, and a mode-1-only sweep will regenerate all 4 modes for every machine that has any rawdata. Verdict: **Designer must add explicit filtering spec to the generate phase description.**

**OQ-G (cron expression parsing):** NOT acceptable as deferred per SF-5 above. The UI ships in Phase 4 with a free-text `schedule_cron` field. The Phase 5 parser must be compatible with what the operator typed in Phase 4. The format must be specified before Phase 4. Verdict: **Designer must choose the format and document it before Phase 4 implementation.**

---

## Strengths

1. **Option C decision is correct for the right reasons.** The rejection of Options A and B is backed by specific, verifiable Wave 1 citations. Option A's inability to express 9 failure modes cleanly (per 01:§2's two terminal states per item) and Option B's single-instance guard (app.py:11621) are both real, confirmed constraints, not speculative ones. The proposal did not pick Option C for architectural elegance — it picked it because the alternatives demonstrably cannot meet the spec.

2. **RISK-4 (A2 double-spawn) is fully addressed.** The `_is_cell_owned_by_active_queue` fourth branch (§4) targets exactly app.py:6085-6141 with the correct JOIN pattern — this is the right fix for the right problem, confirmed against the actual function in source. Identifying this as a 5-line targeted fix rather than a structural rework shows mature scope control.

3. **Per-item terminal status vocabulary is production-quality.** The 9 failure modes each have named terminal status strings, human-readable `terminal_reason` fields, and explicit routing to both the `auto_inspect_items` row and `auto_inspect_events` log. This directly addresses `feedback_invariant_with_fallback_hides_drift.md` and `feedback_no_silent_swallow.md` — the "garbage bucket" anti-pattern is explicitly called out and rejected.

4. **The disk-pressure gap is honestly acknowledged via the BatchRunManager delegation.** The proposal notes that calling `RunManager.start_run` directly (same pattern as `_fleet_batch_item_runner`, app.py:11554) bypasses the disk-pressure loop in `_run_one` (app.py:4920-4960). The proposal does NOT silently inherit that protection. This is an honest gap acknowledgment; the designer could have buried it. Whether it matters in practice depends on disk capacity, but the omission is known and documented, not hidden.

5. **M274 regression tripwire is an excellent addition.** Promoting the BCM baseline machine into an explicit alert mechanism (Phase 5) transforms a passive safeguard into an active one. The concept is architecturally sound and aligns with the `feedback_adversarial_self_review.md` pattern of "verify GREEN != done."

6. **Settings injection is correctly scoped.** The 26 sub-key validation requirement in `_load_settings` (§4 Settings schema) is concrete: range clamping with explicit int/float/bool checks, matching the pattern at app.py:930-958. This is not hand-waved.

7. **Cell-lock yield semantics match FleetRefreshManager's proven pattern.** The 5-second poll with 1800-second timeout before `deferred_lock_conflict` (§3, §5-g) is exactly the pattern at fleet_refresh.py:344-403. Reusing a working pattern rather than inventing a new one is the right call.

---

## Migration risk inventory

### Phase 1 risks

**R1.1 — `_is_cell_owned_by_active_queue` fourth branch added in Phase 1, but the function lives in `RunManager` class which is tested by existing recovery tests.** Adding a fourth SQL branch that queries `auto_inspect_items` (which doesn't exist yet in the schema at time of the branch merge) will raise `sqlite3.OperationalError` on first run. The proposal says this error is "swallowed" (per the existing `except sqlite3.OperationalError: pass` pattern at app.py:6120). This means the fourth branch is safe to add before the tables exist — but the test in §7 Phase 1 ("_is_cell_owned_by_active_queue with sweep-owned cell returns non-None") cannot pass until Phase 1 also creates the tables. The test must be sequenced after table creation in the same phase. This is a test-ordering risk, not a rollback risk.

**R1.2 — `_load_settings` validation for 26 sub-keys is large blast radius.** If any of the 26 new validation blocks has a default-value error (e.g., a wrong type coercion), `_load_settings` silently returns the wrong default for EVERY call. Since `_load_settings` is called on every API request that reads settings, a bug here affects all existing functionality. The test coverage for this must be complete before Phase 1 merges.

### Phase 2 risks

**R2.1 — `start_sweep`'s synchronous md5 refresh (MF-1):** If this runs in the HTTP request handler (not in a background thread), POST /api/auto-inspect/start will block for up to 30 seconds while the refresh runs. The proposal says the refresh is "synchronous" but doesn't specify whether it runs in the request handler or in the sweep daemon thread. If it runs in the handler, it blocks the FastAPI event loop (since FastAPI is ASGI).

**R2.2 — Worker threads picking pending items via SQLite SELECT:** The proposal says N worker threads "pick next pending item (ORDER BY queue_position ASC)" — this is a classic SELECT-then-UPDATE race condition. Two threads can both SELECT the same `pending` item before either has UPDATEd it to `running`. The proposal has no mention of row-level locking or an atomic claim pattern (e.g., `UPDATE ... WHERE status='pending' ORDER BY queue_position LIMIT 1 RETURNING *`). SQLite's WAL mode serializes writers, so the second UPDATE will fail or see no rows — but the proposal doesn't specify how worker threads handle the case where their item was "stolen" between SELECT and UPDATE. This is a standard worker-pool coordination bug.

**R2.3 — Binary-group semaphore dict initialization is pre-sweep, not dynamic:** The `_binary_group_semas` dict is built at `start_sweep` time with semaphores sized by the cells in this sweep's candidate list. If a machine whose codeSummaryMd5 is `c2a4e3be` is NOT in the candidate set (because it's already fresh), no semaphore is created for that md5. If a different sweep is somehow started while this one runs (the 409 guard prevents this — but if two sweeps are running across a restart scenario), the semaphore dict from the old sweep is gone and the new sweep rebuilds it. No correctness risk post-restart since the semaphore is in-memory and restarts rebuild it, but the initialization code must handle the case where `codeSummaryMd5` values in machines.json don't appear in the candidate set.

### Phase 3 risks

**R3.1 — Generate phase restart gap (MF-2):** Already detailed in MF-2. The generate phase has no crash recovery path. If the console restarts during generate, the resume re-runs sampling (potentially duplicating rawdata chunks) and then issues a new generate batch (producing duplicate reports). The risk is real and the proposal does not address it.

**R3.2 — `auto_inspect_events` capped at 500 entries per sweep:** For a 1,688-cell sweep, 500 events is approximately 1 event per 3 cells. Given that each cell produces at least 2 events (`cell_started`, `cell_done`), the cap of 500 will be hit by approximately item 250. After that, events are silently dropped. The proposal says "capped at 500 entries per sweep, same pattern as `events_json` in `batches`" — but `batches` typically have tens of items, not 1,688. The events table will be systematically incomplete for every full-fleet sweep.

### Phase 4 risks

**R4.1 — Per-cell paginated table at 50 rows/page for 1,688 cells = 34 pages:** The proposal says "View all cells" opens a paginated table. At 50 rows/page, a full-fleet sweep has 34 pages. The `GET /api/auto-inspect/status?sweep_id=X&page=N` endpoint is listed in Phase 4 deliverables but the pagination SQL is not specified. If the backend sorts by `queue_position` for pagination (natural sweep order) and the operator is looking for a specific machine, they must scroll through 34 pages. No search/filter spec exists.

**R4.2 — `schedule_cron` field ships as free-text in Phase 4 but the parser is Phase 5:** The operator can type any string in the cron field in Phase 4. If they type a standard 5-field cron expression (e.g., `0 2 * * *`), they will expect it to work when Phase 5 ships. If Phase 5 only implements `HH:MM` format (OQ-G option a), Phase 4-configured cron expressions will silently fail or need a migration. The format must be decided before Phase 4, not after.

### Phase 5 risks

**R5.1 — M274 alert compares the wrong field (OQ-A correctness gap):** Already detailed in MF-4's OQ-A section above. The alert uses `achieved_halfwidth_pp` but must use `achieved_rtp_pct`. No rollback concern — this is a bug in a new Phase 5 feature that would ship wrong on first deploy.

**R5.2 — Cron fires during an existing manual sweep:** The cron scheduler calls `start_sweep(trigger="cron")`. If a manual sweep is running, `start_sweep` returns 409. The cron silently drops the trigger. The next scheduled fire will happen at the next cron interval. This is the correct behavior, but it is not documented in §7 Phase 5. An operator who manually starts a sweep at 1am and has a cron at 2am will not see the cron fire. This could confuse operators who expect "cron = guaranteed sweep."

---

## Edge cases not covered

### EC-1: Mode filter at sweep start vs. modes in machines.json

The proposal says `POST /api/auto-inspect/start` accepts `modes: list[int] | None`. If `modes=None`, the sweep uses modes `[1, 2, 5, 7]`. But every machine in the fleet has exactly 4 modes (per 02:§1 "Every machine in machines.json carries `modes: [1, 2, 5, 7]`"). If a future machine is added with only `modes: [1]`, the sweep's hardcoded `modes=[1,2,5,7]` would attempt to sweep non-existent modes. The proposal does not specify whether the sweep validates requested modes against each machine's `modes` field in machines.json, or assumes all machines always have all 4 modes.

### EC-2: What happens when rawdata_locks.json is missing entirely

The proposal says (§3 Skip conditions): "rawdata_locks.json marks the directory locked → skip." If `rawdata_locks.json` doesn't exist (valid initial state for a fresh deployment), the sweep must treat it as "no locks" and proceed. This is the natural behavior for a JSON-file-based lock system, but it's not stated. If the implementation adds an `open()` call that raises `FileNotFoundError`, every cell would be locked.

### EC-3: The 45-machine standard large binary group is not "M273's problem" — it's a different pattern

Per 02:§8, the 45-machine standard large group (f7a4cefd) has all distinct game configs. The M273 86-machine group has all 86 machines sharing one binary AND most of the type-2 trigger-session mechanic. The proposal's binary-group cap logic lumps both under `_LARGE_GROUP_CAP=2` because "groups >= 20 machines." But the correct risk criterion is not group size — it is "concentration of requests to the same game binary instance on the simulator." The 45-machine group with distinct configs is much lower risk than 86 machines all hitting the same binary's session state. The threshold of >= 20 machines is a proxy for the real criterion, and it over-restricts the 45-machine group.

### EC-4: First-time-load behavior when no reports exist for any cell

The proposal's "needs-sample predicate" (§3 step 3) includes "No report exists for this (machine, mode) at all (absent from `_build_machines_summary` result)" as a `needs_sample=True` trigger. On a fresh deployment with 0 reports, all 1,688 cells would be `needs_sample=True`. The sweep would attempt to sample all 1,688 cells, including the 28 Tier-1 hard cells. The Tier-1 cells would still be classified as `bcm_hard` and `structural_skip` correctly. But the first-run timing estimate changes dramatically: instead of the "342 stale cells" from the Preview example (§2), the first run processes 1,660 easy/moderate cells + 28 hard cells. The wall-time estimate in the user's question brief (17.5 hours) applies only to a partial resweep. A full first-run would be significantly longer, and the proposal has no "first run" communication to the operator.

### EC-5: What does "cancel" mean during the scanning phase

The proposal says cancel is implemented via a cancel flag. The `scanning` phase involves 1,688 calls to `check_rawdata_status` (filesystem reads). If the operator clicks Cancel during scanning, how long does it take to drain? The proposal says "In-flight items run to completion." In the scanning phase, there are no "in-flight items" in the sampling sense — the scan is a single-threaded loop. Is the cancel flag checked per-cell during the scan? The proposal says nothing about cancel responsiveness during scanning. A 1,688-cell filesystem scan loop with no cancel check could take minutes to complete while the UI says "Cancelling...".

### EC-6: Behavior when `_build_machines_summary` cache is warm vs. cold at scan time

Per 03:RISK-2 and the Auditor's note, `_build_machines_summary` returns cached data based on `reports/` mtime fingerprint. If the sweep calls `_build_machines_summary` immediately after a generate batch completes (which writes new `index.json` / `latest.json` files), the fingerprint MAY not have updated yet (file system write lag on Windows). The sweep's scan-time freshness predicate could then use stale report data, incorrectly marking cells as `needs_sample=True` that just had a report generated. This creates a potential duplicate-resample loop. The proposal does not add any explicit cache-invalidation or write-wait logic around the scan's call to `_build_machines_summary`.

### EC-7: The "variant cell class" assignment assumes variants inherit their parent's cell_class

Per the proposal (§3 Cell discovery logic, step 4), the five cell_class values are assigned based on a "hard-case roster" lookup. The proposal cites 02:§7 for the Tier-1 roster and 02:§3 Axis B for trigger-session classification. However, the cell_class assignment code is not specified — only the result values. The question: does a M273$1$1-2-3 variant get classified as `trigger_session` (because M273 is Type-2)? The proposal implies yes ("Type-2 variants inherit the trigger-session classification") but the lookup mechanism is not defined. If implemented naively, the lookup checks `machine` against the hard-case roster — and M273$1$1-2-3 is NOT in any roster, it's a variant. The implementation would classify it as `easy` unless the code explicitly checks whether the machine is a variant and inherits from the parent's classification.

---

## Hidden assumptions

### HA-1: The sweep's 400-line size estimate is for the manager class only

§1 says "approximately 400 lines for the manager class + 80 lines for the SQLite helpers." This does not count:
- Phase 1 changes to `app.py` (settings validation for 26 keys, `_is_cell_owned_by_active_queue` branch, 3 new routes)
- Phase 4 frontend changes (new tab in `index.html`, new JS section in `app.js` — the existing managers' UI sections in `app.js` run hundreds of lines)
- Phase 5 cron scheduler

A realistic estimate is 1,200-1,800 lines of new code including frontend. The "400 lines" framing understates the effort and may affect the implementer's time allocation.

### HA-2: `BatchGenerateManager.start()` can be called by AutoInspectManager directly

The proposal calls `batch_gen_mgr.start(generate_items)` directly from AutoInspectManager. But `batch_gen_mgr` is a local variable in `create_app` that is closed over by route handlers (per 01:§3, "batch_gen_mgr is assigned at app.py:9673 and exposed as a closure captured by the batch-generate-report routes"). The proposal assumes that this object reference is injectable at `AutoInspectManager.__init__` time (§3 Construction shows `batch_gen_mgr=batch_gen_mgr` as a constructor arg). This is valid in Python — references can be passed. But if `BatchGenerateManager` is ever replaced by a different implementation (or constructed lazily), the reference held by `AutoInspectManager` would be stale. The proposal assumes construction order in `create_app` is `BatchGenerateManager` before `AutoInspectManager` — this constraint is not stated.

### HA-3: The upstream simulator is single-process for a given codeSummaryMd5

The binary-group cap rationale (§3) assumes that multiple machines sharing a codeSummaryMd5 all hit "one game binary" on the upstream simulator. This is stated in 02:§8 as a "DoS-self risk pattern" but the actual mechanism is not confirmed: do all 86 M273 variants actually route to the same simulator process? Do they share session state? If the upstream simulator is stateless (each request is independent), the binary-group cap may be unnecessary caution. If it maintains in-memory session state per connected robot, the cap is essential. The proposal treats this as known-true without citing evidence from the upstream sampling API behavior.

### HA-4: `achieved_halfwidth_pp` is available in `summary.json` for all machines

The proposal's convergence check (§5 failure mode b) reads `achieved_halfwidth_pp` from `summary.json`. This field is populated by the analyzer when it computes CI. But per 02:§7, M99 has an open dedup bug that produces structurally wrong results. If M99's analyzer exits with exit code 0 and writes a `summary.json` (which it will if the bug causes double-counting but not a crash), `achieved_halfwidth_pp` may appear to have converged (because the doubled win artificially reduces variance). The CI convergence check would pass for M99 despite the structural error. The proposal has no mechanism to detect this case — M99 would appear as `completed`, not `failed` or `structural_skip`.

### HA-5: The `settings_snapshot_json` stored in `auto_inspect_sweeps` is the correct baseline for md5 mid-sweep drift detection

**The proposal says (§5, failure mode i):** "Detected when `_get_machine_md5(machine, mc, mode)` returns a different value than what was snapshotted at sweep-start time (stored in `settings_snapshot_json`)."

But `settings_snapshot_json` is a snapshot of the `auto_sweep` settings block, not of machine md5 values. The sweep-start md5 snapshot would need to be stored separately — either as a per-machine md5 dict in the sweep row, or by comparing against what was written to `auto_inspect_items` at scan time. The proposal conflates the settings snapshot with the md5 snapshot. The implementation would need a separate structure (e.g., a column `scan_time_config_md5` and `scan_time_code_md5` per item row) to support the drift check. This column does not exist in the proposed `auto_inspect_items` schema (§4).

---

## Comparison to rejected alternatives

### Option A (BatchRunManager wrapper) rejection review

**Rejection rationale cited:** (a) All threads start simultaneously (01:§2); (b) No per-codeSummaryMd5 binary-group cap; (c) Batches mixed with operator batches; (d) Two batch IDs per sweep; (e) Double md5 refresh.

**Verdict on rejection:** JUSTIFIED. The binary-group cap point (b) is the dispositive one — the cap cannot be implemented outside `start_batch` without patching its internals, and 02:§8 calls the M273 concentration risk "High." However, the proposal slightly overstates (a): FleetRefreshManager's serial model ALSO runs one item at a time, and the proposal's Option C sweeps with `sweep_concurrency=3` — not all at once. The "all threads at once" criticism of Option A applies more to its semaphore-only throttle than to its execution model. This doesn't change the verdict, but the framing is slightly misleading.

**What the rejection misses:** Option A would have automatically resolved the generate-phase restart gap (MF-2) since BatchRunManager's own restart recovery (`_restore_persisted_batches`) handles the sampling batch, and a separate `batch_gen_mgr` invocation would be independent. The proposal rejected Option A partly for the generate-phase coupling complexity ("Two batch IDs per sweep with no parent-child link") — but the proposal's own generate phase has the same two-entity problem (sweep row + generate batch) without the link. The rejection avoided one problem and created a structurally similar one.

### Option B (FleetRefreshManager extended) rejection review

**Rejection rationale cited:** (a) Single-instance 409 guard; (b) Serial model requires threading refactor; (c) `_fleet_batch_item_runner` closure parameterization.

**Verdict on rejection:** JUSTIFIED. The 409 guard at app.py:11621 is a confirmed production invariant. The proposal correctly identifies that extending FleetRefreshManager would require modifying a production manager's threading model — a regression surface that touches every existing fleet-refresh user. Option C's "clean isolation" argument holds.

**What the rejection doesn't acknowledge:** Option B's serial model would actually be BETTER for the binary-group cap problem. A serial queue naturally prevents more than one concurrent M273 cell — because FleetRefreshManager processes exactly one item at a time. The cap would be implicit. The proposal rejects Option B partly because it "cannot support the M273 binary-group cap" — but the serial model achieves a cap of 1, which is more conservative than the proposal's cap of 2. The cap argument against Option B is therefore weaker than presented. The threading-refactor argument (to add parallelism to FleetRefreshManager) is the stronger rejection reason and should have been the primary one.

---

## What I did NOT review

1. **Frontend implementation specifics** — the `index.html` tab structure, `app.js` `switchTab` extension, and i18n key reuse were not audited. The proposal's references to `feedback_no_parallel_panel_impl.md` and the existing formatter list are taken at face value.

2. **The Phase 5 M274 alert UI rendering** — whether the warning banner mechanism (implied by "surface it in the UI as a warning banner") reuses existing notification infrastructure or introduces new DOM elements was not checked.

3. **The 421 manifests written in Phase 3 of the prior Wave arch cycle** — the proposal assumes manifests have been shipped for all 422 machines (09:§2 "419 files shipped"). Whether M272's manifest correctly overrides paid_spin_type=140 was not verified by reading the manifest file — this is a runtime dependency the proposal relies on.

4. **Rate-limiter behavior at sustained concurrent background loads** — whether `ConcurrencyLimiter.acquire("background", cancel_flag=...)` is starvation-free when both FleetRefreshManager and AutoInspectManager compete for 3 background slots was not tested by reading `rate_limiter.py`.

5. **SQLite WAL concurrency for 3+ concurrent worker threads** — the proposal runs `sweep_concurrency=3` threads all doing SQLite writes (item status updates). SQLite WAL mode serializes writers but not reads. Whether the write contention at 3 threads creates measurable latency on the poll loop was not evaluated.
