# M37 mode 7 v6 design — 2026-05-12

> Designer restart per v6 m7-only brief. m1/m2/m5 not touched. MODE7-LOCK relaxed-with-tiers permitted; tier 1 (±0.5pp drift) attempted first.

## 1. m7 baseline confirm

Current `slot_designer/machines/M37/weights/mode_7/weights.json` (v3 finalized, post v5 sync):

| 指标 | value |
|---|---|
| RTP | **84.894%** |
| Hit | **14.253%** |
| pid 9 RTP-pp | 22.316 |
| **pid 9 share** | **26.287%** (target ≤ 21%) |
| R2 booster (mi/mn/mj/gr) | 3.016 / 2.166 / 1.656 / 0.1168 |
| R2 high7 | 10.087% |
| R1 wild / high7 / blank | 1.158 / 17.248 / 25.970 |
| R3 wild / high7 / blank | 1.169 / 16.308 / 26.896 |
| R2 blank | 69.155% |
| CV | 10.705 |

Confirmed: matches task §1 baseline note (pid 9 26.29%, RTP 84.89%, hit 14.25%).

## 2. MODE7-LOCK tier 1 search result — FEASIBLE

**Method**: coarse 5-D grid (mini/minor/major weights at tier-1 marginal band; R1+R3 high7/bar/wild factors; R2 high7 weight factor) over 3000 evals → 8 passing all guards → fine 14,400-grid refine → 2229 passing → multi-criteria score (RTP near 85, pid9 ≤ 20.5, minimum archetype dev).

**Tier 1 (±0.5pp drift) result**: **FEASIBLE** with comfortable margin. Best candidate pid 9 share 17.16% (4pp below ceiling); recommended pid 9 share 19.13% (1.87pp below ceiling) at minimum lever deviation.

Min pid 9 share reachable in tier 1: ~17.2% (with bar ×1.20). Achievable comfortably at ~19.1% with moderate bar ×1.15.

**No tier 2/3 escalation needed.**

## 3. n/a — tier 1 sufficient

## 4. Recommended m7 v6 lever values + weights

Final m7 v6 (cand #1 from fine search, lowest multi-criteria score = 1.00):

| Lever | Value | vs m7 baseline | vs m1 v5 |
|---|---|---|---|
| R2 mini weight | **240** | baseline 284 (×0.85) | m1 ship'd 274 |
| R2 minor weight | **190** | baseline 204 (×0.93) | m1 ship'd 196 |
| R2 major weight | **126** | baseline 156 (×0.81) | m1 ship'd 150 |
| R2 high7 weight (total) | 950 | unchanged (factor 1.00) | m1 1280 |
| R2 grand weight | 11 LOCKED | unchanged | matches |
| R1+R3 bar per-symbol | uniform ×1.15 | + 15% | m1 ×1.20 |
| R1+R3 wild | ×1.00 | unchanged | m1 ×0.70 (m7 baseline already low) |
| R1+R3 high7 | ×1.05 | + 5% | m1 ×1.29 |

Output: `session_artifacts/M37/v6_sim_weights/mode_7/weights.json`.

## 5. Resulting marginals + bucket + hit / RTP / pid 9 占比

| | Baseline (m7 v3) | m7 v6 | Δ |
|---|---|---|---|
| **RTP** | 84.894 | **85.021** ✓ in [84, 86] | +0.127 |
| **Hit** | 14.253 | **14.996** ✓ < 20.62 | +0.743 |
| **pid 9 share** | 26.287% | **19.126%** ✓ ≤ 21% | **-7.161pp** |
| pid 9 RTP-pp | 22.316 | 16.261 | -6.055 |
| 1000× freq | 1/N | 1/M | (improved by high7 lever) |
| CV | 10.705 | 11.308 | + (consistent with cut booster, higher variance) |
| **R2 mini** | 3.016 | 2.572 | -0.444 |
| **R2 minor** | 2.166 | 2.036 | -0.130 |
| **R2 major** | 1.656 | 1.350 | -0.306 |
| R2 grand | 0.1168 | 0.1179 | 0 (locked) |
| **R2 high7** | 10.087 | 10.182 | +0.095 |
| R2 bar total | 13.x | 13.934 | (passive) |
| R2 blank | 69.155 | 69.807 | +0.65 (passive small) |
| R1 1bar/2bar/3bar/7bar | 16.67/14.48/14.48/10.00 | 19.17/16.65/16.65/11.50 | +15% per |
| R1 wild | 1.158 | 1.158 | 0 (factor 1.0) |
| R1 high7 | 17.248 | 18.119 | +5% |
| R1 blank | 25.970 | 16.743 | -9.2 (passive absorb cut savings) |
| R3 1bar/2bar/3bar/7bar | 16.58/14.20/14.20/10.64 | 19.07/16.33/16.33/12.24 | +15% |
| R3 wild | 1.169 | 1.169 | 0 |
| R3 high7 | 16.308 | 17.130 | +5% |
| R3 blank | 26.896 | 17.731 | -9.2 (passive) |

**Bucket distribution (RTP-pp)**:

| Bucket | m7 v6 |
|---|---|
| ge1_5 | 14.49 |
| ge5_10 | 10.17 |
| ge10_20 | 17.86 |
| ge20_100 | 17.21 |
| ge100_200 | 14.23 |
| ge200+ | 11.07 |

## 6. MODE7-LOCK drift actual

m1 v5 ship'd anchors: mini 2.786 / minor 1.993 / major 1.525.

| Booster | m7 v6 | drift | tier 1 limit | status |
|---|---|---|---|---|
| mini | 2.572 | 0.214 | 0.5 | ✓ |
| minor | 2.036 | 0.043 | 0.5 | ✓ |
| major | 1.350 | 0.175 | 0.5 | ✓ |
| grand | 0.1179 | (≈ 0.006 vs m1 0.1119) | – | ✓ |

**All three booster tiers within tier 1 (±0.5pp) — tightest possible MODE7-LOCK satisfied.**

## 7. HIT-MONOTONIC check

m1 v5 ship'd hit = 20.918. Required: m7 hit < 20.918 - 0.3 = **20.618**.

m7 v6 hit = **14.996** → slack **5.622pp** (vastly above 0.3pp safety floor). ✓

## 8. Cross-mode invariants check

- m1 weights byte-equal v5 ship'd (verified read-back) ✓
- m2/m5 weights NOT modified (not in m7 designer scope) ✓
- Strip locked (no edits to `reel_strips.json`) ✓
- Paytable locked (no edits to `spec.json`) ✓
- R2 grand weight at position 23 = 11 (LOCKED, unchanged) ✓
- MODE7-LOCK tier 1 satisfied ✓
- HIT-MONOTONIC m7 < m1 - 0.3pp ✓
- RTP-MONOTONIC m7 (85.02) < m1 (94.09) < m2 (current ship'd) < m5 ✓ (m2/m5 not changed)
- §1 BOOSTER-HIER monotone (mini 2.57 > minor 2.04 > major 1.35 > grand 0.12) ✓
  - ratios mini/minor = 1.263, minor/major = 1.508 — both ≥ 1.0 floor ✓
- §2 R2 high7 ≥ 8.93% (10.182) ✓
- §6 archetype (anchored to m7 baseline): bar ±25%, wild ±30%, high7 ±30% — all within ✓
- §12 R1 ≤ R3 blank (16.74 < 17.73 ✓), R1 top ≥ R3 (19.28 > 18.30 ✓), R3 ≤ R2 + 8pp slack (17.73 < 69.81 ✓✓)
- §13 BLANK-FLANK-DIVERSITY strip layout (locked, no edit)
- §14 mid-pay 8% any-reel: min visibility for any bar tier ≫ 8% (R1 7bar window vis = 1 - (1-0.115)^3 = 30.6%) ✓
- TOP-PATH-1000X (grand + R1/R3 high7 lever both ≥ baseline → jackpot path intact) ✓

---

## 80-word summary

m7 v6 ships at **RTP 85.02% / hit 15.00% / pid 9 share 19.13%** — MODE7-LOCK **tier 1** (±0.5pp drift; actual mi 0.21, mn 0.04, mj 0.17). Cut R2 booster weights mini 284→240, minor 204→190, major 156→126 + boost R1+R3 bar ×1.15 + high7 ×1.05 + wild unchanged. R2 high7 weight unchanged. pid 9 share cut from 26.29% → 19.13% (–7.16pp). HIT-MONOTONIC margin 5.6pp. m1/m2/m5 untouched. No tier escalation needed.
