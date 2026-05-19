# P2-B2 Test Plan — 03_tests.md

**Ticket**: phase2/04_core_aggregator (P2-B2)
**Test file**: `tests/backend/test_analyzer_core_aggregator.py`
**Written by**: impl-tester (Wave 1)
**Date**: 2026-05-19

---

## Verdict

**partial** — 124 tests written. 112 pass + 2 skip in current branch state.
10 are intentionally RED because the implementer has not yet finished
updating `player_impact_analyzer.py`'s re-export block for 5 of the 7
callable _utils symbols. These tests will go GREEN when the implementer
completes the PIA re-export step (step 8 of the impl workflow).

---

## Test Files Added

| File | Tests |
|------|-------|
| `tests/backend/test_analyzer_core_aggregator.py` | 124 |

---

## Pre-Implementation State Analysis

When this test file was written, the implementer had partially landed P2-B2:

- `fresh_slotlab/analyzer/core/_utils.py` — EXISTS (fully created)
- `fresh_slotlab/analyzer/core/aggregator.py` — EXISTS (fully created)
- `fresh_slotlab/analyzer/core/parser.py` — DEDUP COMPLETE (9 local defs deleted, _utils import added)
- `fresh_slotlab/player_impact_analyzer.py` — PARTIAL: only `to_float` and `_empty_bankruptcy_tier` resolve to _utils.py; 5 others (`blank_like_symbol`, `bonus_chain_depth_bucket`, `return_bucket`, `_extract_bankruptcy_reps`, `simulate_bankruptcy_from_response`) still resolve to PIA's local definitions

**10 correctly-failing tests** (waiting on PIA re-export completion):
- `TestSingleSourceOfTruth::test_pia_symbol_resolves_to_utils_file[blank_like_symbol]`
- `TestSingleSourceOfTruth::test_pia_symbol_resolves_to_utils_file[bonus_chain_depth_bucket]`
- `TestSingleSourceOfTruth::test_pia_symbol_resolves_to_utils_file[return_bucket]`
- `TestSingleSourceOfTruth::test_pia_symbol_resolves_to_utils_file[_extract_bankruptcy_reps]`
- `TestSingleSourceOfTruth::test_pia_symbol_resolves_to_utils_file[simulate_bankruptcy_from_response]`
- `TestSingleSourceOfTruth::test_pia_and_parser_and_utils_are_same_object[blank_like_symbol]`
- `TestSingleSourceOfTruth::test_pia_and_parser_and_utils_are_same_object[bonus_chain_depth_bucket]`
- `TestSingleSourceOfTruth::test_pia_and_parser_and_utils_are_same_object[return_bucket]`
- `TestSingleSourceOfTruth::test_pia_and_parser_and_utils_are_same_object[_extract_bankruptcy_reps]`
- `TestSingleSourceOfTruth::test_pia_and_parser_and_utils_are_same_object[simulate_bankruptcy_from_response]`

---

## Test Class Map (by contract)

### C1 — Files exist + symbols carved

**TestFilesExist** (5 tests):
- `test_core_utils_exists` — asserts _utils.py on disk
- `test_core_aggregator_exists` — asserts aggregator.py on disk
- `test_core_dir_is_a_directory` — core/ is a dir
- `test_core_init_still_exists` — P2-B1's __init__.py not deleted
- `test_core_parser_still_exists` — P2-B1's parser.py not deleted

**TestAggregatorSymbolsInModule** (26 tests):
- `test_function_or_class_present_in_aggregator[X]` × 16 — each of the 16 function/class symbols accessible from core.aggregator
- `test_constant_present_in_aggregator[X]` × 2 — each of the 2 constants accessible
- `test_bankruptcy_stream_accumulator_is_class` — confirms isinstance(obj, type)
- `test_default_bankroll_multipliers_is_tuple` — confirms tuple type
- `test_default_bankruptcy_session_spins_is_positive_int` — confirms positive int

**TestUtilsSymbolsInModule** (13 tests):
- `test_symbol_present_in_utils[X]` × 9 — each of the 9 shared helpers in core._utils
- `test_to_float_callable` — behavioral smoke (bool-safe, str conversion)
- `test_blank_like_symbol_callable` — behavioral smoke
- `test_return_bucket_callable` — behavioral smoke (eq0 / gt0_lt1 / ge100_lt200)
- `test_simulate_bankruptcy_from_response_callable` — callable check

**TestPIAReExportsAggregatorSymbols** (21 tests):
- `test_pia_has_aggregator_symbol[X]` × 18 — all 16+2 accessible via PIA
- `test_pia_has_utils_only_symbol[X]` × 3 — pure-utility helpers (to_float, blank_like_symbol, bonus_chain_depth_bucket) accessible via PIA

### C2 — P1-A1 canary

**TestP1A1ParityCanary** (3 tests):
- `test_p1_a1_parity_test_file_exists` — file not deleted
- `test_p1_a1_parity_test_importable` — parses as valid Python (AST)
- `test_pia_still_has_simulate_bankruptcy_for_parity_path` — symbol accessible + callable

### C3 — Single source of truth (dedup)

**TestSingleSourceOfTruth** (23 tests):
- `test_pia_symbol_resolves_to_utils_file[X]` × 7 — inspect.getfile(pia.X) endswith "_utils.py"
- `test_parser_symbol_resolves_to_utils_file[X]` × 7 — inspect.getfile(parser.X) endswith "_utils.py"
- `test_pia_and_parser_and_utils_are_same_object[X]` × 7 — pia.X is parser.X is utils.X (object identity)
- `test_constant_value_consistent_across_all_modules[X]` × 2 — value equality for constants

### C4 — Subprocess import safety

**TestSubprocessImportSafety** (8 tests):
- `test_utils_subprocess_import_exits_zero` — rc=0, stdout has 'OK'
- `test_aggregator_subprocess_import_exits_zero` — rc=0, stdout has 'OK'
- `test_utils_subprocess_no_stderr` — -W error import succeeds
- `test_aggregator_subprocess_no_stderr` — -W error import succeeds
- `test_utils_does_not_pull_in_pia_at_import_time` — sys.modules check via subprocess
- `test_aggregator_does_not_pull_in_pia_at_import_time` — sys.modules check via subprocess
- `test_each_new_module_individually_importable[fresh_slotlab.analyzer.core._utils]`
- `test_each_new_module_individually_importable[fresh_slotlab.analyzer.core.aggregator]`

### C5 — Cycle freedom

**TestCycleFreedom** (4 tests):
- `test_utils_does_not_import_from_fresh_slotlab` — static grep for 3 prohibited import targets in _utils.py (Note: fresh_slotlab.round_win is NOT prohibited; the grep matches only the 3 explicitly banned targets)
- `test_aggregator_does_not_import_from_pia` — static grep (import statements only, not docstrings)
- `test_parser_does_not_import_from_aggregator` — static grep
- `test_parser_imports_from_utils_not_defines_locally` — checks BOTH: import present AND local defs absent (guards the "partial landing" scenario where import is added but duplicates not removed)

### C6 — Hash composition

**TestHashCompositionRollsForward** (5 tests):
- `test_adding_utils_py_changes_hash` — hash WITH _utils.py != hash WITHOUT _utils.py
- `test_adding_aggregator_py_changes_hash` — hash WITH aggregator.py != hash WITHOUT
- `test_mutating_utils_py_content_flips_hash` — sentinel byte in-memory → hash flips
- `test_base_version_is_12char_hex` — 12-char lowercase hex (skips if compute_base_analyzer_version not yet in versioning.py)
- `test_base_version_matches_reference_after_p2_b2` — implementer's fn matches reference (_ref_base_version)

### C7 — No silent swallows

**TestNoSilentSwallows** (2 tests):
- `test_utils_no_silent_swallows` — AST scan, baseline 0 (pure stdlib utility)
- `test_aggregator_no_new_silent_swallows_beyond_pia_baseline` — AST scan, baseline 0

**AST Baseline Verification** (done by tester before writing tests):
PIA lines 1100-1900 (the range containing all 16 aggregator symbols):
  ZERO silent swallows found.
  
  Full PIA silent swallow scan found 9 total (lines 1970, 1986, 1995, 2090, 2098, 2677, 3201, 3384, 6033).
  None of these are within lines 1100-1900. Therefore aggregator.py baseline = 0.
  
  _utils.py carries helpers from PIA's utility range; that range also has 0 swallows.
  Therefore _utils.py baseline = 0.

### C8 — Inject-bug TDD

**TestInjectBugC8a_AggregatorSymbolDeletion** (2 tests — mechanism proofs):
- `test_inject_missing_symbol_proof_mechanism` — proves hasattr mechanism
- `test_inject_pia_missing_symbol_proof_mechanism` — proves PIA re-export mechanism

**TestInjectBugC8b_CycleViolation** (2 tests — mechanism proofs):
- `test_inject_cycle_in_utils_proof_mechanism` — proves the grep correctly catches prohibited imports
- `test_inject_back_import_in_aggregator_proof_mechanism` — proves aggregator → PIA direction caught

**TestInjectBugC8c_DeduplicationBreak** (1 test — mechanism proof):
- `test_inject_local_def_breaks_identity_proof_mechanism` — proves two separately-defined functions fail 'is' check

### Supplementary: Existing Test Suites Intact

**TestExistingTestSuitesStillIntact** (15 tests):
- `test_existing_suite_still_exists[X]` × 6 — all 6 existing suites on disk
- `test_existing_suite_still_valid_python[X]` × 6 — parse as valid Python
- `test_parser_test_imports_still_resolve_via_pia` — key symbols for test_analyzer_parsing.py
- `test_bankruptcy_test_imports_still_resolve_via_pia` — key symbols for test_analyzer_bankruptcy.py

---

## Inject-Bug Verification Log

### IB-1: C1 — Delete classify_volatility from aggregator.py

**What was injected:**
```python
# In fresh_slotlab/analyzer/core/aggregator.py line 334:
# REPLACED the def classify_volatility(...) body with:
# INJECT_BUG_C1: classify_volatility deleted to prove C1 test goes RED
```

**Command run:**
```
python -m pytest "tests/backend/test_analyzer_core_aggregator.py::TestAggregatorSymbolsInModule::test_function_or_class_present_in_aggregator[classify_volatility]" -v
```

**Result:** FAILED — AssertionError: fresh_slotlab.analyzer.core.aggregator.classify_volatility not found.

**Restored:** reverted the comment back to the full `def classify_volatility(...)` body.

**Verification after restore:**
```
python -m pytest "tests/backend/test_analyzer_core_aggregator.py::TestAggregatorSymbolsInModule::test_function_or_class_present_in_aggregator[classify_volatility]" -v
```
**Result:** PASSED

**Proves:** `test_function_or_class_present_in_aggregator[classify_volatility]` and all 15 other parametrized variants catch partial carves where a symbol is missing from aggregator.py.

---

### IB-2: C5 — Add prohibited import to _utils.py

**What was injected:**
```python
# In fresh_slotlab/analyzer/core/_utils.py, inserted after line 41:
from fresh_slotlab.analyzer.core.aggregator import quantile_from_hist  # INJECT_BUG_C5
```

**Command run:**
```
python -m pytest "tests/backend/test_analyzer_core_aggregator.py::TestCycleFreedom::test_utils_does_not_import_from_fresh_slotlab" -v
```

**Result:** FAILED — AssertionError: C5 CYCLE VIOLATION: _utils.py contains 1 prohibited import(s). Offending line: `from fresh_slotlab.analyzer.core.aggregator import quantile_from_hist`

**Restored:** deleted the injected import line.

**Verification after restore:**
```
python -m pytest "tests/backend/test_analyzer_core_aggregator.py::TestCycleFreedom::test_utils_does_not_import_from_fresh_slotlab" -v
```
**Result:** PASSED

**Proves:** The C5 static grep test correctly detects a `from fresh_slotlab.analyzer.core.aggregator import X` inside _utils.py.

**Key implementation detail:** The grep pattern only matches actual `import` and `from` statements — it does NOT trigger on docstring mentions of "fresh_slotlab" or on "fresh_slotlab.round_win" imports (which are explicitly NOT prohibited per brief §3 C5).

---

### IB-3: C3 — Re-add local def to parser.py (dedup regression)

**What was injected:**
```python
# In fresh_slotlab/analyzer/core/parser.py, replaced the comment block at ~line 460 with:
# INJECT_BUG_C3: Re-add local to_float to prove C3 test goes RED
def to_float(value, default=0.0):
    """Injected local def that shadows the _utils import — C3 test should fire."""
    return float(value) if value else default
# END INJECT_BUG_C3
```

**Commands run:**
```
python -m pytest \
  "tests/backend/test_analyzer_core_aggregator.py::TestSingleSourceOfTruth::test_parser_symbol_resolves_to_utils_file[to_float]" \
  "tests/backend/test_analyzer_core_aggregator.py::TestSingleSourceOfTruth::test_pia_and_parser_and_utils_are_same_object[to_float]" \
  "tests/backend/test_analyzer_core_aggregator.py::TestCycleFreedom::test_parser_imports_from_utils_not_defines_locally" -v
```

**Results:**
- `test_parser_symbol_resolves_to_utils_file[to_float]` — FAILED: getfile returns `parser.py` instead of `_utils.py`
- `test_pia_and_parser_and_utils_are_same_object[to_float]` — FAILED: `parser.to_float IS NOT utils.to_float`
- `test_parser_imports_from_utils_not_defines_locally` — FAILED: 1 local def found `def to_float(value, default=0.0):`

**Restored:** reverted the injected def back to the comment block.

**Verification after restore:** All 3 tests PASSED.

**Proves:** Three independent tests catch the dedup regression:
1. `test_parser_symbol_resolves_to_utils_file` catches via `inspect.getfile`
2. `test_pia_and_parser_and_utils_are_same_object` catches via object identity (`is`)
3. `test_parser_imports_from_utils_not_defines_locally` catches via static grep for `def to_float(`

**Key insight (documented in test):** Python executes module-level statements top-to-bottom. If both `from _utils import to_float` (line ~38) AND `def to_float(...)` (line ~462) exist in parser.py, the `def` wins because it comes LAST in execution order. This is why deleting the duplicates (not just adding the import) is required for the dedup to be complete.

---

## Coverage Map: Brief Contracts → Tests

| Brief Contract | Test(s) | Status |
|----------------|---------|--------|
| C1: _utils.py exists | TestFilesExist::test_core_utils_exists | PASS |
| C1: aggregator.py exists | TestFilesExist::test_core_aggregator_exists | PASS |
| C1: all 16 aggregator fn/class symbols accessible | TestAggregatorSymbolsInModule::test_function_or_class_present_in_aggregator[X]×16 | PASS |
| C1: 2 constants accessible from aggregator | TestAggregatorSymbolsInModule::test_constant_present_in_aggregator[X]×2 | PASS |
| C1: 9 shared helpers in _utils | TestUtilsSymbolsInModule::test_symbol_present_in_utils[X]×9 | PASS |
| C1: PIA re-exports 16+2 symbols | TestPIAReExportsAggregatorSymbols::test_pia_has_aggregator_symbol[X]×18 | PASS |
| C1: PIA re-exports 3 pure-util helpers | TestPIAReExportsAggregatorSymbols::test_pia_has_utils_only_symbol[X]×3 | PASS |
| C2: P1-A1 canary intact | TestP1A1ParityCanary (3 tests) | PASS |
| C3: inspect.getfile(pia.X) endswith "_utils.py" | TestSingleSourceOfTruth::test_pia_symbol_resolves_to_utils_file[X]×7 | 2 PASS, 5 RED (impl partial) |
| C3: inspect.getfile(parser.X) endswith "_utils.py" | TestSingleSourceOfTruth::test_parser_symbol_resolves_to_utils_file[X]×7 | PASS (dedup done) |
| C3: pia.X is parser.X is utils.X | TestSingleSourceOfTruth::test_pia_and_parser_and_utils_are_same_object[X]×7 | 2 PASS, 5 RED (impl partial) |
| C3: constant values consistent | TestSingleSourceOfTruth::test_constant_value_consistent_across_all_modules[X]×2 | PASS |
| C4: _utils subprocess import rc=0 | TestSubprocessImportSafety::test_utils_subprocess_import_exits_zero | PASS |
| C4: aggregator subprocess import rc=0 | TestSubprocessImportSafety::test_aggregator_subprocess_import_exits_zero | PASS |
| C4: no stderr on import | test_utils_subprocess_no_stderr, test_aggregator_subprocess_no_stderr | PASS |
| C4: no PIA pull-in at import time | test_utils_does_not_pull_in_pia_at_import_time, test_aggregator_does_not_pull_in_pia_at_import_time | PASS |
| C4: each new module individually importable | test_each_new_module_individually_importable[X]×2 | PASS |
| C5: _utils not import prohibited targets | TestCycleFreedom::test_utils_does_not_import_from_fresh_slotlab | PASS |
| C5: aggregator not import PIA | TestCycleFreedom::test_aggregator_does_not_import_from_pia | PASS |
| C5: parser not import aggregator | TestCycleFreedom::test_parser_does_not_import_from_aggregator | PASS |
| C5: parser uses _utils import (dedup done) | TestCycleFreedom::test_parser_imports_from_utils_not_defines_locally | PASS |
| C6: adding new files changes hash | test_adding_utils_py_changes_hash, test_adding_aggregator_py_changes_hash | PASS |
| C6: mutation flips hash | test_mutating_utils_py_content_flips_hash | PASS |
| C6: compute_base_analyzer_version valid | test_base_version_is_12char_hex, test_base_version_matches_reference_after_p2_b2 | SKIP (fn not yet in versioning.py) |
| C7: 0 silent swallows in _utils.py | TestNoSilentSwallows::test_utils_no_silent_swallows | PASS |
| C7: 0 new swallows in aggregator.py | TestNoSilentSwallows::test_aggregator_no_new_silent_swallows_beyond_pia_baseline | PASS |
| C8: inject missing symbol → C1 RED | Proven by IB-1 (actual file edit + run) | VERIFIED |
| C8: inject cycle import → C5 RED | Proven by IB-2 (actual file edit + run) | VERIFIED |
| C8: inject local def → C3 RED | Proven by IB-3 (actual file edit + run) | VERIFIED |
| C7: existing suites intact | TestExistingTestSuitesStillIntact (15 tests) | PASS |

---

## Subprocess vs In-Process Coverage

Per memory `feedback_perf_claim_needs_e2e_event_stream.md`:

**Subprocess tests:**
- C4: 8 tests spawn real `python -c "import ..."` subprocesses via `subprocess.run`
- Two tests use `sys.modules` inspection in subprocess to catch runtime circular import chains
- Two tests use `-W error` flag to catch import-time warnings

**In-process tests:**
- C1, C2, C3, C5, C6, C7: use in-process imports (the import guard at module level)
- C3 identity checks (`is`) are in-process only — this is sufficient because the object identity check is a stronger test than a subprocess run for detecting duplicate definitions

**Why subprocess AND in-process for C4:**
The subprocess test catches runtime failures that in-process imports might miss (e.g., if the test process already has all modules loaded in sys.modules, a circular import might not fire). The subprocess starts from a clean Python environment.

---

## Open Gaps

1. **C3 PIA not yet complete (10 failing tests):** The implementer has not finished updating PIA's re-export block. 5 of the 7 callable _utils symbols still resolve to PIA's local definitions. These will go GREEN when the implementer removes the local PIA definitions and adds the `_utils` import for: `blank_like_symbol`, `bonus_chain_depth_bucket`, `return_bucket`, `_extract_bankruptcy_reps`, `simulate_bankruptcy_from_response`.

2. **C6 compute_base_analyzer_version not yet exported from versioning.py:** 2 tests skip with `requires_base_version`. The function may need to be added to `versioning.py` as part of the P2-A1/P2-B2 deliverable. The hash mechanism is verified via the reference implementation in all skipped tests' siblings.

3. **Bankruptcy stack end-to-end smoke not included:** The brief §6 Risk 2 notes the bankruptcy stack interplay. The P1-A1 parity test (C2) covers this path end-to-end; the individual function behavioral smokes in `TestUtilsSymbolsInModule` cover light checks. A deeper bankruptcy stack integration test (with a real fixture) is impl-verifier's responsibility per the workflow.

4. **is-diff-to-is-same update in test_analyzer_core_parser.py:** Per brief §3 C7, the P2-B1b divergence-audit test that asserts `is_diff=True body_eq=True` must be updated to `is_diff=False` (same object). This is the implementer's job per ticket step 8, not the tester's.

---

## Notes on C5 Implementation

The C5 test for `_utils.py` uses a **precise import-statement-only grep** (not a full-text `fresh_slotlab` search). This is important because:

1. `_utils.py` docstring mentions `fresh_slotlab` in describing what it does NOT import — those mentions are in triple-quoted strings, not import statements. A naive grep would flag them as violations.

2. `_utils.py` legitimately imports from `fresh_slotlab.round_win` via a dual-path try/except block. Per brief §3 C5, `round_win` is NOT in the prohibited list (the prohibited targets are: parser.py, aggregator.py, player_impact_analyzer). `round_win` is in the same non-cyclical category as `trigger_sessions` in parser.py.

The grep pattern requires:
- Line starts with `import ` or `from ` (stripped)
- AND contains one of the 3 prohibited target strings

This correctly allows `from fresh_slotlab.round_win import (...)` while catching `from fresh_slotlab.analyzer.core.aggregator import X`.
