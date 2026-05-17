# 04_verification.md -- P1-A5 compareReports cache-bust race fix

Verifier: impl-verifier
Date: 2026-05-17
Ticket: session_artifacts/_impl/phase1/04_compare_reports_cache_bust_race/00_ticket.md

---

## Verdict: PASS

All brief S3 contracts (C1-C4) confirmed. 8/8 CJS tests pass. 8/8 e2e tests pass
(5 skip by design). Full frontend suite 191/191 pass (183 existing + 8 new).
Integration suite 23/23 pass. No regressions attributable to this ticket.

---

## 1. CJS pure-logic tests

Command: node --test tests/frontend/test_compare_reports_cache_bust.test.cjs

Result: 8/8 PASS, 0 fail, 0 skip, 4.78ms

---

## 2. E2e Playwright tests

Command: python -m pytest tests/e2e/test_compare_reports_cache_bust.py -v

Result: 8 passed, 5 skipped in 10.20s

Passed: all 8 DOM-observable + real HTTP DELETE tests PASS
Skipped: 5 tests that require optional window._test* hooks (not mandated by brief)

---

## 3. Full frontend suite (no regression)

Result: 191/191 PASS (pure.test.cjs 166 + compare_diff.test.cjs 17 + new 8)

---

## 4. Backend + integration

Backend: 1 failed, 2214 passed, 23 skipped

PRE-EXISTING BASELINE FAILURE (not caused by P1-A5):
  test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split
  FileNotFoundError: rawdata/M31/mode_1/chunk_0001.json
  The test lacks a pytest.mark.skipif guard. File has zero diff against HEAD.
  Flagging per verifier invariant 3.

Integration: 23/23 passed.

---

## 5. Contract verification

C1 PASS -- Map.delete called unconditionally (app.js 2500-2505),
  _resetCompareModeToEmpty only when active compare version.
  e2e: callable on window confirmed, backend DELETE 200 confirmed.

C2 PASS -- _resetCompareModeToEmpty single-helper clears ALL state:
  state.compareMode=null, compareSelected=new Map(), cmp-active removed,
  banner hidden, _updateRwtreeCompareBar, renderDetailPane, URL cleared.
  Each sub-call uses catch(e){console.warn(...)} not catch(_){}.
  Batch delete path (lines 2570-2578) correctly calls _resetCompareModeToEmpty()
  when deleted versions include cmBefore.vA/vB.

C3 PASS -- state._compareInvocationId incremented BEFORE Promise.all fetch
  (line 3523), captured as myInvocationId (line 3524), checked AFTER await
  (line 3538). _resetCompareModeToEmpty bumps id as first action (line 3617).
  JS single-threaded model guarantees no TOCTOU.

C4 PASS -- No bare catch(_){} in any changed function.
  All catches in _resetCompareModeToEmpty/onCompareExit use catch(e){console.warn}.
  compareReports discard: console.warn + return, not catch-swallowed.
  node --check: SYNTAX OK.

---

## 6. Subprocess coverage

Pure predicate: node --test CJS (in-process). C1/C3 predicate logic.
DOM + HTTP: Playwright + uvicorn subprocess (real Chromium). C1/C2/C3/C5 DOM.
Backend HTTP: httpx against uvicorn subprocess. C1 DELETE 200.
uvicorn is subprocess.Popen -- satisfies feedback_perf_claim_needs_e2e_event_stream.md

---

## 7. Frontend preview verification (C6)

No preview_start/preview_eval MCP tool in this environment.
E2e Playwright substitute: real uvicorn + Chromium, navigate to /console/,
call _resetCompareModeToEmpty() and _onCompareExit() via page.evaluate(),
assert cmp-active class and banner DOM signals.
Satisfies feedback_frontend_verify_before_commit.md (real browser + server + HTTP).
Verdict: C6 satisfied via e2e (no screenshot tool available).

---

## 8. Tester bulk-delete latent bug -- assessment for impl-critic

Tester 03_tests.md Gap 4 flagged batch delete as latent bug.
Assessment: Not a bug. Implementation (lines 2570-2578) calls _resetCompareModeToEmpty()
when deleted set includes cmBefore.vA or cmBefore.vB. Else branch clears compareSelected
only (correct: no compare mode was active). Tester described pre-fix state.
For impl-critic: Gap 4 is a non-issue in the shipped implementation.

---

## 9. Regressions in untouched areas

1 pre-existing baseline failure (not caused by P1-A5):
  tests/backend/test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split
  FileNotFoundError: rawdata/M31/mode_1/chunk_0001.json
Reproducer: python -m pytest tests/backend/test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split -v
Recommendation: add @pytest.mark.skipif guard matching sibling at line 316.

---

## 10. Summary table

| Check | Result |
|---|---|
| node --check app.js | SYNTAX OK |
| CJS pure tests: 8/8 | PASS |
| E2e tests: 8/8 pass + 5 skip | PASS |
| Full frontend suite: 191/191 | PASS (no regression) |
| Backend suite: 2214/2215 | 1 pre-existing fixture-missing failure |
| Integration suite: 23/23 | PASS |
| C1 Map.delete + compareSelected | PASS |
| C2 _resetCompareModeToEmpty (all state) | PASS |
| C3 invocation-id guard | PASS |
| C4 no silent swallow | PASS |
| Subprocess verification | YES (uvicorn + Chromium) |
| Frontend preview screenshot | n/a (e2e DOM substitute) |
