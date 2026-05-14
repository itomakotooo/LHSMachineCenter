# M43 Stage 2.5 Critic Review — pre-commit gate

**Reviewer**: slot-critic agent  
**Date**: 2026-05-14  
**Artifact under review**: `session_artifacts/M43/02b_stage_2_5_notes.md` + `slot_designer/machines/M43/plugins/feature.py` + `slot_designer/core/engine/rules.py` + `slot_designer/machines/M43/spec.json`

---

## §1 Five Stress-Test Questions

1. Did Implementer write the 01c §3 off-payline doubling correction back into 01c, or is it buried in 02b only?
2. Is `plugin_handled` in core/engine/rules.py the right abstraction, or M43-specific bloat?
3. Is the pay_id 6 40× over-estimation (1% virtual vs 0.08% production) really noise at N=100k?
4. Was pay_id 9 doubling rule verified both directions (wild→4× AND blankup→2× AND blankdown→2×) with numerical breakdown, or one-sided?
5. Is the 0.22pp residual really Monte Carlo noise, or is it the deferred Stage 6 drift (respin under-trigger + mini-game over-trigger) hiding in plain sight?

---

## §2 Answers

---

## Q1 — Correction to 01c §3 off-payline doubling claim: buried in 02b only?

**Cited from**: `session_artifacts/M43/01c_field_analysis.md` §3 line 99-101; `session_artifacts/M43/02b_stage_2_5_notes.md` §1.4

**The concrete conflict**:

01c §3 line 100 states, verbatim:
> "pay_id=6 (`1bar,1bar,1bar`) wins 10,000 base. With one extra wild in the window (e.g. `1bar, blankdown, 1bar` where R2 has a wild on top row), wins 20,000."

02b §4 ("Open Issues Remaining") §3 states, verbatim:
> "`(1bar, blankdown, 1bar)` correctly pays 10× (not 20×), and `(1bar, wild, 1bar)` correctly pays 20× via standard eval."

These are direct numerical contradictions. 01c §3 says `(1bar, blankdown, 1bar)` → 20,000 (doubled). 02b §4.3 says the same pattern → 10,000 (not doubled). Implementer's correction is structurally correct (blankdown is an adjacency marker with multiplier=1 per spec.json; only literal wild has multiplier=2), but the correction exists **only** in 02b §4.3. The original 01c §3 still says the opposite.

**Is the correction written back into 01c?** No. 01c §3 is unchanged. The erroneous "blankdown on payline → win doubled" claim is still the canonical source-of-truth in 01c. Any future agent reading 01c §3 to understand the doubling rule will learn the wrong behavior.

**Additional docstring discrepancy in feature.py**:

`feature.py` module-level docstring (lines 12-21) states:
> "**Off-payline wild doubling** — when a standard payline win fires (bar/7 family pay_ids 2-9 inclusive), any literal `wild` symbol that is on the 3×3 grid but NOT on the mid-row payline doubles the win multiplicatively: win × 2^(off_payline_wild_count)."

This is stated as an implemented mechanic ("Confidence: HIGH"). But `_apply_payline_post_eval` in the same file contains **zero code** for this. `_count_off_payline_wilds` is defined (lines 125-139) but is never called anywhere in `_apply_payline_post_eval` or `simulate_session`. There is no `off_payline_wild_count` variable in the function body. The docstring describes a mechanism that does not exist in the code.

This is a ghost docstring: a future Implementer reading the module docstring will believe off-payline wild doubling is operative, when it is not. The correct interpretation (per 02b §1.4) is that the "off-payline wild doubling" was an over-interpretation — the actual mechanism is on-payline wild.multiplier=2 via standard evaluator. But the module docstring was never corrected.

**VERDICT**: FAIL — FIX BEFORE COMMIT  
Two artifacts contradict each other on the same numerical question, and the module docstring describes unimplemented logic.

**Action**:
1. Add a correction footnote to 01c §3 (not a rewrite — a clearly marked "Stage 2.5 correction" paragraph) stating: "`(1bar, blankdown, 1bar)` pays 10× (not 20×); blankdown has multiplier=1. Only literal wild on payline gives 20× via wild.multiplier=2 in standard eval. See 02b §1.4 for full derivation."
2. Remove the "Off-payline wild doubling" bullet from the feature.py module docstring, or replace it with: "**Off-payline wild — NO additional doubling** — see §1.4 correction: this behavior does not exist. Literal wild on payline is handled by standard evaluator via wild.multiplier=2."
3. Remove or annotate `_count_off_payline_wilds` as dead code (defined but not called).

---

## Q2 — `plugin_handled` core extension: right abstraction or M43-specific bloat?

**Cited from**: `slot_designer/core/engine/rules.py` lines 166-173 + 277-283; `session_artifacts/M43/02b_stage_2_5_notes.md` §1.1

**What was done**: A new kind `"plugin_handled"` was added to `_SUPPORTED_KINDS` in `core/engine/rules.py` with a no-op handler. The explicit motivation: allow a pay_id to appear in spec.json for RTP tracking and reporting without routing through the core evaluator.

**Alternative path (pure plugin, no core touch)**:

Could pay_id 8 have been tracked purely in the plugin without touching core? Yes. Two approaches:

(a) **Spec omission**: Do not declare pay_id 8 in spec.json at all. The plugin fires pay_id 8 via the post-evaluator, writing `PayResult(pay_id=8, ...)` into `outcome.pay`. The reporting layer reads `PayResult.pay_id` — it would see pay_id 8 in the output without any spec declaration. RTP tracking at the aggregator level reads from emitted round data (`PayoutIdToWinAmount`), not from spec entries. No spec entry needed for tracking.

(b) **Spec declaration without core knowledge**: Add pay_id 8 to spec.json with a metadata-only entry and handle the unknown kind silently (e.g., `RuleSet.__init__` could collect unknown kinds into an `_unrecognized` set rather than raising ValueError). This is a slightly weaker form of what was done.

**What the Implementer actually chose**: Option (a) was rejected implicitly (02b §1.2 says the entry exists "for reporting/tracking purposes"), but the case for it is not made. The question of whether the aggregator/analyzer actually reads spec.json `pays` entries to enumerate valid pay_ids (vs reading them from emitted data) is not answered in 02b.

**Is the core touch justified?** Partially. The `plugin_handled` kind is genuinely cross-machine useful (any machine with bespoke evaluator logic hits this problem). The no-op handler is 6 lines of code in rules.py (lines 277-283) and the documentation comment is accurate. It does not pollute evaluator.py. The precedent it sets is well-contained: "if a machine's pay_id logic lives in the plugin, declare it in spec with kind=plugin_handled; core skips it." This is cleaner than silently allowing pay_ids to emit in rounds that have no spec entry.

**Verdict on abstraction quality**: The core touch is a legitimate thin abstraction, not M43-specific bloat, given the pattern will recur on any machine with plugin-side pay logic. However, there is a gap: 02b §1.1 says the entry is needed "for reporting and RTP tracking" but does not cite which tracking system reads spec.json entries. If the aggregator/RTP verifier reads emitted `PayoutIdToWinAmount` (which it does per `memory/reference_round_win_rule_architecture.md`), the spec entry is not strictly needed for tracking — it is needed only to prevent RuleSet from raising ValueError on load. That narrower justification should be documented.

**VERDICT**: PASS-WITH-CAVEAT  
The abstraction is sound and backward-compatible. The core touch is proportionate. The missing piece: the 02b rationale conflates "needed for tracking" (debatable) with "needed to prevent load-time ValueError" (true). This should be clarified in the `rules.py` comment (line 168-173) but is not a commit blocker.

**Action**: Sharpen the inline comment at rules.py line 168 to: "Declared in spec.json so `RuleSet.__init__` does not raise ValueError on load. RTP tracking reads from emitted `PayoutIdToWinAmount`, not from spec entries — this entry is for load-time spec validation, not runtime tracking." Low priority, not a blocker.

---

## Q3 — Pay_id 6 40× over-estimation: noise or structural issue?

**Cited from**: `session_artifacts/M43/02b_stage_2_5_notes.md` §2 pay_id 6 multiplier check table; `session_artifacts/M43/02b_stage_2_5_notes.md` §4 item 4

**Numbers**: Virtual 40× rate ~1% vs production 40× rate 0.08%. This is a factor of **12.5×** over-production. Implementer attributes it to Monte Carlo variance at N=100k vs N=650k.

**Is this actually noise?** No, not primarily.

At N=100k, the production 40× rate of 0.08% corresponds to an expected 80 hits. Virtual shows "~1%", which means ~1,000 hits at N=100k. Monte Carlo standard deviation on a Bernoulli process with p=0.0008 and N=100,000 is sqrt(100,000 × 0.0008 × 0.9992) ≈ 8.9, giving a 3σ interval of roughly 0.062% – 0.098%. A value of 1% is 104σ from the production mean. This is not noise; this is a structural over-estimation of ~12.5×.

**What could cause it**: The 40× pattern for pay_id 6 requires `(1bar, wild, wild)` or `(wild, wild, 1bar)` on the payline — i.e., 2 literal wilds on the payline, giving wild_product = 2×2 = 4, and base pay 10× → 40×. This requires 2 out of 3 payline cells to show literal wild. Given wild appears once per 20-stop strip, the production probability of 2 wilds on a 3-reel payline is roughly (wild_R1 × wild_R2) + (wild_R1 × wild_R3) + (wild_R2 × wild_R3). With R1_wild≈0.157%, R2_wild≈1.852%, R3_wild≈0.187%, the dominant term is R1×R2 + R2×R3 ≈ 0.00291% + 0.00346% ≈ 0.006%. The production 0.08% 40× rate for pay_id 6 includes wild substitutes (blankup/blankdown counted as wilds in line_3_same evaluation), which is consistent. The virtual over-estimation is consistent with one of two causes: (a) reel weight marginals are slightly different in the virtual engine vs production for some cells, making double-wild on payline more likely; or (b) the post-evaluator double-counting — the standard eval fires pay_id 6 at 40× when both non-center payline cells are 1bar and center is wild×wild=4, but the post-evaluator may incorrectly accept an existing pay_id 6 result and not override it when it should be modified.

**The 02b self-review item #2** (Adversarial Self-Review) notes: "The 40× pattern `(wild, wild, 1bar)` or `(1bar, wild, wild)` should not be possible from the strip structure (wild appears at most once per reel in a 20-stop strip)." This is a telling admission: if 2 wild × 1 non-wild on the payline is physically impossible per reel (only 1 wild stop per reel, so at most 1 wild can land per reel per spin), then the standard evaluator's `wild_product` for 2 wilds on a 3-cell payline requires both center and one side to have wild — meaning two different reels each showing their single wild stop simultaneously. This is rare but not impossible. The "should not be possible" phrasing is uncertain, not evidence.

**Sample size needed**: At production rate 0.08%, to achieve ±50% relative precision (enough to confirm structural gap), N = (3/0.0008)² × 0.0008×0.9992 ≈ 9.4M spins. At ±2× relative precision, N ≈ 1.6M. Neither is achievable at Stage 2.5. The 12.5× discrepancy is real structural deviation, not noise. The Stage 6 weight refit will likely shift wild weight marginals and may close this, but it warrants explicit acknowledgment as a known deviation, not "Monte Carlo variance."

**VERDICT**: FAIL — but not a commit blocker if correctly documented  
The Implementer's claim that this is "Monte Carlo variance" is numerically wrong — a 104σ deviation is structural, not statistical. The underlying cause is likely that virtual reel weight marginals generate more double-wild-on-payline events than production. This is a known defect to be addressed at Stage 6 weight refit.

**Action**: In 02b §4 item 4, replace "This is likely due to the wild marginals being slightly different from production at the N=100k scale. At N=650k (production) vs N=100k (virtual), Monte Carlo variance accounts for most of this." with: "Virtual over-estimates 40× rate by ~12.5× (1% vs 0.08%). This is not Monte Carlo noise (104σ from expected). Structural cause: virtual reel weight marginals produce more double-wild-on-payline events than production. Stage 6 weight refit will address this by fitting to production wild marginals. Commit as a known defect, not a closed issue."

---

## Q4 — Pay_id 9 doubling rule: both directions verified, or one-sided?

**Cited from**: `session_artifacts/M43/02b_stage_2_5_notes.md` §2 pay_id 9 doubling check table; feature.py Rule C docstring lines 185-196; 02b §1.3

**The claim**: Implementer says "production data (chunk_0001-0003, 650k spins) shows definitively" that (blank, wild, blank) → 4× ALWAYS and (blank, blankup, blank) → 2× ALWAYS. The 02b self-review §1 says "600+ chunk hits."

**Discrepancy on N**: The Rule C docstring cites "chunk_0001-0003" as source. Three chunks at ~15,400 spins/chunk = approximately 47,000 spins total. That is not "650k spins." The self-review says "600+ chunk hits" (not spins). At 24.7% rate from the §2 verification table, 600+ wild-on-payline hits would require roughly 2,400+ total pay_id 9 events, which across 650k spins at a pay_id 9 rate consistent with the paytable is plausible. But the specific claim "chunk_0001-0003, 650k spins" is a conflation — 3 chunks is not 650k spins.

**Is blankdown verified separately?** The 02b §2 table groups the 2× cases as "blankup/blankdown on payline" together as a single row (74.1% vs 75.3%). This means: blankup→2× AND blankdown→2× are treated as the same bucket. They are strip-equivalent (both are adjacency markers, flanking wild on the physical strip), so physically there is no reason for them to differ. But the claim "ALWAYS" in the feature.py docstring is not backed by a per-symbol breakdown that distinguishes blankup hits from blankdown hits in the 2× bucket.

**More critically**: The feature.py docstring (lines 190-192) states:
> "4× pay_id 9: ALWAYS has literal wild on payline  
> 2× pay_id 9: ALWAYS has blankup/blankdown (no literal wild) on payline"

The test `test_pay_id_9_doubles_when_literal_wild_on_payline` (lines 413-444) tests wild→4× (Case 1) and blankup→2× (Case 2). There is **no test for blankdown→2×**. The test file covers 2 of 3 relevant symbol types on the payline for pay_id 9.

**Is a 3-state rule possible?** Structurally: blankdown is at the same strip position as blankup relative to wild (blankdown above wild, blankup below wild per the reconstructed strip in 01c §1). There is no physical reason for them to pay differently, and 01c §1 confirms they have identical strip semantics. However, the test omission means the "ALWAYS" claim is not machine-verified for the blankdown case.

**VERDICT**: PASS-WITH-CAVEAT  
The structural argument that blankdown and blankup are equivalent is sound. The empirical claim of "650k spins confirms ALWAYS" is slightly inflated (the docstring source says chunk_0001-0003, not 650k). The missing test for blankdown→2× is a test-coverage gap.

**Action**: Add a single test case: `blankdown on payline → pay_id 9 stays at 2×`. Replace the docstring source "chunk_0001-0003, 650k spins" with the accurate "chunk_0001-0003 (~47k spins); blankup/blankdown treated as equivalent adjacency markers per 01c §1 strip structure."

---

## Q5 — 0.22pp residual: noise or deferred Stage 6 drift?

**Cited from**: `session_artifacts/M43/02b_stage_2_5_notes.md` §2 RTP convergence table; §4 items 1 and 2

**Numbers from 02b §4**:

| deferred component | direction | estimated RTP contribution |
|---|---|---|
| Mini-game trigger: virtual 1.32% vs prod 1.18% | OVER (virtual fires more) | ~0.1pp overshoot |
| Respin trigger: virtual 0.94% vs prod 1.37% | UNDER (virtual fires less) | ~0.1-0.2pp undershoot |

Net of these two deferred items: (−0.1pp from mini-game overshoot) + (+0.1 to +0.2pp from respin undershoot) = net 0 to +0.1pp additional RTP when corrected at Stage 6. Direction: correcting both would make virtual RTP move slightly UP (respin correction adds more than mini-game correction removes).

**What is the current gap?** 93.01% virtual vs 93.23% production = −0.22pp. If Stage 6 corrections push virtual RTP up by 0.0–0.1pp (respin dominant), the corrected engine would sit at 93.01 to 93.11% — still ~0.12–0.22pp below production. That remaining gap after Stage 6 corrections (if any) would be unexplained.

**Is 0.22pp genuinely within Monte Carlo noise at N=100k?** Implementer claims std ~0.3-0.5pp. For a binomial-equivalent RTP process with σ_per_spin estimated from production variance, the standard error of the mean RTP over N=100k spins depends on the per-spin win variance. For a machine where most spins produce no win and occasional high wins occur, σ_per_spin is dominated by rare large wins. At N=100k, √(Var/N) ≈ 0.3-0.5pp is plausible for this paytable structure. So 0.22pp is within 1σ, not alarming as a standalone number.

**The structural concern**: The question is not whether 0.22pp is within noise — it is whether Stage 3.5 feasibility pre-check will use this engine and make contract decisions based on an engine that may be systematically low by 0.12–0.22pp after Stage 6 corrections. If Stage 3.5 uses 93.01% as the engine baseline and targets 95%, the 1.99pp gap looks achievable. If Stage 6 corrections bring the engine to 93.2%, only a 1.8pp gap remains. This is a modest difference, but the direction matters: the engine is **not** systematically overestimating RTP; it is underestimating (or correctly estimating within noise). A feasibility pre-check at Stage 3.5 that uses an under-estimating engine gives conservative feasibility estimates — the bias is in the safe direction. The risk of false infeasibility (declaring a target infeasible when it is actually achievable) is real but small here.

**However**: 02b §4 item 2 explicitly states "After Stage 6 refit, virtual RTP may increase by ~0.1-0.2pp from respin correction." If the respin correction materializes at +0.2pp and mini-game correction at −0.1pp, the net Stage 6 shift is +0.1pp, giving 93.11% — a 0.12pp gap vs production. That remaining 0.12pp is then unexplained by any identified mechanism. At Stage 3.5, the right disclosure is: "engine is 0.22pp below production, of which ~0.1pp is identifiable deferred correction; the remaining ~0.12pp is unaccounted and may resolve at Stage 6 or may indicate a missing mechanism."

**VERDICT**: PASS-WITH-CAVEAT  
The 0.22pp is within 1σ Monte Carlo noise and is therefore defensible as a Stage 2.5 close-out. However, labeling it "within Monte Carlo noise" without disclosing that the deferred corrections are in the UP direction (meaning the gap will likely narrow further at Stage 6) understates Stage 3.5's position. Stage 3.5 should know it is working with a conservatively-biased engine (slightly low), not that the engine is exact.

**Action**: Add a sentence to 02b §2 RTP convergence: "Deferred Stage 6 corrections (respin trigger underfit +0.1–0.2pp; mini-game overfit −0.1pp) are net in the upward direction, meaning the true engine RTP after Stage 6 is expected to be 93.01% + 0.0 to 0.1pp = 93.01–93.11%. Stage 3.5 feasibility pre-check should treat the engine as conservatively biased (under-estimates production by 0–0.22pp)."

---

## §3 Overall Verdict

**HOLD — fix Q1 before commit.**

| question | verdict | blocker? |
|---|---|---|
| Q1 — 01c §3 correction buried + ghost docstring in feature.py | **FAIL — FIX BEFORE COMMIT** | YES |
| Q2 — `plugin_handled` core extension | **PASS-WITH-CAVEAT** | No |
| Q3 — pay_id 6 40× over-estimation is not noise | **FAIL — document as known defect** | No (commit with corrected language) |
| Q4 — blankdown case missing from tests | **PASS-WITH-CAVEAT** | No (add test, not blocking) |
| Q5 — 0.22pp residual interpretation | **PASS-WITH-CAVEAT** | No (add disclosure sentence) |

**Hard blocker (Q1)**:

The module docstring in `feature.py` states "Off-payline wild doubling — win × 2^(off_payline_wild_count)" as an implemented mechanic. The code does not implement it — `_count_off_payline_wilds` is never called. A future Implementer or Verifier reading this docstring will model the wrong engine behavior. Additionally, `01c_field_analysis.md` §3 still asserts `(1bar, blankdown, 1bar)` → 20,000, which is the opposite of what the engine implements. These two artifacts together are a live trap for the Stage 4 Designer and Stage 5 Verifier.

**Non-blocking items (Q2, Q3, Q4, Q5)**:

The `plugin_handled` abstraction is sound. The 40× over-estimation should be relabeled as a known structural defect rather than noise, but does not block commit if labeled correctly. The missing blankdown test is a coverage gap. The 0.22pp disclosure should be more explicit but does not change feasibility outcomes.

**Required before commit**:
1. Correct or annotate `feature.py` module docstring to remove the "Off-payline wild doubling — implemented" claim, or clearly mark it as "NOT IMPLEMENTED — original hypothesis disproved; see 02b §1.4."
2. Remove or annotate `_count_off_payline_wilds` as dead code (it is defined on line 125 and never called).
3. Add a correction paragraph to `session_artifacts/M43/01c_field_analysis.md` §3 win-doubling section noting the Stage 2.5 empirical finding.

**Recommended before commit (non-blocking)**:
4. Relabel 02b §4 item 4 from "Monte Carlo variance" to "known structural over-estimation, ~12.5×."
5. Add blankdown test case to `tests/machines/test_M43_engine.py`.
6. Add Stage 6 conservative-bias disclosure sentence to 02b §2 RTP convergence.

---

## Summary

- 5/5 closed-loop with non-empty answers: YES
- Top concern for next stage: `feature.py` module docstring claims "Off-payline wild doubling" is implemented — it is not. `_count_off_payline_wilds` is dead code. This contradicts 02b §1.4, which correctly says the mechanism does not exist. Fix docstring + dead-code annotation before commit. Simultaneously, 01c §3 still says `(1bar, blankdown, 1bar)` → 20,000; engine implements 10,000. Both of these will mislead Stage 4 Designer and Stage 5 Verifier.
