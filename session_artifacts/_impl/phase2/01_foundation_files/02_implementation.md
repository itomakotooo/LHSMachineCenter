# 02_implementation.md — ticket P2-A1 Foundation files

## Round 2 — Spec-alignment to 04_v5 §5.2 (current)

**Verdict**: pass

**Trigger**: impl-critic round 1 found that round-1 deviated from `04_v5 §5.2` spec. Main session rewrote the brief's §3 C1 to spec-verbatim. Round 2 re-anchors all files to the spec.

---

### Round 2 files moved/created/changed

| File | Action | Lines | Brief §§ | Notes |
|---|---|---|---|---|
| `fresh_slotlab/analyzer/features/__init__.py` | CREATED | 9 | §3 C1 | New `features/` subpackage marker; no side effects |
| `fresh_slotlab/analyzer/features/_base.py` | CREATED | 217 | §3 C1, 04_v5 §5.2 verbatim | ABC-based `AnalyzerFeature`; replaces Protocol |
| `fresh_slotlab/analyzer/_stub_features.py` | REWRITTEN | 102 | §3 C1, §7 Wave 1 | Stubs now subclass ABC, implement extract/reduce/emit |
| `fresh_slotlab/analyzer/feature_registry.py` | REWRITTEN | 152 | §3 C3-C4, 04_v5 §5.5.2 | `get_features_for_machine(machine_id, manifest)` manifest-list form |
| `fresh_slotlab/analyzer/__init__.py` | UPDATED | 13 | §1 (package marker) | Updated docstring to reference new `features/_base` subpackage |

**Unchanged** (correct per critic round 1):
- `fresh_slotlab/analyzer/versioning.py` — `compute_effective_analyzer_version` algorithm exactly matches `04_v5 §4.1`; not touched
- `fresh_slotlab/analyzer/feature_protocol.py` — kept for backward compat while impl-tester round-2 test migration completes; old round-1 Protocol

**Total round-2 files moved/created: 2 (features/ subpackage), rewritten: 3**

---

### Round 2 brief-section traceability

| Code change | Brief §3 (round 2) | Arch citation |
|---|---|---|
| `class AnalyzerFeature(ABC)` in `features/_base.py` | §3 C1 "ABC (`from abc import ABC, abstractmethod`) — not a Protocol" | 04_v5 §5.2 verbatim |
| `FEATURE_ID: ClassVar[str] = ""` | §3 C1 "Was: `NAME` → Now: `FEATURE_ID`" | 04_v5 §5.2 line 329 |
| `SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()` | §3 C1 "Add 4 missing ClassVars" | 04_v5 §5.2 line 330 |
| `REQUIRES: ClassVar[tuple[str, ...]] = ()` | §3 C1 "Add 4 missing ClassVars" | 04_v5 §5.2 line 332 |
| `RTP_CONTRIBUTION: ClassVar[bool] = False` | §3 C1 "CRITICAL — Wave 2e RTP gate references this" | 04_v5 §5.2 line 333 |
| `REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}` | §3 C1 "Add 4 missing ClassVars" | 04_v5 §5.2 line 334 |
| `@abstractmethod extract(self, parse_state, chunk_dict) -> dict` | §3 C1 "Was: `aggregate` → Now: `extract(self, parse_state, chunk_dict)`" | 04_v5 §5.2 line 336-337 |
| `@abstractmethod reduce(self, prev_acc, this_acc) -> Any` | §3 C1 "ADD `reduce(self, prev_acc, this_acc)`" | 04_v5 §5.2 line 339-340 |
| `@abstractmethod emit(self, final_acc, summary: dict) -> None` | §3 C1 "Was: `finalize` → Now: `emit`" | 04_v5 §5.2 line 342-343 |
| `@classmethod compute_hash(cls) -> str` | §3 C1 "ADD `@classmethod compute_hash(cls)` per spec lines 345-348" | 04_v5 §5.2 lines 345-348 |
| `features/` subpackage (`__init__.py` + `_base.py`) | §3 C1 "Rename file: `feature_protocol.py` → `features/_base.py`" | 04_v5 §5.2 comment "# fresh_slotlab/analyzer/features/_base.py (NEW)" |
| `get_features_for_machine(machine_id, manifest)` manifest-list form | §3 C1 "Applicability semantic (changed): `manifest.analyzer_features` list (declarative)" | 04_v5 §5.5.2 |
| Stubs subclass `AnalyzerFeature(ABC)` + implement `extract/reduce/emit` | §3 C1 "Rewrite the 4 stub features" | ticket §7 Wave 1 |
| `NeverAppliesStubFeature` → `NeverDeclaredStubFeature` (FEATURE_ID never in any manifest) | §3 C1 applicability semantic change | 04_v5 §5.5.2 |
| `register()` checks `isinstance(feature, AnalyzerFeature)` (ABC-based) | §3 C3 | ticket §3 C3 |
| Idempotency by `FEATURE_ID` (was `NAME`) | §3 C3 | ticket §3 C3 |
| `manifest=None` stub behavior documented | §3 C4 "can accept `manifest: dict | None = None` with documented stub behavior" | ticket §3 C4 |
| No import-time side effects in all new files | §3 C5 | memory `feedback_subprocess_import_suicide_and_module_globals.md` |

---

### Round 2 API spec alignment vs 04_v5 §5.2

```
04_v5 §5.2 spec:                          features/_base.py (round 2):
class AnalyzerFeature(ABC):           →   class AnalyzerFeature(ABC):  ✓
  FEATURE_ID: ClassVar[str] = ""      →     FEATURE_ID: ClassVar[str] = ""  ✓
  SCHEMA_KEYS: ClassVar[tuple] = ()   →     SCHEMA_KEYS: ClassVar[tuple[str,...]] = ()  ✓
  SCHEMA_VERSION: ClassVar[int] = 1   →     SCHEMA_VERSION: ClassVar[int] = 1  ✓
  REQUIRES: ClassVar[tuple] = ()      →     REQUIRES: ClassVar[tuple[str,...]] = ()  ✓
  RTP_CONTRIBUTION: ClassVar[bool]=F  →     RTP_CONTRIBUTION: ClassVar[bool] = False  ✓
  REGISTERED_FALLBACK_RULES: {}       →     REGISTERED_FALLBACK_RULES: ClassVar[dict] = {}  ✓
  @abstractmethod extract(...)→dict   →     @abstractmethod extract(...) -> dict  ✓
  @abstractmethod reduce(...)→Any     →     @abstractmethod reduce(...) -> Any  ✓
  @abstractmethod emit(...)→None      →     @abstractmethod emit(...) -> None  ✓
  @classmethod compute_hash()->str    →     @classmethod compute_hash() -> str  ✓
    hexdigest()[:12]                  →       hexdigest()[:12]  ✓
```

All 11 spec elements matched verbatim.

---

### Round 2 pytest results

**Foundation test file (57 tests, round-2 test suite from impl-tester)**: 57/57 PASSED

```
tests/backend/test_analyzer_foundation.py  57 passed in 0.32s
```

Note: The impl-tester's inject-bug tests mutate source files during their run (write `[:11]` to versioning.py, remove `@abstractmethod`, etc.) and then restore them. Running the suite without clearing `.pyc` files can cause stale bytecode to produce false failures. Running with `python -B` or after `find fresh_slotlab -name "*.pyc" -delete` gives 57/57.

**Broader suite (backend, excluding pre-existing failures)**:

```
2440 passed, 23 skipped, 1 deselected, 1 xfailed — 0 new failures introduced
```

Pre-existing failures (NOT caused by round 2, documented in round 1):
1. `test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split` — missing rawdata fixture `rawdata/M31/mode_1/chunk_0001.json` in this worktree
2. `test_t_critical_table_canonical.py` (3 tests) — test-ordering pollution from concurrent thread; passes alone and in isolation; not caused by my changes

---

### Round 2 contract verification

| Contract | Status | Evidence |
|---|---|---|
| C1: ABC (`from abc import ABC`) — NOT Protocol | PASS | `issubclass(AnalyzerFeature, ABC)` → True |
| C1: `FEATURE_ID` ClassVar (not `NAME`) | PASS | `TestAnalyzerFeatureClassVars::test_old_name_attribute_absent` PASS |
| C1: `SCHEMA_KEYS, REQUIRES, RTP_CONTRIBUTION, REGISTERED_FALLBACK_RULES` ClassVars | PASS | `TestAnalyzerFeatureClassVars` 6/6 PASS |
| C1: `extract, reduce, emit` abstractmethods (not `applies_to, aggregate, finalize`) | PASS | `TestAnalyzerFeatureABC` 5/5 PASS; old methods absent tests PASS |
| C1: TypeError at instantiation for missing abstractmethod | PASS | `TestAnalyzerFeatureABC::test_subclass_missing_*` 3/3 |
| C1: `compute_hash()` returns 12-char hex | PASS | `TestComputeHashClassmethod` 5/5 PASS |
| C1: `RTP_CONTRIBUTION` present (Wave 2e gate dependency) | PASS | Default `False`; AttributeError if absent — this ClassVar is present on ABC |
| C2: 12-char hex, deterministic, sorted | PASS | `TestComputeEffectiveAnalyzerVersion` 11/11 |
| C3: ALL_FEATURES empty on import | PASS | `TestFeatureRegistry::test_all_features_empty_on_fresh_import` |
| C3: `register()` idempotent by FEATURE_ID | PASS | `TestFeatureRegistry::test_register_same_feature_id_is_idempotent` |
| C4: `get_features_for_machine(machine_id, manifest)` manifest-list form | PASS | `TestGetFeaturesForMachine` 5/5 PASS |
| C4: `manifest=None` returns all (documented stub) | PASS | Implementation + docstring; no test for stub path (correct — it's future behavior) |
| C5: subprocess import rc=0 for all new module paths | PASS | `TestNoImportTimeSideEffects` 7/7 PASS (includes `features._base`) |
| C6: inject-bug ABC drop → TypeError fires | PASS | `TestInjectBugC1ABCDrop` 5/5 PASS |
| C6: inject-bug `[:11]` → length assertion fires | PASS | `TestInjectBugC2HashLength` 2/2 PASS |
| C6: inject-bug dedup removal → idempotency fires | PASS | `TestInjectBugC3SilentDedup` 1/1 PASS |
| C6: inject-bug manifest-list enforcement | PASS | `TestInjectBugC4ManifestFiltering` 1/1 PASS |

---

### Round 2 open issues / out-of-scope

1. `feature_protocol.py` (round-1 Protocol) kept in place for backward compat during test migration. Will be removed once impl-tester round-2 fully replaces all test imports. Flag for impl-verifier to remove.

2. `compute_base_analyzer_version()` (sha256 of `core/*.py`) — still out of scope per §4. Wave 2b.

3. `compute_feature_hashes()` — still out of scope per §4. Wave 2b.

4. `_stub_features.py` is testing-only; confirmed not imported by production code.

5. The `manifest=None` stub behavior in `get_features_for_machine` should be removed in Phase 3 when real manifests ship. Documented in registry docstring.

---

### Round 2 risk notes

- **Low risk overall**: new subpackage + rewrites to new files only. `feature_protocol.py` kept intact.
- **`feature_registry.py` now imports from `features._base` not `feature_protocol`**: any code that still imports `AnalyzerFeature` from `feature_protocol` and passes it to `register()` will get `TypeError` (old Protocol stubs not ABC subclasses). This is intentional and correct — old stubs are rewritten.
- **Stale `.pyc` files from inject-bug testing**: impl-tester's inject-bug suite mutates source files during verification. Running pytest without clearing pyc can cause false failures. Mitigation: run `python -B` or delete `__pycache__` before final verification.
- **`RTP_CONTRIBUTION` is load-bearing**: Wave 2e RTP gate does `feature.RTP_CONTRIBUTION` — absent ClassVar raises `AttributeError`. All ABC subclasses inherit `False` default, so unless explicitly overridden this is safe.

---

## Round 1 (historical — deviated from spec; superseded by Round 2 above)

**Verdict**: pass (round 1 tests only)

---

### Round 1 files created

| File | Lines | Brief §§ | Notes |
|---|---|---|---|
| `fresh_slotlab/analyzer/__init__.py` | 11 | §1 (package marker) | Package marker only; docstring lists sub-modules |
| `fresh_slotlab/analyzer/feature_protocol.py` | 105 | §3 C1, §2 → 04_v5 §5.2 | `@runtime_checkable` Protocol with NAME/SCHEMA_VERSION/applies_to/aggregate/finalize |
| `fresh_slotlab/analyzer/versioning.py` | 73 | §3 C2, §2 → 04_v5 §4.1 | `compute_effective_analyzer_version`; exact §4.1 algorithm |
| `fresh_slotlab/analyzer/feature_registry.py` | 115 | §3 C3-C4, §2 → 04_v5 §5.2 | `ALL_FEATURES` list + `register()` + `get_features_for_machine()` |
| `fresh_slotlab/analyzer/_stub_features.py` | 113 | §7 Wave 1 ("4 stub features") | Stubs for testing; NOT registered at import time |

**Total new files (round 1): 5**

---

### Round 1 open issues (now addressed in round 2)

1. **Protocol API surface vs 04_v5 §5.2 discrepancy** — FIXED in round 2. Round 1 used `NAME/applies_to/aggregate/finalize`; spec uses `FEATURE_ID/extract/reduce/emit`. Round 2 aligns to spec.
2. `compute_base_analyzer_version()` — still out of scope. Wave 2b.
3. `compute_feature_hashes()` — still out of scope. Wave 2b.
4. `_stub_features.py` testing-only — confirmed still holds.
