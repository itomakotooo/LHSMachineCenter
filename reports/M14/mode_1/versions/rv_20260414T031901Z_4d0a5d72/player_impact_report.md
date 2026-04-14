# M14 Mode=1 Player Impact Report

## Sampling
- total_spins: 80
- chunks: 1
- target_halfwidth_pp: 5.0
- achieved_halfwidth_pp: None
- stop_reason: max_chunks_reached
- duration_seconds: 0.879

## RTP
- point_pct: 71.775000%
- ci95_interval_pct: None

## Player Impact
- volatility.avg_return_x: 0.717750
- volatility.std_return_x: 2.143650
- volatility.max_observed_return_x: 11.550000
- win_hit_rate: 0.250000
- zero_win_rate: 0.750000
- profit_spin_rate: 0.137500
- breakeven_or_more_rate: 0.137500
- big_win_x10_rate: 0.025000
- avg_win_when_hit_x: 2.871000
- loss_streak p50/p90/p95/max: 2/11/14/14
- win_streak p50/p90/p95/max: 1/2/2/2

## Multiplier Buckets (ret_x = win/bet)
- tail_spin_rate_ge10x: 0.025000
- tail_rtp_contribution_pp_ge10x: 28.050000
- tail_win_share_ge10x: 0.390805
- eq0: spin_rate=0.750000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- gt0_lt0.5: spin_rate=0.100000, avg_x=0.316250, rtp_pp=3.162500, win_share=0.044061
- ge0.5_lt1: spin_rate=0.012500, avg_x=0.660000, rtp_pp=0.825000, win_share=0.011494
- ge1_lt2: spin_rate=0.025000, avg_x=1.485000, rtp_pp=3.712500, win_share=0.051724
- ge2_lt5: spin_rate=0.075000, avg_x=3.336667, rtp_pp=25.025000, win_share=0.348659
- ge5_lt10: spin_rate=0.012500, avg_x=8.800000, rtp_pp=11.000000, win_share=0.153257
- ge10_lt20: spin_rate=0.025000, avg_x=11.220000, rtp_pp=28.050000, win_share=0.390805
- ge20_lt50: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge50_lt100: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge100: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000

## Guideline Assessment
- quality_label: EXPLORATORY
- volatility_class: High
- experience_archetype: Boom-Bust
- recovery_gap: 0.112500
- tail_dependency: 0.390805
- payline_top1_share: 0.228448
- payline_top3_share: 0.647031
- blank_like_rate: 0.486111
- blank_like_col_spread: 0.075000
- x100_bankruptcy_rate: 0.000000
- x200_bankruptcy_rate: 0.000000
- x500_bankruptcy_rate: 0.000000

## Guideline Rule Comparison (External Rules)
- guideline_id: classic_slots_report_guideline_v1
- overall_status: FAIL
- checks: total=11 pass=5 fail=5 missing=0 not_applicable=1
- [fail] Q1_CI_HALF_WIDTH (high): CI half-width should be <= 0.5pp for report-grade output. observed=None target=0.5
- [fail] Q2_SAMPLE_SIZE (high): Total spins should usually be >= 2,000,000. observed=80 target=2000000
- [not_applicable] A2_ZERO_PROFIT_BALANCE (high): If zero_win_rate > 0.80, profit_spin_rate should be >= 0.10. observed=N/A target=0.1
- [fail] P1_PAYLINE_TOP1 (medium): Top-1 payline share should stay <= 0.20. observed=0.22844827586206898 target=0.2
- [fail] P2_PAYLINE_TOP3 (medium): Top-3 payline share should stay <= 0.55. observed=0.6470306513409961 target=0.55
- [fail] S1_SYMBOL_DISTRIBUTION_SKEW (medium): Symbol distribution skew flag should be false. observed=True target=False
- alerts:
- [high] A1_CI_NOT_REACHED: CI half-width target not reached.
- [medium] A6_PAYLINE_CONCENTRATION: Payline RTP contribution is concentrated.
- [medium] A7_SYMBOL_SKEW: Blank-like symbol distribution spread across columns exceeds 5pp.
- action_1: Profile is within baseline guardrails; run targeted A/B tests on mid buckets for finer tuning.

## Conclusion Template (Filled)
1. Data confidence: CI half-width=None, target<=5.0, spins=80, quality=EXPLORATORY.
2. Player feel: Boom-Bust feel with High volatility: zero_win_rate=0.7500, loss_streak_p95=14.
3. RTP structure: >=10x tail contributes 28.0500pp RTP (dependency=0.3908).
4. Session risk: Bankruptcy ladder: x100=0.0000, x200=0.0000, x500=0.0000.
5. Design action: Profile is within baseline guardrails; run targeted A/B tests on mid buckets for finer tuning.

## Top Paylines (approx by split win)
- line 5: hit_rate=0.087500, approx_rtp_pp=16.396875
- line 9: hit_rate=0.087500, approx_rtp_pp=21.553125
- line 8: hit_rate=0.050000, approx_rtp_pp=8.490625
- line 3: hit_rate=0.037500, approx_rtp_pp=4.950000
- line 4: hit_rate=0.037500, approx_rtp_pp=6.084375
- line 1: hit_rate=0.012500, approx_rtp_pp=0.825000
- line 2: hit_rate=0.012500, approx_rtp_pp=0.412500
- line 6: hit_rate=0.012500, approx_rtp_pp=11.000000
- line 7: hit_rate=0.012500, approx_rtp_pp=2.062500

## Top Symbols
- blank: rate=0.486111
- cherry: rate=0.168056
- 1bar: rate=0.083333
- high7: rate=0.070833
- 2bar: rate=0.065278
- 3bar: rate=0.058333
- 5x_wild: rate=0.033333
- 35x_wild: rate=0.016667
- jackpot: rate=0.011111
- 7x_wild: rate=0.006944

## Bankruptcy Probe
- bankroll x100: bankruptcy_rate=0.000000, avg_spins_completed=100.00
- bankroll x200: bankruptcy_rate=0.000000, avg_spins_completed=100.00
- bankroll x500: bankruptcy_rate=0.000000, avg_spins_completed=100.00

## Storage
- raw_round_data_persisted: false
- persisted: player_impact_summary.json + player_impact_report.md

Note: payline contribution is approximate because one spin may hit multiple paylines and win is split evenly across parsed line ids.
