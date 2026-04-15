# Classic Slots Report Guideline (No-Link Practical Edition)

## 1) Goal

Use one stable interpretation framework for all classic-slot reports so planning decisions
do not depend on ad-hoc explanation style.

This guideline is analysis-oriented, not legal advice.

## 2) Mandatory Report Blocks

Every report must include all blocks below. Missing any block means report is incomplete.

1. Sampling Integrity
2. RTP + CI
3. Multiplier Profile (bucketed)
4. Hit and Payout Experience
5. Streak Experience
6. Payline Contribution
7. Symbol Frequency (overall + by reel/column)
8. Bankruptcy Curve (multiple bankroll levels)
9. Key Risks and Action Notes

## 3) Sampling Quality Gate

Minimum quality gate for report-grade output:

1. CI half-width target reached (default: <= 0.5pp).
2. Total spins should usually be >= 2,000,000.
3. Multiplier buckets and tail metrics must exist.
4. Bankruptcy probe must include at least 3 bankroll multipliers.

If any gate fails, report must be marked `EXPLORATORY` (not final).

## 4) Multiplier Bucket Standard (ret_x = win / bet)

Use this exact bucket schema (11 win-bearing buckets; refined tail per
dashboard revision so `>=100` is not collapsed into one pile). Zero-win
sessions are tracked via `hit_and_payout.zero_win_rate`, not as a
dedicated bucket -- the former `eq0` row was structurally zero across
avg_return_x / rtp_contribution_pp / win_share and only added chart noise.

1. `gt0_lt1`
2. `ge1_lt5`
3. `ge5_lt10`
4. `ge10_lt20`
5. `ge20_lt50`
6. `ge50_lt100`
7. `ge100_lt200`
8. `ge200_lt500`
9. `ge500_lt1000`
10. `ge1000_lt5000`
11. `ge5000`

For each bucket, report:

1. `spin_count`
2. `spin_rate`
3. `avg_return_x_in_bucket`
4. `rtp_contribution_pp`
5. `win_share`

Tail metrics (mandatory):

1. `tail_spin_rate_ge10x`
2. `tail_rtp_contribution_pp_ge10x`
3. `tail_win_share_ge10x`
4. `max_observed_return_x`

## 5) Player-Experience Core Metrics

Must include:

1. `zero_win_rate`
2. `win_hit_rate`
3. `profit_spin_rate`
4. `big_win_x10_rate`
5. `avg_win_when_hit_x`
6. `loss_streak_p50/p90/p95/max`
7. `win_streak_p50/p90/p95/max`

Derived interpretation metrics:

1. `recovery_gap = win_hit_rate - profit_spin_rate`
   - Large gap means many "win but still net-loss" spins.
2. `tail_dependency = tail_rtp_contribution_pp_ge10x / rtp_point_pct`
   - High value means RTP relies heavily on rare big events.
3. `dryness = zero_win_rate + normalized(loss_streak_p95)`
   - Use as qualitative indicator, not a strict numeric score.

## 6) Default Classification Rules

### Volatility Class (practical)

Use combined judgment from `std_return_x`, `zero_win_rate`, `tail_dependency`, `loss_streak_p95`.

1. `Low`:
   - `zero_win_rate < 0.65`
   - `loss_streak_p95 <= 8`
   - `tail_dependency < 0.20`
2. `Medium`:
   - `zero_win_rate 0.65~0.75`
   - `loss_streak_p95 9~12`
   - `tail_dependency 0.20~0.35`
3. `High`:
   - `zero_win_rate 0.75~0.82`
   - `loss_streak_p95 13~18`
   - `tail_dependency 0.35~0.50`
4. `Very High`:
   - `zero_win_rate > 0.82`
   - `loss_streak_p95 > 18`
   - `tail_dependency > 0.50`

### Experience Archetype

1. `Grindy`:
   high `zero_win_rate`, low `big_win_x10_rate`, long loss streaks.
2. `Balanced`:
   moderate `zero_win_rate`, moderate `profit_spin_rate`, no extreme tail dependency.
3. `Boom-Bust`:
   high `zero_win_rate` + high `tail_dependency` + visible `big_win_x10_rate`.

## 7) Payline and Symbol Balance Checks

### Payline checks

1. Top-1 payline RTP contribution share > 20% of total payline contribution:
   flag as concentration risk.
2. Top-3 paylines contribution share > 55%:
   flag as strong line concentration.

### Symbol checks

1. Overall blank-like symbol rate around 45%~55% is common for classic style.
2. If blank-like symbol > 58%, usually expect drier feel.
3. If same symbol rate differs by reel/column > 5pp, flag distribution skew for review.

## 8) Bankruptcy Interpretation (session view)

Use fixed session length (default 500 spins), then check bankroll ladder:

1. `x100` bankroll bust rate:
   - > 25%: high short-session frustration risk
2. `x200` bankroll bust rate:
   - > 10%: medium-high retention risk
3. `x500` bankroll bust rate:
   - > 1%: long-session harshness warning

Also report slope between bankroll points; steep drop indicates bankroll sensitivity.

## 9) Report Alert Rules

Trigger alert when any of these occurs:

1. CI target not reached.
2. `zero_win_rate > 0.80` and `profit_spin_rate < 0.10`.
3. `loss_streak_p95 >= 15`.
4. `tail_dependency >= 0.45`.
5. `x200` bankruptcy rate >= 0.10.
6. Payline concentration or symbol skew flags are hit.

## 10) Required Conclusion Template

Each report conclusion should follow this order:

1. `Data confidence` (CI + sample size)
2. `Player feel` (dryness / burst / streak texture)
3. `RTP structure` (which multiplier region contributes RTP)
4. `Session risk` (bankruptcy curve)
5. `Design action` (what to tune first and expected effect)

## 11) Tuning Priority Map

When player feel is too dry:

1. Increase `gt0_lt1` (small wins) spin share first.
2. Keep `tail_rtp_contribution_pp_ge10x` stable unless targeting volatility shift.

When machine feels too flat:

1. Increase `ge10_lt20` / `ge20_lt50` tail share moderately.
2. Avoid raising deep-tail (`ge100_lt200` and beyond) share without controlling `zero_win_rate` and streak length.

When session bust is too high:

1. Improve mid bucket (`ge1_lt5`) before extreme tail.
2. Target lower `loss_streak_p95` and lower `x100/x200` bust rates.

