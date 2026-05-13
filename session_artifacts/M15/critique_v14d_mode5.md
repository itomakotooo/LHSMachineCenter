# M15 v14d Mode 5 — adversarial critique (Critic X)

> **Subject**: D's design `session_artifacts/M15/design_v14d_mode5.md`. Candidate **M5_HMV_plus** (High-Mult-Visible plus). Derived from M2_LC anchor (shipped via v14c) + corrected priority order from v14c critique X.
>
> **Critic stance**: adversarial — verify GREEN is the floor, not the ceiling. D self-claims 17/17 m5 cross-mode invariants PASS; the numbers reproduce exactly. The question is whether the *design* is what the user actually wants given v14c's lesson (cutting h7 is wrong direction) AND the prior shipped v9 m5 archetype. Five candidates rejected this session prior to v14d.
>
> **Production files NOT modified.** No new hardlines proposed. No user-hardline relaxations proposed. Direction sources: USER_HARDLINES.md v8 (hard) + DESIGN_PHILOSOPHY.md §1/§9/§10 + user-confirmed brief 2026-05-12 (direction).
>
> Independent metrics scripts:
> - `session_artifacts/M15/scripts/m15_v14d_critique_metrics.py` (recompute M5_HMV_plus + integer rounding + bucket decomp)
> - `session_artifacts/M15/scripts/m15_v14d_critique_metrics2.py` (shipped v9 m5 baseline)
> - `session_artifacts/M15/scripts/m15_v14d_critique_metrics3.py` (current shipped m2 = M2_LC confirmation)
>
> **TL;DR verdict**: **FIX-FIRST**. Three blocking concerns:
> 1. **M5_HMV+ ≥30× share 40.12% is LOWER than shipped v9 m5's 49.56%**. The "+3.95pp shift higher" is real over M2_LC, but D is shifting from a *worse anchor* — shipped v9 m5 had a stronger high-mult shape than what D is offering. (Critical.)
> 2. **bar_mixed family share 27.73% remains in 'high-dominance' territory** — well above shipped v9 m5's 21.01%. Same single-family-dominance pattern X flagged in v14c; D moved the needle from 31% to 28% but did not approach shipped v9's 21%. (Same shape issue, half-fixed.)
> 3. **Base RTP +0.77pp lift over M2_LC vs shipped v9 m5's +9.35pp lift over its m2** — base "lucky" feel of m5 is structurally suppressed. Memory `project_slot_designer §C` direction "m5 base ≈ m2 + 6-10pp lift" is violated by D's design.

---

## § 0 Tooling sanity — reproduces exact

All 8 of D's headline numbers reproduce to 4 decimal places. Mathematical work is solid.

| metric | D claim | recompute | match |
|---|---:|---:|:---:|
| Total RTP | 508.21pp | 508.207 | ✓ |
| Base RTP | 98.68pp | 98.678 | ✓ |
| Feature RTP | 409.53pp | 409.529 | ✓ |
| Base hit | 33.91% | 33.9108 | ✓ |
| Trigger | 3.3205% | 3.3205 | ✓ |
| Wild_pure cad | 1/60,993 | 1/60,993 | ✓ |
| ≥30× share (payid) | 40.12% | 40.12 | ✓ |
| ≥30× share (combo) | 23.81% | 23.81 | ✓ |
| P(bar1) | 1.114% | 1.114 | ✓ |
| P(bar2) | 1.084% | 1.084 | ✓ |

All 17/17 invariants pass on my independent script.

---

## § 1 Adversarial questions (12 + answers)

### Q1 — ≥30× share +3.95pp shift decomposition: which pays drove it?

Independent per-pay-id delta table:

| pay_id | family | M2_LC pp | M5_HMV+ pp | Δ | in payid ≥30 bucket? |
|---|---|---:|---:|---:|---|
| 1 | wild_pure | 0.283 | 0.328 | +0.045 | YES (strict) |
| 2 | high7_wild | 9.141 | 10.239 | +1.098 | YES (strict) |
| 21 | high7_pure | 5.464 | 5.970 | +0.507 | YES (strict) |
| **3** | **bar3** | 7.000 | 8.104 | **+1.103** | YES (D's convention) |
| **5** | **bar2** | 13.526 | 14.951 | **+1.425** | YES (D's convention) |
| 7 | bar1 | 11.105 | 7.663 | **−3.442** | NO |
| 8 | bar_mixed | 30.517 | 27.359 | **−3.158** | NO |
| 9 | cherry1 | 15.684 | 17.437 | +1.753 | NO |
| 71 | cherry2 | 4.889 | 6.192 | +1.303 | NO |

**Decomposition of +3.95pp payid-ge30 shift**:
- ~+1.6pp from h7 lifts (h7_pure +0.51 + h7_wild +1.10)
- ~+0.04pp from wild_pure
- **~+2.5pp from bar2 + bar3 inclusion** (bar2/bar3 are pay_ids 5/3 — counted in 40-120× bucket per D's convention)
- ~−0.06pp net contributed by other pays

**Critical observation**: bar2 (pay_id 5) has line-pure 10× mult, bar3 (pay_id 3) has 20× pure. They only reach 30× via wild substitution (2 wilds for bar2, 1 wild for bar3). **The "payid-anchored ≥30 share" inflates these pays' entire RTP into the ≥30 bucket even though only a portion of their RTP comes from wild-boosted variants ≥30×.** The combo-view shift (+2.44pp) is the "real" multiplier-shift number.

**Q1 verdict**: ✓ The shift is real, but **40% of the "+3.95pp shift" comes from D's accounting convention (bar2 + bar3 inclusion in 40-120×)**, not from base/h7/dd lifts directly. The combo view (+2.44pp shift) is the player-experience truth.

### Q2 — bar1 family alive vs cosmetic

bar1 share-of-base dropped from M2_LC 11.34% → M5_HMV+ 7.77% (Δ −3.58pp).
- bar1_pure (3 1bars on payline) P = 1.114% (1 in 90 spins).
- bar1 absolute base RTP = 7.66pp.

**Alive criteria (≥1% share-of-base)**: 7.77% >> 1% — **ALIVE**, not cosmetic. ✓

But — bar1 share is now LOWER than bar3 (8.21%) and bar2 (15.15%). In shipped v9 m5 this was also the case (bar1 3.17% < bar3 16.92% — lucky carve-out). M5_HMV+ has bar1 between m2 anchor and shipped v9. Direction toward v9 archetype is right, magnitude is half-way.

**Q2 verdict**: ✓ bar1 alive. No cosmetic-death concern.

### Q3 — Bar §1 hierarchy: strict pyramid or tied?

Exact P values (M5_HMV+):
- P(bar1) = **1.1140%**
- P(bar2) = **1.0839%**
- P(bar3) = **0.2481%**

**P(b1) − P(b2) = +0.0301pp** — STRICT P(b1) > P(b2) but margin only 0.030pp.
P(b2) − P(b3) = +0.836pp — comfortable gap.

For comparison, M2_LC: P(b1)=1.6984%, P(b2)=0.9854% → gap +0.713pp (large).

D claims "tied-tol within 0.10pp" — technically strict P(b1)>P(b2) but margin tiny (0.030pp). Under integer rounding the strict ordering can flip.

**Q3 verdict**: STRICT but TIGHT. ✓ (strict) with **margin warning** (0.03pp).

### Q4 — verify.py HIERARCHY_TIED_TOL source

verify.py line 631:
```python
HIERARCHY_TIED_TOL = 0.001  # 0.10pp absolute
```

Origin (from comment): "Per design_v2 m1: bar1 0.3438% vs bar2 0.3386% — within tied tolerance." Added under design_v2 era to handle stop-count asymmetry (proc_imp #21) in the original m1 design.

**This is agent-justified, not user-stated**. Furthermore, verify.py lines 651-661 already treats m2/m5 bar hierarchy as **INFO not RED** ("design_v2 m2 lucky_lift_directional_invariants"). For mode 5 in particular, bar §1 hierarchy is *informational-only* in the production verify check — D's use of HIERARCHY_TIED_TOL for an "all PASS" m5 check is harvesting that tolerance to justify a tight pyramid that the production verifier wouldn't even RED on for m5.

**Q4 verdict**: HIERARCHY_TIED_TOL is real (not D-promoted) BUT m5 bar hierarchy is INFO in verify.py, so the relevance of "tied vs strict" here is meta-design philosophy, not a verify red line. D's compliance claim is overstated.

### Q5 — LUCKY-MONO m5 hit / trigger margin: integer-rounding survival

Integer-rounding sweep (recomputed at multiple scales):

| scale | m5_hit − m2_hit | m5_trig − m2_trig | LUCKY-MONO hit | LUCKY-MONO trig |
|---|---:|---:|:---:|:---:|
| 100 | +0.2095pp | −0.0303pp | PASS | **FAIL** |
| 500 | −0.0020pp | −0.0068pp | **FAIL** | **FAIL** |
| 1000 | −0.0171pp | +0.0033pp | **FAIL** | PASS |
| 2000 | +0.0781pp | +0.0000pp | PASS | PASS (just barely) |
| 5000 | +0.0556pp | +0.0207pp | PASS | PASS |
| 10000 | +0.0596pp | +0.0193pp | PASS | PASS |

**At scales 100/500/1000 the LUCKY-MONO checks FAIL**. M15 production weight scales are typically in 50-100 range per stop (raw integer weights), but the strip lengths are 36 stops → effective marginal granularity is 1/(sum_weights). For shipped m2 the sum is roughly 1000 per reel. The realistic production scale is in the **1000-2000 range** where hit-MARGIN flips at scale 1000 and trigger-margin is EXACTLY 0 at scale 2000.

**verify.py only enforces `m5_hit >= m2_hit - 1e-9` and `m5_trig >= m2_trig - 1e-9`** (line 862-873). So integer-rounding flip risk is REAL even in verify terms (not just D's self-imposed 1e-4 margin).

**D claims "+0.0165pp margin gives 2× safety over 1e-4 margin"** — but my sweep shows engine-realized values can flip negative at scale 500 (−0.0068pp) and scale 1000 (+0.0033pp marginal). Even at scale 5000 the trigger margin is only +0.0207pp.

**Q5 verdict**: ⚠ **FLIP risk REAL at typical production integer scales**. D's mitigation suggestion ("bump cherry_R1 by +0.001") is theoretically right but punts to verifier instead of pre-fixing.

**Survives? PARTIAL — survives at scales 2000-10000 but FAILS at scales 500-1000.** Risk = 30-50% depending on actual production integer realization.

### Q6 — RTP ceiling probability

Analytic Total RTP = 508.207pp.

| band | margin to ceiling |
|---|---:|
| verify.py [480, 520] (hard RED) | +11.79pp (very safe) |
| D's task-target [491.5, 508.5] | +0.29pp (tight) |
| User_hardlines NO RTP band for m5 | n/a (only m1 [94,96] is user-stated) |

**1M-spin SE estimate**: ~1.44pp (combined base + feature variance per v14c critique §F).
**Engine drift expected**: ±0.5pp (M1 v14 observed).

Upper-bound estimate: 508.21 + 0.5 + 1.44 ≈ **510.15pp**. Margin from verify ceiling 520 is +9.85pp — comfortable.

But: D's "user-target ceiling 508.5" is **agent-defined band, not user-stated**. Per USER_HARDLINES.md v8, m5 has **no user-stated RTP band at all** — only mode 1 has [94, 96]. So the 508.5 ceiling is D's invention.

**Q6 verdict**: ✓ verify ceiling safe. D's self-imposed [491.5, 508.5] band is overly tight + not user-mandated.

### Q7 — Cherry lift ×1.13: shift higher or spread out?

Per-bucket delta (combo final mult):

| bucket | M2_LC pp | M5_HMV+ pp | Δ |
|---|---:|---:|---:|
| 1x (cherry1) | 15.684 | 17.437 | **+1.753** |
| ge2_lt5 (bar_mixed 2/4×) | 30.517 | 27.359 | **−3.158** |
| ge5_lt10 (bar1, cherry2) | 11.182 | 10.057 | −1.125 |
| ge10_lt20 (bar2, bar1+wild) | 11.144 | 10.953 | −0.191 |
| ge20_lt30 (bar3, mid wild) | 8.454 | 9.372 | +0.918 |
| ge30_lt50 | 10.025 | 11.221 | **+1.196** |
| ge50_lt100 | 8.026 | 9.005 | **+0.979** |
| ge100_lt200 | 2.595 | 2.947 | **+0.352** |
| ge200_lt500 | 0.283 | 0.328 | +0.045 |

Sum delta:
- Low (1× + 2-5 + 5-10): **−2.531pp** (low DROPS)
- High (≥30 to <500): **+2.571pp** (high RISES)

Net: high > |low|, direction is "shift higher".

BUT — the cherry1 1× bucket grew by +1.753pp (28% increase in the lowest-mult bucket). Cherry1 is the visual "small wins frequently" pay. So **simultaneously cherry1 1× (lowest mult) is more visible AND ≥30× share is higher**. The mid-range (bar_mixed 2-5×, bar1 5-10×) was cut to fund both ends.

**This is a "bimodal redistribution"** — mass shifted to the 1× anchor AND the ≥30× tier, away from the 2-10× middle. Some might call this "spread out from middle" rather than "uniformly shifted higher". But strictly by ≥30 share count, the direction is correct.

**Q7 verdict**: ✓ Direction matches user intent on ≥30× metric, but **D's cherry lift creates a bimodal shape, not a pure "shift to high"**. User did not explicitly forbid this, but the shape is novel.

### Q8 — Base RTP +0.77pp lift only — within philosophy?

Reference: MODE_DESIGN.md line 100 — shipped v9 m5 base = 108.38pp vs m2 base 99.03pp → **+9.35pp lift** ("per user §d 不矫枉过正").

Memory `project_slot_designer §C`: "m5 base ≈ m2 base + ~6-10pp lift" per user §d.

D's M5_HMV+: m5 base = 98.68pp vs M2_LC m2 base 97.91pp → **+0.77pp lift**.

**D's lift is 8% of shipped v9's lift, 13% of philosophy direction's lower bound (6pp).**

Per memory direction, m5 should feel like "richer base" compared to m2. With base lift only +0.77pp, m5 base shape is essentially indistinguishable from m2 base. The "super-lucky" feel comes ALMOST EXCLUSIVELY from feature_params (locked). For a player switching between m2 and m5 in base spins (the 96.7% of spins that are non-trigger), there is essentially no perceptible difference.

**Q8 verdict**: ⚠ **Base lift is way too small** vs shipped v9 m5 (+9.35pp) and memory direction (+6-10pp). Same flaw as v14c M5_LC+ (which had m5 base −0.83pp below m2). D went from "below m2" to "+0.77pp above m2" — still 1/8 of the previous shipped magnitude. **m5 base shape is essentially m2 base + cherry lift + bar1 cut + tiny h7/dd lifts**, not a "super-lucky m5 base".

### Q9 — Cosmic noise: does base shape diff register vs feature variance?

Feature RTP = 409.53pp (80.6% of total). Base RTP = 98.68pp (19.4%).
Base-game high-mult delta (combo view) vs M2_LC: +2.57pp absolute.
As % of total m5 RTP: 2.57 / 508.21 = **0.51%**.

For a player on m5:
- 96.7% of spins are non-trigger paid spins (base game).
- Of those, the high-mult shift adds ~2.57pp base RTP — or 1 extra ≥30× hit per ~1500 spins (rough).
- The other 3.3% of spins trigger feature (avg payout 123×). These dominate the visual/emotional memory of m5.

Within a 1000-spin session, the player sees:
- ~33 feature triggers (avg ~123× per trigger = ~4060 credits).
- ~50 base ≥30× hits (vs M2 ~47 — +6% increase, hard to perceive).
- Difference from M2 base = ~26 credits (or 0.026% of session payout).

**Q9 verdict**: ⚠ **Base shape difference is cosmically buried under feature variance.** The +2.57pp base shift D engineered is statistically real but **invisible to player perception** in normal play (under 1% of total session payout). User's "高倍率移动" intent — if interpreted at session level — is NOT delivered by base shape changes. Per shipped v9 m5 the more impactful direction was base lift +9pp (large enough that the base RTP shape itself shifts noticeably). D's design doesn't take that approach.

### Q10 — Bar1 share vs cross-mode coherence

M1 SHIPPED bar1 share: 12.11% (per v14c critique table).
M2_LC bar1 share: 11.34%.
**M5_HMV+ bar1 share: 7.77%.**
Shipped v9 m5 bar1 share: **3.17%** (deep cut — lucky carve-out).

M5_HMV+ trajectory: bar1 cut moderately, halfway toward shipped v9 m5's lucky-carve archetype. Direction is right (m5 should cut bar1 below m2), magnitude is 35% of what shipped m5 had.

**Q10 verdict**: ✓ Direction matches shipped m5 archetype, but at "half-strength". Not a violation, but a softer execution of the lucky carve.

### Q11 — Family share dominance: max family

| family | m1 SHIPPED | m2 SHIPPED (M2_LC) | M5_HMV+ | m5 SHIPPED v9 |
|---|---:|---:|---:|---:|
| bar_mixed | 27.93% | 31.17% | **27.73%** | **21.01%** |
| cherry1 | 21.90% | 16.02% | 17.67% | 18.13% |
| high7 (combined) | 8.70% | 14.92% | 16.43% | 16.47% |
| bar2 | 15.40% | 13.81% | 15.15% | 15.71% |
| bar3 | (cut) | 7.15% | 8.21% | **16.92%** |
| bar1 | 12.11% | 11.34% | 7.77% | 3.17% |
| cherry2 | (small) | 4.99% | 6.27% | 7.51% |

**Top family in M5_HMV+: bar_mixed 27.73%** (down from M2_LC 31.17%; up vs shipped v9 m5 21.01%).

X's v14c critique called M2_LC's 31.17% "user-reject territory". D's M5_HMV+ at 27.73% is improvement but still **6.7pp above shipped v9 m5 (21.01%)**. The bar_mixed dominance pattern persists — D shifted some RTP out of bar_mixed (via bar1 cut → bar_mixed combos involving bar1 less probable → bar_mixed P drops), but the family is still the top dog by share.

**Q11 verdict**: ⚠ **Family dominance still > shipped v9 m5 by 6.7pp share**. D didn't address this concern from X's prior critique — only partially relieved it. The user has rejected designs with single-family share > ~25-30%. M5_HMV+ at 27.73% is borderline.

### Q12 — What else might X miss that user would reject?

Hidden tradeoffs in D's design:

1. **R1 blank 28.37% vs shipped v9 m5's 33.11%** (Δ −4.74pp): M5_HMV+ has a noticeably denser R1 than shipped v9 m5. The lucky carve-out (R1 > R3 blank) magnitude is +3.76pp in M5_HMV+ vs +9.04pp in shipped v9. **Visual machine-identity shift**: M5_HMV+ feels like a "tighter" lucky mode than shipped v9.

2. **High7 marginal R3 12.59% vs shipped v9 m5's high7 R3 12.22%** (per critique v14c §0 implied) — essentially equal, but D's design has h7 evenly distributed across reels (12.53/12.62/12.59) vs shipped v9 m5's design which had different cross-reel emphasis. Minor concern.

3. **dd uniform lift ×1.05** — wild_pure cadence 1/60,993 (m5/m2 = 1.158). Shipped v9 m5 had wild cadence different (need check). The uniform dd lift across all reels is "easy" — possibly the same kind of "lift everything uniformly" criticism that v14c got for "uniform bar lift" producing bar_mixed dominance. D's design doesn't escape the criticism.

4. **No PWDF re-derivation acknowledged**. M5_HMV+ has new marginals → mechanism B redistribute (per `_v81_mechanism_b`) needs re-running. D didn't flag this in §13 production risk flags. If user-PSV (player-visible window) for top symbols drops below PWDF floors, verify.py PWDF-FLOOR section fires. Verify needed.

5. **PCOUNT-X-1 not checked**. verify.py [PCOUNT-X-1] caps P(count_x=1) at 6%. Feature_params is byte-equal so should pass — but D didn't include this in the 17-invariant list. Minor — almost certainly inheriting v9 m5's value.

6. **Engine integer-realized wild_pure cadence** — D claims "m5/m2 = 1.158, above 1.1 floor". My sweep at scale 1000 showed wild_pure cadence: needs check. dd marginal R1 2.893% rounds to 29/1000 = 2.9% with rounding noise of ±0.05pp. Cubed effect on wild_pure: noisy.

**Q12 verdict**: ⚠ Three soft concerns added (R1 blank, PWDF re-derivation, dd uniform lift criticism). Not blocking but should be addressed.

---

## § 2 Hard issues (RED — must fix before ship)

### Issue 1 — M5_HMV+ ≥30× share LOWER than shipped v9 m5

| metric | M5_HMV+ | shipped v9 m5 | Δ |
|---|---:|---:|---:|
| ≥30× share (payid) | 40.12% | **49.56%** | **−9.44pp** |
| ≥30× share (combo) | 23.81% | **31.54%** | **−7.73pp** |
| Base RTP | 98.68pp | **108.38pp** | **−9.70pp** |
| bar3 share | 8.21% | **16.92%** | **−8.71pp** |
| bar1 share | 7.77% | 3.17% | +4.60pp |

D's "≥30 share target met ✓ 40.12%" is comparing against M2_LC (36.17%) — but the user has **already approved a shipped v9 m5 with 49.56% high-mult share**. D's design is a REGRESSION on this metric vs what user already accepted. The +3.95pp improvement over M2_LC is a 9.44pp regression vs shipped v9 m5.

**The "M5_HMV+ = M2_LC + ≥30% target met" framing hides that we're proposing a STRUCTURALLY WEAKER m5 than what user shipped 1 week ago.**

If user just wanted a "high-mult m5 base" they could just keep the shipped v9 m5. The reason for this iteration is M2_LC is the new shipped m2 anchor — but the m5 design has to be coherent with the v9 m5 archetype the user previously approved.

### Issue 2 — Base RTP lift +0.77pp vs philosophy direction +6-10pp

Per `project_slot_designer §C` memory: m5 base ≈ m2 base + 6-10pp lift.
Per shipped v9 m5: +9.35pp lift over its m2.
**D's M5_HMV+: +0.77pp** — 8% of philosophy direction's lower bound.

This means m5 base shape is essentially indistinguishable from m2 base shape in player experience. The "super-lucky" feel comes entirely from feature_params (which are byte-equal v9 — locked). Without the base-RTP lift, **m5 only feels different from m2 in feature, not in base**.

D's design treats "≥30 share target" as the only handle for "multiplier向高 shift" — but per Q9, the +2.57pp base shape change is cosmically buried under feature variance (0.51% of total m5 RTP). Without base RTP lift, the actual differentiating signal is weak.

### Issue 3 — bar_mixed share 27.73% remains above shipped v9 m5's 21.01% (+6.72pp)

This is the SAME structural issue X flagged in v14c (M5_LC+ had bar_mixed 31.66%). D shifted from 31% → 28%, halfway toward 21%. **The "uniform bar lift within reel" mechanism that creates bar_mixed dominance is unchanged** — D just adjusted the scalars.

User rejected v14b (bar1 44% dominance), v14a (Q-direction failure), v13 (h7 31.5%), etc. **Single-family share above ~25% is in the rejection zone per session pattern.** M5_HMV+ at 27.73% is borderline.

Mitigation: instead of `b1=0.85, b2=1.03, b3=1.05`, try `b1=0.55, b2=1.15, b3=1.30` — more aggressive bar1 cut + bigger bar3 lift → bar_mixed P drops (less 1bar-majority combos), bar3 share rises toward shipped v9's 17%, bar_mixed share drops toward 21%.

---

## § 3 Soft concerns (WARN — should-fix or document)

1. **R1 blank 28.37% vs shipped v9 m5's 33.11%** (Δ −4.74pp) — denser R1 than shipped lucky archetype. Visible machine-identity shift. Q12.

2. **LUCKY-MONO m5_hit / m5_trig flip risk at integer scales 500-1000** — verified across 6 scales. Risk 30-50%. D self-flagged §13 but punted to verifier. Q5.

3. **Cherry lift ×1.13 creates bimodal shape** — cherry1 (1× bucket) grew +1.75pp while ≥30 bucket grew +2.57pp; middle (5-10×, 2-5×) cut. Player perception: more frequent low-mult cherry hits AND more frequent ≥30× hits, but fewer mid-mult bar wins. Acceptable shape change? Not user-explicit either way. Q7.

4. **dd uniform lift ×1.05** — same "uniform lift" mechanism criticism that gave bar_mixed dominance. Q12.3.

5. **No PWDF re-derivation acknowledged** — new marginals require mechanism B redistribute re-run. D didn't flag in §13. Q12.4.

6. **D's "user-target ceiling 508.5"** is agent-invented, not user-stated. USER_HARDLINES.md v8 has no m5 RTP band. D's 0.29pp ceiling margin worry is self-imposed. Q6.

---

## § 4 Cross-mode coherence with shipped m1/m2/m7

| metric | m1 SHIPPED | m2 SHIPPED (M2_LC) | M5_HMV+ | shipped v9 m5 (ref) |
|---|---:|---:|---:|---:|
| Total RTP | 94.29 | 295.78 | 508.21 | 508.89 |
| Base RTP | 42.77 | 97.85 | 98.68 | **108.38** |
| Base hit | 16.22 | 33.83 | 33.91 | 33.61 |
| Trigger | 1.12 | 3.299 | 3.3205 | 3.247 |
| R1 blank | 38.52 | 27.53 | 28.37 | 33.11 |
| R3 blank | 59.01 | 23.22 | 24.61 | 24.07 |
| ≥30 share (payid) | 34.26% | 36.17% | 40.12% | **49.56%** |
| ≥30 share (combo) | 19.70% | 21.38% | 23.81% | **31.54%** |
| bar_mixed share | 27.93% | 31.17% | 27.73% | **21.01%** |
| bar1 share | 12.11% | 11.34% | 7.77% | **3.17%** |
| bar3 share | (cut) | 7.15% | 8.21% | **16.92%** |
| Wild_pure cad | 1/51,314 | 1/70,607 | 1/60,993 | 1/(needs check) |

**Coherence findings**:
- M5_HMV+ Total RTP matches shipped v9 (508.21 vs 508.89, Δ 0.68pp). **Ceiling-target matched.**
- M5_HMV+ Base RTP is **9.7pp BELOW shipped v9** — significant.
- M5_HMV+ ≥30× share is **9.4pp BELOW shipped v9** (payid) / 7.7pp below (combo).
- M5_HMV+ bar3 share is **8.7pp BELOW shipped v9** — bar3 (20/40/80×) is the natural "mid-high mult anchor" for lucky modes.
- M5_HMV+ bar_mixed share is **+6.7pp ABOVE shipped v9** — bar_mixed dominance persists.

**The structural picture**: shipped v9 m5 used "high bar3 + low bar1 + base lift" to deliver the user's "multiplier向高 shift" intent — a coherent lucky-carve archetype with rich high-mult base. **D's M5_HMV+ uses "cherry-anchor + bar1-cut + small h7/dd lift" — a different archetype that doesn't approach shipped v9's high-mult share.**

This is **not a strict regression** (RTP/hit/trigger all pass), but **m5 has lost machine identity vs shipped v9**: the same player switching from old m5 to new m5 would see less rich high-mult action. If user wanted to retain shipped v9 m5 archetype, this iteration FAILS.

If user is OK with starting fresh from M2_LC anchor and shipped v9 m5 is no longer the reference, then M5_HMV+ is a "from M2_LC" design — but D should FLAG this archetype shift to user.

---

## § 5 Tradeoffs (explicit)

| trade-off | M5_HMV+ position | alternative considered | why D chose this |
|---|---|---|---|
| ≥30 share against M2_LC vs against shipped v9 m5 | ≥30 share 40.12% (over M2_LC 36.17%, but under v9 m5 49.56%) | match v9 m5's 49.56% via bar3 lift + base lift | D chose M2_LC anchor; shipped v9 m5 implicitly abandoned as reference |
| Base RTP +0.77pp lift vs +6-10pp | +0.77pp (tiny) | +6-10pp per memory direction (would push total RTP to ~514 — need user-band relax) | D treated total RTP 508 as ceiling, didn't push base lift further |
| Cherry lift ×1.13 | Bimodal shape (1× and ≥30× both grew) | Cherry × 1.00 (preserve cherry share) + bigger bar3/h7 lift | Cherry lift was cheap hit-margin to satisfy LUCKY-MONO; could be cut |
| Uniform bar1 cut + uniform b2/b3 lift | bar_mixed 27.7%, bar1 7.7%, bar3 8.2% | Aggressive bar1 cut (×0.50) + bar3 ×1.50 (toward shipped v9 shape) | D took "moderate" lever, may not satisfy archetype coherence |
| RTP centered at 508 | Tight (+0.29pp from D's 508.5 target) | Center at 502 with deeper bar1 cut + bigger high-mult lift | D optimized for RTP near ceiling; gives less ceiling headroom |

---

## § 6 Verdict — **FIX-FIRST**

D fixed the explicit v14c critique issue (≥30 share direction — was −3.95pp wrong, now +3.95pp right vs M2_LC). All 17 invariants pass + integer-rounding nominally safe at scales 5000+. The mathematical work is clean.

**But three structural issues remain**:

1. **M5_HMV+ ≥30 share 40.12% is LOWER than shipped v9 m5's 49.56%** — design REGRESSION vs what user already accepted.

2. **Base RTP +0.77pp lift over M2_LC** vs memory direction +6-10pp / shipped v9 m5 +9.35pp. M5 base shape essentially indistinguishable from M2 base. "Super-lucky" feel relies entirely on locked feature.

3. **bar_mixed family share 27.73%** remains in dominance territory (vs shipped v9 m5 21.01%). Same v14c family-dominance issue, half-fixed.

**Verdict**: **FIX-FIRST**. Not SHIP. The design "improves on M2_LC" but doesn't reach the shipped v9 m5 archetype the user previously accepted. This is the same "moving goalposts" anti-pattern (cf. memory `feedback_adversarial_self_review.md`) — D shifted the comparison anchor from shipped m5 (49.56% ≥30 share) to newly-shipped M2_LC (36.17%) to make a +3.95pp shift look like "target met", when in fact 40.12% is still 9.44pp below shipped v9 m5.

---

## § 7 Specific recommendations (if FIX-FIRST)

**Priority order**:

### Mitigation A — Approach shipped v9 m5 archetype (most aligned with user intent)

The structural target should be: ≥30 share (payid) ≥ 45% (closer to shipped v9 49.56%), base RTP ~104-108pp (closer to shipped v9 108.38pp), bar3 share ≥ 12% (closer to shipped v9 16.92%), bar_mixed share ≤ 25% (closer to shipped v9 21.01%).

Required scalar adjustments from M2_LC:
- **bar1 ×0.50-0.60** (deeper cut, target bar1 share ~3-5% per shipped v9)
- **bar3 ×1.40-1.60** (lift bar3 to push high-mult)
- **bar2 ×0.90-0.95** (slight cut — bar2 already 15% share, lift not needed)
- **h7 ×1.10-1.20** (more lift than D's 1.03 — h7 anchors 30/60/120×)
- **dd ×1.10-1.20** (more lift — wild_pure cadence improves significantly)
- **cherry ×1.00** (preserve — no bimodal shape)
- **td ×1.005** (preserve trigger margin)

Expected outcome: base RTP +6-9pp lift (target 104-108pp), total RTP 510-514pp (need user-band relax OR accept verify [480, 520] ceiling — both available within verify hard RED).

If total RTP exceeds D's self-imposed [491.5, 508.5] band, **escalate to user**: "shipped v9 m5 was 508.89pp, philosophy direction wants base +6-10pp lift = total ~514pp. Either (a) lower user-target band to allow 514, or (b) accept smaller base lift and weaker high-mult share than shipped v9."

### Mitigation B — Pre-fix LUCKY-MONO integer-rounding flip risk

Independent of (A) — D should pre-bump cherry_R1 or td_R3 by enough to give LUCKY-MONO ≥0.1pp margin (not ≥0.05pp). My sweep shows current +0.06pp margin flips at scales 500-1000.

### Mitigation C — Document archetype shift

If user is OK with departing from shipped v9 m5 archetype (≥30 share 49% → 40%, base RTP 108 → 99, bar3 17% → 8%), **D should flag this explicitly to user in §15 summary**: "M5_HMV+ proposes a DIFFERENT m5 archetype than shipped v9 — lower base RTP, lower high-mult share, lower bar3 emphasis. If user prefers v9 m5 shape, see Alternative path Mitigation A."

Without this flag, the user reading the design doc would not realize they're being shown a structurally weaker m5 than what they already approved.

### Mitigation D — Run PWDF re-derivation

New marginals require new mechanism B blank redistribute. Run `slot_designer/machines/M15/scripts/redistribute_blanks.py` or equivalent on new weights, verify PWDF-FLOOR section passes for m5 (doublediamond ≥17, high7 ≥25, topdollar ≥10).

---

## § 8 Critical concerns summary table

| concern | M5_HMV+ | hardline? | severity | notes |
|---|---|---|---|---|
| Total RTP in band | 508.21 (verify [480,520] ✓) | YES (verify) | OK | safe |
| LUCKY-MONO hit margin | +0.06pp analytic (flips at int scale 500/1000) | YES (verify) | **HIGH** | mitigation B |
| LUCKY-MONO trig margin | +0.0165pp analytic (flips at int scale 500/1000) | YES (verify) | **HIGH** | mitigation B |
| ≥30 share vs M2_LC | 40.12% (+3.95pp) | NO (D-target) | OK | met self-target |
| ≥30 share vs shipped v9 m5 | 40.12% (−9.44pp) | NO | **CRITICAL** | regression |
| Base RTP lift vs philosophy | +0.77pp (vs +6-10pp memory) | NO (philosophy) | **MEDIUM** | mitigation A |
| bar_mixed family share | 27.73% (vs v9 21%) | NO | **MEDIUM** | mitigation A |
| Bar §1 hierarchy | strict +0.030pp margin | NO (m5 INFO in verify.py) | low | tight but PASS |
| bar1 alive | 7.77% share (alive) | NO | OK | no cosmetic |
| Wild_pure cadence m5/m2 ≥ 1.1 | 1.158 | YES (verify) | OK | safe |
| Jackpot per-reel | 0.4/0.4/0.3% | YES (verify) | OK | safe |
| PWDF re-derivation | not done | YES (verify if breaks) | low | mitigation D |
| Cross-mode coherence (shipped v9 m5 archetype) | regression on 3 metrics | NO | **MEDIUM** | mitigation C |
| Engine drift / RTP ceiling | ~510 upper bound, [480,520] safe | YES (verify) | OK | safe |

---

## § 9 Bottom line

D's M5_HMV+ candidate is **mathematically sound but archetype-mismatched**. Compared to v14c M5_LC+ (which X rejected for going wrong direction on ≥30 share), v14d is a correct-direction improvement. Compared to shipped v9 m5 (the prior user-approved archetype), v14d is a structural regression.

**The user should be shown both candidates side-by-side**: M5_HMV+ (D's current) AND a "Mitigation A" candidate that approaches shipped v9 m5 (≥30 share ~48%, base RTP ~105pp, bar3 share ~14%, bar_mixed share ~23%). The user can then explicitly choose archetype direction.

D's current proposal is **plausibly correct if user is OK with a weaker-base-lift m5 than v9**, but D didn't surface this choice to user.

**Verdict**: **FIX-FIRST** with Mitigation A (or explicit user-flag per Mitigation C).

---

## § 10 Path summary

- This file: `session_artifacts/M15/critique_v14d_mode5.md`
- D's design doc: `session_artifacts/M15/design_v14d_mode5.md`
- D's design script: `session_artifacts/M15/scripts/m15_v14d_design_mode5.py`
- D's candidate JSON: `session_artifacts/M15/scripts/m15_v14d_mode5_candidate.json`
- My metrics scripts:
  - `session_artifacts/M15/scripts/m15_v14d_critique_metrics.py` (reconstruct + bucket decomp + integer rounding)
  - `session_artifacts/M15/scripts/m15_v14d_critique_metrics2.py` (shipped v9 m5 baseline)
  - `session_artifacts/M15/scripts/m15_v14d_critique_metrics3.py` (current shipped m2 confirmation)
- Prior critique (v14c modes 2/5): `session_artifacts/M15/critique_v14c_modes_25.md`
- User hardlines: `slot_designer/machines/M15/USER_HARDLINES.md` (v8)
- Production verify: `slot_designer/machines/M15/verify.py`
- Production weights (shipped, reference): `slot_designer/machines/M15/weights/mode_{1,2,5,7}/weights.json`
- Philosophy: `slot_designer/DESIGN_PHILOSOPHY.md` §1 / §9 / §10 / §15
- Memory: `~/.claude/projects/.../memory/project_slot_designer.md §C`

**No production files modified.** No new hardlines proposed. No user-hardline relaxations proposed.

---

## § 11 Top 3 critical concerns (executive)

1. **M5_HMV+ ≥30× share (payid) 40.12% is 9.44pp BELOW shipped v9 m5's 49.56%.** D claims "target ≥40% met ✓ +3.95pp shift higher" — but comparison anchor is M2_LC (newly shipped m2), not shipped v9 m5 (the prior user-approved m5 archetype). Net effect: a structural regression vs what user already accepted, framed as a directional improvement.

2. **Base RTP lift +0.77pp over M2_LC** vs shipped v9 m5's +9.35pp over its m2, vs memory direction +6-10pp. "Super-lucky" feel relies entirely on locked feature_params; base game in m5 is essentially indistinguishable from base game in m2 except for ≥30 share that contributes ~0.5% of total m5 RTP (cosmic noise vs feature variance).

3. **bar_mixed family share 27.73%** — D moved from M2_LC 31.17% to 27.73% (improvement) but shipped v9 m5 was 21.01%. The "uniform bar lift within reel" mechanism that creates bar_mixed dominance is unchanged from v14c; D adjusted scalars instead of restructuring the mechanism. Same v14c X-flagged single-family-dominance concern, half-fixed.
