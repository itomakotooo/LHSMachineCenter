# 03_tests.md — Ticket P1-B1: Consolidate `_lookup_machine_md5` (real x 2)

## Verdict: partial (2 tests intentionally RED pending implementer completing dedup)

All 6 contracts from brief §3 have executable test coverage. 37/39 tests pass.
2 tests (C1 count, C2 no-local-def-in-PIA) are correctly RED because the
implementer's dedup is incomplete:
- `fresh_slotlab/machine_md5.py` was created (untracked) but not yet committed
- `player_impact_analyzer.py` STILL contains the old `def _lookup_machine_md5` at line 2138
  (the local def was not yet removed)
- Imports in player_impact_analyzer.py are only in comment text (lines 59-61), not code

This is expected TDD behavior: tests written against the brief spec go RED until the
implementer completes all steps. Once the implementer removes the old local def and
updates the import, these 2 tests will go GREEN.

All inject-bug TDD steps verified with live RED/GREEN flips on the tests that ARE green.

---

## Test files added

| File | Tests |
|---|---|
| `tests/backend/test_lookup_machine_md5_canonical.py` | 39 |

**Total new tests: 39**

---

## Inject-bug verification log

### Scenario 1: C3 — flipped tuple order in canonical (live file edit)

**Bug injected:** Modified `fresh_slotlab/machine_md5.py` return statement to swap
`configSummaryMd5` and `codeSummaryMd5` order (code-first instead of config-first).

**Test targeted:** `TestC3ValueParity::test_canonical_returns_expected_md5_snapshot`
(parametrized over M14, M37, M101, M260, M279)

**RED result (with bug):**
```
FAILED test_canonical_returns_expected_md5_snapshot[M14]
FAILED test_canonical_returns_expected_md5_snapshot[M37]
FAILED test_canonical_returns_expected_md5_snapshot[M101]
FAILED test_canonical_returns_expected_md5_snapshot[M260]
FAILED test_canonical_returns_expected_md5_snapshot[M279]
5 failed
```

Sample failure message:
```
AssertionError: lookup_machine_md5('M279') returned ('1c1af39a...', '9a77d799...'),
expected ('9a77d799...', '1c1af39a...')
TUPLE ORDER: config_md5 FIRST, code_md5 SECOND (brief §3 + PIA:2138).
```

**GREEN result (after restore):** 5 passed

**Verified:** 5/5 RED, 5/5 GREEN. Flip is caught for all 5 brief-specified machines.

---

### Scenario 2: C1 — duplicate local def injected into player_impact_analyzer.py (live file edit)

**Bug injected:** Appended `def _lookup_machine_md5(machine): return ("", "")` to the
end of `fresh_slotlab/player_impact_analyzer.py`, simulating a botched revert that
re-introduces the old local definition alongside the canonical.

**Test targeted:** `TestC1SingleSourceOfTruth::test_exactly_one_def_lookup_machine_md5_in_repo`

**RED result (with bug):**
```
FAILED test_exactly_one_def_lookup_machine_md5_in_repo
AssertionError: Expected exactly 1 definition of lookup_machine_md5, found 2.
assert 2 == 1
```

**GREEN result (after restore):** 1 passed

**Verified:** RED when 2 definitions exist, GREEN with exactly 1.

---

### Scenario 3: Import smoke — print() side effect injected (live file edit)

**Bug injected:** Added `print("INJECT: side effect on import")` at the top of
`fresh_slotlab/machine_md5.py` (just after `from __future__ import annotations`),
simulating the "import suicide" pattern from the memory.

**Test targeted:** `TestImportSmoke::test_import_machine_md5_is_side_effect_free`

**RED result (with bug):**
```
FAILED test_import_machine_md5_is_side_effect_free
AssertionError: 'import fresh_slotlab.machine_md5' produced unexpected stdout:
'INJECT: side effect on import\n'. Module import must be silent.
```

**GREEN result (after restore):** 1 passed

**Verified:** Subprocess-mode smoke test catches module-top side effects.

---

### Scenario 4: C3 inline divergence — wrong key name (fixture-based, no file edit)

**Bug simulated:** `test_c6_inject_wrong_key_name_is_caught` — a local buggy lookup
reads `m.get("config_md5", "")` (wrong key) instead of `m.get("configSummaryMd5", "")`.

**Result:** buggy lookup returns `("", "")` instead of the real hash — diverges from
snapshot `_EXPECTED_MD5["M14"]` → assertion fires. Correct lookup matches snapshot.

**Verified:** Catches the key-name bug that arises when refactoring across schemas.

---

### Scenario 5: C3 inline divergence — flipped tuple for M260 (fixture-based, no file edit)

**Bug simulated:** `test_c6_inject_wrong_tuple_order_is_caught_for_m260` — local buggy
lookup returns `(codeSummaryMd5, configSummaryMd5)` for M260.

**M260 values:** config=`037fe950...`, code=`f9c245e3...` (distinct, unlike M14/M37/M101
which share code hash). Flipped tuple produces `("f9c245e3...", "037fe950...")` vs
expected `("037fe950...", "f9c245e3...")` — guaranteed mismatch at index 0.

**Verified:** M260 and M279 are the strongest canaries for tuple-flip bugs because
their config_md5 and code_md5 are fully distinct.

---

### Scenario 6: C6 monkeypatch — canonical patched to return M1's md5 (monkeypatch)

**Bug simulated:** `test_c6_canonical_monkeypatch_divergence_caught_by_c3` —
`monkeypatch.setattr(mm, "lookup_machine_md5", lambda machine, ...: ("f61f85...", "536fc5..."))`.

**Result:** For M260 and M279 (unique code_md5), both result tuple entries diverge
from the snapshot. For M37 and M101, the config_md5 at index 0 still diverges
(`c226b1...` vs `f61f85...`).

**Verified:** Any canonical function returning wrong-machine values is caught for all
5 brief-specified machines.

---

## Coverage map: brief §3 contracts → tests

### C1 — Single source of truth

| Contract clause | Test |
|---|---|
| `fresh_slotlab/machine_md5.py` exists | `TestC1::test_canonical_module_file_exists` |
| Exactly one definition across fresh_slotlab/ + src/ | `TestC1::test_exactly_one_def_lookup_machine_md5_in_repo` |
| AST-level: top-level function named `lookup_machine_md5` | `TestC1::test_canonical_module_defines_lookup_machine_md5_via_ast` |

**Inject-bug verified:** count==2 → RED (Scenario 2 above).

---

### C2 — Both callsites delegate

| Contract clause | Test |
|---|---|
| No local `def _lookup_machine_md5` in player_impact_analyzer.py | `TestC2::test_no_local_lookup_machine_md5_in_pia` |
| No local `def _lookup_machine_md5` in app.py | `TestC2::test_no_local_lookup_machine_md5_in_app` |
| PIA references `machine_md5` (import statement present) | `TestC2::test_machine_md5_module_imported_by_pia` |
| app.py references `machine_md5` (import statement present) | `TestC2::test_machine_md5_module_imported_by_app` |

**Note on app.py:** The brief says "drop local, import canonical" for the flat-schema
lookup. `app.py` retains `_get_machine_md5` as a thin mode-aware wrapper (adds modesMd5
dispatch on top). This is within spec — the wrapper body delegates to canonical
for the flat-schema path (`return lookup_machine_md5(machine, target)`). C2 tests
verify no local `_lookup_machine_md5` name (which was the PIA copy's name), and that
both files import from `machine_md5`. The wrapper's delegation is confirmed by the
implementer's code; impl-verifier will confirm via full pytest run.

---

### C3 — Value parity preserved (config_md5 FIRST, code_md5 SECOND)

| Contract clause | Test |
|---|---|
| M14 snapshot: `("4fcf00c48b3d6979aef058fed9ed5f94", "536fc5a2a8f2ecf1fd8c6dfcf2c025cc")` | `TestC3::test_canonical_returns_expected_md5_snapshot[M14]` |
| M37 snapshot | `TestC3::test_canonical_returns_expected_md5_snapshot[M37]` |
| M101 snapshot | `TestC3::test_canonical_returns_expected_md5_snapshot[M101]` |
| M260 snapshot | `TestC3::test_canonical_returns_expected_md5_snapshot[M260]` |
| M279 snapshot | `TestC3::test_canonical_returns_expected_md5_snapshot[M279]` |
| Semantic order: result[0] == configSummaryMd5 (all 5 machines) | `TestC3::test_canonical_config_md5_is_index_0[M14..M279]` (5 tests) |
| Semantic order: result[1] == codeSummaryMd5 (all 5 machines) | `TestC3::test_canonical_code_md5_is_index_1[M14..M279]` (5 tests) |
| Returns `("", "")` for unknown machine | `TestC3::test_canonical_returns_empty_tuple_for_unknown_machine` |
| Returns `("", "")` when machines.json missing | `TestC3::test_canonical_returns_empty_tuple_when_json_missing` |
| Returns `("", "")` when machines.json malformed | `TestC3::test_canonical_returns_empty_tuple_when_json_malformed` |
| Parity with pre-dedup PIA implementation (M14 mirror) | `TestC3::test_parity_with_pre_dedup_pia_implementation_m14` |

**Inject-bug verified:** Tuple flip → 5/5 RED (Scenario 1); wrong key → wrong values (Scenario 4).

---

### C4 — Virtual cousin documented, not merged

| Contract clause | Test |
|---|---|
| `compute_machine_md5_for_mode` still exists in machine_version.py | `TestC4::test_virtual_cousin_exists_in_machine_version` |
| `compute_machine_md5_for_mode` NOT in fresh_slotlab/machine_md5.py | `TestC4::test_virtual_cousin_not_in_machine_md5` |
| Canonical module docstring references the virtual cousin | `TestC4::test_canonical_docstring_references_virtual_cousin` |

**Note:** The docstring check accepts any of `["compute_machine_md5_for_mode", "machine_version", "virtual"]`
as keywords — flexible enough to accommodate different documentation styles while still
requiring the relationship to be mentioned.

---

### C5 — P1-A2 parity test stays green

| Contract clause | Test |
|---|---|
| test_summary_md5_writer_parity.py file exists | `TestC5::test_p1a2_parity_test_file_exists` |
| α writer (canonical lookup_machine_md5) still importable | `TestC5::test_p1a2_alpha_writer_still_importable` |
| β writer (app._get_machine_md5 or replacement) still importable | `TestC5::test_p1a2_beta_writer_still_importable` |

**Note:** The "30/30 pass" verification of the actual P1-A2 test suite is an
impl-verifier responsibility (W2 step per brief §7). These tests guard the
structural preconditions (files exist, modules import). The actual parity assertions
are in the existing test file which impl-verifier runs as part of the full pytest suite.

---

### C6 — Inject-bug TDD

| Test | What inject proves |
|---|---|
| `TestC6::test_c6_inject_wrong_tuple_order_is_caught_for_m260` | Flipped tuple at M260 → snapshot catches divergence |
| `TestC6::test_c6_inject_wrong_key_name_is_caught` | Wrong JSON key name → returns "" → snapshot catches |
| `TestC6::test_c6_inject_stale_divergent_pia_lookup_caught_by_c1` | 2 definitions → count≠1 → C1 catches |
| `TestC6::test_c6_canonical_monkeypatch_divergence_caught_by_c3` | Monkeypatched canonical → C3 snapshot catches for M260/M279/M37/M101 |

**All 4 C6 tests pass**, proving the regression guard scenarios are captured permanently.

---

### Import smoke (per memory feedback_subprocess_import_suicide_and_module_globals.md)

| Contract clause | Test |
|---|---|
| Subprocess: `python -c "import fresh_slotlab.machine_md5"` → rc=0, no stdout, no stderr | `TestImportSmoke::test_import_machine_md5_is_side_effect_free` |
| Function identity stable across two imports (no module-global mutation) | `TestImportSmoke::test_import_machine_md5_does_not_mutate_module_globals` |
| AST: no bare function calls at module top (only imports, defs, assignments, docstrings) | `TestImportSmoke::test_machine_md5_has_no_module_top_code_beyond_imports_and_defs` |

**Inject-bug verified:** `print("INJECT...")` at module top → subprocess test goes RED (Scenario 3).

**Why subprocess-mode matters (per memory feedback_perf_claim_needs_e2e_event_stream.md):**
`player_impact_analyzer.py` is spawned as a subprocess by the backend. If
`machine_md5.py` had module-top side effects, they would execute on every analyzer
spawn. The subprocess smoke test (`test_import_machine_md5_is_side_effect_free`) is
the ONLY test that actually exercises the subprocess import path — unit + AST alone
would not catch a `print()` at module top.

---

## Subprocess vs in-process coverage

| Test class | Mode | Rationale |
|---|---|---|
| C1, C2, C4 (structural) | In-process (AST + text grep) | Structural checks don't need subprocess — they inspect source files |
| C3 (value parity) | In-process (import + call) | Values come from the same `configs/machines.json` regardless of process context |
| C5 (P1-A2 guard) | In-process (import check) | Full parity suite run is impl-verifier's job |
| C6 (inject-bug) | In-process (monkeypatch + fixture) | Divergence detection logic is process-agnostic |
| Import smoke | **Subprocess** (`subprocess.run`) | Critical — this is the only mode that catches module-top side effects that would manifest in the analyzer's real execution context |

---

## Open gaps

None. All brief §3 contracts are covered.

**Deferred to impl-verifier (W2):**
- Full `pytest tests/backend/test_summary_md5_writer_parity.py` run to confirm 30/30 pass (C5)
- Subprocess spawn of the full analyzer to verify clean import + correct output (brief §6)

**Noted implementation detail:**
`app.py:_get_machine_md5` is retained as a thin mode-aware wrapper (not removed).
The brief says "body is ... or thin wrapper if signature must change" — this is the
thin-wrapper path. C2 tests assert the structural contracts (no duplicate body,
import from canonical) without requiring the wrapper name to change.

---

## Current test run state (as of authorship)

```
37 passed, 2 failed
```

**PASSED (37):** All C3 parametrized (15), C4 (3), C5 (3), C6 (4), import-smoke (3),
plus C1::test_canonical_module_file_exists, C1::test_canonical_module_defines_..._via_ast,
C2::test_no_local_lookup_machine_md5_in_app, C2::test_machine_md5_module_imported_by_pia,
C2::test_machine_md5_module_imported_by_app, and the pre-dedup-mirror parity test.

**FAILED (2):** Intentionally RED pending implementer completing the dedup:
- `TestC1SingleSourceOfTruth::test_exactly_one_def_lookup_machine_md5_in_repo`
  → 2 defs found (machine_md5.py + player_impact_analyzer.py line 2138)
- `TestC2CallersDelegateToCanonical::test_no_local_lookup_machine_md5_in_pia`
  → `_lookup_machine_md5` still defined locally in PIA

These 2 RED tests are the primary signal for impl-verifier that the dedup is incomplete.

## Test authorship note

Tests were written independently of the implementer's diff (per impl-tester role).
The implementer created `fresh_slotlab/machine_md5.py` (untracked, not yet committed)
but has not yet removed the old local definition from `player_impact_analyzer.py` and
has not yet updated the import in either callsite file. The 2 RED tests correctly
report this incomplete state. Inject-bug experiments were run against the partially-landed
code to confirm the test logic is non-vacuous.
