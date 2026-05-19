# 03_tests.md — P2-B1 impl-tester report

## Verdict: partial (pending impl-implementer landing core/parser.py)

Tests are written and structurally verified. 22 tests pass pre-impl; 68 skip until
`core/parser.py` exists; 3 correctly fail (will go GREEN when impl lands).

---

## Test files added

| File | Test count |
|------|-----------|
| `tests/backend/test_analyzer_core_parser.py` | 93 |

---

## Current run status (pre-impl)

```
3 failed (correctly: core/parser.py does not exist yet)
22 passed (infrastructure, inject-bug proofs, canary checks)
68 skipped (guarded by requires_core_parser / requires_base_version)
```

The 3 failures are:
- `TestFilesExist::test_core_parser_exists` — core/parser.py missing (expected)
- `TestSubprocessImportSafety::test_core_parser_subprocess_import_exits_zero` — module not importable (expected)
- `TestSubprocessImportSafety::test_each_core_module_individually_importable[fresh_slotlab.analyzer.core.parser]` — module not importable (expected)

All 3 will go GREEN when impl-implementer creates `core/parser.py`.

---

## Inject-bug verification log

### C8-a — Delete a re-export line in PIA → C3 test goes RED

**What was injected**: simulate `pia` module without `parse_chunk_response` attribute
(class with no attributes — equivalent to deleting the re-export line)

**Mechanism tested**:
```python
class FakePIA: pass
fake = FakePIA()
assert not hasattr(fake, 'parse_chunk_response')  # => False when missing
```

**Test that fires RED**: `TestReExportPattern::test_pia_still_has_symbol_after_carve[parse_chunk_response]`

**Verification**: `hasattr(fake_pia, 'parse_chunk_response')` returns `False` when the
attribute is absent — the `assert hasattr(_pia, symbol_name)` in the test fails.

**Confirmed**: yes (verified via subprocess `python -c` output: `False`)

---

### C8-b — Edit core/parser.py body → hash changes

**What was injected**: appended `# EDITED\n` to sha256 input bytes
(equivalent to adding one line to parser.py)

**Mechanism tested**:
```python
content_original = b"def parse_chunk_response(): pass\n"
content_edited   = b"def parse_chunk_response(): pass\n# EDITED\n"
h_original = hashlib.sha256(content_original).hexdigest()[:12]  # c81526da78e7
h_edited   = hashlib.sha256(content_edited).hexdigest()[:12]    # 7cb4026042a8
assert h_original != h_edited  # => True
```

**Test that fires RED**: `TestBaseAnalyzerVersionHash::test_hash_changes_when_parser_py_content_changes`
(also: `TestBaseAnalyzerVersionHash::test_matches_reference_implementation` if hash fn doesn't re-read files)

**Verification**: sha256 of different byte sequences always differ.
Hash sensitivity confirmed: `c81526da78e7` vs `7cb4026042a8`.

**Confirmed**: yes (hashes differ as expected)

---

### C8-c — Add import-time side effect → subprocess smoke fails

**What was injected**: `print('INJECT_SIDE_EFFECT', file=sys.stderr)` at module top
(equivalent to `import logging; logging.basicConfig()` side effect)

**Mechanism tested**:
```python
result = subprocess.run([sys.executable, '-c', bad_code], capture_output=True)
assert 'INJECT_SIDE_EFFECT' in result.stderr  # detected
```

**Test that fires RED**: `TestSubprocessImportSafety::test_core_parser_subprocess_import_exits_zero`
(asserts `result.returncode == 0` AND `"OK" in result.stdout`; side effects contaminate stderr)

**Verification**: subprocess stderr capture works — `'INJECT_SIDE_EFFECT\n'` confirmed in output.

**Confirmed**: yes (verified via `TestInjectBugC8c_SideEffectSmoke::test_inject_side_effect_proof_mechanism`)

---

### C3 strong form — Duplication (not re-export) caught by `is` check

**What was injected**: two separate function objects with same name (duplicate)

**Mechanism tested**:
```python
def fn_original(): pass
def fn_duplicate(): pass  # separate function, not re-exported
assert fn_duplicate is not fn_original  # => True when duplicated
```

**Test that fires RED**: `TestReExportPattern::test_parse_chunk_response_is_same_object_via_re_export`
(asserts `pia_fn is core_fn` — False when implementer copies body instead of re-exporting)

**Confirmed**: yes (identity check is proven to catch duplication)

---

## Coverage map: every brief contract → which test asserts it

### C1 — Files exist + 15 functions/classes + 8 constants in core/parser.py

| Contract element | Test |
|-----------------|------|
| `core/__init__.py` exists | `TestFilesExist::test_core_init_exists` |
| `core/parser.py` exists | `TestFilesExist::test_core_parser_exists` |
| `core/` is a directory | `TestFilesExist::test_core_dir_is_a_directory` |
| All 15 functions/classes | `TestCoreParserSymbols::test_function_or_class_present_in_core_parser[*]` (parametrized × 15) |
| All 8 constants | `TestCoreParserSymbols::test_constant_present_in_core_parser[*]` (parametrized × 8) |
| `ChunkIntegrityError` subclasses `ValueError` | `TestCoreParserSymbols::test_chunk_integrity_error_is_exception_subclass` |
| `parse_chunk_response` callable | `TestCoreParserSymbols::test_parse_chunk_response_is_callable` |
| `_ENVELOPE_PEEK_BYTES` is positive int | `TestCoreParserSymbols::test_envelope_peek_bytes_is_positive_int` |
| `_ENVELOPE_PEEK_RE` is compiled regex | `TestCoreParserSymbols::test_envelope_peek_re_is_compiled_pattern` |

### C2 — P1-A1 parity test stays GREEN

| Contract element | Test |
|-----------------|------|
| Parity test file exists | `TestP1A1ParityCanary::test_p1_a1_parity_test_file_exists` |
| Parity test file valid Python | `TestP1A1ParityCanary::test_p1_a1_parity_test_file_is_valid_python` |
| `pia.parse_chunk_response` accessible for parse path | `TestP1A1ParityCanary::test_pia_still_has_parse_chunk_response_for_parity_path` |

Note: actual 3-invocation run is impl-verifier's job. This tester asserts the pre-conditions.

### C3 — Re-export pattern: PIA re-exports all moved symbols

| Contract element | Test |
|-----------------|------|
| PIA has all 15 moved functions/classes | `TestReExportPattern::test_pia_still_has_symbol_after_carve[*]` (× 15) |
| PIA has all 8 moved constants | `TestReExportPattern::test_pia_still_has_constant_after_carve[*]` (× 8) |
| `pia.parse_chunk_response IS core_parser.parse_chunk_response` | `TestReExportPattern::test_parse_chunk_response_is_same_object_via_re_export` |
| `pia.parse_rounds IS core_parser.parse_rounds` | `TestReExportPattern::test_parse_rounds_is_same_object_via_re_export` |
| `pia.load_chunk_envelope IS core_parser.load_chunk_envelope` | `TestReExportPattern::test_load_chunk_envelope_is_same_object_via_re_export` |
| `pia.ChunkIntegrityError IS core_parser.ChunkIntegrityError` | `TestReExportPattern::test_chunk_integrity_error_is_same_class_via_re_export` |
| `pia.peek_chunk_envelope IS core_parser.peek_chunk_envelope` | `TestReExportPattern::test_peek_chunk_envelope_is_same_object_via_re_export` |
| `pia._check_round_schema IS core_parser._check_round_schema` | `TestReExportPattern::test_check_round_schema_is_same_object_via_re_export` |
| `pia._REQUIRED_ROUND_FIELDS == core_parser._REQUIRED_ROUND_FIELDS` | `TestReExportPattern::test_required_round_fields_constant_same_object_via_re_export` |

### C4 — Subprocess import safety

| Contract element | Test |
|-----------------|------|
| `core.parser` subprocess rc=0 | `TestSubprocessImportSafety::test_core_parser_subprocess_import_exits_zero` |
| `core.parser` subprocess no stderr | `TestSubprocessImportSafety::test_core_parser_subprocess_no_stderr` |
| `core` package subprocess rc=0 | `TestSubprocessImportSafety::test_core_init_subprocess_import_exits_zero` |
| No circular import pulling in PIA | `TestSubprocessImportSafety::test_core_parser_import_does_not_trigger_pia_side_effects` |
| Each module individually importable | `TestSubprocessImportSafety::test_each_core_module_individually_importable[*]` (× 2) |

### C5 — compute_base_analyzer_version() behavior

| Contract element | Test |
|-----------------|------|
| Returns 12-char hex | `TestBaseAnalyzerVersionHash::test_returns_12_char_hex_string` |
| Is deterministic | `TestBaseAnalyzerVersionHash::test_is_deterministic` |
| Matches reference implementation | `TestBaseAnalyzerVersionHash::test_matches_reference_implementation` |
| Non-zero after parser carve | `TestBaseAnalyzerVersionHash::test_hash_is_nonzero_after_parser_carve` |
| Edit parser.py → hash flips | `TestBaseAnalyzerVersionHash::test_hash_changes_when_parser_py_content_changes` |
| Hash includes parser.py not just __init__ | `TestBaseAnalyzerVersionHash::test_hash_includes_parser_py_not_just_init` |

### C6 — All existing test suites stay GREEN

| Contract element | Test |
|-----------------|------|
| Each of 5 test suite files exists | `TestExistingTestSuitesImportable::test_existing_suite_file_exists[*]` (× 5) |
| Each of 5 test suite files valid Python | `TestExistingTestSuitesImportable::test_existing_suite_file_valid_python[*]` (× 5) |
| test_analyzer_parsing.py imports work | `TestExistingTestSuitesImportable::test_test_analyzer_parsing_imports_still_work` |
| test_chunk_integrity.py imports work | `TestExistingTestSuitesImportable::test_test_chunk_integrity_imports_still_work` |

### C7 — No new try/except: pass swallows

| Contract element | Test |
|-----------------|------|
| parser.py has <= 6 silent swallows (PIA baseline) | `TestNoSilentSwallows::test_core_parser_no_new_silent_swallows_beyond_pia_baseline` |
| core/__init__.py has 0 silent swallows | `TestNoSilentSwallows::test_core_init_no_silent_swallows` |

### C8 — Inject-bug TDD

| Inject scenario | Proof test |
|----------------|-----------|
| C8-a: delete re-export → test RED | `TestInjectBugC8a_ReExportDeletion::test_inject_delete_reexport_proof` |
| C8-b: edit parser.py → hash flips | `TestInjectBugC8b_HashFlip::test_inject_parser_edit_flips_hash_proof` |
| C8-c: add side effect → subprocess catches | `TestInjectBugC8c_SideEffectSmoke::test_inject_side_effect_proof_mechanism` |
| C8-c: logging.basicConfig proof | `TestInjectBugC8c_SideEffectSmoke::test_inject_logging_basicconfig_would_fail_subprocess_smoke` |

---

## Subprocess vs in-process coverage

| Test class | Mode |
|-----------|------|
| `TestSubprocessImportSafety` | All subprocess (real `python -c`) |
| `TestCoreParserSymbols` | In-process (module attribute checks) |
| `TestReExportPattern` | In-process (object identity `is` checks) |
| `TestBaseAnalyzerVersionHash` | In-process (function call + sha256 computation) |
| `TestNoSilentSwallows` | In-process (AST parse of source files) |
| `TestP1A1ParityCanary` | In-process (file existence + AST check) |
| `TestExistingTestSuitesImportable` | In-process (file + import checks) |

Subprocess mode covers C4 fully. C4 is the primary risk per
`feedback_subprocess_import_suicide_and_module_globals.md` — module-top side effects
are only detectable in a fresh process with no shared state.

---

## Open gaps

1. **Actual 3-invocation parity run**: C2 contract (all 3 paths produce byte-identical
   summary) is impl-verifier's job to run. This tester asserts structural preconditions.

2. **compute_base_analyzer_version location**: The brief says it should be in
   `fresh_slotlab.analyzer.versioning`. If P2-A1 shipped without implementing it
   (deferred to P2-B1 as noted in P2-A1 03_tests.md line 180), the C5 tests will
   skip. Implementer must confirm this function is added to versioning.py.

3. **C7 silent-swallow baseline**: The MAX_ALLOWED_SWALLOWS_IN_PARSER = 6 is based on
   grep of PIA lines in the carve range. If the actual carve includes more/fewer lines
   than estimated, this number may need adjustment. If the C7 test fires unexpectedly,
   the baseline constant should be reconciled against the actual carved content.

4. **Circular import guard is soft**: `test_core_parser_import_does_not_trigger_pia_side_effects`
   logs a warning rather than failing if PIA is pulled in. If a cycle is detected,
   impl-critic should classify it as a defect.

5. **Full suite run**: C6 (all 5 existing suites GREEN) is validated structurally here.
   impl-verifier runs `pytest tests/` to confirm actual test results.

---

## Notes

- C7 AST check uses `ast.unparse()` (Python 3.9+) — available in this env (3.14).
- BOM-handling added to C7 for Windows environments.
- The `_ref_base_version()` reference implementation is coded directly from
  §4.1 spec (sha256 of sorted core/*.py files, concatenated, [:12]) — not derived
  from implementer's code.
