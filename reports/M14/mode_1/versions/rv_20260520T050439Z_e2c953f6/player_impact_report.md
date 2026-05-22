# M14 Mode=1 Player Impact Report

## Sampling
- total_spins: 110000
- chunks: 6
- target_halfwidth_pp: 0.5
- achieved_halfwidth_pp: 2.7311251988232677
- chunk_level_halfwidth_pp: None
- session_level_halfwidth_pp: 2.7311251988232677
- stop_reason: max_chunks_reached
- duration_seconds: 905.4

## RTP
- point_pct: 93.488145%
- ci95_interval_pct: [90.7570202557222, 96.21927065336872]

## Player Impact
- volatility.avg_return_x: 0.934881
- volatility.std_return_x: 4.616778
- volatility.max_observed_return_x: 193.550000
- win_hit_rate: 0.208527
- zero_win_rate: 0.791473
- profit_spin_rate: 0.109355
- breakeven_or_more_rate: 0.109355
- big_win_x10_rate: 0.027991
- big_win_x20_rate: 0.010882
- big_win_x50_rate: 0.001664
- big_win_x100_rate: 0.000091
- avg_win_when_hit_x: 4.483257
- loss_streak p50/p90/p95/max: 3/10/13/41
- win_streak p50/p90/p95/max: 1/2/2/8

## Multiplier Buckets (ret_x = win/bet)
- tail_spin_rate_ge10x: 0.027991
- tail_rtp_contribution_pp_ge10x: 63.165545
- tail_rtp_contribution_pp_ge20x: 39.665409
- tail_rtp_contribution_pp_ge50x: 11.388209
- tail_rtp_contribution_pp_ge100x: 1.097636
- tail_win_share_ge10x: 0.675653
- gt0_lt1: spin_rate=0.099173, avg_x=0.344863, rtp_pp=3.420100, win_share=0.036583
- ge1_lt5: spin_rate=0.064700, avg_x=2.186321, rtp_pp=14.145500, win_share=0.151308
- ge5_lt10: spin_rate=0.016664, avg_x=7.655592, rtp_pp=12.757000, win_share=0.136456
- ge10_lt20: spin_rate=0.017109, avg_x=13.735468, rtp_pp=23.500136, win_share=0.251370
- ge20_lt50: spin_rate=0.009218, avg_x=30.675464, rtp_pp=28.277200, win_share=0.302468
- ge50_lt100: spin_rate=0.001573, avg_x=65.431387, rtp_pp=10.290573, win_share=0.110074
- ge100_lt200: spin_rate=0.000091, avg_x=120.740000, rtp_pp=1.097636, win_share=0.011741
- ge200_lt500: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge500_lt1000: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge1000_lt5000: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge5000: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000

## Guideline Assessment
- quality_label: EXPLORATORY
- volatility_class: Very High
- experience_archetype: Boom-Bust
- recovery_gap: 0.099173
- tail_dependency: 0.675653
- payline_top1_share: 0.130039
- payline_top3_share: 0.361909
- blank_like_rate: 0.500811
- blank_like_col_spread: 0.000721
- x100_bankruptcy_rate: 0.975610
- x200_bankruptcy_rate: 0.951220
- x500_bankruptcy_rate: 0.823529

## Guideline Rule Comparison (External Rules)
- guideline_id: classic_slots_report_guideline_v1
- overall_status: FAIL
- checks: total=11 pass=6 fail=4 missing=0 not_applicable=1
- [fail] Q1_CI_HALF_WIDTH (high): CI half-width should be <= 0.5pp for report-grade output. observed=2.7311251988232677 target=0.5
- [fail] Q2_SAMPLE_SIZE (high): Total spins should usually be >= 2,000,000. observed=110000 target=2000000
- [not_applicable] A2_ZERO_PROFIT_BALANCE (high): If zero_win_rate > 0.80, profit_spin_rate should be >= 0.10. observed=N/A target=0.1
- [fail] A4_TAIL_DEPENDENCY (high): tail_dependency should stay below 0.45. observed=0.6756529947987572 target=0.45
- [fail] A5_BANKRUPTCY_X200 (high): x200 bankruptcy rate should stay below 0.10. observed=0.9512195121951219 target=0.1
- alerts:
- [high] A1_CI_NOT_REACHED: CI half-width target not reached.
- [medium] A4_HIGH_TAIL_DEPENDENCY: RTP depends heavily on >=10x tail outcomes.
- [high] A5_X200_BANKRUPTCY_HIGH: x200 bankroll bankruptcy rate is above 10%.
- action_1: Reduce >=10x tail RTP share slightly and reallocate to ge1_lt5.
- action_2: Improve session survivability at x200 bankroll by raising mid-tier payout continuity.

## Conclusion Template (Filled)
1. Data confidence: CI half-width=2.7311251988232677, target<=0.5, spins=110000, quality=EXPLORATORY.
2. Player feel: Boom-Bust feel with Very High volatility: zero_win_rate=0.7915, loss_streak_p95=13.
3. RTP structure: >=10x tail contributes 63.1655pp RTP (dependency=0.6757).
4. Session risk: Bankruptcy ladder: x100=0.9756, x200=0.9512, x500=0.8235.
5. Design action: Reduce >=10x tail RTP share slightly and reallocate to ge1_lt5.

## Top Paylines (approx by split win)
- line 6: hit_rate=0.030927, approx_rtp_pp=12.157091
- line 1: hit_rate=0.030309, approx_rtp_pp=11.148091
- line 7: hit_rate=0.030264, approx_rtp_pp=10.529009
- line 2: hit_rate=0.029882, approx_rtp_pp=10.804823
- line 9: hit_rate=0.029555, approx_rtp_pp=10.731512
- line 3: hit_rate=0.028864, approx_rtp_pp=9.780614
- line 4: hit_rate=0.028709, approx_rtp_pp=9.593102
- line 8: hit_rate=0.028655, approx_rtp_pp=8.996000
- line 5: hit_rate=0.027800, approx_rtp_pp=9.747905

## Top Symbols
- blank: rate=0.500811
- cherry: rate=0.172040
- 1bar: rate=0.089511
- 2bar: rate=0.063241
- 3bar: rate=0.059690
- high7: rate=0.059142
- 5x_wild: rate=0.023495
- 35x_wild: rate=0.012941
- 7x_wild: rate=0.012782
- jackpot: rate=0.006345

## Per-pay_id by SpinType
Columns: payout_id | hit_count | rtp_contribution_pp | total_win. Each sub-section is one SpinType (base vs freespin etc.).

### ST1_paid
| pay_id | hits | rtp_contribution_pp | total_win |
|--------|------|---------------------|-----------|
| 6 | 10985 | 19.3434 | 21277740 |
| 7 | 9094 | 19.0104 | 20911440 |
| 5 | 1889 | 14.3568 | 15792480 |
| 2 | 1026 | 14.0008 | 15400880 |
| 3 | 1176 | 11.8032 | 12983520 |
| 4 | 1260 | 9.6405 | 10604550 |
| 1 | 133 | 5.3330 | 5866350 |

## Per-reel Marginal by SpinType
Symbol probability per reel (col), split by SpinType. prob_pct sums to 100 per (SpinType, reel).

### ST1_paid
#### Reel 0
| symbol | prob_pct |
|--------|----------|
| blank | 50.108% |
| cherry | 17.569% |
| 1bar | 10.202% |
| 3bar | 6.421% |
| 2bar | 6.310% |
| high7 | 3.816% |
| 5x_wild | 2.339% |
| 35x_wild | 1.299% |
| 7x_wild | 1.291% |
| jackpot | 0.645% |
#### Reel 1
| symbol | prob_pct |
|--------|----------|
| blank | 50.036% |
| cherry | 16.472% |
| high7 | 10.109% |
| 1bar | 6.382% |
| 2bar | 6.319% |
| 3bar | 5.152% |
| 5x_wild | 2.345% |
| 35x_wild | 1.293% |
| 7x_wild | 1.252% |
| jackpot | 0.641% |
#### Reel 2
| symbol | prob_pct |
|--------|----------|
| blank | 50.098% |
| cherry | 17.571% |
| 1bar | 10.270% |
| 2bar | 6.343% |
| 3bar | 6.334% |
| high7 | 3.818% |
| 5x_wild | 2.365% |
| 7x_wild | 1.292% |
| 35x_wild | 1.291% |
| jackpot | 0.618% |

## Bankruptcy Simulation (rawdata replay)
- session_spins: 10000
- percentile_keys: [10, 20, 30, 40, 50, 60, 70, 80, 90]
- bankroll x10: bankruptcy_rate=0.997630, median=13, fastest=10, sessions=844, survived=2, P10=10 P20=10 P30=10 P40=11 P50=13 P60=17 P70=25 P80=46 P90=127
- bankroll x100: bankruptcy_rate=0.975610, median=512, fastest=113, sessions=82, survived=2, P10=183 P20=249 P30=285 P40=408 P50=512 P60=747 P70=1164 P80=1959 P90=3583
- bankroll x200: bankruptcy_rate=0.951220, median=1393, fastest=375, sessions=41, survived=2, P10=618 P20=764 P30=874 P40=1085 P50=1393 P60=1763 P70=2963 P80=3887 P90=6781
- bankroll x500: bankruptcy_rate=0.823529, median=7246, fastest=1632, sessions=17, survived=3, P10=2766 P20=3143 P30=3913 P40=4890 P50=7246 P60=7530 P70=7667 P80=9954 P90=10000

## Storage
- raw_round_data_persisted: false
- persisted: player_impact_summary.json + player_impact_report.md

Note: payline contribution is approximate because one spin may hit multiple paylines and win is split evenly across parsed line ids.
