# Adversarial Critique v4 — Wave 2 Architecture Proposal v4

> Wave 3 v4 / arch-critic. Hostile review of `04_architecture_proposal_v4.md`
> (1243 lines, focused 3-issue revision of v3).
>
> Mandate: verify whether the 3 must-resolves from v3 critique are ACTUALLY
> addressed in v4 — not just claimed. 10+ stress questions, migration risk
> inventory, edge cases, hidden assumptions, alternatives double-check,
> final verdict.
>
> Date: 2026-05-17
> Inputs: `00_brief_v4_addendum.md` (v4 contract / 3 issues),
> `05_critique_v3.md` (Critic v3 source), `04_architecture_proposal_v3.md`
> (baseline), `04_architecture_proposal_v4.md` (THE TARGET).
> Wave 1: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`.

---

## §1 Top concerns

### Concern A — Layer 4 Step A is NOT independent of the analyzer's dispatch path; the check is only partially independent

The v4 fix for Critic v3 M1 is structurally correct in intent: Step B re-scans
rawdata independently and Step C compares. But Step A explicitly reads from
`payout_id_by_spin_type_total`:

```
Step A — Capture analyzer's dispatch result:
    # Source: payout_id_by_spin_type_total built during parse_chunk_response
    for pid_str, st_counts in payout_id_by_spin_type_total.items():
        ...
```

`payout_id_by_spin_type_total` is the same in-memory dict that Critic v3
identified as the shared accumulator. Step A correctly captures the analyzer's
position — that is its intended purpose. The check works: Step B provides the
independent ground truth. Step C compares the two. So the *logical structure*
is sound.

The residual concern is narrower: **session-bonus grouping re-attribution.**
Per memory `feedback_session_semantics.md`, bonus-spin wins are attributed to
the paid spin that triggered them. Per `01 §3.5.2`, `parse_chunk_response`
calls `compute_trigger_sessions` which re-attributes free-spin round (ST=44)
payouts back to the triggering paid-spin round (ST=43). If the analyzer does
this re-attribution correctly, `payout_id_by_spin_type_total` would show
ST=43 counts higher than the raw ST=43 round count — **and so would Step B's
naive rawdata scan show them differently**, because Step B counts
`R.SpinType` per round, not per session-attributed bucket.

Step B explicitly uses `R.SpinType` from rawdata. If the analyzer's legitimate
session-attribution logic says "the 10,797 free-spin rounds (ST=44) should be
counted as paid (ST=43) rounds for payout attribution," then `analyzer_dispatch`
would show ST=43 count > Step B's rawdata ST=43 count. Step C would fire.
This is a **false positive** on a correctly-operating machine.

v4 §9.4's "note" field lists this as possible cause "(b) session-bonus grouping
re-attributes free-spin rounds to paid-spin bucket". But the proposal does not
specify how this false positive is *resolved* or *suppressed*. The operator sees
a Layer 4 failure note saying "possible causes: (a)/(b)/(c)" and must diagnose
manually. More critically, the check does not distinguish between a real dispatch
bug (flag it!) and legitimate session-attribution (suppress it). For machines
like M31 (session type-2 per `02 §3.3.4`) this distinction is load-bearing.

**This does not invalidate the Layer 4 redesign.** It means the check has a
systematic false-positive class that v4 §9.4 acknowledges but does not
structurally resolve.

### Concern B — "46 verified" is overstated; 13 named + ~32 unnamed SC-Vanilla machines are unverified against v4's new Layer 4

v4 §6.3.1 claims ~46 Day-1 strict candidates. The claim is that these machines
are expected to trivially pass. That is a well-reasoned expectation, but it is
explicitly contingent on a "pre-Phase-3 verification step" that runs Layer 4
against each machine. The new Layer 4 (Step B) is a **new check that did not
exist before v4**. No machine has been empirically verified under it yet.

The proposal only names 13 SC-Vanilla members explicitly; the remaining ~32 are
"plus the remaining machines with exact `{NormalRTPPreProcessor,
NormalSpinGenerator, NormalSpinValidator}` logicClassNames as identified during
Phase 3 manifest authoring." Those 32 are not named, not yet verified, and not
confirmed to have cached rawdata available. v4 §6.3.1 says the verification step
is required and estimated at 0.5 days, but it is pre-Phase-3 work, not in the
Phase 3 deliverable list. It is therefore easy to skip or defer.

The 46 count is a **target and an expectation**, not a verified result. v4
acknowledges this for M274 ("pending Layer 4 v4 re-verification") but presents
SC-Vanilla as trivially clean without equivalent caveat.

### Concern C — Override semantics for variant: what happens when underlying flips false→true AFTER variant declared override:false

v4 §5.5.7 specifies: a variant may declare `console_diagnostic_complete_override:
false` (regression valve). The resolver logic returns `False` whenever the
override is `False`, regardless of what the underlying's current flag is:

```python
if override is False:
    return False   # regression valve: variant found an edge case
```

This means: if M273 underlying is `false`, and later gets flipped to `true`
(edge case fixed, all 4 layers pass), and M273$WheelSelector$42$ already has
`override: false` — the variant **stays at false permanently**, even though
M273 is now verified complete. The resolver returns `False` unconditionally
on the override branch without checking whether the underlying's fix also
covers the variant's specific edge case.

To "un-override" the variant, someone must manually delete or toggle the
`console_diagnostic_complete_override` field from the variant manifest. v4
provides no signal or reminder that this manual step is required. Per
`feedback_no_silent_swallow.md`, silent omissions that require manual
follow-through create organizational debt.

This is a soft concern (the conservative direction is safe) but the spec
does not address the re-enablement path for a variant that was previously
in override.

### Concern D — Fleet-wide ~35-minute Layer 4 penalty on every fleet pull for unverified machines is unspecified at the system level

v4 §7.4 and §9.5 state that Step B runs for ALL machines on every fleet pull,
not just `complete: true` machines. The estimate is ~5s × 421 = ~35 min
cumulative sequential runtime, or less under parallelism. But the fleet-pull
concurrency model is unspecified. v4 §7.1 and §7.4 are explicitly deferred to
Critic v4 / Validator v4. This is an operational performance question that has
no answer yet in the proposal.

---

## §2 Verification: were the 3 must-resolves from Critic v3 actually addressed?

### M1 (HARD): Layer 4 must catch dispatch-routing bugs

**Critic v3 finding (§3 M1)**: v3 Layer 4 compared two readouts of the same
dict `payout_id_by_spin_type_total`. Lines 6493 (payouts_by_spin_type path) and
6446 (payout_ids_top20 path) both read from the same accumulator. If the
accumulator is wrong, both sides are equally wrong. Layer 4 was a self-
consistency check, not a correctness check.

**v4 response (§9.4)**: Step A captures `payout_id_by_spin_type_total` (the
analyzer's dispatch result). Step B independently iterates rawdata chunks without
calling any analyzer function — reads `R.SpinType` and
`PayoutIdToWinAmount.keys()` directly. Step C compares. The pseudocode is
explicit: "do NOT call any analyzer function" in Step B.

**Verdict: SUBSTANTIALLY ADDRESSED, with one residual (Concern A above)**. The
structural flaw from v3 is fixed. Step B genuinely bypasses the analyzer's
dispatch path. The M31 pid-8 motivating case is correctly handled. The residual
is the session-attribution false-positive class (acknowledged in the note field
but not structurally resolved). The core M1 issue is resolved; the residual is
a new edge case introduced by the fix.

### M2 (HARD): Day-1 strict mode must have members

**Critic v3 finding (§3 M2)**: v3 set all 421 to `false` at Phase 3 cutover,
with the flip mechanism deferred to "the implementation team." Phase 5's strict
policy was permanently dormant from day one.

**v4 response (§6.3)**: §6.3.1 enumerates ~46 Day-1 candidates (SC-Vanilla ~45
+ M274). §6.3.2 specifies flip criteria (4-layer pass + no known issues + audit
log). Phase 5's strict mechanism engages on day one for ~46 machines. §8.13
updates the out-of-scope note to acknowledge that criteria are now specified and
only operational ownership remains out of scope.

**Verdict: ADDRESSED with caveat (Concern B above)**. The mechanism is no longer
dormant by design. The caveat is that the 46 count is a target, not a verified
list, and the pre-Phase-3 verification step must actually be executed. But the
proposal correctly requires it and specifies the criteria. This is acceptable —
the v3 problem was "no plan, no criteria, no enumeration." v4 has all three.

### S1 (SOFT): Variant cascade asymmetry

**Critic v3 finding (§3 S1)**: v3 §5.5.4 said variants ARE the same machine
(justifying eager `analyzer_features` cascade), but v3 §5.5.7 said variants
have independent `console_diagnostic_complete`. Inconsistent stance.

**v4 response (§5.5.7)**: Flag now cascades eagerly from underlying to all
variants. Override allowed only `true → false` (regression valve). Resolver
logic specified. Validation rejects `override: true`. Schema rule 6 updated.

**Verdict: ADDRESSED**. The incoherence Critic v3 identified (same-machine for
parser, different-machine for completeness) is resolved. Both axes now cascade
eagerly. The residual in Concern C (re-enablement path after override) is a
new edge case, not a re-emergence of the v3 asymmetry.

---

## §3 Ten stress questions

---

### Q1: Layer 4 Step A independence — does it accidentally share helpers that would invalidate independence?

**Question**: Step A reads from `payout_id_by_spin_type_total`. Step B iterates
rawdata chunks directly. Is Step B genuinely independent, or does it use any
shared infrastructure (round-classification primitives, rule-resolution,
trigger-session detection) that would contaminate its independence from the
analyzer's dispatch path?

**Designer's likely answer**: Step B explicitly says "do NOT call any analyzer
function." It only calls `json.loads(chunk_path.read_bytes())` and iterates
`round_result.get("SpinType")` and `payout_id_to_win.keys()`. No rule
resolution, no round-classification call, no trigger-session computation. The
only shared infrastructure is the `sorted(rawdata_dir.glob("chunk_*.json"))`
call and standard library JSON parsing. That is independent.

**Verdict: ✓ adequately addressed** — per v4 §9.4 pseudocode, Step B's loop
body calls no analyzer functions. The independence claim is structurally
verifiable from the pseudocode. The concern is not about shared helpers in
Step B itself but about whether Step B's semantics match what the analyzer
*should* produce (see Q2 for the session-attribution case).

---

### Q2: Session-attribution false-positive — does Step B produce counts that are systematically different from what a correct analyzer would produce?

**Question**: Memory `feedback_session_semantics.md` states "bonus spin wins
are attributed to the paid spin that triggered them." Per `01 §3.5.2`,
`compute_trigger_sessions` groups free-spin rounds under their triggering
paid-spin bucket. If the analyzer's session attribution is working correctly,
`payout_id_by_spin_type_total` might have different (pid, ST) counts from the
naive rawdata ST field, specifically: pids that fire during free-spin ST=44
rounds might be attributed to the paid ST=43 bucket. Step B sees only raw
`R.SpinType` values. For machines with session-bonus grouping (e.g., M31,
which is explicitly the motivating case), Step B would show higher ST=44 pid
counts and lower ST=43 pid counts than the analyzer's (correct) dispatch.
Step C fires a false Layer 4 failure.

**Designer's likely answer**: The `note` field in the inconsistency output
(v4 §9.3 + §9.4 Step C) explicitly lists "(b) session-bonus grouping
re-attributes free-spin rounds to paid-spin bucket" as a possible cause. The
operator can distinguish this from a bug. For machines where session-grouping
is the expected behavior, the Layer 4 failure is an investigation prompt, not
an error. For `complete: false` machines it's warn-only, so the operator sees
it and investigates.

**Why this is insufficient**: The proposal does not specify how to resolve a
confirmed false positive. If Layer 4 fires on a machine with correct session-
attribution and the operator confirms it is not a dispatch bug, can Layer 4
be suppressed for that specific (pid, ST) pair? The answer is not in v4. For
a machine with known session-attribution semantics (e.g., any machine using
Type-1 or Type-2 trigger sessions per memory `reference_trigger_session_patterns.md`),
Layer 4 will fire on every analysis run with a false positive. The `complete:
true` → strict policy cannot be applied to such a machine until either (a) Step
B is session-aware, or (b) a per-machine exception mechanism exists. Neither is
specified.

**Verdict: ⚠ partial** — acknowledged in the note field but not structurally
resolved. Machines with session-attribution semantics cannot be declared
`complete: true` under v4 Layer 4 as specified without risking false-positive
strict errors on every run. This narrows the true Day-1 candidate pool (Session-
type machines in the SC-Vanilla cluster may have this issue if any bonus ST
is re-attributed). For pure single-ST SC-Vanilla machines it is a non-issue.

---

### Q3: Layer 4 edge case — pid 666 filter in analyzer vs Step B

**Question**: Per `03 §3.4.6` and `00_brief.md §3` commit `4cbcab2`, the
analyzer's filter changed from `st_win == 0.0` to `st_hits == 0` to keep
pid 666 (M31 scatter trigger, zero-win). Step B counts "existence in
`PayoutIdToWinAmount.keys()`" regardless of win amount. The v4 edge-case table
says "Step B counts the pid regardless of win amount." This seems consistent.
BUT: if the analyzer applies additional filtering or de-duplication logic to
`payout_id_by_spin_type_total` that Step B does not replicate (e.g., M99/M112
sub-round dedup per §9.7), Step C would fire a false positive because Step B
always includes the pid while the analyzer may have de-duped it.

**Designer's likely answer**: v4 §9.7 explicitly lists M99/M112 as "sub-round
dedup defect — Likely Layer 1 or Layer 4." The intent is that Layer 4 *should*
fire on these machines because the dedup behavior is a correctness issue, not
a feature. So the expected behavior for M99/M112 is Layer 4 fails (correctly
flagging the defect). The proposal does not treat these as false positives.

**Why it is partially unresolved**: The proposal's reasoning assumes that any
systematic difference between `payout_id_by_spin_type_total` and Step B's raw
count is a *bug*. But for machines where the analyzer deliberately applies
non-rawdata-aligned transformation (e.g., session-grouping, dedup, attribution),
Step B's "naive" count is *not* the correct reference. The proposal conflates
two cases: (a) dispatch routing bugs (real, should fail) and (b) intentional
transformation mismatches (false positives, should not fail). Both cases trip
Step C with the same mismatch signal.

**Verdict: ⚠ partial** — the M99/M112 case is handled as intended. The
broader class (any machine with intentional non-rawdata-aligned transformation)
is not distinguished from dispatch bugs. For the Day-1 SC-Vanilla cluster this
is benign because those machines have no such transformations. For non-SC-
Vanilla machines it is a live issue.

---

### Q4: Layer 4 Step B performance claim — is <5s for 414k spins realistic?

**Question**: The designer claims Step B adds <5s for 414k spins per addendum
v4 §1 Issue ① perf note. v4 §9.4 notes chunks are "already on local disk" and
the loop is "sequential JSON iteration with no heavy computation." Is this
realistic given the analyzer's chunk-loading behavior?

**Designer's likely answer**: `01 §3.1 Layer 2` documents `parse_chunk_response`
runs 2,354 to 3,961 lines (1,607 lines of code) per chunk. Step B's per-round
loop is ~20 lines of direct Python with no rule resolution. The main analysis
pass (with rule chains, feature extraction, BCM detection, trigger-session
computation) is orders of magnitude more expensive. A pure JSON iteration over
cached files with only `int(raw_st)` and `.keys()` should be much faster. 5s
for 414k spins seems plausible.

**Why it needs validation**: "Chunks are already on local disk" assumes the
main pass ran first. If Step B runs before the main pass (which it cannot by
design — Step A requires `payout_id_by_spin_type_total` from the main pass),
cold disk reads would dominate. Given main pass runs first and OS page cache
will retain chunk data in memory, the 5s estimate is reasonable *for warm cache
reads*. For machines with 1M+ spins (not 414k), Step B scales linearly. At 3M
spins it would be ~36s, not 5s. The estimate is per-machine-representative
(414k), not for outliers.

v4 §7.1 self-acknowledges this question as open. The designer explicitly flags
it for Critic v4 to probe.

**Verdict: ⚠ partial** — estimate is plausible for the representative case but
not bounded for large-rawdata machines. The `--skip-layer4-rawdata-scan`
escape hatch is mentioned as a mitigation. The 35-min fleet-total estimate
assumes parallelism matches per-machine subprocess model. Not validated.

---

### Q5: Day-1 46 candidates — are these verified or projected?

**Question**: v4 §6.3.1 names 13 SC-Vanilla machines explicitly and ~32 unnamed
additional ones ("target: all 45 per `02 §4.2`"). The unnamed 32 are "identified
during Phase 3 manifest authoring" — they do not exist yet. Layer 4 Step B is
a new check that has never run on any machine (it is newly specified in v4). No
machine has been empirically verified against v4 Layer 4. So the "~46 Day-1
strict candidates" is a projected count, not a verified count. v4 §6.3.1
requires a "pre-Phase-3 verification step" but this step is NOT in Phase 2's
deliverable list nor in Phase 3's formal deliverable list — it is described
alongside Phase 3 deliverables but listed separately from the numbered items
in §6.3.3.

**Designer's likely answer**: The expected outcome is "trivially pass" for SC-
Vanilla machines: single ST (no bonus), no required anchors, no bespoke rules.
Layer 4 Step B for a single-ST machine would see all rounds as the same ST,
and the analyzer's dispatch would match. Layer 2/3 are vacuously clean. The
expectation is probabilistically solid.

**Why it is insufficient**: If a single SC-Vanilla machine fails the
pre-Phase-3 verification step, the target drops from 46 to 45. If two fail, 44.
The drop from "46" to a lower number is acceptable only if the proposal
acknowledges the number is a target, not a guarantee. v4 does acknowledge this
for M274 ("pending Layer 4 v4 re-verification") but presents SC-Vanilla as
"expected outcome: pass trivially" without a parallel caveat. The distinction
matters because §6.5 Phase 5's opening sentence is "~46 machines have
`console_diagnostic_complete: true` from Phase 3" — if that number is lower
(say, 30 because the pre-verification found issues with some unnamed SC-Vanilla
machines), §6.5 overstates the day-1 coverage.

**Verdict: ⚠ partial** — Issue ② from addendum v4 is addressed (mechanism no
longer dormant, criteria specified, enumeration exists). The partial flag is
for the unverified 32 members and the absent verification deliverable from the
Phase 2/3 transition.

---

### Q6: Who runs the pre-Phase-3 verification for ~45 SC-Vanilla machines, and when?

**Question**: v4 §6.3.1 says "before setting `console_diagnostic_complete: true`
in any SC-Vanilla manifest, the implementation team runs `rtp_integrity.py`
(built in Phase 2) against each machine's most recent rawdata." `rtp_integrity.py`
is built in Phase 2. Phase 3 writes the manifests. The verification must happen
in the Phase 2→3 transition window. This is a 0.5-day estimate (v4 §7.3 via
§6.5 Phase risk summary). But Phase 3 risk is "MEDIUM — 4-7 (+0.5 for Day-1
verification)." The "+0.5 days" is noted in the phase table but not as a formal
deliverable item.

**Designer's likely answer**: The flip criteria in §6.3.2 govern this. Step 1
requires running the gate. The implementation team executes it before writing
manifests. The 0.5-day estimate is acknowledged.

**Why it is insufficient**: Phase deliverables are enumerated lists. The
pre-Phase-3 verification step is NOT in the §6.3.3 numbered deliverable list.
It is described in §6.3.1 prose. An implementer executing Phase 3 from the
deliverable list would write manifests for all 421 machines, set the ~45 SC-
Vanilla to `true` based on the expectation, and skip the verification. The
criterion to run `rtp_integrity.py` first is buried in §6.3.1 prose, not
enforced by a gating deliverable.

**Verdict: ✗ not addressed** — the pre-verification step is architecturally
specified but not procedurally gated in the Phase 3 deliverable list. It can
be omitted without violating any stated deliverable. The 46 machines could ship
`true` without Layer 4 verification.

---

### Q7: Variant re-enablement path — what happens when underlying flips false→true after variant has override:false?

**Question**: v4 §5.5.7 resolver logic returns `False` unconditionally when
`override is False`. This means a variant with `override: false` stays at
`complete: false` even after the underlying is fixed and flipped to `true`.
To re-enable the variant, someone must manually remove or toggle the override.
v4 does not specify this re-enablement workflow, does not require a ticket/issue,
and does not require updating or removing the `_comment` field.

**Designer's likely answer**: The override is intentionally "sticky conservative"
— the variant stays at false until a human explicitly removes the override. This
is correct conservative behavior: the variant exposed a specific edge case; the
underlying being fixed does not automatically mean the variant's edge case is
also fixed.

**Why it is partially unresolved**: The override is sticky but the mechanism
to *release* the sticky state is unspecified. Specifically:
1. There is no manifest validation rule that flags "underlying is `true` and
   this variant has `override: false` for more than X days."
2. There is no required relationship between the `_comment` (which says "bespoke
   rule pending") and the actual rule being added. A variant can sit with
   `override: false` indefinitely after the underlying's fix without any prompt.
3. For the 85-variant case (M273), if one variant has `override: false`, an
   operator looking at the fleet would see 84 variants strict and 1 warn-only
   with no obvious prompt to investigate whether the edge case was already fixed.

**Verdict: ⚠ partial** — the override semantics are correctly conservative and
the resolver logic is sound. The gap is the re-enablement lifecycle: no reminder
mechanism, no validation check that prompts audit of stale overrides. Acceptable
for a first-iteration spec (this is a soft concern by v4 addendum classification),
but left as an organizational footgun.

---

### Q8: Was Critic v3 M1 ACTUALLY fixed — does Step B genuinely not touch payout_id_by_spin_type_total?

**Question**: The core of Critic v3 M1 was that both sides of the check read
from `payout_id_by_spin_type_total`. v4's fix is that Step B does not touch this
dict. Verify from the pseudocode that Step B has no hidden reference to any
analyzer-maintained state.

**Evidence from v4 §9.4 pseudocode**:
Step B's loop body:
1. `chunk = json.loads(chunk_path.read_bytes())` — pure disk read, no analyzer state
2. `for robot_response in chunk["response"]` — pure iteration
3. `raw_st = round_result.get("SpinType")` — raw field extraction
4. `payout_id_to_win = round_result.get("PayoutIdToWinAmount", {})` — raw field extraction
5. `for pid_str in payout_id_to_win.keys()` — key iteration, no accumulator
6. `fresh_dispatch[pid][st] += 1` — local dict, no shared state

Step A reads `payout_id_by_spin_type_total.items()` and copies into a local
`analyzer_dispatch` dict. Step B builds `fresh_dispatch` independently. The
two are compared in Step C. Neither Step B nor Step C references
`payout_id_by_spin_type_total` — only Step A does.

The M31 pid-8 example in §9.4 explicitly traces: "v3 Layer 4: reads
`payouts_by_spin_type[ST43].rows[8].hit_count = 33167` AND
`payout_ids_top20.rows[8].spin_type_breakdown[43].count = 33167` → they agree
→ Layer 4 PASSES → bug invisible." Then: "v4 Layer 4 Step B: counts rawdata
rounds independently → `fresh_dispatch[8][43] = 22370`, `fresh_dispatch[8][44]
= 10797`" → Step C fires.

**Verdict: ✓ adequately addressed** — the pseudocode is unambiguous. Step B
has no reference to analyzer state. The specific v3 M1 failure mode (same-dict
comparison) is eliminated. The residual session-attribution false-positive is a
new concern, not a re-emergence of the v3 bug.

---

### Q9: Was Critic v3 M2 ACTUALLY fixed — is the mechanism no longer permanently dormant?

**Question**: v3 had zero Day-1 members. v4 claims ~46. But the 13 explicitly
named SC-Vanilla members could in principle ship `true` from day one, giving
the mechanism at least 13 real strict machines even if the unnamed ~32 are
verified more slowly. Does v4's mechanism engage on day one with some known
count?

**Evidence**: v4 §6.3.1 names M1, M14, M37, M101, M105, M127, M13, M135, M137,
M139, M142, M143, M145 as SC-Vanilla members "rawdata-confirmed, per `02 §4.2`
and `02 §3.5.3 Tier-1`." These 13 are explicitly identified in Wave 1 evidence
(`02 §4.2`). For these 13, the eligibility basis is concrete: production history,
no `_unattributed_*` rows, Tier-1 rawdata schema. If Layer 4 is executed against
these 13 before Phase 3, all 13 can ship `true` with high confidence.

The proposal's §6.5 Phase 5 diff explicitly states: "v3: 0 machines have
`console_diagnostic_complete: true` on Phase 5 day 1. v4: ~46 machines have
`console_diagnostic_complete: true` from Phase 3." The mechanism engages
immediately. M274 requires separate Layer 4 v4 verification (explicitly noted).

**Verdict: ✓ adequately addressed** — the v3 permanent-dormancy risk is
resolved. Even if the target of 46 is not fully met (some unnamed SC-Vanilla
or M274 fail pre-verification), at minimum the 13 named SC-Vanilla members
provide a non-zero starting population. Phase 5's strict mechanism engages on
day one for at least 13 machines. The risk that Critic v3 Concern 1 identified
(organizational forgetting, mechanism never engages) is substantially mitigated.

---

### Q10: Was Critic v3 S1 ACTUALLY fixed — is variant cascade now symmetrical and without new asymmetries?

**Question**: v3's asymmetry was: `analyzer_features` cascades eagerly (variants
= same machine), but `console_diagnostic_complete` was per-variant (variants =
different machine for completeness). v4 §5.5.7 makes the flag cascade eagerly.
Does v4 introduce any new asymmetry between `analyzer_features` cascade and
`console_diagnostic_complete` cascade?

**Evidence from v4**:
- §5.5.4–§5.5.5: `analyzer_features` cascades eagerly from underlying. Hash
  composition consequence: all 86 hashes flip when underlying changes.
- §5.5.7: `console_diagnostic_complete` cascades eagerly from underlying. Same
  blast-radius implication explicitly stated: "Flipping the underlying to `true`
  also flips all 85 variants."
- Override direction: `override: false` (regression valve) — matches the concept
  of "variant data revealed a parser edge case" which logically also implies
  the variant should be in `complete: false`.
- §5.6 rule 6 updated: `override: true` is a validation error.
- `resolve_completeness()` pseudocode correctly reads from `underlying_manifest`.

The fields that do NOT support `per_mode_overrides` now explicitly include
`console_diagnostic_complete` (§5.5.6 table), consistent with the per-machine
(not per-mode) nature of the flag.

**One remaining nuance**: `console_diagnostic_complete` is a per-machine flag,
not a per-mode flag. `analyzer_features` can vary per mode via
`per_mode_overrides`. So the cascade symmetry holds at the machine level but
`analyzer_features` has finer granularity. This is not an asymmetry in the
problematic sense — a machine's completeness declaration is coarser than its
feature declaration, which is intentional.

**Verdict: ✓ adequately addressed** — the v3 incoherence is closed. Both cascade
eagerly. Override allowed only `true → false`. The per-machine vs per-mode
granularity difference is intentional and not a new asymmetry.

---

## §4 Migration risk inventory

### Phase 1 risks (unchanged from v3; no v4 changes)

- **R1.1 Global-to-injection refactor**: `RAWDATA_ROOT` (11 references per
  `03 §4.1`) and 33 module globals. Per memory `feedback_subprocess_import_suicide_and_module_globals.md`,
  these have previously caused production-critical bugs. Phase 1 removes them.
  Rollback is trivial revert per phase table.

- **R1.2 Six deduplication extractions**: If any of the 6 duplicated patterns
  (`03 §4.2`) have subtle behavioral differences between their production and
  virtual implementations, Phase 1's consolidation may silently change behavior
  for one of them. No regression test is specified for "virtual behaves
  identically to production on same input."

### Phase 2 risks (Layer 4 new in v4)

- **R2.1 Layer 4 v4 implementation**: Step B's rawdata scan is new code. If it
  has a bug (e.g., wrong nesting level in `chunk["response"]` iteration), it
  silently miscounts `fresh_dispatch` → false positives or false negatives.
  All machines in warn-only at this phase, so false positives are operator noise
  not system failures. False negatives (missed dispatch bugs) continue in
  silence. No independent test against a known-correct dataset is specified.

- **R2.2 `rtp_integrity.py` integration**: Phase 2 builds the gate code but
  does not flip any machine to strict. Risk: regressions in `rtp_integrity.py`
  that cause it to fail silently (swallowed exception) or produce incorrect
  pass/fail results would not be caught at Phase 2 because all machines are
  warn-only and nobody is looking at warn-only output systematically.

- **R2.3 Rollback of Phase 2**: Per phase table, "per-feature revert." If
  `rtp_integrity.py` is coupled to feature extractors, rolling back one
  feature while keeping `rtp_integrity.py` active could produce incorrect
  Layer 1/2 results. The decoupling contract is not specified.

### Phase 3 risks (Day-1 candidates new in v4)

- **R3.1 Pre-Phase-3 verification is not gated**: As flagged in Q6, the
  pre-verification step is described in prose but not a formal deliverable.
  If skipped, machines ship `true` without Layer 4 evidence.

- **R3.2 SC-Vanilla member identification gap**: 32 of the 45 SC-Vanilla
  members are unnamed ("identified during Phase 3 manifest authoring"). The
  taxonomy's SC-Vanilla definition (per `02 §4.2`) is pattern-matched on
  `logicClassNames` — if any of the ~32 unnamed machines have a logicClassNames
  that PARTIALLY matches but has an extra class not in the SC-Vanilla definition,
  they would fail pre-verification. v4 does not specify what happens in this case:
  does the machine ship `false`? Does it get escalated? The fallback behavior is
  not stated.

- **R3.3 M274 Layer 4 re-verification dependency**: M274 ships `true` only after
  "Layer 4 v4 Step B re-verification." This is noted as pending. If this
  verification is not done before Phase 3 cutover (due to time pressure), M274
  ships `false`, reducing the Day-1 count to ~45. Not a failure mode, but a
  known dependency that could cause miscounting in §6.5's Day-1 claim.

- **R3.4 Clean-break rollback**: Per phase table, "manifest ignored on rollback."
  But if Phase 3 cutover overwrites the DB with a new `effective_analyzer_version`
  for all 421 machines, rollback requires reverting ALL 421 manifest-wired
  version columns simultaneously. A partial rollback (some machines reverted,
  others not) would create a mixed-state fleet where some machines use new
  effective versions and others use old ones. The DB column rollback mechanism
  is not specified.

### Phase 5 risks (unchanged from v3; strict-policy flip)

- **R5.1 Day-1 ~46 machines under strict**: The 46 machines will raise
  (not warn) on any Layer 1-4 failure immediately at Phase 5. If a bug in
  `rtp_integrity.py` produces false-positive failures (e.g., the Step B
  session-attribution case from Q2), all 46 machines raise simultaneously on
  the first fleet pull after Phase 5 deploy. Rollback: "policy flip reverts
  globally" — but this is a single config flag, not a code revert. Fast
  rollback to warn-only is available. This is acceptable risk management.

- **R5.2 Stale `complete: true` machines after rule changes**: If a universal
  feature (e.g., `payouts_by_spin_type.py`) is updated post-Phase-5, and the
  update introduces a dispatch change, all `complete: true` machines that use
  that feature will fail Layer 4 on the next fleet pull. This is correct
  behavior (the check caught the regression) but the blast radius is all
  `complete: true` machines simultaneously, which could be disruptive if the
  universal feature update is intentional. The proposal does not specify how
  intentional universal-feature dispatch changes interact with strict Layer 4
  checking.

---

## §5 Edge cases not covered

**E1 — Multi-mode machine where one mode has session-attribution and another does not**: v4's `console_diagnostic_complete` is per-machine (no per-mode override per §5.5.6). Layer 4 Step B would produce false positives for the session-attribution mode. The machine cannot be declared `complete: true` even if all non-session-attribution modes are clean. The per-mode granularity gap is acknowledged ("Fields that do NOT support `per_mode_overrides`: ... `console_diagnostic_complete`") but the consequence for mixed-mode machines is not discussed.

**E2 — Step B chunk iteration order vs analyzer's merge order**: v4 §9.4 Step B sorts chunks by `chunk_path` (alphabetically). The analyzer's main pass iterates chunks in a defined order (per `01 §3.1`). If chunk ordering produces different per-robot interleaving (e.g., robots whose rounds span chunk boundaries), the per-round pid count in Step B would match the analyzer's count exactly only if both traverse the same rounds in the same "which SpinType gets this round" sense. For session-aware attribution this is order-dependent. The proposal does not discuss whether Step B's sort order must match the analyzer's traversal order.

**E3 — SpinType value `43.0` (float) in rawdata**: v4 §7.2 self-identifies this as an open question. The pseudocode does `int(raw_st)` which handles string `"43"` but not float `43.0` (would produce `TypeError` on `int(43.0)` → no, Python `int(43.0)` = `43`; but `int("43.0")` → `ValueError`). If rawdata has `"43.0"` as a string representation of SpinType, the `try: st = int(raw_st)` block would raise `Layer4Error` with "SpinType field invalid." This is an unusual but real rawdata format: per `01 §2.1`, rawdata is JSON and SpinType could be serialized as number or string. If the analyzer handles `"43.0"` via a different normalization path than Step B, there would be false attribution mismatches.

**E4 — Machines with 0 chunks on disk (206 of 421 without cached rawdata per `03 §3.4`)**: v4 §9.4 handles this: "Step B detects 'no rawdata chunks found' and emits specific error." But if 215 of 421 machines (421 - 206 = 215 without rawdata) emit this error on every fleet pull, operators see 215 Layer 4 failures every fleet pull in warn-only mode. The proposal does not specify how "Layer 4 cannot run: no rawdata" is presented vs "Layer 4 ran and found mismatch." Both are in the same Layer 4 failure category per §9.3. Operators may conflate them.

**E5 — New feature plugin that re-dispatches pids to different ST buckets**: If a new feature plugin (e.g., `bespoke_m250_grid.py` per §9.7) explicitly re-routes certain pids from one ST bucket to another as part of correct analysis, `payout_id_by_spin_type_total` would reflect the re-routed distribution. Step B would not reflect it (reads rawdata SpinType directly). Layer 4 would fire. The machine could never be declared `complete: true` for that mode without suppressing Layer 4. The proposal does not specify whether bespoke features are allowed to re-route dispatch, and if so, how Layer 4 accommodates them.

**E6 — Phase 3.5 gap: are the 46 machines verified before or during Phase 3?**: The proposal describes Phase 3 deliverables starting with "write 421 per-machine manifests." The verification step for the 46 Day-1 candidates is described as "pre-Phase-3" but there is no Phase 3.5 in the phase framework. The 0.5-day cost is added to Phase 3's estimate as "+0.5," but the logical placement (after Phase 2 completes `rtp_integrity.py` and before Phase 3 writes manifests) is implicit, not explicit. Implementers may execute Phase 3 manifest writing before the tool is ready.

---

## §6 Hidden assumptions

**H1 — Session-attribution is not a dispatch-routing bug**: v4 Layer 4 assumes
that any mismatch between `payout_id_by_spin_type_total` and rawdata's SpinType
counts is a dispatch routing bug. This is only true for machines without
session-grouping semantics. Per memory `feedback_session_semantics.md`, session
grouping is explicitly by design for bonus-spin machines. The assumption that
"analyzer dispatch should exactly match rawdata SpinType counts" is violated by
correct session-attribution behavior.

**H2 — SC-Vanilla membership is stable**: v4 assumes the ~45 SC-Vanilla machines
identified in `02 §4.2` have not drifted between Wave 1 (taxonomy audit) and
Phase 3 (manifest authoring). If any machine was reconfigured to add a bonus
feature between the taxonomy audit and Phase 3, it would no longer be SC-Vanilla
but would not be flagged until Layer 4 runs on fresh rawdata. The assumption
is operationally reasonable (machines don't change logicClassNames often) but
is not validated by v4 tooling at Phase 3 time.

**H3 — Phase 2 `rtp_integrity.py` is correct before Phase 3 uses it**: The
pre-Phase-3 verification relies on `rtp_integrity.py` being correct (no false
positives, no false negatives). If Phase 2's `rtp_integrity.py` has a bug in
Step B, the verification step would either falsely clear machines (false negative:
incorrect pass → machine ships `true` but would fail correctly implemented Layer
4) or falsely flag SC-Vanilla machines (false positive: machines that should be
`true` ship `false`). There is no stated acceptance criterion for `rtp_integrity.py`
correctness before it is used for flip decisions.

**H4 — `compute_trigger_sessions` result is NOT reflected in `payout_id_by_spin_type_total`**: The Layer 4 design implicitly assumes that session-attribution (from `compute_trigger_sessions`) does NOT feed back into `payout_id_by_spin_type_total`. Per `01 §3.5.2`, trigger sessions group free-spin wins under the triggering paid spin's session. But `payout_id_by_spin_type_total` tracks per-round pid counts by SpinType, not per-session. If this assumption holds (the dict counts rounds, not sessions), then Step B's per-round count should match the dict for machines without session re-attribution in `payout_id_by_spin_type_total`. The proposal does not explicitly verify this assumption from source code. It is an architectural assumption.

**H5 — Parallelism covers the 35-min fleet-total Layer 4 cost**: v4 §7.4 notes
that per-machine parallelism means the fleet-total is not additive. But the
degree of parallelism (number of concurrent subprocesses) depends on the
deployment hardware and the `BatchRunManager` configuration, neither of which
is specified in the proposal. The "~35 min parallelized" claim is ungrounded.

---

## §7 Alternatives double-check

### Alternative B (lightweight per-feature SCHEMA_VERSION sidecar) — rejection verified

v4 §2.2 cites: B cannot implement Layer 4 rawdata cross-check (no per-machine
completeness signal → no `complete: true`/`false` policy). This is structurally
correct. B's sidecar approach is a frontend-schema concern; it has no hook for
a rawdata-level integrity check. The rejection rationale is stronger in v4 than
v3 because v4's Layer 4 is a concrete independent algorithm that B cannot
implement (no per-machine manifest to drive the check). **Rejection: verified.**

### Alternative C (full per-machine analyzer plugin tree) — rejection verified

v4 §2.3 cites: C eliminates sharing; v4's §5.5.7 variant cascade goes in the
opposite direction. Per `02 §4.2`, SC-Vanilla 45 machines sharing a single
vanilla feature set would under C require 45 separate plugin files. Per memory
`feedback_no_parallel_panel_impl.md`, parallel implementations for identical
behavior are an anti-pattern. Additionally, per §1.4, the blast radius for a
universal feature edit under C is still 421 machines (C doesn't solve it either,
and introduces maintenance overhead). **Rejection: verified.**

Note: v4 does not explore a **Alternative D — Session-aware Layer 4** (a variant
of the Layer 4 algorithm that accounts for session-attribution semantics). This
might address the Concern A / Q2 false-positive issue. The omission is not a
problem for the current iteration (the false-positive concern is newly surfaced
by this critique) but is worth flagging for the designer's next pass.

---

## §8 Verdict

**APPROVE-WITH-REVISIONS**

The 3 must-resolves from Critic v3 are substantially addressed:

- **M1 (Layer 4 correctness)**: Core fix is structurally sound — Step B is
  genuinely independent of `payout_id_by_spin_type_total`. The M31 pid-8
  motivating case is demonstrably catchable. **Residual issue**: session-
  attribution false-positive class (Concern A / Q2) is acknowledged but not
  resolved. This is a new surface, not a re-emergence of M1.

- **M2 (Day-1 candidates)**: Mechanism is no longer dormant. 13 named SC-Vanilla
  members provide a minimum non-zero baseline. Flip criteria specified. **Residual
  issue**: pre-Phase-3 verification step is not in the formal Phase 3 deliverable
  list (Q6 / E6), making it skippable. This is a procedural gap, not a design
  gap.

- **S1 (variant cascade)**: Symmetry achieved. Both `analyzer_features` and
  `console_diagnostic_complete` cascade eagerly from underlying. Override allowed
  only `true → false`. **Residual issue**: re-enablement path for stale
  `override: false` variants after underlying fix is unspecified (Q7).

**Specific change requests before final APPROVE**:

1. **(HARD, required before APPROVE)** — §6.3.3 deliverable list must include
   as item 0: "Run `rtp_integrity.py` against each Day-1 candidate machine;
   record pass/fail per machine; any SC-Vanilla machine that fails Layer 4 ships
   `false`, not `true`. Record results in Phase 3 commit message." This gates
   the pre-verification step as a formal deliverable, not prose advice.

2. **(MEDIUM, should-fix)** — §9.4 edge-case table must add a row for the
   session-attribution false-positive case: "Analyzer uses session-bonus
   grouping (Type-1 or Type-2 trigger sessions) — pids fired during bonus ST
   rounds are attributed to paid ST bucket in `payout_id_by_spin_type_total`.
   Step B counts per raw SpinType field, not per session. Mismatch is expected
   and not a dispatch routing bug. Detection: check if trigger_session_pattern
   is non-null in manifest; if so, expected ST-grouping discrepancy for trigger-
   session pids is not a Layer 4 failure." Until this is resolved, any machine
   with `trigger_session_pattern != null` cannot be declared `complete: true`
   under strict Layer 4 without false-positive strict errors.

3. **(SOFT, nice-to-fix)** — §5.5.7 should add one sentence: "When the
   underlying machine's flag is flipped from `false` to `true`, any variant
   manifest carrying `console_diagnostic_complete_override: false` should be
   audited to determine whether the specific edge case that triggered the override
   was resolved by the same fix. A stale override leaves the variant in warn-
   only mode indefinitely." A manifest validation lint rule that flags variants
   with `override: false` whose underlying is `true` for more than X days would
   formalize this.

---

```
arch-critic complete (v4).
- Top concerns: 4 (A session-attribution false-positive / B 46-candidate unverified /
  C override re-enablement path / D fleet Layer-4 perf unspecified)
- Stress questions: 10 (verdict: 4 ✓ / 4 ⚠ / 2 ✗)
- Migration risks flagged: 9 (across 4 phases)
- Edge cases not covered: 6
- Hidden assumptions: 5
- Must-resolves from v3: M1 ✓ (with residual) / M2 ✓ (with procedural gap) / S1 ✓
- Verdict: APPROVE-WITH-REVISIONS
  - 1 HARD change request (pre-verification gated as formal deliverable)
  - 1 MEDIUM change request (session-attribution false-positive in §9.4 edge-case table)
  - 1 SOFT change request (variant override re-enablement lifecycle note)
- Output: session_artifacts/_arch/05_critique_v4.md
```
