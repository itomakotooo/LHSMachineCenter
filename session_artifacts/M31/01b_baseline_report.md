# M31 Mode 1 — Stage 1b Baseline Report

**Date**: 2026-05-14  
**Analyst**: A (Analyst agent, slot-analyst)  
**Scope**: Mode 1 only (mode-1-first universal scope per ONBOARDING_PROCESS.md §1.1)  
**Source data**: 25 chunks, 394,000 paid spins, schema fp `5d02773c069fc396`  
**Summary JSON**: `reports/M31/mode_1/versions/rv_20260514T034512Z_48e77c07/player_impact_summary.json`  
**Script used**: `session_artifacts/M31/scripts/baseline_dump.py`

### Script patches applied (pre-run fixes)

None required. The script ran clean on first execution. However, the symbol-identification in sections 6 and 7 was corrected analytically: the script assumed numeric symbol IDs ("7", "8") but M31 uses string symbol names ("High7", "Wild5x", etc.). All PWDF and asymmetry numbers below use the corrected string-name lookup computed via a supplementary inline script, not the script's hardcoded guesses. This discrepancy is documented for Stage 1c, which will formalize the symbol set.

---

## Section 1: Per-Mode Totals

**Mode 1 only. RTP target: 95.0 pp (universal). Gap: -2.38 pp.**

| Metric | Value |
|---|---|
| RTP (point_pct) | 92.62 pp |
| CI 95% interval | [91.63 pp, 93.61 pp] |
| CI halfwidth | 0.99 pp (target 1.0 pp -- just met) |
| Hit rate (paid rounds) | 13.18% (1 in 7.6 paid rounds) |
| Avg return_x (session-level) | 0.5352x |
| Std return_x | 3.1694x |
| CV (std / avg) | 5.92 |
| Max observed return_x | 160.0x (paid round session-level) |
| Paid spins | 394,000 |
| Bonus spins (free, ST44) | 20,818 |
| Total sessions (session-centric) | 414,818 |

**Notes**:
- RTP is session-centric per `feedback_session_semantics.md`: free-spin wins (ST44, total 154,037,800 credits) are attributed to the triggering paid spin (ST43). Denominator is always paid-spin count x bet.
- ST43 direct wins alone give 53.51 pp; the remaining 39.10 pp comes from free-spin sessions attributed to their triggers.
- CV = 5.92 indicates high volatility relative to avg return -- consistent with a free-spin-heavy structure where most rounds return 0 (86.8% zero-win rate) and infrequent free-spin sessions deliver large payouts.
- Max observed 160x is a single-spin paid-round event (pid=7, Wild10x on all reels producing 160,000 credits at 1000 bet). Free-spin individual spins can reach 200x but those are attributed to the session, not standalone.
- quality_label: EXPLORATORY (CI just met at 394,000 paid spins). Adequate for Stage 1b baseline.

---

## Section 2: Bucket Distribution

**Metric**: `ret_x = session_win / session_bet (paid bet only)` per analyzer multiplier_profile.  
**Denominator**: 394,000 paid rounds. Buckets cover the session-level return-x distribution.

| Bucket | Spin Count | Rate% | RTP Contribution (pp) | Avg Return_x in Bucket |
|---|---|---|---|---|
| gt0_lt1 | 20,835 | 5.2881% | 2.1334 | 0.4034x |
| ge1_lt5 | 17,221 | 4.3708% | 9.8804 | 2.2605x |
| ge5_lt10 | 8,180 | 2.0761% | 12.6951 | 6.1148x |
| ge10_lt20 | 3,994 | 1.0137% | 13.1241 | 12.9467x |
| ge20_lt50 | 1,464 | 0.3716% | 10.8646 | 29.2393x |
| ge50_lt100 | 211 | 0.0536% | 3.5106 | 65.5531x |
| ge100_lt200 | 40 | 0.0102% | 1.3150 | 129.5250x |
| ge200_lt500 | 0 | 0.0000% | 0.0000 | -- |
| ge500_lt1000 | 0 | 0.0000% | 0.0000 | -- |
| ge1000_lt5000 | 0 | 0.0000% | 0.0000 | -- |
| ge5000 | 0 | 0.0000% | 0.0000 | -- |
| **TOTAL (win rounds)** | **51,945** | **13.1840%** | **53.5231** | -- |
| **Zero-win rounds** | 342,055 | 86.8160% | 0.0000 | -- |

**Important caveat**: The analyzer's `multiplier_profile` buckets reflect the NormalFreeSpin feature stream only (paid-round perspective, RTP sum = 53.52 pp). The FreeSpin feature stream (39.10 pp) is reported separately in Section 9. The total RTP 92.62 pp = 53.52 (paid-round buckets) + 39.10 (free-spin attribution).

**Shape observations**:
- RTP is concentrated in the mid-range buckets: ge5_lt10 (12.70 pp) and ge10_lt20 (13.12 pp) together deliver 25.82 pp (48% of the NormalFreeSpin 53.52 pp).
- No paid-round session achieves 200x or above (ge200 buckets are empty). The hard ceiling on paid-round session return is 160x (observed max).
- The distribution is right-tailed but not extreme -- medium-high volatility consistent with CV = 5.92.

---

## Section 3: Per pay_id Breakdown

**Sort order**: RTP contribution descending. Hit rate and cadence are per paid round (denominator = 394,000).

| pay_id | Hit Count | Hit Rate | 1-in-N (paid rounds) | RTP pp | Avg Win when Hit (credits) | Dom. SpinType |
|---|---|---|---|---|---|---|
| 8 | 8,310 | 0.020033 | 49.9 | 28.7281 | 13,621 | ST43 (paid) |
| 7 | 4,110 | 0.009908 | 100.9 | 24.3001 | 23,295 | ST43 (paid) |
| 9 | 6,684 | 0.016113 | 62.1 | 12.2237 | 7,205 | ST43 (paid) |
| 10 | 15,637 | 0.037696 | 26.5 | 7.4831 | 1,886 | ST43 (paid) |
| 4 | 2,371 | 0.005716 | 175.0 | 6.7462 | 11,210 | ST44 (free) |
| 11 | 22,550 | 0.054361 | 18.4 | 4.5892 | 802 | ST43 (paid) |
| 12 | 2,974 | 0.007169 | 139.5 | 3.7741 | 5,000 | ST43 (paid) |
| 5 | 2,882 | 0.006948 | 143.9 | 2.4091 | 3,294 | ST43 (paid) |
| 3 | 865 | 0.002085 | 479.6 | 1.0977 | 5,000 | ST43 (paid) |
| 2 | 124 | 0.000299 | 3,345.3 | 0.4721 | 15,000 | ST43 (paid) |
| 1 | 61 | 0.000147 | 6,800.3 | 0.4645 | 30,000 | ST43 (paid) |
| 6 | 2,052 | 0.004947 | 202.2 | 0.3311 | 636 | ST43 (paid) |
| 666 | 2,974 | 0.007169 | 139.5 | 0.0000 | 0 | ST43 (paid) |
| **TOTAL** | **72,395** | **0.172591** | -- | **92.6190** | -- | -- |

**Preliminary symbol/mechanism notes** (confidence LOW -- formal mapping deferred to Stage 1c):

- **pid=8 (28.73 pp, 50x cadence)**: dominant contributor; avg win 13,621 credits (~13.6x). ST43. The examples show `1bar` on center + multiple wilds. Likely a payline-based bar symbol combination amplified by wild multipliers.
- **pid=7 (24.30 pp, 101x cadence)**: second largest; avg win 23,295 credits (~23.3x). ST43. Examples show `High7` symbol present with Wild10x multiplier combinations (produces 160,000 credit max at 160x). HIGH7 + Wild10x is the top jackpot pathway.
- **pid=9 (12.22 pp, 62x cadence)**: avg win 7,205. ST43. Examples show `3bar` on center row.
- **pid=10 (7.48 pp, most frequent at 26.5x cadence)**: avg win 1,886 credits. ST43. Examples show `2bar` or mixed bar combinations.
- **pid=4 (6.75 pp, 175x cadence)**: dominant SpinType is ST44 (free spin). avg win 11,210 credits. This is the premium free-spin payline outcome.
- **pid=11 (4.59 pp, most-hit at 18.4x cadence)**: avg win 802 credits. ST43. Likely the lowest-tier payline (1bar or mixed low symbol).
- **pid=12 (3.77 pp, 139.5x cadence = same hit count as pid=666)**: avg win exactly 5,000 credits. ST43. Scatter win: exactly 5000 every hit. Co-fires with pid=666 on every trigger.
- **pid=666 (0.00 pp, 139.5x cadence)**: zero-win trigger marker. Always fires together with pid=12. This is the free-spin trigger event. hit_count = 2,974 exactly equals pid=12 hit_count -- confirming they are the same physical event (scatter on all 3 reels fires both: scatter win pid=12 and trigger signal pid=666).
- **pid=3 (1.10 pp, 480x cadence)**: avg win exactly 5,000 credits. ST43. Fixed win of 5000 at medium-rare cadence -- likely a specific symbol combo.
- **pid=2 (0.47 pp, 3345x cadence)**: avg win 15,000 credits. ST43. Jackpot tier below pid=1.
- **pid=1 (0.46 pp, 6800x cadence)**: avg win 30,000 credits. ST43. Top jackpot payline (30x bet). Hit in 61 spins out of 394,000.
- **pid=5 (2.41 pp, 144x cadence)**: avg win 3,294 credits. ST43.
- **pid=6 (0.33 pp, 202x cadence)**: avg win 636 credits. ST43. Lowest-yield payline.

**Note on hit_rate sum**: The sum of all pay_id hit rates (0.172591) exceeds win_hit_rate (0.131840) by 0.040751 (30.9% overage). This is expected: a single round can fire multiple pay_ids simultaneously (e.g., a spin with both a bar payline and a scatter win fires pid=10 + pid=12 + pid=666 in the same round). This is NOT a cross-signal failure.

---

## Section 4: Family RTP Share (Preliminary)

**Grouping basis**: pay_id numeric bands + known trigger semantics. Stage 1c will produce authoritative symbol-to-family mapping. Labels below are PRELIMINARY placeholders.

| Family (Preliminary) | pay_ids | RTP (pp) | Share of Total RTP% |
|---|---|---|---|
| top_jackpot (pid 1,2) | 1, 2 | 0.94 | 1.01% |
| high_pay (pid 3,4,5) | 3, 4, 5 | 10.25 | 11.07% |
| mid_high (pid 7,8) | 7, 8 | 53.03 | 57.25% |
| mid_low (pid 9,10) | 9, 10 | 19.71 | 21.28% |
| low_pay (pid 6,11) | 6, 11 | 4.92 | 5.31% |
| scatter_trigger (pid 12,666) | 12, 666 | 3.77 | 4.07% |
| **TOTAL** | | **92.62** | **100.00%** |

**Key finding**: The mid_high family (pid 7, 8) dominates with 57.25% of all RTP. This is unusual concentration. Stage 1c must resolve whether pid=7 and pid=8 represent distinct symbol families (e.g., "High7 payline" vs "1bar payline") or whether one subsumes the other via wild substitution. The free-spin premium pid=4 (11,210 avg win) sits in high_pay, which means the free-spin mode's most valuable payline is in the 11% family -- notable contrast to the base-game dominance.

**Flagged for Stage 1c**: pid=4 has dominant SpinType ST44 (free spin). Whether "high_pay (pid 3,4,5)" deserves a free-spin sub-family designation depends on the symbol mapping. Leave as-is until Stage 1c.

---

## Section 5: Per-Reel Marginals

**Sample**: All 394,000 paid spins (ST43 only). Computed from center row of `StopSymbolsByCol` (3-element list per reel: [top, center, bottom]). All 3 reels have the same 11-symbol vocabulary.

### Center-row marginals (p_center)

| Symbol | R1 | R2 | R3 | R1-R3 diff |
|---|---|---|---|---|
| blank | 0.3964 | 0.3929 | 0.3575 | +0.0389 |
| 1bar | 0.1873 | 0.1739 | 0.1829 | +0.0044 |
| 2bar | 0.1251 | 0.1160 | 0.1221 | +0.0031 |
| Wild2x | 0.0727 | 0.0671 | 0.0717 | +0.0010 |
| Scatter | 0.0519 | 0.0577 | 0.0514 | +0.0005 |
| Wild3x | 0.0517 | 0.0194 | 0.0513 | +0.0004 |
| 3bar | 0.0417 | 0.0770 | 0.0819 | -0.0402 |
| bell | 0.0314 | 0.0383 | 0.0305 | +0.0009 |
| Wild5x | 0.0211 | 0.0292 | 0.0304 | -0.0093 |
| Wild10x | 0.0106 | 0.0096 | 0.0102 | +0.0004 |
| High7 | 0.0102 | 0.0190 | 0.0102 | -0.0000 |

### Window marginals (p_window = P(symbol appears in any of 3 rows))

Note: p_window can exceed 1.0 when symbol appears in multiple rows of the same spin; blank approaches 1.6x because blank can appear in all 3 rows simultaneously.

| Symbol | R1 | R2 | R3 |
|---|---|---|---|
| blank | 1.6036 | 1.6071 | 1.6425 |
| 1bar | 0.2715 | 0.2501 | 0.2642 |
| 2bar | 0.2291 | 0.2316 | 0.2236 |
| Wild2x | 0.2083 | 0.2107 | 0.1743 |
| Scatter | 0.1866 | 0.2116 | 0.1846 |
| Wild3x | 0.1243 | 0.0862 | 0.1224 |
| 3bar | 0.0943 | 0.1252 | 0.1228 |
| bell | 0.1156 | 0.1145 | 0.1121 |
| Wild5x | 0.0834 | 0.0867 | 0.0715 |
| Wild10x | 0.0315 | 0.0285 | 0.0305 |
| High7 | 0.0517 | 0.0478 | 0.0514 |

**Observations**:
- `blank` is overwhelmingly the densest symbol (0.36-0.40 center-row), consistent with a classic machine design where blank fills the majority of strip positions.
- `1bar` is the most common non-blank symbol at 0.17-0.19 center-row.
- R2 (middle reel) shows notable differences from R1/R3: Wild3x is 0.0194 vs 0.0517/0.0513 (R2 has ~40% the Wild3x density of R1/R3); 3bar is 0.0770 vs 0.0417/0.0819 (R2 richer in 3bar than R1, comparable to R3); High7 is 0.0190 vs 0.0102 on R1/R3 (R2 has ~2x the High7 density).
- These R2 differences are genuine mechanical asymmetries in the reel strip design, not sampling noise at 394k spins.

---

## Section 6: Reel Asymmetry

**Per DESIGN_PHILOSOPHY §12**: R1 should have higher top-symbol density than R_last; blank density should increase from R1 to R_last to create "near-miss illusion" (blanks more frequent at later reels = more partial matches).

### Blank density (center-row, paid spins)

| Reel | p_blank (center) | Rank |
|---|---|---|
| R1 | 0.3964 | Densest blank |
| R2 | 0.3929 | Middle |
| R3 | 0.3575 | Least blank |

**Verdict on blank asymmetry**: R1 blank (0.396) > R3 blank (0.358). Direction is REVERSED relative to the §12 ideal (expected: R1 blank < R_last blank so later reels produce more near-misses). This is a characteristic worth flagging for Stage 4 Designer review -- not a bug, but a design choice that reduces the near-miss density on later reels.

### Top-symbol density (High7, highest-value symbol, center-row)

| Reel | p_High7 (center) |
|---|---|
| R1 | 0.0102 |
| R2 | 0.0190 |
| R3 | 0.0102 |

**Verdict on top-symbol asymmetry**: R1 = R3 = 0.0102; R2 is elevated at 0.019. The pattern is symmetric R1=R3 with a center-reel bump, not the R1 > R_last pattern specified in §12. This suggests M31's reel design uses a symmetric layout with center-reel enrichment rather than a left-to-right declining top-density architecture. Stage 4 Designer note: the §12 convention does not hold here -- this is an existing machine characteristic, not a tuning target for Stage 1b.

### Wild multiplier density (Wild10x, center-row)

| Reel | p_Wild10x (center) |
|---|---|
| R1 | 0.0106 |
| R2 | 0.0096 |
| R3 | 0.0102 |

Roughly uniform across reels for Wild10x. Wild2x/Wild3x show R2 asymmetry (R2 lower for Wild3x at 0.0194 vs 0.0517; R2 higher for Wild2x at comparable levels to R1/R3).

---

## Section 7: Window Visibility (PWDF)

**Per DESIGN_PHILOSOPHY §15.9**: PWDF = p_window / p_center measures how visible a symbol is in the full 3-row window relative to the payline (center row). Numbers only; mechanism classification is Designer's Stage 4 decision.

**Symbols analyzed**: High7, Wild5x, Wild10x, Wild3x, Wild2x (top-value and multiplier symbols).

| Symbol | R1 p_win | R1 p_ctr | R1 PWDF | R2 p_win | R2 p_ctr | R2 PWDF | R3 p_win | R3 p_ctr | R3 PWDF |
|---|---|---|---|---|---|---|---|---|---|
| High7 | 0.0517 | 0.0102 | 5.08 | 0.0478 | 0.0190 | 2.51 | 0.0514 | 0.0102 | 5.04 |
| Wild5x | 0.0834 | 0.0211 | 3.95 | 0.0867 | 0.0292 | 2.97 | 0.0715 | 0.0304 | 2.35 |
| Wild10x | 0.0315 | 0.0106 | 2.99 | 0.0285 | 0.0096 | 2.98 | 0.0305 | 0.0102 | 3.00 |
| Wild3x | 0.1243 | 0.0517 | 2.41 | 0.0862 | 0.0194 | 4.44 | 0.1224 | 0.0513 | 2.39 |
| Wild2x | 0.2083 | 0.0727 | 2.87 | 0.2107 | 0.0671 | 3.14 | 0.1743 | 0.0717 | 2.43 |

**Key observations**:
- **High7** has the highest PWDF on R1 and R3 (5.08, 5.04): it appears in the window approximately 5x more often than on the center payline on those reels. On R2 the ratio drops to 2.51 (R2 has higher center density, so the window ratio is lower).
- **Wild10x** is remarkably consistent: PWDF ~3.0 across all three reels (2.99, 2.98, 3.00). This suggests Wild10x is strip-positioned with very uniform above/below flanking. HIGH confidence that Wild10x has approximately equal top/center/bottom placement.
- **Wild3x** shows a notable R2 spike: PWDF = 4.44 vs 2.41/2.39 on R1/R3. On R2, Wild3x has low center density (0.0194) but moderate window density (0.0862), implying it appears frequently in top/bottom rows on R2 but rarely on the center payline.
- **Wild2x** PWDF ranges 2.43-3.14; moderate visibility enhancement.
- All PWDF values are in the 2-5x range. No symbol has PWDF near 1.0 (which would mean center-row-only placement) or very high (>6x, which would mean almost never on center).

---

## Section 8: Blank-Flank Analysis

**Per DESIGN_PHILOSOPHY §13**: X-Blank-X patterns (same symbol above and below a blank) create near-miss opportunities. Analysis uses the per-spin 3-row window (top, center, bottom) for each reel.

**Method**: For each paid spin, for each reel, when center row = blank, check if top_row == bottom_row (same symbol flanks the blank). This is the window-observable X-blank-X pattern.

**Note**: True strip-level blank-flank requires the static `reel_strips.json` (Stage 2 Implementer artifact). The per-spin window proxy captures whether X-blank-X combinations are visible to the player at each spin -- which is the player-experience-relevant signal. However, it cannot detect strip-level blank-flank clusters (runs of X-blank-X-blank-X on the strip). Stage 2 Implementer must verify §13 strip-level compliance.

| Reel | Blank center appearances | X-blank-X count (top=bot) | Rate |
|---|---|---|---|
| R1 | 156,162 | 0 | 0.0000 |
| R2 | 154,794 | 0 | 0.0000 |
| R3 | 140,839 | 0 | 0.0000 |

**Result**: Zero X-blank-X window instances observed across all 394,000 paid spins.

**Explanation**: In M31's 3-reel window, the center row being blank never coincides with top_row == bottom_row. Two plausible interpretations:

1. The reel strips are designed so that blank positions never have identical symbols both above and below on the visible window (strict blank-flank rule applied at strip level). HIGH confidence this is intentional.
2. The symbol set is rich enough that random coincidence of top==bottom is rare -- but at 394,000 x ~40% blank-center rate = ~155k opportunities, zero coincidences at even a 1% base rate would produce ~1,550 instances. Zero observed is inconsistent with random placement.

**Verdict**: M31 appears to have strict X-Blank-X isolation in the visible window -- i.e., when blank is visible on the center payline, the top and bottom rows never show the same symbol. This is a POSITIVE §13 compliance signal (blank-flanked matching symbols do not appear in the visible window, preventing the "false near-miss" where player sees High7-blank-High7 but blank is on payline).

Stage 2 Implementer should confirm the strip layout enforces this at the design level, not just empirically.

---

## Section 9: Feature Session Bucket

**Feature confirmed applicable** (per upstream_feature_breakdown). M31 has a free-spin bonus triggered by Scatter symbol on all 3 reels simultaneously.

### Trigger mechanics

| Field | Value |
|---|---|
| Trigger pay_id | 666 (SpinType 43, paid spin) |
| Trigger partner pay_id | 12 (scatter win, always co-fires with 666) |
| Trigger hit count | 2,974 |
| Trigger cadence | 1-in-132.5 paid rounds (empirical from rawdata) |
| Analyzer-reported cadence | 1-in-139.5 (based on hit_rate = 0.007169) |
| Note | Minor discrepancy: analyzer hit_rate uses session-level denominator; rawdata count uses spin-level |
| Scatter win per trigger | 5,000 credits exactly (pid=12, avg_win=5000, 100% consistent) |
| Free spins awarded | 7 per trigger (confirmed: all tracked sessions have exactly 7 free spins, sample 5 chunks) |

**Note**: pid=666 hit_count (2,974) == pid=12 hit_count (2,974) exactly. These are the same physical trigger event -- every scatter trigger simultaneously awards the 5000-credit scatter win (pid=12) and sets the free-spin trigger flag (pid=666). Stage 1c should confirm with symbol observation.

### Feature stream RTP contribution

| Feature | Fires | RTP Contribution (pp) | Share of Total Win |
|---|---|---|---|
| NormalFreeSpin (paid rounds, ST43) | 394,000 | 53.52 | 57.79% |
| FreeSpin (free rounds, ST44) | 20,818 | 39.10 | 42.21% |
| **Total** | | **92.62** | **100.00%** |

The FreeSpin feature delivers 42.21% of all machine win from only 5.02% of total rounds (20,818 of 414,818). This is the classic high-volatility free-spin structure.

### Session win distribution (tracker: trigger spin win + all attributed free spin wins)

**Denominator**: 2,974 tracked sessions (= 2,974 trigger events).  
**Bet per paid round**: 1,000 credits.

| Session Return (x = session_win / bet) | Session Count | Rate |
|---|---|---|
| 0x-10x (0 to 10,000 credits) | 328 | 11.03% |
| 10x-50x (10,000 to 50,000 credits) | 1,379 | 46.37% |
| 50x-100x (50,000 to 100,000 credits) | 807 | 27.14% |
| 100x-200x (100,000 to 200,000 credits) | 366 | 12.31% |
| 200x+ (200,000+ credits) | 94 | 3.16% |

| Field | Value |
|---|---|
| Sessions tracked | 2,974 |
| Avg session win | 56,917 credits (56.9x bet) |
| Max session win | 368,000 credits (368x bet) |
| Total session win pool | 169,270,400 credits |
| Session win as RTP contribution | 42.96 pp |
| Analyzer-reported FreeSpin + scatter_trigger RTP | 42.87 pp (39.10 + 3.77) |

The minor difference (42.96 vs 42.87 pp) is due to tracking methodology: the session tracker includes the trigger spin's full WinCredits (which may include wins beyond pid=12 on trigger rounds), while the analyzer strictly separates by pay_id. The 0.09 pp gap is acceptable.

**Distribution shape**: The modal bucket is 10x-50x (46% of sessions). Only 11% of sessions yield less than 10x return, meaning free-spin sessions almost never fail to produce meaningful wins. The 50x+ buckets (42% combined) drive the high CV. No session exceeds 368x, which is consistent with the 7-spin session length and the 200x individual free-spin cap (multiple 200x free spins in one session would be required to reach that ceiling, which is statistically rare).

### FreeSpin bucket distribution (from analyzer, denominator = 20,818 free spins)

| Bucket | Rate | RTP pp |
|---|---|---|
| gt0_lt1 | 4.67% | 0.13 |
| ge1_lt5 | 8.25% | 1.17 |
| ge5_lt10 | 5.55% | 2.02 |
| ge10_lt20 | 7.47% | 5.66 |
| ge20_lt50 | 8.54% | 13.95 |
| ge50_lt100 | 2.75% | 9.89 |
| ge100_lt200 | 0.64% | 4.96 |
| ge200_lt500 | 0.13% | 1.32 |

The free-spin bucket distribution is far richer in the high-end buckets than the paid-spin distribution: 42.2% of free spins produce a meaningful win (vs 13.2% for paid spins), and the ge20_lt50 bucket is the modal win bucket.

---

## Section 10: Cross-Mode Top-Prize Escalation

**N/A -- mode-1-first session. Modes 2/5/7 not yet onboarded. Per ONBOARDING_PROCESS.md §5.M: mark N/A.**

---

## Section 11: Cross-Mode Invariants

**N/A -- mode-1-first session. Only mode 1 is in scope this session. Per ONBOARDING_PROCESS.md §5.M: mark N/A.**

---

## Section 12: Schema Fingerprint

**Reference**: Stage 1a §3 (full schema documentation in `session_artifacts/M31/01a_data_inventory.md`).

| Field | Value |
|---|---|
| Schema fingerprint (sha256[:16]) | `5d02773c069fc396` |
| roundResult field count | 17 |
| Envelope stored fingerprint | `5d02773c069fc396` (match -- CLEAN) |
| Drift vs production analyzer | None -- byte-identical algorithm |
| Status | CLEAN |

The 17-field roundResult schema includes `StopSymbolsByCol` as a list of dash-delimited strings (e.g., `"Wild3x-blank-2bar-"`) rather than numeric IDs. This is M31-specific and differs from machines that use integer symbol IDs (per `feedback_no_hardcode.md`: do not assume numeric symbol semantics from other machines). Stage 1c will produce the authoritative symbol vocabulary.

---

## Chunk 0001 Anomaly Check

**Mandated by Stage 1a §5**: chunk_0001 was collected 2026-04-17 (27 days before the bulk collected 2026-05-14). Different robot configuration (1000 spins x 10 robots vs 2000 x 8). Same (cfg_md5, code_md5).

**Test**: Two-proportion z-test per pay_id, comparing chunk_0001 (10,000 paid spins) vs chunks 2-25 pooled (384,000 paid spins).

| pay_id | Chunk_0001 rate | Chunks_2-25 rate | Z-score |
|---|---|---|---|
| 1 | 0.000000 | 0.000091 | -0.955 |
| 2 | 0.000100 | 0.000195 | -0.678 |
| 3 | 0.001500 | 0.001255 | +0.681 |
| 4 | 0.003100 | 0.002505 | +1.171 |
| 5 | 0.003700 | 0.004872 | -1.667 |
| 6 | 0.003400 | 0.003427 | -0.046 |
| 7 | 0.006300 | 0.005953 | +0.445 |
| 8 | 0.015600 | 0.014318 | +1.064 |
| 9 | 0.012700 | 0.013276 | -0.497 |
| 10 | 0.037300 | 0.035695 | +0.853 |
| 11 | 0.050700 | 0.051651 | -0.424 |
| 12 | 0.007000 | 0.007562 | -0.642 |
| 666 | 0.007000 | 0.007562 | -0.642 |

**Max |z|**: 1.667 (pid=5, z=-1.667).  
**Verdict**: All pay_ids fall within 2-sigma. Max is pid=5 at 1.67 sigma -- the 1-2 sigma range (note only, not a drop flag).

**Chunk 0001 anomaly verdict**: CONSISTENT (|z| < 2 for all pay_ids). chunk_0001 data is statistically compatible with the bulk chunks at the 95% confidence level. No proposal to drop. The 1.67 sigma gap on pid=5 is worth noting for Implementer if pid=5 behavior is found to be time-sensitive in production testing.

---

## Cross-Signal Verification

Mandatory per `feedback_self_verify_output.md`. All checks performed against the live `player_impact_summary.json` + rawdata computation.

| Check | Expected | Observed | Delta | Status |
|---|---|---|---|---|
| sum(pay_id RTP) == summary RTP | 92.61904 pp | 92.61904 pp | 0.00000 pp | PASS |
| sum(pay_id hit_rate) == win_hit_rate | Not expected to match (multi-pid rounds) | 0.172591 vs 0.131840 | +0.040751 overage | NOTE (expected) |
| sum(bucket rates) == win_hit_rate | 0.131840 | 0.131840 | 0.00000 | PASS |
| family RTP share% sums to 100% | 100.00% | 100.00% | 0.00% | PASS |
| any _unattributed / fallback / _other bucket > 0.5% RTP | Should be zero | Zero (per Stage 1a §5.4) | -- | PASS (GREEN) |
| chunk_0001 chi-square divergence | |z| < 2.0 for all pay_ids | max |z| = 1.667 | -- | NOTE (1-2 sigma, note only) |

**Clarification on hit_rate overage**: The sum of per-pay_id hit rates (0.1726) exceeds win_hit_rate (0.1318) because a single paid round can fire multiple pay_ids simultaneously. The win_hit_rate counts a round as "hit" once regardless of how many pay_ids fire. The 30.9% overage implies that on average a round that wins fires ~1.31 pay_ids. This is mechanically consistent with the observed patterns (e.g., scatter trigger always fires both pid=12 and pid=666; some payline rounds fire multiple paylines at once). This is NOT a cross-signal failure.

**Bucket rate vs NormalFreeSpin vs total RTP**: The multiplier_profile buckets sum to 53.52 pp (NormalFreeSpin feature), not 92.62 pp (total). The FreeSpin feature (39.10 pp) is attributed in Section 9 but does not appear in the standard bucket table. This split is correct per the analyzer design and is NOT a cross-signal failure. Total: 53.52 + 39.10 = 92.62 pp -- confirmed.

All four primary cross-signals pass with zero delta. The hit_rate overage is mechanically expected (documented). No fallback buckets. No schema drift. Chunk_0001 is within normal sampling variation.

---

## Summary of Key Findings

1. **RTP gap**: Mode 1 observes 92.62 pp vs 95.0 pp target. Gap = -2.38 pp. The machine's current configuration underperforms the target by 2.38 pp. This is the primary tuning objective.

2. **Free-spin dominance**: 42.21% of total machine win comes from free-spin rounds (20,818 ST44 rounds). 7 free spins per trigger, triggered 1-in-132.5 paid rounds. Free-spin sessions have avg 56.9x return, up to 368x max. The free-spin contribution (39.10 pp) is critical to the machine's overall RTP.

3. **Mid-high family concentration**: pid=7 + pid=8 together contribute 53.03 pp = 57.25% of all RTP. These two pay_ids alone define the machine's RTP profile more than all others combined.

4. **Reel asymmetry diverges from §12**: Blank density is higher on R1 than R3 (reversed from the ideal). Top-symbol (High7) density is symmetric (R1=R3) with R2 elevated. M31 uses a symmetric R1=R3 design rather than the declining-density-left-to-right pattern.

5. **Zero X-Blank-X in window**: No X-blank-X window patterns observed in 394,000 spins. This appears to be a deliberate strip design choice ensuring blank never appears with identical flanking symbols visible to the player -- positive §13 compliance.
