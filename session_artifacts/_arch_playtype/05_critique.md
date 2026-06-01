# Wave-3 Adversarial Critique — Play-Type Architecture Proposal
> arch-critic, Wave 3. 2026-06-01.
> Input: `04_architecture_proposal.md` (proposal), `06_validation.md` (validator findings, taken as given),
> `01_pipeline_map.md`, `03_coupling_audit.md`, `DIRECTION.md §9 + §10`.
> Stance: hostile reviewer who wants this design to fail in production. Every finding is reasoned.

---

## 1. Top Concerns (5 most serious issues)

**TC-1 — Byte-identical proof is hand-waved, not argued (BLOCKER)**
The proposal claims byte-identical output is preserved after moving mechanic code into accumulator
objects, but §8 contains no argument that float accumulation order, dict merge sequence, or the
timing of stash writes is preserved. Per `01_pipeline_map.md §2 Stage 1`, `parse_chunk_response`
carries ~40 stateful accumulators that intermix. Moving BCM and trigger-session logic into
`MechanicAccumulator` objects changes the ORDER in which partial results are written to the chunk
dict relative to the universal body. Any change in dict merge order is byte-non-identical in Python
3.7+ (dict is insertion-ordered). The proposal's §8 simply declares "byte-identical" and lists
excepted keys; it does not argue why accumulation order is preserved. This is the correctness gate
for the entire refactor and it is unproven.

**TC-2 — PreParseProbe ordering is architecturally undefined (BLOCKER)**
The validator confirmed (Item A) that `CostCreditsReliabilityPlugin` cannot be a standard
`MechanicAccumulator` because the `cost_credits_unreliable` flag must set `is_paid_round` behavior
in the UNIVERSAL loop body BEFORE any `on_round` call fires. The proposal acknowledges this in §11
Q5 but does not resolve it. This is not an edge case: `is_paid_round` gates session close, paid-spin
counting, and RTP denominator on every round of every M10-family machine. The standard accumulator
lifecycle (`on_round` → `finalize` → result) structurally cannot satisfy a pre-loop ordering
requirement. No `PreParseProbe` ABC or interface is defined anywhere in §4.1. Phase 2 deliverable 10
ships `CostCreditsReliabilityPlugin` without an agreed interface for it. The entire M10-family (4+
machines) will produce wrong paid-round counts if this is not resolved before implementation.

**TC-3 — ClaimSignature conflict resolution is procedural, not mechanistic (SERIOUS)**
The validator found dual-claim conflicts on M275 ST=126 (BCMFreespin + ScatterFreespin) and M120
ST=138 (MultiSymbolCollection + ScatterFreespin). The proposal's answer to all such conflicts is
"fire an ONBOARDING ALERT; human reviews." For a 310-machine fleet onboard (Phase 3), this means
potentially hundreds of alerts that each require rawdata inspection and a fork-rule addition to
plugin source code — which is a code change, which re-flags the machines that plugin covers, which
triggers re-generation. The proposal has no cap on the number of conflicts expected and no analysis
of how many of the 310 non-pilot machines are likely to trigger alerts. If the alert rate is high,
Phase 3 degenerates into a supervised manifest-authoring process under a different name.

**TC-4 — `_infer_feature_spin_type_mapping` migration plan is incomplete, and the stash contract
is the hidden wire that breaks `CollectMechanic` (SERIOUS)**
The validator confirmed (Item B) that `_infer_feature_spin_type_mapping` feeds TWO consumers:
`_upstream_feature_breakdown_data` and `_collect_mechanic_data` (via `_bcm_bonus_feature` /
`_bcm_bonus_source`). The proposal's §7.1 lists this function as moving to "BCM plugin and
auto-detection" but the migration plan in §9 Phase 1 has no step that explicitly preserves the
`_collect_mechanic_data` stash write. `CollectMechanic.emit()` reads `_bcm_bonus_feature` from the
stash (per `01_pipeline_map.md §3`). If that stash key is not written by the BCM accumulator's
`finalize()`, `CollectMechanic` silently produces empty output. This will NOT be caught by the
byte-identical gate unless the gate checks the `collect_mechanic` display panel — which is a
DISPLAY plugin key. The proposal's §8.1 excepted keys list does not include any display plugin
output, implying it IS checked for byte-identity, which means a stash miss WOULD be caught —
but only if the byte-identical fixture was generated from a BCM machine (M272, M275, etc.). The
proposal's golden test list is M272, M275, M279, M268 in Phase 1 (§9 Phase 1 item 13), so the gate
would catch it in theory — but only if the fixture captures `collect_mechanic` output, which depends
on `CollectMechanic.emit()` running correctly, which depends on the stash being populated. This is a
circular dependency in the test setup.

**TC-5 — The hash composition algorithm silently breaks for machines where `parser.py` is PARTIALLY
carved (SERIOUS)**
The proposal claims that `parser.py` (122 KB, `_CLOSURE_FILES`) can eventually be REMOVED from the
closure once its mechanic branches are "fully evacuated." But the carve is done in phases — Phase 1
carves BCM, Phase 2 carves trigger-sessions and wild-nudge. During the inter-phase period, `parser.py`
contains BOTH the universal coordinator code AND residual mechanic branches not yet extracted (e.g.,
the inline ST-number comparisons: `03_coupling_audit.md §6.1` lists 13 direct ST comparisons in the
loop body). While `parser.py` stays in `_CLOSURE_FILES`, editing the REMAINING mechanic branches still
re-flags 420 machines — no blast-radius improvement for those branches. The proposal's claimed
"122 KB leaves the closure" is contingent on ALL mechanic code being evacuated from `parser.py`, which
is not achievable in Phase 1. The staleness improvement advertised for Phase 1 applies only to the BCM
functions that move; the dominant file (122 KB) stays in the closure through Phase 2 at minimum.
Scenario E of §7.4 ("edit base infrastructure → all 420 re-flag") is correct for universal edits,
but the proposal does not acknowledge that PARTIAL evacuation of `parser.py` gives ZERO hash benefit
for the remaining mechanic code still in that file.

---

## 2. Ten Stress Questions

---

### SQ-1: Float accumulation order — where is the byte-identical argument?

**Question.** `parse_chunk_response` accumulates ~40 variables across the per-robot loop. BCM
accumulators write `all_cycle_peaks`, `collect_robots_seen_total`, and the BCM correction sums
(`_compute_bonus_correction`) to the chunk dict. After moving BCM logic into
`BCMBaseAccumulator.finalize()` → merged via `dict.update()`, the BCM keys are written AFTER the
universal body writes its keys (not interleaved as they are today). In Python, dict insertion order
determines JSON serialization order. If any downstream code constructs a hash or computes a float
sum by iterating the chunk dict in key-order, and that iteration order changes because accumulator
merge is now a post-loop update rather than inline assignments, the output bytes will differ.
Specifically: `_compute_bonus_correction` in `parser.py` (per `01_pipeline_map.md §2 Stage 2`) reads
`all_cycle_peaks` from the chunk dict to compute BCM correction sums. If `all_cycle_peaks` is
written by the accumulator AFTER the universal body tries to read it, the correction computation
runs on stale/empty data. The proposal does not address when in the parse loop `all_cycle_peaks` is
available for reading by other base code.

**Designer's likely response.** "The chunk dict returned by `parse_chunk_response` is only read
AFTER the loop completes; `_compute_bonus_correction` runs in Stage 2 (`main()`), not inside
`parse_chunk_response`. The accumulator's `finalize()` is called before the function returns, so all
keys are present at return time."

**Why insufficient.** This claim requires verification against the actual code. `01_pipeline_map.md §2
Stage 2` places `_compute_bonus_correction` in the finalize stage AFTER the chunk loop, which would
make the response correct. But `03_coupling_audit.md §6.1` says `_close_session` and `_flush_bonus_chain`
run INLINE in the parse loop and depend on trigger-session output (itself B). If `_close_session`
reads trigger-session accumulated state DURING the loop (not after), and trigger-session state is now
produced by a `MechanicAccumulator.on_round` that fires on the same round (not before), the read-write
ordering within a single round iteration is undefined. The proposal does not specify whether `on_round`
fires BEFORE or AFTER the universal inner body reads session state. Per §4.1: "Called for every round
in this robot's round list, in order." — no specification of ordering relative to the universal body's
own per-round operations.

**Verdict: ✗ Not addressed.** The proposal asserts byte-identical without a call-ordering model.

---

### SQ-2: Accumulator on_round ordering — who goes first?

**Question.** Phase 2 activates multiple simultaneous accumulators on machines like M279
(BCMBasePlugin + WildNudgePlugin both active). The parse loop calls `acc.on_round()` for each
accumulator. If `WildNudgeAccumulator.on_round()` calls `is_paid_round(round_dict)` to determine
whether a nudge round is paid, and `BCMBaseAccumulator.on_round()` also reads `CollectCount` for
the same round, the ORDER of these calls must be defined. More critically, if ANY accumulator's
`on_round()` MUTATES `round_dict` (e.g., adding a derived field like `is_bcm_trigger=True`), a
subsequent accumulator reading that field sees a different `round_dict` than one running first. The
proposal's §4.1 says the loop "does NOT know what the accumulator does" — meaning it cannot prevent
mutation. Immutability of `round_dict` across accumulator calls is not specified in the contract.

**Designer's likely response.** "Accumulators observe `round_dict` but do not mutate it. Their
results go into the accumulator's internal state (`to_chunk_partial()`), not back into `round_dict`."

**Why insufficient.** This is a convention, not a contract. The `MechanicAccumulator` ABC in §4.1
has no annotation, no `Protocol[ReadOnly]`, no enforcement. An implementer writing
`BCMListRewardAccumulator` could innocently add `round_dict["_is_trigger"] = True` for convenience.
The proposal has no mechanism to prevent this. Additionally: the BASE universal loop body
(`parse_chunk_response`) assigns derived fields into the per-round dict during processing (e.g.,
`is_paid`, `trigger_anchor`). If accumulators run BEFORE the base body writes these derived fields,
they cannot read them. If they run AFTER, the universal body cannot read accumulator-derived signals.
The proposal needs an explicit ordering model: universal body first, then accumulators, or vice versa.

**Verdict: ✗ Not addressed.** Ordering and mutation contract are both missing from §4.1.

---

### SQ-3: `parser.py` stays in `_CLOSURE_FILES` — what is the actual Phase 1 blast-radius win?

**Question.** The proposal's headline benefit is: "editing BCM-freespin play-type plugin re-flags
only ~34 machines." This is true for the PLUGIN itself. But `parser.py` (122 KB,
`03_coupling_audit.md §2.1`) remains in `_CLOSURE_FILES` through Phase 1 and Phase 2, because the
universal coordinator (the shell that calls `acc.on_round()`) lives in `parser.py`. Any bug fix to
the accumulator DISPATCH MACHINERY in `parser.py` — adding a new accumulator hook, fixing the order
of `on_robot_end` vs `finalize` calls, fixing a missing `acc.on_round` invocation for a corner case
— still re-flags all 420 machines. This means Phase 1 improvement applies ONLY to BCM plugin edits
in isolation. All parse-loop machinery edits remain fleet-wide. The proposal does not quantify how
many of the historical `parser.py` edits would have been "plugin edit only" vs "parser machinery
edit." If the majority of past edits were to the machinery rather than mechanic logic, the blast-radius
improvement is smaller than presented.

**Designer's likely response.** "Once BCM logic moves to the plugin, edits to BCM detection no longer
touch `parser.py`. The 4 commits to `analyzer/core/parser.py` (per `03_coupling_audit.md §3.2`) were
mostly mechanic logic, not machinery."

**Why insufficient.** The 4 post-Phase-6 commits to `parser.py` are a small sample. The 132 commits to
`player_impact_analyzer.py` (from which `parser.py` was carved) include both mechanic and machinery
changes. More importantly: adding NEW play-type plugins in the future DOES require machinery changes
(e.g., adding a hook for a `PreParseProbe` — which TC-2 shows is needed). Each infrastructure
addition to `parser.py` re-flags the fleet. The proposal claims "adding a new accumulator does not
change the dispatch host" (§2 Alternative C rationale) — but that claim holds only for plugins that
fit the STANDARD accumulator lifecycle. Non-standard plugins (PreParseProbe, or any accumulator that
needs additional hook types) will require parser.py changes. The "zero host change" claim is only
true for the 15 known play-types; it cannot be asserted for future mechanics.

**Verdict: ⚠ Partially addressed.** The blast-radius improvement for already-known plugin edits is
real. The residual fleet-wide exposure for parser machinery changes is not quantified.

---

### SQ-4: Hash composition with PARTIAL file carve — the arithmetic is wrong on paper

**Question.** §7.1 states that `round_classification.py`, `round_win.py`, `trigger_sessions.py`,
and the B portions of `player_impact_analyzer.py` "move out of `_CLOSURE_FILES`." But the proposal
also says A functions from these files STAY in base (e.g., `is_paid_round`, `extract_authoritative_pay_ids`,
`RoundWinRule` ABC, `extract_round_win` dispatcher). A file cannot be both "in `_CLOSURE_FILES`" and
"not in `_CLOSURE_FILES`" simultaneously. The actual implementation must be ONE of:
(a) The ENTIRE file leaves `_CLOSURE_FILES` and is reorganized so A functions go to a new base module
and B functions go to plugins.
(b) The file stays in `_CLOSURE_FILES` (because it still contains A functions) and the B functions
are DELETED from it (with their implementations now in plugins).

Option (b) means that the REMAINING A-function content of `round_classification.py` still lives in
`_CLOSURE_FILES`. Editing the B functions in plugins does not touch this file — which is the desired
behavior. But option (b) also means `round_classification.py` stays in the closure as a smaller
file. If the proposal means "the file shrinks but stays in closure," then the hash benefit is: the
A-function remainder is small and stable → less churn risk, not zero. The proposal's phrasing ("move
out of `_CLOSURE_FILES`") implies option (a), which requires a non-trivial reorganization of imports
across all consumers of `round_classification.py` (including `parser.py`, `scripts/infer_paytable.py`,
`scripts/infer_bcm_pairing.py` per `01_pipeline_map.md §5`).

**Designer's likely response.** "Option (a) is intended: the A functions are relocated to a new
`fresh_slotlab/analyzer/core/round_utils.py` (or similar) that stays in closure; the old file is
replaced by plugin modules."

**Why insufficient.** This reorganization is mentioned nowhere in the migration plan (§9). It is a
significant refactor with its own consumer-breakage risk (every import of `round_classification.is_paid_round`
across scripts must be updated). The scripts `infer_paytable.py` and `infer_bcm_pairing.py` import
from `round_classification` per §5 — these are not in the pilot test suite and may break silently.
The proposal must explicitly state the reorganization plan for these shared consumers. Treating this
as an implementation detail is incorrect: it determines whether the hash claim is achievable.

**Verdict: ✗ Not addressed.** The proposal conflates "the file's B functions leave closure" with
"the file leaves closure." These are different outcomes with different import-breakage profiles.

---

### SQ-5: ClaimSignature "required_bonus_remark_pattern" — regex against which field on which rounds?

**Question.** `ClaimSignature.required_bonus_remark_pattern` is described as "at least one BONUS
round must have ReMarks matching this regex." But the validator confirmed (M275 rawdata) that
M275 paid rounds have `TriggerFreespin` remark ABSENT (0/40,000) — the freespin remark only appears
on bonus ST=126 rounds. For M31, paid ST=43 rounds have `ReMarks="TriggerFreespin"` on 334 paid
rounds AND bonus ST=44 rounds have `ReMarks="FreeSpin"`. Both patterns exist on different STs. The
`ScatterFreespinPlugin.CLAIM_SIGNATURE` in §4.2 uses `required_bonus_remark_pattern=r"\bFreeSpin\b"`
— does this match against only bonus rounds (`CostCredits=0` rounds)? Or all rounds? And is the
matching done case-sensitively? The taxonomy (§A3 M31) shows `"FreeSpin"` on bonus rounds and
`"TriggerFreespin"` on paid trigger rounds — these are structurally different strings. If the regex
`r"\bFreeSpin\b"` is evaluated case-insensitively against ALL rounds (not just bonus), it would also
match `TriggerFreespin` (contains `FreeSpin`). This could cause `ScatterFreespinPlugin` to match on
pure-paid machines that happen to have a `TriggerFreespin` remark (if any exist), or cause it to
trigger on the paid trigger round rather than the bonus round, leading to wrong ST assignment.

**Designer's likely response.** "The signature is evaluated against bonus rounds only (CostCredits=0
rounds). The `\bFreeSpin\b` word-boundary ensures `TriggerFreespin` does not match because `Trigger`
is a prefix without a word boundary before `FreeSpin`. Actually `\b` before `F` in `TriggerFreeSpin`
— `r` is a word character, so `\bFreeSpin\b` would NOT match within `TriggerFreeSpin`."

**Why insufficient.** The `\b` analysis is correct if we assume `TriggerFreespin` (lowercase `s`
in `spin`). The taxonomy shows: M31 has `ReMarks="TriggerFreespin"` (lowercase s). But M275's bonus
rounds show `"FreeSpin"` (uppercase S in validation §Case 3). The case sensitivity of the regex and
the exact remark strings across the 310 non-pilot machines are unknown. More critically: the
`_claim.py` schema shows `required_bonus_remark_pattern: str | None` — there is no documentation
of whether matching is against `CostCredits=0` rounds, against all rounds, per-round or on the
concatenated set of all remarks. This ambiguity is a contract gap; a subtly wrong regex or scope
assumption will silently misclassify machines during Phase 3 fleet onboarding.

**Verdict: ✗ Not addressed.** The ClaimSignature contract does not specify the evaluation scope
(which rounds, case sensitivity, matching semantics) for `required_bonus_remark_pattern`.

---

### SQ-6: `detect_play_types()` uses "first 500-2000 rounds from chunk_0001" — what if the first chunk has no bonus rounds?

**Question.** The auto-detector in §5.1 runs against `sample_rounds: list[dict]` from "first 500-2000
rounds from chunk_0001." Per `02_taxonomy.md §A3 M31`: freespin trigger rate is 334/42,000 = ~0.79%.
In 2,000 rounds, expected trigger count = 15.8 — likely enough. But M99's lock-symbol bonus triggers
at `411/(51,193+2,192) = 0.77%`. In 2,000 rounds, expected bonus rounds = ~15. Fine. But consider
the worst case: jackpot-tier pay_ids on M275 appear on 76/80,000 = 0.095% of paid rounds. In the
first 2,000 rounds, expected jackpot trigger count = ~1.9. Some machines could have ZERO jackpot
events in the first 2,000 rounds. `ClaimSignature.required_trigger_pay_id` for a jackpot-class plugin
would NOT match. The plugin would not be detected, and the jackpot field attribution would go to the
fallback bucket silently. The proposal has no mechanism to handle rare-trigger mechanics where the
first-chunk sample is too small to observe the distinguishing signal.

**Designer's likely response.** "The jackpot tier pay_ids (27502/27503/27504) are in the
PER-MACHINE CONFIG, not in the `ClaimSignature`. The plugin that handles jackpot tiers is detected
by BCM fields (which are present on every paid round, not just jackpot triggers). The jackpot config
populates after detection, not as part of detection."

**Why insufficient.** This is plausible for M275's jackpot tiers. But `BCMListRewardPlugin`'s claim
signature (§4.3, §5.3) REQUIRES `required_trigger_pay_id="5801"` as part of detection (not config).
The M274 validation confirmed: 423 paid ST=140 rounds carry pay_id=5801 out of 40,000 = 1.06%
trigger rate. In 2,000 sample rounds, expected pay_id=5801 triggers = ~21. Fine. But for a variant
machine where the list-reward trigger is rarer (say 0.1%), 2,000 rounds might have 2 triggers. The
proposal does not specify a minimum sample size guarantee or a fallback when `required_trigger_pay_id`
is not observed in the sample. If detection fails silently, the machine runs with `active_plugins`
missing the `BCMListRewardPlugin` and the unattributed bucket reappears — the exact bug this refactor
fixes for M274.

**Verdict: ⚠ Partially addressed.** Common trigger rates (>0.5%) are safe with 2,000 rounds. Rare
triggers are not handled. No minimum-sample guarantee exists in the proposal.

---

### SQ-7: M275 dual-trigger BCM+scatter — the `st_map` claim is over-simplistic

**Question.** The validator found (Item C) that ST=126 on M275 is triggered by BOTH BCM peak
(8.2%) and scatter pay_id=666 (91.8%), and there is NO bonus-round-level discriminator — the
trigger type is only visible on the preceding paid round. The proposal's handling of this: fire
an ONBOARDING ALERT, human reviews. The validator's suggested fix: `ScatterFreespinPlugin` adds
`exclude_if_fields_present=frozenset({"CollectCount","AccCredits"})` so it does not claim ST=126
on BCM machines. Then `BCMFreespinPlugin` owns ST=126 on M275. But this creates a correctness
problem: `BCMFreespinPlugin`'s accumulator must handle BOTH scatter-triggered and BCM-triggered
freespin rounds and distinguish them internally by looking at the preceding paid round. This means
the accumulator must maintain cross-round state (most recently seen trigger type) and attribute
freespin wins to the correct trigger category. The proposal does not specify whether `on_round` has
access to PREVIOUSLY SEEN rounds or only the current round. The `on_robot_end(all_rounds)` hook
does receive all rounds — but trigger-session detection needs per-round attribution during the
loop, not after the fact.

**Designer's likely response.** "`BCMFreespinAccumulator` tracks the most-recently-seen trigger type
in its state. When it sees a paid round with CollectCount=1000 or pay_id=666, it records the trigger
type. When it subsequently sees a bonus ST=126 round, it attributes to the last trigger type. This
is exactly what the current `compute_trigger_sessions` does for Type 1 sessions."

**Why insufficient.** The current `compute_trigger_sessions` (Type 1, `trigger_sessions.py:131`)
runs on the full ordered robot round list and can look backward across the list. The `on_round`
interface as specified in §4.1 receives `(round_dict, round_idx)` — not the full preceding sequence.
The accumulator can maintain its own per-robot state (the preceding trigger type) as instance state,
which does work. But the `on_robot_end(all_rounds)` contract then becomes REDUNDANT for this case
(since the state was built up incrementally). The proposal does not clarify when each hook is the
appropriate vehicle. More critically: this incremental-state approach requires the parse loop to
call `on_round` IN ORDER — which §4.1 says it does. But for distributed or chunked replay with
robot-reordering, out-of-order calls would corrupt the state. The proposal does not acknowledge this
fragility.

**Verdict: ⚠ Partially addressed.** The per-round incremental state model works for ordered replay.
The proposal does not document the ordering guarantee as a contract requirement.

---

### SQ-8: `mechanism_registry.py` — the docstring-reality gap is not actually resolved

**Question.** `03_coupling_audit.md §9 hotspot 10` confirmed: `mechanism_registry.py` IS in
`_CLOSURE_FILES` despite its docstring claiming otherwise. The proposal's §7.1 says `mechanism_registry.py`
is "moved to base-excluded plugin (`machine_mechanics` display plugin absorbs or it becomes a
play-type plugin post)." But `MechanismRegistry.build()` is currently called at `main()` finalize
stage and its output (`_mechanism_registry`) is read by `MachineMechanics.emit()`. If
`mechanism_registry.py` is moved OUT of base and INTO a plugin, `MechanismRegistry.build()` must be
called by that plugin's `emit()` — not by `main()`. This means the registry build MOVES to plugin
time (display stage) from finalize time (post-accumulate). But `MechanismRegistry.build()` reads
from `summary` keys that are written during finalize — specifically it needs `feature_chunk_tally`
and play-type fields that the accumulators produced. If `MechanismRegistry.build()` moves to
plugin emit time, it runs AFTER all chunks are merged and the summary is assembled, which is
correct. But the proposal does not trace this call-chain relocation explicitly. "Absorbs or becomes
a play-type plugin" is not a design decision — it is two different designs with different call
chains.

**Designer's likely response.** "The `MachineMechanics` display plugin already calls
`MechanismRegistry.build()` inside `emit()`. The refactor simply moves the class definition FROM a
file in `_CLOSURE_FILES` TO the `machine_mechanics.py` plugin file. No call-chain change needed."

**Why insufficient.** If this is true, then the fix is indeed a one-file move. But the proposal
says the function is "absorbed" OR "becomes a play-type plugin" — these are structurally different.
If `MechanismRegistry.build()` currently runs in `main()` finalize (per `01_pipeline_map.md §4`
which shows `MechanismRegistry.build()` at Stage 4 emit loop) and ALSO has outputs that feed OTHER
parts of `main()` before the emit loop, moving it to a plugin's `emit()` changes when the build
happens. The proposal must choose one design and state it explicitly.

**Verdict: ⚠ Partially addressed.** The fix direction is identified (remove from closure) but the
specific mechanism is left ambiguous.

---

### SQ-9: `display_features_for_play_types()` — the auto-apply function that replaces manifests is completely unspecified

**Question.** The hash composition algorithm in §7.2 Step 3 calls
`display_features_for_play_types(play_type_config.active_plugins)` to determine which display
plugins apply to a machine. This function replaces the entire 420-manifest system. It must answer:
given `active_plugins=["bcm_base","scatter_freespin"]`, which of the 9 display plugins apply?
The function is not defined anywhere in the proposal. This is not a detail — it is the CORE of the
manifest-replacement. The current manifests are 420 files declaring all 9 plugins for nearly every
machine. If `display_features_for_play_types` returns all 9 for all machines, it replicates the
current behavior (all universal). If it returns a subset, the function must encode the
play-type-to-display-feature mapping. That mapping is itself a new design artifact. For example:
does `CollectMechanic` display plugin apply only to machines with `bcm_base` active? Or to all?
If `CollectMechanic` is display-only on BCM machines, then for M14 (pure_paid), `CollectMechanic`
does NOT apply → its emit is skipped → the `collect_mechanic` section disappears from M14's report.
This is a visible output change that the proposal does not acknowledge as a change.

**Designer's likely response.** "The display plugins are universal (all 9 apply to all machines,
same as today's manifests). `display_features_for_play_types` returns all 9 for all machines
initially, and can be narrowed later."

**Why insufficient.** If all 9 apply to all machines, the function is a no-op wrapper, and the
manifest replacement is cosmetic. More critically, `DIRECTION.md §4` says the 420 manifests are
"DISCARDED (greenfield)" and "detection becomes automatic." This implies at minimum that
`CollectMechanic` should NOT apply to pure-paid machines (M14), since there is no collect mechanic
to display. Today's manifests apply it to M14 because "apply all 9 to all machines" is the lazy
default — not because it is correct. If the new system maintains this lazy default, it is not an
improvement. If it narrows by play-type, the narrowing rule is unspecified.

**Verdict: ✗ Not addressed.** `display_features_for_play_types()` is invoked but not defined.
The manifest-replacement logic is the most consequential unspecified piece of the proposal.

---

### SQ-10: What happens to orphan reports during Phase 1/2 transition when the feature flag is flipped?

**Question.** Phase 1 uses `--use-play-type-plugins` feature flag. When the flag is DISABLED
(monolith path), reports are generated with `effective_analyzer_version = base_hash + display_plugin_hashes + mode`.
When the flag is ENABLED, reports are generated with the new composition (`base_hash + play_type_hashes + display_feature_hashes + config_hash + mode`). Both sets of reports coexist on disk. The backend's
staleness check compares the current `effective_analyzer_version` against the stored value. If an
operator runs with the flag ENABLED (new composition) and then DISABLES it (old composition), every
machine that was regenerated under the new composition will now show as STALE under the old
composition — even though the underlying analysis may be identical. The rollback process described
in §9 Phase 1 says "disable the flag and the monolith path resumes" — but it does not address the
stale-report debris left on disk from the flag-enabled runs. Users will see a fleet-wide "stale"
badge after rollback that requires an explanation.

**Designer's likely response.** "The rollback is expected to produce stale signals for machines that
were regenerated under the new hash model. Operators would need to regenerate reports under the old
model after rollback."

**Why insufficient.** The proposal positions rollback as a safety net ("if byte-identical gate
fails, disable the flag"). But if rollback requires a fleet regeneration to clear the stale signal,
it is not a cheap rollback — it is a double-regeneration (once forward under new model, once back
under old model). For 327 machines × average ~2 modes = ~654 `(machine,mode)` pairs, this is a
meaningful operator burden. The proposal does not acknowledge this cost or provide a lighter-weight
rollback path (e.g., keeping old reports and only serving new ones when the flag is enabled).

**Verdict: ✗ Not addressed.** Rollback leaves stale debris and requires a full fleet re-generation.
The cost is not mentioned in §9.

---

## 3. Migration Risk Inventory

### Phase 1 risks

**R1-1 (BLOCKER) — BCM accumulator `finalize()` write order vs `_close_session` read order.**
If `_close_session` (inline in `parse_chunk_response`) reads BCM-derived state (e.g., `cycle_peak`
flag) during the per-round loop, and the BCM accumulator's state is only written to the chunk dict
at `finalize()` after the robot's rounds complete, then during the loop `_close_session` reads stale
data. This is the ordering problem from SQ-1. If the byte-identical gate catches it, Phase 1 fails
with a diff that requires rethinking the accumulator lifecycle. If the gate does NOT catch it (because
the session close logic happens after the round but before the golden comparison is made), the
regression is silent.

**R1-2 (SERIOUS) — `collect_mechanic_data` stash not populated after BCM migration.**
Per TC-4: if `BCMBaseAccumulator.finalize()` does not write `_bcm_bonus_feature` and
`_bcm_bonus_source` to the chunk dict (which the main loop stashes into `_collect_mechanic_data`),
`CollectMechanic.emit()` produces empty panels for BCM machines. The byte-identical gate on M272 /
M275 WILL catch this — but only if `CollectMechanic` output is included in the golden comparison
fixture. The proposal does not explicitly list which top-level keys in `player_impact_summary.json`
are included in the byte-identical check. If `collect_mechanic` panel is excluded (e.g., under the
assumption it is "a display plugin, not mechanic output"), the regression is silent.

**R1-3 (SERIOUS) — `machine_round_win_rules.json` migration for M274 may not be atomic.**
Phase 1 retires the M274 entry from `machine_round_win_rules.json` and migrates it to
`configs/play_type_configs/M274/mode_1.json`. If the auto-generated per-machine config file is not
written before the first analysis run under the new flag, the `BCMListRewardAccumulator` will have
no `trigger_anchors` config → it will run with default (empty) anchors → pay_id=5801 attribution
will not fire → M274 reverts to unattributed ST=139 output. The proposal says the config is
"auto-generated on first analysis run" (§6.2) — but if the first run uses the empty config, the
first output is wrong. The config must be pre-generated (or seeded from `machine_round_win_rules.json`)
BEFORE the first flag-enabled run.

**R1-4 (MINOR) — `bcm_pairings.json` entries for Phase 1 pilots "retired" without specifying the
retirement mechanism.**
§9 Phase 1 item 17 says "bcm_pairings.json entries for Phase 1 pilots retired." If this means the
JSON file is edited to REMOVE those 5 machines' entries while the monolith path (flag disabled) still
reads the file, then during a rollback the monolith path runs against a bcm_pairings.json missing the
pilot entries — `_load_bcm_pairings()` returns no pairing for M272/M275/M274/M279/M268 → BCM bonus
feature resolution falls back to heuristic → output differs from pre-migration. This is a rollback
failure mode: retiring config entries before the monolith path is decommissioned corrupts the rollback.

### Phase 2 risks

**R2-1 (SERIOUS) — `trigger_sessions.py` removal from closure changes base_hash at Phase 2 start.**
When `trigger_sessions.py` is removed from `_CLOSURE_FILES` (Phase 2 item 11), `base_hash` changes
fleet-wide. This is expected once — but it happens DURING Phase 2, which is a mid-migration
fleet-wide re-flag. All machines that were regenerated under Phase 1 (with `trigger_sessions.py`
still in closure) are now stale again. The proposal acknowledges "fleet regeneration is expected once"
in Phase 3 — but Phase 2's closure change also triggers a fleet-wide re-flag. This means operators
see TWO fleet-wide re-flag events: one when Phase 1 lands (hash composition algorithm changes) and
one when Phase 2 removes files from closure. The proposal does not mention this Phase 2 re-flag.

**R2-2 (SERIOUS) — `compute_trigger_sessions` is 230 lines covering Type 1 + Type 2 families; moving
it to a single `TriggerSessionAccumulator` risks over-large plugin scope.**
Proposal §11 Q1 raises this as an open question. The critic position: merging Type 1
(Remark-triggered) and Type 2 (win==0 anchor) into one accumulator means ANY change to either
family's logic changes the `ScatterFreespinPlugin` hash → all scatter-freespin machines re-flag.
Currently, M31 uses Type 1 and M273 (WheelSelector) uses Type 2. If they are in one plugin,
fixing a Type 2 bug for WheelSelector re-flags M31 (which only uses Type 1). This is WORSE than
the current situation where the single `trigger_sessions.py` at least groups all trigger logic in
one place. The split (`RemarkTriggerPlugin` for Type 1, `WheelSelectorPlugin` for Type 2) achieves
better isolation. The designer deferred this to Wave 3 — it must be decided before implementation.

**R2-3 (MINOR) — `manifest_loader.py` stays in `_CLOSURE_FILES` after manifests are "discarded."**
`manifest_loader.py` is 37,946 bytes in `_CLOSURE_FILES` (03_coupling_audit.md §2.1). If manifests
are greenfield-discarded in Phase 3, `manifest_loader.py` becomes dead code in base. It stays in the
closure (contributing to `base_hash`) forever unless explicitly removed. The proposal does not mention
retiring `manifest_loader.py` from the closure after the manifest system is abandoned.

### Phase 3 risks

**R3-1 (SERIOUS) — ONBOARDING ALERT rate for 310 non-pilot machines is unknown and unbounded.**
The proposal has no estimate of what fraction of the 310 remaining machines will trigger ONBOARDING
ALERTS during auto-detection. If 20% of machines have novel or ambiguous STs (63 machines), Phase 3
requires 63 manual rawdata inspections + fork-rule additions to plugin code. Each plugin change
re-flags the machines that plugin covers. The proposal describes Phase 3 as "purely additive (new
configs, new reports)" with "no code changes needed for most rollbacks" — but if fork rules require
plugin source changes, Phase 3 is NOT additive-only.

**R3-2 (SERIOUS) — Deleting 420 manifests before regenerating all reports is a point of no return.**
Phase 3 item 6 deletes all 420 `machine_manifests/*.json`. Once deleted, the old hash composition
(which needed manifests for display feature resolution) cannot be used. Any machine NOT yet
regenerated under the new model will show as stale with no way to regenerate it under the old model.
The deletion must happen AFTER all machines have been regenerated, not before. The proposal implies
simultaneous: "manifests are DELETED" as a deliverable alongside "auto-detection configs generated for
all machines" — these must be sequenced, not simultaneous.

**R3-3 (MINOR) — Old test suite deletion (`test_2a..6_*` per DIRECTION §6) before new suite is green
leaves a coverage gap.**
Phase 3 item 7 deletes old test files. If this happens before all 15 play-type plugins have
byte-identical golden tests, there is a period where the test suite provides zero coverage of the
migrated mechanic logic. The proposal does not specify whether old test deletion is gated on new test
coverage being sufficient.

---

## 4. Edge Cases Not Covered

**EC-1 — Robot with ZERO rounds in a chunk.**
`MechanicAccumulator` lifecycle: `on_round()` × N, then `on_robot_end()`, then `finalize()`. What
happens when N=0 (robot with no rounds in this chunk)? Some machines might have robots with no rounds
in a chunk if the chunk boundary cuts at a robot boundary. The accumulator's internal state is
uninitialized. `to_chunk_partial()` must handle empty state without crashing. Not specified.

**EC-2 — First-chunk sample has NO bonus rounds (pure paid machine with very rare bonus).**
If `detect_play_types()` runs on 2,000 rounds that happen to be all paid ST (e.g., machine with
0.01% bonus trigger rate), the auto-detector sees no bonus STs → no bonus plugin matches → all bonus
ST assignments are "unclaimed" when the actual analysis runs → ONBOARDING ALERT fires mid-analysis,
not pre-analysis. The proposal says detection runs "at the START of an analysis run (before any
chunk is parsed)" — but the sample is drawn from "first 500-2000 rounds from chunk_0001." If
chunk_0001 has no bonus, detection fails, analysis proceeds with incomplete `active_plugins`. The
MachinePlayTypeConfig is written with wrong (or empty) `active_plugins` and cached — subsequent runs
also use the wrong config.

**EC-3 — Machine variant with DIFFERENT SpinType than its parent.**
`03_coupling_audit.md §6.4` notes 167 variant manifests inherit from parent. Under the new model,
auto-detection runs per (machine, mode). A variant machine (e.g., M273$variant42) might use ST=126
while M273 uses ST=44 for the same mechanic (different engine generations). The auto-detector must
handle this correctly — the per-variant `play_type_configs/<M273$variant42>/mode_1.json` will have a
different `st_map` than M273's. This is handled correctly by the design in principle (per-variant
config), but the proposal gives no example or test case for variant-specific ST remapping. Onboarding
M273's 85 variants automatically will likely generate many ONBOARDING ALERTS if variant STs differ
from the parent.

**EC-4 — Accumulator exception mid-chunk.**
If `BCMBaseAccumulator.on_round()` raises an exception on round 5,000 of 10,000 (e.g., unexpected
`CollectCount` field type on a new machine variant), the parse loop has no defined error-handling
behavior. The proposal does not specify whether the exception propagates (aborting the chunk), is
caught and logged (accumulator produces partial output), or triggers an onboarding alert. An
unhandled exception from an accumulator aborts the analysis run — worse than the current behavior
where the inline code would have produced a wrong-but-not-crashed output.

**EC-5 — `on_robot_end` receives all rounds including paid rounds, not just bonus.**
Per §4.1: `on_robot_end(all_rounds: list[dict])`. For a 10,000-round chunk with 250 robots of ~40
rounds each, `all_rounds` = 40 rounds for that robot. But for machines with variable robot sizes
(some robots may have 1 paid round + 0 bonus, others 1 paid + 50 bonus), the accumulator must handle
variable-length `all_rounds`. More critically, `on_robot_end` runs AFTER all `on_round` calls for that
robot — it is a post-hoc hook. If the accumulator uses `on_robot_end` to correct or finalize per-robot
state (e.g., detecting that a BCM cycle started in this robot and ended in the NEXT robot → the trigger
attribution must span robots), the single-robot view in `on_robot_end` is insufficient. The proposal
does not address BCM cycle peaks that span robot boundaries.

**EC-6 — `MECHANIC_DEPS` ordering is defined for emit() but proposal does not specify if it also
governs on_round() ordering.**
`MECHANIC_DEPS` is used to order `emit()` calls (topo-sort at display time). But the proposal says
accumulators receive `on_round()` in the order defined by `active_plugins`. If `BCMListRewardPlugin`
has `MECHANIC_DEPS = ("bcm_base",)`, does this guarantee `BCMBaseAccumulator.on_round()` fires
BEFORE `BCMListRewardAccumulator.on_round()` for every round? If not, the ListReward accumulator
cannot safely read BCM-accumulated state on the same round. The proposal implies the `MECHANIC_DEPS`
ordering applies to both emit and on_round, but does not state this explicitly.

---

## 5. Hidden Assumptions

**HA-1 — "The external contract of parse_chunk_response does not change" (§2 Alternative C rationale).**
The proposal assumes the chunk dict schema (keys and value semantics) is stable across the carve.
This is not guaranteed: the B functions being carved (BCM detection, trigger-session computation)
PRODUCE many of the chunk dict keys that downstream code reads. If the accumulator's
`to_chunk_partial()` uses different key names or data structures than the inline code currently uses,
the downstream `main()` accumulation loop (which does `dict.update()` across chunks) breaks.
Wave 1 evidence: `01_pipeline_map.md §2 Stage 1` lists the result assembly as "the KEYS are
universal, VALUES come from B-stage logic above" — the keys are designed by the current B code.
Moving B code must preserve EXACTLY the same keys. Not validated.

**HA-2 — "bcm_pairings.json auto-detection replaces 30-machine pairing" (§6.1).**
The proposal claims the BCM accumulator observing "which SpinType follows a cycle-peak trigger" IS
the BCM bonus feature, by definition. This assumes the pairing is unambiguous — that exactly one bonus
ST follows each BCM peak. M275 data (validator Case 3) shows that BOTH BCM-peak triggers (8.2%) AND
scatter triggers (91.8%) produce the SAME bonus ST=126. The BCM accumulator sees ST=126 after both
trigger types, so "the ST that follows" is always 126 — both triggers share the same bonus. The
auto-detection of "which ST is the BCM bonus" is trivial in this case. But for M260 (BCM + FreeSpin
+ WheelSpin, per taxonomy §A1), there are MULTIPLE bonus STs following paid rounds. Which one is the
BCM bonus? The auto-detection claim assumes the answer is visible from the rawdata — but M260's
`02_taxonomy.md §A8 item 1` identifies ST=105 as "likely transition rounds" with MEDIUM confidence.
If the ST pairing is ambiguous, `bcm_pairings.json` manual config is not eliminable.

**HA-3 — "MachinePlayTypeConfig is NOT hand-authored" (§6.2).**
The proposal says the config "is auto-generated by the auto-detector on first analysis run and
cached. It is NOT hand-authored. If the auto-detector disagrees with a cached config, it raises an
onboarding alert rather than silently overwriting." This assumes the auto-detector is ALWAYS correct
enough to be trusted. But the M10-family CostCredits case shows that some machines have rawdata
patterns that require domain knowledge to interpret correctly. If the auto-detector generates a wrong
config (e.g., misidentifies a machine as having BCM play-type because it happens to have a
`CollectCount`-like field from a different mechanic), the only remedy is an ONBOARDING ALERT — which
requires a human to correct the config by hand. But the proposal says the config is "NOT
hand-authored." This creates a contradiction: auto-detection can be wrong, correction requires human
input, but human input is not supposed to produce hand-authored configs.

**HA-4 — "The 393-machine hash compose is safe after plugin extraction" (implicit throughout).**
The hash composition in §7.2 adds `play_type_plugin_hashes` and `config_hash` terms to the existing
model. The existing model was verified for correctness across 393 machines in the variants fleet
rollout (per memory `project_variants_fleet.md`: "md5 fanout; all resolution walks variants_map").
The new composition adds new terms. If any new term has a collision (two different
`active_plugins` lists producing the same sorted-hash sequence) or a degenerate case (empty
`active_plugins` produces an empty hash component that collides with a single-plugin hash), the
staleness signal is unreliable. The proposal does not include a collision analysis for the new hash
composition.

**HA-5 — "Virtual analyzer's `_patch_summary_md5_tags` is a one-line addition" (§12 item 4).**
The proposal dismisses virtual analyzer compatibility as "a one-line addition." Per
`01_pipeline_map.md §6.2`, `_delegate_to_real_analyzer:652-687` calls the REAL analyzer subprocess
with virtual rawdata chunks. Play-type auto-detection runs inside the real analyzer subprocess. The
virtual machine's rawdata may have SpinType distributions that DON'T match any registered plugin's
`CLAIM_SIGNATURE` (virtual machines can have non-production mechanic combinations). If auto-detection
fires an ONBOARDING ALERT for a virtual machine during `_delegate_to_real_analyzer`, that alert is
embedded in the subprocess output and then propagated back to the virtual summary. The frontend
would then show an onboarding alert badge for a slot-designer virtual machine — which is not a
production machine and should not trigger production onboarding workflow. This is not "a one-line
addition."

---

## 6. Comparison to Alternatives — Double-Checking Rejection Rationale

### Alt-A (per-robot hook inside parse loop) — rejected in favor of Alt-C

**Rejection claim**: "parse_chunk_response STAYS in `_CLOSURE_FILES`; blast-radius improvement is
partial."

**Check**: The proposal argues Alt-C differs from Alt-A because "once all mechanic code is in
accumulators, parse_chunk_response becomes a mechanical coordinator with zero mechanic knowledge"
and can eventually leave `_CLOSURE_FILES`. But as shown in SQ-3 and TC-5, this evacuation is
CONTINGENT on full B-code extraction (all phases), requires reorganizing `round_classification.py`
imports (SQ-4), and still leaves `parser.py` in the closure during Phases 1 and 2. During the
transition, Alt-A and Alt-C produce IDENTICAL blast-radius behavior — `parser.py` stays in closure
for both. The differentiation only materializes in Phase 3 or beyond. **The rejection of Alt-A
stands, but the differentiation from Alt-C is delayed and phase-conditional — this is not stated.**

### Alt-B (two-stage parse with ParsedRound struct) — rejected in favor of Alt-C

**Rejection claim**: "If a mechanic plugin needs a field that Layer 1 didn't emit, it fails at
runtime."

**Check**: The proposal's counter-choice (Alt-C) avoids this by passing the raw `round_dict` to
accumulators. But SQ-2 shows that passing the raw `round_dict` creates its own contract problem:
accumulators can read fields the universal body has not yet computed for that round (e.g., `is_paid`
may be computed by the universal body AFTER the accumulator's `on_round` fires). Alt-B's `ParsedRound`
struct failure mode ("field omitted from struct → runtime failure") is loud and caught immediately.
Alt-C's failure mode ("accumulator reads field before universal body writes it → wrong value") is
silent and not caught by type checking. **Alt-B's explicit contract has a correctness advantage over
Alt-C's implicit contract. The rejection rationale's implied trade-off ("explicit contract is harder
to get right but fails louder") is not addressed.** The "field omitted" risk could be mitigated in
Alt-B by passing the full `round_dict` alongside the `ParsedRound` struct — a hybrid that the
proposal did not consider.

### Claim Alt-2 (lazy detection) — rejected

**Rejection claim**: "all accumulator objects run for all robots on all chunks, wasted computation;
effective hash cannot be computed BEFORE the run."

**Check**: The second rejection reason (hash cannot be pre-computed) is the stronger one and
correctly applies. **Rejection stands on the hash pre-computation ground. The computation waste
concern is valid but secondary.**

### Claim Alt-3 (ST-number-as-key) — rejected

**Rejection claim**: "violates DIRECTION.md §10: 'Plugin claim key = feature signature; ST = the
resulting per-machine partition'."

**Check**: The rejection is correct per signed-off DIRECTION. **Rejection stands unambiguously.**

---

## 7. §9/§10 DIRECTION Fidelity Check

**§10 Fidelity Item 1: "Plugin claim key = feature signature; ST = the resulting per-machine partition
(NOT ST-number-as-key)."**
STATUS: HONORED in the ClaimSignature design. The `required_fields` / `required_bonus_remark_pattern`
are field-level signals, not ST numbers. ST numbers appear only in the auto-detected `st_map` output,
not as plugin identification. HOWEVER: the `ClaimSignature` contract gap (SQ-5 — evaluation scope
not specified) is a partial violation risk. If the evaluator defaults to "check all rounds for the
field" rather than "check bonus rounds only," an ST=140 paid round could accidentally trigger a bonus
plugin's signature.

**§10 Fidelity Item 2: "No human-confirmed manifest. Auto-detection from rawdata."**
STATUS: HONORED in principle. The per-machine config is auto-generated, not hand-authored. HOWEVER:
the contradiction in HA-3 (wrong auto-detection → human corrects → but "not hand-authored") is a
§4 violation risk. The DIRECTION says "if detection is wrong, a human RAISES it → fix is to the
DETECTION LOGIC (a base/plugin change), NOT a per-machine confirm file." If the only remedy for a
wrong auto-detection is a code change to detection logic, this is extremely heavyweight for
individual machine exceptions. The proposal's ONBOARDING ALERT path (human reviews, defines fork rule)
does route through plugin code changes for fork rules — but the per-machine `trigger_anchors` config
in §6.2 IS a per-machine hand-authored value. This blurs the line between "config auto-populated from
detection" and "config hand-authored to fix wrong detection."

**§10 Fidelity Item 3: "ST collisions = FORK + onboarding ALERT, never a pre-census."**
STATUS: HONORED. The auto-detector does not pre-scan the fleet for ST collisions. Collisions are
surfaced per-machine on first run. Correct.

**§9 Fidelity: "byte-identical proves the CARVE didn't change behavior; it does NOT prove the
behavior was right."**
STATUS: HONORED for M274 (correctness fix flagged explicitly, §8.2). But the proposal does not
apply this principle to the 55 BCM machines with `fallback_pct > 0.5%` (per
`03_coupling_audit.md §8 Case A`). Those machines are designated byte-identical targets even though
their current output has measurable fallback. §8.3 lists M250 (100% fallback) and M268/M260/M264
(70-90% fallback) as "correctness-fix candidates" but only M274 has explicit correctness-fix test
treatment. The proposal needs to explain why M250 (100% fallback) is not also treated as a
correctness-fix candidate in Phase 1 or Phase 2.

---

## 8. Verdict

**APPROVE-WITH-REVISIONS**

The core structural decision (Alternative C parse-loop + MechanicAccumulator + ClaimSignature
auto-detection + per-machine config hashing) is sound. The problem it solves (fleet-wide re-flag on
mechanic edits, silent config dependencies) is real and confirmed by Wave 1 evidence. The validator's
four rawdata cases confirm the decomposition routes correctly in principle.

**Required before implementation starts (blockers):**

1. **TC-1 / SQ-1 / SQ-2**: Define the ordering model for `on_round()` calls relative to the universal
   loop body per round. Specify: (a) universal body runs first per round, THEN accumulators, or vice
   versa; (b) `round_dict` is read-only for accumulators (enforce via contract or documentation);
   (c) which base-derived fields are available to `on_round()` at call time. Without this, byte-identical
   is not an achievable property — it is a hope.

2. **TC-2**: Define the `PreParseProbe` ABC (a distinct lifecycle from `MechanicAccumulator` that runs
   once before the per-robot loop begins and writes universal parse flags like `cost_credits_unreliable`
   to a shared parse state object). Specify how the universal loop body reads this parse state.

3. **SQ-9**: Define `display_features_for_play_types()`. Specify which display plugins apply to which
   play-types. This determines whether manifest deletion is safe and whether the output schema for
   pure-paid machines changes.

4. **SQ-4**: Specify the reorganization plan for `round_classification.py` and `round_win.py` A-function
   remainders. State explicitly whether these files LEAVE `_CLOSURE_FILES` (requiring import refactor
   across consumer scripts) or STAY (with B-functions deleted from them, making them smaller-but-still-in-closure).

**Required before Phase 2 starts (serious):**

5. **TC-4**: Migration plan §9 Phase 1 must explicitly list the step where `BCMBaseAccumulator.finalize()`
   writes `_bcm_bonus_feature` and `_bcm_bonus_source` to the chunk partial dict, so `CollectMechanic`
   continues to receive its stash.

6. **R1-4**: Per-machine configs for Phase 1 pilot machines must be pre-seeded from `machine_round_win_rules.json`
   and `bcm_pairings.json` BEFORE those files' pilot entries are retired, so rollback does not corrupt
   the monolith path.

7. **R2-2** / Q1 from proposal §11: Decide now whether `compute_trigger_sessions` (Type 1 + Type 2) lives
   in one `ScatterFreespinPlugin` or is split into `RemarkTriggerPlugin` (Type 1) and
   `WheelSelectorPlugin` (Type 2). This decision changes the blast radius for M31 vs M273 mechanic fixes.
   Deferring past Phase 2 implementation start is too late.

**Design gap to document (not implementation-blocking but must be acknowledged):**

8. **SQ-6 + EC-2**: Add a minimum-sample guarantee or a fallback re-detection path for machines where
   the first-chunk sample does not observe a rare trigger (< ~5 observations in 2,000 rounds). The
   current design silently caches a wrong `active_plugins` list.

9. **EC-5**: Specify whether BCM cycle peaks that SPAN robot boundaries (paid peak in robot N, bonus
   rounds in robot N+1) are handled, and which hook (`on_robot_end` or cross-robot state) is
   responsible.

10. **HA-5**: Virtual analyzer compatibility is not a one-line addition. ONBOARDING ALERTS generated
    for virtual machines must be suppressed or routed separately from production onboarding workflow.

**Single most dangerous hidden assumption:**

HA-1 — "The external contract of `parse_chunk_response` does not change." If any key in the chunk
dict that downstream `main()` reads is missing or renamed after B-function extraction, the
accumulation loop silently produces wrong aggregates. The byte-identical gate is the guard — but
only if the golden fixtures capture every key that downstream code reads, including `_collect_mechanic_data`,
`all_cycle_peaks`, BCM correction sums, and trigger-session keys. The proposal does not enumerate
which chunk dict keys are in scope for the byte-identical comparison. Until that list is explicit and
complete, the gate cannot be trusted.
