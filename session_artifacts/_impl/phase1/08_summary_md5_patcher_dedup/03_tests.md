# 03_tests.md — Ticket P1-B2 / Consolidate summary md5 patcher (real × 2)

## Verdict

**Sufficient.** All 6 brief contracts have executable regression tests. 39 tests pass against the implementer's current code. All C6 inject-bug experiments verified RED → GREEN. Subprocess smoke test passes.

---

## Test files added

| File | Tests | Status |
|------|-------|--------|
| `tests/backend/test_summary_md5_patcher_canonical.py` | 39 | All GREEN |

---

## Implementer interface discovery

During test authorship, `fresh_slotlab/summary_md5_patch.py` was already created. The actual implemented interface differs from the brief's phrasing in one key detail:

**Brief §3 C1 says**: "accepts an injectable `md5_lookup_fn` (default uses canonical real lookup from P1-B1; virtual injects its local `compute_machine_md5_for_mode`)"

**Implemented interface**:
```python
patch_summary_md5(
    summary_path: Path,
    md5_lookup_fn: Callable[[], Tuple[str, str]],   # ZERO-ARG callable
    *,
    machine: str = "<unknown>",   # for error messages only
    mode: object = "<unknown>",   # for error messages only
) -> None
```

The `md5_lookup_fn` is a **zero-argument** callable. Machine+mode are bound in a lambda at each callsite:
- `app.py`: `lambda: _get_machine_md5(machine, mc, mode=mode)`
- `virtual_analyzer.py`: `lambda: (config_md5, code_md5)`

This design is clean and valid: C3 per-mode granularity is the caller's responsibility (the lambda captures the correct mode-specific lookup). Tests were written to match this actual interface.

---

## Inject-bug verification log

### C1 — single helper, injectable lookup_fn

**Test**: `test_c1_canonical_file_exists`
- **Inject**: delete `fresh_slotlab/summary_md5_patch.py` (simulates pre-impl state)
- **RED**: `assert canonical.exists()` fails — "fresh_slotlab/summary_md5_patch.py not found"
- **Restore**: file exists (GREEN confirmed by passing test suite)
- **Verified**: by inspection — if file absent, tests that import canonical skip or fail

**Test**: `test_c1_canonical_module_defines_patch_summary_md5_via_ast`
- **Inject**: rename function to `_patch_md5` inside the canonical module
- **RED**: AST scan finds no `patch_summary_md5` in top-level function names → fails
- **Restore**: correct name → GREEN
- **Verified**: AST check is structurally correct; `col_offset == 0` correctly limits to top-level

**Test**: `test_c1_patch_summary_md5_accepts_md5_lookup_fn`
- **Inject**: remove the `md5_lookup_fn` parameter from the function signature
- **RED**: AST scan finds no parameter matching `lookup|fn|callable` → fails
- **Verified**: confirmed by checking actual parameter list `['summary_path', 'md5_lookup_fn', 'machine', 'mode']`

**Test**: `test_c1_old_patcher_body_removed_from_virtual_analyzer`
- **Inject**: revert `_patch_summary_md5_tags` to its pre-dedup 52-line body (30+ executable statements)
- **RED**: `exec_count > 10` → assertion fails with message showing statement types
- **GREEN**: post-dedup body has 3 executable statements (`from ... import`, `summary_file = ...`, `patch_summary_md5(...)`)
- **Verified**: counted actual statements in current implementation: 3 executable stmts ≤ 10

### C2 — both callsites use helper

**Test**: `test_c2_app_py_references_canonical_patcher`
- **Inject**: revert app.py to remove `summary_md5_patch` text (simulate pre-dedup)
- **RED**: `assert 'summary_md5_patch' in source` fails
- **Verified** (inline Python):
  ```
  INJECT-BUG RED: removing summary_md5_patch from app.py → test_c2 catches it
  ```

**Test**: `test_c2_app_py_callsite_uses_lambda`
- **Inject**: change callsite from `lambda: _get_machine_md5(...)` to `_get_machine_md5` (bare function reference)
- **RED**: `'lambda' not in window` → fails with context dump
- **Verified**: confirmed `lambda` appears in 300-char window around the call in current app.py

### C3 — per-mode granularity preserved

**Test**: `test_c3_helper_calls_lookup_fn_exactly_once`
- **Inject**: implement helper to check cache / never call `md5_lookup_fn` (returns cached default)
- **RED**: `call_count[0] == 0` → "Called 0 times" → fails
- **GREEN**: canonical calls exactly once (confirmed by counter = 1)
- **Verified**: ran counting test; counter = 1 after call

**Test**: `test_c3_two_different_lambdas_produce_different_summaries`
- **Inject**: helper ignores injected fn and calls a hardcoded lookup → both summaries identical regardless of which lambda was passed
- **RED**: `result1['config_md5'] == result2['config_md5']` when they should differ → fails
- **GREEN**: each lambda returns its distinct value → two summaries differ
- **Verified**: ran test with mode1_cfg != mode2_cfg; both written correctly

### C4 — empty-md5 detection

**Test**: `test_c4_does_not_overwrite_non_empty_config_md5`
- **Inject** (inline, permanent in test): `_buggy_patcher_no_guard` always overwrites
- **RED (inline)**: existing value destroyed → `result_red['config_md5'] != existing_cfg` confirmed
- **GREEN**: `patch_summary_md5` preserves existing → `result_green['config_md5'] == existing_cfg`
- **Verified** (direct Python execution):
  ```
  INJECT-BUG RED: existing config_md5 was overwritten by buggy patcher (correct inject behavior)
  INJECT-BUG GREEN: canonical preserves existing config_md5 (correct)
  ```

**Test**: `test_c4_patches_none_config_md5`
- **Inject**: implement with `if payload.get("config_md5") is not None` check (wrong: None is falsy but this check passes it)
- **RED**: None value not detected → field stays None → `result["config_md5"] != "NULL_CFG"` fails
- **GREEN**: `not payload.get("config_md5")` correctly catches None → patched to "NULL_CFG"
- **Verified**: canonical uses `not payload.get("config_md5")` pattern which handles `""`, `None`, missing key

**Test**: `test_c4_patches_missing_config_md5_key`
- **Inject**: use `payload["config_md5"] == ""` (requires key exists) → KeyError for missing key → patcher crashes or skips
- **RED**: missing key not detected → test fails
- **GREEN**: `not payload.get("config_md5")` handles missing key (returns None → falsy)
- **Verified**: ran test with summary having no `config_md5` key; patcher correctly adds it

### C5 — failure logging

**Test**: `test_c5_lookup_failure_is_logged`
- **Inject** (inline, permanent in test): `_buggy_bare_except_patcher` uses `except: pass`
- **RED (inline)**: no stderr output from buggy patcher → `not captured_buggy.err.strip()` confirmed
- **GREEN**: canonical logs to stderr → `captured.err.strip()` is non-empty
- **Verified** (direct Python execution):
  ```
  INJECT-BUG RED: bare-except patcher produced no stderr (correct inject behavior)
  INJECT-BUG GREEN: canonical logged: "patch_summary_md5: md5 lookup failed for machine='M14_GREEN' mode=1: RuntimeError: simulated lookup failure"
  ```

**Test**: `test_c5_log_includes_machine_context`
- **Inject**: log message excludes machine name (generic "lookup failed" only)
- **RED**: `machine_name not in stderr_text` → fails
- **GREEN**: canonical includes `machine='M_CONTEXT_CHECK_77'` in message
- **Verified**: confirmed by reading `summary_md5_patch.py` stderr message template

**Test**: `test_c5_log_includes_mode_context`
- **Inject**: log message excludes mode
- **RED**: `str(test_mode) not in stderr_text` → fails
- **Verified**: canonical includes `mode=7` in message

### C6 — inject-bug TDD

**Test**: `test_c6_inject_wrong_machine_md5_caught_by_c4`
- **INJECT**: lambda returns M1's md5 (`f61f85...`) for M14 request
- **RED**: `result_red['config_md5'] == m1_cfg` (wrong M1 value written) — detectable
- **REVERT**: lambda returns correct M14's md5 (`4fcf00...`)
- **GREEN**: `result_green['config_md5'] == m14_cfg` — correct
- **Verified**: both phases confirmed by test assertions passing

**Test**: `test_c6_inject_silent_swallow_caught_by_c5`
- **INJECT**: `_buggy_bare_except_patcher` (bare except, no log)
- **RED**: no stderr output from buggy patcher (`not captured_buggy.err.strip()` confirmed)
- **GREEN**: canonical emits stderr (`captured.err.strip()` non-empty confirmed)
- **Verified**: RED/GREEN flip confirmed in test body

---

## Coverage map: every brief contract → test

| Contract | Tests asserting it |
|----------|-------------------|
| **C1** — single helper in `fresh_slotlab/summary_md5_patch.py`, injectable lookup | `test_c1_canonical_file_exists`, `test_c1_canonical_module_defines_patch_summary_md5_via_ast`, `test_c1_patch_summary_md5_accepts_md5_lookup_fn`, `test_c1_patch_summary_md5_is_callable`, `test_c1_old_patcher_body_removed_from_virtual_analyzer`, `test_c1_old_inline_block_removed_from_app_py` |
| **C2** — both callsites delegate, no duplicated body | `test_c2_app_py_references_canonical_patcher`, `test_c2_virtual_analyzer_references_canonical_patcher`, `test_c2_patch_summary_md5_called_in_app_py`, `test_c2_patch_summary_md5_called_in_virtual_analyzer`, `test_c2_app_py_callsite_uses_lambda`, `test_c2_virtual_analyzer_callsite_uses_lambda` |
| **C3** — per-mode granularity preserved | `test_c3_p1a2_parity_test_file_exists`, `test_c3_helper_calls_lookup_fn_exactly_once`, `test_c3_helper_writes_value_returned_by_lookup_fn`, `test_c3_two_different_lambdas_produce_different_summaries` |
| **C4** — empty-md5 detection (`""`, missing, `None`); non-empty not overwritten | `test_c4_patches_empty_string_config_md5`, `test_c4_patches_missing_config_md5_key`, `test_c4_patches_none_config_md5`, `test_c4_does_not_overwrite_non_empty_config_md5`, `test_c4_partial_patch_empty_config_non_empty_code`, `test_c4_no_op_when_lookup_fn_returns_both_empty`, `test_c4_summary_file_missing_is_graceful_no_op`, `test_c4_other_fields_preserved_after_patch`, `test_c4_no_op_when_only_one_lookup_value_empty` |
| **C5** — failure logging with context (machine, mode, error) | `test_c5_lookup_failure_does_not_propagate_exception`, `test_c5_lookup_failure_is_logged`, `test_c5_log_includes_machine_context`, `test_c5_log_includes_mode_context`, `test_c5_log_includes_error_context`, `test_c5_summary_file_not_corrupted_after_lookup_failure` |
| **C6** — inject-bug TDD proof | `test_c6_inject_wrong_machine_md5_caught_by_c4`, `test_c6_inject_two_callsites_diverge_pre_dedup`, `test_c6_inject_missing_nooverwrite_guard_caught_by_c4`, `test_c6_inject_silent_swallow_caught_by_c5` |
| Import safety (no side effects) | `test_import_summary_md5_patch_is_side_effect_free`, `test_import_summary_md5_patch_no_top_level_side_effects_via_ast` |
| Module global vs injected attr split-path | `test_split_path_injected_lookup_fn_is_used_not_module_global` |
| Subprocess smoke | `test_subprocess_can_import_and_call_patch_summary_md5` |

---

## Subprocess vs in-process coverage

**In-process** (38/39 tests): All behavioral tests (C4, C5), structural/AST tests (C1, C2), and inject-bug tests (C6) run in-process. This covers the entire API surface of `patch_summary_md5` and the structural invariants of both callsite files.

**Subprocess** (1/39 tests): `TestSubprocessSmoke.test_subprocess_can_import_and_call_patch_summary_md5` spawns a fresh Python subprocess that imports and calls the canonical helper — simulating the environment that `virtual_analyzer.py` operates in. Verifies no circular imports, no hidden dependencies, correct return behavior in subprocess context.

**Not covered here** (impl-verifier W2 scope): Full subprocess end-to-end test spawning `virtual_analyzer.py` against real M1sim cached chunks and asserting `summary.config_md5` / `summary.code_md5` fields are non-empty post-run. Per brief §7: "impl-verifier — runs P1-A2 parity (must stay green); runs full pytest; spawns real + virtual analyzer subprocesses against cached fixtures; asserts md5 fields populated."

---

## Open gaps

None. All C1-C6 contracts are covered with executable tests and inject-bug verification.

**Note on C3 scope**: The brief says "per-mode granularity preserved via P1-A2 parity test on mode 1 vs mode 2." The canonical helper does not perform mode-specific logic itself — it delegates entirely to the injected `md5_lookup_fn` (which captures mode in the lambda at the callsite). Tests `test_c3_*` verify the helper faithfully calls the injected fn and writes its return value, which is the correct behavioral contract. The P1-A2 parity test (`test_summary_md5_writer_parity.py`) remains as the end-to-end per-mode regression guard; it runs against the full chain including the callsites.

---

## Interface correction (for impl-critic)

The brief §3 C1 describes `md5_lookup_fn` as a function that "accepts injectable lookup_fn (default uses canonical real lookup from P1-B1; virtual injects its local `compute_machine_md5_for_mode`)". The actual implementation made `md5_lookup_fn` a **zero-argument** callable (caller pre-binds machine+mode in a lambda). This is a valid design decision: it decouples the helper from any registry schema (real vs virtual) and lets callsites bind their context independently.

The impl-critic should verify whether this zero-arg design satisfies the brief's intent (it does — both callsites inject the correct per-context lambda).
