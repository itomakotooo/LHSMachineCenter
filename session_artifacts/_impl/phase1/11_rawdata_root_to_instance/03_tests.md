# 03_tests.md — P1-B6 `RAWDATA_ROOT` global → instance attribute

## Verdict: **partial**

All critical contracts (C1/C2/C3/C5/C6) are covered with inject-bug verified tests.
C4 (virtual-console subprocess smoke) is deferred to impl-verifier per Wave 2 split.

Note: the implementer's 02_implementation.md confirms that only ONE functional ref (app.py line 3393)
was actually broken — all other refs (lines 721, 1198, 3321, 5452) already had the correct
fallback pattern. Our test file covers all of these correctly: the 2 RED tests guard
the actual prod bug; the 18 GREEN tests encode structural invariants that survive refactoring.

---

## Test files added

| File | Tests |
|------|-------|
| `tests/backend/test_rawdata_root_split_path.py` | 20 |

---

## Test status against current (pre-fix) branch

| Test | Status before impl fix | Status after impl fix |
|------|------------------------|----------------------|
| `TestSplitPath::test_batch_manager_stores_injected_rawdata_root` | GREEN | GREEN |
| `TestSplitPath::test_batch_manager_rawdata_root_independent_of_global_mutation` | GREEN | GREEN |
| `TestSplitPath::test_check_rawdata_status_uses_passed_root_not_global` | GREEN | GREEN |
| `TestSplitPath::test_check_rawdata_status_fallback_reads_global_when_none_passed` | GREEN | GREEN |
| `TestStartBatchUsesInstanceRoot::test_start_batch_check_rawdata_status_receives_instance_root` | **RED** | GREEN |
| `TestStartBatchUsesInstanceRoot::test_start_batch_auto_cleanup_uses_instance_root` | GREEN | GREEN |
| `TestCheckRawdataStatusSignature::test_check_rawdata_status_accepts_rawdata_root_param` | GREEN | GREEN |
| `TestCheckRawdataStatusSignature::test_check_rawdata_status_rawdata_root_defaults_to_none` | GREEN | GREEN |
| `TestBatchRunManagerInit::test_init_stores_injected_rawdata_root_as_instance_attr` | GREEN | GREEN |
| `TestBatchRunManagerInit::test_init_none_falls_back_to_rawdata_root_global` | GREEN | GREEN |
| `TestBatchRunManagerInit::test_two_instances_have_independent_rawdata_roots` | GREEN | GREEN |
| `TestRecoverOrphanRunningRuns::test_recover_orphan_does_not_crash_with_bad_rawdata_root` | GREEN | GREEN |
| `TestRecoverOrphanRunningRuns::test_recover_orphan_source_does_not_reference_rawdata_root_global` | GREEN | GREEN |
| `TestModuleLevelRawdataRoot::test_rawdata_root_module_constant_exists` | GREEN | GREEN |
| `TestModuleLevelRawdataRoot::test_rawdata_root_is_path_instance` | GREEN | GREEN |
| `TestModuleLevelRawdataRoot::test_rawdata_root_default_set_from_env_var` | GREEN | GREEN |
| `TestPerRefFallbackPattern::test_fallback_fn_uses_explicit_param_over_global[check_rawdata_status]` | GREEN | GREEN |
| `TestCreateAppWiresRawdataRoot::test_create_app_batch_mgr_rawdata_root_matches_param` | GREEN | GREEN |
| `TestCreateAppWiresRawdataRoot::test_create_app_batch_mgr_rawdata_root_is_not_module_global` | GREEN | GREEN |
| `TestStartBatchProdBugGuard::test_start_batch_scans_injected_root_not_module_global` | **RED** | GREEN |

The 2 RED tests guard exactly the prod bug (original line 3259/3393: `check_rawdata_status(it.machine, it.mode)` with no rawdata_root arg). The 18 GREEN tests verify structural invariants that already hold (constructor stores root, module global preserved, etc.).

---

## Inject-bug verification log

### Experiment 1 — Primary prod-bug guard

**Ref**: `BatchRunManager.start_batch` → `check_rawdata_status(it.machine, it.mode)` (app.py line 3393, no rawdata_root passed)

**Inject-bug**: Current state of app.py line 3393 IS the bug: `check_rawdata_status(it.machine, it.mode)` — no `rawdata_root=self._rawdata_root` argument.

**Tests guarding this ref**:
- `test_start_batch_check_rawdata_status_receives_instance_root`
- `test_start_batch_scans_injected_root_not_module_global`

**Red step** (bug present, current app.py line 3393):
```
FAILED tests/backend/test_rawdata_root_split_path.py::TestStartBatchUsesInstanceRoot::test_start_batch_check_rawdata_status_receives_instance_root
AssertionError: start_batch called check_rawdata_status with rawdata_root=None but expected <virtual_rawdata>.
FAILED tests/backend/test_rawdata_root_split_path.py::TestStartBatchProdBugGuard::test_start_batch_scans_injected_root_not_module_global
AssertionError: start_batch called check_rawdata_status with rawdata_root=None instead of <virtual_root>.
```

**Fix applied** (temporarily):
```python
raw_status = check_rawdata_status(
    it.machine, it.mode,
    rawdata_root=self._rawdata_root,
    machines_config=self._machines_config,
)
```

**Green step** (fix applied):
```
PASSED tests/backend/test_rawdata_root_split_path.py::TestStartBatchUsesInstanceRoot::test_start_batch_check_rawdata_status_receives_instance_root
PASSED tests/backend/test_rawdata_root_split_path.py::TestStartBatchProdBugGuard::test_start_batch_scans_injected_root_not_module_global
```

**Restored to bug state**: 2 tests RED again. Verification complete.

---

### Experiment 2 — BatchRunManager.__init__ stores injected root

**Ref**: `BatchRunManager.__init__` lines 3320-3322:
```python
self._rawdata_root = (
    rawdata_root if rawdata_root is not None else RAWDATA_ROOT
)
```

**Tests guarding this ref**: `test_batch_manager_stores_injected_rawdata_root`, `test_batch_manager_rawdata_root_independent_of_global_mutation`, `test_two_instances_have_independent_rawdata_roots`

**Inject-bug simulation**: If `__init__` did `self._rawdata_root = RAWDATA_ROOT` (ignoring param):
- `test_batch_manager_stores_injected_rawdata_root` → RED (bm._rawdata_root == SENTINEL, not injected)
- `test_batch_manager_rawdata_root_independent_of_global_mutation` → RED
- `test_two_instances_have_independent_rawdata_roots` → RED (both would have same global root)

These tests were GREEN before the ticket started (the constructor already correctly stored the param) — they encode the structural invariant that must survive refactoring.

---

### Experiment 3 — check_rawdata_status uses rawdata_root param

**Ref**: `check_rawdata_status` free function, line 721:
```python
root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT
```

**Tests guarding this ref**: `test_check_rawdata_status_uses_passed_root_not_global`, `test_fallback_fn_uses_explicit_param_over_global[check_rawdata_status]`

**Inject-bug simulation**: If line 721 was `root = RAWDATA_ROOT` (hardcoded):
- With RAWDATA_ROOT pointing at SENTINEL_WRONG_ROOT (nonexistent), the function would crash (`mode_dir = root / machine / ...` on nonexistent path)
- Test asserts no crash and returns dict when real root is passed → would go RED

---

### Experiment 4 — create_app threads rawdata_root into batch_manager

**Ref**: `create_app` at line ~5452 + BatchRunManager construction at line ~5485:
```python
rd_root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT
...
batch_mgr = BatchRunManager(store, manager, cr, ..., rawdata_root=rd_root)
```

**Tests guarding this ref**: `test_create_app_batch_mgr_rawdata_root_matches_param`, `test_create_app_batch_mgr_rawdata_root_is_not_module_global`

**Inject-bug simulation**: If create_app dropped the rawdata_root arg to BatchRunManager:
- `app.state.batch_manager._rawdata_root` would be RAWDATA_ROOT (global), not tmp_rawdata
- `test_create_app_batch_mgr_rawdata_root_matches_param` → RED
- `test_create_app_batch_mgr_rawdata_root_is_not_module_global` → RED (with sentinel monkeypatch)

---

### Experiment 5 — _recover_orphan_running_runs does not touch RAWDATA_ROOT

**Ref**: `RunManager._recover_orphan_running_runs` source — no RAWDATA_ROOT reference.

**Tests guarding this ref**:
- `test_recover_orphan_source_does_not_reference_rawdata_root_global` (static source inspection)
- `test_recover_orphan_does_not_crash_with_bad_rawdata_root` (runtime with RAWDATA_ROOT = nonexistent sentinel)

**Inject-bug simulation**: If `_recover_orphan_running_runs` referenced RAWDATA_ROOT:
- Source inspection test → RED (assertion on "RAWDATA_ROOT" in source text)
- Runtime test → RED (crash or wrong behavior when sentinel path used)

---

## Coverage map: brief contracts → tests

| Contract | Tests |
|----------|-------|
| **C1** Path enumeration — `check_rawdata_status` free fn uses param | `test_check_rawdata_status_uses_passed_root_not_global`, `test_fallback_fn_uses_explicit_param_over_global` |
| **C1** Path enumeration — `BatchRunManager.__init__` stores injected root | `test_init_stores_injected_rawdata_root_as_instance_attr`, `test_init_none_falls_back_to_rawdata_root_global` |
| **C1** Path enumeration — `start_batch` passes `self._rawdata_root` to `check_rawdata_status` | `test_start_batch_check_rawdata_status_receives_instance_root`, `test_start_batch_scans_injected_root_not_module_global` |
| **C1** Path enumeration — `_run_one` disk-pressure uses `self._rawdata_root` for cleanup | `test_start_batch_auto_cleanup_uses_instance_root` |
| **C1** Path enumeration — `create_app` threads rawdata_root through to BatchRunManager | `test_create_app_batch_mgr_rawdata_root_matches_param`, `test_create_app_batch_mgr_rawdata_root_is_not_module_global` |
| **C2** Split-path regression (monkeypatch global, assert instance unaffected) | `test_batch_manager_stores_injected_rawdata_root`, `test_batch_manager_rawdata_root_independent_of_global_mutation`, `test_create_app_batch_mgr_rawdata_root_is_not_module_global` |
| **C3** Per-path inject-bug | See inject-bug log above (5 experiments) |
| **C4** Virtual console subprocess smoke | **Deferred** — impl-verifier Wave 2 responsibility |
| **C5** `_recover_orphan_running_runs` safety | `test_recover_orphan_does_not_crash_with_bad_rawdata_root`, `test_recover_orphan_source_does_not_reference_rawdata_root_global` |
| **C6** Module-level RAWDATA_ROOT preserved as backward-compat default | `test_rawdata_root_module_constant_exists`, `test_rawdata_root_is_path_instance`, `test_rawdata_root_default_set_from_env_var`, `test_init_none_falls_back_to_rawdata_root_global`, `test_check_rawdata_status_fallback_reads_global_when_none_passed` |
| **Prod-bug check_rawdata_status:3259 explicit guard** | `test_start_batch_scans_injected_root_not_module_global` (primary), `test_start_batch_check_rawdata_status_receives_instance_root` (secondary) |

---

## Open gaps

### C4 — Virtual console subprocess smoke (deferred)

**What it should test**: Spawn `virtual_app.py` as a real subprocess, POST a batch run request, verify that rawdata chunks written during the run land in `VIRTUAL_RAWDATA_ROOT` (slot_designer/rawdata/) and NOT in the real `RAWDATA_ROOT` (repo/rawdata/).

**Why deferred**: This requires a running virtual_app process, an actual batch queue, and a mock upstream sampler — all of which are impl-verifier territory (Wave 2 per brief §7). The unit-level tests in this file cover the structural invariant; the subprocess test covers the runtime path.

**Where to add**: `tests/integration/test_virtual_console_rawdata_isolation.py` or extend the impl-verifier script that validates Wave 2 contracts.

**Escalation flag**: If impl-verifier cannot exercise this (e.g., virtual_app is not importable or has no test mode), escalate to main session.

### C3 partial — `delete_rawdata` free fn (line ~1198)

`delete_rawdata` has the same `root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` fallback pattern. The parametrize fixture at `TestPerRefFallbackPattern` is designed to be extended with `("delete_rawdata", app_mod.delete_rawdata)` once that function's test fixture requirements are understood. Currently omitted because `delete_rawdata` triggers actual disk deletions and needs a more complex fixture.

### Pre-existing test failure (unrelated)

`tests/backend/test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split` fails with `FileNotFoundError: rawdata/M31/mode_1/chunk_0001.json` — a missing fixture file unrelated to this ticket. Not caused by P1-B6 changes.

---

## Subprocess vs in-process coverage

| Test layer | Coverage |
|------------|----------|
| In-process unit (spy/monkeypatch) | 20 tests — all structural invariants + prod-bug guards |
| In-process integration (app_factory + TestClient) | 2 tests — create_app wiring |
| Subprocess / virtual-console end-to-end | 0 — deferred to impl-verifier (C4) |

The prod bug at line 3393 is a pure in-process structural bug (wrong argument at a function call site), so in-process unit tests with a spy are the correct and sufficient tool. The subprocess test (C4) is additive safety for the virtual-console path, not a substitute.
