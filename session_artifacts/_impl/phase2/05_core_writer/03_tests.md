# P2-B3 impl-tester report — `tests/backend/test_analyzer_core_writer.py`

## Verdict: **sufficient**

Writer.py was already landed by impl-implementer when tester ran. All 64 tests execute against the live implementation. 62 pass, 2 skip (C6 hash-composition gated on `versioning.py` export, consistent with parser/aggregator precedent). All four inject-bug proofs confirmed: inject → RED, restore → GREEN.

---

## Test files added

| File | Tests |
|------|-------|
| `tests/backend/test_analyzer_core_writer.py` | 64 (62 pass, 2 skip) |

---

## Pre-impl baseline (writer.py was already present)

Because the implementer landed writer.py before the tester ran, there was no "waiting on impl" skip phase. The pre-impl baseline section is N/A. The suite ran green against the live code from the first full run.

---

## Inject-bug verification log

### C8-a — PIA re-export deletion

**Target contract:** `pia._save_chunk_cache IS writer._save_chunk_cache` (C1 identity).

**Inject:** Commented out `_save_chunk_cache` from the dual-path import block in `fresh_slotlab/player_impact_analyzer.py` lines 219-223 (package-mode arm) and 226-230 (script-mode arm).

**Result → RED:**
```
FAILED TestPIAReExports::test_pia_has_save_chunk_cache
  AssertionError: fresh_slotlab.player_impact_analyzer._save_chunk_cache not found.
FAILED TestPIAReExports::test_pia_save_chunk_cache_is_same_object
  AttributeError: module has no attribute '_save_chunk_cache'
```

**Restored → GREEN:** Both tests pass. Confirmed 2 tests go red on inject.

**Tests guarded:** `test_pia_has_save_chunk_cache`, `test_pia_save_chunk_cache_is_same_object`

---

### C8-b — Override path ignored

**Target contract:** `override_config_md5` / `override_code_md5` appear in envelope verbatim; lookup is not called when either override is set (memory `feedback_md5_granularity_and_stamping.md`).

**Inject:** In `fresh_slotlab/analyzer/core/writer.py` lines 140-141, changed:
```python
config_md5 = override_config_md5 or ""
code_md5 = override_code_md5 or ""
```
to:
```python
config_md5 = ""  # INJECT-BUG C8-b
code_md5 = ""    # INJECT-BUG C8-b
```

**Result → RED:**
```
FAILED TestSaveChunkCacheRoundTrip::test_round_trip_override_path_stamps_localcfg_values
  AssertionError: Override path: expected _config_md5='localcfg_xyz', got ''.
FAILED TestInjectBugC8b_OverridePathIgnored::test_inject_override_ignored_proof_mechanism
  AssertionError: INJECT-BUG PROOF C8-b: override was ignored — got '' but expected 'override_value'.
```

**Restored → GREEN:** Both tests pass.

**Tests guarded:** `test_round_trip_override_path_stamps_localcfg_values`, `test_inject_override_ignored_proof_mechanism`

---

### C8-c — Atomic write cleanup removed

**Target contract:** When `os.replace` fails, the `.tmp` file is cleaned up by the outer `except` block (no lingering partials).

**Inject:** In `fresh_slotlab/analyzer/core/writer.py` lines 188-196, replaced the outer `except` body:
```python
except Exception:  # noqa: BLE001
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except OSError:
        pass
```
with:
```python
except Exception:  # noqa: BLE001
    pass  # INJECT-BUG C8-c: cleanup removed
```

**Verification mechanism:** `test_atomic_write_cleans_up_tmp_on_replace_failure` patches `os.replace` in writer module's namespace to raise `OSError("disk full")`. `Path.write_text()` still runs (pathlib bypasses the mocked `os`), writing a real `.tmp` to disk. Without the cleanup, `.glob("*.tmp")` finds it.

**Result → RED:**
```
FAILED TestAtomicWrite::test_atomic_write_cleans_up_tmp_on_replace_failure
  AssertionError: Lingering .tmp files found after failed os.replace: ['chunk_0000.json.tmp']
```

**Restored → GREEN:** Test passes. Confirmed by direct observation: `list(cache_dir.iterdir())` returns `['chunk_0000.json.tmp']` with inject, `[]` after restore.

**Tests guarded:** `test_atomic_write_cleans_up_tmp_on_replace_failure`

---

### C8-d — Back-import to PIA injected

**Target contract:** writer.py must not contain any `import` or `from ... import` statement referencing `fresh_slotlab.player_impact_analyzer` (C5 cycle freedom).

**Inject:** Added to top of `fresh_slotlab/analyzer/core/writer.py`:
```python
from fresh_slotlab.player_impact_analyzer import compute_analyzer_version as _cv  # INJECT-BUG C8-d
```

**Detection mechanism:** AST-based (not raw-text grep). The test parses writer.py via `ast.parse()` and walks `ast.Import` / `ast.ImportFrom` nodes. This correctly ignores docstring prose that mentions PIA by name (writer.py's module docstring references PIA in lines 6 and 22 — raw grep would false-positive on these; AST does not).

**Result → RED:**
```
FAILED TestCycleFreedom::test_no_back_import_to_pia
  AssertionError: C5 CYCLE VIOLATION: core/writer.py contains 1 back-import(s)
  writer.py:46: from fresh_slotlab.player_impact_analyzer import compute_analyzer_version
```

**Restored → GREEN:** Test passes.

**Tests guarded:** `test_no_back_import_to_pia`, `test_writer_may_import_from_core_parser`

**Important implementation note on C5:** The initial grep-based detection (matching `"fresh_slotlab.player_impact_analyzer" in line`) false-positived on writer.py's own docstring (lines 6 and 22), which mentions PIA by name in prose. Fixed by switching to AST node detection, matching the pattern from `TestCycleFreedom._find_pia_import_nodes`. This is the correct approach for any future cycle-freedom tests.

---

## Coverage map: every brief contract → test

### C1 — Files exist + symbols carved

| Brief requirement | Test |
|-------------------|------|
| `writer.py` file present | `TestFilesExist::test_core_writer_file_exists` |
| `writer.py` is a regular file | `TestFilesExist::test_core_writer_is_a_file` |
| `core/__init__.py` not deleted | `TestFilesExist::test_core_init_still_exists` |
| `_save_chunk_cache` in writer | `TestCoreWriterSymbols::test_symbol_present_in_core_writer[_save_chunk_cache]` |
| `write_summary_json` in writer | `TestCoreWriterSymbols::test_symbol_present_in_core_writer[write_summary_json]` |
| Both are callable | `TestCoreWriterSymbols::test_symbol_is_callable[*]` (parametrized) |
| Signature: `cache_dir` param | `TestCoreWriterSymbols::test_save_chunk_cache_signature_has_cache_dir_param` |
| Signature: `override_config_md5` + `override_code_md5` | `TestCoreWriterSymbols::test_save_chunk_cache_has_override_md5_params` |
| Signature: `summary` + `output_dir` | `TestCoreWriterSymbols::test_write_summary_json_signature_has_summary_and_output_dir` |
| PIA re-exports `_save_chunk_cache` | `TestPIAReExports::test_pia_has_save_chunk_cache` |
| PIA re-exports `write_summary_json` | `TestPIAReExports::test_pia_has_write_summary_json` |
| `pia._save_chunk_cache IS writer._save_chunk_cache` | `TestPIAReExports::test_pia_save_chunk_cache_is_same_object` |
| `pia.write_summary_json IS writer.write_summary_json` | `TestPIAReExports::test_pia_write_summary_json_is_same_object` |
| `CHUNK_CACHE_VERSION` canonical in writer, re-exported by PIA | `TestPIAReExports::test_pia_chunk_cache_version_re_exported_from_writer` |

### C2 — P1-A1 canary

| Brief requirement | Test |
|-------------------|------|
| Parity test file still exists (structural) | `TestP1A1ParityCanary::test_p1_a1_parity_test_file_exists` |
| Full 23/23 parity run | Skipped — impl-verifier's job per ticket §7 Wave 2 |

### C3 — `_save_chunk_cache` semantic preservation

| Brief requirement | Test |
|-------------------|------|
| Non-override: all 13 envelope fields present | `TestSaveChunkCacheRoundTrip::test_round_trip_non_override_path_all_fields_present` |
| Non-override: lookup stub values stamped | `TestSaveChunkCacheRoundTrip::test_round_trip_non_override_path_md5_from_lookup` |
| Non-override: `_payload_sha256` survives `load_chunk_envelope` integrity check | `TestSaveChunkCacheRoundTrip::test_round_trip_non_override_path_payload_sha256_valid` |
| Override path: `override_config_md5` / `override_code_md5` appear in envelope | `TestSaveChunkCacheRoundTrip::test_round_trip_override_path_stamps_localcfg_values` |
| Override partial (config only): `_code_md5` = `""`, not from lookup | `TestSaveChunkCacheRoundTrip::test_round_trip_override_partial_config_only` |
| Envelope `_machine`, `_mode`, `_bet`, etc. correct | `TestSaveChunkCacheRoundTrip::test_round_trip_envelope_machine_mode_bet_fields` |
| `cache_dir=None` → early return, no lookup | `TestSaveChunkCacheRoundTrip::test_round_trip_cache_dir_none_returns_immediately` |
| Atomic: `.tmp` file cleaned up on `os.replace` failure | `TestAtomicWrite::test_atomic_write_cleans_up_tmp_on_replace_failure` |
| Atomic: tmp suffix is `.json.tmp` (not `.tmp.tmp`) | `TestAtomicWrite::test_atomic_write_tmp_suffix_is_dot_tmp` |
| Atomic: no exception propagated on disk full | `TestAtomicWrite::test_atomic_write_no_exception_on_disk_full` |
| `_rawdata_index_update_entry` called with `(rawdata_root, machine, mode, cache_dir)` | `TestRawdataIndexUpdateEntryCalled::test_rawdata_index_update_called_with_correct_args` |
| `_rawdata_index_update_entry` NOT called if `os.replace` fails | `TestRawdataIndexUpdateEntryCalled::test_rawdata_index_update_not_called_if_write_fails` |
| `_rawdata_index_update_entry` failure is silent | `TestRawdataIndexUpdateEntryCalled::test_rawdata_index_update_failure_is_silent` |
| `write_summary_json` creates `player_impact_summary.json` | `TestWriteSummaryJson::test_write_summary_json_creates_file` |
| `write_summary_json` returns `Path` | `TestWriteSummaryJson::test_write_summary_json_returns_path` |
| `write_summary_json` content round-trips | `TestWriteSummaryJson::test_write_summary_json_content_round_trips` |
| `write_summary_json` uses `ensure_ascii=False` | `TestWriteSummaryJson::test_write_summary_json_uses_ensure_ascii_false` |
| `write_summary_json` uses `indent=2` | `TestWriteSummaryJson::test_write_summary_json_uses_indent_2` |

### C4 — Subprocess import safety

| Brief requirement | Test |
|-------------------|------|
| `python -c "import fresh_slotlab.analyzer.core.writer"` rc=0 | `TestSubprocessImportSafety::test_core_writer_subprocess_import_exits_zero` |
| No stderr on import | `TestSubprocessImportSafety::test_core_writer_subprocess_no_stderr` |
| Importing writer does not trigger PIA side effects | `TestSubprocessImportSafety::test_core_writer_import_does_not_trigger_pia_side_effects` |
| Each module individually importable (parametrized) | `TestSubprocessImportSafety::test_each_core_module_individually_importable[*]` |

### C5 — Cycle freedom

| Brief requirement | Test |
|-------------------|------|
| writer.py has zero `import`/`from ... import` nodes referencing PIA | `TestCycleFreedom::test_no_back_import_to_pia` (AST-based) |
| parser.py imports are allowed (confirmed by same AST guard) | `TestCycleFreedom::test_writer_may_import_from_core_parser` |

### C6 — Hash composition

| Brief requirement | Test |
|-------------------|------|
| Adding writer.py flips `compute_base_analyzer_version()` | `TestHashComposition::test_writer_py_included_in_base_version_hash` — SKIPPED (requires_base_version) |
| Placeholder | `TestHashComposition::test_c6_hash_composition_gated_on_versioning` — explicit `pytest.mark.skip` |

### C7 — No new silent swallows

| Brief requirement | Test |
|-------------------|------|
| writer.py has ≤ 3 silent swallows (PIA baseline = 3) | `TestNoSilentSwallows::test_writer_no_new_silent_swallows_beyond_pia_baseline` |
| writer.py has ≥ 1 silent swallow (best-effort guards preserved) | `TestNoSilentSwallows::test_writer_has_exactly_baseline_silent_swallows` |

### C7 — Existing tests not broken

| Brief requirement | Test |
|-------------------|------|
| 7 existing test files still exist | `TestExistingTestSuitesNotBroken::test_existing_suite_file_exists[*]` (parametrized) |
| 7 existing test files parse as valid Python | `TestExistingTestSuitesNotBroken::test_existing_suite_file_valid_python[*]` (parametrized) |
| PIA still exports `_save_chunk_cache`, `CHUNK_CACHE_VERSION`, etc. | `TestExistingTestSuitesNotBroken::test_pia_still_has_chunk_integrity_symbols` |

### C8 — Inject-bug TDD

| Inject scenario | Test | Proven |
|----------------|------|--------|
| Delete PIA re-export → test_pia_has_save_chunk_cache RED | `TestInjectBugC8a_ReExportDeletion::test_inject_delete_reexport_proof_mechanism` | YES |
| Override path ignored → test_round_trip_override_path RED | `TestInjectBugC8b_OverridePathIgnored::test_inject_override_ignored_proof_mechanism` | YES |
| Cleanup removed → lingering .tmp detected | `TestInjectBugC8c_AtomicWriteCleanup::test_inject_missing_cleanup_proof_mechanism` | YES |
| Back-import added → AST guard fires | `TestInjectBugC8d_CycleInjection::test_inject_back_import_proof_mechanism` | YES |

---

## Subprocess vs. in-process coverage

| Contract | Coverage type |
|----------|---------------|
| C3 round-trip tests | In-process (temp dir) |
| C4 subprocess safety | Real subprocess (`python -c`) |
| C5 cycle freedom | Static AST scan (not runtime) |
| C8 inject proofs | In-process mechanism proofs + actual file-edit red/green runs |

Per memory `feedback_perf_claim_needs_e2e_event_stream.md`: C4 uses real subprocess. The chunk cache writer itself is called in-process during sampling (not as a subprocess target), so in-process round-trip tests are the correct primary mode for C3.

---

## Open gaps

1. **C6 hash composition** — fully skipped pending `compute_base_analyzer_version` export from `versioning.py`. The simulation test `test_writer_py_included_in_base_version_hash` is gated on `requires_base_version` marker. Once `versioning.py` exports that function, the skip marker removes and the test runs.

2. **update_chunk_entry best-effort swallow** — writer.py's second inner `try/except Exception: pass` (for `update_chunk_entry`) is covered by the C7 baseline count check (3 swallows allowed). No dedicated functional test for the `update_chunk_entry` path because that function belongs to `fresh_slotlab.chunk_index`, not this ticket's scope. The best-effort silence is verified indirectly: any exception in that block propagates neither to the caller nor prevents the chunk file from being written.

3. **P1-A1 three-invocation parity** — structural canary only (file existence). The actual 23/23 parity run is impl-verifier's job per ticket §7 Wave 2.

---

## Implementation notes discovered during testing

**C5 grep → AST migration:** Raw text grep on `"fresh_slotlab.player_impact_analyzer" in line` false-positives on writer.py's module docstring (lines 6 and 22), which mentions PIA by name as prose documentation. The parser test (`test_no_back_import_to_pia` in `test_analyzer_core_parser.py`) uses the same raw-text approach with `line.lstrip().startswith("#")` filtering — this was safe for parser.py (which had no docstring referencing PIA). For writer.py it was not safe. Solution: AST-based `_find_pia_import_nodes` static method that walks `ast.Import` / `ast.ImportFrom` nodes only. This should be backported to `test_analyzer_core_parser.py` and `test_analyzer_core_aggregator.py` if their modules ever gain docstrings mentioning PIA by package name.

**Dependency injection confirmed:** The implementer correctly used keyword-only arguments (`lookup_machine_md5` and `rawdata_index_update_entry` as `*`-separated kwargs) to avoid the writer → PIA cycle. Tests pass callables inline, confirming the DI contract is testable and working.

**C7 baseline = 3:** The three intentional silent swallows in writer.py (lines 170, 186, 195) match exactly the three in PIA's original `_save_chunk_cache` (lines 1440, 1456, 1465). No new swallows added by the carve.
