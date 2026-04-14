# M14 Mode=1 Player Impact Report

## Sampling
- total_spins: 200
- chunks: 1
- target_halfwidth_pp: 5.0
- achieved_halfwidth_pp: None
- stop_reason: max_chunks_reached
- duration_seconds: 0.87

## RTP
- point_pct: 136.580000%
- ci95_interval_pct: None

## Player Impact
- volatility.avg_return_x: 1.365800
- volatility.std_return_x: 6.550598
- volatility.max_observed_return_x: 79.010000
- win_hit_rate: 0.220000
- zero_win_rate: 0.780000
- profit_spin_rate: 0.115000
- breakeven_or_more_rate: 0.115000
- big_win_x10_rate: 0.040000
- avg_win_when_hit_x: 6.208182
- loss_streak p50/p90/p95/max: 3/10/13/14
- win_streak p50/p90/p95/max: 1/2/3/4

## Multiplier Buckets (ret_x = win/bet)
- tail_spin_rate_ge10x: 0.040000
- tail_rtp_contribution_pp_ge10x: 98.905000
- tail_win_share_ge10x: 0.724154
- eq0: spin_rate=0.780000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- gt0_lt0.5: spin_rate=0.090000, avg_x=0.305556, rtp_pp=2.750000, win_share=0.020135
- ge0.5_lt1: spin_rate=0.015000, avg_x=0.623333, rtp_pp=0.935000, win_share=0.006846
- ge1_lt2: spin_rate=0.030000, avg_x=1.466667, rtp_pp=4.400000, win_share=0.032216
- ge2_lt5: spin_rate=0.010000, avg_x=2.970000, rtp_pp=2.970000, win_share=0.021745
- ge5_lt10: spin_rate=0.035000, avg_x=7.605714, rtp_pp=26.620000, win_share=0.194904
- ge10_lt20: spin_rate=0.025000, avg_x=14.080000, rtp_pp=35.200000, win_share=0.257724
- ge20_lt50: spin_rate=0.010000, avg_x=24.200000, rtp_pp=24.200000, win_share=0.177186
- ge50_lt100: spin_rate=0.005000, avg_x=79.010000, rtp_pp=39.505000, win_share=0.289244
- ge100: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000

## Guideline Assessment
- quality_label: EXPLORATORY
- volatility_class: Very High
- experience_archetype: Boom-Bust
- recovery_gap: 0.105000
- tail_dependency: 0.724154
- payline_top1_share: 0.134903
- payline_top3_share: 0.443824
- blank_like_rate: 0.506667
- blank_like_col_spread: 0.013333
- x100_bankruptcy_rate: 0.000000
- x200_bankruptcy_rate: 0.000000
- x500_bankruptcy_rate: 0.000000
- alerts:
- [high] A1_CI_NOT_REACHED: CI half-width target not reached.
- [medium] A4_HIGH_TAIL_DEPENDENCY: RTP depends heavily on >=10x tail outcomes.
- action_1: Reduce >=10x tail RTP share slightly and reallocate to ge1_lt2 or ge2_lt5.

## Conclusion Template (Filled)
1. Data confidence: CI half-width=None, target<=5.0, spins=200, quality=EXPLORATORY.
2. Player feel: Boom-Bust feel with Very High volatility: zero_win_rate=0.7800, loss_streak_p95=13.
3. RTP structure: >=10x tail contributes 98.9050pp RTP (dependency=0.7242).
4. Session risk: Bankruptcy ladder: x100=0.0000, x200=0.0000, x500=0.0000.
5. Design action: Reduce >=10x tail RTP share slightly and reallocate to ge1_lt2 or ge2_lt5.

## Top Paylines (approx by split win)
- line 7: hit_rate=0.045000, approx_rtp_pp=18.425000
- line 9: hit_rate=0.040000, approx_rtp_pp=18.951250
- line 5: hit_rate=0.040000, approx_rtp_pp=23.241250
- line 4: hit_rate=0.040000, approx_rtp_pp=16.256250
- line 3: hit_rate=0.035000, approx_rtp_pp=9.020000
- line 1: hit_rate=0.030000, approx_rtp_pp=10.780000
- line 2: hit_rate=0.030000, approx_rtp_pp=14.740000
- line 8: hit_rate=0.015000, approx_rtp_pp=19.611250
- line 6: hit_rate=0.010000, approx_rtp_pp=5.555000

## Top Symbols
- blank: rate=0.506667
- cherry: rate=0.176111
- 1bar: rate=0.089444
- 3bar: rate=0.064444
- high7: rate=0.055556
- 2bar: rate=0.051667
- 5x_wild: rate=0.020000
- 35x_wild: rate=0.014444
- 7x_wild: rate=0.013889
- jackpot: rate=0.007778

## Bankruptcy Probe
- bankroll x100: bankruptcy_rate=0.000000, avg_spins_completed=100.00

## Storage
- raw_round_data_persisted: false
- persisted: player_impact_summary.json + player_impact_report.md

Note: payline contribution is approximate because one spin may hit multiple paylines and win is split evenly across parsed line ids.
