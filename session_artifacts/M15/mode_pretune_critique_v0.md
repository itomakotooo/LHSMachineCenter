# Stage 4 — Pre-tune adversarial review (Agent X)

> Date: 2026-05-11
> Subject: D's `session_artifacts/M15/design_v0.md` + `targets_v0/M15_mode{1,2,5,7}_target.json`
> Reviewer: X (魔鬼律师 / adversarial critic)
> Contract: `slot_designer/ONBOARDING_PROCESS.md` §4 X row + §5 Stage 4 review
> Method: `slot_designer/WORKFLOW.md` §2 + memory `feedback_adversarial_self_review.md`

---

## Verdict

**REVISE** — D's narrative is well-cited and philosophy-honoring at the section level, but the **core mode 1 lever math is internally inconsistent**: D's stated weight moves (cherry / bar cuts + bar1 boost) cause base RTP to DROP ~5pp, yet D claims they will RAISE base RTP +4.35pp. D's `(2,40,40,14,4)` count_x weights also drop EV ~4% (D claims EV preserved). And the bar1/bar2 hierarchy claim collides with strip layout (1bar has 3 stops vs 2bar's 4 stops per reel — fixable but D didn't note the structural pin). Net: D's targets are reasonable; D's **derivation** doesn't compose. Without fixing the chain, Stage 6 tuner gets contradictory cost signals and will Pareto-trap. This is REVISE-level not ESCALATE — D can fix without user input by re-doing the algebra honestly.

---

## 1. Math claims re-derived (Step 1)

### 1.1 [BLOCKER] D's "base RTP 43.15 → 47.5pp" lever chain doesn't compose

D writes (§3.4 of design_v0.md):
> "Combined effect of U#1 cherry cut (lowers base 1.3pp) + bar1/bar2 boost (raises base 5-6pp) → net base up ~4pp."

Then in §5.1 derivation, D's actual proposed moves:
- cherry1 P 13.77% → 12.5% (Δ -1.27pp at 1× = **-1.27pp RTP**)
- bar_mixed P 3.86% → 2.5% (Δ -1.36pp at avg ~2× per pay_id 8 = **-2.72pp RTP**)
- bar1 P 0.25% → 0.50% (Δ +0.25pp at 5× = **+1.25pp RTP**)
- bar2 P 0.58% → 0.42% (Δ -0.16pp at 10× = **-1.6pp RTP**)
- bar3 P 0.11% → 0.08% (Δ -0.03pp at 20× = **-0.6pp RTP**)
- high7_wild P 0.014% → 0.010% (Δ -0.004pp at 30× = **-0.12pp RTP**)
- wild_pure P 0.00166% → 0.00154% (Δ ≈ -0.0001pp at 200× = -0.02pp RTP)

**Sum: -5.08pp base RTP**. D's narrative says +4.35pp (47.5 - 43.15).

**Direction is opposite. Magnitude off by 9.4pp.** D cannot get base RTP 43.15 → 47.5 via "cherry cut + bar1 boost". D would need to either:
- (a) ADD a high-payout lever to grow base (e.g., high7_wild +0.01pp at 30× = +0.3pp, repeat across symbols)
- (b) Drop the 47.5pp target and admit M15's structural base ceiling at lower RTP
- (c) Accept feature share will be higher than 50% if base shrinks (collides with U#3 50:50 ±5pp)

D's "bar1/bar2 boost raises base 5-6pp" sentence is the load-bearing falsehood. bar1 5× × bar2 10× movement of ±0.25pp gives at most ±2.5pp combined, not +5-6pp.

**What would satisfy this**: D re-derives base RTP starting from v7 43.15pp, lists each proposed marginal delta × pay-multiplier, sums to target ±0.5pp. If the chain sums to 38pp not 47.5pp, D revises target (47.5 → e.g. 42-44pp) OR finds new high-payout levers.

### 1.2 [BLOCKER] x_count_weights `(2,40,40,14,4)` drops feature EV ~4%

D writes (§5.1):
> "x_count_weights: `(5,40,40,12,3)` → `(2,40,40,14,4)` (user_brief #4 cap; redistribute to count_x=4/5 to keep EV ~46×)."

E[count_x] check:
- v7: (1·5 + 2·40 + 3·40 + 4·12 + 5·3) / 100 = (5+80+120+48+15)/100 = **2.68**
- D's v0: (1·2 + 2·40 + 3·40 + 4·14 + 5·4) / 100 = (2+80+120+56+20)/100 = **2.78**

E[count_x] rose +3.7%. Feature EV scales roughly linearly with E[count_x] (more cards per round → more value drawn). So EV would rise, not stay flat — but D's `x_value_weights` (§5.1) is also being REDUCED (40.97→25 on the dominant value=5 bin, plus uppershift). Net effect: EV is **not preserved by design**, it's an emergent function of the new joint x_count × x_value distribution which D has not computed. Without that compute, **D's "trigger 1.03% × EV 46 = 47.5pp" arithmetic is circular**: feature RTP is the unknown we're solving for, not a fixed input.

**What would satisfy this**: D runs `analyze_feature(proposed_feature_params)` (the plugin already exposes this — 01b §1 used it) and reports actual EV under proposed x_count_weights + x_value_weights. Then the trigger derivation closes.

### 1.3 [MEDIUM] bar1 boost colliding with strip layout

D claims (§2.1 / §5.1):
> "bar1 P 0.25% → 0.50% (philosophy §1 family hierarchy — bar1 (5×) should be MORE frequent than bar2 (10×); currently inverted)."

Strip stop counts (reel_strips.json `_notes`):
- R1: 1bar=3, 2bar=4, 3bar=4 stops
- R2: 1bar=3, 2bar=4, 3bar=4 stops
- R3: 1bar=3, 2bar=4, 3bar=3 stops

1bar has FEWER STOPS than 2bar across all reels. Marginal density = sum(weights at this symbol) / sum(all weights). For 1bar marginal to EXCEED 2bar marginal across all reels, per-stop 1bar weight must exceed per-stop 2bar weight by ~33% (4/3 ratio compensation) AT MINIMUM, more given the inverse-pyramid GAP requirement (§1 says ≥1.2-1.3× gap).

In v7 mode 1 R3 weights, 2bar stops weight = 41, 3bar stops weight = 43, 1bar stops weight = 22 (low-1bar positions) and 8/8 (lower-1bar positions). The 22/8/8 vs 41 distribution is what gives 2bar 16.62% / 1bar 12.47% on R3 even with 3 vs 4 stops.

**Achievable but non-trivial**: D must lift per-stop 1bar weight by ~50-100% to get 1bar marginal ≥ 1.3× 2bar marginal. **D didn't note the structural pin** — the tuner could easily Pareto out (lift 1bar marginal but at cost of total reel weight inflation that suppresses other families).

**What would satisfy this**: D's design_v0.md §2.1 + §5.1 should explicitly note "1bar has 3 stops vs 2bar's 4 stops per reel; achieving 1bar P > 2bar P requires per-stop 1bar weight ≥ ~1.5× per-stop 2bar weight. Tuner cost function must include hard floor for this." Alternative: D ships strip change (rebalance 1bar=4, 2bar=3) but this changes strip md5 and invalidates rawdata — out of scope per §13 + design intent.

### 1.4 [PASS] Mode 1 hit target 16.5% reaches via the cut levers

D's hit cut chain checks out independent of RTP:
- cherry1 -1.27pp hit, bar_mixed -1.36pp hit, bar2 -0.16pp hit, bar3 -0.03pp hit, plus +0.25pp from bar1 lift = **net -2.57pp hit**
- v7 19.31% − 2.57 = 16.74% ≈ D's target 16.5%. ✓

The hit math composes. Only the RTP and EV math don't.

### 1.5 [PASS] count_x=1 cap math

D says `(5,40,40,12,3)` → `(2,40,40,14,4)` gives P(count_x=1) = 2/100 = 2%. ✓ Hits user_brief #4 cap exactly.

### 1.6 [PASS] Mode 5 feature EV ratio (2.33×) preserves U#5 headroom

v7 m5 P(R≥1000/spin) = 1.28e-7; user_brief cap 1e-5; headroom 78×. D proposes EV 132.81 → 143× (+8%), x_value_weights shift toward big values. Conservative — well within headroom. ✓

### 1.7 [PASS] U#6 jackpot R2 0.74% → ≤0.6% fix scope

D correctly surfaces v7 m2 R2 = 0.743% as U#6 violation (process_improvements #15). The fix is straightforward: cut R2 jackpot weight. m5 inherits via base byte-equal. ✓

### 1.8 [MEDIUM] Mode 2/5 base CV target band collision with base byte-equal lock

D writes m2 base CV target 4.5 [4.0, 5.5], m5 base CV "= m2 (via base byte-equal)". OK structurally.

But: D writes m1 base CV target 4.0 [3.0, 5.0]. Philosophy §5 says higher RTP → lower CV. Base RTP m2 = 150pp vs m1 = 47.5pp. m2 base CV should be < m1 base CV. **D has m2 base CV = 4.5 > m1 base CV = 4.0** — this is direction-wrong per §5.

D handwaves this in §2.5: "m2 base RTP 150pp vs m1 43-47pp means CV math differs". Not a real answer. CV is standardized; higher RTP at same variance → lower CV (CV = σ/μ; μ scales with RTP, σ scales differently). Lucky mode lifting all tiers uniformly should give CV down, not up.

**What would satisfy this**: D either (a) revises m2 base CV target to < m1 target (e.g., m1=4.0, m2=3.5); or (b) explicitly argues why M15's lucky-mode mechanism breaks the §5 expectation (e.g., "lucky mode disproportionately lifts mid/top tier which extends variance more than mean").

---

## 2. Philosophy compliance audit (Step 2)

| § | Topic | D's handling | X verdict |
|---|---|---|---|
| §1 | Family inverse pyramid | bar1 < bar2 violation flagged, fix proposed | **PARTIAL** — fix proposed but doesn't note 3-stop/4-stop strip pin (§1.3 above) |
| §2 | Brand visibility | doublediamond / topdollar / high7 named; floor "≥ v7 measured" | **DEVIATED (justified)** — D defers PWDF redesign per §15.6; cherry visibility floor not stated |
| §3 | Blank cap headroom | "keep ≥5 weight headroom per blank stop" | **HONORED** |
| §4 | Cut mode tier preservation | small cut, mid/top byte-equal; v7 violations (bar1/bar2 in m7 NOT byte-equal m1) flagged | **HONORED** |
| §5 | CV-RTP consistency | m7 CV ≥ m1 ✓; m2 CV ≤ m1 ✗ (D set m2=4.5 > m1=4.0) | **DEVIATED (unjustified — REVISE)** — see §1.8 |
| §6 | Family share vs archetype ±15% | high7 deviation owned (M15-specific); cherry/bar within | **HONORED with owned deviation** |
| §7 | Top-jackpot escalation | base wild_pure byte-equal m2/m5; escalation lives in feature tail | **DEVIATED (justified)** — owned in §4.5/§8.3; documented |
| §8 | Hit ≤70% per pay_id | cherry1 71.3% violation; carve-out to 80% | **DEVIATED (justified)** — owned in §4.7; cherry-anywhere archetype-required |
| §9 | Mode-pair monotonicity | all directions covered; m2/m5/m7 vs m1 OK | **HONORED** |
| §10 | Pareto trap awareness | family share floors ship; tuner cost hint given | **PARTIAL** — see §6 Pareto audit below; floors are present but high7 floor 2% may not bite |
| §11 | "假但不怪" axiom | mode narratives written (§5.1-§5.4); player feel articulated | **HONORED** |
| §12 | Reel asymmetry R1≤R3 blank | m1/m7 lock kept; m2/m5 relaxed per §12.3 lucky carve-out | **HONORED with owned deviation** |
| §13 | Blank-flank diversity | 0 violations measured; D leaves strip alone | **HONORED** |
| §14 | Visual rhythm | "keep current strip ordering" — no per-machine check articulated | **PARTIAL** — D didn't audit whether v7 strip has run-of-3-same-family. 01b §8 only checked §13 not §14. Low-risk but not actively verified |
| §15 | PWDF window visibility | physical reel; defer redistribution; "no PWDF redistribute scheduled in v0" | **HONORED with explicit defer** |

**Bottom line**: One direction-wrong (§5 m2 base CV), one structural-pin missed (§1 bar1 strip), one passive-not-audited (§14). The rest are honored or have owned deviations.

---

## 3. D's open questions — X's takes (Step 3)

### 3.1 D's Q#8.1 — count_x=1 cap direction (low priority)

D's interpretation: user_brief #4 ≤2% means single-card is rare (a "special" event). Alternative: count_x=1 should be COMMON (matching archetype's per-round single-offer).

**X's take**: D's interpretation is correct. The user wrote "≤ 2%" — that's clearly a cap (rare), not a floor (common). The archetype's "per-round single-offer" is a separate concept (each round IS one offer) and is honored by `max_rounds=4` and `accept_threshold=40` — count_x is M15's *added* per-round variance mechanic ("each offer is built from 1-5 cards"), not the per-round count. **D's reading is right; no revisit needed.** D can drop this from open questions.

### 3.2 D's Q#8.2 — m2 feature widening near U#5 cap

D: v7 m2 P(R≥1000/spin) = 2.92e-6; cap 1e-5; headroom only 3.4×. Widening x_value_weights for CV target [1,2] could push over.

**X's take**: D is right to flag this. The proposed m1 x_value_weights shift (40.97 → 25 on dominant bin, 0.0001 → 0.05 on value=1000) lifts P(value=1000 drawn per pick) from 1e-6 to ~5e-4 (500× lift). At m2's higher trigger 2.45% and count_x distribution skewing higher, m2 could land at 1-3e-5 — right at or over cap. D's recommendation of `_safety_band_target_max: 5e-6` for m2 is right, but the **CV target [1,2] may be unreachable inside that safety band**. This is a real engineering tension D hasn't quantified.

**Resolution**: D should compute `P(R≥1000/spin)` under proposed m2 weights via `analyze_feature` BEFORE Stage 6 starts, not discover it via tuner pushing the boundary. If proposed m2 weights yield 1.5e-5, D revises x_value_weights down (and accepts m2 feature CV lands at e.g. 1.2 not 1.5 mid-band).

### 3.3 D's Q#8.3 — Top-jackpot escalation via feature tail

D: m5 vs m2 wild_pure cadence is identical (byte-equal base lock); §7 escalation must live in feature side.

**X's take**: D's reading is **correct AND philosophy gap-filling**. process_improvements #18 already captures this as a feedback-worthy philosophy clarification. The M15 carve-out is appropriate. But D should add a **concrete verifier red line**:

> P(feature R ≥ X per paid spin) escalates m1 < m2 < m5 with ratio m5/m2 ≥ ~2 (mirroring base wild_pure §7 m5/m2 ≥ 2 target).

Without that concrete metric, "escalation lives in feature tail" is unenforceable. D's M15_mode5_target.json names `mode_5_top_jackpot_in_feature_tail` but doesn't pick a threshold X. **Pick X = 200 or 500 explicitly** — that's what makes the verifier red line bite.

### 3.4 D's Q#8.5 — MODE7 byte-equal interpretation (high priority)

D: user_brief says "feature_params 字节级 = mode 1". Reading (a) = `feature_params` block only; reading (b) = block + R3 topdollar weights. D picks (b).

**X's take**: D's reading (b) is **defensible but stronger than the text demands**. Literal reading of "feature_params 字节级 = mode 1": `feature_params` is the JSON block name. R3 topdollar weights live in the `weights` array (not the `feature_params` block). So literal text supports (a) only.

But: the SPIRIT of "mode 7 = mode 1 砍小奖 freq" + "trigger rate equal" implies (b). And `MODE7_LOCK_trigger_equal_to_mode1` in 01b §11 is RED at 0.000454pp — telling us someone designed for trigger equality.

**Recommendation**: This is an ESCALATE-worthy question for user, not a D unilateral decision. Process_improvements #19 already flags. **X says**: ask user "do you want literal byte-equal (b) or marginal-equal-within-tolerance (a)?" before V writes the verify red line. If user says "byte-equal" (b), D's design is right. If "marginal-equal" (a), tolerance 0.001pp would PASS v7 directly and D doesn't need to mass-edit weights.

The cost of (b) is that R3 topdollar stop weights must be IDENTICAL m1↔m7 → cascading effect: total R3 weight per mode is locked → other R3 weights interlocked. Not free.

### 3.5 [X's additional Q] — m2/m5 R2 jackpot fix path

D mentions jackpot R2 fix path in §3.7. The fix lowers R2 jackpot weight from current ~9 (v7 m2 produces 0.743% with R2 total weight ~1212) to ≤7. R2 total weight drops 2 → other R2 marginals lift 0.16% relative. Bar2/cherry/high7 on R2 each lift slightly. **None of D's m2 family marginal targets account for this** — D simply asserts "m2 family marginals will look like v7" but the R2 jackpot cut redistributes 2 units of weight across all other R2 symbols.

**Resolution**: D's m2 target file is silent on this. Verifier should expect ~1-2% relative lift across m2 R2 non-jackpot marginals as a side-effect of fixing U#6. Note in mode_2_target.json.

---

## 4. Items D did NOT think of (Step 4)

This is the highest-value section per WORKFLOW.md §2.5.

### 4.1 [HIGH] Base RTP arithmetic doesn't close (see §1.1)

Already detailed in §1.1 above. D's stated levers produce -5pp base RTP; D claims +4.35pp. Off by 9.4pp wrong direction. This is the single most important finding.

**Why D missed it**: D wrote narrative-first, didn't sum the deltas. D's §3.4 "bar1/bar2 boost raises base 5-6pp" is a flagrant arithmetic error: bar1 0.25→0.50 at 5× is +1.25pp, not +5pp.

### 4.2 [HIGH] Feature EV is not preserved under proposed `feature_params` changes (see §1.2)

D claims trigger 1.03% × EV 46× = 47.4pp ≈ 47.5pp feature RTP. But proposed x_count_weights `(2,40,40,14,4)` raises E[count_x] +3.7%, AND proposed x_value_weights shifts substantially (CV widening). EV is the joint output. D has not computed actual EV under proposed weights. Until D runs `analyze_feature(proposed_params)`, the "trigger × EV = feature RTP" arithmetic is unfounded.

**Why D missed it**: D treated EV as exogenous because v7's `_analytic.ev_per_trigger=46.0` is in weights.json (which D was instructed to ignore — yet implicitly relied on as the EV anchor).

### 4.3 [HIGH] bar1/bar2 hierarchy fix limited by strip stop counts (see §1.3)

1bar has 3 stops per reel; 2bar has 4. Per-stop 1bar weight must be 33%+ higher than per-stop 2bar weight just to achieve marginal equality; ≥50% higher for inverse-pyramid GAP per §1.

**Why D missed it**: D worked in marginal space, not stop-weight space. D's "boost bar1" is hand-wavy without a per-stop weight floor.

### 4.4 [MEDIUM] m2 base CV target direction-wrong per §5 (see §1.8)

D set m2 base CV (4.5) > m1 base CV (4.0). Philosophy §5: higher-RTP modes should have lower CV. Lucky mode lifting all tiers uniformly should compress CV downward.

**Why D missed it**: D set CV targets independently per mode without cross-checking §5 direction.

### 4.5 [MEDIUM] x_value_weights tail at value=1000 lifted 500× could push m2 over U#5

v7 m1 x_value_weights for value=1000 bin: 0.0001 (probability ~1e-6 per pick). D proposes 0.05 (probability ~5e-4 per pick) = **500× lift**. At m2 trigger 2.45% × max_rounds 4 × count_x ≤5 × P(pick=value=1000) ≈ 2.45% × 4 × 5 × 5e-4 = 2.45e-4 = 2.45e-3% per paid spin. v7 m2 P(R≥1000/spin) was 2.92e-6 ≈ 2.92e-4%. **Proposed: ~25e-4% = 25e-6 = 2.5e-5 per paid spin → ABOVE U#5 cap 1e-5**. ❌ MAYBE violates.

D's M15_mode2_target.json has `_safety_band_target_max: 5e-6` but D's m1 x_value_weights proposal would BLOW PAST that at m2 trigger × count scaling.

**Why D missed it**: D considered U#5 only in mode 1 context (low trigger, headroom 480×). At m2 (2.4× trigger) and m5 (2.4× trigger × buffed EV), the same x_value_weights tail compounds. D needs to compute m2 P(R≥1000/spin) under proposed m1-uniform x_value_weights BEFORE committing to those values.

**What would satisfy this**: D ships TWO x_value_weights candidates: m1-uniform AND m2-attenuated-tail (lower weight at value=1000 for m2 vs m1) — and DOC reason. v7 currently uses same x_value_weights across all modes (see weights.json for m2/m5/m7 — not actually byte-equal, m2/m5 have different x_value_weights from m1). Actually let me re-check this claim — see §4.6 below.

### 4.6 [MEDIUM] v7 x_value_weights ARE different per mode — D didn't notice

01b §1 reports v7 feature R range [5×, 4880×] for ALL modes including m1. But m1 v7 EV is 46×, m5 is 132.8× — same max but different mass distribution per mode. v7 already differentiates `feature_params` across modes (m1/m2 different x_value_weights for EV lift).

D's M15_mode7_target.json says "mode_7_feature_params_byte_equal_m1" — this is correct for m7 (cut mode = m1 byte-equal). But for m2/m5 D's design is silent on whether m2 `feature_params` is byte-equal to m1 or differentiated. D's §5.3 says "x_value_weights shift slightly upward... to lift EV 46×→61×" — so m2 IS differentiated. But D's mode2_target.json `lucky_lift_directional_invariants` doesn't say anything about feature_params constraints.

**Why D missed it**: D's narrative is incomplete on the question of "is m2 `feature_params` ≠ m1 by design or by coincidence?" — verifier needs to know this to construct cross-mode invariants.

**What would satisfy this**: D adds explicit clauses: "m2 feature_params block != m1 feature_params block by design (lucky mode EV lift). m7 feature_params byte-equal m1 (cut mode invariant). m5 feature_params != m2 (super-lucky EV lift)."

### 4.7 [MEDIUM] No design intent for m1 cherry2 / cherry3 frequencies

D's §5.1 lever list says "cherry2 and cherry3 frequency unchanged" but doesn't state values. D's family share floor `cherry_family_total: floor 30, cap 50` covers them collectively, but cherry2 / cherry3 individual marginals + §1 ordering (cherry1 P > cherry2 P > cherry3 P) is unverified after cherry1 cut.

v7: cherry1 13.77% > cherry2 0.71% > cherry3 0.011% — pyramid OK. Post-cut: cherry1 12.5% > cherry2 0.71% > cherry3 0.011% — still OK. But if tuner Pareto-traps and lifts cherry2 to absorb missing RTP, the gap closes. D should pin floor and ceiling.

**What would satisfy this**: D adds `cherry2: floor 0.4%, cap 1.5%` and `cherry3: floor 0.005%, cap 0.05%` to family_share_of_base_floors_pct (or in per-pay_id frequency space, more natural for §1 enforcement).

### 4.8 [MEDIUM] Mode 7 R3 topdollar byte-equal m1 implies R3 total weight reshuffling

If R3 topdollar stop weight is fixed = m1 (e.g., 8/8), AND m7 needs R3 trigger 1.03% same as m1, then per-stop topdollar in m7 must equal m1 (both 8/8) AND R3 total weight in m7 must equal m1 (1420). But v7 m7 R3 total = 1242 (not 1420). To make m7 R3 total = 1420, D needs to BOOST some R3 non-topdollar weights in m7 by net +178 over v7. That conflicts with m7's "cut blanks dilute" character (m7 R3 blank 57.97% > m1 54.51%). If R3 blanks LOSE weight in m7 (to keep blank weight headroom), where does the +178 go?

D's design_v0.md §8.5 commits to byte-equal R3 topdollar weights but doesn't compute the cascading R3 reshuffling impact.

**Why D missed it**: D treated "R3 topdollar weights byte-equal" as a localized fix. It's not — R3 total weight is the denominator for every R3 symbol's marginal, so locking one stop weight cascades.

**What would satisfy this**: D shows the R3 weight rebalance plan for m7: which R3 stops gain/lose to keep total = 1420 OR explicitly accepts R3 total m7 ≠ m1 (in which case the trigger marginal still drifts, defeating the purpose).

**Note**: This may actually mean D's reading (b) of byte-equal is structurally impossible without also changing m7 R3 blank distribution. Worth escalating with §3.4 above to user.

### 4.9 [LOW] §14 visual rhythm not audited for v7 baseline

01b §8 confirmed §13 blank-flank diversity (0 violations) but did NOT measure §14 visual rhythm (max consecutive Bar, top-symbol spacing, Cherry distribution). D says "v0: keep current strip ordering" — strip IS being preserved, so §14 v7 state propagates to v0. But if v7 has §14 issues, they propagate too. **No one looked**.

**What would satisfy this**: V/A adds §14 inspection to verify.py with M15-specific thresholds derived from archetype (or accepts "§14 inspected at strip-design time during onboarding, no v0 changes").

### 4.10 [LOW] No empirical sanity check planned before Stage 6 tune starts

D's design_v0.md has 0 instances of running v0-target weights through `analytic_profile()` to sanity-check feasibility. Per WORKFLOW.md Step 2 "dump 实际数字眼过": D should run ONE candidate weights set (e.g., v7 weights × proposed multipliers) through analytic_profile and dump the result BEFORE Stage 6 tune iter 1 begins. If the math math doesn't reach 95% RTP at 16.5% hit AND 50:50 split simultaneously in any candidate, D has discovered Pareto-trap territory before wasting tuner cycles.

**Why D missed it**: D operated 100% in narrative space, never touched a Python tool. Designer agent contract per ONBOARDING_PROCESS.md §4 says "Read / Write" but doesn't prohibit running analytic_profile for sanity. D should have done so.

**What would satisfy this**: D produces a `session_artifacts/M15/scripts/design_v0_feasibility.py` that takes v7 weights, applies proposed marginal deltas (cherry -1.27pp, bar1 +0.25pp, etc.), and dumps resulting RTP / hit / CV. If output is 38pp not 47.5pp, D iterates the design before Stage 5 starts.

---

## 5. Decision items (Step 5)

| # | Severity | Owner | Item | What "satisfied" looks like |
|---|---|---|---|---|
| 1 | BLOCKER | D | Re-derive base RTP arithmetic; current chain produces -5pp not +4.35pp | Each marginal delta × pay-mult summed; ±0.5pp of target; possibly revise target downward |
| 2 | BLOCKER | D | Compute actual EV under proposed `feature_params` via `analyze_feature` | Report EV under (2,40,40,14,4) × new x_value_weights; close the trigger × EV arithmetic |
| 3 | HIGH | D | Compute m2 P(R≥1000/spin) under proposed m1 x_value_weights at m2's higher trigger/count | If output >5e-6, propose m2-attenuated x_value_weights and update mode2_target.json |
| 4 | HIGH | D | Note bar1 strip-stop-count pin (3 stops vs 2bar's 4); per-stop weight ≥1.5× required | Add to §2.1 and §5.1 of design_v0.md; tuner cost function gets explicit per-stop floor |
| 5 | HIGH | D | Show m7 R3 weight rebalance plan if R3 topdollar byte-equal m1 is enforced | Either (a) full R3 weight redistribution showing total=1420 reachable in m7 without §3 blank cap collision; OR (b) escalate Q to user (literal vs marginal byte-equal) |
| 6 | HIGH | user | Adjudicate §3.4 / process_improvements #19: literal byte-equal or marginal-equal for m7 trigger | One-sentence user answer; D updates design + targets accordingly |
| 7 | MEDIUM | D | Fix m2 base CV target direction (§5 says lower-than-m1, D has higher) | Either revise to <4.0 OR write explicit argument for why M15 lucky mechanism inverts §5 |
| 8 | MEDIUM | D | Pin cherry2 / cherry3 individual frequencies; bar1/bar2/bar3 in m7 byte-equal m1 explicit | Add per-pay frequency bands to all target.json files |
| 9 | MEDIUM | D | Document whether m2/m5 feature_params is "byte-equal m1+lift" or "fully differentiated" | One sentence each in mode2 and mode5 target.json `cross_mode_locks_reference` |
| 10 | MEDIUM | D | Pick concrete X for "P(feature R ≥ X) escalates m5 > m2 > m1" | Choose X = 200 or 500; add to mode5_target.json as named verifier metric |
| 11 | MEDIUM | D | Note m2 family R2 marginal lift side-effect when fixing U#6 jackpot R2 | One line in mode2_target.json predicting bar2/cherry/high7 R2 lift ~1-2% relative |
| 12 | LOW | V (Stage 5) | Audit §14 visual rhythm for current v7 strip (max consecutive bar, top-symbol spacing) | Either accept v7 strip is §14-clean OR ship strip changes (breaks rawdata md5; major) |
| 13 | LOW | D | Build pre-Stage-5 feasibility sanity script | `scripts/design_v0_feasibility.py` outputs RTP/hit/CV under v7 weights + proposed deltas |

**Items 1-2 are gating**: without resolving these, the Stage 5 V can't write meaningful red lines (every line cites a target number that's arithmetically unreachable). Items 3-5 are next-priority because they shape mode 2/5/7 target.json content.

**ESCALATE single item**: #6 (literal vs marginal byte-equal interpretation) needs user input; D shouldn't unilaterally pick.

---

## 6. Pareto-trap risk audit

Per WORKFLOW.md §2.5 + memory `feedback_tuner_pareto_trap.md`: where can the tuner "find an easy out" that satisfies numbers but violates design intent?

### 6.1 [HIGH] Base RTP gap induces Pareto trap

If D's design ships as-is with target 47.5pp base, and the lever set only delivers ~38pp, **the tuner has 9pp of unsourced RTP to make up**. Cheapest option: lift bar_mixed back (D's chosen cut) OR lift cherry1 back. Tuner will UNDO D's cuts to chase base RTP target. Result: hit target also lifts back (D's hit cut depended on those cuts). Tuner ping-pongs between RTP and hit; converges to v7-ish. **D's whole design becomes a no-op**.

**Defense**: fix item #1 in §5 above. Re-derive arithmetic until target is reachable WITHOUT undoing D's lever choices.

### 6.2 [MEDIUM] cherry1 floor 25% vs cap 40% — symmetric pull

D's mode1_target.json says `cherry1: floor 25.0, cap 40.0`. v7 actual 31.91%; target post-cut ~30% (cherry1 12.5% × 1.0 / new base 38pp = 32.9% — but if target 47.5pp base reachable, 12.5/47.5 = 26.3%).

**Trap**: If tuner has flexibility in base RTP target (47.5 ±3.5pp band), tuner can land base = 50pp and cherry1 = 12.5/50 = 25% — RIGHT AT FLOOR. Then cherry1 cut from 13.77% to 12.5% gives cherry-share-of-base 25%, exactly at floor, no headroom, ANY tuner perturbation puts cherry1 share <25% violating floor. Iteration ping-pong.

**Defense**: floor 25 → 26 OR target band [25.0, 33.0] not [25.0, 40.0]. Tighter band = less room to Pareto-trap on edges.

### 6.3 [MEDIUM] High7 floor 2% — too generous, won't bite

D's mode1_target.json `high7_total: floor 2.0, cap 8.0`. v7 high7_total = 2.97% (high7_wild 2.76 + high7_pure 0.21). Floor 2% means tuner can cut high7 to 2% AND comply. Player-experience: high7 brand visibility drops by 33% silently.

**Defense**: tighten floor to 2.5% or 3% so v7 actual is "near floor" not "between floor and cap with 50% room to cut".

### 6.4 [MEDIUM] mode 7 base RTP target 37.5pp vs feature 47.5pp — feature share 56% looks fine but cut-mode design intent says feature unchanged

D's m7 base:feature target 44:56 (37.5pp : 47.5pp). v7 m7 39:61 (33.24pp : 51.85pp). v0 shifts toward 44:56. But target 37.5pp base is +4.26pp over v7 33.24pp — same arithmetic concern as m1 (where does the +4pp come from?). At m7 you can't lever cherry/bar UP (that violates "砍小奖" intent). So m7 base RTP also doesn't compose.

**Defense**: Tuner will likely converge to m7 base ≈ 35pp (between v7 and target), feature ~50pp (since byte-equal m1 features pin EV/trigger). Total ~85pp ✓. But the 44:56 split target is aspirational. **Either accept band [40:60, 50:50] for m7 OR re-derive target**.

### 6.5 [LOW] Mode 5 feature EV 143× via x_value_weights upper shift

D's M15_mode5_target.json: x_value_weights shift weight upper toward value=50/100/1000. **Trap**: if tuner chases EV target 143× with cheapest path, it'll spike value=1000 weight (highest EV per probability mass). v7 had value=5/5 with weight 40.97 each — most mass at lowest value. Moving 5pp mass from value=5 to value=1000 quadruples EV. **Result**: tail at value=1000 lifts, P(R≥1000/spin) spikes — could approach U#5 cap.

**Defense**: D's mode5_target.json should add explicit `p_value_1000_per_pick_max` (e.g., ≤1e-3 = 1000× v7's 1e-6 — tail still rare but lifted). Without this, tuner Pareto-traps the easy-EV-path.

---

## Process_improvements.md additions

Three new entries (will be appended in main session after verdict accepted):

### #20 — Designer math chain must close numerically before Stage 5 starts

Designer is allowed Read / Write per §4 contract but should ALSO use `analytic_profile` / `analyze_feature` for sanity-check arithmetic. D session shipped design with base RTP target +4.35pp claimed but proposed levers gave -5pp. WORKFLOW.md Step 2 "dump 实际数字眼过" should apply to Designer too (not only post-tune Verifier). Recommend ONBOARDING_PROCESS.md §4 D row add: "Designer MUST submit a feasibility sanity dump (proposed marginal deltas summed to target) with design_vN.md."

### #21 — bar1 / 1bar hierarchy depends on strip stop count, not just weights

When a symbol has fewer stops than another, marginal-density inverse-pyramid (§1) requires per-stop weight compensation = stop-count-ratio × hierarchy-gap-ratio. M15 1bar=3 stops vs 2bar=4 stops → 1bar per-stop weight ≥ 1.5× 2bar per-stop weight just to clear inverse-pyramid GAP. Designer must derive in per-stop-weight space, not marginal space.

### #22 — Stage 5 Verifier red lines should include feasibility numerator check

Independent of TDD bug-injection check, Stage 5 Verifier should also validate "target is reachable" by re-running Designer's proposed marginal deltas summed against v7 baseline. RED if sum gives wrong-direction. Catches Designer arithmetic errors before tuner wastes cycles.

---

## End of mode_pretune_critique_v0.md

> **Next**: D revises design_v0.md addressing items #1-#11 in §5. After D revision, X re-reviews (mode_pretune_critique_v1.md) → if items 1-5 closed (gating), Stage 4 PASSES → Stage 5 V can begin.
