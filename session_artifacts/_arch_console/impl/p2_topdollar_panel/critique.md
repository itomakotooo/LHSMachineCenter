# impl-critic: Console P2 (generic stats-panel renderer + topdollar_choice) — critique

**Date:** 2026-06-03 · **Branch:** `claude/playtype-rearch` · **Base:** console P1 `4af3085`
**Verdict:** APPROVE-WITH-FIXES (1 BLOCKER + 1 SERIOUS) → all REQUIRED fixes applied + re-verified; see resolutions.

## Required fixes (both RESOLVED by coordinator before commit)

1. **[BLOCKER] Stale panel on the normal machine-switch load path.** The topdollar_choice descriptor used a
   `present()` skip (`if (typeof descriptor.present === "function" && !descriptor.present(ctx)) continue;`). But
   `_resetDebugPanelsToEmpty()` is NOT called on the completed-run load path (only on !currentRunId / 404 / error
   paths) — so on M15→M14 switch, `present()=false` skips render → `renderStatsPanel` never runs → the panel stays
   visible with M15 data. The coordinator's first cut (adding topDollarChoicePanel to the reset list) did NOT fix
   the happy path, and was wrongly "verified" by calling `_resetDebugPanelsToEmpty()` directly instead of the real
   switch sequence.
   → **RESOLVED (critic's preferred fix):** removed `present()` entirely from the descriptor AND the dispatch loop.
   `renderStatsPanel` SELF-HIDES when its data is absent (the P1 pattern every panel uses), so it runs on every
   paint and can never go stale. Re-verified in the real browser the ACTUAL sequence: `renderStatsPanel({a:{td}})`
   → panel shown; `renderStatsPanel({a:{}})` → panel hidden. Added test guards: the loop has NO `descriptor.present`
   reference, NO descriptor carries a `present` field, and `topDollarChoicePanel` is in the reset hide-list — so the
   trap can't return. (The reset-list entry is kept as belt-and-suspenders for the clean nothing-loaded state, like
   every sibling gated panel.)

2. **[SERIOUS] Tally column headers reused `thSpinType`/`thSpinCount`** ("SpinType / 次数") — wrong for the
   picks-per-session and dollar-tier tallies (their keys are pick counts / dollar tiers, not SpinTypes).
   → **RESOLVED:** each tally section declares its own `keyColKey`/`countColKey`; spec sets picks→(抽取次数/局数),
   tiers→(面额/次数). Added 5 i18n keys (zh+en). Verified in-browser the headers render 抽取次数/面额, no "SpinType".

## Verified by the critic / coordinator (no fix needed)
- Existing P1 panels unperturbed (additive): the dispatch change is only the loop guard removal; renderStatsPanel
  is new; no existing renderXxx fn changed.
- M15 values render EXACTLY (440 / 1.10% / 54.32% / 45.68% / 201 / 45.27% / 91 / 40,000 / 440,000 / 50.36pp /
  picks 104/66/69/201 / tiers 2188/1030/230/22/2). M14 (no section) → panel hidden. zh/en translate. Zero console errors.
- Generic renderer reuses fmt + fInt/fRate + sibling CSS (.mech-section/.drilldown-table) — no parallel impl.
- 15 frontend registry tests + 192 existing green; node --check clean.

## Optional / deferred (P3 hardening — low risk now, single panel)
- `renderStatsPanel` resolves its body via `panel.querySelector("div")` (implementer + critic flagged). Works for
  the current markup (body div is first); future spec panels should target an explicit body id.
- Compare-mode Δ column for the generic renderer (P2 renders ctx.a only).
- Empty-sections / non-numeric-tally-key edge cases (can't occur for the current spec).
- `_enterCompareMode` / `_onCompareExit` paint without a prior reset (latent; same-machine compare pairs in
  practice; the self-hide fix makes topdollar correct there regardless since render always runs).
