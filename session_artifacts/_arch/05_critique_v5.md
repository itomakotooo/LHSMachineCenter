# Adversarial Critique v5 — Wave 2 Architecture Proposal v5

> Wave 3 v5 / arch-critic. Hostile review of `04_architecture_proposal_v5.md`
> (1402 lines, focused 7-issue revision of v4).
>
> Mandate: verify whether the 4 Concerns (A/B/C/D) from Critic v4 and the
> 3 documentation gaps (§3.1/§3.2/§3.3) from Validator v4 are ACTUALLY
> addressed in v5 — not just claimed. 10+ stress questions, migration risk
> inventory, edge cases, hidden assumptions, alternatives double-check,
> final verdict.
>
> Date: 2026-05-17
> Inputs: `00_brief_v5_addendum.md` (v5 contract / 4 substantive + 3 polish),
> `05_critique_v4.md` (Critic v4 source), `06_validation_v4.md` (Validator v4
> 3 doc gaps), `04_architecture_proposal_v4.md` (1243-line baseline),
> `04_architecture_proposal_v5.md` (THE TARGET, 1402 lines).
> Wave 1: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`.

---

## §1 Top concerns

### Concern I — Addendum v5 §1 Issue ① mislabels M14 and M139 as trigger-session machines, but v5 §6.3.1 correctly places them in SC-Vanilla. Internal contradiction between addendum and proposal.

The addendum v5 §1 Issue ① states: "For machines with `trigger_session_pattern != null` (M14/M15/M120/M139/M279 + many BCM), these legitimately differ." This is the designer's own input brief. However, `02_taxonomy.md §4.2` explicitly places M14 and M139 in the SC-Vanilla cluster (ST-1A, plain machines, no bonus ST). v5 §6.3.1 correctly places M14 and M139 in Group A (Day-1 strict candidates, `trigger_session_pattern: null`). v5 §2.1 also lists "M14/M15/M120/M139/M279 etc." in the Skip approach consequence sentence.

The contradiction does not damage the proposal mechanically — the manifest examples for M15 (trigger) and the SC-Vanilla examples for M1/M14 are internally consistent, and M14 is correctly marked `trigger_session_pattern: null`. But the addendum's incorrect citation of M14 and M139 as trigger-session machines means Critic v5 cannot simply verify "all listed trigger-session machines get `layer4_applicable: false`" against the addendum list, because the list is wrong. The designer has addressed the right problem but with an incorrect machine list in the problem statement.

The operational risk is low — the proposal itself is consistent. The documentation risk is that future readers of the addendum chain see M14/M139 listed as trigger-session machines, which contradicts their SC-Vanilla classification and could lead an implementer to incorrectly set `trigger_session_pattern` or `layer4_applicable: false` for those machines.

### Concern II — `layer4_applicable` per-mode resolution is claimed but not specified

v5 §5.5.6 states: "`layer4_applicable` (does NOT support `per_mode_overrides`) — per-mode variation is handled via `trigger_session_pattern_override` which, when non-null in any mode, drives the per-mode `layer4_applicable` resolution." This "drives the per-mode `layer4_applicable` resolution" is an algorithmic claim — a resolution function that must exist in `manifest_loader.py`. No pseudocode is provided. For a machine that has `trigger_session_pattern: null` at the top level but `trigger_session_pattern_override: "type_1"` in per_mode_overrides for, say, mode 5, the resolution must determine that mode 5 has `layer4_applicable: false` while modes 1, 2, 7 have `layer4_applicable: true`.

This is plausible as a machine exists with mode-dependent session patterns (per `02_taxonomy.md`, several machines use selector types that vary by mode). But the resolution function's contract is undefined. The statement "when non-null in any mode, drives the per-mode `layer4_applicable` resolution" is ambiguous: does it mean "if non-null in mode N, that specific mode gets `layer4_applicable: false`" (per-mode granularity) or "if non-null in any mode, the whole machine gets `layer4_applicable: false`" (machine-level blunt override)? Both readings are possible from the text. The former is more correct but requires the manifest loader to compute `effective_layer4_applicable(M, mode)` separately per mode. The latter would unnecessarily disable Layer 4 for all modes of a multi-mode machine where only one mode has trigger sessions.

Per `03_coupling_audit.md §4.1`, the manifest loader is a Phase 3 deliverable (item 2 in §6.3.3). If the resolution contract is ambiguous, Phase 3 implementers may choose either interpretation, leading to correctness divergence from the architect's intent.

### Concern III — Day-2 candidates lack a return path specification

v5 §6.3.3 item 0 specifies that failed Day-1 candidates become "Day-2 pending QA." The consequences are: set `console_diagnostic_complete: false`, add to "Day-2 pending QA" subsection in the Phase 3 commit description, note which layer failed. But after this point, the spec is silent. Day-2 candidates have no defined:

1. Re-entry path back to Day-1 consideration. The general flip criteria in §6.3.2 apply, but there is no explicit "a Day-2 candidate follows the same path as any machine graduating from `false` to `true`" statement.
2. Time-to-resolution expectation. Unlike the quarterly cadence for override review, there is no minimum or maximum time a machine can sit in "Day-2 pending QA."
3. Tracking mechanism. The Phase 3 commit description is a one-time artifact. If the failed candidate needs active investigation, there is no spec-backed issue tracker or re-verification ticket requirement.

This is the same organizational-footgun risk as the pre-v5 override mechanism: a machine lands in "Day-2 pending QA" in a commit message, the investigation is deprioritized, and months later no one remembers the machine exists in a degraded state. The override's quarterly QA review was added precisely to prevent this pattern for variants; Day-2 candidates have no analogous cadence.

### Concern IV — Lint rule warning has no action threshold and never becomes a blocker

v5 §5.5.7 adds a lint rule that runs in CI on every PR touching manifests. It emits a WARNING (not an error) when a variant override is stale. The spec explicitly states "It does NOT block merges." The quarterly QA review is the "enforcement mechanism." This means:

- Repeated CI warnings accumulate without resolution. A PR author can see the warning and proceed to merge regardless.
- There is no escalation path: if the quarterly QA review is missed (§7.2 acknowledges ownership is unspecified), warnings accumulate indefinitely with zero enforcement.
- Per memory `feedback_no_silent_swallow.md`, outcomes of best-effort hooks must be persisted; but a warning that never becomes an error can be treated as noise by the team.

The warning-only policy is consistent with the conservative direction (never auto-clear), but the gap between "warning exists" and "warning is acted upon" is bridged entirely by an unowned quarterly process (§7.2 explicitly: "organizational assignment is out of this proposal's scope"). The lint rule is therefore a reminder with no teeth, relying entirely on an organizational process that the spec does not actually own.

---

## §2 Verification: are the 4 Concerns (A/B/C/D) from Critic v4 actually addressed?

### Concern A — Layer 4 trigger-session false-positive structural fix

**Critic v4 finding**: v4's Step B does naive rawdata scan; `compute_trigger_sessions` re-attribution means `analyzer_dispatch[pid][st]` systematically differs from `fresh_dispatch[pid][st]` for machines with `trigger_session_pattern != null`. Layer 4 fires false-positives on every fleet pull for ~17+ machines.

**v5 response (§9.4)**: Skip approach. Machines with `trigger_session_pattern != null` get `layer4_applicable: false` in manifest. Applicability gate fires before Step A. Manifest validation rule 11 enforces consistency. Trade-off documented: trigger-session machines lose Layer 4 protection entirely.

**Verdict: RESOLVED**. The false-positive class is eliminated structurally. The Skip approach's trade-off (Layer 4 never runs for trigger-session machines) is a design choice the addendum explicitly authorized (approach b). Manifest validation rule 11 prevents the inconsistent state (`trigger_session_pattern != null` AND `layer4_applicable: true`). The motivating false-positive scenario — M15 triggering on every fleet pull — no longer fires.

One residual question: v5 §5.5.6 claims that `trigger_session_pattern_override` in `per_mode_overrides` "drives the per-mode `layer4_applicable` resolution," but the resolution algorithm is not specified (Concern II above). This is a spec gap in the fix, not a re-emergence of the original false-positive, because machines with blanket `trigger_session_pattern: null` at top level and no mode overrides (the majority case) are unaffected.

### Concern B — 46 Day-1 candidates unverified; pre-Phase-3 verification not gated

**Critic v4 finding (Q6/E6)**: v4 §6.3.1 described the verification step in prose but not in the Phase 3 deliverable list. Implementers following the deliverable list could skip the step and set ~46 machines to `true` based on expectation alone.

**v5 response (§6.3.3)**: Item 0 added as "GATE — must complete before proceeding to items 1-9." Per-machine pass/fail recorded in Phase 3 kickoff commit message. Failed candidates become "Day-2 pending QA." Estimated cost ~10 min.

**Verdict: RESOLVED**. The gate is now a numbered deliverable item, not prose. "Must complete before proceeding to items 1-9" is a clear gating signal. The recording requirement (commit message with per-machine pass/fail) creates accountability. Residual gap: Day-2 candidates lack a return path (Concern III above) — but this is a new gap introduced by v5's attempt to fix Concern B, not a re-emergence of the original procedural omission.

### Concern C — Override re-enablement path unspecified

**Critic v4 finding (Q7)**: v4 §5.5.7 specified how to ADD `override: false` (with `_comment` required) but not how to REMOVE it. A variant could sit at `override: false` indefinitely after the underlying's issue was fixed. No reminder mechanism, no validation warning for stale overrides.

**v5 response (§5.5.7)**: Three additions: (1) override metadata (`override_set_at`, `override_set_reason`, `override_set_by`) required when override is set; (2) override-clearing procedure specified (run `rtp_integrity.py` against variant rawdata, remove metadata fields, commit with audit log); (3) quarterly QA review process; (4) stale-override lint rule in `manifest_lint.py` with CI warning.

**Verdict: RESOLVED with residual (Concern IV)**. The re-enablement lifecycle is now fully specified. The clearing procedure has concrete steps. The quarterly QA review provides a cadence. The lint rule provides a CI signal. The residual in Concern IV (lint warning has no enforcement mechanism and quarterly QA ownership is unassigned) is a soft operational gap, not a re-emergence of the original unspecified path.

### Concern D — Fleet-wide ~35 min Layer 4 penalty unspecified

**Critic v4 finding (Q4)**: v4 §7.4 (later §7.1) deferred the fleet pull performance question to the Critic. Estimate of ~5s per machine was unvalidated; 421-machine sequential total of ~35 min was unspecified.

**v5 response (§9.4 perf note)**: Per machine ~3s for 414k spins on warm disk. Reasoning: Step B's loop is ~20 lines of direct Python (no rule resolution, no trigger-session computation) vs 1,607+ lines of `parse_chunk_response`. Revised full fleet sequential total: 421 × ~3s = ~21 min. Trigger-session machines (`layer4_applicable: false`) add 0s. Wall-clock under parallelism is dominated by the slowest machine's Step B. Measurement during implementation recommended; `--skip-layer4-rawdata-scan` escape hatch if any Day-1 candidate exceeds 10s.

**Verdict: RESOLVED**. A concrete estimate with stated basis is provided. The estimate acknowledges linear scaling for large-rawdata machines (1M spins ≈ 7-8s; 3M spins ≈ 22s). The implementation measurement recommendation is appropriate. The ~35 min estimate from v4 is revised downward due to: (a) per-machine is ~3s not ~5s; (b) trigger-session machines (material fraction) add 0s. The residual parallelism claim ("wall-clock is dominated by slowest machine") is an assumption about the fleet pull concurrency model — it is plausible per `01_pipeline_map.md §3` (per-machine subprocesses) but not verified. This is acceptable for a design proposal.

### Polish gap §3.1 — RoundWinRules MUST NOT write to `payout_id_by_spin_type_total`

**v5 response (§9.4)**: Explicit 2-line constraint before Step A pseudocode, with reasoning (would cause Step A to capture synthetic pids not in rawdata) and empirical verification (M274's `_bcm_cycle` has `spin_type_breakdown = []` per Validator v4 §2.6.4).

**Verdict: RESOLVED**. Constraint is explicit, reasoned, and empirically verified.

### Polish gap §3.2 — Variant override removal procedure

**v5 response (§5.5.7)**: 3-step procedure with commit message template. Same §6.3.2 flip criteria apply to the variant.

**Verdict: RESOLVED**. Procedure is concrete and auditable.

### Polish gap §3.3 — `_unattributed_*` Step C note

**v5 response (§9.4 Step C)**: `is_fallback_pid` field in inconsistency dict; note text "[FALLBACK PID] This mismatch corroborates Layer 2's fallback-bucket detection." Implementers MUST NOT suppress.

**Verdict: RESOLVED**. Note is in the pseudocode itself, not in prose that implementers might skip.

---

## §3 Ten stress questions

### Q1: Layer 4 Skip approach — is it an over-broad surrender? ~17+ trigger-session machines plus BCM variants lose Layer 4 entirely.

**Question**: The addendum v5 authorized approach (b) but also said the designer should "document trade-off explicitly." v5 documents it at §9.4 and §2.1. But is the scope of the surrender accurately characterized? Per `02_taxonomy.md §4.2`, the SC-WheelSelector cluster alone has ~96 rows (M273 + 85 variants + 11 other underlying machines and variants). SC-TopDollar has 17 rows (Type 1 trigger). `plugin-common-selector-type2` covers M201, M209, M257 + variants = ~20 rows. That is potentially 130+ manifest rows that permanently lack Layer 4, not just "~17 documented trigger-session machines." The addendum v5 §1 says "~17 documented trigger-session machines, plus many BCM machines that use trigger semantics."

**Designer's likely answer**: The "~17 documented trigger-session machines" figure refers to underlying machines (not variants). Variants share the underlying's manifest; Layer 4 applicability is inherited. The 85 M273 variants all inherit `layer4_applicable: false` from M273 — they are one decision, not 85 separate ones. The "130+ rows" framing overstates because variant rows are not independent Layer 4 decisions.

**Why partially insufficient**: Even limiting to underlying machines: SC-TopDollar has 5 underlying machines (M12, M15, M90, M132, M206) + WheelSelector has ~11 underlying machines (M102, M187, M188, M198, M203, M204, M216, M219, M247, M261, M273) + CommonSelector-type2 has M201, M209, M257 = 19+ underlying trigger-session machines, not 17. The "~17" figure in the addendum is an undercount per Wave 1 evidence. More importantly, the addendum itself was the specification target; v5 defers the count to addendum-as-given rather than verifying it against `02_taxonomy.md`. For a fleet-coverage argument ("Layer 4 covers the majority"), the ~19+ vs ~17 distinction is material if the fleet is 421 machines: 19/421 = 4.5% without Layer 4 by underlying machine count; but by manifest row count the figure is higher.

**Verdict: ⚠ partial** — trade-off is documented and the Skip approach is structurally correct. The fleet fraction without Layer 4 coverage may be slightly larger than characterized. For the purposes of this review, the approach is sound; the exact count is an implementation-time concern.

---

### Q2: Skip enforcement — manifest validation rule 11 catches `trigger_session_pattern != null AND layer4_applicable: true`. What about the reverse: `trigger_session_pattern == null AND layer4_applicable: false`? Operator opt-out — allowed?

**Question**: Validation rule 11 (§5.6) only fires if BOTH conditions are true simultaneously: non-null trigger pattern AND `layer4_applicable: true`. The reverse situation — a machine author sets `layer4_applicable: false` with `trigger_session_pattern: null` — is not prohibited. An operator could opt out of Layer 4 for a non-trigger-session machine (e.g., to avoid the ~3s cost, or because a bespoke transformation was added that makes Step B counts diverge). Is this intentional?

**Designer's likely answer**: The field `layer4_applicable` is optional and defaults to `true` (per §5.5.2 note: "may be omitted"). Setting `layer4_applicable: false` with `trigger_session_pattern: null` would silently disable Layer 4 for a machine that could benefit from it. Since the manifest is author-controlled, this is an operator decision. Manifest validation can't know if a machine has an undocumented non-rawdata-aligned transformation.

**Why this matters**: v5 creates a one-way escape hatch via `layer4_applicable: false` that is only constrained to be consistent WITH `trigger_session_pattern`. A future developer adding a bespoke feature that re-dispatches rounds (see Critic v4 edge case E5: "bespoke feature re-routes pids to different ST buckets → Layer 4 would fire → machine could never be `complete: true` → author sets `layer4_applicable: false`") would use this to silently suppress Layer 4 without any validation check. Rule 11 only prevents the inverse direction.

**Verdict: ⚠ partial** — the validation rule prevents inconsistency in the trigger-session direction. It does not prevent silent Layer 4 suppression for non-trigger-session machines with bespoke dispatch. This is an accepted design gap in v5, consistent with the "operator controls the manifest" philosophy. Worth flagging for implementers.

---

### Q3: Day-1 verification gate (Issue ②) — is item 0 actually unskippable? What is the enforcement mechanism beyond "GATE" label?

**Question**: v5 §6.3.3 labels item 0 "GATE — must complete before proceeding to items 1-9." But in practice, Phase 3 is executed by a human implementer writing files and running scripts. Nothing in the Phase 3 deliverable list mechanically prevents items 1-9 from proceeding before item 0 completes. No CI check verifies that item 0's per-machine pass/fail is recorded before manifests are written. No script enforces the ordering.

**Designer's likely answer**: The "GATE" label + "must complete before proceeding to items 1-9" is a procedural requirement. The commit message recording requirement creates accountability: if the Phase 3 kickoff commit message lacks item 0's pass/fail table, the omission is detectable in code review. Phase 3 is a planned migration with a kickoff commit, not an ad-hoc change.

**Why partially insufficient**: Code review catches the recording omission only if a reviewer looks for it. The proposal does not mandate a reviewer check for item 0's presence in the commit message. There is no CI check that validates "all Day-1 candidates appear in the commit message with PASS status." Compared to, say, a git hook or a `validate_manifests.py` rule that detects `console_diagnostic_complete: true` without a corresponding pass entry in a `day1_verification.json` sidecar, the current enforcement is purely social (the commit message convention).

**Verdict: ⚠ partial** — the gate is formally stated as a numbered deliverable item and the recording requirement creates accountability. The enforcement mechanism is social (commit message review) rather than technical (CI check or validation script). This is weaker than the manifest validation rules in §5.6 which are technically enforced. For a process-oriented concern, social enforcement may be acceptable; but it is not the same strength as the other validation rules.

---

### Q4: Day-2 candidates return path — what is the path from "Day-2 pending QA" back to Day-1?

**Question**: v5 §6.3.3 item 0 specifies that failed candidates go to "Day-2 pending QA" subsection in the Phase 3 commit description. The return path is not specified. The general flip criteria in §6.3.2 exist, but there is no explicit statement that "a Day-2 candidate follows the same path as any machine graduating from `complete: false` to `complete: true` per §6.3.2." How long can a machine sit in Day-2 limbo? Is there a quarterly review analogous to the override review?

**Designer's likely answer**: Day-2 candidates are just `console_diagnostic_complete: false` machines with a known failure. Once the failure is fixed (bespoke rule added, rawdata re-run, etc.), they follow §6.3.2 flip criteria: all applicable layers pass, no known issues, audit log in commit message. The Phase 3 commit description is not the ongoing tracker — it is just the initial record of failure.

**Why insufficient**: The Day-2 designation exists only in one commit message. There is no mechanism that says "at the next quarterly review, check if M274 or SC-Vanilla machine X (which failed item 0) now passes." Per Concern III above: a machine whose initial Phase 3 verification failed could sit at `complete: false` indefinitely in the same way overrides could before v5. The quarterly QA review for overrides (§5.5.7) explicitly covers variant overrides; it does NOT explicitly cover Day-2 failed candidates. These are two different populations but the same organizational risk.

**Verdict: ✗ not addressed** — Day-2 candidates' return path relies on §6.3.2 (which they implicitly satisfy) but is never explicitly stated. More critically, there is no time-bounded review cadence for Day-2 candidates. They could wait indefinitely without triggering any CI warning or quarterly review.

---

### Q5: Variant override metadata — `override_set_clear_target` field is not included. Could reduce manual review burden.

**Question**: The brief probe asks whether v5 should include `override_set_clear_target` (e.g., "remove me when underlying issue X is fixed"). This would let the lint rule fire specifically when the referenced issue is closed, rather than relying on timestamp comparison with the underlying's last flip date.

**Designer's likely answer**: The lint rule uses `underlying_last_flip > override_set_at` as a proxy for "the underlying was fixed after the override was set." This is conservative: it fires a warning any time the underlying is updated after the override, even if the underlying update is unrelated to the variant's specific edge case. A `clear_target` field would make the signal more precise.

**Why the current design is adequate but imprecise**: The lint rule may generate false-positive warnings: if M273's underlying flips `true` for a reason unrelated to M273$WheelSelector$42$'s specific Wheel nesting issue, the lint rule fires for M273$WheelSelector$42$. The operator must then re-run `rtp_integrity.py` to check if the variant now passes. This is additional work per warning. A `clear_target: "ISSUE-42: deep Wheel nesting fallback"` would let the lint rule skip the warning until that issue is marked closed. However, this adds complexity (issue tracker integration or free-text matching) and is a polish concern, not a correctness concern.

**Verdict: ✓ adequately addressed** — the current metadata fields (at, reason, by) plus the timestamp-based lint rule constitute an adequate lifecycle mechanism. The `clear_target` suggestion would improve precision but is not load-bearing.

---

### Q6: Quarterly QA review — no interrupt path for critical regression. If a stale override covers a now-critical machine, the quarterly cadence may be too slow.

**Question**: v5 §5.5.7 specifies a quarterly cadence for reviewing stale overrides. What if the stale override covers a machine that is now in a critical production context (e.g., M273$WheelSelector$42$ is a high-revenue machine and the operator discovers its console report is permanently warn-only months after the underlying was fixed)? Is there an interrupt path, or is quarterly the only review gate?

**Designer's likely answer**: The `true → false` direction is always immediately available: any team member can flip `true → false` without ceremony (§6.3.2 direction asymmetry). The reverse (`false → true`) for a specific variant requires running `rtp_integrity.py` against the variant's rawdata and clearing the override per the §5.5.7 procedure. This can be done at any time — it does not need to wait for the quarterly review. The quarterly review is the scheduled cadence; an urgent need can trigger an ad-hoc review at any time.

**Verdict: ✓ adequately addressed** — the clearing procedure in §5.5.7 is not gated on the quarterly calendar. Any operator who discovers a stale override and confirms the edge case is resolved can clear it immediately per the specified procedure. The quarterly review is a safety net for overrides that nobody noticed. Urgent cases are unblocked.

---

### Q7: Lint rule action threshold — warns forever with no escalation. Is this an organizational footgun?

**Question**: The lint rule emits a WARNING in CI on every PR touching manifests. It does NOT block merges. The quarterly QA review is the enforcement mechanism. But §7.2 explicitly defers organizational ownership ("who schedules the review?") to the implementation team. If no one owns the quarterly review, the lint warning accumulates indefinitely.

**Designer's likely answer**: The proposal's scope is the technical specification, not organizational ownership. The lint rule creates a persistent CI signal. The quarterly review procedure is defined. The proposal explicitly flags §7.2 as an open question for the implementation team to resolve. This is the same class as §8.13 out-of-scope items (operational ownership, scheduling tooling).

**Why the gap matters**: Unlike §8.13 items (which are "nice to have" operations tooling), the quarterly review is the ENFORCEMENT MECHANISM for a stale-override footgun. Per memory `feedback_no_silent_swallow.md`, best-effort post-hooks must persist diagnostic outcomes — but if the quarterly review has no owner, the lint warning is the only signal, and it never becomes an error. This creates a warning that cannot become an error by design. The v4 gap (no reminder mechanism) is closed by v5; but the enforcement path still terminates at an unowned organizational process.

**Verdict: ⚠ partial** — the lint rule + quarterly review closes the original gap (no reminder). The residual is that enforcement depends on an unowned process. This is explicitly acknowledged in §7.2 as out of scope, making it a known gap rather than an oversight. Flagging for the implementation team to resolve before Phase 3.

---

### Q8: Layer 4 perf — ~3s/machine on warm disk. Cold start: first fleet pull after service restart?

**Question**: v5 §9.4 perf note states: "The ~3s estimate assumes chunks are already on local disk from the main pass (OS page cache warm)." But on the first fleet pull after a service restart, the OS page cache is cold. The main pass reads chunks into memory, then Step B reads them again. If the OS evicts the chunks between the main pass and Step B (possible if chunk size × number of concurrent machines exceeds available RAM), Step B faces cold disk reads. On spinning disk, cold read for a 414k-spin machine (~50MB chunk × 8 chunks = ~400MB per machine) could be 5-10× slower than warm cache. Validator v4 §2.6.2 notes the M274 sample is 48 chunks.

**Designer's likely answer**: Step B runs "as part of `rtp_integrity.py`" which is called "after `pia.main()` returns" per §9.5. The main pass has already read all chunks. For sequential per-machine processing, the OS page cache should retain the most recently read machine's chunks in memory. For parallelized fleet pulls (multiple machines running concurrently), memory pressure is higher. However, the `--skip-layer4-rawdata-scan` escape hatch (§9.4) provides a development-workflow bypass if Step B is too slow.

**Why the estimate needs a caveat**: v5 §9.4 correctly notes "measurement during implementation recommended" and "if Step B exceeds 10s for any machine in the Day-1 candidate set, add `--skip-layer4-rawdata-scan`." But the caveat is framed as a development-workflow concern, not a cold-start production concern. On the deployment hardware (single Win box per `project_internal_deploy_intent.md`), if a nightly fleet pull starts from a cold cache state, Step B's contribution to total fleet pull time could be materially higher than ~20 min.

**Verdict: ⚠ partial** — the ~3s warm-disk estimate is plausible and the implementation measurement recommendation is appropriate. The cold-start case is not explicitly addressed in the perf note. For the specific deployment context (single Win box, nightly fleet pull from cold state), the actual Step B overhead may exceed the estimate. The `--skip-layer4-rawdata-scan` escape hatch mitigates but is framed as dev-only.

---

### Q9: Mirror approach §8.14 — is this an admission that Skip is suboptimal?

**Question**: v5 §8.14 documents the Mirror approach (approach a) as an explicitly out-of-scope future option, with a full implementation pointer: "the relevant entry point is `fresh_slotlab/trigger_sessions.py`'s `compute_trigger_sessions` function." Is the inclusion of this detailed future path an architectural hedge — i.e., is the designer uncomfortable with Skip and leaving an escape hatch?

**Designer's likely answer**: The Skip approach's trade-off is clearly documented: "~17+ documented trigger-session machine families lose Layer 4 coverage." The trade-off is accepted for this iteration because Layer 4's goal is "verify dispatch routing correctness, not verify trigger-session re-attribution correctness." §8.14 is a responsible documentation of the deferred option, not a sign of hesitation. The addendum explicitly authorized approach (b).

**Verdict: ✓ adequately addressed** — §8.14's inclusion of the Mirror approach is appropriate future-proofing, not architectural hedging. The addendum authorized Skip explicitly; the designer accepted it; the trade-off is documented. §8.14's implementation pointer is useful for the future session that may revisit it. This is not an admission of inadequacy.

---

### Q10: RoundWinRules constraint — convention-only or code-enforced?

**Question**: v5 §9.4 states "RoundWinRules MUST NOT write to `payout_id_by_spin_type_total` directly." This is a textual constraint in the spec. Is there a code-level enforcement (e.g., Python `@property` setter on `payout_id_by_spin_type_total` that raises `AttributeError`, or a type annotation using `ReadOnly`) to prevent a future rule author from accidentally violating it?

**Designer's likely answer**: The constraint is validated by existing practice (M274's `_bcm_cycle` does NOT write to the dict — empirically confirmed). The `RoundWinRule` ABC in `round_win.py:102` is the enforcement surface. If the ABC's `extract_win` and `extract_payouts` methods are specified to not accept `payout_id_by_spin_type_total` as an argument, a rule author cannot write to it without deliberately bypassing the interface. The constraint in the spec is the architectural contract; code-level enforcement is an implementation concern for Phase 2.

**Why convention-only is a risk**: Per `03_coupling_audit.md §3.4`, `payout_id_by_spin_type_total` is a shared accumulator. Future rule authors may not read the constraint in §9.4 and may accidentally write to it by looking at the data flow and following the pattern of other accumulators. The constraint is a prose comment in the pseudocode (`# RoundWinRules MUST NOT write to this dict`). If the `RoundWinRule` ABC's `extract_win` / `extract_payouts` interface does not accept `payout_id_by_spin_type_total` as a parameter, the constraint is structurally enforced by interface design (you'd need to reach outside the interface to violate it). But if the orchestration code passes the full parse state (including `payout_id_by_spin_type_total`) to rule methods, the constraint is bypassable.

**Verdict: ⚠ partial** — the constraint is explicitly stated in the spec with clear reasoning. Whether it is code-enforced or convention-only depends on how Phase 2 structures the `RoundWinRule` ABC's interface. This is not specified in v5. Convention-only constraints have historically been violated in this codebase (per `feedback_subprocess_import_suicide_and_module_globals.md` — module globals that "should not be accessed" were accessed). The constraint should ideally be structurally enforced at the interface level.

---

### Q11: Two open questions remaining — are they pre-approval-blocking or implementation-only?

**Question**: v5 §7 has exactly 2 open questions. §7.1 is "future session-aware Layer 4 for trigger-session machines" (explicitly a v6+ design question, not a v5 blocker). §7.2 is "quarterly QA review ownership and tooling" (organizational concern, same class as §8.13 out-of-scope items). Are these genuinely implementation-only, or does §7.2's unresolved ownership create a pre-approval blocker?

**Designer's likely answer**: §7.2 acknowledges the organizational concern. The spec defines the procedure and the lint rule provides the technical signal. Organizational assignment is the same class as "who owns the flip decision for non-Day-1 machines" (§8.13) — both are explicitly out of scope for the design proposal. The architecture is complete and implementable regardless of who owns the quarterly review.

**Why §7.2 is not pre-approval-blocking**: The quarterly review is for stale VARIANT overrides, which are a post-Phase-3 operational concern. Phase 3 ships with 0 variant overrides (no variant has `override: false` yet — these are set only when a specific variant's data reveals an edge case during QA). The first quarterly review would be needed only after at least one variant has been granted an override. That is a post-migration operational concern. The design is complete without resolving ownership.

**Verdict: ✓ adequately addressed** — both open questions are genuinely implementation-only or post-migration operational concerns. Neither is pre-approval-blocking. The reduction from v4's 4 open questions to 2 represents meaningful convergence.

---

### Q12: Cross-cutting: v5 addendum §1 Issue ① says M14 and M139 are trigger-session machines. v5 §6.3.1 correctly places them in SC-Vanilla (Group A, `trigger_session_pattern: null`). Is there a genuine factual conflict?

**Question**: The addendum v5 §1 Issue ① text lists "M14/M15/M120/M139/M279" as machines with `trigger_session_pattern != null`. But per `02_taxonomy.md §4.2`, both M14 and M139 are in SC-Vanilla (ST-1A, no bonus ST, F-Plain). v5 §6.3.1 is consistent with the taxonomy. The addendum is wrong about M14 and M139.

**Designer's likely answer**: The addendum §1 is the problem framing text authored by the design team before v5 was written. The designer resolved the discrepancy correctly: the manifest examples for M14 show `trigger_session_pattern: null, layer4_applicable: true`, which is consistent with SC-Vanilla taxonomy. M14 gets full Layer 4 coverage. M139 also gets `trigger_session_pattern: null` (consistent with SC-Vanilla). The addendum's machine list was incorrect; the proposal's treatment of the machines is correct.

**Why this still warrants a flag**: The addendum is part of the design artifact chain and is referenced by downstream readers (Validator v5, future designers). Validator v5 is specifically tasked with testing "Layer 4 v5 against a trigger-session machine (M14 or M15) to verify the structural fix." If the Validator v5 tests M14 expecting it to be a trigger-session machine (based on the addendum §1 text) and finds it has `layer4_applicable: true` (per v5), the Validator may report a discrepancy as a proposal inconsistency rather than recognizing it as an addendum error. This creates a risk of a false critique in v5 validation, not a risk in production implementation.

**Verdict: ⚠ partial** — the proposal is internally consistent and Wave 1-consistent (M14 in SC-Vanilla with `trigger_session_pattern: null`). The addendum contains an incorrect machine list. For production implementation this is harmless because implementers write manifests from the proposal (not the addendum), and the proposal is correct. For the validation step (Validator v5 testing M14 as trigger-session), the error could cause confusion. A clarification note would prevent this.

---

## §4 Migration risk inventory

### Phase 1 risks (unchanged from v4; no v5 changes)

**R1.1**: RAWDATA_ROOT module global (11 references per `03 §4.1`) + 33 module globals. Phase 1 refactor. Per memory `feedback_subprocess_import_suicide_and_module_globals.md`, these have caused production-critical bugs. Phase 1 removes them. Rollback trivial.

**R1.2**: 6 duplication extractions (per `03 §4.2`). If virtual and production implementations have subtle behavioral differences, consolidation may silently change behavior for one. No regression test specified for "virtual behaves identically to production on same input."

### Phase 2 risks (v5 adds trigger-session skip logic)

**R2.1**: Layer 4 implementation with trigger-session skip logic. The `layer4_applicable` flag gating must be correctly resolved in `rtp_integrity.py`. If the per-mode resolution (§5.5.6's "when non-null in any mode, drives the per-mode `layer4_applicable` resolution") is not implemented correctly, trigger-session machines in specific modes may fail to skip Layer 4, reintroducing the false-positive class.

**R2.2**: Phase 2 runs Layer 4 in warn-only mode for all machines. False-positive warnings for machines that should be skipped (due to incorrect `layer4_applicable` resolution) would appear as noise but not block reports. Silent false-positive accumulation is a risk if nobody monitors warn-only output systematically.

**R2.3**: `payout_id_by_spin_type_total` constraint is convention-only at Phase 2. If Phase 2's forcing-function bespoke features (12 machines per §6.2 deliverable 4) include any new `RoundWinRule` that accidentally writes to this dict, the Layer 4 constraint is violated silently. Test coverage for this constraint is not specified.

### Phase 3 risks (v5 adds item 0 gate and Day-2 candidates)

**R3.1**: Item 0 enforcement is social, not technical (Q3 above). An implementer who skips item 0 would write manifests with `true` flags unverified against Layer 4. CI validation does not catch this because `validate_manifests.py` checks schema consistency, not "was Layer 4 actually run before setting `true`?"

**R3.2**: If M274 fails item 0 (the one Day-1 Group B candidate requiring a full 8-robot × 8-chunk Layer 4 run), it drops to Day-2. §6.5 Phase 5 claims "~46 machines have `console_diagnostic_complete: true` from Phase 3." If M274 fails, this count is 45. §6.5 does not account for the possibility of a lower count. Minor inconsistency risk.

**R3.3**: SC-Vanilla member identification gap (32 of 45 unnamed, per Critic v4 R3.2). Still present in v5 — the unnamed 32 are identified "during Phase 3 manifest authoring." Item 0 now gates their `true` authorization, which mitigates the risk that they ship `true` unverified. But the membership determination is still at-authoring-time, not validated against Phase 3's manifest writing.

**R3.4**: `layer4_applicable` field population for 421 machines. v5 §6.3.3 item 1 says "Write 421 per-machine manifests. Include `layer4_applicable` field per §5.5.2 for all machines with `trigger_session_pattern != null`." But the resolution of which machines have non-null `trigger_session_pattern` requires knowing the trigger-session cluster membership — which comes from Wave 1 taxonomy + the same Phase 3 discovery process. Per `02_taxonomy.md §4.2`, SC-TopDollar + SC-WheelSelector + SC-CommonSelector clusters are trigger-session; but the exact membership of "many BCM machines with trigger semantics" (per addendum v5) is not enumerated. An implementer may miscategorize a BCM machine's `trigger_session_pattern` as null when it should be non-null, silently enabling Layer 4 for a machine that would generate false-positives.

### Phase 5 risks (v5: 46 machines in strict mode on Day 1)

**R5.1**: If `rtp_integrity.py` has a bug in its Layer 4 skip logic (skips when it should not, or runs when it should skip), and the bug activates after Phase 3 data is committed, a trigger-session machine that was correctly skipped during item 0 verification might fire Layer 4 during Phase 5's strict mode. This would raise on the machine rather than warning. Rollback: revert Phase 5 or flip the machine's `console_diagnostic_complete` to `false` (fast path). Not catastrophic but disruptive.

**R5.2**: Stale SC-Vanilla assumption. If any of the ~45 SC-Vanilla machines had their configuration updated between Wave 1 (taxonomy audit, which counted them as plain) and Phase 3 (manifest authoring), they might now have a bonus ST not reflected in the manifest. Layer 4 Step B would see the new bonus ST in rawdata; `payout_id_by_spin_type_total` would track the bonus pids correctly; Step C compares — they match (no routing bug). So Layer 4 wouldn't fire spuriously. But Layers 1-3 might fire if the manifest's `spin_type_convention` doesn't include the new bonus ST. This is caught at item 0 verification before Phase 3 cutover. Risk mitigated by item 0.

---

## §5 Edge cases not covered

**E1 — Per-mode `layer4_applicable` resolution function**: As noted in Concern II, §5.5.6 claims a per-mode resolution algorithm exists for machines with `trigger_session_pattern_override` in `per_mode_overrides`. No pseudocode. No edge cases specified. A machine with, say, mode 1: `trigger_session_pattern: null` and mode 2: `trigger_session_pattern_override: "type_1"` — what is `layer4_applicable` for mode 1 vs mode 2? The spec does not specify whether the resolution is per-mode granular or machine-level blunt.

**E2 — Trigger-session machine that graduates to `complete: true` — flip criteria for these machines**: §6.3.2 flip criteria say "For machines with `layer4_applicable: false`, Layers 1-3 must return PASS." This is correct and explicit. But a trigger-session machine like M15 graduating to `complete: true` has a weaker guarantee than SC-Vanilla (no Layer 4 dispatch verification). The flip criteria spec does not note this asymmetry in guarantee level. An operator evaluating a trigger-session machine's flip proposal might assume the same 4-layer coverage applies to all `complete: true` machines, but trigger-session ones are permanently 3-layer.

**E3 — Adding a trigger-session machine as a Day-1 candidate in a future Phase 3 expansion**: Phase 3 identifies ~46 Day-1 candidates. All of these are trigger-session-free. If a future Phase 3 expansion (post-migration) proposes to make a trigger-session machine (e.g., M15 once its topdollar rule is verified) a strict candidate, item 0 applies. But item 0 says "run `rtp_integrity.py` in Layer 1-4 mode (all applicable)." For a trigger-session machine, "all applicable" means Layers 1-3 only. The operator reading item 0 might expect Layer 4 to run and be puzzled by its absence. Item 0 does not explicitly mention this case.

**E4 — CI warning accumulation between quarterly reviews**: If the quarterly QA review is missed for one quarter, the lint rule emits warnings on every PR touching any manifest. If 10 PRs touch manifests during a missed quarter, 10 sets of warnings accumulate. There is no mechanism to mark a warning as "under investigation" or "acknowledged." The next quarterly reviewer must triage all accumulated warnings, some of which may have already been investigated and found non-actionable. The lint rule has no "acknowledged" or "snooze" state.

**E5 — Machine with `trigger_session_pattern: null` that has a future bespoke feature re-dispatching pids**: As noted in Critic v4 E5, if a future bespoke feature explicitly re-routes pids to different ST buckets, Step C fires a false-positive for a non-trigger-session machine. The `layer4_applicable: false` opt-out is technically available for this case (Q2 above), but neither the mechanism nor the guidance for using it is specified in §5.5.6 beyond "trigger_session_pattern == null AND layer4_applicable: false is allowed but not validated."

**E6 — M273$WheelSelector$42$ override-clearing procedure: Layer 4 was never applicable**: §5.5.7 override-clearing procedure says "Run `rtp_integrity.py` against the specific variant's rawdata. All applicable layers must PASS (Layer 4 only if `layer4_applicable: true` for this variant)." For M273 variants, `layer4_applicable` is inherited as `false`. So the clearing procedure for an M273 variant effectively only requires Layers 1-3 to pass. This is correct but the spec should note explicitly that trigger-session variants' clearing procedure never includes Layer 4 — otherwise an implementer may believe a stricter check was required.

---

## §6 Hidden assumptions

**H1 — SC-Vanilla machines have no undeclared per-mode trigger sessions**: v5 §6.3.1 states "All [SC-Vanilla machines] have `trigger_session_pattern: null` (plain machines, no bonus ST)." This is derived from `02_taxonomy.md §4.2` which identifies the cluster by logicClassNames. The assumption is that SC-Vanilla logicClassNames ({NormalRTPPreProcessor, NormalSpinGenerator, NormalSpinValidator}) are incompatible with trigger-session behavior. This is a reasonable inference from the taxonomy but is not explicitly verified against `fresh_slotlab/trigger_sessions.py`'s routing logic. If a SC-Vanilla machine's rawdata happens to contain rounds with `trigger_session_pattern`-compatible structures, `compute_trigger_sessions` might still act on them — but `payout_id_by_spin_type_total` would reflect the re-attribution, and Step B's naive count would diverge. The assumption is likely correct but is structural (inferred from logicClassNames) not verified (confirmed from rawdata inspection).

**H2 — `trigger_session_pattern` in manifest is the sole determinant of `compute_trigger_sessions` activation**: v5 assumes that `layer4_applicable: false` correctly predicts all cases where `compute_trigger_sessions` modifies `payout_id_by_spin_type_total`. But `compute_trigger_sessions` may activate based on rawdata content (e.g., presence of `Trigger` in `ReMarks` field) independently of the manifest field. Per memory `reference_trigger_session_patterns.md`, Type 1 trigger detection uses `Trigger` in `ReMarks` and Type 2 uses win=0 anchor + empty ReMarks. A machine not classified as trigger-session in the manifest could still have `compute_trigger_sessions` active if its rawdata contains these markers. In that case, `payout_id_by_spin_type_total` would be re-attributed, and Step B's naive count would differ — producing a false-positive Layer 4 failure on an ostensibly non-trigger-session machine. This assumption is not validated in v5.

**H3 — Quarterly QA review will be executed**: The stale-override machinery (lint rule + quarterly review + clearing procedure) depends on an organizational process that has no named owner (§7.2). The assumption that this process will run is unstated but load-bearing. Per memory `feedback_no_silent_swallow.md`, outcomes must be persisted — but if no one runs the review, stale overrides persist indefinitely and the lint warnings become background noise.

**H4 — Item 0 cost estimate (~10 min) is accurate**: §6.3.3 item 0 estimates "~10 minutes for all 46 candidates (inclusive of setup, teardown, and any machine that requires rawdata re-fetch)." The 45-machine × ~3s = ~135s is ~2.25 minutes. The "~10 minutes inclusive of setup/teardown/rawdata re-fetch" assumes no machine in the Day-1 set needs rawdata re-sampling (each has cached rawdata). Per `03_coupling_audit.md §3.4`, 206 of 421 machines have no cached rawdata. The 45 SC-Vanilla machines are rawdata-confirmed (per §6.3.1 "rawdata-confirmed, per `02 §4.2`"), but M274 requires "full 8-robot × 8-chunk run." If any of the ~32 unnamed SC-Vanilla machines lack cached rawdata (not confirmed in Wave 1), the ~10 min estimate is an underestimate by the rawdata re-sampling cost.

---

## §7 Alternatives double-check

### Alternative B (lightweight per-feature SCHEMA_VERSION sidecar) — rejection verified

v5 §2.2: "B doesn't implement the operator-diagnostic framing from addendum v3 §1. Under B, the console has no per-machine completeness signal and cannot implement v4/v5's Layer 4 rawdata cross-check." This is structurally correct. B has no `console_diagnostic_complete` mechanism, cannot run `rtp_integrity.py` with per-machine skip logic, and has no `layer4_applicable` field. The v5 Skip approach's trigger-session gating is entirely manifest-driven — B cannot replicate it. **Rejection: verified.**

### Alternative C (full per-machine analyzer plugin tree) — rejection verified

v5 §2.3: C eliminates sharing wholesale; incompatible with §5.5.5 eager variant cascade. Per `02_taxonomy.md §4.2`, the 166-variant fleet (M273 × 85 + others) would require 166 duplicate manifests under C. v5's variant cascade is the opposite approach. Additionally, C does not solve the trigger-session false-positive problem (C has no manifest-level `trigger_session_pattern` or `layer4_applicable` field — each plugin would need its own trigger-session handling). **Rejection: verified.**

**Note on Alternative D (Session-aware Layer 4, Mirror approach)**: Critic v4 flagged this as an unexamined alternative. v5 addresses it explicitly in §8.14 as the Mirror approach — documented as a future option with implementation pointer. The rejection of Mirror for v5 (reduces Layer 4 independence, shares `compute_trigger_sessions`) is reasoned and consistent with Layer 4's stated goal ("verify dispatch routing correctness, not verify trigger-session re-attribution correctness"). The rejection is adequately documented, not just assumed.

---

## §8 Verdict

### Summary of Concern A/B/C/D resolution

| Concern | v4 status | v5 resolution | Critic v5 verdict |
|---|---|---|---|
| A — Layer 4 trigger-session false-positive | Acknowledged, not structurally resolved | Skip approach: `layer4_applicable: false` + rule 11 | RESOLVED (with Concern II residual on per-mode resolution spec) |
| B — 46 Day-1 candidates unverified; not gated | Procedural gap | §6.3.3 item 0 as formal gating deliverable | RESOLVED (with Concern III/Q4 residual on Day-2 return path) |
| C — Override re-enablement path unspecified | Soft concern; unspecified | Override metadata + clearing procedure + quarterly QA + lint | RESOLVED (with Concern IV residual on lint warning enforcement) |
| D — Fleet Layer 4 perf unspecified | Open question | §9.4 perf note ~3s; trigger-session 0s; implementation measurement recommended | RESOLVED |

### Summary of Validator v4 documentation gap resolution

| Gap | v4 status | v5 resolution | Critic v5 verdict |
|---|---|---|---|
| §3.1 — RoundWinRules MUST NOT write to `payout_id_by_spin_type_total` | Unspecified | §9.4 explicit constraint with reasoning + empirical verification | RESOLVED |
| §3.2 — Variant override removal procedure | Unspecified | §5.5.7 3-step clearing procedure with audit log | RESOLVED |
| §3.3 — `_unattributed_*` Step C note | Unspecified | §9.4 Step C `is_fallback_pid` field + note text | RESOLVED |

### Verdict: APPROVE-WITH-REVISIONS

All 4 Concerns (A/B/C/D) and all 3 polish gaps are substantially addressed. The proposal is convergent. The remaining issues are either (a) soft operational gaps explicitly acknowledged as out-of-scope, or (b) minor spec underspecifications in new mechanisms introduced by v5 itself.

**Change requests (ordered by severity)**:

**1. MEDIUM — §5.5.6 must add pseudocode for per-mode `layer4_applicable` resolution**

Claim: "per-mode variation is handled via `trigger_session_pattern_override` which, when non-null in any mode, drives the per-mode `layer4_applicable` resolution." The resolution algorithm is stated but not specified. Per-mode granular resolution (mode N with non-null override → that mode's `layer4_applicable` = false; other modes unaffected) is the correct interpretation but must be made explicit, as it determines whether machines with mixed-mode trigger semantics run Layer 4 on their non-trigger modes.

**2. MEDIUM — §6.3.3 must clarify Day-2 return path explicitly**

Item 0 specifies the path into Day-2. The return path from Day-2 must be explicitly stated: "Day-2 candidates follow the same §6.3.2 flip criteria as any `complete: false` machine. There is no separate Day-2 re-verification ceremony — once the failing layer's issue is resolved, run `rtp_integrity.py` and flip per §6.3.2." This closes the organizational-footgun risk of indefinite Day-2 limbo. Optionally add Day-2 candidates to the same quarterly review as stale overrides.

**3. SOFT — §9.4 perf note should acknowledge cold-disk start case**

Add one sentence: "Cold-start case (OS page cache cold after service restart): Step B faces cold disk reads for all chunk files. On typical spinning-disk or SSD deployment hardware, Step B may take 2-5× longer than the warm-disk estimate. The `--skip-layer4-rawdata-scan` escape hatch is available for development workflows but MUST NOT be used in production fleet pulls."

**4. SOFT — Addendum v5 §1 Issue ① machine list is incorrect**

M14 and M139 are SC-Vanilla machines with `trigger_session_pattern: null`. The addendum lists them as trigger-session machines. The proposal itself is correct (M14/M139 in §6.3.1 Group A with `layer4_applicable: true`). A clarification note should be added to the addendum or to v5 §9.4's trigger-session list to prevent downstream reader confusion, especially given that Validator v5 is tasked with testing "M14 or M15" as a trigger-session machine.

---

```
arch-critic complete (v5).
- Top concerns: 4 (I addendum machine-list error / II per-mode layer4_applicable resolution unspecified /
  III Day-2 return path absent / IV lint warning no enforcement mechanism)
- Stress questions: 12 (verdict: 5 checkmark / 5 partial / 2 not-addressed)
- Migration risks flagged: 10 (across 4 phases)
- Edge cases not covered: 6
- Hidden assumptions: 4
- Concerns from v4: A checkmark (with Concern II residual) / B checkmark (with Concern III/Q4 residual) /
  C checkmark (with Concern IV residual) / D checkmark
- Validator v4 doc gaps: all 3 resolved (section-3.1 checkmark / section-3.2 checkmark / section-3.3 checkmark)
- Verdict: APPROVE-WITH-REVISIONS
  - 2 MEDIUM change requests (per-mode layer4_applicable resolution spec; Day-2 return path)
  - 2 SOFT change requests (cold-disk perf caveat; addendum machine list correction)
- Output: session_artifacts/_arch/05_critique_v5.md
```
