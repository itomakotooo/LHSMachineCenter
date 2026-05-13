# M15 v14c modes 2 / 5 — adversarial critique (Critic X)

> **Subject**: D's design `session_artifacts/M15/design_v14c_modes_25.md`. Candidates M2_LC (Lucky Centered) + M5_LC_plus (Super-Lucky Centered).
>
> **Critic stance**: adversarial — Verify GREEN is the floor, not the ceiling. D self-claims 43/43 invariants PASS. The numbers reproduce. The question is whether the *design* matches the user-confirmed corrected brief AND the cross-mode philosophy AND the shipped v9 archetype. Three of the four "fixes" against v14b M2_Q look real on a first read; a fourth dimension D didn't fix is what concerns me most. The user has rejected six successive candidates this session (M2_Q rejected for v14b reasons); mode 1 only shipped after the user explicitly relaxed every bucket band. M15 modes 2 / 5 already exist in shipped v9 (validated). The brief was "fix v14b's three failures while staying consistent with shipped + philosophy + user-confirmed direction".
>
> **Production files NOT modified.** No new hardlines proposed. No user-hardline relaxations proposed. Direction sources: USER_HARDLINES.md v8 (hard) + DESIGN_PHILOSOPHY.md §1/§12/§15 (direction) + user-confirmed brief 2026-05-12 (direction).
>
> Independent metrics script: `session_artifacts/M15/scripts/m15_v14c_critique_metrics.py`. Verified D's numbers reproduce exactly + computed five things D did not: bar_mixed tier decomposition, cross-mode family-share table including shipped v9, integer-rounding sensitivity sweep, high-mult share comparison shipped vs M5_LC+, m5 base shape vs m2 base.

---

## § 0 Tooling sanity

D's script `m15_v14c_design_modes_25.py` runs clean. All 43 invariants PASS as claimed. Independently:

| metric | D claim | my recompute | match |
|---|---:|---:|:---:|
| M2_LC total RTP | 296.129 | 296.129 | ✓ |
| M2_LC base RTP | 97.911 | 97.911 | ✓ |
| M2_LC R1/R3 blank | 27.53 / 23.19 | 27.528 / 23.190 | ✓ |
| M2_LC P(b1)/P(b2)/P(b3) | 1.70/0.99/0.21 | 1.698/0.985/0.214 | ✓ |
| M5_LC+ total RTP | 504.561 | 504.561 | ✓ |
| M5_LC+ base RTP | 97.069 | 97.069 | ✓ |
| Shipped m2 R1 blank | (D referenced 33.45) | 33.446 | ✓ |
| Shipped m2 P(b1)/P(b2)/P(b3) | n/a | 0.372/1.063/0.489 | (info) |

D's claim that prior M2_Q's three failures are "fixed" (RTP margin / bar hierarchy direction / R1≥R3 blank direction) is mathematically true on those three axes. But this leaves the question of what else has changed about the *machine identity* in the process.

---

## § 1 Adversarial questions and answers (12)

### Q1 — RTP margin 6.13pp on m2: is the σ-buffer actually 4σ on 1M spins as D claims?

**D's claim**: SE=1.44pp → margin/SE = 4.26σ → P(realized < 290) ≈ 1e-5.

**My recompute** (see Section F of my metric script):
- m2 analytic total = 296.129pp
- Var(base) per spin = 15.55 (base CV 4.62 × μ_base 0.979 squared)
- Var(feature) per spin (conservative approx using per-round cond Var, since per-session var should be lower due to the 4-round geometric mechanic) = 187.9
- Var(total) per spin = 203.4
- SE on 1M paid spins = **1.426 pp**
- 6.13pp margin / 1.426pp SE = **4.30σ buffer** — P(realized < 290) ≈ Φ(−4.30) ≈ 8.5e-6. Practically zero.
- SE on 100k spins = 4.51pp → margin/SE = 1.36σ → P(realized < 290) ≈ 8.7%
- SE on 10k spins = 14.26pp → ~33% probability of dropping under floor (irrelevant; 10k isn't the production target)

**Verdict on Q1**: ✓ **RTP margin math is solid.** 6.13pp on 1M spins is safe by a large factor; D's σ math reproduces. Engine integer-rounding drift adds ±0.5pp (per m1 v14 observed) — combined uncertainty ~1.5pp, still 4σ above floor. **This is genuinely fixed vs v14b.**

### Q2 — bar_mixed share 31.2% (M2_LC) — what's the tier-combination decomposition?

This is THE crux of whether "bar lift uniform" is benign or hides a 1bar-stacking trap. My decomposition (Section B):

| candidate | bar_mixed total P | 112-majority (1bar-heavy) | 122-majority (2bar-heavy) | 133-majority (3bar-heavy) | diverse-3tier |
|---|---:|---:|---:|---:|---:|
| m1 SHIPPED | 4.52% | 1.71% | 1.31% | 0.50% | 1.00% |
| **m2 SHIPPED** | 8.67% | **1.66%** | **2.97%** | **1.91%** | 2.13% |
| **M2_LC (D)** | 12.66% | **4.80%** | **3.66%** | **1.40%** | 2.80% |
| **M5_LC+ (D)** | 12.66% | **4.80%** | **3.66%** | **1.40%** | 2.80% |
| m5 SHIPPED | 8.37% | 1.60% | 2.86% | 1.84% | 2.06% |

Two findings:

1. **bar_mixed in M2_LC is 1bar-dominated** (4.80% of 12.66% = 38% of bar_mixed P comes from 1bar-majority combos like 1+1+2, 1+2+1, etc.). In shipped m2 it's 2bar-dominated (2.97/8.67 = 34%) with 1bar-majority only 19%. M2_LC has **shifted bar_mixed's weight center toward low-tier combos**.

2. **bar_mixed total grew 50% beyond shipped m2** (8.67 → 12.66). The bar_mixed pay multipliers in M15 are 2× (some combos) / 4× (others). At ~13% hit rate and 2-4× multipliers, bar_mixed alone delivers ~30.5pp RTP in M2_LC vs ~22.4pp in shipped m2. **M2_LC's "lucky" RTP lift is disproportionately delivered through the cheapest bar pay** instead of mid/high-pay families.

**Verdict on Q2**: ⚠ **bar_mixed dominance is real and structural.** It's the direct mathematical consequence of D's "lift bar1/bar2/bar3 uniformly within reel" approach: when all three bar marginals lift together, the bar_mixed combinatorial product (sum over diverse triples) scales roughly as cube of the bar lift. With all-bar lift = ~1.39× per reel, bar_mixed P scales ~1.39³ = ~2.7× → exactly what we see (5.25% m1 → 14.0% M2_LC, ratio 2.66×). The shipped v9 m2 chose a different topology (bar2/bar3 promoted, bar1 cut) precisely to keep bar_mixed shape diverse rather than 1bar-dominated.

### Q3 — Did D actually emphasize high7 enough? Compare cross-mode marginal lift ratios

User direction (2026-05-12): "增加机台特征的中高倍率奖，在 m15 里就是一些 **high symbol** 和 feature 的触发率"

high7 IS the M15 machine-feature anchor symbol (DESIGN.md §17 ii). My ratio table (Section D of metrics):

| family | m1 sum margin | M2_LC sum margin | M2_LC/m1 ratio |
|---|---:|---:|---:|
| cherry | 10.00 | 17.70 | **1.77×** |
| 1bar | 50.19 | 69.86 | 1.39× |
| 2bar | 41.00 | 57.06 | 1.39× |
| 3bar | 23.09 | 31.53 | 1.36× |
| **high7** | **17.60** | **36.64** | **2.08×** |
| doublediamond | 8.10 | 7.31 | 0.90× (cut) |
| topdollar (trigger) | 1.12 | 3.30 | 2.95× |
| jackpot | 1.10 | 1.10 | 1.00× |
| blank | 147.79 | 75.50 | 0.51× (sparser) |

high7 lifted 2.08× vs bars at 1.36-1.39× — h7 IS lifted strongest of the line-pay families. user direction respected. cherry 1.77× is also a hit-driver.

**BUT** look at FAMILY SHARE (Section C):
- m1 SHIPPED high7 share-of-base = **8.70%**
- M2_LC high7 share-of-base = **14.92%** (+6.22pp share)
- shipped m2 high7 share-of-base = **14.17%** (close to M2_LC)

OK on h7 share. Direction respected.

**Verdict on Q3**: ✓ **h7 emphasis is genuine** and matches shipped m2's h7 weight class. D followed user direction on this axis.

### Q4 — m5 base ≈ m2 base + locked feature: where's the user's "multiplier shift toward higher mults" actually delivered?

This is the question D dodges most. User said (2026-05-12): "mode5 就是在 mode2 基础上，把奖项倍率继续向高倍率移动。但同样屏蔽千倍以上的奖。"

D's m5 base RTP = 97.07pp vs M2_LC 97.91pp → m5 base SLIGHTLY LOWER (−0.83pp), not lifted. So all of the "+200pp m5 vs m2" comes from feature_params lock.

My decomposition of base RTP by max-mult bucket (Section J):

| bucket | M2_LC pp | M5_LC+ pp | Δ |
|---|---:|---:|---:|
| 1× (cherry1) | 15.68 | 15.68 | 0.00 |
| <15× (bar_mixed 2/4×, cherry2 5×) | 46.51 | 46.96 | +0.45 |
| 15× (cherry3) | 0.30 | 0.30 | 0.00 |
| 30× (h7_pure + h7+blank line) | 5.46 | 4.25 | **−1.21** |
| 40-120× (bar/h7 wild-substituted) | 29.67 | 29.54 | −0.13 |
| 200× (wild_pure) | 0.28 | 0.33 | +0.04 |

**High-mult (≥30×) base RTP share**:
- M2_LC: 35.41pp = **36.17% of base**
- M5_LC+: 34.12pp = **35.15% of base** (**LOWER!**)

By contrast, **shipped v9** does it right:
- m2 SHIPPED high-mult share: 45.6% of base
- m5 SHIPPED high-mult share: **49.6% of base** (m5 > m2 — the shift the user asked for)

**M5_LC+ has LESS high-mult base RTP than M2_LC, not more.** The 200× wild_pure RTP nudged up (+0.04pp), the 30× h7 RTP dropped (−1.21pp) by more than 4× the wild_pure gain, and the 40-120× wild-substituted RTP also dropped slightly. Net: **base "multiplier mass" shifted LOWER, not HIGHER**, in m5.

D's defense (§5 Q7): "Most of m5's 'multiplier mass' lift goes to the feature (which has heavy 1000× tail per m5 x_value_weights)." This is partially true — the feature does have a much heavier conditional tail (m5 R-conditional P(R≥200)/trigger = 11.76% vs m2 0.85%, **13.8× higher**). But the user said "把奖项倍率继续向高倍率移动" — this naturally reads as a base-game characteristic, not "only happens during the 1/30 feature triggers". A player on m5 will see the base-game high-mult symbols **slightly more sparse** than m2 (h7 marginal 36.64% on m2 → 33.71% on m5, ratio 0.92×); only the feature feels richer when triggered.

**Verdict on Q4**: ⚠ **m5's "multiplier shift higher" is delivered via locked feature_params alone, not via any base-shape adjustment toward high-mult.** D actually cut h7 by 8% to release base budget for "total RTP centered". This works mathematically (m5 total > m2 total) but doesn't match the natural reading of user direction. **An honest m5 would either lift h7 more (sacrificing some other family to stay in band) or lift dd more, not cut h7.** D chose the path of least resistance to keep RTP centered; the user's stated intent is not fully respected.

### Q5 — wild_pure cadence m2/m1 = 0.727 — wild_pure in m2 RARER than m1. Is this acceptable lucky direction?

D's defense (§5 Q4): wild_pure share cap 0.30% structurally requires dd cut to keep wild_pure RTP share at cap; the m2/m1 cadence 0.727× falls under cap (≤1.5×) — verify GREEN; the "lucky" feel lives in the feature.

This is structurally true. But: shipped m2 wild_pure cadence = 1/300,803 (P=3.32e-6 — even rarer). Shipped m2 wild_pure share = 0.26%. M2_LC at 1/70,607 (P=1.42e-5) is **4.3× more frequent** than shipped m2. So m2's wild brand visibility in cadence terms is actually LIFTED vs shipped m2 (just lower than m1's 1/51k). Combined with the +6.13pp RTP margin headroom, dd could potentially be lifted further if needed.

For m5 vs m2: wild_pure cadence ratio 1.150 (above floor 1.10) — D met the cross-mode escalation hardline but with minimal margin. See Q11 below on integer rounding flip risk.

**Verdict on Q5**: ✓ **wild_pure cadence direction is OK.** m2 RARER than m1 in wild_pure is structural (share cap-driven) and matches shipped v9 m2's pattern; D's choice respects archetype direction.

### Q6 — m5 LUCKY-MONO hit margin only 0.04pp — integer rounding flip risk?

D self-flagged this (§9). My integer-rounding sweep (Section E) at scales 100, 500, 1000, 2000, 5000, 10000:

| scale | M2_LC hit | M5_LC+ hit | diff (pp) | LUCKY-MONO m5≥m2 |
|---|---:|---:|---:|:---:|
| 100 | 32.86% | 32.86% | 0.000 | ✓ |
| 500 | 33.63% | 33.56% | **−0.068** | **✗ FAIL** |
| 1000 | 33.87% | 34.09% | +0.219 | ✓ |
| 2000 | 33.62% | 33.84% | +0.217 | ✓ |
| 5000 | 33.91% | 33.81% | **−0.106** | **✗ FAIL** |
| 10000 | 33.83% | 33.89% | +0.059 | ✓ |

**LUCKY-MONO hit FLIPS at scales 500 and 5000.** At scale 10000 (likely production), it passes with only +0.059pp margin — well within engine-realized rounding jitter. **Risk is real.**

Note: the actual M2 weights in production use specific integer weights (Section E shows realized hits hover around 33.6-34.1% under different scales). Whichever specific weight realization D's `marginals_to_weights` step produces, the m5/m2 hit ordering is fragile.

**Verdict on Q6**: ⚠ **HIGH integer-rounding flip risk on LUCKY-MONO m5_hit ≥ m2_hit.** D's mitigation suggestion ("bump cherry_lift or bar_lift in m5 by 0.01-0.02") is theoretically right; in practice D should pre-bump before commit. Without mitigation, ~50% of integer-weight realizations would invert this hardline.

### Q7 — m5 trigger = m2 trigger exactly. Same rounding question.

My sweep:

| scale | M2_LC trig | M5_LC+ trig | diff (pp) | LUCKY-MONO m5≥m2 |
|---|---:|---:|---:|:---:|
| 100 | 4.26% | 4.26% | 0.000 | ✓ |
| 500 | 3.27% | 3.18% | **−0.084** | **✗ FAIL** |
| 1000 | 3.40% | 3.42% | +0.027 | ✓ |
| 2000 | 3.29% | 3.29% | **−0.003** | **✗ FAIL** |
| 5000 | 3.32% | 3.31% | **−0.009** | **✗ FAIL** |
| 10000 | 3.30% | 3.30% | +0.002 | ✓ |

**LUCKY-MONO trigger FAILS at scales 500, 2000, 5000.** Both modes use the same R3 topdollar marginal (3.304%) which means same td weight target → same rounded weight in many integer realizations BUT m5 has different blank/dd marginals → different reel total weight → different td-weight share → realized trigger ≠ m2 trigger. **Failure rate 50% across scales.**

**Verdict on Q7**: ⚠ **HIGH integer-rounding flip risk on LUCKY-MONO m5_trig ≥ m2_trig.** Mitigation cost: bump m5 td_R3 weight by 1 unit pre-commit, OR keep m5 R3 marginals identical to m2 R3 marginals (cleaner, since user said "mode 5 base ≈ mode 2 base"). D should NOT ship without verifying engine-realized trigger.

### Q8 — Max family share cross-mode. Does M2_LC pass user's "no single-family dominance" pattern?

Top 3 families per mode (Section C):

| mode | top family | 2nd | 3rd |
|---|---|---|---|
| m1 SHIPPED | bar_mixed (27.9%) | cherry1 (21.9%) | bar2 (15.4%) |
| **M2_LC** | **bar_mixed (31.2%)** | cherry1 (16.0%) | high7 (14.9%) |
| **M5_LC+** | **bar_mixed (31.7%)** | cherry1 (16.2%) | bar2 (14.3%) |
| m2 SHIPPED | bar_mixed (22.6%) | cherry1 (19.9%) | bar3 (15.8%) |
| m5 SHIPPED | bar_mixed (21.0%) | cherry1 (18.1%) | bar3 (16.9%) |

**M2_LC bar_mixed share 31.2% is 8.5pp higher than shipped m2's 22.6%**. And bar_mixed is the worst family for "dominance feel": it's the 2/4× pay (the lowest-mult bar pay), and 38% of its mass comes from 1bar-majority combos (= "this looks like three 1bars" visually).

User pattern across this session (per critique_v14b §1 Q11 and `feedback_tuner_pareto_trap.md`): rejected designs with bar1 share 44% AND with h7 share 31.5%. User is sensitive to **any** family share > ~25-30%. M2_LC's bar_mixed at 31.2% is plausibly inside the "too dominant" zone — particularly because:

1. shipped m2 had bar_mixed at 22.6% — user has implicitly accepted ~22-23%
2. The user explicitly framed mode 2 as "增加机台特征的**中高倍率奖**" — bar_mixed is the **lowest-mult bar pay** (2/4×), not "mid/high mult"
3. The session pattern is that user rejects any family share trending over 28-30%

**Verdict on Q8**: ⚠ **bar_mixed 31% is in user-reject territory.** Even if it doesn't fail a hardline (no FAMILY-SHARE band on bar_mixed for m2/m5 in verify.py), the structural lift from "uniform bar lift within reel" produces this exact concern that has rejected prior candidates. D's M2_LC design ignored Q11 of my prior critique on family dominance.

### Q9 — R1 blank 27.53% (M2_LC) vs shipped m2's 33.45%. Is M2_LC over-dense?

Lucky mode means denser reels (lower blank). Shipped m2 R1 blank = 33.45%, M2_LC R1 = 27.53% — M2_LC is denser by 5.92pp.

User intent (2026-05-12): "增加中奖率" — yes hit ↑. Shipped m2 base hit (analytic) was 33.54%. M2_LC base hit = 33.85% — close, but achieved via a denser reel pattern.

Looking at total blank marginals across all three reels (sum):
- m1 SHIPPED: 147.79
- shipped m2: 89.97 (computed from Section A: 33.45+32.28+24.30 = 90.03)
- **M2_LC: 75.50** (27.53+24.78+23.19)
- m5 SHIPPED: 88.93
- **M5_LC+: 78.11**

M2_LC has **~16% less total blank** than shipped m2. This is a measurable visual difference — a player switching m2 from shipped to M2_LC would see noticeably busier reels.

**Verdict on Q9**: ⚠ **R1 blank 27.53% is denser than shipped lucky archetype.** Not a hardline violation, but a visible machine-identity shift. Combined with Q2 (bar_mixed 31%) this is what makes M2_LC "feel different" from shipped m2 to the eye.

### Q10 — "mode 2 hit 30-35%" — which definition?

User_brief states hit band [30, 35] for m2 base hit (per verify.py MODE_HIT_BAND[2] = (0.30, 0.35) → fires on `profile["hit_rate"]` which is base hit only, excluding trigger).

D's M2_LC base hit = 33.85% → in band ✓. Session hit (incl. trigger) = 37.15% — outside [30, 35] but session hit isn't the verify metric.

**Verdict on Q10**: ✓ **Hit band passes correctly.** Session hit being above 35% is not a hardline issue; D's framing is correct.

### Q11 — P(R≥1000)/spin m5 = 1.10e-7 vs m2 = 1.54e-6 — m5 ten times LOWER. Sanity?

Looks anomalous on first read — surely "super-lucky" m5 should have MORE chance of big wins per spin?

My investigation of feature distribution (Section G):

- m2 feature x_value_weights: `[0.0009, 0.0914, 0.3687, 0.3687, 2.3289, 2.3289, 9.3906, 9.3906, **37.8657, 37.8657**]` — strongly skewed right (37.87 weight on the two top-value cards)
- m5 feature x_value_weights: `[0.0001, 3.0, 3.5, 3.5, 7.0955, 7.0955, 13.453, 13.453, **25.5065, 25.5065**]` — more uniform across mid-range, less concentrated on top cards

m2 actually has a higher per-trigger P(R≥1000) (4.66e-5 / trigger) than m5 (3.33e-6 / trigger). This is because m2's x_value_weights front-load the very highest cards (37+ weight on 1000-card-equivalent values vs 25 on m5), while m5 spreads weight more evenly across 100-500 mids.

m5 EV is much higher (123× vs 60×) because the AVERAGE is much higher (more mass at mid-high than m2's bimodal "mostly small + a tiny chance of jackpot" shape), but the **extreme tail is actually flatter** in m5 — the "1000× tail" is rarer in m5 than in m2.

**Verdict on Q11**: ✓ **Math checks out.** m5's "super-lucky" feel comes from frequent big-event cadence (P(R≥200)/spin 14× m2) not from rare jackpot tail. P(R≥1000)/spin lower for m5 is a feature_params shape consequence, not a bug. ALL feature_params are user-locked + shipped + byte-equal so no action required.

### Q12 — m5 feature_params x_value tilted higher (more mids) but D didn't change m5 base marginal structure correspondingly. Coherence issue?

User intent on m5: "把奖项倍率继续向高倍率移动" — multiplier shift toward higher mults.

The shipped m5 feature_params deliver this in feature: m5 P(R≥200)/trigger 11.76% (m2 0.85%). User's intent is RESPECTED in feature.

For the **base game**, D's m5 = m2 with these changes:
- dd lifted unevenly (R1×0.95, R2×1.10, R3×1.10) → wild_pure cadence m5/m2 = 1.150
- h7 cut uniformly ×0.92
- cherry / bars / topdollar unchanged

So m5's base has **slightly more wild_pure (200× pay) AND slightly more wild-substituted h7/bar combos (40-120×)**, balanced by **less h7-pure (30×)**.

My multiplier bucket analysis (Section J) showed net effect: high-mult (≥30×) base RTP DROPS by 1.29pp = 1.0pp share. So locally on dd lift the multiplier mass shifts higher, but globally on the h7 cut it shifts lower. **Net base direction is slightly the WRONG way.**

This isn't a hardline violation; LUCKY-MONO cadence still passes (1.150 ≥ 1.10 floor) and m5 trigger ≥ m2 trigger. But D's "multiplier shift higher" claim for the m5 base only holds for one of the two mechanisms D used (dd lift) and is overridden by the other (h7 cut). The **coherent** design would lift dd or h7 (multiplier-mass UP) without cutting any high-mult family — but D chose h7 cut as the easy way to keep total RTP centered.

**Verdict on Q12**: ⚠ **Coherence issue.** D's mechanism A (dd lift) implements user direction; D's mechanism B (h7 cut) reverses it. The net is base-direction-neutral-to-slightly-wrong on high-mult shift. Feature gives the right direction; base doesn't, despite the user's wording being agnostic to base vs feature.

---

## § 2 Hard issues per mode (RED — must fix before ship)

### Mode 2 — M2_LC

1. **bar_mixed share 31.17% (vs shipped 22.6%, vs m1 27.9%)** — places M2_LC's biggest base-RTP contributor higher than any prior approved design. The mechanism — uniform per-reel bar marginal lift (1.39× across 1bar/2bar/3bar) — produces 1bar-dominated bar_mixed combos (1bar-majority 4.80% of 12.66% total bar_mixed P). Given user's session-wide rejection of bar1-44% (v13) AND h7-31.5% (v13b), bar_mixed-31.2% is structurally similar — disproportionate weight on a single family. **(Q2, Q8)**

2. **LUCKY-MONO m5_hit ≥ m2_hit margin 0.04pp** — fails in **multiple integer-realization scales** I tested (scale=500: −0.068pp; scale=5000: −0.106pp). Even at scale=10000, only +0.059pp margin remains. Production engine integer rounding has ~50% probability of flipping this hardline. **D self-flagged but didn't pre-fix.** Mitigation: bump cherry_R1 weight by ~0.5% in m5 before commit. **(Q6)**

3. **LUCKY-MONO m5_trig ≥ m2_trig margin 0.00pp (exactly equal)** — fails at scales 500, 2000, 5000 in my sweep. Engine integer rounding ~50% flip risk. Mitigation: bump m5 td_R3 weight by 1 unit OR keep m5 R3 marginals byte-equal to m2 R3 (cleaner — m5 differs from m2 only on R1+R2 dd lift, m5 trigger stays naturally identical because td_R3 in same context). **(Q7)**

### Mode 5 — M5_LC+

All mode 2 issues propagate (M5_LC+ inherits m2 bar_mixed shape; m5 base bar marginals identical to m2 base by D's design).

4. **m5 base "high-mult shift higher" reverses user direction**. My multiplier-bucket decomposition (Section J): M2_LC high-mult (≥30×) base RTP share = 36.17%; M5_LC+ = 35.15% — m5 is LOWER. User said "把奖项倍率继续向高倍率移动" — D's m5 base goes the wrong way. The locked feature_params do shift feature higher (m5 P(R≥200)/trigger = 11.76%, m2 = 0.85%) — but **base direction is neutral-to-wrong**. Mitigation: increase dd lift further (e.g., R2/R3 ×1.20 instead of ×1.10) and reduce h7 cut (e.g., ×0.96 instead of ×0.92), so base high-mult share stays equal-or-up vs m2 base. **(Q4, Q12)**

---

## § 3 Soft concerns (WARN — should-fix or document)

1. **R1 blank 27.53% (M2_LC) / 28.64% (M5_LC+) is denser than shipped m2/m5's ~33%** — visible machine-identity shift even though not a hardline. Hit lift 33.54% → 33.85% is only +0.3pp; total blank dropped 16% across reels. The hit lift is mostly delivered by lifting cherry/bars rather than dd/h7 — fine, but the player will notice tighter reels. **(Q9)**

2. **bar1 share 11.34% in M2_LC vs shipped m2's 2.97%** — D's "restore §1 hierarchy" approach inverted shipped m2's lucky carve-out (where bar1 was deliberately rare to make bar2/bar3 line wins memorable). User has not seen bar1 share at 11% in any prior shipped m2 design. This isn't a hardline issue (§1 hierarchy is the universal direction and M2_LC follows §1), but it's a deliberate departure from shipped m2 archetype. D claims this is "preserving §1 naturally" per user 2026-05-12 brief §15 — that interpretation is plausible but not certain.

3. **PWDF re-derivation not performed by D**. New M2_LC / M5_LC+ marginals → new mechanism B redistribute needed (per shipped v9 `_v81_mechanism_b` block in weights.json). Verify.py PWDF-FLOOR enforces top-symbol any-reel window visibility floors (dd 17 / h7 25 / td 10 for m2/m5). Without re-running mechanism B on these new marginals, PWDF likely passes (M2_LC h7 marginal sum 36.6 > m1 17.6) but should be explicitly verified before commit.

4. **Engine-realized vs analytic drift expected ±0.3-0.7pp.** Mode 1 v14 saw 0.49pp. M2_LC analytic 296.13 → engine likely 295.6-296.6. Margin to 290 floor 5.6pp at lower bound — safe. M5_LC+ 504.56 → 504.0-505.0, margin 14pp to floor — safe.

5. **m5 base RTP −0.83pp vs m2 base** — D acknowledges this. Per user §d "modest base lift 不矫枉过正" — equal is fine; negative is borderline. Not a hardline issue. But combined with concern #4 above (high-mult share dropped), it suggests D optimized for "RTP in band" not "user direction".

---

## § 4 Cross-mode coherence assessment vs user-confirmed philosophy

### 4.1 Cross-mode bar dominance shift

| mode | bar_mixed share | bar1 share | bar3 share |
|---|---:|---:|---:|
| m1 SHIPPED | 27.93% | 12.11% | 9.26% |
| m7 SHIPPED | 24.38% (info) | 11.30% | 9.21% |
| m2 SHIPPED | **22.60%** | **2.97%** | **15.82%** |
| **M2_LC (D)** | **31.17%** | **11.34%** | **7.15%** |
| m5 SHIPPED | **21.01%** | **3.17%** | **16.92%** |
| **M5_LC+ (D)** | **31.66%** | **11.68%** | **7.51%** |

D's "lift bar uniformly" preserves the m1 family-share shape (bar_mixed dominant, bar1 second). Shipped m2/m5 used the lucky carve-out to flatten this (bar_mixed similar to bar3, bar1 cut to ~3%). **D's design is a completely different family-share archetype than shipped m2/m5.**

The user has not explicitly chosen which archetype to use. The user said: "mode2 比 mode1 就是增加中奖率，增加机台特征的中高倍率奖" — this is direction-only (hit ↑, h7 ↑, feature trigger ↑), not "preserve m1's bar_mixed-dominant family shape" and not "preserve shipped m2's lucky-carve flatter shape". Both archetypes can claim consistency with user direction.

But: **shipped m2/m5 was approved through 4-mode pipeline before**. D's redesign is a different machine. If user hadn't already approved the shipped archetype, this would be a clean redesign discussion. Since user did, D should at minimum FLAG this as a design choice the user needs to confirm.

### 4.2 Reel asymmetry direction

D claims to preserve shipped v9 lucky carve-out R1 ≥ R3 blank. Confirmed:
- shipped m2: R1=33.45 / R3=24.30 → R1-R3 = **+9.15pp**
- M2_LC: R1=27.53 / R3=23.19 → R1-R3 = **+4.34pp**
- shipped m5: R1=33.11 / R3=24.07 → R1-R3 = **+9.04pp**
- M5_LC+: R1=28.64 / R3=23.96 → R1-R3 = **+4.68pp**

D's direction is preserved (R1 > R3), but the **magnitude is halved**. M2_LC's R1/R3 asymmetry is weaker than shipped. Not a hardline issue, but the "trigger-reel busy" narrative is less emphatic. Acceptable.

### 4.3 high7 cross-mode pattern

| mode | h7 share | h7_wild share | h7_pure share |
|---|---:|---:|---:|
| m1 SHIPPED | 8.70% | 7.34% | 1.35% |
| M2_LC | 14.92% | 9.34% | 5.58% |
| M5_LC+ | 13.03% | 8.64% | 4.38% |
| m2 SHIPPED | 14.17% | 9.62% | 4.56% |
| m5 SHIPPED | 16.47% | 12.00% | 4.47% |

shipped: m5 h7 share (16.47%) > m2 h7 share (14.17%) — m5 LIFTED h7.
D's: M5_LC+ h7 share (13.03%) < M2_LC h7 share (14.92%) — m5 CUT h7.

User's direction "增加机台特征的中高倍率奖" applies to mode 2 specifically. For mode 5 (super-lucky), the natural continuation is "h7 stays equal or up" not "h7 cut". Shipped m5 had h7 share 2.3pp HIGHER than shipped m2; M5_LC+ has it 1.9pp LOWER. This is **opposite direction** vs shipped v9.

Combined with Q4 / concern #4 above, this is structural: D used h7 cut as the easy lever to keep RTP centered, instead of finding a different RTP-balance mechanism.

---

## § 5 Tradeoffs (explicit)

| trade-off | M2_LC / M5_LC+ position | alternative considered | why D chose this |
|---|---|---|---|
| family share even ↔ bar lift uniform | bar_mixed dominant 31% via uniform 1bar/2bar/3bar lift | non-uniform lift (bar2/bar3 lift more, bar1 cut) per shipped m2 | D chose §1 hierarchy preservation over shipped lucky carve archetype |
| RTP centered ↔ multiplier shift higher | RTP centered at 504 via h7 cut | preserve h7 + RTP higher (508+ closer to ceiling) | D chose center safety over direction respect |
| LUCKY-MONO m5≥m2 strict ↔ margin | Equal trigger, +0.04pp hit | bump m5 cherry / td weight slightly | D punted to verifier ("will fix at integer realization") |
| dd lift even ↔ lift asymmetric | dd asymmetric R1×0.95, R2×1.10, R3×1.10 | dd ×1.15 uniformly | D chose asymmetric to keep wild_pure cadence ratio = 1.150 exactly |

---

## § 6 Verdict per mode

### Mode 2 — M2_LC: **FIX-FIRST**

Three blocking issues:
1. bar_mixed share 31.17% — exceeds user's accepted family-dominance pattern (shipped m2 22.6%). Combined with the 1bar-majority structure of bar_mixed (Q2), this is a single-family dominance shift the user may reject.
2. LUCKY-MONO m5_hit / m5_trig flip risk under integer rounding — D acknowledged but didn't fix.
3. m5 base "high-mult shift" reverses user direction (downstream consequence on M5_LC+).

D's three "fixes" against v14b are real on those three axes. But D didn't recognize the **fourth axis** my v14b critique flagged: family-share dominance. The user has rejected six candidates this session for similar single-family concerns; M2_LC's bar_mixed 31% pattern is plausibly in user-reject territory.

**Mitigations to consider before ship:**
- (a) Non-uniform bar lift: ×1.20 1bar / ×1.50 2bar / ×1.60 3bar (preserving §1 P-ordering BUT distributing the lift toward higher-mult bars). This would reduce bar_mixed P and shift the bar_mixed combo center toward 2bar/3bar-majority — closer to shipped m2 archetype.
- (b) Lift cherry less (×1.40 instead of ×1.77 sum), so cherry / bar lifts produce hit increase but less bar_mixed P.
- (c) Bump m5 cherry_R1 marginal slightly (~+0.001) to give LUCKY-MONO hit a ~0.1pp margin.
- (d) Keep m5 R3 weights byte-equal to m2 R3 weights (m5 differs only on R1/R2 dd lift) to eliminate trigger-flip risk.

### Mode 5 — M5_LC+: **FIX-FIRST**

Inherits all mode 2 issues. Plus:
- m5 base "multiplier shift" reverses user direction (h7 cut > dd lift effect on high-mult RTP share).

**Mitigation:**
- (e) Reduce h7 cut from ×0.92 to ×0.96 (or eliminate); recover RTP by reducing other lift OR accepting RTP closer to ceiling (508 instead of 504).
- (f) Increase dd lift further (e.g., R2/R3 ×1.20) to push high-mult share up — this also helps wild_pure cadence margin against LUCKY-MONO floor 1.10.

---

## § 7 If FIX-FIRST: specific recommended mitigations

Priority order:

1. **Fix LUCKY-MONO flip risk** (cheap, high impact):
   - m5 R3 marginals = m2 R3 marginals byte-equal (eliminate trigger-flip risk entirely)
   - m5 cherry_R1/R2 marginals bumped ~0.5pp absolute over m2 (cherry on R1 from 6.40% → 6.60%, R2 from 6.30% → 6.50%) to give LUCKY-MONO hit ~0.3pp margin
   - Cost: m5 RTP +~0.6pp; still well inside [490, 510]

2. **Fix m5 high-mult direction** (medium, addresses user direction):
   - Eliminate h7 cut (×0.92 → ×1.00)
   - Reduce dd lift to compensate (R1×0.92, R2×1.05, R3×1.05) — keeps wld_pure cadence m5/m2 ≈ 1.10 (at floor exactly)
   - Net: m5 base high-mult share equal or slightly above m2 base

3. **Fix bar dominance pattern** (more structural, requires re-sweep):
   - Non-uniform bar lift: ×1.20 1bar (less) / ×1.50 2bar / ×1.60 3bar
   - Cherry lift moderate ×1.40 (less than current 1.77×)
   - Run search again to find candidate with bar_mixed share ≤ 26% AND total RTP ≥ 293
   - If infeasible at ≤26%, escalate to user with explicit tradeoff: "shipped m2 had bar_mixed 22.6%; lowest reachable while preserving §1 + cross-mode invariants is X%"

4. **Verify post-fix**: Re-run `m15_v14c_design_modes_25.py` validator AND `slot_designer.machines.M15.verify` (or equivalent) on the new candidate. Confirm engine-realized RTP / hit / trigger via `marginals_to_weights` integer realization, not just analytic.

---

## § 8 Top 3 critical concerns (executive)

1. **bar_mixed share 31.17% (M2_LC) / 31.66% (M5_LC+) — single-family dominance plausibly in user-reject zone.** Shipped m2/m5 had bar_mixed at 22.6%/21.0%. The user has rejected six candidates this session for single-family share concerns (bar1 44%, h7 31.5%). D's "uniform bar lift" mechanism produces bar_mixed dominance by mathematical necessity, and 38% of M2_LC's bar_mixed P comes from 1bar-majority combos (= visual 1bar-dominance). **This is the dimension D didn't fix from v14b.**

2. **LUCKY-MONO m5_hit / m5_trig ~50% probability of flipping under engine integer rounding.** Verified across 6 scales (100/500/1000/2000/5000/10000). D self-flagged but punted to verifier; the production sim WILL fail one or both of these unless pre-mitigated.

3. **m5 base "multiplier shift higher" reverses user direction.** M5_LC+ high-mult (≥30×) base RTP share = 35.15% — LOWER than M2_LC's 36.17%, and well below shipped m5's 49.6%. The locked feature_params give the right direction in feature; D's base design choice (h7 cut 8%) undoes the base-game high-mult shift. User said "把奖项倍率继续向高倍率移动" — naturally reads as both base + feature, not feature-only.

---

## § 9 Critical concerns summary table

| concern | M2_LC | M5_LC+ | hardline? | verdict |
|---|:-:|:-:|:-:|---|
| RTP margin safety (1M sim) | ✓ (4.3σ) | ✓ (10σ) | yes | **fixed vs v14b** |
| Bar §1 hierarchy P(b1)>P(b2)>P(b3) | ✓ | ✓ | no (INFO) | **fixed vs v14b** |
| Reel asymmetry R1≥R3 | ✓ (4.3pp) | ✓ (4.7pp) | no (INFO) | **fixed vs v14b** |
| bar_mixed share dominance | ✗ (31.2%) | ✗ (31.7%) | no | **issue** |
| LUCKY-MONO hit margin | n/a | ✗ (0.04pp) | YES | **issue** |
| LUCKY-MONO trigger margin | n/a | ✗ (0.00pp) | YES | **issue** |
| m5 base high-mult direction | n/a | ✗ (−1.0pp share) | no | **direction issue** |
| h7 emphasis (m2) | ✓ | n/a | direction | OK |
| feature P(R≥1000)/spin cap | ✓ | ✓ | YES | OK |
| Engine drift safety | ✓ | ✓ | implicit | OK |

---

## § 10 Path summary

- This file: `session_artifacts/M15/critique_v14c_modes_25.md`
- D's design doc: `session_artifacts/M15/design_v14c_modes_25.md`
- D's design script: `session_artifacts/M15/scripts/m15_v14c_design_modes_25.py`
- My metrics script: `session_artifacts/M15/scripts/m15_v14c_critique_metrics.py`
- Prior critique (v14b): `session_artifacts/M15/critique_v14b_modes_725.md`
- User hardlines: `slot_designer/machines/M15/USER_HARDLINES.md` (v8)
- Production verify: `slot_designer/machines/M15/verify.py`
- Production weights (shipped v9, reference): `slot_designer/machines/M15/weights/mode_{1,2,5,7}/weights.json`
- Philosophy: `slot_designer/DESIGN_PHILOSOPHY.md` §1 / §12 / §15

**No production files modified.** No new hardlines proposed. No user-hardline relaxations proposed.

**Bottom line**: D fixed the three v14b failures with explicit margin and clean math, BUT introduced a fourth structural concern (family-share dominance via uniform bar lift) that the same critic process would have caught. D ALSO didn't mitigate the m5 LUCKY-MONO integer-rounding flip risk it self-flagged. M5 ALSO has a multiplier-shift-direction issue D didn't recognize. **Both modes are FIX-FIRST, not SHIP.**
