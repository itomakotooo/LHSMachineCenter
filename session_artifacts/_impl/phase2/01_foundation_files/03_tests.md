# 03_tests.md — Ticket P2-A1 Foundation files

---

## ROUND 2 UPDATE — spec-aligned ABC API (2026-05-18)

### Verdict

**sufficient**

All 6 contracts (C1-C6) asserted against round-2 spec-aligned API. 57 tests total.
All 57 GREEN against implementer's round-2 code. 7 inject-bug experiments completed.

### Test files (round 2)

| File | Tests |
|------|-------|
| `tests/backend/test_analyzer_foundation.py` | 57 (was 37 in round 1) |

Net new tests in round 2: **+20**

### What changed in round 2

| Aspect | Round 1 | Round 2 |
|--------|---------|---------|
| Import path | `fresh_slotlab.analyzer.feature_protocol` | `fresh_slotlab.analyzer.features._base` |
| Base class | `@runtime_checkable Protocol` | `ABC` |
| Check pattern | `isinstance()` | `TypeError at instantiation` |
| `NAME` | Tested as required attr | Tested as ABSENT (renamed to FEATURE_ID) |
| `applies_to()` | Tested as required method | Tested as ABSENT (manifest-declared) |
| `aggregate()` | Tested as required method | REMOVED; `extract()` tested |
| `finalize()` | Tested as required method | REMOVED; `emit()` tested |
| `reduce()` | Not present | NEW abstractmethod tested |
| ClassVars tested | `NAME`, `SCHEMA_VERSION` | `FEATURE_ID`, `SCHEMA_KEYS`, `SCHEMA_VERSION`, `REQUIRES`, `RTP_CONTRIBUTION`, `REGISTERED_FALLBACK_RULES` |
| `compute_hash()` | Not present | NEW classmethod tested (5 tests) |
| C4 filtering | `applies_to()` predicate | `manifest["analyzer_features"]` list |
| C5 subprocess paths | 4 paths (feature_protocol) | 4 paths (features._base replaces feature_protocol) |
| Regression guards | Round-1 API absent | Explicit tests that `NAME`, `applies_to`, `aggregate`, `finalize` do NOT exist |

### Inject-bug verification log (round 2)

Per memory `feedback_integration_test_argv.md`: every regression test proven red by injecting the bug it claims to catch.

#### C1 inject 1 — remove `@abstractmethod` from `extract`

**Injected**: Changed `@abstractmethod` + `def extract(...)` to plain `def extract(...)` in `fresh_slotlab/analyzer/features/_base.py`.

**Tests that fired RED**:
- `TestAnalyzerFeatureABC::test_subclass_missing_extract_raises_type_error` — `Failed: DID NOT RAISE <class 'TypeError'>`
- `TestInjectBugC1ABCDrop::test_inject_drop_extract_TypeError_fires` — `AssertionError: INJECT-BUG PROOF C1/extract: subclass missing extract() must raise TypeError`

**Restored**: `@abstractmethod` decorator restored. Both tests GREEN.

#### C1 inject 2 — rename `FEATURE_ID` to `NAME` in ABC

**Injected**: Changed `FEATURE_ID: ClassVar[str] = ""` to `NAME: ClassVar[str] = ""` in `_base.py`.

**Tests that fired RED**:
- `TestAnalyzerFeatureClassVars::test_feature_id_default_is_empty_string` — `AssertionError: AnalyzerFeature.FEATURE_ID ClassVar not found. C6 inject-bug: rename FEATURE_ID to NAME → this fires.`
- `TestAnalyzerFeatureClassVars::test_old_name_attribute_absent` — `AssertionError: AnalyzerFeature.NAME attribute found — this should be FEATURE_ID in round 2.`

**Restored**: `FEATURE_ID` restored. Both tests GREEN.

#### C1 inject 3 — `RTP_CONTRIBUTION` default set to `True`

**Injected**: Changed `RTP_CONTRIBUTION: ClassVar[bool] = False` to `= True` in `_base.py`.

**Test that fired RED**:
- `TestAnalyzerFeatureClassVars::test_rtp_contribution_default_is_false` — `AssertionError: RTP_CONTRIBUTION default must be False, got True`

**Restored**: `False` restored. Test GREEN.

#### C1 inject 4 — `compute_hash()` truncated to `[:11]`

**Injected**: Changed `hexdigest()[:12]` to `hexdigest()[:11]` in `compute_hash()` in `_base.py`.

**Tests that fired RED**:
- `TestComputeHashClassmethod::test_compute_hash_returns_12_char_hex_string` — `AssertionError: compute_hash() must return 12-char string, got len=11`
- `TestComputeHashClassmethod::test_compute_hash_matches_sha256_of_source_file` — `AssertionError: compute_hash() mismatch: actual='81c1c7eb3d2' expected='81c1c7eb3d26'`

**Restored**: `[:12]` restored. Both tests GREEN.

#### C2 inject — `compute_effective_analyzer_version` truncated to `[:11]`

**Injected**: Changed `h.hexdigest()[:12]` to `h.hexdigest()[:11]` in `versioning.py`.

**Tests that fired RED**:
- `TestComputeEffectiveAnalyzerVersion::test_returns_12_char_hex_string` — `AssertionError: Expected 12-char hash, got len=11: '8b1e30bc192'`
- `TestComputeEffectiveAnalyzerVersion::test_example1_snapshot` — `AssertionError: E1 snapshot mismatch: got '2da53c98604', expected '2da53c98604d'`

**Restored**: `[:12]` restored. Both tests GREEN. (Same experiment as round 1; confirms unchanged versioning guard still works.)

#### C3 inject — remove FEATURE_ID dedup from `register()`

**Injected**: Replaced the idempotency check block in `feature_registry.register()` with `ALL_FEATURES.append(feature)` (unconditional).

**Test that fired RED**:
- `TestFeatureRegistry::test_register_same_feature_id_is_idempotent` — `AssertionError: After re-registering the same feature by FEATURE_ID, ALL_FEATURES has length 2 instead of 1.`

**Restored**: FEATURE_ID dedup check restored. Test GREEN.

#### C4 inject — manifest filtering replaced by "return all features"

**Injected**: Changed `get_features_for_machine` to `return list(ALL_FEATURES)` (ignores manifest entirely).

**Tests that fired RED**:
- `TestGetFeaturesForMachine::test_filters_by_manifest_analyzer_features_list` — `AssertionError: feat_b must NOT be in result (not in manifest['analyzer_features'])`
- `TestGetFeaturesForMachine::test_empty_manifest_features_returns_empty` — `AssertionError: When manifest['analyzer_features'] is empty, result must be empty. assert 1 == 0`
- `TestInjectBugC4ManifestFiltering::test_inject_applies_to_based_filtering_would_fail` — `AssertionError: feat_b_inject is registered but NOT in manifest — must be excluded.`

**Restored**: manifest-based filtering restored. All tests GREEN.

### Coverage map (round 2) — brief contracts → tests

| Contract | Test(s) |
|----------|---------|
| **C1** — ABC subclass with all 3 abstractmethods instantiates | `TestAnalyzerFeatureABC::test_complete_subclass_instantiates_without_error` |
| **C1** — missing `extract` → TypeError at instantiation | `TestAnalyzerFeatureABC::test_subclass_missing_extract_raises_type_error` |
| **C1** — missing `reduce` → TypeError at instantiation | `TestAnalyzerFeatureABC::test_subclass_missing_reduce_raises_type_error` |
| **C1** — missing `emit` → TypeError at instantiation | `TestAnalyzerFeatureABC::test_subclass_missing_emit_raises_type_error` |
| **C1** — unrelated class is not ABC subclass | `TestAnalyzerFeatureABC::test_unrelated_class_is_not_abc_subclass` |
| **C1** — `FEATURE_ID: ClassVar[str]` default `""` | `TestAnalyzerFeatureClassVars::test_feature_id_default_is_empty_string` |
| **C1** — `SCHEMA_KEYS: ClassVar[tuple]` default `()` | `TestAnalyzerFeatureClassVars::test_schema_keys_default_is_empty_tuple` |
| **C1** — `SCHEMA_VERSION: ClassVar[int]` default `1` | `TestAnalyzerFeatureClassVars::test_schema_version_default_is_one` |
| **C1** — `REQUIRES: ClassVar[tuple]` default `()` | `TestAnalyzerFeatureClassVars::test_requires_default_is_empty_tuple` |
| **C1** — `RTP_CONTRIBUTION: ClassVar[bool]` default `False` (Wave 2e gate) | `TestAnalyzerFeatureClassVars::test_rtp_contribution_default_is_false` |
| **C1** — `REGISTERED_FALLBACK_RULES: ClassVar[dict]` default `{}` | `TestAnalyzerFeatureClassVars::test_registered_fallback_rules_default_is_empty_dict` |
| **C1** — round-2 regression: `NAME` attr ABSENT | `TestAnalyzerFeatureClassVars::test_old_name_attribute_absent` |
| **C1** — round-2 regression: `applies_to()` ABSENT | `TestAnalyzerFeatureClassVars::test_old_applies_to_method_absent` |
| **C1** — round-2 regression: `aggregate()` ABSENT | `TestAnalyzerFeatureClassVars::test_old_aggregate_method_absent` |
| **C1** — round-2 regression: `finalize()` ABSENT | `TestAnalyzerFeatureClassVars::test_old_finalize_method_absent` |
| **C1** — `compute_hash()` exists as classmethod | `TestComputeHashClassmethod::test_compute_hash_exists_as_classmethod` |
| **C1** — `compute_hash()` returns 12-char hex | `TestComputeHashClassmethod::test_compute_hash_returns_12_char_hex_string` |
| **C1** — `compute_hash()` matches sha256 of source file | `TestComputeHashClassmethod::test_compute_hash_matches_sha256_of_source_file` |
| **C1** — `compute_hash()` on subclass reads subclass module | `TestComputeHashClassmethod::test_compute_hash_on_subclass_reads_subclass_module` |
| **C1** — `compute_hash()` is deterministic | `TestComputeHashClassmethod::test_compute_hash_is_deterministic` |
| **C2** — returns 12-char hex string | `TestComputeEffectiveAnalyzerVersion::test_returns_12_char_hex_string` |
| **C2** — E1 snapshot | `TestComputeEffectiveAnalyzerVersion::test_example1_snapshot` |
| **C2** — E2 feature order is sorted | `TestComputeEffectiveAnalyzerVersion::test_example2_feature_order_is_sorted` |
| **C2** — E3 changing one feature hash changes output | `TestComputeEffectiveAnalyzerVersion::test_example3_changing_one_feature_hash_changes_output` |
| **C2** — E4 changing mode changes output | `TestComputeEffectiveAnalyzerVersion::test_example4_changing_mode_changes_output` |
| **C2** — E5 mode=None differs from mode=int | `TestComputeEffectiveAnalyzerVersion::test_example5_mode_none_differs_from_mode_int` |
| **C2** — E6 changing base_hash changes output | `TestComputeEffectiveAnalyzerVersion::test_example6_changing_base_hash_changes_output` |
| **C2** — deterministic | `TestComputeEffectiveAnalyzerVersion::test_deterministic_same_call_same_output` |
| **C2** — feature deduplication | `TestComputeEffectiveAnalyzerVersion::test_feature_deduplication_in_machine_features` |
| **C2** — empty machine_features valid | `TestComputeEffectiveAnalyzerVersion::test_empty_machine_features_uses_only_base_and_mode` |
| **C2** — cross-check vs reference implementation | `TestComputeEffectiveAnalyzerVersion::test_result_matches_reference_implementation` |
| **C3** — ALL_FEATURES empty by default | `TestFeatureRegistry::test_all_features_empty_on_fresh_import` |
| **C3** — register() appends feature | `TestFeatureRegistry::test_register_appends_feature` |
| **C3** — register() idempotent by FEATURE_ID | `TestFeatureRegistry::test_register_same_feature_id_is_idempotent` |
| **C3** — register() preserves ALL_FEATURES reference | `TestFeatureRegistry::test_register_returns_expected_reference` |
| **C3** — register() supports multiple distinct features | `TestFeatureRegistry::test_register_multiple_distinct_features` |
| **C4** — filters by manifest["analyzer_features"] list | `TestGetFeaturesForMachine::test_filters_by_manifest_analyzer_features_list` |
| **C4** — stable registration order within manifest filter | `TestGetFeaturesForMachine::test_stable_registration_order_within_manifest_filter` |
| **C4** — empty registry returns empty list | `TestGetFeaturesForMachine::test_empty_registry_returns_empty_list` |
| **C4** — empty manifest features returns empty | `TestGetFeaturesForMachine::test_empty_manifest_features_returns_empty` |
| **C4** — manifest feature not in registry is silently skipped | `TestGetFeaturesForMachine::test_manifest_feature_not_in_registry_is_silently_skipped` |
| **C5** — subprocess import round-1 modules exits rc=0 | `TestNoImportTimeSideEffects::test_subprocess_import_round1_modules_exits_zero` |
| **C5** — subprocess import features._base exits rc=0 | `TestNoImportTimeSideEffects::test_subprocess_import_features_base_exits_zero` |
| **C5** — no stderr on round-1 modules | `TestNoImportTimeSideEffects::test_subprocess_import_no_stderr_round1` |
| **C5** — each of 4 modules individually importable (×4) | `TestNoImportTimeSideEffects::test_each_module_importable_individually[*]` |
| **C6** — inject drop extract → TypeError fires | `TestInjectBugC1ABCDrop::test_inject_drop_extract_TypeError_fires` |
| **C6** — inject drop reduce → TypeError fires | `TestInjectBugC1ABCDrop::test_inject_drop_reduce_TypeError_fires` |
| **C6** — inject drop emit → TypeError fires | `TestInjectBugC1ABCDrop::test_inject_drop_emit_TypeError_fires` |
| **C6** — inject FEATURE_ID renamed to NAME → ClassVar check fires | `TestInjectBugC1ABCDrop::test_inject_feature_id_renamed_to_name_fails_classvar_check` |
| **C6** — inject RTP_CONTRIBUTION=True → False check fires | `TestInjectBugC1ABCDrop::test_inject_rtp_contribution_default_true_fails_check` |
| **C6** — inject 11-char truncation → length check fires | `TestInjectBugC2HashLength::test_inject_truncate_11_chars_would_fail_length_check` |
| **C6** — snapshot values are 12 chars | `TestInjectBugC2HashLength::test_snapshot_length_guards_truncation` |
| **C6** — inject append-without-dedup → idempotency fires | `TestInjectBugC3SilentDedup::test_inject_unconditional_append_would_fail_idempotency` |
| **C6** — inject applies_to filtering (old API) → manifest guard fires | `TestInjectBugC4ManifestFiltering::test_inject_applies_to_based_filtering_would_fail` |

### Subprocess vs in-process coverage (round 2)

**C5 tests** spawn real subprocesses to catch import-time side effects per memory `feedback_subprocess_import_suicide_and_module_globals.md`. The round-2 `features._base` module path is tested in a dedicated subprocess test plus the parametrized individual-import test.

**C1-C4 tests** run in-process: the contract being tested (ABC machinery, ClassVar defaults, registry filtering) does not require subprocess context — these are pure unit/API tests.

### Open gaps (round 2)

- `compute_base_analyzer_version()` (hashes `core/*.py`) — Wave 2b deliverable, not P2-A1.
- `compute_feature_hashes()` (reads feature source files) — Wave 2b deliverable.
- Per-machine manifest loader — Phase 3 deliverable. The `manifest=None` stub behavior in `get_features_for_machine` is documented in the implementation (`feature_registry.py:144-147` returns all features). **No test currently covers the `manifest=None` path** (P2-A1 R2 critic Q3 correction; an earlier version of this doc incorrectly claimed it was tested). Phase 3 (when real manifest loader lands) should add the test.
- impl-verifier owns full subprocess smoke run; C5 tests here cover from the tester's perspective.
- Backward compat with existing `analyzer.main()` is explicitly out of scope per §4.
- ~~`feature_protocol.py` (round-1 file) still exists; subprocess smoke still passes for it. It may be removed in a later cleanup ticket.~~ **DELETED** by main session per round-2 critic R2 — test migration was complete; backward-compat justification expired; risk of Wave 2b author importing wrong class. File removed; `grep` confirmed no remaining importers.

---

## ROUND 1 (original — preserved below)

### Verdict

**sufficient**

All 6 contracts (C1-C6) asserted. Inject-bug experiments completed for C1, C2, and C3.
37 tests, all GREEN against the implementer's landed code.

---

### Test files added

| File | Tests |
|------|-------|
| `tests/backend/test_analyzer_foundation.py` | 37 |

---

### Inject-bug verification log (round 1)

#### C1 inject — drop `aggregate` from Protocol

**Injected**: Removed the `aggregate` method definition from `AnalyzerFeature` in
`fresh_slotlab/analyzer/feature_protocol.py` (replaced with a comment).

**Test that fired RED**: `TestAnalyzerFeatureProtocol::test_stub_missing_aggregate_fails_isinstance`

**Error**: `AssertionError: Stub missing aggregate() should NOT satisfy isinstance check. … assert True is False`

**Explanation**: Without `aggregate` in the Protocol, `isinstance(_NoAggregate(), AnalyzerFeature)` returns `True` even though the stub doesn't have `aggregate`. The test caught this because it asserts the result is `False`.

**Restored**: `aggregate` method re-added to Protocol. Test goes GREEN.

#### C2 inject — truncate hash to 11 chars

**Injected**: Changed `return h.hexdigest()[:12]` to `return h.hexdigest()[:11]` in
`fresh_slotlab/analyzer/versioning.py`.

**Tests that fired RED**:
- `TestComputeEffectiveAnalyzerVersion::test_returns_12_char_hex_string` — `AssertionError: Expected 12-char hash, got len=11: '8b1e30bc192'`
- `TestComputeEffectiveAnalyzerVersion::test_example1_snapshot` — `AssertionError: E1 snapshot mismatch: got '2da53c98604', expected '2da53c98604d'`

**Explanation**: Both the length check and snapshot check fired simultaneously. The inject proved both are real regressions guards.

**Restored**: `[:12]` restored. Both tests GREEN.

#### C3 inject — remove NAME dedup check from register()

**Injected**: Replaced the idempotency check block in `feature_registry.register()` with
an unconditional `ALL_FEATURES.append(feature)`.

**Test that fired RED**: `TestFeatureRegistry::test_register_same_name_is_idempotent`

**Error**: `AssertionError: After re-registering the same feature by NAME, ALL_FEATURES has length 2 instead of 1. C3 idempotency: register() must not create duplicates. C6 inject-bug: removing the NAME dedup check makes this fire.`

**Explanation**: Without the NAME check, two calls to `register()` with the same stub produced `len == 2`. The test correctly caught this.

**Restored**: NAME dedup check restored. Test GREEN.

---

### Coverage map (round 1) — brief contracts → tests

| Contract | Test(s) |
|----------|---------|
| **C1** — AnalyzerFeature is @runtime_checkable; isinstance works for valid stub | `TestAnalyzerFeatureProtocol::test_protocol_is_runtime_checkable` |
| **C1** — NAME required by Protocol | `TestAnalyzerFeatureProtocol::test_stub_missing_name_fails_isinstance` |
| **C1** — aggregate() required by Protocol | `TestAnalyzerFeatureProtocol::test_stub_missing_aggregate_fails_isinstance` |
| **C1** — finalize() required by Protocol | `TestAnalyzerFeatureProtocol::test_stub_missing_finalize_fails_isinstance` |
| **C1** — applies_to() required by Protocol | `TestAnalyzerFeatureProtocol::test_stub_missing_applies_to_fails_isinstance` |
| **C1** — SCHEMA_VERSION required by Protocol | `TestAnalyzerFeatureProtocol::test_stub_missing_schema_version_fails_isinstance` |
| **C1** — unrelated class is not AnalyzerFeature | `TestAnalyzerFeatureProtocol::test_plain_object_is_not_analyzer_feature` |
| **C2** — returns 12-char hex string | `TestComputeEffectiveAnalyzerVersion::test_returns_12_char_hex_string` |
| **C2** — E1 snapshot (base_hash=abc, features=[f1,f2], mode=1) | `TestComputeEffectiveAnalyzerVersion::test_example1_snapshot` |
| **C2** — E2 feature order is sorted (f1,f2 == f2,f1) | `TestComputeEffectiveAnalyzerVersion::test_example2_feature_order_is_sorted` |
| **C2** — E3 changing one feature hash changes output | `TestComputeEffectiveAnalyzerVersion::test_example3_changing_one_feature_hash_changes_output` |
| **C2** — E4 changing mode changes output | `TestComputeEffectiveAnalyzerVersion::test_example4_changing_mode_changes_output` |
| **C2** — E5 mode=None differs from mode=int | `TestComputeEffectiveAnalyzerVersion::test_example5_mode_none_differs_from_mode_int` |
| **C2** — E6 changing base_hash changes output | `TestComputeEffectiveAnalyzerVersion::test_example6_changing_base_hash_changes_output` |
| **C2** — deterministic (same inputs → same output) | `TestComputeEffectiveAnalyzerVersion::test_deterministic_same_call_same_output` |
| **C2** — feature deduplication (sorted set) | `TestComputeEffectiveAnalyzerVersion::test_feature_deduplication_in_machine_features` |
| **C2** — empty machine_features valid | `TestComputeEffectiveAnalyzerVersion::test_empty_machine_features_uses_only_base_and_mode` |
| **C2** — cross-check vs reference implementation | `TestComputeEffectiveAnalyzerVersion::test_result_matches_reference_implementation` |
| **C3** — ALL_FEATURES empty by default | `TestFeatureRegistry::test_all_features_empty_on_fresh_import` |
| **C3** — register() appends feature | `TestFeatureRegistry::test_register_appends_feature` |
| **C3** — register() is idempotent by NAME | `TestFeatureRegistry::test_register_same_name_is_idempotent` |
| **C3** — register() preserves ALL_FEATURES list reference | `TestFeatureRegistry::test_register_returns_expected_reference` |
| **C3** — register() supports multiple distinct features | `TestFeatureRegistry::test_register_multiple_distinct_features` |
| **C4** — get_features_for_machine filters by applies_to | `TestGetFeaturesForMachine::test_filters_by_applies_to_predicate` |
| **C4** — stable registration order | `TestGetFeaturesForMachine::test_stable_registration_order` |
| **C4** — empty registry returns empty list | `TestGetFeaturesForMachine::test_empty_registry_returns_empty_list` |
| **C4** — no applicable features returns empty list | `TestGetFeaturesForMachine::test_none_applies_to_machine_returns_empty` |
| **C5** — subprocess import all 4 modules exits rc=0 | `TestNoImportTimeSideEffects::test_subprocess_import_all_modules_exits_zero` |
| **C5** — subprocess import emits no stderr | `TestNoImportTimeSideEffects::test_subprocess_import_no_stderr` |
| **C5** — each module individually importable (parametrized ×4) | `TestNoImportTimeSideEffects::test_each_module_importable_individually[*]` |
| **C6** — inject Protocol drop → isinstance False proof | `TestInjectBugC1ProtocolDrop::test_inject_drop_aggregate_isinstance_is_false` |
| **C6** — inject 11-char truncation → length check fires proof | `TestInjectBugC2HashLength::test_inject_truncate_11_chars_would_fail_length_check` |
| **C6** — snapshot values are 12 chars (guards C2 truncation) | `TestInjectBugC2HashLength::test_snapshot_length_guards_truncation` |
| **C6** — inject append-without-dedup → idempotency fires proof | `TestInjectBugC3SilentDedup::test_inject_unconditional_append_would_fail_idempotency` |

---

### Hash composition worked examples

Pre-computed independently via reference implementation before reading implementer's code.
All snapshots match the §4.1 algorithm exactly.

| Example | Inputs | Expected hash | Asserts |
|---------|--------|---------------|---------|
| E1 | base=`abc`, features=[f1→hash1, f2→hash2], mode=1 | `2da53c98604d` | snapshot + 12-char + hex |
| E2 | Same as E1 but features in reversed order [f2, f1] | `2da53c98604d` (same) | sorting invariant |
| E3 | base=`abc`, f1→`CHANGED`, f2→hash2, mode=1 | `c9927743ddae` | feature hash change |
| E4 | base=`abc`, features=[f1,f2], mode=2 | `09b114f7b259` | mode change |
| E5 | base=`abc`, features=[f1,f2], mode=None | `8f0d95353584` | mode=None vs mode=int |
| E6 | base=`CHANGED_BASE`, features=[f1,f2], mode=1 | `3f986f5883b3` | base_hash change |

---

### Subprocess vs in-process coverage (round 1)

**C5 tests** spawn real subprocesses to catch import-time side effects.
**C1-C4 tests** run in-process (pure unit tests against Protocol and registry APIs).
