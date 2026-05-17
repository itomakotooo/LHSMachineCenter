# 03_tests.md — P1-C1 Remaining module globals + pure-function extraction

## Verdict: **partial**

The implementer has completed a PARTIAL migration. G3 (_static_attrs_cache), G4
(_in_use_modes/_in_use_lock), and G5 (_lock_cache) are fully migrated to
AppCacheState with the `_cs` parameter pattern. G1 (machines_summary_cache) and
G2 (rawdata_overview_cache) have the AppCacheState slots but the FUNCTION BODIES
(_build_machines_summary / _build_rawdata_overview) were updated — the old module
global names were removed and the functions now correctly reference cs.machines_summary_cache
/ cs.rawdata_overview_cache. However, create_app() does not yet instantiate and
attach a per-app AppCacheState to app.state.cache_state, so routes still fall back
to _MODULE_CACHE_STATE (the module-level singleton). This means multi-worker
isolation is not complete end-to-end.

---

## Test files added

| File | Tests |
|------|-------|
| `tests/backend/test_app_state_isolation.py` | 39 |

---

## Test status against current branch (post-implementer partial migration)

| Test | Status |
|------|--------|
| `TestMachinesSummaryCacheState::test_app_cache_state_has_machines_summary_cache_slot` | GREEN |
| `TestMachinesSummaryCacheState::test_two_fresh_cache_states_have_independent_machines_summary_caches` | GREEN |
| `TestMachinesSummaryCacheState::test_machines_summary_cache_is_empty_on_fresh_instance` | GREEN |
| `TestMachinesSummaryCacheState::test_module_level_machines_summary_cache_does_not_exist` | GREEN |
| `TestMachinesSummaryCacheState::test_build_machines_summary_does_not_raise_name_error` | GREEN |
| `TestMachinesSummaryCacheState::test_build_machines_summary_split_path_instance_vs_module_global` | GREEN |
| `TestRawdataOverviewCacheState::test_app_cache_state_has_rawdata_overview_cache_slot` | GREEN |
| `TestRawdataOverviewCacheState::test_two_fresh_cache_states_have_independent_rawdata_overview_caches` | GREEN |
| `TestRawdataOverviewCacheState::test_module_level_rawdata_overview_cache_does_not_exist` | GREEN |
| `TestRawdataOverviewCacheState::test_build_rawdata_overview_does_not_raise_name_error` | GREEN |
| `TestRawdataOverviewCacheState::test_build_rawdata_overview_split_path_instance_vs_module_global` | GREEN |
| `TestStaticAttrsCacheState::test_load_static_attrs_uses_fresh_cs_not_module_global` | GREEN |
| `TestStaticAttrsCacheState::test_two_cs_instances_have_independent_static_attrs_caches` | GREEN |
| `TestStaticAttrsCacheState::test_save_static_attrs_updates_only_the_given_cs` | GREEN |
| `TestStaticAttrsCacheState::test_load_static_attrs_defaults_to_module_cache_state` | GREEN |
| `TestInUseModesCacheState::test_acquire_with_fresh_cs_does_not_touch_module_global` | GREEN |
| `TestInUseModesCacheState::test_release_with_fresh_cs_does_not_touch_module_global` | GREEN |
| `TestInUseModesCacheState::test_get_in_use_snapshot_with_fresh_cs_returns_fresh_cs_state` | GREEN |
| `TestInUseModesCacheState::test_two_cs_instances_have_independent_in_use_modes` | GREEN |
| `TestInUseModesCacheState::test_in_use_modes_thread_safety_per_instance` | GREEN |
| `TestInUseModesCacheState::test_auto_cleanup_uses_per_instance_in_use_snapshot` | GREEN |
| `TestLockCacheCacheState::test_load_rawdata_locks_with_fresh_cs_ignores_module_global_cache` | GREEN |
| `TestLockCacheCacheState::test_two_cs_instances_have_independent_lock_caches` | GREEN |
| `TestLockCacheCacheState::test_save_rawdata_locks_updates_only_given_cs` | GREEN |
| `TestLockCacheCacheState::test_load_rawdata_locks_defaults_to_module_cache_state` | GREEN |
| `TestStaticAttrsMechKeys::test_static_attrs_mech_keys_exists` | GREEN |
| `TestStaticAttrsMechKeys::test_static_attrs_mech_keys_contains_expected_values` | GREEN |
| `TestStaticAttrsMechKeys::test_extract_mechanics_from_summary_uses_mech_keys_constant` | GREEN |
| `TestAppCacheStateStructure::test_app_cache_state_instantiation_has_no_side_effects` | GREEN |
| `TestAppCacheStateStructure::test_no_new_module_top_app_build_patterns_in_backend_modules` | GREEN |
| `TestAppCacheStateStructure::test_module_cache_state_slots_match_expected` | GREEN |
| `TestMultiWorkerCreateAppIsolation::test_create_app_exposes_cache_state_on_app_state` | **RED** |
| `TestMultiWorkerCreateAppIsolation::test_two_create_app_instances_have_different_cache_state_objects` | XFAIL |
| `TestSubprocessImportSmoke::test_import_app_as_subprocess_produces_no_unexpected_output` | GREEN |
| `TestSubprocessImportSmoke::test_app_cache_state_instantiation_in_subprocess` | GREEN |
| `TestPureFunctionExtraction::test_extract_mechanics_from_summary_is_pure` | GREEN |
| `TestPureFunctionExtraction::test_extract_features_from_summary_is_pure` | GREEN |
| `TestPureFunctionExtraction::test_machines_summary_fingerprint_is_pure` | GREEN |
| `TestPureFunctionExtraction::test_rawdata_overview_fingerprint_is_pure` | GREEN |

**Total: 37 GREEN, 1 RED, 1 XFAIL** (at time of test-tester writing)

---

## Inject-bug verification log

### Experiment 1 — G1: _MACHINES_SUMMARY_CACHE module global removal

**Contract**: After migration, `app_mod._MACHINES_SUMMARY_CACHE` must NOT exist
(replaced by `AppCacheState.machines_summary_cache`).

**Inject-bug**: Manually add `app_mod._MACHINES_SUMMARY_CACHE = {}` to simulate
pre-migration state.

**Test guarding this**: `test_module_level_machines_summary_cache_does_not_exist`

**Red step** (with `app_mod._MACHINES_SUMMARY_CACHE = {}`):
```
FAILED: hasattr(app_mod, '_MACHINES_SUMMARY_CACHE') → True → AssertionError
```

**Green step** (current branch — global removed):
```
PASSED: hasattr(app_mod, '_MACHINES_SUMMARY_CACHE') → False
```

**Inject-bug verification**: confirmed in-process. Restoring → GREEN.

---

### Experiment 2 — G1: _build_machines_summary raises no NameError

**Contract**: `_build_machines_summary` must not crash with NameError on the old
global name. The implementer must have updated the function body to use
`cs.machines_summary_cache` via `_cs` parameter.

**Inject-bug**: Temporarily revert function body to use old `_MACHINES_SUMMARY_CACHE`
name (which no longer exists as module attr).

**Test guarding this**: `test_build_machines_summary_does_not_raise_name_error`

**Red step** (old body referencing `_MACHINES_SUMMARY_CACHE`):
```
FAILED: NameError: name '_MACHINES_SUMMARY_CACHE' is not defined
```
(This was observed during initial test run before implementer updated function body.)

**Green step** (current branch — function uses cs.machines_summary_cache):
```
PASSED
```

---

### Experiment 3 — G1: split-path instance vs module global

**Contract**: `_build_machines_summary(rr, _cs=fresh_cs)` must use `fresh_cs.machines_summary_cache`,
NOT `_MODULE_CACHE_STATE.machines_summary_cache`.

**Inject-bug**: If `_cs` param is added to signature but body still uses
`_MODULE_CACHE_STATE` (not `cs = _cs if _cs is not None else _MODULE_CACHE_STATE`),
then poisoning `_MODULE_CACHE_STATE` would cause the function to return the poison result.

**Test guarding this**: `test_build_machines_summary_split_path_instance_vs_module_global`

**Red step** (if function ignores `_cs`):
```
FAILED: result.get('__module_poison__') is True — function returned module-global poison
```

**Green step** (function correctly uses `cs = _cs if _cs is not None else _MODULE_CACHE_STATE`):
```
PASSED: result is the fresh computed result, not the module poison
```

**XFAIL guard**: If `_build_machines_summary` doesn't accept `_cs` at all, the test
calls `pytest.xfail()` with an explanation. Currently GREEN because the function
does accept `_cs`.

---

### Experiment 4 — G2: _RAWDATA_OVERVIEW_CACHE module global removal

**Contract**: `app_mod._RAWDATA_OVERVIEW_CACHE` must NOT exist after migration.

**Inject-bug**: Same as G1 — add `app_mod._RAWDATA_OVERVIEW_CACHE = {}`.

**Test guarding this**: `test_module_level_rawdata_overview_cache_does_not_exist`

**Red step** (global restored): FAILED
**Green step** (current branch): PASSED

---

### Experiment 5 — G3: _load_static_attrs uses _cs, not module global

**Contract**: When `_cs=fresh_cs` is passed, `_load_static_attrs` must read from
`fresh_cs.static_attrs_cache`, not `_MODULE_CACHE_STATE.static_attrs_cache`.

**Inject-bug**: Poison `_MODULE_CACHE_STATE.static_attrs_cache["data"]` = sentinel;
set mtime=0 (cache hit condition). Call `_load_static_attrs(path, _cs=fresh_cs)`
where fresh_cs has `data=None` (cache miss → must re-read from disk).

**Expected RED if bug present**: Function would see module global mtime=0 matching
fresh_cs.static_attrs_cache["mtime"]=0, return sentinel.

**Expected GREEN after migration**: Function uses fresh_cs (data=None → re-reads path).

**Test guarding this**: `test_load_static_attrs_uses_fresh_cs_not_module_global`

**Verified**:
```python
>>> result = _load_static_attrs(path, _cs=fresh_cs)
>>> result.get("__sentinel__")
None  # sentinel NOT returned
>>> "M77" in result.get("machines", {})
True  # disk data correctly loaded
# → GREEN
```

---

### Experiment 6 — G4: _acquire_in_use uses _cs, not module global

**Contract**: `_acquire_in_use(machine, mode, _cs=fresh_cs)` must add to
`fresh_cs.in_use_modes`, NOT `_MODULE_CACHE_STATE.in_use_modes`.

**Inject-bug simulation**: If function ignores `_cs`:
```
fresh_cs.in_use_modes → does NOT contain key (would be empty)
_MODULE_CACHE_STATE.in_use_modes → WOULD contain key
```

**Verified**:
```python
>>> _acquire_in_use("M_INJECT", 42, _cs=fresh_cs)
>>> ("M_INJECT", 42) in fresh_cs.in_use_modes
True   # correct
>>> ("M_INJECT", 42) in _MODULE_CACHE_STATE.in_use_modes
False  # correct — module global not touched
# → GREEN
```

**Test guarding this**: `test_acquire_with_fresh_cs_does_not_touch_module_global`

---

### Experiment 7 — G5: _load_rawdata_locks uses _cs, not module global

**Contract**: `_load_rawdata_locks(path, _cs=fresh_cs)` must use
`fresh_cs.lock_cache`, NOT `_MODULE_CACHE_STATE.lock_cache`.

**Inject-bug**: Poison `_MODULE_CACHE_STATE.lock_cache = {"mtime": 0, "data": {("M_MODULE", 99)}}`.
`fresh_cs.lock_cache = {"mtime": 0, "data": None}` (cache miss → re-reads disk).

**Verified**:
```python
>>> result = _load_rawdata_locks(path, _cs=fresh_cs)
>>> ("M_FRESH_LOCK", 3) in result
True   # loaded from disk
>>> ("M_MODULE_LOCK", 99) in result
False  # module poison not returned
# → GREEN
```

**Test guarding this**: `test_load_rawdata_locks_with_fresh_cs_ignores_module_global_cache`

---

### Experiment 8 — C5: create_app does not yet wire AppCacheState (RED test)

**Contract**: `create_app()` must attach an `AppCacheState()` to `app.state.cache_state`
so route closures use per-instance cache, not `_MODULE_CACHE_STATE`.

**Current state**: `create_app()` does not set `app.state.cache_state`.

**Test guarding this**: `test_create_app_exposes_cache_state_on_app_state`

**Red step** (current branch):
```
FAILED: AssertionError: app.state does not have .cache_state attribute.
```

**Green step** (after implementer adds `app.state.cache_state = AppCacheState()` in create_app):
```
PASSED
```

This is the remaining production bug: without this, all route handlers share
`_MODULE_CACHE_STATE` across multiple app instances (e.g., in tests that create
two apps, or in a multi-worker process).

---

## Coverage map: brief contracts → tests

| Contract | Tests |
|----------|-------|
| **C2 G1** — machines_summary_cache migrated, old global removed | `test_module_level_machines_summary_cache_does_not_exist`, `test_build_machines_summary_does_not_raise_name_error`, `test_build_machines_summary_split_path_instance_vs_module_global`, `test_app_cache_state_has_machines_summary_cache_slot`, `test_two_fresh_cache_states_have_independent_machines_summary_caches`, `test_machines_summary_cache_is_empty_on_fresh_instance` |
| **C2 G2** — rawdata_overview_cache migrated, old global removed | `test_module_level_rawdata_overview_cache_does_not_exist`, `test_build_rawdata_overview_does_not_raise_name_error`, `test_build_rawdata_overview_split_path_instance_vs_module_global`, `test_app_cache_state_has_rawdata_overview_cache_slot`, `test_two_fresh_cache_states_have_independent_rawdata_overview_caches` |
| **C2 G3** — static_attrs_cache: _cs param isolation | `test_load_static_attrs_uses_fresh_cs_not_module_global`, `test_two_cs_instances_have_independent_static_attrs_caches`, `test_save_static_attrs_updates_only_the_given_cs`, `test_load_static_attrs_defaults_to_module_cache_state` |
| **C2 G4** — in_use_modes + in_use_lock: _cs param isolation | `test_acquire_with_fresh_cs_does_not_touch_module_global`, `test_release_with_fresh_cs_does_not_touch_module_global`, `test_get_in_use_snapshot_with_fresh_cs_returns_fresh_cs_state`, `test_two_cs_instances_have_independent_in_use_modes`, `test_auto_cleanup_uses_per_instance_in_use_snapshot` |
| **C2 G5** — lock_cache: _cs param isolation | `test_load_rawdata_locks_with_fresh_cs_ignores_module_global_cache`, `test_two_cs_instances_have_independent_lock_caches`, `test_save_rawdata_locks_updates_only_given_cs`, `test_load_rawdata_locks_defaults_to_module_cache_state` |
| **C2 G6** — _STATIC_ATTRS_MECH_KEYS constant preserved | `test_static_attrs_mech_keys_exists`, `test_static_attrs_mech_keys_contains_expected_values`, `test_extract_mechanics_from_summary_uses_mech_keys_constant` |
| **C3** — No new import-time side effects | `test_app_cache_state_instantiation_has_no_side_effects`, `test_no_new_module_top_app_build_patterns_in_backend_modules` |
| **C3** — AppCacheState slots match expected 6 globals | `test_module_cache_state_slots_match_expected` |
| **C4** — Pure function extraction | `test_extract_mechanics_from_summary_is_pure`, `test_extract_features_from_summary_is_pure`, `test_machines_summary_fingerprint_is_pure`, `test_rawdata_overview_fingerprint_is_pure` |
| **C5** — Multi-worker isolation per global | `test_two_fresh_cache_states_have_independent_*` (5 tests across G1-G5) |
| **C5** — create_app wires per-instance AppCacheState | `test_create_app_exposes_cache_state_on_app_state` (**RED**), `test_two_create_app_instances_have_different_cache_state_objects` (XFAIL) |
| **C5** — Thread safety under concurrent acquire/release | `test_in_use_modes_thread_safety_per_instance` |
| **C6** — Subprocess: import clean, globals empty | `test_import_app_as_subprocess_produces_no_unexpected_output`, `test_app_cache_state_instantiation_in_subprocess` |

---

## Open gaps

### Gap 1: create_app does not wire AppCacheState to route closures (RED test)

**What**: `create_app()` must instantiate `AppCacheState()` and:
1. Attach as `app.state.cache_state` (tested by `test_create_app_exposes_cache_state_on_app_state` → RED)
2. Pass `_cs=app_cache` to every route closure that calls `_build_machines_summary`,
   `_build_rawdata_overview`, `_load_static_attrs`, `_acquire_in_use`,
   `_release_in_use`, `_get_in_use_snapshot`, `_load_rawdata_locks`, etc.

Without (2), even if `app.state.cache_state` is set, the route functions still call
without `_cs` and fall back to `_MODULE_CACHE_STATE`.

**Why not fully tested here**: Verifying that EVERY route closure correctly threads
`_cs` through is impl-verifier (Wave 2) territory — it requires spawning the app
with `TestClient` and hitting each endpoint. The structural test
(`test_create_app_exposes_cache_state_on_app_state`) is the entry gate.

**Escalation flag**: If the implementer has already added `app.state.cache_state`
but the route closures still don't use it (the common "impl says done but wiring
is missing" pattern per P1-B6 hallucination context), impl-verifier must check
each route's closure captures `app_cache` not just that `cache_state` is set.

### Gap 2: G1/G2 split-path XFAIL guard

`test_build_machines_summary_split_path_instance_vs_module_global` and
`test_build_rawdata_overview_split_path_instance_vs_module_global` check for
`_cs` in the function signature and `pytest.xfail()` if absent. Both currently
PASS (functions accept `_cs`). If a future refactor removes `_cs`, they become
XFAIL (not RED) — which is intentional since the contract would need re-design.

### Gap 3: Route-level _cs threading (impl-verifier Wave 2)

Each endpoint that calls the migrated helpers must pass `_cs=app.state.cache_state`.
The following endpoints need checking:
- `GET /api/machines/summary` → `_build_machines_summary(rr, _cs=app_cache)`
- `GET /api/rawdata/overview` → `_build_rawdata_overview(rd_root, mc, retention, _cs=app_cache)`
- `GET /api/machines/static` → `_load_static_attrs(path, _cs=app_cache)`
- `POST /api/rawdata/{m}/mode/{n}/lock` → `_set_rawdata_lock(..., _cs=app_cache)`
- All cleanup paths → `_auto_cleanup_for_space(..., _cs=app_cache)`
- All acquire/release paths → `_acquire_in_use/release_in_use(..., _cs=app_cache)`

This is impl-verifier territory; impl-tester can only assert the structural hook.

---

## Subprocess vs in-process coverage

| Layer | Coverage |
|-------|----------|
| In-process unit (AppCacheState direct) | 33 tests — per-instance isolation + _cs split-path |
| In-process structural (create_app) | 2 tests (1 RED, 1 XFAIL) — wiring contract |
| Subprocess / import smoke | 2 tests — C6 import safety + empty globals |
| Route-level TestClient end-to-end | 0 — deferred to impl-verifier Wave 2 |

Per memory `feedback_perf_claim_needs_e2e_event_stream.md`: the structural unit
tests verify the split-path isolation at the function level. Route-level isolation
(TestClient calling `/api/machines/summary` from two different apps) is the
subprocess-equivalent test for this change and belongs to impl-verifier.

---

## Implementer actions required to clear all tests

1. **`create_app` wiring** (clears 1 RED + 1 XFAIL):
   ```python
   # In create_app(), after building manager/batch_mgr:
   app_cache = AppCacheState()
   app.state.cache_state = app_cache
   # Then thread app_cache through to all route closures that call migrated helpers
   ```

2. **Route closure threading** (verified by impl-verifier Wave 2):
   Each route that calls `_build_machines_summary`, `_build_rawdata_overview`,
   `_load_static_attrs`, `_load_rawdata_locks`, `_acquire_in_use`, etc. must
   capture `app_cache` in its closure and pass `_cs=app_cache`.
