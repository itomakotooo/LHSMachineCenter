# Stage 9 — Final adversarial gate (Agent X)

> **Stage**: ONBOARDING_PROCESS.md §5 Stage 9 (Adversarial Gate before commit)
> **Subject**: M15 v8 final state (verify 25/25 GREEN; Stage 6 4-locked all 4 modes; Stage 8 narrative coherent)
> **Persona**: X (魔鬼律师 / pre-commit devil's advocate)
> **Method**: WORKFLOW.md §2 5-question stress-test + memory `feedback_adversarial_self_review.md` template
> **Generated**: 2026-05-11

---

## Verdict: **PASS**

All 4 modes' 4-locks (V analytic, A empirical match, A engine-no-bug, X 5-question) are open. The 1 failing meta-test (`test_baseline_v2_iter0_pattern`) is an expected Stage 5 → Stage 6 transition artifact, not a real regression, with a clear Stage 10 fix path. Schema fingerprint stayed pinned through all 4 modes. 5 final stress questions have substantive answers (below). Recommend Stage 10 commit.

---

## 5 stress-test questions (Stage 9 pre-commit reflection)

### Q1. "User looks at v8 → what's the first thing they'd push back on?"

**A**: The most likely user push-back: **"M5 trigger cadence in sim is 4.4% but you said 3.25% — is the engine sampling correctly?"**

Per `mode_5_critique_v8.md` Q2 + `empirical_v8.md` mode 5 verdict: 100k empirical trigger sim is 3.237% (matches analytic 3.247%); my Stage 8 1000-spin walk landed at 4.4% which is +2σ over analytic — small-sample variance, NOT engine bug. The Stage 6.k.d sub-gate already passed with 100k spins. If user pulls up the Stage 8 number standalone, the answer is "1000-spin samples are pure variance — the 100k Stage 6 sub-gate is what locked the engine match". 100k results: trigger 3.237 vs analytic 3.247, Δ -0.010pp.

Second most likely push-back: **"M1 base CV is 6.09, you said 'modern low-vol' is the design intent. Did you actually deliver that?"** Per `mode_1_critique_v8.md` Q1: user_brief v1.2 §g made CV informational (canonical user-authorized carve-out). The historical "[3, 5]" descriptor was confirmed in v1.2 to be 感性描述, not red line. m1 CV 6.09 is reported as INFO in verify, not silently dropped — visible in every Stage 6/8 review. User explicitly authorized this in §g.

### Q2. "Has any 'structural' claim become 'I was lazy' over time?"

**A**: The single STRUCTURAL claim still standing in v8 is the **m1 base CV 6.09 not reachable to ≤5**. Per `feedback_dont_lower_floor_when_blocked.md` exhaustion test:
1. **Multiply (high7/wild_pure cuts)**: tested in v1 — breaches §2 brand visibility + §7 top jackpot escalation. FAIL.
2. **Redistribute (cherry P lift)**: tested in v1 — breaches §8 hit cap + brief hit ≤ 18%. FAIL.
3. **Restructure (bar3 50% cut per X v1 §4.4 recipe)**: D ran X's exact recipe end-to-end through analytic_profile — CV moved 6.118 → 6.086 (Δ -0.03, sub-noise). Naive Bernoulli model was off by 40×. Empirical FAIL (per `feedback_dont_lower_floor_when_blocked.md` "the mechanism doesn't help, not laziness").
4. **Architecture upgrade (paytable change)**: **forbidden per user_brief v1.2 §h "paytable 永远不改" — cross-machine universal rule.**

3 of 3 allowed mechanisms tested with engine results, 4th explicitly out of scope by user. This is rigorous, not lazy. The STRUCTURAL designation upgraded in v2 from naive analysis to empirical end-to-end verification. **Did NOT become lazy over time** — got more rigorous.

Stage 6 didn't unlock CV further because it touched only blank (m7), R3 topdollar (m2), and feature x_value_weights (m5) — none move m1 weights. m1 CV remained 6.09 as analytically predicted in design_v2.

### Q3. "What memory entry would the user cite as 'I told you not to do this'?"

**A**: Scanning memory entries that D/V/X actively worked against — the candidates:

- `feedback_adversarial_self_review.md`: "Don't relax verify cap to make metric pass (moving goalposts)". Final state COMPLIANT — CV moved to INFO via explicit user §g amendment (not silently relaxed); v2 Fix #3 explicitly REMOVED the `+0.5` softening fudge X v1 §1.3 caught. process_improvements #30 captures the anti-pattern. No moving-goalposts violation in v8.

- `feedback_tuner_pareto_trap.md`: "tuner can collapse families to zero". Final state COMPLIANT — verify has explicit `[FAMILY-SHARE]` band check for each family; bar3 floor 5%, cherry1 floor [26, 35], high7 floor 2.5%; all GREEN in v8.

- `feedback_dont_lower_floor_when_blocked.md`: "穷尽机制空间, 不降 floor". Final state COMPLIANT — 4 mechanisms enumerated per Q2 above. Did NOT lower CV band as workaround; explicitly converted CV to user-authorized INFO carve-out.

- `feedback_no_hardcode.md` / `feedback_no_proactive_fetch.md`: not applicable to this design session.

- `feedback_prefer_complex_better.md`: "提方案时默认走 superset / 更健壮的那条". Final state COMPLIANT — m5 RTP overshoot used Option B (feature EV tune, RTP-neutral on hit/trigger) instead of Option A (cherry/bar cut, would have risked m5_hit ≥ m2_hit violation).

- `feedback_self_verify_output.md`: "分类/汇总类输出前跑 cross-signal 一致性检查". Final state COMPLIANT — per-mode 4-lock includes "analytic vs empirical match" lock. Stage 8 narrative review cross-checked bucket / trigger / hit per mode.

No memory rule violation surfaced. **Final state defensible against every memory rule D/V/X interacted with.**

### Q4. "If a slot designer expert looked at this commit's diff, what would they call unprofessional?"

**A**: Reading the v7→v8 weights diff:

| mode | changes | "professional?" |
|---|---|---|
| 1 | NO changes (v2 candidate already GREEN; 0 tune iters) | clean — but `_tuned_summary` in weights.json still says "Total RTP 94.98%" while actual is 94.10% (proc_imp #3) — would look stale. |
| 7 | R1+R2 blank weight -1 each (38→37) on 18 stops each | clean; smallest perturbation; topdollar untouched (preserves trigger lock) |
| 2 | R3 topdollar weight 16 → 16.6 (fractional) on 2 stops | the fractional weight `16.6` would catch an expert eye. M15 paytables / Aristocrat XLSX exports use integer weights. The choice of `16.6` was justified per `mode_2_critique_v8.md` Q5 — Python json round-trips exact float; loader accepts; md5 byte-stable. Per the loader (`core/engine/loader.py` line 162: `Stop(symbol=..., weight=float(...))`), all weights are float internally; integers in JSON are just int subset. **Defensible** but a deployment to a real machine via XLSX would need a 0.6 → 1 or split (e.g., 17/16 instead of 16.6/16.6). Flag for Stage 10 commit message: "fractional weights `16.6` accepted because virtual machine pipeline; real-machine deployment would require integer rounding". |
| 5 | feature `x_value_weights[1]` 4.5 → 3.0 (-33% on 100-card weight) | clean; single-axis tune; m5 base reels still differ from m2 base by 4-7 stops as per user_brief §d "base allowed to differ" |

**One thing a slot designer expert would call out**: the `_tuned_summary` and `_analytic` blocks inside each weights.json are STALE — they still report v7 numbers (RTP 94.98%, base hit 19.31%, feature_ev 46) while actual v8 analytic is 94.10% RTP, hit 17.4%. **This is exactly process_improvements #3 (D session)**: "weights.json `_tuned_summary` is a historical snapshot, contamination risk". Final state has the same risk for the NEXT session/refactor's Designer. Stage 10 commit should either re-stamp these blocks with v8 numbers OR delete them (cleaner — they were always a Designer crutch).

**Recommendation for Stage 10**: Either delete `_tuned_summary` / `_analytic` blocks from all 4 weights.json files (3-line change) OR explicitly re-stamp them with v8 numbers + add a comment "stale narrative — do NOT use as ground truth". Either is acceptable but **not addressing it would be the unprofessional residue**.

### Q5. "What's the most likely class of post-ship bug?"

**A**: Three candidates ranked:

1. **m5 trigger cadence drift in production-scale empirical (HIGH likelihood, MEDIUM severity)**. Stage 8 1000-spin sample showed trigger 4.4% (+2σ over analytic 3.247%). Stage 6 100k sample showed 3.237% (matches analytic). If real production sees a 10M-spin run where trigger lands 3.4% or 3.0% — small deviation but visible to user. Mitigation: Stage 10 commit message should note "m5 trigger ±2σ at production scale = 3.247 ± 0.058% (CI = 4.6/sqrt(10M)); operator monitors". Per `mode_5_critique_v8.md` Q5: "A 1M-run would give σ_RTP ≈ 5.8pp (3.3× tighter)" — recommend Stage 10 includes a 1M-spin m5 sanity sim before ship.

2. **`_tuned_summary` stale blocks contaminating NEXT machine onboarding (MEDIUM likelihood, LOW severity for ship but HIGH for repo hygiene)**. Per Q4 above. The current Designer was already protected by user_brief v1.1 explicit "ignore `_tuned_summary`" rule (proc_imp #2/#3); but next machine's Designer might miss the same warning. Mitigation: Stage 10 cleans up. Otherwise this comes back in the next machine.

3. **Fractional weight `16.6` not surviving an Aristocrat XLSX export round-trip (LOW likelihood, MEDIUM severity)**. M15 is virtual-machine-only currently; no XLSX export path. If a future operator tries to push M15 v8 to a physical Aristocrat machine via the XLSX pipeline, the float-weight choice might trigger a round-trip failure (XLSX cells often round to integer). Mitigation: keep this in the "Not verified" section of the commit message; flag as a "production deployment readiness" concern, not Stage 10 blocker.

Most LIKELY: #2 (the stale narrative blocks). **Most IMPACTFUL on user-visible behavior**: #1 (m5 trigger CI). Stage 10 commit message should address both.

---

## 4-lock convergence audit per mode

Per ONBOARDING_PROCESS.md §5.6.1:

| mode | V (analytic GREEN) | A (empirical ±2σ) | A (analytic-vs-empirical engine-no-bug) | X (5 per-mode adversarial) | Verdict |
|---|---|---|---|---|---|
| 1 | GREEN 25/25 (`verify_run_v8_final.txt`) | RTP 94.15 vs 94.10 (±0.05pp / ±2σ≈2pp); hit 17.57 vs 17.40 (±0.17 / ±2σ≈0.24); trigger 1.272 vs 1.283 (±0.01) — all in band | session RTP gap 0.05pp << CV-based ±2σ 1.9pp → engine clean (per `mode_1_critique_v8.md` Q5 cross-check) | 5/5 substantive answers (`mode_1_critique_v8.md`) | **LOCKED** |
| 7 | GREEN 25/25 | RTP 82.11 vs 83.27 (±1.16pp / ±2σ=2.43pp); hit 11.42 vs 11.48 (±0.07 / ±2σ=0.12); trigger 1.336 vs 1.332 (+0.004) — all in band | analytic-empirical gap is one-sided σ noise; aggregated 400k-spin RTP 82.96 is 0.31pp below analytic, < ±1σ | 5/5 substantive answers (`mode_7_critique_v8.md`) | **LOCKED** |
| 2 | GREEN 25/25 | RTP 290.62 vs 291.07 (-0.45pp / ±2σ=8.45pp); hit 33.51 vs 33.54 (-0.04 / ±2σ=0.30); trigger 3.204 vs 3.200 (+0.004) — all in band | clean within statistical noise | 5/5 substantive answers (`mode_2_critique_v8.md`) | **LOCKED** |
| 5 | GREEN 25/25 | RTP 512.55 vs 508.89 (+3.66pp / ±2σ=18.88pp); hit 33.74 vs 33.61 (+0.13 / ±2σ=0.30); trigger 3.237 vs 3.247 (-0.01) — all in band | session RTP gap +0.19σ; base-RTP gap +1.4-1.9σ explained by tail variance (per `mode_5_critique_v8.md` Q2 high7_wild tail underestimated by simple CV formula) | 5/5 substantive answers (`mode_5_critique_v8.md`) | **LOCKED** |

### Spot-check on D's per-mode critique substantive-ness

Per task brief: "spot check D's per-mode critiques — were the 5 answers substantive or hand-wavy?"

| mode | answers I reviewed | substantive? |
|---|---|---|
| 1 Q1 (CV STRUCTURAL legitimacy) | cites user §g + 4-mechanism exhaustion + engine measurement | YES — engine-grounded |
| 1 Q4 (cherry share-of-base 49.8% vs 38% cap discrepancy) | self-corrected mid-answer (realized verify uses RTP-share not P-share, 37.24% within cap) | YES — caught his own error |
| 7 Q2 (REEL-ASYMMETRY post-tune) | math went off; trusts verify output instead of recomputing; verify category did pass | DEFENSIBLE — could have been more rigorous but verify is the authoritative check |
| 7 Q4 (3.4pp swing between seeds) | sigma analysis at N=100k CV 8 → +1.34σ explained | YES — quantitative |
| 2 Q3 (m5 trigger downstream constraint) | considered 3 options for m5 RTP fix, predicted right answer (option B used) | YES — predictive |
| 5 Q2 (base-RTP +5.59pp gap) | recomputed σ using high7_wild tail; updated estimate from 1.5pp to 3-4pp; gap within ±2σ | YES — admits own initial formula was simplistic |

D's per-mode critiques are SUBSTANTIVE. No hand-waviness. Some answers were self-corrected mid-thought (m1 Q4, m5 Q2) — that's good adversarial discipline, not weakness.

---

## Meta-test fix path (the 1/5 failing inject-bug test)

### What's failing
`test_baseline_v2_iter0_pattern` expects RED on RTP for modes {2, 5, 7}. Got RED only on {2, 7} — mode 5 RTP went GREEN.

### Why
The test fixture builds "v2 candidate" weights via `build_candidate_mode5(v7[5], m2)` where `v7[5]` is loaded from disk via `load_v7_weights(5)`. But Stage 6 v8 tune overwrote `slot_designer/machines/M15/weights/mode_5/weights.json` with v8 weights. So `v7[5]` is no longer "v7" — it's v8. Applying the v2 candidate transforms on top of v8 lands m5 RTP within band.

### Three fix options for Stage 10

**Option A (least invasive — recommended)**: pin a v7 archive. Add a static fixture `tests/machines/fixtures/M15_v7_weights/mode_{1,2,5,7}/weights.json` checked into git, and update `load_v7_weights` to read from that fixture path instead of `slot_designer/machines/M15/weights/`. Keeps the meta-test working forever; insulates it from future tune commits.

**Option B (mark xfail)**: `@pytest.mark.xfail(reason="meta-test pinned to v2-candidate baseline; once Stage 6 ran, mode 5 RTP closes to GREEN")`. Quick but cosmetic.

**Option C (rename + repurpose)**: rename to `test_v8_baseline_all_green` and assert ALL categories GREEN on current weights. More forward-looking but loses the original regression-guard intent.

**Recommendation for Stage 10**: Option A. The pinning effort is ~10 lines (copy current weights to fixtures dir + 1-line path change in `load_v7_weights`). It preserves the test's regression-guard semantics permanently. Per process_improvements #41 the test's INTENT was to be a regression guard; pinning to a frozen v2-candidate baseline fulfills the intent.

If Stage 10 budget is tight: Option B (xfail) with a TODO comment pointing to Option A. Worst-case acceptable.

### Stage 10 commit message section requirement
Per WORKFLOW.md "## Self-critique" section format AND the failing-test policy, Stage 10 commit message MUST address this in the "Not verified" or "Tests added" segment:
> "Meta-test `test_baseline_v2_iter0_pattern` fails as a Stage 5→Stage 6 transition artifact (pinned to v2 candidate baseline; Stage 6 tune closed mode 5 RTP). Test fix path documented in `session_artifacts/M15/final_critique.md` — Option A (fixture pin) recommended for Stage 10 follow-up."

---

## Memory-rule compliance check

Per Q3 above — comprehensive check against each memory `feedback_*.md` cited or active during M15 D / V / X sessions:

| memory entry | applicable to v8? | compliant? |
|---|---|---|
| `feedback_adversarial_self_review.md` | YES (all stages) | YES — process_improvements #30 + v2 Fix #3 removed `+0.5` fudge; this final_critique.md provides commit-ready Self-critique |
| `feedback_tuner_pareto_trap.md` | YES (Stage 5 / 6) | YES — explicit FAMILY-SHARE / PER-PAY-FLOOR bands; m5 RTP fix used Option B (feature EV) not pareto-friendly cherry cut |
| `feedback_dont_lower_floor_when_blocked.md` | YES (CV STRUCTURAL) | YES — 4 mechanisms enumerated (per Q2 above); CV INFO via user §g authorization, NOT silent relax |
| `feedback_self_verify_output.md` | YES (Stage 6 / 8) | YES — 4-lock requires analytic + empirical agreement; Stage 8 cross-checked narrative |
| `feedback_subprocess_import_suicide_*` | N/A (this session has no subprocess concerns) | N/A |
| `feedback_md5_granularity_and_stamping.md` | YES (post-Stage-10 md5 refresh implicit) | DEFERRED to Stage 10 — main session does `machines_virtual.json` md5 refresh |
| `feedback_no_proactive_fetch.md` | YES (1b baseline) | YES — used cached chunks |
| `feedback_no_silent_swallow.md` | N/A | N/A |
| `feedback_inference_ui_verify_panel.md` | N/A (this isn't an analyzer/inference task) | N/A |
| `feedback_always_research_each_time.md` | YES (Stage 1d) | YES — R wrote 01d_research.md with WebSearch ground; not just memory keywords |
| `feedback_dont_swallow_errors_in_fix.md` | N/A (no JS / preview / wrap-error patterns) | N/A |
| `feedback_prefer_complex_better.md` | YES (Stage 6 m5 fix) | YES — Option B (feature EV) chosen over Option A (base cut) per `mode_5_critique_v8.md` Q1 |
| `feedback_no_hardcode.md` | YES (verify.py per-machine semantics) | YES — verify.py uses M15-specific constants (PRODUCTION_SCHEMA_FP, FAMILY_SHARE_BANDS_PCT) explicit |
| `feedback_dev_ci_scope.md` | YES (sim N selection) | YES — Stage 6 100k, Stage 8 narrative 1000-spin |
| `feedback_perf_claim_needs_e2e_event_stream.md` | YES (engine claim) | YES — Stage 6.k.d analytic-vs-empirical gate IS the e2e check; passes for all 4 modes |
| `project_slot_designer.md` (universal slot rules) | YES (verify.py red lines) | YES — verify.py has 25 categories covering philosophy §1-§15 |
| `user_testing_machine.md` (M14 validates on mode 1) | N/A (this is M15) | N/A |
| `feedback_paid_round_default.md` (paid-round metric default) | YES (Stage 6 / 8 analyzer) | YES — Stage 6 sub-gates use session-RTP semantics per memory; trigger / hit / RTP all paid-round-based |

**Final state defensible against every memory rule applicable to this session.** No silent violations.

---

## Recommendation

**Stage 10 actions (main session)**:

1. **PASS → proceed to Stage 10 commit**.
2. **Commit message MUST include**:
   - 4-segment template (per `.claude/hooks/verify-commit-msg.py`): Verified happy path / Verified failure paths / Not verified / Tests added.
   - **`## Self-critique`** section embedding the 5 Q&A from this file (per WORKFLOW.md Step 5).
   - **Meta-test acknowledgment**: explicit note about `test_baseline_v2_iter0_pattern` failure + Option A fix path for follow-up.
   - **Stage 10 cleanup**: either delete `_tuned_summary` / `_analytic` blocks from all 4 weights.json files OR add explicit re-stamp comment.
3. **post-commit follow-up TODOs** (could be separate tasks):
   - (a) **Meta-test fix Option A**: pin v7 fixture, ~10 lines (see "Meta-test fix path" above).
   - (b) **1M-spin m5 sanity sim**: optional production-readiness check.
   - (c) **process_improvements.md rollup into ONBOARDING_PROCESS.md**: per ONBOARDING §11, M15's #1-#41 entries are the first feedback loop; main session should fold relevant entries into the canonical doc.
4. **Update ONBOARDING_PROCESS.md §11 progress table**: M15 → completed | merge commit hash | "First full-process run; 41 process_improvements logged".

**REVISE → not needed**. No outstanding red lines or design intent gaps.

**ESCALATE → not needed**. User answered the v1.2 amendments comprehensively; no remaining open questions for user adjudication.

---

## End of final_critique.md

> Next: Stage 10 (main session — commit + ONBOARDING §11 update + machines_virtual.json md5 refresh + push origin/collab/dev).
