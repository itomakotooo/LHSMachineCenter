# 04_verification.md - P2-A2 Manifest loader

Verifier: impl-verifier W2 | Date: 2026-05-18 | Verdict: PARTIAL

## 1. Pytest results

Ticket file: 90 passed, 2 xfailed in 0.24s. Matches tester 03_tests.md: YES.
Both xfail are strict=True, NOT xpass - confirmed.

Full backend suite: 4 failed, 2587 passed, 23 skipped, 3 xfailed in 74.64s
Pre-existing failures (all unrelated to P2-A2):
  [1] test_analyzer_st_split::test_zero_win_but_fired_pid_retained_in_split
      FileNotFoundError: rawdata/M31/mode_1/chunk_0001.json missing in worktree.
      Confirmed pre-existing by running in isolation.
  [2-4] test_t_critical_table_canonical.py (3 tests)
      Pass in isolation (3 passed), fail only in full-suite (test-ordering pollution).
      Confirmed pre-existing.
Zero new regressions introduced by P2-A2.

## 2. Finding 1 - C2 gap: variant analyzer_features direct-set (CONFIRMED)

Reproducer: pytest test_manifest_loader.py::TestC2::test_variant_cannot_override_analyzer_features_directly
Result: XFAIL (strict=True)

Code: resolve_inheritance() lines 177-223 of manifest_loader.py.
merged = copy.deepcopy(parent) overwrites only: machine_id, manifest_version, inherits_from,
4 completeness/metadata fields, per_mode_overrides.
NO guard: if 'analyzer_features' in manifest and inherits_from is not None: raise ...
Variant with direct analyzer_features -> silently accepted (parent value stays), no error.
Spec section 3 C2: 'Variant CANNOT override analyzer_features directly' (must be an error).
impl-critic must rule: raise ManifestValidationError vs silent-ignore.

## 3. Finding 2 - C6 spec ambiguity: is not None vs _UNSET sentinel (CONFIRMED)

Reproducer: pytest test_manifest_loader.py::TestC6::test_mode_override_null_returns_true
Result: XFAIL (strict=True)

Live: resolve_layer4_applicable({trigger_session_pattern: type_1,
  per_mode_overrides: {2: {trigger_session_pattern_override: None}}}, 2) -> False
Expected per section 5.5.6 (null is valid override): True

Code lines 473-474:
  override = mode_block.get('trigger_session_pattern_override')
  if override is not None:  # cannot distinguish absent vs explicit null

Spec contradiction:
  P1 pseudocode: if override is not None (matches implementer)
  Section 5.5.6 table: trigger_session_pattern_override: null is a valid override value
impl-critic must resolve which is authoritative.

## 4. Finding 3 - validate_manifest registry parameter (CONFIRMED)

Code: registry: Any | None = None
Docstring: 'feature_registry module or object with ALL_FEATURES attribute'
Usage line 571: all_feature_ids = {f.FEATURE_ID for f in registry.ALL_FEATURES}
Not a plain list. Tests use _StubRegistry adapter. Deliberate API design, not a bug.
Production use with real feature_registry module works (exposes ALL_FEATURES attribute).

## 5. All 11 validation rules

Rule 1:  lines 560-567. test_rule1_machine_not_in_machines_config: PASS
Rule 2:  lines 570-579. test_rule2_unknown_analyzer_feature_id: PASS
Rule 3:  lines 586-592. Structural check only (non-empty string). Fleet-level check deferred Phase 3.
Rule 4:  lines 595-608. Live: dependency missing -> Rule 4 error. CONFIRMED
Rule 5:  lines 612-635. Live: mode removes RTP_CONTRIBUTION feature -> Rule 5 error. CONFIRMED
Rule 6:  lines 638-670. test_rule6_variant_override_true_is_error: PASS
Rule 7:  lines 674-689. test_rule7_expected_paid_st_empty_is_error: PASS
Rule 8:  lines 693-708. Live: complete=True + RTP feature absent -> Rule 8 error. CONFIRMED
Rule 9:  lines 711-721. Live: declared vs observed mismatch -> Rule 9 error; match -> ok. CONFIRMED
Rule 10: lines 725-738. test_rule10 (3 tests): PASS
Rule 11: lines 742-751. test_rule11 (4 tests): PASS

pytest TestC5ValidateManifest11Rules: 11 tests PASS

## 6. resolve_completeness verbatim match to spec section 5.5.7

Line-by-line vs spec lines 553-573:
  _UNSET = object()                   -> line 61 YES
  underlying_complete = ...           -> line 400 YES
  override = ...get(..., _UNSET)      -> line 401 YES
  if override is _UNSET: return ...   -> lines 402-403 YES
  if override is False: return False  -> lines 404-405 YES
  raise ManifestValidationError(...)  -> lines 407-411 YES (verbatim message)

Live output: 'MV3: console_diagnostic_complete_override: true is not permitted.
Variants cannot elevate completeness above their underlying.
Underlying MU3 is the authoritative source.'
Matches spec error message exactly.

## 7. Subprocess import safety

Command: python -c 'import fresh_slotlab.analyzer.manifest_loader' -> rc=0, stdout=OK
Test test_subprocess_import_no_side_effects: PASS

## 8. Subprocess vs in-process coverage

90 in-process tests (C1-C8). TestC7 spawns real subprocess: PASS.
manifest_loader.py is pure file-read + dict-manipulation. In-process is correct coverage level
(feedback_perf_claim_needs_e2e_event_stream.md targets batch workers, not loader modules).

## 9. md5 / version invariants

Not applicable. P2-A2 has no cache write paths.

## 10. Frontend changes

Not applicable. Backend-only.

## 11. Regressions in untouched areas

Zero new regressions. 4 backend failures are pre-existing.
All P2-A2 files are new-untracked. No existing files modified.

## 12. Stop reasons for PARTIAL

Gap 1 (C2 xfail): No raise when variant sets analyzer_features directly.
  Spec forbids it; implementation silently ignores. Missing error hides authoring mistakes.
  impl-critic must rule on fix.

Gap 2 (C6 xfail): is not None vs _UNSET sentinel.
  Explicit trigger_session_pattern_override: null cannot clear base pattern.
  Spec contradiction between P1 pseudocode and section 5.5.6 table.
  impl-critic must resolve which is authoritative.

Both xfail(strict=True). No xpass occurred.

## 13. Summary

Check                                            | Result
90 pass + 2 xfail strict (NOT xpass)            | CONFIRMED
Finding 1 (C2: no guard for direct af)           | CONFIRMED
Finding 2 (C6: is not None / null ambiguity)     | CONFIRMED
Finding 3 (registry: module/.ALL_FEATURES)       | CONFIRMED
All 11 validation rules implemented              | YES (rule 3 structural-only)
resolve_completeness verbatim match spec 5.5.7   | YES
Subprocess import safe rc=0                      | YES
New regressions from P2-A2                       | ZERO
Pre-existing failures                            | 4