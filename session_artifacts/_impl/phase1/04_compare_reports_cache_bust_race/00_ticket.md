# Ticket P1-A5 — `compareReports` cache-bust race fix (Batch 1b)

> Phase 1 / Batch 1b. Actual bug fix in the frontend — when a report version is DELETEd while the user has it selected for comparison, the UI can show stale data.

---

## §1 Ticket scope

Fix the frontend race: `DELETE /api/reports/.../{version}` (backend `app.py:7735`) can run while the user has the deleted version in `state.compareSelected` (frontend `app.js:119`) — possibly mid-`_enterCompareMode` fetch. Today the deletion clears the file on disk but the frontend keeps showing the stale comparison until the user manually refreshes.

Files expected to change:
- `src/web_console/frontend/app.js` (around `compareReports:3477`, `_enterCompareMode:3505`, `compareSelected:119`, per-row delete handler near `2487`)
- `tests/frontend/test_compare_reports_cache_bust.{py,js}` (new — if existing frontend test harness in `tests/frontend/`; otherwise add `tests/integration/` Python test driving preview server)

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §5 Q8` — race documented
- Memory `feedback_error_branch_resets_all_state.md` — half-reset is UI lying; every related state slot must reset together
- Memory `feedback_fasttimer_overlap_needs_oneshot.md` — concurrent fetches need one-shot guard
- Memory `feedback_frontend_verify_before_commit.md` — preview-verify before commit
- Memory `feedback_dont_swallow_errors_in_fix.md` — don't wrap fetches in catch-all try/catch

---

## §3 Contract (testable invariants)

### C1 — Map clears on DELETE
When `DELETE /api/reports/{machine}/mode/{n}/versions/{rv}` succeeds, every entry in `state.compareSelected` with matching `(machine, mode, version)` is removed. Verifiable: trigger DELETE → grep `state.compareSelected.has(rv)` returns false.

### C2 — Compare-mode exit on DELETE during comparison
If user is currently in `_enterCompareMode(a, b, vA, vB)` and DELETE removes either vA or vB → exit compare mode, reset compare-related UI panels per memory `feedback_error_branch_resets_all_state.md`. Single `_resetCompareModeToEmpty()` helper that clears every panel the success path fills.

### C3 — In-flight fetch guard
If `compareReports()` or `_enterCompareMode()` has an outstanding fetch when DELETE fires for one of the compared versions → the fetch's response is discarded on completion (one-shot guard per memory `feedback_fasttimer_overlap_needs_oneshot.md`). Use a per-compare-invocation id (e.g., `state._compareInvocationId`) — fetch checks invocation id matches state's current id before applying response.

### C4 — No silent swallow
Per memory `feedback_dont_swallow_errors_in_fix.md`: do NOT wrap the fix in `try { } catch (_) { }`. If DELETE races with a 200 response that was in-flight, fail visibly (toast or console.warn) so the bug is reportable.

### C5 — Inject-bug TDD
Tester: revert the cache-bust fix → fakes a DELETE during compare via preview-eval JS → assert UI still shows the stale data (test red). Restore → test green. Document in `03_tests.md`.

### C6 — Preview-verified
Per memory `feedback_frontend_verify_before_commit.md`: verifier opens preview server, manually simulates the race (select v1+v2 for compare, click DELETE v1, observe UI exits compare cleanly). Screenshot before/after in `04_verification.md`.

---

## §4 Out of scope

- Refactoring `DELETE /api/reports/...` backend route
- Adding optimistic-UI to compare mode
- Adding undo for DELETE

---

## §5 Rollback path

Single commit. `git revert <sha>` restores prior compare behavior. The race remains as-is (acceptable — it's been latent for months).

---

## §6 Risk + rollback notes

**Risk class**: MEDIUM. Frontend UI change with race-condition logic — easy to introduce new races if not carefully tested.

**Existing tests affected**: any frontend tests that exercise compare mode. If none exist, that's also a finding (compare mode is untested?). impl-tester adds the regression test in this ticket; if surrounding compare-mode coverage is needed, flag for separate ticket.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — writes the cache-bust fix per §3 C1-C4 + `02_implementation.md`
- `impl-tester` — writes the regression test + inject-bug verification per §3 C5

### Wave 2 (parallel)
- `impl-verifier` — preview-verifies the flow per §3 C6 + runs all frontend / integration tests
- `impl-critic` — checks: are all DELETE paths covered (per-row delete + bulk delete + per-version DELETE button)? Per memory `feedback_enumerate_safety_paths.md`. Was any error swallowed silently?

Expected wall time: ~45-60 min (frontend + preview verify is slower).
