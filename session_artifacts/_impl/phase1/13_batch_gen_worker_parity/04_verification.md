# Verification: P1-D1 — _batch_gen_worker.py parity with _run_generate_report

## Verdict: PARTIAL

4/4 contracts applied and verified. Subprocess e2e PASS. One test-isolation regression found in test_batch_worker_post_hook.py: the _reset_worker_globals fixture in that file does NOT reset the 3 new P1-D1 globals (_patch_summary_md5_fn, _run_post_inference_fn, _lookup_machine_md5_fn). The tester updated test assertions to match new format, but the cross-file isolation gap means 3 tests fail when run after the parity file in the full backend suite.

---

## Pytest results - 3 critical test files

Command:
  python -m pytest tests/backend/test_batch_gen_worker_parity.py tests/backend/test_classify_chunks_historical_consumers.py tests/backend/test_batch_worker_post_hook.py -v

Result when run as group:
  test_batch_gen_worker_parity.py:                 23 passed
  test_classify_chunks_historical_consumers.py:    16 passed, 1 xfailed
  test_batch_worker_post_hook.py:                  3 FAILED (cross-file contamination), 5 passed when run alone

Note on 3 failures in test_batch_worker_post_hook.py:
  Cross-file test isolation problem. The _reset_worker_globals fixture in that file (lines 30-39) saves/restores only _analyzer_mod and _project_root -- NOT the 3 new P1-D1 globals. Tests from the parity file set these globals; post_hook tests see non-None globals, changing runtime behavior and breaking assertions.

  When run alone: python -m pytest tests/backend/test_batch_worker_post_hook.py
  Result: 5 passed, 0 failed. (CONFIRMED)

  Required action (tester round 2): Update _reset_worker_globals in test_batch_worker_post_hook.py to also save/restore _patch_summary_md5_fn, _run_post_inference_fn, _lookup_machine_md5_fn using the same getattr/setattr pattern already in test_batch_gen_worker_parity.py.

---

## End-to-end checks

### C1 - Job dict includes md5 filter keys
7 tests PASS. M14/M1/M99 parametrized, virtual machine modesMd5 schema, value-match from registry.
test_classify_chunks: xfail strict=True removed, now PASS (C5 first test).
VERDICT: PASS

Reproducer:
  python -m pytest tests/backend/test_batch_gen_worker_parity.py::TestJobDictIncludesMd5FilterKeys -v
  Result: 7 passed

### C2 - Worker forwards md5 args to analyzer CLI argv
Subprocess e2e argv capture against real worker:
  --upstream-config-md5 present: YES
  value: 4fcf00c48b3d6979aef058fed9ed5f94
  matches job dict: True
  --upstream-code-md5 present: YES
  value: 536fc5a2a8f2ecf1fd8c6dfcf2c025cc
  matches job dict: True
  Positions in argv: [32]='--upstream-config-md5' [33]=value [34]='--upstream-code-md5' [35]=value

Fix B confirmed: historical files remain on disk (md5-is-tag per memory feedback_md5_is_a_tag_not_a_destruction_signal.md).
VERDICT: PASS

### C3 - Worker calls patch_summary_md5 after analyzer
Subprocess e2e against M14/mode_1 (6 real cached production chunks):
  Worker result ok=True, elapsed_s=0.88
  summary config_md5: 4fcf00c48b3d6979aef058fed9ed5f94 (non-empty: True)
  summary code_md5: 536fc5a2a8f2ecf1fd8c6dfcf2c025cc (non-empty: True)
md5 round-trip: empty -> patched -> matches registry -> no-overwrite when pre-populated.
VERDICT: PASS

### C4 - Worker calls run_post_analyzer_inference after analyzer
Subprocess e2e with SLOT_SKIP_AUTO_INFER=1:
  post_hook entries: 1
  entry: {"canonical_post_inference": true, "machine": "M14", "mode": 1, "skip": "env_SLOT_SKIP_AUTO_INFER"}
VERDICT: PASS

### C5 - xfail markers
  test_batch_job_dict_includes_md5_filter_keys: xfail removed, NOW PASS. PASS.
  test_batch_job_chunk_dir_does_not_contain_historical_chunks: strict=True -> strict=False, remains XFAIL.
  Brief says remove both markers but Fix B does not physically clean chunk_dir. Architecturally defensible per
  md5-is-tag invariant and brief S4 (out-of-scope). ACCEPTABLE.

### C6 - Worker pool resource-snapshot safety
  Before _pool_worker_init:
    _patch_summary_md5_fn is None: True
    _run_post_inference_fn is None: True
    _lookup_machine_md5_fn is None: True
  After _pool_worker_init:
    _patch_summary_md5_fn is not None: True (is patch_summary_md5: True)
    _run_post_inference_fn is not None: True (is run_post_analyzer_inference: True)
    _lookup_machine_md5_fn is not None: True (is lookup_machine_md5: True)
    _project_root == project_root: True
VERDICT: PASS

---

## Fix B vs Fix A architectural choice

Fix B (CLI filter flags --upstream-config-md5 / --upstream-code-md5) chosen over Fix A (physical dir cleanup).
Per memory feedback_md5_is_a_tag_not_a_destruction_signal.md: md5 is a tag not a destruction signal.
Physical deletion violates this invariant. Fix B enforces historical-chunk exclusion at the analyzer CLI level.
Fix A was not in brief S4 scope.

---

## Md5 round-trip verification (per memory feedback_md5_granularity_and_stamping.md)

M14 md5 from registry: cfg=4fcf00c48b3d6979aef058fed9ed5f94, code=536fc5a2a8f2ecf1fd8c6dfcf2c025cc
Before patch:  config_md5='', code_md5=''
After patch:   config_md5='4fcf00c48...' code_md5='536fc5a2...'
Round-trip match: True
No-overwrite when populated: True
VERDICT: PASS

---

## Full pytest regression

Command: python -m pytest tests/backend/ -q
Result: 7 failed, 2437 passed, 23 skipped, 1 xfailed

Failure analysis:

1. tests/backend/test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split
   Pre-existing: YES. Missing M31 rawdata fixture (FileNotFoundError). Not P1-D1 responsible.

2. tests/backend/test_lookup_machine_md5_canonical.py - M37, M279 (2 tests)
   Pre-existing: YES. Pinned md5 values stale (configs/machines.json updated before P1-D1). Not P1-D1 responsible.

3. tests/backend/test_t_critical_table_canonical.py - C1/C6 (3 tests)
   Pre-existing: YES. Test-isolation order issue in full suite; all 3 pass when run alone or with full tests/backend/ deselecting other files. Not P1-D1 responsible.
   Confirmed: ran same tests against HEAD before P1-D1 changes -- same 3 failures.

4. tests/backend/test_batch_worker_post_hook.py - 3 tests
   Pre-existing: NO. Cross-file state contamination from parity tests setting _patch_summary_md5_fn etc. and _reset_worker_globals not cleaning them up.
   Tester action required (round 2).

---

## Subprocess verification

YES - ran real _pool_worker_init + run_analyzer_job against M14/mode_1 (6 real production chunks).
All 3 fixes observed:
  C2: CLI argv contains --upstream-config-md5 / --upstream-code-md5 with correct values
  C3: summary file has populated config_md5 / code_md5 after run
  C4: canonical post_hook entry present with skip marker

---

## Frontend verification

N/A - no frontend changes in this ticket.

---

## Open issues requiring tester round 2

1. Update _reset_worker_globals fixture in test_batch_worker_post_hook.py (lines 30-39) to save/restore
   _patch_summary_md5_fn, _run_post_inference_fn, _lookup_machine_md5_fn.
   Without this, 3 tests fail in the full suite due to cross-file state contamination from parity tests.
   The fix is identical to the pattern in test_batch_gen_worker_parity.py _reset_worker_globals (lines 79-118).

---

## Stop reasons for PARTIAL

1. 3 tests in test_batch_worker_post_hook.py fail in the full suite (cross-file isolation regression from
   incomplete _reset_worker_globals fixture). Tester action required.
2. Brief C5 exact wording: remove both xfail markers. Second marker changed to strict=False instead of
   removed. Architecturally defensible but technically deviates from brief exact wording.
