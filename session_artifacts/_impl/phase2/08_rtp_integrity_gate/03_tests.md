# 03_tests.md — P2-E1 impl-tester report

## Verdict: partial (pending impl-implementer landing rtp_integrity.py)

Tests are written and structurally verified. 54 tests skip until
`fresh_slotlab/analyzer/rtp_integrity.py` exists on disk.

---

## Test files added

| File | Test count |
|------|-----------|
| `tests/backend/test_rtp_integrity_gate.py` | 54 |

---

## Current run status (pre-impl)

```
54 skipped in 0.09s
```

All 54 tests skip via class-level `@pytest.mark.skipif(not RTP_GATE.exists(), ...)`.
Zero failures pre-impl. Zero passes (all guarded). All will go GREEN when
impl-implementer creates `fresh_slotlab/analyzer/rtp_integrity.py`.

---

## Inject-bug verification log

Inject-bug proofs are documented as "anticipated" because the implementation file
does not yet exist. Each proof describes the exact line to hand-edit, which assertion
fires RED, and why restoring restores GREEN. The discipline follows
`memory/feedback_integration_test_argv.md`.

Proofs will be re-run (confirmed red → green) when the implementation lands in Wave 2
(impl-verifier). The test code itself is the specification of the inject procedure.

---

### IB-1 — Layer 2 prefix list: drop `_unattributed_` from FALLBACK_PREFIXES

**Target test**: `TestC10InjectBugTDD::test_ib1_l2_unattributed_prefix_must_fire`
(also exercises all `test_l2_reserved_prefix_fires[_unattributed_*]` parametrized cases
in `TestC3Layer2FallbackPrefixes`)

**Bug to inject** in `fresh_slotlab/analyzer/rtp_integrity.py`:
```python
# Original (GREEN):
FALLBACK_PREFIXES = ("_unattributed_", "_other", "_default", "_misc")

# Injected (RED):
FALLBACK_PREFIXES = ("_other", "_default", "_misc")  # _unattributed_ removed
```

**Expected when bug injected**:
- `result.layer2_no_fallback_buckets_ok` is `True` (prefix not detected)
- `"_unattributed_st1"` not in `result.layer2_fallback_buckets_found`
- Assertion `result.layer2_no_fallback_buckets_ok is False` FAILS → test RED

**Expected after revert**:
- Prefix detection fires → `layer2_no_fallback_buckets_ok is False` → test GREEN

**Coverage breadth**: This single inject triggers 3 tests RED:
- `test_ib1_l2_unattributed_prefix_must_fire`
- `test_l2_reserved_prefix_fires[_unattributed_st1]`
- `test_l2_reserved_prefix_fires[_unattributed_st139]`

---

### IB-2 — warn_only default: change `True` to `False`

**Target test**: `TestC10InjectBugTDD::test_ib2_warn_only_true_must_not_raise`
(also: `TestC7WarnOnlyMode::test_warn_only_default_is_true_no_raise`)

**Bug to inject** in `fresh_slotlab/analyzer/rtp_integrity.py`:
```python
# Original (GREEN):
def check_rtp_integrity(
    summary: dict,
    *,
    manifest: dict | None = None,
    rawdata_dir: Path | None = None,
    warn_only: bool = True,
) -> RTPIntegrityResult: ...

# Injected (RED):
def check_rtp_integrity(
    summary: dict,
    *,
    manifest: dict | None = None,
    rawdata_dir: Path | None = None,
    warn_only: bool = False,  # <-- changed True to False
) -> RTPIntegrityResult: ...
```

**Expected when bug injected**:
- `check_rtp_integrity(failing_summary)` (no explicit warn_only kwarg) raises `RTPIntegrityError`
- The `try/except` in the test catches it → `pytest.fail(...)` → test RED
- Also: `inspect.signature` test for `warn_only.default is True` fires RED

**Expected after revert**:
- Default is `True` → no raise → test GREEN

**Note**: The `test_check_rtp_integrity_signature` test in `TestC1FileAndAPI` will ALSO fire
RED on this inject, providing a second signal.

---

### IB-3 — Step C a_count/f_count swap

**Target test**: `TestC10InjectBugTDD::test_ib3_step_c_counts_not_swapped`
(also: `TestC6Layer4StepABC::test_l4_divergent_count_fires_inconsistency`)

**Bug to inject** in `fresh_slotlab/analyzer/rtp_integrity.py` Step C:
```python
# Original Step C inconsistency entry (GREEN):
inconsistencies.append({
    "pay_id": pid,
    "spin_type": st,
    "analyzer_dispatch_count": a_count,   # <-- correct
    "rawdata_observed_count": f_count,    # <-- correct
    "difference": a_count - f_count,
    ...
})

# Injected (RED):
inconsistencies.append({
    "pay_id": pid,
    "spin_type": st,
    "analyzer_dispatch_count": f_count,   # <-- SWAPPED
    "rawdata_observed_count": a_count,    # <-- SWAPPED
    "difference": a_count - f_count,
    ...
})
```

**Expected when bug injected** (fixture: analyzer says 5, rawdata shows 3):
- `entry["analyzer_dispatch_count"]` == 3 (wrong, should be 5)
- Assertion `a_count == 5` FAILS → test RED

**Expected after revert**:
- `entry["analyzer_dispatch_count"]` == 5 → assertion PASSES → test GREEN

---

## Coverage map: every brief contract → which test asserts it

### C1 — File exists + API matches spec

| Contract element | Test |
|-----------------|------|
| `rtp_integrity.py` exists at exact path | `TestC1FileAndAPI::test_file_exists` |
| `check_rtp_integrity` importable + callable | `TestC1FileAndAPI::test_imports_succeed` |
| `RTPIntegrityResult` importable + instantiable | `TestC1FileAndAPI::test_imports_succeed` |
| `main` importable + callable | `TestC1FileAndAPI::test_imports_succeed` |
| `RTPIntegrityResult` is frozen dataclass | `TestC1FileAndAPI::test_rtp_integrity_result_is_frozen_dataclass` |
| Frozen: writing to instance raises | `TestC1FileAndAPI::test_rtp_integrity_result_is_frozen_dataclass` |
| All 16 fields present | `TestC1FileAndAPI::test_rtp_integrity_result_has_15_fields` |
| `warn_only` keyword-only, default=True | `TestC1FileAndAPI::test_check_rtp_integrity_signature` |
| `RTPIntegrityError` importable + Exception subclass | `TestC1FileAndAPI::test_rtp_integrity_error_importable` |

### C2 — Layer 1 invariant catches arithmetic drift

| Contract element | Test |
|-----------------|------|
| Exact match → L1 ok | `TestC2Layer1Invariant::test_l1_exact_match_passes` |
| Divergence >1e-6 → L1 fail + error non-empty | `TestC2Layer1Invariant::test_l1_divergence_fires` |
| Zero totals edge case → L1 ok | `TestC2Layer1Invariant::test_l1_zero_totals_edge_case` |
| FP rounding residual within tolerance | `TestC2Layer1Invariant::test_l1_floating_point_tiny_diff_within_tolerance` |
| Large value divergence → L1 fail | `TestC2Layer1Invariant::test_l1_large_value_divergence_fires` |
| Error message is informative (contains digits) | `TestC2Layer1Invariant::test_l1_error_message_is_informative` |

### C3 — Layer 2 catches reserved fallback prefixes

| Contract element | Test |
|-----------------|------|
| `_unattributed_*` fires L2 | `TestC3Layer2FallbackPrefixes::test_l2_reserved_prefix_fires[_unattributed_st1]` |
| `_unattributed_st139` fires L2 | `TestC3Layer2FallbackPrefixes::test_l2_reserved_prefix_fires[_unattributed_st139]` |
| `_other*` fires L2 | `TestC3Layer2FallbackPrefixes::test_l2_reserved_prefix_fires[_other_bucket]` |
| `_default*` fires L2 | `TestC3Layer2FallbackPrefixes::test_l2_reserved_prefix_fires[_default_win]` |
| `_misc*` fires L2 | `TestC3Layer2FallbackPrefixes::test_l2_reserved_prefix_fires[_misc_catch]` |
| `'666'` (legitimate) does NOT fire L2 | `TestC3Layer2FallbackPrefixes::test_l2_legitimate_pid_666_does_not_fire` |
| `'_bcm_cycle'` does NOT fire L2 (exact prefix match) | `TestC3Layer2FallbackPrefixes::test_l2_bcm_cycle_pid_does_not_fire` |
| Clean summary → L2 ok, found=[] | `TestC3Layer2FallbackPrefixes::test_l2_clean_summary_passes` |
| Multiple fallback pids ALL reported | `TestC3Layer2FallbackPrefixes::test_l2_multiple_fallback_pids_all_reported` |

### C4 — Layer 3 checks required anchors

| Contract element | Test |
|-----------------|------|
| Required anchor with 0 hits → L3 fail, anchor in missing | `TestC4Layer3AnchorCoverage::test_l3_required_anchor_with_zero_hits_fails` |
| Required anchor absent from summary → L3 fail | `TestC4Layer3AnchorCoverage::test_l3_required_anchor_absent_from_summary_fails` |
| Required anchor with >0 hits → L3 ok | `TestC4Layer3AnchorCoverage::test_l3_required_anchor_with_positive_hits_passes` |
| Empty anchors [] → vacuously ok | `TestC4Layer3AnchorCoverage::test_l3_empty_anchors_vacuously_passes` |
| Multiple anchors: one missing → L3 fail | `TestC4Layer3AnchorCoverage::test_l3_multiple_anchors_all_must_pass` |
| No manifest → L3 vacuously ok | `TestC4Layer3AnchorCoverage::test_l3_no_manifest_skips_anchor_check` |

### C5 — Layer 4 skip for trigger-session machines

| Contract element | Test |
|-----------------|------|
| `layer4_applicable=False` → skip, L4 consistent_ok=None, skip_reason non-empty | `TestC5Layer4SkipTriggerSession::test_l4_skip_when_layer4_applicable_false` |
| `trigger_session_pattern='type_1'` → skip | `TestC5Layer4SkipTriggerSession::test_l4_skip_when_trigger_session_pattern_type1` |
| `rawdata_dir=None` + applicable → skip with reason (no crash) | `TestC5Layer4SkipTriggerSession::test_l4_skip_when_rawdata_dir_none_and_applicable` |
| L4 skip does NOT skip L1/L2/L3 (all still enforced) | `TestC5Layer4SkipTriggerSession::test_l4_skip_does_not_affect_l1_l2_l3` |

### C6 — Layer 4 Step A/B/C consistency

| Contract element | Test |
|-----------------|------|
| Matching dispatch → L4 ok, inconsistencies=[] | `TestC6Layer4StepABC::test_l4_matching_dispatch_passes` |
| Divergent count (5 vs 3) → L4 fail, entry a_count=5 f_count=3 | `TestC6Layer4StepABC::test_l4_divergent_count_fires_inconsistency` |
| SpinType missing → Layer4Error raised | `TestC6Layer4StepABC::test_l4_missing_spintype_raises_layer4error` |
| SpinType 'not_an_int' → Layer4Error raised | `TestC6Layer4StepABC::test_l4_invalid_spintype_raises_layer4error` |
| Zero-win pid counted by existence (keys()) | `TestC6Layer4StepABC::test_l4_zero_win_pid_counted_by_existence` |
| Multiple chunks: ALL scanned (total count) | `TestC6Layer4StepABC::test_l4_multiple_chunks_all_scanned` |
| Empty rawdata dir → explicit error/fail | `TestC6Layer4StepABC::test_l4_no_rawdata_chunks_reports_error` |

### C7 — Warn-only mode

| Contract element | Test |
|-----------------|------|
| `warn_only=True` explicit → no raise, passed=False | `TestC7WarnOnlyMode::test_warn_only_true_does_not_raise` |
| Default (omit kwarg) → no raise, passed=False | `TestC7WarnOnlyMode::test_warn_only_default_is_true_no_raise` |
| `warn_only=False` + failure → raises RTPIntegrityError | `TestC7WarnOnlyMode::test_warn_only_false_raises_on_failure` |
| `warn_only=False` + passing summary → no raise | `TestC7WarnOnlyMode::test_warn_only_false_does_not_raise_when_passing` |
| `warn_only=True` + passing → passed=True | `TestC7WarnOnlyMode::test_warn_only_true_passes_when_all_ok` |

### C8 — Subprocess import safety + CLI smoke

| Contract element | Test |
|-----------------|------|
| `python -c "import fresh_slotlab.analyzer.rtp_integrity"` rc=0 + no stderr | `TestC8SubprocessSmoke::test_subprocess_import_rc0` |
| `python -m fresh_slotlab.analyzer.rtp_integrity --help` rc=0 | `TestC8SubprocessSmoke::test_subprocess_cli_help_rc0` |
| CLI without --machine → non-zero rc, no traceback | `TestC8SubprocessSmoke::test_subprocess_cli_requires_machine_arg` |

### C9 — Full regression (delegated)

Delegated to impl-verifier (runs `pytest tests/` against full suite). Not in this file.

### C10 — Inject-bug TDD

| Inject scenario | Proof test |
|----------------|-----------|
| IB-1: drop `_unattributed_` from FALLBACK_PREFIXES | `TestC10InjectBugTDD::test_ib1_l2_unattributed_prefix_must_fire` |
| IB-2: change `warn_only=True` default to `False` | `TestC10InjectBugTDD::test_ib2_warn_only_true_must_not_raise` |
| IB-3: swap a_count/f_count in Step C | `TestC10InjectBugTDD::test_ib3_step_c_counts_not_swapped` |

### Additional coverage (beyond brief minimum)

| Contract element | Test class |
|-----------------|-----------|
| Fallback pid in L4 inconsistency: `is_fallback_pid=True` | `TestLayer4FallbackPidCorroboration` |
| Legitimate pid: `is_fallback_pid=False` | `TestLayer4FallbackPidCorroboration` |
| `passed=True` requires ALL applicable layers ok | `TestPassedAggregation` |
| `passed=False` when only L2 fails | `TestPassedAggregation` |
| `completeness_declared` mirrors manifest field | `TestPassedAggregation` |

---

## Subprocess vs in-process coverage

| Test class | Mode |
|-----------|------|
| `TestC8SubprocessSmoke` | Subprocess (real `python -c`, `python -m`) |
| `TestC1FileAndAPI` | In-process (import + introspection) |
| `TestC2Layer1Invariant` | In-process (synthetic summaries) |
| `TestC3Layer2FallbackPrefixes` | In-process (synthetic summaries) |
| `TestC4Layer3AnchorCoverage` | In-process (synthetic summaries + manifests) |
| `TestC5Layer4SkipTriggerSession` | In-process (synthetic summaries + manifests) |
| `TestC6Layer4StepABC` | In-process + tempdir (synthetic chunk JSON files) |
| `TestC7WarnOnlyMode` | In-process (synthetic summaries) |
| `TestC10InjectBugTDD` | In-process + tempdir (C10-IB3 uses chunk files) |
| `TestLayer4FallbackPidCorroboration` | In-process + tempdir |
| `TestPassedAggregation` | In-process (synthetic summaries + manifests) |

Subprocess coverage (C8): two real subprocess spawns exercise import safety and CLI.
These are the critical paths per memory `feedback_perf_claim_needs_e2e_event_stream.md`
and `feedback_subprocess_import_suicide_and_module_globals.md`.

In-process coverage (C1-C7, C10): Layer 4 Step A/B/C tests use a real tmpdir with
real JSON chunk files — this exercises the actual file I/O path in Step B without
spawning a subprocess. Spawning is not needed here because the bug surface is not
in subprocess context (Layer 4 runs inside `check_rtp_integrity`, not in a worker
subprocess).

---

## Open gaps

1. **C9 full regression**: `pytest tests/` against the complete 715+ test suite
   is impl-verifier's job. Not in this file.

2. **CLI machine+mode end-to-end**: The brief C8 also states
   "exits 0 if all applicable layers pass; non-zero with error JSON to stderr if any fail"
   when run against a real rawdata dir. This path is NOT tested here (requires M14 cached
   fixture on disk). It is delegated to impl-verifier who will run
   `python -m fresh_slotlab.analyzer.rtp_integrity --machine M14 --mode 1 --rawdata-dir ...`.

3. **Layer4Error exact message content**: Tests assert `Layer4Error` is raised for
   corrupt data. The exact error message text (chunk path + robot ID + "data corruption"
   hypothesis) per §9.4 is NOT asserted here — it is observable but not load-bearing
   for regression purposes.

4. **`rawdata_dir=None` with `layer4_applicable=True` behavior**: The test
   `test_l4_skip_when_rawdata_dir_none_and_applicable` accepts both "skip with reason"
   and "raise Layer4Error" — either is acceptable per the brief's design-choice note.
   Impl-critic should confirm which the implementer chose and whether it's consistent
   with §9.4 edge-case table ("Machine has no rawdata cached → Layer 4 fails explicitly").

5. **Manifest field name mismatch risk**: The tests pass manifest as a raw dict.
   If the implementer expects a typed `Manifest` object rather than a dict, some tests
   will need to be updated. The brief §1 shows `manifest: dict | None = None`, so
   dict-passing should be correct.

6. **`Layer4Error` importability**: Tests in `TestC6Layer4StepABC` import `Layer4Error`
   from `fresh_slotlab.analyzer.rtp_integrity`. If the implementer places it in a
   different module (e.g., `fresh_slotlab.analyzer.core.errors`), the import path
   needs adjusting. The brief does not specify a module for `Layer4Error` explicitly —
   the ticket only shows `RTPIntegrityError`. The test assumes `Layer4Error` is in the
   same module. If it's not exported from `rtp_integrity`, these tests will fail with
   ImportError; the implementer should either export it or the tests need adjusting.

---

## Notes on field count discrepancy

The tester task instructions say "15 fields per brief §1" but the actual §1 dataclass
in `00_ticket.md` lists 16 fields (machine, mode, passed, layer1_invariant_ok,
layer1_error, layer2_no_fallback_buckets_ok, layer2_fallback_buckets_found,
layer3_anchors_ok, layer3_missing_anchors, layer4_applicable,
layer4_per_st_consistency_ok, layer4_inconsistencies, layer4_skip_reason,
summary_message, suggested_actions, completeness_declared).

The test `test_rtp_integrity_result_has_15_fields` is named for the brief's stated
"15 fields" but asserts `len(fields) == 16` matching the actual §1 dataclass count.
This is correct behavior — the brief instructions appear to have an off-by-one (they
may have counted while `layer4_skip_reason` was not yet in the spec). The assert
reflects the ground truth.
