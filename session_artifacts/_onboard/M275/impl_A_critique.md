# impl-critic — framework sub-pass A (session-dim fix) adversarial review

> Recorded by the coordinator from the impl-critic run (2026-06-11; the agent returned its
> findings inline). Verdict: **APPROVE-WITH-FIXES** — the three required fixes were
> implemented in implementer round 3 and locked by tester round 2 before commit.

## Required fixes (all landed)

1. **SQ-1 [REAL-BUG] WARN/FAIL collapse** — both warn (1–5% gap) and fail (>5%) returned
   `session_conservation_ok=False`; callers could not distinguish expected orphan-gap from a
   genuine attribution bug (structural echo of feedback_invariant_with_fallback_hides_drift).
   FIXED: 4th serialized field `session_conservation_level`: None|"ok"|"warn"|"fail";
   `session_conservation_ok` is the convenience bool (True iff level=="ok"). Locked by the
   three-class tester suite (ok / warn / fail / boundary).
2. **SQ-8 [RISK] misleading iter-6 claim** — the settlement-ST bucket-feed dim-switch does NOT
   fix Type-2 bucket cards: `upstream_feature_breakdown`'s fallback guard
   (`feat_bucket_total_win == 0`) never fires when bonus rounds carry real WinCredits, so
   M275's bucket display is unchanged by this pass. FIXED: comment rewritten honestly; the
   dim value kept as the correct seed for future consumers. M275's session-multiplier display
   arrives via the per-ST extraction layer (sub-pass B / W4).
3. **SQ-4 [RISK] strict-equality flake** — the M275 real-data test asserted
   `session_win_sum == total_win`, which silently depends on robot_0 having no orphan bonus
   rounds. FIXED (tester round 2): exact orphan-aware invariant
   `session_win_sum == total_win − orphan_bonus_win`; IB-A1 re-verified red→green under the
   new form.

Optional improvements also landed: conservation-actually-fires tests (level non-None on a
qualifying machine; not just key presence); Type-1 + round_win_rules dim-path regression
(`session_dim_win` == settlement value, not Σ raw offers); malformed spin_types entry gets a
specific skip reason.

## Noted, accepted as-is (with reasons)

- **SQ-2** dim `last_non_none` resets on a zero-win bonus round — identical to the
  pre-existing pid-path semantics; faithfully mirrored, not a regression.
- **SQ-3** Type-1 + rules uses `dim_sum` (rule-view) rather than `dim_last_nonnone` — equal in
  practice because rules zero phantom rounds; locked by the new Group F tests.
- **SQ-5** machines without a SpinType-native manifest skip conservation — registration ==
  manifest exists, so every report-generating machine has one; skip reason is explicit.
- **SQ-6/8** Type-2 bucket-card display gap — deferred to the per-ST extraction layer by
  design (recorded in the M275 design caveats).
- **SQ-9** `session_dim_win` is the BONUS-block total; the full session = trigger paid win +
  dim win (added in `_close_session`) — semantics now documented in the docstrings.
- **SQ-10** cross-chunk session straddle — robots never straddle chunks in this data layout
  (a chunk carries whole robots), and the conservation alarm would surface it if a future
  layout changed that.
- **SQ-11** malformed manifest entries — specific skip reason added (fix 3).
