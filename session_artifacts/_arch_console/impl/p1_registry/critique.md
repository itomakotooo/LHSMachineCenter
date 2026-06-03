# P1 Registry Critique — impl-critic

> Branch: `claude/playtype-rearch`. Uncommitted changes vs base `5721fd3`.
> Files in scope: `src/web_console/frontend/panel_registry.js` (new),
> `src/web_console/frontend/app.js` (modified), `src/web_console/frontend/index.html` (modified),
> `tests/frontend/panel_registry.test.cjs` (new).

---

## Verdict: APPROVE-WITH-FIXES

One MINOR item requires a fix before commit (cache-busting scope). All other findings are MINOR
or informational. No BLOCKER or SERIOUS bugs found.

---

## Stress Questions (12)

**Q1 [VERIFIED OK]**: Does `renderTailDepGrid` silently rely on a `cards` variable computed by
the old outer `_paintAnalysisFromSummary` scope that is now gone?

NO. `renderTailDepGrid` (app.js:7084) calls `PURE.extractMetricCards(s, state.lang)` itself and
gets its own `cards`. `PURE.extractMetricCards` is a pure function (reads only `summary` and
`lang`, no side effects). `renderBigWinGrid` also re-calls it. This is 2-3 redundant invocations
vs. the original 1-but-shared, but output is byte-identical since the function is deterministic.
`state.lang` does not change during a single paint. Not a bug.

**Q2 [VERIFIED OK]**: Is `renderPayIdOverview` correctly fire-and-forget?

YES. Original dispatch at `5721fd3:app.js:7239` = `renderPayIdOverview(s);` — no `await`. The
registry descriptor at `panel_registry.js:49` has `fireAndForget: true`. The coordinator's fix
was correct. Test at `panel_registry.test.cjs:126` asserts this. Verified.

**Q3 [VERIFIED OK — TIMING CHANGE NOTED]**: Was `library_ranking` originally awaited, and
does making it `fireAndForget` change observable DOM?

The original `_paintAnalysisFromSummary` contained `await apiGet(...)` inside the library-ranking
`try` block (5721fd3:app.js:7161), meaning the original function PAUSED on the library fetch
before rendering the bucket distribution. The new code fires `renderLibraryRanking` without await.
Effect: `renderBucketDistribution` and all subsequent sync panels now render WITHOUT waiting for
the library fetch. The DOM content of those panels is UNAFFECTED (they do not read
`state.libraryDistributions`). `applyLibraryRanking` writes only to `kpiVolatilitySub` and
`kpiArchetypeSub`, which no other panel in the registry reads or overwrites concurrently. Final DOM
is byte-identical; only intermediate render timing is faster. Acceptable deviation — an improvement
not a regression. However: this is technically a behavioral change the byte-identical contract
doesn't explicitly permit. Treated as MINOR.

**Q4 [VERIFIED OK]**: Does the registry dispatch loop silently swallow throwing panels?

NO. The loop (app.js:7286-7292) has NO try/catch. A synchronous throwing panel propagates up
through `await descriptor.render(ctx)` and surfaces to the caller. `_enterCompareMode` catches
at 3764 and logs via `console.error`. `refreshCurrentRun` does not catch the outer await of
`_paintAnalysisFromSummary`; a throw there would surface as an unhandled rejection at the
`loadBootstrap` / `setInterval` caller level — same as original. Test at `panel_registry.test.cjs:135`
asserts no try-block in the dispatch loop body.

**Q5 [MINOR — UNHANDLED REJECTION RISK]**: If a `fireAndForget` async panel rejects (unhandled
Promise), what happens?

`descriptor.render(ctx)` returns a Promise that is discarded. If it rejects, it becomes an
unhandled rejection. No global `window.addEventListener("unhandledrejection", ...)` handler is
present in app.js or index.html. In Chrome/Firefox, this surfaces as a console error. In older
Node environments (and some production JS runtimes), it can terminate the process.

Risk: `renderPaylineClassification` has internal try/catch on its API call, so it shouldn't
reject. `renderPayIdOverview` has internal try/catch on both its API calls. `renderLibraryRanking`
has internal try/catch. All 3 fireAndForget panels protect themselves internally. So in practice
the rejection risk is near-zero for the current panel set. BUT: a future panel added as
fireAndForget without internal error handling would silently fail with an unhandled rejection
that goes to console noise only, not to the UI. This is a framework-level design gap for P2+.

**Q6 [MINOR — FUTURE RISK]**: `PANEL_REGISTRY` missing from `_asset_hash_for_console`.

`_asset_hash_for_console()` (app.py:7258-7268) hashes `pure.js`, `app.js`, `styles.css` only.
`panel_registry.js` is NOT in this list. This means:

- For P1: app.js IS modified, so the hash changes, and browsers will fetch new `panel_registry.js`. Safe this deployment.
- For P2+ iterations: if ONLY `panel_registry.js` changes (e.g., adding a new panel descriptor without touching app.js), the asset hash does NOT change, and browsers with a cached `panel_registry.js` serve the old version. This will produce a stale registry bug.

Note: `compare_diff.js` has the same pre-existing exclusion. P1 introduced a new file with the
same risk. Requires a one-line fix to add `panel_registry.js` to the hash computation before
deploying P2+.

**Q7 [VERIFIED OK]**: Does the sort callback `(a, b) => a.order - b.order` shadow and corrupt
any outer variable?

NO. `const sorted = (window.PANEL_REGISTRY || []).slice().sort((a, b) => a.order - b.order)`.
The `a` and `b` in the sort callback are the two descriptor objects under comparison. The outer
`s` parameter and `ctx` const are in different scopes and not referenced inside the sort callback.
Standard JS sort callback naming — no issue.

**Q8 [VERIFIED OK]**: Does `window.PANEL_REGISTRY || []` silently render an empty page if
`panel_registry.js` fails to load or has a parse error?

YES, it silently fails. If `panel_registry.js` fails to parse, `window.PANEL_REGISTRY` is
undefined, `(window.PANEL_REGISTRY || [])` is `[]`, and the loop iterates zero descriptors.
The analysis tab renders completely empty with no console error from app.js. This is a silent
failure mode. However, the browser WILL log a SyntaxError at parse time, so it's not truly
invisible. Accepted as a framework limitation consistent with how `window.COMPARE_DIFF` is
loaded (same pattern). MINOR.

**Q9 [VERIFIED OK]**: In compare mode (`_enterCompareMode`), does `ctx.b` get the right value?

YES. `_enterCompareMode` sets `state.compareMode = { a, b, vA, vB }` BEFORE calling
`_paintAnalysisFromSummary(a)`. When `_paintAnalysisFromSummary` builds `ctx`, it reads
`(state.compareMode && state.compareMode.b) || null` — which is the just-set `b`. P1 panels
ignore `ctx.b` and read `state.compareMode.b` internally (same global). `ctx.b` is wired for P2+
panels only. No divergence.

**Q10 [VERIFIED OK]**: Is the order 100→2000 sequence byte-identical to the original 7036→7248?

The pipeline map §3 table and the original code order at `5721fd3:app.js:7036-7248` both show:
KPI tiles → tail-dep → big-win → library-ranking → bucket → rtp_clamp_warning →
report_self_check → spin_type_breakdown → feature_breakdown → payline_classification →
pay_id_overview → payouts_by_spin_type → field_discovery → machine_mechanics →
bonus_chain_dynamics → collect_cycle → payline_drilldown → symbol_drilldown →
reel_marginal → bankruptcy_analysis.

The registry order 100→2000 maps these 20 slots in exact correspondence. Test at
`panel_registry.test.cjs:81` asserts the full ordered id sequence. Verified.

**Q11 [VERIFIED OK]**: Do the 15 originally-named render fns have their signatures changed?

NO. The existing render fns (`renderRtpClampWarning`, `renderSpinTypeBreakdown`, etc.) are called
with `(ctx.a)` where `ctx.a = s`. In the original they were called as `renderXxx(s)`. Identical.
The functions themselves are not modified — confirmed by zero body changes in `git diff 5721fd3
-- app.js` for the existing fns. Each extracted fn receives `s` as a positional arg same as before.

**Q12 [VERIFIED OK]**: Does any extracted fn (renderKpiTiles/renderTailDepGrid/renderBigWinGrid/
renderBucketDistribution) read a closure variable from the old outer scope that no longer exists?

NO. Each extracted fn uses:
- `state.compareMode` (module-level global — still accessible)
- `PURE.extractMetricCards` (module-level global — still accessible)
- `byId`, `setKpi`, `_cmpCell`, `fInt` (module-level globals — still accessible)
- `window.COMPARE_DIFF` (window global — still accessible)
None of these were parameters or locals of the old `_paintAnalysisFromSummary`. All closures
resolve correctly.

---

## Code-level Bugs / Risks

1. **MINOR** — `_asset_hash_for_console` does not include `panel_registry.js`. Safe for P1
   (app.js changes trigger hash update). Risk for P2+ panel-only changes. See Q6.

2. **MINOR** — `renderLibraryRanking` fires without await; original awaited inline. Final DOM
   byte-identical; only intermediate render order changes (bucket renders earlier). See Q3.

3. **MINOR** — `window.PANEL_REGISTRY || []` silently renders empty if script fails to load.
   Pre-existing pattern for `window.COMPARE_DIFF`; consistent. See Q8.

4. **MINOR** — Docstring of `_paintAnalysisFromSummary` (app.js:7262-7264) still says
   "Async because applyLibraryRanking does its own fetch" — technically stale; the library
   ranking is now fireAndForget so it no longer causes the function to block.

---

## Test-level Gaps

1. **GAP** — No test verifies that `window.PANEL_REGISTRY` missing causes `[]` fallback (i.e.,
   the silent-empty-page scenario is not asserted as "acceptable" or flagged as "should warn").

2. **GAP** — Test `panel_registry.test.cjs:135` detects no `try {` in the dispatch loop body,
   but it does so via text grep (not AST). A comment `// don't add try {` would false-positive.
   Acceptable for this use case but fragile.

3. **GAP** — No test asserts that future additions of non-async functions wrapped in
   `await descriptor.render(ctx)` are safe (they are — `await syncFn()` works). Not a gap in
   practice but there is no test coverage for synchronous panels going through the await path.

4. **GAP** — The inject-bug test (panel_registry.test.cjs:172) only mutates the in-memory
   registry object; it does not exercise the actual DOM rendering path. It proves the registry
   array drives iteration, but not that a removed descriptor actually leaves its container empty
   in the real browser. The verifier's browser-level inject-bug was the real proof.

---

## Claim-vs-Reality Gaps (commit message vs diff)

Since the changes are uncommitted, no commit message exists to fact-check. The brief's claims are:

- "Byte-identical rendered DOM" — VERIFIED for final DOM. Intermediate render timing slightly
  faster due to library-ranking becoming fire-and-forget. No DOM content change.
- "15 named panel fns UNCHANGED" — VERIFIED. Zero body changes to existing fns.
- "5 extracted fns are logic-identical" — VERIFIED for KpiTiles/BucketDistribution (pure extraction).
  TailDepGrid and BigWinGrid re-call `PURE.extractMetricCards` (was shared from outer scope); output
  is identical since the function is pure.
- "fireAndForget correctness" — VERIFIED. 3 panels: library_ranking, payline_classification,
  pay_id_overview. All 3 matched to original no-await behavior.

---

## Edge Cases Not Covered

1. `PANEL_REGISTRY` undefined (panel_registry.js fails to load) → silent empty page.
2. Only `panel_registry.js` modified in P2+ without touching app.js → stale cache served.
3. Concurrent `_paintAnalysisFromSummary` calls (fast-polling overlap) — same risk as original,
   not introduced by P1; the fire-and-forget panels could now have two concurrent renders.
4. Browser with strict unhandled-rejection termination + a future fire-and-forget panel that
   throws — no framework-level catch. Acceptable for P1 since all 3 current fireAndForget
   panels have internal try/catch.

---

## Required Fixes Before Commit/Merge

**1. Add `panel_registry.js` to `_asset_hash_for_console` in `app.py`.**

Current (app.py:7260): `for name in ("pure.js", "app.js", "styles.css"):`
Required: `for name in ("pure.js", "app.js", "panel_registry.js", "styles.css"):`

Without this fix, any future P2+ change to `panel_registry.js` alone will not bust the browser
cache. For P1 this is safe because app.js changes; for subsequent commits it is a latent bug.
Since P2 is the immediate next phase and it WILL modify `panel_registry.js`, this will hit prod
on the very next iteration.

This fix also requires adding `src/web_console/backend/app.py` to the surgical commit list.

---

## Optional Improvements (not blocking)

1. Update the `_paintAnalysisFromSummary` docstring (app.js:7262) to reflect that the library
   ranking is now fire-and-forget and doesn't cause the function to pause.

2. Add a `console.warn("panel_registry.js missing: PANEL_REGISTRY not found")` when
   `window.PANEL_REGISTRY` is falsy, so the silent-empty-page scenario is observable in
   browser devtools.

3. Consider adding `panel_registry.js` to the `_asset_hash_for_console` computation alongside
   the required fix (same thing — just surfacing it as an optional refactor if you prefer to
   rethink the hash computation structure).

---

## Exact Surgical `git add` List

```
git add src/web_console/frontend/panel_registry.js
git add src/web_console/frontend/app.js
git add src/web_console/frontend/index.html
git add tests/frontend/panel_registry.test.cjs
git add src/web_console/backend/app.py          # required: add panel_registry.js to hash
git add session_artifacts/_arch_console/impl/p1_registry/brief.md
git add session_artifacts/_arch_console/impl/p1_registry/critique.md
```

Do NOT use `git add -A` — the working tree contains 618 slot_designer deletions,
configs/machines.json changes, and other unrelated artifacts.
