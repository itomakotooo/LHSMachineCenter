# Console refactor P1 (impl) — panel registry + presence-driven dispatch (BYTE-IDENTICAL)

> Coordinator brief for the impl-* team. Branch `claude/playtype-rearch`. Frontend-only.
> Goal: replace the hardcoded panel dispatch with a **registry-driven, presence-based assembler** — with
> **ZERO observable change** (byte-identical rendered DOM). This lands the framework; new/migrated panels
> (P2+) ride on it. Read `session_artifacts/_arch_console/01_pipeline_map.md` (the full panel inventory +
> hard cases) + `00_brief.md` first.

## Why P1 is wrap-first (zero-change)
P1 only changes HOW panels are invoked (a registry loop instead of a hardcoded sequence at app.js:7230-7248
+ the inline blocks at 7036-7228). It does NOT change WHAT any panel renders. Each existing panel is
registered by WRAPPING its current render fn → identical output by construction. This de-risks the framework;
generic renderers + ctx-threading + new panels come in P2+.

## Deliverables
1. **A panel registry** (new file `src/web_console/frontend/panel_registry.js`, loaded before app.js in
   index.html; or a clearly-delimited section near the top of app.js if a new file complicates load order —
   implementer's call, but prefer a new file for isolation). Shape:
   ```js
   // window.PANEL_REGISTRY = ordered array of descriptors
   { id: "rtp_clamp_warning", order: 50, fireAndForget: false,
     render: (ctx) => renderRtpClampWarning(ctx.a) }   // wraps the existing fn
   ```
   Keep descriptors minimal for P1: `{id, order, render(ctx), fireAndForget?}`. (A `present(ctx)` predicate is
   NOT needed in P1 — the existing render fns already self-gate by hiding their container; keep that behavior.)
2. **A `ctx` object** built once in `_paintAnalysisFromSummary(s)`: `{ a: s, b: (state.compareMode && state.compareMode.b) || null, machine: s.machine, mode: s.mode, compare: !!state.compareMode }`. P1 wrapped fns IGNORE ctx.b (they still read `state.compareMode.b` internally as today — DO NOT change them) — ctx just makes B available for P2 new panels. ctx.a replaces the bare `s` arg.
3. **Refactor `_paintAnalysisFromSummary`** (app.js:7036): build ctx, then iterate `PANEL_REGISTRY` sorted by
   `order`, calling each `render(ctx)`; `fireAndForget` descriptors are called WITHOUT await (preserve
   `renderPaylineClassification`'s current fire-and-forget at 7238); async non-fire-and-forget panels
   (`renderPayIdOverview`) are awaited exactly as today. **Preserve the EXACT current call order** via `order`
   values (KPI tiles → tail-dep → big-win → library-ranking-async → bucket → the 15 named panels in their
   7230-7248 order). Order is the current dispatch order; do not reorder.
4. **Extract the 4 inline blocks** (currently inline in `_paintAnalysisFromSummary`) to named fns, then register
   them — each must do BYTE-IDENTICAL DOM writes:
   - `renderKpiTiles(ctx)` ← lines 7039-7086 (the `PURE.extractMetricCards` + `setKpi` loop). **Highest-risk
     extraction** — many element IDs; reproduce exactly.
   - `renderTailDepGrid(ctx)` ← 7091-7122
   - `renderBigWinGrid(ctx)` ← 7123-7148
   - `renderBucketDistribution(ctx)` ← 7166-7228
   - the library-ranking async (7154-7164) ← register as a `fireAndForget` descriptor calling the same
     `apiGet(/api/library/distributions)` → `applyLibraryRanking` logic.
5. **Dead stubs**: `renderRunHistory`/`updateBatchBar`/`renderPayoutGroupDrilldown` (app.js:3951-3958) are NOT
   in the dispatch — leave them untouched in P1 (deletion is optional cleanup, out of P1 scope).

## What P1 does NOT do (P2+)
- No generic renderers (kv-table/rows-table descriptors) yet.
- No `topdollar_choice` panel yet (that is P2 — proves the framework).
- No migrating existing fns to read ctx.b instead of the global (P3).
- No `present(ctx)` predicate / summary-key-driven visibility (P3 — for now keep each fn's self-hiding).
- No backend changes.

## Gate (impl-tester + impl-verifier) — BYTE-IDENTICAL DOM is the contract
1. **Byte-identical rendered DOM**, real cached reports, pre-change vs post-change:
   - Run a report through the console for **M15** (has topdollar in summary but NO panel yet — so the debug tab
     must look IDENTICAL), **M275** (multi-feature), and **compare mode** (A/B — the 9 compare-aware panels must
     be identical since they still read `state.compareMode.b`).
   - Method: `preview_start` the console; load each report; snapshot the analysis container's `innerHTML`
     (the debug-tab panel region) via `preview_eval`; compare pre-change (HEAD `5721fd3`) vs working-tree.
     Normalize only volatile bits (run_id/timestamps in the DOM if any). ANY structural diff = FAIL.
   - Per `feedback_no_parallel_panel_impl`: this is the visual-parity gate — same containers, same content.
2. **Page loads clean** (`feedback_frontend_verify_before_commit`): `node --check` both JS files;
   `preview_start` + load a report + `preview_console_logs` shows no new errors; the debug tab renders.
3. **Inject-bug** (`feedback_enumerate_safety_paths.md`): drop one descriptor from the registry → that panel's
   container goes empty in the DOM snapshot (proves the registry actually drives rendering) → restore → identical.
4. Frontend tests (if any under `tests/` for app.js/pure.js) stay green.

## Memory feedback to honor
- `feedback_no_parallel_panel_impl` — wrap existing fns; do NOT rewrite any panel's render logic in P1.
- `feedback_frontend_verify_before_commit` — node --check + preview load + DOM snapshot before handoff.
- `feedback_stop_preview_self` — stop the preview server after verifying.
- `feedback_dont_swallow_errors_in_fix` — the registry loop must not wrap render calls in catch-all that hides
  a panel throwing; if a panel errors, it should surface (console error), not silently vanish.
- Surgical commit — stage only the frontend files; NEVER `git add -A` (618 slot_designer deletions etc. in tree).

## Deliverable
Uncommitted frontend changes (implementer) → DOM byte-identical + inject-bug (tester) → preview e2e (verifier)
→ critique.md (critic). Coordinator commits on APPROVE.
