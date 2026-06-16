# impl-critic — dimension framework Phase 3 (freespin progression + ufb labels)

> Recorded by the coordinator from the impl-critic run (2026-06-16; the agent returned
> findings inline but did not persist this file). The verdict's only "SHIP-BLOCKER" was
> the two NEW files being git-UNTRACKED — a non-issue (they are staged in the Phase 3
> commit). The real MEDIUM findings (honesty labels) were fixed before commit.

Phase 3 scope: a NEW base-excluded `freespin_progression` extractor (per-round ExtraRatio ×
FS-index + FS-index hit arc + per-session win-tier, split per trigger-path) that delivers the
long-deferred parser_blind metrics; freespin_dynamics consumes it → `er_ladder` /
`fs_index_arc` / `session_tier_distribution` sections with by_dim; frontend renders the 3 new
per-path sub-panels; upstream_feature_breakdown swaps the coarse `[via]` heuristic for accurate
dimension labels. Coordinator-verified: base_hash c5d2199142c3 unchanged; 4 single-dim goldens
byte-identical; M275 re-baselined; ER climb FS1 145→FS10 1641; FS-arc cliff FS1 0.438→FS10
0.037; session_tier Σ==909; full analyzer suite 713 passed.

## Fixed before commit (real findings)

1. **session_tier_distribution.total_sessions over-counts double-trigger sessions** — under
   additive_sessions a multi-trigger block is credited to EACH matched path, so the merged
   aggregate counts it once per path. FIX: added `total_sessions_note` documenting the caveat
   (mirrors the existing `_trigger_path_section` caveat). Never silent.
2. **ufb per-path bucket histograms are BORROWED from the highest-win coarse row (approximate)**
   while labels/fires/win/rtp are accurate. FIX: added `bucket_data_approximate: true` on the
   per-path rows + corrected `_dimension_source` to say "accurate labels/fires/win; bucket_*
   approximate" (feedback_invariant_with_fallback_hides_drift — the approximation is surfaced).
3. **session_tier by_dim computed but not rendered** (frontend gap). FIX: app.js session-tier
   table now renders per-path session-count columns when ≥2 real paths (consistent with the
   ER-ladder / FS-arc tables).

## Extractor-collision (the 20 test failures the full suite caught — resolved)

`freespin_progression` declares `DECLARED_IN_KEY="trigger_paths"` (same as `trigger_path`), so
get_extractors_for_manifest returns BOTH for any trigger_paths manifest. freespin_progression
filters internally to freespin-ROLE STs (inert on non-freespin: zero tracked STs, empty output)
— architecturally correct, but the registry still returns it (key-based). 20 test_st_extract_framework
assertions hard-coded "exactly 1 extractor / extractors[0] == trigger_path"; relaxed to select
the trigger_path extractor BY ID (robust). 1 test_m275_onboarding parser_blind contract updated
(F4/F5 now DELIVERED → removed from the blind list; F3a — only a return_bucket PROXY for the
server's SummaryWin taxonomy — stays genuinely flagged).

## Noted, accepted as-is

- "inert but returned" extractor adds one no-op observe_round per round on trigger_paths
  machines — negligible; making the registry role-aware would be a closure change (base_hash).
- proportional payid split denominator (extractor rule-view win vs parser raw) — equal on
  M275; a divergence-machine edge flagged for future.
- FS-index from ReMarks "Freespin N": malformed/out-of-range N is dropped from that round's
  ER/arc entry (no junk bucket); a per-extractor error surfaces via the parser's snapshot.
- `_obs_errors`/`_begin_robot_error` are NOT dead — the parser's per-extractor try/except writes
  to them (the established st_extract error-snapshot contract); the critic miscalled these.
