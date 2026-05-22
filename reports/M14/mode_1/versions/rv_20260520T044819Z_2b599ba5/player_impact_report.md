# M14 Mode=1 Player Impact Report

## Sampling
- total_spins: 0
- chunks: 0
- target_halfwidth_pp: 0.5
- achieved_halfwidth_pp: None
- chunk_level_halfwidth_pp: None
- session_level_halfwidth_pp: None
- stop_reason: max_chunks_reached
- duration_seconds: 903.091

## RTP
- point_pct: 0.000000%
- ci95_interval_pct: None

## Player Impact
- volatility.avg_return_x: 0.000000
- volatility.std_return_x: 0.000000
- volatility.max_observed_return_x: 0.000000
- win_hit_rate: 0.000000
- zero_win_rate: 0.000000
- profit_spin_rate: 0.000000
- breakeven_or_more_rate: 0.000000
- big_win_x10_rate: 0.000000
- big_win_x20_rate: 0.000000
- big_win_x50_rate: 0.000000
- big_win_x100_rate: 0.000000
- avg_win_when_hit_x: 0.000000
- loss_streak p50/p90/p95/max: 0/0/0/0
- win_streak p50/p90/p95/max: 0/0/0/0

## Multiplier Buckets (ret_x = win/bet)
- tail_spin_rate_ge10x: 0.000000
- tail_rtp_contribution_pp_ge10x: 0.000000
- tail_rtp_contribution_pp_ge20x: 0.000000
- tail_rtp_contribution_pp_ge50x: 0.000000
- tail_rtp_contribution_pp_ge100x: 0.000000
- tail_win_share_ge10x: 0.000000
- gt0_lt1: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge1_lt5: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge5_lt10: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge10_lt20: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge20_lt50: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge50_lt100: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge100_lt200: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge200_lt500: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge500_lt1000: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge1000_lt5000: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000
- ge5000: spin_rate=0.000000, avg_x=0.000000, rtp_pp=0.000000, win_share=0.000000

## Guideline Assessment
- quality_label: EXPLORATORY
- volatility_class: Low
- experience_archetype: Balanced
- recovery_gap: 0.000000
- tail_dependency: 0.000000
- payline_top1_share: 0.000000
- payline_top3_share: 0.000000
- blank_like_rate: 0.000000
- blank_like_col_spread: 0.000000
- x100_bankruptcy_rate: 0.000000
- x200_bankruptcy_rate: 0.000000
- x500_bankruptcy_rate: 0.000000

## Guideline Rule Comparison (External Rules)
- guideline_id: classic_slots_report_guideline_v1
- overall_status: FAIL
- checks: total=11 pass=8 fail=2 missing=0 not_applicable=1
- [fail] Q1_CI_HALF_WIDTH (high): CI half-width should be <= 0.5pp for report-grade output. observed=None target=0.5
- [fail] Q2_SAMPLE_SIZE (high): Total spins should usually be >= 2,000,000. observed=0 target=2000000
- [not_applicable] A2_ZERO_PROFIT_BALANCE (high): If zero_win_rate > 0.80, profit_spin_rate should be >= 0.10. observed=N/A target=0.1
- alerts:
- [high] A1_CI_NOT_REACHED: CI half-width target not reached.
- action_1: Profile is within baseline guardrails; run targeted A/B tests on mid buckets for finer tuning.

## Conclusion Template (Filled)
1. Data confidence: CI half-width=None, target<=0.5, spins=0, quality=EXPLORATORY.
2. Player feel: Balanced feel with Low volatility: zero_win_rate=0.0000, loss_streak_p95=0.
3. RTP structure: >=10x tail contributes 0.0000pp RTP (dependency=0.0000).
4. Session risk: Bankruptcy ladder: x100=0.0000, x200=0.0000, x500=0.0000.
5. Design action: Profile is within baseline guardrails; run targeted A/B tests on mid buckets for finer tuning.

## Top Paylines (approx by split win)

## Top Symbols

## Per-pay_id by SpinType
Columns: payout_id | hit_count | rtp_contribution_pp | total_win. Each sub-section is one SpinType (base vs freespin etc.).

## Per-reel Marginal by SpinType
Symbol probability per reel (col), split by SpinType. prob_pct sums to 100 per (SpinType, reel).

## Bankruptcy Simulation (rawdata replay)
- session_spins: 10000
- percentile_keys: [10, 20, 30, 40, 50, 60, 70, 80, 90]
- bankroll x10: bankruptcy_rate=0.000000, median=0, fastest=-, sessions=0, survived=0, P10=0 P20=0 P30=0 P40=0 P50=0 P60=0 P70=0 P80=0 P90=0
- bankroll x100: bankruptcy_rate=0.000000, median=0, fastest=-, sessions=0, survived=0, P10=0 P20=0 P30=0 P40=0 P50=0 P60=0 P70=0 P80=0 P90=0
- bankroll x200: bankruptcy_rate=0.000000, median=0, fastest=-, sessions=0, survived=0, P10=0 P20=0 P30=0 P40=0 P50=0 P60=0 P70=0 P80=0 P90=0
- bankroll x500: bankruptcy_rate=0.000000, median=0, fastest=-, sessions=0, survived=0, P10=0 P20=0 P30=0 P40=0 P50=0 P60=0 P70=0 P80=0 P90=0

## Storage
- raw_round_data_persisted: false
- persisted: player_impact_summary.json + player_impact_report.md

Note: payline contribution is approximate because one spin may hit multiple paylines and win is split evenly across parsed line ids.
