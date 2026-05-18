# P1-D1 — `_batch_gen_worker.py` parity — Test Report

---

## Round 2 update — 2026-05-18

### Verdict change: sufficient (for post_hook contract)

The 3 pre-existing tests in `tests/backend/test_batch_worker_post_hook.py` that
were FAILING against the implementer's stashed P1-D1 code have been updated to
match the new canonical `InferenceResult` serialisation format. All 5 tests in
that file now pass; all 3 updated tests are inject-bug verified.

### What changed (old → new format)

Old format (pre-P1-D1):
```python
post_hook = [
    {"context": {"script_root": ..., "project_root": ..., "rawdata_root": ..., "sys_executable": ...}},
    {"hook": "paytable_shape", "skip": "script_missing", "path": ...},
    {"hook": "classifier",     "skip": "script_missing", "path": ...},
]
```

New format (P1-D1 canonical InferenceResult serialisation):
```python
post_hook = [{
    "canonical_post_inference": True,
    "machine": "M1",
    "mode": 7,
    "failed": True,            # set when any script rc != 0 or error
    "paytable_shape": {"ok": False, "rc": None, "stderr_tail": "", "error": "script_missing", "wall_time_seconds": 0.0},
    "classifier":     {"ok": False, "rc": None, "stderr_tail": "", "error": "script_missing", "wall_time_seconds": 0.0},
}]
```
For skipped (env var): `{"canonical_post_inference": True, "machine": ..., "mode": ..., "skip": "env_SLOT_SKIP_AUTO_INFER"}`.
No separate `{"context": {...}}` entry exists.

### 3 tests updated

| Test | Old assertion | New assertion |
|---|---|---|
| `test_post_hook_records_script_missing` | `{"context": ...}` present; `{"skip": "script_missing"}` × 2 | `entry["failed"] is True`; `entry["paytable_shape"]["error"] == "script_missing"`; `entry["classifier"]["error"] == "script_missing"` |
| `test_post_hook_context_includes_anchoring_info` | `ctx["project_root"]`, `ctx["script_root"]`, `ctx["rawdata_root"]`, `ctx["sys_executable"]` | `entry["machine"] == job["machine"]`; `entry["mode"] == job["mode"]`; `entry["paytable_shape"]["error"] == "script_missing"` (proves _project_root used for path resolution) |
| `test_post_hook_handles_missing_chunk_dir` | `{"skip": "chunk_dir_missing"}` present | `result["ok"] is True` (no crash); `entry["canonical_post_inference"] is True`; `entry.get("skip") != "chunk_dir_missing"` (old signal gone); `entry["paytable_shape"]["ok"] is False` |

### Behavior change for test 3 (missing chunk_dir)

The old impl had an explicit `chunk_dir_missing` guard (worker lines 161-165 pre-D1).
The new canonical helper has no such guard: when `chunk_dir` is absent,
`rawdata_root` is set to `None` (worker line 240), which causes the helper to bypass
Guard 2 and attempt the scripts. Since the test's `_project_root` has no `scripts/`
subtree, both scripts hit `error="script_missing"`. The observable invariant —
"missing chunk_dir must not crash the worker" — is preserved. The diagnostic signal
changed from `chunk_dir_missing` to `script_missing`.

### Inject-bug verification log (round 2)

**Test 1: `test_post_hook_records_script_missing`**

Inject: comment out `if infer_result.failed: hook_entry["failed"] = True` (worker line 280-281).
Result: `AssertionError: expected failed=True when both scripts missing`
Restore: test GREEN.

**Test 2: `test_post_hook_context_includes_anchoring_info`**

Inject: change `"machine": infer_result.machine` to `"machine": "WRONG_MACHINE"` (worker line 273).
Result: `AssertionError: machine mismatch in hook entry: {'machine': 'WRONG_MACHINE', ...}; assert 'WRONG_MACHINE' == 'M1'`
Restore: test GREEN.

**Test 3: `test_post_hook_handles_missing_chunk_dir`**

Inject: comment out the `for s in infer_result.scripts: hook_entry[s.name] = {...}` loop (worker lines 282-289).
Result: `AssertionError: expected paytable_shape sub-entry when chunk_dir is missing, got {'canonical_post_inference': True, 'machine': 'M1', 'mode': 7, 'failed': True}`
Restore: test GREEN.

---

## Round 1 verdict (preserved below)

## Verdict: partial

All 23 tests in `test_batch_gen_worker_parity.py` pass against the implementer's
current code. Inject-bug verified 15/15 for the three main fix contracts (C1/C2/C3).

C5 is partially satisfied: one of the two xfail markers was removed (first test now
PASS); the second was changed from `strict=True` to `strict=False` rather than
removed — this is an impl-tester flag for the critic (see C5 gap below).

Three pre-existing tests in `test_batch_worker_post_hook.py` are now FAILING due
to the implementer's post_hook format change. This is a critic flag, not a tester
responsibility.

---

## Test files

| File | Tests added | Status |
|---|---|---|
| `tests/backend/test_batch_gen_worker_parity.py` | 23 (new) | 23/23 GREEN |
| `tests/backend/test_classify_chunks_historical_consumers.py` | 0 (modified: 1 xfail removed, 1 xfail kept `strict=False`) | 16 PASS, 1 XFAIL |

---

## Coverage map — brief contracts to tests

### C1 — Job dict includes md5 filter keys

| Brief assertion | Test |
|---|---|
| `upstream_config_md5` key present in job | `TestJobDictIncludesMd5FilterKeys::test_job_dict_has_upstream_config_md5` |
| `upstream_code_md5` key present in job | `TestJobDictIncludesMd5FilterKeys::test_job_dict_has_upstream_code_md5` |
| Values come from machine registry (not hardcoded) | `TestJobDictIncludesMd5FilterKeys::test_job_dict_md5_values_match_machine_lookup` |
| Virtual machine modesMd5 per-mode path | `TestJobDictIncludesMd5FilterKeys::test_job_dict_md5_keys_virtual_machine` |
| Parametrized M14/M1/M99 coverage | `TestJobDictIncludesMd5FilterKeys::test_job_dict_md5_parametrized[...]` (3 rows) |

### C2 — Worker forwards md5 args to analyzer CLI argv

| Brief assertion | Test |
|---|---|
| `--upstream-config-md5` in argv | `TestWorkerForwardsMd5ArgsToAnalyzerArgv::test_argv_contains_upstream_config_md5_flag` |
| `--upstream-code-md5` in argv | `TestWorkerForwardsMd5ArgsToAnalyzerArgv::test_argv_contains_upstream_code_md5_flag` |
| CLI values match job dict exactly | `TestWorkerForwardsMd5ArgsToAnalyzerArgv::test_argv_md5_values_match_job_dict` |
| Missing keys graceful fallback (no crash) | `TestWorkerForwardsMd5ArgsToAnalyzerArgv::test_missing_md5_keys_in_job_does_not_crash_worker` |

### C3 — Worker calls patch_summary_md5 after analyzer

| Brief assertion | Test |
|---|---|
| config_md5 populated after worker run | `TestWorkerCallsPatchSummaryMd5::test_summary_config_md5_populated_after_worker_run` |
| code_md5 populated after worker run | `TestWorkerCallsPatchSummaryMd5::test_summary_code_md5_populated_after_worker_run` |
| `_patch_summary_md5_fn` called once | `TestWorkerCallsPatchSummaryMd5::test_patch_summary_md5_called_with_correct_lookup` |
| No-overwrite when already populated (C4 of patch helper) | `TestWorkerCallsPatchSummaryMd5::test_md5_not_overwritten_when_already_populated` |

### C4 — Worker calls run_post_analyzer_inference after analyzer

| Brief assertion | Test |
|---|---|
| result dict has `post_hook` key | `TestWorkerCallsRunPostAnalyzerInference::test_result_has_post_hook_key` |
| post_hook is non-empty list | `TestWorkerCallsRunPostAnalyzerInference::test_post_hook_is_non_empty` |
| SLOT_SKIP_AUTO_INFER=1 records skip marker | `TestWorkerCallsRunPostAnalyzerInference::test_skip_env_var_triggers_skip_marker` |
| Inference fires after analyzer (ordering) | `TestWorkerCallsRunPostAnalyzerInference::test_inference_called_after_analyzer_not_before` |

### C5 — xfail markers removed

| Test | Before | After |
|---|---|---|
| `TestBatchPathHistoricalFilterGap::test_batch_job_dict_includes_md5_filter_keys` | `@pytest.mark.xfail(strict=True)` | No marker — PASS (C1 fix landed) |
| `TestBatchPathHistoricalFilterGap::test_batch_job_chunk_dir_does_not_contain_historical_chunks` | `@pytest.mark.xfail(strict=True)` | `@pytest.mark.xfail(strict=False)` — still XFAIL |

GAP: The second test was changed from `strict=True` to `strict=False`, not fully removed.
The brief says "REMOVE xfail markers on the 2 TestBatchPathHistoricalFilterGap tests."
Implementer's rationale: Fix B (CLI md5 filter) was chosen over Fix A (physical dir cleanup),
so the physical-dir-cleanliness assertion still genuinely fails. This is a design decision
that the critic must validate — if Fix B satisfies the brief's C2 contract (historical
chunks not reaching the analyzer), the second test's xfail is acceptable. The first test's
strict-True xfail was correctly removed.

### C6 — Worker pool resource-snapshot safety

| Brief assertion | Test |
|---|---|
| md5 lookup reads from job dict, not live global | `TestWorkerPoolResourceSnapshotSafety::test_machines_config_read_from_job_dict_not_module_global` |
| New helper imports have zero import-time side effects | `TestWorkerPoolResourceSnapshotSafety::test_new_md5_imports_do_not_have_module_level_side_effects` |
| `_project_root` not mutated by job calls | `TestWorkerPoolResourceSnapshotSafety::test_worker_globals_are_isolated_across_job_calls` |

### C1+C2 integration (end-to-end in-process chain)

| Brief assertion | Test |
|---|---|
| prepare_fn job dict keys → run_analyzer_job argv | `TestJobDictToArgvEndToEnd::test_prepare_fn_md5_keys_appear_in_analyzer_argv` |

---

## Inject-bug verification log

The inject-bug experiment used `git stash` of the implementer's changes to restore
pre-fix base code, then ran `pytest`. This is equivalent to "reverting the target line"
for all contracts simultaneously since the bugs are in the code the implementer added.

### Pre-fix RED (15 tests):
```
FAILED TestJobDictIncludesMd5FilterKeys::test_job_dict_has_upstream_config_md5
FAILED TestJobDictIncludesMd5FilterKeys::test_job_dict_has_upstream_code_md5
FAILED TestJobDictIncludesMd5FilterKeys::test_job_dict_md5_values_match_machine_lookup
FAILED TestJobDictIncludesMd5FilterKeys::test_job_dict_md5_keys_virtual_machine
FAILED TestJobDictIncludesMd5FilterKeys::test_job_dict_md5_parametrized[M14-1-...]
FAILED TestJobDictIncludesMd5FilterKeys::test_job_dict_md5_parametrized[M1-7-...]
FAILED TestJobDictIncludesMd5FilterKeys::test_job_dict_md5_parametrized[M99-2-...]
FAILED TestWorkerForwardsMd5ArgsToAnalyzerArgv::test_argv_contains_upstream_config_md5_flag
FAILED TestWorkerForwardsMd5ArgsToAnalyzerArgv::test_argv_contains_upstream_code_md5_flag
FAILED TestWorkerForwardsMd5ArgsToAnalyzerArgv::test_argv_md5_values_match_job_dict
FAILED TestWorkerCallsPatchSummaryMd5::test_summary_config_md5_populated_after_worker_run
FAILED TestWorkerCallsPatchSummaryMd5::test_summary_code_md5_populated_after_worker_run
FAILED TestWorkerCallsPatchSummaryMd5::test_patch_summary_md5_called_with_correct_lookup
FAILED TestWorkerPoolResourceSnapshotSafety::test_machines_config_read_from_job_dict_not_module_global
FAILED TestJobDictToArgvEndToEnd::test_prepare_fn_md5_keys_appear_in_analyzer_argv
```

**What caused each RED:**
- C1 (7 tests): `_prepare_batch_gen_item` job dict has no `upstream_config_md5` / `upstream_code_md5` keys
- C2 (3 tests): `run_analyzer_job` argv list has no `--upstream-config-md5` / `--upstream-code-md5` flags
- C3 (3 tests): `_patch_summary_md5_fn` module global does not exist / is None; summary md5 fields stay empty
- C6a (1 test): same as C3 — no patch_summary_md5 → config_md5 stays empty
- C1+C2 chain (1 test): job dict missing upstream_* keys → assert fails before reaching argv test

### Post-fix GREEN (23/23 pass after `git stash pop`):
All 23 tests pass against implementer's code.

### C4 inject-bug note:
C4 tests (post_hook existence / SLOT_SKIP_AUTO_INFER skip marker) pass on BOTH pre-fix
and post-fix code because the post_hook mechanism existed before P1-D1. The new P1-D1
contribution is using the canonical `run_post_analyzer_inference` helper rather than
inline subprocess code. The C4 tests validate the observable contracts (hook runs,
skip marker appears, key present) which are satisfied by both implementations.

A more targeted C4 inject-bug would be: set `worker._run_post_inference_fn = None`
and assert the result contains a "not_initialized" skip marker. This IS tested indirectly
by `test_post_hook_is_non_empty` (the skip marker still appears via the else branch
in the new code).

---

## Pre-existing regression found during testing

**File**: `tests/backend/test_batch_worker_post_hook.py`
**3 tests now FAIL on implementer's code:**
- `test_post_hook_records_script_missing`
- `test_post_hook_context_includes_anchoring_info`
- `test_post_hook_handles_missing_chunk_dir`

**Root cause**: Implementer changed post_hook format from old `[{context: {...}}, {hook: "paytable_shape", skip: "script_missing", ...}]` list to new canonical `InferenceResult` serialized as `[{canonical_post_inference: True, machine: ..., failed: True, paytable_shape: {ok, rc, ...}}]`.

The old tests look for `{"context": ...}` and `{"skip": "script_missing"}` entries which no longer exist in the new format.

**Flag for critic**: These 3 test failures are NOT caused by the tester's new tests. They
are a regression introduced by the implementer changing the hook's output format without
updating the corresponding tests. The critic should require the implementer to either:
(a) update `test_batch_worker_post_hook.py` to match the new canonical format, or
(b) preserve backward compatibility of the post_hook entry shape.

---

## Subprocess vs in-process coverage

All 23 tests are in-process (no real subprocess spawning). This is correct per the
brief's test scope: the contracts under test (job dict keys, argv construction,
patch_summary_md5 call, post_hook key presence) are all Python-layer logic in the
worker module. The e2e subprocess verification (real worker pool against M14 fixture)
is delegated to impl-verifier per brief §7 Wave 2.

The argv-capture tests (C2) validate that the CLI flags reach the analyzer module's
`main()` entry point via `sys.argv` — which is the exact contract, since the worker
uses `sys.argv = argv; _analyzer_mod.main()` (in-process simulation of subprocess argv).

---

## Open gaps

1. **C5 second xfail**: `test_batch_job_chunk_dir_does_not_contain_historical_chunks` is
   still `xfail(strict=False)`. Brief said to remove both xfail markers. Blocked by
   implementer choosing Fix B over Fix A. Critic to validate.

2. **C4 canonical helper wiring**: C4 tests confirm the post_hook contract (key exists,
   skip marker fires) but do not specifically verify the `canonical_post_inference: True`
   marker introduced by the implementer's new format. This is by design — the brief's C4
   contract is behavioral, not format-specific.

3. **C6 split-path depth**: The split-path test (C6a) demonstrates that when
   `_project_root` points at a wrong directory, the md5 values still come from the
   job dict's `machines_config`. A deeper test would verify that `_lookup_machine_md5_fn`
   (the pre-snapped function) is used rather than a live re-import at job time. The
   current `test_patch_summary_md5_called_with_correct_lookup` covers this via mock
   substitution of the module global.

4. **Subprocess e2e**: Verifier owns M14/M1sim real batch run to confirm summary md5
   populated + inference output appears + no historical chunks in analyzer input.
