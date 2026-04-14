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
- `stop_reason`
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

- `metric` (`ret_x = win / bet`)
- `buckets`:
  - `bucket`
  - `spin_count`
  - `spin_rate`
  - `avg_return_x_in_bucket`
  - `rtp_contribution_pp`
  - `win_share`
- tail metrics:
  - `tail_spin_rate_ge10x`
  - `tail_rtp_contribution_pp_ge10x`
  - `tail_win_share_ge10x`

### `streaks`

- `loss_streak_p50/p90/p95/max`
- `win_streak_p50/p90/p95/max`

### `paylines_top20`

Top payline contributions with rate and contribution fields.

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
- `classification`
- `derived_metrics`
- `bankruptcy_checks`
- `concentration_checks`
- `symbol_checks`
- `alerts`
- `action_recommendations`

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

