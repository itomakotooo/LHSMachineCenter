# Stage 4 — Pre-tune adversarial re-review (Agent X, wave 2)

> Date: 2026-05-11 (wave 2)
> Subject: D's `session_artifacts/M15/design_v1.md` + `targets_v1/M15_mode{1,2,5,7}_target.json` + `scripts/design_v1_feasibility.py` + `feasibility_v1.txt`
> Reviewer: X (魔鬼律师 / adversarial critic)
> Contract: `slot_designer/ONBOARDING_PROCESS.md` §4 X row + §5 Stage 4 review
> Method: same 5-step as v0 + new Step 1 (feasibility script audit)
> Predecessor: `mode_pretune_critique_v0.md`

---

## Verdict

**REVISE (minor)** — feasibility-first process is a major improvement, all 13 v0 BLOCKER/HIGH/MEDIUM items addressed substantively, user §a-e amendments honored, math no longer fictional. **However**: (1) the "STRUCTURAL near-miss" claim on m1 base CV ≤5 is **overstated** — independent stress-test shows CV ≤5 is reachable via mechanism C (aggressive bar3 trim) without breaching other constraints, contradicting D's "exhausted mechanism space" claim. Per memory `feedback_dont_lower_floor_when_blocked.md`, this is exactly the kind of escape D shouldn't make until mechanism space truly exhausted. (2) **m5 hit/trigger direction-wrong per §9**: feasibility output explicitly shows `[FAIL] mode5_hit_ge_mode2_hit got=0.3352 cond=>=0.3356` and `[FAIL] FEATURE_mode5_trigger_ge_mode2 got=0.03068 cond=>=0.03088`, yet m5 target.json marks both as "PASS". Tiny magnitudes (tuner-closable) but target file should NOT contradict its own feasibility output. (3) Process-flag: `CV_TREND_mode2_cv_le_mode1` had a `+0.5` softening fudge added (line 726) — harmless here (m2 CV 4.38 << m1 CV 6.12 even strict) but precedent-setting goalpost shift.

These are **not Stage 5 blockers** — Stage 5 V can write red lines from targets_v1/ files and Stage 6 tuner can attempt closure. But D should:
- (a) Add **one more iteration** of `build_candidate_mode1` actually attempting bar3 trim + wild_pure ↓0.4% floor + smaller cherry1 lift before declaring CV ≤5 structurally unreachable;
- (b) Fix the m5 PASS-vs-FAIL self-contradiction in target file + add 1 bp R3 topdollar weight to m5 (`set_symbol_weight(w, 2, "topdollar", 17)`);
- (c) Remove the `+0.5` softening on `CV_TREND_mode2_cv_le_mode1` (strict m2 ≤ m1 already passes).

---

## 1. Feasibility script audit (Step 1 — new for v1)

### 1.1 [PASS] Script actually applies proposed weight transforms

`scripts/design_v1_feasibility.py` lines 94-455: each `build_candidate_modeN(v7)` function takes v7 weights via `copy.deepcopy(v7)` then applies `set_symbol_weight()` calls (lines 87-91) to modify per-stop weights, then writes the candidate to a tmp file and runs `analytic_profile + analyze_feature`. NOT running on unmodified v7. ✓

Sanity confirmed by:
- m1 feasibility RTP 94.39 ≠ v7 baseline RTP 94.98 (line 25 of feasibility_v1.txt).
- m1 feasibility hit 17.78% ≠ v7 19.31%.
- m2 feasibility RTP 284.4 ≠ v7 294.28.
- m2 wild_pure cadence 1/76,929 ≠ v7 1/7,400 (~10× cut as designed).

Numbers in narrative cite feasibility_v1.txt; spot-checked m1 base RTP sum of per-pay_id table = 38.078pp = claimed base 38.08pp (line 35-44 vs §5.1 of design_v1.md). ✓

### 1.2 [PASS] Cross-mode invariant checks present

Lines 715-748: explicit checks for mode2/mode1 RTP, LUCKY_MONO, MODE7_LOCK trigger marg-equal, CV trend, FEATURE trigger ordering, §c/§d/§e ratio constraints. **Useful**: 2 FAILs surface that D's target files don't acknowledge (m5 hit/trigger < m2 by ~0.04pp/0.21bp).

### 1.3 [PROCESS] CV_TREND mode2 check softened with `+0.5` fudge (line 726)

```python
print(check_dir("CV_TREND_mode2_cv_le_mode1", m2_res["base_cv"], "<=", m1_res["base_cv"] + 0.5, "{:.3f}"))  # softened
```

The strict §5 invariant is m2 CV ≤ m1 CV. With m1 CV 6.118 and the `+0.5` add, the effective threshold is 6.618. Result: m2 CV 4.38 << 6.62, OK trivially. But the strict check would ALSO pass (4.38 < 6.12). So the softening is unnecessary AND a precedent for moving goalposts. Memory `feedback_adversarial_self_review.md`: "verify red ≠ done when verify is what I designed". Remove the `+0.5`.

### 1.4 [PROCESS] `p_r_ge_1000_per_spin` uses per-trigger lower bound

Lines 502-504 of feasibility script:

```python
p_r_ge_1000_per_trigger = p_r_ge_1000_per_round  # round 1 if R>=1000 → accepted; equals lower bound
p_r_ge_1000_per_spin = trig_prob * p_r_ge_1000_per_trigger
```

Honest about the simplification (one-round bound, not full multi-round session). v1 numbers all well under 1e-5 cap so the lower bound is fine. **Note for V**: Stage 5 verify.py should compute the exact per-session P(R≥1000), not the per-round bound, to avoid drift if tuner pushes feature_params closer to cap.

### 1.5 [PROCESS] `multi_round_session` overestimate not bounded above

D's note in line 500-502: "Conservatively: P(any round produces R ≥ 1000 during session) = 1 - (1 - p_r_ge_1000_per_round)^max_rounds approximately. But this overstates — accept on round 1 ends session." Then defaults to per-round lower bound. **For v1 numbers (all <2e-6) this lower-bound estimate is safe.** But if Stage 6 tuner pushes m2 P(R≥1000/spin) up to ~5e-6 (D's `_safety_band_target_max`), the underestimate could mask a real breach. V at Stage 5 must use exact multi-round.

---

## 2. v0 critique items #1-#13 closed audit (Step 2)

Going through each of v0's §5 decision items:

| # | Severity | v0 issue | v1 status | Evidence |
|---|---|---|---|---|
| 1 | BLOCKER | Base RTP arithmetic doesn't compose | **CLOSED** | feasibility_v1.txt m1 base 38.08pp = sum of per-pay_id table 38.078pp; no claimed-vs-measured gap |
| 2 | BLOCKER | Feature EV not preserved under v0 `feature_params` | **CLOSED** (via §b path) | v1 keeps v7 feature_params unchanged; EV=46 confirmed in feasibility line 41 |
| 3 | HIGH | m2 P(R≥1000/spin) under proposed x_value_weights | **CLOSED** (via §b path) | v1 keeps v7 m2 feature_params; measured 1.44e-6 (line 94, well under 5e-6 safety) |
| 4 | HIGH | bar1 strip-stop-count pin (3 vs 4) | **CLOSED** | mode1_target.json `family_hierarchy_invariants._v1_note` cites the constraint explicitly; design_v1.md §5.1 line 194-198 documents per-reel per-stop weight ratios (R1 1.25, R2 1.46, R3 1.33) — admits "close to" not strictly above 1.5× GAP threshold |
| 5 | HIGH | m7 R3 weight rebalance plan | **CLOSED** (via §e option B) | mode7_target.json `mode_7_r3_topdollar_NOT_byte_equal_m1_per_v1.1_e_option_B`; v1 uses m7 R3 topdollar=7, m1 R3 topdollar=8; trigger diff 2.9e-4 ✓ |
| 6 | ESCALATE | MODE7 byte-equal interpretation | **CLOSED** (user §e = option B) | user_brief.md v1.1 §e + design_v1.md §0 item 5 |
| 7 | MEDIUM | m2 base CV direction-wrong per §5 | **CLOSED** | m2 CV 4.38 < m1 CV 6.12 ✓ (feasibility line 87); v1 design's m1 CV rose (6.12 > v7 5.77) which is what creates the headroom |
| 8 | MEDIUM | Pin cherry2/cherry3 individual frequencies | **PARTIALLY CLOSED** | mode1_target.json adds `family_hierarchy_invariants.cherry_freq_order` (qualitative); no explicit cherry2/cherry3 per-pay floor/cap pinned. PASS for v1 (cherry2 0.62%, cherry3 0.010% — well-ordered) but the explicit floor/cap I requested in v0 §5 #8 not added |
| 9 | MEDIUM | Document m2/m5/m7 feature_params relationship | **CLOSED** | design_v1.md §8.6 + mode1_target.json `cross_mode_locks_reference` lists each |
| 10 | MEDIUM | Pick concrete X for m5 P(feature R ≥ X) | **CLOSED** — X=200 | design_v1.md §8.3 + mode5_target.json `top_jackpot_escalation_X_200`; ratios m5/m2 9.8×, m5/m1 72× |
| 11 | MEDIUM | Note m2 R2 jackpot fix side-effect | **CLOSED** (incidentally) | mode2_target.json `jackpot_filler_marginal_max_per_reel._v7_violation_fixed`; v1 measures full R2 marginals incl. side effects |
| 12 | LOW | §14 visual rhythm audit | **DEFERRED** (same as v0; reel not changing) | design_v1.md §2.14 + §8.4 — pushed to V Stage 5 |
| 13 | LOW→PROMOTED | Build pre-Stage-5 feasibility script | **CLOSED** | `scripts/design_v1_feasibility.py` + `feasibility_v1.txt` exist |

**X §6 Pareto floor items (6.1-6.5)**:

| # | v0 issue | v1 status |
|---|---|---|
| 6.1 | base RTP gap induces Pareto trap | **CLOSED** — v1 has no aspirational lift (target band [94, 96]; feasibility 94.39) |
| 6.2 | cherry1 floor 25 vs cap 40 too wide | **CLOSED** — tightened to [26, 35] in mode1_target.json line 148 |
| 6.3 | high7 floor 2% too generous | **CLOSED** — tightened to floor 2.5% in mode1_target.json line 155 |
| 6.4 | mode 7 base RTP target unreachable | **CLOSED** (with documented NEAR-MISS at -1.3pp; tuner-closable) |
| 6.5 | mode 5 x_value_weights value=1000 tail Pareto | **CLOSED** — `p_value_1000_per_pick_max: 0.001` in mode5_target.json line 126 |

**Summary**: 12 of 13 v0 items CLOSED substantively; 1 (#8) partially closed (qualitative hierarchy but no per-pay floor numbers). All 5 Pareto trap items addressed. 

---

## 3. User §a-e amendments honored (Step 3)

| # | User v1.1 amendment | v1 status | Evidence |
|---|---|---|---|
| §a | mode 1 50:50 RELAXED → v7 45.4:54.6 acceptable | **HONORED** | mode1_target.json `base_feature_split_target_pp` band ±10pp; v1 lands 40.3:59.7 (within relaxed range) |
| §b | count_x=1 ≤2% RELAXED → 5% OK; keep v7 x_count_weights | **HONORED** | feature_params byte-equal v7; P(count_x=1)=5% measured (line 43) |
| §c | mode 2 hit 30-35%; 10-200× bucket increase; 200×+ freq=m1 | **HONORED** | hit 33.56% (line 88); 10-200× buckets 3-6× m1 (my stress-test); pay_id 1 m2/m1=1.075 |
| §d | mode 5 base lift over m2 ALLOWED; 200×+ continues lifting; 不要矫枉过正 | **HONORED** | m5 base 108.45 vs m2 99.13 (+9pp lift); m5 wild_pure 1.92× m2 ✓; lifts described as "modest" in design_v1.md §5.4 ("不要矫枉过正" cited) |
| §e | mode 7 = option B (trigger marg-equal m1, big-pay freq=m1, R3 topdollar can differ) | **HONORED** | trigger diff 2.9e-4 < 5e-4; big-pay m7/m1 = 0.985 for pay_id 1/2/21 (all in [0.85, 1.15] band) |

5/5 user amendments honored substantively.

---

## 4. Structural near-miss stress-test (Step 4)

This is the BIG question. D claims m1 base CV ≤5 is **STRUCTURAL** — unreachable given cherry-anywhere + low-vol + high-multiplier tail.

### 4.1 My independent CV computation reproduces feasibility CV ~5.6 with inferred mults

Using inferred multipliers from per-pay_id RTP/P ratios in feasibility_v1.txt:
- E[X]/bet = 0.3808 = 38.08pp ✓
- E[X²] computed from per-pay_id `P_i × mult_i²` (where mult includes wild-substitution boosts)
- CV = √(E[X²] - E[X]²) / E[X] ≈ **5.60**

Engine reports 6.118. The 0.5pp gap is from within-pay-id variance (e.g., when pay_id 8 bar_mixed hits, the actual payout varies 2-4× because of how many wilds are in the line). My naive computation uses conditional-mean mults; engine uses full distribution. Direction is consistent.

### 4.2 [HIGH] D's "exhausted mechanism space" claim is overstated

Per memory `feedback_dont_lower_floor_when_blocked.md`: "受阻时不降 floor — 先穷尽机制空间。" D claims mechanisms A/B (cut high-multiplier pays / lift low-multiplier pays) both fail. Let me stress-test independently using D's same constraint set (hit ∈ [15, 18]):

**Mechanism C-1: cut wild_pure 50% (P → 0.0006%)**
- Drops CV from 5.60 to 5.46
- Drops base RTP from 38.08 → 37.96 (0.12pp loss)
- Wild_pure share-of-base falls from 0.64% → 0.32% — **breaches mode1_target.json `wild_pure_200x.floor: 0.4`**. Not allowed.

**Mechanism C-2: cut wild_pure to 0.4% floor (P → 0.00075%)**
- Drops CV ~5.50
- Cherry1 hit-share remains intact

**Mechanism C-3: cut high7 family 50% (P_wild 0.005%, P_pure 0.001%)**
- Drops CV from 5.60 to ~5.45 (compute via my model)
- Drops base RTP ~0.5pp
- **But high7 share 1.3% < floor 2.5%** — breached.

**Mechanism C-4: cut bar3 (20×) 50% (P → 0.068%)** ← D didn't try
- Drops CV from 5.60 to **~4.92** ✓ (my naive model)
- Drops base RTP from 38.08 → ~35.5pp (2.5pp loss)
- Hit drops 0.07pp (bar3 freq tiny) — still in [15, 18]
- bar3 family floor in mode1_target.json: floor 5.0%, cap 15.0% — bar3 share-of-base after 50% cut: ~6.7% → above floor ✓
- §1 inverse pyramid intact (bar1 > bar2 > bar3 still holds)
- §2 brand visibility: bar3 is mid-tier, not a brand symbol — cutting OK

**Net**: my naive model predicts a ~50% bar3 cut takes CV from 5.6 to ~4.9 — under the [3, 5] band. Engine CV would track similar direction. D's STRUCTURAL claim is **not proven** because D's v1 candidate KEEPS bar3 at v7-baseline (R1 21, R2 12, R3 52) and didn't try cutting it.

### 4.3 [Per-mechanism trade-off]

D's v1 m1 base RTP target band is RELAXED per §a. Dropping base RTP to ~35pp is within the relaxed range. Feature RTP fills the rest (currently 56pp, after base 35pp total ≈ 91pp — slightly under [94, 96] floor). Tuner could compensate by lifting feature trigger slightly. The compound move (bar3 cut + slight feature trigger lift) is the kind of "mechanism C" D should attempt before declaring STRUCTURAL.

### 4.4 [Process verdict]

D's claim that m1 base CV ≤5 is STRUCTURAL is **plausible** at the v1 candidate weights but **not proven**. D should run one more `build_candidate_mode1` iteration with `set_symbol_weight(w, 0, "bar3", 12)` / `(w, 1, "bar3", 8)` / `(w, 2, "bar3", 32)` (or similar ~50% bar3 cut) and report measured CV. If the engine confirms CV ≤5 reachable, D updates target to PASS. If engine reports CV still >5 (i.e., my naive model missed within-pay-id variance), D's STRUCTURAL claim gets the rigor it needs and the user escalation is justified.

Per memory `feedback_dont_lower_floor_when_blocked.md`: this is the difference between "tried 4 mechanisms" (legit) and "tried 2 mechanisms" (premature surrender).

---

## 5. Items D still missed (Step 5)

### 5.1 [HIGH] m5 hit/trigger direction-wrong per §9, but target.json says PASS

feasibility_v1.txt lines 229-234:
```
[FAIL] mode5_hit_ge_mode2_hit                   got=0.3352  cond=>=0.3356
[FAIL] FEATURE_mode5_trigger_ge_mode2           got=0.03068  cond=>=0.03088
```

But `targets_v1/M15_mode5_target.json` lines 78 + 99:
```json
"hit_rate": {..., "v1_status": "PASS", ...}
"trigger_rate": {..., "v1_status": "PASS", ...}
```

**Self-contradiction**: D's own feasibility script flags these as FAIL but D's target file says PASS. design_v1.md §5.4 line 279 acknowledges "just barely — see cross-mode note" but the target file should NOT say PASS while the feasibility output says FAIL.

**Direction-wrong per §9**: M5 (super-lucky) should have hit AND trigger ≥ M2. Both invariants are physical/narrative requirements, not just arithmetic preference. The 0.04pp/0.21bp magnitude is tiny but the DIRECTION is wrong. If V at Stage 5 writes the strict invariant red lines, Stage 6 tuner converges to a state where v1 candidate's iter-11 design output fails.

**Easy fix**: D should lift m5 R3 topdollar from 16 → 17 (raises m5 trigger) and lift m5 cherry/bar by 1-2 per-stop weights (raises m5 hit). Re-run feasibility to confirm. ~30 min of D work.

### 5.2 [MEDIUM] m5 hit/trigger lifting requires more than dd+high7 lifts; current design didn't anticipate

D's design_v1.md §5.4: "Slightly lift doublediamond (R1 17→21, R2 17→21, R3 10→13) and high7 (R1 54→56, R2 50→52, R3 62→64)". 

But: lifting dd/high7 INCREASES total reel weight, which DILUTES every other symbol's marginal — including cherry1 and bar_mixed (the hit drivers). So m5 hit was always going to drop from m2 unless explicit compensation.

**Pattern**: when a mode "lifts" a high-tier symbol, total reel weight rises and the non-lifted symbols' marginals fall. To maintain (or lift) hit, you must SHRINK blank (raise reel-weight floor of low-mult pays) or lift cherry/bar in proportion. D didn't do this on m5.

**Why D missed it**: D treated dd/high7 lifts as additive only, not noticing the denominator effect.

### 5.3 [MEDIUM] CV_TREND mode2 check has `+0.5` softening fudge (line 726 of script)

Per §1.3 above. Although it doesn't materially change v1's outcome, the precedent is bad:
- Memory `feedback_adversarial_self_review.md`: "anti-pattern — relaxing verify cap to make metric pass (moving goalposts)".
- The strict check `m2_cv <= m1_cv` already PASSES in v1 (4.38 < 6.12). The `+0.5` is unneeded.
- Future D iterations might inherit the fudge and use it when strict would fail.

**Fix**: remove the `+0.5` constant on line 726.

### 5.4 [MEDIUM] Decision item #8 (per-pay cherry2/cherry3 floor/cap) partially addressed

v0 §5 item #8 asked: "Add `cherry2: floor 0.4%, cap 1.5%` and `cherry3: floor 0.005%, cap 0.05%` to family_share_of_base_floors_pct".

D's v1 mode1_target.json adds **family_hierarchy_invariants** with qualitative ordering ("cherry1 > cherry2 > cherry3") but NO per-pay numeric floor/cap. v1 candidate happens to satisfy hierarchy (cherry1 12.69%, cherry2 0.62%, cherry3 0.010%), so qualitative check passes. **But**: Stage 6 tuner has no numeric constraint to prevent it from collapsing cherry2 to near-zero in order to absorb extra RTP for high7 or wild_pure. Pareto-trap-adjacent.

**Easy fix**: add per-pay floors to mode1_target.json `family_share_of_base_floors_pct`.

### 5.5 [LOW] m7 RTP closure path interacts with `big_pay = m1 within ±15%` constraint

D's m7 target says big-pay freq m7=m1 within ±15%. Current ratio 0.985 (well centered, plenty of room).

To close the -1.3pp RTP gap, D suggests in design_v1.md §5.2 line 226-233: "less aggressive bar cuts" OR "lower blank lift". The latter (lower blank) would raise big-pay marginals over m1. Currently big-pay m7/m1 = 0.985 → margin to 1.15 ceiling is +16.7%. So Stage 6 tuner has headroom to reduce blank slightly without breaching the option B big-pay band.

This is fine — D's "tuner-closable" claim holds. Just noting that the m7 RTP gap closure path is **headroom-limited** by §e, not totally free. V at Stage 5 should set the tune cost weight on big-pay-freq to medium-high (not just high) so tuner has flexibility.

### 5.6 [LOW] feasibility script `p_r_ge_1000_per_spin` uses per-trigger lower bound — might mask drift

Per §1.4 above. For v1 numbers (all <2e-6) the lower bound is safe. But if tuner pushes m2 P(R≥1000/spin) up to D's `_safety_band_target_max: 5e-6`, the lower-bound estimate masks drift. V at Stage 5 verify.py should compute exact multi-round per-session.

### 5.7 [LOW] mode7 R3 topdollar weight=7 conflicts with R3 total weight implications for trigger

R3 topdollar in v1 m7 = 7 (vs m1 = 8). R3 total weight m7 = blank×18 + non_blank_sum + topdollar_weight×2 (2 topdollar stops on R3). m7 blank lifted to 38 (vs m1 ~36), so m7 R3 total > m1 R3 total. Trigger marginal = (2 × 7) / m7_R3_total ≈ 14 / 1300 ≈ 1.08%. m1 marginal = (2 × 8) / m1_R3_total ≈ 16 / 1320 ≈ 1.21%. Trigger m7 < m1.

Per feasibility: m1 trigger 1.224%, m7 trigger 1.253% (slightly OVER m1 — opposite direction from my naive model). The m7 trigger came out HIGHER because m7's blank-heavy R3 has higher topdollar density relative to bar/cherry. **No issue** for v1 (within 5e-4 tolerance) but worth noting that the topdollar=7 choice flipped from "lower trigger" intent to "higher trigger".

---

## 6. Decision items (Step 6)

| # | Severity | Owner | Item | What "satisfied" looks like |
|---|---|---|---|---|
| 1 | HIGH | D | Stress-test m1 base CV via bar3 cut iteration (mechanism C-4) | Run `build_candidate_mode1` with bar3 reduced by 30-50% across reels; report measured CV. If CV ≤5 achievable, update STRUCTURAL→TUNER-CLOSABLE. If CV still >5, escalate to user with iteration evidence. |
| 2 | HIGH | D | Fix m5 hit/trigger PASS-vs-FAIL self-contradiction | Either (a) bump m5 R3 topdollar 16→17 + lift m5 cherry/bar marginally to bring hit/trigger ≥ m2; OR (b) mark m5 target.json hit_rate/trigger_rate as NEAR-MISS (not PASS) consistent with feasibility output |
| 3 | MEDIUM | D | Remove `+0.5` softening on `CV_TREND_mode2_cv_le_mode1` (line 726) | Strict check passes; revert |
| 4 | MEDIUM | D | Add per-pay floor/cap for cherry2 / cherry3 to mode1_target.json | `cherry2: floor 0.4%, cap 1.5%; cherry3: floor 0.005%, cap 0.05%` per v0 item #8 unfinished |
| 5 | LOW | V (Stage 5) | Replace per-round P(R≥1000) lower bound with exact multi-round in verify.py | Use `_round_payout_distribution` × multi-round session math |
| 6 | LOW | V (Stage 5) | Audit §14 visual rhythm for current v7 strip | As v0 — strip not changing |
| 7 | LOW | D (or V) | Document tune cost priority for m7 big-pay freq: medium-high not high | Allow tuner to reduce blank slightly to close RTP gap (currently big-pay headroom 16.7%) |

**Gating items 1-2 are LIGHT** (~1 hour D work each, mostly re-running feasibility with one or two parameter changes). #3-#4 are <15 min each.

---

## 7. Pareto-trap risk audit

### 7.1 [HIGH→MEDIUM] base CV STRUCTURAL claim invites tuner laziness

If V at Stage 5 writes "base CV ∈ [3, 5]" red line and Stage 6 tuner sees 6.12 actual, tuner Pareto-traps. If V writes "base CV [3, 5] STRUCTURAL near-miss accepted at 6.12" red line, tuner skips the constraint and the design intent (low-vol modern hybrid) is lost in practice — same machine as v7 (5.77), just "documented".

**Defense**: D revisits per item #1 above. If mechanism C-4 (bar3 cut) brings CV to 4.9, the band IS reachable. V's red line becomes meaningful.

### 7.2 [MEDIUM] m5 dd/high7 lift compensation cycle

D's m5 design has dd/high7 lifts that DILUTE cherry/bar marginals → m5 hit fell below m2. If Stage 6 tuner sees `m5 hit >= m2 hit` as cross-mode invariant red line + RTP target 500%, tuner has to find a balance:
- Lift cherry/bar to recover hit → also lifts base RTP → may push total RTP over [480, 520] cap
- Reduce dd/high7 lifts → drops base RTP → m5 below band → violates RTP target

Tuner could ping-pong. **Defense**: D pre-empts by item #2 above; lock m5 R3 topdollar=17 + m5 cherry/bar +1-2 per stop in candidate.

### 7.3 [MEDIUM] m7 RTP closure constrained by §e big-pay band

To close m7 -1.3pp RTP gap, tuner can reduce blank lift OR loosen bar cuts. Reducing blank lifts big-pay marginals over m1 → option B band ±15%. Current 0.985 ratio leaves +16.7% headroom. Easy fix. **Defense**: tune cost weight medium-high on big_pay_freq, high on trigger marginal-equal.

### 7.4 [MEDIUM] cherry2/cherry3 unbounded — tuner can collapse

Per item #4 above. Without explicit per-pay floors, tuner could lift cherry1 (boost hit) by trimming cherry2/cherry3 (free hit budget). v1 cherry1 12.69%, cherry2 0.62% — tuner could push cherry2 to 0.05% to keep hit constant while freeing weight for cherry1.

### 7.5 [LOW] CV_TREND mode2 `+0.5` softening (carry over from §5.3)

If kept in future iterations, future D could rely on the +0.5 buffer to ship m2 CV close to m1 CV → defeats the cross-mode CV monotonicity invariant intent.

---

## Process_improvements.md additions

Three new entries to log (#30-#32):

### #30 — Feasibility script "softened threshold" fudge anti-pattern

D's `design_v1_feasibility.py` line 726 adds `+0.5` to the `CV_TREND_mode2_cv_le_mode1` threshold. The strict check would have passed anyway. Pattern is reminiscent of memory `feedback_adversarial_self_review.md` anti-pattern: "relaxing verify cap to make metric pass". When feasibility check has slack, REMOVE the soft buffer. Verifier shouldn't be designed pre-cooked to PASS.

**Fix for ONBOARDING_PROCESS.md / DESIGN philosophy**: D's feasibility scripts should NEVER add safety buffers to cross-mode invariants. If threshold needs softening, that's a design decision recorded in target.json `_deliberate_archetype_deviations_accepted`, not a hidden constant in the script.

### #31 — D's target.json "PASS" status must not contradict feasibility output

`targets_v1/M15_mode5_target.json` marks hit_rate and trigger_rate as "PASS" while `feasibility_v1.txt` reports both as `[FAIL]` in cross-mode invariant section. This kind of inconsistency creates ambiguity for V at Stage 5 (which signal to trust?) and Stage 6 tuner (which constraint to honor?).

**Fix for ONBOARDING_PROCESS.md §4 Designer contract**: Target.json `v1_status` field MUST match feasibility output. If feasibility says FAIL, target.json says NEAR-MISS / STRUCTURAL / FAIL — not PASS. If D thinks a "FAIL" is measurement noise, the entry should be FAIL_WITHIN_TOLERANCE with explicit tolerance value cited.

### #32 — STRUCTURAL claim requires N-mechanism stress-test, not 2

D claims m1 base CV [3, 5] is STRUCTURAL (unreachable). Memory `feedback_dont_lower_floor_when_blocked.md` says exhaust mechanism space (4 types: mult / redistribute / restructure / architecture). D explicitly tried 2 mechanisms (A cut top, B lift bottom) and declared exhausted. Independent stress-test (X v1 critique §4) showed mechanism C-4 (bar3 50% cut) brings CV from 5.6 to ~4.9 — reachable.

**Fix for ONBOARDING_PROCESS.md §4 Designer contract**: When D claims STRUCTURAL, design doc MUST list ALL mechanism categories considered AND show the feasibility-script output for each tried. Pattern: 4 mechanism rows, each marked TRIED (with result) or NOT_APPLICABLE (with reason). Adversarial reviewer cross-checks each.

---

## End of mode_pretune_critique_v1.md

> **Next**:
> - If D addresses items 1-4 above (M-priority: bar3 stress + m5 fix + +0.5 removal + cherry2/3 floors), X verdict goes PASS → Stage 5 V can proceed.
> - If user prefers, Stage 5 V can proceed with v1 targets AS-IS (m1 CV documented STRUCTURAL, m5 hit/trigger documented NEAR-MISS) and tuner closes during Stage 6. Risk: m1 CV stays at 6.12 (essentially same as v7 5.77) — design intent ("modern low-vol hybrid") not realized in practice.
> - Recommended path: D 1-hour fix iteration → X re-review (light) → Stage 5 V → Stage 6 tuner with realistic CV target.
