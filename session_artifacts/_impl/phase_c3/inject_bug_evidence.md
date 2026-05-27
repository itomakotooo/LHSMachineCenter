# Phase C3 — Inject-Bug Evidence

> **Date**: 2026-05-27
> **Agent**: impl-tester
> **Per**: memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)

## Summary Table

| Bug | File:Change | Tests That Went RED | RED Count | Revert → GREEN |
|---|---|---|---|---|
| A: emit() always empty shape | `payouts_by_spin_type.py`: `shape = {}` unconditionally | `test_emit_shape_populated`, `test_emit_shape_keyed_n_of_a_kind`, `test_c3_new_fields_not_all_none` (subprocess) | 3 | ✓ |
| B: parser drops col_set | `parser.py`: remove `payout_id_col_set[_c3pid_s].add(_c3col)` | `test_at_least_one_row_has_3x3_columns` (M275 subprocess), `test_m14_covered_columns_nonempty` (M14 subprocess) | 2 | ✓ |
| C: is_trigger_marker always False | `payouts_by_spin_type.py`: `"is_trigger_marker": False` | `test_trigger_marker_line_id_minus1_only_win_zero` (unit), `test_pid_666_is_trigger_marker_true` (M275 subprocess ×2) | 3 | ✓ |
| D: hit_count always 0 | `payouts_by_spin_type.py`: `"hit_count": 0` | `test_legacy_fields_byte_identical_vs_c2_smoke` (M275), `test_legacy_fields_byte_identical_vs_c2_smoke` (M14) | 2 | ✓ |

## Detailed Evidence

### Bug A: emit() always emits empty shape

**Injection**: In `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` emit(),
changed:
```python
shape: dict[str, int] = {
    f"{mc}_of_a_kind": cnt
    for mc, cnt in sorted(mc_dist.items())
} if mc_dist else {}
```
to:
```python
shape: dict[str, int] = {}  # INJECT-BUG-A: always empty
```

**RED output** (3 tests):
- `test_c3_enrichment.py::TestC3EmitEnrichment::test_emit_shape_populated` — AssertionError: Expected '3_of_a_kind' in shape
- `test_c3_enrichment.py::TestC3EmitEnrichment::test_emit_shape_keyed_n_of_a_kind` — AssertionError: Unexpected shape keys: set()
- `test_c3_byte_identical_legacy_fields_m275.py::TestM275C3LegacyFieldsByteIdentical::test_c3_new_fields_not_all_none` — AssertionError: No rows have a populated 'shape' dict

**Revert → GREEN**: All 3 tests passed.

---

### Bug B: parser drops payout_id_col_set append

**Injection**: In `fresh_slotlab/analyzer/core/parser.py`, replaced:
```python
for _c3pos in _c3rec.get("positions", []):
    _c3col = (_c3pos + 1) // 100 - 1
    if _c3col >= 0:
        payout_id_col_set[_c3pid_s].add(_c3col)
```
with:
```python
pass  # payout_id_col_set not updated
```

**RED output** (2 subprocess tests — unit test does NOT catch this):
- `test_c3_byte_identical_legacy_fields_m275.py::TestM275C3LegacyFieldsByteIdentical::test_at_least_one_row_has_3x3_columns` — AssertionError: No rows have covered_columns==[0,1,2]
- `test_c3_byte_identical_legacy_fields_m14.py::TestM14C3LegacyFieldsByteIdentical::test_m14_covered_columns_nonempty` — AssertionError: M14 pid 6 has empty covered_columns

Note: The unit test `test_emit_covered_columns_populated` PASSED even with the bug
(it uses synthetic acc data that bypasses parser). This confirms that subprocess
tests are mandatory per `memory/feedback_perf_claim_needs_e2e_event_stream.md`.

**Revert → GREEN**: Both subprocess tests passed.

---

### Bug C: is_trigger_marker always False

**Injection**: In `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` emit(),
changed:
```python
"is_trigger_marker": is_trigger,
```
to:
```python
"is_trigger_marker": False,  # INJECT-BUG-C: always False
```

**RED output** (3 tests):
- `test_c3_enrichment.py::TestC3TriggerMarkerDetection::test_trigger_marker_line_id_minus1_only_win_zero` — AssertionError: pid '666' with line_id=-1 only and win=0 must be is_trigger_marker=True. Got: False
- `test_c3_trigger_marker_m275.py::TestM275Pid666TriggerMarker::test_pid_666_is_trigger_marker_true` — AssertionError: M275 pid '666' must have notes.is_trigger_marker=True. Got: False
- `test_c3_byte_identical_legacy_fields_m275.py::TestM275C3Pid666TriggerMarker::test_pid_666_is_trigger_marker_true` — AssertionError: M275 pid 666 must have is_trigger_marker=True

**Revert → GREEN**: All 3 tests passed.

---

### Bug D: hit_count legacy field overwritten (always 0)

**Injection**: In `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` emit(),
changed:
```python
"hit_count": st_hits,
```
to:
```python
"hit_count": 0,  # INJECT-BUG-D: always zero
```

**RED output** (2 tests):
- `test_c3_byte_identical_legacy_fields_m275.py::TestM275C3LegacyFieldsByteIdentical::test_legacy_fields_byte_identical_vs_c2_smoke` — Legacy field diffs: ST126_free/8/hit_count: C2=710 vs C3=0, ... (all rows)
- `test_c3_byte_identical_legacy_fields_m14.py::TestM14C3LegacyFieldsByteIdentical::test_legacy_fields_byte_identical_vs_c2_smoke` — 7 regressions: ST1_paid/1/hit_count: C2=254 vs C3=0, ...

**Revert → GREEN**: Both byte-identical tests passed.

## Conclusion

All 4 inject-bug cycles passed: RED (with bug) → GREEN (reverted). The C3 test
suite catches regressions in:
1. Shape computation (emit-level)
2. Covered columns (parser-level, subprocess-only)
3. Trigger marker detection (both unit and subprocess)
4. Legacy field integrity (byte-identical, subprocess-only)
