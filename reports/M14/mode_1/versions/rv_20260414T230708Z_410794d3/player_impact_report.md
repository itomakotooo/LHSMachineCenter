# M14 Mode=1 Player Impact Report

## Sampling
- total_spins: 40
- chunks: 1
- target_halfwidth_pp: 5.0
- achieved_halfwidth_pp: None
- stop_reason: max_chunks_reached
- duration_seconds: 0.599

## RTP
- point_pct: 55.000000%
- ci95_interval_pct: None

## Player Impact
- volatility.avg_return_x: 0.550000
- volatility.std_return_x: 2.349882
- volatility.max_observed_return_x: 11.550000
- win_hit_rate: 0.100000
- zero_win_rate: 0.900000
- profit_spin_rate: 0.050000
- breakeven_or_more_rate: 0.050000
- big_win_x10_rate: 0.025000
- avg_win_when_hit_x: 5.500000
- loss_streak p50/p90/p95/max: 7/11/11/11
- win_streak p50/p90/p95/max: 1/2/2/2

## Multiplier Buckets (ret_x = win/bet)
- tail_spin_rate_ge10x: 0.025000
- tail_rtp_contribution_pp_ge10x: 28.875000
- tail_win_share_ge10x: 0.525000
- eq0: spin_rate=0.900000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- gt0_lt0.5: spin_rate=0.025000, avg_x=0.220000, rtp_pp=0.550000, win_share=0.010000
- ge0.5_lt1: spin_rate=0.025000, avg_x=0.550000, rtp_pp=1.375000, win_share=0.025000
- ge1_lt2: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge2_lt5: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge5_lt10: spin_rate=0.025000, avg_x=9.680000, rtp_pp=24.200000, win_share=0.440000
- ge10_lt20: spin_rate=0.025000, avg_x=11.550000, rtp_pp=28.875000, win_share=0.525000
- ge20_lt50: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge50_lt100: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge100: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000

## Guideline Assessment
- quality_label: EXPLORATORY
- volatility_class: Very High
- experience_archetype: Boom-Bust
- recovery_gap: 0.050000
- tail_dependency: 0.525000
- payline_top1_share: 0.550000
- payline_top3_share: 0.780000
- blank_like_rate: 0.530556
- blank_like_col_spread: 0.008333
- x100_bankruptcy_rate: 0.000000
- x200_bankruptcy_rate: 0.000000
- x500_bankruptcy_rate: 0.000000

## Guideline Rule Comparison (External Rules)
- guideline_id: classic_slots_report_guideline_v1
- overall_status: FAIL
- checks: total=11 pass=5 fail=6 missing=0 not_applicable=0
- [fail] Q1_CI_HALF_WIDTH (high): CI half-width should be <= 0.5pp for report-grade output. observed=None target=0.5
- [fail] Q2_SAMPLE_SIZE (high): Total spins should usually be >= 2,000,000. observed=40 target=2000000
- [fail] A2_ZERO_PROFIT_BALANCE (high): If zero_win_rate > 0.80, profit_spin_rate should be >= 0.10. observed=0.05 target=0.1
- [fail] A4_TAIL_DEPENDENCY (high): tail_dependency should stay below 0.45. observed=0.5249999999999999 target=0.45
- [fail] P1_PAYLINE_TOP1 (medium): Top-1 payline share should stay <= 0.20. observed=0.55 target=0.2
- [fail] P2_PAYLINE_TOP3 (medium): Top-3 payline share should stay <= 0.55. observed=0.78 target=0.55
- alerts:
- [high] A1_CI_NOT_REACHED: CI half-width target not reached.
- [high] A2_DRY_AND_LOW_PROFIT: High dead-spin rate with low profit-spin rate.
- [medium] A4_HIGH_TAIL_DEPENDENCY: RTP depends heavily on >=10x tail outcomes.
- [medium] A6_PAYLINE_CONCENTRATION: Payline RTP contribution is concentrated.
- action_1: Increase low/mid return buckets (gt0_lt0.5 and ge0.5_lt1) to reduce dry feel.
- action_2: Reduce >=10x tail RTP share slightly and reallocate to ge1_lt2 or ge2_lt5.

## Conclusion Template (Filled)
1. Data confidence: CI half-width=None, target<=5.0, spins=40, quality=EXPLORATORY.
2. Player feel: Boom-Bust feel with Very High volatility: zero_win_rate=0.9000, loss_streak_p95=11.
3. RTP structure: >=10x tail contributes 28.8750pp RTP (dependency=0.5250).
4. Session risk: Bankruptcy ladder: x100=0.0000, x200=0.0000, x500=0.0000.
5. Design action: Increase low/mid return buckets (gt0_lt0.5 and ge0.5_lt1) to reduce dry feel.

## Top Paylines (approx by split win)
- line 7: hit_rate=0.050000, approx_rtp_pp=30.250000
- line 1: hit_rate=0.025000, approx_rtp_pp=0.550000
- line 2: hit_rate=0.025000, approx_rtp_pp=12.100000
- line 3: hit_rate=0.025000, approx_rtp_pp=12.100000

## Top Symbols
- blank: rate=0.530556
- cherry: rate=0.183333
- 1bar: rate=0.088889
- 2bar: rate=0.080556
- high7: rate=0.047222
- 3bar: rate=0.027778
- 7x_wild: rate=0.011111
- 5x_wild: rate=0.011111
- 35x_wild: rate=0.011111
- jackpot: rate=0.008333

## Bankruptcy Probe
- bankroll x100: bankruptcy_rate=0.000000, avg_spins_completed=200.00
- bankroll x200: bankruptcy_rate=0.000000, avg_spins_completed=200.00
- bankroll x500: bankruptcy_rate=0.000000, avg_spins_completed=200.00

## Storage
- raw_round_data_persisted: false
- persisted: player_impact_summary.json + player_impact_report.md

Note: payline contribution is approximate because one spin may hit multiple paylines and win is split evenly across parsed line ids.
