# Ticket P1-D1 — `_batch_gen_worker.py` parity with `_run_generate_report`

> Phase 1 follow-up. Closes the 3 known gaps surfaced by P1-A4, P1-B2, P1-B5 critics. The worker is currently a leaner driver than the in-process equivalent; this ticket brings it to parity.

---

## §1 Ticket scope

Apply 3 consolidated fixes to `src/web_console/backend/_batch_gen_worker.py` + `src/web_console/backend/app.py:_prepare_batch_gen_item` so that batch-generated reports produce the SAME summary as `_run_generate_report` (within `--from-cache` vs `--resume-from-cache` semantics).

Files expected to change:
- `src/web_console/backend/app.py:_prepare_batch_gen_item:7136+` — add `upstream_config_md5` + `upstream_code_md5` keys to job dict
- `src/web_console/backend/_batch_gen_worker.py` — (a) forward md5 args as `--upstream-config-md5` / `--upstream-code-md5` CLI flags; (b) call `patch_summary_md5(summary_file, lookup_fn=...)` after analyzer returns; (c) call `run_post_analyzer_inference(...)` after analyzer returns
- `tests/backend/test_classify_chunks_historical_consumers.py` — REMOVE `xfail` marker on the 2 P1-A4 R2 tests (`test_batch_job_dict_includes_md5_filter_keys` + `test_batch_job_chunk_dir_does_not_contain_historical_chunks`); they should NOW pass
- `tests/backend/test_batch_gen_worker_parity.py` (new) — regression tests for all 3 fixes

---

## §2 Brief sections cited

- `session_artifacts/_impl/phase1/PHASE_1_TICKETS.md` "Known Follow-ups" §3 rows 2-4 (consolidated gap)
- Memory `feedback_enumerate_safety_paths.md` — every callsite must be migrated
- Memory `feedback_md5_granularity_and_stamping.md` — per-mode md5 stamping discipline
- Memory `feedback_perf_claim_needs_e2e_event_stream.md` — subprocess-mode verification mandatory
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` — worker pool initializer pattern
- Existing test `tests/backend/test_batch_worker_post_hook.py` — pattern reference for post-hook test discipline

---

## §3 Contract (testable invariants)

### C1 — Job dict includes md5 filter keys
`_prepare_batch_gen_item(machine, mode)` returns a dict containing both `upstream_config_md5` and `upstream_code_md5` keys (values from canonical `lookup_machine_md5(machine)` per P1-B1; for virtual machines via `compute_machine_md5_for_mode`). Verifiable: existing `test_batch_job_dict_includes_md5_filter_keys` (P1-A4 xfail) flips to PASS without xfail marker.

### C2 — Worker forwards md5 args to analyzer
`_batch_gen_worker.py:run_analyzer_job` builds CLI argv including `--upstream-config-md5 <cfg>` and `--upstream-code-md5 <code>` from `job["upstream_config_md5"]` / `job["upstream_code_md5"]`. Analyzer subprocess receives them and filters chunks to current-md5 only.

### C3 — Worker calls `patch_summary_md5` after analyzer
After `analyzer.main()` writes `player_impact_summary.json`, worker calls `patch_summary_md5(summary_file, lookup_fn=lambda: lookup_machine_md5(machine, machines_config_path))`. Virtual machines' summary md5 fields now populated correctly (not `md5_status=untagged`).

### C4 — Worker calls `run_post_analyzer_inference` after analyzer
After `patch_summary_md5`, worker calls `run_post_analyzer_inference(summary_path, paytables_dir, classify_dir, opts)` per the canonical P1-B5 helper. Best-effort post-hook; failures land in `_post_inference_failure.json` per memory `feedback_no_silent_swallow.md`.

### C5 — P1-A4 xfail tests flip to PASS
`tests/backend/test_classify_chunks_historical_consumers.py::TestBatchPathHistoricalFilterGap`:
- `test_batch_job_dict_includes_md5_filter_keys` — was xfail strict=True; now PASS without marker
- `test_batch_job_chunk_dir_does_not_contain_historical_chunks` — was xfail strict=True; now PASS without marker

Per memory `feedback_adversarial_self_review.md`: removing xfail marker is the CORRECT action when the underlying bug is fixed. `strict=True` ensured this transition is explicit (XPASS would fail the test if we forgot to remove the marker).

### C6 — Worker pool resource-snapshot safety
Per memory `feedback_subprocess_import_suicide_and_module_globals.md`: any module-global resources the worker needs (sys.path, cwd, env) must be snapshot at worker-pool `initializer=` time (existing pattern at `_batch_gen_worker.py:38+`). New md5/inference imports inherit the same pattern; no live-global reads from job-level code.

### C7 — Inject-bug TDD
For each fix:
- C1 inject: remove keys from job dict → assert test_batch_job_dict_includes_md5_filter_keys goes red
- C2 inject: remove `--upstream-*-md5` from CLI argv build → assert analyzer reads historical chunks
- C3 inject: remove `patch_summary_md5` call → assert virtual-machine batch summary has empty md5
- C4 inject: remove `run_post_analyzer_inference` call → assert no inference output appears
Document each in `03_tests.md`.

---

## §4 Out of scope

- Refactoring `_batch_gen_worker.py` beyond these 3 fixes
- Changing `BatchGenerateManager` orchestration logic
- Adding new analyzer CLI flags (only forwarding existing `--upstream-*-md5` per analyzer spec)
- Schema changes to `_post_hook.json` (kept compat with existing format per P1-B5)

---

## §5 Rollback path

Single commit. `git revert <sha>` restores pre-fix state. xfail markers stay removed (they'd be RED again — that's the regression net).

---

## §6 Risk + rollback notes

**Risk class**: MEDIUM-HIGH. Worker pool + subprocess + md5 stamping + post-inference compose 3 features in one fix. Per memory `feedback_perf_claim_needs_e2e_event_stream.md`: e2e subprocess verification mandatory.

**Subprocess-mode**: worker pool runs in separate processes. Module imports happen at `initializer=`. Verifier MUST spawn real worker pool against M14 or M1sim cached fixture and verify all 3 fixes land.

**Coordination with P1-B6 hallucination**: per memory + my session experience, trust-but-verify implementer's pytest claims. Run pytest myself before commit.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — 3 fixes per §3 C1-C4
- `impl-tester` — `tests/backend/test_batch_gen_worker_parity.py` per §3 contracts; ALSO remove xfail markers in `test_classify_chunks_historical_consumers.py` per C5

### Wave 2 (parallel)
- `impl-verifier` — e2e subprocess M14/M1sim batch run; assert summary md5 populated + inference output appears; assert no historical chunks in analyzer input
- `impl-critic` — adversarial review; check for new silent swallows; verify all 3 P1-A4/B2/B5 follow-up entries can be CLOSED

Expected wall time: ~60-90 min (largest single ticket since P1-B6).
