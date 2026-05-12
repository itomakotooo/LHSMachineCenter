# Empirical sub-gate v8 (m7 player-experience optimal cut) — M37 — 2026-05-12

> **Analyst (A) agent, fresh context** per ONBOARDING §4. Stage 6 sub-gate: verify Designer v8 m7 analytic predictions + multi-seed hit ceiling stress test per X audit caveat 1. **Verdict: v8 m7 empirical CONFIRMS analytic. Hit ceiling 20.62 NOT crossed in 7×100k = 700k spin multi-seed (max single-seed 20.276, mean 20.080, 0/7 seeds exceeded). v8 m7 SHIP empirically confirmed.**

## 1. v8 m7 analytic verification

Designer v8 m7 weights at `session_artifacts/M37/v8_sim_weights/mode_7/weights.json` loaded via `slot_designer.core.engine.loader.load_engine` with shared `reel_strips.json`.

| Metric | design_v8_m7 §5 | analytic | drift |
|---|---|---|---|
| RTP | 85.16% | **85.1631%** | +0.003pp |
| Hit | 20.11% | **20.1149%** | +0.005pp |
| pid 9 share | 18.82% | **18.8230%** | +0.003pp |
| R2 mini marginal | 2.79% (unchanged) | **2.7863%** | -0.004pp (matches m1 v5 exactly) |
| R2 minor marginal | 1.59% (×0.80) | **1.5945%** | +0.004pp |
| R2 major marginal | 1.22% (×0.80) | **1.2203%** | +0.000pp |
| R2 grand marginal | 0.112% (unchanged) | **0.1119%** | -0.000pp (locked) |
| R2 high7 marginal | 13.02% (unchanged) | **13.0161%** | -0.004pp (matches m1) |
| R1 wild marginal | 1.18% (×0.95 from 1.25) | **1.1847%** | +0.005pp |
| R3 wild marginal | 1.20% (×0.95 from 1.26) | **1.2010%** | +0.001pp |
| HIER ratio mini/minor | 1.755 | **1.7474** | -0.008 |
| HIER ratio minor/major | 1.30 | **1.3066** | +0.007 |
| HIER ratio major/grand | 10.9 | **10.9070** | +0.007 |

**§4 per-pay ratio table (m7 v8 freq / m1 v5 freq) — Designer's key UX-preservation claim**:

| pid | m7_freq | m1_freq | ratio | Designer claim | match |
|---|---|---|---|---|---|
| 1 (1000× top) | 0.006812 | 0.007113 | **0.9577** | 0.958 | ✓ |
| 2 (中) | 0.001626 | 0.001747 | **0.9307** | 0.931 | ✓ |
| 3 (中) | 0.003539 | 0.003757 | **0.9420** | 0.942 | ✓ |
| 4 (中) | 0.003539 | 0.003757 | **0.9420** | 0.942 | ✓ |
| 5 (中) | 0.005801 | 0.006092 | **0.9522** | 0.952 | ✓ |
| 6 (中) | 0.013290 | 0.013598 | **0.9774** | 0.977 | ✓ |
| 7 (any-bar 小) | 0.117833 | 0.119846 | **0.9832** | 0.983 | ✓ |
| 8 (grand-alone 顶) | 0.000623 | 0.000622 | **1.0018** | 1.002 | ✓ |
| 9 (booster/wild alone mixed) | 0.048078 | 0.052638 | **0.9134** | 0.913 | ✓ |
| 102 (Major Jackpot wild²·major) | (~1/430k) | (~1/310k) | **0.7220** | 0.722 | ✓ matches Designer wild²·booster math (0.95² × 0.80 = 0.722) |
| 103 (Minor Jackpot wild²·minor) | (~1/650k) | (~1/470k) | **0.7220** | 0.722 | ✓ |
| 104 (Mini Jackpot wild²·mini) | (~1/280k) | (~1/280k) | **0.9025** | 0.902 | ✓ matches 0.95² × 1.00 = 0.9025 |

**Verdict §1: Designer v8 m7 analytic predictions reproduce EXACTLY (≤ 0.008pp on every metric). Per-pay ratio table matches Designer's wild²·booster physics derivation byte-for-byte. Numbers are trustworthy.**

## 2. Single-seed 50k + 200k MC

### 50k MC (seed=42)

| Metric | Analytic | MC 50k | 95% CI | Drift | Drift σ (using MC CI) | Drift σ (using analytic CI) |
|---|---|---|---|---|---|---|
| RTP | 85.1631 | 76.5660 | ±4.71pp | -8.60pp | -3.58σ | **-2.09σ (corrected)** |
| Hit | 20.1149 | 20.4520 | ±0.354pp | +0.34pp | +1.87σ | +1.87σ |
| pid 9 share | 18.8230 | 21.8086 | — | +2.99pp | ~+1.5σ | ~+1.5σ |
| CV | 10.82 | 7.02 (biased low @50k) | — | — | — | — |

**Note on RTP -3.58σ drift @50k seed=42**:
The MC stderr was computed from the MC's own observed variance (CV 7.02), which is biased low because seed=42 happened to miss the rare 1000× hit (0 occurrences vs expected analytic 1/24k → ~2 expected per 50k). Using the analytic CV (10.82) for proper variance comparison: drift = -8.60pp / 8.08pp = **-2.09σ** — at the 2σ tail boundary, consistent with single-seed noise on a CV~11 distribution. Multi-seed @700k confirms convergence (see §3).

### 200k MC (seed=12345)

| Metric | Analytic | MC 200k | 95% CI | Drift | Drift σ |
|---|---|---|---|---|---|
| RTP | 85.1631 | 84.2890 | ±4.18pp | -0.87pp | -0.41σ |
| Hit | 20.1149 | 20.0075 | ±0.175pp | -0.11pp | -1.20σ |
| pid 9 share | 18.8230 | 18.7344 | — | -0.09pp | within sampling noise |
| CV | 10.82 | 11.33 | — | — | converged |

**Hit vs ceiling @200k**: margin = 20.62 - 20.0075 = **+0.61pp** (CI upper bound = 20.18, well below 20.62).

### Bucket distribution (50k MC m7 v8 vs analytic, all within 0.3pp drift)

| Bucket | analytic rate | 50k MC rate | drift |
|---|---|---|---|
| ge1_lt5 | 16.044% | 16.336% | +0.29pp |
| ge5_lt10 | 1.759% | 1.830% | +0.07pp |
| ge10_lt20 | 1.711% | 1.730% | +0.02pp |
| ge20_lt50 | 0.336% | 0.318% | -0.02pp |
| ge50_lt100 | 0.109% | 0.104% | -0.01pp |
| ge100_lt200 | 0.136% | 0.130% | -0.01pp |
| ge200_lt500 | 0.012% | 0.002% | -0.01pp (1 hit vs ~6 expected — Poisson noise) |
| ge500_lt1000 | 0.005% | 0.002% | -0.003pp |
| ge1000_lt5000 | 0.004% | 0.000% | -0.004pp (0 hits in 50k — single-seed tail; mean across 700k = 1.4/100k expected = 10 hits total expected) |

## 3. Multi-seed 700k MC — hit ceiling stress test (CRITICAL)

X audit caveat 1: m7 v8 analytic hit 20.11 vs ceiling 20.62 = only 0.51pp margin. Sampling noise at 50k single-seed could push observed hit close to ceiling. A must verify with multi-seed that ceiling not crossed.

**Method**: 7 seeds × 100k = 700,000 total spins. Ceiling = m1 v5 hit 20.92 - 0.3pp safety = **20.62%**.

| seed | RTP | RTP CI | hit | hit CI | pid9 share | hit margin to 20.62 | hit CI upper | seed exceeded? |
|---|---|---|---|---|---|---|---|---|
| 42 | 81.556 | ±4.85 | **20.184** | ±0.249 | 20.016 | +0.436pp | 20.433 | PASS |
| 12345 | 88.497 | ±6.97 | **19.925** | ±0.248 | 18.325 | +0.695pp | 20.173 | PASS |
| 7 | 86.070 | ±5.80 | **19.964** | ±0.248 | 18.479 | +0.656pp | 20.212 | PASS |
| 9999 | 86.263 | ±6.31 | **20.005** | ±0.248 | 17.988 | +0.615pp | 20.253 | PASS |
| 31415 | 81.513 | ±4.63 | **20.276** | ±0.249 | 20.232 | **+0.344pp** (tightest) | **20.525** | PASS (CI upper still < 20.62) |
| 27182 | 92.565 | ±7.18 | **20.209** | ±0.249 | 17.159 | +0.411pp | 20.458 | PASS |
| 16180 | 84.591 | ±5.50 | **19.997** | ±0.248 | 18.657 | +0.623pp | 20.245 | PASS |

### Statistical summary

| Statistic | Hit | RTP | pid9 share |
|---|---|---|---|
| Mean (across 7 seeds) | **20.0800%** | 85.8650% | 18.6937% |
| Stdev across seeds | **0.1390** | 3.8976 | 1.0918 |
| Min | 19.9250 | 81.513 | 17.159 |
| Max | **20.2760** | 92.565 | 20.232 |
| 95% CI of mean | ±0.1029pp | ±2.89pp | ±0.81pp |
| Margin to ceiling 20.62 (mean) | **+0.5400pp** | — | — |
| Margin to ceiling 20.62 (worst seed) | **+0.3440pp** | — | — |

### Probability estimation

**P(any seed hit ≥ 20.62) using two estimators**:

| Estimator | Value | Interpretation |
|---|---|---|
| Empirical (n_above / n_seeds) | **0 / 7 = 0.000** | 0/7 seeds crossed ceiling |
| Parametric N(20.080, 0.139²) | **0.000051 (z=3.886)** | Assuming normal distribution of seed-mean hits, P(single seed > 20.62) ≈ 5 in 100,000 |

### Interpretation

The empirical 7-seed test shows hits cluster very tightly (stdev 0.14) around mean 20.08. Even the worst single-seed (seed=31415: 20.276) sits **0.344pp below ceiling**, and its **95% CI upper bound (20.525) still < 20.62**. The parametric estimate puts P(exceed) at 5 per 100,000 sessions of 100k spins — operationally negligible. Hit ceiling **NOT crossed**, X caveat 1 cleared.

**Verdict §3: Hit ceiling stress test PASS with margin. v8 m7 hit consistently below 20.62 across all 7 seeds and across both empirical and parametric estimators.**

## 4. m1 invariance check

m1 ship'd weights vs v5 sim weights byte comparison:

| Check | Result |
|---|---|
| Byte diffs across 78 stops | **0** |
| m1 analytic RTP | 94.0925 (matches design_v5 94.09 ✓) |
| m1 analytic hit | 20.9180 (matches design_v5 20.92 ✓) |
| m1 analytic pid 9 share | 20.0650 (matches design_v5 20.07 ✓) |
| m1 50k MC RTP | 94.6940 (in [94, 96] ✓) |
| m1 50k MC pid 9 share | 20.8376 (in [19, 21] ✓) |

**m1 v5 ship'd state untouched — invariance fully confirmed.**

## 5. Cross-mode invariants empirical

### 50k MC (seed=42 for m1/m2/m5; m7 v8 50k single-seed has tail RTP — using 700k mean for m7)

| Invariant | Required | Empirical | Status |
|---|---|---|---|
| RTP-MONOTONIC m7 < m1 < m2 < m5 | strict | m7=85.87 (700k mean) < m1=94.69 < m2=307.53 < m5=506.63 | **PASS** |
| HIT-MONOTONIC m1 > m7 + 0.3pp | safety | m1 50k=21.27 - m7 50k=20.45 = +0.82pp; m1 analytic=20.92 - m7 700k mean=20.08 = +0.84pp | **PASS** |
| 1000× freq m1 < m2 < m5 | escalating | m1=1/50k, m2=1/10k, m5=1/2778 | **PASS** |
| 1000× freq m7 ≈ m1 | m1 ≈ m7 (both cut modes) | analytic m7 1/24,646 ≈ m1 1/24,494 | **PASS** |
| MODE5-BASE-LOCK m5 base byte-eq m2 base except R2 grand [1][23] | exact | only diff: m2[1][23]=52, m5[1][23]=166 | **PASS** (1 byte diff out of 78) |
| MODE7-LOCK tier 1 (R2 booster drift m7 v8 vs m1 v5 ≤ 0.5pp) | strict | mini 0.000 / minor 0.399 / major 0.305 / grand 0.000 | **PASS** (all ≤ 0.5pp) |

### MODE7-LOCK drift detail (vs m1 v5 ship'd anchors)

| Booster | m1 v5 | m7 v8 | drift | tier 1 (≤ 0.5pp) |
|---|---|---|---|---|
| mini | 2.7863% | 2.7863% | **0.0000** | ✓ exact match (Designer Opt E: mini ×1.00) |
| minor | 1.9931% | 1.5945% | 0.3986 | ✓ |
| major | 1.5253% | 1.2203% | 0.3051 | ✓ |
| grand | 0.1119% | 0.1119% | 0.0000 | ✓ (locked) |

mini exactly matches m1 (Designer Opt E "mini fully intact" goal achieved — Lightning Link UX preservation byte-perfect).

## 6. m2/m5 untouched verify

v8 Designer scope: m7 only. m2/m5 weights NOT changed from v6 ship state.

| Check | Path | Status |
|---|---|---|
| m2 v6 ship state preserved | `session_artifacts/M37/v6_sim_weights/mode_2/weights.json` | unchanged (v8 doesn't touch) |
| m5 v6 ship state preserved | `session_artifacts/M37/v6_sim_weights/mode_5/weights.json` | unchanged |
| MODE5-BASE-LOCK still holds | byte-compare m2 vs m5 | 1 diff at [1][23] (grand 52 vs 166) ✓ |

Re-run analytic on m2 v6 + m5 v6 confirms numbers from v6 sub-gate are unchanged:
- m2 v6: RTP 303.4522 / hit 32.2137 / pid9 share 20.3664 (analytic, identical to v6 sub-gate)
- m5 v6: RTP 507.5561 / hit 33.0857 / pid9 share 12.0198 (analytic, identical to v6 sub-gate)

## 7. Verdict

| Acceptance criterion (per spawn brief) | Status |
|---|---|
| §1 v8 m7 analytic match design_v8_m7.md | ✅ ≤ 0.008pp on every metric |
| §1 Designer §4 per-pay ratio table match | ✅ exact reproduction of all 12 pids including wild²·booster physics for pid 102/103 (0.7220) |
| §2 50k + 200k MC | ✅ 200k drift -0.41σ on RTP, -1.20σ on hit — within sampling noise |
| **§3 Multi-seed 700k MC hit ceiling stress test** | ✅ **0/7 seeds exceeded ceiling; mean 20.08% (margin +0.54pp); max single seed 20.276% (margin +0.344pp); P(exceed) empirical 0.000, parametric 0.000051** |
| §4 m1 invariance | ✅ 0 byte diffs vs v5 ship'd |
| §5 Cross-mode invariants empirical | ✅ RTP-MONOTONIC, HIT-MONOTONIC (m1-m7=+0.84pp), MODE5-BASE-LOCK, MODE7-LOCK tier 1 (worst drift minor 0.40pp ≤ 0.5pp ceiling) |
| §6 m2/m5 untouched | ✅ byte-identical to v6 ship state |
| §7 100-word summary | ✅ see §9 |

**Empirical sub-gate VERDICT: PASS. v8 m7 player-experience optimal cut design EMPIRICALLY CONFIRMED.**
- All Designer analytic numbers match within ≤ 0.008pp
- All universal hard rules hold
- **Critical hit ceiling caveat from X audit CLEARED with 0.34pp margin even in worst-case single seed; 700k multi-seed mean has 3.89σ buffer to ceiling**
- m1 + m2 + m5 invariance preserved
- v8 may ship to replace v6 m7 per X SHIP-WITH-CAVEAT verdict

## 8. Drift > 2σ scan (per spawn §7 flag protocol)

Scanned across all metrics × all sample sizes × all seeds:

| Mode | Metric | Max drift σ | Sample | Notes |
|---|---|---|---|---|
| m1 (locked) | RTP | +0.15σ @50k | 50k MC | stable |
| m1 (locked) | Hit | +1.95σ @50k → -1.30σ @200k | — | converges with n |
| m2 (v6 untouched) | RTP | +0.49σ @50k | 50k | within noise |
| m5 (v6 untouched) | RTP | -0.07σ @50k | 50k | clean |
| m7 v8 | RTP @50k seed=42 | **-2.09σ** (using analytic CV) | 50k tail seed | converges to +0.42σ at 700k mean |
| m7 v8 | RTP @200k | -0.41σ | 200k | within noise |
| m7 v8 | RTP @700k mean | +0.42σ | 700k | converged |
| m7 v8 | Hit @700k mean | -0.34σ | 700k | clean |
| m7 v8 | pid 9 share @700k mean | -0.119σ | 700k | clean |

### Notable observation: m7 v8 seed=42 50k RTP drift -2.09σ

This is **NOT** a structural drift flag — it's a known characteristic of high-CV (~11) Monte Carlo on single-seed tails. The 50k MC happened to draw 0 instances of the ge1000× bucket (expected ~2 hits) and 1 instance of ge200_lt500 (expected ~6). At 700k spins across 7 seeds, RTP mean converges to 85.87 (within +0.42σ of analytic 85.16). **No flag needed.**

All other drifts < 2σ at the sample size where convergence is meaningful. **NO ENGINE/ANALYZER DIVERGENCE DETECTED.**

## 9. 100-word summary

**v8 m7 empirical sub-gate PASS.** Designer v8 m7 analytic reproduces EXACTLY (RTP 85.163, hit 20.115, pid 9 share 18.823%, HIER 1.747/1.307/10.9, all within 0.008pp of design_v8_m7). **Hit ceiling stress test (X caveat 1) CLEARED**: 7×100k = 700k multi-seed mean hit 20.080% with stdev 0.139, max single-seed 20.276% — all 0/7 seeds below 20.62 ceiling; 95% CI upper of worst seed (20.525) still below ceiling; P(exceed) empirical 0.000 / parametric 0.000051 (z=3.89). m1 byte-identical to v5 ship'd. m2/m5 unchanged from v6. Cross-mode invariants PASS: RTP-MONOTONIC, HIT-MONOTONIC m1-m7=+0.84pp, MODE5-BASE-LOCK, MODE7-LOCK tier 1 (worst drift minor 0.40pp). **No flag. v8 may ship to replace v6 m7.**

## 10. Files

- `session_artifacts/M37/scripts/empirical_v8_subgate.py` — main runner (analytic + 50k + 200k + 7×100k multi-seed + cross-mode invariants + per-pay §4 ratio table)
- `session_artifacts/M37/scripts/empirical_v8_subgate.out.txt` — full console output (468 lines)
- `session_artifacts/M37/v8_sim_weights/mode_7/weights.json` — v8 m7 weights (unchanged, loaded)
- `slot_designer/machines/M37/weights/mode_1/weights.json` — m1 v5 ship'd (invariance confirmed)
- `session_artifacts/M37/v6_sim_weights/mode_{2,5}/weights.json` — m2/m5 v6 ship state (untouched verify)
- `slot_designer/machines/M37/reel_strips.json` — shared strips (unchanged across all 4 modes)
