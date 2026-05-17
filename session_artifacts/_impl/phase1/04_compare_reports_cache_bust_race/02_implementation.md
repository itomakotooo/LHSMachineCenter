# 02_implementation.md — Ticket P1-A5 compareReports cache-bust race fix

## Verdict

pass

## Files changed

1 file: `src/web_console/frontend/app.js`

### Change summary by region

| Region | Line range (post-edit, approx) | Brief § |
|---|---|---|
| `state._compareInvocationId` field added | ~123–129 | §3 C3 |
| `compareReports()` — invocation-id guard | ~3519–3544 | §3 C3, C4 |
| `_resetCompareModeToEmpty()` helper (new) | ~3606–3637 | §3 C2, C3, C4 |
| `_onCompareExit()` — delegates to helper | ~3639–3653 | §3 C2 |
| Per-row delete handler — C1+C2 logic | ~2494–2505 | §3 C1, C2, C3 |
| Batch delete handler — C1+C2 logic | ~2548–2578 | §3 C1, C2, C3 |

## Brief-section traceability

### C1 — Map clears on DELETE

Per-row delete handler (rwtree `.rwtree-delete-btn`):
- Added `const wasInCompare = state.compareSelected?.has?.(rv)` before `delete(rv)` so we can distinguish "was selected" from "is in active compare mode".
- Existing `state.compareSelected?.delete?.(rv)` is retained (already did the Map removal, now also guarded by wasInCompare check).

Batch delete handler (`rwtreeBatchDeleteBtn`):
- After the delete loop, `deletedVersions` array is built from `entries.map(([rv]) => rv)`.
- If none of those versions were in `compareMode`, `state.compareSelected = new Map()` clears the Map as before.
- If they were in `compareMode`, `_resetCompareModeToEmpty()` is called which internally replaces `state.compareSelected` with a fresh empty Map.

### C2 — Compare-mode exit on DELETE during comparison

New `_resetCompareModeToEmpty()` helper (brief §3 C2, citing memory `feedback_error_branch_resets_all_state.md`):
- Clears `state.compareMode = null`
- Clears `state.compareSelected = new Map()`
- Removes `cmp-active` body class
- Calls `_renderCompareBanner()` (which hides the banner when `compareMode == null`)
- Calls `_updateRwtreeCompareBar()` (hides the compare action bar)
- Calls `renderDetailPane()` (resets the detail pane)
- Removes `?compare=...` URL param
- Does NOT repaint `latestSummary` (the deleted version IS stale data; repaint is only safe for the `_onCompareExit` button path which still has valid data)

`_onCompareExit()` is now a thin wrapper: calls `_resetCompareModeToEmpty()` then optionally repaints with `latestSummary` (the user chose to exit, their latestSummary is still valid).

Per-row delete: calls `_resetCompareModeToEmpty()` when `wasInCompare && cm && (cm.vA === rv || cm.vB === rv)`.

Batch delete: calls `_resetCompareModeToEmpty()` when `cmBefore` existed and the deleted set included `cmBefore.vA` or `cmBefore.vB`.

### C3 — In-flight fetch guard

`state._compareInvocationId: 0` added to state initializer.

`compareReports()`:
- Before the `Promise.all` fetch, increments `state._compareInvocationId` and captures `myInvocationId = state._compareInvocationId`.
- After both fetches resolve, checks `myInvocationId !== state._compareInvocationId`. If they differ, a DELETE raced and called `_resetCompareModeToEmpty()` which bumped the counter — response is discarded with a visible `console.warn` (not silent).

`_resetCompareModeToEmpty()`:
- Bumps `state._compareInvocationId = (state._compareInvocationId || 0) + 1` as its first action, atomically invalidating any concurrent compareReports() invocation.

### C4 — No silent swallow

- No bare `catch (_) {}` added anywhere in the fix.
- `_resetCompareModeToEmpty()` internal `try/catch` blocks on `_updateRwtreeCompareBar`, `renderDetailPane`, and URL update all log via `console.warn(...)` — not silent.
- Batch delete loop changed from `catch (_) { failed += 1; }` to `catch (err) { console.warn(...); failed += 1; }`.
- The invocation-id discard path uses `console.warn(...)` explicitly.

## Pytest / node test results

Frontend tests (touched modules: app.js):
- `tests/frontend/pure.test.cjs`: 166/166 passing
- `tests/frontend/compare_diff.test.cjs`: 17/17 passing
- `node --check src/web_console/frontend/app.js`: SYNTAX OK

No backend Python tests touch `compareReports` / `compareSelected` — confirmed via grep. This is itself a finding (see Open Issues).

## Open issues / out-of-scope items deferred

1. **No existing tests for compare mode** — `tests/frontend/` has no tests covering `compareReports`, `_enterCompareMode`, `_onCompareExit`, or `compareSelected`. The regression test (brief §3 C5) is impl-tester's responsibility. Flag to impl-tester: the inject-bug / revert TDD cycle is important here because the race is inherently async.

2. **`_restoreCompareFromUrl()` on page load** — this path also calls `_enterCompareMode` but has no invocation-id guard. Brief does not mention URL-restore as a race vector. Left as-is (out of scope per brief §4). Flag for impl-critic to assess.

3. **Bulk-delete via global rawdata detail table** — brief §7 Wave 2 mentions impl-critic checks "all DELETE paths". The global rawdata detail table (separate from the rwtree) may have its own delete path. Not mentioned in brief §1 expected changes. Flag for impl-critic.

4. **`state.latestSummary` not cleared in `_resetCompareModeToEmpty`** — by design: `_resetCompareModeToEmpty` doesn't touch `latestSummary` because (a) the comparison data itself is what's stale, not necessarily the single-mode summary, and (b) clearing it would break any subsequent `_onCompareExit` repaint. The caller (`_onCompareExit`) decides whether to repaint. Flag for impl-critic to validate this choice.

## Risk notes

- **Invocation-id check is correct for JS single-threaded model**: `state._compareInvocationId = ... + 1` in `_resetCompareModeToEmpty` runs synchronously in the event loop. The `compareReports` fetch callbacks only check after their `await Promise.all` completes. There is no TOCTOU here — the check `myInvocationId !== state._compareInvocationId` happens in a microtask after the fetch, which is always serialized after the synchronous bump in `_resetCompareModeToEmpty`.

- **Per-row delete races with `_onCompareExit` button**: If the user clicks both simultaneously, `_resetCompareModeToEmpty` is idempotent (setting null/empty Map/class removal are all no-ops on already-reset state), so double-call is safe.

- **Batch delete `cmBefore` snapshot**: Captured before the delete loop. If a concurrent `_enterCompareMode` fires inside the loop (another tab, not realistic but theoretically possible in the same JS event loop — it cannot, because the loop uses `await` and JS is single-threaded), the snapshot protects against that. Sound design.
