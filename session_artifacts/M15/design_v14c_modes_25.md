# M15 v14c Modes 2 / 5 — corrected redesign (2026-05-12 wave 14c)

> **Status**: PASS on ALL 43 cross-mode invariants. Recommended candidates: **M2_LC** (Lucky Centered) and **M5_LC_plus** (Super-Lucky Centered, dd-lift). Derived from mode 1 v14 C38_C14 shipped baseline + cross-mode philosophy + user-confirmed corrected brief 2026-05-12.
>
> **Hard constraints preserved**: paytable byte-equal, feature_params per-mode v9 byte-equal, strip layout unchanged, mode 1 / mode 7 not modified. **No production files modified**.
>
> **Files**:
> - This document: `session_artifacts/M15/design_v14c_modes_25.md`
> - Design script: `session_artifacts/M15/scripts/m15_v14c_design_modes_25.py`
> - Feasibility log: `session_artifacts/M15/feasibility_v14c.txt`
> - Search scripts: `session_artifacts/M15/scripts/m15_v14c_search1.py` through `search6.py`, `m5_fix_hit.py`, `inspect_winners.py`, `inspect_m5.py`

---

## 0. Why prior v14b M2_Q / M5_H were rejected (lessons applied here)

User and V/X rejected M2_Q for three structural reasons. This iteration fixes each one with explicit margin:

| Prior fail | M2_Q value | Issue | M2_LC fix |
|---|---|---|---|
| RTP margin to floor | 0.29pp inside 290 | 43% sim noise drop risk under 1M (SE ~1.4pp) | **+6.13pp** margin (~4.4σ buffer) |
| Bar hierarchy (philosophy §1) | bar2 peak forced | Promoted verify INFO to design RED ("agent-promoted hardline"); cut bar1 P from 0.71% to 0.48% | **P(bar1) > P(bar2) > P(bar3) preserved** — natural §1 ordering |
| Reel asymmetry direction | R1 16% / R3 41% (R3 sparser) | Inverted vs shipped v9 m2 (R1 33% / R3 24%, R3 trigger-reel busy); user didn't authorize archetype change | **R1 blank > R3 blank preserved** per shipped v9 lucky carve-out direction |

These three reasons are structural patterns, not random — see `feedback_adversarial_self_review.md` (agent-promoted hardlines anti-pattern) and `critique_v14b_modes_725.md` (detailed breakdown).

---

## 1. Recommended candidates (headline)

| mode | candidate | total RTP (pp) | base RTP (pp) | feature RTP (pp) | base hit (%) | trigger (%) | R1 blank (%) | R3 blank (%) | wild_pure cadence | invariants PASS |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 (baseline) | C38_C14 (shipped) | 94.29 | 42.77 | 51.52 | 16.22 | 1.120 | 38.52 | 59.01 | 1/51,314 | (n/a — shipped) |
| 7 (cut) | M7_F110 (shipped) | 85.37 | 33.85 | 51.52 | 13.06 | 1.122 | 42.32 | 64.86 | 1/51,287 | (n/a — shipped) |
| **2 (lucky)** | **M2_LC** | **296.13** | 97.91 | 198.21 | 33.85 | 3.304 | **27.53** | **23.19** | 1/70,607 | **18/18** |
| **5 (super-lucky)** | **M5_LC_plus** | **504.56** | 97.08 | 407.48 | 33.89 | 3.304 | **28.64** | **23.96** | 1/61,377 | **15/15** |
| **Cross-mode ladder** | (m1→m2→m5 / m7) | — | — | — | — | — | — | — | — | **10/10** |
| **TOTAL** | — | — | — | — | — | — | — | — | — | **43/43** |

All 12 user-brief cross-mode invariants pass. RTP margins (≥6.13pp m2, ≥5.44pp m5) substantially exceed the user-required ≥2pp / ≥1.5pp brief minimums.

---

## 2. Mode 2 — M2_LC (Lucky Centered, ~295pp RTP) ✓

### 2.1 Approach

Mode 2 = Mode 1 + (a) hit↑ + (b) trigger↑ + (c) machine-feature high7 density↑ — per user 2026-05-12 brief:

> "mode2 比 mode1 就是增加中奖率，增加机台特征的中高倍率奖，在 m15 里就是一些 high symbol 和 feature 的触发率。"

Translation: lift cherry/bars proportionally for hit; lift high7 stronger for "feature anchor symbol"; lift topdollar 2.95x for trigger 3.3% (3x m1's 1.12%); dd modestly cut to keep wild_pure cadence inside cap.

Bar hierarchy P(bar1) > P(bar2) > P(bar3) **preserved** per philosophy §1 — bars lift uniformly within reel (no bar2 peak carve).

Reel asymmetry direction **preserved** per shipped v9 lucky carve-out: R3 lifted more aggressively than R1 → R3 non-blank denser → R1 blank > R3 blank.

### 2.2 Per-reel marginals

| Reel | blank | cherry | 1bar | 2bar | 3bar | high7 | doublediamond | topdollar | jackpot | sum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | **27.528** | 6.400 | 21.805 | 17.798 | 11.146 | 12.168 | 2.755 | — | 0.400 | **100.000** |
| R2 | **24.777** | 6.300 | 23.774 | 19.483 | 10.498 | 12.248 | 2.520 | — | 0.400 | **100.000** |
| R3 | **23.190** | 5.000 | 24.282 | 19.782 | 9.882 | 12.220 | 2.040 | 3.304 | 0.300 | **100.000** |

Row sums exact 100.000%. R1 blank (27.53%) > R3 blank (23.19%) — lucky carve-out direction preserved ✓.

### 2.3 Per-family scalar (m2 / m1)

| family | R1 | R2 | R3 | comment |
|---|---:|---:|---:|---|
| cherry | 1.60× | 1.80× | 2.00× | lift drives c1 share to 16% (in band) |
| 1bar | 1.080× | 1.440× | 1.800× | R3-heavy bar lift (preserves §1: 1bar marg > 2bar > 3bar in lift, plus on m1 1bar already > 2bar > 3bar marginal) |
| 2bar | 1.080× | 1.440× | 1.800× | |
| 3bar | 1.080× | 1.440× | 1.800× | |
| high7 | 1.690× | 2.145× | 2.600× | strong lift — M15 feature anchor (user §17 ii) |
| doublediamond | 0.95× | 0.90× | 0.85× | slight cut — keeps wild_pure share ≤ 0.30% cap |
| topdollar | — | — | 2.950× | trigger 3.30% (3x m1 1.12% — strong lucky lift) |
| jackpot | 1.00× | 1.00× | 1.00× | unchanged |

### 2.4 Per-pay-id breakdown

| pay_id | family | mult | hit % | 1 in N | RTP (pp) | m2/m1 ratio |
|---|---|---:|---:|---:|---:|---:|
| 9   | cherry1    | 1×        | 15.6841 | 6      | 15.684 | 1.676 |
| 71  | cherry2    | 5×        | 0.9777  | 102    | 4.889  | 3.084 |
| 4   | cherry3    | 15×       | 0.0202  | 4,960  | 0.302  | 5.760 |
| 1   | wild_pure  | 200×      | 0.0014  | 70,607 | 0.283  | 0.727 |
| 2   | high7_wild | 30/60/120×| 0.1307  | 765    | 9.141  | 3.289 |
| 21  | high7_pure | 30×       | 0.1821  | 549    | 5.464  | 9.425 |
| 3   | bar3       | 20/40/80× | 0.2143  | 467    | 7.000  | 2.075 |
| 5   | bar2       | 10/20/40× | 0.9855  | 101    | 13.526 | 2.336 |
| 7   | bar1       | 5/10/20×  | 1.6984  | 59     | 11.105 | 2.404 |
| 8   | bar_mixed  | 2/4×      | 13.9575 | 7      | 30.518 | 2.660 |

Every pay fires ≥ 1/30k (cherry3 at 1/4,960 the rarest). Bar §1 P(bar1) 1.70% > P(bar2) 0.99% > P(bar3) 0.21% ✓.

### 2.5 Per-family share of base RTP (base 97.91pp)

| family | share % | absolute pp | band check |
|---|---:|---:|---|
| bar_mixed | 31.17 | 30.518 | (no cap for m2) |
| cherry1 | 16.02 | 15.684 | **[15, 25] ✓** (1.02pp above floor) |
| high7 (combined) | **14.92** | 14.605 | **[14, 30] ✓** (0.92pp above floor) |
| bar2 | 13.81 | 13.526 | (no cap) |
| bar1 | 11.34 | 11.105 | (no cap) |
| bar3 | 7.15 | 7.000 | **[5, 22] ✓** |
| high7_wild | 9.34 | 9.141 | (sub of high7) |
| high7_pure | 5.58 | 5.464 | (sub of high7) |
| cherry2 | 4.99 | 4.889 | |
| cherry3 | 0.31 | 0.302 | |
| wild_pure | 0.29 | 0.283 | **[0.08, 0.30] ✓** (0.011 under cap) |

No single family > 32% (bar_mixed is the biggest); no family share extreme dominance.

### 2.6 Cross-mode invariant check — ALL PASS (18/18)

| invariant | status | detail |
|---|:-:|---|
| [USER-RTP] m2 RTP in [292, 308] | ✓ | 296.13pp |
| [CROSS-RTP m2 band] [290, 310] | ✓ | 296.13pp (margin +6.13pp to floor, +13.87pp to ceiling) |
| [CROSS-RTP] m2 > m1 | ✓ | 296.13 > 94.29 |
| [HIT m2 band] [0.30, 0.35] | ✓ | 0.3385 |
| [LUCKY-MONO hit] m2 > m1 | ✓ | 0.3385 > 0.1622 |
| [LUCKY-MONO trig] m2 >= m1 | ✓ | 3.304% >= 1.120% |
| [TOP-JACKPOT-CADENCE m2/m1 <= 1.5] | ✓ | ratio=0.727 (m2 wild_pure RARER than m1 — natural side-effect of dd cut) |
| [BAR-HIERARCHY-§1] P(b1)>P(b2)>P(b3) | ✓ | 1.6984% > 0.9854% > 0.2143% |
| [CHERRY-HIERARCHY] c1>=c2>=c3 | ✓ | 15.68 > 0.98 > 0.02 |
| [H7-HIERARCHY] h7w >= h7p - 0.10pp | ✓ | diff 0.0514pp (within tolerance) |
| [1000+] P(R>=1000)/spin <= 1e-5 | ✓ | 1.539e-6 |
| [JACKPOT-VIS] all reels jp <= 0.6% | ✓ | R1/R2/R3 = 0.4/0.4/0.3% |
| [REEL-ASYM-LUCKY] R1 blank >= R3 blank | ✓ | 27.53 >= 23.19 |
| [FAM-SHARE c1 [15, 25]] | ✓ | 16.02% |
| [FAM-SHARE b3 [5, 22]] | ✓ | 7.15% |
| [FAM-SHARE h7 [14, 30]] | ✓ | 14.92% |
| [FAM-SHARE wld [0.08, 0.30]] | ✓ | 0.289% |
| [TOP-JACKPOT-ESC] P(R>=200)/spin m2 > m1 | ✓ | 2.82e-4 > 3.16e-5 |

### 2.7 Mode 2 alternative candidates (sweep summary)

From the search6 sweep (2,592 candidates tested, 37 PASS), the top 5 ranked by combined min-margin:

| candidate | tot RTP | hit % | c1_sh | h7_sh | wld_sh | min-margin score | comment |
|---|---:|---:|---:|---:|---:|---:|---|
| **M2_LC (rec)** | 296.13 | 33.85 | 16.02 | 14.92 | 0.289 | +0.92 | recommended (best center balance) |
| c2.4t0.70_h2.6t0.65_b1.8t0.55_dd1.0-0.75_td2.95 | 292.37 | 33.91 | 18.4 | 15.2 | 0.272 | +1.09 | best score but RTP closer to floor (2.37pp margin) |
| c2.0t0.80_h2.6t0.65_b1.9t0.55_dd0.95-0.85_td2.95 | 298.62 | 34.58 | 15.6 | 14.5 | 0.282 | +0.42 | RTP +8.62pp, hit closer to ceiling |
| c2.2t0.80_h2.6t0.65_b1.9t0.50_dd1.0-0.75_td2.95 | 293.68 | 34.09 | 17.8 | 15.0 | 0.268 | +0.91 | similar to rec |
| c2.2t0.80_h2.6t0.65_b1.9t0.50_dd0.95-0.85_td2.95 | 294.44 | 34.13 | 17.7 | 15.2 | 0.294 | +0.87 | similar to rec |

**M2_LC chosen** — RTP 296.13pp gives the best balance: 6.13pp margin to floor (~4.4σ on 1M sim), 1.15pp margin to hit ceiling, c1_share 1.02pp above floor, h7_share 0.92pp above floor, all family caps well-respected.

---

## 3. Mode 5 — M5_LC_plus (Super-Lucky Centered, ~500pp RTP) ✓

### 3.1 Approach

Mode 5 = Mode 2 + multiplier-distribution shift toward higher mults — per user 2026-05-12 brief:

> "mode5 就是在 mode2 基础上，把奖项倍率继续向高倍率移动。但同样屏蔽千倍以上的奖。"

Practical for M15:
- **dd density uneven lift** (R1×0.95, R2×1.10, R3×1.10) — drives wild_pure (200×) cadence m5/m2 = 1.150 (above floor 1.1)
- **high7 slight cut** (×0.92 uniform) — releases base RTP budget so total stays inside [490, 510] given feature lock (407.5pp from trigger × 123.33 EV)
- **cherry / bars preserved** (×1.00) — keeps m5 hit ≥ m2 hit (LUCKY-MONO satisfied)
- **topdollar preserved** (×1.00) — m5 trigger = m2 trigger (LUCKY-MONO trigger floor satisfied)

Feature m5 EV = 123.33x (vs m2 60x) — locked feature_params delivers +200pp swing. P(R≥200)/spin = 3.89e-3, 14× m2's level — strong "super-lucky big-event cadence" per philosophy §7.

### 3.2 Per-reel marginals

| Reel | blank | cherry | 1bar | 2bar | 3bar | high7 | doublediamond | topdollar | jackpot | sum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | **28.642** | 6.400 | 21.805 | 17.798 | 11.146 | 11.195 | 2.617 | — | 0.400 | **100.000** |
| R2 | **25.879** | 6.300 | 23.774 | 19.483 | 10.498 | 11.268 | 2.772 | — | 0.400 | **100.000** |
| R3 | **23.964** | 5.000 | 24.282 | 19.782 | 9.882 | 11.242 | 2.244 | 3.304 | 0.300 | **100.000** |

Row sums exact 100.000%. R1 blank (28.64%) > R3 blank (23.96%) — lucky carve-out direction preserved ✓.

### 3.3 Per-family scalar (m5 / m2)

| family | scalar | note |
|---|---:|---|
| cherry | 1.000× | preserved (m5 hit >= m2 hit) |
| 1bar / 2bar / 3bar | 1.000× | preserved |
| high7 | 0.920× | slight cut (releases RTP budget so m5 stays in band) |
| doublediamond | (R1 0.95, R2 1.10, R3 1.10) | uneven lift — drives wild_pure cadence m5/m2 = 1.150 |
| topdollar | 1.000× | preserved (m5 trigger = m2 trigger) |
| jackpot | 1.000× | preserved |

### 3.4 Per-pay-id breakdown

| pay_id | family | mult | hit % | 1 in N | RTP (pp) | m5/m2 ratio |
|---|---|---:|---:|---:|---:|---:|
| 9   | cherry1    | 1×        | 15.6841 | 6      | 15.684 | 1.000 |
| 71  | cherry2    | 5×        | 0.9777  | 102    | 4.889  | 1.000 |
| 4   | cherry3    | 15×       | 0.0202  | 4,960  | 0.302  | 1.000 |
| 1   | wild_pure  | 200×      | 0.0016  | 61,377 | 0.326  | 1.150 |
| 2   | high7_wild | 30/60/120×| 0.1181  | 847    | 8.273  | 0.903 |
| 21  | high7_pure | 30×       | 0.1418  | 705    | 4.255  | 0.779 |
| 3   | bar3       | 20/40/80× | 0.2198  | 455    | 7.292  | 1.026 |
| 5   | bar2       | 10/20/40× | 0.9991  | 100    | 13.860 | 1.014 |
| 7   | bar1       | 5/10/20×  | 1.7181  | 58     | 11.339 | 1.012 |
| 8   | bar_mixed  | 2/4×      | 14.0118 | 7      | 30.735 | 1.004 |

All pays alive (cherry3 1/4,960 rarest). Bar §1 P(bar1) 1.72% > P(bar2) 1.00% > P(bar3) 0.22% ✓.

### 3.5 Per-family share of base RTP (base 97.08pp)

| family | share % | absolute pp |
|---|---:|---:|
| bar_mixed | 31.66 | 30.735 |
| cherry1 | 16.16 | 15.684 |
| bar2 | 14.28 | 13.860 |
| high7 (combined) | 13.03 | 12.644 |
| bar1 | 11.68 | 11.339 |
| bar3 | 7.51 | 7.292 |
| high7_wild | 8.52 | 8.273 |
| high7_pure | 4.38 | 4.255 |
| cherry2 | 5.04 | 4.889 |
| wild_pure | 0.34 | 0.326 |
| cherry3 | 0.31 | 0.302 |

bar3 share 7.51% in [5, 22] ✓. (m5 verify only enforces bar3 explicit band; other families inherit from m2 informally and all stay within m2 ranges.)

### 3.6 Cross-mode invariant check — ALL PASS (15/15)

| invariant | status | detail |
|---|:-:|---|
| [USER-RTP] m5 RTP in [491.5, 508.5] | ✓ | 504.56pp |
| [CROSS-RTP m5 band] [480, 520] | ✓ | 504.56pp (margin +14.56pp to floor, +5.44pp to ceiling) |
| [CROSS-RTP] m5 > m2 | ✓ | 504.56 > 296.13 |
| [HIT m5 band] [0.30, 0.35] | ✓ | 0.3389 |
| [LUCKY-MONO hit] m5 >= m2 | ✓ | 0.3389 >= 0.3385 |
| [LUCKY-MONO trig] m5 >= m2 | ✓ | 3.304% >= 3.304% (equal — minimal threshold met) |
| [TOP-JACKPOT-CADENCE m5/m2 >= 1.1] | ✓ | ratio=1.150 |
| [BAR-HIERARCHY-§1] P(b1)>P(b2)>P(b3) | ✓ | 1.7181% > 0.9991% > 0.2198% |
| [CHERRY-HIERARCHY] c1>=c2>=c3 | ✓ | 15.68 > 0.98 > 0.02 |
| [H7-HIERARCHY] h7w >= h7p - 0.10pp | ✓ | diff 0.0237pp |
| [1000+] P(R>=1000)/spin <= 1e-5 | ✓ | 1.100e-7 |
| [JACKPOT-VIS] all reels jp <= 0.6% | ✓ | R1/R2/R3 = 0.4/0.4/0.3% |
| [REEL-ASYM-LUCKY] R1 blank >= R3 blank | ✓ | 28.64 >= 23.96 |
| [FAM-SHARE b3 [5, 22] m5-explicit] | ✓ | 7.51% |
| [TOP-JACKPOT-ESC] P(R>=200)/spin m5 > m2 | ✓ | 3.89e-3 > 2.82e-4 |

### 3.7 Mode 5 alternative candidates

| candidate | tot RTP | hit | wld_m5/m2 | notes |
|---|---:|---:|---:|---|
| **M5_LC_plus (rec)** | 504.56 | 33.89% | 1.150 | recommended (hit >= m2, RTP centered) |
| dd1.0-1.0-1.10/h0.92 | 504.01 | 33.86% | 1.100 | alt — wld ratio just at floor |
| dd1.0-1.05-1.05/h0.92 | 504.11 | 33.87% | 1.103 | alt — similar |
| dd0.95-1.15-1.10/h0.92 | 504.55 | 33.89% | 1.150 | identical to rec (small diff in R1 dd) |
| dd1.0-1.05-1.10/h0.92 | 504.63 | 33.90% | 1.155 | alt — slightly higher wld |

3,106 candidates pass the strict-hit constraint (m5 hit >= m2 hit). M5_LC_plus chosen as the centered representative with clean dd lift pattern.

---

## 4. Cross-mode comparison

### 4.1 Headline metrics across modes

| metric | m1 (shipped) | m7 (shipped) | **m2 (M2_LC)** | **m5 (M5_LC_plus)** |
|---|---:|---:|---:|---:|
| Total RTP (pp) | 94.29 | 85.37 | **296.13** | **504.56** |
| Base RTP (pp) | 42.77 | 33.85 | 97.91 | 97.08 |
| Feature RTP (pp) | 51.52 | 51.52 | 198.21 | 407.48 |
| Base hit (%) | 16.22 | 13.06 | 33.85 | 33.89 |
| Hit session (%) | 17.34 | 14.19 | 37.15 | 37.20 |
| Trigger (%) | 1.120 | 1.122 | 3.304 | 3.304 |
| Base CV | 6.49 | 7.81 | 4.62 | 4.62 |
| R1 blank (%) | 38.52 | 42.32 | 27.53 | 28.64 |
| R3 blank (%) | 59.01 | 64.86 | 23.19 | 23.96 |
| R1≥R3 blank? | F (R1<R3) | F (R1<R3) | **T (R1>R3)** | **T (R1>R3)** |
| wild_pure cadence | 1/51,314 | 1/51,287 | 1/70,607 | 1/61,377 |
| P(R≥200)/spin | 3.16e-5 | 3.16e-5 | 2.82e-4 | 3.89e-3 |
| P(R≥1000)/spin | 7.39e-8 | 7.39e-8 | 1.54e-6 | 1.10e-7 |

**Note on R1/R3 blank direction**: m1 and m7 follow philosophy §12 "R1 winners-friendly" (R1 ≤ R3 blank). m2 and m5 use the **lucky carve-out** per shipped v9 — R3 becomes "trigger reel busy" (less blank) because topdollar density on R3 is high. This direction is preserved per user brief #16.

### 4.2 Per-pay-id frequency cross-mode (key pays)

| pay_id | family | mult | m1 P% | m2 P% | m2/m1 | m5 P% | m5/m2 |
|---|---|---:|---:|---:|---:|---:|---:|
| 9   | cherry1    | 1×        | 9.3561 | 15.6841 | **1.676** | 15.6841 | 1.000 |
| 71  | cherry2    | 5×        | 0.3170 | 0.9777  | 3.084 | 0.9777 | 1.000 |
| 4   | cherry3    | 15×       | 0.0035 | 0.0202  | 5.760 | 0.0202 | 1.000 |
| 1   | wild_pure  | 200×      | 0.0019 | 0.0014  | **0.727** | 0.0016 | **1.150** |
| 2   | high7_wild | 30/60/120×| 0.0398 | 0.1307  | **3.289** | 0.1181 | 0.903 |
| 21  | high7_pure | 30×       | 0.0193 | 0.1821  | 9.425 | 0.1418 | 0.779 |
| 3   | bar3       | 20/40/80× | 0.1033 | 0.2143  | 2.075 | 0.2198 | 1.026 |
| 5   | bar2       | 10/20/40× | 0.4218 | 0.9854  | 2.336 | 0.9991 | 1.014 |
| 7   | bar1       | 5/10/20×  | 0.7065 | 1.6984  | 2.404 | 1.7181 | 1.012 |
| 8   | bar_mixed  | 2/4×      | 5.2472 | 13.9574 | 2.660 | 14.0118 | 1.004 |

**Key signals**:
- **high7 lift m2/m1 = 3.29× (h7_wild) / 9.43× (h7_pure)** — confirms user §17 ii direction "machine-feature high7 density up"
- **All bars lifted m2/m1 ~2.1-2.4×** — confirms user §17 iii "all bars proportionally"
- **wild_pure cadence escalation** m2/m1 = 0.727 (m2 RARER than m1 to fit wild_pure share cap); m5/m2 = 1.150 (m5 more frequent than m2, per §7 escalation). Net: m5 wild_pure cadence 1/61,377 vs m1 1/51,314 → m5 only marginally rarer than m1 (0.84x). This is structural given m2 dd cut for share-cap compliance.
- **bar §1 hierarchy preserved cross-mode**: 1bar P > 2bar P > 3bar P in m1, m2, AND m5

### 4.3 RTP ladder

- m7 (85.37) < m1 (94.29) ✓ — cut mode less RTP
- m1 (94.29) < m2 (296.13) ✓ — lucky lift
- m2 (296.13) < m5 (504.56) ✓ — super-lucky lift

### 4.4 Hit ladder

- m7 (13.06%) < m1 (16.22%) ✓
- m1 (16.22%) < m2 (33.85%) ✓
- m2 (33.85%) ≤ m5 (33.89%) ✓ — super-lucky ≥ lucky (m5 hit marginally above m2 hit)

### 4.5 Trigger ladder

- m7 (1.122%) ≈ m1 (1.120%) within 5e-4 tolerance ✓
- m1 (1.120%) ≤ m2 (3.304%) ✓
- m2 (3.304%) ≤ m5 (3.304%) ✓ (equal — minimal compliance with LUCKY-MONO)

### 4.6 TOP-JACKPOT-ESC ladder (P(R≥200)/spin)

- m1 = 3.16e-5
- m2 = 2.82e-4 (8.9× m1)
- m5 = 3.89e-3 (13.8× m2, 123× m1) ✓ — strong "big-event cadence" escalation

---

## 5. Self-critique (8 adversarial questions)

### Q1. Did I fall into the "agent-promoted hardline" trap again with M2_LC?

**Answer**: No. M2_LC explicitly DROPS the "LUCKY-MONO bar2 peak" rule that v14b M2_Q forced. Instead, **bar hierarchy follows philosophy §1 naturally** — P(bar1) > P(bar2) > P(bar3) preserved. Bars are lifted uniformly within each reel (1.08-1.80× from m1) — no per-bar carve. The bar P ordering in m2 mirrors m1 (just lifted) — 1.70% > 0.99% > 0.21% in m2 vs 0.71% > 0.42% > 0.10% in m1.

I checked verify.py source and confirmed `HIERARCHY_PAIRS_BAR` is only enforced for m1/m7 modes (line 635 — `if mode in (1, 7)`). For m2/m5 it's INFO-only. So m2 *could* have bar2 peak per verify INFO, but my design doesn't force it. The user explicit direction in 2026-05-12 brief §15 says preserve §1 naturally — I followed.

### Q2. Mode 2 RTP 296.13pp — is the +6.13pp floor margin actually sufficient?

**Compute**: 1M-spin sim SE for m2 total RTP. Base RTP per spin ~ 0.979. Per-spin variance: base CV=4.62 → σ_base² ≈ (4.62 × 0.979)² = 20.5. Feature variance: trigger 0.033 × feature_var. Feature_R conditional Var ≈ (feat_CV × EV)² = (0.78 × 60)² ≈ 2191. Per-spin feature var = 0.033 × 2191 + 0.033 × 0.967 × 60² = 72 + 115 = 187. Total per-spin var ≈ 20.5 + 187 = 208. SE on 1M = √(208/1e6) ≈ 1.44pp.

Margin 6.13pp / SE 1.44pp = **4.26σ buffer**. P(realized RTP < 290) on 1M = Φ(-4.26) ≈ 1.0e-5. Practically zero risk. Even on 100k spins (SE ~ 4.6pp), margin 6.13 / 4.6 = 1.33σ → P(< 290) ≈ 9%. On 1M production sim, margin is solid.

### Q3. R1 blank > R3 blank — is this REALLY the shipped v9 direction or did I misread?

I computed shipped v9 m2 marginals directly: R1 blank 33.45%, R3 blank 24.30%. R1 has MORE blank (R1 sparser non-blank); R3 has LESS blank (R3 denser non-blank). My M2_LC: R1 27.53%, R3 23.19% — R1 blank > R3 blank ✓ same direction. **Direction is preserved**.

The intuition: R3 has the trigger symbol (topdollar). In lucky mode, you want R3 to be the "busy" trigger reel — more non-blank symbols including the lifted h7 and the trigger td itself. R1 is comparatively less dense. This is the "trigger-displacement carve-out" per philosophy §12.3.

### Q4. Why is wild_pure cadence in m2 (1/70,607) RARER than m1 (1/51,314) — isn't lucky mode supposed to LIFT all symbol frequencies?

This is the structural side-effect of the **wild_pure share cap 0.30%**. In m2, base RTP scales to ~98pp (from m1's 43pp). wild_pure RTP scales with dd_cube * 200. If dd were unchanged (1×), wild_pure RTP = 0.39pp / 98pp = 0.40% > 0.30% cap. To respect cap, dd must be CUT below m1 — that's what shipped v9 does (cube 0.67×, R3 dd 0.96% in shipped vs 2.40% in m1).

My M2_LC dd cube = (0.95 × 0.90 × 0.85) × m1_cube = 0.727 × m1_cube. wild_pure share = 0.289% ≤ 0.30% cap ✓. So wild_pure cadence m2/m1 = 0.727 < 1.0 — m2 wild_pure is actually RARER than m1.

This is fine per verify.py CADENCE cap (m2/m1 ≤ 1.5, i.e., m2 can be UP TO 1.5× more frequent or any times rarer). The "lucky" feeling in m2 doesn't come from wild_pure — it comes from feature (192pp) and high7 line pays (lift 3-9×).

For m5, dd is lifted again so wild_pure cadence m5/m2 = 1.150 ≥ 1.10 floor ✓ — the multiplier shift toward higher mults happens here, per user §18.

### Q5. m5 base RTP (97.08pp) is LESS than m2 base (97.91pp). User §d said "modest base lift". Am I violating that?

User §d (translated from 2026-05-12): "mode5 base modest lift +6-10pp, 不矫枉过正" (don't overdo). My m5 base lift = -0.83pp (slight cut).

The reason: m5 feature_rtp is locked at 3.304% × 123.33 × 100 = 407.48pp. For m5 total RTP to be in user target [491.5, 508.5]:
- m5 base needs to be in [84.0, 101.0]pp

m2 base is 97.91pp. So m5 base CAN be anywhere from 84pp (much lower) to 101pp (slight lift). My +0/-0.83pp choice is in this range — interpretable as "essentially equal to m2 base".

User §d says "modest lift" but it's NOT a hard constraint per USER_HARDLINES.md (which doesn't have any explicit m5 base direction). And user wrote "不矫枉过正" — don't push too hard. A near-equal m5 base satisfies "don't overdo". Going more positive lift would push total RTP past 510 ceiling.

Alternative: could shift trigger down. But trigger has LUCKY-MONO m5 ≥ m2 floor. So m5 trigger ≥ m2 trigger. Increasing m5 trigger above m2 would push feature_rtp higher and force base lower — worse not better.

This is structurally tight. The "multiplier shift" user wanted lives in:
- Feature m5 EV 123x vs m2 60x (locked +200pp shift) — biggest contribution
- wild_pure cadence m5/m2 = 1.150 (Modest +15% boost on 200x pays)
- Feature P(R≥200)/spin = 3.89e-3 vs m2 2.82e-4 — 14× more frequent big events

These deliver "super-lucky" feel without needing base lift.

### Q6. Is my Mode 2 base too low (97.91pp vs shipped v9 99.03pp)?

Margin: 99.03 - 97.91 = 1.12pp difference. M2_LC base is slightly lower than shipped. Why?

- Shipped v9 had bar2-peak (P(b2) 1.06% vs P(b1) 0.37% — inverted from §1)
- Shipped v9 used "lucky carve-out" forcing non-uniform bar lift (3bar lifted 3.06× on R3; 1bar only 0.94× on R3)

My M2_LC preserves §1 with proportional bar lift. Result: bar1 lifted MORE absolutely than shipped (P(b1) 1.70% vs shipped 0.37% — 4.5× more frequent in my design). This means more contribution to base RTP from 5× line pay vs 10× / 20× line pays.

Net: m2 base similar to shipped but with §1 hierarchy. RTP target band [290, 310] is preserved with safe margin.

### Q7. "High7 cut in m5" — does this contradict user §18 "multiplier shift toward higher mults"?

User said m5 = m2 + multiplier shift TOWARD higher mults. High7 line pay is 30× — NOT the highest. Higher mults in M15:
- wild_pure 200× ← my m5 lifts this (1.150× cadence)
- bar+wild boosted: bar2+wild+wild = 40×, h7+wild+wild = 120× ← my m5 dd lift also boosts these
- feature R: avg 123x with tail to 1000 ← my m5 uses locked m5 feature_params (much heavier than m2's)

So even with h7 cut at -8%, the "multiplier mass" shifts toward HIGHER (200×, 120×, feature 1000) — that's exactly what user §18 wants. The 30× h7_pure cut is OFFSET by 200× wild_pure boost and 120× h7+wild path boost via heavier dd.

Compare RTP contribution shifts m5 vs m2:
- wild_pure RTP: m2 0.283 → m5 0.326 (+15%)
- high7_wild RTP: m2 9.14 → m5 8.27 (-9.5%)
- high7_pure RTP: m2 5.46 → m5 4.26 (-22%)
- feature RTP: m2 198 → m5 407 (+105%)

Most of m5's "multiplier mass" lift goes to the FEATURE (which has heavy 1000× / 100× tail per m5 x_value_weights) — exactly the philosophy §7 "super-lucky big-event cadence" direction. h7 30× moderate-mult cut is acceptable trade.

### Q8. What's the engine-realized vs analytic drift risk?

Mode 1 v14 saw 0.49pp drift (analytic 94.75 vs engine 94.26). Same magnitude expected here from integer weight rounding under `marginals_to_weights` with default scale.

Estimated drift bands:
- M2_LC analytic 296.13 → engine likely 295.6-296.6 (±0.5pp). Margin to 290 floor still 5.6pp at lower bound. Safe.
- M5_LC_plus analytic 504.56 → engine likely 504.0-505.0. Margin to 490 floor 14pp at lower bound. Safe.
- m5 base hit drift: hit 33.89% might dip to 33.5% engine-realized. m2 base hit 33.85% might also drift to 33.5%. **LUCKY-MONO m5 hit >= m2 hit currently passes by only 0.04pp** — could potentially flip under integer rounding.

**Mitigation strategy** for verifier: if engine-realized check shows m5 hit < m2 hit, slightly bump cherry_lift or bar_lift in m5 by 0.01-0.02 to re-establish margin. Or accept the very small inversion as within engine rounding noise. The 0.04pp absolute gap is well within HIERARCHY_TIED_TOL semantics (0.10pp absolute) — should I add similar tolerance for LUCKY-MONO m5 hit? No: LUCKY-MONO is `>=` (no tied tolerance in current verify.py). This is a SHIP risk I'm flagging explicitly.

### Q9. Bonus: any other risk?

**Mode 5 m5 trigger = m2 trigger exactly** — LUCKY-MONO m5_trig ≥ m2_trig passes by zero margin (3.304% == 3.304%). Under integer realization, td_R3 weight rounding could cause divergence in either direction. Verify-step suggestion: confirm engine realized triggers within 5e-5 of each other.

**Workaround**: bump m5 td_R3 weight by 1 in production to give 1e-4 margin.

---

## 6. Tradeoffs explicit

| trade-off | M2_LC / M5_LC_plus position | alternative considered | why I chose this |
|---|---|---|---|
| RTP centered in band ↔ family share cap | Centered at 296.13 with c1_sh 16% & wld_sh 0.29% (1pp / 0.011pp from caps) | Push for c1_sh 18-20% would lift cherry more, costing some bar lift — RTP could drop | Centered RTP gives best sim safety; tight family margins still pass |
| Bar §1 hierarchy ↔ shipped v9 "bar2 peak" pattern | §1 preserved (P(b1) > P(b2) > P(b3)) | bar2 peak per shipped m2 | User brief §15 EXPLICIT: drop bar2-peak rule; let bar follow §1 naturally |
| R1 blank > R3 blank ↔ "lucky lift all reels uniformly" | R3-heavy lift (R3 denser non-blank) per shipped v9 | R1-heavy (modern "R1 winners-friendly" extending into lucky) | User brief §16 EXPLICIT: preserve shipped v9 lucky direction |
| dd density up (multiplier shift) ↔ wild_pure share cap | dd cube 0.727× m1 in m2; m5 lift 1.20× over m2 → cube 0.838× m1 | dd cube same as m1 would breach wild_pure share cap | wild_pure share cap is structural verify RED; must respect |
| h7 cut in m5 ↔ user §18 "high mults up" | h7 cut 8% releases base budget for centered RTP | h7 preserved would push m5 total > 510 ceiling | Higher mults LIVE in wild_pure (200x) + feature (heavy tail) — both lifted m5 vs m2 |
| m5 trigger = m2 trigger ↔ LUCKY-MONO strict | Trigger equal | m5 trigger slightly above m2 | Strict LUCKY-MONO m5_trig >= m2_trig minimal compliance; equal satisfies. Lift would push total > 510 |

---

## 7. Path summary

- **Design doc** (this file): `session_artifacts/M15/design_v14c_modes_25.md`
- **Design script**: `session_artifacts/M15/scripts/m15_v14c_design_modes_25.py`
- **Feasibility log**: `session_artifacts/M15/feasibility_v14c.txt`
- **Search scripts** (audit trail): `session_artifacts/M15/scripts/m15_v14c_search1.py` through `search6.py`, `m5_fix_hit.py`, `inspect_winners.py`, `inspect_m5.py`
- **Mode 1 baseline** (reference, not modified): `slot_designer/machines/M15/weights/mode_1/weights.json`, `session_artifacts/M15/design_v14.md`
- **Mode 7 baseline** (reference, not modified): `slot_designer/machines/M15/weights/mode_7/weights.json`, `session_artifacts/M15/design_v14b_modes_725.md` §2

**No production files modified.** Output is design recommendation only — main session ships after V/X review and engine-realized validation.

---

## 8. Final summary table

| metric | mode 1 (shipped) | mode 7 (shipped) | mode 2 (M2_LC) | mode 5 (M5_LC_plus) |
|---|---:|---:|---:|---:|
| Total RTP (pp) | 94.29 | 85.37 | **296.13** | **504.56** |
| RTP user-target band | [94, 96] | [83, 87] | [292, 308] | [491.5, 508.5] |
| RTP verify band | [94, 96] | [83, 87] | [290, 310] | [480, 520] |
| RTP margin (lo / hi) | 0.29 / 1.71 | 2.37 / 1.63 | **6.13 / 13.87** | **14.56 / 5.44** |
| Base hit (%) | 16.22 | 13.06 | 33.85 | 33.89 |
| Trigger (%) | 1.120 | 1.122 | 3.304 | 3.304 |
| wild_pure cadence | 1/51,314 | 1/51,287 | 1/70,607 | 1/61,377 |
| wild_pure ratio (m2/m1, m5/m2) | — | — | 0.727 (≤ 1.5 cap) | 1.150 (≥ 1.1 floor) |
| Bar §1 P(b1) > P(b2) > P(b3) | ✓ | ✓ | **✓** | **✓** |
| R1 ≥ R3 blank (lucky carve, m2/m5 only) | (n/a) | (n/a) | **✓ (27.53 ≥ 23.19)** | **✓ (28.64 ≥ 23.96)** |
| P(R≥1000)/spin ≤ 1e-5 | 7.4e-8 | 7.4e-8 | 1.5e-6 | 1.1e-7 |
| P(R≥200)/spin ladder m1<m2<m5 | 3.2e-5 | 3.2e-5 | 2.8e-4 | 3.9e-3 (esc ✓) |
| Jackpot per-reel ≤ 0.6% | ✓ (0.4/0.4/0.3) | ✓ | ✓ (0.4/0.4/0.3) | ✓ (0.4/0.4/0.3) |
| Total invariants PASS | (shipped) | (shipped) | **18/18** | **15/15** |
| Cross-mode ladder PASS | — | — | — | **10/10** |

**GRAND TOTAL: 43/43 invariants PASS.**

---

## 9. Status flags for main session

- ✅ Mode 2 RTP at safe distance from band edges (6.13pp margin = 4.26σ on 1M sim)
- ✅ Bar §1 hierarchy preserved (no agent-promoted hardline)
- ✅ Reel asymmetry per shipped v9 lucky carve-out (R1 blank > R3 blank)
- ✅ All FAMILY-SHARE verify bands respected
- ⚠️ m5 LUCKY-MONO hit margin only 0.04pp (33.89% vs 33.85%) — flag for engine-realized check post-integer-rounding
- ⚠️ m5 LUCKY-MONO trigger equality (3.304% == 3.304%) — flag for engine-realized check; bump td_R3 weight slightly if needed
- ✅ Engine-realized RTP drift expected ±0.5pp; both modes have ≥5pp band margin
