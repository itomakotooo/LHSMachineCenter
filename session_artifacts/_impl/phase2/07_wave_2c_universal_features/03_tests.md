# 03_tests.md — impl-tester report for P2-C Wave 2c universal features

## Verdict

**sufficient**

All 8 brief contracts (C1–C8) are covered. 68 tests pass, 2 skip (skips are
expected: `compute_base_analyzer_version` not yet exported from versioning.py,
consistent with the running pattern across P2-B1b through P2-B4). Both inject-bug
proofs are verified RED→GREEN.

---

## Test files added

| File | Tests |
|------|-------|
| `tests/backend/test_wave_2c_universal_features.py` | **68 pass, 2 skip** (70 total) |

---

## Pre-impl baseline (feature files not yet created)

Running the suite before the implementer landed (feature modules absent from
`fresh_slotlab/analyzer/features/`) would produce:

- C1 parametrized tests: **skipped** (guard pattern fires: `if not (FEATURES_DIR / spec["module_file"]).exists(): pytest.skip(...)`)
- C2 parametrized tests: **skipped** (same guard)
- C4 emit-invocation tests: **RED** (no `_feature.emit(` in PIA source yet)
- C8b restore test: **skipped** (emit loop not yet wired)

Post-impl (all 4 feature files present + PIA wired): **68 pass, 2 skip**.

---

## Inject-bug verification log

### C8a — Registration inject (register() call absent)

**Target test**: `TestRegistrationOnImport::test_feature_registered_after_module_import[payouts_by_spin_type]`

**Inject step**: Edited `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` line 65:
```python
# Before (correct):
register(PayoutsBySpinType())

# After (injected bug):
# register(PayoutsBySpinType())  # INJECT-BUG: commented out to test C8a
```

**Result RED**: Test failed with:
```
AssertionError: FEATURE_ID='payouts_by_spin_type' not in ALL_FEATURES after importing
fresh_slotlab.analyzer.features.payouts_by_spin_type.
  Before import: []
  After import:  []
  C2 contract: module-bottom register(MyFeature()) call must fire.
  C8 inject-bug: commenting out register() makes this RED.
```

**Restore**: Reverted the comment — `register(PayoutsBySpinType())` restored.

**Result GREEN**: `1 passed`.

---

### C8b — emit-invocation inject (loop body replaced with no-op)

**Target tests**:
- `TestMainInvokesFeatureEmit::test_main_source_contains_feature_emit_call`
- `TestMainInvokesFeatureEmit::test_main_function_ast_contains_emit_call`

**Inject step**: Edited `fresh_slotlab/player_impact_analyzer.py` line 4774:
```python
# Before (correct):
        _feature.emit(None, summary)

# After (injected bug):
        _ = _feature  # INJECT-BUG: emit call removed to test C8b
```

**Result RED**: Both string-search and AST tests failed:
```
AssertionError: No '_feature.emit(' call found after 'for _feature in ALL_FEATURES:'
AssertionError: No 'feature.emit(...)' call found in main()'s AST.
```

**Restore**: Reverted to `_feature.emit(None, summary)`.

**Result GREEN**: Both tests `passed`.

---

## Coverage map: every brief contract → test

| Contract | Description | Tests | Status |
|----------|-------------|-------|--------|
| C1 | 4 feature module files exist | `TestFeatureModulesExist::test_module_file_exists[*]` ×4 | PASS |
| C1 | Each exports AnalyzerFeature subclass | `test_module_exports_analyzer_feature_subclass[*]` ×4 | PASS |
| C1 | FEATURE_ID ClassVar matches feature_id | `test_feature_id_classvar_matches_module_name[*]` ×4 | PASS |
| C1 | Class is instantiable (all 3 abstractmethods concrete) | `test_class_is_instantiable[*]` ×4 | PASS |
| C1 | RTP_CONTRIBUTION == False | `test_rtp_contribution_classvar_is_false[*]` ×4 | PASS |
| C2 | Registration on import | `TestRegistrationOnImport::test_feature_registered_after_module_import[*]` ×4 | PASS |
| C2 | Re-import idempotent | `test_re_import_is_idempotent[*]` ×4 | PASS |
| C3 | P1-A1 canary file present | `TestP1A1CanaryReference::test_parity_test_file_exists` | PASS |
| C3 | Summary keys present in source | `test_pia_summary_keys_present_in_source` | PASS |
| C4 | main() has ALL_FEATURES emit loop (string) | `TestMainInvokesFeatureEmit::test_main_source_contains_feature_emit_call` | PASS |
| C4 | main() imports ALL_FEATURES | `test_pia_imports_all_features_from_registry` | PASS |
| C4 | main() has emit call in AST | `test_main_function_ast_contains_emit_call` | PASS |
| C5 | compute_base_analyzer_version is 12-char hex | `TestHashComposition::test_base_version_is_12char_hex` | SKIP (fn not in versioning.py) |
| C5 | Base version only hashes core/*.py (not features/) | `test_base_version_does_not_include_features_dir` | SKIP (fn not in versioning.py) |
| C5 | feature.compute_hash() returns 12-char hex | `test_feature_compute_hash_returns_12char_hex[*]` ×4 | PASS |
| C5 | compute_hash() deterministic | `test_feature_compute_hash_is_deterministic[*]` ×4 | PASS |
| C6 | Subprocess import rc=0 | `TestSubprocessImportSafety::test_subprocess_import_exits_zero[*]` ×4 | PASS |
| C6 | Subprocess import no stderr | `test_subprocess_import_no_stderr[*]` ×4 | PASS |
| C6 | Subprocess registers in ALL_FEATURES | `test_subprocess_import_registers_in_registry[*]` ×4 | PASS |
| C7 | Pattern A extract returns {} | `TestPatternANoOpExtractReduce::test_pattern_a_extract_returns_empty_dict[*]` ×2 | PASS |
| C7 | Pattern A reduce returns prev_acc | `test_pattern_a_reduce_returns_prev_acc_unchanged[*]` ×2 | PASS |
| C7 | Pattern A emit callable | `test_pattern_a_emit_is_callable[*]` ×2 | PASS |
| C8 | Registration inject proof | `TestInjectBugRegistration::test_inject_missing_register_call_makes_feature_id_absent` | PASS |
| C8 | Registration restore proof | `test_inject_register_not_called_then_restore_shows_green` | PASS |
| C8 | Emit inject proof (string) | `TestInjectBugEmitInvocation::test_inject_no_emit_call_makes_c4_test_fire` | PASS |
| C8 | Emit inject proof (AST) | `test_inject_emit_absent_from_ast_makes_c4_test_fire` | PASS |
| C8 | Emit restore proof | `test_restore_emit_call_present_in_actual_pia_source` | PASS |
| Extra | SCHEMA_KEYS includes brief §1 keys | `TestSchemaKeysDeclared::test_schema_keys_includes_expected_summary_keys[*]` ×4 | PASS |

---

## Open gaps

1. **C5 `compute_base_analyzer_version` skipped**: The function is not yet exported from `versioning.py` — consistent with all prior Wave 2 tickets (P2-B1b through P2-B4). Tests are guarded with `@requires_base_version` and will run once the function is added. This is a known architectural debt, flagged since P2-B2 critic (SQ6).

2. **C3 parity canary byte-identity**: The full 23/23 byte-identical regression (`test_analyzer_three_invocation_parity.py`) is impl-verifier's responsibility. The tester asserts only file presence and structural key presence. Byte-identity parity of Pattern B output (bankruptcy_simulation, bankruptcy_probe) against pre-Wave-2c behavior is the highest risk in C3 — this is explicitly deferred to impl-verifier.

3. **Pattern B reduce semantics**: `TestPatternANoOpExtractReduce` skips the `reduce` no-op assertion for Pattern B features (`bankruptcy_simulation`, `multiplier_profile`) per the brief's "skip the reduce assertion for Pattern B classes" instruction. Wave 2d will add reduce logic for these.

---

## Subprocess vs in-process coverage

- **C6** (`TestSubprocessImportSafety`): 12 tests — all spawn real `python -c "import <module>"` subprocesses. Per memory `feedback_perf_claim_needs_e2e_event_stream.md`.
- **C2 re-import idempotent**: In-process via `importlib.import_module` (sufficient — the idempotency contract lives in `feature_registry.register()` which is in-process; subprocess-mode would not exercise it differently).
- **C4 main() wiring**: AST + string-based source check — structural, not runtime. Sufficient for the wiring contract (runtime behavioral check is the P1-A1 parity canary in impl-verifier's scope).

---

## Implementation notes discovered during testing

1. **PIA file has UTF-8 BOM** (`﻿`): `player_impact_analyzer.py` is saved with Windows UTF-8 BOM. All reads use `encoding="utf-8-sig"` to strip it. `ast.parse()` requires BOM-free input; the fix is critical for the AST test.

2. **Pattern A emit checks `summary["player_impact"]`, not top-level `summary`**: The implementer's `PayoutsBySpinType.emit()` does `assert key in summary.get("player_impact") or {}`. The C7 emit callability test was updated to pass `{"player_impact": {key: {}}}` rather than `{key: {}}`.

3. **Loop variable is `_feature`, not `feature`**: The implementer used `for _feature in ALL_FEATURES:`. The C4 string check and C8b inject proofs were updated to use a regex that finds `for <any_var> in ALL_FEATURES:` and then asserts `<any_var>.emit(` follows.

4. **`BankruptcySimulation.emit(` appears in PIA source** (in docstrings or comments): A naive `\w+\.emit\(` regex matches it, creating false-positive matches when the actual loop emit call is removed. Fixed by extracting the loop variable name from the `for ... in ALL_FEATURES:` pattern and searching specifically for `<loop_var>.emit(`.
