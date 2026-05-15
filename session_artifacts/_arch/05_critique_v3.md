# Adversarial Critique v3 — Wave 2 Architecture Proposal v3

> Wave 3 v3 / arch-critic. Hostile review of `04_architecture_proposal_v3.md`
> (1261 lines, focused revision of v2 — operator-diagnostic reframe + Layer 4
> + `console_diagnostic_complete` flag + Phase 2 gate construction + variant
> justification). Per `.claude/agents/arch-critic.md`: 10+ stress questions,
> migration risk inventory, edge cases not covered, hidden assumptions,
> alternatives rejection double-check, final verdict. Critique, no redesign.
>
> Date: 2026-05-15
> Inputs: `00_brief.md` + `00_brief_v2_addendum.md` + **`00_brief_v3_addendum.md`**
> (the v3 contract), `01_pipeline_map.md`, `02_taxonomy.md`,
> `03_coupling_audit.md`, `05_critique.md` (v1; 17 questions), `05_critique_v2.md`
> (v2; 18 questions, 6 must-resolves; my previous output), `06_validation_v2.md`
> (clean APPROVE), `04_architecture_proposal_v3.md` (THE TARGET).
>
> Convergence trajectory: v1 critique = 11 must-resolves. v2 critique = 6
> must-resolves. v3 should be ≤ 3 or full APPROVE.

---

## §1 Top concerns

### Concern 1 — Phase 5 day-1 reality: zero strict machines because Phase 3 set all 421 to `false`

v3 §5.5.3 explicit: "All 421 machines start `console_diagnostic_complete: false` at
Phase 3 cutover. Per-machine flip to `true` happens as machine rules are verified
clean by some QA pass (out of scope for v3 — implementation team handles)."

v3 §6.5 Phase 5 deliverable 1: "Policy flip in `rtp_integrity.py`: when
`manifest.console_diagnostic_complete == true`, layer failures raise; when
`== false`, warnings only."

Compose these two: **on the day Phase 5 ships, there are zero machines where
the strict-error policy actually fires.** Every report stays in warn-only mode.
Phase 5's "policy flip" is a no-op until someone (the unnamed "QA team" per
§8.13) starts flipping individual flags.

This is structurally correct per addendum v3 §2 must-resolve #6 and per the
v2-critique Concern 5 resolution — it eliminates the 22-red-banners day-1
problem. But it raises a different problem: **the proposal ships a
strict-default mechanism that has zero strict members on day one and provides
no spec for when (or whether) strict members will accumulate**. v3 §8.13
explicitly defers the flip mechanism to "the implementation team" without
naming roles, criteria, or schedule.

Cite v3 §8.13: "Which team owns flip decisions (QA / operator / slot-* team /
arch team)" — left open. "What verification triggers a flip" — left open.
"Workflow for batch flipping" — left open. "Tooling for the flip workflow" —
left open.

The architectural risk: a year after Phase 5 ships, the system is fully
deployed but **no machine has ever been flipped to `true`**, because the flip
process was never specified and nobody owns it. The strict-error gate is
permanently dormant. Per addendum v3 §1 "Console-correctness is the
precondition for the whole architecture's diagnostic value" — if no machine
is ever declared `complete: true`, the architecture's main correctness
mechanism (strict error) never engages. Operators always see warnings, learn
to ignore them (alert fatigue), and v3 collapses to v0 effective behavior:
silent fallback under another name.

This is the kind of organizational footgun where "out of scope" loads more
weight than it can carry. The proposal should at minimum spec a **verification
criterion sketch** ("a machine flips to `true` when these N rawdata-driven
gates pass on a representative sample, signed off by [role]") even if the
implementation is genuinely outside v3 scope.

Per 02 §4.2 ~45 SC-Vanilla machines have been in production for years with no
known issues — they are obviously flippable. M274 is empirically clean per
Validator v2 §2.6 live measurement. These could be flipped on Phase 5 day 1
under a minimal verification criterion (e.g., "4 layers PASS on most recent
fleet pull"). v3 doesn't do this; it punts.

**Verdict signal**: structurally consistent, operationally hand-wavy. The
defer-to-QA carve-out is the single biggest unspecified item in v3.

### Concern 2 — Layer 4's "mechanical equality" claim is too strong; both fields trace back to the same accumulator

v3 §9.2 Layer 4: "Both A and B are derived from the same rawdata SpinType
field via the same `payouts_by_spin_type` feature. Equality is mechanical —
they're two presentation slices of the same accumulator."

I verified by reading `fresh_slotlab/player_impact_analyzer.py:6438-6509`:

- `payouts_by_spin_type[label].rows[pid].hit_count` (line 6493) reads from
  `payout_id_by_spin_type_total[str(pid)][st_int]`.
- `payout_ids_top20.rows[pid].spin_type_breakdown[N].count` (line 6446) reads
  from `st_hits.items()` where `st_hits = payout_id_by_spin_type_total[str(pid)]`.

**Both sides read from the same dict, `payout_id_by_spin_type_total`.** They
are not "two derivations from the same rawdata" — they are two READOUTS of
the same in-memory tally. If the dict is wrong, both sides are equally wrong
(because they read the same wrong dict). They will agree, and Layer 4 will
pass, and the bug will be invisible.

The case that addendum v3 §2 must-resolve #2 wanted to catch — "pay_id 8
fires 33,167 times: rawdata shows 22,370 in ST=43 (paid) + 10,797 in ST=44
(free)... if console's logic mistakenly attributes all 33,167 to ST=43... the
per-ST breakdown is silently wrong" — is a bug at the **dispatch level**
(routing rounds into ST buckets during `parse_chunk_response`). Both
`payouts_by_spin_type` and `payout_ids_top20.spin_type_breakdown` consume
the dispatched bucket counts; if the dispatch is wrong, both reflect the
wrong dispatch. **Layer 4 as currently specified cannot catch this.**

To catch it, Layer 4 would need a **second derivation path from the same
raw input** — for example, recomputing `(pid, ST)` counts directly from
the raw `roundResult` list during a verifier pass, and comparing against
the analyzer's `payout_id_by_spin_type_total`. That's a different and harder
implementation than what §9.2 describes.

v3 §7.3 partially acknowledges this: "is there any analyzer path where these
two derived values could legitimately differ... Tentative answer: per v2 §10
+ addendum v3 §2 reframe, both values are computed by the same feature's
`extract`/`reduce`/`emit` path." The designer's own tentative answer is
"they shouldn't differ because they use the same code path" — which is
exactly the problem. If they use the same code path, the check is a
self-consistency assertion (will always pass if the code path is internally
consistent, regardless of whether the code path is correct).

**Layer 4 catches**: a renderer-level bug where two summary fields are
populated from different code paths and one diverges. (E.g., if a future
refactor splits the emitter so `payouts_by_spin_type` reads from accumulator
X and `payout_ids_top20.spin_type_breakdown` reads from accumulator Y, and
X/Y disagree, Layer 4 fires.)

**Layer 4 does NOT catch**: the M31 pid-8 case described in addendum v3 §2.
The dispatch bug puts wrong values into the shared accumulator; both readers
see consistent-but-wrong.

This is a real spec gap. The reframe wanted "catch within-pid mis-attribution
between SpinTypes" and Layer 4 as drawn doesn't deliver it for the
representative motivating example.

### Concern 3 — Variant cascade eager + `console_diagnostic_complete: false` for new variants creates the same operational problem just renamed

v3 §5.5.5 makes variant cascade eager: "Hash-composition consequence: when
M273.json's manifest changes, all 86 hashes (1 underlying + 85 variants)
flip." v3 §5.5.7 note: "A variant can be `console_diagnostic_complete: false`
(still being built) even if its underlying is `true`, because variant-specific
data may have edge cases the underlying didn't surface."

Stress test the operator's path. M273 underlying has been verified clean by
QA (flip to `true`). Operator now creates a new variant
`M273$NewSelector$0$.json` with `inherits_from: "M273.json"`. New variants
ship with `console_diagnostic_complete: false` per the §5.5.7 stance. They
inherit ALL the same analyzer features (eager cascade) but warn-only on
integrity layers.

What's the operator workflow now?
1. The variant gets sampled. It has variant-specific data.
2. The variant's manifest is structurally identical to underlying's (inherits
   from M273.json, no overrides).
3. The variant's Layer 1-4 checks should produce the same results as
   underlying for the same kind of mistakes — because parser is identical.
4. Yet variant is `false` (warn-only). Underlying is `true` (strict).
5. Same parser, same data shape, different policy. **Why?**

Per v3 §5.5.7 the reason is "variant-specific data may have edge cases the
underlying didn't surface". But the parser is the same; the rawdata is what
varies. So the operator is left to discover variant-specific data edge cases
manually, by reading warnings. This is exactly what v2's threshold gate was
doing — letting silent issues sit until someone notices.

Worse: per §5.5.5 the variant fanout means 85 variants of M273 all warn-only
even after M273 is strict. They could all be silently wrong. They get
warnings, not errors. They go un-investigated. Operator sees 85 yellow
banners and tunes them out.

The fix should be obvious from the v3 framing: if variant ARE the same
machine (per §5.5.4 "parser sharing is by definition"), then their
`console_diagnostic_complete` should also inherit from underlying. v3 §5.5.7
explicitly rejects this ("the flag is per-variant, not inherited") on the
grounds that variant-specific data may differ. But "rawdata may differ" is
true for **every** machine being added — it's the universal case, not a
variant-special case.

The framing is incoherent: §5.5.4 says variants ARE the same machine for
parser purposes (so `analyzer_features` cascades eagerly), but §5.5.7 says
variants are NOT the same machine for completeness purposes (so the flag
doesn't cascade). The first claim is leveraged for hash composition
soundness; the second is reserved as a workflow escape hatch. Pick one.

If variants are the same machine: flag should inherit. If they aren't: don't
eager-cascade analyzer_features. Currently v3 takes both stances depending on
which is more convenient.

### Concern 4 — The "all 421 start false" cutover creates an [INCOMPLETE] permanent state for the safe-vanilla majority

Per v3 §5.5.3 every M1 / M14 / M37 (the 45 SC-Vanilla machines per `02 §4.2`)
ships with `console_diagnostic_complete: false`. Per v3 §6.5 Phase 5
deliverable 3 the UI shows "yellow [INCOMPLETE] badge" for these.

**Reality check from `02 §4.2`**: SC-Vanilla is 45 machines that have been in
production for years with no known correctness issues. M14 is explicitly the
user's validation machine per memory `user_testing_machine.md` ("mode 1 RTP
精准监控"). Validator v2 §2.6 walks M274 live data and shows all 4 layers
pass empirically.

Post-Phase-5 deploy, the user opens the UI and sees:
- M14 mode 1 — yellow [INCOMPLETE] banner (because flag is false by default)
- M1 mode 1 — yellow [INCOMPLETE] banner
- M274 mode 1 — yellow [INCOMPLETE] banner (despite 4-layer-clean per
  Validator v2)
- ... 421 banners total

Per addendum v3 §1 the console is the operator's diagnostic tool — "Console
must analyze rawdata correctly so its diagnostic signals are trustworthy."
But the signal "[INCOMPLETE]" on a perfectly-working M14 mode 1 is the OPPOSITE
of trustworthy. The operator learns to disregard the warning because they
know it's noise on at least the 45 SC-Vanilla machines.

This is the **default-to-warning-everywhere** anti-pattern. The signal
becomes worthless when it triggers on machines that are obviously fine.

v3 §6.5 deliverable 4 says "the operator (or QA team) flips
`console_diagnostic_complete` to `true` for machines whose rules are verified
clean. The known-broken triage table (§9.7) is illustrative; comprehensive
triage is QA's task." But comprehensive triage of 421 machines is a months-
long project. During that window, operators are in front of 421
[INCOMPLETE] banners.

A minimum proposal would be: identify the obvious-safe machines (SC-Vanilla
+ M274 + any with 4-layer empirical pass) and ship them `true` at Phase 3
cutover. v3 doesn't do this — it explicitly says all 421 start `false`, no
carve-outs. Per addendum v3 §2 must-resolve #6 user said "out of scope for
v3", but the cutover default is in v3 scope and v3 picks the maximally
conservative option (all false). This is the user explicitly asking
"strict-when-unspecced" again (the v2 footgun) and getting "warn-when-
unspecced" by default everywhere instead.

### Concern 5 — Phase 2 timing: 12 bespoke plugins + RTP gate code + Layer 4 + 6-workflow demo in 12-16 days

v3 §6.7 Phase 2 estimate: 12-16 days (was 10-14 in v2, +2-3 days for
the gate code construction moved here from Phase 5). Deliverables:

1. Carve `core/` (4 files: base_pipeline, chunk_aggregation, summary_writer,
   schema_gate)
2. Carve 4 universal features
3. Carve 9 cluster-shared features
4. Carve **12 NET-NEW bespoke features** including:
   - `bespoke_m21_buffalo.py` — never been written
   - `bespoke_m260_buffs.py` — never been written (M260 has 100% / 70-90%
     fallback leak per memory)
   - `bespoke_m268_credits_symbol.py` — never been written
   - `bespoke_m279_combo.py` — never been written; 3-feature stack
   - `bespoke_m113_expanded.py` — never been written; expanding-wild singleton
   - `bespoke_m11_diamond.py` — never been written
   - `bespoke_m250_grid.py` — never been written; 20-reel grid mechanic
   - `bespoke_m108_fillup.py` — never been written
   - `bespoke_m65_collection.py` — never been written
   - `bespoke_m67_open_close.py` — never been written
   - `bespoke_m120_reward_id.py` — never been written
   - `bespoke_m274_listrewardwheel.py` — partially exists as
     `bcm_cycle_anchor_m274` rule
5. **NEW v3**: build `rtp_integrity.py` with 4 layers (warn-only) +
   structured error format + suggested_actions templates
6. **NEW v3**: demonstrate Example 6 workflow end-to-end on M250

8 days of headroom past the carving (4 + 4 + 9 + 12 = 29 files plus the
gate). At ~1 day per bespoke plugin (optimistic for genuinely-novel mechanics
like M250's 20-reel grid and M21's Buffalo counters), that's 12 days of
plugin authoring alone, plus 2-3 days of gate construction, plus the M250
demo. The Phase 2 budget is tight even with the same plugin count v2 had,
and v3 adds the gate code on top.

Per v2 critique Concern 3 (now relevant again with shifted scope) and per
memory `feedback_invariant_with_fallback_hides_drift.md`, M250's bespoke fix
is genuinely non-trivial — Validator v2 §2.7 confirms M250 has 100% fallback
leak today with no current fix path. Writing `bespoke_m250_grid.py` is not
copy-pasting from a template.

Per addendum v3 §2 must-resolve #3 the resolution moves the gate to Phase 2
to break Phase 2/Phase 5 circular dependency — correct in principle. But
the Phase 2 budget is now substantially more loaded than v2's, with the same
top-line estimate ±2-3 days. Either the estimate is optimistic (likely) or
some of the 12 bespoke plugins must be deferred (which breaks the forcing-
function discipline that the addendum specifically wanted).

v3 §7.1 raises this exact concern as an "open question for critic": "is
'build the gate AND the demo in Phase 2' feasible in the revised 12-16 day
Phase 2 window?" Designer's tentative answer says Layer 4 implementation is
independent of feature-carving order. I agree on the sequencing dependency.
But that doesn't address the total work-budget question. Critic verdict: the
budget is optimistic; the proposal should either add 3-5 days to Phase 2 or
explicitly accept that some of the 12 bespoke plugins will be deferred (with
documented criteria for which ones make the cut).

---

## §2 10+ stress questions

### Q1 — Did v3 actually integrate operator-diagnostic framing, or just rename §9?

**Question**: per the harness probe #1, did §1 + §9 actually shift framing,
or is this a cosmetic rename of v2's enforcement gate?

**Attempted answer for the designer**: §1.1 rewrites the problem statement
verbatim per addendum v3 §1. §1.3 explicitly names "the §9 framing change —
operator diagnostic, not internal assertion". §9.1 opens: "The console exists
to help the operator (策划) find issues in production machine configurations
they themselves wrote." §9.3 error messages use the addendum-required form:
"Possible causes: (a) operator misconfigured something / (b) console rule
for X needs update / (c) data corruption."

**Hostile re-read of §9**:

- §9.2 Layer 1 unchanged from v2.
- §9.2 Layer 2 substantively changed (no numeric threshold; any fallback
  bucket fires). ✓ genuine framing shift.
- §9.2 Layer 3 unchanged from v2.
- §9.2 Layer 4 NEW.
- §9.3 error format genuinely includes the (a)/(b)/(c) actionable hints.
  Example JSON for M250 has 4 `suggested_actions` strings. ✓ operator-
  diagnostic framing present.
- §9.4 surfacing language: "When the console cannot reliably analyze a
  machine, it must surface that to the operator with actionable diagnosis
  hints — not silently fall back to wrong numbers." ✓ operator-side framing.

The framing IS integrated, not just renamed. The error messages reference
operator misconfig as the first hypothesis (not internal bug). The
suggested_actions field gives the operator concrete next steps. The reframe
is real and load-bearing.

**Verdict**: ✓ adequately addressed.

### Q2 — Does Layer 4 actually catch within-pid mis-attribution between SpinTypes (the motivating M31 pid-8 case)?

**Question**: per Concern 2 above, Layer 4 compares two summary fields that
both read from the same in-memory accumulator. Does this catch a dispatch-
level bug?

**Attempted answer for the designer**: §9.2 Layer 4 specifies the cross-check
between `payouts_by_spin_type[label].rows[pid].hit_count` and
`payout_ids_top20.rows[pid].spin_type_breakdown[N].count`. Both are derived
from the same rawdata's SpinType field. §7.3 designer's own tentative answer:
"both values are computed by the same feature's `extract`/`reduce`/`emit`
path."

**Hostile rebuttal**: per my read of `player_impact_analyzer.py:6438-6509`,
both fields read from `payout_id_by_spin_type_total`. They are not two
derivations from rawdata — they are two READOUTS of the same dict. If the
dispatch into the dict is wrong, both sides are equally wrong.

The motivating example (addendum v3 §2 must-resolve #2): "if console's logic
mistakenly attributes all 33,167 to ST=43 (or any other proportion than
rawdata's true 22,370:10,797), the per-ST breakdown is silently wrong".
This bug puts wrong counts into `payout_id_by_spin_type_total` during
`parse_chunk_response`. Both Layer 4 readers consume the same wrong dict.
Layer 4 passes. Bug invisible.

What Layer 4 actually catches: a future emitter-level inconsistency where
the two presentation slices diverge (e.g., one filters zero-hit pids, the
other doesn't). This is the kind of bug introduced when refactoring the
emitter — a real concern, but not the motivating case.

To catch the motivating case, Layer 4 would need to recompute (pid, ST)
counts from the raw round list independently (e.g., re-iterate
`roundResult[*].SpinType` and `PayoutIdToWinAmount` and reconstruct the
counts), then compare against `payout_id_by_spin_type_total`. That is a
different implementation than §9.2 describes.

**Verdict**: ✗ not addressed. The implementation as drawn catches a different
class of bug than the one the addendum motivating example describes. Layer 4
catches "emitter-slice inconsistency" not "dispatch mis-routing".

### Q3 — How does `console_diagnostic_complete: false` machine's report actually appear to the operator?

**Question** per harness probe #3: all 421 ship `false` at Phase 3. What's
the user experience?

**Attempted answer for the designer**: §5.5.3 says "Report is still produced
+ flagged '[INCOMPLETE]' in the summary metadata + visible in the rwtree
UI". §6.5 Phase 5 deliverable 3: "Per-machine cell shows a yellow
'[INCOMPLETE]' badge for `console_diagnostic_complete: false` machines whose
gate fired warnings." §9.4: "Yellow border + '[INCOMPLETE]' badge for
`completeness_declared == false` machines with warning layers."

**Hostile re-read**: there's a subtle distinction. §6.5 says "[INCOMPLETE]"
appears for machines that **fired warnings**. §9.4 says the same. So a
machine with `complete: false` that passes all 4 layers cleanly should NOT
get the badge.

But the warning is on Layer 1-4 firing, not on machine completeness. So an
M1 mode 1 with `complete: false` that passes Layer 1-4 (which is its
empirically-clean state today) would presumably show as normal cell, not
yellow. ✓ that's the right design.

**However**: per Concern 4 above, the warning-on-firing logic means
M1/M14/M37 etc., (45 SC-Vanilla) all show normal cells (no warnings). But
M250 with `complete: false` and 100% fallback shows yellow [INCOMPLETE].
That's a 2-state UI signal: normal (passes silently) vs yellow ([INCOMPLETE]
with warnings).

The third state from the v3 §6.5 spec — "Red border + 'Integrity failed'
badge for `completeness_declared == true` machines with failing layers" —
is zero machines on day-1.

So Phase 5 day-1 UI states:
- ~45 SC-Vanilla machines: normal cell ✓
- ~22 known-broken BCM machines: yellow [INCOMPLETE] ⚠
- M274: normal cell (4 layers pass per Validator v2) ✓
- Remaining ~354 machines: depends on whether they trip any layer

This is actually OK in practice for the visible-to-operator path. ✓ partial
answer.

But the spec implication that **any** machine, including the obvious-clean
ones, could be flipped to `true` only via the unspecified QA workflow
(§8.13) remains a concern per Concern 1.

**Verdict**: ⚠ partial — operationally workable, but the workflow for
flipping is the dominant unspecified thing.

### Q4 — Phase ordering: does Phase 2 building the gate actually break the Phase 2/Phase 5 circular dependency?

**Question** per harness probe #4: v3 §6.2 deliverable 5 says Phase 2 builds
gate code. v3 §6.5 says Phase 5 flips policy. Does Phase 2 deliverable 5's
M250 demo execute correctly?

**Attempted answer for the designer**: §6.2 deliverable 5: "Build
`fresh_slotlab/rtp_integrity.py` — implements `check_rtp_integrity(summary,
manifest) -> RTPIntegrityResult` with all 4 layers per §9. In Phase 2 the
gate runs in warn-only mode for every analyzer run." §6.2 deliverable 6:
"Demonstrate Example 6 workflow end-to-end using the gate that exists in
Phase 2: Pick M250 → minimal manifest → Run RTP integrity gate (now exists
in Phase 2!) → fails with explicit Layer 2 + Layer 3 errors → Add features/
bespoke_m250_grid.py → Re-run RTP gate → passes."

**Hostile cross-check**:

- Deliverable 5 produces the gate. ✓
- Deliverable 6 uses the gate from deliverable 5. ✓
- Phase 5 deliverable 1 is just the policy flip (warn → error for `true`
  machines). ✓

The circular dependency is genuinely resolved. Phase 2 is self-contained.
Phase 5's purview is narrow.

**Caveat (becomes my Concern 5)**: while phase ordering is now coherent, the
Phase 2 work-budget is heavier. But that's a different concern — it's not a
circular dependency, it's a scope question.

**Verdict**: ✓ phase ordering circular dependency resolved.

### Q5 — Variant carve-out justification: does it hold up against hypothetical "M273$NewSelector$0$ with slightly different decision tree"?

**Question** per harness probe #5: §5.5.4 1-paragraph justification claims
"variants are parser-sharing by definition, not similarity assumption".
Stress-test: what if operator creates a `M273$NewSelector$0$` variant
tomorrow with a slightly different decision tree that requires a tiny
analyzer rule difference?

**Attempted answer for the designer**: §5.5.4 paragraph 2: "There is no
scenario where M273.json's analyzer_features list should differ from
M273$WheelSelector$42$.json's analyzer_features list — they are reading the
same rawdata schema from the same machine code." If the new variant has
a different decision tree that requires a different parser, by definition
it's not a variant — it's a new underlying machine that should have its own
machine_id without `$` infix.

**Hostile rebuttal**:

In practice this is fuzzy. M273 has 85 variants today (`02 §3.5.3 / §4.1`).
Suppose an operator creates `M273$NewSelector$0$` because the upstream
machine code spawned a new selector option. The new selector might:

(a) Behave identically from the parser's perspective (same SpinType set,
    same PayoutByPayline shape, same trigger ReMarks) — variant cascade OK.
(b) Behave slightly differently (e.g., emits a new pay_id when the new
    selector option is picked) — parser must handle the new pay_id;
    `analyzer_features` may need a tiny addition.

Under §5.5.4 the variant cascade is eager: if the underlying M273.json
doesn't add the new feature, neither do variants. So path (b) would
require either (i) updating M273.json to add the feature (which cascades to
all 86 variants), or (ii) overriding `analyzer_features_override` at the
variant level, which §5.5.7 example shows is technically possible
(`"analyzer_features_override": null` could in principle be a non-null
list).

**The contradiction**: §5.5.4 paragraph 2 declares "There is no scenario
where ... analyzer_features list should differ". §5.5.7 mechanism allows
`analyzer_features_override: <non-null>` to override. So either §5.5.4
absolutist statement is overstated, OR §5.5.7 override slot is misleadingly
present.

The §5.5.5 eager-cascade documentation tries to bridge this by saying "if
the underlying's parser is incomplete, all its variants will fail Layer 1-4
checks for the same reason" — but that's about cleanliness, not feature
override capability.

In practice, the cleanest workflow for case (b) is to update the underlying
to add the feature. But the proposal doesn't prohibit per-variant feature
overrides; the §5.5.7 example shows the override slots exist. If an
operator uses them, the variant diverges from underlying. The "parser
sharing by definition" claim is downgraded to "parser sharing by
convention, unless the operator overrides".

**Verdict**: ⚠ partial. The §5.5.4 justification is rhetorically strong but
the §5.5.7 mechanism allows per-variant override, which weakens the
"by definition" claim. The proposal should either disallow variant-level
analyzer_features_override (forcing all variant parser changes through the
underlying), or soften §5.5.4's "no scenario" language.

### Q6 — The 3 open questions Designer leaves in §7: implementation-only, or pre-approval-blocking?

**Question** per harness probe #6: §7 has 3 open questions for critic.
Pre-approval-blocking?

**Attempted answer for the designer**: §7.1 Phase 2 budget feasibility +
Layer 4 implementation independence; §7.2 `console_diagnostic_complete` flip
authority + per-mode granularity; §7.3 Layer 4 false-positive sources.

**Critic assessment of each**:

- **§7.1**: not pre-approval-blocking on the sequencing question (Layer 4 IS
  independent of feature-carving order per my reading). Budget concern IS
  pre-approval-blocking per my Concern 5 — but it's a scope/timing concern,
  not a correctness concern. Can ship with explicit acknowledgment.

- **§7.2**: the per-mode flag granularity question. Designer's tentative
  answer: "the flag means 'console claims it can diagnose this machine'.
  Mode-5 not-monitorable is a measurement-side concern... not a parser-side
  concern. The flag is about parser correctness." This is reasonable. But
  cite memory `user_testing_machine.md` "mode 2/5 RTP 不可精准监控" — for
  M14 the user has specifically called out mode 5 as not-monitorable. If
  M14 is flipped to `true` and mode 5 fires Layer 1 (sum invariant) or
  Layer 4 (per-ST consistency) on sampling noise, the operator gets a
  strict error on M14 mode 5. The §7.2 answer relies on Layer 1-4 being
  immune to sampling-side issues. Layer 1 is genuinely arithmetic so it
  is immune. Layer 4 (as my Concern 2 notes) is a same-accumulator
  self-consistency check, also immune. Layer 2 is "any fallback bucket
  exists" — also immune to sampling noise (fallback comes from rule gaps,
  not from sampling). Layer 3 (anchor coverage) requires anchor pid to
  have > 0 hits — could fail if sample is too small to capture an anchor
  even on a machine that has the rule. This IS a sampling-side
  vulnerability. §7.2 designer doesn't address Layer 3 specifically. Not
  blocking; flag it.

- **§7.3**: this is essentially my Concern 2. Designer's tentative answer
  ("they shouldn't differ because they use the same code path") is the
  problem, not the solution. **This is pre-approval-blocking** because
  the addendum v3 §2 must-resolve #2 specifically wanted Layer 4 to
  catch the motivating M31 pid-8 case, and as drawn Layer 4 does not
  catch that case.

**Verdict on §7 questions**: §7.1 and §7.2 are implementation-detail
deferrable. §7.3 is the same issue as my Concern 2 and is
**pre-approval-blocking**.

### Q7 — Day-1 reality with all-false default: does the strict-error mechanism ever engage?

**Question** per harness probe #7: Phase 5 ships strict-policy-flip for
`complete: true` machines. But Phase 3 set all 421 to `false`. So Phase 5
day-1 = 0 strict machines.

**Attempted answer for the designer**: per §6.5 Phase 5 deliverable 4
"Known-broken machines triage — at Phase 5 deploy time, the operator (or QA
team) flips `console_diagnostic_complete` to `true` for machines whose rules
are verified clean." §8.13 "QA workflow out of scope for v3".

**Critic assessment**: this is my Concern 1. The strict-error mechanism is
on the shelf but with zero members until the unspecified QA process kicks
in. The proposal should at minimum spec which machines are
**eligible** for the flip (e.g., 4-layer empirical pass on most recent
fleet pull) without specifying who does the flip or when. As it stands,
v3 ships an architecture where the most important safety mechanism is
permanently dormant pending a process that the proposal explicitly
declares out-of-scope.

A minimum fix: a Phase 5 deliverable that identifies the obvious-eligible
machines (SC-Vanilla 45 + M274 + any with empirical 4-layer pass on
representative rawdata) and flips them at Phase 3 cutover. This converts
v3 from "all-false default" to "obvious-clean-flipped, rest-false-default",
which is the right starting point per the operator-diagnostic framing
(addendum v3 §1 — "Console must be correct so its signals are trustworthy"
— the trustworthiness signal needs to engage on day 1 for the machines
where it can engage).

**Verdict**: ⚠ partial. The day-1 reality is consistent with the spec but
operationally unhelpful. A minimum carve-out (flip the obvious-clean
machines at cutover) would strengthen the proposal materially.

### Q8 — Inheritance semantics in Layer 4: if M273$variant inherits from M273, does Layer 4 auto-pass for variants?

**Question** per harness probe #8: if M273$variant inherits from M273 and
Layer 4 checks pass for M273, does it auto-pass for variants?

**Attempted answer for the designer**: §5.5.5 eager cascade means analyzer
features cascade. Layer 4 runs on the variant's own rawdata + variant's
effective manifest (which equals underlying's manifest after eager
resolution).

**Critic assessment**:

- Per §9.5 "Trigger | When integrity check runs": every analyzer run
  invokes the check. Variants get sampled separately (per §5.5.4 "Storage
  and reports MUST be isolated per variant"). So Layer 4 runs per-variant
  on the variant's own rawdata.
- The check uses the variant's effective manifest (resolved via eager
  cascade). Same features as underlying.
- The check compares `payouts_by_spin_type` against
  `payout_ids_top20.spin_type_breakdown` in the variant's summary — using
  variant's own data.
- So variant-specific dispatch issues would (in principle, modulo Concern
  2) be caught by variant-specific Layer 4 runs. The check is NOT shared
  across variants — it runs per-summary.

**Verdict**: ✓ adequately addressed. Per-variant Layer 4 runs on variant
data. The variant inherits features from underlying but the check itself
runs on variant rawdata.

(Caveat: per Concern 2, Layer 4 as drawn doesn't catch dispatch-level bugs
even for the underlying. The per-variant runs share the same limitation.)

### Q9 — Trust model for `console_diagnostic_complete: true`: who can flip it? Auditable?

**Question** per harness probe #9: who flips it? Designated QA role?
Auditable?

**Attempted answer for the designer**: §8.13 "Which team owns flip
decisions" — out of v3 scope. §6.5 deliverable 4 "operator (or QA team)"
flips. §10.1 must-resolve #6: "the operator (via QA team workflow per
§8.13) flips per-machine."

**Critic assessment**:

- Mechanism: the manifest file `machine_manifests/<M>.json` has the
  `console_diagnostic_complete` field. Anyone with PR access to that file
  can flip it.
- Auditability: git history shows the commit. ✓ inherent.
- Verification: the proposal does NOT specify what verification is
  required before a flip. Per §6.5 "machines whose rules are verified
  clean" — verification process undefined. Per §8.13 "out of scope".
- Concretely: at Phase 5 deploy, a careless or rushed operator could flip
  M250 to `true` (it's in their PR backlog) without verifying any of the
  4 layers pass on representative rawdata. The strict-error mechanism
  then fires on M250's known-broken state and the run fails. UI shows red
  banner. Operator panics, flips back to `false`. Day wasted.

The lack of a verification-precondition is the biggest weakness of v3's
flip mechanism. Per addendum v3 §2 must-resolve #6 "out of scope" — but
"out of scope" applied to a load-bearing safety mechanism is shaky.

**Verdict**: ⚠ partial — auditable via git but verification criteria
undefined. The proposal should at minimum spec a verification template
(e.g., "before flipping to `true`, run `python -m fresh_slotlab.rtp_integrity
M<N>` against representative rawdata; all 4 layers must pass") even if
the operational ownership of the flip is genuinely out of v3 scope.

### Q10 — Did v3 break Wave 3 v2 validator case walks?

**Question** per harness probe #10: v2 ended with Validator clean APPROVE.
v3's changes (Layer 4 + policy flip + variant docs) should not break those
walks. Did Designer explicitly preserve case-walk compatibility?

**Attempted answer for the designer**: §10 resolution map and §3 reasoning
both claim "A v3 reuses Wave 3 v2's validated parts." Specifically: hash
composition unchanged (§4 entirely), manifest schema mechanics preserved
(§5.5.1 unchanged), Plugin Protocol unchanged (§5.2), file tree unchanged.

**Critic re-walk of v2 validator §2 cases under v3 spec**:

- **§2.1 M1**: v2 manifest had `fallback_share_threshold_pct: 0.5`. v3
  manifest example (§5.11 M1) has NO threshold field, has
  `console_diagnostic_complete: false`. The "3 layers PASS" walk in v2
  §2.1 needs minor re-walk for Layer 4 (which trivially passes for M1
  per my Concern 2 analysis — M1 has minimal spin_type_breakdown
  complexity). ⚠ minor re-walk needed; outcome same.

- **§2.6 M274**: Validator v2 walked all 3 layers PASS on live data. Layer 4
  re-walk for M274: per `02 §3.5.1` M274 has spin_type_breakdown data.
  The cross-check would presumably pass (per Concern 2, both readers
  consume same dict; trivially equal). ⚠ minor re-walk needed; outcome
  same.

- **§2.7 M250**: Validator v2 walked Layer 2 fails (100% fallback) + Layer
  3 fails (missing `_bcm_cycle`). v3 Layer 2 now fires on any fallback
  bucket (no threshold). Same outcome (Layer 2 fails). Layer 4 walk: M250
  has spin_type_breakdown; the cross-check would pass (same readers,
  same dict) — but Layer 2 + Layer 3 still fire. Same outcome.

- **§2.8a M65 "vanilla manifest hits integrity wall"**: same outcome under
  v3 — Layer 2 fires on any fallback bucket, same actionable error.

- **§2.8b M14 cross-mode**: hash composition unchanged from v2 — same
  outcome.

- **§2.9 M400 hypothetical**: feature discovery mechanism unchanged from
  v2 — same outcome.

The v2 case walks remain valid under v3 with minor Layer 4 additions
(which trivially pass for these cases per Concern 2). No catastrophic
regression.

**However**: this points to another property of Layer 4 as drawn — it
trivially passes for every case the validator walked. That's consistent
with Concern 2: Layer 4 is a same-source self-consistency check that
should always pass unless the analyzer's emitter has an internal
inconsistency (rare). The motivating case (dispatch mis-routing) isn't
covered.

**Verdict**: ✓ case-walk compatibility preserved. Layer 4 trivially passes
for all 8 v2 walked cases.

### Q11 — `console_diagnostic_complete` validation rule 8 is a tautology

**Question**: §5.6 rule 8 (v3 NEW): "if `console_diagnostic_complete: true`,
every feature in `analyzer_features` with `RTP_CONTRIBUTION=True` MUST be
present." What's the failure mode this catches?

**Critic assessment**:

The rule says "if you declare yourself complete AND your features list says
feature X has RTP_CONTRIBUTION=True THEN your features list must contain
feature X". This is tautological — the features list is checked against
itself.

I think the intent was different — perhaps "if you declare yourself
complete, then every feature in the canonical universal-RTP set must be in
your features list". But the rule as written reads circularly.

Possible designer intent (reading charitably): the rule checks against the
feature registry's `ALL_FEATURES` rather than against the machine's own
list. So it's "if you declare yourself complete, every feature in
`ALL_FEATURES` with RTP_CONTRIBUTION=True must be in your manifest's
`analyzer_features`". That would be a coherent rule (ensuring complete
machines have full RTP coverage).

Per the v3 prose this isn't clear. The rule should be re-worded.

**Verdict**: ⚠ minor doc bug. Not blocking; rule 8 needs re-wording to
specify whether the comparison is against `ALL_FEATURES` (registry) or the
manifest's own features list.

### Q12 — Hash composition mode dimension unconditionally baked: still a UX regression for cross-mode comparison?

**Question**: v2 critique Q5 raised that `|| mode` in hash composition
forces per-mode hash differences even for machines that don't distinguish
per-mode. v3 §4.1 is unchanged from v2.

**Attempted answer for the designer**: §4.1 algorithm unchanged. Validator
v2 §4.6 "Cross-product summary table" walked this and concluded it's
"desired" — maintains today's 1007 (m,mode) stale-bucket resolution.

**Critic assessment**: this is a defendable design choice. Validator v2's
§4.6 accepted it. My v2 critique flagged it as ⚠ partial. v3 doesn't
change it.

Per Validator v2 §4.6 "Cross-product insight: 0 regressions across all 50
cells. v2 provides identical or strictly-better invalidation behavior".
The mode-dim is additive; doesn't break compare-mode rendering as long as
the frontend reads the badge per-(machine, mode) which it already does.

**Verdict**: ✓ accepted in v2 validation; v3 unchanged. Closed.

### Q13 — `expected_paid_st` + `expected_bonus_st` validation when rawdata has none of those ST values

**Question**: §5.6 rule 9 "Declared `spin_type_convention.paid` must match
observed paid-ST set." What if observed paid-ST set is empty (because the
sample is too small) or extra (because of a new ST never anticipated)?

**Critic assessment**:

- Small sample: observed ST set is subset of declared. If declared is
  `[1]` and observed is `[]` (empty sample), rule 9 fires? §5.6 rule 9
  "must match" — strict equality fires. False positive on small samples.

- New ST: declared is `[1]`, observed is `[1, 200]` (new bonus type).
  Rule 9 fires correctly — manifest needs update.

The proposal doesn't address the small-sample case. §5.6 rule 9 runs "at
first run", presumably against whatever's there. Trivial sample sizes
could trip it.

This is a Phase 5 / Phase 6 operational concern. Not blocking; flag it.

**Verdict**: ⚠ minor edge case. Small-sample false-positives on rule 9.

### Q14 — Inheritance under per-feature edit: Layer 4 runs per-variant — but variant's `payouts_by_spin_type` is variant-specific data

**Question**: per Concern 3 + Q8 — if M273 underlying is flipped to `true`,
M273$variant42$ stays `false`. Their parsers are identical (eager cascade).
Variant gets sampled, runs Layer 4 on variant's own
`payouts_by_spin_type` — what about under-sampling artifacts where a
particular variant has few rounds and the per-ST distribution is sparse?

**Critic assessment**: Layer 4 is integer equality on (pid, ST) counts. Few
rounds → few hits → still mechanical equality (both readers see the same
small numbers). The integer comparison is sampling-insensitive.

**Verdict**: ✓ Layer 4 is sampling-insensitive per its mechanical nature.

### Q15 — `inherits_from` resolution recursion depth bound

**Question**: §6.3 deliverable 2: "`manifest_loader.py` — reads
`machine_manifests/<M>.json`, resolves `inherits_from` recursively". What
prevents A → B → C → A cycles, or 100-level deep chains?

**Attempted answer for the designer**: not specified explicitly.

**Critic assessment**: §5.5.4 documents variants inherit from their
single underlying. The natural depth is 1 (variant → underlying). The
proposal doesn't spec what happens if M273 itself has `inherits_from:
"M_someother.json"`. Per the §5.5.4 framing variants ARE the same machine
as their underlying, so multi-level inheritance shouldn't exist by
intended use.

But the resolver is "recursive" per §6.3 deliverable 2 — recursion implies
the mechanism supports depth > 1. The proposal doesn't bound this. A
typo in `inherits_from` could create a cycle.

**Verdict**: ⚠ minor — recursive resolver should specify max depth (1 for
variants per intended use) or cycle detection. Not blocking.

### Q16 — Layer 2 over-eager: legitimate use of a fallback-prefix pid

**Question**: §9.2 Layer 2 v3: "Any pay_id starting with one of these
triggers Layer 2." Reserved prefixes: `_unattributed_`, `_other`,
`_default`, `_misc`.

What if a future analyzer feature legitimately needs a `_misc` pid for a
real purpose (e.g., a clearly-labeled "miscellaneous credit adjustment"
that's intentional, not a fallback)? The reserved prefix list bakes in
"these prefixes mean failure".

**Critic assessment**: this is a forward-compatibility concern. The prefix
list is owned by the integrity check. A new feature wanting to use
`_misc` would need to either pick a non-reserved name (`misc_credit_adj`)
or update the integrity check's prefix list.

Not blocking. The reserved prefix list is itself part of the architecture
and changeable.

**Verdict**: ✓ acceptable; forward-compatibility is the architecture
team's choice.

### Q17 — Storage layout for `summary.rtp_integrity_check`: does the existing 1007 (m,mode) reports get the field on regen?

**Question**: v3 ships `summary.rtp_integrity_check` field per §6.2
deliverable 5. Per addendum §1.2 clean-break, old reports are invalidated
at Phase 3 cutover. So all regenerated reports have the new field.

**Critic assessment**: per addendum §1.2 + v3 §6.7 Phase 3 row "Manifest
files; new DB col", the clean-break works. ✓ no problem.

**Verdict**: ✓ clean per addendum §1.2.

### Q18 — Phase 6 audit deliverable now duplicates QA flip work

**Question**: §6.6 Phase 6 deliverable 3: "Audit medium outliers (~30
machines per `02 §5.2`) — write manifests for them; run RTP integrity;
flip `console_diagnostic_complete: true` for verified-clean ones."

But §8.13 says the flip workflow is out of v3 scope (QA team handles).
Phase 6 deliverable 3 is in v3 scope. These two say opposite things.

**Critic assessment**: Phase 6 is "optional / out-of-scope" per §6.7. So
the deliverable's "flip" wording is non-binding. But the wording itself
contradicts §8.13.

**Verdict**: ⚠ minor wording contradiction. §6.6 deliverable 3 should
either be removed (since §8.13 puts flip work out of scope) or §8.13
should be relaxed to "flip workflow out of v3 scope except for the
Phase 6 optional medium-outlier audit deliverable". Not blocking.

### §2 stress questions summary

| # | Topic | Verdict |
|---|---|---|
| Q1 | Operator-diagnostic framing genuinely integrated | ✓ |
| Q2 | Layer 4 catches motivating M31 pid-8 case | ✗ not addressed |
| Q3 | `complete: false` machine UX | ⚠ partial |
| Q4 | Phase 2/Phase 5 circular dependency resolved | ✓ |
| Q5 | Variant carve-out justification holds against hypothetical "M273$NewSelector" | ⚠ partial |
| Q6 | §7 designer open questions: are they pre-approval-blocking? | ⚠ partial (§7.3 is, ≡ Concern 2) |
| Q7 | Day-1 strict-mechanism engagement | ⚠ partial |
| Q8 | Layer 4 inheritance for variants | ✓ |
| Q9 | Trust model for flip | ⚠ partial |
| Q10 | v3 preserves v2 validator case walks | ✓ |
| Q11 | §5.6 rule 8 tautology | ⚠ minor doc bug |
| Q12 | Mode dim in hash | ✓ closed in v2 validation |
| Q13 | Small-sample rule 9 false positive | ⚠ minor edge case |
| Q14 | Variant under-sampling Layer 4 | ✓ |
| Q15 | inherits_from recursion bound | ⚠ minor |
| Q16 | Layer 2 reserved-prefix forward compat | ✓ |
| Q17 | summary.rtp_integrity_check on regen | ✓ |
| Q18 | Phase 6 vs §8.13 contradiction | ⚠ minor |

Totals: **8 ✓**, **9 ⚠**, **1 ✗**. Significant improvement vs v2 (1 ✓, 12 ⚠,
5 ✗).

---

## §3 Migration risk inventory

### Phase 1 (LOW-MEDIUM per §6.7) — unchanged from v2

All Phase 1 risks v2 flagged carry over identically (3-writers parity,
RAWDATA_ROOT cascade, regression test design). v3 makes no Phase 1 changes.

### Phase 2 (HIGH per §6.7) — risks identified

| Risk | Source | Severity |
|---|---|---|
| 12 bespoke plugins + gate code + demo in 12-16 day budget (Concern 5) | §6.2 deliverables 4 + 5 + 6 | HIGH |
| Layer 4 implementation per Concern 2 may not actually catch the motivating case; spec drift between intent and implementation | §9.2 Layer 4 + addendum v3 §2 must-resolve #2 | MEDIUM-HIGH |
| Monkey-patch in sliced architecture: os._exit reach (v2 carry-over) | §5.8 | MEDIUM |
| 12 forcing-function machine fix-ups: M250's 20-reel grid genuinely novel work | §6.2 deliverable 4 | MEDIUM-HIGH |
| Gate code's structured error format + suggested_actions is template-heavy; templates need authoring | §9.3 | LOW-MEDIUM |

Rollback per §6.7: per-feature revert. Gate code revert reverts to no-gate
state (which is today's state). Clean rollback path.

### Phase 3 (MEDIUM per §6.7) — risks identified

| Risk | Source | Severity |
|---|---|---|
| 421 manifests all-false at cutover causes 421 [INCOMPLETE]-on-warning banners; alert fatigue (Concern 4) | §5.5.3 initial values + §6.3 deliverable 1 | HIGH |
| Mode dimension in hash (carry-over from v2 Q5) | §4.1 | LOW (v2 validation accepted) |
| `inherits_from` cascade now eager — when underlying changes, 86 hashes flip (carry from v2 Q10, now documented eager) | §5.5.5 | MEDIUM (documented; honest about cost) |
| Per-mode RTP integrity contract: §5.5.6 explicit list addresses validator v2 doc gap | §5.5.6 | LOW (resolved) |
| Validation rule 8 tautology (Q11) | §5.6 rule 8 | LOW (minor doc bug) |
| Manifest authorship for 421 machines: clarified to all-false default, so authorship is mostly templated | §6.3 deliverable 1 | MEDIUM (reduced from v2 because no per-machine threshold to set; auth simpler) |
| Rule 9 small-sample false positive (Q13) | §5.6 rule 9 | LOW |

### Phase 4 (LOW per §6.7) — unchanged from v2

Frontend renderer registry + SCHEMA_VERSION enforcement. v3 doesn't change.

### Phase 5 (LOW-MEDIUM per §6.7) — risks identified

| Risk | Source | Severity |
|---|---|---|
| Day-1 strict-mechanism has 0 members (Concern 1) | §6.5 deliverable 4 + §8.13 | HIGH |
| QA flip workflow unspecified; mechanism could remain permanently dormant | §8.13 + §10.1 | HIGH |
| 45 SC-Vanilla + M274 obvious-clean machines stay `false` post-Phase-5; UI noise (Concern 4) | §5.5.3 | MEDIUM-HIGH |
| Phase 6 vs §8.13 wording contradiction (Q18) | §6.6 deliverable 3 vs §8.13 | LOW |
| Trust model for flip: anyone with PR access can flip without verification (Q9) | §6.5 deliverable 4 + §8.13 | MEDIUM |

Rollback per §6.7: "Policy flip reverts globally". Means the strict-error
mechanism is disabled globally. Per §5.5.3 the manifest's
`console_diagnostic_complete` flag still exists but is no longer
consulted. Reverts to pre-Phase-5 warn-only state. Clean.

### Phase 6 (LOW per §6.7) — unchanged from v2 + Q18 wording contradiction

### Cross-phase rollback failure modes (v3-specific)

1. **Phase 5 policy-flip rollback after some operators have flipped flags**:
   if operators have flipped 30 machines to `true` during Phase 5, then
   Phase 5 is reverted, those flags stay in the manifest files (they're
   not undone by the policy-flip rollback). The flags become benign
   metadata. On Phase 5 re-deploy, those flags re-activate strict-error.
   Operationally: manifest changes outlive policy reverts. Clean per
   architecture but operators may not expect flags to "remember".

2. **Phase 2 gate code rollback**: if Phase 2's gate code is reverted, the
   `summary.rtp_integrity_check` field is no longer populated. Frontend
   per §6.4 + §9.4 reads this field; absence handled gracefully (legacy
   no-banner path). Reports written during Phase 2 with the field still
   exist on disk — frontend can show them but with no live gate data
   for newer runs. Mixed-state acceptable.

---

## §4 Edge cases not covered

1. **`_unattributed_*` legitimate use**: what if a future analyzer feature
   legitimately needs a "_misc" or similar prefix for a real, intentional
   purpose? Layer 2 reserved-prefix list bakes in semantics; future
   features must coordinate (Q16). Not blocking.

2. **`inherits_from` cycle / multi-level depth**: resolver is recursive
   per §6.3 deliverable 2 but no depth or cycle bound spec'd (Q15).

3. **Layer 3 anchor coverage under-sampling**: if rawdata sample is too
   small to have hit an anchor pid even on a machine with the correct
   rule, Layer 3 fires (false positive). §7.2 partially acknowledges
   "RTP-not-monitorable" modes but doesn't spec sampling-side immunity
   for Layer 3 specifically.

4. **Operator flipping `true` without verification**: anyone with PR access
   to `machine_manifests/<M>.json` can flip the flag. No verification
   precondition (Q9). Concretely: a careless flip on M250 produces a red
   strict-error banner on day-1 with predictable failure modes.

5. **Manifest writing for 215 rawdata-less machines**: v3 inherits v2's
   concern (Q12 v2). Manifests must be authored without rawdata to
   verify against. With all-false default at cutover this is less
   immediately painful (no false positives) but the post-flip
   verification step (which is OOS per §8.13) cannot run without
   rawdata. The flip mechanism is effectively limited to the 206
   rawdata-bearing machines.

6. **Phase 2 deliverable 6's M250 demo**: assumes M250 rawdata exists
   (which Validator v2 §2.7 confirms it does: `rawdata/M250/mode_1/chunk_0001.json`).
   But the demo also assumes `bespoke_m250_grid.py` can be written that
   makes the 4 layers pass. Per memory `feedback_invariant_with_fallback_hides_drift.md`
   M250's fix is non-trivial work. If the bespoke plugin doesn't make 4
   layers pass in the Phase 2 budget, the demo fails. v3 doesn't have a
   fallback demo machine.

7. **`per_mode_overrides` resolution order ambiguity**: §5.5.6 says
   "_remove first, then _add". What if both `analyzer_features_remove`
   and `analyzer_features_add` mention the same feature_id? Result
   depends on ordering. The proposal doesn't enumerate this collision
   case.

8. **`inherits_from` + `per_mode_overrides` interaction**: a variant
   that inherits from underlying — does the variant's `per_mode_overrides`
   merge with underlying's, or replace it? §5.5.7 example shows
   variant fields all null; doesn't cover this case.

9. **Variant `console_diagnostic_complete: false` while underlying is
   `true`**: per Concern 3 + §5.5.7, M273 underlying is `true` but
   M273$variant42$ stays `false`. The variant fires warnings while the
   underlying fires errors on the same kind of failure. Operator sees
   inconsistent signal classes for the same underlying mechanic.

10. **`integrity_failures` DB table schema**: §6.5 deliverable 2 mentions
    "state/console/console.db.integrity_failures table". Schema
    undefined (carry from v2).

11. **Re-running gate on the same report**: if Phase 5 ships and an
    operator re-runs `POST /api/runs/integrity-check-all`, does the gate
    re-compute, or is the result cached in `summary.rtp_integrity_check`?
    §9.5 lists triggers but not freshness/caching semantics.

12. **Concurrent manifest edit during analyzer run**: carry from v2 edge
    case 3. v3 doesn't address.

---

## §5 Hidden assumptions

### A1 — Layer 4 self-consistency catches the dispatch-level bug

Per Concern 2 / Q2. The §9.2 implementation as drawn reads from the same
in-memory accumulator on both sides; would not catch a routing bug at
`parse_chunk_response`. The proposal assumes the cross-check provides
end-to-end attribution verification. It provides emitter-slice
self-consistency.

### A2 — QA flip workflow will exist and operate effectively post-Phase-5

Per Concern 1 / Q7. §8.13 punts the workflow to "implementation team".
The architecture's strict-error safety mechanism depends on QA
verification flipping flags. If QA doesn't operate at scale, strict-error
permanently dormant.

### A3 — All-false default at cutover is acceptable operationally

Per Concern 4. 421 [INCOMPLETE] machines (or 421 normal cells with
warnings underneath) until QA flips them. Assumed acceptable. Operators
who see [INCOMPLETE] on M14 (which they know to be correct) train
themselves to ignore the badge. Alert fatigue.

### A4 — Phase 2 budget covers gate code + 12 bespoke plugins + M250 demo

Per Concern 5 / Q1 in v3 §7.1. 12-16 day budget. Aggressive.

### A5 — Variant-level `analyzer_features_override` is sufficiently rare to not undermine "parser sharing by definition" claim

Per Q5. §5.5.7 mechanism allows per-variant feature override. §5.5.4
claims variants ARE the same machine for parser purposes. Tension.

### A6 — Variants' per-variant `console_diagnostic_complete` is the right granularity

Per Concern 3. Variants share parser eagerly but completeness flag is
per-variant. The asymmetry is justified by "variant-specific data may
have edge cases" but the same is true of any machine — undermining the
variant-specific justification.

### A7 — Eager cascade's 86-machine fan-out for M273 changes is acceptable

Per §5.5.5. v3 explicitly accepts this cost. Honest. (No longer hidden as
in v2.)

### A8 — Layer 2 "any fallback bucket" doesn't fire on small-sample artifacts

Per Q13 + Layer 2 reserved-prefix list. Fallback buckets are produced by
parser-rule gaps, not sampling. Reasonable assumption per current
analyzer (the `_unattributed_*` synthesizer fires when sum invariant
needs filling regardless of sample size). ✓ defensible.

### A9 — Validation rule 8's intent is "RTP_CONTRIBUTION=True features must
be in the manifest" not "the features list must contain its own
RTP_CONTRIBUTION=True features"

Per Q11. Doc bug; intent presumably the former.

---

## §6 Comparison to rejected alternatives (re-check)

### Alternative B — Lightweight per-feature SCHEMA_VERSION sidecar

v3 §2.2 keeps v2 rejection: "B doesn't satisfy the operator-diagnostic
framing from addendum v3 §1. Under B, the console has no mechanism to
declare 'I cannot diagnose this machine'."

**Counter-critique**: defensible. The operator-diagnostic framing is the
v3-specific load-bearing addition that B cannot accommodate.

**Verdict**: B rejection defensible.

### Alternative C — Full per-machine analyzer plugin tree

v3 §2.3 keeps v2 rejection: "C eliminates sharing wholesale; addendum
§1.5 says 'sharing is opt-in via manifest', not 'no sharing'."

**Counter-critique**: defensible. v3 §5.5.4 variant carve-out is
specifically the case where sharing IS by definition (variants ARE the
same machine), and C would force 166 redundant per-variant plugin files.

**Verdict**: C rejection defensible.

---

## §7 Verdict

### APPROVE-WITH-REVISIONS

v3 successfully integrates the addendum v3 framing changes:
- §1 + §9 genuinely reframed per addendum v3 §1 operator-diagnostic
  premise (Q1 ✓).
- `console_diagnostic_complete` per-machine flag replaces v2's numeric
  threshold cleanly; eliminates v2 Critic Concern 2 (false-positive
  cliff) and v2 Q16 (threshold authority).
- Phase 2/Phase 5 circular dependency resolved by moving gate code to
  Phase 2 (Q4 ✓).
- Eager variant cascade explicitly documented (§5.5.5).
- Validator v2 minor doc gaps closed (§5.5.6 per_mode_overrides + §9.7
  illustrative-not-exhaustive).
- Phase 5 day-1 reality: `complete: false` default protects 22+ today-
  broken BCM machines from red banners (Critic v2 Concern 5 resolved).

v2 critique convergence:
- v1 critique = 11 must-resolves
- v2 critique = 6 must-resolves
- v3 critique = **2 must-resolves** + 1 soft-resolve

The trajectory of convergence is real. But v3 is **not** clean APPROVE
because two structural issues remain.

### Must-resolves for v3 (2 + 1 soft)

**M1. Layer 4 doesn't catch dispatch-level mis-attribution (Concern 2 / Q2 / §7.3 designer-acknowledged open question)**

Per §9.2 Layer 4: both compared fields
(`payouts_by_spin_type[label].rows[pid].hit_count` and
`payout_ids_top20.rows[pid].spin_type_breakdown[N].count`) read from the
same in-memory accumulator (`payout_id_by_spin_type_total` per my
`player_impact_analyzer.py:6438-6509` read). They are not two derivations
from rawdata; they are two readouts of the same dispatch result. If
dispatch is wrong, both readouts agree, Layer 4 passes silently. The
motivating M31 pid-8 case from addendum v3 §2 must-resolve #2 (where
33,167 hits get mis-routed to ST=43 instead of split 22,370:10,797) puts
wrong values into the shared accumulator; Layer 4 cannot see it.

Designer's own §7.3 tentative answer ("both values are computed by the
same feature's `extract`/`reduce`/`emit` path") confirms the issue.

**Fix sketch (not redesign)**: Layer 4 must include an independent
re-derivation of (pid, ST) counts from the raw `roundResult` list (e.g.,
re-iterate `SpinType` and `PayoutIdToWinAmount` per round, reconstruct
counts), then compare against the analyzer's
`payout_id_by_spin_type_total`. This is a different and harder
implementation than what §9.2 describes. The designer should either
(a) re-implement Layer 4 to actually catch the motivating case, or
(b) rename Layer 4 to reflect what it actually checks ("emitter-slice
self-consistency") and acknowledge that dispatch-level routing bugs
remain undetected by the gate.

**M2. Phase 5 day-1 strict mechanism has zero members; flip workflow unspecified (Concern 1 / Concern 4 / Q7 / Q9)**

The combination of:
- §5.5.3 "All 421 machines start `console_diagnostic_complete: false`"
- §8.13 flip workflow out of v3 scope
- §6.5 deliverable 4 "QA verifies clean"

means Phase 5 ships a strict-error mechanism with zero members and no
spec for when/how members will be added. The architecture's main safety
mechanism is permanently dormant pending an unspecified process.

**Fix sketch**: v3 should add a Phase 5 (or Phase 3) deliverable that
identifies the obvious-eligible machines (SC-Vanilla ~45 + M274 + any
machine where 4 layers empirically pass on most recent rawdata) and
flips them to `true` at cutover. The "flip mechanism" can remain
out-of-scope, but the **eligibility criterion** and the **initial
populated set** should be specified. Without this, v3 ships with a
mechanism whose main consumer never engages.

A minimum acceptable form: a verification template (e.g., "before
flipping to `true`, run `python -m fresh_slotlab.rtp_integrity M<N>`
against representative rawdata; all 4 layers must pass; commit
manifest change with link to verification log") + an initial flipped
set at cutover.

**S1 (soft).  Variant cascade asymmetry between `analyzer_features` (eager) and `console_diagnostic_complete` (per-variant) is incoherent (Concern 3 / Q5)**

§5.5.4 declares variants ARE the same machine for parser purposes
(eager cascade). §5.5.7 declares variants are NOT the same machine for
completeness purposes (per-variant flag). The parser-sharing-by-
definition claim is strong; the per-variant-flag justification ("variant-
specific data may have edge cases the underlying didn't surface") is
weak — that's true of every machine added, not variant-specific.

**Fix sketch**: pick one position. Either variants are fully the same
machine (in which case flag also cascades), or they aren't (in which
case `analyzer_features` shouldn't cascade either, and variants need
explicit feature lists). The asymmetric stance is convenient but
incoherent.

(Soft because the asymmetric stance is workable in practice — operators
will eventually flip variants to `true` after their per-variant data is
validated. But the doctrinal contradiction should be acknowledged.)

### Other items to address (non-blocking)

- Q11: §5.6 rule 8 tautology — re-word to specify the comparison is
  against `ALL_FEATURES` registry, not the manifest's own list.
- Q5: §5.5.4 absolutist "no scenario where M273.json's
  analyzer_features list should differ" overstated given §5.5.7 override
  slots exist. Soften wording or remove the override slot from variant
  manifests.
- Q13: §5.6 rule 9 small-sample false-positive — spec a minimum sample
  size for the rule.
- Q15: `inherits_from` recursion depth bound — spec max depth (1) or
  cycle detection.
- Q18: §6.6 deliverable 3 vs §8.13 wording — resolve which scope owns
  flip work in Phase 6.
- Concern 5 (Phase 2 budget): either add 3-5 days to Phase 2 estimate or
  document explicit deferral criterion for some of the 12 bespoke
  plugins.

### Why APPROVE-WITH-REVISIONS not APPROVE

Per harness preamble: "v3 should converge — your v1 had 11 must-resolves,
v2 had 6, v3 should be ≤ 3 (or full APPROVE)". v3 has 2 hard must-
resolves + 1 soft. That's at the boundary.

The Layer 4 issue (M1) is the more serious of the two — it's a stated
architectural goal (catch within-pid mis-attribution per addendum v3 §2
must-resolve #2) that the implementation as drawn doesn't deliver for
the motivating case. The designer's own §7.3 open question hints at this.

The day-1 reality issue (M2) is operationally serious but architecturally
fixable with a small addition (eligibility criterion + initial flipped
set).

If both M1 and M2 are addressed in v4 (concrete spec amendments, not
full rewrite), v4 would be clean APPROVE. If only M2 is addressed, v4
would still have the Layer 4 spec drift. If neither: REJECT.

Given v3 is otherwise a substantial improvement over v2 (clean §9
reframe, threshold/false-positive cliff eliminated, phase ordering fixed,
variant carve-out documented, eager cascade explicit, validator doc gaps
closed), APPROVE-WITH-REVISIONS is the right verdict.

---

```
arch-critic complete.
- Version: v3
- Top concerns: 5
- Stress questions: 18 (verdict: 8 ✓ / 9 ⚠ / 1 ✗)
- Migration risks flagged: 17 (across 6 phases + 2 cross-phase)
- Edge cases not covered: 12
- Verdict: APPROVE-WITH-REVISIONS
- Must-resolves: 2 hard (Layer 4 spec drift; day-1 flipped-set) + 1 soft (variant cascade asymmetry)
- Output: session_artifacts/_arch/05_critique_v3.md
```
