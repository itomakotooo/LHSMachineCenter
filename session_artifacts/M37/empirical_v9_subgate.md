# Empirical sub-gate v9 (m7 cut-mode-feel restoration) — M37 — 2026-05-12

> **Analyst (A) agent, fresh context** per ONBOARDING §4. Stage 6 sub-gate: verify Designer v9 m7 analytic predictions + **CRITICAL multi-seed 5M MC RTP lower bound stress test** per X audit caveat 2 (RTP 84.011 vs floor 84.0 margin only 0.011pp).

## VERDICT: **FLAG — RTP lower bound stress test FAIL. Recommend Designer v9.1 re-tune (K_bar 0.83 instead of 0.82, target analytic RTP ~85).**

---

## 1. v9 m7 analytic verification

Designer v9 m7 weights at `session_artifacts/M37/v9_sim_weights/mode_7/weights.json` loaded via standard loader with shared `reel_strips.json`.

| Metric | design_v9_m7 §5 | analytic | drift |
|---|---|---|---|
| RTP | 84.011% | **84.0110%** | 0.000pp |
| Hit | 16.986% | **16.9856%** | -0.004pp |
| pid 9 share | 26.77% | **26.7739%** | +0.004pp |
| HIER ratio mini/minor | 1.272 | **1.272** | 0.000 |
| HIER ratio minor/major | 1.307 | **1.307** | 0.000 |
| HIER ratio major/grand | 13.6 | **13.62** | +0.02 |
| R2 mini marginal | 2.535% (×0.91) | **2.5355%** | +0.001pp |
| R2 minor marginal | 1.993% (byte-eq m1) | **1.9931%** | +0.000pp |
| R2 major marginal | 1.525% (byte-eq m1) | **1.5253%** | +0.000pp |
| R2 grand marginal | 0.112% (locked) | **0.1119%** | 0.000pp (locked) |
| R2 high7 marginal | 13.02% (byte-eq m1) | **13.0161%** | -0.004pp |
| R1 wild marginal | 1.247% (×1.00) | **1.2470%** | +0.000pp |
| R3 wild marginal | 1.264% (×1.00) | **1.2642%** | +0.000pp |
| R1 bar_sum marginal | ~52% (K_bar 0.82) | **48.69%** | (R1 1bar 14.61 / 2bar 12.66 / 3bar 12.66 / 7bar 8.76; sum 48.69 — Designer §5 "~52%" was approximate) |
| R3 bar_sum marginal | ~52% (K_bar 0.82) | **48.72%** | (R3 ~ same) |

### §4 per-pay ratio table (m7 v9 freq / m1 v5 freq)

| pid | tier | m7_freq | m1_freq | ratio | Designer claim | match |
|---|---|---|---|---|---|---|
| 1 (high7×3 → 1000×) | 顶 | 0.007022 | 0.007113 | **0.9871** | 0.987 | ✓ |
| 2 (7bar×3) | 中 | 0.001199 | 0.001747 | **0.6862** | 0.686 | ✓ (drift below 0.70 floor) |
| 3 (3bar×3) | 中 | 0.002561 | 0.003757 | **0.6815** | 0.682 | ✓ (drift below 0.70 floor) |
| 4 (2bar×3) | 中 | 0.002561 | 0.003757 | **0.6815** | 0.682 | ✓ (drift below 0.70 floor) |
| 5 (1bar×3) | 小 | 0.004150 | 0.006092 | **0.6813** | 0.681 | ✓ |
| 6 (any-7 mix) | 小 | 0.011179 | 0.013598 | **0.8221** | 0.822 | ✓ |
| 7 (any-bar) | 小 MAIN CUT | 0.080637 | 0.119846 | **0.6728** | 0.673 | ✓ cut delivered |
| 8 (grand-alone) | 顶 | 0.000762 | 0.000622 | **1.2255** | 1.225 | ✓ rises naturally |
| 9 (mixed) | mix | 0.059776 | 0.052638 | **1.1356** | 1.136 | ✓ |
| 102 (Major JP) | 大 | 0.000002 | 0.000002 | **1.0000** | 1.000 | ✓ |
| 103 (Minor JP) | 大 | 0.000003 | 0.000003 | **1.0000** | 1.000 | ✓ |
| 104 (Mini JP) | 大 | 0.000004 | 0.000004 | **0.9100** | 0.910 | ✓ K_mini |

**§1 verdict**: Designer v9 m7 analytic numbers reproduce EXACTLY (≤ 0.005pp drift on every metric). Designer's prediction infrastructure is trustworthy. **Numbers are NOT the issue — the issue is the design landed at the floor edge by design.**

---

## 2. Single-seed 50k + 200k MC

### 50k MC (seed=42)

| Metric | Analytic | MC 50k | Drift | Drift σ (analytic CV) |
|---|---|---|---|---|
| RTP | 84.0110 | 76.2100 | -7.80pp | **-1.95σ** (tail seed; SE under analytic CV = 7.84pp) |
| Hit | 16.9856 | 17.1620 | +0.18pp | +1.05σ |
| pid 9 share | 26.7739 | 30.5524 | +3.78pp | (high variance) |

50k seed=42 is a tail seed (typical for high CV ~11 distribution). The MC's own CI (4.76pp) under-estimates the true variance because tail seeds miss rare large-multiplier events.

### 200k MC (seed=12345)

| Metric | Analytic | MC 200k | Drift | Drift σ |
|---|---|---|---|---|
| RTP | 84.0110 | **85.7720** | +1.76pp | +0.88σ |
| Hit | 16.9856 | 16.8930 | -0.09pp | -1.10σ |
| pid 9 share | 26.7739 | 25.5147 | -1.26pp | within sampling noise |

200k MC RTP lands at 85.77 — above the floor by 1.77pp. Single-seed result, but consistent with analytic 84.01 plus seed noise.

**Single-seed result is unreliable for floor-margin questions because RTP standard error at 100k = 2.83pp under analytic CV 10.65.** Multi-seed mean is the only way to answer the question.

---

## 3. CRITICAL: Multi-seed MC — RTP lower bound stress test

### §3.1 7-seed initial batch (100k each = 700k spins)

| seed | RTP | hit | pid9 share | RTP vs floor 84.0 |
|---|---|---|---|---|
| 42 | 80.539 | 16.968 | 28.27 | **BELOW** (-3.46pp) |
| 12345 | 86.227 | 16.847 | 25.57 | above (+2.23pp) |
| 7 | 82.567 | 17.042 | 27.46 | **BELOW** (-1.43pp) |
| 9999 | 83.509 | 16.837 | 26.22 | **BELOW** (-0.49pp) |
| 31415 | 82.303 | 17.088 | 27.96 | **BELOW** (-1.70pp) |
| 27182 | 79.768 | 17.303 | 28.66 | **BELOW** (-4.23pp) |
| 16180 | 82.637 | 16.775 | 26.86 | **BELOW** (-1.36pp) |

**Initial 7-seed mean: RTP 82.51 (margin -1.49pp to floor); 6/7 seeds below floor. CI of mean [80.96, 84.06].**

This was suspicious — 6/7 below floor when parametric predicts ~50% — so I expanded the sample.

### §3.2 Expanded 50-seed × 100k = 5M spins (definitive)

Combined 7 initial + 14 follow-up + 29 final = **50 seeds × 100k = 5,000,000 total spins**.

| Statistic | Value |
|---|---|
| **Mean RTP** | **83.6190%** (analytic 84.0110; drift -0.392pp = -0.99σ — within statistical noise) |
| SE of mean | 0.3966 |
| **95% CI of mean** | **[82.8417, 84.3963]** (straddles floor) |
| Stdev across seeds | 2.8042 (consistent with expected SE under CV 10.65 at 100k) |
| RTP range across seeds | [77.94, 89.22] |
| **Margin of mean to floor (84.0)** | **-0.381pp** |
| **Seeds below floor** | **30/50 (60.0%)** |
| Empirical P(seed RTP < 84.0) | 0.600 |
| Parametric P(seed @100k < 84.0) under N(84.011, 2.83) | 0.499 |

### §3.3 Sanity check — is this engine bias or sampling noise?

| Check | Result | Interpretation |
|---|---|---|
| 1000× hit count @3M spins | 140 observed vs 122.5 expected (+1.6σ above) | Rare big-hit bucket is slightly OVER-counted, ruling out engine missing big wins |
| Mean RTP drift sigma | -0.99σ from analytic | Within 2σ — not a systematic bias, but a real seed-distribution tail |
| Drift consistency with v8 sub-gate | v8 m7 700k drift was +1.29pp (+0.87σ from analytic 85.02 → mean 86.31) | High-variance noise expected on CV~11 m7 mode — direction is seed-dependent |
| Hit mean | 17.0036 (analytic 16.9856; drift +0.018pp) | exact match — confirms engine sampling is correct |

**Conclusion**: The mean RTP drift -0.39pp at 5M is **statistical noise (-0.99σ), not engine bias**. But the **operational fact remains**: with analytic at 84.011 and CV 10.65, **60% of operational 100k slot sessions will land RTP < 84.0**. This is the result the X audit warned about.

### §3.4 RTP stress test verdict

Per spawn brief §3:
- "If multi-seed mean RTP < 84.0 → FLAG, Designer needs v9.1 re-tune"
- "If multi-seed mean RTP ≥ 84.1 (small buffer) → ✓ SHIP"
- **Mean RTP = 83.619 → FAILS BOTH conditions**

| Test | Required | Actual | Status |
|---|---|---|---|
| Mean RTP ≥ 84.0 | strict floor | **83.619** | **FAIL** (-0.381pp below) |
| 95% CI lower of mean ≥ 84.0 | strict | 82.842 | **FAIL** |
| Empirical P(seed < 84.0) | ideally low | 0.600 | **FAIL** |
| Mean RTP ≥ 84.1 (sub-gate ship buffer) | comfort | **83.619** | **FAIL** |

**§3 STRESS TEST: FAIL**

---

## 4. Hit ceiling check

### Analytic
- Analytic m7 hit: 16.9856%
- Universal §9 ceiling (m1 hit 20.92 - 0.3pp safety): **20.62%**
- Margin: **+3.6344pp** comfortable

### Multi-seed empirical (50 seeds × 100k = 5M spins)
- Hit mean: **17.0036%** (essentially equal to upper band 17.0)
- Hit stdev across seeds: 0.1363
- 95% CI of mean: [16.97, 17.04]
- Hit range: [16.70, 17.30]
- Seeds with hit > 17.0: **25/50 (50%)**
- Seeds with hit > 20.62 (universal §9): **0/50** ✓
- Max single seed hit: 17.303 (margin to 20.62: +3.32pp)

**Hit ceiling §9 PASS comfortable** (3.32pp+ margin). 

**BUT — Hit upper band 17.0 secondary observation**: design_v9_m7 brief states m7 hit ∈ [14, 17] as "non-negotiable". Hit mean lands exactly at 17.0036 — **50% of seeds will be above the 17 upper band**. This may also need Designer attention but is informational since the primary "non-negotiable" was the §9 safety distance from m1 (3.93pp gap), not the absolute hit < 17 number.

---

## 5. m1 / m2 / m5 invariance check

### m1 byte-equality (v5 ship'd)

| Check | Result |
|---|---|
| Byte diffs m1 ship'd vs m1 v5 sim | **0** |
| m1 analytic RTP | 94.0925 (matches design_v5 94.09 ✓) |
| m1 analytic hit | 20.9180 (matches design_v5 20.92 ✓) |
| m1 analytic pid 9 share | 20.0650 (matches design_v5 20.07 ✓) |

### m2 / m5 untouched (v6 state preserved)

| Check | Result |
|---|---|
| MODE5-BASE-LOCK m5 vs m2 | 1 byte diff at [1][23] (grand m2=52, m5=166), 77/78 byte-eq ✓ |
| m2 v6 analytic | RTP 303.4522 / hit 32.2137 / pid9 20.3664 (byte-identical to v6 sub-gate) |
| m5 v6 analytic | RTP 507.5561 / hit 33.0857 / pid9 12.0198 (byte-identical to v6 sub-gate) |

**m1/m2/m5 fully invariant. v9 work touched only m7.**

---

## 6. Cross-mode invariants empirical

| Invariant | Required | Empirical | Status |
|---|---|---|---|
| RTP-MONOTONIC m7 < m1 < m2 < m5 | strict | m7 mean 83.62 < m1 94.69 < m2 307.53 < m5 506.63 | **PASS** |
| HIT-MONOTONIC m1 > m7 + 0.3pp | safety | m1 analytic 20.92 - m7 mean 17.00 = +3.92pp | **PASS** (huge margin per Designer cut-mode-feel goal) |
| 1000× freq m1 ≈ m7 < m2 < m5 | escalating | m1 analytic 1/24,494, m7 v9 analytic 1/24,494, m2 1/9,032, m5 1/2,866 | **PASS** (m1 ≈ m7 by design — R2 high7 + R1/R3 high7 + grand all byte-eq m1) |
| MODE5-BASE-LOCK m5 base byte-eq m2 base except R2 grand [1][23] | exact | 1 byte diff at correct position | **PASS** |
| MODE7-LOCK tier 1 (m7 R2 booster drift vs m1 v5 ≤ 0.5pp) | strict | mini 0.251 / minor 0.000 / major 0.000 / grand 0.000 | **PASS** (all ≤ 0.5pp) |

### MODE7-LOCK drift detail

| Booster | m1 v5 | m7 v9 | drift | tier 1 |
|---|---|---|---|---|
| mini | 2.7863% | 2.5355% | 0.2508 | ✓ |
| minor | 1.9931% | 1.9931% | **0.0000** | ✓ (byte-eq m1) |
| major | 1.5253% | 1.5253% | **0.0000** | ✓ (byte-eq m1) |
| grand | 0.1119% | 0.1119% | **0.0000** | ✓ (locked) |

minor + major byte-eq m1 v5 (Designer Opt: middle-tier preserve per §4 — booster-alone mid-pay paths intact).

---

## 7. Verdict

### **§3 RTP lower bound stress test: FAIL**

Multi-seed 5M spin definitive test confirms X audit caveat 2 was correct:
- **Mean RTP at 5M sample = 83.619** (margin -0.381pp BELOW floor 84.0)
- **60% of operational seeds land below 84.0**
- 95% CI of mean [82.84, 84.40] straddles floor with majority below
- Even the most-optimistic mean (CI upper 84.40) leaves only 0.40pp buffer
- This is NOT engine bias — drift -0.99σ is statistically consistent with no bias — it's the **design landing at the floor edge by construction**

### All other gates PASS

| Test | Status | Notes |
|---|---|---|
| §1 Analytic vs design_v9 | ✅ Exact match (≤ 0.005pp) |
| §1 §4 per-pay ratio table | ✅ All 12 pids match Designer claim |
| §2 50k + 200k MC | ✅ Single-seed within sampling noise of analytic |
| **§3 RTP lower bound stress** | **❌ FAIL** | Mean below floor |
| §4 Hit ceiling §9 (20.62) | ✅ PASS comfortable (3.3pp+ margin) |
| §5 m1 invariance | ✅ 0 byte diffs |
| §5 m2/m5 untouched | ✅ byte-identical to v6 |
| §6 RTP-MONOTONIC | ✅ |
| §6 HIT-MONOTONIC m1-m7 | ✅ +3.92pp (huge cut-mode-feel margin) |
| §6 1000× freq m1 ≈ m7 < m2 < m5 | ✅ |
| §6 MODE5-BASE-LOCK | ✅ |
| §6 MODE7-LOCK tier 1 | ✅ (worst drift mini 0.25pp ≤ 0.5pp ceiling) |

### Secondary observation — Hit upper band 17.0

Hit mean lands at **17.0036**, with 50% of seeds above 17.0. This is the second tight margin alongside the RTP floor. v9.1 retune should consider both.

---

## 8. Recommendation to main session

### **NO-SHIP v9 as-is. Designer v9.1 re-tune required.**

#### Suggested v9.1 directions (per spawn brief §7):

**Option A: K_bar = 0.83 (gentle relaxation)**
- Reduces R1+R3 bar cut intensity from 0.82× to 0.83×
- Expected analytic RTP: ~85% (from grid sweep data in Designer §4, "K_bar 0.823, K_wild 0.98, K_mini 0.91" → RTP 84.017 was on the edge; bumping K_bar to 0.83 should land RTP ~85)
- Trade: hit rises slightly (back near 17.10 — over upper band 17)
- pid 2/3/4 ratio rises toward 0.70 (better §4 mid preserve)
- Need user to accept hit > 17 OR explicit hit band amend to [14, 17.5]

**Option B: K_bar = 0.825 + K_mini = 0.95**
- Slightly less bar cut + slightly less mini cut
- Both directions push RTP up
- May land RTP 84.3-84.5 (small buffer)
- Hit ~17.05 (still borderline)

**Option C: Accept pid 2/3/4 ratio 0.65 floor + K_bar 0.83**
- Even deeper structural trade on mid-bar (vs current 0.68)
- Allows K_bar = 0.83 → RTP ~85, hit 17.1
- Requires brief amend pid 2/3/4 floor to 0.65

**Option D: Brief amend RTP floor to 83.5 + accept current v9**
- User decision: relax floor from 84.0 to 83.5
- Current analytic 84.01 + mean 83.62 → comfortable under 83.5 amended floor
- No design re-tune needed
- Cost: m7 RTP narratively "weaker cut mode" loses some structure

X strong recommendation in critic_review_v9 §4 was "Option (a) defer to A empirical sub-gate; if mean < 84 → v9.1". **A confirms mean < 84 (with 60% empirical below-floor rate). v9.1 escalation triggered per X process.**

---

## 9. Drift > 2σ scan

Scanned across all sample sizes:

| Sample | Metric | Drift σ (using analytic CV) | Notes |
|---|---|---|---|
| m7 v9 50k seed=42 | RTP | -1.95σ | tail seed, expected |
| m7 v9 200k seed=12345 | RTP | +0.88σ | within noise |
| m7 v9 700k 7-seed mean | RTP | -1.40σ | tail batch |
| m7 v9 2.1M 21-seed mean | RTP | -0.01σ | converged to analytic |
| m7 v9 5M 50-seed mean | RTP | **-0.99σ** | **within 1σ — NOT engine bias, sampling tail** |
| m7 v9 5M 50-seed mean | Hit | +0.13σ | clean |
| m7 v9 5M 50-seed mean | pid 9 share | +0.18σ | clean |

**No drift > 2σ at sample sizes where convergence is meaningful.** No engine/analyzer divergence detected. **The §3 stress test FAIL is NOT a drift issue — it's a design margin issue.**

---

## 10. 100-word summary

**v9 m7 empirical sub-gate FLAG — RTP lower bound stress test FAIL.** Designer v9 analytic reproduces EXACTLY (RTP 84.011, hit 16.986, pid9 26.77%, all within 0.005pp). 50-seed × 100k = 5M MC mean RTP = **83.619** (-0.381pp below 84.0 floor, -0.99σ drift = statistical noise not engine bias). **60% of seeds (30/50) land RTP < 84.0** — confirms X audit caveat 2. CI of mean [82.84, 84.40] straddles floor. Hit ceiling §9 (20.62) PASS comfortable (3.3pp+ margin). m1/m2/m5 untouched. Cross-mode invariants PASS. **Recommend Designer v9.1: bump K_bar 0.82 → 0.83 (analytic RTP ~85, real buffer), OR amend RTP floor to 83.5, OR explicit user pivot.**

## 11. Files

- `session_artifacts/M37/scripts/empirical_v9_subgate.py` — main runner (analytic + 50k + 200k + 7×100k initial multi-seed + cross-mode invariants + per-pay §4 table)
- `session_artifacts/M37/scripts/empirical_v9_subgate.out.txt` — initial run console output (477 lines)
- `session_artifacts/M37/scripts/v9_rtp_followup.py` — +14 seeds (21 total × 100k = 2.1M)
- `session_artifacts/M37/scripts/v9_rtp_final.py` — +29 seeds (50 total × 100k = 5M) definitive RTP stress test
- `session_artifacts/M37/v9_sim_weights/mode_7/weights.json` — v9 m7 weights (unchanged, loaded)
- `slot_designer/machines/M37/weights/mode_1/weights.json` — m1 v5 ship'd (invariance confirmed)
- `session_artifacts/M37/v6_sim_weights/mode_{2,5}/weights.json` — m2/m5 v6 ship state (untouched verify)
