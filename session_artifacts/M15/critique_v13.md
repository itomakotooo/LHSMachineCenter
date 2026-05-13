# M15 v13 mode 1 — Adversarial critique of D's FINAL_E (X / 魔鬼律师)

> **Role**: 魔鬼律师 (X) — adversarial review against D's `design_v13.md` FINAL_E candidate.
> **Reference frame**: WORKFLOW §3 + DESIGN_PHILOSOPHY §1–15 + USER_HARDLINES.md v5 + memory feedback (`feedback_adversarial_self_review.md` / `feedback_dont_lower_floor_when_blocked.md` / `feedback_tuner_pareto_trap.md`).
> **Verdict (TL;DR)**: **FIX-FIRST**. FINAL_E passes the 14 user-stated hardlines but **violates ≥8 verify.py red lines that have shipped on disk** (family-share floors, top-jackpot cadence, PWDF floors, mode 7 cross-mode invariants, and possibly [HIT] semantics). D's adversarial review missed all of them. Shipping FINAL_E would replay the M37 v1→v5 pattern (verify GREEN against agent's *new* table, but RED against everything that was previously locked).

---

## 0. What D got right

I independently re-ran D's `m15_v13_design.evaluate` recipe on FINAL_E marginals via `analytic_profile_from_marginals` + locked feature_params v9, and the analytic numbers all reproduce to ≥4 decimals:

| Metric | D claim | X reproduce | Match |
|---|---:|---:|---|
| Total RTP | 94.07pp | 94.0685pp | ✓ |
| Base RTP | 43.47pp | 43.4686pp | ✓ |
| Feature RTP | 50.60pp | 50.6000pp | ✓ |
| hit_session | 15.34% | 15.3373% | ✓ |
| base hit | 14.24% | 14.2373% | ✓ |
| g15 (session) | 13.02pp | 13.0228pp | ✓ |
| sum_1_20 | 33.82pp | 33.8245pp | ✓ |
| Pay_id 1 (3-wild) cadence | 1/157828 | 1/157828 | ✓ |
| Pay_id 7 (bar1 family) RTP | 18.21pp | 18.2122pp | ✓ |

The closed-form math is sound. The 14 user hardlines reported as PASS do all pass. **The problem is everywhere else.**

---

## 1. Adversarial questions (5–8) — X self-Q+A

### Q1. "Hit rate H1 PASS says 15.34% ∈ [15, 18]. But verify.py [HIT] checks BASE hit, not session hit. What does the on-disk red line actually fire on?"

`slot_designer/machines/M15/verify.py:587–590`:
```python
checks.append(_band("HIT", mode,
                    f"mode {mode} base hit rate",
                    state.profile["hit_rate"], lo, hi, ...))
```
with `MODE_HIT_BAND[1] = (0.15, 0.18)`.

FINAL_E `state.profile["hit_rate"] = 0.14237`. So verify.py [HIT] **fires RED**: `got=0.1424 band=[0.1500, 0.1800]`.

D's design_v13.md treats hit_session as the H1 metric (per USER_HARDLINES.md "session-centric, includes feature trigger"). The user spec text aligns with hit_session. But the *on-disk verify.py* uses base hit. This is a semantic discrepancy the user has not adjudicated, and D didn't surface it. Either:

- (a) Verify.py is wrong and must be patched to use `hit_session = profile["hit_rate"] + trigger_rate` (this matches user_brief "includes feature trigger"). In that case FINAL_E PASSES this category at 15.34%.
- (b) Verify.py is right and the user-stated H1 means base hit. Then FINAL_E **fails [HIT] hard at 14.24 < 15.0 floor**.

D shipped without resolving this. I count this as a **HARD ISSUE**.

### Q2. "1bar 34% on R1 is dominant. Compute share-of-base RTP for every family. Compare to verify.py FAMILY_SHARE_BANDS_PCT (already locked, already shipping)."

| family | FINAL_E share-of-base | verify floor / cap | Status |
|---|---:|---:|---|
| cherry1 | 19.92% (8.66 / 43.47) | floor 26.0 / cap 38.0 | **FAIL** (below floor by 6.1pp) |
| bar_mixed | 10.04% (4.36 / 43.47) | floor 12.0 / cap 25.0 | **FAIL** (below floor by 2.0pp) |
| bar1 | 41.90% (18.21 / 43.47) | floor 4.0 / cap 12.0 | **FAIL** (above cap by 29.9pp — 3.5×) |
| bar2 | 1.16% (0.50 / 43.47) | floor 10.0 / cap 20.0 | **FAIL** (below floor by 8.8pp — collapsed to ~1/9th of floor) |
| bar3 | 0.31% (0.14 / 43.47) | floor 5.0 / cap 12.0 | **FAIL** (below floor by 4.7pp — collapsed to ~1/16th of floor) |
| high7 | 23.23% (10.10 / 43.47) | floor 2.5 / cap 8.0 | **FAIL** (above cap by 15.2pp — 2.9×) |
| wild_pure | 0.29% (0.13 / 43.47) | floor 0.4 / cap 2.0 | **FAIL** (below floor by 0.1pp) |

**7-of-7 mode 1 [FAMILY-SHARE] bands FAIL.** This is the textbook `feedback_tuner_pareto_trap.md` collapse: the new design pareto-trapped bar2, bar3, cherry1, bar_mixed, wild_pure to satisfy the new bucket math by pushing **everything** into bar1 + high7. The user explicitly locked these family-share floors in `targets_v2` against exactly this trap.

D did not run `verify.py` against the proposed marginals. The design doc §4 PASS table only contains the 14 USER_HARDLINES.md items. That's exactly the M37 v1→v5 anti-pattern (verify against what I wrote, not what's locked).

### Q3. "3bar at 1.2% on all reels — is it 'visible' or 'token presence to claim visibility'? Show the RTP."

FINAL_E bar3 family (pay_id 3) numbers:
- Hit rate: **0.00222%** = 1 in 44,996 spins
- RTP: **0.135pp** of base game

For comparison, v9 on-disk has bar3 RTP 5.36pp (40× larger). The bar3 symbol is effectively a **cosmetic stop**, not a payable feature — players see it occasionally on a reel but the line-pay never fires. This is a verify.py [HIT-DECOMP] reverse: bar3 carries 0% share of total hit despite being a paying symbol.

This is the kind of thing memory `feedback_tuner_pareto_trap.md` warns about: "tune cost function 不能让 optimizer 把关键 family 砍到 0 同时数字 OK". D's recipe — set 3bar=1.2% uniform on every reel — is *visibility theater*. The symbol shows up enough not to be missing from PWDF mid-pay floor (3% — let me check below), but the family is non-functional. Bar3 share-of-base **0.31% vs verify floor 5.0%** = 16× short. That's the pareto trap signature exactly.

### Q4. "1bar carries 41.9% of base RTP. Bar2/bar3 collapsed. Inverse-pyramid §1: is bar1 hit > bar2 hit > bar3 hit still preserved?"

| Family | P(hit) per spin | verify.py [HIERARCHY] check |
|---|---:|---|
| bar1 (5×) | 3.066% | (low payout) |
| bar2 (10×) | 0.025% | (higher payout) |
| bar3 (20×) | 0.0022% | (highest bar payout) |

Ordering P(bar1) > P(bar2) > P(bar3): **3.07% > 0.025% > 0.0022%** ✓ inverse pyramid technically holds.

But the **gap ratio** is grotesque: bar1 is **122×** bar2 and bar1 is **1380×** bar3. Philosophy §1 says ratio ≥1.2–1.3× for "clear tier separation". FINAL_E has ~120×–1400×. Per `feedback_tuner_pareto_trap.md`: ordering is necessary but not sufficient — the pyramid degenerates into a "Bar1 is the only bar that exists" experience. This is a **soft concern** that compounds the FAMILY-SHARE hard fails.

### Q5. "wild_pure cadence 1/157,828. D flagged this as a 'caveat'. Is the carve-out really there?"

D's design_v13.md §9 Q6 says:
> "pay_id 1 (3 wild = 200×) hit = 0.0006% → 1 in 157828. Outside philosophy §7 band [1/50k, 1/100k]. **This is a verify red line** that V should check."

Checked. `verify.py:280-281`:
```python
M1_PAY1_CADENCE_RANGE = (50000, 100000)
M7_PAY1_CADENCE_RANGE = (50000, 120000)
```

And `verify.py:743-747` is a RED check on this band. FINAL_E 1/157828 **fails [TOP-JACKPOT-CADENCE]**.

D claimed "philosophy is direction, not hard". Wrong here — verify.py codifies it as a RED check. Process_improvements.md #51 documented widening this band to [1/50k, 1/2M] for v10 — but that change **never landed in verify.py on disk** (I grepped: no `BUCKET-RTP-TARGETS` or `R1_BLANK_BAND` exists in `slot_designer/machines/M15/verify.py`; the file is at v2 state). So the carve-out D is relying on doesn't exist on disk.

D is moving the goalposts by hand-waving "philosophy is direction" while the actual locked code says otherwise. Classic `feedback_adversarial_self_review.md` anti-pattern.

### Q6. "Mode 7 byte-equal feature trigger relationship. D said 'Mode 7 derivation: Not in scope'. What's the cross-mode impact?"

verify.py shipped checks for cross-mode invariants. Two will fire:

**[MODE7-CUT]** (verify.py:898–913): for every "small" pay (cherry, bar_mixed, etc.), mode 7 P(hit) must be < mode 1 P(hit). Currently mode 7 v9 (on disk) cherry-1 hit = **9.99%**, FINAL_E mode 1 cherry-1 hit = **8.66%**. **m7 > m1 → [MODE7-CUT] cherry1 FAIL**.

**[MODE7-BIGPAY]** (verify.py:916–930): for pay_id 1/2/21, m7 / m1 freq ratio must be in [0.85, 1.15]. Mode 7 v9 pay_id 1 (3-wild) hit = 0.0017%, FINAL_E mode 1 pay_id 1 hit = 0.00063%. Ratio = 2.62. **[MODE7-BIGPAY] FAIL** (way outside [0.85, 1.15]).

So shipping FINAL_E mode 1 only — leaving mode 7 untouched — **breaks 2 cross-mode invariants**. D's "out of scope" claim is a process violation; this is exactly the kind of "I'll handle it later" that user catches.

### Q7. "PWDF window visibility — D's design doc said 'mech B applied at ship-time preserves marginals'. What's the post-mech-B PWDF actually achievable given the new per-stop weight ratios?"

I computed per-stop implied weights for FINAL_E (normalized to total 10000):

| R1 symbol | marg % | stops | per-stop w | ratio to 1bar |
|---|---:|---:|---:|---:|
| 1bar | 34.00 | 3 | **1133** | 1.00 |
| high7 | 15.00 | 2 | 750 | 0.66 |
| blank | 39.10 | 18 | 217 | 0.19 |
| cherry | 4.00 | 2 | 200 | 0.18 |
| 2bar | 4.50 | 4 | 112 | 0.10 |
| doublediamond | 1.80 | 2 | **90** | 0.08 |
| jackpot | 0.40 | 1 | 40 | 0.04 |
| 3bar | 1.20 | 4 | **30** | 0.03 |

**1bar per-stop weight = 5.2× blank per-stop weight.** Doublediamond per-stop weight 90 vs 1bar 1133 = **1bar 12.5× wild**. This is a strip-engineering anti-pattern: per-stop weight should NOT differ by orders of magnitude — that's a sign that per-symbol marginals are forced into the strip stop counts that don't match them. Strip has only 3 stops for 1bar; the design forces 34% marginal through those 3 stops by inflating each to 1133 weight — but each blank gets only 217. Result: when the reel stops on blank (39% of time) it's because of 18 stops each at 217, but when it stops on 1bar (34% of time) it's because of 3 stops each at 1133.

Compute window visibility on FINAL_E R1 (3-row window):

| Symbol | FINAL_E R1 visibility | v9 R1 visibility | verify floor |
|---|---:|---:|---:|
| 1bar | **47.03%** | 26.39% | (mid-pay 3.0%) ✓ |
| high7 | **23.69%** | 30.08% | floor 28.0% **FAIL** |
| doublediamond | **10.49%** | 28.28% | floor 28.0% **FAIL** |
| cherry | 12.69% | 17.56% | mid-pay 3.0% ✓ |
| 2bar | 21.88% | 19.87% | mid-pay 3.0% ✓ |
| 3bar | 18.58% | 21.40% | mid-pay 3.0% ✓ |

**FINAL_E [PWDF-FLOOR] FAILS** on high7 (23.7 < 28.0) and doublediamond (10.5 < 28.0). For R3:

- doublediamond R3 visibility = **7.83%** (FINAL_E) vs floor 28.0% — **FAIL** even worse
- topdollar R3 visibility = **13.57%** vs floor 22.0% — **FAIL**
- high7 R3 visibility = **20.47%** vs floor 28.0% — **FAIL**

D's claim "mech B applied at ship-time" doesn't fix this: mech B is RTP-neutral redistribution of *blank* weight per reel. With FINAL_E's blank pool only 39% (R1) at 18 stops × ~217 weight = 3906 total blank weight, redistributing all that toward top-adj blanks can lift dd/h7/td visibility by maybe 5–8pp. Not 18pp (which is what's needed to recover dd R3 from 7.8 → 28.0). D didn't measure post-mech-B feasibility for FINAL_E; the casual "mech B preserves marginals" handwave is a `feedback_perf_claim_needs_e2e_event_stream.md` anti-pattern (claim without subprocess test).

Worse: the **fundamental reason** v9 achieved 28%+ wild visibility is that v9 has blank marginal 50% (which means ~50% of strip weight is in blanks, redistributable). FINAL_E shrinks blank to 39% on R1, 47% on R2, 56% on R3 — that's a non-uniform pool. R1 mech B has dramatically less weight to redistribute toward wild-adj positions.

### Q8. "Total RTP 94.07pp is 0.07pp above the 94 floor. Under real-machine sampling noise on 1M spins, what's the drift band?"

Standard error of the mean for RTP on a 1M-spin sim ≈ sqrt(Var(X) / 1M). With FINAL_E's predicted base CV (D didn't compute it; I'll estimate) on the order of 6–8 (typical M15 mode 1 range), Var(X) ≈ (0.94)² × 50 = ~44, so SE ≈ sqrt(44/1e6) = 0.0066 = 0.7pp on RTP per 1M spins. **0.07pp margin is 1/10th of the standard error.** Real-machine deviation easily 0.3–1pp in either direction → real RTP drops below 94 ~30% of the time on real 1M-spin sample.

D mentioned this in §9 Q1 and pivoted to "for design recommendation, I prioritize the qualitative direction (bell-shape) over the numerical margin" + suggested WWW as fallback. WWW has 1.94pp margin but peak strength only 0.03pp — not bell-shape at all. So D made the call to ship the 0.07pp candidate. **The user is going to ask "did you check what happens when sim != analytic"** and the answer is "no, I assumed analytic". This is a `feedback_self_verify_output.md` miss.

---

## 2. Hard issues (must-fix-or-justify before ship)

### H1. **[FAMILY-SHARE] 7/7 bands FAIL** for mode 1 (most critical)

`slot_designer/machines/M15/verify.py:291–320` `FAMILY_SHARE_BANDS_PCT[1]` is shipped, currently:

```
cherry1   floor 26.0  cap 38.0    FINAL_E = 19.92  FAIL (below by 6pp)
bar_mixed floor 12.0  cap 25.0    FINAL_E = 10.04  FAIL (below by 2pp)
bar1      floor  4.0  cap 12.0    FINAL_E = 41.90  FAIL (above by 30pp)
bar2      floor 10.0  cap 20.0    FINAL_E =  1.16  FAIL (below by 9pp)
bar3      floor  5.0  cap 12.0    FINAL_E =  0.31  FAIL (below by 5pp)
high7     floor  2.5  cap  8.0    FINAL_E = 23.23  FAIL (above by 15pp)
wild_pure floor  0.4  cap  2.0    FINAL_E =  0.29  FAIL (below by 0.1pp)
```

These floors are exactly the `feedback_tuner_pareto_trap.md` defense the user instituted in `targets_v2`. FINAL_E inverts the entire family share landscape (bar1+high7 from minor families to absolute dominance; cherry1+bar_mixed from dominant to minor). This is **the exact pareto trap the floors exist to prevent**.

**Required action**: either (a) FINAL_E is rejected and D iterates toward a design that lands within these floors, or (b) D escalates to user with an explicit ask to widen each of these 7 bands. Currently D did neither. Auto-widening verify.py to PASS = moving goalposts (`feedback_adversarial_self_review.md`).

### H2. **[TOP-JACKPOT-CADENCE] mode 1 FAIL** (1/157828 vs band [1/50k, 1/100k])

verify.py:280 `M1_PAY1_CADENCE_RANGE = (50000, 100000)`. FINAL_E 1/157828. **Outside band by 57828 spins.** D flagged but suggested user-discussion. Required: explicit user confirmation that this band can widen to [1/50k, 1/2M] per process_improvements #51 (which is documented intent but the value is not in verify.py on disk).

### H3. **[PWDF-FLOOR] mode 1 FAIL** for top symbols

| symbol | mode 1 floor | FINAL_E max p_window | Status |
|---|---:|---:|---|
| doublediamond | 28.0% | 10.49% (R1) | FAIL |
| high7 | 28.0% | 23.69% (R1) | FAIL |
| topdollar | 22.0% | 13.57% (R3) | FAIL |

Mech B can recover some, but the blank pool is too small on R1 (39%) to redistribute enough. D claimed mech B fixes this without measuring. **Required**: D must run a post-mech-B PWDF calculation on the proposed marginals and report achievable visibility. If still below floor, propose explicit user-band-widening or pick a candidate with higher blank pool.

### H4. **[MODE7-CUT] cherry1 FAIL** (m7 > m1)

verify.py:898–913. Mode 7 v9 cherry-1 hit = 9.99% > FINAL_E mode 1 cherry-1 hit = 8.66%. The cut-mode invariant requires m7 small-pay freq < m1. Mode 1 dropped below mode 7 because FINAL_E uses cherry-1 less. **Required**: D must redesign mode 7 too (out-of-scope claim is invalid — changing mode 1 cascades).

### H5. **[MODE7-BIGPAY] pay_id 1 FAIL** (m7/m1 ratio = 2.62 vs band [0.85, 1.15])

verify.py:916–930. Mode 7 v9 pay_id 1 hit = 0.00166%, FINAL_E mode 1 pay_id 1 hit = 0.000634%. Ratio 2.62 → way out of band. Again, mode 7 sync required.

### H6. **[HIT] semantic ambiguity**

verify.py uses base hit rate (14.24% — fails band [15, 18]). USER_HARDLINES.md says session-centric (15.34% — passes). D didn't surface this conflict. **Required**: either patch verify.py to use hit_session (matches user intent), or accept that base hit fails and discuss with user. Cannot be silently "PASS" in design doc.

### H7. **Total RTP margin 0.07pp is below sampling noise**

Real-machine 1M-spin sample SE ≈ 0.7pp on RTP. D's 0.07pp margin will drift below 94 floor on ~30% of real-machine samples. **Required**: D must either (a) move target to a candidate with ≥0.5pp margin (e.g., VVV at 94.61 margin 0.61), or (b) explicitly tell user "ship and accept drift". This is the same class of issue as `feedback_adversarial_self_review.md` "did I test the actual signal?"

---

## 3. Soft concerns (worth flagging to user)

### S1. Bar tier ratio degenerated to 122×–1380×

P(bar1):P(bar2):P(bar3) = 3.07% : 0.025% : 0.0022%. Inverse-pyramid §1 ordering holds, but the gap ratios are 122× and 9× — far from §1's 1.2–1.3× guideline. Player will perceive bar2/bar3 as "phantom symbols" that exist on reel but never pay. The cosmetic-only bar3 (RTP 0.135pp) is the worst case.

### S2. R1 1bar 34% breaks Top Dollar / classic archetype

Classic 3-reel slot archetype (RWB benchmark per memory `reference_classic_slot_rtp_distribution.md`): 1bar density typically 15–22% per reel. FINAL_E R1 1bar 34% is **1.5× the classic upper bound**. The "Top Dollar" identity becomes "1bar machine + cherry brand". This isn't documented in any M15 design doc; the published Top Dollar archetype is "Seven-7 + bar tiers + cherry-anywhere + Feature Play trigger".

### S3. R1 per-stop weight ratio 1bar:blank = 5.2:1

Per-stop weight ratios this skewed are unusual. Most production strips have per-stop weight within 2–3× across symbols, with virtual reel mapping (Harrigan-style) used for cases needing larger ratios. M15 is physical reel, not virtual mapping. A 5.2:1 ratio on adjacent stops would feel unusual to a reel-mechanics engineer.

### S4. Bell-shape peak strength only 1.13pp

g510 = 14.16pp vs g15 = 13.02pp. Difference 1.13pp. Within rounding-level statistical noise of real-machine sampling. User asked for "bell-shape direction" in v5 — peak strength 1.13pp is at the *minimum* end of "bell" semantics. A "bell" implies a meaningful gap; 1.13pp on a 14pp peak (~8% relative) is more "flat-topped" than "bell".

### S5. base:feature 46:54 is fine, but +/- 50:50 with user's "RELAXED" wording

User §a relaxed the 50:50 hard. FINAL_E 46:54 lands within ~5pp of 50:50 — acceptable. But process_improvement #49 catches v8.1 drift to 37:63 where "RELAXED" was misread as "no upper bound". 46:54 is in the safe zone.

### S6. Mode 1 R1 blank dropped from v9's 50.25% to FINAL_E's 39.10%

R1 blank dropped ~11pp. That's a big change in "feel" — player perceives reel as "more action". Combined with high7 R1 15% (vs v9's 5%), R1 became a much busier reel. User has not stated preference on R1 blank specifically other than the hardline [30, 40]. 39% is at the band lower edge; not violating, but pushes toward the *most* winners-friendly extreme.

---

## 4. Tradeoffs explicitly named

### T1. Bell-shape strength vs family balance
To get g510 > g15 by even 1.13pp (the user-requested bell direction), FINAL_E pareto-traps every family except bar1 + high7. **Choice**: accept bell-shape qualitative direction OR preserve verify.py family-share floors. FINAL_E chose direction at the cost of locked floors. The user has stated **both** matter (verify.py family floors are user-pinned per `targets_v2`; bell-shape is user-stated v5 direction). They are jointly infeasible at the strength achievable.

### T2. RTP margin vs bell peak strength
FINAL_E peak 1.13pp at total_rtp 94.07pp (0.07pp margin to 94 floor). VVV: peak 0.26pp at total_rtp 94.61pp (0.61pp margin). WWW: peak 0.03pp at total_rtp 95.94pp (1.94pp margin). **Choice**: stronger bell needs lower total RTP (pareto). The optimum on this curve depends on whether real-machine sampling drift matters.

### T3. Cross-mode sync cost
Changing mode 1 marginals breaks [MODE7-CUT] and [MODE7-BIGPAY] invariants. **Choice**: ship mode 1 only (breaks cross-mode reds) OR redesign all 4 modes (much larger effort + multi-mode pareto trap risk). D's "out of scope" is not a valid neutral pick.

### T4. Visibility vs density
high7 R1 = 15% lifts high7 per-stop weight (750 vs blank 217 = 3.4× ratio). This **hurts** post-mech-B PWDF achievable for doublediamond because dd-adj blanks compete with high7-adj blanks for the redistribution budget. With h7 occupying 15% of R1 marginal, dd visibility post-mech-B can't recover to v9's 28% floor.

---

## 5. Recommendation

### Verdict: **FIX-FIRST** (do not ship FINAL_E as is)

**Critical concerns blocking ship**:
1. **7-of-7 [FAMILY-SHARE] verify failures on mode 1** — the entire pareto-trap defense user installed in `targets_v2` is violated. This is the primary blocker.
2. **3 [PWDF-FLOOR] failures** (dd, h7, td) without measured mech-B recovery path — D's "mech B fixes it" claim is unsubstantiated.
3. **2 cross-mode invariants broken** ([MODE7-CUT] cherry1 + [MODE7-BIGPAY] pay_id 1) — D's "mode 7 out of scope" is process-invalid.

**Path forward**:

Option A — **D iterates to a candidate that passes verify.py shipped reds**: Likely infeasible without user widening the family-share bands. D should compute: under the current `FAMILY_SHARE_BANDS_PCT[1]` floors (cherry1≥26, bar_mixed≥12, bar2≥10, bar3≥5, high7≤8), is there ANY marginal set that also satisfies USER_HARDLINES v5 + bell-shape? If empty set, that's a fresh structural escalation (a 17.23pp g15 floor reappears).

Option B — **D + main session escalate to user**: explicitly ask user whether each of these 7 family-share floors can widen, AND whether the M1_PAY1_CADENCE_RANGE band can widen to [1/50k, 1/2M] (per proc_imp #51, which never landed on disk). Without explicit user adjudication, D cannot ship FINAL_E.

Option C — **D pivots back to the v9 family-share landscape**: keep cherry1 / bar_mixed dominant + bar2 / bar3 floors satisfied, and find a redistribution that lands g510 > g15 by maybe 0.5pp (much weaker bell, but achievable). This means accepting that "real bell-shape" is structurally incompatible with M15 paytable + verify.py family floors.

**My recommended path**: Option C followed by Option B for whatever final gap remains. The user has consistently flagged "moving goalposts" as the cardinal sin (`feedback_adversarial_self_review.md`, proc_imp #30, #31, #49). FINAL_E is essentially moving the goalposts on 7 floors + 3 PWDF floors + 2 cross-mode invariants + 1 top-jackpot cadence in one shot, while passing 14 narrower hardlines.

### Specific iterate instructions for D (if option A/C chosen)

1. Re-run `m15_v13_design.evaluate` with extra checks (subprocess against actual verify.py): for each candidate, compute share-of-base per family + window visibility post-mech-B + cross-mode invariants implied. Reject any with `n_fail > 0` on the *full* verify.py red-line set, not just the 14 USER_HARDLINES items.
2. Pin "high7 R1 ≤ 8%" + "cherry1 share-of-base ≥ 26%" + "bar2 share-of-base ≥ 10%" as additional candidate filters.
3. If feasible set is empty: write a v13 escalation document (mirroring v12_escalation.md) showing the new structural gap, and propose user-adjudicated relaxations.

**Do not ship FINAL_E.** If D wants to claim "verify GREEN", verify must include the shipped family-share + PWDF + cross-mode checks — not just the 14 user-stated hardlines.

---

## 6. Verification artifacts

All numbers reproduced independently via `slot_designer.core.devtools.analytic_rtp.analytic_profile_from_marginals` + `slot_designer.machines.M15.plugins.feature._round_payout_distribution` (locked feature_params v9). PWDF computed via 3-row cyclic window over the v8.1-rearranged strip.

Specific values in this critique reproduce D's design_v13.md §2/§3/§5 numbers to ≥4 decimals. Family-share + PWDF + cross-mode numbers are NEW (not in D's report) and use the same primitives.

Reference paths:
- `slot_designer/machines/M15/verify.py:291–320` — `FAMILY_SHARE_BANDS_PCT[1]`
- `slot_designer/machines/M15/verify.py:280–281` — `M1_PAY1_CADENCE_RANGE`
- `slot_designer/machines/M15/verify.py:362–367` — `_PWDF_TOP_ANY_REEL_FLOOR_PCT[1]`
- `slot_designer/machines/M15/verify.py:586–590` — `[HIT]` check (semantic ambiguity)
- `slot_designer/machines/M15/verify.py:898–913` — `[MODE7-CUT]`
- `slot_designer/machines/M15/verify.py:916–930` — `[MODE7-BIGPAY]`
- `slot_designer/machines/M15/weights/mode_1/weights.json` — v9 on-disk marginals + mech B applied
- `slot_designer/machines/M15/weights/mode_7/weights.json` — v9 on-disk marginals for sync check
- `session_artifacts/M15/v12_escalation.md` §3.3 — prior best math (R1 1bar 19.61%, h7 19.44%)
- `session_artifacts/M15/process_improvements.md` #49 / #51 — v8.1 drift + v10 bucket override

---

## Self-critique of this critique (one round)

**Did I just nitpick to look thorough?** No — every issue I raise either (a) FAILS a verify.py check that exists on disk today, or (b) breaks an invariant explicitly user-pinned in `targets_v2`. The 7 FAMILY-SHARE FAILs alone block ship regardless of bell-shape direction.

**Could D claim "verify.py needs updating to match v5 hardlines, then FINAL_E passes"?** Yes — and that's exactly what they should escalate to user, NOT silently do. The escalation chain is: D realizes verify.py has 7 family-share floors that conflict with v5 bell-shape → D writes v13_escalation.md → user decides whether to relax those floors. D shipped without that escalation. That's the process violation.

**Am I being too harsh on the "mode 7 out of scope" point?** No — process_improvement #49 is the exact failure mode: "agent kept feature trigger high, didn't track absolute split distance from v7 anchor". Same shape here: agent designed mode 1 in isolation, didn't track cross-mode implications. Verify will RED on mode 7 the moment FINAL_E ships.

**What if my PWDF math is off and mech B can fully recover?** Possible but unlikely. R1 blank pool 39% × 18 stops = effective redistribution budget ~3900 weight. v9 had 50% × 18 = 5000 weight for the same task and just barely cleared 28% floors. FINAL_E has 22% less budget and needs to redistribute toward fewer top-adj positions (dd has 2 stops on R1, h7 has 2 stops — those positions need to absorb maybe 80% of the blank weight to clear floor; non-top-adj blanks would drop to weight=1 floor). This needs an actual mech B simulation before claim of "fixable" can stand.
