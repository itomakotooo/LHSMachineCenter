# Phase C1 — Inject-Bug Evidence

Date: 2026-05-25
Tester: impl-tester (Claude agent)

## Protocol

Per memory/feedback_enumerate_safety_paths.md: each test must be proven to
catch its claimed regression by running inject-bug → RED → revert → GREEN.

---

## Bug 1: PipelineContext frozen=True removal

**Test file**: `tests/analyzer/test_pipeline_context.py`
**Tests affected**: `TestPipelineContextIsFrozen` (3 tests)

**Bug injected**: `pipeline_context.py` line 83
- Changed `@dataclass(frozen=True)` to `@dataclass(frozen=False)`

**RED result**:
```
FAILED TestPipelineContextIsFrozen::test_frozen_raises_on_mutation
  Failed: DID NOT RAISE any of (FrozenInstanceError, AttributeError)
FAILED TestPipelineContextIsFrozen::test_frozen_raises_on_new_attr
  Failed: DID NOT RAISE any of (FrozenInstanceError, AttributeError)
FAILED TestPipelineContextIsFrozen::test_frozen_mechanism_registry_field
  Failed: DID NOT RAISE any of (FrozenInstanceError, AttributeError)
3 failed
```

**Revert**: Restored `@dataclass(frozen=True)`

**GREEN result**: 3 passed

---

## Bug 2: BankruptcySimulation bankruptcy_probe overwrite

**Test file**: `tests/analyzer/test_c1_byte_identical_m14.py`
**Tests affected**: `TestM14BankruptcySimulation::test_bankruptcy_probe_equals_tiers`

**Bug injected**: `bankruptcy_simulation.py` emit()
- Added line after `player_impact["bankruptcy_probe"] = bankruptcy_rows`:
  `player_impact["bankruptcy_probe"] = []  # BUG: overwrites with empty list`

**RED result**:
```
FAILED TestM14BankruptcySimulation::test_bankruptcy_probe_equals_tiers
  AssertionError: bankruptcy_probe must be identical to bankruptcy_simulation.tiers
  assert [] == [{'bankroll_multiplier': 10, ...}]
1 failed
```

**Revert**: Removed the injected overwrite line

**GREEN result**: 1 passed

---

## Bug 3: MechanismRegistry jackpot_applicable = True

**Test file**: `tests/analyzer/test_pipeline_context.py`
**Tests affected**: `TestMechanismRegistryInitialState` (2 tests)

**Bug injected**: `pipeline_context.py` MechanismRegistry.__init__
- Changed `self.jackpot_applicable: bool = False` to `True`

**RED result**:
```
FAILED TestMechanismRegistryInitialState::test_all_applicable_flags_false
  AssertionError: jackpot_applicable must be False in C1 placeholder
  assert True is False
FAILED TestMechanismRegistryInitialState::test_summary_dict_falsy_applicable_values
  assert True is False
2 failed
```

**Revert**: Restored `self.jackpot_applicable: bool = False`

**GREEN result**: 4 passed

---

## Bug 4: Cycle detection removed from topological_sort

**Test file**: `tests/analyzer/test_c1_init_error_surfacing.py`
**Tests affected**: `TestPluginCyclicDependencyError` (4 tests)

**Bug injected**: `topo_sort.py` — removed the cycle detection block:
```python
# Removed:
if len(result) < len(features):
    cycle_nodes = sorted(fid for fid, deg in in_degree.items() if deg > 0)
    raise PluginCyclicDependencyError(cycle=cycle_nodes)
# Replaced with:
return result  # silently returns partial result
```

**RED result**:
```
FAILED TestPluginCyclicDependencyError::test_cycle_a_b_raises
  Failed: DID NOT RAISE PluginCyclicDependencyError
FAILED TestPluginCyclicDependencyError::test_cycle_error_message_is_informative
  Failed: DID NOT RAISE PluginCyclicDependencyError
FAILED TestPluginCyclicDependencyError::test_three_node_cycle_raises
  Failed: DID NOT RAISE PluginCyclicDependencyError
FAILED TestPluginCyclicDependencyError::test_cycle_with_valid_prefix_node_raises
  Failed: DID NOT RAISE PluginCyclicDependencyError
4 failed
```

**Revert**: Restored the full cycle detection block

**GREEN result**: 4 passed

---

## Summary

| Bug | Test | RED | GREEN |
|-----|------|-----|-------|
| frozen=True removed | test_pipeline_context (3) | 3 FAIL | 3 PASS |
| bankruptcy_probe overwrite | test_c1_byte_identical_m14 (1) | 1 FAIL | 1 PASS |
| jackpot_applicable = True | test_pipeline_context (2) | 2 FAIL | 2 PASS |
| cycle detection removed | test_c1_init_error_surfacing (4) | 4 FAIL | 4 PASS |
