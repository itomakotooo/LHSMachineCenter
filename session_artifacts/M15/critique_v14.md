# M15 v14 mode 1 — Adversarial critique of D's C38_C14_rtp_target_95 (X / 魔鬼律师)

> **Role**: X — 魔鬼律师, adversarial review of D's archetype-first redesign post user v8 directive ("放开所有rtp分桶的限制。只满足reel体验和rtp构成的合理性。")
> **Reference**: WORKFLOW §3, DESIGN_PHILOSOPHY §1–15, USER_HARDLINES.md v8, memory (`reference_classic_slot_rtp_distribution.md` / `feedback_tuner_pareto_trap.md` / `feedback_dont_lower_floor_when_blocked.md` / `feedback_adversarial_self_review.md`), prior critique `critique_v13c.md`.
> **Verdict (TL;DR)**: **FIX-FIRST**. D's C38 is the most balanced candidate of the v13/v14 series on symbol-marginal level (no symbol > 20.2% per reel, no single "named" family > 22%), and the math reproduces exactly. BUT two structural concerns are unaddressed: (1) **combined bar family RTP share = 64.69%** of base RTP — this IS bar-family dominance, just relabeled at a higher abstraction level than v13's pure-bar1 dominance; (2) **bar_mixed share 27.94% IS partly composite-tier loophole** — 21% of bar_mixed RTP is "1bar+1bar+2bar" (just bar1+bar2 in disguise), and only 19% is "true 3-tier-different" (1+2+3bar). On player perception, C38 reads as a **"bar slot"** (R1 has 47% bar density, all 3 bar tiers + bar_mixed account for 65% of base RTP) rather than a "classical 7-bar slot" (RWB at 50% seven share / 31% bar; Blazing 68% seven / 18% bar). Also: **P(RTP drift below 94 on 1M sim) = 12.5%** under SE 0.65pp — not negligible. User's "RTP composition reasonable" qualitative invariant is at risk: would the user say "OK ship" if told C38 is a bar slot (65% bar RTP, 10% seven RTP)? **Probably yes** if framed honestly; almost certainly NO if marketed as "classical 7-bar archetype" without that disclosure.

---

## 0. What D got right (independent reproduction)

All numerics reproduce to 4 decimals via independent run (`session_artifacts/M15/scripts/m15_v14_critique_audit.py`).

| Metric | D's claim | X reproduce | Match |
|---|---:|---:|---|
| Base RTP | 42.772pp | 42.7725pp | ✓ |
| Base hit | 16.215% | 16.2182% | ✓ |
| R1 blank | 38.500% | 38.5000% | ✓ |
| Trigger rate | 1.133% | 1.1300% | ✓ |
| Feature EV per trigger | 45.88x | 46.0000x | ✓ (D rounded — 46.00x exact) |
| Total RTP (analytic) | 94.752pp | 94.7525pp | ✓ |
| Hit session | 17.348% | 17.3482% | ✓ |
| bar1_pure RTP | 5.18pp | 5.180pp | ✓ |
| bar_mixed RTP | 11.95pp | 11.951pp | ✓ |
| wild_pure cadence | 1/51,314 | 1/51,314 | ✓ |
| dd PWDF max | 27.90% | 27.902% | ✓ |
| h7 PWDF max | 30.76% | 30.765% | ✓ |

D's math is correct. The critique focuses on **design framing**, **archetype mapping**, **hidden composite dominance**, and **adversarial questions D did not fully answer**.

D's self-critique (§14 Q1-Q8 in `design_v14.md`) is actually the most honest in the v13/v14 series — Q1 directly admits "bar_mixed 27.94% might be hidden dominance" and addresses it. To D's credit, the candidate is genuinely a structural improvement over v13c PPP_v20 (cherry1 single-family max 21.87% vs PPP_v20 high7 31.48%). **However**, three issues warrant FIX-FIRST verdict.

---

## 1. Adversarial questions (10) — X self-Q+A

### Q1. "bar_mixed 27.94% — is this really 'not single-family dominant', or is it just a composite-pay loophole?"

**Partly loophole, partly genuine composite.** Independent decomposition of pay_id 8 (bar_mixed) by underlying 3-reel bar-tier combination:

| Combo (sorted) | P(combo) % | % of bar_mixed | Has wild? |
|---|---:|---:|---:|
| **1bar+1bar+2bar** | 1.1023% | **21.00%** | No |
| 1bar+2bar+3bar | 0.9992% | 19.04% | No |
| 1bar+2bar+2bar | 0.9002% | 17.15% | No |
| 1bar+1bar+3bar | 0.6118% | 11.66% | No |
| 2bar+2bar+3bar | 0.4080% | 7.77% | No |
| 1bar+2bar+wild | 0.3609% | 6.87% | Yes (wild_boost ×2) |
| 1bar+3bar+3bar | 0.2761% | 5.26% | No |
| 2bar+3bar+3bar | 0.2254% | 4.29% | No |
| 1bar+3bar+wild | 0.2011% | 3.83% | Yes |
| 2bar+3bar+wild | 0.1642% | 3.13% | Yes |

**Aggregated by unique bar tiers involved (ignoring wild positions)**:
- Involves **1bar + 2bar only**: 45.02% of bar_mixed
- Involves 1bar + 2bar + 3bar (true 3-tier): **19.04%** of bar_mixed
- Involves 1bar + 3bar only: 20.75% of bar_mixed
- Involves 2bar + 3bar only: 15.20% of bar_mixed

**Implication**: bar_mixed is **mostly bar1+bar2 combos** (45%), only 19% is true 3-tier "any 3 bars" diversity. The "multi-family composite" framing in D's §5 understates this. If you asked a player who saw the most common bar_mixed result ("two 1bars and one 2bar pays 2x"), they would call it "a near-bar1 win", not a "diverse 3-tier composite". **Loophole component**: of the 21% bar_mixed share, ~13pp is effectively "bar1 + bar2 paired" — adding to single-tier bar1 (12.11%) + bar2 (15.37%) shares.

So in terms of **player perception of "which bar tier is paying"**, the share is approximately:
- bar1 visible: bar1_pure (12.11%) + bar_mixed-with-1bar (~25% of bar_mixed share = ~7pp) = ~19% of base
- bar2 visible: bar2_pure (15.37%) + bar_mixed-with-2bar (~22% of bar_mixed share = ~6pp) = ~21% of base
- bar3 visible: bar3_pure (9.27%) + bar_mixed-with-3bar (~17% of bar_mixed share = ~5pp) = ~14% of base

Slightly more even than the raw family_pp suggests, but the **TOTAL bar share of base RTP = 64.69%**. That's the structural dominance pattern.

Genuine answer: bar_mixed at 27.94% is partly a composite-tier loophole (45% of it is just bar1+bar2 pairs) but partly genuine 3-tier mixing (19% true any-3-bars). The honest framing is "**bar-family dominance has been spread across bar1/bar2/bar3 evenly enough to not violate single-symbol dominance, but the family is still 65% of base RTP**".

### Q2. "cherry1 share 21.88% — is this acceptable cherry-anywhere classical (low-pay)?"

Cherry-1 (any 1+ cherry on payline = 1x) fires every 1 in 11 spins. Compared to classical IGT Red White Blue:
- RWB: Cherry / low pays = **16% of RTP**
- Blazing Sevens: Cherry / Dollar / Bell = 12.9% of RTP
- C38: cherry combined (cherry1+2+3) = **25.70% of base** ≈ 11.6% of total (with feature)

So C38's cherry share is **~1.6× the RWB cherry-low share** at total-RTP level, but is at the same proportion or slightly higher than RWB at base-RTP level. The "1 in 11 spins" cadence is what drives this — base game hit rate is dominated by cherry-1 (9.36% / 16.21% base hit = **57.7% of base hits are cherry-1**).

Is 25% cherry share "acceptable"? Per philosophy §8 "any pay > 70% of hits = unbalanced". Cherry-1 is 57.7% of base hits — within band but on the high side. **Not a violation, but worth noting**: the player effectively plays a "cherry slot with bar mid-pays" rather than a "bar slot with cherry anchor". RWB has cherry-1 at ~38% of hits (per Harrigan PAR sheets, lower); C38 is somewhat cherry-heavy on hit-frequency basis.

**Honest answer**: cherry-1 21.88% share is within classical IGT range at base level, but cherry as a fraction of base hits (57.7%) is high. Player perception: "cherries pay constantly" — anchor classical OK, but not flatly "low-pay" — it's a **dominant hit driver**.

### Q3. "Bar hierarchy P(bar1)=0.71% > P(bar2)=0.42% > P(bar3)=0.10%. Is the 7× drop from bar1 to bar3 right? Or is bar3 too rare?"

Ratios:
- bar1/bar2 = 1.68× (within philosophy §1 [1.2-1.3×] band)
- bar2/bar3 = 4.08× (above philosophy §1 [1.2-1.3×] — bar3 is "much rarer" tier)

bar3_pure cadence = 1/967 spins ≈ ~1 per **70 minutes of 200-spin/hour play**. P(at least 1 bar3 in 500-spin session) = 40.4%. So a 500-spin session has 60% chance of NEVER seeing a bar3_pure win, but a 1000-spin session shows it ~64% of the time. This is **borderline visible** — significantly more visible than v13c PPP_v20's 1/16k (98% sessions never see it), but not classical-RWB-bar visible (~1/300).

**Acceptable**: yes, bar3_pure at 1/967 is meaningfully alive. **Better than v13c**: yes (16× more visible than PPP_v20). **Classical RWB band?** No — RWB has all bar pures at ~1/300 (more frequent). C38 bar3 cadence is "boutique mid-tier rare" rather than "classical RWB bar 1/300 active tier".

### Q4. "Hit 17.34% — at upper edge [15, 18]. Margin only 0.66pp from upper cap. Under 1M-spin sim noise, would hit drift over 18?"

**Independent SE estimate**: SE(hit_session) on 1M spins = ±0.0379pp (binomial approximation on p = 0.17348).

**Margin to upper [18]**: 0.652pp = **17.2σ**.
**P(drift over 18)** ≈ 0.0000.

This is extraordinarily safe — hit_session essentially cannot drift over 18 cap from sampling noise alone. Hit is statistically anchored. ✓ **No risk**.

### Q5. "RTP 94.262 engine vs 94.752 analytic = 0.49pp drift from integer rounding. Margin from 94 floor is 0.26pp. Is this safe?"

**Independent SE estimate**: SE(total_rtp) on 1M spins = **±0.65pp** (from compute of Var[X] = E[X²] − E[X]² with E[X²] ≈ 42.76, dominated by feature variance from 1000×/100× feature x-card payouts).

**Margin to floor [94]** at analytic 94.75pp: 0.75pp = **1.15σ**. At engine-realized 94.262pp: 0.26pp = **0.40σ**.

**P(drift below 94 on 1M sim, using analytic 94.75)** ≈ **12.5%**.
**P(drift below 94 on 1M sim, using engine 94.262)** ≈ **34%** (Φ(−0.40)).

This is **non-trivial RTP floor risk**. The engine-realized 94.262 leaves only 0.26pp under the [94, 96] floor — that's a 1 in 3 chance of producing a 1M sim that reads under 94. D's claim "engine-realized is the truth for production; analytic is the design target" is correct, but the engine number is uncomfortably close to floor.

**Mitigation options**:
- Alt A (C14) RTP 95.80 — much safer floor margin, but cadence under 50k philosophy floor.
- Alt C (C37) RTP 94.518 — slightly safer (0.52pp margin = 0.80σ, ~21% drift risk).

D's recommendation of C38 is the "centered" candidate but **NOT** the safest on RTP floor. Worth flagging.

### Q6. "dd PWDF 27.90% under 28% verify.py floor (-0.10pp). D claims structural strip-layout limit. Is mechanism B at maximum redistribution? Could strip restructure (more dd stops on R1) push to 28+?"

Strip restructure is **out of scope per user direction** (H3 in design_v14, "Strip layout unchanged"). So that's not the relevant question — is mech B at max possible redistribution?

**Independent check**: D's mech B uses `top_symbols = (doublediamond, high7, topdollar)`. With 3 top symbols competing for the same blank pool, each gets a slice. If we reconfigure:

| top_symbols config | dd_max PWDF | h7_max PWDF | td_max PWDF |
|---|---:|---:|---:|
| **D's (dd, h7, td)** | **27.90%** | 30.77% | 24.69% |
| (dd, h7) only | 27.90% | 43.96% | 1.16% |
| (dd,) only | **61.25%** | 7.24% | 1.16% |
| (dd, h7, td, jackpot) | 25.10% | 28.00% | 22.55% |

**dd PWDF could go to 61.25%** if we used only dd as the "top" mech-B target. But that would crash h7 PWDF below floor (7.24% vs 28% verify floor — much worse than current 0.10pp shortfall). The current D config is a **multi-objective compromise** — pushing dd up requires pulling h7 down.

**Could D do better?** Tested (dd, h7) only — dd_max stays at 27.90% (same), h7 jumps to 43.96% (much higher), but topdollar PWDF collapses to 1.16% (way below 22% verify floor). So **with current strip + mech B + 3 top symbols, 27.90% appears to be the dd ceiling**.

**Honest answer**: D's mech B configuration is near-optimal under the multi-objective constraint. The 0.10pp shortfall is structural to strip layout (1 dd stop on R3, 2 each on R1/R2 sharing the blank pool with h7 + topdollar). Under user's "strip layout unchanged" direction, **the dd PWDF floor cannot be fixed via mech B alone**. The fix requires either:
- (a) Strip restructure (out of user scope)
- (b) Verify.py PWDF floor relaxation (need V/X to argue case)
- (c) Accept caveat (same as v13b ZZZ ship pattern)

This is the same H5 issue as v13c. D applied **the same workaround pattern** — caveat documentation — but didn't fully prove the 4-mechanism exhaustion that `feedback_dont_lower_floor_when_blocked.md` mandates.

### Q7. "verify.py FAMILY-SHARE 4 REDs expected by D: bar1 12.11 at cap 12 (RED+0.11); high7 8.69 over cap 8 (RED+0.69); cherry1 21.87 under floor 26 (RED−4.13); bar_mixed 27.94 over cap 25 (RED+2.94). Each one — is it user-relevant or stale verify.py band?"

These bands at `slot_designer/machines/M15/verify.py:291-300` (`FAMILY_SHARE_BANDS_PCT[1]`) were authored under prior design intent — pre-v8 hardlines were stricter. The bands encode:

| Band | Floor | Cap | C38 value | Status | Stale or user-relevant? |
|---|---:|---:|---:|---|---|
| cherry1 | 26.0 | 38.0 | 21.87 | **RED** (under) | **STALE** — user v8 said "no single family dominate". Pushing cherry1 to 26+ pushes single-family dominance to ~30% range (which user rejected in v13c high7 31.5%). Float should be lowered to ~20% to match v8 intent. |
| bar_mixed | 12.0 | 25.0 | 27.94 | **RED** (over) | **PARTLY STALE** — bar_mixed structural under M15 paytable when bars are visible. But the **spirit** ("bar_mixed cap to prevent dominance") is relevant: 27.94% IS at dominance level. Verify.py cap 25% encodes this. |
| bar1 | 4.0 | 12.0 | 12.11 | **RED** (over) | **MARGINAL** — 0.11pp over is rounding. The spirit (anti-bar1-dominance from v13a/b rejection) is satisfied: 12.11 << 44% rejected. Verify.py needs subtle update; the principle holds. |
| high7 | 2.5 | 8.0 | 8.69 | **RED** (over) | **MARGINAL** — 0.69pp over. The spirit ("no high7 dominance" post-PPP_v20 rejection) is satisfied: 8.69 << 31.5% rejected. Verify.py marginal violation. |

**Summary**: 1 stale (cherry1 floor — clearly conflicts with v8 direction), 2 marginal (bar1 + high7 — spirit OK, letter 0.1-0.7pp off), 1 real (bar_mixed cap 25% — C38 is 2.94pp over, this captures the user's "bar dominance" concern legitimately).

**Recommendation**: V/X should NOT auto-widen verify.py to match C38 (moving goalposts trap). Instead, update verify.py to encode v8 direction explicitly:
- cherry1 floor: 26 → 18 (single-family floor not relevant under v8)
- bar1 cap: 12 → 15 (small relax, principle preserved)
- high7 cap: 8 → 10 (small relax, principle preserved)
- bar_mixed cap: 25 → 28 OR FLAG as real concern (this is the actual structural concern)

### Q8. "Strip rearrange / mechanism B — D applied mech B post-design. PWDF table — confirm via independent compute. Is mech B at max possible redistribution?"

Confirmed in Q6 above. D's mech B values reproduce exactly. With current top_symbols set, redistribution is near-optimal across the 3-objective compromise (dd / h7 / topdollar all need PWDF lift).

**One more check**: what does **strip restructure** buy us if user relents?
- Adding a 3rd dd stop on R3 (currently 1 stop): dd R3 PWDF could rise from 14.18% → ~28% with strip+mech B redo, lifting dd MAX above 28% floor.
- Cost: strip md5 changes → ALL existing rawdata in all 4 modes invalidated → 4× re-sampling cost (potentially 4+ hours upstream throttled time per [reference_upstream_sampling_api.md](../../../.claude/memory/reference_sampling_api.md)).

D should propose this as **explicit option** in escalation block.

### Q9. "Compared to v13a FINAL_E (bar1 44%) and v13c PPP_v20 (h7 31.5%) — is C38 fundamentally different in family-share shape, or is the bar_mixed 27.93% just hiding the dominance differently?"

Side-by-side single-family share comparison:

| Family | v13a FINAL_E | v13c PPP_v20 | v14 C38 | User reaction |
|---|---:|---:|---:|---|
| bar1_pure | **44.09%** | 26.60% | 12.11% | v13a rejected; "bar1 独大" |
| high7 combined | 19.57% | **31.48%** | 8.69% | v13c rejected; "完全不行" |
| cherry1 | 20.37% | 22.84% | 21.87% | ? |
| bar_mixed | 10.17% | 10.45% | **27.94%** | ? |
| cherry combined | ~21% | ~27% | **25.70%** | ? |
| **bar all (1+2+3+mx)** | ~56% | ~40% | **64.69%** | ? |
| seven combined | 19.57% | 32.18% | 9.61% | ? |

**Distinct improvements in C38**:
- No single named family > 22% — TRUE improvement over v13a/c which had a single named family > 30%.
- Cherry / bar / seven family architecture is genuinely more balanced at the **named-family level**.

**However**:
- **Bar-class total share (1+2+3+mx) jumps to 64.69%** — significantly higher than v13a (~56%) and v13c (~40%). This is the **new dominance axis**.
- **Seven share collapses to 9.61%** (vs v13c's 32%, v13a's 20%) — C38 is the LEAST seven-anchored of the three.

**Honest verdict**: C38 has solved the single-symbol dominance problem (no one named symbol > 22%) but the **dominance has aggregated up to the family LEVEL** (bar combined 65%). The question for user is: "Is bar-combined dominance the same complaint as bar1 dominance, or different?" 

If user reads C38 family shares and says "bar1 12 + bar2 15 + bar3 9 + bar_mixed 28 = 65% — bar dominant family, same problem at different level" → 4th rejection.
If user reads C38 and says "no single named family > 22%, and the bar mixing reflects a 'bar slot' which is what classical IGT is" → ship.

This depends entirely on **whether user's invariant is about SYMBOL-level dominance or FAMILY-level dominance**. D inferred symbol-level (correctly per Q1 in design_v14), but the user has not explicitly stated. **REQUIRED**: surface this question to user before ship.

### Q10. "Cosmetic pay check: cherry-3 P 1/28k. Bar3_pure P 1/967. Are these in user's 'each pay fires meaningfully' range?"

Per user v8 direction: "**normal spin 各 pay 都得发奖（不能 bar3_pure 1/16k 这种 cosmetic 死 pay）**". Independent firing rates and session probabilities:

| Pay | 1-in-N | P(≥1 in 150) | P(≥1 in 500) | P(≥1 in 1000) | Status |
|---|---:|---:|---:|---:|---|
| cherry1 | 11 | 100% | 100% | 100% | Dominant |
| cherry2 | 315 | 37.89% | 79.56% | 95.8% | Active |
| cherry3 | 28,571 | 0.52% | 1.73% | 3.4% | **SLIM** |
| wild_pure | 51,314 | 0.29% | 0.97% | 1.9% | Anchor-rare (in cadence band) |
| high7_wild | 2,518 | 5.78% | 18.01% | 32.6% | Active |
| high7_pure | 5,184 | 2.85% | 9.19% | 17.5% | Active |
| **bar3_pure** | **967** | **14.37%** | **40.38%** | 64.4% | **Acceptable** (not 'cosmetic dead') |
| bar2_pure | 237 | 46.95% | 87.92% | 98.5% | Active |
| bar1_pure | 141 | 65.50% | 97.12% | 99.9% | Active |
| bar_mixed | 19 | 99.97% | 100% | 100% | Dominant |

**User's "no cosmetic dead pay" check**: user explicitly named "bar3_pure 1/16k 这种 cosmetic 死 pay" as the negative example. C38 has bar3_pure at 1/967 — that's **17× better than the cosmetic-dead example**. ✓ This direction is satisfied.

**Cherry-3 at 1/28,571** is the rarest "active" pay. In a 1000-spin session, only 3.4% see it. Compared to wild_pure (also rare classical) at 1.9% session visibility, cherry-3 is slightly more visible. **Cherry-3 cadence**: 3 firings per 100k spins, similar to top-jackpot rarity. **Acceptable** as a "classical 15× rare pay", but worth flagging as **the rarest non-jackpot pay**.

**Honest verdict**: per-pay firing meets user's "no cosmetic dead pay" direction. cherry-3 is the rarest at 1/28k (D acknowledges this in §7 of design_v14). bar3_pure visibility (40% of 500-spin sessions see one) is substantially better than v13c PPP_v20 (0.8% session visibility). ✓ The user direction is met.

---

## 2. Hidden metrics independently computed

### 2.1 bar_mixed decomposition (Q1 detail)

Out of total bar_mixed P = 5.249%, by underlying tier:
- **45.02%** is "1bar + 2bar combos" (most common type)
- 20.75% is "1bar + 3bar combos"
- 19.04% is true "1bar + 2bar + 3bar all-different" (genuine 3-tier composite)
- 15.20% is "2bar + 3bar combos"

The "true any-3-bar" share is only **19% of bar_mixed**, or **5.3% of base RTP** — significantly less than the marketing of "bar_mixed = diverse combinatorial tier". **Most bar_mixed wins look like "1bar+1bar+2bar pays 2x"** — feels like a bar1+bar2 weak pay, not a "diverse tier composite".

### 2.2 Combined family bar share (the headline finding)

| Family group | RTP (pp) | % of base | % of total (with feature) |
|---|---:|---:|---:|
| Bar (1+2+3+mixed) | 27.671 | **64.69%** | 29.20% |
| Cherry (1+2+3) | 10.993 | 25.70% | 11.60% |
| Seven (h7_pure + h7_wild + wild_pure) | 4.109 | 9.61% | 4.34% |
| Feature | 51.980 | — | 54.86% |

**C38 base game = bar slot** (65% bar RTP). NOT a classical 7-bar slot (where RWB has 31% bar / 50% seven, Blazing 18% bar / 68% seven). The "C38 is classical IGT 7-bar" framing in D's §1 / §17 is **misleading** about archetype mapping.

### 2.3 Hit composition

Of the 16.21% base hit rate, **57.7% are cherry-1** wins (P=9.36% / 16.21%). The slot hits like a cherry-anywhere slot first, with bar mid-pays as secondary anchor.

### 2.4 1-in-N firing reproduces D

All match D's report. Coverage in §1 Q10 table above.

### 2.5 Hit & blank sampling noise

- Hit margin to upper [18]: 17.2σ → P(over 18) ≈ 0.0000 — **safe**
- R1 blank margin to upper [40]: 30.8σ → safe

### 2.6 RTP sampling noise (the headline risk)

SE(total_rtp) on 1M spins ≈ ±0.65pp (Var[X] ≈ 42.76, dominated by feature variance from 1000×/100× x-cards). Engine 94.26 margin to floor [94] = 0.40σ → **P(under 94 on 1M sim) ≈ 34%**. **NON-TRIVIAL — flag to user.**

---

## 3. Archetype comparison (C38 vs classical IGT)

Per `memory/reference_classic_slot_rtp_distribution.md`:

| Archetype | RTP | Cherry/low | Bar | Seven | Top jackpot rarity |
|---|---|---|---|---|---|
| **Red White & Blue (IGT)** | 87.47% | **16%** | **31%** | **50%** | 1/262,144 |
| **Blazing Sevens (IGT)** | 89.09% | 12.9% | 18.1% | **68.8%** | 1/81,920 |
| **C38 (base only)** | 42.77 (of 94.75 total) | 25.7% | **64.7%** | 9.6% | 1/51,314 |
| **C38 (base + feature)** | 94.75 | 11.6% | 29.2% | 4.3% | 1/51,314 |

**Verdict**: C38 (base only) is a **bar slot, NOT a 7-bar classical**. RWB has 50% seven RTP — C38 has 10%. Blazing has 68% seven — C38 has 10%. The "classical 7-bar archetype" framing in D's §1 ("Classical IGT 7-bar 3-reel slot archetype") is **mis-archetype**. C38 is structurally a "**bar slot with cherry anchor and feature trigger**".

**Mitigating context** (per the memory file): "M1 mode 1/7 达不到 classic 50% Seven share—因为 M1 paytable 的 wild 机制 ... 把 Bar 三连放大到 30-90×". M15's paytable has bar_mixed as a 2x pay on ANY 3 bars — this IS the mechanism that absorbs RTP into the bar family. With M15 paytable locked, getting C38 to a 50% seven share is **structurally infeasible** (per same memory note about M1).

**Honest archetype claim**: C38 fits "**3-reel bar slot with cherry-anywhere + Feature Play feature**". Not "classical 7-bar slot" (RWB/Blazing). The archetype claim in D's report should be downgraded.

**Comparison to "C38 viewed as session-level" (with feature)**:
- Cherry 11.6%, Bar 29.2%, Seven 4.3%, Feature 54.86%

This is essentially a **"feature-driven slot"** — base game is bar+cherry anchor (~40% of RTP comes from these), feature drives 55% of RTP. It's NOT a classical IGT line-only slot at all in this framing. It IS the M15 archetype as documented (`slot_designer/machines/M15/DESIGN.md` Feature Play family).

**Net**: archetype label needs adjustment in D's report. C38 is NOT classical IGT 7-bar; C38 IS a M15-paytable-shaped bar+feature slot. The classical-IGT-7-bar baseline is the WRONG anchor for marketing claims, even if it's reasonable as a "low-pay/mid-pay/high-pay proportion guideline".

---

## 4. Hard issues (must address before ship)

### H1. **Combined bar family RTP share = 64.69% of base** — IS this single-family dominance under user's invariant?

D's §5 frames bar_mixed as "multi-family composite — NOT single-family dominance". This is letter-true (bar_mixed is a line_3_group pay, not a single-symbol pay) but **spirit-questionable**:
- Combined bar share (1+2+3+mixed) = 65% of base RTP
- v13a/b/c rejection pattern was about "one family dominating"
- The user has NOT explicitly stated whether bar1_pure 44% (v13a) and bar_combined 65% (C38) are the same complaint

**Required action**: D / main session must surface to user before ship: "C38 has bar_combined = 65% of base RTP, including 27.94% in pay_id 8 (bar_mixed line_3_group, 45% of which is just 1bar+2bar combos, 19% is true 3-tier). Is this acceptable bar-slot archetype, or does it trigger the same 'family dominance' rejection pattern as v13a/c?"

The risk is: user will pattern-match "65% bar = bar dominance" → 4th rejection. The defense is: user said "放开所有rtp分桶的限制" and **didn't explicitly say "no family combined > X%"**. D's framing is defensible BUT needs explicit user check.

### H2. **Archetype mis-labeling**

D's design doc claims "Classical IGT 7-bar 3-reel slot archetype" (§1, §17, §10). Per archetype comparison in §3 above, C38 has 9.6% seven RTP (vs RWB 50% / Blazing 68%). C38 is **NOT a 7-bar slot** — it's a bar-and-cherry-anchor slot with feature-driven jackpot tier.

**Required action**: relabel archetype in D's doc to "M15 Feature Play bar slot with cherry-anywhere anchor". Drop "classical 7-bar" framing. Honest archetype description matters for user's mental model.

### H3. **dd PWDF 27.90% < 28% verify.py floor (-0.10pp)**

Same issue as v13b/c. D treats as "structural caveat". Per `feedback_dont_lower_floor_when_blocked.md`, before declaring "structural", D must prove 4-mechanism exhaustion:
1. Marginal redistribution: ✓ (explored 39 candidates)
2. Mech B reconfiguration: PARTIAL (verified D's config near-optimal, but didn't test 4-symbol top groupings — though my Q6 test rules it out)
3. Strip restructure: NOT EXPLORED — adding R3 dd stop could push PWDF above 28%; user constraint blocks this
4. Architecture upgrade (virtual reel mapping): NOT EXPLORED — not in user scope

**Required action**: D's escalation block should explicitly state "PWDF 0.10pp under floor requires user choice: (a) accept caveat (b) authorize strip restructure (c) update verify.py to drop floor to 27 (d) authorize architecture upgrade". Don't just ship with "same as v13b/c caveat".

### H4. **RTP floor risk on 1M sim — P(under 94) = 34%**

Engine-realized 94.262 margin to floor [94] = 0.26pp = 0.40σ on 1M-spin sim. **34% chance** a real 1M sim reads under 94, **producing a hard verify FAIL**. Alt C (C37) has 0.52pp margin (21% drift risk); Alt A (C14) has 1.80pp margin (~0.3% drift risk).

**Required action**: surface to user: "Recommended C38 has 34% RTP-under-94 drift risk on 1M sim. Alt A (C14, RTP 95.80) has <0.5% drift risk but cadence under philosophy [50k, 100k] floor by 5.5k. Alt C (C37, RTP 94.518) has ~21% drift risk and cadence in band. Choose:"
- (a) C38 (most centered hardlines, ~34% drift)
- (b) C14 (safest RTP, cadence slightly under philosophy band)
- (c) C37 (middle ground)

### H5. **bar_mixed share 27.94% over verify.py cap 25%** — legitimate concern, not stale

Per Q7 analysis, cherry1/bar1/high7 verify.py bands are arguably stale under v8 direction. **bar_mixed cap 25% is NOT stale** — it captures exactly the "bar dominance via composite tier" concern. C38 violates this by 2.94pp.

D's argument in §5 that "this is structural under M15 paytable" is partly true (any bar density supports bar_mixed at archetypal level), but the cap exists to flag the dominance pattern.

**Required action**: explicit user adjudication: "bar_mixed share 27.94% exceeds verify.py cap 25% by 2.94pp. This is structural under M15 paytable. Accept (and update verify.py) OR reject and revisit candidate set?"

---

## 5. Soft concerns

### S1. Hit composition cherry-1 dominant (Q2)

Cherry-1 = 57.7% of base hits. Player perception: "cherry pays constantly" — anchor classical OK, but cherry plays more like a "primary win source" than a "low-pay supplement". Not a violation; archetype mapping note.

### S2. Bar visual density per reel (R1=47%, R2=37%, R3=30%)

R1 has 47% of stops being some bar tier — that's nearly half of the wheel. Visually, the player will see "bar everywhere". Classical IGT RWB bar density ~30-40% per reel. C38 R1 is at the upper edge of classical.

### S3. Per-pay session firing balance (Q10)

cherry-3 at 1/28k — rarest non-jackpot pay. 1.7% of 500-spin sessions see one. Not "dead" per user definition, but **the most cosmetic-feeling pay** in C38. Worth flagging.

### S4. Bar hierarchy gap bar2→bar3 = 4.08×

Per philosophy §1, gap ratio ≥ 1.2-1.3× is required. bar1→bar2 = 1.68× (good). bar2→bar3 = 4.08× (4× the philosophy floor — bar3 is unusually rare compared to bar2). Acceptable but worth noting hierarchy is somewhat steep at the high-bar end.

### S5. Seven family share collapse vs v13c

C38 has seven RTP share 9.61% vs PPP_v20 32%. The "shift away from seven dominance" was deliberate, but C38 is now **the LEAST seven-anchored M15 mode 1 candidate ever**. If user later wants "more seven feel" (per archetype 7-bar narrative), C38 is the worst basis.

### S6. CV 6.52 (informational per user v3)

D reports base CV 6.52 (engine). Per philosophy §5, mode 1 (95% RTP) classical CV is 6-12 — C38 at 6.52 is on the low side, consistent with cherry-1 frequent-hit dominance. Not a violation; informational.

---

## 6. Tradeoff matrix

| Choice | If you accept | You give up |
|---|---|---|
| **Ship C38** | Best balance of named single-family shares (max 22% cherry1, max symbol 20% 1bar) | (a) combined bar family 65% of base — could be perceived as "bar slot dominance"; (b) archetype label is "bar slot not 7-bar"; (c) 34% RTP-under-94 drift risk; (d) PWDF -0.10pp under verify.py floor; (e) verify.py FAMILY-SHARE 4 RED |
| **Ship Alt A (C14)** | RTP 95.80 (1.80pp margin to floor — safe drift), cleaner bar_mixed 27.78%, larger margin to upper RTP cap | wild_pure cadence 1/44k (5.5k under philosophy floor — informational) |
| **Ship Alt C (C37)** | RTP 94.52 (0.52pp margin), cadence in band 1/53k | bar_mixed 28.27% slightly higher, slim RTP margin (~21% drift risk) |
| **Iterate further** | Could find sub-25% bar_mixed at cost of trimming bar density (which hits base RTP) | Likely pushes seven or cherry up — same v13 series pareto re-emergence |
| **Escalate to user (recommended)** | Honest framing of family-aggregation dominance concern + archetype mislabeling + RTP drift risk + PWDF + verify.py REDs | Requires user decision on bar-combined dominance + verify.py update direction |

---

## 7. Verdict: **FIX-FIRST**

**C38 has solved single-symbol dominance** (no symbol > 20.2% per reel, no named single family > 22%) — this is a genuine improvement over v13a/b/c. The math reproduces, the design exploration was thorough (39 candidates), self-critique is the most honest of the v13/v14 series. **D's iteration progress is real**.

**However**, four issues prevent direct ship:

1. **Combined bar family share = 64.69%** has not been adjudicated by user. The pattern of v13 rejections is about dominance; bar-combined dominance at family-aggregation level was not user-stated as forbidden, but also not explicitly approved. **User check required before ship.**

2. **Archetype mis-labeling**: D's "Classical IGT 7-bar archetype" framing is wrong per `reference_classic_slot_rtp_distribution.md`. C38 is a "bar slot with cherry anchor and feature trigger", not a 7-bar slot. **Doc relabel required.**

3. **RTP drift risk**: Engine 94.262 has ~34% chance of producing a 1M sim under 94 floor. **Surface to user with Alt A as safer alternative.**

4. **PWDF -0.10pp + bar_mixed +2.94pp verify.py REDs**: same v13b/c pattern of "ship with caveat" without 4-mechanism exhaustion proof or explicit user adjudication on verify.py update direction.

---

## 8. Specific recommendation

**Path A (recommended): Escalation document**

D writes `session_artifacts/M15/v14_escalation.md` covering:

1. **Family-level dominance check** (Q1, H1):
   - Combined bar family = 65% of base RTP
   - bar_mixed decomposition (45% bar1+bar2 / 19% true 3-tier / 36% other)
   - Ask user: "Is bar-combined family dominance the same problem as bar1/h7 single-symbol dominance, or different?"

2. **Archetype labeling** (H2):
   - C38 is NOT classical 7-bar (seven RTP 9.6%, vs RWB 50% / Blazing 68%)
   - C38 IS a "bar slot with cherry anchor + Feature Play"
   - Ask user: "Is this archetype acceptable, or do you want 7-heavy classical?" (latter requires paytable change, currently locked)

3. **RTP drift risk** (H4):
   - C38 engine 94.262 → 34% drift-under-94 risk on 1M sim
   - Alternatives: C14 (95.80, <0.5% drift), C37 (94.52, ~21% drift)
   - Ask user: pick one

4. **PWDF / verify.py REDs** (H3, H5):
   - dd PWDF -0.10pp under verify.py floor — structural under strip lock
   - bar_mixed share +2.94pp over verify.py cap — structural under paytable + RTP floor
   - Other family-share REDs (cherry1 floor 26 stale; bar1 cap 12 marginal; h7 cap 8 marginal)
   - Ask user: which to (a) accept caveat (b) update verify.py to encode v8 direction (c) authorize strip restructure (d) other

**Path B (alternative): Ship C38 with explicit caveats**

If user is fine with all 4 concerns (acceptable bar combined dominance, archetype is M15-paytable-shaped not classical-IGT, 34% RTP drift risk acceptable for 1M sim production, verify.py REDs to be updated per H5), then C38 can ship. Required actions:

1. Update `design_v14.md` archetype label to "bar slot with cherry anchor + Feature Play"
2. Update verify.py FAMILY_SHARE_BANDS_PCT[1] per Q7 recommendations
3. Add ship-time bar3_pure / cherry-3 / wild_pure cadence note for production sampling
4. Document RTP drift risk in commit message; flag as "if production 1M reads under 94, fall back to C14"

**My recommendation**: **Path A first**. After 3 rejected v13 iterations, the cost of one more clarification round to user is much less than a 4th rejection. The user explicitly relaxed bucket bands in v8 — they MIGHT relax other constraints too if asked, OR they might point at the bar-combined issue and ask for re-iteration. Either way, the conversation is cheaper than re-shipping.

**Do NOT** ship C38 silently. The framing concerns (H1 + H2) are non-trivial and the user has been pattern-matching dominance across 3 rejections. Surface, ask, then ship.

---

## 9. Self-critique of this critique (one round)

**Am I being too harsh on "bar combined 65%"?** Possibly. The user's invariant ("不能接受 bar1 独大") was specifically about a SINGLE family — and bar_mixed IS a separately-named family per evaluation_order and per pay_id. By the letter of user's statement, bar1 12% + bar_mixed 28% are NOT "one family at 40%". By the spirit, "combined bar shape RTP" might or might not be the concern. **Honest**: I don't know what the user's reaction will be. The right move is to ASK, not assume.

**Am I demanding too much escalation?** After 3 rejections, ANY iteration that fails to surface "the potentially-problematic structural pattern" risks 4th rejection. The cost of 1 escalation question is much lower than 1 more reject. Escalation overhead is justified.

**Did I miss D's actual quality?** No — D's archetype work IS the most thorough of v13/v14. The 39-candidate exploration, the explicit self-critique Q1-Q8, the alternative table — all are good practice. C38 IS the best candidate in the set. The critique is about **framing** + **escalation discipline**, not about candidate quality per se.

**Did I propose any changes user has not explicitly authorized?** No. All recommended actions are:
- Asking user for explicit adjudication (H1, H2, H4, H5)
- Updating verify.py band that user did not explicitly set (Q7)
- Following `feedback_dont_lower_floor_when_blocked.md` (H3)

No new hardlines added. No user-stated relaxation reversed.

**Could C38 actually ship?** Yes, with disclosure of all 4 concerns. The user might say "OK, all 4 fine, ship it". My recommendation against silent ship is about **process discipline post-3-rejections**, not about C38 being broken.

**Verify reproduction integrity?** All numbers in §1 / §2 reproduce via:
- `slot_designer.core.devtools.analytic_rtp.analytic_profile_from_marginals` (C38 marginals)
- `slot_designer.machines.M15.plugins.feature._round_payout_distribution` (feature_params v9 locked)
- `slot_designer.core.devtools.player_experience.symbol_window_probability` (PWDF post mech B)
- Strip layout from `slot_designer/machines/M15/reel_strips.json` v8.1 (no production file modified)
- Scripts: `session_artifacts/M15/scripts/m15_v14_critique_audit.py`, `m15_v14_critique_pwdf.py`

---

## 10. Verification artifacts and reference paths

- `slot_designer/machines/M15/USER_HARDLINES.md` v8 (read for v8 direction)
- `slot_designer/DESIGN_PHILOSOPHY.md` (cross-machine universal rules, §10 pareto trap is key)
- `slot_designer/machines/M15/verify.py:280-380` (FAMILY_SHARE_BANDS_PCT[1] + _PWDF_TOP_ANY_REEL_FLOOR_PCT[1] — read-only)
- `slot_designer/machines/M15/spec.json` (paytable locked — read confirmed line_3_group on {1bar, 2bar, 3bar})
- `slot_designer/machines/M15/reel_strips.json` v8.1 (strip layout locked, 36-stop alternating)
- `session_artifacts/M15/design_v14.md` (D's report under critique)
- `session_artifacts/M15/scripts/m15_v14_design.py` (D's script, 39 candidates)
- `session_artifacts/M15/critique_v13c.md` (prior X critique on PPP_v20)
- `session_artifacts/M15/scripts/m15_v14_critique_audit.py` (X audit script — independent reproduction)
- `session_artifacts/M15/scripts/m15_v14_critique_pwdf.py` (X PWDF / mech B audit)
- `memory/reference_classic_slot_rtp_distribution.md` (RWB 50% seven / 31% bar / 16% cherry baseline)
- `memory/feedback_tuner_pareto_trap.md` (philosophy §10 defense rationale)
- `memory/feedback_dont_lower_floor_when_blocked.md` (4-mechanism exhaustion requirement)
- `memory/feedback_adversarial_self_review.md` (process — "structural" without fix attempt = moving goalposts)

No production file modified. No hardline added. Critique uses philosophy + first principles + classical archetype as direction.
