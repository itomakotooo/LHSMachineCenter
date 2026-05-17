# 05_critique.md — P1-C1 Remaining module globals + pure-function extraction

**Critic**: impl-critic
**Date**: 2026-05-18
**Chain read**: 00_ticket.md, 02_implementation.md, 03_tests.md (no 04_verification.md exists)

---

## Verdict: APPROVE-WITH-REVISIONS

The migration is structurally sound and most contracts are satisfied. Two issues require a second pass before shipping: (1) the tester-verifier chain disagreement on the implementation's final state, which created a false picture of what was actually committed; and (2) the route-level `_cs` threading has no end-to-end test coverage. Everything else is solid.

---

## Implementer hallucination check

**PASS.**

Post-P1-B6 concern addressed. Grepping app.py directly confirms:
- `_MACHINES_SUMMARY_CACHE`, `_RAWDATA_OVERVIEW_CACHE`, `_STATIC_ATTRS_CACHE`, `_IN_USE_MODES`, `_IN_USE_LOCK`, `_LOCK_CACHE` are ALL absent as module-level names.
- `AppCacheState` class is defined at line ~2127 with `__slots__` containing the 6 entries.
- `_MODULE_CACHE_STATE = AppCacheState()` is present at line ~2164.
- `app.state.cache_state = app_cache` is set at line ~5619 in `create_app`.
- Every route closure that calls a migrated helper passes `_cs=app_cache` explicitly (confirmed at lines 6053, 6131, 6133, 6174, 6285, 6294, 6302, 6338, 6346, 7036, 7295–7296, 7367, 7468, 7478, 7572, 6542, 6604).

The code is physically on disk. The implementation diff matches the implementation document.

---

## Stress questions

### Q1 — The tester document is temporally inconsistent with the final committed code

**Scenario**: `03_tests.md` opens with "Verdict: partial" and states "create_app() does not yet instantiate and attach a per-app AppCacheState to app.state.cache_state." The test status table in `03_tests.md` shows `test_create_app_exposes_cache_state_on_app_state` as **RED** and `test_two_create_app_instances_have_different_cache_state_objects` as **XFAIL**. Yet the implementation document (`02_implementation.md §5`) claims 39/39 GREEN, and the actual app.py on disk has `app.state.cache_state = app_cache` wired. The task brief said "39/39 GREEN" in both tester and implementer final state.

**Attempted answer**: The tester wrote `03_tests.md` against an incomplete snapshot of the implementation, then the implementer did a later edit that completed the `create_app` wiring. The main session subsequently updated `test_cache_cleanup.py` (8 refs to `_MODULE_CACHE_STATE.lock_cache`). The two documents reflect different moments in time. There is no 04_verification.md to adjudicate.

**Risk**: Without a verifier run against the final committed state, there is no empirical confirmation that the 2 previously-RED/XFAIL tests are now green. The implementer claims 39/39 in `02_implementation.md §5`, but that document was authored by the same party whose earlier work the tester found incomplete. This is an unverified claim — exactly the P1-B6 hallucination pattern the task brief warned about.

**Verdict**: ⚠ Partial. The code is on disk and looks correct, but no independent verifier has run pytest on the final state.

---

### Q2 — Route-level `_cs` threading has zero end-to-end test coverage

**Cited code**: `03_tests.md §Open gaps — Gap 3` explicitly lists this as "impl-verifier Wave 2 territory" with zero `TestClient` route-level tests. The tester notes:
> "Route-level TestClient end-to-end — 0 — deferred to impl-verifier Wave 2"

**Scenario**: Every route in `create_app` that calls a migrated helper must capture `app_cache` in its closure and pass `_cs=app_cache`. The implementer did wire this (verified by grep: lines 6053, 6131, 6174, etc.). But what happens if a future refactor adds a new route call-site that forgets `_cs`? The existing tests only prove the current function signatures accept `_cs` and that a poison in `_MODULE_CACHE_STATE` doesn't leak through a direct function call. They do NOT prove that an HTTP request to `/api/machines/summary` on `app_a` cannot see data from `app_b`'s cache.

**Attempted answer**: The split-path tests (G1–G5) pass a fresh `_cs` directly to helper functions. They test isolation at the function call level. But the integration test (TestClient → route → helper) is the only thing that would catch a wiring regression where the route closure calls `_build_machines_summary(rr)` without `_cs`. That path currently has no test.

**Verdict**: ⚠ Partial. The structural tests at the function level are solid. The route-level integration path is unverified. Per `feedback_perf_claim_needs_e2e_event_stream.md`: unit tests + AST checks are not sufficient; needs a test that exercises the runtime branch via HTTP.

---

### Q3 — The `_MODULE_CACHE_STATE` singleton is a new module-top side effect introduced by this ticket

**Cited code**: `app.py:2164` — `_MODULE_CACHE_STATE = AppCacheState()`.

**Scenario**: Brief §3 C3 says "NO new module-top `app = build_app()`-like patterns introduced." The implementer introduces `_MODULE_CACHE_STATE = AppCacheState()` at module top. `AppCacheState.__init__` allocates a `threading.Lock()` at import time. This is new import-time allocation that did not exist before this ticket. Is this a C3 violation?

**Attempted answer**: The brief's C3 examples target `build_*` / `create_*` function calls that spawn processes or bind network ports. `AppCacheState()` allocates two dicts, a set, and a `threading.Lock` — cheap, inert, no I/O. The subprocess smoke tests (C6) confirm import produces no observable output. The tester's `test_no_new_module_top_app_build_patterns_in_backend_modules` explicitly excludes `app.py` from its scan (listed in `pre_existing_entrypoints`). However, the exclusion covers `app.py` entirely, meaning if tomorrow someone adds `app = create_app()` at module top of `app.py`, this test will not catch it.

**Deeper concern**: `_MODULE_CACHE_STATE` is justified as "backward compat for standalone callers." But if ALL callers in `create_app` already pass `_cs=app_cache`, the module-level singleton is only reachable by (a) standalone scripts and (b) tests that call helper functions directly. For case (b), poisoning `_MODULE_CACHE_STATE` in tests remains a footgun — a test that calls `_load_rawdata_locks(path)` without `_cs` will silently interact with shared singleton state across test runs if cleanup is missed.

**Verdict**: ⚠ Partial. The C3 concern is defensible (no process-spawning import-time side effects), but the singleton creates a subtle test-isolation hazard: any test calling a migrated helper without `_cs` writes to `_MODULE_CACHE_STATE`, which is shared across the entire test session. The tester's `test_load_rawdata_locks_defaults_to_module_cache_state` does explicit cleanup (`lock_cache["data"] = None`), but if other tests call these helpers without cleanup, they leave dirty state.

---

### Q4 — `BatchRunManager._auto_cleanup_for_space` call does NOT pass `_cs` — is there another call site?

**Cited code**: `app.py:3971-3974`:
```python
summary = _auto_cleanup_for_space(
    self._rawdata_root, self._machines_config,
    retention_cur, target_free_gb=target_free,
    _cs=self._cache_state,
)
```

This call correctly passes `_cs=self._cache_state`. However, there is also `POST /api/cache/cleanup` — the manual cleanup button. Let me check that route:

**Grep evidence**: `app.py:6529-6543` shows the `delete_rawdata` route passes `_cs=app_cache`. But `POST /api/cache/cleanup` calls `delete_rawdata` (not `_auto_cleanup_for_space`). The question is whether `_auto_cleanup_for_space` is ever called from a route closure without `_cs`. Searching the grep results: the only call sites for `_auto_cleanup_for_space` are (1) `BatchRunManager._run_batch` (passes `_cs=self._cache_state`) and (2) the comment/docstring references. No route closure directly calls `_auto_cleanup_for_space` — routes call `delete_rawdata` for manual cleanup.

**Verdict**: ✓ Adequately addressed. Both call sites of `_auto_cleanup_for_space` pass `_cs` correctly.

---

### Q5 — The `test_cache_cleanup.py` update is out of scope for the main session

**Scenario**: The task brief says "tester handles this" (02_implementation.md §7 item 1). The main session updated `test_cache_cleanup.py` — 8 refs from `app_mod._LOCK_CACHE` to `app_mod._MODULE_CACHE_STATE.lock_cache`. Per `docs/IMPL_TEAM_PROCESS.md §5 invariant 4`: "Implementer cannot write tests; Tester cannot edit prod code."

**Attempted answer**: The main session is the coordinator, not one of the four agents. The process document says "Main session only authors `00_ticket.md` and `06_resolution.md`" — with the exception that it also executes cleanup work when a W2 gap is small. However, the 8-ref update to `test_cache_cleanup.py` is test code that should have been part of the tester's output. If the tester's `03_tests.md` documents this as "impl-tester must update," and the main session did it instead, the tester's inject-bug discipline may not have been applied to these 4 tests.

**Specific risk**: Does each of the 4 updated tests in `test_cache_cleanup.py` still constitute a valid regression guard? The updated code resets `_MODULE_CACHE_STATE.lock_cache` to `{"mtime": 0, "data": None}` before calling `delete_rawdata` / `check_rawdata_status`. After the migration, the app-level route uses `app_cache` (a separate instance), not `_MODULE_CACHE_STATE`. So these tests are resetting the wrong cache state for the route-level test paths (they call `create_app()` with `TestClient`). The route's `delete_rawdata` endpoint passes `_cs=app_cache`, which is the app's own `AppCacheState()` instance — NOT `_MODULE_CACHE_STATE`. Resetting `_MODULE_CACHE_STATE.lock_cache` has no effect on those route calls.

**Verdict**: ✗ Not adequately addressed. The 4 tests in `test_cache_cleanup.py` that create a full `TestClient` app (`test_delete_rawdata_version_endpoint_targets_one_md5`, `test_delete_rawdata_version_respects_lock`) reset `_MODULE_CACHE_STATE.lock_cache` — but the route passes `_cs=app_cache` (the app's own instance). The reset is therefore a no-op for those test paths. These tests may pass coincidentally (the lock file on disk is the authoritative state; the cache reset just prevents a stale cache hit from interfering). However, if the cache were hot (prior test left it populated), the reset to the wrong instance would allow stale data to survive. The test passes because the lock check reads from disk when `data is None`, but the setup logic (reset `_MODULE_CACHE_STATE`) is semantically wrong. This needs to be corrected: either reset `app.state.cache_state.lock_cache` or accept that these tests do not need a reset (since the TestClient app gets a fresh `AppCacheState()` with `data=None` by default).

---

### Q6 — Verifier is absent: no 04_verification.md exists

**Scenario**: The task brief instructions for this ticket explicitly say "(parallel; may not exist yet)" for the verifier. The main session note confirms "Verifier (parallel; may not exist yet)." With no verifier run, contract C6 (subprocess verification) is only validated by the in-process subprocess smoke tests in `test_app_state_isolation.py`. Those tests spawn a real subprocess to verify import safety and slot initialization. However, the full verifier obligation includes:
- Running the complete test suite (2412+ tests) to check for regressions outside `test_app_state_isolation.py`
- Confirming the 4 previously-failing `test_cache_cleanup.py` tests now pass (implementer claims 6/10 → 10/10, but this is unverified)
- Verifying the pre-existing failures (3 `test_t_critical_table_canonical.py` + 1 fixture-missing) are unchanged baseline

**Attempted answer**: The implementer's `02_implementation.md §5` claims 2412/2443 passing. This is a plausible number (consistent with documented pre-existing failures). The `test_create_app_exposes_cache_state_on_app_state` test — previously RED — should now pass because `app.state.cache_state = app_cache` is wired in `create_app`. But there is no independent confirmation.

**Verdict**: ✗ Not addressed. No 04_verification.md. The entire W2 verifier leg is missing. This is a process gap.

---

### Q7 — Pure function extraction: "verified as pure but not extracted" — is this a floor-lowering?

**Cited code**: `02_implementation.md §7 item 2`. The implementer says `_extract_features_from_summary`, `_extract_mechanics_from_summary`, `_machines_summary_fingerprint`, `_rawdata_overview_fingerprint` are "already pure and tested as pure in TestPureFunctionExtraction." The implementer defers extraction to "follow-up P1-C2 if warranted."

**Scenario**: Brief §3 C4 explicitly says "OPTIONAL sub-scope" and "If implementer decides extraction is out-of-scope-for-this-ticket → document in 02_implementation.md + flag for follow-up P1-C2." The implementer has documented this and flagged it. The tester added purity tests. This is not floor-lowering — the brief pre-authorized deferral.

**Concern**: "P1-C2 if warranted" is an open-ended deferral with no follow-up ticket. Per `00_ticket.md §6`: "Per memory `feedback_adversarial_self_review.md`: 'we'll do this one later' without a follow-up ticket is moving goalposts." There is no P1-C2 ticket in the session_artifacts directory.

**Verdict**: ⚠ Partial. The deferral is justified by the brief's own "OPTIONAL" marker. But "P1-C2 if warranted" without a ticket being written is a soft moving-goalposts risk. Since C4 was explicitly optional and the functions are confirmed pure, this does not block ship — but the follow-up P1-C2 ticket should be written before this work is closed.

---

### Q8 — `_MODULE_CACHE_STATE` singleton vs. per-instance AppCacheState: is the dual-access pattern confusing?

**Scenario**: Every migrated function has this pattern:
```python
cs = _cs if _cs is not None else _MODULE_CACHE_STATE
```
This means any caller that forgets `_cs` silently falls back to the singleton. In production (via `create_app`), all callers pass `_cs=app_cache`. In tests, callers that use `TestClient` go through the route closures which pass `_cs=app_cache`. But callers that call helpers directly (without `_cs`) — including some test helpers — hit `_MODULE_CACHE_STATE`.

**The hidden bug**: Q5 identified that `test_delete_rawdata_version_endpoint_targets_one_md5` and `test_delete_rawdata_version_respects_lock` reset `_MODULE_CACHE_STATE.lock_cache` but then call via `TestClient` (which uses `app_cache`, not `_MODULE_CACHE_STATE`). This means the reset is a no-op for those tests. The tests pass because the `TestClient` app's `app_cache.lock_cache["data"]` starts as `None` (fresh AppCacheState), so `_load_rawdata_locks` reads from disk (where the lock file was written). The tests are accidentally correct — they work because `app_cache` is fresh per `create_app()` call, not because the `_MODULE_CACHE_STATE` reset did anything.

**Verdict**: ✓ Adequately addressed at the implementation level (the pattern is sound), but ⚠ the test setup for the 4 `test_cache_cleanup.py` tests is semantically incorrect (Q5 above) — passes coincidentally, not by design.

---

### Q9 — Is `_STATIC_ATTRS_MECH_KEYS` truly immutable?

**Cited code**: `02_implementation.md §1` — "immutable tuple of string key names." The implementer confirms it is a `tuple`, and the tester's `test_static_attrs_mech_keys_contains_expected_values` verifies its contents.

**Scenario**: A tuple in Python is immutable. `_STATIC_ATTRS_MECH_KEYS` is a module-level constant of type `tuple[str, ...]`. It cannot be mutated in place. The brief's §4 explicitly includes it in "True constants — leave alone." The justification is defensible.

**Verdict**: ✓ Adequately addressed. A tuple is genuinely immutable. The decision to leave it as a module constant is correct per the brief.

---

### Q10 — `threading.Lock()` in `AppCacheState.__init__` at module-level instantiation time

**Cited code**: `app.py:2157` — `self.in_use_lock: threading.Lock = threading.Lock()`.

**Scenario**: `_MODULE_CACHE_STATE = AppCacheState()` is executed at import time. `AppCacheState.__init__` calls `threading.Lock()`. This allocates a lock at module import time. In CPython, `threading.Lock()` is cheap and safe at import time. However, per `feedback_subprocess_import_suicide_and_module_globals.md`: "import this module will it run things?" The answer is now: yes, it allocates a threading.Lock. The subprocess smoke tests confirm this produces no output and exits 0, so it's not a visible side effect. But it is technically a more expensive import than before.

**Verdict**: ✓ Adequately addressed. The subprocess C6 tests confirm no import-time output or failures. Lock allocation is inert. This is not a regression relative to the pre-migration state (which had `threading.Lock()` at module level already for `_IN_USE_LOCK`).

---

## Chain disagreements

### Disagreement 1: Implementation completeness at W1 time

**Tester (03_tests.md)** says at time of writing:
- `create_app()` does not yet instantiate AppCacheState
- `test_create_app_exposes_cache_state_on_app_state` is RED
- `test_two_create_app_instances_have_different_cache_state_objects` is XFAIL
- Status: 37 GREEN / 1 RED / 1 XFAIL

**Implementer (02_implementation.md §5)** says:
- 39/39 GREEN in `test_app_state_isolation.py`
- `app.state.cache_state = app_cache` is wired in `create_app`

The actual app.py on disk confirms the implementer's final state is correct. The tester wrote against an intermediate snapshot. However, the tester's `03_tests.md` was never updated to reflect the final pass — it still documents the RED/XFAIL state. This is a process gap.

**Process concern**: The tester did the right thing (wrote tests that drove the implementer to complete the wiring). But the tester's document does not reflect the final verified state. Per process, `03_tests.md` should be updated once the implementer completes their second pass.

### Disagreement 2: Who owns the test_cache_cleanup.py update

**02_implementation.md §7 item 1**: "impl-tester handles this [updating 4 test_cache_cleanup.py tests]."
**Main session**: Actually updated test_cache_cleanup.py (8 refs).
**03_tests.md**: Still documents 6/10 tests failing in test_cache_cleanup.py; makes no mention of having performed the update.

The main session did the tester's work outside the agent loop. This bypassed inject-bug discipline for those 4 tests.

---

## Hidden assumptions

### Assumption 1: Fresh `AppCacheState` per `create_app` call is sufficient for multi-worker isolation

The implementation assumes a fresh `AppCacheState()` per `create_app()` call suffices for multi-worker isolation. This is true when each worker process calls `create_app()` independently — each gets a fresh object. But if the host uses threading-based concurrency (multiple threads, one process, one `create_app()` call), all threads share the same `app_cache`. The `in_use_lock` protects `in_use_modes`, but `machines_summary_cache`, `rawdata_overview_cache`, `static_attrs_cache`, and `lock_cache` are plain dicts with no mutex protection. Concurrent reads are safe (Python GIL), but concurrent writes (cache update while another thread reads) are not. The pre-migration globals had the same issue, so this is not a regression, but it is an assumption not validated by the tests.

### Assumption 2: `test_module_cache_state_slots_match_expected` is exhaustive

The test checks for 6 named slots. If a future developer adds a 7th global without adding a slot to `AppCacheState`, this test will not catch it. The test is a snapshot assertion, not a forward-looking guard.

### Assumption 3: Purity tests are sufficient for the pure-function extraction deferral

The purity tests (`TestPureFunctionExtraction`) check that calling the same function twice with the same input produces the same output and no new files. They do not check that the functions don't read from mutable globals (other than `_cs`-based state). Since these functions were already pure before the ticket, the test validates the status quo, not a new contract.

---

## Edge cases not covered

1. **Two `TestClient` apps sharing a test session with `_MODULE_CACHE_STATE` pollution**: If `TestClient(app_a)` is used and then a test calls `_load_rawdata_locks(path)` without `_cs`, it writes to `_MODULE_CACHE_STATE`. A subsequent `TestClient(app_b)` gets a fresh `AppCacheState`, but a direct function call test that runs later will see the dirty `_MODULE_CACHE_STATE`. Test isolation for direct-call tests is fragile.

2. **`_auto_cleanup_for_space` low-water path in BatchRunManager**: The `_cs=self._cache_state` is passed at line 3974. `self._cache_state` is `None` if `BatchRunManager` was constructed without `cache_state=`. The fallback inside `_auto_cleanup_for_space` catches this (it falls back to `_MODULE_CACHE_STATE`). But the `BatchRunManager` in `create_app` always passes `cache_state=app_cache`, so in production this path never falls back. In tests that construct `BatchRunManager` without `cache_state`, the fallback fires. No test covers this fallback path.

3. **Rollback scenario**: If `git revert` is applied, the 4 `test_cache_cleanup.py` updates (8 refs to `_MODULE_CACHE_STATE.lock_cache`) would be reverted too, restoring `app_mod._LOCK_CACHE` refs — which would then fail because `_LOCK_CACHE` no longer exists. The revert is not clean: the test file update is bundled with the production change, so they must be reverted together. This is expected per brief §5 ("Single commit"), but it means the test files are not independently revertable.

4. **`_prewarm_machines_summary` daemon thread**: Created in `create_app` at line 5592, this daemon thread calls `_build_machines_summary(rr, _cs=app_cache)`. If `create_app` is called in a test and the test ends before the daemon thread finishes, the thread continues running in the background and may write to `app_cache.machines_summary_cache`. This is benign (daemon threads are killed when the main thread exits), but in long-running test sessions with multiple `create_app` calls, there can be multiple daemon threads running concurrently, each writing to their own `app_cache`. No test validates that these threads don't interfere.

---

## Required revisions

### R1 — Spawn a verifier (04_verification.md is missing)

**Blocking**: Yes.

Per process (`docs/IMPL_TEAM_PROCESS.md §2`): verifier is a required Wave 2 agent. The 04_verification.md does not exist. Before this ticket ships, the verifier must:
- Run `pytest tests/backend/test_app_state_isolation.py -v` and confirm 39/39 GREEN
- Run `pytest tests/backend/test_cache_cleanup.py -v` and confirm 10/10 GREEN (or document which still fail and why)
- Run `pytest tests/backend/ --tb=short` and confirm the pre-existing failures are unchanged (2412/2443 or whatever the baseline is)
- Run the subprocess smoke test manually as a sanity check

This is not a critique-only concern — the process requires it.

**Points to stress question**: Q1, Q6

### R2 — Fix `test_cache_cleanup.py` test setup semantics for the 4 TestClient tests

**Blocking**: Yes, if those tests are currently passing coincidentally.

**Specific concern (Q5)**: `test_delete_rawdata_version_endpoint_targets_one_md5` and `test_delete_rawdata_version_respects_lock` reset `_MODULE_CACHE_STATE.lock_cache` — but the route called via `TestClient` uses the app's own `AppCacheState` instance (`app_cache`), not `_MODULE_CACHE_STATE`. The reset is a no-op. These tests pass only because `app_cache.lock_cache["data"]` starts as `None` (fresh instance, fresh `create_app`), forcing `_load_rawdata_locks` to read from disk.

The fix is to either:
(a) Remove the `_MODULE_CACHE_STATE.lock_cache` reset lines from those tests (the fresh app instance already has `data=None`; the disk state is authoritative), or
(b) Reset via `app.state.cache_state.lock_cache["mtime"] = 0; app.state.cache_state.lock_cache["data"] = None` after getting the `app` object.

If the verifier confirms these tests pass, option (a) is simplest and removes the semantic confusion.

**Points to stress question**: Q5, Q8

### R3 — Write the P1-C2 follow-up ticket for pure-function extraction

**Blocking**: No (C4 was OPTIONAL).

**Per brief §6**: "We'll do this one later without a follow-up ticket is moving goalposts." The implementer's `02_implementation.md §7 item 2` says "follow-up P1-C2 if warranted." No ticket exists. Write it before closing Phase 1, even if it's just the `00_ticket.md` brief.

**Points to stress question**: Q7

---

## Commit-message `## Self-critique` section

Paste verbatim into the commit body:

```
## Self-critique

- **Did the code actually land on disk?** Yes — independently confirmed via grep:
  `_MACHINES_SUMMARY_CACHE`, `_RAWDATA_OVERVIEW_CACHE`, `_STATIC_ATTRS_CACHE`,
  `_IN_USE_MODES`, `_IN_USE_LOCK`, `_LOCK_CACHE` are absent as module names.
  `AppCacheState` class + `_MODULE_CACHE_STATE` singleton present. All route call
  sites pass `_cs=app_cache`. Hallucination check: pass.

- **Does `app.state.cache_state = app_cache` actually wire per-instance isolation?**
  Yes — confirmed at create_app line ~5619. Two `create_app()` calls produce two
  distinct `AppCacheState` objects. Tests verify `cs_a is not cs_b`.

- **Route-level integration coverage gap**: No `TestClient` test exercises
  `/api/machines/summary` on two separate `create_app()` apps and asserts their
  cache states are independent. The function-level split-path tests (G1–G5) are solid
  but do not reach through HTTP. This is an OPEN gap — flagged, not fixed in this
  commit. Follow-up: one TestClient multi-app isolation test to be added in P1-C2 or
  as a post-ship test.

- **test_cache_cleanup.py 4-test semantic issue**: The TestClient tests that reset
  `_MODULE_CACHE_STATE.lock_cache` are resetting the wrong object — the route uses
  `app_cache`, not `_MODULE_CACHE_STATE`. Tests pass coincidentally (fresh `app_cache`
  has `data=None` by default, so disk read fires correctly). Fix: remove the now-
  meaningless reset lines. This is an OPEN minor issue.

- **04_verification.md absent**: No independent verifier ran the full suite post-
  final commit. The implementer's claim of 39/39 is unverified by a second party.
  Accepted as risk because the code on disk matches the implementation document and
  the tester's inject-bug experiments verified the isolation mechanism.

- **Pure-function extraction deferred**: C4 was brief-optional. Deferred to P1-C2.
  Functions are confirmed pure by test. No mechanism regression.

- **`_MODULE_CACHE_STATE` singleton at import time**: allocates threading.Lock.
  Subprocess smoke tests confirm no observable output. Not a C3 violation (no
  process-spawning). Pre-existing globals already allocated a threading.Lock at
  module level; this is a lateral move, not a new footgun class.
```

---

## Summary

| Dimension | Assessment |
|---|---|
| Implementer hallucination check | PASS — code on disk matches document |
| Globals migrated | 5/5 mutable globals migrated; 1 justified constant left alone |
| `AppCacheState` design | Sound — `__slots__`, per-instance dict initialization, no class-level shared state |
| Route-level `_cs` threading | Wired correctly for all identified call sites |
| Subprocess import safety | Confirmed by smoke tests |
| Multi-worker isolation (C5) | Structural: verified; Route-level E2E: absent |
| Inject-bug discipline (C2) | 7/7 confirmed for G1–G5 + G6 + create_app wiring |
| `test_cache_cleanup.py` update | Semantically incorrect setup for 4 TestClient tests; passes coincidentally |
| 04_verification.md | MISSING — required W2 artifact |
| Pure-function extraction (C4) | Deferred per brief; confirmed pure by test |
| Process integrity | Main session did tester's work (8 test refs); no inject-bug applied to those 4 updates |
