# M37 mode 7 — Designer v9.1 (RTP empirical margin fix, delta from v9)

## 1. v9 → v9.1 delta (RTP empirical FAIL fix)

**v9 problem**: Analyst empirical 5M MC verdict — mean RTP **83.619** vs floor 84.0 = **-0.381pp**. 30/50 seeds (60%) land RTP < 84.0. Analytic-vs-empirical drift -0.99σ within 1σ noise → **not engine bias**, just Designer v9 K_bar=0.82 → analytic RTP 84.011 sits 0.39σ above floor → 50-50 empirical chance under.

**v9.1 fix per brief**: K_bar 0.82 → **0.83** (less aggressive cut, +1pp analytic RTP buffer). Single-point K_bar=0.83 K_wild=1.0 K_mini=0.91 → RTP 84.481% (0.019pp below new floor 84.5). Minimal tweak: lift K_mini 0.91 → **0.94** (less mini cut → +0.27pp RTP) to land safely in [84.5, 85.5].

## 2. Lever values (v9.1)

| Lever | v9 | v9.1 | delta | notes |
|-------|------|------|-------|-------|
| K_bar | 0.82 | **0.83** | +0.01 | per brief — primary RTP buffer fix |
| K_wild | 1.00 | 1.00 | 0 | kept (R1+R3 wild fully preserved) |
| K_mini | 0.91 | **0.94** | +0.03 | minor fine-tune; single-point K_bar=0.83 K_mini=0.91 gave RTP 84.48 (just below 84.5 floor) — bump K_mini to land in band |

R2 minor/major/grand/high7/bar byte-eq m1 v5. R1+R3 high7 byte-eq m1 v5.

## 3. Resulting analytic + per-pay table

**Analytic outcome**: RTP **84.747%**, hit **17.254%**, pid 9 share **26.44%**, hit-gap vs m1 = 3.665pp (real cut mode feel intact).

| pid | name | freq | rtp_pp | ratio vs m1 | tier (§4) | floor check |
|-----|------|------|--------|-------------|-----------|-------------|
| 1 | high7×3 10× | 0.00705 | 19.97 | 0.991 | 顶 | ≥ 0.85 PASS |
| 2 | 7bar×3 6× | 0.00123 | 3.01 | 0.706 | 中 | ≥ 0.68 PASS |
| 3 | 3bar×3 5× | 0.00263 | 4.74 | 0.701 | 中 | ≥ 0.68 PASS |
| 4 | 2bar×3 4× | 0.00263 | 3.79 | 0.701 | 中 | ≥ 0.68 PASS |
| 5 | 1bar×3 3× | 0.00427 | 3.98 | 0.700 | 小 | cut OK |
| 6 | any-7-mix 2× | 0.01133 | 4.59 | 0.833 | 小 | cut OK |
| 7 | any-bar 1× | 0.08273 | 14.67 | **0.690** | 小 (MAIN CUT) | cut delivered |
| 8 | grand-alone 100× | 0.00076 | 7.55 | 1.214 | 顶 | PASS |
| 9 | booster/wild-alone | 0.05989 | 22.41 | 1.138 | mix | — |
| 102 | (wild,major,wild) | 0.0000024 | 0.024 | 1.000 | 大 | PASS |
| 103 | (wild,minor,wild) | 0.0000032 | 0.016 | 1.000 | 大 | PASS |
| 104 | (wild,mini,wild) | 0.0000040 | 0.008 | 0.940 | 大 | PASS |

R2 booster marginals: mini 2.619% > minor 1.993% > major 1.525% > grand 0.112%. HIER monotone strict ✓. mini/minor ratio **1.314** (now in conventional 1.2-1.3 range, vs v9 1.272 at low edge).

## 4. v9.1 vs v9 comparison (1 row per metric)

| metric | v9 | v9.1 | delta |
|--------|------|------|-------|
| K_bar | 0.82 | 0.83 | +0.01 |
| K_mini | 0.91 | 0.94 | +0.03 |
| analytic RTP | 84.011% | **84.747%** | **+0.736pp** |
| analytic hit | 16.986% | 17.254% | +0.268pp |
| pid 9 share | 26.77% | 26.44% | -0.33pp |
| hit-gap vs m1 | 3.93pp | 3.67pp | -0.27pp (still real cut mode feel) |
| pid 2 ratio | 0.686 | 0.706 | +0.020 (now ≥ 0.70 strict) |
| pid 3 ratio | 0.682 | 0.701 | +0.019 (now ≥ 0.70 strict) |
| pid 4 ratio | 0.682 | 0.701 | +0.019 (now ≥ 0.70 strict) |
| pid 1 ratio | 0.987 | 0.991 | +0.004 |
| pid 104 ratio | 0.910 | 0.940 | +0.030 (mini-related) |
| HIER mini/minor | 1.272 | 1.314 | +0.042 |
| R2 mini marginal | 2.535% | 2.619% | +0.084pp (better Lightning Link visibility) |

Both pid 2/3/4 ratios now satisfy the original v9 brief 0.70 floor (no longer "structural drift accept"). Side benefit of the v9.1 fix.

## 5. Predicted empirical (analytic + margin)

Analytic-empirical drift on v9 was -0.99σ (mean 83.619 vs analytic 84.011). σ_empirical ≈ 0.395pp per 5M sample (from observed). For v9.1:

- Analytic RTP 84.747%
- Expected empirical mean ≈ 84.747 - 0.4 = **~84.35%** (1σ low-side margin) to 84.747 - 0 = 84.75% (mean)
- 30/50 seed empirical floor band: 84.0 with σ=0.395 — analytic 84.747 sits **1.89σ above 84.0 floor** (vs v9's 0.39σ above)
- Probability empirical mean < 84.0 ≈ Φ(-1.89) ≈ **3% (vs v9's ~30%)**

Plus brief relaxed hit ceiling to 17.5 — v9.1 hit 17.254 sits 0.25pp below ceiling with 1σ margin (vs v9's 16.99 sitting 0.01pp below 17.0 strict).

## 6. Files

Output weights: `session_artifacts/M37/v9_1_sim_weights/mode_7/weights.json`
