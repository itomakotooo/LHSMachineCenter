# Phase C4 — Inject-bug evidence

**Date**: 2026-05-27
**Produced by**: impl-tester
**Branch**: `claude/analyzer-unbundle-c2`

Each entry shows: bug location → which test turned RED → reverted → test GREEN.

---

## Bug A — emit() always sets jackpot.applicable=False

**File**: `fresh_slotlab/analyzer/features/machine_mechanics.py`
**Line**: ~324 (MachineMechanics.emit)

**Injected change**:
```python
# Changed from:
jp_applicable = reg.jackpot_applicable
# To:
jp_applicable = False  # BUG_INJECT_A: always False
```

**Test that turned RED**:
`test_c4_machine_mechanics_plugin.py::TestMachineMechanicsEmit::test_emit_jackpot_applicable_from_registry`

**Failure message**:
```
AssertionError: jackpot.applicable must be True (from registry), even when jp_spins=0.
Got: False.
```

**After revert**: GREEN ✓

**What this guards**: The plugin must read jackpot_applicable from the Mechanism Registry, not compute it from raw counters. This is the structural gap #1 fix — old code used `jp_spins > 0` which fails for M275-style PIDs.

---

## Bug B — REGISTERED_FALLBACK_RULES wrong key name

**File**: `fresh_slotlab/analyzer/features/machine_mechanics.py`
**Line**: ~153 (class level)

**Injected change**:
```python
# Changed from:
REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {
    1: {"_detection_source": None}
}
# To:
REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {
    1: {"_detection_src": None}  # wrong key name
}
```

**Test that turned RED**:
`test_c4_machine_mechanics_plugin.py::TestMachineMechanicsClassInvariants::test_registered_fallback_rules_v1`

**Failure message**:
```
{'_detection_src': None}
Right contains 1 more item: {'_detection_source': None}
```

**After revert**: GREEN ✓

**What this guards**: v1 → v2 migration rule must use exact key name `_detection_source`. Wrong key name silently fails to populate the field for v1 summaries loaded by new frontend.

---

## Bug C — Path A jackpot detection removed from MechanismRegistry (CRITICAL — gap #1 guard)

**File**: `fresh_slotlab/analyzer/mechanism_registry.py`
**Line**: ~167 (MechanismRegistry.build Tier 3 Path A)

**Injected change**:
```python
# Changed from:
_path_a: set[str] = set()
for pid_s in payout_id_win:
    try:
        pid_int = int(pid_s)
    except ValueError:
        continue
    if pid_int >= 10000 and pid_s not in scatter_marker_pids:
        _path_a.add(pid_s)
# To:
_path_a: set[str] = set()
# BUG_INJECT_C: skip Path A detection entirely
pass
```

**Test that turned RED**:
`test_c4_m275_gap_1_closed.py::TestM275Gap1JackpotApplicable::test_m275_jackpot_applicable_true`

**Failure message**:
```
AssertionError: jackpot.applicable must be True for M275 (gap #1 closure). Got: False.
Full jackpot block: {"applicable": false, "trigger_spins": 0, "jackpot_ids": [],
"jackpot_id_count": 0, "total_win": 0.0, "rtp_contribution_pp": 0.0,
"_detection_source": "tier3_raw"}
```

**After revert**: GREEN ✓

**What this guards**: Path A (PID >= 10000 detection) is the critical signal for M275-style jackpot machines. Without it, 26 machines silently regress to jackpot.applicable=False despite real jackpot PIDs in payout_id_win. This is the canonical regression test for gap #1 closure.

---

## Bug D — Freespin Tier 2 detection threshold too high (CRITICAL — gap #2 guard)

**File**: `fresh_slotlab/analyzer/mechanism_registry.py`
**Line**: ~206 (MechanismRegistry.build Tier 2 freespin)

**Injected change**:
```python
# Changed from:
if bonus_chain_lengths:
    freespin_applicable = True
# To:
if len(bonus_chain_lengths) > 9999:  # BUG_INJECT_D: threshold too high
    freespin_applicable = True
```

**Test that turned RED**:
`test_c4_m275_gap_2_closed.py::TestM275Gap2FreespinApplicable::test_m275_freespin_applicable_true`

**Failure message**:
```
AssertionError: free_spin.applicable must be True for M275 (gap #2 closure). Got: False.
Full free_spin block: {"applicable": false, "chain_spins": 0, "chain_rate": 0.0,
"retriggers": 0, "max_chain_length": 0, "total_win": 0.0, "rtp_contribution_pp": 0.0,
"_detection_source": "tier2_bonus_chain_lengths_empty"}
```

**After revert**: GREEN ✓

**What this guards**: Tier 2 freespin detection must trigger on any non-empty bonus_chain_lengths list. M275 has ~908 chains (len ~908). Any threshold > 908 silently breaks freespin detection. This is the canonical regression test for gap #2 closure.

---

## Bug E — Path B (JackpotIds union) removed from MechanismRegistry (CRITICAL — NB1 fix guard)

**File**: `fresh_slotlab/analyzer/mechanism_registry.py`
**Line**: ~177 (MechanismRegistry.build Tier 3 Path B)

**Injected change**:
```python
# Changed from:
_path_b: set[str] = jackpot_ids_seen - scatter_marker_pids
jackpot_pid_set = frozenset(_path_a | _path_b)
# To:
_path_b: set[str] = set()  # BUG_INJECT_E: Path B removed
jackpot_pid_set = frozenset(_path_a)  # Path B excluded
```

**Test that turned RED**:
`test_c4_m11_jackpot_ids_union.py::TestM11JackpotIdsUnion::test_m11_jackpot_applicable_true`

**Failure message**:
```
AssertionError: jackpot.applicable must be True for M11 (via JackpotIds raw field).
Got: False.
Full jackpot block: {"applicable": false, "trigger_spins": ..., "jackpot_ids": [...],
"jackpot_id_count": 3, ...}
```

*(Note: jackpot_ids was populated from the accumulator fallback path but applicable was False because jackpot_pid_set was empty — no PIDs in Path A set since M11's 1102/1103/1104 are all < 10000.)*

**After revert**: GREEN ✓

**What this guards**: Path B (JackpotIds raw field union) is the ONLY detection path for M11-style machines whose jackpot PIDs are numerically < 10000. Without Path B, M11 silently regresses to jackpot.applicable=False. This is the canonical regression test for the v3 NB1 surgical fix.

---

## Summary table

| Bug | File:location | Test RED | After revert |
|-----|---------------|----------|--------------|
| A — emit always False | machine_mechanics.py:324 | test_emit_jackpot_applicable_from_registry | GREEN ✓ |
| B — wrong fallback key | machine_mechanics.py:153 | test_registered_fallback_rules_v1 | GREEN ✓ |
| C — Path A removed | mechanism_registry.py:167 | test_m275_jackpot_applicable_true | GREEN ✓ |
| D — threshold > 9999 | mechanism_registry.py:206 | test_m275_freespin_applicable_true | GREEN ✓ |
| E — Path B removed | mechanism_registry.py:177 | test_m11_jackpot_applicable_true | GREEN ✓ |
