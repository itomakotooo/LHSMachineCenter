# M15 v14b modes 7 / 2 / 5 — adversarial critique (Critic X)

> **Subject**: D's design `session_artifacts/M15/design_v14b_modes_725.md` (M7_F110 / M2_Q_h7_max_uneven_dd / M5_H_from_M2_Q) derived from mode 1 v14 C38_C14 shipped baseline.
>
> **Critic stance**: adversarial. Verify GREEN is the floor, not the ceiling. The user has rejected six successive candidates this session (v9 → v10 → v11 → v12 → v13 → v13b → v13c → v14 culled by user). Mode 1 only shipped after the user explicitly relaxed every numerical bucket band and forced D to re-anchor on "reel 体验合理 + RTP 构成合理" qualitative directions. The same scrutiny applies here.
>
> **Production files NOT modified.** No new hardlines proposed. No user-hardline relaxations proposed. All judgment uses DESIGN_PHILOSOPHY + memory + USER_HARDLINES.md v8 as direction.

---

## § 0 Tooling sanity

D's design script was re-derived from mode 1 v14 C38_C14 marginals; numbers in `feasibility_v14b.txt` (lines 196 / 268) match the design doc tables. I independently confirmed:

- mode 1 v14 dd marginals R1/R2/R3 = 2.90 / 2.80 / 2.40 → wild_pure P = 1.95e-5 → 1/51,314 ✓
- M2_Q dd 5.5 / 5.0 / 1.0 → wild_pure P = 2.75e-5 → 1/36,364 ✓; ratio m2/m1 = 1.41 (cap 1.5) ✓
- M5_H dd 5.94 / 5.40 / 1.08 → wild_pure P = 3.46e-5 → 1/28,867 ✓; ratio m5/m2 = 1.26 (floor 1.1) ✓

Verify.py invariants encoded by D's verify script (`m15_v14b_verify_modes_725.py`) MATCH production `slot_designer/machines/M15/verify.py` invariants (RTP bands, hit bands, LUCKY-MONO, MODE7-*, TOP-JACKPOT-ESC, JACKPOT-VIS, 1000+).

The "LUCKY-MONO bar2 peak (b2>b1 ∧ b2>b3)" rule D applied as a PASS criterion is **D's interpretation of memory §I** and is *not* a RED in production `slot_designer/machines/M15/verify.py`. There HIERARCHY for m2/m5 bar pairs is reported as INFO only (verify.py line 652-661, "lucky carve-out — wild-substitution boost on bar2/bar3"). This is a fault line — see § 1 Q9.

---

## § 1 Adversarial questions and answers (10)

### Q1 — Mode 2 RTP 290.29 sits 0.29 pp inside floor 290. Sim noise σ across modes — is M2_Q production-safe?

**Compute σ for total RTP, 1 M paid spins, mode 2:**

- Base RTP per spin: μ_base = 1.103, CV_base = 4.56 (D's number). σ_per_spin (base only) = 4.56 · 1.103 = 5.03 → Var ≈ 25.3 per spin → SE on 1 M paid spins = √(25.3/1 e6) ≈ 0.0050 → ±0.50 pp.
- Feature RTP per spin: trigger 0.030 × feature_EV 59.99 ≈ 1.800 mean per spin. P(R≥1000)/spin ≈ 1.4e-6 contributes ≈ 1400×1.4e-6 ≈ 0.002 pp²/spin from the 1000-card tail (negligible).
- Feature variance dominated by trigger-flip σ² ≈ p(1-p)·EV² + p·Var(R|trigger). Var(R|trigger) using feature CV ≈ 0.78 → Var(R|trigger) = (0.78×59.99)² ≈ 2191. Per-paid-spin feature var ≈ 0.030·2191 + 0.030·0.970·59.99² ≈ 65.7 + 104.6 ≈ 170.
- Total per-spin var ≈ 25.3 + 170 ≈ 195. SE on 1 M = √(195/1 e6) ≈ 0.014 → **±1.4 pp on total RTP**.

**Empirical SE ≈ 1.4 pp on 1 M spins.** M2_Q margin to floor is 0.29 pp → roughly P(realized < 290) ≈ Φ(−0.21) ≈ **42%**. Effectively a coin flip whether engine sim or production rawdata drops m2 under floor.

Verdict: **HIGH RISK**. D's own §6 Q2 self-critique flags this. The "structural floor pinning" framing is correct but D's recommendation ("accept or relax cap") punts to the user. From the critic seat: shipping at 290.29 is shipping on a 50/50.

This is the single highest-impact issue across all three modes.

### Q2 — Mode 2 dd marginals 5.5 / 5.0 / 1.0 — what's the actual asymmetry consequence for wild_pure cadence and visual feel?

dd R3 = 1.0% is **5× lower than dd R1 = 5.5%**, an extreme asymmetry. Math first:

- P(wild_pure) = 0.055 · 0.050 · 0.010 = 2.75e-5 → 1/36,364. Cadence stays within TOP-JACKPOT-ESC cap (1.41× m1). ✓
- P(high7_pure) on R1+R2+R3 line still relies on h7 marginal — D computed 0.215% → 1/466. ✓ feature trigger rate 3.00% (td R3 0.030) byte-equal LUCKY-MONO m2/m1.

**Visual experience question — is the R3 dd visibility tolerable?** Mode 1 v14 baseline R3 dd = 2.40%. M2_Q R3 dd = 1.00% — **less than half** the standard mode density. A player switching modes 1 → 2 will see **less double-diamond on the right reel** in lucky mode than standard mode.

Cross-reference shipped m2: shipped dd 2.87 / 4.69 / 0.96 — R3 dd is also depressed (0.96%) BUT R1 dd 2.87% is comparable to mode 1's 2.40%. The pattern is "R2 spikes, R3 dips" — *not* "R1 spikes, R3 dips". D's M2_Q has R1 spike at 5.5% which is **double** mode 1's R1 dd. That is not the shipped pattern.

Verdict: **CONCERN**. R3 dd at 1.0% is below the m1 baseline (philosophy §15 brand visibility "frequency 在 lucky/super-lucky 应有可见 lift") — wild brand visibility on R3 *drops* not *lifts* going m1→m2. Combined with the unprecedented R1 dd 5.5% spike, this is a different machine identity than shipped m2.

### Q3 — Is the dd 5.5/5.0/1.0 uneven pattern a clever cap-evasion or goalpost-moving?

D's stated rationale (§3.1): "uneven dd marginal … keeps wild_pure cadence within the [TOP-JACKPOT-ESC] 1.5× cap (1/36k vs m1 1/51k, ratio 1.41) while letting R1/R2 dd boost wild-substitution paths on bar2/h7 lines."

This is **mathematically clever** — by pushing dd density forward (R1) and starving R3, wild substitution on bar2 (10×) and high7 (30×) lines gets the boost without driving 3-wild combinatorial above cap. But it creates two concerns:

1. **It uses dd as a multi-purpose lever** (line substitution booster AND brand symbol AND wild_pure feeder). Per memory §F machine archetype lock + §A axiom: the dd symbol is M15's brand wild. Splitting "where does the wild visibility live" across reels by a 5× factor is mode-specific reshaping of brand identity.

2. **It tunes the marginal layout to game a metric** (TOP-JACKPOT-ESC cap). Per `feedback_adversarial_self_review.md`: "relaxing verify cap to make metric pass" is moving goalposts. D is not relaxing the cap, but D is reshaping marginals specifically to fit the cap — a structural neighbor.

Verdict: **AMBIGUOUS**. Acceptable IF user confirms that lucky mode brand wild visibility should live on R1/R2 (not on R3). Otherwise this is "metric pass at the cost of brand coherence".

### Q4 — Mode 7 R1 blank 42.35% — exceeds mode 1's [30, 40] band. Is this OK for cut mode?

USER_HARDLINES.md v8 line 29: R1 blank ∈ [30, 40] is **mode-1 specific**. Mode 7 / 2 / 5 have no R1 blank hardline.

Mode 7 R1 blank 42.35% is **2.35 pp above mode 1's 40% upper edge**. Per philosophy §4 cut mode small_pay_cut, blank lift is the cut mechanism — algebraically required. K-scaling F=1.10 lifts blank uniformly by 10% relative.

Per philosophy §12 R1 winners-friendly direction: R1 ≤ R(last) blank. M7_F110: R1 42.35% < R3 64.87% ✓. Direction preserved.

Per philosophy §C cross-mode hit ladder: mode 7 (13.06%) < mode 1 (16.22%) ✓.

**Visual continuity question**: a player switching m1 → m7 sees R1 go from "62% non-blank" to "58% non-blank". A 4 pp shift. Not jarring. Cherry / bar1 visible-stop density on R1 drops ~8%. Acceptable per cut narrative.

Verdict: **OK**. Mode 7 R1 blank 42.35% is structurally derived (K-scale F=1.10) and visually continuous.

### Q5 — Mode 7 hit 13.06% — paylines-aware band evaluation

M15 is 1-line classic. Per memory §D 1-line classic hit band 12-20% mode-1 baseline; cut mode "略降" ≈ −3 pp. So mode 7 hit band ≈ 9-17%.

M7_F110 hit 13.06% is well inside. Per verify.py MODE_HIT_BAND[7] = (0.10, 0.16). PASS.

Cross-check the cut-mode mechanic: small-pay P ratios m7/m1 should be ~0.7-0.9 (modest cut, not collapse). D's table 5.4:
- pay9 cherry1: 0.889 ✓
- pay71 cherry2: 0.773 ✓
- pay8 bar_mixed: 0.677 — borderline aggressive cut
- pay7 bar1: 0.706
- pay5 bar2: 0.714
- pay3 bar3: 0.744

bar_mixed cut to 0.677× is the deepest. Philosophy §4 says small-pay cut is the design goal, but 32% cut on bar_mixed is at the lower end of "modest". Player experience: bar wins ~30% less frequent in cut mode. Acceptable cut narrative.

Verdict: **OK**. M7_F110 hit 13.06% is in band; cut shape is structurally clean per §4.

### Q6 — Mode 2 hit 33.58% vs user band [30, 35]. What's the hit_session decomposition?

D's table 5.1: M2_Q hit_session 36.58% = base_hit 33.58% + trigger 3.00%. Trigger is counted in hit_session per USER_HARDLINES.md "Feature trigger 算 hit_rate" rule.

But the verify.py HIT band uses `profile["hit_rate"]` which is **base hit only** (excludes trigger). So MODE_HIT_BAND[2] = (0.30, 0.35) is base-hit. M2_Q base 33.58% PASS.

Mode 2 hit decomposition by family (from D's table 5.4 pay_hits):
- cherry1: 19.65% (58% of base hit)
- bar_mixed: 9.52% (28%)
- cherry2: 1.61% (5%)
- bar2: 1.56% (5%)
- high7_wild: 0.22% (0.7%)
- high7_pure: 0.21% (0.6%)
- bar1: 0.48% (1.4%)
- bar3: 0.27% (0.8%)
- cherry3: 0.04% (0.13%)
- wild_pure: 0.003% (0.008%)

cherry1 share-of-base-hit 58.5% — well under HIT_DECOMP_CAP_CHERRY1 80%. PASS.

Verdict: **OK on hit math.** No single-pay dominance violation.

### Q7 — Mode 2 R1 blank 16.10% vs shipped m2 R1 blank 33.45% — is this the same machine?

I computed shipped m2 marginals directly from `weights/mode_2/weights.json` × `reel_strips.json`:

| reel | shipped m2 blank | M2_Q proposed blank | delta |
|---|---:|---:|---:|
| R1 | 33.45% | **16.10%** | −17.35 pp |
| R2 | 32.28% | 27.60% | −4.68 pp |
| R3 | 24.30% | 40.70% | **+16.40 pp** |

This is **a complete reel-asymmetry inversion**. Shipped m2 has R1 ≈ R2 > R3 (R3 is busiest reel because td/dd are concentrated there). M2_Q has R1 < R2 < R3 monotonic (R3 sparsest).

This is **not** "mirror the shipped m2 pattern" as D claims (§3.1). Per philosophy §12: "R1 ≤ R3 blank" is *universal direction* for standard modes; lucky modes have a documented carve-out (philosophy §12.3 lucky widened tolerance). The carve-out lets m2/m5 reverse the direction — **shipped m2 does**. D's M2_Q goes the *other* way (R1 winners-friendly), which is the *standard mode direction*.

This means M2_Q reverses the shipped m2's lucky-mode signature. A player on m2 will see R3 spinning sparsely (40.7% blank) and R1 crowded (16.1% non-blank → 84% non-blank). On shipped m2 they see R3 dense and R1 medium. Different machine feel.

Verify.py's REEL-ASYMMETRY for m2/m5 reports as **INFO** (line 1146), so it doesn't RED. But verify INFO ≠ design intent silent. The shipped m2 pattern (R1 ≥ R3 blank, R3 = trigger reel busy) is the M15 lucky archetype that the user has approved.

Verdict: **HARD CONCERN**. M2_Q is functionally a *different lucky archetype* than shipped m2 (and shipped m2 has been validated through 4-mode pipeline). The user did not authorize an archetype change — the brief was "based on mode 1 + global design philosophy framework, complete modes 7/2/5". A different lucky-mode reel-asymmetry is *beyond* "complete based on mode 1".

### Q8 — Mode 5 base lift only +5.84 pp over m2 base. Per user_brief v1.1 §d "modest lift" — is the m5 narrative ("super-lucky 顶奖更密") delivered?

D's table 5.1:
- m2 base 110.31 pp + feature 179.98 pp = 290.29 pp total
- m5 base 116.15 pp + feature 381.10 pp = 497.24 pp total

Base lift 5.84 pp (5.3% relative). Feature lift 201 pp (112% relative). Per memory §C: "mode 5 base RTP **完全不动** from mode 2 base" → M5 = M2 base byte-equal + feature override. D **partially** follows this — M5_H lifts dd R1/R2 by 8% and td by 3% and cherry by 3% (m5_from_m2 default lifts).

User_brief v1.1 §d allows modest base lift over m2 base — D's 5.84 pp lift IS modest (per memory range "+5-10 pp"). Per-pay m5/m2 ratios all 1.01-1.06× (D's table 5.4) — base feel byte-similar.

Where the m5 "super-lucky" feel lives:
- wild_pure cadence: m5 1/28,867 vs m2 1/36,364 (1.26× more frequent) ✓
- Feature EV/cond: m5 123× vs m2 60× (~2× richer per trigger) ✓
- P(R≥200/spin): m5 3.6e-3 vs m2 2.6e-4 (14× more) ✓

Verdict: **OK on narrative delivery.** Player feels m5 vs m2 difference via feature richness + slightly tighter wild_pure cadence. Base is appropriately byte-similar per philosophy §C.

But sub-concern: dd R3 0.96% (shipped) → 1.08% (M5_H). Same R3-suppression pattern propagates. Same brand-visibility issue from Q2.

### Q9 — "LUCKY-MONO bar2 peak (b2>b1 ∧ b2>b3)" — agent-authored or user-stated?

**Critical:** Searched USER_HARDLINES.md v8 and memory `project_slot_designer.md` and DESIGN_PHILOSOPHY.md. Result:

- USER_HARDLINES.md v8: NO bar2 peak rule. The only universal cross-mode rule is "Feature shape locked", "Feature trigger 算 hit_rate", paytable lock, jackpot ≤ 0.6%.
- Memory `project_slot_designer.md`: no §I. There IS a §1 inverse pyramid bar1>bar2>bar3 universal rule (line 11-23 of DESIGN_PHILOSOPHY.md).
- DESIGN_PHILOSOPHY.md: §1 says "lower-payout symbol must P ≥ higher-payout symbol". For bar family: P(bar1) ≥ P(bar2) ≥ P(bar3). This is the *opposite* of "bar2 peak".

**The "LUCKY-MONO bar2 peak" invariant exists ONLY in:**
- `slot_designer/machines/M15/verify.py` — but as **INFO not RED** (line 652-661, `_info` not `Check(ok=...)`)
- D's design script `m15_v14b_design_modes_725.py` — applied as a PASS criterion in the sweep filter (lines 855-861)
- D's design doc — claimed as a hardline (table 3.5 "PASS" status)

D's design **enforces bar2-peak as a hardline that doesn't exist in user-stated or universal philosophy or production verify-RED**. This is agent-authored invariant promotion (verify INFO → design RED).

The shipped m2 satisfies bar2-peak (P_bar1 0.37 < P_bar2 1.06 ∧ P_bar3 0.49 < P_bar2 1.06) — so this is an *empirical* property of the shipped m2. But promoting "empirically true on shipped" → "hardline for redesign" without user approval is the same anti-pattern as `feedback_adversarial_self_review.md`'s "picked threshold".

Verdict: **PROCESS VIOLATION**. D promoted an INFO observation to a hardline. The constraint matters because it directly drove the bar1 P collapse (m2 P_bar1 0.48% < m1 P_bar1 0.71%, a 32% absolute frequency cut on the most-frequent line-pay symbol in standard mode).

If this rule is *removed*, the M2_Q design constraint loosens and the bar1 share could recover toward 8-12% (vs the current 3.71%). Per philosophy §1 universal inverse pyramid: bar1 SHOULD be more frequent than bar2 — D's design directly violates §1 for m2/m5 under the cover of an INFO observation.

### Q10 — Cross-mode bar hierarchy: mode 1 P(bar1) > P(bar2) > P(bar3). Mode 2/5 invert. Visual jarring on mode switch?

mode 1 v14: bar1 0.707% / bar2 0.422% / bar3 0.103% → classic descending pyramid
M2_Q: bar1 0.479% / bar2 1.562% / bar3 0.274% → bar2 inverted to peak
M5_H: bar1 0.503% / bar2 1.614% / bar3 0.289% → same as m2

Cross-mode visual: a player on mode 1 sees bar1 line wins ~1/141 spins; on mode 2 sees bar2 line wins ~1/64 spins (peak) but bar1 only ~1/209 (RARER than mode 1). The user could plausibly perceive this as "1bar wins disappeared in lucky mode" which contradicts the lucky-mode mental model ("everything more frequent").

This is the design tradeoff D names in §6 Q3 — "bar1 SHARE drops because bar2/h7 get bigger lifts, not because bar1 hits drop dramatically". But D's own per-pay table shows bar1 P went DOWN absolutely (0.71% → 0.48%, a 32% drop). Not "share drops while frequency holds" — frequency actually drops too.

**Per memory §C mode 2 archetype "balanced all-tier lift"**: all tiers should LIFT in lucky mode. D's bar1 lift is *negative*. This violates the philosophy direction *for the bar1 family*.

Verdict: **HARD CONCERN**. Bar1 frequency collapse in lucky mode is a philosophy §C violation under the cover of "lucky carve-out". The user has explicitly rejected design candidates this session for less than this (cf. session log: bar1 share 44%, h7 share 31.5% both rejected — user's bar against single-family extremes is well-established).

### Q11 — Family share comparison across modes — single-family dominance check

Combined share-of-base by mode (D table 5.5):

| family | m1 | m7 | m2 (M2_Q) | m5 (M5_H) |
|---|---:|---:|---:|---:|
| cherry1 | 21.87 | 24.64 | 17.81 | 17.34 |
| cherry total | 25.70 | 28.37 | 25.70 | 25.29 |
| bar1 | 12.11 | 11.30 | **3.71** | **3.79** |
| bar2 | 15.37 | 14.55 | 20.69 | 20.76 |
| bar3 | 9.27 | 9.21 | 9.03 | 9.30 |
| bar_mixed | 27.94 | 24.38 | 19.83 | 19.23 |
| **bar total** | **64.69** | **59.44** | **53.26** | **53.08** |
| high7 | 8.69 | 11.02 | 20.54 | 21.03 |
| wild_pure | 0.91 | 1.16 | 0.50 | 0.60 |

No single-family dominance >25% in any proposed mode. Combined bar family is 53-65% across all modes (classic 3-reel bar-dominant chassis, consistent).

But the **bar1 share collapse 12% → 3.7%** is the worst inter-mode delta on any single family. The user rejected v13's "bar1 share 44%" and v13b's "h7 share 31.5%" both as single-family extreme dominance. M2_Q has the *inverse* extreme: bar1 *under-representation* at 3.71%. The user's pattern is sensitivity to extreme family shares — bar1 at 3.7% is structurally extreme even if it doesn't cap-fail.

Cross-mode share of high7 family: m1 8.69% → m7 11.02% (modest) → m2 20.54% → m5 21.03%. A **2.4× lift on h7 in lucky mode** is a real "lucky brand shift" — but it's compensated by bar1 collapse. The h7 lift looks reasonable; the bar1 collapse is the cost.

Verdict: **CONCERN**. Single-family dominance is OK, but bar1 *suppression* to 3.7% combined with h7 *promotion* to 20+% is a non-uniform "lucky lift" that doesn't match memory §C "balanced all-tier lift". Likely the user would call this out.

### Q12 — Engine-realized vs analytic drift — could m2 drop under 290 after integer rounding?

D's §9.7 tradeoffs note acknowledges "Engine-realized vs analytic drift expected to be ~0.1-0.5pp on total RTP per integer weight rounding". Mode 1 v14 saw 0.49 pp delta (analytic 94.752 → engine 94.262).

M2_Q analytic 290.29. After integer weight rounding, drift could go either direction. Assuming similar magnitude:
- 95% CI on engine-realized vs analytic for m2: ±0.5 pp
- Combined with 1 M sim noise SE = 1.4 pp from Q1
- Total uncertainty around engine RTP = √(0.5² + 1.4²) ≈ 1.5 pp

So engine-realized 1 M sim m2 could come in anywhere in [290.29 − 3 pp, 290.29 + 3 pp] = [287.3, 293.3] at 95% confidence. **P(engine 1 M < 290) ≈ 0.43** (still close to coin flip).

Verdict: **HIGH RISK CONFIRMED**. M2_Q has ~43% chance of failing the [CROSS-RTP m2 band] hard line in engine sim, even before considering production rawdata variance.

---

## § 2 Hard issues per mode (RED)

### Mode 7 — M7_F110
**No hard issues.** K-scaling is algebraically clean. Cross-mode invariants structurally guaranteed (top symbol marginals exact preservation → big-pay freq exact preservation). Mode-7 cut-mode philosophy §4 fully satisfied.

### Mode 2 — M2_Q
1. **RTP floor risk (Q1, Q12)**: 290.29 pp with ~43% probability of failing [CROSS-RTP m2 band] under engine sim or production rawdata. The 0.29 pp margin is below the 1.4 pp 1 M-spin SE.
2. **Reel-asymmetry inversion vs shipped m2 (Q7)**: R1 16.10 / R3 40.70 reverses shipped m2's R1 33.45 / R3 24.30 lucky archetype. Verify.py INFO doesn't RED but this is a machine-identity shift the user did not authorize.
3. **Agent-authored hardline "LUCKY-MONO bar2 peak" (Q9)**: design enforces verify INFO as a RED. Direct cause of bar1 frequency collapse violating philosophy §1 inverse pyramid universal rule for bar family. User has not signed off on this carve-out for M15.
4. **Bar1 frequency *absolute* drop in lucky mode (Q10)**: P(bar1) 0.71% → 0.48% violates memory §C "balanced all-tier lift" direction for lucky mode.

### Mode 5 — M5_H
1. **All Mode 2 issues propagate** (M5_H derived from M2_Q). Reel-asymmetry inversion, bar2-peak rule, bar1 absolute drop persist.
2. **RTP floor risk**: m5 497.24 vs band [480, 520]. Sim noise σ on m5 even larger (CV 4.56 + heavier feature). SE ≈ 2 pp on 1 M spins. Margin to floor 17 pp — comfortable. Not the m5 concern.

---

## § 3 Soft concerns (WARN)

1. **Mode 7 cherry3 cadence 1/43k**: cosmetic-rare. D's §6 Q7 self-critique notes "23 firings per 1 M spins". Acceptable per cut-mode relaxed floor.
2. **Mode 2 dd R3 1.0% — brand visibility on R3 dips below mode 1 baseline 2.40%**. Philosophy §15 lucky modes "频率有可见 lift" — dd R3 *dips* not *lifts* m1→m2. Minor visual-narrative friction.
3. **R2 dd pattern across modes**: m1 R2 dd 2.80% → M2_Q R2 dd 5.00% (1.79×) → M5_H R2 dd 5.40% (1.93×). Cross-mode dd visibility on R2 escalates fine. But R1 dd cross-mode: m1 2.90% → M2_Q 5.50% (1.90×) — R1 dd doubles in lucky mode. Player sees R1 frequent double-diamonds in lucky which is a legit "wild reel is lucky" narrative, BUT it doesn't match shipped m2 (R1 dd 2.87% in shipped). Different lucky-mode signature.
4. **PWDF re-derivation not performed in this design pass** (D §9.6). Mechanism B should re-apply post-tune if strip weights change. M7 K-scaling changes weights; M2_Q / M5_H new marginals → new mechanism-B blank redistribute needed before commit. Verify.py PWDF-FLOOR floors:
   - mode 2: dd 17 / h7 25 / td 10
   - mode 5: dd 17 / h7 25 / td 10
   - mode 7: dd 34 / h7 34 / td 24
   - Without re-running mechanism B, PWDF achievements not verified. RED on verify.py if missed.
5. **Mode 7 R3 blank 64.87%** vs mode 1 R3 blank 58.97% (+5.9 pp) — within universal §12 direction (R1 ≤ R3). No issue.

---

## § 4 Cross-mode coherence assessment

Two coherence concerns:

### 4.1 Reel-asymmetry direction inversion (lucky carve-out)

| mode | R1 blank | R3 blank | direction |
|---|---:|---:|---|
| m1 v14 shipped | 38.50 | 58.97 | R1 < R3 (standard) |
| m7 proposed | 42.35 | 64.87 | R1 < R3 (standard) |
| m2 shipped | 33.45 | 24.30 | R1 > R3 (lucky carve-out) |
| **m2 M2_Q** | **16.10** | **40.70** | **R1 < R3** (back to standard) |
| m5 shipped | 33.11 | 24.07 | R1 > R3 (lucky carve-out) |
| **m5 M5_H** | **15.39** | **40.35** | **R1 < R3** (back to standard) |

**M2_Q and M5_H *erase* the shipped lucky-mode reel-asymmetry carve-out.** Per philosophy §12.3 lucky modes have a carve-out — *to allow* R1 ≥ R3 (trigger reel busy). D's proposed modes don't use the carve-out; they go back to standard direction.

Question for user: which lucky-mode reel asymmetry is intended? Shipped pattern (R3 trigger reel = busy reel) or proposed pattern (R1 winners-friendly, R3 sparse)?

### 4.2 Bar hierarchy direction inversion

| mode | P(bar1) | P(bar2) | P(bar3) | direction |
|---|---:|---:|---:|---|
| m1 v14 shipped | 0.707 | 0.422 | 0.103 | bar1 > bar2 > bar3 (§1 standard) |
| m7 M7_F110 | 0.499 | 0.301 | 0.077 | bar1 > bar2 > bar3 (§1 standard) |
| m2 shipped | 0.372 | 1.063 | 0.489 | bar2 > bar3 > bar1 (lucky carve) |
| **m2 M2_Q** | 0.479 | 1.562 | 0.274 | **bar2 > bar1 > bar3** (different lucky carve) |
| m5 shipped | 0.405 | 1.124 | 0.535 | bar2 > bar3 > bar1 (lucky carve) |
| **m5 M5_H** | 0.503 | 1.614 | 0.289 | **bar2 > bar1 > bar3** (different) |

D's lucky carve-out shape is **bar2 > bar1 > bar3**. Shipped lucky shape is **bar2 > bar3 > bar1**. Both violate §1, but they're different patterns. Visual:
- Shipped: bar1 is RARE, bar3 is the second-most-common line-bar
- Proposed: bar3 is RARE, bar1 keeps second-most-common position

Player sees on shipped lucky m2: lots of bar2 + bar3 line wins, fewer bar1. Player sees on proposed M2_Q: lots of bar2 + bar1 line wins, fewer bar3. Different feels.

**Neither matches §1 universal direction**, but both are within verify INFO carve-out. The question is which carve-out *the user intended* — D doesn't have user sign-off on either.

---

## § 5 Tradeoffs (explicit)

| tradeoff | M2_Q / M5_H position | alternative |
|---|---|---|
| RTP centered in band ↔ TOP-JACKPOT-ESC cap | RTP at floor edge (290.29) because cap pinned | Relax cap to 1.6× — user authorization required |
| bar2 peak (D rule) ↔ §1 inverse pyramid | bar2 peak honored, §1 violated for m2/m5 | Drop bar2-peak constraint, restore bar1 > bar2 — likely makes RTP unreachable |
| R3 dd 1.0% to keep wild_pure cadence ↔ §15 brand visibility | dd R3 < m1 R3 (brand visibility regression) | Lift R3 dd → wild_pure cadence exceeds 1.5× cap (Q3) |
| Independent archetype lift ↔ shipped lucky carve continuity | M2_Q is different shape from shipped m2 | Keep shipped m2 marginals + re-anchor only to v14 m1 numeric outputs — D rejected this in §6 Q8 but the alternative deserves a fresh look |
| F=1.10 mode 7 ↔ F=1.12 alternative | 85.72 centered | F=1.12 at 84.10 — also acceptable |

---

## § 6 Verdict per mode

### Mode 7 — M7_F110: **SHIP**

K-scaling is algebraically clean. No process violations. All invariants structurally guaranteed. RTP 85.72 centered in [83, 87]. Cut-mode philosophy §4 + memory §D fully satisfied. Mode 7 design is *clean*.

One caveat: verify.py PWDF-FLOOR check needs re-run after K-scaling produces new weights. If mechanism B-redistributed weights are preserved (D didn't re-derive), PWDF likely still passes (top-symbol marginals byte-equal m1 means top-adj-blank weighting carries through). But D should explicitly verify post-K-scale before commit.

### Mode 2 — M2_Q: **FIX-FIRST**

Three blocking issues:
1. **RTP floor 0.29 pp margin** with 1.4 pp SE → ~43% probability of failing under engine/production sim (Q1, Q12).
2. **Reel-asymmetry direction reversal vs shipped m2** without user authorization (Q7).
3. **Agent-promoted "LUCKY-MONO bar2 peak" hardline driving bar1 frequency collapse** violating §1 universal inverse pyramid (Q9, Q10).

Specific fixes to consider before committing:
- (a) Drop the bar2-peak hardline → allow bar1 P to recover toward §1 direction. Re-search for an RTP-feasible candidate with bar1 ≥ bar2 OR loose bar2-peak. Likely opens 5-10 candidates that previously failed only on bar2-peak.
- (b) Use shipped m2's reel-asymmetry direction (R1 ≥ R3 blank) — restore the lucky carve-out the user has implicitly approved by shipping.
- (c) Push for ~3 pp RTP margin (target 293-295) by lifting h7 marginal modestly + restoring bar1 — likely structurally feasible if (a) and (b) honored.

If fixes (a)+(b)+(c) cannot collectively reach RTP ≥ 293, the next step is *user sign-off* on either (i) lucky-mode reel-asymmetry reversal, (ii) bar2-peak hardline promotion, or (iii) TOP-JACKPOT-ESC cap relaxation — *not* ship-as-is.

### Mode 5 — M5_H: **FIX-FIRST**

Inherits all M2_Q issues by construction. RTP 497.24 has 17 pp margin — not the m5 concern. The m5 design follows m2 once m2 is fixed.

Suggested approach: settle M2_Q first, then re-derive M5_H with `dd_lift_pct=8, td_lift_pct=3, cherry_lift_pct=3` against the new m2 baseline.

---

## § 7 Specific recommendations

1. **Mode 7 ship M7_F110** after verifying PWDF-FLOOR holds post-K-scale (or running mechanism B redistribute if not).
2. **Mode 2 — three actions**:
   - (a) **Critically reconsider whether "bar2 peak" should be a hardline**. The verify.py only reports it as INFO. D promoted it. Test whether removing this constraint opens a *better* candidate (higher RTP margin, less extreme bar1 collapse, closer to shipped m2 archetype). Likely opens ≥3 candidates in the existing sweep that previously failed only on bar2-peak.
   - (b) **Verify whether shipped m2 reel-asymmetry pattern (R1 ≥ R3 blank, R3 = trigger reel busy)** is the M15 lucky-mode signature the user expects. If yes, M2_Q's R1 16% / R3 40% is wrong direction. Re-design with R1 ≥ R3.
   - (c) If both (a) and (b) make 290+ infeasible, escalate to user *before* committing. Options: relax TOP-JACKPOT-ESC cap to 1.6× (user_brief v1.1 §c relaxation request), or accept lower lucky-mode RTP target (user-stated band relaxation), or accept a different lucky archetype (user sign-off on new reel-asymmetry direction).
   - **Do NOT ship M2_Q at 290.29 as-is.** The 43% probability of engine/production sim falling below floor is unacceptable risk.
3. **Mode 5 — derive from fixed mode 2** with `m5_from_m2` template (current `dd_lift_pct=8, td_lift_pct=3, cherry_lift_pct=3` is fine).
4. **Stop the agent-authored hardlines pattern.** "LUCKY-MONO bar2 peak" enforcement is exactly the `feedback_adversarial_self_review.md` "structural" pattern — verify INFO promoted to design RED without user OK. The user has been *the* gatekeeper this session on what is and isn't a hardline (cf. v3 of USER_HARDLINES.md "Removed mode 2/5/7 hardlines — not user-stated, agent-derived"). D needs to remove all verify INFO → design RED promotions from the candidate sweep before re-running.
5. **Document the engine-realized vs analytic delta** before commit. D's design numbers are all analytic. Run actual engine sim on M7_F110 / M2_Q / M5_H per verify.py to confirm the per-mode totals don't drift below band. M2_Q is the immediate risk; M7/M5 should be fine but should be checked.

---

## § 8 Top 3 critical concerns (executive)

1. **Mode 2 RTP at floor edge (0.29 pp margin) with sim SE ~1.4 pp** — ~43% probability of engine/production sim failing CROSS-RTP m2 band hardline. This single issue is sufficient to block commit.
2. **Agent-promoted "LUCKY-MONO bar2 peak" hardline drives bar1 absolute frequency drop** (m1 0.71% → m2 0.48%) — violates §1 universal inverse pyramid AND memory §C "balanced all-tier lift" without user authorization.
3. **Mode 2/5 reel-asymmetry direction reversed vs shipped m2** (R1 << R3 blank in proposed vs R1 ≥ R3 in shipped) — changes the lucky-mode signature without user sign-off, despite user reviewing/approving the shipped pattern previously.

---

## § 9 Path summary

- This file: `session_artifacts/M15/critique_v14b_modes_725.md`
- D's design: `session_artifacts/M15/design_v14b_modes_725.md`
- D's design script: `session_artifacts/M15/scripts/m15_v14b_design_modes_725.py`
- D's verify script: `session_artifacts/M15/scripts/m15_v14b_verify_modes_725.py`
- D's sweep log: `session_artifacts/M15/feasibility_v14b.txt`
- User hardlines: `slot_designer/machines/M15/USER_HARDLINES.md` (v8)
- Production verify: `slot_designer/machines/M15/verify.py`
- M15 archetype + mode design: `slot_designer/machines/M15/{DESIGN,MODE_DESIGN}.md`
- Memory: `~/.claude/projects/.../memory/project_slot_designer.md` (universal §A-Z)
- Philosophy: `slot_designer/DESIGN_PHILOSOPHY.md` §1-15

**No production files modified.** No new hardlines proposed. No user-hardline relaxations proposed.
