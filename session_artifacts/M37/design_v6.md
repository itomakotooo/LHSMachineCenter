# M37 mode 2 + mode 5 v6 design — 2026-05-12

> Designer fresh-context v6 restart (prev Designer stalled on m7 MODE7-LOCK). Scope: **m2 + m5 only**. m7 deferred to separate task. m1 v5 ship'd untouched.

## 1. m2 baseline (v3 finalized)

| 指标 | value |
|---|---|
| RTP | 300.32% |
| hit | 32.34% |
| pid 9 RTP占比 | 22.66% (need ≤ 21 = cut ~1.7pp) |
| pid 9 RTP | 68.07 |
| R2 mini | 11.08% |
| R2 minor | 8.25% |
| R2 major | 6.09% |
| R2 grand | 0.59% |
| R2 high7 | 7.96% |
| R2 blank | 56.93% |
| R1 wild | 1.48% |
| R3 wild | 1.48% |
| R1 high7 | 12.14% |
| R3 high7 | 12.59% |
| HIER ratios | mi/mn=1.343, mn/mj=1.355 |

Per-pay RTP (baseline): pid1=36.25, pid2=19.07, pid3=26.17, pid4=26.79, pid5=22.56, pid6=11.52, pid7=58.14, pid8=31.48, pid9=68.07.

## 2. m2 lever search summary

**Approach**: small adjustment around v3 baseline. v6 amendment says "m2 already 22.66% close to 21% — small change, don't blow up archetype".

**Lever ranges explored (refined sweep)**:
- booster_factor (uniform mini/minor/major scale): {0.90, 0.92, 0.94, 0.96, 0.98, 1.00}
- R2 high7 factor: {0.95, 1.00, 1.05}
- R1+R3 wild factor: {0.70, 0.75, 0.80, 0.83, 0.85, 0.88, 0.92}
- R1+R3 high7 factor: {1.00, 1.03}
- R1+R3 bar factor (uniform): {1.00, 1.03, 1.05}

**Candidates evaluated**: 756 (well within ≤3000 budget). **Feasible (pid9_share ≤ 20.5 safety + all soft boundaries)**: 123.

Optimization objective: minimum L1 deviation from v3 baseline marginals (weighted: high7×2, wild×1.5, bar×1, booster×1.5).

## 3. m2 recommended (smallest L1 dev within safety buffer)

### 3.1 Lever values

| Lever | v3 baseline | v6 chosen | Δ |
|---|---|---|---|
| R2 mini weight (`weights[1][5]`) | 974 | **955** | ×0.98 |
| R2 minor weight (`weights[1][11]`) | 725 | **710** | ×0.98 |
| R2 major weight (`weights[1][17]`) | 535 | **524** | ×0.98 |
| R2 high7 total (pos1+pos13) | 700 (350+350) | 700 (350+350) | unchanged |
| R2 grand weight (`weights[1][23]`) | 52 | 52 | **locked** |
| R1 bar all positions | × per-position | ×1.05 uniform | small boost |
| R3 bar all positions | × per-position | ×1.05 uniform | small boost |
| R1 wild all positions | × per-position | ×0.92 uniform | small cut |
| R3 wild all positions | × per-position | ×0.92 uniform | small cut |
| R1+R3 high7 | unchanged | unchanged | – |
| R1+R3 blank | passive absorb | passive absorb | – |

### 3.2 m2 v6 marginals

| Symbol | baseline | v6 | Δ% |
|---|---|---|---|
| R1 1bar | 19.09 | 20.05 | +5.0% |
| R1 2bar | 18.08 | 18.98 | +5.0% |
| R1 3bar | 15.82 | 16.62 | +5.0% |
| R1 7bar | 12.31 | 12.91 | +5.0% |
| R1 wild | 1.48 | 1.35 | -8.4% |
| R1 high7 | 12.14 | 12.14 | 0 |
| R1 blank | 21.09 | 17.95 | -14.9% (passive) |
| R3 1bar | 18.13 | 19.03 | +5.0% |
| R3 2bar | 17.12 | 17.98 | +5.0% |
| R3 3bar | 14.98 | 15.74 | +5.1% |
| R3 7bar | 11.16 | 11.73 | +5.1% |
| R3 wild | 1.48 | 1.35 | -8.6% |
| R3 high7 | 12.59 | 12.59 | 0 |
| R3 blank | 24.55 | 21.59 | -12.0% (passive) |
| R2 mini | 11.08 | 10.92 | -1.4% |
| R2 minor | 8.25 | 8.12 | -1.6% |
| R2 major | 6.09 | 5.99 | -1.5% |
| R2 grand | 0.59 | 0.60 | locked (weight 52) |
| R2 high7 | 7.96 | 8.00 | +0.5% (passive) |
| R2 blank | 56.93 | 57.23 | +0.5% (passive) |

### 3.3 m2 v6 hard target verify

| Hard target | baseline | v6 actual | Status |
|---|---|---|---|
| RTP ∈ [295, 305] | 300.32 | **303.45** | ✅ |
| pid 9 占比 ≤ 21% | 22.66% | **20.37%** | ✅ (0.63pp safety) |
| §1 HIER ratio ≥ 1.0 | 1.343, 1.355 | **1.345, 1.355** | ✅ |
| §14 mid-pay any-reel ≥ 8% | OK | OK (min 1bar visibility R3 ~48.2%) | ✅ |
| hit in [30, 36] | 32.34 | **32.21** | ✅ |
| R2 grand weight unchanged (locked 52) | 52 | **52** | ✅ |
| Strip layout unchanged | OK | OK (no strip edit) | ✅ |
| Archetype ±30% high7, ±30% wild, ±25% bar | – | within all soft bands | ✅ |

### 3.4 m2 v6 per-pay RTP

| pay_id | baseline | v6 | Δ |
|---|---|---|---|
| 1 (high7×3) | 36.25 | 35.36 | -0.89 |
| 2 (7bar×3) | 19.07 | 20.31 | +1.24 |
| 3 (3bar×3) | 26.17 | 28.02 | +1.85 |
| 4 (2bar×3) | 26.79 | 28.74 | +1.95 |
| 5 (1bar×3) | 22.56 | 24.23 | +1.67 |
| 6 (high7+7bar mix) | 11.52 | 12.01 | +0.49 |
| 7 (anybar) | 58.14 | 63.59 | +5.45 |
| 8 (line) | 31.48 | 29.17 | -2.31 |
| **9 (side-wild/booster-alone)** | **68.07** | **61.80** | **-6.27** |
| **TOTAL** | 300.32 | **303.45** | +3.13 |

pid 9 down 6.27 RTP: small wild cut + small booster cut, redistributed to bar shifts pid 9 → pid 7 / pid 3-5.

## 4. m5 auto-inherit from m2 + grand fixed

Per universal MODE5-BASE-LOCK (slot_designer §10): m5 base byte-eq m2 base except R2 grand position.

**Build**: byte-copy m2 v6 weights, override `weights[1][23]` (R2 grand) from 52 (m2) → 166 (m5 baseline value, preserves super-lucky RTP).

**MODE5-BASE-LOCK verify**: m5 base byte-equal to m2 v6 base except position [1][23]. ✅

## 5. m5 v6 verify

| Hard target | baseline | v6 actual | Status |
|---|---|---|---|
| RTP ∈ [490, 510] | 499.63 | **507.56** | ✅ |
| pid 9 占比 ≤ 21% | 13.45% | **12.02%** | ✅ (huge margin) |
| §1 HIER monotone | 1.343, 1.355 | **1.345, 1.355** | ✅ |
| §14 mid-pay any-reel ≥ 8% | OK | OK | ✅ |
| hit in [30, 40] | 33.21 | **33.09** | ✅ |
| MODE5-BASE-LOCK | – | **byte-eq m2 except R2 grand** | ✅ |

m5 v6 marginals: R2 grand 1.87% (baseline 1.86%), R2 mini 10.78%, R2 minor 8.01%, R2 major 5.91%. Per-pay RTP: pid1=58.87, pid7=105.04, pid8=91.93, pid9=61.01.

## 6. Cross-mode invariants

| Invariant | Status |
|---|---|
| **m1 unchanged** (v5 ship'd) | ✅ RTP=94.09 / hit=20.92 / pid9=20.07% |
| **m7 not touched** (deferred) | ✅ |
| **MODE5-BASE-LOCK** m5 base = m2 base + grand | ✅ |
| **GRAND-SIGNATURE** m2 grand 0.595% / m5 grand 1.874% (per-mode bands) | ✅ |
| **§9 HIT-MONOTONIC** m1=20.92 < m2=32.21 ≈ m5=33.09 | ✅ (need m7 < m1 - 0.3 = 20.62 — left to m7 task) |
| **Paytable / spec / strip layout** unchanged | ✅ |
| **TOP-PATH-1000X** via high7-grand-high7 — R1+R3 high7 + grand unchanged | ✅ |
| **§13 BLANK-FLANK-DIVERSITY** strip locked | ✅ |

## 7. Files

- `session_artifacts/M37/v6_sim_weights/mode_2/weights.json` — m2 v6 final
- `session_artifacts/M37/v6_sim_weights/mode_5/weights.json` — m5 v6 final (auto-inherit)
- `session_artifacts/M37/_designer_scratch_v6/m2_v6_applier.py` — lever applier
- `session_artifacts/M37/_designer_scratch_v6/m2_v6_search.py` — coarse search (2100 cand)
- `session_artifacts/M37/_designer_scratch_v6/m2_v6_refine.py` — refined search (600 cand)
- `session_artifacts/M37/_designer_scratch_v6/m2_v6_final_pick.py` — final pick w/ 0.5pp safety buffer (756 cand)
- `session_artifacts/M37/_designer_scratch_v6/m5_v6_build_and_verify.py` — m5 build + verify

## 8. Summary (≤ 80 words)

**m2 final**: booster ×0.98 + R1+R3 wild ×0.92 + R1+R3 bar ×1.05. RTP 303.45 (target [295,305] ✅), pid9_share 20.37% (target ≤21 ✅, 0.63pp buffer), hit 32.21 (target [30,36] ✅). HIER ratios preserved (1.345/1.355). R2 grand+high7+R1/R3 high7 untouched. **m5 verify**: MODE5-BASE-LOCK obeyed, RTP 507.56, pid9_share 12.02%, hit 33.09 — all GREEN. m1 untouched. m7 deferred to separate task.
