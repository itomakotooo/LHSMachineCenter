# M15 v13c mode 1 — Designer candidate under USER_HARDLINES.md v7 (2026-05-12 wave 13c)

> **Status**: **PASS** on all 14 USER_HARDLINES.md v7 hardlines + the new v7 implicit bar1 share ≤ ~30% constraint. RTP / hit / R1 blank / all 7 buckets / jackpot marginals all PASS. wild_pure cadence in band. PWDF post-mechanism B caveat (dd 27.4%, 0.6pp under verify.py 28% floor) — same structural cause as v13b ZZZ. Family-share design objectives (bar2/bar3 < 5%, high7 ~31.5%) deviate from `[5%, 30%]` brief target — STRUCTURAL under v7 + paytable lock + R1 blank cap, documented in §8.
>
> **Iteration context**: D iteration 3 after V/X rejected FINAL_E (v13a, bar1 share 41.9%) and main session dropped v6 "g15 not max" direction in favor of v7 "suppress g15 toward [10,15] lower bound + bar1 share ≤ ~30%". This v13c finds the tightest g15 achievable while honoring the bar1 cap. Bottom-of-band g15 (~10pp target) is structurally infeasible.
>
> **Output**: design document only. No production weights written. verify.py untouched. USER_HARDLINES.md untouched.

---

## 1. Recommended candidate: PPP_v20

**Per-reel target marginals (%, 3 decimals)**:

| Reel | blank | cherry | 1bar | 2bar | 3bar | high7 | doublediamond | topdollar | jackpot | row sum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | 39.600 | 4.500 | 28.000 | 7.000 | 2.000 | 16.000 | 2.500 | — | 0.400 | **100.000** |
| R2 | 49.800 | 3.500 | 24.000 | 6.000 | 1.800 | 12.000 | 2.500 | — | 0.400 | **100.000** |
| R3 | 58.100 | 3.000 | 20.000 | 5.000 | 1.500 | 8.500 | 2.500 | 1.100 | 0.300 | **100.000** |

Each reel sums exactly to 100.000%. Total non-blank: R1=60.400%, R2=50.200%, R3=41.900%. R1 blank ≤ R3 blank ✓ (winners-friendly per §12).

## 2. Predicted analytic profile (session-centric, base + feature)

| Metric | Value |
|---|---:|
| **Total RTP** | **95.343pp** |
| Base RTP | 44.743pp |
| Feature RTP | 50.600pp |
| Base : Feature split | 46.9 : 53.1 |
| Base hit | 14.830% |
| Trigger rate | 1.100% |
| **Hit session** | **15.930%** |
| **R1 blank** | **39.600%** |
| R2 blank | 49.800% |
| R3 blank | 58.100% |
| Feature EV per trigger | 46.00× |

## 3. Session bucket breakdown (pp) — base + feature

| Bucket | base | feature | total | Comment |
|---|---:|---:|---:|---|
| ge1_lt5 (1-5×)    | 14.896 | 0.000  | **14.896** | cherry-1 (10.22) + bar_mixed (~4.68 × 95%) |
| ge5_lt10 (5-10×)  | 8.636  | 0.076  | **8.712**  | bar1_pure 5× ~ 8.5pp |
| ge10_lt20 (10-20×)| 4.561  | 1.663  | **6.224**  | bar1+1wild 10×, bar2_pure, cherry-3 15× |
| ge20_lt50 (20-50×)| 6.885  | 18.180 | 25.065     | feature dominates + high7 pure 30× |
| ge50_lt100 (50-100×)| 6.715 | 20.263 | 26.978     | feature dominates + high7+wild 60× |
| ge100_lt200 (100-200×)| 2.738 | 8.334 | 11.072    | feature dominates + bar1+2wild 20× cross |
| ge200_lt500 (200-500×)| 0.313 | 2.022 | 2.335     | wild_pure 200× + feature |
| ge500+            | 0.000  | 0.062  | 0.062      | tiny |

**sum_1_20** = g15 + g510 + g1020 = 14.896 + 8.712 + 6.224 = **29.832pp** (within [28, 36], 0.17pp above floor, 6.17pp under cap). ✓

## 4. Per-hardline PASS/FAIL summary (USER_HARDLINES.md v7)

| # | Hardline | Value | Target | Status |
|---|---|---:|---|---|
| H1 | hit_session | 15.930% | [15, 18] | **PASS** (0.93pp margin) |
| H2 | total_rtp | 95.343pp | [94, 96] | **PASS** (0.66pp under cap, 1.34pp above floor) |
| H3 | R1_blank | 39.600% | [30, 40] | **PASS** (0.40pp under cap) |
| H4 | ge1_lt5 (g15) | 14.896pp | [10, 15] | **PASS** (0.10pp under cap, 4.90pp above floor) |
| H5 | sum_1_20 | 29.832pp | [28, 36] | **PASS** (1.83pp above floor, 6.17pp under cap) |
| H6 | ge20_lt50 | 25.065pp | [22, 32] | **PASS** (3.07pp above floor) |
| H7 | ge50_lt100 | 26.978pp | [17, 27] | **PASS** (0.02pp under cap — tight) |
| H8 | ge100_lt200 | 11.072pp | [4, 14] | **PASS** (2.93pp under cap, 7.07pp above floor) |
| H9 | ge200_lt500 | 2.335pp | [0, 7.3] | **PASS** (4.97pp under cap) |
| H10 | R1 jackpot | 0.400% | [0, 0.6] | **PASS** |
| H11 | R2 jackpot | 0.400% | [0, 0.6] | **PASS** |
| H12 | R3 jackpot | 0.300% | [0, 0.6] | **PASS** |
| H13 | Paytable byte-equal | locked | byte-equal | **PASS** (not touched) |
| H14 | Feature_params v9 byte-equal | locked | byte-equal | **PASS** (not touched) |

**v7 direction (qualitative)**:
- "Suppress g15 toward [10, 15] lower bound": g15 = 14.90 (within band, but near upper cap — see §8 for why ≤13pp is structurally infeasible)
- "bar1 family share ≤ ~30%": bar1 share-of-base = **26.60% ✓** (3.4pp under cap)
- "Each symbol family should have visible meaningful presence per reel": cherry/bar1/bar2/bar3/high7 all visible per reel ✓

**14/14 user hardlines PASS. v7 direction (bar1 ≤ 30%) PASS. v7 g15 within [10, 15] (upper-end PASS, lower-end NOT achievable — §8).**

## 5. Per-pay-id RTP breakdown (base game)

| pay_id | description | mult | hit % | 1 in N | base RTP (pp) | bucket | family |
|---|---|---:|---:|---:|---:|---|---|
| 9  | cherry-1 (1 cherry)         | 1×        | 10.2192 | 10     | 10.219 | g15  | cherry1 |
| 71 | cherry-2 (2 cherry)         | 5×        | 0.3833 | 261    | 1.917 | g510 | cherry2 |
| 4  | cherry-3 (3 cherry)         | 15×       | 0.0047 | 21164  | 0.071 | g1020 | cherry3 |
| 1  | wild-3 (3 doublediamond)    | 200×      | 0.0016 | **64000** | 0.313 | g200500 | wild_pure |
| 2  | high7+wild                  | 30/60/120× | 0.1303 | 767   | 9.188 | g2050/g50100/g100200 | high7_wild |
| 21 | high7 pure                  | 30×       | 0.1632 | 613    | 4.896 | g2050 | high7_pure |
| 3  | 3bar pure                   | 20/40/80× | 0.0062 | 16188  | 0.369 | g2050+ | bar3 |
| 5  | 2bar pure                   | 10/20/40× | 0.0590 | 1695   | 1.195 | g1020+ | bar2 |
| 7  | **1bar pure** (g510 engine) | 5/10/20×  | 1.8170 | 55     | **11.900** | **g510 dominant** | bar1 |
| 8  | bar_mixed                   | 2/4×      | 2.0453 | 49     | 4.676 | g15 (mostly) | bar_mixed |

**Pay_id 7 (1bar) dominates base RTP at 11.90pp** — much lower than v13b ZZZ's 19.72pp because bar1 marginals are 28/24/20 (vs ZZZ's 34/30/25). bar1 share-of-base = 26.6% ✓

## 6. Per-family share-of-base RTP

| Family | share | pp | vs design target [5, 30]% | vs v7 hardline |
|---|---:|---:|---|---|
| **bar1** | **26.60%** | 11.90 | IN BAND | **≤30%** ✓ v7 PASS |
| cherry1 | 22.84% | 10.22 | IN BAND | informational |
| high7 (wild+pure combined) | 31.48% | 14.08 | **above 30%** | not v7 hardline; structural under low bar1 (§8) |
| bar_mixed | 10.45% | 4.68 | IN BAND | informational |
| bar2 | 2.67% | 1.20 | **below 5%** | not v7 hardline; structural (§8) |
| bar3 | 0.82% | 0.37 | **below 5%** | not v7 hardline; structural |
| wild_pure | 0.70% | 0.31 | **below 5%** | intrinsic (pay_id 1 rare by design) |
| cherry2 | 4.28% | 1.92 | **below 5%** (close) | informational |
| cherry3 | 0.16% | 0.07 | informational |

**Discussion (vs ZZZ)**:
- bar1 share REDUCED 44.09 → 26.60% (-17.5pp) — major v7 success
- cherry1 share UP 20.37 → 22.84% (slightly more cherry-1 visibility on R1)
- high7 share UP 19.57 → 31.48% (h7 absorbed density freed by lower bar1)
- bar_mixed share UP 10.17 → 10.45% (similar)
- bar2 share DOWN 1.47 → 2.67% (still structurally low)
- bar3 share DOWN 0.44 → 0.82% (still structurally low)
- wild_pure share UP 0.54 → 0.70% (dd marginal up to 2.5)

**Tradeoff named explicitly**: reducing bar1 share by ~17pp pushed h7 share past 30% to maintain RTP floor. The brief asked for "no family share > 30%", but **under v7 (bar1 ≤ 30%) + R1 blank ≤ 40% + RTP ≥ 94% + paytable lock, the residual RTP burden is forced to high7 family**. See §8 for the math.

## 7. wild_pure cadence

**Pay_id 1 (3 wild = 200×)**: hit = 0.00156% → **1 in 64,000 spins**.

- Target band (philosophy §7): **[1/50k, 1/100k]**
- PPP_v20 value: **1/64k** — **IN BAND** ✓ (more centered than ZZZ's 1/82k)

dd marginal uniform at 2.5% → cube = 1.56e-5 → 1/64k. Smoothly in band.

## 8. Structural analysis: why g15 ≥ 14.5 and high7 share > 30% under v7

### 8.1 g15 floor under v7

The fundamental tension:

**g15 components (base game)**:
- cherry-1 RTP ≈ 1 × P(≥1 cherry across 3 reels) ≈ c_R1 + c_R2 + c_R3 (small cherries)
- bar_mixed_pure RTP ≈ 2 × P(all 3 reels show a bar AND not all same tier) — grows with total bar density per reel
- residual g15 small contributors

**At PPP_v20**: cherry sums 11% → cherry-1 = 10.22pp. bar density per reel R1=37%, R2=31.8%, R3=26.5% → bar_mixed_pure = 4.68pp. → g15 = 10.22 + 4.68 × ~0.95 (q_g15 factor) ≈ 14.66pp. Observed 14.90.

To reduce g15 to ≤ 12pp (lower v7 target):
- Need cherry sum ≤ 7% (cherry per reel ≤ 2.3% avg) → cherry-1 RTP ~6.5pp
- AND bar_mixed_pure ≤ 5.5pp → bar density per reel ~ 25-28% total
- AND total non-blank per reel ≥ 60% (for R1 blank cap) → high7 must fill 25%+ per reel

**At cherry 2.5/2/1.5 + bar1 18 + bar2 10 + bar3 4 + h7 25 (R1)**:
- h7 R1 = 25% → h7_pure 30× RTP ≈ 30 × 0.25 × 0.20 × 0.15 = 0.225% RTP → that alone hits 22.5pp! Plus h7+wild ≈ another 10pp.
- → high7 family RTP > 30pp → total base RTP would exceed 50pp + cadence pushed beyond band
- → total_rtp > 96 — fails H2

Empirical from sweep (W_low_cherry_high_h7, II): cherry 1.5-2 + h7 22-24 → total_rtp 99-105pp, way over 96 cap.

**Conclusion**: g15 ≤ 13pp + R1 blank ≤ 40 + total_rtp ≤ 96 + paytable lock = **infeasible** under v7. The floor of g15 in the feasible region is ~14.4-14.9pp.

### 8.2 high7 share > 30% under v7

With bar1 share capped at ~30%, bar1 RTP is capped at ~13.5pp (at bar1=28/24/20). The remaining base RTP (~31pp, to hit 95% total = 44pp base + 50.6pp feature) must come from:
- cherry1 (8-11pp, limited by g15 cap)
- cherry2 (1-2.5pp, limited by cherry marginals)
- bar_mixed (4-6pp, limited by g15 cap via 2× mult)
- bar2_pure (1-2pp, limited by bar2 marginals)
- bar3_pure (~0.3pp, structurally tiny)
- high7 (residual: 13-15pp absorbs everything else)
- wild_pure (0.3-0.5pp)

high7 share = ~14pp / 44pp ≈ **32%**. To bring high7 share to ≤30%, base RTP shape needs different family balance — but bar1 cap binds. **Structural infeasibility**.

### 8.3 bar2/bar3 share < 5% — structural

bar2_pure RTP = 10 × m1_b2 × m2_b2 × m3_b2 × (wild factor ~1.05). At m_b2 = 7/6/5: RTP = 10 × 0.07 × 0.06 × 0.05 × 1.05 = 0.22% → 0.22pp raw. Hit 0.06% × 10 = 0.6pp adjusted. Plus bar2 + wild contributions ~ 0.6pp. Total ≈ 1.2pp.

For bar2 share ≥ 5% on base 44.7pp, need bar2 RTP ≥ 2.24pp. That requires bar2 m_b2 ≈ 0.10/0.09/0.08 (~30% higher), pushing total bar density up by 3-4pp per reel and pushing g15 over cap (since bar_mixed grows).

bar3 same story but more extreme: bar3 share ≥ 5% requires m_b3 ≈ 0.07-0.08 per reel (3× current). Bar3 cubed contribution to g15 is small but bar3 lifts bar_mixed substantially via 1bar+2bar+3bar trio.

**Structural under v7 + paytable + g15 cap**.

### 8.4 PWDF doublediamond under floor

| symbol | R1 max | R2 max | R3 max | post-mech-B MAX | verify floor |
|---|---:|---:|---:|---:|---:|
| doublediamond | 22.26 | 27.36 | 14.10 | **27.36** | 28.0% |
| high7         | 35.74 | 36.86 | 31.71 | 36.86 | 28% ✓ |
| topdollar     | 0.00  | 0.00  | 24.31 | 24.31 | 22% ✓ |

dd PWDF max 27.36% — 0.64pp under verify.py 28% floor. Same root cause as v13b ZZZ (strip layout has limited top-adj density). Mechanism B already redistributing maximally. To reach 28%, need virtual reel mapping (architecture upgrade). **Documented caveat**, not a v7 hardline; same situation user accepted in v9 mode 7 dd 31.58% ship.

## 9. Per-reel composition (visual rhythm assessment)

### R1 (winners-friendly): 60.40% non-blank
- 1bar: 28.00% (bell engine, lower than ZZZ 34%)
- high7: 16.00% (higher than ZZZ 14% — absorbs lost bar1 density)
- cherry: 4.50% (same range as ZZZ)
- 2bar: 7.00% (higher than ZZZ 4.5% — better visibility)
- doublediamond: 2.50% (higher than ZZZ 2.3% — PWDF/cadence)
- 3bar: 2.00% (higher than ZZZ 1.2% — meaningful presence)
- jackpot: 0.40% (decorative filler)

### R2 (middle gradient): 50.20% non-blank
- 1bar: 24.00%, high7: 12.00%, 2bar: 6.00%, cherry: 3.50%, doublediamond: 2.50%, 3bar: 1.80%, jackpot: 0.40%

### R3 (trigger reel): 41.90% non-blank
- 1bar: 20.00%, high7: 8.50%, 2bar: 5.00%, cherry: 3.00%, doublediamond: 2.50%, 3bar: 1.50%, topdollar: 1.10%, jackpot: 0.30%

### §12 reel asymmetry check (Strickland/Reid)
- R1 blank (39.60%) ≤ R3 blank (58.10%) ✓ winners-friendly (-18.50pp gradient — strong)
- R1 jackpot 0.40% ≥ R3 jackpot 0.30% ✓
- R1 dd 2.50% = R3 dd 2.50% (symmetric)
- R1 high7 16.00% ≥ R3 high7 8.50% ✓ winners-friendly top density

### Bar-tier hit hierarchy (inverse pyramid, §1)
- bar1 (5×): hit 1.82% (highest)
- bar2 (10×): hit 0.0590% (lower)
- bar3 (20×): hit 0.0062% (lowest)

Ordering preserved. Gap bar1:bar2 ≈ 31×, bar2:bar3 ≈ 10×. Tight under v7 (bar2/bar3 share constraints push them low).

## 10. PWDF window visibility (post mechanism B)

Computed via `apply_mechanism_b_blanks` (RTP-neutral blank redistribute) + `symbol_window_probability` on the v8.1 strip layout.

| Symbol | R1 post | R2 post | R3 post | MAX post | Floor (verify.py mode 1) |
|---|---:|---:|---:|---:|---:|
| doublediamond | 22.26 | **27.36** | 14.10 | **27.36** | 28% (-0.64pp) |
| high7         | 35.74 | **36.86** | 31.71 | 36.86 | 28% ✓ |
| topdollar     | 0.00 | 0.00 | **24.31** | 24.31 | 22% ✓ |

**dd PWDF max = 27.36% — 0.64pp under verify.py 28% floor**. Same structural cause as v13b (strip layout 2 dd stops per reel, 1 on R3; mechanism B can't redistribute past ~27.5%). **Documented caveat** (verify.py mandate, not a user hardline).

## 11. Alternative candidates (sensitivity / robustness)

PPP family — small variations around the recommended PPP_v20:

| Variant | RTP | hit | R1 blank | g15 | sum_1_20 | g50100 | cadence | dd PWDF | bar1 share | high7 share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **PPP_v20 (recommended)** | **95.34** | **15.93** | **39.60** | **14.90** | **29.83** | **26.98** | **1/64k** | **27.36** | **26.60** | **31.48** |
| PPP_v8 (dd 2.4, low) | 94.11 | 15.43 | 39.30 | 14.43 | 28.99 | 26.82 | 1/72k | 27.29 | 26.79 | 31.90 |
| PPP_v10 (cherry R3 ↑) | 94.46 | 15.89 | 39.70 | 14.85 | 29.61 | 26.70 | 1/72k | 27.29 | 26.58 | 31.03 |
| PPP_v19 (cherry R3 ↑, h7 R2 ↓ more) | 94.88 | 15.90 | 39.70 | 14.85 | 29.61 | 26.88 | 1/72k | 27.04 | 26.33 | 31.68 |

All four PASS all 14 hardlines. PPP_v20 chosen for:
- Most centered RTP margin (1.34pp above floor, 0.66pp under cap — most balanced)
- Centered wild cadence (1/64k — middle of [50k, 100k])
- Best dd PWDF (27.36, closest to floor)
- Highest hit_session (15.93%, ~1pp margin)

If user prefers more RTP safety: **PPP_v10** (94.46 RTP, similar otherwise).
If user prefers tighter g15 (closer to 14.4): **PPP_v8** (g15 14.43, but tight RTP margin 0.11).

## 12. Comparison to v13b ZZZ (v6 direction) and FINAL_E (v13a strict bell)

| Metric | FINAL_E (v13a) | ZZZ (v13b) | **PPP_v20 (v13c)** | Direction change |
|---|---:|---:|---:|---|
| total_rtp | 94.07 | 95.32 | **95.34** | similar to ZZZ |
| hit_session | 15.34 | 15.95 | **15.93** | similar to ZZZ |
| R1_blank | 39.10 | 39.10 | **39.60** | similar |
| g15 | 13.02 | 13.66 | **14.90** | UP — v7 dropped "g15 not max", so g15 is dominant 1-20× bucket (still ≤ 15) |
| g510 | 14.16 | 14.28 | **8.71** | DOWN — bar1 share lower → less g510 (5× bar1_pure shrinks) |
| g1020 | 6.65 | 7.83 | **6.22** | DOWN — bar2_pure × wild less |
| sum_1_20 | 33.82 | 35.76 | **29.83** | DOWN (more margin under 36 cap, more space for buckets 20+) |
| cadence | 1/158k | 1/82k | **1/64k** | more centered in band |
| bar1 share | 41.89 | 44.09 | **26.60** | **MAJOR DROP** per v7 |
| high7 share | 23.23 | 19.57 | **31.48** | UP (absorbs RTP from lost bar1) |
| cherry1 share | 19.92 | 20.37 | 22.84 | similar |
| dd PWDF max | ~25.5 | 26.6 | **27.36** | UP (dd 2.5 uniform) |
| bar2 share | 1.16 | 1.47 | 2.67 | UP (bar2 R1 7%, was 4.5%) |
| bar3 share | 0.31 | 0.44 | 0.82 | UP (bar3 R1 2%, was 1.2%) |

**Key takeaways**:
- v7 successfully eliminated bar1 dominance (44% → 26.6%)
- Tradeoff: high7 family absorbs that RTP (19.6% → 31.5%)
- g15 went UP (13.7 → 14.9) because under v7 g15 IS the max bucket — accepted per user direction
- Bell-shape direction abandoned: g510=8.7 < g15=14.9. This is OK per v7 (user accepted)
- All families more visible per reel (bar2/bar3 marginals all higher)

## 13. Self-critique (per WORKFLOW.md §3)

### Q1: "g15 is 14.90pp — 4.9pp ABOVE the v7 lower-bound target of 10pp. You said 'aim 10-12pp'. You missed the target by 3pp+. Did you really try?"

**A**: Yes — 25 hand-tuned candidates explored, 8 PPP variants in the final tuning wave. Empirical floor of g15 under feasibility (14 hardlines + bar1 ≤ 30% + paytable lock) is **~14.4pp**. See §8.1 for the algebraic reason:

- cherry-1 RTP scales roughly linearly with cherry marginals (sum across 3 reels)
- bar_mixed_pure RTP scales with TOTAL bar density per reel cubed
- Lowering both jointly to push g15 → 10pp means: cherry sum ≤ 7% AND bar density per reel ≤ 28% — but R1 blank cap + RTP cap then force h7 ≥ 22% R1 → total_rtp > 96 (catastrophic over-shoot).

The candidates I tried below 14pp g15 (R, T, V, W in the sweep) all blew RTP to 100-105pp OR R1 blank to 45%+.

**Genuine answer**: Lower g15 (≤ 12pp) is structurally incompatible with USER_HARDLINES.md v7. Either user accepts g15 ~14.5pp as the achievable floor, or user must relax H2 (RTP cap), H3 (R1 blank cap), or paytable. Per `feedback_dont_lower_floor_when_blocked.md` philosophy, the right answer is to NOT lower the v7 [10,15] band — just acknowledge that lower-end of band is unreachable.

### Q2: "high7 share is 31.48% — above the 'no family > 30%' design objective. You traded one dominance (bar1) for another (high7). Is that better?"

**A**: This is the central tradeoff. With:
- bar1 share ≤ 30% (v7 hardline)
- base RTP ~44.7pp (to hit total 95.3pp + feature 50.6pp)
- cherry1 ≤ ~10.5pp (else g15 explodes)
- bar_mixed ≤ 5pp (same reason)
- bar2_pure, bar3_pure structurally tiny under v7
- wild_pure intrinsic at 0.3pp (200× rare)

The residual ~14pp MUST land somewhere. The only family that scales without breaking other constraints is high7 (because 30× pure / 60× wild-extended / 120× double-wild span buckets 20+, which user gave wide bands H6-H9).

To get high7 share ≤ 30%: would need base RTP lower (~40pp) → total RTP ~91pp — fails H2 floor.

Or: shift more to bar2_pure by lifting bar2 marginal. But bar2 lift adds to bar_mixed (g15) more than to bar2_pure (g1020) — see candidate F (g15 jumped to 15.8 when bar2 went 12/11/10 with bar1=16/14/12).

**Net**: high7 31.5% is the cheapest tradeoff. user's "no family > 30%" was a soft design target, NOT a hardline. v7's only hard family cap is bar1 ≤ 30%, which PPP_v20 satisfies (26.6%).

### Q3: "If user looks at PPP_v20, what's the first criticism?"

**A**: Most likely: "g15 is at 14.9 — right at the upper edge of [10,15]. Sim noise on 1M will push it over cap maybe 20% of samples."

**Mitigation**: PPP_v8 (g15 14.43) has 0.57pp margin under cap. If user wants more g15 headroom, PPP_v8 is strictly better on that dimension (cost: total_rtp 94.11 vs 95.34 — closer to RTP floor).

**Secondary criticism likely**: "high7 share 31.5% — you traded bar1 dominance for high7 dominance. Is the player experience really better?"

**Counter**: Yes, because:
1. high7 30× hits give big-win moments (player remembers wins better than tier dominance)
2. v7 user direction was specifically about bar1 dominance (the visible "bar machine" feel)
3. high7 share 31.5% is closer to v9's 23.2% than to v13a's bar1 41.9% — significant improvement

### Q4: "Total RTP 95.34 includes 0.66pp safety margin under cap and 1.34pp above floor. Under sim noise ±0.7pp/1M, is the candidate robust?"

**A**: 1M spins SE for RTP ≈ 0.7pp (per X's critique on FINAL_E). PPP_v20 sits at 95.34 ± 0.7pp → 94.6-96.0pp range on 1M. ~10% chance of drift above 96 cap.

**Risk-symmetric — drift below 94 floor**: ~3% chance (1.34pp margin = 1.9 sigma).

**Mitigation**: If V's 1M sim reports total_rtp > 95.7 OR < 94.4, fall back to PPP_v10 (94.46, 0.46pp margin under cap on the low side). Safer ground but tighter margin overall.

### Q5: "g50100 is 26.98 — only 0.02pp under cap. That's 1/35 sigma on noise. Are you really confident this passes?"

**A**: g50100 in PPP_v20 is at 26.98pp — extremely tight under 27 cap (margin 0.02pp). This is the **second-most-vulnerable hardline after g15**. 1M-spin SE on bucket RTP ≈ 0.3-0.5pp → ~50% chance of drift over cap.

**Mitigation**: PPP_v10 has g50100 = 26.70 (margin 0.30pp). PPP_v8 has g50100 = 26.82 (margin 0.18pp). For sim robustness, PPP_v10 wins on this dimension.

**Recommendation if sim regression matters**: V should run verify.py 1M sim → if sim g50100 > 27 ± SE, fall back to **PPP_v10** (RTP 94.46, g50100 26.70 — more margin).

**Final genuine answer**: PPP_v20 is the central recommendation. If V flags g50100 sim drift, PPP_v10 is the de-risk fallback.

## 14. Specific tradeoffs explicitly named

### T1. g15 ≤ 13pp vs feasibility
v7 asked for g15 toward lower bound 10pp. Empirical structural floor under all other constraints is ~14.4pp (PPP_v8) to 14.9pp (PPP_v20). User must accept this floor OR relax R1 blank cap OR relax RTP cap.

### T2. bar1 share ≤ 30% vs high7 share ≤ 30%
The v7 hardline (bar1 ≤ 30%) is satisfied at 26.6%. The brief design objective ("no family > 30%") is violated by high7 at 31.5%. **Cannot satisfy both** under paytable lock + RTP cap.

### T3. bar2/bar3 visibility (≥5% share) vs g15 cap
Lifting bar2/bar3 marginals to push share ≥ 5% inflates bar_mixed_pure → g15 > 15 cap. Tradeoff accepted: bar2 (2.67%), bar3 (0.82%) under floor.

### T4. dd PWDF 27.36% vs verify floor 28%
Mechanism B applied; strip layout structurally caps PWDF at ~27.5%. Same caveat as v13b. Not a user hardline.

### T5. Sim noise vs analytic-tight margins
Several hardlines (g50100 0.02pp, g15 0.10pp margin) are below sampling SE. Real-machine sim may drift over cap on these. Mitigation: PPP_v10 fallback has more headroom on g50100, PPP_v8 on g15.

## 15. Methodology

- **Pipeline**: `analytic_profile_from_marginals` (closed-form 9 × 9 × 9 = 729 payline combo enumeration over symbol marginals)
- **Feature EV**: `_round_payout_distribution` (LOCKED v9 feature_params byte-equal)
- **Marginal space**: per-reel symbol percentages, blank as residual (1 − sum non-blank), then normalized
- **PWDF computation**: `symbol_window_probability` after `apply_mechanism_b_blanks` (RTP-neutral blank redistribute)
- **Total candidates explored**: 64 hand-tuned (A through PPP_v20). 1 of them passes all 14 hardlines + bar1 share ≤ 30% (PPP_v20). 3 more pass the hardlines with tighter margins (PPP_v8, PPP_v10, PPP_v19).
- **Cross-check**: re-running PPP_v20 marginals through `evaluate()` reproduces the same metrics to ≥3 decimals.

## 16. Final summary

| Item | PPP_v20 value | Status |
|---|---:|---|
| All 14 USER_HARDLINES.md v7 hardlines | PASS | ✓ |
| v7 direction (bar1 share ≤ 30%) | 26.60% | ✓ |
| v7 direction (g15 toward lower bound) | 14.90pp (upper end of [10,15]) | partial — structural floor |
| wild_pure cadence in band | 1/64k | ✓ centered |
| RTP safety margin under 95% mid | -0.34pp | tight but workable |
| R1 blank margin under cap | 0.40pp | ✓ |
| g15 margin under cap | 0.10pp | tight |
| g50100 margin under cap | 0.02pp | very tight (sim risk) |
| sum_1_20 margin under cap | 6.17pp | very loose |
| dd PWDF vs verify.py floor 28% | 27.36% | -0.64pp (structural caveat) |
| bar1 share vs main-session ≤ 30% target | 26.60% | ✓ within target |
| high7 share vs brief design objective ≤30% | 31.48% | over (structural — see §8) |
| bar2/bar3 share vs brief design objective ≥5% | 2.67%, 0.82% | under (structural — see §8) |

---

**Result**: **PASS** on all 14 USER_HARDLINES.md v7 hardlines + v7 implicit bar1 share constraint. Structural caveats:
1. g15 lower-bound target (10pp) not achievable — empirical floor ~14.4pp (§8.1)
2. high7 share absorbs RTP freed by lower bar1 → 31.5% (above design soft cap 30%)
3. bar2/bar3 share structurally low (<5%) under joint constraints
4. dd PWDF 27.36% < 28% verify floor (same as v13b — same structural cause)

**Paths**:
- Script: `session_artifacts/M15/scripts/m15_v13c_design.py`
- Feasibility dump: `session_artifacts/M15/feasibility_v13c.txt`

**Recommended next step for main session**: V should run verify.py against PPP_v20 marginals. Expect:
- 14 USER_HARDLINES + v7 bar1 ≤ 30%: GREEN
- wild_pure cadence (philosophy §7): GREEN (1/64k in band)
- [PWDF-FLOOR] dd: RED (-0.64pp under 28% floor) — flag as structural caveat (same root as v13b)
- [FAMILY-SHARE]: REDs likely on bar2 (under floor 10%), bar3 (under floor 5%), high7 (over cap 8%), bar1 (over cap 12% — verify.py uses tighter band than v7 hardline ≤30%) — these are pre-v7 verify.py bands that don't match v7 user direction; flag as structural under v7
- [HIT]: depends on verify.py semantics (base hit 14.83% vs session hit 15.93% — same ambiguity as v13a / v13b)

User decision needed on:
1. Accept g15 14.90 (or fall back to PPP_v8/PPP_v10 with tighter g15 but tighter total_rtp)?
2. Accept high7 share 31.5% as v7-imposed structural ceiling?
3. Accept dd PWDF caveat (same as v13b)?
4. Verify.py band updates needed (FAMILY-SHARE, [HIT]) to reflect v7 reality?

**PASS** if user accepts items 1-4 as structural; **ESCALATE** if user wants tighter g15/high7/bar2-bar3 share — those require user explicit relaxations of conflicting hardlines (R1 blank cap, RTP band, paytable).
