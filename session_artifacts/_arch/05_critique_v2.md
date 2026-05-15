# Adversarial Critique v2 — Wave 2 Architecture Proposal v2

> Wave 3 v2 / arch-critic. Hostile review of `04_architecture_proposal_v2.md`
> (1490 lines, Alternative A v2: per-machine manifests + sliced analyzer +
> RTP integrity gate + 6-phase migration). Per `.claude/agents/arch-critic.md`:
> 10+ stress questions, migration risk inventory, edge cases not covered,
> hidden assumptions, alternatives rejection double-check, final verdict.
> Critique, no redesign.
>
> Date: 2026-05-15
> Inputs: `00_brief.md` + `00_brief_v2_addendum.md` (the new contract),
> `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`,
> `04_architecture_proposal.md` (v1; reference), `05_critique.md` (v1
> critique — 17 stress questions, 5 top concerns), `06_validation.md`
> (v1 validation — 4 spec gaps), `04_architecture_proposal_v2.md` (THE
> TARGET — v2 designer rewrite, addresses 11 must-resolves + 4 spec gaps
> + 5 mapper blockers + 5 addendum updates).

---

## §1 Top concerns (most serious issues)

### Concern 1 — "Every machine potentially unique" philosophy is asserted but the implementation still secretly clusters via `inherits_from`

The addendum §1.5 is explicit: no default cluster tier; every machine has its
own manifest; "vanilla machines have short manifests, complex machines have
long manifests; quantitative difference only". v2 §5.5 says **"v2 picks
per-machine files (Option 5.5b)"** and §3 §327 reasoning #1 says **"There is
no 'default cluster' anymore"**.

But scroll to §5.5 variants subsection: v2 introduces `inherits_from`. The
M273$WheelSelector$0$ example at lines 720-729 inherits from M273.json and
declares only overrides. §7.1 open question hints at multi-level
inheritance.

**Why this matters**: `inherits_from` is a default-cluster-mechanism by
another name. The 85 M273 variants share a single underlying file
specifically because they were classified as "definitionally identical".
This is the same "share the cluster default" pattern the addendum rejected,
just renamed.

Worse — it's worse than v1's super-cluster approach because:

- v1 was honest that the super-cluster was the inheritance root. Operator
  could grep "members of SC-Vanilla" in one place.
- v2's `inherits_from` is per-machine-files. If 50 machines inherit from
  M273.json, finding them requires grepping all 421 manifest files for
  `"inherits_from": "M273.json"`. The discovery surface is worse.

And the underlying inheritance hop hides the structural similarity that
made the addendum's "every machine potentially unique" warning load-bearing:
an operator looking at M273$WheelSelector$42$.json sees only the override
delta and **cannot tell from one file** whether M273.json itself was
audited for RTP correctness. The addendum's premise — "M250 looked vanilla
until investigated; assume any machine could be like M250" — applies to
M273.json. If M273.json hasn't been audited under the new framework, 85
variants share its un-audited assumption.

Per `02 §4.1` observation 6: "all 166 variants share Axes 1-4 with their
underlying". This is exactly the "lump together" pattern memory
`feedback_invariant_with_fallback_hides_drift.md` warns against — except
now it's lump-by-inheritance rather than lump-by-default-cluster, and the
RTP integrity gate (§9) is supposed to catch errors per machine. But
**Layer 2 (fallback share) and Layer 3 (anchor coverage) require
rawdata**, and `02 §1` says 119 of 166 variants have NO rawdata. The
integrity gate cannot run for ~70% of variants. They are
inherits_from-trusted without verification.

This is a real residue of the v1 framing that v2 did not eliminate. The
addendum §1.5 paragraph 1 said "every one of the 421 machines has an
explicit manifest", but v2's variant inheritance produces variants whose
manifest content is effectively delegated. ✓ to the letter of "every
machine has a manifest file", but ✗ to the spirit of "every machine is
verified individually".

### Concern 2 — RTP integrity gate has false-positive cliff that will block legitimate operations

§9 lays out 3-layer check: Layer 1 (sum invariant) + Layer 2 (fallback
share ≤ threshold) + Layer 3 (required anchors present). The default
threshold is 0.5% (§5.5, §5.11 M1 manifest example). A machine fails if
ANY layer fails.

**Stress scenario** — fleet pull at 3am, M1 mode 1 fresh 10k spin sample:
- Layer 1 OK.
- Layer 2: fleet-pull RTP variance means `_unattributed_*` bucket could
  hit 0.6% on a particular 10k chunk by sampling noise. This is below
  the CI half-width that `02 §6.2`-ish vanilla machines naturally
  exhibit. **A "vanilla" machine with no structural fallback issue can
  trip Layer 2 just by sampling variance.**
- Result: M1 marked failed, run status='failed', operator paged at 3am.

`pia.main` returns non-zero exit (§9.4). `RunManager.start_run` marks
status='failed' with `failure_reason='rtp_integrity'`. Backend exposes
`GET /api/runs/{rid}/integrity`. The operator sees a red badge on M1 —
a machine that's never been a problem.

The proposal does not specify:
- Sample-size minimum for Layer 2 (should not gate on <50k spins).
- Statistical CI on `fallback_share_pct` (the threshold should be in CI
  terms not point-estimate).
- Whether re-run with more spins clears the failure.

**Construction of a hypothetical that passes all 3 layers but has wrong
RTP**: yes, this is possible.

Scenario: a machine's bonus_feature uses a multi-anchor settlement where
pay_id=A is the "official" anchor (e.g., a freespin trigger marker) and
pay_id=B is the actual win-bearing settlement. Manifest declares
required_attribution_anchors=[A] (operator's belief). Layer 3 passes
because A has > 0 hits. Layer 1 passes because the sum invariant holds.
Layer 2 passes because there's no `_unattributed_*` bucket — instead the
win was mis-attributed to pay_id=C (the wrong pid). The win went
*somewhere*, just not to the correct place.

This is the **mis-attribution case** memory
`feedback_invariant_with_fallback_hides_drift.md` discusses indirectly
(M274's 4.87% was correctly bucketed but to the wrong tag pre-rule). v2's
gate catches `_unattributed_*` leak (the "obvious fallback") but not "win
attributed to wrong real pid" (silent mis-attribution within real pids).

The 3-layer check is not a complete RTP correctness check. It's a fallback-bucket
+ anchor-presence check. The summary_message in §9.3 calls it "RTP
integrity FAILED" but it's checking 3 surrogates for RTP correctness, not
RTP correctness itself.

**Operator UX cost**: per the planned Phase 5 strict-default-error mode
(§9.5 `exception_policy = "error"` default), any false-positive blocks
the run AND the operator must (a) read the structured error, (b)
investigate, (c) downgrade exception_policy to "warn" if the failure is
legitimate sampling variance. Per §7.3 open question v2 even admits
"machines that have never been audited might unexpectedly fail" — but
defers the strict-vs-warn rollout to Wave 3. This is exactly the
"strict_when_unspecced" footgun.

### Concern 3 — Phase 2 forcing-function pre-commit gate cannot actually validate the framework

Per addendum §1.3, Phase 2 must onboard 12 known-complex machines AND
demonstrate the M250 graduation workflow end-to-end BEFORE locking the
framework. v2 §6 Phase 2 deliverables 4 and 5 codify this.

But Phase 2's onboarding of these 12 machines requires:

1. **`features/bespoke_m250_grid.py`** — but the grid mechanic for M250's
   20-reel singleton (`02 §3.3.2`, `02 §5.1`) hasn't been written
   anywhere yet. Phase 2's forcing-function deliverable requires this
   code to exist. Time estimate (§6.5): 10-14 days for Phase 2
   total — does that include writing 12 bespoke plugins from scratch
   AND the framework AND the parity tests? Per memory
   `feedback_invariant_with_fallback_hides_drift.md` M250 has 100% RTP
   leak — the bespoke fix is non-trivial.

2. **RTP integrity gate** is Phase 5 deliverable per §6. Phase 2 cannot
   verify "machine X passes RTP integrity" because the gate doesn't
   exist yet. Phase 2 §6 deliverable 5.2-5.4 explicitly says "Run RTP
   gate → fails with explicit error... Re-run RTP gate → passes." This
   requires the gate. So Phase 2 forcing function depends on Phase 5
   deliverable — **but Phase 5 comes after Phase 2 in §6.5 ordering**.

Either:
- Phase 5 deliverable 1 (the rtp_integrity.py module) needs to ship in
  Phase 2 (out of phase order; deliverable 6.5's "Phase 5 last" reasoning
  is broken), OR
- Phase 2's forcing-function workflow demo is impossible to execute as
  specified (workflow requires gate that doesn't exist yet).

Reading §6 Phase 2 deliverable 5 carefully: "Run RTP gate → fails with
explicit error." This presumes the gate exists. §6 Phase 5 deliverable
1 says rtp_integrity.py is created in Phase 5. **The forcing-function
demo cannot be performed without re-ordering deliverables**, but the
proposal claims §6.5 "Why Phase 5 last" reasoning supports the ordering.
Internally inconsistent.

3. **The 12 forcing-function plugins**: v2 §6 Phase 2 deliverable 4 says
   "If any of these 12 cannot be expressed cleanly, the framework
   iterates (e.g., add a new lifecycle hook, expand `AnalyzerFeature`
   Protocol, etc.) BEFORE Phase 2 is locked." This is the right
   discipline. **But**: per memory `feedback_invariant_with_fallback_hides_drift.md`,
   M250's bespoke fix has not been built today. So during Phase 2 the
   team must build M250's bespoke implementation. That can take days
   itself. Per §6.5 timing 10-14 days is optimistic if 6 of 12 plugins
   are net-new code (M250, M268, M260, M21 Buffalo, M67, M11 — all
   per Validator §3.1 / §5.1 heavy outliers that lack any existing
   bespoke today).

The forcing function is the right idea (resolves Critic Concern 5 from
v1). But its execution depends on (a) RTP gate existing in Phase 2 —
contradicting §6.5 phase ordering, and (b) 12 net-new bespoke plugins
existing in 10-14 days — optimistic.

### Concern 4 — `inherits_from` semantics undefined for the case that matters most: 166 variants change when underlying changes

§7.1 explicitly raises this — "is `inherits_from` the right semantic?
Should we support multi-level inheritance?" v2 §5.5 picks (b) inheritance
via `inherits_from` because variants share Axes 1-4.

But the cascade question is unanswered:

**Scenario A**: M273.json changes its `analyzer_features` array (e.g.,
adds `cycle_peak_detection` because Phase 5 audit found leak). All 85
M273$WheelSelector$*$ variants — do their `effective_analyzer_version`
hashes ALSO flip? §4.6 hash composition map line 497 says manifest changes
flip `effective_analyzer_version` — but for the inheritor or the
inheritee?

If inheritance is "lazy" (compute the effective manifest from inherits_from
chain at every hash computation), then yes — 86 hashes flip (1 underlying +
85 variants). **This is the same 86-machine cohort fan-out as today's
upstream md5 fanout per `03 §3.4` ("c2a4e3be71b798a8...: 86 machines on
the same code hash")**. No reduction.

If inheritance is "eager" (variants get a snapshot of M273.json's
manifest at variant-create time), then changing M273.json doesn't
propagate to variants — and now variants drift from their underlying.
Per `02 §4.1` observation 6 variants are "definitionally identical except
selector parameterization". If they don't auto-update, then variants
silently keep using old manifest content while M273.json's audit fix
sits unapplied to 85 of its 86-machine cohort.

Neither resolution is clean:
- Lazy = 86-machine cohort fan-out (the v1 outcome).
- Eager = silent drift between variants and underlying.

§7.1 defers to Wave 3 v2 (critic). My answer: this is not deferrable. The
hash composition algorithm and the manifest schema both encode this
choice. The "every machine potentially unique" addendum philosophy
demands eager (variants are independent files; updates explicit). But
that requires the 85 M273 variant files to update in lockstep when
M273.json updates — which is the same operational coupling as 85 rows in
a central manifest file. The supposed "per-machine PR isolation"
advantage of per-machine files vanishes.

### Concern 5 — Phase 6 "optional consolidation" creates a half-state where 22 BCM machines violate manifests

Per §6 Phase 6 deliverables, "Consolidate `machine_round_win_rules.json`
into per-machine manifests" is **optional**. Phase 5 ships the strict-error
RTP integrity gate (§9). Phase 6 ships "audit medium outliers (`02 §5.2`
~30 machines) — write manifests for them; run RTP integrity; address any
failures."

But §5.6 manifest validation rule 1 says "every machine in
configs/machines.json MUST have a manifest file in machine_manifests/.
Missing file = error." And Phase 3 ships 421 manifest files. So all 421
machines have manifests by Phase 3.

The conflict: Phase 5 ships the RTP gate as strict-error. Phase 5 gate
runs on every fleet-wide pull. Per `02 §3.5.1` 22+ BCM machines today
silently leak >0.5% RTP into `_unattributed_st<N>`. Phase 5 catches
these — sets `passed=false`. `RunManager.start_run` marks
status='failed'. UI shows red.

**Phase 6 is "optional"** — meaning Phase 5 ships **first**, with 22
broken-from-day-one BCM machines. Operators see 22 red banners. Phase 6
addresses the medium outliers but is deferred (and per §6.5 "Phase 6
LOW; optional throughout").

How does this work in practice?

Option A: Phase 5 ships in opt-in (warn-only) mode initially, escalating
to strict-error later. v2 §6 Phase 5 deliverable 6 says "default is
strict" — but rollout language at end of Phase 5 says "Gate becomes
opt-in on rollback". Inconsistent.

Option B: Operators downgrade `exception_policy` to "warn" for the 22+
machines until Phase 6 fixes them. But Phase 5 hasn't been written yet
when those manifests need to be created (Phase 3). Either the manifests
ship with exception_policy=warn for those 22 (defeating the strict
default), or the manifests ship with exception_policy=error and the
operator hits 22 errors on Phase 5 deploy.

Per Critic Concern 3 in v1 critique — and explicit Critic Concern 3 in
v2 above — this is the strict-vs-lenient question that addendum §1.4
explicitly demanded resolution for. v2 says "strict" but the rollout
sequence ships the strict gate BEFORE the audits that find the bugs.
The right ordering is Phase 6 fixes BEFORE Phase 5 strict gate. v2 has
them backwards.

§7.3 open question even acknowledges this: "should there be a per-machine
'audited' flag... Or is the cleaner play to require operator audit
before manifest commit?" That's the right question, but the proposal
doesn't pick — yet ships Phases 3 → 5 in an order that breaks if neither
is picked.

---

## §2 10+ stress questions

### Q1 — Did the designer actually shift philosophy, or just paper over the v1 "84% cluster" framing?

**Question**: addendum §1.5 explicitly rejected v1's "default cluster + 12
outliers" framing. v2 claims to integrate this throughout §3, §5, §6.
But scan v2 §3 reasoning #1: "Two machines that both declare {base,
freespin_v2} are on a shared path *because they both declared it*, not
because they were classified into the same tier." Test this by reading
the manifest examples in §5.11 — does M1's manifest look like "every
machine potentially unique" or like "M1 is in the default cluster
template"?

**Attempted answer for the designer**: §5.5 picks per-machine files
(Option 5.5b). §5.11 shows M1.json — 8 fields declared explicitly. §3.327
explicitly disclaims default cluster.

**Why insufficient (re-read with hostile lens)**: The M1 manifest example
at §5.11 lines 803-825 declares 4 features — `payouts_by_spin_type`,
`reel_marginal_by_spin_type`, `bankruptcy_simulation`, `multiplier_profile`.
This is **identical** to the v1 SC-Vanilla cluster default per `04 §5.5`
(v1). The fact that it's spelled out in M1.json instead of inherited
from a cluster doesn't change the substance — operators will copy-paste
this 4-feature block into 213+ "vanilla" machine manifests. The
default-cluster pattern emerges in practice via copy-paste even if the
mechanism is per-machine files.

Per §6 Phase 3 deliverable 1: "Write 421 per-machine manifests... Most
machines are short manifests (~10 lines JSON declaring 4-5 universal
features)." This sentence is **literally describing a cluster default
applied 200+ times**. The framework permits per-machine difference; the
canonical onboarding flow is "use the standard 4 features unless you
know otherwise". The addendum's warning ("保持警惕" — stay vigilant)
operationalizes to "verify every one of the 4-feature manifests is
actually correct for that machine via RTP integrity". The RTP gate
attempts this (§9) but fails for the 215 rawdata-less machines (§8.12).

**Hidden cluster default**: the 4-feature template at §5.11 M1 is the
de-facto default cluster. v2 has the mechanism for per-machine variation
but inherits v1's tendency for ~200 machines to use the same template.

Concretely — looking at §5.11 M1.json field-by-field:
- `feature_tags: ["Plain"]` — that's the F-Plain super-cluster from `02 §3.2`
- `analyzer_features: [4 universal]` — that's the SC-Vanilla cluster default
- `rtp_integrity_contract.fallback_share_threshold_pct: 0.5` — the global default

Per addendum §1.5: "保持警惕,...所有的机台都有可能有这种程度的复杂性".
The operator filling in 213+ manifests with the same 4-feature template
is **not** being vigilant. They're being efficient. The addendum-vs-pragmatics
tension is unresolved.

**Verdict**: ⚠ partial — mechanism shifted; canonical operational pattern still
clusters via convention. The addendum's "every machine potentially
unique" only shows up if operators write per-machine validating audits
(which requires rawdata which 215 machines don't have).

### Q2 — Can a machine pass all 3 RTP integrity layers and still have silently wrong RTP?

**Question**: per Concern 2 above, layers 1+2+3 cover sum invariant +
fallback share + anchor coverage. None of these checks "is the win
attributed to the *correct* real pid". Construct a case.

**Attempted answer for the designer**: §9.6 "If Layer 2 fails (fallback
share too high)... If Layer 3 fails (missing anchors)..." Both deal with
detectable misattribution. Implicit assumption: any misattribution shows
up as Layer 2 or Layer 3 failure.

**Hypothetical that breaks the gate**: machine X has 2 paylines paying
the same symbol set (e.g., 3 Cherries left-to-right and 3 Cherries
right-to-left). Paytable defines pay_id=10 for line 1 (left), pay_id=11
for line 2 (right). Both should fire equally often.

A bug in `attribute_lines_to_pay_ids` (`round_classification.py:232`)
misroutes win for left-to-right lines into pay_id=11 (the right-only
pid). Result: pay_id=10 has 0 hits in summary; pay_id=11 has 2x hits.

- Layer 1: `sum(pid_win) == chunk_win`. **Passes**. Total RTP is correct.
- Layer 2: no `_unattributed_*` bucket. **Passes**. fallback_share_pct=0.
- Layer 3: required anchors. Manifest may not list pid=10 as
  "required attribution anchor" (it's a vanilla payline, not an
  anchor). **Passes**.

Result: gate is GREEN. Operator believes "RTP integrity OK". But pay_id=10
is silently dead in every report. UI shows pid=11 as twice as common as
it is. Player-impact analysis is wrong even though sum-RTP is right.

This is exactly the kind of "wrong attribution within real pids" memory
`reference_round_classification_primitives.md` documents (Bug 1, suffix
attribution). The RTP integrity gate doesn't check for it.

**Suggested mitigation the designer might offer**: "the rawdata sanity
check at §5.6 rule 7 validates that observed paid-ST matches manifest".
That's about ST presence, not pid attribution correctness. The gate has
no check on **per-pid hit distribution sanity**. ✗ not addressed.

**Verdict**: ✗ not addressed — gate is incomplete. Can pass all 3
layers with silently wrong attribution. The gate's name "RTP integrity"
overpromises; it's really a "fallback-bucket + anchor-presence" check.
Misattribution within real pids is invisible.

### Q3 — 421 × manifest overhead: is the proposed onboarding workflow realistic?

**Question**: Phase 3 deliverable 1 says "Write 421 per-machine manifests
in slot_designer/configs/machine_manifests/<M>.json". Per §6.5 estimate:
4-6 days for Phase 3 total. Authoring 421 manifest files in 4-6 days =
~70-105 manifests/day. Spec the writing workflow. Who authors them?
Auto-generated from rawdata? Slot-* team? Validator audit?

**Attempted answer for the designer**: §6 Phase 3 deliverable 1 implies
"Most machines are short manifests (~10 lines JSON declaring 4-5
universal features)" — copy-paste template. The 12 forcing-function
machines + variant underlyings get longer. v2 §6 Phase 3 deliverable 9
mentions `scripts/manifest_audit.py` (fleet-wide drift report) and
`scripts/manifest_lint.py` (single-file lint) as bulk tooling.

**Why insufficient**:

- **Auto-generation source**: from `configs/machines.json`'s logicClassNames?
  From `bcm_pairings.json`? From observed rawdata fingerprint? Per
  `02 §3.5` the inference between observable signal and manifest content
  is fuzzy — `logicClassNames=Plain` does NOT mean the analyzer's vanilla
  default produces correct RTP (per addendum §1.5 paragraph 1: "Plain"
  does not mean simple).
- **Auto-generation correctness**: if M250 today shows surface signal of
  "BCM" (logicClassNames=BCM) and we auto-generate manifest with
  `analyzer_features=[<BCM cluster defaults>]`, RTP integrity catches the
  100% leak and operator must intervene. But the operator doesn't know
  *which* of the 421 auto-generated manifests are wrong without running
  the gate on each one. Per `02 §1` only 206 machines have rawdata; the
  other 215 can't be gate-tested at manifest-author-time.
- **Per addendum §1.5** the spirit is to be **vigilant** about each
  machine. Auto-generation produces a "default cluster"-quality manifest
  for 200+ machines without any per-machine verification.

§6 Phase 3 deliverable 1 estimates 4-6 days but doesn't say where the
authorship effort goes. If it's auto-generation, the addendum's vigilance
mandate is violated. If it's per-machine review, 4-6 days is ~50
manifests/day vigilant review — unrealistic for any single operator.

The proposal needs to spec:
- Initial bulk generation pipeline.
- Per-machine review gate.
- Slot-* team handoff if review requires slot-* expertise.
- Manifests for the 215 rawdata-less machines (can't run §5.6 rule 7).

§7.3 open question even names a subset of this: "should there be a
per-machine 'audited' flag in the manifest, where un-audited machines
default to 'warn'?" This is the operationally-load-bearing question
about the manifest authorship workflow, deferred.

**Verdict**: ⚠ partial — strategy claimed, no spec for the bulk authorship
workflow. 4-6 day estimate is unsubstantiated. Per addendum §1.5
vigilance principle is in tension with bulk authorship; tension
unresolved.

### Q4 — Phase 2 forcing-function workflow demo: is M250 actually onboardable as vanilla today?

**Question**: §6 Phase 2 deliverable 5 specifies the M250 graduation
workflow end-to-end. But Validator §2.4 (the v1 validation) noted M250
has "0 on-disk reports" — the file system has no M250 report version
dirs. M250 has 8 completed runs in the DB but no surviving artifacts.
**Can M250 actually be onboarded as vanilla today?** Per memory 100% RTP
leak — the vanilla manifest declaration ("M250 should be SC-BCM-Modern")
would immediately fail the gate. So the **workflow demo's "start with
vanilla manifest, fail, add bespoke, pass" sequence requires M250's
rawdata to be analyzed AND the bespoke plugin to exist BEFORE Phase 2
ships**.

**Attempted answer for the designer**: §6 Phase 2 deliverable 4 names
`bespoke_m250_grid.py` in the 12 plugins to write during Phase 2. §6
Phase 2 deliverable 5 walks the workflow end-to-end.

**Why insufficient**: re-reading Phase 2 deliverable 5 step-by-step
(§4.3 Example 6 from line 449):
1. Machine X starts with a short manifest declaring 4 universal features.
2. RTP integrity gate (§9) runs → fails.

Step 2 requires §9 to exist. Per §6.5 Phase 5 ships the gate. **Phase 2
deliverable 5 cannot be executed before Phase 5**. This is the same
inconsistency as Concern 3 above.

Alternative reading: "RTP integrity gate" in §6 Phase 2 deliverable 5
refers to ad-hoc rawdata analysis (not the full §9 gate); operator
manually runs `verify_payid_invariant.py` from memory
`reference_round_win_rule_architecture.md`. But this isn't the same
thing — it's a per-fixture lint, not a fleet-wide integrity gate.

If Phase 2 must demonstrate the workflow but the gate doesn't exist:
- Operator demonstrates manually with ad-hoc scripts.
- Phase 5 later ships the formal gate.
- The "workflow" the proposal claims to validate in Phase 2 is **a
  hypothetical-future workflow**, not the actual one.

§4.3 Example 6 paragraph 7: "Framework unchanged — no analyzer monolith
edit, no Phase-2-level refactor. Just added a new feature file +
manifest line." But until Phase 5 RTP gate exists, the operator has no
**mechanism** to discover that M250 needs the bespoke plugin in the
first place. The workflow's discovery step requires the gate, which
ships later.

**Verdict**: ✗ not addressed — Phase 2 forcing-function workflow demo
is internally inconsistent with §6.5 phase ordering. Either Phase 5's
gate ships earlier or Phase 2's workflow demo is a hand-wave.

### Q5 — Hash composition mode dimension: does `|| mode` break cross-mode comparison?

**Question**: v2 §4.1 algorithm:
```
effective_analyzer_version(M, mode) =
    sha256(base_hash || sorted(features_M_uses[mode]) || mode)[:12]
```
Frontend currently compares mode-1 vs mode-5 reports of same machine
(per `01 §2 layer 5` `compareReports` at `app.js:3477`). Under v2, two
reports from M14 mode 1 and M14 mode 5 always have **different**
`effective_analyzer_version` values (because `|| mode` differs). Does
this break compare-mode rendering?

**Attempted answer for the designer**: not directly addressed in v2. §6
Phase 4 deliverable 3 mentions "compare_diff.js integration" but says
"parallel registry mechanism so compare-mode rendering also goes through
registry-driven fallback". It's about renderer dispatch, not version
comparison.

**Why insufficient**: `compareReports` at `app.js:3477-3504` compares two
report versions. Under v1, both reports of same machine, different mode
share the same whole-file `analyzer_version` — comparison renders as
"same analyzer, different mode". Under v2, **their effective versions
differ structurally** even when both manifests + features are identical
because mode is baked into hash. The "analyzer version match badge" at
`app.js:1895 _renderRwtreeCell` would show "different analyzer" for the
two reports, which is misleading.

Per `02 §3.1` headline: paid-ST is mostly 1 or 140. Many machines have
same analyzer_features across modes. Under v2:
- M14 mode 1 effective_version = sha256(base || features || "mode=1")
- M14 mode 2 effective_version = sha256(base || features || "mode=2")
- These differ even with identical features.

Per §5.5 `per_mode_overrides` is for machines that genuinely differ per
mode (M14 might be one — memory `user_testing_machine.md`). But for
machines where per-mode features are identical, the mode-dim baked into
hash is noise.

**Better design**: only include mode in hash if `per_mode_overrides` is
non-empty for that mode (i.e., the machine actually distinguishes
per-mode). v2 §4.1 unconditionally includes mode. This forces
mode-distinct hashes even for machines that don't distinguish, breaking
comparison badges.

**Verdict**: ⚠ partial — mode dimension addresses Critic v1 Q11 but
introduces a UX regression for cross-mode comparison. Designer should
conditional the mode dim on per_mode_overrides presence.

### Q6 — Phase 6 "optional consolidation": can Phase 5 ship before Phase 6?

**Question**: Phase 6 is marked "optional / out-of-scope". §6.5 timing
table says Phase 6 LOW risk, 3-5 days, "optional throughout". But Phase
5 (RTP gate strict-error) ships before Phase 6 (medium outlier audit).
Per `02 §3.5.1`, 22+ BCM machines today silently leak. Per §6 Phase 3 deliverable 1
those 22 machines get manifests in Phase 3 declaring `cycle_peak_detection`
+ universal features. Per `02 §3.5.1` memory, only 13 have explicit
RoundWinRule; the other ~22-27 have no rule. They will FAIL Layer 2 of
the gate on Phase 5 deploy with `_unattributed_*` > 0.5%.

What's Phase 5 deploy day look like for those 22 machines?

**Attempted answer for the designer**: §6 Phase 5 deliverable 5 has the
known-broken triage table — names M250, M268, M260, M264, M163, M147 (6
machines). "By Phase 5 completion, every machine in the table has either
passed integrity OR has explicit operator sign-off on warn policy."

**Why insufficient**:

- The named 6 in the table doesn't match the 22+ from memory
  `feedback_invariant_with_fallback_hides_drift.md`. Memory says "55 of
  117 cached BCM (m, mode) pairs >0.5%". `02 §3.5.1` extrapolates to
  ~22-27 machines (M250 100%, M268/M260/M264 70-90%, M163/M147 35%, plus
  another ~16-21 in the 0.5-35% band). v2's triage table covers ~6 of
  the ~22; the rest are undocumented.
- "By Phase 5 completion" means Phase 5 ships then closes ALL these. If
  Phase 5 is 5-7 days (§6.5), and 22 machines need bespoke plugins or
  rule enablements, that's ~3-4 hr/machine including auditing rawdata,
  writing fix, testing — tight but conceivable.
- **But**: Phase 5 ships the gate as strict-error default (§9.5). During
  Phase 5 development, **every fleet pull triggers the gate**. The 22
  red banners appear immediately. Operators (and CI) see fleet-wide
  errors during Phase 5's own development cycle.

The proposal does not spec:
- How Phase 5 ships incrementally so the gate goes live only after the
  22 triage entries are clean.
- What happens during the multi-day Phase 5 development cycle when
  the gate is "almost ready but 22 machines still red".
- Whether Phase 5 is feature-flagged at the per-machine level vs global.

§7.3 open question speaks to this ("audited flag"). v2 doesn't pick. So
the Phase 5 rollout is undefined in practice. Designer says "default is
strict" but operationally Phase 5 day 1 = 22+ red banners.

**Verdict**: ⚠ partial — Phase 5/6 ordering creates a half-state. Strict
gate ships before all manifests pass it. Operationally broken.

### Q7 — `feature_registry.ALL_FEATURES`: maintained manually? Auto-discovered? Trust model?

**Question**: v2 §5.7 says feature modules MUST be imported in
`fresh_slotlab/analyzer/features/__init__.py` (single import list).
Each feature module uses `@register` decorator. `feature_registry.ALL_FEATURES`
is the runtime source of truth. **What's the trust model?**

**Attempted answer for the designer**: §5.7 specifies the discovery
mechanism explicitly — manual `@register` decorator + manual import in
`__init__.py`. Manifest validation rule 2 (§5.6) catches manifest typos
at commit/deploy time. Runtime errors out clearly.

**Why insufficient**:

- **Race condition with manifest authoring**: if dev1 adds
  `features/foo.py` and registers via `@register`, but dev2's manifest
  PR doesn't yet reference it, what happens? The feature exists in
  registry but no machine uses it. §5.10 says "Adding a feature:
  register; add reference in any machine manifest that needs it. RTP
  gate validates." Adding without referencing is allowed.
- **Reverse**: dev3's manifest references `foo` before `features/foo.py`
  is merged. Manifest validation fails per §5.6 rule 2. But what if
  someone runs the analyzer before validation runs? Runtime error per
  §5.7 — "RuntimeError: machine M_X manifest references feature 'F_id'
  not in registry". Run aborts. Per `01 §2 layer 4 _watch_run`, the
  status='failed'. Operator sees red.
- **Stale registry on disk**: per `03 §4.4` "per-worker in-process
  caches" — `_MACHINES_SUMMARY_CACHE` etc. are per-worker. If a worker
  warms up with registry version A while features/ has been updated to
  version B, dispatch is wrong. Per Critic Edge Case 1 (v1 critique) +
  v2 §6 Phase 4 deliverable 7 ("Frontend cache-bust for RENDERER_REGISTRY
  updates: include the registry version in {{ASSET_HASH}}"). Frontend
  covered. Backend not — no `_FEATURE_REGISTRY_VERSION` invalidation.
- **Trust assumption**: registry trusts that every `@register`-decorated
  class is a valid feature. No runtime check that `FEATURE_ID` is unique
  (two modules with same FEATURE_ID would silently overwrite the
  registry entry). No check that `SCHEMA_KEYS` is non-empty (a feature
  declaring no keys writes nothing). No check that `REQUIRES` references
  exist.

**Verdict**: ⚠ partial — mechanism specified; trust model under-specced
(uniqueness, validity, cache invalidation in multi-worker).

### Q8 — SCHEMA_VERSION enforcement: frontend renderer schema_version differs from data — hard fail? Soft warning? Migration?

**Question**: v2 §5.4 sets up SCHEMA_VERSION bump policy. §5.3
RendererPlugin has `minSchemaVersion`, `maxSchemaVersion`, `fallbackRules`.
A report on disk has `summary.schema_versions[feature_id] = X`.
Renderer's `[minSchemaVersion, maxSchemaVersion]` doesn't include X.
What happens?

**Attempted answer for the designer**: §5.3 codes the renderer with
explicit version range + fallbackRules. The `_paintAnalysisFromSummary`
iterates registry; checks `summary.schema_versions[feature_id]` vs
supported range; selects fallback if needed.

**Why insufficient**:

- **Case: X < minSchemaVersion AND no fallback rule for X→current**.
  Per §5.3 example M14 mode 1 v1 report would have `schema_versions:
  {payouts_by_spin_type: 1}`. Renderer declares `minSchemaVersion: 1`.
  OK. But for a feature with `minSchemaVersion: 2` (the new schema),
  a v1 report has version=1 which is below minimum AND no fallback
  exists. Designer's intent presumably: skip the renderer (empty
  panel). But §5.3 example sketches the dispatch logic loosely. What
  the actual behavior is when version is out of range and no fallback
  exists — undefined.
- **Case: X > maxSchemaVersion** (future report on disk, current
  frontend doesn't know that schema). Same question, opposite direction.
  A newer summary in a rollback scenario would have schema_version 3
  while current frontend understands 1-2. Behavior unspecified.
- **Case: feature module deleted (per §5.10), but historical reports
  reference its schema_version**. v2 §5.10 says "report is simply
  marked 'incompatible with current analyzer'; operator regenerates".
  But until regen, the report is on disk. UI shows it. What does the
  renderer do? Show empty panel? Crash? Show legacy field via the v1
  inline path? Undefined.
- **Case: enforcement bypass**. The pre-commit hook (§5.4) is the
  enforcement. But it operates at git commit time. A developer could
  push directly to the branch without local hook, or override with
  `--no-verify`. CI catches second case (per `00 §3` policy). But
  rebase-and-force-push could rewrite history, possibly slipping a
  silent rename through. §5.4 says "block commit with a clear error
  message" — assumes the developer doesn't bypass. No runtime check
  catches a schema rename without bump if the hook was bypassed.

**Verdict**: ⚠ partial — happy path covered; out-of-range / deleted /
hook-bypass cases unspecified.

### Q9 — `AnalyzerFeature.REQUIRES` topological dependency: cycle handling? Deprecated-but-dependents?

**Question**: §5.2 adds `REQUIRES` to AnalyzerFeature ABC. §5.7
specifies topological sort at orchestrator startup. **What if there's a
cycle? What if a feature is deprecated but still has dependents?**

**Attempted answer for the designer**: §5.7: "Cycle in REQUIRES → error
at registry initialization." This covers cycle.

**Why insufficient**:

- **Cycle handling specifics**: at registry initialization (which is
  application boot per §5.7 "feature_dependency_order... raises if
  cycle"), if a cycle is detected the analyzer fails to start. Per
  `01 §2 layer 4` `RunManager.start_run` spawns analyzer subprocess —
  if subprocess startup fails, the run's status is set to 'failed'. Per
  `_watch_run` (referenced in `01 §2 layer 4`) the failure surfaces. OK
  for the analyzer process. **But what about the backend itself**? Per
  `01 §2 layer 4` `create_app` is called for both consoles. If the
  backend imports feature_registry at app start (likely), a registry
  cycle kills the FastAPI app's boot, taking down both consoles.
  Recovery: revert feature module. No graceful degrade.
- **Deprecated feature with dependents**: §5.10 says "Deleting a
  feature: only allowed if no manifest references it. CI lint job:
  search all manifests for the feature_id; if found, deletion blocked."
  This handles manifest references but **not REQUIRES references**. A
  feature F1 may have `REQUIRES = ("F2",)`. If F2 is deleted (no
  manifest references it; only F1 does via REQUIRES), the deletion lint
  passes — but F1's REQUIRES now points to non-existent F2. Runtime:
  topological sort fails. F1 cannot be loaded. Every machine declaring
  F1 fails.
- **Stale dependency check**: §5.10 doesn't say `scripts/manifest_lint.py`
  checks REQUIRES dependency reachability. So a feature deletion can
  break F1's REQUIRES chain silently until next analyzer boot.

**Verdict**: ⚠ partial — cycle detection mentioned; deprecation/REQUIRES
interaction not specified.

### Q10 — `inherits_from` variant semantics: what happens when underlying changes?

**Question (deep dive on Concern 4)**: M273.json changes (e.g., adding
`cycle_peak_detection` to analyzer_features). 85 M273$WheelSelector$*$
inherit_from M273.json. Cascade? Manual?

**Attempted answer for the designer**: §5.5 specifies `inherits_from`
syntax. §7.1 explicitly defers semantic question (multi-level? cascade?)
to Wave 3 v2.

**Why insufficient**: per Concern 4 above, lazy resolution = 86-machine
fan-out per change (the v1 outcome); eager = silent drift between
variant and underlying. v2 doesn't pick.

Per `03 §3.4` upstream md5 fanout already shows 86-machine cohorts. If
v2's `inherits_from` is lazy, the manifest-driven cohort is the same
shape. The blast-radius table at §1.3 has "Per-cluster feature edit: 12-30
machines" — but **edits to M273.json affect 85 variants** under lazy
inheritance, which is way above the 12-30 range. This contradicts the
table.

If v2's `inherits_from` is eager, then operators must propagate M273.json
changes to 85 variant files manually. The "per-machine PR isolation"
advantage is lost.

§5.5 paragraph 728-733 gives a variant manifest sketch with three
"_override" fields all null. This suggests **eager** (variants override
selectively; null means "inherit at compute time"). But the algorithm
in §4.1 reads `manifest.analyzer_features` for hash composition; if
variant manifest has `analyzer_features_override: null`, the resolution
must look up underlying — that's **lazy**. Internal contradiction.

**Verdict**: ✗ not addressed — semantic genuinely deferred to Wave 3 v2
critic. My answer: cannot pick without breaking either blast-radius
profile or per-machine isolation. Either way, addendum §1.5 "every
machine potentially unique" via inheritance is **structurally weaker**
than per-machine fully-explicit manifests.

### Q11 — Phase 2/Phase 5 cross-dependency: forcing function workflow needs gate that ships in Phase 5

**Question** (cf. Concerns 3+5+4): Phase 2 deliverable 5 requires §9 RTP
integrity gate. §6 Phase 5 ships the gate. So Phase 2's workflow demo
depends on Phase 5. Reconcile.

**Attempted answer for the designer**: §6.5 phase summary table puts
Phase 5 in slot 5 (after Phase 2). v2 §6 Phase 2 deliverable 5 walks the
workflow but doesn't explicitly cite that the gate is required.

**Why insufficient**: Phase 2 step "Run RTP gate → fails with explicit
error" requires the gate. Reading Phase 2 deliverable 5 sub-bullets
again:
```
2. Run RTP gate → fails with explicit error.
3. Add features/bespoke_m250_grid.py to fix.
6. Re-run RTP gate → passes.
```
"Run RTP gate" can only execute if rtp_integrity.py exists. v2 §6 Phase
5 says rtp_integrity.py is a Phase 5 deliverable. **Phase 2 cannot
complete deliverable 5 without Phase 5's rtp_integrity.py**.

Possible designer fix:
- Re-order: Phase 5 → Phase 2.
- Carve a minimal subset of §9 (just Layer 2 fallback check) into Phase 2
  as a "preview gate" without UI / fleet-wide / etc.
- Drop deliverable 5 from Phase 2; restructure workflow demo as Phase 5
  task.

None of these are specified. The proposal claims Phase 2 forcing
function exists AND Phase 5 ships gate, in this order. Internally
inconsistent.

**Verdict**: ✗ not addressed — phase ordering is broken.

### Q12 — 215 of 421 machines without rawdata bypass §5.6 rule 7

**Question**: §5.6 rule 7 is rawdata sanity check ("if rawdata is
available... must match observed paid-ST set"; "if cycle_peak_detection
NOT declared but rawdata has CollectCount extras, error"). Per `02 §1`,
**215 of 421 machines have no rawdata**. Rule 7 is bypassed for them.
Per addendum §1.4 constraint S — fleet-wide pull must emit correct RTP
or explicit error. Per §9.1 RTP gate also needs rawdata to compute
fallback_share_pct. 215 machines without rawdata cannot be gate-checked
either.

**Attempted answer for the designer**: §8.12 explicitly disclaims: "215
machines without rawdata bypass that rule. Future task: backfill rawdata
or accept manifest authoring without rawdata-driven validation."

**Why insufficient**: §8.12 puts it in out-of-scope. But it's **load-bearing
for constraint S compliance**. The addendum §1.4 said "for any
fleet-wide pull". 215 machines (>51%) of the fleet can't run constraint
S in any meaningful sense.

§9.5 lists triggers — every fleet-wide pull. The 215 machines:
- Never run live sampling because they're on the registry but rawdata
  has never been collected.
- May be triggered for sampling via `POST /api/runs` someday.
- Their manifests are written sight-unseen (no rawdata to verify against).

When such a machine is sampled for the first time post-Phase-5: the
chunk arrives, the analyzer runs, fallback_share_pct is computed, gate
runs. Either:
- Gate passes — the 215 machines' "blind" manifests turned out to be
  correct (lucky / well-templated).
- Gate fails — manifest needed work; operator gets red banner on the
  first fleet pull involving the machine.

The proposal doesn't address this discovery moment. The 215 machines are
in a "manifests authored but not yet RTP-validated" state for as long as
they remain rawdata-less. The whole constraint-S premise is **conditional
on rawdata being present**, which holds for only 51% of the fleet today.

**Verdict**: ⚠ partial — disclaim in §8.12, but constraint S can't be
honored for the 215. The disclaimer is technically present; the
implication for addendum §1.4 unaddressed.

### Q13 — In-process monkey-patch path: pia.main moves but post_json stays — sound?

**Question**: §5.8 says `pia.post_json` stays in `player_impact_analyzer.py`;
`pia.main` stays as the public CLI entry but becomes a thin orchestrator
importing from `analyzer/core/base_pipeline.py`. Monkey-patches attach to
pia.* unchanged. Per `01 §2 layer 4` 3 monkey patches: pia.post_json,
sys.argv, os._exit. Phase 1 deliverable 9 codifies 3-style parity test.

**Attempted answer for the designer**: §5.8 says monkey-patches attach
at same attribute. Phase 1 deliverable 9 byte-identical-summary parity
test enforces equivalence.

**Why insufficient**:

- **`os._exit` patch**: Per `01 §5 #1` the in-process path patches
  `os._exit` so analyzer's process-suicide at `pia:8170` doesn't kill
  the backend. Per §5.8, `pia.main` lives in player_impact_analyzer.py.
  But the actual exit-call site — if it lives inside
  `analyzer/core/base_pipeline.py:main_post_process` or similar — would
  call `os._exit` from there. Monkey-patch on `pia.os._exit` attaches
  to the `os` module reference from `pia`'s namespace. Submodule
  `analyzer/core/base_pipeline.py` has its own `import os`. Patching
  `pia.os._exit` doesn't affect `analyzer.core.base_pipeline.os._exit`.
  In-process replay can be killed unless the patch attaches more deeply.
- **`sys.argv` patch**: same issue — `pia.main` reads `sys.argv` at
  invocation. If `pia.main` immediately delegates to
  `analyzer.core.base_pipeline.entry(args)`, then `sys.argv` patch
  works (read in pia first). But if argv reads happen inside core
  modules (e.g., argparse), `sys.argv` is module-global; monkey-patch
  on `sys.argv` works regardless of where the read happens. **OK**.
- **`pia.post_json` patch**: per §5.8, `pia.post_json` stays in
  player_impact_analyzer.py. Patching attaches; OK. **But**: if any
  core module also imports `post_json` (e.g., `from .. import
  post_json`), it'd hold a name-bound reference to the original. Patch
  on pia.post_json doesn't affect the core module's bound reference.

These are technical implementation details, but `01 §5 #1` calls out
"the contract that says 'these three behave the same' is implicit (no
spec / tests asserting all three produce identical summaries)". v2
Phase 1 deliverable 9 codifies the parity test. **But** the parity test
proves equality on **today's** behavior; after Phase 2 slicing, all
three styles invoke a different `pia.main` (the thin orchestrator). If
the parity test runs in Phase 1 (before Phase 2), it tests the pre-slice
code. Re-running the parity test in Phase 2 post-slice would re-verify.
§6 Phase 2 deliverable 8 mentions per-cluster regression tests; doesn't
explicitly mention re-running the 3-style parity test.

**Verdict**: ⚠ partial — direction good; specific patching pitfalls in
sliced architecture not enumerated.

### Q14 — Manifest authoring during Phase 3: per-mode override semantics for "in-scope" vs "out-of-scope" modes

**Question**: §5.5 `per_mode_overrides` example shows M274 mode 5 having
`analyzer_features_remove: ["bonus_chain_dynamics"]`. Per memory
`user_testing_machine.md` "mode 2/5 RTP 不可精准监控" — RTP cannot be
precisely monitored on modes 2/5. So mode 2/5 are out-of-scope for
RTP precision. Does the per_mode_overrides include `rtp_integrity_contract`
override (per-mode threshold relaxation)?

**Attempted answer for the designer**: §5.5 shows only
`analyzer_features_remove/add` per_mode_overrides. RTP integrity contract
is at machine level. No per-mode override for the contract.

**Why insufficient**: this is exactly the case §7.4 raises as an open
question. M14 mode 1 (RTP-monitorable) vs M14 mode 5 (RTP-not-monitorable)
need different RTP integrity treatment. v2 doesn't pick.

If RTP integrity is global per-machine, then M14 mode 5's gate runs and
fails (because RTP is meaningfully wrong on mode 5 for reasons unrelated
to attribution). M14 mode 5 is permanently red.

If RTP integrity is per-(machine, mode), then per_mode_overrides needs
to allow rtp_integrity_contract overrides. v2 §5.5 doesn't sketch this.

§7.4 defers to Wave 3 v2. My answer: per-(machine, mode) is the right
granularity (mode-distinct nature of the constraint). The proposal needs
to spec the per-mode contract override. Without it, mode 5 of every
multi-mode machine becomes a perpetual gate failure.

**Verdict**: ⚠ partial — open question; substantively missing in §5.5
schema.

### Q15 — Phase 1 deliverable 7 RAWDATA_ROOT injection: 4 sites currently use fallback pattern

**Question**: §6 Phase 1 deliverable 7 (RAWDATA_ROOT injection fix)
specifies "4 sites currently using `rawdata_root if rawdata_root is not
None else RAWDATA_ROOT` fallback — convert to required parameter; remove
fallback. Force callers to inject explicit path."

This is the same Critic v1 Q8 concern. v2 specifies the conversion but
doesn't address the **call-site cascade**.

**Attempted answer for the designer**: §6 Phase 1 deliverable 7: "4
sites — convert to required parameter; remove fallback. 7 remaining
sites — convert to `self._rawdata_root` for class-method ones; convert
to required parameter for module-level functions. Use FastAPI's
`Depends(get_rawdata_root)` pattern for routes."

**Why insufficient**:

- The 4 sites at lines 695, 1064, 3187, 5318 are inside larger functions
  / classes. Converting their parameter to required forces callers of
  those functions to provide the param. Cascade depth: how deep does the
  required-param ripple? Likely 5-20 call sites per converted function.
- Per `03 §4.1` "7 remaining sites — class methods vs module-level" —
  module-level functions don't have `self._rawdata_root`. Per Phase 1
  deliverable 7: "Use FastAPI's `Depends(get_rawdata_root)` pattern for
  routes." But not all 7 are routes. Some are utility functions called
  from multiple contexts. FastAPI Depends doesn't apply.
- **Regression test**: `tests/backend/test_rawdata_root_injection.py`
  "patch + assertion" — patches the module-level RAWDATA_ROOT to a
  sentinel; asserts no code path reads it. **But**: if a code path reads
  through a closure or imported reference (e.g., `from app import
  RAWDATA_ROOT`), the patch on `app.RAWDATA_ROOT` doesn't affect imported
  references. The test design needs to validate against runtime, not
  static.

Memory `feedback_subprocess_import_suicide_and_module_globals.md` is the
canonical pattern: "tests must split paths to prevent coincidence-masked
bugs". v2 §6 Phase 1 deliverable 7's regression test description doesn't
mention split-path testing (test both real and virtual console runtime
paths separately). Same coincidence-masking risk.

**Verdict**: ⚠ partial — direction good; cascade implementation
underspecced; regression test design weak.

### Q16 — Layer 2 fallback threshold authority and rollout

**Question**: §5.5 `rtp_integrity_contract.fallback_share_threshold_pct`
defaults to 0.5. §9.1 quotes the same. Who picks the threshold per
machine? Per addendum §1.4: silent fallback forbidden. But 0.5% is a
specific number. Authority?

**Attempted answer for the designer**: §5.5 example uses 0.5; M279 uses
1.0. Per-machine adjustment via manifest.

**Why insufficient**:

- **0.5% is operator-arbitrary**. Memory `feedback_invariant_with_fallback_hides_drift.md`
  notes M274 had 4.87% (well above 0.5); M250 100% (way above); M163/M147
  35% (above). The 0.5 threshold catches all known cases. **But**: it
  also catches sampling noise. Per Concern 2: 10k spin chunk on a
  vanilla machine can have 0.6% fallback by sampling variance. The
  proposal doesn't address this — Concern 2 applies.
- **Per-machine override authority**: who sets M279=1.0 vs M260=0.5?
  Operator? Slot-* team? Validator? The manifest is per-machine PR
  isolation per §5.5 — but the threshold is a numeric value that gates
  fleet operation. If operator sets too low → false positives;
  too high → silent leak still possible. Slot-* expertise needed but
  per addendum §3 slot-* per-machine work is out-of-scope.
- **Cross-machine consistency**: if M250 sets 0.5 but M270 sets 5.0,
  the gate accepts way more leak from M270. Is there a fleet-level
  policy? The proposal doesn't say. Operator can effectively neutralize
  the gate by setting threshold to 100 for every machine.

**Verdict**: ✗ not addressed — threshold authority and tuning are
operationally critical but unspecced.

### Q17 — Phase 1 deliverable 3: "Reconcile 3-writers question BEFORE extraction"

**Question**: §6 Phase 1 deliverable 3: "BEFORE extraction, run a parity
test that loads identical (machine, mode) data through all 3 paths and
asserts identical md5 stamps emitted. If they diverge: pick the
authoritative one... patch the others. Block extraction until parity is
established."

What if parity is NOT established? `01 §5 #3` raised this as a question
because observation cannot tell whether the 3 writers agree. If parity
test reveals divergence, what's the path forward?

**Attempted answer for the designer**: §6 Phase 1 deliverable 3 says
"pick the authoritative one (likely `_lookup_machine_md5` from
configs/machines.json...); patch the others."

**Why insufficient**:

- The "patch the others" assumes the divergence is fixable. What if
  one writer reads upstream md5 (real console) and another computes
  locally (virtual)? They by-design produce different stamps. Per
  `01 §4`, `_lookup_machine_md5` reads from `machines.json` (which
  contains upstream-stamped md5 for real fleet); `_patch_summary_md5_tags`
  in virtual analyzer reads from virtual md5 (locally computed). These
  diverge **by design** because real and virtual have different md5
  authorities.
- The "parity" test must be (machine, mode)-scoped: for the same
  machine in real-fleet context, all 3 paths agree. For virtual
  machines, paths diverge from real-fleet path. The parity test
  contract: real-paths agree among themselves; virtual-paths agree
  among themselves; they don't need to agree cross-context.
- §6 Phase 1 deliverable 3 doesn't make this distinction. Reading
  literally: "loads identical (machine, mode) data through all 3 paths
  and asserts identical md5 stamps". If "identical data" is real-fleet
  rawdata, all 3 paths (live sampling, in-process replay, virtual
  delegate) should agree. **But**: virtual delegate is for virtual
  rawdata, not real rawdata. The contract is mis-stated.

**Verdict**: ⚠ partial — parity-test contract underspecced for the
real-vs-virtual md5 authority distinction.

### Q18 — Did v2 address Critic Concern 1 (universal feature edit dominates historical change pattern)?

**Question**: v1 Critic Concern 1 said 5 of 7 brief §3 commits land in
universal features → no reduction. v2 §1.3 + §4.5 acknowledge this
("universal feature edit class stays at 1× by design"). Is the
acknowledgment sufficient?

**Attempted answer for the designer**: §1.3 table explicitly names the
class as 1×. §4.5 explains: "What the proposal does allow is making more
features non-universal." The shift is a path-of-least-resistance
argument: today there's no incentive to carve; v2 makes carving easy.

**Why insufficient**:

- §1.3 is honest. But the table also lists "Bespoke-plugin lift for a
  previously-vanilla machine" as 421×, which is hypothetical and
  contingent on the workflow demo (Concern 3 + Q4) actually working.
- §4.5: "Over time the proposal expects... universal features stay
  universal; new mechanisms are introduced as opt-in." This is a
  future-pattern claim, not a guaranteed property. The blast-radius
  profile shift is what v2 **enables**, not what it **forces**.
- The proposal does not state a roadmap for **demoting** existing
  universal features to non-universal. `bankruptcy_simulation` is
  marked universal in §6 Phase 2 deliverable 2. If a machine doesn't
  need bankruptcy_simulation (e.g., a free-to-play demo machine), it
  still inherits universality per the default 4-feature template
  (§5.11 M1). The "every machine potentially unique" addendum spirit
  is to question every universal — but v2 doesn't say "audit each
  universal feature to see if any subset could drop it".

**Verdict**: ✓ adequately addressed — designer was honest. The
acknowledgment is in §1.3 and §4.5. Critic Concern 1 from v1 is
resolved by the honest reframing.

### §2 stress questions summary

| # | Topic | Verdict |
|---|---|---|
| Q1 | Philosophy shift vs. residual de-facto cluster | ⚠ partial |
| Q2 | 3-layer gate completeness (pass all 3, wrong RTP) | ✗ not addressed |
| Q3 | 421-manifest authorship workflow | ⚠ partial |
| Q4 | Phase 2 forcing-function demo requires Phase 5 gate | ✗ not addressed |
| Q5 | Mode dimension breaks cross-mode comparison badge | ⚠ partial |
| Q6 | Phase 5/6 ordering — strict gate before fix landed | ⚠ partial |
| Q7 | feature_registry trust model + cache invalidation | ⚠ partial |
| Q8 | SCHEMA_VERSION enforcement edge cases | ⚠ partial |
| Q9 | REQUIRES topological — deprecation/cycle interaction | ⚠ partial |
| Q10 | inherits_from cascade semantics | ✗ not addressed |
| Q11 | Phase 2/5 cross-dependency (gate needed in Phase 2) | ✗ not addressed |
| Q12 | 215 rawdata-less machines bypass constraint S | ⚠ partial |
| Q13 | Monkey-patch in sliced architecture (os._exit reach) | ⚠ partial |
| Q14 | Per-mode RTP integrity contract override missing | ⚠ partial |
| Q15 | RAWDATA_ROOT injection cascade + test design | ⚠ partial |
| Q16 | Layer 2 threshold authority + rollout | ✗ not addressed |
| Q17 | 3-writers parity-test contract real vs virtual | ⚠ partial |
| Q18 | Critic v1 Concern 1 acknowledged | ✓ |

Totals: **1 ✓**, **12 ⚠**, **5 ✗**. Q18 is the only fully-resolved
question; Critic v1 Concern 1 was successfully integrated.

---

## §3 Migration risk inventory

### Phase 1 (LOW-MEDIUM per §6.5) — risks identified

| Risk | Source | Severity |
|---|---|---|
| 3-writers parity-test contract real-vs-virtual mis-stated (Q17) | §6 Phase 1 deliverable 3 + `01 §4` | MEDIUM |
| RAWDATA_ROOT cascade ripples through 5-20 callers (Q15) | §6 Phase 1 deliverable 7 | MEDIUM |
| Regression test for RAWDATA_ROOT injection design coincidence-masks per memory `feedback_subprocess_import_suicide` | Q15 | HIGH |
| `virtual_app.py:201` lazy-init breaks any caller importing the module expecting `app` (Critic v1 Q15 carryover) | §6 Phase 1 deliverable 8 | LOW-MEDIUM (mitigated by grep) |
| Phase 1 deliverable 11 (frontend probe-and-fallback doc) is documentation-only with no runtime check; future drift | §6 Phase 1 deliverable 11 | LOW |
| Phase 1 deliverable 12 (compareReports cache-bust race) only adds error handling for 404; doesn't address rename race (DELETE+ADD same version) | §6 Phase 1 deliverable 12 | LOW |

Rollback: per §6.5 trivial. Phase 1 is additive. Per addendum §1.2 no
data preservation concern.

### Phase 2 (HIGH per §6.5) — risks identified

| Risk | Source | Severity |
|---|---|---|
| Phase 2 forcing-function workflow demo requires Phase 5 gate that doesn't exist (Q4, Q11) | §6 Phase 2 deliverable 5 vs §6.5 | HIGH |
| 12 bespoke plugins as net-new code in 10-14 days (memory shows ~22 BCM machines have RTP issues today) | §6 Phase 2 deliverable 4 + §6.5 | HIGH |
| Monkey-patch in sliced architecture: os._exit reach across modules (Q13) | §5.8 | MEDIUM |
| Byte-identical golden file regression at most exercises rawdata-bearing machines (206 of 421); 215 untestable on this axis | §6 Phase 2 deliverable 8 + `02 §1` | MEDIUM |
| If a forcing-function machine doesn't fit, framework iterates "before Phase 2 is locked" — but no clear gate for "locked"; ambiguous | §6 Phase 2 reasoning | LOW-MEDIUM |
| Schema gate placement in core (Q17 from v1 / Critic v2 Q17) — `_REQUIRED_ROUND_FIELDS` semantics if a feature claims extras not in baseline | §6 Phase 2 deliverable 1.4 + §2.1 file tree | MEDIUM |

Rollback: per §6.5 per-feature revert. Each carved feature module is
independently revertible. **But** if the framework Protocol changed
during Phase 2 (e.g., adding a new lifecycle hook because a forcing-function
machine didn't fit), reverting that hook reverts all features that
adopted it. Cascade.

### Phase 3 (MEDIUM per §6.5) — risks identified

| Risk | Source | Severity |
|---|---|---|
| 421 manifests in 4-6 days = 70-105/day; if review-mandated, unrealistic; if auto-gen, addendum §1.5 vigilance violated (Q3) | §6 Phase 3 deliverable 1 | HIGH |
| Mode dimension causes cross-mode comparison badge regression (Q5) | §4.1 | MEDIUM |
| Per-mode RTP integrity contract override missing (Q14) | §5.5 + §7.4 | MEDIUM-HIGH |
| `inherits_from` cascade undefined (Concern 4 + Q10) | §5.5 + §7.1 | HIGH |
| Manifest validation rule 7 bypassed for 215 rawdata-less machines; constraint S unverifiable for them (Q12) | §5.6 + §8.12 | MEDIUM |
| Clean-break authorization (addendum §1.2) means 2030 runs become stale; no UPDATE migration; operators see 2030-stale banner on Phase 3 deploy | §6 Phase 3 deliverable 6 | LOW (per addendum acceptance) |

Rollback: per §6.5 "Manifest ignored on rollback". Files stay on disk
but consumer code is reverted. Clean per addendum §1.2.

### Phase 4 (LOW per §6.5) — risks identified

| Risk | Source | Severity |
|---|---|---|
| SCHEMA_VERSION enforcement bypass via hook skip / force-push (Q8) | §5.4 | MEDIUM |
| Out-of-range schema_version case (data < min or data > max) unspecified (Q8) | §5.3 | LOW-MEDIUM |
| compare_diff.js integration is "parallel registry mechanism" — implementation unspecced | §6 Phase 4 deliverable 3 | LOW |
| Renderer skip when feature_id not in manifest produces empty panels for renderers with no fallback | §6 Phase 3 deliverable 7 | LOW |
| `_MACHINES_SUMMARY_CACHE`-style per-worker caches not invalidated when renderer registry version flips backend-side (`03 §4.4`) | Q7 + §6 Phase 4 deliverable 7 | LOW |

Rollback: trivial revert per §6.5.

### Phase 5 (MEDIUM-HIGH per §6.5) — risks identified

| Risk | Source | Severity |
|---|---|---|
| Strict-error default + 22+ broken BCM machines = 22 red banners on Phase 5 deploy (Concern 5, Q6) | §9.5 + `02 §3.5.1` | HIGH |
| Layer 2 false positives from sampling variance on small chunks (Concern 2) | §9.1 | MEDIUM-HIGH |
| Gate passes with silent mis-attribution within real pids (Concern 2, Q2) | §9 layer enumeration | HIGH (gate is overpromised) |
| Threshold authority undefined; operator can neutralize gate by setting threshold high (Q16) | §5.5 + §9.1 | HIGH |
| 215 rawdata-less machines untestable by gate (Q12) | §8.12 | MEDIUM |
| Layer 3 anchor list maintenance burden; manifest must enumerate every required anchor per machine | §5.5 + §9.1 | LOW-MEDIUM |
| Exit-code based failure mode: analyzer returns non-zero on Layer X fail; subprocess workflows must propagate (per `01 §2 layer 4`) | §9.4 | LOW |

Rollback: per §6.5 "Gate becomes opt-in on rollback". But the structured
errors and the `runs.failure_reason='rtp_integrity'` status persist. If
the gate is reverted, those runs need their status reset. Database
clean-up needed. Underspecced.

### Phase 6 (LOW per §6.5) — risks identified

| Risk | Source | Severity |
|---|---|---|
| "Optional" framing creates ambiguity: is Phase 6 ever shipped? When? | §6 Phase 6 | LOW |
| `machine_round_win_rules.json` consolidation deferred — neither-fish-nor-fowl state (rules in two places) | §6 Phase 6 deliverable 1 | LOW (mitigation: `load_rules_for_machine` reads either source per §5.9) |
| Medium outlier audit (~30 machines per `02 §5.2`) deferred — leakage in 35-90% range stays uncaught until Phase 6 ships | §6 Phase 6 deliverable 3 | MEDIUM |

### Cross-phase rollback failure modes

1. **Phase 2 mid-deploy abandonment**: per Concern 3, Phase 2 forcing
   function depends on Phase 5 gate. If team commits Phase 2 partials
   (e.g., 8 of 12 forcing-function plugins), reverts, the registered
   plugins disappear but the manifests Phase 3 was going to reference
   may have been pre-written. Tracking ownership during Phase 2 is
   fragile.
2. **Phase 5 strict-gate rollback**: per §6.5 "Gate becomes opt-in on
   rollback". Once strict, exception_policy=error in 421 manifests.
   Rolling back the gate means flipping all 421 manifests'
   exception_policy to warn — a mass manifest update. Or keeping the
   manifests strict but the gate's enforcement off. Both have weird
   half-states.
3. **Phase 1 deliverable 7 RAWDATA_ROOT cascade**: if Phase 1 ships the
   "required parameter" version of 4-of-11 sites + the test, then a
   regression rolls back Phase 1, the 7 other sites that were converted
   to `self._rawdata_root` are not reverted. Mixed state.
4. **Phase 3 manifest deploy + Phase 5 gate**: if Phase 3 deploys 421
   manifests but Phase 5 hasn't shipped gate yet (per §6.5 ordering),
   manifests are written without integrity verification. When Phase 5
   ships, suddenly 50+ machines fail (per memory). The "review during
   Phase 3" claim of §6 Phase 3 deliverable 1 is unrealistic — no gate
   to review against.

---

## §4 Edge cases not covered

1. **First-run integrity gate timing**: per §9.4 the gate runs at end
   of analyzer run. But sampling can be hours long (`01 §2 layer 4`).
   Operator runs sampling overnight, gate fails at 3am, the next-day
   reports are not generated. Per §9.5 every fleet pull runs the gate
   — but the gate can't preempt a long-running sample. So a fleet pull
   running 8 hours doesn't get gate result until hour 8. No
   early-stopping spec.

2. **Manifest schema migration when SCHEMA_VERSION of integrity contract
   changes**: §5.5 has `manifest_version: 1`. If we evolve the schema
   to manifest_version 2 (e.g., adding per-mode rtp_integrity_contract
   per Q14), how are 421 existing manifests updated? Per addendum §1.2
   clean break authorizes regen of all reports, but not regen of all
   manifest files. Manifest migration logic unspecified.

3. **Concurrent manifest edit during analyzer run**: analyzer reads
   manifest at startup (§5.7). If operator updates manifest mid-run
   (e.g., changing exception_policy), the running subprocess holds old
   manifest content. Same as feature module hot-reload issue in v1
   Critic Edge Case 3.

4. **Frontend renderer registry version skew between dev/prod**: §6
   Phase 4 deliverable 7 adds frontend cache-bust. But if the registry
   version in backend (Phase 3 manifest data) is N, and frontend asset
   hash version is N-1 (rolled back partially), schema_version
   decisions may diverge between server's view and client's view.

5. **RTP integrity check for variants without rawdata**: variant
   `M273$WheelSelector$42$` has no rawdata. Inherits from M273.json.
   When fleet pull runs, M273$WheelSelector$42$ never gets sampled
   (per `02 §1` no rawdata implies sampling not yet done). When does
   the gate run for it? Per §9.5 the gate runs on every fleet pull —
   but the variant isn't on the fleet pull list because it has no
   sampling configured. The variant's manifest is effectively
   ungated.

6. **Plugin removal cascade**: §5.10 says deleting a feature requires
   no manifest references it. But what if a feature is referenced
   only via REQUIRES (Q9)? Or transitively through inheritance
   (`inherits_from` Q10)? §5.10 doesn't enumerate.

7. **Bespoke plugin authoring for the long tail**: §6 Phase 2 ships 12
   bespoke plugins. §6 Phase 6 audits ~30 medium outliers, possibly
   adding more bespoke plugins. The proposal doesn't bound the total
   number of bespoke plugins long-term. If every machine eventually
   needs a bespoke (per addendum §1.5 "every machine potentially
   unique"), the framework approaches Alternative C (rejected). The
   growth curve isn't projected.

8. **Manifest test fixtures**: when a feature module is updated,
   regression tests need fixture data. §6 Phase 2 deliverable 8
   mentions "byte-identical summary against golden file". When
   manifest is updated (Phase 3), the golden files for that
   (machine, mode) need re-baseline. Workflow undefined.

9. **CI build time**: 421 manifest files + SCHEMA_VERSION lint + RTP
   gate fixture testing → CI lengthens. No discussion of budget.

10. **JSON Schema validator authority**: §5.5 references
    `manifest_schema.json` (JSON Schema for validation). Authoring of
    the schema itself — who writes it, what's the review process —
    not specified. The schema becomes a load-bearing artifact;
    incorrect schema lets bad manifests through.

11. **Variant inheritance under per-feature edit**: if a feature
    referenced by underlying machine but not variant changes, does
    the variant's effective version flip? Per inheritance lazy/eager
    question (Q10) — unanswered. Concrete: M273.json declares
    `wild_nudge_classification`. M273$WheelSelector$0$.json does NOT
    override `analyzer_features`. Per inherits_from, variant inherits.
    Now `wild_nudge_classification.py` changes. Variant's effective
    version flips (lazy resolution) or doesn't (eager). Determined by
    Q10 answer; absent.

12. **Operator who doesn't author code**: §6 Phase 5 deliverable 5
    triage table assumes operator can write `features/bespoke_m250_grid.py`.
    Per `00 §2` slot-* team scope is separate. Who in the team writes
    bespoke plugins? Slot-* team? Architecture team? Ops? Not specced.

13. **Backward-compat for manifest_version field**: when v2 ships,
    manifests are version 1. If v3 changes the schema, what does v3
    code do reading a v1 manifest? Version-aware reader? Hard fail?
    Auto-migrate? Not specced. Per addendum §1.2 the clean break is
    for *reports*, not *manifests*.

14. **Phase 1 deliverable 3 (3-writers parity)**: the spec says "if
    they diverge: pick authoritative; patch others". What's the bar
    for divergence? Byte-identical md5? Same value mod whitespace?
    Different precision rounding? Not specced.

15. **Logging during gate failure**: §9.4 says CLI prints
    human-readable to stderr. What's the log retention? Where does
    aggregate gate-failure data live for trend analysis? `runs.failure_reason`
    is one event; not a time series. The integrity_failures table
    mentioned at §9.4 is sketched but schema undefined.

---

## §5 Hidden assumptions

### A1 — Every machine can express its RTP correctness via the 3-layer check

§9.1 defines the 3 layers. Per Concern 2 + Q2, layers 1-3 don't catch
mis-attribution within real pids. The assumption: layers 1-3 are
sufficient to certify RTP correctness. Per memory
`reference_round_classification_primitives.md` Bug 1 (suffix attribution
M120/M139/M279) showed that real-pid mis-attribution exists. The
assumption is violated.

### A2 — The 215 rawdata-less machines' manifests are correct without rawdata verification

§5.6 rule 7 + §8.12 + §9 rely on rawdata. 215 machines have none.
Hidden assumption: operator-authored manifests are correct in the
absence of rawdata-based verification. Per addendum §1.5 "every machine
potentially unique" + memory M250-style hidden issues, this assumption
is at odds with the addendum.

### A3 — Phase 2 forcing-function workflow demo can be executed in Phase 2

Per Q4 + Q11 + Concern 3: the workflow demo requires Phase 5 gate.
Hidden assumption: gate-or-equivalent exists by Phase 2. Per §6.5
ordering, it doesn't.

### A4 — Bulk manifest authorship completes in 4-6 days

§6 Phase 3 deliverable 1 schedules 421 manifests in Phase 3's 4-6 day
window. Hidden assumption: per-machine review + author + lint averages
fast. Per addendum §1.5 vigilance, manifests should not be bulk-templated.
Per `02 §1` 215 have no rawdata to verify against — the manifest must be
authored blindly. Assumption violated.

### A5 — inherits_from semantics will be picked correctly in Wave 3

§7.1 defers to critic. Hidden assumption: critic picks a clean answer.
Per Q10 there is no clean answer — both lazy and eager have
operational costs.

### A6 — Strict-default RTP integrity will be operationally feasible from Phase 5 day 1

§9.5 says default exception_policy=error. Hidden assumption: by Phase 5
deploy, every manifest's gate passes. Per Concern 5 + Q6, ~22 machines
fail today. Phase 5's 5-7 day window includes fixing all 22. Optimistic.

### A7 — 12 bespoke plugins can be written in Phase 2's 10-14 days

Per §6 Phase 2 deliverable 4. Hidden assumption: each is fast to write.
Per memory, M250/M268/M260 etc. have not been written today — they're
known-broken with no current fix. Hidden assumption: each is a 1-2 day
exercise. Slot-* expertise required per `02 §5.1`.

### A8 — `inherits_from` produces "the same" effective manifest at runtime regardless of underlying changes

Per Q10 + Concern 4. Hidden assumption: variant manifests reliably
reflect their underlying. Per the cascade question — unanswered.

### A9 — `os._exit` and `sys.argv` monkey-patches work in the sliced architecture

Per Q13. Hidden assumption: the monkey-patches attach at the right
namespace level. Sliced architecture introduces sub-module imports of
`os` that may not pick up patches on `pia.os`.

### A10 — `feature_registry.ALL_FEATURES` cache invalidation works correctly across workers

Per Q7. Hidden assumption: per-worker caches respect registry version.
No mechanism specified.

### A11 — The threshold value 0.5% is meaningful for fleet-wide use

Per Q16. Hidden assumption: 0.5% catches real misattribution without
false-positives on sampling noise. No statistical justification.

### A12 — `compute_code_md5` virtual-side flip on `core/engine/symbol.py` change is acceptable

Per §4.4 + §8.6. Hidden assumption: per-virtual-machine isolation from
core engine changes is genuinely out of scope. Validator §3.2 noted
this is awkward; v2 keeps it disclaimed. The assumption is that the
small virtual fleet (6 machines) doesn't deserve isolation work.

### A13 — Universal features remain universally-declared in 200+ manifests after Phase 3

Per Q1 + Q18 + §1.3. Hidden assumption: operators continue to declare
the 4-feature template even after the addendum's vigilance principle.
Operators copy-paste from M1.json into M101.json into M127.json...
without per-machine verification. The "every machine potentially
unique" addendum becomes paperwork; in practice machines remain
clustered via convention.

---

## §6 Comparison to rejected alternatives (rejection rationale double-check)

### Alternative B — Lightweight per-feature SCHEMA_VERSION sidecar

v2 §2.2 rejects B because "addendum §1.4 makes it non-viable" (no RTP
integrity gate) and "does not allow per-machine isolation of bespoke
logic".

**Counter-critique**: B is rejected for the right reasons under
addendum §1.4. But Critic v1's counter to v1's B-rejection still
applies: B's claim was "smaller pie that covers what's actually
touched today". Per Critic v1 Concern 1 + Q6, the historical change
pattern is 5/7 universal features. v2 acknowledges in §1.3 / §4.5 that
universal features still flip everything. So A and B have the **same
properties on the historical change pattern** — A's advantage is in
hypothetical future changes that benefit from per-cluster or
per-machine scoping. Plus A satisfies constraint S; B doesn't.

**Verdict on B-rejection**: defensible. B doesn't satisfy constraint
S which is a hard requirement from addendum §1.4.

### Alternative C — Per-machine analyzer plugin tree

v2 §2.3 rejects C because "addendum §1.5 says 'sharing is opt-in via
manifest', NOT 'no sharing'". A's composition model is what §1.5 wants.

**Counter-critique**: defensible. C eliminates sharing wholesale; A
permits it. Memory `feedback_no_parallel_panel_impl.md` is on-point.

**Verdict on C-rejection**: defensible.

---

## §7 Verdict

### APPROVE-WITH-REVISIONS

The v2 proposal correctly integrates 4 of 5 addendum updates (1, 2, 3, 4
each have a concrete v2 section). v2's §1.3 honest blast table
resolves Critic v1 Concern 1 cleanly. v2's clean-break authorization
(addendum §1.2) cleanly removes the dual-comparison/NULL-handling
machinery. v2's strict-error RTP integrity gate (addendum §1.4 + §9) is
the right architectural shape for constraint S.

But: addendum §1.5 (the most fundamental update) is **only partially
implemented**:
- The mechanism (per-machine manifest files) is in place.
- The canonical operational pattern (200+ machines using a 4-feature
  template) reproduces the v1 cluster default by another name.
- `inherits_from` introduces a default-by-inheritance pattern that the
  addendum explicitly rejected for super-clusters.

And the RTP integrity gate (the addendum §1.4 enforcement mechanism)
has 3 critical issues that block strict-error rollout:
1. Layer 2 has false-positive risk from sampling noise (Concern 2).
2. Layers 1-3 don't catch mis-attribution within real pids (Q2).
3. Phase 5 strict-default ships before Phase 6 medium-outlier fixes (Concern 5).

And Phase 2's forcing-function workflow demo depends on Phase 5's gate
that doesn't exist yet at Phase 2 time (Concerns 3 + 4, Q4, Q11). This
is an internal contradiction in §6 phase ordering.

These are not "minor revisions" — they're structural questions about the
proposal's enforcement mechanism (the gate's correctness) and its
rollout order (phase dependencies). The v2 makes substantial progress
over v1 (11 must-resolves addressed, 4 spec gaps addressed) but
introduces new structural questions in §9 and §6 ordering.

### Specific change requests

Critic asks designer to address before approval moves to APPROVE:

1. **Resolve Phase 2 / Phase 5 ordering contradiction** (Concerns 3 +
   4, Q4, Q11). Either:
   - Ship a minimal §9 Layer 2 fallback check in Phase 2 (preview
     gate) before the full §9 system in Phase 5.
   - Re-order: Phase 5 → Phase 2.
   - Drop Phase 2 deliverable 5 demo; restate as Phase 5 task.

2. **Spec inherits_from cascade semantics** (Concern 4, Q10).
   Lazy vs eager. With each choice's blast-radius implication explicit.

3. **Address RTP gate Layer 2 false-positive cliff** (Concern 2).
   Specify:
   - Minimum sample size for Layer 2.
   - Statistical CI on `fallback_share_pct` (threshold in CI terms,
     not point estimate).
   - Re-run-with-more-spins workflow.

4. **Acknowledge 3-layer gate doesn't catch mis-attribution within real
   pids** (Concern 2, Q2). Rename or scope explicitly. The current name
   "RTP integrity FAILED" overpromises.

5. **Spec Layer 2 threshold authority** (Q16). Who picks the value per
   machine? Is there a fleet-level minimum/maximum? Mechanism to
   prevent operator from neutralizing gate by setting threshold high.

6. **Spec Phase 5 rollout for the 22+ today-broken BCM machines**
   (Concern 5, Q6). Per-machine audited flag (§7.3 deferred)?
   Migration from "today-broken with no rule" to "Phase-5-passing"?
   Order Phase 6 audits before Phase 5 strict-default.

7. **Spec 421-manifest authorship workflow** (Q3). Bulk auto-generation
   source? Per-machine review gate? Slot-* team handoff? Reconcile
   with addendum §1.5 vigilance principle.

8. **Spec per-mode RTP integrity contract override** (Q14). M14 mode 1
   in-scope vs M14 mode 5 out-of-scope per `user_testing_machine.md`.

9. **Conditional mode dimension in hash composition** (Q5). Only include
   mode in hash if per_mode_overrides is non-empty for that mode. Avoid
   cross-mode comparison badge regression.

10. **Spec feature_registry trust model** (Q7). FEATURE_ID uniqueness
    check, SCHEMA_KEYS non-empty check, REQUIRES validity check at
    registry load. Per-worker cache invalidation mechanism.

11. **Spec out-of-range / deleted schema_version handling**
    (Q8). What does renderer do when summary version is below min /
    above max / feature deleted?

12. **Spec REQUIRES deprecation interaction** (Q9). Feature deletion
    must check REQUIRES references, not just manifest references.

13. **Spec monkey-patch attachment in sliced architecture** (Q13).
    `os._exit` reach across modules; `post_json` reach with
    `from .. import post_json` patterns.

14. **Document 215 rawdata-less machines as a constraint-S compliance
    gap** (Q12). Explicit roadmap (per-pull deferred check on first
    sample) or explicit operator acceptance.

15. **Address residual cluster-by-convention via `inherits_from`**
    (Concern 1, Q1). Either: drop `inherits_from`, force per-machine
    explicit. Or: explicitly accept "85 variants share underlying"
    and document the gate-coverage implications for un-rawdata-ed
    variants.

If items 1-6 are resolved with concrete specs, the proposal can move
to APPROVE. Items 7-15 are second-tier (operational/edge-case) and can
defer to phase-specific detailed planning.

Without items 1-6 resolved, proceeding to implementation invites: (a)
Phase 2 unable to complete deliverable 5 because gate doesn't exist;
(b) Phase 5 day-1 with 22 red banners and no graceful rollout; (c)
gate that names itself "RTP integrity" but isn't checking RTP integrity
(rather: fallback bucket + anchors); (d) 215 of 421 machines outside
addendum §1.4 enforcement.

---

```
arch-critic complete.
- Version: v2
- Top concerns: 5
- Stress questions: 18 (verdict: 1 ✓ / 12 ⚠ / 5 ✗)
- Migration risks flagged: 27 (across 6 phases + cross-phase rollback)
- Edge cases not covered: 15
- Verdict: APPROVE-WITH-REVISIONS
- Output: session_artifacts/_arch/05_critique_v2.md
```
