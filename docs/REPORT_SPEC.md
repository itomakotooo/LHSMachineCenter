# Report Spec

This document defines the expected output contract of
`player_impact_summary.json` and `player_impact_report.md`.

## Output Files

For each report version:

- `player_impact_summary.json`
- `player_impact_report.md`

Location:

- `reports/<machine>/mode_<id>/versions/<report_version>/`

Mode index files:

- `reports/<machine>/mode_<id>/index.json`
- `reports/<machine>/mode_<id>/latest.json`

## Summary Top-Level Keys

Expected top-level fields:

- `report_id`
- `run_id`
- `machine`
- `mode`
- `output_all_robots_result`
- `sampling`
- `rtp`
- `player_impact`
- `upstream_analysis` -- server-side analysisResult.TotalWin cross-check
- `collect_mechanic` -- M272+ collect bonus tally (`applicable=false`
  on non-collect machines)
- `guideline_assessment`
- `guideline_comparison`
- `storage`

## `sampling`

Core fields:

- `target_halfwidth_pp`
- `achieved_halfwidth_pp`
- `chunk_spin_times`
- `chunk_robot_count`
- `batch_concurrency`
- `chunks`
- `total_spins`
- `paid_spins` -- CostCredits>0 rounds (added in the paid-session
  refactor; the denominator RTP uses)
- `bonus_spins` -- CostCredits==0 rounds (bonus / free / re-spin)
- `stop_reason` -- `target_ci_reached` / `max_chunks_reached` /
  `user_stop` (graceful cancel; see HANDOVER §13f) / various error
  strings for failed runs
- `duration_seconds`
- `started_at`
- `finished_at`

## `rtp`

- `point_pct`
- `ci95_interval_pct`

## `player_impact`

### `volatility`

- `avg_return_x`
- `std_return_x`
- `max_observed_return_x`
- `return_bucket_rate`

### `hit_and_payout`

- `zero_win_rate`
- `win_hit_rate`
- `profit_spin_rate`
- `breakeven_or_more_rate`
- `big_win_x10_rate`
- `avg_win_when_hit_x`
- `lack_credit_spin_rate`

### `multiplier_profile`

- `metric` (`ret_x = session_win / session_bet (paid bet only)`)
- `buckets` (11 win-bearing entries; `eq0` is NOT emitted -- zero-win
  share lives in `hit_and_payout.zero_win_rate`):
  - `bucket`
  - `spin_count`
  - `spin_rate`
  - `avg_return_x_in_bucket`
  - `rtp_contribution_pp`
  - `win_share`
- tail metrics (ge10x canonical; matching ge20x/ge50x/ge100x live
  under `guideline_assessment.derived_metrics`):
  - `tail_spin_rate_ge10x`
  - `tail_rtp_contribution_pp_ge10x`
  - `tail_win_share_ge10x`

### `streaks`

- `loss_streak_p50/p90/p95/max`
- `win_streak_p50/p90/p95/max`

### `paylines_top20`

Top payline contributions with rate and contribution fields. Each
row carries:

- `payline_id`, `hit_count`, `hit_rate`
- `approx_win_credits`, `approx_rtp_contribution_pp`
- `top_symbols` -- list of `{symbol, count}` ordered by frequency
- `top_symbols_source` -- `"rln"` when the winning rounds' upstream
  `RewardLastNode` populated the list (authoritative), `"heuristic"`
  when we fell back to the left-3-col intersection

### `payout_ids_top20`

Primary Pay ID drilldown, built from `PayoutIdToWinAmount` across
all winning rounds. Per row: `payout_id`, `hit_count`, `hit_rate`,
`total_win`, `avg_win_when_hit`, `rtp_contribution_pp`. Replaces the
older `payout_groups_top20` (still emitted for back-compat; M14 +
M272 mode 1/2 always reported group_id=0).

### `spin_type_breakdown`

Per-SpinType (int code) aggregation. Per row:

- `spin_type` (int)
- `behavior_name` -- `"paid"` / `"free"` / `"mixed"`, derived from
  per-type paid-rounds count (not hardcoded)
- `spins`, `share_pct`, `win_rounds`, `paid_rounds`, `hit_rate`
- `total_bet` (face BetAmount), `total_paid_bet` (CostCredits>0 only),
  `total_win`
- `rtp_pct` -- `win / paid_bet` OR **`null`** when all rounds of this
  SpinType are free (paid_bet == 0); UI renders "N/A" for null
- `rtp_contribution_pp` -- win / overall total_bet * 100 (comparable
  across types)

### `upstream_feature_breakdown`

From upstream `analysisResult.FeatureWin`. Machine-named feature
grouping -- M14: single "Normal" feature so `applicable=false`; M272
mode 1: "NormalCollectionSpin" + "NewFreespin" with per-feature
total_win, rtp_contribution_pp, share_of_total_win and a payouts[]
sub-list keyed by upstream payout_id.

### `bonus_chain_dynamics`

From the round `ReMarks` field (`"Freespin N; CollectCount:X;
ExtraRatio:R; [AddFreespins; M]"`). Per sample:

- `chain_count`, `bonus_round_count`, `avg_chain_length`
- `chain_length_quantiles` (p50 / p90 / p95 / max / avg)
- `chain_max_ratio_quantiles` (same shape, over peak ExtraRatio)
- `self_retrigger_round_rate`, `avg_retriggers_per_chain`
- `extra_ratio_histogram` -- `[{ratio, rounds}, ...]`
- `extra_ratio_by_chain_depth` -- depth buckets (1 / 2-5 / 6-10 /
  11-20 / 21+) -> avg ExtraRatio at that depth (the MapCollection
  energy-ramp curve)

Emits `applicable=false` on machines without ReMarks Freespin
annotations (M14).

### `symbols_top20` and `symbols_by_column_top10`

Symbol-level and reel/column-level frequency breakdown.

### `bankruptcy_probe`

List entries by bankroll multiplier:

- `bankroll_multiplier`
- `bankruptcy_rate`
- `bankrupt_robots`
- `completed_robots`
- `avg_spins_completed`
- `robots`
- `session_spins`
- `init_credits`

## `guideline_assessment`

Contains deterministic assessment values derived from summary metrics:

- `data_quality`
- `classification` -- `volatility_class` (Very High / High / Medium
  / Low) + `experience_archetype` (Boom-Bust / Grindy / Balanced)
- `derived_metrics`:
  - `recovery_gap = win_hit_rate - profit_spin_rate`
  - `tail_dependency` -- legacy alias for `tail_dependency_ge10x`
  - `tail_dependency_ge{10x,20x,50x,100x}` -- multi-threshold tail
    (how RTP dependency on ≥Nx wins evolves as the threshold rises;
    slow decay = Boom-Bust, sharp decay = grindy)
  - `tail_rtp_contribution_pp_ge{10x,20x,50x,100x}` -- matching
    pp-of-RTP contributions from each threshold tier
- `bankruptcy_checks`
- `concentration_checks`
- `symbol_checks`
- `alerts`
- `action_recommendations`

## `upstream_analysis`

Cross-check against server-side `analysisResult.TotalWin`:

- `server_total_win`, `our_total_win`, `delta`, `delta_pct`
- `matches` -- boolean (within max(1.0, server * 1e-6) tolerance)
- `server_robots_seen`

`matches=true` with `delta=0` is the normal case (M14 + M272 mode 1
both verified). Drift would surface here before it leaks into the
report.

## `collect_mechanic`

M272+ collect bonus tally:

- `applicable` -- false on non-collect machines (M14 reports this)
- `robots_with_data`, `total_collects`, `max_acc_credits_observed`,
  `avg_spins_between_collects`
- `clamp_warning` -- `{applicable, pending_robots,
  total_pending_paid_spins, pending_share_of_paid_spins,
  avg_paid_spins_per_collect, note}`. Fires when SpinTimes truncated
  mid-collect-cycle so observed RTP is a lower bound (frontend
  renders a warning via `#rtpClampWarning` when applicable=true).

## `guideline_comparison`

Compares summary metrics against external rules file:

- `overall_status`
- `pass_count`
- `fail_count`
- `missing_count`
- `not_applicable_count`
- `hard_fail_count`
- `failed_check_ids`
- `checks` (per-rule result)

Rule source:

- `configs/classic_slots_guideline_rules.json`

## Quality Gate Convention

If minimum statistical conditions are not met, report should be considered
exploratory and treated as directional only.

Typical report-grade expectation:

- CI half-width reached target (`<= 0.5pp`)
- sufficiently large sample size (commonly in millions of spins)

