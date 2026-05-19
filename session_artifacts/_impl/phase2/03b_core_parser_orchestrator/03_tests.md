# Test Report — P2-B1b: Carve `parse_chunk_response` into `analyzer/core/parser.py`

**Verdict: sufficient**

---

## Suite counts (current state as of tester pass)

Run: `python -m pytest tests/backend/test_analyzer_core_parser.py -q`

```
83 passed, 7 skipped, 2 xfailed in 0.45s
```

Previous baseline (pre-B1b tester pass): 82 passed, 7 skipped, 2 xfailed.  
New test added: `test_no_back_import_to_pia` → +1 passed.

**Current implementer state**: the implementer has landed the docstring update and the dual-path import scaffolding (imports from `trigger_sessions`, `round_classification`, `round_win`) into `parser.py`, but the `parse_chunk_response` function body itself has NOT yet been moved. The 2 xfails remain correctly in place.

**Post-impl expected state** (after implementer appends `parse_chunk_response` body, removes xfails, restores parametrize entry):
- 2 xfailed → 2 passed (flip from xfail to pass)
- 1 new parametrize entry `"parse_chunk_response"` → +1 passed for `test_function_or_class_present_in_core_parser` + +1 passed for `test_pia_still_has_symbol_after_carve`
- Net expected: **87 passed, 7 skipped, 0 xfailed**

Note: the 7 skipped tests remain skipped as long as `compute_base_analyzer_version` is not importable from `versioning.py` (`_BASE_VERSION_IMPORTABLE=False`). That is unchanged by P2-B1b.

**C3 guard (new test) on current state**: the implementer's new dual-path imports in `parser.py` correctly import from `fresh_slotlab.trigger_sessions`, `fresh_slotlab.round_classification`, and `fresh_slotlab.round_win` — NOT from `fresh_slotlab.player_impact_analyzer`. `test_no_back_import_to_pia` passes GREEN on this scaffolding commit.

---

## Test files

| File | Tests |
|------|-------|
| `tests/backend/test_analyzer_core_parser.py` | 83 pass + 7 skip + 2 xfail (pre-impl); 87 pass + 7 skip + 0 xfail (post-impl) |

No new test files added. One new test added to the existing file.

---

## Contract coverage map

### C1 — `parse_chunk_response` lives in `core/parser.py`

| Sub-contract | Covering test |
|---|---|
| `def parse_chunk_response` present in `core/parser.py` | `TestCoreParserSymbols::test_parse_chunk_response_is_callable` (currently xfail; flips to PASS after impl) |
| `_REQUIRED_FUNCTIONS_AND_CLASSES` includes `"parse_chunk_response"` | `TestCoreParserSymbols::test_function_or_class_present_in_core_parser[parse_chunk_response]` (currently commented-out parametrize entry; implementer must restore per ticket §6 step 7) |
| `pia.parse_chunk_response IS core_parser.parse_chunk_response` identity | `TestReExportPattern::test_parse_chunk_response_is_same_object_via_re_export` (currently xfail; flips to PASS after impl) |

All three C1 sub-contracts are pre-written and xfail-gated — they will auto-flip to PASS when the implementer performs step 7 (remove xfail decorators + restore parametrize entry).

### C2 — `pia.main()` unchanged behavior (P1-A1 parity)

| Sub-contract | Covering test |
|---|---|
| P1-A1 parity test file exists | `TestP1A1ParityCanary::test_p1_a1_parity_test_file_exists` |
| P1-A1 parity test file is valid Python | `TestP1A1ParityCanary::test_p1_a1_parity_test_file_is_valid_python` |
| `pia.parse_chunk_response` accessible for parity path | `TestP1A1ParityCanary::test_pia_still_has_parse_chunk_response_for_parity_path` |
| **Actual 3-invocation byte-identical parity** | `tests/integration/test_analyzer_three_invocation_parity.py` (not run here; impl-verifier's job per ticket §7 Wave 2) |

C2 is fully covered: the in-file canary asserts structural safety; the integration test asserts behavioral parity. Confirmed the integration test file exists and spawns real subprocesses.

### C3 — Cycle freedom

| Sub-contract | Covering test |
|---|---|
| Static grep: `core/parser.py` has zero `fresh_slotlab.player_impact_analyzer` imports (non-comment lines) | **NEW: `TestSubprocessImportSafety::test_no_back_import_to_pia`** |
| Subprocess import: importing `core.parser` exits rc=0 | `TestSubprocessImportSafety::test_core_parser_subprocess_import_exits_zero` |
| *(Pre-existing soft guard — tautological)* | `TestSubprocessImportSafety::test_core_parser_import_does_not_trigger_pia_side_effects` — NOTE: line 605 has `or True` making the cycle assertion always pass. This test only asserts rc=0 (not cycle absence). The new `test_no_back_import_to_pia` is the authoritative C3 guard. |

**Gap identified and closed**: the existing `test_core_parser_import_does_not_trigger_pia_side_effects` is tautological for cycle detection. The new grep-based test is the correct C3 guard.

### C4 — xfail decorators removed

No test needed for this contract. It is a process-level outcome: the implementer removes the two `@pytest.mark.xfail` decorators and restores the parametrize entry. The test runner outcome (0 xfailed post-impl) is self-evidencing. The impl-verifier confirms by running the suite post-impl.

### C5 — Hash composition rolls forward

| Sub-contract | Covering test |
|---|---|
| `compute_base_analyzer_version()` returns 12-char hex | `TestBaseAnalyzerVersionHash::test_returns_12_char_hex_string` |
| Output is deterministic | `TestBaseAnalyzerVersionHash::test_is_deterministic` |
| Output matches reference sha256 of `core/*.py` | `TestBaseAnalyzerVersionHash::test_matches_reference_implementation` |
| Hash is nonzero after carve | `TestBaseAnalyzerVersionHash::test_hash_is_nonzero_after_parser_carve` |
| **Adding content to parser.py flips the hash** | `TestBaseAnalyzerVersionHash::test_hash_changes_when_parser_py_content_changes` (C8-b inject-bug proof) |
| Hash includes parser.py, not just `__init__.py` | `TestBaseAnalyzerVersionHash::test_hash_includes_parser_py_not_just_init` |
| `compute_effective_analyzer_version` respects base hash input | `test_analyzer_foundation.py::TestComputeEffectiveAnalyzerVersion::test_example6_changing_base_hash_changes_output` |

C5 is fully covered. Note: `TestBaseAnalyzerVersionHash` tests are currently skipped because `_BASE_VERSION_IMPORTABLE=False` in pre-impl state (they require `compute_base_analyzer_version` in `versioning.py`). This is expected; they will pass once the versioning implementation is in place (P2-A1 or P2-B1b).

### C6 — All existing tests pass

| Sub-contract | Covering test |
|---|---|
| Existing test suite files exist on disk | `TestExistingTestSuitesImportable::test_existing_suite_file_exists` (parametrized × 5) |
| Existing test suite files are valid Python | `TestExistingTestSuitesImportable::test_existing_suite_file_valid_python` (parametrized × 5) |
| `test_analyzer_parsing.py` import symbols still work via PIA | `TestExistingTestSuitesImportable::test_test_analyzer_parsing_imports_still_work` |
| `test_chunk_integrity.py` import symbols still work via PIA | `TestExistingTestSuitesImportable::test_test_chunk_integrity_imports_still_work` |
| PIA has all 14 moved symbols (backward compat re-exports) | `TestReExportPattern::test_pia_still_has_symbol_after_carve` (parametrized × 14) |
| PIA has all 8 moved constants (backward compat re-exports) | `TestReExportPattern::test_pia_still_has_constant_after_carve` (parametrized × 8) |

C6 is fully covered by existing tests.

### C7 — No error swallowing added

| Sub-contract | Covering test |
|---|---|
| `parser.py` silent swallow count <= pre-carve PIA baseline (6) | `TestNoSilentSwallows::test_core_parser_no_new_silent_swallows_beyond_pia_baseline` |
| `core/__init__.py` has zero silent swallows | `TestNoSilentSwallows::test_core_init_no_silent_swallows` |

C7 is covered by AST-based static checks. The baseline is set to 6 (pre-existing PIA patterns in the carved range). The test fails if the carve adds any NEW `except: pass` beyond the literal copy.

Note from the brief: "static-grep-checkable." The AST approach is strictly superior to grep for this case (no false positives from comments or strings).

### C8 — Inject-bug TDD

| Inject scenario | Verified by |
|---|---|
| C8-a: delete re-export in PIA → identity test RED | `TestInjectBugC8a_ReExportDeletion::test_inject_delete_reexport_proof` (mechanism proof); actual catch is `TestReExportPattern::test_pia_still_has_symbol_after_carve` |
| C8-b: edit parser.py body → hash flips | `TestBaseAnalyzerVersionHash::test_hash_changes_when_parser_py_content_changes` + `TestInjectBugC8b_HashFlip::test_inject_parser_edit_flips_hash_proof` |
| **C8-c (cycle): back-import in parser.py → test RED** | **NEW: `TestSubprocessImportSafety::test_no_back_import_to_pia`** — inject-bug proof documented below |

---

## Inject-bug verification log

### New test: `test_no_back_import_to_pia`

**What is being guarded**: C3 cycle freedom — `core/parser.py` must not contain any executable import from `fresh_slotlab.player_impact_analyzer`.

**Inject step**: Added the following line to `fresh_slotlab/analyzer/core/parser.py` after the stdlib imports (line 32):

```python
from fresh_slotlab.player_impact_analyzer import parse_rounds  # INJECT_BUG_TEST_SENTINEL
```

**Result (injected)**: `FAILED tests/backend/test_analyzer_core_parser.py::TestSubprocessImportSafety::test_no_back_import_to_pia`

```
AssertionError: C3 CYCLE VIOLATION: core/parser.py contains 1 back-import(s) to fresh_slotlab.player_impact_analyzer.
  parser.py:32: from fresh_slotlab.player_impact_analyzer import parse_rounds  # INJECT_BUG_TEST_SENTINEL
assert 1 == 0
```

**Revert**: Removed the injected line, restoring `core/parser.py` to its pre-inject state.

**Result (restored)**: `PASSED tests/backend/test_analyzer_core_parser.py::TestSubprocessImportSafety::test_no_back_import_to_pia`

Full suite (restored): `83 passed, 7 skipped, 2 xfailed`

### Tautological guard note (pre-existing)

`TestSubprocessImportSafety::test_core_parser_import_does_not_trigger_pia_side_effects` at line 605 has:

```python
assert "pia_imported=True" not in result.stdout or True, (...)
```

The `or True` makes this assertion always vacuously true. The test only provides an rc=0 subprocess check, NOT a cycle guard. The new `test_no_back_import_to_pia` is the authoritative cycle-freedom test (C3). The tautological line is NOT modified (it is existing prod test code; the task scope is test-only additions).

---

## Open gaps

| Gap | Recommendation |
|---|---|
| C4 (xfail removal) has no automated assertion on the xfail count itself | Accepted by design: the test runner surface (0 xfailed) is self-evidencing; impl-verifier confirms by running post-impl. |
| `test_core_parser_import_does_not_trigger_pia_side_effects` cycle assertion is tautological (`or True`) | Documented. The new `test_no_back_import_to_pia` supersedes it for C3. The tautological assertion in the existing test is a pre-existing issue outside this ticket's scope. Flag for impl-critic to note; correction would be to remove the `or True`. |
| C7 `MAX_ALLOWED_SWALLOWS_IN_PARSER = 6` may need updating after `parse_chunk_response` lands | The count of 6 was determined from grep of the P2-B1a carved range. The `parse_chunk_response` body (1857 lines) may contain additional pre-existing `except: pass` patterns from PIA. The implementer must run the suite post-carve and update the baseline constant if needed. This is not a new addition — it is a carry-over of the existing PIA patterns. |
| C2 actual byte-identical parity | Out of scope for this tester pass. Delegated to impl-verifier + `tests/integration/test_analyzer_three_invocation_parity.py`. |

---

## Subprocess vs in-process coverage

| Test | Mode |
|---|---|
| `test_core_parser_subprocess_import_exits_zero` | Subprocess (`python -c`) |
| `test_core_parser_subprocess_no_stderr` | Subprocess (`python -c -W error`) |
| `test_core_init_subprocess_import_exits_zero` | Subprocess (`python -c`) |
| `test_core_parser_import_does_not_trigger_pia_side_effects` | Subprocess (`python -c`) — rc=0 only |
| `test_each_core_module_individually_importable` | Subprocess (`python -c`) × 2 |
| `test_no_back_import_to_pia` | In-process (static grep of file on disk) |
| `test_function_or_class_present_in_core_parser` | In-process (`hasattr` after module import) |
| `test_parse_chunk_response_is_callable` | In-process (xfail; flips post-impl) |
| All hash tests | In-process (file I/O + sha256) |
| All re-export identity tests | In-process (`is` identity check) |
| P1-A1 actual parity | Subprocess (via `test_analyzer_three_invocation_parity.py`) — impl-verifier runs this |

The cycle-freedom contract (C3) is most naturally a static (in-process) grep check because the bug does not require runtime to manifest — a text pattern in the source file is the definitive signal. A subprocess sys.modules check would be weaker because CPython can resolve a cycle without ImportError (partially-initialized module cache). The static grep is both faster and more reliable.
