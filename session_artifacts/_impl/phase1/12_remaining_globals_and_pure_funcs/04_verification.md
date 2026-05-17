# 04_verification.md — P1-C1 Remaining module globals + pure-function extraction

**Ticket**: phase1/12_remaining_globals_and_pure_funcs
**Verifier**: impl-verifier
**Date**: 2026-05-18
**Verdict**: PASS

---

## 1. Independent pytest — targeted 49 tests

Command:
  python -m pytest tests/backend/test_app_state_isolation.py tests/backend/test_cache_cleanup.py -v

Result:
  49 passed in 1.38s

All 49 GREEN. No XFAIL, no RED.

Note: at tester-writing time, test_create_app_exposes_cache_state_on_app_state was RED and
test_two_create_app_instances_have_different_cache_state_objects was XFAIL. The main session
patched tests/backend/test_cache_cleanup.py (10 _LOCK_CACHE -> _MODULE_CACHE_STATE.lock_cache
references) and the implementer completed create_app() wiring. Both now GREEN. Confirmed.

---

## 2. Globals migration — grep verification

Command:
  grep -n "_MACHINES_SUMMARY_CACHE|..." src/web_console/backend/app.py

Result (only lines remaining in app.py referencing these names):
  2207: comment "Migrated from _RAWDATA_OVERVIEW_CACHE module global to AppCacheState"
  2324: comment "Migrated from _STATIC_ATTRS_CACHE module global to AppCacheState"
  2334: comment "Migrated from _IN_USE_MODES/_IN_USE_LOCK module globals to"
  2374: comment "Migrated from _LOCK_CACHE module global to AppCacheState per P1-C1."
  2458: comment "_STATIC_ATTRS_MECH_KEYS is a true constant..."
  2461: _STATIC_ATTRS_MECH_KEYS = (  <-- live constant assignment
  2557: mk for mk in _STATIC_ATTRS_MECH_KEYS  <-- usage inside function

Global migration status:
  _MACHINES_SUMMARY_CACHE  : GONE (only comment, no live assignment) -> AppCacheState.machines_summary_cache
  _RAWDATA_OVERVIEW_CACHE  : GONE (only comment, no live assignment) -> AppCacheState.rawdata_overview_cache
  _STATIC_ATTRS_CACHE      : GONE (only comment, no live assignment) -> AppCacheState.static_attrs_cache
  _IN_USE_MODES + _IN_USE_LOCK: GONE (only comment) -> AppCacheState.in_use_modes + in_use_lock
  _LOCK_CACHE              : GONE (only comment, no live assignment) -> AppCacheState.lock_cache
  _STATIC_ATTRS_MECH_KEYS  : REMAINS at line 2461 (correct per brief S4 - true constant)

5/6 globals migrated. 6th correctly left as constant.

---

## 3. C5 multi-worker safety

test_two_create_app_instances_have_different_cache_state_objects: PASSED (was XFAIL at tester time).

Code verified:
  Line 5580: app_cache = AppCacheState()  -- inside create_app() function body
  Line 5619: app.state.cache_state = app_cache
  Two create_app() calls produce two distinct Python objects (separate id()).

---

## 4. C3 — No import-time side effects

Grep for ^[A-Z_]+ = build_ / ^app = / ^server =: No matches found.

Subprocess smoke:
  python -c "import src.web_console.backend.app; print(OK)"
  Output: OK
  Exit code: 0
  No stderr, no side-effect output.

_MODULE_CACHE_STATE = AppCacheState() at line 2164 is safe: only allocates data containers
(dict + set + threading.Lock), no filesystem access, no subprocess spawn, no route registration.

---

## 5. AppCacheState class + _cs injection pattern (route-level verification)

Class defined at line 2127 with __slots__ = 6 attrs.
_MODULE_CACHE_STATE = AppCacheState() at line 2164 (module-level backward-compat singleton).

Route handlers verified to inject _cs=app_cache:
  GET  /api/machines/summary                (line 6053)
  GET  /api/machines/static                 (lines 6131, 6133)
  GET  /api/rawdata/overview                (line 6174)
  GET  /api/rawdata/{machine}               (line 6285 -- lock read)
  POST /api/rawdata/{machine}/mode/{n}/lock (line 6294)
  DEL  /api/rawdata/{machine}/mode/{n}/lock (line 6302)
  acquire/release in-use                    (lines 7036, 7367, 7468, 7478)
  _merge_machine_static                     (line 7296)
  auto-cleanup/delete                       (lines 6542, 6604)

BatchRunManager receives cache_state=app_cache at line 5610; uses self._cache_state at
lines 3974, 4014, 4228 for acquire/release.

delete_rawdata at line 1181 accepts _cs, passes to _load_rawdata_locks at line 1249.
Route handler at line 6542 passes _cs=app_cache to delete path.

All consumers of all 5 migrated globals pass _cs=app_cache within create_app() closure scope.

---

## 6. Full pytest regression suite

Command:
  python -m pytest tests/backend/ tests/integration/ -v --tb=no -q

Result:
  4 failed, 2439 passed, 23 skipped, 2 xfailed in 127.22s

Failures (all pre-existing baseline):
  1. test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split
     -- Missing fixture rawdata/M31/mode_1/chunk_0001.json (FileNotFoundError)
     -- Pre-existing per implementer notes S5

  2-4. test_t_critical_table_canonical.py::test_c1_player_impact_analyzer_imports_from_sampler
       test_t_critical_table_canonical.py::test_c1_virtual_analyzer_imports_from_sampler
       test_t_critical_table_canonical.py::test_c6_split_path_monkeypatch_proves_sampler_attr_used
     -- Test-ordering import-cache interference in full suite; all PASS in isolation
     -- Pre-existing per implementer notes S5

0 new failures introduced by P1-C1.

---

## 7. Subprocess vs in-process coverage

  In-process unit (AppCacheState direct, per-global isolation) : 33 tests GREEN
  In-process structural (create_app wiring)                    : 2 tests GREEN (was 1 RED + 1 XFAIL)
  Subprocess import smoke                                      : 2 tests GREEN
  Route-level _cs injection                                    : code-verified for all 8+ endpoints

---

## 8. Regressions in untouched areas

Count: 0 new regressions. 4 failures in full suite are all pre-existing baseline.

---

## 9. Summary table

  Check                                          Result
  49/49 targeted tests GREEN                     PASS
  _MACHINES_SUMMARY_CACHE gone                   PASS
  _RAWDATA_OVERVIEW_CACHE gone                   PASS
  _STATIC_ATTRS_CACHE gone                       PASS
  _IN_USE_MODES + _IN_USE_LOCK gone              PASS
  _LOCK_CACHE gone                               PASS
  _STATIC_ATTRS_MECH_KEYS remains (constant)     PASS (correct per brief S4)
  C5 multi-worker isolation                      PASS
  C3 no import-time side effects                 PASS
  Subprocess smoke rc=0                          PASS
  All route handlers inject _cs=app_cache        PASS
  Full suite 0 new failures                      PASS
  Frontend changes                               N/A
