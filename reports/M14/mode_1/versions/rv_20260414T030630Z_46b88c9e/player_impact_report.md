# M14 Mode=1 Player Impact Report

## Sampling
- total_spins: 200
- chunks: 1
- target_halfwidth_pp: 5.0
- achieved_halfwidth_pp: None
- stop_reason: max_chunks_reached
- duration_seconds: 1.086

## RTP
- point_pct: 52.250000%
- ci95_interval_pct: None

## Player Impact
- volatility.avg_return_x: 0.522500
- volatility.std_return_x: 2.087416
- volatility.max_observed_return_x: 15.400000
- win_hit_rate: 0.170000
- zero_win_rate: 0.830000
- profit_spin_rate: 0.090000
- breakeven_or_more_rate: 0.090000
- big_win_x10_rate: 0.020000
- avg_win_when_hit_x: 3.073529
- loss_streak p50/p90/p95/max: 5/15/15/20
- win_streak p50/p90/p95/max: 1/2/2/3

## Multiplier Buckets (ret_x = win/bet)
- tail_spin_rate_ge10x: 0.020000
- tail_rtp_contribution_pp_ge10x: 26.510000
- tail_win_share_ge10x: 0.507368
- eq0: spin_rate=0.830000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- gt0_lt0.5: spin_rate=0.060000, avg_x=0.302500, rtp_pp=1.815000, win_share=0.034737
- ge0.5_lt1: spin_rate=0.020000, avg_x=0.605000, rtp_pp=1.210000, win_share=0.023158
- ge1_lt2: spin_rate=0.025000, avg_x=1.540000, rtp_pp=3.850000, win_share=0.073684
- ge2_lt5: spin_rate=0.030000, avg_x=2.878333, rtp_pp=8.635000, win_share=0.165263
- ge5_lt10: spin_rate=0.015000, avg_x=6.820000, rtp_pp=10.230000, win_share=0.195789
- ge10_lt20: spin_rate=0.020000, avg_x=13.255000, rtp_pp=26.510000, win_share=0.507368
- ge20_lt50: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge50_lt100: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge100: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000

## Guideline Assessment
- quality_label: EXPLORATORY
- volatility_class: Very High
- experience_archetype: Boom-Bust
- recovery_gap: 0.080000
- tail_dependency: 0.507368
- payline_top1_share: 0.364211
- payline_top3_share: 0.582105
- blank_like_rate: 0.493333
- blank_like_col_spread: 0.013333
- x100_bankruptcy_rate: 0.000000
- x200_bankruptcy_rate: 0.000000
- x500_bankruptcy_rate: 0.000000
- alerts:
- [high] A1_CI_NOT_REACHED: CI half-width target not reached.
- [high] A2_DRY_AND_LOW_PROFIT: High dead-spin rate with low profit-spin rate.
- [medium] A3_LONG_LOSS_STREAK: Loss streak p95 is high.
- [medium] A4_HIGH_TAIL_DEPENDENCY: RTP depends heavily on >=10x tail outcomes.
- [medium] A6_PAYLINE_CONCENTRATION: Payline RTP contribution is concentrated.
- action_1: Increase low/mid return buckets (gt0_lt0.5 and ge0.5_lt1) to reduce dry feel.
- action_2: Reduce >=10x tail RTP share slightly and reallocate to ge1_lt2 or ge2_lt5.

## Conclusion Template (Filled)
1. Data confidence: CI half-width=None, target<=5.0, spins=200, quality=EXPLORATORY.
2. Player feel: Boom-Bust feel with Very High volatility: zero_win_rate=0.8300, loss_streak_p95=15.
3. RTP structure: >=10x tail contributes 26.5100pp RTP (dependency=0.5074).
4. Session risk: Bankruptcy ladder: x100=0.0000, x200=0.0000, x500=0.0000.
5. Design action: Increase low/mid return buckets (gt0_lt0.5 and ge0.5_lt1) to reduce dry feel.

## Top Paylines (approx by split win)
- line 3: hit_rate=0.055000, approx_rtp_pp=19.030000
- line 2: hit_rate=0.045000, approx_rtp_pp=8.965000
- line 5: hit_rate=0.025000, approx_rtp_pp=2.420000
- line 6: hit_rate=0.025000, approx_rtp_pp=9.955000
- line 8: hit_rate=0.020000, approx_rtp_pp=2.860000
- line 1: hit_rate=0.020000, approx_rtp_pp=0.605000
- line 9: hit_rate=0.015000, approx_rtp_pp=4.510000
- line 4: hit_rate=0.010000, approx_rtp_pp=3.740000
- line 7: hit_rate=0.005000, approx_rtp_pp=0.165000

## Top Symbols
- blank: rate=0.493333
- cherry: rate=0.177778
- 1bar: rate=0.089444
- 2bar: rate=0.070000
- high7: rate=0.058889
- 3bar: rate=0.055556
- 5x_wild: rate=0.021667
- 7x_wild: rate=0.017222
- 35x_wild: rate=0.012222
- jackpot: rate=0.003889

## Bankruptcy Probe
- bankroll x100: bankruptcy_rate=0.000000, avg_spins_completed=100.00

## Storage
- raw_round_data_persisted: false
- persisted: player_impact_summary.json + player_impact_report.md

Note: payline contribution is approximate because one spin may hit multiple paylines and win is split evenly across parsed line ids.
