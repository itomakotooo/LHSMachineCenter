# Ticket P1-C1 — Resolution

> **LAST Phase 1 ticket.** Migration of remaining 5 mutable module globals to per-instance `AppCacheState` pattern.

## Decision: **SHIP**

| Source | Verdict |
|---|---|
| impl-implementer | PASS partial (~22.9 min); 5/6 globals migrated; 6th `_STATIC_ATTRS_MECH_KEYS` is true constant per brief §4; flagged 4 test_cache_cleanup attr refs need update |
| impl-tester | partial (~15.5 min); 39 tests; 7/7 inject-bug; initial 1 RED + 1 XFAIL → now GREEN after implementer's create_app wiring landed |
| impl-verifier | PASS (~7.8 min); 5/6 globals confirmed via grep; 49/49 targeted + 2439/2443 full suite; 0 regressions; C5 multi-worker isolation verified |
| impl-critic | APPROVE-WITH-REVISIONS — R1 verifier pending (resolved) / R2 vacuous resets in TestClient tests / R3 P1-C2 ticket missing |

## Main session R2+R3 fixes

**R2 — vacuous resets in TestClient tests**: critic found that 2 of the 4 `test_cache_cleanup.py` tests use TestClient (which uses fresh `app.state.cache_state` per-instance), so my earlier `_MODULE_CACHE_STATE.lock_cache` reset is a no-op for those routes. Fix: removed the vacuous reset lines from the 2 TestClient tests with explanatory comments. Kept the resets for the 2 tests that use direct function calls (which DO use the module-level singleton fallback). Tests still 49/49 pass.

**R3 — P1-C2 ticket for pure-function extraction**: documented in PHASE_1_TICKETS.md "Known Follow-ups" section. Per brief §5, pure-function extraction was OPTIONAL sub-scope. Implementer prioritized the uniform `AppCacheState` migration; pure-function extraction deferred to potential P1-C2.

## Architectural summary

Implementer migrated 5 mutable module globals to a single `AppCacheState` class with two access modes:

**Module singleton** (`_MODULE_CACHE_STATE`):
- Top-level binding `_MODULE_CACHE_STATE = AppCacheState()` at module init
- Used as fallback when callers don't pass `_cs=...` parameter
- Backward-compat for legacy direct function callers (e.g., `check_rawdata_status(...)` without `_cs`)

**Per-instance** (`app.state.cache_state`):
- Each `create_app()` call instantiates a fresh `AppCacheState()` 
- Attached to `app.state.cache_state` at line ~5619
- Route handlers take `_cs=app_cache` (closures capture the per-app cache)
- C5 multi-worker safety: 2 `create_app()` calls → 2 distinct `AppCacheState` objects

## Pytest results

- 49/49 targeted (39 P1-C1 app_state_isolation + 10 test_cache_cleanup) GREEN
- 2439/2443 full suite (4 pre-existing baseline failures: M31 fixture missing + test-ordering cache_cleanup interference)
- 0 new regressions
- Subprocess import smoke: `python -c "import src.web_console.backend.app; print('OK')"` rc=0, no stderr

## Process learning (added to memory implicitly via this ticket)

Pattern observed across P1-C1 (and P1-B6): when implementer claims pytest pass, run independently before trusting. P1-B6 had hallucination caught by verifier; P1-C1 had vacuous test-reset caught by critic; both prevented bad commits.

## Commit reference

Commit `<sha>` on `claude/stoic-napier-f0ea00`. Includes:
- `src/web_console/backend/app.py` MODIFIED (~290-line delta; AppCacheState class; 5 globals removed; create_app wires per-instance cache)
- `tests/backend/test_app_state_isolation.py` NEW (39 tests)
- `tests/backend/test_cache_cleanup.py` MODIFIED (8 attr refs migrated by main session; 2 vacuous resets removed per R2)
- 6 markdown artifacts in `session_artifacts/_impl/phase1/12_remaining_globals_and_pure_funcs/`
- `session_artifacts/_impl/phase1/PHASE_1_TICKETS.md` MODIFIED (P1-C2 follow-up entry added per R3)
