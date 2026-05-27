# Phase C6 — Inject-bug evidence

Date: 2026-05-27
Branch: claude/analyzer-unbundle-c2

## Bug A — emit() skips stash read (tests stash-pattern contract)

**Location injected**: `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py`
**Injection**: replaced `stash = summary.pop(_STASH_KEY)` + full bcd passthrough with
  `summary.pop(_STASH_KEY, None); player_impact["bonus_chain_dynamics"] = {}`

**Tests that went RED**:
- `test_c6_bonus_chain_dynamics_plugin.py::TestBonusChainDynamicsEmit::test_emit_reads_stash_overwrites_bonus_chain_dynamics` — KeyError: 'applicable'
- `test_c6_bonus_chain_dynamics_plugin.py::TestM275BonusChainDynamics::test_m275_applicable_true` — KeyError: 'applicable'

**After revert**: 2 passed

---

## Bug B — trigger_marker detection removed (CRITICAL gap #3 guard)

**Location injected**: `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py`
**Injection**: replaced the `is_trigger = pid_str in scatter_marker_pids` conditional block
  with `notes = {"is_trigger_marker": False}` for all rows unconditionally.

**Tests that went RED**:
- `test_c6_gap_3_pid_666_trigger_marker.py::TestPid666TriggerMarker::test_pid_666_is_trigger_marker`
  — AssertionError: pid 666 must have is_trigger_marker=True. notes: {'is_trigger_marker': False}
- `test_c6_gap_3_pid_666_trigger_marker.py::TestTriggerMarkerCount::test_trigger_marker_count_exactly_one`
  — AssertionError: M275 must have exactly 1 trigger marker row. Got 0.
- `test_c6_carve_completion.py::TestGap3TriggerMarker::test_gap_3_pid_666_trigger_marker`
  — AssertionError: Gap #3 not closed: pid 666 must have is_trigger_marker=True.

**After revert**: 3 passed

---

## Bug C — bonus_chain_dynamics removed from M275 manifest (CRITICAL meta guard)

**Location injected**: `slot_designer/configs/machine_manifests/M275.json`
**Injection**: removed "bonus_chain_dynamics" from analyzer_features list
  (plugin no longer runs for M275 → emit() never called → payout_ids_top20 rows lack notes)

**Tests that went RED**:
- `test_c6_carve_completion.py::TestGap3TriggerMarker::test_gap_3_pid_666_trigger_marker`
  — AssertionError: Gap #3 not closed: pid 666 notes: {}
- `test_c6_carve_completion.py::TestGap8PayoutIdsTop20Notes::test_gap_8_payout_ids_top20_rows_have_notes`
  — AssertionError: Gap #8 not closed: payout_ids_top20 rows missing 'notes': pids ['1', '2', '4', '7', '8', '3', '6', '5', '27502', '27504', '27503', '666']
- `test_c6_gap_3_pid_666_trigger_marker.py::TestPid666TriggerMarker::test_pid_666_is_trigger_marker`
  — AssertionError: pid 666 notes: {}

**After revert** (M275.json restored with bonus_chain_dynamics): 3 passed

---

## Summary

| Bug | Invariant guarded | Tests fired RED | Reverted GREEN |
|-----|-------------------|-----------------|----------------|
| A   | Stash pattern — emit reads stash (not empty dict) | 2 | 2 |
| B   | Gap #3 — is_trigger_marker=True for pid 666 | 3 | 3 |
| C   | Manifest registration — plugin must run for M275 | 3 | 3 |
