# 05_critique.md — Ticket P1-A5 compareReports cache-bust race fix

Reviewer: impl-critic
Date: 2026-05-17
Verifier file: 04_verification.md — ABSENT (verifier is parallel; running without it)

---

## Verdict: APPROVE-WITH-REVISIONS

Two confirmed bugs require a second implementer pass:

1. **Per-row delete handler: C2 logic gap** — deleted version is removed from `compareSelected` even when `_resetCompareModeToEmpty()` is NOT called, leaving the Map one element short but `compareMode` still active.
2. **`_restoreCompareFromUrl`: C4 violation** — outer `catch (_e)` swallows all errors including genuine runtime errors, with zero diagnostic output.

---

## 5-10 stress questions

---

### Q1 — Tester's flagged bulk-delete bug: what is it actually?

**Question:** 03_tests.md Gap 4 says the batch handler "sets `state.compareSelected = new Map()` but does NOT call `_resetCompareModeToEmpty()`." Is this true in the committed code?

**Investigation:** Reading `app.js:2566-2578`:
```
const deletedVersions = entries.map(([rv]) => rv);
if (cmBefore && (
  deletedVersions.includes(cmBefore.vA) ||
  deletedVersions.includes(cmBefore.vB)
)) {
  _resetCompareModeToEmpty();
} else {
  state.compareSelected = new Map();
}
```

The tester's Gap 4 description is outdated — it describes the pre-fix code. The implementer DID add `_resetCompareModeToEmpty()` for the compare-case branch. The `else` branch fires when `cmBefore` is null or when the deleted versions don't overlap `vA/vB`, which is correct behavior (no active compare to exit, just clear the selection).

**However**, there is a subtler issue in the `else` branch: it clears `state.compareSelected = new Map()` but does NOT bump `state._compareInvocationId`. If a `compareReports()` fetch is in-flight at the time of the bulk delete (user clicked "对比" just before batch-deleting unrelated versions), the in-flight fetch will still apply its result after the map is cleared. In the `else` branch the compare-mode versions are NOT deleted, so this is debatable as a risk; the invocation ID guard only matters when the version being fetched is also the one being deleted. For the `else` branch the batch-deleted versions are not the compare-mode versions, so the fetch can legitimately complete. The guard's purpose is specifically to prevent applying data for a deleted version — not every Map clear. This is therefore NOT a bug.

**Verdict:** ✓ The tester's flagged bulk-delete concern was describing pre-fix code. The committed implementation correctly handles the batch-delete path. No bug here, but the tester's Gap 4 misleads the reader into thinking this is still open.

---

### Q2 — Per-row delete handler: C2 logic gap (double-write vs gate)

**Question:** At `app.js:2500-2505`, the per-row delete handler does:
```js
const wasInCompare = state.compareSelected?.has?.(rv);
state.compareSelected?.delete?.(rv);  // line 2501
const cm = state.compareMode;
if (wasInCompare && cm && (cm.vA === rv || cm.vB === rv)) {
  _resetCompareModeToEmpty();           // line 2504 — also deletes via new Map()
}
```
When `_resetCompareModeToEmpty()` is called at line 2504, it sets `state.compareSelected = new Map()` internally (clearing ALL entries), which supersedes the `delete(rv)` at line 2501 — fine, idempotent. When `_resetCompareModeToEmpty()` is NOT called (user had `rv` in `compareSelected` but NOT as `vA` or `vB`, i.e. `wasInCompare=true` but the version was selected-but-not-active), line 2501 removes `rv` from the map correctly.

But: what if `wasInCompare=false` and `cm` exists with `cm.vA === rv`? This scenario: the user selected 2 versions for compare, triggered compare mode, then DESELECTED vA from the checkbox (removing it from `compareSelected`), but compare mode is still active (`compareMode.vA` still holds `rv`). Now `wasInCompare=false` and the `if` at line 2503 evaluates to `false && ...` = `false`. The per-row delete of `rv` succeeds on disk, `compareSelected` has it removed (it wasn't there), but `compareMode.vA` still points to the now-deleted version and compare mode stays active. The UI continues showing stale data for version `rv`.

**Attempted answer:** Is this scenario reachable? `compareMode.vA` is set by `_enterCompareMode` from the entries in `compareSelected` at the time `compareReports()` was called. After entering compare mode, the user can clear individual checkboxes. If the user unchecks `rv` (vA) while in compare mode, `compareSelected.delete(rv)` runs in the checkbox handler, but `compareMode.vA` still points to `rv`. Then a per-row delete of `rv` hits this exact path.

**Verdict:** ✗ This is a real bug. The guard at line 2503 should be:
```
if (cm && (cm.vA === rv || cm.vB === rv))
```
without requiring `wasInCompare`. C2 contract says "if user is currently in `_enterCompareMode(a, b, vA, vB)` and DELETE removes either vA or vB → exit compare mode." The brief's C2 does not require the version to be in `compareSelected`; it requires the version to match `compareMode.vA` or `compareMode.vB`. The `wasInCompare &&` gate is an incorrect extra precondition.

---

### Q3 — `_resetCompareModeToEmpty` completeness: does it clear every slot that `_enterCompareMode` fills?

**Question:** `_enterCompareMode` (line 3556-3583) sets the following:
- `state.compareMode = { a, b, vA, vB }` — cleared by `_resetCompareModeToEmpty` ✓
- `switchTab("debug")` — NOT reversed by `_resetCompareModeToEmpty` (no `switchTab` call)
- `_renderCompareBanner()` — called by `_resetCompareModeToEmpty` ✓ (clears banner when `compareMode=null`)
- URL `?compare=` param — cleared by `_resetCompareModeToEmpty` ✓
- `state.latestSummary = a` — NOT cleared by `_resetCompareModeToEmpty`
- `document.body.classList.add("cmp-active")` — cleared by `_resetCompareModeToEmpty` ✓
- `_paintAnalysisFromSummary(a)` — this populates KPI tiles, bucket table, payIdOverviewPanel, etc. via `_paintAnalysisFromSummary`. `_resetCompareModeToEmpty` calls `renderDetailPane()` but does NOT call `_resetDebugPanelsToEmpty()`.

Specifically: `state.latestSummary` is set to the compare-mode `a` summary at line 3576. `_resetCompareModeToEmpty` deliberately does not clear it (02_implementation.md open issue #4: "by design"). `_onCompareExit` then uses `state.latestSummary` for its repaint. This design choice is intentional and documented.

The memory `feedback_error_branch_resets_all_state.md` says "every related state slot must reset together." `state.latestSummary` is tied to compare mode (it was set BY `_enterCompareMode`). After delete-triggered reset, it points to data from the now-deleted version A. The `_onCompareExit` repaint guard at line 3646 checks `if (state.latestSummary)` before repainting — but the implementer notes "_onCompareExit does NOT repaint on delete path" (which is `_resetCompareModeToEmpty` directly, not `_onCompareExit`). So no spurious repaint occurs on the delete path.

BUT: `state.latestSummary` still contains stale data from the deleted version. Any subsequent code that checks `state.latestSummary` (e.g. a timer re-painting the panel, or a user later clicking a different machine that falls into a path that references `latestSummary` before overwriting it) could use the stale summary. The `_resetDebugPanelsToEmpty` helper at line 6694 explicitly clears `state.latestSummary = null` — but `_resetCompareModeToEmpty` does not call it.

**Verdict:** ⚠ Partial. The design choice is intentional and the immediate repaint-on-delete path is safe. But `state.latestSummary` retains stale data from a deleted version after `_resetCompareModeToEmpty`. This is a hidden assumption: if any polling path reads `latestSummary` before the next user interaction sets it, it would use deleted-version data. Not an immediate crash, but a potential silent lie. The implementer should at minimum document this as a risk in code comments (it currently appears only in `02_implementation.md`).

---

### Q4 — C4 no-silent-swallow: `_restoreCompareFromUrl` catch block

**Question:** `_restoreCompareFromUrl` (line 3657-3682) has an outer `catch (_e)` at line 3674 that swallows ALL errors from the URL-restore path — including genuine JS runtime errors (TypeError, ReferenceError) that could arise from the new code paths. The comment says "Bad / stale ?compare= — strip it and continue normal boot." But this catch encompasses all exceptions from `apiGet` calls AND from `_enterCompareMode`, not just URL-parse errors.

**Per memory `feedback_dont_swallow_errors_in_fix.md`:** "修 bug 时加 `try {} catch (_) {}` 会吞掉 ReferenceError / scope 类错误."

**Is this a new catch or pre-existing?** This code (lines 3657-3682) appears to be PRE-EXISTING — the `_restoreCompareFromUrl` function is not listed in 02_implementation.md's "Change summary by region." The implementer flagged this as out-of-scope at open issue #2.

**However**, the `_enterCompareMode` at line 3673 is the same function that now has compare-mode-entry logic. If a bug in `_enterCompareMode` throws post-fix, the `_restoreCompareFromUrl` catch would silently swallow it. The outer catch in `_restoreCompareFromUrl` predates this ticket but the risk surface increased because `_enterCompareMode` now interacts with `compareMode` state more deeply.

**Verdict:** ⚠ Partial. This catch is pre-existing and out of scope per the brief. But the implementer explicitly called it out at open issue #2 ("left as-is (out of scope per brief §4)"). The tester and verifier need to flag it for a follow-on ticket. It is not a regression introduced by this fix, so it does not warrant REJECT.

---

### Q5 — 5 skipped e2e tests: are they critical paths or genuinely optional?

**Question:** 5 e2e tests are marked `pytest.skip` because they require `window._testGetCompareSelectedSize`, `window._testCompareSelectedHas`, `window._testGetCompareInvocationId`, `window._testSetCompareSelected`, `window._testSetCompareMode`, `window._testTriggerDeleteCompareCleanup` hooks that the implementer did NOT add to `app.js`.

Looking at the test code (e2e test file), these skipped tests cover:
- `test_c1_initial_compare_selected_is_empty` — C1 state, covered by DOM indirectly
- `test_c1_delete_clears_version_from_compare_selected_via_hook` — C1 wiring test; tester acknowledges this is impl-verifier scope (Gap 1)
- `test_c3_delete_increments_compare_invocation_id` — C3 invocation-id bump by delete handler (requires `_testTriggerDeleteCompareCleanup`)
- `test_c5_on_compare_exit_clears_compare_selected_via_hook` — C5 exit clears compareSelected

**Are these critical?** The invocation-id bump by the delete handler (`test_c3_delete_increments_compare_invocation_id`) IS a critical contract — C3 is the main race guard. Its correctness is covered by CJS pure tests, but the wiring test (delete handler actually calls `_resetCompareModeToEmpty` which actually bumps the counter) has NO passing automated test. The tester's inject-bug log Bug 3 is an inline proof, not a live test.

**Verdict:** ⚠ The 5 skipped tests represent real gaps, particularly `test_c3_delete_increments_compare_invocation_id`. The CJS tests prove the guard PREDICATE works if the function is called, but do not prove the DELETE HANDLER actually calls `_resetCompareModeToEmpty`. This wiring gap is acknowledged in Gap 1 of 03_tests.md but assigned to impl-verifier as "C6 preview scope." If the verifier's 04_verification.md (absent) doesn't cover this, C3 wiring is untested by any automated test.

---

### Q6 — `_compareInvocationId` monotonicity: does the implementation handle `state._compareInvocationId` being undefined at first read?

**Question:** `state._compareInvocationId = (state._compareInvocationId || 0) + 1` at line 3523 and 3617 uses `|| 0` as fallback. The state initializer sets `_compareInvocationId: 0` at line 129. The fallback is defensive-only. If `state` is partially constructed (race during boot), the `|| 0` prevents NaN. This is correct.

But `compareReports` at line 3523 increments FIRST, then captures: `state._compareInvocationId = ... + 1; const myId = state._compareInvocationId;`. The check at line 3538 is `myInvocationId !== state._compareInvocationId`. If `compareReports()` is called twice concurrently (user double-clicks 对比), the second invocation will bump the id AFTER the first captures it but BEFORE the first fetch completes. The first invocation's guard check will then discard its result (false positive discard). This is benign — the second fetch will apply, which is correct.

**Verdict:** ✓ Correctly designed. The `|| 0` fallback is defensive and correct. The double-click case discards the first fetch, applies the second — acceptable behavior.

---

### Q7 — C3 in-flight guard: does `_resetCompareModeToEmpty` bumping BEFORE clearing `compareMode` create a window where `compareMode` is non-null but the invocation id has advanced?

**Question:** `_resetCompareModeToEmpty` at lines 3614-3637 does:
1. Line 3617: bumps `_compareInvocationId` (C3 invalidation)
2. Line 3618: sets `state.compareMode = null`

Between step 1 and step 2 (both synchronous in JS event loop, so no actual gap), is there any path that could read `compareMode` as non-null but treat the invocation as invalid? No — JS is single-threaded, these two lines execute atomically in one synchronous block. No microtask can interrupt between them.

**But**: `compareReports()` at line 3538 checks `myInvocationId !== state._compareInvocationId` AFTER the `await Promise.all`. After this guard passes (or fails), `_enterCompareMode(a, b, vA, vB)` is called (line 3545). `_enterCompareMode` then sets `state.compareMode = { a, b, vA, vB }` (line 3557). If the guard check passes (IDs match), then the guard didn't fire `_resetCompareModeToEmpty`, so `compareMode` was null (or old) and gets set to fresh data. Correct.

If the guard check FAILS (IDs differ), the function returns at line 3543. `_enterCompareMode` is NOT called. `compareMode` remains null (from the prior `_resetCompareModeToEmpty`). Correct.

**Verdict:** ✓ The ordering of state mutations in `_resetCompareModeToEmpty` is correct and the single-threaded JS model makes it atomic.

---

### Q8 — Per memory `feedback_no_parallel_panel_impl.md`: did the implementer create parallel helpers?

**Question:** `_resetCompareModeToEmpty` is a new helper. Does it duplicate any existing function?

Candidates to check: `_onCompareExit` (existing) — no, that was a separate exit function that now CALLS `_resetCompareModeToEmpty`. `_resetDebugPanelsToEmpty` (existing, line 6694) — clears ALL debug panels including `state.latestSummary`. `_resetCompareModeToEmpty` is scoped to compare-mode state only, deliberately not clearing `latestSummary` or KPI tiles (its design rationale is documented in 02_implementation.md open issue #4).

These are NOT parallel implementations — they serve different scopes. `_resetDebugPanelsToEmpty` is the "full debug tab clear" (used on 404/no-run-id), `_resetCompareModeToEmpty` is the "compare mode teardown" (used on DELETE/exit). Both are legitimately distinct.

**Verdict:** ✓ No parallel impl created. `_resetCompareModeToEmpty` is a focused new helper that delegates to existing functions (`_renderCompareBanner`, `_updateRwtreeCompareBar`, `renderDetailPane`) rather than reimplementing them.

---

### Q9 — Backend DELETE returning 404 for already-deleted version: what does the frontend do?

**Question:** The per-row delete handler at line 2491-2505 calls `apiDelete(...)`. If the backend returns 404 (version already deleted by another tab, or double-click), `apiDelete` presumably throws. The `catch` at line 2508 alerts and re-enables the button. The C1/C2 cleanup at lines 2500-2505 is inside the `try` block (after the `await`), so it does NOT run on 404.

Is this correct? If the version is already deleted on disk, `compareSelected` still has it (user has it checked), and `compareMode` still references it. The user sees an alert "删除失败" and the stale version remains checked and visible in compare mode. This is arguably incorrect — a 404 means the version IS deleted, so the UI should still remove it from `compareSelected`.

However: this is a pre-existing behavior of the `catch` block (not introduced by this ticket). The ticket only specifies what to do on SUCCESS. And a 404 in single-tab normal usage is unusual.

**Verdict:** ⚠ Real edge case, pre-existing, out of scope for this ticket. The ticket brief §4 explicitly limits scope to the race fix; 404 handling is not mentioned. Flag for a follow-on ticket.

---

### Q10 — State leak across page sessions: `state._compareInvocationId` starts at 0 on each page load. Is there cross-tab contamination?

**Question:** JS `state` is a `const` object initialized fresh on each page load. Tabs are independent browser contexts. `_compareInvocationId` is per-tab. No cross-tab contamination possible via `state`. URL `?compare=` persistence is handled by `_restoreCompareFromUrl` — each tab loading a shared URL with `?compare=` would each restore their own independent `compareMode`.

**Verdict:** ✓ No cross-tab state leak. Each tab owns its own `state` object.

---

## Chain disagreements (implementer vs tester vs verifier)

### Disagreement D1: Tester's Gap 4 vs committed code

03_tests.md Gap 4 describes the batch-delete handler as NOT calling `_resetCompareModeToEmpty` when a compared version is deleted. The committed code at `app.js:2571-2575` DOES call it. The tester's description of the "latent bug" is factually wrong for the committed code. This creates a misleading signal for impl-critic (the task setup says "tester FLAGGED bulk-delete path latent bug for your attention"). The implemented bulk-delete path is actually correct; the tester's description was written against a draft.

**Impact:** None on correctness. But if a future reviewer reads Gap 4 and treats it as live, they will waste time investigating a non-existent bug.

### Disagreement D2: 04_verification.md absent

The verifier's artifact is absent. Brief §7 says Wave 2 runs impl-verifier and impl-critic in parallel, so absence is expected. However: C6 (preview-verified, `feedback_frontend_verify_before_commit.md`) requires a live preview verify before commit. This is unverified. The tester's Gap 1 explicitly defers the click→delete→DOM wiring test to impl-verifier scope. If 04_verification.md is never produced or doesn't cover that wiring, C3 wiring has zero automated coverage.

### Disagreement D3: Brief C2 scope vs implementer's per-row guard

Brief C2 says: "if user is currently in `_enterCompareMode(a, b, vA, vB)` and DELETE removes either vA or vB → exit compare mode." The implementer added an extra precondition `wasInCompare &&` at line 2503. This narrows C2 below what the brief specifies (see Q2 above). Brief and implementation disagree.

---

## Hidden assumptions

### HA1 — `wasInCompare` as proxy for "version is in active compare"

The per-row delete handler uses `wasInCompare = state.compareSelected?.has?.(rv)` as a gate before checking `compareMode.vA/vB`. This assumes that any version in an active compare will ALWAYS also be in `compareSelected`. This is false after the user unchecks a checkbox while in compare mode (see Q2). The assumption is hidden — not documented anywhere in the implementation notes or tests.

### HA2 — `state.latestSummary` is safe to retain after compare-mode delete

`_enterCompareMode` sets `state.latestSummary = a` (line 3576). `_resetCompareModeToEmpty` leaves `latestSummary` intact. The assumption is that no code path will auto-repaint from `latestSummary` after the delete-triggered reset without the user taking an explicit action. This relies on no polling timer reading `latestSummary` autonomously. The implementer documents this assumption in 02_implementation.md open issue #4 but it is not validated by any test.

### HA3 — Invocation-id guard is the ONLY race vector in compare mode

The fix guards `compareReports()` → `_enterCompareMode()`. But `_restoreCompareFromUrl()` also calls `_enterCompareMode()` (line 3673) WITHOUT an invocation-id guard. The assumption is that URL-restore-triggered compare mode is not a race vector. This holds on fresh page load (no concurrent DELETE possible before the page is loaded), but if a user shares a `?compare=` URL and someone deletes one of the versions before the page finishes loading, the `_enterCompareMode` call in `_restoreCompareFromUrl` will succeed (the DELETE hasn't cleared local state yet since page just loaded) and display stale data — which is the original bug. The implementer documents this at open issue #2.

---

## Edge cases not covered

### EC1 — User unchecks vA checkbox while in compare mode, then deletes vA via per-row button

Scenario: user enters compare mode (vA + vB selected), then unchecks vA's checkbox. `compareSelected` no longer has vA, but `compareMode.vA` still points to vA. User then clicks the per-row delete button for vA. Handler: `wasInCompare = state.compareSelected?.has?.(rv)` → false (unchecked). `state.compareSelected?.delete?.(rv)` — no-op (not in map). Guard `if (wasInCompare && ...)` → false. `_resetCompareModeToEmpty()` NOT called. Compare mode stays active with `compareMode.vA` pointing to deleted data. **This is the confirmed bug from Q2.**

### EC2 — `_resetCompareModeToEmpty()` called while `renderDetailPane()` is async mid-paint

`_resetCompareModeToEmpty` calls `renderDetailPane()` synchronously (lines 3625-3627). `renderDetailPane` itself is synchronous but calls `showMachineDetail(focused)` which may trigger async side-effects. Not a correctness issue (the state is cleared before the call), but the detail pane rerender may race with compare-mode KPI tiles still being painted by a prior async `_paintAnalysisFromSummary` call. Low severity: the compare-mode KPI values would briefly appear before being overwritten by the `renderDetailPane` call. Cosmetic, not data-integrity.

### EC3 — Batch-delete deletes BOTH vA and vB simultaneously

The batch handler checks `cmBefore.vA` OR `cmBefore.vB`. If both are in `deletedVersions`, `_resetCompareModeToEmpty()` is called once. This is correct — idempotent. ✓

### EC4 — Bulk delete of versions NOT in compareSelected but which ARE compareMode.vA/vB

Same root cause as EC1 / Q2. If vA was deselected from the batch-select bar before batch delete, it's not in `entries` (batch delete only deletes what's in `compareSelected`). So `deletedVersions` wouldn't include vA. `compareMode.vA` still points to deleted data if another mechanism deleted vA. Actually, the batch delete handler builds `entries` from `state.compareSelected` at the time of the click — if vA is not in `compareSelected`, it can't be batch-deleted via this path. This is a different scenario than EC1 and is not a bug.

### EC5 — DELETE during `_restoreCompareFromUrl` fetch on page load

On page load with `?compare=v1,v2`, `_restoreCompareFromUrl` fires two `apiGet` calls. If v1 is deleted by another client mid-fetch, the `apiGet` for v1 returns 404. The outer `catch (_e)` at line 3674 catches this, strips the URL param, and continues — which is correct behavior. But the catch also swallows genuine JS runtime errors (see Q4). Low risk in practice.

---

## Required revisions

### R1 (REQUIRED — fixes confirmed bug Q2/EC1): Per-row delete handler C2 guard condition

`app.js:2503`: Change:
```js
if (wasInCompare && cm && (cm.vA === rv || cm.vB === rv)) {
```
to:
```js
if (cm && (cm.vA === rv || cm.vB === rv)) {
```
(Remove `wasInCompare &&` precondition.) The C2 contract is "if DELETE removes vA or vB → exit compare mode," regardless of whether `rv` is still in `compareSelected`.

The `state.compareSelected?.delete?.(rv)` at line 2501 should remain (it's correct to also clear it from the map if present). The `_resetCompareModeToEmpty()` call will clear the entire map anyway via `state.compareSelected = new Map()`.

### R2 (REQUIRED — closes tester's misleading Gap 4): Update 03_tests.md Gap 4 description

03_tests.md Gap 4 should be updated to reflect that the committed batch-delete path IS correct, and the "latent bug" description is no longer accurate. This is a documentation-only correction so the future reviewer isn't misled.

### R3 (REQUIRED for C3 wiring coverage): Either add window test hooks or document that C3 wiring is verifier-verified-only

If 04_verification.md (absent) does not provide evidence that the click→delete→`_resetCompareModeToEmpty()` wiring was manually verified, this is an untested C3 wiring gap. The team must either:
- Add `window._testGetCompareInvocationId`, `window._testTriggerDeleteCompareCleanup` hooks to `app.js` (un-skipping 3 e2e tests), OR
- Produce `04_verification.md` with explicit evidence that the wiring was manually tested.

---

## Commit-message `## Self-critique` section

Ready to paste into the commit body verbatim:

```
## Self-critique

- Q: Does the per-row delete handler's `wasInCompare &&` guard cover all C2 paths?
  A: NO — if the user unchecks vA from compareSelected while in compare mode, then
  deletes vA via the per-row button, `wasInCompare` is false and `_resetCompareModeToEmpty`
  is not called despite `compareMode.vA === rv`. Bug confirmed. Requires R1 revision.

- Q: Does the tester's "bulk-delete latent bug" in Gap 4 reflect the committed code?
  A: No — the committed batch handler correctly calls `_resetCompareModeToEmpty()` for
  the compare-mode case. Gap 4 describes pre-fix code. Gap 4 description is misleading
  and needs correction (R2).

- Q: Is `state.latestSummary` safe to retain stale data after delete-triggered reset?
  A: Partially — no auto-repaint fires on the delete path, so no immediate UI lie.
  But latestSummary holds deleted-version data until next user action. Documented
  assumption (HA2), not fixed in this pass. Follow-on ticket recommended.

- Q: Does `_restoreCompareFromUrl`'s outer `catch (_e)` silently swallow runtime errors?
  A: Yes — pre-existing, out of scope per brief §4. The new compare paths routed
  through `_enterCompareMode` increase the blast radius. Follow-on ticket to add
  `console.warn(_e)` at minimum.

- Q: Are the 5 skipped e2e tests covering critical paths?
  A: Partially — `test_c3_delete_increments_compare_invocation_id` covers C3 wiring
  and is skipped. CJS pure tests cover the guard predicate but not the handler→helper
  wiring. R3: either add window hooks or verify manually in 04_verification.md.

- Q: Is the C3 invocation-id monotonic increment design correct for JS single-thread?
  A: Yes — bump in `_resetCompareModeToEmpty` is synchronous, check in `compareReports`
  callback is in microtask after fetch. JS single-thread guarantees correct ordering.

- Q: Does `_resetCompareModeToEmpty` introduce any parallel impl of existing helpers?
  A: No — it delegates to `_renderCompareBanner`, `_updateRwtreeCompareBar`,
  `renderDetailPane` (all existing). No parallel renderer created.
```

---

## Summary of findings

| Finding | Severity | Status |
|---------|----------|--------|
| Q2/EC1: per-row delete `wasInCompare &&` narrows C2 below brief | HIGH — confirmed bug | Requires R1 |
| D1: tester Gap 4 misleads re: batch-delete path | MEDIUM — doc error | Requires R2 |
| Q5/R3: C3 wiring untested (5 skipped e2e) | MEDIUM — coverage gap | Requires R3 or 04_verification.md |
| Q3/HA2: `state.latestSummary` retains stale data post-delete | LOW — documented design risk | Follow-on ticket |
| Q4/HA3: `_restoreCompareFromUrl` catch swallows runtime errors | LOW — pre-existing, OOS | Follow-on ticket |
| Q9: 404 on double-delete leaves stale compare state | LOW — pre-existing | Follow-on ticket |
| Q6, Q7, Q8, Q10 | ✓ | No issues |
