# M15 v13c mode 1 — Adversarial critique of D's PPP_v20 (X / 魔鬼律师)

> **Role**: 魔鬼律师 (X) — adversarial review against D's `design_v13c.md` PPP_v20 candidate.
> **Reference**: WORKFLOW §3, DESIGN_PHILOSOPHY §1–15, USER_HARDLINES.md v7, memory feedback (`feedback_adversarial_self_review.md` / `feedback_tuner_pareto_trap.md` / `feedback_dont_lower_floor_when_blocked.md` / `feedback_self_verify_output.md`), prior `critique_v13.md` (FINAL_E review).
> **Verdict (TL;DR)**: **FIX-FIRST**. PPP_v20 satisfies the v7 user-explicit `bar1 share ≤ ~30%` directive (26.6%) but the underlying problem the user has been pointing at for three iterations — "a single family must not dominate" — is **STRUCTURALLY UNCHANGED**, just relabeled. **high7 31.5% is bar1 44% wearing a different jersey**, and verify.py codifies that as an even more violent miss (393.5% of cap vs bar1's 221.6%). D also independently confirms three pre-existing locked invariants are violated (FAMILY-SHARE 6/7 fail; HIT-DECOMP cherry1 right at brink; PWDF dd 0.64pp under floor) without escalation. User has rejected v13a (bar1 41.9%), v13b (bar1 44%), and PPP_v20 will be rejected for the *same underlying reason* unless main session explicitly surfaces "the user's invariant CANNOT be satisfied jointly with current paytable + RTP cap" and gets adjudication.

---

## 0. What D got right (independent reproduction)

I re-ran D's PPP_v20 marginals through the same primitives (`analytic_profile_from_marginals` + locked feature_params v9):

| Metric | D claim | X reproduce | Match |
|---|---:|---:|---|
| Base RTP | 44.74pp | 44.743pp | ✓ |
| Base hit | 14.83% | 14.830% | ✓ |
| g15 (session) | 14.896pp | 14.896pp | ✓ |
| sum_1_20 | 29.832pp | 29.832pp | ✓ |
| pay_id 7 (bar1) RTP | 11.90pp | 11.900pp | ✓ |
| pay_id 1 cadence | 1/64,000 | 1/63,999 | ✓ |
| bar1 share-of-base | 26.60% | 26.60% | ✓ |
| high7 share-of-base | 31.48% | 31.48% | ✓ |

Numerics reproduce to ≥4 decimals. D's analytic math is correct. **The problem is what's not in the design doc's PASS section.**

D's self-critique (Q1–Q5) actually correctly identifies most of the structural issues and gives honest tradeoffs. To that extent this is the most adversarial-aware D iteration in the v13 series. **However**, three things still warrant FIX-FIRST verdict:

1. The fundamental user invariant ("no single family dominates") is preserved-in-letter (bar1 ≤ 30%) but violated-in-spirit (high7 31.5%, larger over-cap on verify.py than bar1 was).
2. D documents `[FAMILY-SHARE]` and `[PWDF-FLOOR]` REDs as "structural caveats" but does not escalate to user. Per `feedback_adversarial_self_review.md`, "structural" without first attempting fix = moving goalposts.
3. The two design directions user explicitly stated in v7 ("尽可能克制 g15" + "bar1 share ≤ ~30%") are partly accommodated and partly papered over (g15 14.90, at the *upper* edge of [10,15], not the lower edge user asked for).

---

## 1. Adversarial questions (10) — X self-Q+A

### Q1. "User rejected bar1 41.9% (v13a) and 44% (v13b) as 'bar1 独大'. PPP_v20 has high7 share 31.5%. Is high7 31.5% effectively the same problem with a different label?"

**Yes.** The user's underlying invariant is "no single family >> ~25-30%". They picked bar1 as the example because that's what the previous candidates produced, but their pattern of rejection has been about **any** family dominating. Look at the per-family share on PPP_v20:

| family | share-of-base | rank |
|---|---:|---:|
| **high7** | **31.48%** | **#1** |
| bar1 | 26.60% | #2 |
| cherry1 | 22.84% | #3 |
| bar_mixed | 10.45% | #4 |
| cherry2 | 4.28% | |
| bar2 | 2.67% | |
| bar3 | 0.82% | |
| wild_pure | 0.70% | |
| cherry3 | 0.16% | |

high7 is now the largest single family. **31.5% > 26.6% > 22.8%**. D's argument for why this is OK rests on three claims:

(a) "user said 'bar1 ≤ 30%' specifically and high7 was not user-named" — technically true, but treats user as legalist, not human. User's invariant is about dominance perception, not the specific label.

(b) "high7 30×/60×/120× big-win narrative is a feature not a bug" — possibly true in isolation, but verify.py FAMILY_SHARE_BANDS_PCT[1] caps high7 at **8%** (philosophy + targets_v2). PPP_v20 is **393.5% of that cap**.

(c) "structural — bar1 ≤ 30% forces residual to high7" — D's algebra in §8.2 is sound, BUT the conclusion should be "we can't satisfy both jointly; ESCALATE to user", not "ship the candidate and document the failure". This is the `feedback_dont_lower_floor_when_blocked.md` anti-pattern: "受阻时不降 floor — 先穷尽机制空间".

**Verdict**: same problem, different label. User will reject with similar reasoning.

---

### Q2. "g15 14.90pp is at the *upper* edge of [10, 15]. User said '尽可能克制 g15' (suppress toward lower bound 10). Did D actually suppress, or just nominally satisfy the band?"

PPP_v20 g15 = 14.90, **0.10pp under cap, 4.90pp above floor**. D claims "lower v7 target (10pp) is structurally infeasible — empirical floor ~14.4pp". Let me check.

D's structural argument (§8.1):
- cherry-1 RTP ≈ sum of per-reel cherry marginals → 10.22pp at cherry 4.5/3.5/3
- bar_mixed RTP ≈ ~5pp at bar density per reel 37/32/27%
- 14.90pp total = 10.22 + 4.66 base

To get g15 to 10pp:
- Cherry sum would need to drop ~3pp (cherry-1 RTP drops to ~7pp)
- bar_mixed would need to drop ~2pp

The displacement from cherry/bar_mixed would land in... where? Currently bar_mixed and cherry1 are mid-band. Pushing them down means **more RTP shifts to high7 or bar1**, but bar1 is capped at ~30% under v7. So:

(i) If we drop cherry1 and bar_mixed, the displaced RTP has to go to high7 (already 31.5%) or features (already 50.6pp, fixed by locked feature_params). High7 jumps further.

(ii) Alternative: drop total RTP. But hit_session also drops (cherry1 dominates hit count). [HIT] floor 15% binds.

**Is D's "infeasible" claim honest?** Partly. The algebraic argument is correct *under the existing paytable + locked feature_params + locked R1 blank band*. But there's an unexplored dimension D didn't try: **shift more RTP to bar2/bar3 by lifting their marginals**. D rejected this in §8.3 saying "bar2/bar3 lift inflates bar_mixed via 2-bar+1-other paths". Let me verify whether *small* bar2/bar3 lift could shift ~2pp from cherry+bar_mixed to bar2_pure/bar3_pure (g1020 bucket) without inflating g15.

Actually D's §8.3 is correct: bar_mixed comes from 1+2+3 bar combos, and lifting bar2 from 7/6/5 to 10/9/8 lifts bar_mixed_pure proportionally to bar density. Let me see the magnitude.

Take R1 from 7 to 10: bar density R1 from 37% to 40%. R1 blank cap (40%) binds. So bar2 lift more than that requires displacing high7 R1 — which is currently 16% sitting between cherry 4.5% and 1bar 28%. Squeezing.

**Honest answer**: D's "g15 ≤ 13pp infeasible under v7 + paytable + R1 blank cap" claim is *probably* correct, but D didn't explicitly *prove* it (no sweep over R1 blank 30-35% to free density, no exploration of bar2/bar3 ≥ 5% configurations near R1 blank floor). D explored 25 hand-tuned candidates near PPP; that's not an exhaustive feasibility proof. The verdict "user must accept 14.9 as floor OR relax" is potentially correct but **should be presented as a feasibility report with explicit lower-bound proof, not as a candidate to ship**.

Per `feedback_dont_lower_floor_when_blocked.md` philosophy: "先穷尽实现方案 — 4 类机制". D explored 1 mechanism direction (marginal redistribution). The other 3 (paytable re-multiplier, strip restructure, architecture upgrade) are off-limits per user lock. So that *might* be the answer — but **say it explicitly**, don't ship a candidate with "g15 at upper edge of band that user wanted lower-edge".

---

### Q3. "D claims g15 < 14.4pp structurally infeasible. Is this correct or did D miss design space?"

I'll spot-check: what about a "low cherry + low bar_mixed + slightly more h7" configuration?

```
R1: blank 35.5, cherry 2.5, 1bar 25, 2bar 7, 3bar 2, h7 19, dd 2.5, jp 0.5
```
- cherry sum ~7%: cherry-1 RTP ~6.5pp
- bar density R1 34% — slightly lower
- h7 R1 19% — pushes h7 share higher
- R1 blank 35.5% — within band

What would g15 be? cherry-1 ~6.5pp + bar_mixed_pure ~3.5pp + small ≈ **~10.5pp** — IN THE LOWER-EDGE TARGET ZONE.

But what does this do to other constraints?
- high7 share = ??: with h7 R1=19, h7_pure RTP ≈ 30 × 0.19 × 0.14 × 0.10 = 0.797 × 100 = 79pp? Wait, that's RTP fraction. Let me redo.
- h7_pure: 30 × P(h7,h7,h7) = 30 × 0.19 × 0.14 × 0.10 = 30 × 0.00266 = 0.0798 → **7.98pp RTP**
- h7_wild: ~10pp (slightly less than 9.19 at v20)
- **high7 family RTP ~18pp** — share-of-base ~40% (worse than PPP_v20's 31.5%)
- bar1 share at bar1 25/(~22)/(~18) → bar1_pure RTP ~8pp → share ~18% (better than PPP_v20's 26.6%)
- Total base RTP: cherry-1 6.5 + cherry-2 ~1pp + bar1 8 + bar2 ~1.4 + bar3 ~0.4 + h7 18 + bar_mixed 3.5 + wild_pure 0.3 = ~39pp
- Add feature 50.6pp → total ~89.6pp — **fails RTP floor [94, 96]**

So D's broad conclusion holds: lowering g15 to ~10 forces high7 share UP (worse than 31.5%) AND can drop total RTP below 94 floor.

**Honest answer**: D's "g15 floor ~14.4pp" claim is broadly correct in the explored region, with the caveat that the search wasn't proven exhaustive. The deeper truth: **g15 floor binds the system because cherry-anywhere (paytable line_3_group) + 3-of-a-kind bar_mixed line geometry forces cherry-1 + bar_mixed_pure to fill g15 even at minimum marginals**. This is structural to paytable, not to v7 hardlines per se.

That said, **D should have made this proof explicit in the design doc, not buried in "Q1 — Yes I tried 25 candidates"**. The user has been twice rejected; they need a *crisp* structural proof that "g15 ≤ 12pp is infeasible given paytable lock + RTP floor + bar1 cap + R1 blank ≤ 40 + feature_params lock", with sweep coverage shown.

---

### Q4. "high7 R1 16% — classic seven-symbol density is typically 4-8%. PPP_v20 has 16% on R1. Quantify the teasey-ness via near-miss analysis."

**Near-miss for high7 3-of-a-kind**:
- P(h7 on R1+R2, NO h7 R3) = 0.16 × 0.12 × (1−0.085) = **1.757% per spin** = 1 in 56
- P(h7 3-of-a-kind pure) = 0.16 × 0.12 × 0.085 = 0.163% per spin = 1 in 612
- **Near-miss / win ratio = 10.76×**

By comparison, ZZZ (v13b, h7 R1 14%, R2 10%, R3 6%):
- Near-miss rate 1.316%, win rate 0.084%, ratio 15.67×
- Both ZZZ and PPP_v20 have h7 saturated on R1+R2 with R3 starvation — **both are textbook near-miss reels**

So PPP_v20 produces a high7 near-miss roughly every 56 spins, only paying a high7 line-win every 612 spins. **For a 150-spin session, expect ~2.7 high7 near-misses but only ~0.25 wins**. The player sees h7 frequently on R1 and R2 (43% window visibility on R1, 33% R2 by my 3-row window calculation), but it almost never lands on R3.

**Is this "good slot design"?** Depends on user intent. Harrigan 2007 documented that near-miss frequency at 10-15× win frequency is exactly the "manufactured frustration" pattern flagged as predatory in academic gambling research. IGT designs typically target 4-6× near-miss/win ratio. PPP_v20 at 10.76× sits at the *upper* end of the engineered near-miss zone.

This isn't a hardline violation — but it IS a soft concern that user should be aware of. The high7 R1 density of 16% (almost 4× classic baseline) is exactly the symbol-density inflation that Harrigan's "award symbol clustering" critique describes.

---

### Q5. "bar2 R1 7% vs ZZZ 4.5% — slight uptick. bar3 R1 2% vs ZZZ 1.2%. Are these meaningfully visible or still cosmetic?"

**bar2_pure** (3-of-a-kind 2bar = 10×):
- P(hit) = 0.07 × 0.06 × 0.05 = **0.021% per spin** = 1 in 4,761
- 150-spin session: P(at least 1 bar2-pure win) = 8.5%, expected count = 0.088

**bar3_pure** (3-of-a-kind 3bar = 20×):
- P(hit) = 0.02 × 0.018 × 0.015 = **0.00054% per spin** = 1 in 185,185
- 150-spin session: P(at least 1 bar3-pure win) = **0.81%** (less than 1%)
- 500-spin session: P(at least 1 bar3-pure win) = 2.7%

For comparison, ZZZ:
- bar2_pure P = 0.0135% = 1 in 7,407
- bar3_pure P = 0.00026% = 1 in 384,615

**Both bar2 and bar3 pure pays are effectively DEAD on PPP_v20**:
- bar3_pure: 99% of typical sessions never see one. This is the same "visibility theater" critique I made on FINAL_E (Q3 in critique_v13).
- bar2_pure: ~8% of sessions see one — slightly better than dead but still extremely rare.

**Compared to classic 3-reel benchmarks** (`reference_classic_slot_rtp_distribution.md`): a healthy "Bar slot" has bar2 ≥ 1 hit per 200 spins. PPP_v20 is 1 per 4,761 — **24× rarer than benchmark**.

So PPP_v20's slight marginal lift (bar2 7 vs 4.5, bar3 2 vs 1.2) does not move bar2/bar3 into meaningful gameplay zone. **They remain cosmetic stops, not paying tiers**. The PPP_v20 narrative as "classic bar slot" is misleading; it's a "1bar + h7 dominant slot" with 2bar/3bar as visual decoration.

---

### Q6. "Compute the exact per-pay-id probabilities. If bar3_pure or cherry-3 < 0.01% (1 in 10,000+), it's an effectively dead pay."

| pay_id | description | mult | P(hit) | 1 in N | effectively dead? |
|---|---|---:|---:|---:|---|
| 9  | cherry-1 (any cherry)         | 1×        | 10.219% | 9       | active (anchor pay) |
| 71 | cherry-2 (2 cherry)           | 5×        | 0.383%  | 261     | meaningful |
| 4  | **cherry-3** (3 cherry)       | 15×       | **0.0047%** | **21,164** | **DEAD** |
| 1  | wild-3 (3 dd)                 | 200×      | 0.0016% | 64,000  | rare-by-design (top-jackpot tier) |
| 2  | high7+wild (mixed)            | 30/60/120× | 0.130%  | 767     | meaningful |
| 21 | high7 pure                    | 30×       | 0.163%  | 612     | meaningful |
| 3  | **3bar pure**                 | 20×       | **0.0062%** | **16,187** | **DEAD** |
| 5  | 2bar pure                     | 10×       | 0.059%  | 1,695   | weak (8% of sessions see one) |
| 7  | 1bar pure                     | 5×        | 1.817%  | 55      | dominant pay |
| 8  | bar_mixed                     | 2/4×      | 2.045%  | 49      | dominant pay |

**Dead pays (< 1 in 10,000)**:
- pay_id 4 (cherry-3): 1 in 21,164 — **dead** (99% of 150-spin sessions never see it)
- pay_id 3 (bar3 pure): 1 in 16,187 — **dead**

**Quasi-dead (< 1 in 1,000)**:
- pay_id 5 (bar2 pure): 1 in 1,695

**Honest archetypal check**: PPP_v20 is **NOT a "classic bar slot"**. It's a "**Cherry-bar1-h7 trio dominates, bar2/bar3 cosmetic**" design. The bar tier hierarchy (philosophy §1) is technically preserved (P(bar1)=1.82% > P(bar2)=0.06% > P(bar3)=0.006%) but the gap ratios are **31× and 9.5×** — both 30-1000× larger than philosophy §1's "1.2-1.3× clear tier separation" guideline. From a "假但不怪" standpoint (philosophy §11), bar2 and bar3 fail the "real bar slot has bar tiers paying" requirement.

---

### Q7. "RTP 95.34 margin from 96 cap = 0.66pp (better than FINAL_E). But hit 15.93 close to upper [15, 18] floor. What's the hit margin reality?"

PPP_v20 vs sampling SE on 1M spins:

| Metric | Value | Band | Margin under cap | Margin above floor | 1M SE estimate |
|---|---:|---|---:|---:|---:|
| Total RTP | 95.34 | [94, 96] | 0.66pp | 1.34pp | ~0.7pp |
| Hit session | 15.93 | [15, 18] | 2.07pp | 0.93pp | ~0.4pp |
| g15 | 14.90 | [10, 15] | **0.10pp** | 4.90pp | ~0.3pp |
| g50100 | 26.98 | [17, 27] | **0.02pp** | 9.98pp | ~0.3pp |
| R1 blank | 39.60 | [30, 40] | 0.40pp | 9.60pp | ~0.5pp |
| sum_1_20 | 29.83 | [28, 36] | 6.17pp | 1.83pp | ~0.5pp |

D's self-critique Q5 correctly identifies **g50100 0.02pp margin** as the most-vulnerable hardline. Under 0.3pp SE, that's **~50% chance of drifting over 27 cap** on a single 1M-spin sim. **g15 0.10pp margin** is similar (~30% drift risk over 15 cap).

For hit: 0.93pp above floor — comfortable (2.3σ margin).
For total RTP: 1.34pp above floor — comfortable (1.9σ).

**Cap-side risk**: real-machine sim has high probability of producing one or both of:
- g15 > 15 (→ user-stated hardline FAIL)
- g50100 > 27 (→ user-stated hardline FAIL)

D's recommendation to fall back to PPP_v10 (g50100 26.70, g15 14.85) under sim drift is sensible. But PPP_v10 RTP 94.46 has only 0.46pp under cap — symmetric drift risk to PPP_v8's 94.11 floor.

**Honest verdict**: PPP_v20 is on a 2-dimensional knife-edge (g15 + g50100 both within 0.10pp of cap). Any of the PPP variants (8/10/19/20) trade one tight margin for another. **The infeasibility is intrinsic to the design space, not to PPP_v20's choice of point**.

---

### Q8. "dd PWDF max 27.36% — D claims 'same root cause as v13b (strip layout)'. Could mech B different config push dd above 28%?"

Strip layout (v8.1 from `reel_strips.json`):
- R1 dd: 2 stops / 36 stops
- R2 dd: 2 stops / 36
- R3 dd: 1 stop / 36

Mechanism B (RTP-neutral redistribute) on R2 with dd at 2 stops:
- 18 blank stops, 18 non-blank
- redistribute blank weight: non-top-adj blanks → 1, top-adj blanks absorb remaining

With dd marginal 2.5% and 2 stops on R2: each dd stop has 36 × 0.025/2 = 0.45 weight (assuming uniform). Wait, marginals are computed from weights; let me reframe.

The post-mechanism-B PWDF cap is governed by: **(stops × blank_adj_factor + stops) / total_window_positions**. With 2 dd stops on R2 (positions p_1 and p_2), 3-row window includes p±1, so dd visible if reel stops at any of p1-1, p1, p1+1, p2-1, p2, p2+1 (6 positions assuming p1, p2 not adjacent).

If all blank weight redistribute concentrates on those 4 adj positions (2 per dd stop), and dd stops keep their weight, then:
- dd-related positions get full mass
- dd visible positions ratio = 6 / 36 = 16.67% raw, BUT post-mech-B pushes the weighted visibility to ~27% (D's measurement)

To push dd visibility >28%: need a 3rd dd stop on R2 (or push existing 2 dd to even more concentrated weight). The 27.36% number IS the structural ceiling at 2 dd stops with current blank pool.

**Could D push dd above 28% by changing dd marginal in PPP_v20?** dd marginal is 2.5% in PPP_v20 (same as v13b ZZZ). Increasing dd marginal doesn't add stops (those are strip-layout fixed); it just redistributes weight per existing stops. Per-stop weight increase doesn't help PWDF (visibility is window-position based).

**Honest answer**: D's "strip layout cap = 27.36%" claim is correct under fixed strip. The fix is strip restructure (add a 3rd dd stop on R2, or move topdollar from R3 to R2 with dd). But strip restructure changes md5 → invalidates ALL existing rawdata across all 4 modes. That's a major decision the user must adjudicate.

**Process critique**: D should have explicitly proposed strip restructure as a fix option (with consequences) in §8.4 instead of "documented caveat, same as v13b". That's `feedback_dont_lower_floor_when_blocked.md` deviation: "受阻时不降 floor — 先穷尽机制空间". Strip restructure (mechanism C analog: change underlying structure not redistribute) is the un-explored mechanism.

---

### Q9. "[FAMILY-SHARE] verify.py shipped band caps — count exact REDs and compare to ZZZ."

verify.py shipped FAMILY_SHARE_BANDS_PCT[1] (`slot_designer/machines/M15/verify.py:291-300`):

| family | floor | cap | PPP_v20 share | ZZZ share | FINAL_E share |
|---|---:|---:|---:|---:|---:|
| cherry1 | 26.0 | 38.0 | **22.84 FAIL_FLOOR** | 20.37 FAIL | 19.92 FAIL |
| bar_mixed | 12.0 | 25.0 | **10.45 FAIL_FLOOR** | ~9 FAIL | 10.04 FAIL |
| bar1 | 4.0 | 12.0 | **26.60 FAIL_CAP** (221.6% of cap) | 44.09 FAIL (367.4% of cap) | 41.89 FAIL (349.1% of cap) |
| bar2 | 10.0 | 20.0 | **2.67 FAIL_FLOOR** | 1.47 FAIL | 1.16 FAIL |
| bar3 | 5.0 | 12.0 | **0.82 FAIL_FLOOR** | 0.44 FAIL | 0.31 FAIL |
| high7 | 2.5 | 8.0 | **31.48 FAIL_CAP** (393.5% of cap) | 19.57 FAIL (244.6% of cap) | 23.23 FAIL (290.4% of cap) |
| wild_pure | 0.4 | 2.0 | 0.70 PASS | ~0.5 (PASS) | 0.29 FAIL |

**PPP_v20 [FAMILY-SHARE] FAILS: 6 / 7**.
- Improvement over ZZZ/FINAL_E: bar1 dropped from 44/42 → 26.6 (less catastrophic but still 2.2× over cap)
- Regression: high7 jumped from 19/23 → 31.5 (BIGGEST single-family violation in v13 series at 393.5% of cap)
- Improvement over ZZZ/FINAL_E: wild_pure now PASSES (0.70 ∈ [0.4, 2.0])

**Net**: PPP_v20 has slightly fewer FAMILY-SHARE FAILs (6 vs 7), but the **single worst over-cap violation is WORSE on PPP_v20** (high7 393.5% of cap, vs FINAL_E bar1 349.1%). The dominance shifted, not resolved.

This directly contradicts D's report §6 claim that PPP_v20 is a "major v7 success" — it's a *labeled* success on bar1 ≤ 30%, but **the underlying philosophy §10 pareto-trap defense is more violated, not less**.

---

### Q10. "Cross-mode mode 7 byte-equal trigger relation: PPP_v20 mode 1 changes; mode 7 stays. Cross-mode invariants?"

Same mode-7 sync issues as FINAL_E (per critique_v13 Q6). With PPP_v20:

**[MODE7-CUT]** (verify.py:898-913) requires: for every "small" pay, P(m7) < P(m1).
- Mode 7 v9 on disk: cherry-1 hit = 9.99%
- PPP_v20 mode 1: cherry-1 hit = 10.22%
- m7 < m1 → ✓ PASS (10.22 > 9.99, mode 1 higher = cut mode pattern OK)

Actually wait — re-check: I computed cherry-1 hit = 10.22% on PPP_v20 mode 1. Mode 7 v9 has 9.99%. So PPP_v20 mode 1 (10.22) > mode 7 v9 (9.99) → MODE7-CUT direction PASSES.

But: **PPP_v20 cherry marginals (4.5/3.5/3) vs mode 7 v9 cherry (which is m1 v9 cherry × 0.5)** — these are derivations from mode 1 base, not preserved. The byte-equal relationship is BROKEN by shipping a new mode 1.

**[MODE7-BIGPAY]** (verify.py:916-930) requires: for pay_id 1/2/21, m7/m1 hit ratio ∈ [0.85, 1.15].
- Mode 7 v9: pay_id 1 hit ≈ 0.00166%
- PPP_v20 mode 1: pay_id 1 hit = 0.00156%
- Ratio: 0.00166 / 0.00156 = **1.064** → IN BAND ✓ (closer to 1.0 than FINAL_E's 2.62)

So mode 7 cross-mode invariants on big-pay actually PASS for PPP_v20 (lucky surprise — the bar1+h7+dd marginals on PPP_v20 happen to track v9 closer). This is unlike FINAL_E.

**However**: the mode 7 weights on disk (`slot_designer/machines/M15/weights/mode_7/weights.json`) are mode 1 v9 × (cherry × 0.5, bar1/2/3 × 0.9). If PPP_v20 ships as mode 1, mode 7 will need to be re-derived — and the [MODE7-CUT] / [MODE7-BIGPAY] PASS status today is **incidental, not enforced**. D's "mode 7 out of scope" claim is process-correct for design phase but **requires explicit ship-time gate**: V must re-derive mode 7 from PPP_v20 mode 1 and re-verify.

---

## 2. Hard issues (must fix or justify before ship)

### H1. **high7 share-of-base 31.5% = 393.5% of verify.py cap — biggest single-family violation in v13 series**

verify.py:298 caps high7 at 8.0% (philosophy §10 pareto defense + targets_v2). PPP_v20 puts high7 at **31.48%**. This is **23.48pp over cap**, **3.9× the cap**.

D's algebra (§8.2) demonstrates this is structural under v7 + paytable + R1 blank + RTP floor. **Conclusion D drew**: ship with documented caveat. **Correct conclusion**: this is exactly the situation `feedback_dont_lower_floor_when_blocked.md` warns about — must explore mechanism space (paytable change, R1 blank lower, RTP cap relaxation, strip restructure) BEFORE declaring "infeasible".

User has stated **paytable is locked** (USER_HARDLINES.md universal rule). User has stated **feature_params is locked**. User has *not* stated bar1 cap is hard 30% — D inferred it from "不能接受 bar1 独大". User has stated R1 blank ∈ [30, 40] (hard). User has stated total_rtp ∈ [94, 96] (hard).

**Required action**: D / main session must surface to user: "The combination of (bar1 share ≤ 30%) + (paytable lock) + (feature_params lock) + (R1 blank ≥ 30) + (total_rtp ≥ 94) **mathematically forces high7 share to 30%+ as the residual sink**". User then chooses:
- (a) Accept high7 dominance (define what cap is acceptable)
- (b) Relax bar1 ≤ 30% inference (re-allow bar1 dominance as v13a/b)
- (c) Relax R1 blank lower bound (more blank → less density to absorb)
- (d) Relax total_rtp floor (less base RTP burden)
- (e) Reconsider paytable lock for mode 1 specifically

Currently D presents this as a "structural caveat, ship the candidate". That's the same anti-pattern user has rejected 3 times. **Required**: explicit escalation document with the 5 options framed.

### H2. **6/7 [FAMILY-SHARE] REDs locked on disk**

Per Q9. PPP_v20 fails:
- cherry1 (below floor 26 by 3.16pp)
- bar_mixed (below floor 12 by 1.55pp)
- bar1 (above cap 12 by 14.6pp)
- bar2 (below floor 10 by 7.33pp)
- bar3 (below floor 5 by 4.18pp)
- high7 (above cap 8 by 23.48pp)

Only wild_pure PASSES (0.70 ∈ [0.4, 2.0]).

These bands are the **philosophy §10 pareto-trap defense user installed in targets_v2**. They exist precisely to prevent the kind of design PPP_v20 represents. Shipping PPP_v20 = invalidating the defense.

**Required action**: explicit user adjudication on which (if any) bands to widen, or which to drop entirely (e.g., "bar2 floor 10% impossible under v7 → drop or widen to 2%"). Verify.py must NOT be auto-widened to match PPP_v20 ("moving goalposts").

### H3. **g50100 0.02pp from cap — sub-SE margin**

26.98pp vs cap 27.00pp. 1M-spin sim SE ≈ 0.3pp → **~50% drift probability over cap**. PPP_v10 (g50100 26.70) is the de-risk alternative D names. **Required**: either commit PPP_v20 with explicit ship-then-iterate-if-RED policy, or ship PPP_v10 from the start.

### H4. **g15 0.10pp from cap**

14.90pp vs cap 15.00pp. Similar sub-SE margin. PPP_v8 (g15 14.43) is the de-risk alternative but tighter on RTP floor (94.11). Tradeoff. **Required**: same as H3.

### H5. **PWDF dd 27.36% < 28% verify floor**

Per Q8. Strip-layout-bound. D acknowledges; suggests "same caveat as v13b accepted at v9 mode 7 ship". But the v9 mode 7 dd 31.58% caveat is on a different floor (lucky/cut mode floors are lower). Mode 1 floor 28% is the actively-enforced PWDF mandate. **Required**: explicit "drop verify.py mode 1 dd PWDF floor to 27" OR "redesign strip with 3rd dd stop on R2" decision.

### H6. **[HIT] base vs session semantic ambiguity (carried from FINAL_E)**

verify.py:587-590 uses `state.profile["hit_rate"]` = base hit rate. PPP_v20 base hit = 14.83% — **fails [HIT] band [15, 18]**. USER_HARDLINES.md says session-centric (15.93% — passes).

This is the same H6 from critique_v13 (FINAL_E). User has not adjudicated. D did not surface. **Required**: either patch verify.py to use hit_session, OR explicit user decision that base hit < 15 is acceptable under session reading.

---

## 3. Soft concerns

### S1. high7 R1 16% breaks classic-7 archetype baseline (per `reference_classic_slot_rtp_distribution.md`)

Classic Blazing Sevens / Red White Blue baseline: high7 R1 density 4-8%. PPP_v20 R1=16% is **2-4× classic baseline**. The "classic 3-reel + cherry-anywhere + Feature Play" archetype is not preserved if high7 has 4× the density of a classic.

### S2. high7 near-miss / win ratio = 10.76× (Q4)

In Harrigan-defined manufactured-frustration zone (10-15× = predatory ratio in academic research). IGT typical is 4-6×. Not a hardline, but worth flagging to user as a "假但不怪" (philosophy §11) concern.

### S3. bar2 / bar3 effectively dead (Q5, Q6)

Per-spin probabilities:
- bar2 pure: 1 in 4,761 — 8% of 150-spin sessions see one
- bar3 pure: 1 in 16,187 — 0.8% of 150-spin sessions see one

The "bar slot" claim is misleading; PPP_v20 is "1bar + h7 dominant + cherry brand" with bar2/bar3 as cosmetic stops. Not a hardline violation; archetype mismatch.

### S4. cherry-3 dead pay (1 in 21,164)

Same critique as FINAL_E. cherry-3 is structurally rare under cherry-anywhere paytable + low cherry R3, but PPP_v20's cherry R3 = 3% makes cherry-3 even rarer than v9 baseline (~1 in 8,000). Not a critical issue but pay_id 4 is effectively dead.

### S5. Per-stop weight ratio inflation

Implied per-stop weight on R1 PPP_v20:
- 1bar: 28% / 3 stops = ~3360 per stop (normalized to 10000 total)
- blank: 39.6% / 18 stops = ~220 per stop
- 3bar: 2% / 4 stops = ~50 per stop
- Ratio 1bar:blank ≈ 15.3:1; 1bar:3bar ≈ 67:1

These are highly extreme per-stop weights for a physical reel. v9 baseline had ratios ~3:1. Not a verify violation, but a hint that the marginal targets are being forced through too-few strip stops.

### S6. Bell-shape direction abandoned (g510 = 8.71 < g15 = 14.90)

D explicitly acknowledges in §12 that bell-shape was dropped per v7. The user's underlying intent ("normal spin 不许 g15 dominant") is now violated — g15 IS the dominant bucket. User stated they'd accept this in v7, but the underlying experience-design rationale for bell-shape was real. Worth flagging.

---

## 4. Tradeoff matrix

| Choice | If you accept | You give up |
|---|---|---|
| **Ship PPP_v20** | bar1 ≤ 30% (v7 satisfied), g15 in band, all 14 user hardlines GREEN | (a) high7 31.5% = bar1 dominance with different label; (b) 6/7 FAMILY-SHARE REDs; (c) PWDF dd RED; (d) bar2/bar3 cosmetic; (e) classic archetype fidelity |
| **Ship PPP_v10** (safer margins) | RTP 94.46 above floor by 0.46pp, g50100 26.70 (more headroom), g15 14.85 (more headroom) | RTP closer to floor (1.54pp below mid); high7 share still ~31%; same FAMILY-SHARE / PWDF REDs |
| **Ship PPP_v8** (RTP-floor risk) | g15 14.43 (closer to v7 "lower edge" intent) | RTP 94.11 (0.11pp above floor — sub-SE) — high drift risk under cap-side noise; same FAMILY-SHARE REDs |
| **Iterate further (option A)** | Could find ~14.4pp g15 floor with bar1 share 26% locked | High7 share will still be 30%+ — structural floor unchanged |
| **Escalate to user (option B)** | Honest framing of the impossible-jointly-constrained system | Requires user to adjudicate verify.py band relaxations OR drop a hardline |
| **Pivot to "v9 family balance" (option C from critique_v13)** | Preserve cherry1/bar_mixed dominance, satisfy more FAMILY-SHARE bands | g15 ≥ 15 likely (cherry-1 RTP > 11pp), bar1 share will rise (10pp+); user "no bar1 dominant" violated |

---

## 5. Verdict: **FIX-FIRST**

**Top 3 critical concerns**:

1. **high7 31.5% = bar1 44% wearing a different jersey** (Q1). The user's underlying invariant ("no single family dominates") is violated. Verify.py codifies this at 393.5% of cap — the LARGEST single-family over-cap violation in the v13 series. D's argument "user only said bar1" treats user as legalist; user's pattern of rejection is dominance-pattern-based.

2. **6/7 [FAMILY-SHARE] REDs and PWDF dd RED unexplored** (H2 + H5). D documents these as "structural under v7" but doesn't escalate. Per `feedback_dont_lower_floor_when_blocked.md`, "structural" requires proving 4-mechanism exhaustion before that label sticks. D explored 1 mechanism (marginal redistribution); strip restructure, R1 blank relaxation, paytable consideration are unexplored.

3. **No escalation document**. The structural conclusion D draws (g15 floor 14.4pp + high7 30%+ residual) IS likely correct, but the format is wrong: D presents a candidate to ship with caveats, not a feasibility report with adjudication options. After 3 rejected iterations, user needs:
   - Crisp proof that {USER_HARDLINES v7} + {paytable lock} + {feature_params lock} = no feasible candidate satisfying all desired soft objectives
   - Enumeration of relaxation options (5 from H1)
   - Recommended path with explicit consequences

**Specific path forward**:

**OPTION B (escalate)** is the correct call. Specifically:
1. D / main session writes `session_artifacts/M15/v13c_escalation.md` covering:
   - Structural proof: under v7 hardlines, high7 share-of-base ≥ 30% is forced (with sweep evidence over R1 blank ∈ [30, 40], cherry sum ∈ [5, 15], bar1 R1 ∈ [15, 30])
   - 5 relaxation options enumerated (per H1)
   - Recommended option with consequences
2. User decides which relaxation to accept
3. THEN D iterates within the relaxed space and ships

**Alternative path (OPTION A)**: D explicitly explores the 4 mechanism dimensions per `feedback_dont_lower_floor_when_blocked.md`:
- Mechanism 1: marginal redistribution (done — yielded PPP_v20)
- Mechanism 2: strip restructure (add 3rd dd stop on R2 to fix PWDF; potentially restructure for better archetype balance) — UNEXPLORED
- Mechanism 3: paytable consideration (out of scope per user lock, but flag if it's the only path)
- Mechanism 4: architecture upgrade (virtual reel mapping for PWDF) — UNEXPLORED

If after Mechanism 2 + 3 + 4 the floor still holds, ESCALATE per Option B.

**Do not ship PPP_v20.** It's the most adversarial-aware candidate in the v13 series (D's self-critique Q1-Q5 is actually solid), but the underlying user invariant violation (Q1) makes shipping ineffective — user will reject for the 4th time with the same "but high7 is now dominant" reasoning.

---

## 6. Self-critique of this critique (one round)

**Am I being too harsh on D's "structural caveat" framing?** Mostly no. D's algebraic argument that bar1 ≤ 30% + paytable + RTP floor + R1 blank cap forces high7 ≥ 30% is sound; the criticism is that this conclusion should be a FEASIBILITY REPORT with escalation, not a CANDIDATE TO SHIP. Process violation, not math violation.

**Am I missing that user might accept PPP_v20 anyway?** Possible. User's v7 statement was explicit about bar1 share ≤ 30%, and PPP_v20 satisfies that. If the user reads PPP_v20 and says "OK ship", that's their call. But the pattern across 3 rejections suggests user's mental model is about dominance, not labels. The bar/high7 swap is unlikely to land well without explicit user-stated framing.

**Did I over-count FAMILY-SHARE failures?** No — I independently reproduced D's marginals through `analytic_profile_from_marginals` and counted 6/7 FAILs against verify.py-on-disk bands. These are checkable facts, not opinion.

**Could D's "high7 absorbs residual RTP" claim be wrong?** I spot-checked one alternative configuration (h7 R1=19, low cherry, see Q3) — pushes h7 share to 40%, breaks RTP floor. D's broader claim holds in the explored region. The lurking question is whether the explored region was exhaustive — D's 25 candidates is finite, not proof.

**Did I propose changing anything user-stated?** No. All H1-H6 are either:
- Asking for user adjudication (H1, H5)
- Pointing out shipped verify.py invariants D needs to address (H2)
- Naming sim-noise risks (H3, H4)
- Carrying forward unresolved semantic ambiguity from FINAL_E (H6)

Nothing proposes loosening a user-stated hardline. Per task constraints, I propose escalation paths only.

**Am I the "looks fine" agent?** No. This verdict is FIX-FIRST, with three named structural blockers. I am calling D's iteration progress (the bar1 → 26.6% reduction is real and significant) but also calling that the iteration did not solve the user's underlying invariant.

---

## 7. Verification artifacts

All numbers in §1 / §2 reproduce via:
- `slot_designer.core.devtools.analytic_rtp.analytic_profile_from_marginals` (PPP_v20 marginals as 3-reel dict list)
- `slot_designer.machines.M15.plugins.feature._round_payout_distribution` (locked feature_params v9)
- Strip from `slot_designer/machines/M15/reel_strips.json` v8.1 (no production file touched)
- Verify.py bands from `slot_designer/machines/M15/verify.py:280-380` (read-only)

Reference paths:
- `slot_designer/machines/M15/verify.py:291-300` — `FAMILY_SHARE_BANDS_PCT[1]` (6/7 FAIL on PPP_v20)
- `slot_designer/machines/M15/verify.py:362-367` — `_PWDF_TOP_ANY_REEL_FLOOR_PCT[1]` (dd FAIL at 27.36 < 28)
- `slot_designer/machines/M15/verify.py:280` — `M1_PAY1_CADENCE_RANGE` (1/64k PASS)
- `slot_designer/machines/M15/verify.py:586-590` — `[HIT]` semantic ambiguity (carried from FINAL_E)
- `slot_designer/machines/M15/USER_HARDLINES.md` v7 (read for v7 changelog entry on user intent)
- `session_artifacts/M15/design_v13c.md` — D's report (PPP_v20)
- `session_artifacts/M15/scripts/m15_v13c_design.py` — D's script
- `session_artifacts/M15/critique_v13.md` — prior X critique on FINAL_E

No production file modified. No hardline added. Critique uses philosophy + first principles as direction.
