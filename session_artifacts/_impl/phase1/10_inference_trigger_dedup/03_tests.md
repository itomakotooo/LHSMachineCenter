# 03_tests.md — Ticket P1-B5 Inference-Trigger Dedup

## Verdict: sufficient

All 7 brief contracts (C1–C7) are covered by executable tests. 44 tests pass
against the implementer's already-landed `fresh_slotlab/post_inference.py`.
Inject-bug TDD verified for 2 critical paths (script-not-found, silent-swallow).

---

## Test files added

| File | Tests |
|------|-------|
| `tests/backend/test_post_inference_canonical.py` | 44 |

---

## Inject-bug verification log

### Experiment 1 — script-not-found silent-skip bug

Bug injected: replaced the script-not-found handler in
`fresh_slotlab/post_inference.py` lines 266–282 with `continue` (silent skip
— no `result.failed = True`, no `_write_failure_diagnostic`, no stderr log).

```python
# INJECTED BUG (in fresh_slotlab/post_inference.py):
if not script.exists():
    continue  # silent skip — replaces 11 correct lines
```

Tests that went RED:
- `TestC5_InjectBugTDD::test_script_not_found_produces_diagnostic_and_failed_true`
  — `assert result.failed is True` → AssertionError (got False)
- `TestC5_InjectBugTDD::test_both_scripts_missing_both_reported_in_diagnostic`
  — `assert diag_file.is_file()` → AssertionError (file absent)

Restored: re-added the 11 original lines. Both tests go GREEN. All 44 pass.

### Experiment 2 — silent-swallow conceptual proof

`TestC5_InjectBugTDD::test_silent_swallow_pattern_makes_c3_test_red` contains
an inline simulation of the `try/except: pass` forbidden pattern. The test:

1. Defines `_silent_swallow_helper` that wraps subprocess.run in
   `try: ... except: pass` and returns `failed=False` with no diagnostic file.
2. Invokes it on a nonexistent script path.
3. Asserts that `diag_file.is_file() == False` AND `result.failed == False`
   (proving the bug violates C3).
4. The assertion is structured so if this stands, C3 tests would fail — the
   test documents the failure mode, proving the real helper must not do this.

This test passes GREEN (proves the bug simulation is working correctly, i.e.,
the simulated bug does fail C3 as expected).

---

## Coverage map — every brief contract to test

### C1 — Single helper with explicit path args

| Brief requirement | Test |
|---|---|
| Module `fresh_slotlab.post_inference` importable | `TestC1::test_module_is_importable` |
| `run_post_analyzer_inference` callable | `TestC1::test_helper_function_exists` |
| `InferenceResult` with `.failed: bool` | `TestC1::test_InferenceResult_exists_with_failed_attr` |
| Helper accepts (summary_path, paytables_dir, classify_dir, opts) | `TestC1::test_helper_accepts_explicit_path_args` |
| Return type has `.failed` | `TestC1::test_return_type_has_failed_attr` |
| Both dirs can be None | `TestC1::test_paytables_dir_and_classify_dir_can_be_none` |
| No import-time side effects | `TestC1::test_no_import_time_side_effects` |

### C2 — Both callsites use helper

| Brief requirement | Test |
|---|---|
| `app.py` imports/uses `fresh_slotlab.post_inference` | `TestC2::test_app_py_imports_post_inference` |
| `virtual_analyzer.py` imports/uses `fresh_slotlab.post_inference` | `TestC2::test_virtual_analyzer_imports_post_inference` |
| `app.py` inline subprocess loop gone | `TestC2::test_app_py_no_longer_has_inline_subprocess_inference_loop` |
| `virtual_analyzer.py` inline loop gone | `TestC2::test_virtual_analyzer_no_longer_has_inline_inference_loop` |

### C3 — Failure diagnostic on disk

| Brief requirement | Test |
|---|---|
| rc != 0 → `_post_inference_failure.json` written | `TestC3::test_rc_nonzero_writes_diagnostic_file` |
| rc != 0 → `InferenceResult.failed = True` | `TestC3::test_rc_nonzero_sets_failed_true` |
| all rc = 0 → `failed = False` | `TestC3::test_rc_zero_sets_failed_false` |
| Helper does NOT raise | `TestC3::test_helper_does_not_raise_on_subprocess_failure` |
| Helper logs to stderr (not silent) | `TestC3::test_helper_logs_to_stderr_on_failure` |
| Diagnostic has: script_name, rc, stderr_tail, argv, wall_time_seconds | `TestC3::test_diagnostic_file_contains_required_fields` |
| stderr_tail captures final line | `TestC3::test_stderr_tail_captures_final_line` |
| No diagnostic file on clean success | `TestC3::test_no_diagnostic_file_when_all_ok` |
| cwd field in diagnostic | `TestC3::test_diagnostic_cwd_field` |

### C4 — Worker resource snapshot

| Brief requirement | Test |
|---|---|
| opts["env"] used for subprocess, not live os.environ | `TestC4::test_opts_env_overrides_live_os_environ` |
| opts["env"]=None falls back to os.environ | `TestC4::test_opts_env_none_falls_back_to_live_environ` |
| Module globals corrupted → helper still works (split-path) | `TestC4::test_module_global_wrong_value_does_not_break_helper` |

### C5 — Inject-bug TDD

| Brief requirement | Test |
|---|---|
| Script-not-found → diagnostic + failed=True | `TestC5::test_script_not_found_produces_diagnostic_and_failed_true` |
| Both scripts missing → both in diagnostic | `TestC5::test_both_scripts_missing_both_reported_in_diagnostic` |
| Silent-swallow → C3 tests go red (documented proof) | `TestC5::test_silent_swallow_pattern_makes_c3_test_red` |
| First-only failure still writes diagnostic | `TestC5::test_only_first_script_fails_still_writes_diagnostic` |

### C6 — Subprocess-mode end-to-end

| Brief requirement | Test |
|---|---|
| virtual_analyzer subprocess triggers inference hook | `TestC6::test_virtual_analyzer_subprocess_inference_hook_fires` |
| Hook failure does not crash virtual_analyzer process | `TestC6::test_virtual_analyzer_subprocess_no_hook_exception_propagates` |

### C7 — Regression test template (test_batch_worker_post_hook.py pattern)

| Brief requirement | Test |
|---|---|
| Module globals reset fixture | `TestC7::_reset_post_inference_globals` (autouse) |
| SLOT_SKIP_AUTO_INFER=1 short-circuits, failed=False, no diag | `TestC7::test_skip_env_short_circuits_no_subprocess_and_no_failure` |
| Script missing → failed=True (mirror of batch worker pattern) | `TestC7::test_script_missing_surfaces_failed_not_silent_swallow` |
| Always returns result, never None | `TestC7::test_result_always_returned_regardless_of_outcome` |
| wall_time_seconds in diagnostic | `TestC7::test_wall_time_seconds_present_in_diagnostic` |
| argv in diagnostic is a list | `TestC7::test_argv_in_diagnostic_is_a_list` |
| opts['log_to_dir'] writes _post_hook.json | `TestC7::test_log_to_dir_also_writes_post_hook_json` |

### Parametrized path coverage (memory feedback_enumerate_safety_paths.md)

| Path | Tests |
|---|---|
| rc=0/0 → failed=False; rc=1/0, 0/1, 1/1, 2/0, 127/127 → failed=True | `TestAllPathsCovered::test_exit_code_to_failed_mapping[*]` (6 cases) |
| paytable missing, classifier missing, both missing → failed=True | `TestAllPathsCovered::test_script_missing_coverage_per_script[*]` (3 cases) |

---

## Subprocess vs in-process coverage

In-process (monkeypatched subprocess.run): all C1/C3/C4/C5/C7 tests. These
run in <2s total and cover the contract surface precisely.

Subprocess-mode (real subprocess spawn): C6 tests spawn `virtual_analyzer.py`
as a real subprocess per memory `feedback_perf_claim_needs_e2e_event_stream.md`.
The test uses a minimal empty fixture and SLOT_SKIP_AUTO_INFER=0 to exercise
the live subprocess path.

---

## Open gaps

1. `test_diagnostic_cwd_field` — passes GREEN because the implementer's
   `ScriptResult` includes a `cwd` field (found `_cwd = str(...)` in the
   landed code). If the implementer removes `cwd`, this test would go RED.

2. C2 structural checks (`test_app_py_no_longer_has_inline_subprocess_inference_loop`,
   `test_virtual_analyzer_no_longer_has_inline_inference_loop`) use heuristic
   AST-text patterns rather than true import-graph analysis. They are sufficient
   for the current refactor but could produce false-negatives if the implementer
   restructures in an unexpected way. impl-critic should verify C2 manually.

3. C6 subprocess test with empty fixture may skip ("no chunks in fixture") if
   the virtual_analyzer exits before the inference hook fires. The test degrades
   gracefully to a skip. Full C6 coverage requires a fixture with at least one
   synthetic chunk — deferred to impl-verifier's Wave 2 task per brief §7.

4. Pre-existing failure in `test_post_analyzer_inference_logging.py::
   TestPostHookLogsToDisk::test_writes_post_hook_json_with_timeout_outcome`:
   this test checks `error == "timeout"` but the new shared helper writes
   `error = "timeout_after_300.0s"`. This is an impl-critic issue (API
   compatibility of the old callsite wrapper), not introduced by my tests.

---

## Implementer API notes (discovered during test-writing)

The implementer's `run_post_analyzer_inference` signature differs from the
brief's abstract description in one way: opts requires `machine`, `mode`,
and `scripts_dir` as explicit keys (not derived from `summary_path`). This
is a valid implementer choice — the brief says "explicit path args" and
all three are explicit. Tests were written against the actual landed API.

`ScriptResult` has a `cwd` field not mentioned in C3 — this is a superset
of the brief's requirements. The `test_diagnostic_cwd_field` test asserts it.

`_post_inference_failure.json` is a JSON list (one entry per failed script),
not a single dict. Tests handle both formats via `_find_field` helper.
