# Adversarial Critique — Wave 2 Architecture Proposal

> Wave 3 / arch-critic. Hostile review of `04_architecture_proposal.md` (1477 lines,
> recommended Alternative A: granular analyzer version + manifest-declared plugins,
> 5-phase migration). Per `.claude/agents/arch-critic.md`: 10+ stress questions,
> migration risk inventory, edge cases not covered, hidden assumptions, alternatives
> rejection double-check, final verdict. Critique, no redesign.
>
> Date: 2026-05-15
> Inputs: `00_brief.md`, `01_pipeline_map.md` (mapper),
> `02_taxonomy.md` (taxonomist), `03_coupling_audit.md` (coupling auditor),
> `04_architecture_proposal.md` (designer).

---

## §1 Top concerns (most serious issues)

### Concern 1 — The headline blast-radius reduction is a phantom for the changes that actually happen

Proposal §4.2 worked-example #2 admits the truth in passing: a rename inside
`features/payouts_by_spin_type.py` (the **8411c9d-class change** that motivated
the entire review) **still invalidates 421 machines** post-migration, because
every cluster default lists this feature universally. §4.2 example #5 has the
same property: any `core/base_pipeline.py` touch flips all 421.

Looking at the 7 fleet-shared commits in `00 §3`:

| Commit | Lives in (proposal §6.5) | Post-migration invalidation radius |
|---|---|---|
| `54b7d01` | `core/engine/symbol.py` | 6 virtual (same as today per `03 §5.1`) |
| `729a6ca` | `features/payouts_by_spin_type.py` + `features/reel_marginal_by_spin_type.py` | **421** (universal feature) |
| `8411c9d` | `features/payouts_by_spin_type.py` (SCHEMA_VERSION bump) | **421** |
| `7e5fe32` | frontend registry fallbackRules | n/a (frontend) |
| `0f981b9` | `features/payouts_by_spin_type.py` | **421** |
| `4cbcab2` | `features/payouts_by_spin_type.py` | **421** |
| `5c4a111`/`284fd19` | `features/payouts_by_spin_type.py` | **421** |

**5 of 7 commits map to a single feature module that is universal.** The 10×
reduction claim from `02 §6.5` only materializes for changes that **don't
correspond to the historical commit pattern**. The proposal reduces blast
radius for hypothetical future changes (BCM cleanup rule, M21 Buffalo tweak)
while leaving the **actually observed** failure pattern untouched. This is the
most damning thing about the design and §4.2 itself admits it twice — but the
recommendation in §3 doesn't reckon with it.

Compare to brief §4 user goal: "**添加新机台,有一些新 feature,更新分析器,
会不会导致我所有的 report 失效?**" The proposal answers "no, if the new
feature is plugin-able and machine-specific". But the **observed** pattern is
analyzer maintenance (rename / filter fix / threshold change) on a universal
feature, which the proposal explicitly leaves at 421-invalidation.

### Concern 2 — Phase 2 (slice analyzer) before Phase 3 (manifests) creates a load-bearing window with no manifest

Per §6 phase ordering, Phase 2 ships the sliced analyzer + `compute_base_analyzer_version`
+ feature module hashes, but Phase 3 ships the manifests + the wiring that lets
`compute_effective_analyzer_version` actually read a per-machine feature list.

In the Phase-2-deployed / Phase-3-not-yet window:

- The analyzer has feature modules with `compute_hash()` capability.
- No machine has a manifest, so `machine_features` argument to
  `compute_effective_analyzer_version` is undefined / has to be "assume all
  features".
- The proposal §6 phase 2 deliverable 13 says "Write
  `summary.effective_analyzer_version` alongside `summary.analyzer_version`".
- Without a manifest, what does `effective_analyzer_version` resolve to? The
  proposal does not spec this. Most likely it falls back to the whole-file
  hash (because every machine "uses all features"). At that point the new
  field is **byte-identical to the old one** in every report, providing zero
  benefit, AND adding a column to the DB schema (`runs.effective_analyzer_version`
  per §4.4) that's a duplicate of `analyzer_version`.

Worse: Phase 2 rollback is non-trivial. §6.2 says "revert the phase-2 commits.
The pre-phase-2 monolith is preserved in git". But if **any reports were
generated during the Phase-2 window with `effective_analyzer_version` stamped**,
those reports now have a field the rolled-back analyzer doesn't know how to
produce. The frontend (per §4.4 "Frontend reads `effective_analyzer_version`
first, falls back to legacy") needs the new field. Phase 2 rollback ⇒ new
reports lose the field ⇒ but old reports written during phase 2 still have it
⇒ inconsistent state. The frontend then needs to handle: "old report
(pre-phase-2)" + "phase-2 report (has new field)" + "rolled-back report (no
new field)". The proposal docs only the 2-state case.

### Concern 3 — Manifest correctness is load-bearing with no enforcement until §7.4

§5.5 validation rule 4 is a **warning, not an error**. §7.4 explicitly defers
the strict-vs-lenient decision to Critic. But Wave 1 evidence is unambiguous
that under-declared manifests are the **status quo** for the fleet:

- `02 §3.5.2` shows ~35-40 machines need `detect_cycle_peak`, ~25 need
  `is_wild_nudge_round`, but only **13 machines** have explicit
  `RoundWinRule` registrations (`03 §2.1`). The other 22-27 machines today
  rely on `parse_chunk_response`'s implicit per-round logic.
- Memory `feedback_invariant_with_fallback_hides_drift.md` (cited in
  taxonomy §3.5.1): "55 of 117 cached BCM (machine, mode) pairs have >0.5%
  RTP falling into the `_unattributed_st<N>` fallback bucket (M250 100%,
  M268/M260/M264 70-90%)". These machines silently leak RTP today because
  the rule isn't declared.

Migrating this fleet to a manifest-driven world with only warning-level drift
detection means: **adding a feature plugin to features/ that isn't in any
manifest = orphan code that runs nowhere**, AND **machine that needs a
feature plugin but doesn't declare it = wrong report, silently**. Either
direction breaks the brief's §5.6 ("no silent data loss").

The proposal punts this to Critic in §7.4. My verdict: this needs to be an
error, not warning. But making it an error means the **migration cannot
ship until manifests are perfectly accurate** — which Wave 1 evidence says
they currently aren't.

### Concern 4 — Three open questions from `01 §5` block migration but proposal defers them

`01 §5` raises 8 mapper-level unknowns. The proposal §7.9 acknowledges 3 are
blocking but defers to Critic. They are:

- **§5 #1 — three invocation styles (subprocess / in-process / batch-pool)
  with no spec saying they behave identically**: Phase 1 deliverable 1
  ("Extract `_lookup_machine_md5` to a shared module") assumes both
  identities can be unified, but the in-process path monkey-patches
  `pia.post_json`, `sys.argv`, `os._exit` (`01 §2 layer 4`); the
  batch-pool path uses `_pool_worker_init` re-importing per worker
  (`01 §4`). If these three already diverge in subtle ways, the "shared
  primitive" extraction will codify a behavior that one of the three
  paths actually doesn't follow. No regression coverage today.
- **§5 #3 — three writers all setting summary md5**: `01 §5 #3` says
  "cannot tell from observation alone whether they always agree". The
  proposal §6 phase 1 deliverable 2 says "extract `_patch_summary_md5_tags`
  to shared module". But if the three writers today produce subtly
  different md5 values for the same (machine, mode) — e.g. live sampling
  reads `_lookup_machine_md5` directly, virtual delegate path
  recomputes via virtual md5, in-process patches in `_run_generate_report`
  — extracting "the shared md5 writer" presumes a single source of
  truth that may not exist. Phase 1 risks unifying-with-the-wrong-side.
- **§5 #7 — `_classify_chunks` historical-bucket consumption by
  in-process replay**: the proposal §6 phase 3 deliverable 6 says "skip
  renderers whose feature_id isn't in the report's manifest". But which
  chunks feed the analyzer in the first place — including any historical
  chunks — depends on `_classify_chunks`, which routes by md5. Manifest
  drift could mean: machine X drops feature F from manifest ⇒
  effective_analyzer_version changes ⇒ historical chunks classified as
  fresh become "historical" ⇒ might still feed analyzer per `01 §5 #7`.

These are not exotic edge cases; they are gaps in the contract that the
proposal builds on.

### Concern 5 — Phase 5 retro-fit of 12 heavy outliers is risk-deferred to the latest phase

Per §6 phase 5: the 12 heavy outliers (M21/M260/M268/M279/M274/M113/M11/M250/M108/M65/M67/M120
per `02 §5.1`) are retro-fit last. But these are the **highest-risk machines**
(per memory `feedback_invariant_with_fallback_hides_drift.md` M250/M268/M260/M264 already
leak 70-100% RTP into fallback bucket; M279 is "custom engine"; M21 is the
most-bespoke; M260 has 10-key extras singleton).

If Phases 1-4 produce a framework that doesn't handle these machines cleanly,
we discover it in **Phase 5** — by which point Phase 2's analyzer slicing is
deployed, Phase 3's manifests are in production, and Phase 4's renderer
registry is wired. The Phase-5 rollback path per §6 phase 5 ("revert
phase-5 commits per outlier") doesn't unwind the structural Phase-2
commitments that the outlier surfaced as inadequate. The outliers should be
the **forcing function**, validated against the cluster framework FIRST
(before the framework is committed).

This is the classic "your design works for the easy 80% but you didn't
prove it for the hard 20%" pattern.

---

## §2 10+ stress questions

### Q1 — Backward-compat for 2030 existing runs across 1007 (m, mode) pairs

**Question**: per `03 §3.3` live DB measurement, `state/console/console.db`
has 2030 completed runs across 1007 distinct (machine, mode) pairs. What
happens to these runs' `analyzer_version` values on migration day?

**Attempted designer answer**: §4.4 says "Backward-compat invariant: every
report on disk today has the old `analyzer_version` field, no
`effective_analyzer_version`. Frontend reads `effective_analyzer_version`
first, falls back to legacy `analyzer_version`." §6 phase 3 deliverable 4
updates `_run_generate_report` + virtual_analyzer + RunManager.start_run to
stamp the new field.

**Why insufficient**: there's no migration script for existing reports. The
2030 existing reports continue to have only `analyzer_version`. When
`/api/reports/stale-count` is updated per §6 phase 3 deliverable 5 to compare
"`runs.effective_analyzer_version` vs the freshly-computed per-machine
effective version", what does it do for the 2030 rows whose
`effective_analyzer_version` IS NULL?

Two plausible behaviors, both broken:
- (a) Treat NULL as "stale" → fleet-wide regen banner explodes. Brief §5.1
  violation ("Forced regen of all reports = unacceptable").
- (b) Treat NULL as "current" → no badge, but then the user can never tell
  which old reports are actually fresh under the new model. Stale info
  silently displayed.

Brief §5 constraint #1 is "Backward-compat for existing 393 machines'
reports: in-flight reports must continue to be served + displayed correctly
throughout migration. Forced regen of all reports = unacceptable." The proposal
acknowledges this in §6.6 but doesn't spec the NULL-handling. Brief §5
"Forced regen acceptable" is NOT stated anywhere; §5.1 says the opposite.

**Verdict**: ⚠ partial — the schema preservation is named, but the
DB-row-level migration path for the 2030 existing rows is unspecified.

### Q2 — Manifest collision when M_X declares P_a and M_Y declares P_a + P_b, and P_a internally uses P_b's protocol

**Question**: trace a concrete cross-machine plugin dependency case. If
`features/cycle_peak_detection.py` (declared by ~35 BCM machines per §4.2)
internally needs to call into `features/collect_mechanic.py` to fetch the
`AccCredits` accumulator (since both extract from `CollectCount` chunks),
does the manifest semantics handle this correctly?

**Attempted designer answer**: §5.2 `AnalyzerFeature` Protocol has
`extract(parse_state, chunk_dict)`. `parse_state` could carry the
accumulator. Each feature is independent.

**Why insufficient**: the proposal doesn't define `parse_state`'s shape. If
feature P_a needs P_b's output as input, two scenarios:

- **Scenario A**: M_X declares only P_a (not P_b). At
  `parse_chunk_response` time the orchestrator iterates declared features
  and skips P_b. P_a's `extract()` fails because P_b's accumulator is
  missing from `parse_state`. **Silent breakage**: report contains P_a
  output that's wrong.
- **Scenario B**: P_a auto-pulls P_b. Now M_X effectively uses both even
  though manifest says only P_a. M_X's `effective_analyzer_version`
  doesn't reflect the implicit P_b dependency → editing P_b's source
  doesn't invalidate M_X's reports even though P_b's behavior changes M_X's
  output. **Silent staleness**.

The proposal §5.2 punts dependency resolution entirely. No
`AnalyzerFeature.REQUIRES = ("collect_mechanic",)` field. No topological
order specified. `parse_chunk_response` is 1607 lines (`01 §2 layer 2`,
lines 2354-3961) with sub-stages that already implicitly depend on each
other (e.g. BCM cycle peak detection at `01 §2 layer 2` row 7 reads
`AccCredits` extracted earlier). Slicing without explicit dependency
declaration will accidentally hide these.

**Verdict**: ✗ not addressed.

### Q3 — Phase ordering risk: Phase-2-in-prod / Phase-3-not-yet window

**Question**: Phase 2 (slice analyzer, write `effective_analyzer_version`)
ships before Phase 3 (manifests + wiring). What does
`effective_analyzer_version` resolve to in this window? Rollback path during
the window?

**Attempted designer answer**: §6 phase 2 deliverable 13 says "Write
summary.effective_analyzer_version alongside summary.analyzer_version
(additive — no field rename)". Phase 2 rollback per §6: "revert the phase-2
commits. The pre-phase-2 monolith is preserved in git; reverting restores
it. Old reports continue working".

**Why insufficient**: see Concern 2 above. Without a manifest:

- `compute_effective_analyzer_version(machine_features=??)` — what's the
  input?
- Most likely fallback: assume `machine_features = ALL_FEATURES` (the entire
  set), making `effective_analyzer_version` byte-identical to a hash of
  base + all features. This is functionally identical to the old whole-file
  hash. No reduction realized in this window.
- Worse: phase 3 then changes `machine_features` to manifest-driven, which
  flips the `effective_analyzer_version` value for **every machine
  simultaneously** at phase-3 deploy time. This is a fleet-wide invalidation
  event that the proposal calls "rollback simplicity: TRIVIAL" in §6.5.

What happens to the runs written during Phase 2 with the "all-features"
effective_analyzer_version? At Phase 3 deploy they all become stale. 1007
(machine, mode) pairs stale_analyzer banner.

**Verdict**: ✗ not addressed.

### Q4 — Plugin discovery and validation at runtime

**Question**: machine X's manifest declares plugin P. How does the analyzer
at run time know:
- That `features/P.py` exists?
- That P's protocol matches the expected ABC?
- Whether to load it eagerly or lazily?
- What happens if `features/P.py` is missing?

**Attempted designer answer**: §5.2 has `class AnalyzerFeature(ABC)` with
abstract methods. §5.5 validation rule 2: "Every `analyzer_feature` ID
listed must correspond to a real module under
`fresh_slotlab/analyzer/features/`". §6 phase 3 deliverable 7: "Manifest
validation CLI: `scripts/validate_manifests.py`".

**Why insufficient**: validation CLI runs **at developer time**, not at
analyzer subprocess startup. The runtime flow per `01 §4`:

- RunManager.start_run spawns analyzer subprocess (`01 §2 layer 4`).
- Subprocess imports `player_impact_analyzer`.
- Subprocess does NOT today read the manifest. Phase 3 must add this.

The proposal doesn't spec:
- File-system scan (every `features/*.py` discovered at boot)? — slow for
  cold start
- Registry table (a `FEATURE_REGISTRY` dict the orchestrator consults)?
- Manifest entries that reference a non-existent feature → what error?

The new `features/` dir vs the new manifest are two separately-authored
artifacts. Drift between them (feature module deleted but manifest still
references it; manifest references typo'd feature_id) is a class of bug
the proposal doesn't address. `scripts/validate_manifests.py` is one tool;
the runtime needs its own guard. Currently the analyzer subprocess just
crashes mid-run when something it expects isn't there — at line
`player_impact_analyzer.py:8170` calls `os._exit` (`01 §5 #1`). What does
"feature P missing" look like in the run history?

**Verdict**: ⚠ partial — protocol exists, validation CLI exists, but
runtime discovery + missing-feature error path is undefined.

### Q5 — 12 heavy outliers retro-fit in Phase 5 — should they move earlier as forcing function?

**Question**: the 12 heavy outliers (M21/M260/M268/M279/M274/M113/M11/M250/M108/M65/M67/M120
per `02 §5.1`) are the riskiest machines. If Phases 1-4 produce something
that doesn't work for them, we discover it only in Phase 5. Phase 5
rollback wouldn't unwind Phases 1-4. Shouldn't one outlier be Phase 1
forcing function?

**Attempted designer answer**: §6 phase 5: "Convert all 12 heavy outliers
to use per-machine bespoke plugin modules"; "Rollback: revert
phase-5 commits per outlier. Each bespoke plugin lift is independently
reversible".

**Why insufficient**: see Concern 5 above. Specific cases:

- **M279** ("custom engine" per memory): Phase 2 carves
  `features/wild_nudge_classification.py` for ~7 machines (M279/M226/M149/M140/M26/M51/M256
  per `02 §3.5.2`). What if M279's wild_nudge logic doesn't match the
  generic version because of its BCM+MoveNudge+Wheel three-feature combo
  (`02 §5.1`)? §6 phase 5 deliverable 2 says "bespoke_m279_combo.py" —
  but if the generic wild_nudge_classification can't satisfy M279, then
  6 of the 7 wild-nudge machines benefit from the lift but M279
  gets... another bespoke file? Now we have BOTH the generic feature
  AND the bespoke override, and the manifest has to express priority.
- **M260** (10-key extras singleton with `Buffs`, `NodeIndex`): Phase 2
  carves `features/collect_mechanic.py` for 30 BCM machines. M260's
  `IncreasedCredits` + `IndexToCreditPool` + `NodeIndex` extras are
  not in the standard BCM-21k pattern. If `features/collect_mechanic.py`
  can't accommodate, M260 needs a fork. Phase 5 retrofits this.

The structural test of whether the framework can scale to outliers is
**not** done before commit to the framework. Phase 5 ordering means we
buy the framework first, then test it. That's the wrong order for the
hardest 20%.

**Verdict**: ✗ not addressed (defer-to-last is the explicit design choice
and it's wrong).

### Q6 — `compute_analyzer_version` granularization concrete arithmetic for the 5 case studies

**Question**: walk worked numbers for the 5 case studies in `03 §5`
(54b7d01 / 729a6ca / 8411c9d / 4cbcab2 / reverted 5c4a111). Does the
proposed algorithm `sha256(base_hash || sorted(feature_hashes_M_uses))[:12]`
actually give the ~10× reduction `02 §6.5` claims?

**Attempted designer answer**: §4.2 worked examples reproduce the
numbers: example #1 (universal feature) = 421, example #2
(payouts_by_spin_type) = 421 same as today, example #3 (cycle peak
detection) = 35, example #4 (M21 Buffalo) = 1, example #5 (core
base_pipeline.py) = 421.

**Why insufficient (showing the calc for each)**:

| Commit | What it touches per §6.5 | Members per `02 §6.2/§6.5` | Today's blast | Post-mig blast |
|---|---|---|---|---|
| `54b7d01` | `core/engine/symbol.py` (virtual only) | 6 virtual | 6 virtual / 0 real | **6 virtual / 0 real** (unchanged) |
| `729a6ca` | `features/payouts_by_spin_type.py` (universal) | 421 (cluster default) | 1007 (m,mode) per `03 §5.2` | **1007 (m,mode)** (same) |
| `8411c9d` | same file, schema bump | same | same | **same** |
| `4cbcab2` | same file, filter fix | same | same | **same** |
| `5c4a111`/revert | same file | same | same | **same** |

5 of 5 historical commits show **zero reduction** under the proposed
algorithm because they all touch `features/payouts_by_spin_type.py`,
which is universal by `02 §6.5`.

`02 §6.5` middle column ("If per-tier-2 plugin") only shows the
reduction for **hypothetical** changes not historically observed:
"Change ST=14 phantom-filter threshold (SC-TopDollar only 17 rows)" and
"Add new BCM `_unattributed_st` cleanup rule (S-BCM-21k 28 rows)" and
"Theme-specific tweak on M21 Buffalo extras (1 machine)". Yes those would
reduce. But the **measured** change pattern (5 of 7 commits in `00 §3`
on universal features) wouldn't.

This is the math behind Concern 1. §4.2 even shows it: example #2
acknowledges 421 invalidation. But the §3 recommendation pitches "A is
the only alternative that solves all five pain points" without addressing
this gap.

**Verdict**: ✗ not addressed (the math shows the reduction doesn't
apply to the observed change pattern, and the proposal doesn't reconcile).

### Q7 — Schema-rename silent break — what does the proposal actually prevent?

**Question**: `00 §3` notes `8411c9d` rename (`hit_rate_pct → hit_rate`)
was protected by `7e5fe32` frontend fallback. Does the proposal's
frontend renderer plugin protocol include explicit versioning, or just
"renaming protocol"? Concrete: if a future commit renames `total_win` →
`win_total` in a plugin, what does the proposal guarantee about prevention?

**Attempted designer answer**: §5.3 RendererPlugin has `minSchemaVersion`,
`maxSchemaVersion`, `fallbackRules`. §5.2 `AnalyzerFeature.SCHEMA_VERSION`
bumped on breaking field rename. §6 phase 4 deliverable 4: "Add fallback
unit tests: load a frozen v1-schema fixture and a v2-schema fixture; assert
renderer produces identical rendered output for both."

**Why insufficient**: the protection is **policy not enforcement**. The
proposal §7.8 explicitly defers "what counts as breaking" to Validator —
no concrete rule. So if a developer renames `total_win → win_total` and
DOESN'T bump SCHEMA_VERSION, nothing catches it:

- No static check: there's no AST-level "renamed a SCHEMA_KEYS field
  without bumping SCHEMA_VERSION" linter proposed.
- No test forced: the fallback unit test in §6 phase 4 deliverable 4 only
  exists for fields known to have been renamed. A new rename without
  test addition slides through.
- The current state (per `03 §4.3`): only `payouts_by_spin_type` family
  has frontend fallback for `8411c9d` rename. Every other field rename
  would still silently break. Post-migration: same vulnerability for
  every feature module's first rename — until someone notices and adds
  fallback rule + bumps SCHEMA_VERSION.

§7.8 admits the policy hasn't been drafted. So the answer for "renames
`total_win → win_total`" is: **same silent break as today, unless the
developer remembers to (a) bump SCHEMA_VERSION (b) add fallback rule (c)
add unit test**. The proposal's renderer registry exists, but the
correctness depends on developer discipline. `feedback_no_parallel_panel_impl.md`
(cited in proposal) and the analogous `feedback_invariant_with_fallback_hides_drift.md`
both say "fallback discipline doesn't survive 6 months of churn".

**Verdict**: ⚠ partial — infrastructure exists, but enforcement
mechanism is undefined. Same silent-break vulnerability remains.

### Q8 — `RAWDATA_ROOT` module-global fix mechanism

**Question**: per `03 §4.1`, `RAWDATA_ROOT` at `app.py:518` has 11
references. Proposal §6 phase 1 deliverable 4: "Replace all `RAWDATA_ROOT`
module-global reads inside class methods (11 references per `03 §4.1`):
grep `app.py` for `RAWDATA_ROOT` outside the const declaration; convert
each to `self._rawdata_root` (using the existing injection at
`create_app`'s `rawdata_root=...` param)". What about backward compat
with the 11 existing call sites?

**Attempted designer answer**: §6 phase 1 deliverable 4 says "convert
each to `self._rawdata_root`". The comment at `app.py:3769-3779` is the
template — already in use at the BatchRunManager path; deliverable
generalizes.

**Why insufficient**: 4 of the 11 sites (lines 695, 1064, 3187, 5318 per
`03 §4.1`) currently use the pattern `rawdata_root if rawdata_root is not
None else RAWDATA_ROOT`. These are **module-level functions** or
**factory-level**, not class methods. They don't have `self._rawdata_root`
to refer to. Are they refactored to class methods? Are new parameter
injections needed? The proposal says "convert each to self._rawdata_root"
without addressing: which of the 11 are even on `self`?

Looking at `03 §4.1`: "11 references to `RAWDATA_ROOT` in `app.py`; per the
docstring the safe ones use `rawdata_root if rawdata_root is not None
else RAWDATA_ROOT` fallback (lines 695, 1064, 3187, 5318) — only safe
when the caller is in production mode AND the default is the correct
one. Virtual-console paths that bypass the fallback are latent bombs."

So 4 of 11 are already "safe-ish" but only for production mode. Proposal
phase 1 deliverable 4 doesn't distinguish: are these 4 unchanged or
refactored? The remaining 7 are the "latent bombs" — what's the proposed
mechanism for them? FastAPI dependency injection (proposal hints with
`create_app`'s param)? Config object? Function parameter?

Memory `feedback_subprocess_import_suicide_and_module_globals.md` lays
out the principle ("grep each module global, change to self._xxx; tests
must split paths to prevent coincidence-masked bugs"). The proposal
references this memory but doesn't propose a concrete mechanism — just
"convert each". For a Phase-1 deliverable, this is too vague to estimate
risk.

**Verdict**: ⚠ partial — direction named, mechanism not.

### Q9 — Virtual / prod console duplication — which dups does the proposal actually fix?

**Question**: per `01 §4`, the duplication sites are:
1. md5 lookup (`_lookup_machine_md5`)
2. md5 patch into summary (`_patch_summary_md5_tags` vs in-process
   patch at `_run_generate_report:6955`)
3. Session-CI half-width formula
4. t-critical table (two implementations)
5. Inference-script trigger (`_run_post_analyzer_inference` vs
   `_run_inference_scripts`)
6. Schema fingerprint (`_compute_upstream_schema_fingerprint` vs
   `compute_schema_fingerprint`)

Does proposal §6 phase 1 address all 6, or only some?

**Attempted designer answer**: §6 phase 1 deliverables 1-3 are: (1)
extract `_lookup_machine_md5`, (2) extract `_patch_summary_md5_tags`,
(3) unify session-CI helpers. §1 pain point #4 cites `01 §4`.

**Why insufficient**: deliverables 1, 2, 3 cover dups 1, 2, 3 + 4 (the
session-CI helpers contain the t-critical table). But:

- **Dup #5 (inference-script trigger)**: NOT in phase 1 deliverables.
  `01 §4` notes "Same `paytable_shape` + `classifier` subprocess calls;
  different argument signatures (real takes `paytables_dir`/`classify_dir`
  param; virtual hardcodes the virtual paths). Diverging error reporting."
  The proposal §1 pain point #4 mentions "two inference-trigger hooks"
  but Phase 1 deliverables don't extract them.
- **Dup #6 (schema fingerprint)**: NOT in phase 1 deliverables. Two
  implementations (`_compute_upstream_schema_fingerprint` at analyzer
  `:2108` vs `compute_schema_fingerprint` at virtual emitter; `01 §4`).

So Phase 1 covers 4 of 6 dups. The other 2 (inference hooks + schema
fingerprint) remain. The proposal might consider them later phases but
the migration plan doesn't say. If they're out of scope, the proposal
should say so explicitly; if in scope, they should be in some phase.

**Verdict**: ⚠ partial — 4 of 6 explicitly addressed, 2 not mentioned.

### Q10 — Plugin lifecycle ownership

**Question**: when a plugin is deprecated (no machine declares it
anymore), does the analyzer auto-delete it? Manual? What about historical
reports stamped with that plugin's hash — can they still be deserialized?

**Attempted designer answer**: not directly addressed in proposal.

**Why insufficient**: the proposal doesn't spec:

- **Deletion**: if `features/wheel_selector_type2.py` is dropped (no
  machine references it), does it get auto-removed from the analyzer
  tree? Manual? What's the test?
- **Historical reports**: existing reports on disk reference a feature
  hash by `effective_analyzer_version`. If the feature module is later
  deleted, can `effective_analyzer_version` still be computed for those
  reports? The legacy `analyzer_version` still works (it's a whole-file
  hash, which always recomputes to **some** value). But
  `effective_analyzer_version` for an old report = `sha256(base ||
  features_listed_in_old_manifest)` — and one of `features_listed_in_old_manifest`
  no longer exists. The lookup fails silently?
- **Report-version drift**: the proposal §6 phase 5 retro-fits "12
  heavy outliers" into bespoke plugin modules. If 2 years later we
  consolidate (M21 bespoke merges into a "buffalo-pattern" feature),
  the old M21 report points to `bespoke_m21_buffalo` which no longer
  exists. What does the runtime do?

Memory `feedback_md5_is_a_tag_not_a_destruction_signal.md` is exactly
about not destroying historical-tagged data. The proposal would do well
to extend that to plugin hashes. But it doesn't.

**Verdict**: ✗ not addressed.

### Q11 — Per-mode hash interaction with manifest

**Question**: `02 §3.5.1` shows `compute_machine_md5_for_mode(entry,
mode)` is per-mode (per memory `feedback_md5_granularity_and_stamping.md`).
Manifest schema in proposal §5.5 is **per-machine**, not per-(machine,
mode). What happens if a machine's mode 1 needs feature F1 and mode 2
needs feature F2 + F3?

**Attempted designer answer**: §5.5 schema includes
`"spin_type_convention": {"paid": [...], "bonus": [...]}` — a single
convention per machine. M14 mode 1 vs mode 2 share the same convention.

**Why insufficient**: per `02 §3.5.3` BCM pairings, "Distribution of
declared `bonus_feature` (mode 1)" — implicit that BCM declarations are
mode-1-specific. M260 mode 1 might be paid+freespin; M260 mode 2 might
have different bonus_feature.

Reading `02 §3.1` table: paid-ST `1` (54 machines), paid-ST `140` (25
machines). Implicit assumption is one convention per machine. But the
fleet has multi-mode machines (e.g. M14 has mode 1, 2, 5, 7 per memory
`user_testing_machine.md`). The proposal doesn't say whether modes share
the manifest entry.

If they do, the per-mode hash composition becomes:
```
effective_analyzer_version(M, mode) =
   sha256(base_hash || features_M_uses[mode] || mode_id)[:12]
```
But proposal §4.1 says `effective_analyzer_version(M) =
sha256(base_hash || features_M_uses)[:12]` — **no mode dimension**.

If a feature is mode-specific (e.g. bankruptcy_simulation runs only on
mode 1 per memory `user_testing_machine.md` "mode 2/5 RTP 不可精准
监控"), the manifest can't express that. Or the proposal expects every
mode to use the same effective_analyzer_version, in which case mode 2 +
mode 5 each get the same stamp. Then `/api/reports/stale-count`'s 1007
(m, mode) dedupe per `03 §3.3` becomes 421 (m,) dedupe in the new
system. Loss of granularity.

**Verdict**: ⚠ partial — proposal doesn't address mode-axis of manifest.

### Q12 — Variant-fanout integration with manifest

**Question**: per `02 §3` taxonomy, 166 of 421 entries are variants
derived from 26 underlyings. M273 alone has 85 variants. Does the
proposal §5.6 manifest fan out all 85 M273 variants explicitly, or
inherit via existing `machine_variants.py:336` machinery?

**Attempted designer answer**: §5.6 shows
`M12$TopDollarSelector$0$` with explicit manifest entry. §7.5 (open
question) acknowledges: "85 nearly-identical rows (one per variant), or
a single variant-template row that fans out via the existing
`machine_variants.py:336` machinery? Validator: please review."

**Why insufficient**: the proposal explicitly defers this to Wave 3
Validator. But the choice has hash-composition implications:

- Per-variant manifest entries: M273 variants each have their own
  `effective_analyzer_version`. If all 85 share the same hash, then
  why have 85 separate rows?
- Variant-template inheritance: M273 variant manifest inherits from
  M273 base. Then a change to M273 base's manifest changes all 85
  variants' hash simultaneously. This is the existing 86-machine
  cohort fan-out from `03 §3.4` ("86 machines on the same code
  hash"). Not a reduction — same blast radius as today's upstream
  fanout, just renamed.

Either choice has issues. Proposal doesn't pick. The 85-variant case
is a real one that needs an answer before manifest schema is finalized.

**Verdict**: ⚠ partial — open question deferred.

### Q13 — In-process analyzer monkey-patch path under sliced architecture

**Question**: per `01 §2 layer 4`, `_run_generate_report` at `app.py:6700`
monkey-patches `pia.post_json`, `sys.argv`, `os._exit` to in-process-import
the analyzer. Under Phase 2's sliced architecture, the analyzer is no
longer a monolith — it's a `core/` + 16 `features/` modules. Does the
monkey-patch still work?

**Attempted designer answer**: not explicitly addressed. Phase 2
deliverable 14 ("Add tests: byte-identical summary regression vs golden
files") suggests testing is in scope; not the import structure.

**Why insufficient**: the in-process path imports `pia` (the analyzer
module) and calls `pia.main()`. If `main()` now lives in
`fresh_slotlab/analyzer/core/base_pipeline.py` instead of
`fresh_slotlab/player_impact_analyzer.py`, the in-process call site needs
updating. The 3 monkey-patches (`pia.post_json`, `sys.argv`, `os._exit`)
are on specific attributes — if `post_json` moves to
`fresh_slotlab/analyzer/core/sampler.py`, the patch attaches to the wrong
module.

Worse: `01 §5 #1` says "the contract that says 'these three behave the
same' is implicit (no spec / tests asserting all three produce identical
summaries for the same chunks)". Splitting the analyzer into 16 modules
breaks the 1:1 mapping. The proposal must address: what does the
in-process import path look like post-Phase-2?

**Verdict**: ✗ not addressed.

### Q14 — `compute_code_md5` (virtual) vs `compute_base_analyzer_version` (proposed) naming

**Question**: §7.3 itself raises this. They are conceptually different
(machine identity vs analyzer process version) but both feel "hash this
Python source". Does proposal pick a clean naming?

**Attempted designer answer**: §7.3 punts to Validator.

**Why insufficient**: §4.3 says "This proposal does not change either
path's hash composition." So `compute_code_md5` (machine_version.py:109,
virtual-only) and `compute_base_analyzer_version` (new, fresh_slotlab,
analyzer-only) coexist. Two functions hashing Python source with similar
names. A developer 6 months in: which do I touch when I add a new core
file?

Worse, `compute_code_md5` already takes `(machine_name)` and feeds
6 virtual machines. `compute_base_analyzer_version()` takes no
machine. Pairing them with `compute_effective_analyzer_version(M)` makes
the API surface 3 hash functions with different scopes. The proposal
doesn't propose a naming convention.

**Verdict**: ⚠ partial — open question, but adds API surface complexity
without a clean resolution.

### Q15 — Subprocess + import-time side-effect interaction

**Question**: `01 §5 #4` + `03 §4.4`: `virtual_app.py:201` runs `app =
build_virtual_app()` at module import → calls `refresh_machines_virtual`.
Per memory `feedback_subprocess_import_suicide_and_module_globals.md`,
this is the suicide pattern. Phase 1 deliverable 5 adds a regression
test for `virtual_registry` subprocess safety. What about
`virtual_app.py:201` itself?

**Attempted designer answer**: §6 phase 1 deliverable 5 covers
`virtual_registry`, not `virtual_app`. Memory cited.

**Why insufficient**: the deliverable 5 test only checks that
`virtual_registry` imports cleanly. But the original 2026-04-21 bug
was: subprocess imported `virtual_app` → triggered the import-time
build_virtual_app → which called `_recover_orphan_running_runs` →
self-killed the subprocess. Memory fix was: carve out `virtual_registry`
as side-effect-free, route subprocess callers through that.

Phase 1 deliverable 5 codifies the fix that's already in place
(`virtual_registry` is the safe path). The remaining footgun
(`virtual_app:201` itself is still side-effect-laden) is unaddressed.
Anyone who imports `slot_designer.core.backend.virtual_app` directly
still triggers the suicide path. The proposal doesn't propose moving
`app = build_virtual_app()` to a lazy / explicit construct.

**Verdict**: ⚠ partial — known-fix codified, but the underlying
side-effect-on-import remains.

### Q16 — Open question §7.9 (mapper §5 questions) gating before Phase 1

**Question**: Proposal §7.9 says 3 of the 8 mapper-§5 open questions
deserve resolution before Phase 1. But it doesn't say which 3. Per
01 mapper §5, the 8 questions are #1 (three invocation styles), #2
(inference duplication), #3 (three summary md5 writers), #4
(reporter.py orphan), #5 (frontend probe fallback location), #6
(aggregate vs per-mode md5), #7 (`_classify_chunks` historical
semantics), #8 (compareReports cache-bust race).

**Attempted designer answer**: §7.9 names "#1 — three invocation
styles", "#5 — frontend probe-and-fallback location unknown", "#8 —
compareReports cache-bust race". Deferred to Critic to "flag any that
block this proposal".

**Why insufficient**: §7.9 names 3 but per Concern 4 above, **also**
#3 (three summary md5 writers) is a Phase 1 blocker because phase 1
deliverable 2 extracts the writer. And #7 (`_classify_chunks` historical
chunks feeding analyzer) is a Phase 3 blocker because manifest changes
flip md5 → reclassify chunks → may feed analyzer wrong data.

So §7.9 understates the blocker set. Effective set = #1, #3, #5, #7, #8.
Five of 8 mapper questions are pre-Phase-1 gates. The proposal commits
to a 5-phase migration without resolving them. That's an optimistic
risk profile.

**Verdict**: ⚠ partial — 3 blockers named, 2 more (#3, #7) missed.

### Q17 (bonus) — `_REQUIRED_ROUND_FIELDS` upstream schema gate

**Question**: §7.1 raises this. Per `player_impact_analyzer.py:1465`,
this gate validates upstream schema for every chunk. Where does it live
post-split? Is it `core/` (universal) or per-cluster `features/` (each
cluster declares its required fields)?

**Attempted designer answer**: §7.1 open question, defers to Validator.

**Why insufficient**: this is not a deferrable question — it sits at
the boundary between `core/` and `features/`. If `core/` requires all 17
baseline fields, then machines with optional fields (e.g. the 59
machines with extras per `02 §3.4`) succeed but the 147 machines with
only baseline succeed too — both per `core/`. If `features/` declares
extras per cluster, then `core/` must accept any subset and downstream
features fail-soft if their required extras aren't present.

The proposal's §4 hash composition implicitly assumes `core/` is one
hash and features are independent. But the schema-gate decision changes
which file's hash this lives in. Punting this question changes the
worked-example numbers in §4.2.

**Verdict**: ✗ not addressed (and it's a pre-Phase-2 decision).

### §2 stress questions summary

| # | Topic | Verdict |
|---|---|---|
| Q1 | Backward-compat for 2030 existing runs | ⚠ partial |
| Q2 | Manifest collision / plugin dependencies | ✗ not addressed |
| Q3 | Phase-2-pre-Phase-3 rollback window | ✗ not addressed |
| Q4 | Plugin discovery at runtime | ⚠ partial |
| Q5 | 12 heavy outliers retro-fit in Phase 5 (too late) | ✗ not addressed |
| Q6 | Concrete arithmetic for 5 case studies | ✗ not addressed |
| Q7 | Schema-rename silent break prevention | ⚠ partial |
| Q8 | `RAWDATA_ROOT` global fix mechanism | ⚠ partial |
| Q9 | Virtual/prod dup coverage (4 of 6 fixed) | ⚠ partial |
| Q10 | Plugin lifecycle ownership / historical reports | ✗ not addressed |
| Q11 | Per-mode hash interaction with manifest | ⚠ partial |
| Q12 | Variant-fanout integration with manifest | ⚠ partial |
| Q13 | In-process monkey-patch path under sliced analyzer | ✗ not addressed |
| Q14 | `compute_code_md5` vs `compute_base_analyzer_version` naming | ⚠ partial |
| Q15 | Subprocess + import-time side-effect remaining | ⚠ partial |
| Q16 | Mapper §5 gating items understated | ⚠ partial |
| Q17 | `_REQUIRED_ROUND_FIELDS` core vs feature placement | ✗ not addressed |

Totals: **0 ✓**, **10 ⚠**, **7 ✗**. No question fully answered.

---

## §3 Migration risk inventory

### Phase 1 (LOW per proposal) — risks identified

| Risk | Source | Severity |
|---|---|---|
| `_lookup_machine_md5` extraction codifies-the-wrong-side bug if 3 writers disagree (mapper §5 #3) | `01 §5 #3` | MEDIUM |
| `_patch_summary_md5_tags` extraction same risk; comment-cross-reference at write sites doesn't prove behavioral equivalence | `01 §4` | MEDIUM |
| 11 `RAWDATA_ROOT` references → "convert to self._rawdata_root" doesn't work for module-level functions; 4 of 11 have existing fallback pattern, 7 don't | `03 §4.1`, Q8 | HIGH |
| `virtual_app:201` import-time side effect remains (only `virtual_registry` covered by regression test) | `03 §4.4`, Q15 | LOW |
| Inference-script trigger duplication NOT in phase 1 deliverables (proposal cites it but doesn't extract) | `01 §4`, Q9 | LOW |
| Schema fingerprint duplication NOT in phase 1 deliverables | `01 §4`, Q9 | LOW |

Rollback complication: phase 1 dedupes touch 3 files (`identity_stamp.py`,
`session_ci.py`, refactored `app.py` and `virtual_analyzer.py`). Each
revert needs to restore both call sites in lockstep. Half-revert =
broken.

### Phase 2 (HIGH per proposal) — risks identified

| Risk | Source | Severity |
|---|---|---|
| Pre-manifest window: `effective_analyzer_version` = whole-file hash (no benefit), DB column duplicates `analyzer_version` | Concern 2, Q3 | HIGH |
| Plugin extraction without dependency declarations → silent reads of unextracted accumulators | Q2 | HIGH |
| In-process monkey-patch (`pia.post_json`, `pia.main`) breaks if `pia` no longer hosts these attrs | Q13 | HIGH |
| Byte-identical golden-file regression tests passing doesn't prove behavioral equivalence under all rawdata patterns (only the sampled machines per Phase 2 deliverable 14) | Q5 | MEDIUM |
| Outliers (M260, M279, M250, M21) untouched in Phase 2 → may reveal Phase 2 cut-points are wrong in Phase 5 | Concern 5, Q5 | HIGH |
| `_REQUIRED_ROUND_FIELDS` schema gate placement undecided — affects which file's hash this lives in | Q17 | MEDIUM |
| 12 bespoke files + 10 shared features = 22+ new module files; potential for accidental cross-imports | §6 Phase 2 deliverable 11 | LOW |

Rollback: revert phase-2 commits. But reports written during phase 2
have `effective_analyzer_version` field; reverted analyzer doesn't write
it. Frontend (if Phase 3 also rolled back) reads
`effective_analyzer_version || analyzer_version` → fallback works.
Acceptable but tracks state on disk.

### Phase 3 (MEDIUM per proposal) — risks identified

| Risk | Source | Severity |
|---|---|---|
| 2030 existing runs have NULL `effective_analyzer_version` — stale-count behavior under NULL undefined | Q1 | HIGH |
| Manifest-vs-rawdata drift on ~22 machines (BCM cycle, wild-nudge) — MANIFEST_DRIFT warning silently ignored vs blocked, undecided | Concern 3, §7.4 | HIGH |
| Manifest typo or missing feature_id → runtime behavior undefined (Q4) | Q4 | MEDIUM |
| Variant fanout (M273 × 85, etc.) — per-variant or template? Undecided | Q12 | MEDIUM |
| Cluster default inheritance semantics: `+` add but no `-` remove (§7.2) | §7.2 | LOW |

Rollback: per proposal "Manifest file stays on disk but is ignored.
`compute_effective_analyzer_version` returns the same value as
`compute_analyzer_version` (whole-file hash). The 421 machines' reports
stay valid." This rollback path requires keeping `compute_analyzer_version`
fully functional through Phase 5 — Phase 2's "thin wrapper" claim
must hold.

### Phase 4 (LOW per proposal) — risks identified

| Risk | Source | Severity |
|---|---|---|
| `RENDERER_REGISTRY` central registry must be co-evolved with feature SCHEMA_VERSION bumps — no enforcement | Q7 | HIGH |
| SCHEMA_VERSION bump policy undefined (§7.8) — same silent-break risk as today | Q7, §7.8 | HIGH |
| Renderer skip-if-not-in-manifest (Phase 3 deliverable 6) → empty panels for legacy reports lacking manifest field | Q1 | MEDIUM |
| `compare_diff.js` not mentioned in Phase 4 deliverables; mapper §1 confirms it's a 3rd rendering site | `01 §1.4` | MEDIUM |

### Phase 5 (MEDIUM per proposal) — risks identified

| Risk | Source | Severity |
|---|---|---|
| Outlier conversion happens AFTER framework is committed → can't re-cut Phases 2-3 if needed | Concern 5, Q5 | HIGH |
| 12 bespoke plugins × ~average 300 lines = 3600 LoC of per-machine logic. Reuse failure mode (Concern 4 already 8000 LoC monolith just moved into per-machine files) | `02 §5.1`, Q5 | MEDIUM |
| `configs/machine_round_win_rules.json` "optionally drop in favor of per-machine manifest" — neither-fish-nor-fowl interim state | Proposal §6 Phase 5.3 | MEDIUM |
| Medium outliers (`02 §5.2` ~30 machines) not covered by 12 heavy bespoke plugins — what about them? Defer or include? | §7.6 open question | MEDIUM |

### Cross-phase rollback failure modes

1. **State on disk during Phase 2 / Phase 3 rollback**: reports written
   with new fields don't unwrite. Frontend has dual-read; backend
   stale-count must remain dual-read. The "trivial rollback" claim
   requires the frontend / backend code path to outlive the rollback —
   if commit reverts frontend AND backend AND analyzer in lockstep, the
   reports written during the rolled-back phase become unreadable
   under frontend (no fallback to read new field's value).
2. **Manifest stays on disk after Phase 3 rollback**: `slot_designer/configs/machine_plugin_manifest.json`
   is the central file. Rollback removes the read code but file
   persists. Next Phase 3 attempt has to handle the stale manifest
   file or migrate it.
3. **Phase 2 + Phase 3 partial-deploy mid-incident**: in production we
   might land Phase 2 then ship hotfix unrelated to migration; weeks
   later try Phase 3. By then the analyzer code is sliced, so the
   "monolith for rollback" reference point has moved.
4. **Phase 5 outlier failure**: discovering M260 needs Phase-2-level
   refactor mid-Phase-5 forces either: (a) carry M260 with legacy code
   indefinitely (regression), (b) re-cut Phase 2 (mid-migration
   architecture change).

---

## §4 Edge cases not covered

1. **Multi-tenant / multi-worker `RENDERER_REGISTRY`**: §5.3 frontend
   registry is a module-level const in `app.js`. If a worker / page
   reload reads a stale cached version (per `03 §4.4` "per-worker
   in-process caches"), version mismatch isn't detected.

2. **Manifest write race**: per `03 §4.4` "virtual_app._local_md5_refresh
   writes to machines_virtual.json on every console boot AND every
   /api/machines/refresh-md5 call". The new `machine_plugin_manifest.json`
   is per Phase 3 deliverable 1. Who's authoritative? File rewriter at
   boot? CLI editor in dev? Race window?

3. **Feature module hot-reload**: if a developer edits
   `features/payouts_by_spin_type.py` while the analyzer subprocess is
   running, the running subprocess holds the old version (subprocess
   Python doesn't auto-reload). `compute_feature_hashes` per §4.1
   caches "at startup". Stale state for the duration of a long run.

4. **Cross-feature data sharing**: `parse_state` in §5.2 protocol is
   not specified. Implicit. Two features writing the same accumulator
   key collide silently.

5. **Migration of in-flight runs**: Phase 2 deploy happens. There's an
   active run completing (per `01 §2 layer 4` runs can be hours long).
   The active run started under monolith, finishes under sliced
   analyzer. Or worse, restarted via `_recover_orphan_running_runs` (per
   `01 §2 layer 4` `4686-4725`) and now picks up sliced analyzer
   mid-stream. Undefined.

6. **Frontend caching `_MACHINES_SUMMARY_CACHE` etc.** per `03 §4.4`
   are per-worker. Phase 4 deploys new registry while workers warm up
   with old. Stale dispatch path possible until cache invalidates.

7. **`reporter.py` legacy module** (`01 §5 #4`, `03 §2.6`): proposal
   §8.7 says "leave in place". But if any test fixture or external
   tooling consumes it, slicing the analyzer's `parse_chunk_response`
   could orphan it further. No deletion → ongoing maintenance burden.

8. **Schema enforcement at write time**: `AnalyzerFeature.SCHEMA_KEYS`
   per §5.2 declares keys this feature writes. No runtime check that
   the feature's `emit()` actually writes those keys. Drift between
   declared SCHEMA_KEYS and actual emit possible. Manifest pulls in
   feature ID but doesn't validate output shape.

9. **i18n keys per feature**: per memory
   `feedback_no_parallel_panel_impl.md` (cited in proposal §5.3),
   i18n keys must reuse. But per-feature module → per-feature i18n
   namespace? Or shared registry? Proposal §8.10 punts.

10. **Audit log of which feature hash a report was generated under**:
    `summary.effective_analyzer_version` is a single hash. Not a
    decomposition into per-feature hashes. So if a regression is
    suspected and we want to know "which feature module produced
    field X in this report", we can't recover it from the report
    alone. Proposal doesn't propose audit-trail field.

11. **`5c4a111` reverted threshold** (per `00 §3` deferred): proposal
    §8.2 says "preserves the current 80% threshold logic inside
    `features/payouts_by_spin_type.py` without touching it". But the
    threshold logic is one of the parts of `parse_chunk_response`
    that's most-touched (5 of 7 fleet-shared commits). Hardening it
    into a feature module means future threshold work also goes
    through Phase-2-style golden-file regen. Slowdown for the
    most-active surface.

12. **The 33 module globals in analyzer (`03 §4.1`)**: proposal
    Phase 1 deliverable 4 covers `RAWDATA_ROOT` (1 of ~52 globals
    in `app.py` + 33 in analyzer). The remaining 32 analyzer
    module globals (including `ENDPOINT_URL` which is mutated at
    runtime per `03 §4.4`) are unaddressed.

13. **`CHUNK_CACHE_VERSION` bump impact** (`03 §4.1`): "bump this and
    every cached envelope's `_cache_version` becomes invalid
    simultaneously". The proposal doesn't address how feature-module
    changes interact with envelope versioning.

14. **`_PEEK_RE_CORE` regex invariant** (`03 §6 #6`): "envelope writers
    MUST place `_chunk_index`, `_config_md5`, `_code_md5` BEFORE
    `response` in the JSON envelope. ... a writer-side reorder
    silently halves cache-replay throughput." Adding
    `_effective_analyzer_version` to envelopes (if any) would have
    to fit this constraint.

15. **Test infrastructure**: `tests/backend/test_analyzer_st_split.py`
    (per `00 §3`) tests the current ST-split shape. Phase 2 carve-out
    of `payouts_by_spin_type.py` either reuses these tests or rewrites.
    Test ownership and migration not addressed.

---

## §5 Hidden assumptions

### A1 — Cluster defaults can be cleanly inherited

§5.5 Option 5.5c (recommended hybrid) inherits cluster defaults with
`+feature_id` appends and (per §7.2 open question) maybe `-feature_id`
removes. But `02 §4.2` defines 6 super-clusters covering ~213/255 machines
(SC-Vanilla 45, SC-BCM-Modern 28, SC-TopDollar 17, SC-WheelSelector 96,
SC-LockRespin-50 9, SC-MoveNudge 6 — total 201 not 213; gap not
explained). The other ~42 are heavy + medium outliers (`02 §5.4`). The
assumption is that 213 machines map cleanly to one super-cluster each.
But `02 §4.1` machines like M250 (sits in SC-BCM-Modern but has 20-reel
grid singleton on Axis 3) and M279 (in SC-BCM-Modern but 3-feature
combo) show machines that straddle. Hidden assumption: super-cluster
membership is single-valued. Wave 1 data shows it isn't.

### A2 — Analyzer monolith can be cleanly sliced

§6 Phase 2 lists 10 feature modules + 12 bespoke. `01 §2 layer 2` shows
`parse_chunk_response` has 15+ inline stages, many with implicit
dependencies (e.g. CostCredits-reliability probe at `:2495-2517` feeds
LockReSpin-style machines; that flag is then used by trigger-anchor
extraction). The assumption is that the cut-points exist cleanly. Q2
shows they don't.

### A3 — `02 §6.5` 10× projection applies to historical change pattern

Per Q6 above, 5 of 7 fleet-shared commits in `00 §3` are universal
features → no reduction. The hidden assumption is future changes look
different from historical. No evidence presented.

### A4 — Backward-compat fallbacks survive churn

Proposal §3 reasoning #1: "backward-compatible by construction" via
fallback patterns. But memory `feedback_invariant_with_fallback_hides_drift.md`
(cited in proposal's §1 pain point #2!) is the lesson that
**fallbacks hide drift**. Proposal's `?? legacy_field` pattern is
exactly the M274 `_unattributed_st139` fallback in spirit. Hidden
assumption: this fallback discipline scales while the older one
didn't. No evidence.

### A5 — Manifest drift is detectable from rawdata scan

§5.5 validation rule 4: "if rawdata is available for this machine, scan
the chunks and verify". But `02 §1` notes "rawdata coverage is partial"
— 215 of 421 machines have NO rawdata. For those 215 machines, manifest
drift IS undetectable. The proposal assumes rawdata is sufficient.

### A6 — Forced regen is acceptable (contradicts brief)

Phase 3 deliverable 5 updates stale-count to use `effective_analyzer_version`.
For 2030 existing runs, that field is NULL. The implicit assumption is
either: (a) those runs become stale and operators regen (violates brief
§5.1); or (b) NULL is handled magically (unspecified per Q1). The
proposal §6.6 claims "no regen forced" but doesn't show how. Hidden
assumption: backend reads NULL as "current".

### A7 — Feature modules are independent

§5.2 `AnalyzerFeature` Protocol is single-feature. No `REQUIRES` field.
Hidden assumption: features can be independently extracted. Q2 shows
some can't (BCM cycle peak detection vs collect mechanic share
accumulators). Hidden assumption violated.

### A8 — `_classify_chunks` will continue to feed analyzer the correct chunks

Per `01 §5 #7` open question: kept-vs-deletable-vs-historical
classification IS consumed by `_run_generate_report:6733` to decide
which chunks the in-process replay sees. Phase 3 changes
`effective_analyzer_version` semantics. Hidden assumption: the chunk-md5
routing isn't sensitive to analyzer version semantics. But manifest
changes flip md5 → reclassify → may feed historical chunks.

### A9 — All 3 invocation styles already behave identically

Per `01 §5 #1`: "the contract that says 'these three behave the same'
is implicit (no spec / tests asserting all three produce identical
summaries for the same chunks)". Phase 1 extracts shared primitives —
hidden assumption: today's behavior already converges. No evidence.

### A10 — `compute_code_md5(machine_name)` only matters for 6 virtual machines

§4.3 says proposal "does not change" the real-fleet upstream md5 path.
Hidden assumption: the real-fleet path is unchanging. But brief §3 lists
54b7d01 as a `core/engine/symbol.py` edit, and `03 §5.1` confirms it
flips 6 virtual hashes and 0 real ones. Implicit assumption: any future
core/engine change also stays virtual-only. But the brief §1 says
"adding a new machine with new features should NOT unnecessarily
invalidate all 393 machines' reports". If future onboarding involves
moving real-fleet machines into virtual (or vice versa), this
assumption breaks.

---

## §6 Comparison to rejected alternatives (rejection rationale double-check)

### Alternative B — Lightweight SCHEMA_VERSION sidecar

Rejection rationale per proposal §2.2 cons: "Does NOT solve pain point #1
(the 1007-pair blast on `analyzer_version`). Comment-only edit still
invalidates the same 1007 pairs. ... Defers the real problem."

**Counter-critique**: per Q6 + Concern 1, **Alternative A also doesn't
solve the 1007-pair blast for the historical change pattern**. The
proposal admits this in §4.2 example #2 ("Invalidation radius: same as
today (421)"). So Alternative B's "doesn't solve #1" is the same
property A has for the actual change pattern.

What A adds over B: **structural slicing** + **future per-cluster
reduction** + **bespoke isolation for 12 outliers**. The marginal value
is real but the size-of-the-pie claim ("solves all 5 pain points") is
overstated. Alternative B's smaller pie covers exactly what's
demonstrably-touched today.

The proposal §2.4 comparison table claims A "Realizes `02 §6.5` 10×
reduction: YES" and B "NO". But per Q6, A's actual realized reduction
on historical changes is 0×. A more honest table would say A: YES for
hypothetical future changes, NO for historical change pattern. B: NO
for both. The vote should be: is the architectural complexity of A
worth the hypothetical reduction? Proposal doesn't make this case
explicitly.

**Verdict on rejection**: rejection-of-B rationale is partially
over-claimed. B is more defensible than the proposal presents.

### Alternative C — Per-machine analyzer plugin tree

Rejection rationale per proposal §2.3 cons: "Reuse becomes hard;
onboarding cost balloons; hash composition becomes per-machine
(no shared test surface); migration is enormous"; cites memory
`feedback_no_parallel_panel_impl.md`.

**Counter-critique**: this rationale is solid. Per `02 §4.2` ~213
machines cluster cleanly; C forces every one to have its own plugin.
For SC-Vanilla's 45 machines, that's 45 redundant files. The memory
cite is on-point. **Rejection of C: defensible**.

But note: Proposal §6 Phase 5 deliverable 2 creates 12 bespoke files
(`bespoke_m21_buffalo.py`, etc.). That's per-machine plugin
methodology for outliers. The proposal accepts per-machine plugins
when needed; just rejects the universal application of C. Reasonable.

**Verdict on rejection**: defensible.

---

## §7 Verdict

### APPROVE-WITH-REVISIONS

The proposal is structurally sound in direction but materially
under-specified for implementation commitment. The five top concerns
each name a substantive gap that would surface as production breakage
or rework. Five of seventeen stress questions are not addressed at all;
ten are partially addressed. The rejection of Alternative B is partly
over-claimed. The rejection of Alternative C is defensible.

### Specific change requests

Critic asks designer to address before approval moves to APPROVE:

1. **Reconcile the "10× reduction" claim with the historical change
   pattern** (Concern 1, Q6). Either: (a) acknowledge in §3
   recommendation that 5 of 7 fleet-shared commits land in universal
   features and reduction doesn't materialize for them, with a
   discussion of whether the design is still worth it; or (b)
   restructure §6.5 worked examples to show change patterns more
   representative of historical commits.

2. **Spec the Phase-2-pre-Phase-3 window** (Concern 2, Q3). What does
   `compute_effective_analyzer_version` return when no manifest exists?
   What happens to runs written in that window when Phase 3 deploys?
   Rollback path during the window?

3. **Decide MANIFEST_DRIFT severity** (Concern 3, §7.4). Strict-error
   or warning. With justification. If strict, plan for the migration
   gate (~22 BCM machines today violate the manifest they'd be
   assigned). If warning, plan for `_unattributed_*` fallback bucket
   metric (per `feedback_invariant_with_fallback_hides_drift.md`) to
   become a top-line invariant.

4. **Resolve the 5 mapper-§5 blockers** (Concern 4, Q16). Specifically
   #1 three invocation styles, #3 three summary md5 writers, #5
   frontend probe-and-fallback location, #7 `_classify_chunks`
   historical-chunk feeding, #8 compareReports cache-bust race. These
   are pre-Phase-1 gates.

5. **Move at least one heavy outlier conversion EARLIER** (Concern 5,
   Q5). E.g. M260 as Phase 2 forcing function — verify the
   feature-module cut accommodates M260's 10-key extras singleton +
   `IncreasedCredits` semantics. If the framework can't, that's known
   pre-Phase-2-commit. Phase 5 as the validation step is too late.

6. **Spec `AnalyzerFeature.REQUIRES`** (Q2). Plugin dependency
   declaration. Topological ordering at runtime. Validate no implicit
   accumulator sharing.

7. **Handle existing 2030 runs' NULL `effective_analyzer_version`** (Q1).
   Migration script (preferred) or runtime NULL semantics. Must respect
   brief §5.1.

8. **Spec plugin discovery + missing-plugin runtime error** (Q4).
   File-system scan vs registry table vs lazy import. Error path when
   manifest references non-existent feature.

9. **Address in-process monkey-patch in sliced architecture** (Q13).
   Where does `pia.main` live? Where do the 3 monkey-patches attach?

10. **Cover remaining 2 duplications** (Q9). Inference-script trigger +
    schema fingerprint. Either in Phase 1 or explicit out-of-scope.

11. **Decide per-mode manifest dimension** (Q11). Is manifest per-machine
    or per-(machine, mode)? Effects on hash composition.

12. **Decide variant-fanout integration** (Q12, §7.5). Explicit per-variant
    manifest vs template inheritance. Hash composition effect.

13. **Plugin lifecycle / historical-report deserialization** (Q10).
    What happens when a plugin is dropped?

14. **Define SCHEMA_VERSION bump policy** (Q7, §7.8). Explicit rules,
    not deferred.

15. **Decide `_REQUIRED_ROUND_FIELDS` schema-gate placement** (Q17,
    §7.1). Pre-Phase-2 decision.

If 1, 2, 3, 4, 5, 7, 11, 12, 13, 14, 15 are resolved with concrete
specs, the proposal can move to APPROVE. Items 6, 8, 9, 10 are
implementation details that can defer to Phase 1 detailed planning.

Without these resolutions, proceeding to implementation invites the
specific failure modes outlined above: silent fleet-wide invalidation
in Phase 3 deploy, in-process import breakage in Phase 2,
manifest-drift-induced wrong reports for ~22 BCM machines, and Phase 5
discovering the framework doesn't fit M260/M279.

---

```
arch-critic complete.
- Top concerns: 5
- Stress questions: 17 (verdict: 0 ✓ / 10 ⚠ / 7 ✗)
- Migration risks flagged: 25 (across 5 phases + cross-phase rollback)
- Edge cases not covered: 15
- Verdict: APPROVE-WITH-REVISIONS
- Output: session_artifacts/_arch/05_critique.md
```
