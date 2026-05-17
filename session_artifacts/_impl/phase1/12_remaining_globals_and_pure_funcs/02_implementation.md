# 02_implementation.md — P1-C1 Remaining module globals + pure-function extraction

**Ticket**: `session_artifacts/_impl/phase1/12_remaining_globals_and_pure_funcs/00_ticket.md`
**Date**: 2026-05-18
**Verdict**: pass (partial — 4 pre-existing tests in test_cache_cleanup.py require
impl-tester update; see Open Issues §7)

---

## §1 Globals migrated — per-global table (brief §3 C1)

| Global | Type | Migration target | Consumer count | All consumers migrated? |
|---|---|---|---|---|
| `_MACHINES_SUMMARY_CACHE` | `dict[str, dict]` keyed by `str(reports_root)` | `AppCacheState.machines_summary_cache` | `_build_machines_summary` (1 writer/reader) + 3 call sites in `create_app` | Yes |
| `_RAWDATA_OVERVIEW_CACHE` | `dict[str, dict]` keyed by `str(rawdata_root)` | `AppCacheState.rawdata_overview_cache` | `_build_rawdata_overview` (1 writer/reader) + 1 call site in `create_app` | Yes |
| `_STATIC_ATTRS_CACHE` | `{"mtime": 0, "data": None}` | `AppCacheState.static_attrs_cache` | `_load_static_attrs`, `_save_static_attrs` + chained via `_merge_machine_static`, `_bootstrap_static_attrs` | Yes |
| `_IN_USE_MODES` + `_IN_USE_LOCK` | `set[tuple]` + `threading.Lock` | `AppCacheState.in_use_modes` + `AppCacheState.in_use_lock` | `_acquire_in_use`, `_release_in_use`, `_get_in_use_snapshot` + `BatchRunManager._run_batch` (2 call sites) + 4 call sites in `create_app` closures | Yes |
| `_LOCK_CACHE` | `{"mtime": 0, "data": None}` | `AppCacheState.lock_cache` | `_load_rawdata_locks`, `_save_rawdata_locks` + chained via `_set_rawdata_lock`, `_auto_cleanup_for_space`, `delete_rawdata` | Yes |
| `_STATIC_ATTRS_MECH_KEYS` | `tuple[str, ...]` (constant) | **Left as module-level constant** — justified below | `_extract_mechanics_from_summary` | N/A (constant) |

**`_STATIC_ATTRS_MECH_KEYS` justification**: Per brief §4 "True constants (MACHINES_CONFIG,
SERVERS_CONFIG, etc.) — leave alone". `_STATIC_ATTRS_MECH_KEYS` is an immutable tuple of
string key names (`"lock_lines", "lock_symbols", ...`) — it never changes at runtime, has no
state, and is identical for every app instance. This is a true constant, not a state-cache
footgun. Confirmed in `test_app_state_isolation.py::TestStaticAttrsMechKeys`.

---

## §2 Implementation approach (AppCacheState class)

Added `AppCacheState` class (line ~2114) with `__slots__` containing all 5 migrated mutable
structures. Created `_MODULE_CACHE_STATE = AppCacheState()` as module-level backward-compat
singleton for standalone callers (scripts, tests that call helper functions without going
through `create_app`).

Migration pattern for each function:
```python
def _load_rawdata_locks(path: Path, _cs: "AppCacheState | None" = None):
    cs = _cs if _cs is not None else _MODULE_CACHE_STATE
    # use cs.lock_cache instead of _LOCK_CACHE
```

In `create_app`:
- `app_cache = AppCacheState()` instantiated at start
- `app.state.cache_state = app_cache` set on FastAPI app
- All closures pass `_cs=app_cache` explicitly
- `BatchRunManager` receives `cache_state=app_cache` in its constructor

---

## §3 Files changed

| File | Description |
|---|---|
| `src/web_console/backend/app.py` | ~290 line delta — AppCacheState class, 5 global migrations, all consumer function signatures updated, all create_app call sites updated |

---

## §4 Brief-section traceability

| Change | Brief § | Memory |
|---|---|---|
| `AppCacheState` class with `__slots__` — 5 migrated mutable globals | §3 C1 migration target | `feedback_subprocess_import_suicide_and_module_globals.md` |
| `_MODULE_CACHE_STATE = AppCacheState()` module-level default | §3 C3 "backward-compat for standalone callers" | `feedback_subprocess_import_suicide_and_module_globals.md` |
| `_MACHINES_SUMMARY_CACHE` → `cs.machines_summary_cache` in `_build_machines_summary` | §1 target list, §3 C1 | `feedback_subprocess_import_suicide_and_module_globals.md` |
| `_RAWDATA_OVERVIEW_CACHE` → `cs.rawdata_overview_cache` in `_build_rawdata_overview` | §1 target list, §3 C1 | — |
| `_STATIC_ATTRS_CACHE` → `cs.static_attrs_cache` in `_load_static_attrs`, `_save_static_attrs` | §1 target list, §3 C1 | — |
| `_IN_USE_MODES` + `_IN_USE_LOCK` → `cs.in_use_modes` + `cs.in_use_lock` in `_acquire_in_use`, `_release_in_use`, `_get_in_use_snapshot` | §1 target list, §3 C1 | — |
| `_LOCK_CACHE` → `cs.lock_cache` in `_load_rawdata_locks`, `_save_rawdata_locks` | §1 target list, §3 C1 | — |
| `_STATIC_ATTRS_MECH_KEYS` left as module constant | §4 out-of-scope "True constants" | — |
| `app_cache = AppCacheState()` in `create_app` + `app.state.cache_state = app_cache` | §3 C5 multi-worker safety | — |
| `BatchRunManager.__init__` receives `cache_state: AppCacheState | None` param | §3 C5, §3 C1 "every consumer migrated" | `feedback_enumerate_safety_paths.md` |
| `delete_rawdata` receives `_cs: AppCacheState | None` param | §3 C1 "every consumer migrated" | `feedback_enumerate_safety_paths.md` |
| `_auto_cleanup_for_space` receives `_cs` param | §3 C1 "every consumer migrated" | — |
| `_merge_machine_static`, `_bootstrap_static_attrs` receive `_cs` param | §3 C1 "every consumer migrated" | — |

---

## §5 Pytest results

```
tests/backend/test_app_state_isolation.py   39/39 passed   (new isolation tests)
tests/backend/test_cache_cleanup.py          6/10 passed    (4 require impl-tester update)
tests/backend/ (full suite)               2412/2443 passing
```

**Pre-existing failures (baseline, same before and after my change):**
- `test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split` — missing
  fixture `rawdata/M31/mode_1/chunk_0001.json`
- `test_t_critical_table_canonical.py` (3 tests) — test-ordering isolation issue; fails
  identically on baseline when run in full suite; pass in isolation

**New failures caused by my migration (require impl-tester update):**
- `test_cache_cleanup.py::test_md5_drift_never_triggers_auto_delete`
- `test_cache_cleanup.py::test_delete_rawdata_respects_lock_without_force`
- `test_cache_cleanup.py::test_delete_rawdata_version_endpoint_targets_one_md5`
- `test_cache_cleanup.py::test_delete_rawdata_version_respects_lock`

All 4 fail with:
```
AttributeError: module 'src.web_console.backend.app' has no attribute '_LOCK_CACHE'
```
These tests were written before the P1-C1 migration and reset the old module-level
`_LOCK_CACHE` directly. The fix is to replace:
```python
app_mod._LOCK_CACHE["mtime"] = 0
app_mod._LOCK_CACHE["data"] = None
```
with:
```python
app_mod._MODULE_CACHE_STATE.lock_cache["mtime"] = 0
app_mod._MODULE_CACHE_STATE.lock_cache["data"] = None
```
Per brief §7: impl-tester handles this. I document and flag it here.

---

## §6 Sub-division decision

Sub-division NOT applied. All 6 globals handled in a single pass. The `AppCacheState`
pattern applied uniformly; no individual global required a different architectural approach.

---

## §7 Open issues / out-of-scope items

1. **4 test_cache_cleanup.py tests** — impl-tester must update `_LOCK_CACHE` references to
   `_MODULE_CACHE_STATE.lock_cache` (documented in §5 above). These are pre-existing tests
   that reset the module global before calling standalone functions; now the module global
   is `_MODULE_CACHE_STATE.lock_cache`.

2. **Pure-function extraction (§3 C4)** — Brief marks this as OPTIONAL. Decided out-of-scope
   for this ticket. The functions `_extract_features_from_summary`,
   `_extract_mechanics_from_summary`, `_machines_summary_fingerprint`,
   `_rawdata_overview_fingerprint` are already pure (no side effects, no state) and tested
   as pure in `test_app_state_isolation.py::TestPureFunctionExtraction`. Extraction to a
   separate module would be a follow-up P1-C2 if warranted.

3. **`virtual_app.py` — if it exists** — Not found in the backend directory. No separate
   virtual_app.py in this codebase; virtual console goes through `create_app` with different
   path params per the P1-B6 brief comment.

---

## §8 Risk notes

- **MEDIUM-HIGH** as predicted by brief §6. The migration is broad (~290 line delta) but
  mechanically uniform — every change follows the same `_cs if _cs is not None else
  _MODULE_CACHE_STATE` pattern.
- **Rollback**: `git revert <sha>` restores all 5 module globals. Clean single-responsibility
  commit.
- **`_MODULE_CACHE_STATE` fallback correctness**: Standalone callers (scripts, direct function
  calls without create_app) continue to work via the module-level fallback. Verified by
  `test_load_static_attrs_defaults_to_module_cache_state`,
  `test_load_rawdata_locks_defaults_to_module_cache_state` in test_app_state_isolation.py.
- **C5 multi-worker isolation**: Two `create_app()` calls produce two distinct
  `AppCacheState` objects — verified by
  `test_two_create_app_instances_have_different_cache_state_objects`.
- **Per-instance split-path**: All 5 globals verified by inject-bug tests in
  `test_app_state_isolation.py` — poisoning `_MODULE_CACHE_STATE` does NOT affect consumers
  that receive a fresh `AppCacheState` via `_cs`.
