# Validation — Wave 3 representative case walk-through

> Wave 3 deliverable from `arch-validator`. Walks **7 representative
> machines** through the Alternative A proposal in `04_architecture_proposal.md`
> to verify it handles them concretely. Reports verdict per the
> contract in `.claude/agents/arch-validator.md`.
>
> **Date**: 2026-05-15
> **Brief**: `session_artifacts/_arch/00_brief.md`
> **Repo root**: `User_Managerment_GPT/`

---

## §1 Representatives picked

7 cases chosen per the brief's distribution requirement (≥5 + 1 outlier
+ 1 hypothetical). Coverage rationale grounded in `02 §4.2` super-cluster
table:

| # | Machine | Super-cluster / category (02 §4.2 + §5) | Why picked |
|---|---|---|---|
| 1 | **M1** | SC-Vanilla (45 machines) | The largest natural cluster; the cheapest possible onboarding case. Proposal claims "minimal manifest" for these (`04 §5.6` M14 example). Pure 1-line 3-reel paytable, S-Base envelope, no rules. |
| 2 | **M15** | SC-TopDollar (17 rows = 5 underlying + 12 variants) | One of the only two machine families with **explicit** `RoundWinRule` configs today (`02 §3.5.1`). Tests the proposal's claim that `RoundWinRule` is preserved as-is. Has S-TopDollar 6-extras schema fingerprint; relies on Type 1 trigger sessions + `settlement_winamount` rule. |
| 3 | **M37** | SC-Vanilla member with a **virtual-only** in-spec reroll mechanic | Tests the boundary between virtual-side `compute_code_md5` and real-side analyzer features. M37 has no `plugins/` dir but uses a `reroll_blocks` spec field (verified in `slot_designer/machines/M37/spec.json`). Crucially: NOT in `bcm_pairings.json`. |
| 4 | **M99** | Outlier (02 §5.2 medium outlier) — singleton ST `{96}/{97,98}` | Tests how a *medium* outlier (singleton on 1-2 axes) fits the proposal. Per memory `reference_round_win_rule_architecture.md`: "NOT_FIXED：M99/M112 ST=97+98 sub-round 双发待 dedupe rule". So M99 is a **known-gap** machine with no current rule yet a real defect. Tests proposal's manifest drift detection (§5.5 validation rule 4). |
| 5 | **M279** | Heavy outlier (02 §5.1) — "custom engine + wheel" | The most-fragmented documented machine: F-BCM + MoveNudge + Wheel three-feature combo; ST `{140}/{2,36}`; needs `is_wild_nudge_round` + `attribute_lines_to_pay_ids` suffix + cycle peak handling all together. Has the largest per-machine `slot_designer/machines/M279/plugins/` tree (7 files under `m279/`). Tests the proposal's `bespoke_m279_combo.py` claim (`04 §6 phase 5`). |
| 6 | **M274** | SC-BCM-Modern member; the **only** machine with `bcm_cycle_anchor` rule | Tests the proposal against the most-recent real fleet-shared commit (`bcm_cycle_anchor_m274` rule per `configs/machine_round_win_rules.json:6-16`). Live evidence: report at `reports/M274/mode_1/versions/rv_20260513T034506Z_rawdata_847d89_9633e9/player_impact_summary.json` confirms `_bcm_cycle` synthetic anchor (pid=`_bcm_cycle`, 315 hits, 4.87% RTP contribution). |
| 7 | **M400 (hypothetical)** | Future new machine — novel "collect bar resets after wild progression" | Tests onboarding cost claim (brief §6 + `04 §5.6`). Novel mechanic not in current fleet — neither S-BCM-21k nor S-LockSym nor SC-WheelSelector cleanly fits. Forces proposal to demonstrate it handles genuine novelty, not just rearranging existing categories. |

Cluster coverage:

- **SC-Vanilla** ✓ (M1, M37)
- **SC-TopDollar** ✓ (M15)
- **SC-BCM-Modern** ✓ (M274 + M279 partly)
- **SC-MoveNudge** ✓ (M279 partly)
- **Heavy outliers (§5.1)** ✓ (M279)
- **Medium outliers (§5.2)** ✓ (M99)
- **Hypothetical novel** ✓ (M400)

Not covered (acceptable per §1 of agent definition's 5-7 budget): SC-WheelSelector
(96 rows of M273 + variants, but Axis 1-4 inherit so coverage is shallow), SC-LockRespin-50,
and S-LockLines. Discussion of these surfaces in §6 verdict where relevant.

Live ground-truth data points used throughout (from Bash queries against the
working tree, before writing this document):

- `state/console/console.db`: 2030 completed runs across 1007 distinct
  (machine, mode) pairs (matches `03 §3.3`).
- `configs/machines.json`: 421 entries (matches `02 §1`, `03 §3.4`).
- `slot_designer/configs/machines_virtual.json`: 6 entries; M1sim + M37sim share
  `code_md5=03ff4194e214` (both plugin-empty); 4 others distinct (matches `03 §3.1`).
- `reports/M274/mode_1/versions/rv_20260513T034506Z_rawdata_847d89_9633e9/player_impact_summary.json`:
  has `pid=_bcm_cycle` (315 hits, 4.87% RTP), `pid=5801` (3592 hits, 54.11% RTP),
  no `payouts_by_spin_type` block (older analyzer pre-`729a6ca`).
- Per-case DB counts: M1=15 completed runs, M15=9, M37=10, M99=8, M274=3, M279=10.

---

## §2 Per-case walkthrough

### §2.1 — Case 1: M1 (SC-Vanilla baseline)

| Aspect | Today (current architecture) | Under proposal (Alternative A) |
|---|---|---|
| Which analyzer modules used | All of `parse_chunk_response` (`01 §2 layer 2`, lines 2354-3961). Specifically: `extract_round_win` default path (no rule), `is_paid_round`, `parse_paylines`, `simulate_bankruptcy_from_response`, `build_multiplier_bucket_rows`. No round_win_rule. No `is_wild_nudge_round` (ST-1A signature `{1}/{}`). No `detect_cycle_peak` (S-Base, no `CollectCount`). | **Manifest** (`04 §5.6` minimal): `{"machine_id": "M1", "cluster": "SC-Vanilla", "overrides": {}}`. Inherits SC-Vanilla defaults: `analyzer_features=[payouts_by_spin_type, reel_marginal_by_spin_type, bankruptcy_simulation, multiplier_profile]` (per `04 §5.5` cluster table). No `round_win_rules`. No `classification_primitives` overrides. |
| Hash computation | Today: `summary.analyzer_version = compute_analyzer_version()` = SHA256 of entire 8,176-line `player_impact_analyzer.py`, first 12 hex (`03 §3.3`). Touching anything anywhere in analyzer flips this. M1sim (virtual) also has `code_md5 = compute_code_md5("M1") = 03ff4194e214` — hash of 11 core/engine + core/emitter files (M1 has no `plugins/` dir; `03 §3.1`). | `summary.effective_analyzer_version(M1) = sha256(base_hash || feature_hashes["payouts_by_spin_type"] || feature_hashes["reel_marginal_by_spin_type"] || feature_hashes["bankruptcy_simulation"] || feature_hashes["multiplier_profile"])[:12]`. **4 feature hashes** participate (universal features only). M1sim's `compute_code_md5` unchanged. |
| Onboarding cost | New M1-class machine today: must edit `configs/machines.json` (registry); analyzer logic auto-applies (no rule needed; default path covers); frontend auto-applies (S-Base extras = no special panels). **Cost: 1 file touched.** | New M1-class machine: edit `configs/machines.json` AND add `{"machine_id": "M<new>", "cluster": "SC-Vanilla", "overrides": {}}` to central manifest. **Cost: 2 files touched** (minor regression vs today for the trivial case; cluster reference is the cheapest possible manifest entry per `04 §5.6` claim). |
| Invalidation when shared analyzer changes | Today: ANY byte change in `player_impact_analyzer.py` → `analyzer_version` flips → 1007 (m,mode) pairs flagged stale (M1 always included as one of those 1007). | Under proposal: change to one of the 4 universal features → M1's `effective_analyzer_version` flips, but only because those 4 are explicitly declared. Change to `cycle_peak_detection` (not in M1's manifest) → M1 untouched. **Reduction depends on which feature is changed.** Universal feature changes still flip M1; targeted feature changes (`02 §6.5` "Add new BCM `_unattributed_st` cleanup rule" case) → M1 NOT flipped. |
| Migration steps | N/A | Phase 1: M1 sees zero change (no md5/summary-patch site touches its data). Phase 2: M1's existing summary written by same orchestrator; carve-out emits same fields. Phase 3: M1 gets a minimal manifest entry. Phase 4: registry-driven dispatch transparently renders M1 as before. Phase 5: no retro-fit needed (M1 is in SC-Vanilla cluster, no bespoke). Rollback at any phase: M1 reverts cleanly. |
| Verdict | ✓ handled | ✓ handled |

**Concrete evidence**: M1 has 15 completed runs in DB (`SELECT COUNT(*) FROM runs WHERE machine='M1'`). All would receive new `effective_analyzer_version` field on next regen but continue serving with their existing `analyzer_version` field via the dual-read fallback (`04 §4.4` "Frontend reads `effective_analyzer_version` first, falls back to legacy `analyzer_version`").

**Issue surfaced**: the 2-file-touch onboarding regression for trivial new machines is real but small. **Suggestion** (NOT a redesign): proposal §5.5c's "empty per-machine = inherit cluster defaults" implies that a new SC-Vanilla machine could omit a manifest entry entirely if a fallback rule classifies it as SC-Vanilla automatically. Worth Critic discussion.

---

### §2.2 — Case 2: M15 (SC-TopDollar; existing rule-bearing machine)

| Aspect | Today (current architecture) | Under proposal (Alternative A) |
|---|---|---|
| Which analyzer modules used | `extract_round_win` invokes `SettlementWinAmountRule` (`round_win.py:163`) for phantom-ST=14 → 0 / settlement-ST=15 → `WinAmount`. `extract_round_trigger_anchor` returns the TopDollar `Trigger` ReMarks anchor pid=666 (Type 1 trigger session per `trigger_sessions.py` docstring). S-TopDollar schema-fingerprint (`02 §3.4`): 6 extras keys (`ChosenDollar, DollarCount, ExtraRatio, JackpotIds, OfferValue, WinAmount`). The rule_id `topdollar_selector_settlement` covers all 12 TopDollar variants (`02 §3.5.1`); M15 underlying inherits via fanout. | **Manifest**: `{"machine_id": "M15", "cluster": "SC-TopDollar", "overrides": {"spin_type_convention": {"paid": [1], "bonus": [14, 15]}}}`. Inherits SC-TopDollar defaults (`04 §5.5` central): `analyzer_features=[payouts_by_spin_type, bankruptcy_simulation, topdollar_settlement, multiplier_profile]`, `round_win_rules=[topdollar_selector_settlement]`, `feature_tags=[Selector]`. `SettlementWinAmountRule` preserved as-is per `04 §5.4`. |
| Hash computation | `analyzer_version` is whole-file hash (`03 §3.3`). M15sim virtual entry: `config_md5=5e2db7b34896`, `code_md5=eb2c52375000` (distinct from M1sim because `slot_designer/machines/M15/plugins/{feature.py, plugin.py}` add 16KB+8KB to per-machine hash input; `03 §3.1`). | `effective_analyzer_version(M15) = sha256(base_hash || feature_hashes for [payouts_by_spin_type, bankruptcy_simulation, topdollar_settlement, multiplier_profile])[:12]`. **4 feature hashes**; one of them (`topdollar_settlement`) is the carved-out home of the existing `SettlementWinAmountRule` per `04 §6 phase 5`'s retro-fit table. M15sim's `compute_code_md5` unchanged. |
| Onboarding cost | New TopDollar variant: add row to `configs/machines.json` + `applies_to` array of rule `topdollar_selector_settlement` (1 file each). **Cost: 2 files.** | New TopDollar variant: add row to `configs/machines.json` + manifest entry `{"machine_id": "M<new>", "cluster": "SC-TopDollar", "overrides": {}}` (per `04 §5.6` variant example) + optionally update `applies_to` array (or have the manifest auto-imply it via `round_win_rules: ["topdollar_selector_settlement"]` from cluster default). **Cost: 2 files** (same). |
| Invalidation when shared analyzer changes | Today: any analyzer byte → M15's analyzer_version flips. M15-specific behavior in `SettlementWinAmountRule` (`round_win.py:163`) → flips when `round_win.py` is edited (rare; only 13 machines listed). | Under proposal: change in `features/topdollar_settlement.py` → flips only the 17 SC-TopDollar machines (5 underlying × 1 + 12 variants). **Reduction: 421 → 17 = 24×** (matches `04 §4.2` worked example #4 for the bespoke flavor; this case is for the cluster-shared feature). Change in `features/bankruptcy_simulation.py` (universal) → still flips M15 (and all 421). |
| Migration steps | N/A | Phase 1: M15 sees no change (md5/summary-patch only affects identity-stamping mechanics). Phase 2: `features/topdollar_settlement.py` carve-out lifts the existing `SettlementWinAmountRule` invocation into the new feature module. Verified against M15's golden report. Phase 3: M15 manifest entry written. Phase 4: M15 renders with the same panels as today; registry-driven dispatch. Phase 5: no retro-fit needed for M15 underlying (SC-TopDollar cluster covers it); variant manifest entries auto-generated. |
| Verdict | ✓ handled | ✓ handled |

**Concrete evidence**: `configs/machine_round_win_rules.json` line 17-42 confirms `topdollar_selector_settlement` rule with 12 variants in `applies_to`. M15 base has S-TopDollar schema (`02 §3.4`). Today's 9 completed runs for M15 keep serving (the existing `analyzer_version` matches what they were generated with; the new effective version is additive).

**Issue surfaced**: M15's 9 runs in DB lose their "fresh" badge after `analyzer_version → effective_analyzer_version` migration unless backend's `/api/reports/stale-count` (per `04 §6 phase 3.5`) handles dual-comparison correctly — falling back to legacy `analyzer_version` for pre-migration runs. This is implementation detail but worth noting: phase 3 deliverable 5 says "compare `runs.effective_analyzer_version` vs the freshly-computed per-machine effective version, not the whole-file hash" — but pre-migration runs have NULL effective_version. **Suggestion**: spec out the dual-read in phase 3 explicitly. Designer should add a clause: "For runs predating phase 3 deployment, fall back to the legacy `analyzer_version` comparison."

---

### §2.3 — Case 3: M37 (reroll mechanic, virtual-only spec feature)

| Aspect | Today (current architecture) | Under proposal (Alternative A) |
|---|---|---|
| Which analyzer modules used | M37 has rawdata under `rawdata/M37/mode_{1,2,5,7}` so it's part of real fleet. ST-1A signature (paid=1, no bonus). F-Plain feature tag. S-Base schema. **NOT in bcm_pairings.json** (confirmed by grep). NOT in `machine_round_win_rules.json`. Uses default analyzer path: `extract_round_win=r.get("WinCredits",0)`, `parse_paylines`, default per-pid attribution. The "reroll mechanic" lives in `slot_designer/machines/M37/spec.json.reroll_blocks` (`spec.json` line 9-12 verified) but this is **virtual-only** — affects only M37sim's simulator output, NOT the real fleet analyzer logic. | **Manifest** for M37: same as M1: `{"machine_id": "M37", "cluster": "SC-Vanilla", "overrides": {}}`. Real M37 (rawdata-fingerprinted; on real fleet) doesn't list any bespoke feature because its reroll mechanic is invisible to the analyzer (analyzer sees only post-reroll rounds). M37sim (virtual): unchanged `compute_code_md5=03ff4194e214` (no `plugins/` dir; matches M1sim). |
| Hash computation | M37 (real fleet, machines.json): upstream `codeSummaryMd5` + `configSummaryMd5` from `/MachineConfigMd5` (`03 §3.4`). M37sim (virtual): `compute_code_md5("M37") = 03ff4194e214` — same as M1sim because both lack `plugins/` dir. `config_md5=12b2af815aac` (distinct from M1sim's `c195dfd3a9ed`; spec differs). | Real M37: `effective_analyzer_version` = same 4-feature-hash composition as M1 (SC-Vanilla cluster). Virtual M37sim: `compute_code_md5` unchanged (proposal `04 §4.3` clarifies: "This proposal does not change either path's hash composition"). |
| Onboarding cost | Adding M37-class machine today: bare row in `machines.json`. Reroll mechanic exists only in virtual simulator (`spec.json`); analyzer sees pre-processed rounds. **Cost: 1 file (real) or 4 files (virtual: spec.json + reel_strips.json + weights/ + machines_virtual.json fanout).** | Same as today + the manifest entry. Per `04 §5.6` minimal example. **Cost: 1+1 file (real)** OR same 4-file virtual cost. |
| Invalidation when shared analyzer changes | Today: M37 in the 1007 (m,mode) stale-bucket on any analyzer touch. M37sim: hash flips ONLY if `core/engine/**/*.py` or `core/emitter/**/*.py` touched (`03 §3.5 [c]` flow). Per `03 §5.1`, commit `54b7d01` ("scatter symbol kind") flipped M37sim's `code_md5` because `core/engine/symbol.py` was touched, even though M37 doesn't use scatter (M37 has no `plugins/` dir to override `core/engine/symbol.py` behaviors). | Real M37 (10 completed runs): same invalidation pattern as M1 (SC-Vanilla peer). Virtual M37sim: unchanged behavior — proposal does NOT change `compute_code_md5` (`04 §4.3` explicit). **Observation: M37sim still flips on every `core/engine/*.py` change because Phase B docstring says "Touching core/* flips every machine's md5".** Proposal §4 acknowledges this and does not address it. This is **out of scope for the proposal** per `04 §8.6` ("Re-onboarding the 6 virtual machines under a new spec format" is out of scope) but raises whether the virtual-side hash composition is itself an architecture issue that should be in scope. |
| Migration steps | N/A | Phase 1: M37sim sees no behavior change. Phase 2: real M37 analyzer-side carve-outs are byte-identical (golden test against existing M37 reports per `04 §6 phase 2 deliverable 14`). Phase 3: M37 gets a SC-Vanilla manifest entry. Phase 4: same renderers, same panels. Phase 5: no retro-fit. |
| Verdict | ⚠ awkward — handled but exposes a known limitation | ⚠ awkward |

**Concrete evidence**: `slot_designer/machines/M37/spec.json` confirms `reroll_blocks` field exists (line 9-12) but is consumed by `slot_designer/core/engine/spin.py` (per `03 §3.1` core engine file list), NOT by `fresh_slotlab/player_impact_analyzer.py`. The reroll happens before chunks are emitted; the analyzer never sees pre-reroll round attempts.

**Issue surfaced (⚠ awkward)**: The proposal **inherits** the virtual-side problem that `compute_code_md5` flips all 6 virtual machines on any `core/engine/*.py` change. `02 §6.5` projects 10× blast-radius reduction across all change classes, but this particular axis (virtual-side core engine flips → all virtual machines flip) is NOT in the proposal's scope. Memory `feedback_md5_granularity_and_stamping.md` already lessons-learned around per-mode granularity but not per-virtual-machine isolation from core engine changes.

**Suggestion to designer (NOT redesign; flag only)**: §4.3 explicitly disclaims this scope; add a clause noting "virtual-side `compute_code_md5` blast radius is documented in `02 §6.5` but addressed separately by future spec-format work (`04 §8.6`)". M37 case verifies the proposal handles real M37 (sees no change) and disclaims virtual M37sim's core-engine flip. Acceptable but worth noting.

---

### §2.4 — Case 4: M99 (BCM-21k-ish outlier — singleton ST + known unfixed dedup)

| Aspect | Today (current architecture) | Under proposal (Alternative A) |
|---|---|---|
| Which analyzer modules used | Per `02 §4.1`: M99 has ST `{96}/{97,98}` (singleton), F-Wheel, 6-line paytable, S-LockSym extras. Memory `reference_round_win_rule_architecture.md` cites M99/M112 as "NOT_FIXED: ST=97+98 sub-round 双发待 dedupe rule". Today: `extract_round_win` default; `is_paid_round` (CostCredits-based); NO `is_wild_nudge_round` (ST not 36); HAS `extract_authoritative_pay_ids` + suffix-fallback via `attribute_lines_to_pay_ids` (per `02 §3.5.2`); HAS schema with `LockSymbols, PrevLockSymbols` extras → S-LockSym path indirectly hit. **No explicit RoundWinRule.** Result: M99/M112 have known double-counting on ST=97+98 sub-rounds that nobody has built a rule for yet. | **Manifest**: M99 doesn't cleanly fit SC-Vanilla / SC-TopDollar / SC-BCM-Modern / SC-WheelSelector / SC-LockRespin-50 / SC-MoveNudge (the 6 super-clusters in `04 §5.5`). Likely: `{"machine_id": "M99", "cluster": null, "overrides": {"spin_type_convention": {"paid": [96], "bonus": [97, 98]}, "feature_tags": ["Wheel", "LockSymbol"], "analyzer_features": ["payouts_by_spin_type", "bankruptcy_simulation", "multiplier_profile", "lock_symbol_handling"]}}` (assuming `lock_symbol_handling` becomes a new tier-2 feature module per `02 §6.2 plugin-lock-symbol` candidate). |
| Hash computation | `analyzer_version` = whole-file SHA256. M99 in stale bucket on any analyzer touch (1 of 1007 (m,mode) per DB). | `effective_analyzer_version(M99) = sha256(base || features_used)`. Features used: 4 universals + new `lock_symbol_handling`. **5 feature hashes participate.** Adding `lock_symbol_handling` to fix the M99/M112 dedup bug invalidates only the 5 S-LockSym machines (`02 §3.4`: M103, M104, M99, M240, plus M239 in lock-symbol combo) + M112 (singleton with similar pattern). **Reduction: 421 → 5-6 = ~70×.** |
| Onboarding cost | New M99-class machine today: row in `machines.json`. If you build the M99/M112 dedup rule it goes in `machine_round_win_rules.json.applies_to=["M99","M112"]`. **Cost: 2 files.** | New M99-class machine: row in `machines.json` + manifest entry (cluster=null, overrides). If `lock_symbol_handling` feature module gets the dedup rule: same surface (`round_win_rules` array). **Cost: 2 files.** |
| Invalidation when shared analyzer changes | Today: M99 always invalidated by analyzer touches (universal); M99 nominally not invalidated by `round_win.py` edits unless `RoundWinRule` ABC changes. | Under proposal: M99 invalidated only when `core/*` or one of its 5 declared features changes. Adding `cycle_peak_detection` (BCM machines) does NOT invalidate M99 even though M99 has some BCM-ish characteristics — **but** if M99 is later determined to need cycle peak handling, manifest drift validation (`04 §5.5 rule 4`) would warn. |
| Migration steps | N/A | Phase 1: M99 unaffected (no rule changes). Phase 2: byte-identical regen; M99 has no rawdata reports in `reports/M99/mode_*/versions/` (verified empty — no version dirs); 8 completed runs in DB but no on-disk version artifacts. Phase 3: M99 manifest entry written manually as a non-cluster outlier. Phase 4: registry-driven dispatch unchanged. Phase 5: **discover M99 needs `lock_symbol_handling` feature**; this is exactly the kind of "MANIFEST_DRIFT" warning §5.5 rule 4 wants to detect. Designer's §7.4 open question asks "strict or lenient" — M99 is the case study. |
| Verdict | ⚠ awkward (proposal partly handles, drift detection finishes the job) | ⚠ awkward |

**Concrete evidence**: Memory snippet (verbatim from `reference_round_win_rule_architecture.md`): "NOT_FIXED：M99/M112 ST=97+98 sub-round 双发待 dedupe rule". `reports/M99/mode_{1,2,5,7}/versions/` all empty — M99 has 8 completed runs in DB but no surviving version dirs on disk (`reports/M99/mode_1/versions/` ls returns no output, only the parent `mode_1/index.json` exists). M99's rawdata coverage is full (`mode_{1,2,5,7}` chunk dirs present).

**Issue surfaced (⚠ awkward)**: M99 is an example where the **cluster-default approach doesn't fit** (M99 in no super-cluster). The proposal handles this by allowing `cluster: null` with explicit `analyzer_features` array, which works — but the implication is that ~30 medium outliers (`02 §5.2` count) plus 12 heavy outliers (`02 §5.1`) = **42 machines** will need explicit-overrides manifest entries with non-cluster classification. That's not a deal-breaker but is meaningfully larger than the proposal's `04 §6 phase 5 deliverable 1` "12 retro-fit map" suggests.

**Suggestion to designer**: this case needs the §7.4 open question (strict vs lenient drift detection) resolved before phase 3 ships. Recommend: warn (not block) by default, with a CLI flag to escalate; this preserves momentum while surfacing the M99-class gaps that memory has already documented.

Also: this case demonstrates Designer §7.6 ("Heavy-outlier bespoke plugin — does this scale beyond 12?") is real. M99 is in §5.2 medium-outlier list (so not in the 12 heavy outliers), but still needs explicit handling. **42 machines** out of 421 fleet ≈ 10% would be in the "non-cluster" lane. The proposal should account for this — perhaps a "tier-2 archetype cluster" between super-cluster and bespoke that captures lock-symbol family (`02 §6.2 plugin-lock-symbol` candidate; 5 machines), `02 §6.2 plugin-lock-lines` (5 machines), etc.

---

### §2.5 — Case 5: M279 (heavy outlier, "custom engine + wheel")

| Aspect | Today (current architecture) | Under proposal (Alternative A) |
|---|---|---|
| Which analyzer modules used | Per `02 §5.1`: M279 is a heavy outlier: ST `{140}/{2,36}` singleton, F-BCM + MoveNudge + Wheel three-feature combo. S-BCM-21k schema (`02 §3.4`). Uses: `is_wild_nudge_round` (ST=36+ReMarks=move; `02 §3.5.2`), `attribute_lines_to_pay_ids` suffix (27905 → 104 per `02 §3.3.4` and `round_classification.py` Bug 1 docstring per memory), `detect_cycle_peak` (has `CollectCount` extras), `at_cycle_peak_indices`, `infer_bcm_target_spin_type`. NO explicit `RoundWinRule` (despite needing one — per memory `feedback_invariant_with_fallback_hides_drift.md`, M279 should need `bcm_cycle_anchor` like M274 but doesn't have one enabled). Has the **largest per-machine plugin tree**: `slot_designer/machines/M279/plugins/` contains `m279_driver.py`, `m279_round.py`, and `m279/` subdir with `collect.py`, `engine.py`, `loader.py`, `nudge.py`, `wheel.py` (7 files total ~43KB; `03 §3.1`). | **Manifest**: `{"machine_id": "M279", "cluster": "SC-BCM-Modern", "overrides": {"feature_tags": ["BCM", "MoveNudge", "Wheel"], "spin_type_convention": {"paid": [140], "bonus": [2, 36]}, "analyzer_features": ["+wild_nudge_classification", "+bespoke_m279_combo"]}}`. Per `04 §5.6` M279 example, the `+` prefix appends to cluster defaults. Inherits SC-BCM-Modern 7 features + adds `wild_nudge_classification` + `bespoke_m279_combo` (the per-machine bespoke per `04 §6 phase 5 deliverable 2`). |
| Hash computation | `analyzer_version` whole-file; M279sim (virtual) `compute_code_md5("M279")=7803ae4fe30a` based on 11 core/* files + 7 per-machine `plugins/m279/**/*.py` files. | `effective_analyzer_version(M279) = sha256(base || features_used)`. Features used: 7 cluster defaults + 2 appended (`wild_nudge_classification`, `bespoke_m279_combo`) = **9 feature hashes**. M279sim's `compute_code_md5` unchanged (proposal preserves virtual-side hashing). |
| Onboarding cost | New M279-class machine today: row in `machines.json`. Plus may need new entries in `bcm_pairings.json` (M279 has entries for modes 1,2,5,7; line 781-808 confirmed). Plus may need rule in `machine_round_win_rules.json` if bcm_cycle_anchor needed. **Cost: 2-3 config files + heavy custom engine code per-machine.** | Same as today, plus manifest entry with `cluster=SC-BCM-Modern` + explicit overrides. **Cost: 2-3 config files + 1 manifest entry + likely custom `features/bespoke_m<new>_combo.py`** depending on novelty. |
| Invalidation when shared analyzer changes | Today: M279 in 1007-pair stale bucket on any analyzer change. Has 10 completed runs across 4 modes (per DB). | Under proposal: M279 invalidated when any of its 9 features changes. **Crucially**, change in `features/bespoke_m279_combo.py` invalidates **only M279** (per `04 §4.2` worked example #4 reduction: 421→1 = 421× reduction). Change in `features/wild_nudge_classification.py` (`02 §6.2 plugin-wild-nudge` candidate, ~7 machines + variants) invalidates ~7 machines. **This is the proposal's strongest demonstrated reduction case.** |
| Migration steps | N/A | Phase 1: M279 sees no behavior change. Phase 2: `features/wild_nudge_classification.py` carved out; tests against M279's golden report (per `04 §6 phase 2 deliverable 14` mentioning "+ 6 of the 12 heavy outliers" — M279 is in the §5.1 heavy outliers list so explicitly named in the migration plan deliverable). Phase 3: M279 manifest entry with explicit overrides. Phase 4: registry dispatch handles M279's expanded panel set. Phase 5: `bespoke_m279_combo.py` lifts M279-specific conditionals from `parse_chunk_response` — per `04 §6 phase 5 deliverable 2` `features/bespoke_m279_combo.py` is explicitly named. |
| Verdict | ✓ handled | ✓ handled |

**Concrete evidence**: `slot_designer/machines/M279/plugins/m279/{collect.py, engine.py, loader.py, nudge.py, wheel.py}` confirms the 5-module subdir + `m279_driver.py` + `m279_round.py` at parent (7 total ≈43KB). DB shows 10 completed M279 runs. `configs/bcm_pairings.json:781-808` confirms M279 mode 1 has `bonus_feature="Wheel"`, modes 2/5/7 have `bonus_feature="MoveSpin"` — confirming the proposal's claim about M279's combo nature (3 distinct features stacking).

**Issue surfaced (none — clean handling)**: M279 is the proposal's headline case for blast-radius reduction. The `bespoke_m279_combo.py` lift (`04 §6 phase 5 deliverable 2`) cleanly isolates M279-specific code; the cluster reference (SC-BCM-Modern) handles the shared BCM behaviors; the appended `wild_nudge_classification` plugin captures the MoveNudge axis. **All three of M279's distinct features are captured by separate plugin modules**, each with its own hash. This is the proposal working as designed.

**One observation**: the proposal does NOT propose enabling `bcm_cycle_anchor` for M279 (which per memory `feedback_invariant_with_fallback_hides_drift.md` should be enabled). This is consistent with `04 §8` "out of scope" but means M279's fallback-bucket leakage stays unfixed under the new architecture too. **Suggestion**: phase 5 manifest validation sweep should explicitly flag M279 as a candidate for `bcm_cycle_anchor` enablement (this is exactly the `02 §3.5.1` "they're a known gap" note, which §5.5 validation rule 4 promises to catch). The phase 5 deliverable 4 ("Fleet validation sweep ... reports any MANIFEST_DRIFT warning. Reconcile with user") should explicitly cover this. **Worth a note in the proposal.**

---

### §2.6 — Case 6: M274 (only `bcm_cycle_anchor` machine; recent BCM rule example)

| Aspect | Today (current architecture) | Under proposal (Alternative A) |
|---|---|---|
| Which analyzer modules used | Per `02 §4.1` and `02 §5.1`: ST `{140}/{139}` singleton (shared with M192 only), F-BCM + Wheel, S-BCM-21k, 6-line paytable. **Only machine with `bcm_cycle_anchor` rule** (`03 §2.1` table row for `BCMCycleAnchorRule` row, `applies_to: ["M274"]` per `configs/machine_round_win_rules.json:13-15`). Uses: `BCMCycleAnchorRule` (`round_win.py:345`), `detect_cycle_peak`, `extract_round_trigger_anchor` (overridden by rule to inject synthetic pid=`_bcm_cycle`). Schema has 4 extras keys (`AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards`). Bonus_feature per `configs/bcm_pairings.json:703-724` = `ListRewardWheel` for all 3 active modes (1,5,7). | **Manifest**: `{"machine_id": "M274", "cluster": "SC-BCM-Modern", "overrides": {"spin_type_convention": {"paid": [140], "bonus": [139]}, "bcm_target_feature": "ListRewardWheel", "round_win_rules": ["bcm_cycle_anchor_m274"]}}`. Per `04 §5.6` M274 example — exactly the proposal's documented case. Inherits SC-BCM-Modern's 7 analyzer_features. Adds the existing `bcm_cycle_anchor_m274` rule via `round_win_rules` array. |
| Hash computation | `analyzer_version` whole-file. M274 NOT in virtual registry (only 6 virtual machines: M1sim, M15sim, M37sim, M43sim, M31sim, M279sim — verified in `slot_designer/configs/machines_virtual.json`). | `effective_analyzer_version(M274) = sha256(base || features_used)`. Features used: 7 SC-BCM-Modern features. **7 feature hashes participate.** Rule `bcm_cycle_anchor_m274` is declared in manifest but lives in `configs/machine_round_win_rules.json` per `04 §5.4` ("`load_rules_for_machine` reads either source"). |
| Onboarding cost | New BCM-cycle machine like M274 today: row in `machines.json` + `bcm_pairings.json` entry + rule applies_to update in `machine_round_win_rules.json`. **Cost: 3 files.** | Same 3 files + manifest entry. **Cost: 4 files.** Slight regression for this specific case. |
| Invalidation when shared analyzer changes | Today: M274 in 1007-pair stale bucket on any analyzer touch (3 completed runs per DB; verified). | Under proposal: M274 invalidated when (a) any SC-BCM-Modern feature hash flips → invalidates all ~28 BCM-21k schema machines (S-BCM-21k cluster from `02 §3.4`), or (b) the rule registry `RoundWinRule` ABC changes → invalidates 13 rule-bearing machines. `02 §6.5` worked example "Add new BCM `_unattributed_st` cleanup rule" → 421 → 28 BCM = **15× reduction**. |
| Migration steps | N/A | Phase 1: M274 sees no behavior change. Phase 2: byte-identical regen against M274's current `rv_20260513T034506Z_rawdata_847d89_9633e9` report. Verified observation: that report carries `pid=_bcm_cycle` with 315 hits, 4.87% RTP — the synthetic anchor. Phase 2's `features/cycle_peak_detection.py` carve-out must preserve this. Phase 3: M274 manifest entry per `04 §5.6` example (already in proposal). Phase 4: registry dispatch unchanged. Phase 5: maybe consolidate `machine_round_win_rules.json` into per-machine manifest (`04 §6 phase 5 deliverable 3` optional). |
| Verdict | ✓ handled | ✓ handled |

**Concrete evidence (LIVE data)**: queried `reports/M274/mode_1/versions/rv_20260513T034506Z_rawdata_847d89_9633e9/player_impact_summary.json`:
- `machine="M274"`, `config_md5=847d89cd5a651c14b44d56f3a998608b`, `code_md5=9633e9d6b64234f0d0b63a44a7954aaf`, `analyzer_version=ac7ff302873b`
- `rtp.point_pct=106.34%` (above target — known issue)
- `sampling.total_spins=358780`
- `player_impact.payout_ids_top20`: contains `pid=5801 hits=3592 rtp_pp=54.11` and `pid=_bcm_cycle hits=315 rtp_pp=4.87`
- **Notable absence**: `payouts_by_spin_type` is NOT in this summary — this was the `729a6ca` commit that added it (after M274's report was generated; M274 has not been re-run since). Confirms that older reports without the field continue to load — backward-compat is real.

**Issue surfaced (none, all clean)**: M274 is the textbook case the proposal handles correctly. The `_bcm_cycle` synthetic anchor produced by `BCMCycleAnchorRule` is preserved across the migration; the manifest captures the rule reference; the hash composition correctly invalidates only the BCM machines on a `cycle_peak_detection` feature edit.

---

### §2.7 — Case 7: M400 (hypothetical future machine)

**Scenario**: M400 introduces a **novel mechanic**: "collect bar resets after wild progression". A horizontal collect bar fills as wild symbols progress through the grid (paid spins). When the bar reaches 100%, a bonus is triggered (ST=200 — a new SpinType), and the bar resets. Crucially: **the bar progression depends on per-spin grid analysis** that no current machine performs.

This is not any of: (a) plain BCM cycle (depends on `CollectCount`, not bar percentage), (b) lock-respin, (c) TopDollar selector, (d) wheel, (e) wild nudge (different trigger). It's genuine novelty.

| Aspect | Today (current architecture) | Under proposal (Alternative A) |
|---|---|---|
| Which analyzer modules used | Doesn't exist today. To add: would need a new code path inside `parse_chunk_response` (the 8,176-line monolith) — likely a new conditional block somewhere in the 2354-3961 range. Add per-machine entries in `bcm_pairings.json` (if BCM-like; otherwise no). Add per-machine `RoundWinRule` subclass in `round_win.py` if standard win extraction isn't sufficient. **Cost: 4+ files touched** including the heavy 8,176-line analyzer file. Any byte change in the analyzer file → 1007 (m,mode) stale flag. | **Proposed**: write a new feature module `fresh_slotlab/analyzer/features/wild_progression_bar.py` (or similar) implementing the `AnalyzerFeature` Protocol. New SCHEMA_KEYS (e.g. `player_impact.wild_progression_bar`). Optionally a new `RoundWinRule` subclass. Manifest: `{"machine_id": "M400", "cluster": null, "overrides": {"spin_type_convention": {"paid": [1], "bonus": [200]}, "feature_tags": ["WildProgression", "FreeSpin"], "analyzer_features": ["payouts_by_spin_type", "bankruptcy_simulation", "multiplier_profile", "wild_progression_bar"]}}`. **Cost: 1 new module + 1 manifest entry + 1 machines.json row + maybe 1 round_win_rule.** |
| Hash computation | Today: any new code in analyzer flips `analyzer_version` for all 1007 (m,mode) pairs. **Reduction factor: 0×.** Adding M400 forces fleet-wide stale flag. Brief §4 user goal explicitly named: "添加新机台,有一些新 feature,更新分析器,会不会导致我所有的 report 失效?" — answer today is YES. | Under proposal: new feature module `wild_progression_bar.py` is hashed independently. M400's manifest is the only one listing it. **No other machine's `effective_analyzer_version` changes.** Brief §4 user goal satisfied: O(1) impact. Worked example #4 in `04 §4.2` covers this exact pattern. |
| Onboarding cost | 4+ files including analyzer monolith. Risk of touching the wrong section of 8k lines is high. | 3-4 files, all small. The new feature module is self-contained — `compute_hash()` reads its own `__file__` bytes (`04 §5.2` default impl). Manifest references it by FEATURE_ID. **Lowest-touch onboarding the proposal can deliver.** |
| Invalidation when shared analyzer changes | Today: M400 always in stale bucket on any analyzer touch. | Under proposal: M400 invalidated only by (a) core/* changes, (b) `wild_progression_bar.py` changes, or (c) one of the universal features changes. Other machines unaffected by `wild_progression_bar.py` edits. **Reduction: 421 → 1 for the bespoke feature; 421 → 421 for universal feature changes.** |
| Migration steps | N/A (M400 doesn't exist yet) | If onboarding happens **after** Wave 2 deployment: standard path. If **during migration**: M400 onboarding can wait for phase 2-3 complete. Rollback if M400 introduces problems: revert just M400's manifest + feature module, fleet unaffected. |
| Verdict | ✗ broken today (fleet-wide blast unavoidable) | ✓ handled |

**Concrete evidence (constructed scenario)**: this hypothetical demonstrates the proposal's most important user-facing claim. Today, adding any new mechanic-related logic to `player_impact_analyzer.py` (per `03 §6` #1) **automatically** invalidates 1007 (m,mode) pairs because `compute_analyzer_version()` is whole-file SHA256. Under proposal, the new feature module's hash is independent.

**Issue surfaced (none for the proposal — this is the win case)**: M400 is exactly the brief §4 user goal scenario; proposal handles it correctly. The `AnalyzerFeature` Protocol's `compute_hash()` from `__file__` bytes (`04 §5.2` default impl) ensures isolation.

**One concrete sanity check the validator wants the designer to confirm**: when M400's `wild_progression_bar.py` is created, the analyzer orchestrator (`main()` post-migration) needs to discover it. Today's orchestrator does NOT auto-discover; it has hardcoded calls to extraction blocks. The proposal §5.2 says "The orchestrator at main() reads SCHEMA_KEYS during summary assembly to know what keys to expect" but doesn't fully spec the discovery mechanism. **Suggestion**: in phase 2, designate a registration pattern (e.g. each feature module registers itself via decorator or imports into a `features/__init__.py` `ALL_FEATURES` tuple). Without it, the orchestrator silently skips new features. This is a small spec gap.

---

## §3 Cases that break

Strictly speaking, **none of the 7 cases are catastrophically broken** under the proposal. However, 4 cases surface **awkwardness** or **gaps**, listed here in decreasing severity:

### §3.1 — M99 (Case 4): cluster gap

- **Root cause**: M99 (and the ~30 medium outliers of `02 §5.2` plus ~5 each of plugin-lock-symbol / plugin-lock-lines candidates from `02 §6.2`) doesn't fit any of the 6 super-clusters in `04 §5.5`. M99 also has a **known-unfixed** dedup bug per memory `reference_round_win_rule_architecture.md`.
- **Impact on proposal**: §4 + §5 ASSUME most machines fit one of 6 clusters; reality is ~42 machines fall outside (12 heavy + ~30 medium). Manifest size and validation scope are larger than §5.5 implies.
- **One-line suggestion**: this case needs **either** (a) intermediate "tier-2 archetype clusters" added to `04 §5.5` covering plugin-lock-symbol (5 machines), plugin-lock-lines (5 machines), plugin-wheel-selector-type2 (96 rows), plugin-common-selector-type2 (~20 rows), plugin-wild-nudge (7 machines) — i.e. promote the `02 §6.2` candidates into named clusters; **or** (b) explicit acknowledgment that ~42 of 421 machines (~10%) use `cluster=null` with explicit overrides.

### §3.2 — M37 (Case 3): virtual-side `compute_code_md5` blast radius

- **Root cause**: Touching `core/engine/symbol.py` flips ALL 6 virtual machines' `code_md5` simultaneously per `03 §5.1`. M37 is the cleanest demonstration: M37 doesn't use `scatter` semantics but its hash flipped after `54b7d01` because it shares `core/engine/symbol.py` with all virtual machines. The proposal §4.3 explicitly disclaims this scope.
- **Impact on proposal**: brief §6 success criterion "Adding a new machine should affect O(1) hashes, not O(N=393)" is satisfied on the **real-fleet (analyzer) side** but NOT on the **virtual-side core engine**. For the 6 virtual machines (M1sim, M15sim, M37sim, M43sim, M31sim, M279sim), core/engine changes still cause O(6) invalidation. Brief §1 user goal is mostly satisfied — virtual is a small fleet — but the limitation should be explicit.
- **One-line suggestion**: this case needs **an explicit clause in §4.3** noting that `compute_code_md5` is per-virtual-machine but bundles ALL `core/engine/*.py` + `core/emitter/*.py` files; per-virtual-machine isolation from core-engine changes is **out of scope for this proposal** but documented for follow-up.

### §3.3 — M15 (Case 2): pre-migration runs lose freshness signal

- **Root cause**: phase 3 deliverable 5 says backend compares `runs.effective_analyzer_version` vs freshly-computed effective version. Pre-migration runs have NULL effective_version; comparison logic must fall back to legacy `analyzer_version`.
- **Impact on proposal**: 2030 completed runs (per DB) pre-date phase 3. Without explicit dual-comparison, all 2030 immediately show "stale" badge after migration deployment. The brief §5.1 ("existing reports continue serving") is satisfied for **serving**, but the freshness badge regresses.
- **One-line suggestion**: this case needs **explicit dual-comparison spec** in `04 §6 phase 3 deliverable 5`: "For runs with NULL effective_analyzer_version, fall back to legacy analyzer_version comparison."

### §3.4 — M400 (Case 7): feature discovery mechanism unspecified

- **Root cause**: `04 §5.2` defines `AnalyzerFeature` Protocol but doesn't fully spec how the orchestrator (`main()` post-migration) discovers feature modules. Without a registration pattern, new feature files may be silently skipped.
- **Impact on proposal**: M400 onboarding requires the new `wild_progression_bar.py` to be picked up by the orchestrator. If the orchestrator hardcodes feature module names, M400's onboarding becomes "add one line to a registry list", which is fine but should be explicit.
- **One-line suggestion**: this case needs **a registration pattern specified** (e.g. each feature module exports itself into `features/__init__.py:ALL_FEATURES`, or auto-discovery via `importlib.iter_modules` at orchestrator startup).

---

## §4 Hash composition trace — file-edit → invalidation per case

This section walks each of the 5 brief §3 commits (`54b7d01`, `729a6ca`, `8411c9d`, `4cbcab2`, `5c4a111` reverted) against each of the 7 cases, both Today vs Under-proposal. Cross-product evidence comes from `03 §5`.

### §4.1 — Predicted-vs-Actual matrix for `54b7d01` (scatter symbol kind)

Files edited: `core/engine/symbol.py` (+8 lines), `core/engine/evaluator.py` (+8 lines, 3 hunks), `core/engine/spin.py` (4 comment edits), `core/engine/feature_protocol.py` (2 comment edits), `slot_designer/machines/M31/spec.json` (kind: filler→scatter).

| Case | Today: `code_md5` flips? | Today: `analyzer_version` flips? | Under proposal: `effective_analyzer_version` flips? | Verified path |
|---|---|---|---|---|
| **M1 (real)** | No (real fleet upstream-md5; `03 §5.1` "0 real-fleet hash flips") | No (analyzer source untouched) | No | ✓ proposal matches today |
| **M1sim (virtual)** | **Yes** (`code_md5=03ff4194e214` will flip because `core/engine/symbol.py` is in M1sim's hash input per `03 §3.1`) | n/a | **Yes** (proposal `04 §4.3` explicitly does NOT change virtual code_md5 path; M1sim still flips on core/engine change) | Both today and under proposal: M1sim flips. **Expected.** |
| **M15 (real)** | No | No | No | ✓ |
| **M15sim (virtual)** | Yes (same reason as M1sim) | n/a | Yes | ✓ (no change) |
| **M37 (real)** | No | No | No | ✓ |
| **M37sim (virtual)** | Yes (`code_md5=03ff4194e214`, same as M1sim) | n/a | Yes | ✓ — limitation surfaced in §3.2 |
| **M99 (real)** | No | No | No | ✓ |
| **M279 (real)** | No | No | No | ✓ |
| **M279sim (virtual)** | Yes (`code_md5=7803ae4fe30a` flips because shared core/* changed) | n/a | Yes | ✓ |
| **M274 (real)** | No | No | No | ✓ |
| **M400 (hypothetical)** | n/a | n/a | No (M400 doesn't use core/engine/symbol.py through any feature module that hashes it) | ✓ Better than today — but only because M400 is real-fleet, not virtual |

**Plus M31sim's `configSummaryMd5` specifically flipped** because `M31/spec.json` was changed (filler→scatter; `03 §5.1` evidence). Other virtual machines: configSummaryMd5 unchanged.

**Verdict on `54b7d01` predictions**: ✓ matches `03 §5.1` audit. Proposal correctly handles the real-fleet side (no flips); the virtual-side flip is acknowledged but not reduced (§3.2 limitation).

### §4.2 — Predicted-vs-Actual matrix for `729a6ca` (add payouts_by_spin_type)

File edited: `fresh_slotlab/player_impact_analyzer.py` (+230 lines).

| Case | Today: `analyzer_version` flips? | Under proposal: `effective_analyzer_version` flips? | Notes |
|---|---|---|---|
| M1 | Yes (all 1007 stale) | Yes (`payouts_by_spin_type` is in M1's manifest as universal feature) | Same blast as today; matches `04 §4.2` worked example #2 ("invalidation radius: same as today (421)"). |
| M15 | Yes | Yes (same reason) | Same |
| M37 | Yes | Yes | Same |
| M99 | Yes | Yes (universal feature) | Same |
| M279 | Yes | Yes | Same |
| M274 | Yes | Yes | Same |
| M400 (hypothetical) | n/a | Yes if M400 also declares `payouts_by_spin_type` in manifest | Same — universal feature. **But**: this is where the proposal demonstrates flexibility: if M400 doesn't need ST-split (single SpinType), M400 wouldn't declare it; the feature change wouldn't flip M400. |

**Crucial observation**: today, ALL 7 cases get invalidated by `729a6ca`. Under proposal, ALL 7 still get invalidated **because the proposal treats `payouts_by_spin_type` as a universal feature** (declared by every manifest's cluster default). The proposal's `04 §4.2` worked example #2 explicitly says "invalidation radius: same as today (421)" for this case.

**The proposal's improvement is theoretical here, not practical**: it provides the *mechanism* to make `payouts_by_spin_type` opt-out, but the default behavior keeps it universal. **This is fine** — the brief asks for "the *ability* to scope" not "scope everything by default". Designer §7.4 question about strict-vs-lenient drift detection is the related decision point.

### §4.3 — Predicted-vs-Actual matrix for `8411c9d` (rename hit_rate_pct → hit_rate)

File edited: `player_impact_analyzer.py` (+38/-38), `tests/backend/test_analyzer_st_split.py`, `src/web_console/frontend/app.js` (+338/-324), `src/web_console/frontend/pure.js` (-12).

Under proposal, the analyzer's portion would land in `features/payouts_by_spin_type.py`. The frontend's portion lands in the new `RENDERER_REGISTRY` (`04 §5.3`).

| Case | Today: `analyzer_version` flips? Frontend break? | Under proposal: `effective_analyzer_version` flips for which cases? Frontend break? |
|---|---|---|
| M1 (15 runs) | Yes; renderer broken if no fallback (rescued by `7e5fe32`) | Yes (universal feature `payouts_by_spin_type` schema_version bumps to 2). Renderer registry handles fallback explicitly per `04 §5.3` → no break for pre-rename M1 reports. |
| M15 (9 runs) | Yes; rescued by fallback | Yes; renderer registry covers it |
| M37 (10 runs) | Yes; rescued | Yes; covered |
| M99 (8 runs in DB, 0 on disk) | Yes (DB stale flag) | Yes — but M99 has no on-disk reports to render anyway |
| M279 (10 runs) | Yes; rescued | Yes; covered |
| M274 (3 runs) | Yes — but verified: M274's most-recent report (rv_20260513T...) has NO `payouts_by_spin_type` block at all (older analyzer) → no fallback rescue needed because the field is absent | Yes; orchestrator-side schema_versions block addressed `04 §4.4`'s legacy-field carve-out |
| M400 (hypothetical, no on-disk data) | n/a | Yes if M400 declares `payouts_by_spin_type` |

**Verdict**: proposal handles this case identically to today in invalidation radius (universal feature) but **better** in renderer break risk (explicit registry > scattered `??` fallbacks). Confirms `03 §4.3` concern about silent schema renames is structurally addressed.

### §4.4 — Predicted-vs-Actual matrix for `4cbcab2` (`st_win==0` → `st_hits==0` filter)

File edited: `player_impact_analyzer.py` (1-line filter change, line ~6481), `tests/backend/test_analyzer_st_split.py` (+ Test 10, 11).

| Case | Today | Under proposal |
|---|---|---|
| M1 | analyzer_version flips; no semantic impact (M1 has no zero-win trigger pids in its 1-line paytable per `02 §4.1`) | Same. Universal feature edit → invalidation; semantic null for M1. |
| M15 | analyzer_version flips; M15 has pid 666 trigger marker (per `02 §3.3.4`), so post-fix M15 reports gain a row | Same. `features/payouts_by_spin_type.py` schema_version bumps; M15 reports gain the row on regen. |
| M37 | analyzer_version flips; no zero-win trigger pids in M37 | Same |
| M99 | flips; behavior dependent on M99's specific pid distribution (rawdata not deeply probed for this) | Same |
| M279 | flips; M279 has trigger pid 27905 (per `02 §3.3.4` "Bug 1"), may gain row | Same |
| M274 | flips; M274 has pid 5801 ListRewardWheel trigger anchor (per `02 §3.3.4` and verified in M274 summary at 3592 hits, 54% RTP) — but pid 5801 has WIN > 0, so the filter change doesn't affect it; pid `_bcm_cycle` similarly has WIN > 0 | Same |
| M400 | n/a today | Universal feature edit → flips if M400 declares it |

**Verdict**: identical invalidation pattern Today vs Proposal. Proposal doesn't change blast radius for this case (universal feature edit). Confirms `03 §5.4` finding.

### §4.5 — Predicted-vs-Actual matrix for `5c4a111` reverted (80% threshold)

File edited: `player_impact_analyzer.py:6404-6417`, `tests/backend/test_analyzer_st_split.py`.

Out-of-scope per brief §7 and `04 §8.2`. The threshold logic lives inside `features/payouts_by_spin_type.py` post-migration. The behavior is opaque to validator scope.

| Case | Today | Under proposal |
|---|---|---|
| All 7 | analyzer_version flips on commit + flips again on revert (`03 §5.5`) | `effective_analyzer_version` (for the `payouts_by_spin_type` feature) flips on commit + flips again on revert. Same pattern. |

**Verdict**: same blast pattern. No improvement from proposal because the universal feature scope captures this.

### §4.6 — Cross-product summary table

For each of the 7 cases × 5 commits = 35 cells, the proposal-vs-today comparison:

| Case \ Commit | 54b7d01 (scatter) | 729a6ca (ST-split add) | 8411c9d (rename) | 4cbcab2 (filter) | 5c4a111 reverted (threshold) |
|---|---|---|---|---|---|
| M1 (real) | Same: no flip (real-side) | Same: universal flip | Same: universal flip; better break-resistance under proposal | Same | Same |
| M1sim (virtual) | Same: code_md5 flip | n/a (analyzer change doesn't touch virtual code_md5) | n/a | n/a | n/a |
| M15 (real) | Same: no flip | Same: flip | Same: flip + better break-resistance | Same: flip + reports gain row | Same |
| M37 (real) | Same: no flip | Same | Same | Same | Same |
| M37sim (virtual) | Same: code_md5 flip | n/a | n/a | n/a | n/a |
| M99 (real) | Same: no flip | Same | Same | Same | Same |
| M279 (real) | Same: no flip | Same | Same | Same | Same |
| M279sim (virtual) | Same: code_md5 flip | n/a | n/a | n/a | n/a |
| M274 (real) | Same: no flip | Same; M274 doesn't yet have field anyway | Same | Same (pid 5801 win>0 unaffected) | Same |
| M400 (hyp) | n/a | Universal flip *if* declared; otherwise no flip | Same as 729a6ca | Same | Same |

**Key insight from this matrix**: for the 5 brief §3 commits, the proposal provides **identical or strictly-better** invalidation behavior across all 7 cases. **No regression cases.**

The proposal's wins come from **commits not in the brief §3 set** — specifically:
1. Adding a per-cluster feature (e.g. `cycle_peak_detection`): proposal reduces 421 → 28 (`04 §4.2` example #3).
2. Adding a per-machine bespoke (e.g. `bespoke_m21_buffalo`): proposal reduces 421 → 1 (`04 §4.2` example #4).
3. Onboarding M400-class novelty: proposal reduces 421 → 1.

These wins are real even though they don't show up in the §4.1-§4.5 commit-replay matrix. Verifying these wins against any new commit would require the proposal to be deployed.

---

## §5 Backward-compat check

For each case, can existing on-disk reports continue serving without regeneration?

### §5.1 — Per-case backward-compat verification

| Case | Reports on disk (`reports/<M>/mode_*/versions/`) | Backend serves them? Under proposal? | Regen needed for migration? |
|---|---|---|---|
| **M1** | Multiple version dirs across modes; 15 completed runs in DB | Today: yes. Under proposal: yes via `04 §4.4` dual-read pattern ("Frontend reads `effective_analyzer_version` first, falls back to legacy `analyzer_version`"). The legacy `analyzer_version` field is preserved per `04 §6 phase 2 deliverable 13`. | No — backward-compat preserved. **Test**: a phase-3 frontend with the dual-read pattern + a phase-2 report on disk (legacy field only) renders identically to today. Validator suggests adding a regression test for this in phase 3 deliverables. |
| **M15** | Multiple version dirs; 9 completed runs | Same as M1 — backward-compat preserved | No |
| **M37** | Multiple version dirs; 10 completed runs | Same — preserved | No |
| **M99** | **Empty versions/ dirs across all 4 modes** (verified by ls); 8 DB run rows but no on-disk artifacts | Backend has nothing to serve today; proposal doesn't change this | No (nothing to preserve) |
| **M279** | Multiple version dirs; 10 completed runs | Preserved | No |
| **M274** | 3 version dirs (most recent: `rv_20260513T034506Z_rawdata_847d89_9633e9`); 3 completed runs | Preserved. Verified by reading: `analyzer_version=ac7ff302873b`, has `_bcm_cycle` pid in `payout_ids_top20` (will continue rendering). | No |
| **M400 (hyp)** | n/a — doesn't exist | n/a | n/a |

### §5.2 — General backward-compat verification

Sampling the **schema fields the frontend renders** under each phase:

| Schema field | Pre-migration reports | Phase 2 reports (after analyzer slicing) | Phase 3 reports (after manifests) | Frontend reads under proposal |
|---|---|---|---|---|
| `summary.analyzer_version` | Present | Present (kept as legacy field per `04 §6 phase 2 deliverable 13`) | Present (kept) | Yes — fallback |
| `summary.effective_analyzer_version` | Absent | Present (additive write) | Present | Yes — primary |
| `summary.config_md5`, `summary.code_md5` | Present | Present | Present | Yes |
| `player_impact.payouts_by_spin_type` | Absent (pre-`729a6ca`) or present (post-) | Same | Same | Yes — with schema_version-gated fallback per `04 §5.3` registry |
| `player_impact.payout_ids_top20[].rtp_contribution_pp` | Present | Present | Present | Yes |
| `summary.schema_versions` | Absent | Present (additive) | Present | Yes — per `04 §5.3` registry |

**Backward-compat verdict**: ✓ **fully maintained** for all 6 real-data cases (M1, M15, M37, M99, M274, M279) AND for the hypothetical M400. The proposal's `04 §6 phase 2 deliverable 13` ("Write summary.effective_analyzer_version alongside summary.analyzer_version") is the load-bearing claim. The dual-field write + dual-read pattern + frontend fallback rule registry collectively preserve every existing report's renderability.

**One regen scenario, optional**: if user wants the updated `_bcm_cycle` attribution from `bcm_cycle_anchor_m274` rule to flow into M274's older reports (rv_20260511, rv_20260512), those would need regen — but they ALREADY would need regen today for the same reason. Proposal doesn't make this worse.

**One regen scenario for M99**: M99 has 0 on-disk reports. If/when M99 reports are generated post-migration, they'd carry the new `effective_analyzer_version` schema natively. No backfill needed.

### §5.3 — DB schema migration

Per `04 §6 phase 3 deliverable 4`: backend writes new `effective_analyzer_version` column to `runs` table. Per `04 §8.8`: ALTER TABLE is trivial. **Backward-compat consideration**: existing 2030 rows have NULL `effective_analyzer_version`. The `/api/reports/stale-count` logic at `app.py:5694` must handle NULL — see §3.3 issue surfaced; one-line spec gap.

**Migration verdict**: backward-compat is preserved across the 7 cases. **Maintained.**

---

## §6 Verdict

### §6.1 — Summary

| Verdict signal | Count |
|---|---|
| Cases walked | 7 |
| ✓ handled cleanly | 4 (M1, M15, M279, M274) |
| ⚠ awkward (handled but with caveats) | 3 (M37 virtual-side scope, M99 cluster gap, M400 discovery mechanism not fully specced) |
| ✗ broken | 0 |
| Cases that **break the proposal** | 0 |
| Cases that **surface fixable spec gaps** | 4 (§3.1, §3.2, §3.3, §3.4) |
| Backward-compat | Fully maintained |
| Cross-product (7 × 5 commits) regressions | 0 |

### §6.2 — Final verdict: **APPROVE-WITH-REVISIONS**

The proposal **handles all 7 representative cases correctly in principle**. The hash composition algorithm (`04 §4.1`), manifest schema (`04 §5.5`), feature carve-out plan (`04 §6 phase 2`), and backward-compat strategy (`04 §6.6`) all hold up under concrete walk-through. The brief §4 user goal — "添加新机台,有一些新 feature,更新分析器,会不会导致我所有的 report 失效?" — is **correctly answered by the proposal**: yes for universal feature changes (and that's the intended behavior); no for per-cluster or per-machine bespoke feature changes (and that's the win).

But **four spec gaps emerged during validation** that the designer should address in a revision before implementation begins:

1. **§3.1 / M99 / SC-non-cluster machines**: ~42 of 421 machines (`02 §5.1` 12 heavy + `02 §5.2` ~30 medium) don't fit the 6 super-clusters. Proposal's `04 §5.5` cluster table needs to either (a) add intermediate clusters (lock-symbol, lock-lines, wheel-selector, etc. — the `02 §6.2` plugin candidates), or (b) explicitly acknowledge that ~10% of fleet uses `cluster=null` with explicit overrides. Current §5.5 implies most machines fit the 6 super-clusters; reality is ~84% (`02 §5.4`).

2. **§3.2 / M37sim / virtual-side core engine blast radius**: `compute_code_md5` flips all 6 virtual machines on any `core/engine/*.py` change. `04 §4.3` disclaims scope for this but doesn't explicitly note the implication. **Add a sentence in §4.3** noting "Per-virtual-machine isolation from core engine changes remains out of scope for this proposal."

3. **§3.3 / M15 / pre-migration runs freshness signal**: phase 3 deliverable 5 needs explicit dual-comparison spec: "For runs with NULL effective_analyzer_version, fall back to legacy analyzer_version comparison." Without this clause, 2030 existing runs immediately flip to "stale" after migration deploy.

4. **§3.4 / M400 / feature discovery mechanism**: `04 §5.2` Protocol sketch doesn't specify how the orchestrator discovers feature modules. Add a registration pattern (decorator, `features/__init__.py:ALL_FEATURES`, or `importlib.iter_modules`-based auto-discovery) to phase 2 deliverables.

**Plus one bonus suggestion** (not a blocker; surfaced in §2.5 M279 walkthrough): phase 5 manifest validation sweep should explicitly enumerate machines flagged by memory `feedback_invariant_with_fallback_hides_drift.md` (M279, M250, M268, M260, M264, M163, M147) as `bcm_cycle_anchor` candidates needing enablement. The proposal correctly leaves enablement out-of-scope but should at least document the audit deliverable.

### §6.3 — What APPROVE-WITH-REVISIONS means here

Per `00 §9` ("if Wave 3 verdict = REJECT or APPROVE-WITH-MAJOR-REVISIONS, coordinator loops back to Wave 2 (designer v2); minor revisions handled in main-session-authored `07_decision.md`"):

The 4 revisions identified are **minor**:
- All four are clarification / explicit-acknowledgment / one-line spec additions.
- None require changing the algorithm (hash composition stays; manifest schema stays; phase plan stays).
- None invalidate the validator's "✓ handled" verdicts on M1, M15, M279, M274.

Therefore: **APPROVE-WITH-REVISIONS**, with the 4 revisions captured in `07_decision.md` for designer-or-coordinator to apply (no second Wave 2 loop needed).

### §6.4 — Cluster coverage gaps the validator did NOT walk

Cases not walked but worth a brief assessment for completeness (per agent definition §1 ≥1 outlier — covered, ≥1 hypothetical — covered):

- **SC-WheelSelector (96 rows including 85 M273 variants)**: not walked individually. The proposal `04 §7.5` open question explicitly asks "manifest carry 85 nearly-identical rows ... or fan out via variant machinery?" This is a phase 3 implementation decision; not a validator block.
- **SC-LockRespin-50 (9 machines)**: similar to SC-Vanilla in cluster handling; not walked. Expected to behave like M1 case.
- **S-LockLines family (5 machines)**: similar to the M99 case (would need `lock_lines` feature module under proposal). Same gap as §3.1.

These do not contradict the verdict.

---

```
arch-validator complete.
- Cases walked: 7
- Verdicts: 4 ✓ / 3 ⚠ / 0 ✗
- Cases that break: 0 (4 awkward cases surface fixable spec gaps)
- Backward-compat: fully maintained
- Verdict: APPROVE-WITH-REVISIONS
- Output: session_artifacts/_arch/06_validation.md
```
