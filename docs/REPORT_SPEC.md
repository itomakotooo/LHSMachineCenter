# Report Spec

This document defines the expected output contract of
`player_impact_summary.json` and `player_impact_report.md`.

> **Producer status (2026-06-05): generation is OFFLINE.** The report
> orchestrator (`fresh_slotlab/player_impact_analyzer.py`) was removed and
> is being rebuilt SpinType-native on the analyzer core
> (`fresh_slotlab/analyzer/core/*`). `POST /api/batch-run` returns HTTP 503
> and `scripts/batch_generate_reports.py` is a stub until the new engine
> lands. **This schema remains the live contract**: existing reports on disk
> are read and rendered unchanged (the frontend panel registry hard-depends
> on these `player_impact.*` sections), and the new engine MUST reproduce the
> schema below byte-for-byte in shape. Field names here were verified against
> reports under `reports/M14/mode_1/versions/*/player_impact_summary.json`
> and the emit code in `fresh_slotlab/analyzer/features/*`.

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
- `config_md5` / `code_md5` -- server-side machine fingerprint at
  sampling time (paytable / paylines / engine code on the server).
  Drift means rawdata is from an older server version → resample.
- `analyzer_version` -- legacy 12-hex source-hash field. Kept for
  back-compat; no longer the freshness comparator (it hashed the now-removed
  `player_impact_analyzer.py` monolith). Use `effective_analyzer_version`.
- `effective_analyzer_version` -- per-(machine, mode) effective hash
  (honesty-3): `sha256(base ⊕ {declared feature hashes} ⊕ mode)[:12]`.
  This is the value the console compares for report freshness. Empty
  string when the machine has no manifest / registry; see
  `effective_analyzer_version_error`. Produced by
  `fresh_slotlab/analyzer/versioning.py`
  `compute_effective_version_for_machine`.
- `effective_analyzer_version_error` -- diagnostic; `null` on success,
  else `"<ExcType>: <msg>"` naming why the field is empty (so operators
  don't have to grep stderr).
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

### How sections are produced (plugin model)

Display sections are produced by **plugins** under
`fresh_slotlab/analyzer/features/`, each owning its own compute/emit.
Plugins register in `fresh_slotlab/analyzer/feature_registry.py`
(`ALL_FEATURES` — empty at import, populated as plugin modules register
themselves); a machine's manifest (`analyzer_features` list) declares which
features it emits, so the exact set of populated sections is per-machine. A
section absent from a machine's manifest is simply not emitted (distinct from
`applicable=false`, which a declared feature emits when it has no data for
that machine).

The plugin modules present today are `payouts_by_spin_type`,
`reel_marginal_by_spin_type`, `bankruptcy_simulation`, `multiplier_profile`,
`multiplier_wild`, `machine_mechanics`, `upstream_feature_breakdown`,
`collect_mechanic`, `bonus_chain_dynamics`, plus the SpinType-native
`spin_type_outcomes`, `spin_type_rtp_buckets`, and `topdollar_choice`.

Manifests come in two forms: legacy flat manifests under
`slot_designer/configs/machine_manifests/<machine>.json` (read by
`versioning.py` for the freshness hash) and the new SpinType-native schema
under `configs/machine_manifests/<machine>.json` (e.g. `M15.json`, parsed by
`fresh_slotlab/analyzer/machine_spec.py`).

> The **top-level orchestration** that drove this emit loop (`main()` in
> `player_impact_analyzer.py`) has been removed and is being rebuilt; see the
> producer-status note at the top of this file. The plugins and the section
> contract below survive and are what the new engine wires together.

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
all winning rounds **plus** trigger-session win fold-in (see
`fresh_slotlab/trigger_sessions.py` + `reference_trigger_session_patterns.md`
memory note). Per row: `payout_id`, `hit_count`, `hit_rate`,
`total_win`, `avg_win_when_hit`, `rtp_contribution_pp`,
`spin_type_category`, `dominant_spin_type`, `spin_type_breakdown`.

**Parity invariant (iter 3-6 locked)**:
`sum(payout_ids_top20[*].rtp_contribution_pp) ==
summary.rtp.point_pct` within 0.01pp tolerance. This is the core
fleet-wide correctness contract — if it breaks, a new aggregator
has introduced (a) denominator inconsistency, (b) double-counting
with existing paths, or (c) a missing attribution. Test lock:
`test_payout_ids_top20_rtp_sum_equals_summary_rtp` on the M272
bonus-heavy fixture.

Trigger-token pay_ids (M15 TopDollar's pay_id 666, M273 Wheel's
5801, etc.) carry `total_win = 0` on raw round data but accrue
their bonus feature's session win via `trigger_sessions` helper's
per-session attribution. M209-style rounds where
`sum(Payout) > WinCredits` (phantom alternative rewards) are
scaled proportionally at the round aggregator so `pay_id win += value *
(WinCredits / sum(Payout))`.

Replaces the older `payout_groups_top20` (still emitted for
back-compat; M14 + M272 mode 1/2 always reported group_id=0).

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

**Chain edges (iter 4 two-ended)**: each feature row carries both
`chain_parent_feature` (= chain **successor**, historical
misnomer — "what comes after this feature in the round
sequence") and `chain_predecessor_feature` (= who fires this
feature). Confidence labels on each end. Front-end's
`chainsInto(payingName)` builds inbound breadcrumbs from
`chain_parent_feature` edges (back-compat preserved).

**Settlement-style features (iter 5-6)**: Pass 5 binds paying
features to zero-win settlement SpinTypes (M15 TopDollar → ST
15; the settlement rounds have `WinCredits=None` so round-level
aggregators see no data). Such features get their
`bucket_distribution` from a per-session win histogram keyed by
settlement ST instead of the round-level `spin_type_bucket_win`.
Feature header `rtp_contribution_pp` equals
`sum(bucket_distribution[*].rtp_contribution_pp)` exactly.

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

### `payline_symbol_top20`

Joint (payline_id, symbol_code) analysis. Top 20 by rtp_contribution_pp.
Per row: `payline_symbol` (composite key), `payline_id`, `symbol`,
`hits`, `total_win`, `rtp_contribution_pp`.

### `session_rtp_curves`

Per-robot cumulative RTP at ~50 sampled paid-spin indices. Each entry
is a list of `{spin, cum_rtp}`. Capped at 50 robots. Frontend can
plot spaghetti lines or compute p10/p50/p90 envelope.

### `chain_ratio_sequences`

Per-chain ordered ExtraRatio list, e.g. `[100, 200, 300, 400, 500]`.
Shows the complete multiplier escalation path within each bonus chain.
Capped at 50 chains.

### `reel_position_top20`

Position codes from `PayoutByPayline`'s `(pos1,pos2,...)` groups,
ranked by hit count. Per row: `position`, `hits`.

### `symbols_top20` and `symbols_by_column_top10`

Symbol-level and reel/column-level frequency breakdown.

### `bankruptcy_probe`

Back-compat alias for the tier list inside `bankruptcy_simulation`
(see API_REFERENCE `summary.player_impact.bankruptcy_simulation` for the
richer rawdata-replay shape). Legacy consumers read `bankruptcy_probe`;
both keys are produced by the `bankruptcy_simulation` feature plugin.
List entries by bankroll multiplier:

- `bankroll_multiplier`
- `bankruptcy_rate`
- `bankrupt_robots`
- `completed_robots`
- `median_spins_completed`
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
- `newfreespin_correction` -- `{applicable, detected_cycle_length,
  completed_cycles_total, robots_with_pending_cycle,
  avg_newfreespin_payout, estimated_correction_pp}`. Dynamically
  detects the BuffCollectionMap cycle length from CC reset patterns
  (M272 mode 1 = 1000 paid spins). Estimates lost RTP from
  incomplete cycles. `estimated_correction_pp` is the additive
  correction to apply to `rtp.point_pct`. Zero when
  chunk_spin_times is perfectly aligned to the cycle length.

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

