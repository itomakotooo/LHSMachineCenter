# Console refactor P2 (impl) — generic stats-panel renderer + topdollar_choice panel

> Coordinator brief for the impl-* team. Branch `claude/playtype-rearch`, on top of console P1 (`4af3085`).
> Goal: prove the flexible-assembly framework end-to-end — a **generic, spec-driven stats-panel renderer**,
> with `topdollar_choice` as its FIRST user. Declaring a spec → the panel appears (zero bespoke render code).
> M15's ST=14 stats finally show in the console UI. Read `session_artifacts/_arch_console/01_pipeline_map.md`
> (§3 panel inventory, §4 contract) + the P1 brief/critique in `../p1_registry/` first.

## Why generic, not bespoke
The user directive is "panels FLEXIBLY ASSEMBLED, not hardwired." A bespoke `renderTopDollarChoice` registered
in the registry would still be per-feature hardwired render code. P2 builds a GENERIC renderer driven by a spec
so future simple features (e.g. multiplier_wild) get a panel by declaring a spec — no new render fn. BUT the
generic renderer MUST produce DOM in the EXISTING console panel style (no parallel impl) — same panel
container/`hidden` toggle, same `fmt()` i18n, same `PURE.fInt`/`fRate` formatters, same table CSS classes as the
sibling panels. Mirror `renderBonusChainDynamicsPanel` (app.js:6256) + `renderMachineMechanics` (app.js:4391)
for the conventions (`feedback_no_parallel_panel_impl`).

## The data (from a real M15 report — the gate's ground truth)
`summary.topdollar_choice` (top-level) =
```
{ applicable:true, total_sessions:440, trigger_rate:0.011,
  picks_per_session:{1:104,2:66,3:69,4:201}, stopped_early_rate:0.5431..., forced_4th_rate:0.4568...,
  forced_4th_count:201, bad_gamble_count:91, bad_gamble_rate:0.4527..., settled_win_median:40000,
  settled_win_max:440000, dollar_tier_counts:{5:2188,10:1030,20:230,50:22,100:2}, rtp_contribution_pp:50.3625 }
```
A non-TopDollar machine has NO `topdollar_choice` key (or `applicable:false`) → the panel must NOT show.

## Deliverables
1. **Generic renderer** in app.js: `renderStatsPanel(ctx, spec)` (or a clearly-named equivalent). Driven by `spec`:
   ```
   spec = { panelId, summaryKey, titleKey, applicableField:"applicable",
            sections: [
              { type:"kv",    rows:[ {labelKey, path, fmt} ] },     // fmt ∈ {int,pct,pp,raw}
              { type:"tally", titleKey, path }                       // path → {key:count} dict
            ] }
   ```
   - Reads `ctx.a[spec.summaryKey]`; if missing or `![applicableField]` → `panel.classList.add("hidden")`, return.
   - Else `remove("hidden")`, build DOM: a KV table (label = `fmt(labelKey)`, value via the chosen formatter)
     + one small table per tally section. REUSE the console's existing formatters + i18n + CSS — read pure.js
     for `fInt`/`fRate` (note: `fRate` already multiplies fractions to %? confirm by reading it — pick the
     formatter so `trigger_rate 0.011 → "1.10%"`, `rtp_contribution_pp 50.3625 → "50.36%"` / "pp" consistent
     with how other panels show pp). Match the table markup/classes a sibling panel uses (don't invent new CSS).
   - Single-mode only for P2 (ctx.a). Compare-mode (ctx.b / `_cmpCell` delta column) is P3 — for P2 in compare
     mode, render A's values (a NEW panel has no compare behavior to preserve; don't break compare, just no Δ col).
2. **`topdollar_choice` spec** (the first user) declaring: title + the KV rows (total_sessions, trigger_rate,
   stopped_early_rate, forced_4th_rate, bad_gamble_rate [+ show `bad_gamble_count`/`forced_4th_count` as context],
   settled_win_median, settled_win_max, rtp_contribution_pp) + 2 tally sections (picks_per_session, dollar_tier_counts).
3. **Container** `topDollarChoicePanel` in index.html — mirror a sibling panel's container markup (`hidden` class +
   `data-i18n` title). Place it sensibly among the feature panels.
4. **i18n keys** (zh + en) in `pure.js` `I18N` for the title + every label (find the dict; add to BOTH langs).
   zh labels e.g. tdChoiceTitle="TopDollar 玩家选择(ST=14)", tdTotalSessions="触发局数", tdTriggerRate="触发率",
   tdStoppedEarly="见好就收率", tdForced4th="被逼到第4抽率", tdBadGamble="越赌越亏率", tdSettledMedian="结算中位",
   tdSettledMax="结算最大", tdRtpContribution="占总 RTP", tdPicksPerSession="每局抽取次数分布",
   tdDollarTiers="面额分布" (pick clean wording; en mirror).
5. **Register** the descriptor in `panel_registry.js`: `{ id:"topdollar_choice", order:850 (between
   spin_type_breakdown 800 and feature_breakdown 900), present:(ctx)=>!!(ctx.a.topdollar_choice &&
   ctx.a.topdollar_choice.applicable), render:(ctx)=>renderStatsPanel(ctx, TOPDOLLAR_CHOICE_SPEC) }`.
   (P1 descriptors have no `present`; P2 may add an OPTIONAL `present` the loop honors — if you add `present`
   support to the loop, keep it backward-compatible: descriptors without `present` always render, as in P1.)

## Gates (impl-tester + impl-verifier)
1. **Existing panels byte-identical (additive-only)**: the P1 panels must be UNCHANGED in rendered DOM — adding
   the generic renderer + the new descriptor must not perturb any existing panel. Re-run the P1 DOM check on M14.
2. **New panel correct on M15**: generate an M15 report (`python -m fresh_slotlab.player_impact_analyzer
   --machine M15 --rtp-mode 1 --from-cache rawdata/M15/mode_1 --output-dir <tmp> --max-chunks 5`), load its
   summary in the console, assert the topDollarChoicePanel renders with values matching the summary EXACTLY
   (440 sessions, 1.10% trigger, picks 104/66/69/201, bad-gamble 45.3%, median 40000, tiers 2188/1030/230/22/2,
   RTP 50.36%). Visual-parity: the panel must look like a sibling (same table style), not a parallel impl.
3. **Non-TopDollar hides it**: on M14 (no topdollar_choice section) the panel stays `hidden`.
4. **node --check + preview** (`feedback_frontend_verify_before_commit`): both JS files; preview load M15 + M14,
   confirm panel shows/hides correctly + ZERO console errors; then `preview_stop`. (The console DB has M14 runs;
   for M15 either generate+register a run via the gen flow, or load the M15 summary via `preview_eval` calling
   `_paintAnalysisFromSummary(m15Summary)` after fetching the generated summary file.)
5. **i18n both langs**: toggle zh/en, confirm labels translate (no raw keys shown).
6. **Frontend tests**: extend `tests/frontend/panel_registry.test.cjs` (or a new test) — assert the
   topdollar_choice descriptor is registered at order 850 with a `present` predicate; a generic-renderer unit
   test feeding a fixture `topdollar_choice` section + asserting the produced HTML contains the right values.
   inject-bug: break one spec field path → that value shows wrong/missing → revert.

## Out of scope (P3+)
- Compare-mode Δ column for the generic renderer.
- Migrating EXISTING simple panels to the generic renderer.
- `feature_errors` banner; multiplier_wild panel.
- Backend changes.

## Memory feedback to honor
- `feedback_no_parallel_panel_impl` — reuse fmt/fInt/fRate + sibling table CSS + i18n; visual parity with siblings.
- `feedback_frontend_verify_before_commit` + `feedback_stop_preview_self` — node --check + preview verify + stop.
- `feedback_self_verify_output` — assert the panel numbers against the M15 summary, dump actuals.
- Surgical commit — stage only the frontend files + i18n + test; NEVER `git add -A`.

## Deliverable
Uncommitted frontend changes (implementer) → tests + M15/M14 preview proof (tester) → preview e2e (verifier) →
critique.md (critic). Coordinator commits on APPROVE.
