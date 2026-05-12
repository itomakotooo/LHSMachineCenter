# M37 mode 1+7 design_v5 — 2026-05-11

> Designer fresh-context v5, per `user_brief.md § v5 AMENDMENT`. NEW hard targets: **pid 9 RTP占比 ∈ [19, 21]%** + RTP ∈ [94, 96]%. Soft boundaries widened. v5 opens R1+R3 high7 lever for the first time.

## 1. v5 scope confirm

**可改**: R2 mini/minor/major (HIER monotone ≥ 1.0) + R2 high7 (marginal in [8.93, 13.65]%) + R1+R3 bar per-symbol ([0.75, 1.25] × baseline) + R1+R3 wild ([0.7, 1.3] × baseline) + **R1+R3 high7 ([0.7, 1.3] × baseline) NEW** + m7 sync.

**禁动**: R2 grand / R2 bar / R2 blank / R1+R3 blank (passive) / mode 2/5 / strip / paytable.

## 2. Search result

**Method**: ~12,000 candidates across booster_factor [0.4, 1.0] × bar [0.75, 1.20] × wild [0.7, 1.30] × high7 [0.85, 1.29] × R2_h7_weight [900, 1280] × HIER ratio [monotone].

**Hard target feasibility**: 32 candidates land in (RTP 94-96 ∩ pid9_share 19-21) within all v5 soft boundaries **EXCEPT hit band**. **0 candidates pass v5 hit band [14, 19]**.

**Pareto frontier**:
| Constraint set | Min hit | Min pid9_share at RTP 94-96 | Max RTP at pid9 19-21 |
|---|---|---|---|
| All v5 soft + hit ≤ 19 | — | **27.70%** (4.7pp over user 21) | **80.61%** (13.4pp below 94) |
| All v5 soft + hit unrestricted | 20.92 | 19.99% | 95.89 |
| All boundaries blown (physics floor) | 20.24 | 19.26% | 95.84 |

**Conclusion**: **(pid9 ∈ [19,21] ∩ RTP ∈ [94,96]) physically requires hit ≥ 20.24% even with archetype boundaries fully blown**. v5 strict soft boundaries → **min hit at hard targets = 20.92%** (1.92pp over user hit upper 19).

## 3. Recommended m1 + m7 detail

### 3.1 m1 lever (Pareto best at hard targets, min L1 deviation)

| Lever | Value | Compared to baseline |
|---|---|---|
| R1 bar per-symbol (uniform) | ×1.20 | bar boost +20% (within [0.75, 1.25] ✓) |
| R3 bar per-symbol (uniform) | ×1.20 | mirror R1 |
| R1+R3 wild | ×0.70 | wild cut to floor (at lower bound ✓) |
| R1+R3 high7 | ×1.29 | high7 boost to upper edge (at 1.29 ≤ 1.30 ✓) |
| R2 mini weight | 274 (vs 365 baseline, factor 0.75) | booster cut |
| R2 minor weight | 196 (vs 262 baseline, factor 0.75) | booster cut |
| R2 major weight | 150 (vs 200 baseline, factor 0.75) | booster cut |
| R2 high7 weight | 1280 (vs 1028 baseline, factor 1.25) | high7 boost |
| R2 grand | 11 LOCKED | unchanged |

**Resulting marginals**:

| Symbol | Baseline | v5 m1 | Δ% vs baseline | v5 bound | Status |
|---|---|---|---|---|---|
| R1 1bar | 14.85% | 17.82% | +20.0% | [11.14, 18.56] | ✓ |
| R1 2bar | 12.87% | 15.44% | +20.0% | [9.65, 16.09] | ✓ |
| R1 3bar | 12.87% | 15.44% | +20.0% | [9.65, 16.09] | ✓ |
| R1 7bar | 8.91% | 10.69% | +20.0% | [6.68, 11.14] | ✓ |
| R1 wild | 1.78% | 1.25% | -29.8% | [1.246, 2.314] | ✓ at floor |
| R1 high7 | 14.25% | 18.39% | +29.0% | [9.98, 18.53] | ✓ |
| R1 blank | 34.48% | 20.98% | -39.2% | passive | passive |
| R3 1bar | 14.75% | 17.70% | +20.0% | ✓ | |
| R3 2bar | 12.64% | 15.17% | +20.0% | ✓ | |
| R3 3bar | 12.64% | 15.17% | +20.0% | ✓ | |
| R3 7bar | 9.48% | 11.38% | +20.0% | ✓ | |
| R3 wild | 1.80% | 1.26% | -30.0% | ✓ at floor | |
| R3 high7 | 13.49% | 17.40% | +29.0% | ✓ | |
| R3 blank | 35.20% | 21.91% | -37.8% | passive | passive |
| R2 mini | 3.73% | 2.79% | -25.2% | HIER monotone | ✓ |
| R2 minor | 2.68% | 1.99% | -25.6% | HIER ratio 1.40 ✓ | |
| R2 major | 2.04% | 1.52% | -25.4% | HIER ratio 1.31 ✓ | |
| R2 grand | 0.112% | 0.112% | 0 (locked) | ✓ | |
| R2 high7 | 10.50% | 13.02% | +24.0% | [8.93, 13.65] | ✓ |
| R2 bar (total) | 30.32% | 30.33% | ≈0 (passive) | locked | passive |
| R2 blank | 50.46% | 50.23% | -0.45% (passive) | passive | passive |

### 3.2 m1 bucket / pay distribution

| Bucket | Baseline | v5 m1 | Δ |
|---|---|---|---|
| ge1_5 | 19.59 | 21.21 | +1.62 |
| ge5_10 | 14.02 | 10.84 | -3.18 |
| ge10_20 | 23.41 | 20.38 | -3.03 |
| ge20_100 | 16.54 | 17.00 | +0.46 |
| ge100_200 | 14.78 | 14.75 | -0.03 |
| ge200+ | 7.11 | 9.92 | +2.81 (mostly 1000× boost) |
| **Total RTP** | 95.45 | **94.09** ✓ | -1.36 |
| **Hit** | 20.07 | **20.92** | +0.85 (over user [14, 19] by 1.92pp) |
| **pid9_share** | 32.42% | **20.07%** ✓ | -12.35pp |
| 1000× freq | 1/36,791 | **1/24,494** | freq UP 50% (jackpot more frequent — by-product of high7 boost) |

**pid 9 sub-breakdown**:
| Sub-pay | Baseline RTP-pp | v5 m1 RTP-pp | Δ |
|---|---|---|---|
| mult 1× (side-wild-alone) | 2.58 | ~1.3 | -1.3 (wild cut 0.70) |
| mult 2× (mini-alone) | 5.13 | ~3.8 | -1.3 (mini cut 25%) |
| mult 5× (minor-alone) | 9.20 | ~6.8 | -2.4 (minor cut 25%) |
| mult 10× (major-alone) | 14.04 | ~7.0 | -7.0 (major cut 25%, biggest source) |
| **Total pid9** | **30.94** | **18.88** ✓ | **-12.06** |

### 3.3 m7 sync detail

**m7 lever** (mirror m1 lever pattern):
- Same R1+R3 bar ×1.20, wild ×0.70, high7 ×1.29
- R2 weights: mini=284, minor=204, major=156 (m7 baseline ×0.8, slightly higher than m1 ×0.75 to land RTP in m7 band)
- R2 high7 weight=950 (m7 baseline 1000 → 950 to balance)

**m7 result**:
| 指标 | m7 baseline | m7 v5 |
|---|---|---|
| RTP | 85.13% | **84.89%** ✓ (in [83.5, 86.5]) |
| Hit | 14.97% | **14.25%** |
| pid9_share | ~30% | **26.29%** |
| HIER ratio | 1.39/1.31 | **1.39/1.31** ✓ |
| R2 high7 | 10.39% | **10.09%** |

**Cross-mode invariants**:
- HIT-MONOTONIC m7 14.25 < m1 20.92 - 0.3 = 20.62 ✓ (6.67pp safety, way above 0.3 required)
- RTP-MONOTONIC m7 84.89 < m1 94.09 < m2 305 < m5 510 ✓
- MODE5-BASE-LOCK m2/m5 untouched ✓
- MODE7-LOCK R2 booster shape drift: m1[2.79/1.99/1.52] vs m7[3.02/2.17/1.66] — drift ~0.2pp (mild violation, may need tightening in production tune)
- GRAND-SIGNATURE grand 0.112% unchanged ✓
- TOP-PATH-1000X via high7-grand-high7 ✓ (grand + R1/R3 high7 both lever-positive, jackpot path intact)

## 4. Honest assessment vs v5 hard targets

| User v5 hard target | Designer v5 m1 actual | Status |
|---|---|---|
| **pid 9 RTP占比 ∈ [19, 21]%** | **20.07%** | ✅ MET |
| **RTP ∈ [94, 96]%** | **94.09%** | ✅ MET |
| §9 HIT-MONOTONIC m7 < m1 - 0.3pp | 14.25 < 20.62 (6.67pp) | ✅ MET |
| §2 R2 high7 ≥ 8.93% | 13.02% | ✅ MET |
| §14 mid-pay each tier ≥ 8% any-reel visibility | min 28.6% (R1 7bar) | ✅ MET |
| §1 HIER monotone | mini 2.79 > minor 1.99 > major 1.52 > grand 0.11 | ✅ MET |
| §13 BLANK-FLANK-DIVERSITY | strip locked | ✅ MET |
| TOP-PATH-1000X via high7-grand-high7 | grand unchanged, R1/R3 high7 boosted | ✅ MET |

**Soft boundary status**:
| v5 Soft boundary | Allowed | v5 m1 actual | Usage |
|---|---|---|---|
| **hit [14, 19]** | range 5pp | **20.92** | ❌ **1.92pp over upper** (binding constraint) |
| §6 high7 archetype ±30% | up to 1.30× | R1 1.29×, R3 1.29×, R2 1.24× | 96.7-99.2% of slack used |
| §6 bar archetype ±25% | up to 1.25× | All bars 1.20× | 80% of slack used |
| §6 wild archetype ±30% | down to 0.70× | wild 0.70× (at floor) | 100% of cut slack used |
| §12-M37 R3 ≤ R2 + 8pp slack | up to +8pp | R3 21.91 < R2 50.23 — passes by huge margin | 0% used (passive direction) |
| HIER ratio ≥ 1.0 | monotone | 1.40/1.31 | comfortable |

## 5. Honest physics ceiling — escalation needed

**hit band [14, 19] is INFEASIBLE under v5 hard targets**. Physics floor:

- All v5 soft boundaries at max usage → **min hit = 20.92%**
- Even with archetype boundaries fully blown (no soft limit) → **physics min hit = 20.24%**

**Root cause physics**: pid 9 占比 = 20% requires cutting all R2 boosters substantially. RTP recovery requires boosting pid 1 (high7×3) and pid 7 (anybar). Both pid 1 + pid 7 boosting **directly inflates hit** (more match combinations per spin). The 3 components are coupled — cannot simultaneously achieve (pid9 ↓ + RTP 94 + hit ≤ 19).

**Designer recommendation**: User must accept ONE of:

### Option A: relax hit band [14, 22] (Recommended)
- v5 m1 lands at hit 20.92 — within widened [14, 22]
- All other v5 boundaries respected at max usage
- Cost: hit 21 is "above conventional classic 3-reel" (industry ~17-19% RWB) — but pid9 share down to 20% means user "wins are bigger when they hit" — narrative consistent

### Option B: re-target pid 9 share to [22, 24]%
- Loosen pid9 target by 2-3pp (from 20% → 22-24%)
- v5 m1 at hit ≤19 would land at pid9 ~27% — even softer
- Cost: pid9 not at user-pinned 20%

### Option C: relax archetype further (e.g., high7 ±40%, bar ±35%)
- v5 m1 already at 96-100% slack usage on high7/wild
- Extra slack would marginally reduce hit (e.g., wild cut to 0.5× could shave hit 0.5pp)
- Cost: archetype deviation grows further (already at ±25-30%)

### Option D: change paytable
- forbidden per universal §1.1
- listed only for completeness

## 6. Verify red-line 建议 (V agent)

**Conditional on user picking Option A**:
- [HIT] band: change to **[14, 22]** (was [14, 19])
- [BUCKET-GE1_5] new band: ge1_lt5 RTP-pp ∈ [18, 24] (current target 21.21, baseline 19.59)
- **[PID9-SHARE] NEW**: pid9 RTP / total RTP ∈ [19, 21]% (precise red line)
- [BOOSTER-HIER] ratio monotone, ≥ 1.0 (v5 amendment)
- [ARCHETYPE-HIGH7] ±30%: R1 high7 ∈ [9.98, 18.53], R3 ∈ [9.44, 17.54], R2 ∈ [8.93, 13.65]
- [ARCHETYPE-BAR] ±25%: each bar tier in [0.75, 1.25] × baseline
- [ARCHETYPE-WILD] ±30%: R1/R3 wild marginal in [0.7, 1.3] × baseline
- [REEL-ASYMMETRY] §12-M37 R3 ≤ R2 + 8pp slack (v5 amendment)
- §14 MID-PAY-VISIBLE-FLOOR ≥ 8% any-reel — v5 m1 passes (min 28.6%, far above)
- §2 BRAND-VISIBLE R2 high7 ≥ 8.93% — v5 m1 passes (13.02%)
- TOP-PATH-1000X via high7-grand-high7 — unchanged
- §13 BLANK-FLANK-DIVERSITY — strip locked
- All v3 finalized verify categories for m2/m5 unchanged
- m7: [HIT] m7 < m1 hit - 0.3pp safety (auto), MODE7-LOCK R2 booster shape drift ≤ 0.5pp

## 7. Files

- `_designer_scratch/v5_applier.py` — v5 7-D lever with all guards
- `_designer_scratch/v5_pareto.py` — Pareto explore script
- `_designer_scratch/v5_rec_m1.json` — m1 recommended weights
- `_designer_scratch/v5_rec_m7.json` — m7 sync weights

## 8. 一行 summary

**v5 hard targets pid9 ∈ [19,21]% + RTP ∈ [94,96] MET**: m1 RTP 94.09 / pid9 20.07% / hit **20.92 (1.92pp over hit [14,19] soft band — binding constraint)** / 1000× freq 1/24.5k. m7 sync RTP 84.89 / hit 14.25 / pid9 26.3% with HIT-MONOTONIC + MODE7-LOCK preserved. **Designer recommends hit band [14, 22] relaxation** (Option A) — physics min hit at hard targets is 20.24% even with archetype boundaries blown.
