# 05 — Architecture Critique: Analyzer Unbundle (M275-driven)

> **Produced by**: arch-critic (W3)
> **Date**: 2026-05-25
> **Topic dir**: `session_artifacts/_arch_analyzer_unbundle/`
> **Inputs consumed**: 00_brief.md, 01_pipeline_map.md, 02_taxonomy.md, 03_coupling_audit.md, 04_architecture_proposal.md, live codebase reads
> **Verdict**: APPROVE-WITH-REVISIONS

---

## §1 Top Concerns (5 most serious)

**TC1 — Mechanism Registry build timing uses Tier 2 evidence that isn't yet computed (ordering contradiction, §12.3)**

The proposal claims Tier 2 (bonus_chain_dynamics, F6) provides freespin evidence for the registry. But the registry is built "after all chunks merged, before emit()," while F6 hasn't run yet at registry-build time. The proposal notices this at §12.3 and pivots: "use Tier 3 raw SpinType detection instead." But Tier 3 ST behavior labeling comes from F1's `spin_type_rows`, which also hasn't emitted yet. The ordering is: registry build → F1 emit → F2/F3/F4 emit → F5 emit → F6 emit. The proposal claims Tier 3 raw `spin_type_spins` is sufficient for M275, but the ST behavior classification (paid vs. free) that turns raw ST counts into `"free"` label lives inside F1, not the registry builder. The registry either re-implements F1's classification logic, or it has a hidden dependency on F1's output — which means F1 must emit before the registry builds. This ordering constraint is neither stated as a rule nor enforced anywhere in the design.

**TC2 — Phase ordering contradiction: F1 must emit before F3/F4, but F1 is never carved (stays inline), creating an unmarked contract**

The proposal states F3 and F4 plugins reconstruct `_st_label` from `summary["player_impact"]["spin_type_breakdown"]` which Block F1 writes. This is the correct resolution. But it requires F1's inline code to have already written `spin_type_breakdown` to the summary dict before any plugin's `emit()` is called. The proposal does not enforce this. The emit loop runner (which the proposal says uses REQUIRES + topological sort) only knows about feature IDs — F1 is not a plugin, it is inline code. There is no mechanism to express "run inline block F1 before running any plugin." If a future phase accidentally calls the plugin emit loop before F1's inline code runs, F3/F4 silently see an empty `spin_type_breakdown` and produce empty output with no error.

**TC3 — `DECLARED_DEPS` is a runtime key-presence check, not a type-safe contract. Silent mis-attribution remains possible during migration (§4.2)**

The dep validation code in §4.2 checks `if dep_key not in summary: raise RuntimeError`. This catches a missing key but does not catch a key written with the wrong schema (e.g., `_bcm_bonus_feature = None` is present but semantically empty — not an error per the check, but the collect_mechanic plugin would silently produce a wrong result). More critically: during Phase C5, `upstream_feature.py` must write `summary["_bcm_bonus_feature"]` as a side effect of its `emit()`. But the emit-loop pseudocode in §4.2 shows the DECLARED_DEPS validation happening before `emit()` is called for each plugin. This means the runner validates that `_bcm_bonus_feature` is present before calling `collect_mechanic.emit()` — but `upstream_feature.emit()` writes it. If topological sort puts `upstream_feature` first, the key is present when `collect_mechanic` runs. If sort order is wrong (or if `upstream_feature` errors mid-emit), the key is absent and the RuntimeError fires mid-run — killing the entire report build. Per `03_coupling_audit.md §4.3`, the current BankruptcySimulation temp-key pattern is already fragile; DECLARED_DEPS formalizes it but does not eliminate the fragility of run-killing failures on a key ordering error.

**TC4 — "Universal" Phase C2 feature addition to all 253 manifests is actually the proposal's largest single fleet invalidation event, and it happens before the BCM-specific phases have been validated (§7.2, §8.4)**

The proposal presents the C1-C6 phased rollout as "at most 6 fleet-wide invalidation events." But Phase C2 adds `payout_id_panel` to all 253 non-variant manifests in a single PR, changing all 253 machines' `effective_analyzer_version`. Phase C3 does the same for `payouts_by_spin_type`. Phases C4, C5, C6 each do it again. That is 5 of the 6 phases each triggering a 253-machine invalidation. The proposal calls this "the surgical property" but surgical means isolated blast radius. What is described is: fix M275 as pilot → immediately add to all 253 machines. The surgeon cuts one incision and then opens the entire patient. The designer's rationale is that inline code was already running for all machines, so universalizing is correct. This is true, but it means the migration carries a 5×253 = 1265 machine-mode rebuild burden with no incremental validation window. If Phase C2's `payout_id_panel` has a bug that affects a machine class that is not M275 (e.g., machines with non-666 scatter markers, of which there are 50), the operator discovers it after rebuilding 253 machines — not after piloting on M275.

**TC5 — The DECLARED_DEPS mechanism puts `_mechanism_registry` as a temp key in summary, then deletes ALL `_`-prefixed keys after emit. This creates a window where the registry object is garbage-collected mid-emit if any plugin holds a reference past emit (§4.2, cleanup block)**

The proposal's cleanup code at §4.2 is: `for _key in list(summary): if _key.startswith("_"): del summary[_key]`. This runs after ALL plugins have emitted. The registry is at `summary["_mechanism_registry"]` (a live Python object, not a JSON-serializable dict). When cleanup runs, the registry reference in `summary` is deleted. Any code that retained a reference via `registry = summary.get("_mechanism_registry")` inside `emit()` still holds the object alive. But if any plugin in the emit loop tries to read `summary["_mechanism_registry"]` after cleanup (e.g., a late-running plugin that was incorrectly ordered), it gets `KeyError`, not a clean error. The cleanup-on-emit-all pattern is correct for JSON temp keys but introduces a subtle timing dependency for non-JSON objects (the registry instance) that could cause confusing failures during development of later phases.

---

## §2 Stress Questions (15 questions)

---

### Q1 — Mechanism Registry placement and its own invalidation

**Question**: The designer places `mechanism_registry.py` in `fresh_slotlab/analyzer/` (not `core/`) to avoid fleet-wide base-hash invalidation. Per `03_coupling_audit.md §2.1 Symbol 1`, only `core/*.py` files feed `compute_base_analyzer_version`. Files outside `core/` are not hashed. But the registry is imported by plugin files. When `mechanism_registry.py` changes (e.g., the jackpot PID threshold changes from ≥10000 to ≥9000), which hash detects this?

**Designer's likely answer**: "The plugin files that import `mechanism_registry.py` will have their own file hash checked. When a plugin file is edited to use the new registry interface, its hash changes, which flips `effective_analyzer_version` for machines declaring that plugin."

**Why it is insufficient**: The hash of a plugin file (`AnalyzerFeature.compute_hash()` in `_base.py:190`) hashes `sys.modules[cls.__module__].__file__` — the plugin's `.py` source file. It does NOT hash the content of imported modules. If `mechanism_registry.py` changes its jackpot threshold logic from `>= 10000` to `>= 9000`, the plugin files that import it are UNCHANGED. Their file bytes are unchanged. The plugin file hashes are unchanged. `effective_analyzer_version` is unchanged. Old reports remain classified as "current" when they were produced with the old threshold. A machine that previously had jackpot_applicable=False (because its jackpot PID was 9500) would continue to show the old incorrect result until manually regenerated.

**Evidence**: `03_coupling_audit.md §2.1 Symbol 4` explicitly documents: "`compute_hash()` hashes `cls.__module__.__file__` which is the plugin's own `.py` file." It does not transitively hash imports.

**Verdict**: NOT ADDRESSED. The registry being outside `core/` prevents fleet-wide invalidation but also means registry logic changes are invisible to the versioning system. This is the exact same pre-existing gap for `round_classification.py` and `round_win.py` (`01_pipeline_map.md §10 Q7`, `04 §8.2`), which the proposal acknowledges but defers. The proposal defers the same gap for `mechanism_registry.py` without acknowledging that it defers it.

---

### Q2 — Jackpot PID threshold: PID 9999, 10001, 27000

**Question**: The designer's jackpot detection is "any PID in `payout_id_win` where `int(pid) >= 10000`." Per `02_taxonomy.md §5 Ax5`, 26 machines have jackpot PIDs observed as ≥10000. But: (a) What if a machine has a regular high-multiplier win at PID 10001 that is not a jackpot? (b) What if a machine's jackpot is PID 9999? (c) What if PID 27000 is a feature-marker (trigger only, win=0) for some other machine — would it be misclassified as a jackpot PID because 27000 ≥ 10000?

**Designer's likely answer**: "Tier 1 manifest override handles edge cases. Operators can declare `mechanism_overrides.jackpot_pid_set` explicitly. Tier 3 raw ≥10000 is a heuristic that works for the 26 observed machines. The naming convention (machine-ID-prefixed: 27502 = M275's jackpot) suggests 10000+ as a reliable threshold."

**Why it is insufficient**: The scatter marker pid=666 is a zero-win PID with line_id=-1. The scatter detection rule (line_id=-1 + win=0) correctly filters scatter PIDs before jackpot classification. But the proposal does not make clear whether `jackpot_pid_set` detection first checks `if pid in scatter_marker_pids: exclude`. If PID 27000 is a scatter-trigger for machine X (zero-win, line_id=-1) AND ≥10000, it would be added to `jackpot_pid_set` by Tier 3 raw detection. The scatter exclusion must happen before jackpot classification, and this order is not specified in the proposal.

More concretely: `02_taxonomy.md §5 Ax5` documents 26 machines with jackpot PIDs. The threshold ≥10000 is not validated against machines outside those 26. There are 230 machines that currently show no jackpot PIDs — have any of them been checked for PIDs ≥10000 that are NOT jackpots? The taxonomy was built from first-chunk samples (1500 rounds per machine). A machine with a rare high-PID feature-marker (hit rate 1 in 500) might appear in the "no jackpot" group simply because the sample was too small.

**Verdict**: PARTIAL. The fallback to Tier 1 manifest override is a valid escape valve for edge cases. But the interaction between scatter marker detection and jackpot detection (ordering and exclusion logic) is not specified in the proposal.

---

### Q3 — DECLARED_DEPS topological sort edge cases

**Question**: The proposal says "the runner enforces topological order" using `REQUIRES`. What happens when: (a) two plugins declare `REQUIRES` on each other (mutual dependency); (b) a plugin's `REQUIRES` names a FEATURE_ID not in the manifest's `analyzer_features` list; (c) `DECLARED_DEPS` names a temp key `"_foo"` but no plugin writes `_foo` (typo); (d) the topological sort produces an ambiguous ordering (multiple valid orderings — are they deterministic across Python versions/dict implementations)?

**Designer's likely answer**: "(a) Circular dependency should raise RuntimeError at sort time. (b) The DECLARED_DEPS validation catches missing keys before emit. (c) DECLARED_DEPS validation raises RuntimeError if key not in summary. (d) Python's sort is stable; break ties by declaration order in manifest."

**Why it is insufficient**: For (a): the proposal does not specify whether the topo-sort raises a runtime error on cycle detection or silently picks an arbitrary order. For (b): if `CollectMechanicFeature.REQUIRES = ("upstream_feature",)` but the manifest doesn't declare `"upstream_feature"`, then `get_features_for_machine(manifest)` returns `CollectMechanicFeature` without `UpstreamFeatureFeature`. The topo-sort has a node with an edge to a non-existent node — not a circular dependency, but a missing dependency. The proposal is silent on this case. The consequence: `collect_mechanic.emit()` runs; `_bcm_bonus_feature` dep is absent; RuntimeError fires; report build fails silently (or is caught by §4.3 error handling as a log-and-continue). For (c): same as (b). For (d): the proposal says "REQUIRES + topological sort by runner" but does not specify which topo-sort implementation or tie-breaking rule. The existing `feature_registry.py`'s `get_features_for_machine()` returns features in registration order (`ALL_FEATURES` list order). Registration order comes from import order, which is currently three independent import sites (`pia:4816-4827`, `versioning.py:165-176`, `validate_manifests.py:43-47`). If Phase C5 adds `upstream_feature` and `collect_mechanic` to `ALL_FEATURES`, which site imports them first determines registration order. This is the same ordering trap that caused silent wrong results in the existing system (`03_coupling_audit.md §4.1 ALL_FEATURES`).

**Verdict**: NOT ADDRESSED. The proposal asserts topological sort without specifying the algorithm, cycle detection, or missing-dependency behavior.

---

### Q4 — `_st_label` reconstruction requires F1 to have already emitted

**Question**: The proposal at §3 (response to ordering objection) states: "F2/F3/F4 plugins can reconstruct `_st_label` from `summary['player_impact']['spin_type_breakdown']` which Block F1 writes to summary at emit time." The proposal's Phase C1 does not carve F1 — F1 stays inline. The emit loop runner in §4.2 calls `_machine_features = get_features_for_machine(manifest)` and then iterates over them. Where in the code flow does Block F1's inline execution happen relative to the emit loop?

**Designer's likely answer**: "F1 runs inline in the finalization block before the plugin emit loop. The order is: F1 inline → mechanism_registry build → plugin emit loop."

**Why this is potentially insufficient**: The proposal's Phase C1 deliverables list at §7.2 do not include "ensure F1 runs before the emit loop." The call site pseudocode in §4.2 shows the new emit loop starting with `mechanism_registry = _build_mechanism_registry(...)` and then iterating plugins. If the PIA finalization block structure is not explicitly ordered (F1 → registry build → plugins), a future refactor could move the plugin loop before F1's inline code and break F3/F4 silently. The proposal relies on positional ordering of code in `player_impact_analyzer.py` — a convention, not an enforced contract. Since `_st_label` is not written to summary (it's a temp local), F3/F4 plugins reading `summary["player_impact"]["spin_type_breakdown"]` will get `KeyError` if called before F1 runs.

**Verdict**: PARTIAL. The design is logically correct but depends on implicit code ordering that is not enforced by the plugin protocol. Phase C3 deliverables should explicitly state the ordering requirement for the implementer.

---

### Q5 — Backward compatibility: 393×N existing reports missing `machine_mechanics` fields from registry

**Question**: After Phase C4 ships and M275's `machine_mechanics` key now has `jackpot_pid_set` and `freespin_st_set` fields, what does the frontend do when it reads an older report that has `machine_mechanics.jackpot.applicable: false` with no `jackpot_pid_set` field?

**Designer's likely answer**: "Field additions are additive. Old reports don't have the new fields; the frontend renders them as absent/undefined, not as an error. The REGISTERED_FALLBACK_RULES mechanism on the machine_mechanics plugin handles this."

**Why it is insufficient**: The proposal's `machine_mechanics.py` plugin (Phase C4) is a NEW plugin — it did not exist before Phase C4. Old reports were built without this plugin running. Old reports' `machine_mechanics` key was written by the PIA inline Block F8. The new plugin's `SCHEMA_VERSION = 1` is the first version. Old reports have no `machine_mechanics` key from the plugin (they have it from inline code). The `REGISTERED_FALLBACK_RULES` mechanism maps old SCHEMA_VERSIONs to new ones — but it requires a `schema_version` field to be present in the stored data to know which rules to apply. Old inline-produced `machine_mechanics` keys have NO `schema_version` field (inline code never wrote it). The frontend renderer has no way to distinguish "this is an old-inline-produced key" from "this is a plugin-produced key at schema v1." Per `03_coupling_audit.md §4.4`: "REGISTERED_FALLBACK_RULES is defined in _base.py but not yet consumed by any production code." The fallback mechanism is a declared intent, not a shipped capability.

**Evidence**: `03_coupling_audit.md §4.4` explicitly states: "No backward-compatibility rendering is currently possible for historical summaries if a plugin bumps its schema version." This is a direct contradiction of the proposal's migration claim.

**Verdict**: NOT ADDRESSED. The REGISTERED_FALLBACK_RULES mechanism is not shipped. The migration table at §11.2 says "field values corrected in C4 (jackpot.applicable may flip true)" which is fine for new reports, but does not address frontend behavior on existing old reports that show `applicable: false` without `jackpot_pid_set`.

---

### Q6 — Per-chunk extract() call creates N×M redundant work: memory and performance characterization absent

**Question**: The proposed `extract()` wiring in §4.2 calls `_feature.extract(parse_state, rec)` once per chunk per declared plugin. For M275 mode 1 with ~10 chunks and (post-carve) ~8 plugins, this is 80 `extract()` calls. But the concern is about `reduce()` accumulation: if `payout_id_panel.extract()` accumulates per-pid payline records from each chunk, and each chunk has 5000+ rounds with 10+ pids, the `_feature_accs` dict for `payout_id_panel` grows to hold a full replica of the cross-chunk payline accumulator. How large is this in memory relative to PIA's existing `payout_id_win`, `payout_id_hits`, `payline_winning_symbols_rln` accumulators?

**Designer's likely answer**: "The plugin accumulates only what it needs. `payout_id_panel.extract()` reads from the chunk-level `rec` dict's already-aggregated fields, not from raw round-level data. The `rec` dict's `payout_id_win` is already a per-pid aggregate. The plugin's `reduce()` merges these aggregates, which is the same cost as PIA's existing merge loop."

**Why this requires scrutiny**: The proposal at §4.1 says `ParseState.chunk_dict` gives access to `payline_winning_symbols_rln` (a per-pid payline topology record). If `payout_id_panel.extract()` needs this to compute `shape`, `cols`, `paylines` fields (Gap #7, #8 per §7.2 Phase C2 deliverables), it is accumulating per-pid payline records — not just win/count integers. `payline_winning_symbols_rln` per `01_pipeline_map.md §2` is `dict[str, dict[...]]` with per-payline symbol placement data. Duplicating this accumulator in the plugin's own `_feature_accs` doubles the memory cost for that data structure. For 393 machines with 10 chunks each, PIA already has this data; the plugin replicates it. The proposal gives no memory bound analysis.

**Verdict**: PARTIAL. The design is architecturally sound (plugins aggregate from already-aggregated chunk records, not raw rounds). But the claim that "N×M work where M=plugin count" is resolved by noting plugins consume already-aggregated data — this needs explicit statement in the proposal so implementers don't replicate raw-round accumulation inside `extract()`.

---

### Q7 — Phased carve invalidation cadence: 5 phases × 253 machines = 1265 rebuilds with no pilot window

**Question**: The proposal at §7.2 says "each phase is independently deployable." For Phases C2 through C6, the deliverables include: "Add X feature universally to all 253 non-variant manifests." This means each phase triggers a 253-machine `effective_analyzer_version` flip. With ~10 modes per machine (modes 1, 2, 5, 7 per M275's manifest), that is up to 253×4 = 1012 stale report entries per phase, 5 phases = 5060 stale entries. Where is the operator workflow for rebuilding these? The brief constraint `00_brief.md §4` says 393×N existing reports must remain readable — they do remain readable, but operators must trigger 5060 regenerations. Is there a batch mechanism?

**Designer's likely answer**: "Operators use the web console's batch run feature to regenerate reports. The phased rollout means this is spread over time, not all at once. The `feedback_md5_is_a_tag_not_a_destruction_signal.md` principle means old reports are not deleted — only marked historical."

**Why it is insufficient**: The proposal does not state the operator burden explicitly. The phrase "migration cost: MEDIUM, approximately 3 phased releases" understates the batch-rebuild scope. Per `session_artifacts/_impl/STATUS.md` (referenced in the brief), 59 machines already fail L2 smoke — these machines may have incomplete or broken cached data. Re-running 253+ machines from cache for 5 phases assumes cache validity across all machines. For machines with stale or missing cached chunks (e.g., M281 per `02_taxonomy.md §13` has no rawdata), re-running is not possible from cache. The proposal is silent on this edge.

**Verdict**: PARTIAL. The migration story correctly applies the md5-as-tag principle but omits the operator workflow for batch rebuild and the edge case of machines with no valid cached chunks.

---

### Q8 — Sidecar persistence race conditions and concurrent-run behavior

**Question**: The proposal at §5.4 says `mechanism_portrait.json` is written alongside `player_impact_summary.json` in `reports/<M>/mode_<N>/versions/<rv>/`. If two concurrent runs produce reports for the same machine/mode (e.g., batch run + manual re-run), do they write to the same path? What are the locking semantics?

**Designer's likely answer**: "Each run has a unique `rv_<timestamp>` directory. Two concurrent runs produce different `rv_` directories and do not conflict."

**Why this is plausible but needs verification**: Per `01_pipeline_map.md §1`, the output path is `args.output_dir/player_impact_summary.json` where `args.output_dir` is set by the backend to a versioned run directory. If the backend correctly generates unique `rv_` IDs per run, there is no collision. But the proposal at §6 also mentions `reports/M275/mode_1/latest_portrait.json` as an optional "per-machine latest-portrait pointer." If two concurrent runs both try to write `latest_portrait.json` simultaneously, the last writer wins. This is the same race condition pattern that exists for `latest.json` — the existing system presumably handles this (the proposal doesn't explain how). Since `latest_portrait.json` is deferred to Phase 3 and marked optional, this is not blocking.

**Verdict**: ADEQUATELY ADDRESSED for the core sidecar (versioned per-run directory). The optional latest-portrait pointer has the acknowledged race but is deferred and optional.

---

### Q9 — Cross-reference detector confidence: upstream_feature_breakdown stability

**Question**: The mechanism registry's freespin detection (Tier 2) uses `bonus_chain_dynamics.chain_count > 0` as evidence. But `bonus_chain_dynamics` is computed in Block F6, which has NOT run when the registry is built (per §12.3 the registry is built before the emit loop). The proposal resolves this by falling back to Tier 3 raw (SpinType in `spin_type_spins` with "free" behavior). But the `upstream_feature_breakdown` panel (Tier 2 source) itself depends on `_infer_feature_spin_type_mapping()` (`01_pipeline_map.md §3 Block F5 helper calls`). If the upstream API changes its `FeatureWin` schema (a known risk per `memory/reference_sampling_api.md`), both the upstream_feature_breakdown detection AND the mechanism registry's Tier 2 evidence become unreliable simultaneously. What is the fallback?

**Designer's likely answer**: "Tier 1 manifest override takes precedence. If upstream API changes, the operator declares `mechanism_overrides.freespin_applicable: true` in the manifest. The three-tier precedence ensures the system degrades gracefully."

**Why it is insufficient for the no-manifest-reviewed-96%-of-BCM-machines reality**: Tier 1 requires operator intervention. For the 96% of BCM machines with unreviewed manifests (`02_taxonomy.md §8`, 53 of 57 BCM machines are not reviewed), no Tier 1 override will be declared. If upstream API silently changes and Tier 2 breaks, Tier 3 raw detection is the only fallback. For machines like M275 where `CurFreeSpin = 0` and `JackpotIds = ""` (the original bugs that created gaps #1 and #2), Tier 3 raw would also produce the wrong answer. The three-tier system's safety guarantee depends on Tier 1 being populated — which it isn't for 96% of BCM machines.

**Verdict**: PARTIAL. The three-tier design is sound. But the assumption that Tier 1 is the fallback of last resort conflicts with the documented manifest review state.

---

### Q10 — "Zero-code new machine" property for M275 itself: multiplier wilds excluded

**Question**: The proposal at §13.1 states "Case B — BCM recombination (standard): Zero-code onboarding property HOLDS after this work, for the following mechanism combinations: BCM cycle collection, Freespin triggered by scatter, Jackpot PIDs, BCM+Freespin+Wheel combination. Multiplier wilds: NOT YET." M275 has 4 hard mechanics: BCM + multiplier wild + jackpot + scatter. The "zero-code" claim for M275 explicitly excludes multiplier wilds. Does the property hold for M275, or only for a hypothetical "M275 without multiplier wilds"?

**Designer's likely answer**: "The zero-code property holds for M275 minus gap #4. Gap #4 is paused fleet-wide, not M275-specific. The property is satisfied for the 3 of 4 mechanics that CAN be auto-inferred. Gap #4 requires resuming multiplier inference, which is a separate project."

**Why the claim is misleading as stated**: M275 is the driving case presented to the user. The brief's goal is "a correct report for M275 without any code change." If M275 produces a report where `multiplier_wilds.applicable: "paused"` in the portrait, the gap is not closed for M275 — it is deferred. The proposal at §10 Gap #4 entry says "tested via: N/A until multiplier inference bugs are fixed." This is honest. But §13.1's claim "BCM+Freespin+Wheel combination: zero-code after this work" with M275 as the test case while simultaneously deferring one of M275's four defining mechanics is a scoping claim that could mislead the user when they look at the M275 report and still see `multiplier_wilds.applicable: "paused"`.

**Verdict**: PARTIAL. The proposal is internally consistent about what is deferred. The presentation conflates "M275's combination type" with "M275 fully correct" in a way that a non-technical reviewer could misread.

---

### Q11 — Hidden state in PIA main() beyond `_st_label` and `_bcm_bonus_feature`

**Question**: The coupling auditor (`03_coupling_audit.md §4.3`) flags `_bankruptcy_rows` and `_bankruptcy_sim_session_spins`. The proposal correctly handles these via DECLARED_DEPS. But `01_pipeline_map.md §4 Block F7` describes `feature_to_spin_type`, `spin_type_to_feature`, `_sub_stream_acc`, `sub_streams_by_feature` as intermediates from Block F5. When F5 is carved into `upstream_feature.py`, how does F6 (`bonus_chain_dynamics.py`) access `spin_type_to_feature` which F5 computes at `pia:3501`? (`01_pipeline_map.md §7 Dependency D`). The proposal at §7.2 Phase C5 says "upstream_feature.py sets `_bcm_bonus_feature` and `_bcm_bonus_source` as DECLARED_DEPS." But Dependency D (F5→F6 via `spin_type_to_feature`) is NOT listed in the DECLARED_DEPS of Phase C6's `bonus_chain_dynamics.py` plugin.

**Designer's likely answer**: "The `bonus_chain_dynamics` block (F6) uses `chains_by_feature` accumulator from the merge loop, which already has feature labels. The `spin_type_to_feature` mapping is used to build `all_chains_by_feature` at `pia:3491` inside the merge loop — this dependency resolves during chunk accumulation, not in the finalization block."

**Inspection result**: Grep of `pia.py` shows `all_chains_by_feature` populated in the merge loop (`pia:1866` and `pia:2592` — both the from-cache and online paths). The feature name labeling on chain entries happens in the merge loop, not in the finalization block. F6's finalization block reads the pre-labeled `all_chains_by_feature`. This means Dependency D is resolved earlier in the pipeline than the proposal's ordering table (`01_pipeline_map.md §7`) suggests, and the cross-plugin coupling between F5 and F6 at emit time is less severe than the coupling auditor implied.

**However**: `01_pipeline_map.md §7 Dependency D` explicitly says "Block F6 (bonus_chain_dynamics) uses `spin_type_to_feature` at `pia:3501` to categorize `chain_chunk_summaries` entries." This refers to F6's finalization code, not the merge loop accumulation. If this is in the finalization block, then F5 must have already run its inference before F6 categorizes entries. The proposal does not address this specific sub-dependency.

**Verdict**: NOT ADDRESSED for the specific F5→F6 via `spin_type_to_feature` dependency in finalization. The proposal covers F5→F9 (DECLARED_DEPS for `_bcm_bonus_feature`) but not F5→F6. Phase C6 deliverables must enumerate this dependency.

---

### Q12 — Frontend renderer registry deferral vs. SCHEMA_VERSION bump in Phase C3

**Question**: Phase C3 bumps `payouts_by_spin_type` SCHEMA_VERSION from 1 to 2 and adds a `REGISTERED_FALLBACK_RULES = {1: {"missing_fields": [...]}}`. But `03_coupling_audit.md §4.4` explicitly states: "REGISTERED_FALLBACK_RULES is defined in _base.py but not yet consumed by any production code." Phase 4 (frontend renderer registry) is deferred to `00_brief.md §6`. Without the frontend renderer registry consuming `REGISTERED_FALLBACK_RULES`, how does the frontend handle old reports at schema version 1 that lack `shape`, `cols`, `paylines`, `notes` fields?

**Designer's likely answer**: "Since the new fields are additive, old reports render correctly — the new fields are simply absent. The `REGISTERED_FALLBACK_RULES` mechanism is future-proofing for when schema changes are breaking (not additive). For Phase C3's purely additive changes, the frontend just doesn't render the new columns for old reports."

**Why this requires explicit acknowledgment**: The proposal at §14.2 says "old frontend renders them if present, ignores if absent" for the additive fields. This is fine if the frontend renderer iterates dynamically over present fields. But `03_coupling_audit.md §2.1 Symbol 9` shows `app.js:5440` has a note about `payouts_by_spin_type` rows not carrying `rtp_pct`. If `app.js` has any hard-coded field references in its `payouts_by_spin_type` renderer (not just dynamic iteration), the assumption "ignores if absent" may not hold. The proposal does not verify this claim against the actual renderer code.

**Evidence**: `03_coupling_audit.md §2.1 Symbol 9` documents `app.js:5385–5386` reads `payouts_by_spin_type` and `app.js:5440` comments on missing `rtp_pct`. The renderer behavior on new fields is not confirmed in the proposal.

**Verdict**: PARTIAL. The additive-is-safe assumption is likely correct but is not verified against the actual `app.js` renderer code. The implementer should grep `app.js` for hard-coded `payouts_by_spin_type` row field accesses before shipping Phase C3.

---

### Q13 — Gap #6 `estimated_correction_pp: 0.0` — if correct, proposal scope is 7/8 gaps, not 8/8

**Question**: The proposal's §15 Q1 says Gap #6 "may not be a formula bug but a correct 0.0 output." The brief `00_brief.md §3 table` lists 8 gaps. The proposal at §10 marks Gap #6 as "open question." If Gap #6 is actually correct (not a bug), then the proposal closes 7 gaps out of 8 (or 6 out of 8 if multiplier wilds remain deferred). Does the proposal still justify its Medium migration cost and 6-phase carve for 7/8 gap closure?

**Designer's likely answer**: "Gap #6 requires formula investigation before claiming it's closed. The architecture sets up the infrastructure (portrait surfaces `robots_with_pending_cycle`) to investigate. The other 6 confirmed gaps (excluding #4 deferred, #6 open) justify the full carve."

**Why this doesn't require pushback from critic**: The carve is justified independently of gap count — the structural unbundling (plugin system, mechanism registry, DECLARED_DEPS) delivers value regardless of whether Gap #6 is a real bug. The gap count is motivation, not justification. This critique accepts the designer's reasoning.

**Verdict**: ADEQUATELY ADDRESSED. The proposal is honest about Gap #6 uncertainty and the architecture provides investigation infrastructure without requiring a premature formula fix.

---

### Q14 — M273 family (85 variants) benefit claim: variants inherit via `inherits_from`?

**Question**: The proposal at §11.4 says "fixing M275 benefits 107 fleet entities if variants inherit the corrected manifest." M273 has 85 variants (`02_taxonomy.md §10`). These variants use `inherits_from: "M273"` (their base), NOT `inherits_from: "M275"`. M275 and M273 are separate base machines in the same archetype. How does fixing M275's manifest benefit the 85 M273 variants?

**Designer's likely answer**: "The 107-entity benefit claim is for the B_BCM_FREESPIN_WHEEL archetype as a whole (20 base + 87 variants). The universal feature addition (adding new plugins to all 253 non-variant manifests) benefits all 20 bases including M273. M273's variants inherit from M273, and when M273 gets the new features, its 85 variants inherit them."

**Why the math is off**: The proposal at §11.4 states "variants inherit via `inherits_from` cascade." But `inherits_from` in variant manifests points to the BASE machine, not M275. The 85 M273 variants inherit from M273.json. The new plugins are added universally to ALL 253 non-variant manifests including M273.json. When M273.json gets `payout_id_panel` and `machine_mechanics`, its 85 variants inherit those features. M275's specific manifest corrections (`spin_type_convention.paid = [140]`) do NOT flow to M273 variants — they are M275-specific. The 107-entity benefit claim is for archetype-level plugin universalization, not for M275-specific fixes. This is technically correct but could be clearer.

**Verdict**: ADEQUATELY ADDRESSED (the mechanism is correct), but the phrasing at §11.4 "fixing M275 (the archetype's driving case) benefits 107 fleet entities" is misleading — the benefit comes from universal plugin addition, not from M275-specific manifest corrections.

---

### Q15 — Implementation order: ALL_FEATURES three manual-import sites and new plugin registration

**Question**: The coupling auditor (`03_coupling_audit.md §2.2 Symbol 5`) documents three manual import sites that populate `ALL_FEATURES`: `versioning.py:165-176` (imports all plugins for hash computation), `pia:4816-4827` (imports all plugins for emit loop), and `validate_manifests.py:43-47` (imports all plugins for validation). When Phase C2 adds `payout_id_panel.py`, all three sites must import it, or the new plugin is silently absent from `ALL_FEATURES` at those sites. The proposal at §7.2 Phase C2 deliverables lists "M275 manifest updated" and "all 253 non-variant manifests updated" but does not list "add import of `payout_id_panel` to all three import sites." Has the designer enumerated these sites?

**Designer's likely answer**: "The implementation would naturally include adding the import. This is standard plugin registration."

**Why it matters enough to flag**: `03_coupling_audit.md §2.2 Symbol 5` explicitly documents the three-import-site trap and notes it as a "behavior-stable" risk: "If a new plugin is registered but NOT imported before `compute_effective_version_for_machine`, its hash is silently absent → wrong version for all machines that declare that feature ID." The proposal's Phase C2 deliverables section at §7.2 does not enumerate the three import sites as an explicit acceptance criterion. This omission means an implementer who adds the plugin file and updates manifests but forgets one import site will get silently wrong `effective_analyzer_version` for all 253 machines.

**Evidence**: `fresh_slotlab/player_impact_analyzer.py:4821-4827` — the two dual-path import blocks must both be updated. `fresh_slotlab/analyzer/versioning.py:165-176` must also be updated. Per `memory/feedback_subprocess_import_suicide_and_module_globals.md`, import-time side effects and dual-path imports are known failure modes in this codebase.

**Verdict**: NOT ADDRESSED. The Phase C2 (and C4, C5, C6) deliverables must explicitly enumerate: "(N) Add import of new plugin to `pia:4816-4827` (both try blocks), `versioning.py:165-176`, `validate_manifests.py:43-47`. Verify `ALL_FEATURES` count equals expected N after import."

---

## §3 Migration Risk Inventory

### Phase C1 risks

**Risk C1-1 — Dual-path merge loop: `extract()` wiring applied to one path only.**
PIA has the merge loop duplicated at `pia:1614-1963` (from-cache) and `pia:2620-2960` (online path), explicitly noted in source (`01_pipeline_map.md §8 Duplication 1`). Phase C1 must wire `extract()` in BOTH paths. The deliverables at §7.2 C1 say "wiring in PIA merge loop" (singular) — if the implementer patches only the from-cache path, online sampling runs never call `extract()` and plugins accumulate nothing from live-sampling runs.

**Rollback failure mode**: the rollback for C1 is "revert the 5 PIA merge loop lines that call `extract()`." If the implementer accidentally modified both paths but the rollback spec says "revert 5 lines," the rollback is incomplete and online-path plugins remain broken.

**Risk C1-2 — Pattern A `emit(None, summary)` → `emit({}, summary)` call signature change.**
C1 deliverable 5 says "update all 4 existing plugins from `emit(None, summary)` to `emit(final_acc, summary)` where `final_acc = {}` by default." The Pattern A plugins have assertions (`assert key in summary["player_impact"]`) that fire regardless of `final_acc`. Changing the call signature from `emit(None, summary)` to `emit({}, summary)` is backward-compatible only if no plugin code checks `if final_acc is None:` as a sentinel. The existing `_base.py` shows `emit(self, final_acc, summary)` signature — the current call site at `pia:4831` passes `None` as `final_acc` (the `parse_state` position argument, not `final_acc`). The current signature is actually `emit(parse_state, summary)` not `emit(final_acc, summary)`. This is a load-bearing signature change.

**Risk C1-3 — BankruptcySimulation.DECLARED_DEPS addition with no behavioral change claim.**
C1 deliverable 4 adds `DECLARED_DEPS = ("_bankruptcy_rows", "_bankruptcy_sim_session_spins")` to `BankruptcySimulation`. The dep validation in the new emit loop raises RuntimeError if these keys are absent. If any future code path runs `BankruptcySimulation.emit()` before the bankruptcy temp keys are stashed (e.g., in a test or a diagnostic mode), the RuntimeError is new behavior that was not present before. Tests for `BankruptcySimulation` must be verified against this new validation.

### Phase C2 risks

**Risk C2-1 — Double-write if Block F2 inline removal is incomplete.**
`03_coupling_audit.md §5 Case Study B` explicitly warns: "if PIA inline is NOT removed and plugin emit() writes the same key, last writer wins." Phase C2 must remove F2 and F2b inline code atomically with the plugin promotion. If the PR partially merges (only the plugin file, not the PIA inline removal), both write `payout_ids_top20` — plugin overwrites inline. The output appears correct but the test suite may have assertions against the inline output path that now pass for the wrong reason.

**Risk C2-2 — Non-666 scatter marker machines (50 machines) behavior change.**
The proposal's `payout_id_panel` plugin classifies pids in `registry.scatter_marker_pids`. The registry detects scatter markers as "line_id=-1 AND win=0." There are 50 machines with non-666 scatter markers (`02_taxonomy.md §6 Ax6`). These machines previously classified their scatter marker as `cat=paid` (the same bug as Gap #3 for M275). Phase C2 fixes this fleet-wide. The fix is correct but it IS a behavior change for 50 machines that previously showed `cat=paid` for their scatter marker. Frontend consumers that filter on `cat=paid` (e.g., RTP attribution) may see slightly different output for these 50 machines after Phase C2. The proposal's migration table at §11.2 does not call this out.

**Risk C2-3 — `payout_groups_top20` suppression: 9 machines with real groups.**
The proposal says 9 machines have non-zero `PayoutGroupId`. The registry sets `payout_groups_applicable = False` when "all observed PayoutGroupId == 0." For the 9 machines with real groups, `payout_groups_applicable = True` and the panel continues. But how does the registry determine "all zeros" — from the per-chunk accumulator `payout_group_win` which maps group_id → total_win? If a machine has both group_id=0 (most rounds) and group_id=5 (some rounds), the accumulator has both keys. The `max(payout_group_win.keys()) == 0` check from `04 §5.2` would incorrectly conclude "all zeros" if it only checks the max key. The correct check is whether any non-zero group_id has non-zero hits — a two-field check, not a max-key check.

### Phase C3 risks

**Risk C3-1 — Pattern A emit assertion removal.**
The Pattern A `PayoutsBySpinType.emit()` currently asserts `"payouts_by_spin_type" in player_impact`. When promoted to Pattern B, this assertion must be removed AND the inline Block F3 code must be removed. If the assertion removal happens but F3 removal is delayed (partial PR), the Pattern B plugin writes the key, then the assertion (now gone) no longer guards. If the assertion is kept but the plugin also writes, the assertion passes because the plugin wrote it — masking any logic error in the plugin's output.

### Phase C4 risks

**Risk C4-1 — `machine_mechanics.jackpot.applicable` value change for 26 machines.**
This is an intentional behavioral change (gap closure). But for the 25 machines OTHER than M275 that have jackpot PIDs (`02_taxonomy.md §5 Ax5`), the change from `applicable: false` to `applicable: true` may conflict with those machines' `rtp_integrity_contract.required_attribution_anchors`. If a jackpot PID is now marked `applicable: true` but is NOT in the machine's `required_attribution_anchors`, the Layer 3 integrity check behavior changes. The proposal should enumerate the 26 jackpot machines and verify their integrity contracts will remain GREEN after Phase C4.

### Phase C5 risks

**Risk C5-1 — `_resolve_bonus_feature()` called three times, now called twice in Phase C5.**
`01_pipeline_map.md §8 Duplication 2` documents `_resolve_bonus_feature()` called 3 times: once in F5 setup (`pia:3478`) and twice in F9 (`pia:4706, 4718`). Phase C5 consolidates to "compute once in upstream_feature.py, stash as DECLARED_DEPS." But the third call at `pia:4718` is for `feature_match` (a different result path than `pia:4706`'s `bonus_feature`). The consolidation must verify that a single `_resolve_bonus_feature()` call produces both the `bonus_feature` and `feature_match` outputs that F9 needs — or that two calls with the same arguments produce the same result (idempotent, just redundant).

**Risk C5-2 — `_load_bcm_pairings()` disk read eliminated but the config file remains unhashed.**
Phase C5 consolidates to one `_load_bcm_pairings()` call. This is correct. But `01_pipeline_map.md §10` and `04 §8.2` explicitly acknowledge `configs/bcm_pairings.json` is NOT hashed into `effective_analyzer_version`. If `bcm_pairings.json` is edited after Phase C5 ships, the collect_mechanic outputs change but no `effective_analyzer_version` changes. Old reports remain "current" when they used the old BCM pairings. The proposal acknowledges this deferred gap but does not flag it as a Phase C5 risk.

### Cross-phase rollback risks

**Risk XP-1 — Rolling back Phase C3 while C2 is already live.**
If Phase C3 (payouts_by_spin_type Pattern B) needs rollback after Phase C2 (payout_id_panel) is already live, the rollback restores Block F3 inline code in PIA. But the PIA inline Block F3 uses `_st_label` which was defined at `pia:3302-3305`. If Phase C2's PR modified PIA around that block (removing F2 inline), the F3 inline code's line numbers and local variable scope may have shifted. Rollback is not as simple as "restore F3 inline code" — it requires restoring the exact PIA state before C3 including the local variable context.

**Risk XP-2 — M275 manifest corrections in Phase C4 vs manifest errors already affecting Layer 4.**
Phase C4 corrects M275's manifest: `spin_type_convention.paid = [140]` and `expected_paid_st = [140]`. But M275 currently has `layer4_applicable: true` per the live manifest. With `expected_paid_st = [1]` (wrong), the Layer 4 check has been running against the wrong ST. After Phase C4's manifest correction, Layer 4 runs against ST=140 for M275, which may reveal Layer 4 failures that were previously masked by the wrong `expected_paid_st`. This is not a rollback risk per se, but it means Phase C4 may expose NEW failures for M275 that were hidden by the wrong manifest — which could be confusing if the operator interprets them as regressions.

---

## §4 Edge Cases Not Covered

**EC1 — First-time-load: manifest has `mechanism_overrides` but no rawdata yet.**
If a machine's manifest declares `mechanism_overrides.jackpot_pid_set: ["27502"]` but the machine has never been analyzed (no rawdata), the registry is built from Tier 1 alone. The portrait is written with `"_detection_source": "manifest"`. What does the `payout_id_panel` plugin do when `payout_id_win` is empty (no rawdata)? It writes `payout_ids_top20: []`. The registry's `jackpot_pid_set` from Tier 1 says jackpot applicable, but `payout_ids_top20` has no jackpot pid rows. The two panels are now inconsistent — portrait says jackpot applicable, `payout_ids_top20` has no jackpot entries.

**EC2 — Variant manifest inheriting from a base that is not in the universal feature addition list.**
The universal feature addition adds new plugins to "all 253 non-variant manifests." Variant manifests use `inherits_from`. If a base manifest is missing from the 253 (e.g., M278 and M280 per `02_taxonomy.md §13` have manifest issues), their variants don't inherit the new plugins. `compute_effective_version_for_machine` calls `versioning.py:186` which checks `inherits_from`. If the base manifest is malformed, the version computation falls back to the base — but which features does the variant declare? The proposal does not address machines with problematic base manifests.

**EC3 — Machines with `SpinType = 1` where `spin_type_spins["1"]` is the paid ST accumulator.**
The mechanism registry builds `freespin_applicable` from "any SpinType with 'free' behavior label from F1." F1's `spin_type_rows` classifies ST behavior based on `spin_type_bet`, `spin_type_paid_bet`, and ReMarks patterns. For machines where paid ST=1 and bonus ST is also ST=1 (never observed but possible in misconfigured machines), F1 may misclassify all spins as "paid" and the registry sets `freespin_applicable = False` incorrectly. More practically: for machines where the manifest's `spin_type_convention` is wrong (116 of 253 manifests have wrong `paid: [1]`), does F1's behavior classification rely on the manifest's convention or on rawdata observation?

**EC4 — Concurrent batch runs during a phase transition (plugin file updated, manifests not yet updated).**
If a batch run starts while Phase C2 is partially deployed (plugin file added but not all 253 manifests updated), machines with the updated manifest run with the new plugin; machines with the old manifest run without it. Both produce `effective_analyzer_version` values. The new-manifest machines use `payout_id_panel`; old-manifest machines use inline code. The resulting reports have different `payout_ids_top20` schema (new machines have `trigger_only`, `notes` fields; old don't). Frontend renders both in the same UI session, potentially causing inconsistent column rendering.

**EC5 — `mechanism_portrait.py` write failure behavior.**
The proposal says `mechanism_portrait.json` is written by `mechanism_portrait.py` after `write_summary_json()`. Per `memory/feedback_no_silent_swallow.md`, post-hook failures must persist diagnostic to disk, not be swallowed. If `mechanism_portrait.py` fails (e.g., JSON serialization error because the registry holds a non-serializable object), does the main run fail or does it continue with only `player_impact_summary.json` written? The proposal does not specify the error handling for the portrait write. If the portrait write is in a try/except that swallows the error, operators will never know the portrait is missing.

**EC6 — `effective_bet_for_rtp` availability during plugin emit.**
Per `01_pipeline_map.md §7 Dependency E`, `effective_bet_for_rtp` is used by every panel that computes `rtp_contribution_pp` (F2, F3, F4, F5, F6, F8, F9). When these panels become plugins and their `emit()` is called, they need `effective_bet_for_rtp` from the finalization context. The proposal does not specify how `effective_bet_for_rtp` is made available to plugin `emit()` calls. Is it passed via `DECLARED_DEPS` (declared as a temp key in summary)? Or is it in `final_acc`? The dependency is fleet-wide and load-bearing for RTP integrity.

**EC7 — `total_spins` and `total_paid_sessions` denominators.**
Similar to EC6, Block F9 (`collect_mechanic`) uses `total_spins`, `total_paid_sessions`, `clamp_pending_robots_total` etc. These are accumulator values from the merge loop, not from any plugin's `extract()`. When `collect_mechanic.py` Plugin B is called in `emit()`, how does it access `total_spins`? Via the summary dict? The summary dict at that point has the finalized `rtp.our_total_spins` and `player_impact.spin_type_breakdown` but the raw accumulator variables like `total_spins` are local to `main()`. The proposal does not specify how raw accumulator values (as opposed to summary-written fields) are made available to plugin emit().

---

## §5 Hidden Assumptions

**HA1 — F1 output structure is stable and consumable by plugins.**
The proposal assumes F3/F4 plugins can reconstruct `_st_label` from `summary["player_impact"]["spin_type_breakdown"]`. This requires that `spin_type_breakdown` exists, is written before the emit loop, and has a stable schema with ST integers as identifiable keys. `01_pipeline_map.md §4 Block F1` says `spin_type_breakdown` is written "at `pia:4441`." The emit loop runs after the summary is assembled. If the summary assembly (at `pia:4427-4516`) writes multiple keys at once from a literal dict, `spin_type_breakdown` is present when the emit loop runs. But if F1's inline code is ever moved into the summary literal construction, the ordering may change. This assumption is not validated in the proposal.

**HA2 — The 26 jackpot-PID machines all have PIDs ≥10000 as OBSERVED in cached rawdata.**
The registry builds `jackpot_pid_set` from observed `payout_id_win` with `int(pid) >= 10000`. This assumes the jackpot events have been observed in the cached chunk set. For machines with very rare jackpot events (e.g., M218 which has jackpot PIDs but may have hit rate < 1 per 10k spins), the 10k-spin cache may have zero jackpot observations. The registry would then set `jackpot_applicable = False` — same as the current gap. `02_taxonomy.md §5` says the 26 machines were identified from "first chunk of each machine (1500 rounds per machine)." If a jackpot PID has hit rate 1 in 5000, the first chunk may not have observed it. The Tier 1 manifest override is the escape valve, but for the 96% of BCM machines with unreviewed manifests, no Tier 1 override will exist.

**HA3 — `REQUIRES` topological sort is deterministic and cycle-free in the deployed fleet.**
The proposal asserts the runner enforces topological sort. This assumes no plugin declares a circular REQUIRES chain. In the proposal's design, `collect_mechanic.REQUIRES = ("upstream_feature",)`. If a future Phase C7 adds a plugin that `REQUIRES = ("collect_mechanic",)` and somehow `upstream_feature.REQUIRES = ("new_plugin",)`, there would be a cycle. The proposal provides no cycle detection specification.

**HA4 — The manifest validator (`validate_manifest`) handles new DECLARED_DEPS and REQUIRES ClassVars.**
`manifest_loader.py:622,648,664` validates `analyzer_features` against `ALL_FEATURES` using Rules 2, 4, 5, 8. After Phase C2 adds new plugins, the validator must recognize `"payout_id_panel"` as a valid feature ID. This requires the validator to have imported the new plugin (to populate `ALL_FEATURES`). If `validate_manifests.py` has a static list of plugin imports, adding a new plugin without updating `validate_manifests.py` silently makes `manifest["analyzer_features"] = ["payout_id_panel"]` fail Rule 2 validation for every machine.

**HA5 — Adding `_mechanism_registry` as a DECLARED_DEPS temp key does not cause JSON serialization failures.**
The cleanup block at §4.2 deletes all `_`-prefixed keys from summary before writing. The `write_summary_json()` call happens after cleanup. But the writer receives the summary dict. If any plugin's `emit()` stores a reference to the registry object INSIDE a summary value (not just reading from `_mechanism_registry`), and the cleanup block misses that embedded reference, `write_summary_json()` would fail when it tries to JSON-serialize the registry object. The proposal does not specify that `MechanismRegistry` must be JSON-serializable or that plugins must not embed registry references in their output.

---

## §6 Comparison to Alternatives

### Alternative 1 — Deferred mechanism registry, per-block fixes only (rejected at §2.1)

**Rejection rationale in proposal**: "does not address root cause; recreates coupling; does not close `extract()` lifecycle gap."

**Critique of rejection**: The rejection is valid on all three counts. However, the proposal slightly overstates the coupling problem with Alternative 1. Specifically: Gap #1 and #2 fixes (per §2.1 sketch: "add cross-reference in Block F8 — `if any(int(pid) >= 10000 for pid in payout_id_win)` → set jackpot applicable") are a local one-line change that does NOT recreate "exactly the coupling pattern the plugin architecture was designed to eliminate." They read a local accumulator (`payout_id_win`) that is already available in F8's scope — not a cross-panel write/read dependency. Alternative 1's blast radius for Gap #1 fix is genuinely "touch F8, flip legacy analyzer_version" — identical to Case Study B in `03_coupling_audit.md §5`. The proposal correctly identifies this as broad-but-not-destructive invalidation.

**Where Alternative 1 is genuinely weaker**: The "zero-code new machine" property is not achievable under Alternative 1 — this is the core user requirement. Alternative 1's rejection on this ground alone is sufficient; the coupling argument is secondary but still valid.

**Verdict**: Rejection is correct and adequately justified. The coupling restatement at §2.1 is slightly overstated but does not change the verdict.

### Alternative 3 — Per-chunk extract() wiring only (rejected at §2.3)

**Rejection rationale in proposal**: "does not close any of the 8 gaps; no standalone value."

**Critique of rejection**: The rejection is correct. Alternative 3 is infrastructure work without user-visible output. The brief's explicit requirement is "M275 as the driving case" with gap closure. Alternative 3 delivers none of that. The rejection is justified.

**One note**: Alternative 3 actually has more than zero standalone value — it unblocks ALL future Pattern B carves without requiring the full gap closure. If the team had budget constraints (e.g., implement only C1 and stop), Alternative 3 is the deliverable. The proposal dismisses this too quickly. However, given the user's explicit "最好直接把现在的 analyzer 拆了" instruction, the aggressive Alternative 2 is the correct choice.

---

## §7 Verdict

**APPROVE-WITH-REVISIONS**

The architecture proposal is fundamentally sound. The three-tier mechanism registry, DECLARED_DEPS formalization, Protocol v2 `extract()` wiring, and phased carve plan are all well-reasoned and grounded in Wave 1 evidence. The hash composition analysis is correct. The rejection of Alternative 1 is justified. The proposal honestly defers gaps #4 and #6.

### Mandatory revisions before approval (ordered by severity)

**REV-1 (Blocker) — Specify the ordering of: F1 inline → mechanism registry build → emit loop, as an enforced contract in Phase C1.**
The current proposal relies on positional code order in `player_impact_analyzer.py`. This must be stated as an explicit invariant in Phase C1 acceptance criteria, not an implicit convention. Specifically: the registry builder must document "F1's `spin_type_breakdown` must be in summary before this is called" and the emit loop must document "this must run after F1's inline code has completed."

**REV-2 (Blocker) — Phase C2 through C6 deliverables must enumerate all three `ALL_FEATURES` import sites (`pia:4816-4827` both try blocks, `versioning.py:165-176`, `validate_manifests.py:43-47`) as explicit acceptance criteria.**
Without this, the silent wrong-version risk documented in `03_coupling_audit.md §2.2 Symbol 5` will manifest for new plugins.

**REV-3 (Blocker) — Specify how raw accumulator values (`effective_bet_for_rtp`, `total_spins`, `total_paid_sessions`) are made available to plugin `emit()` calls.**
These are local variables in `main()` when the emit loop runs. Plugins that compute `rtp_contribution_pp` (which is the point of most panels) need `effective_bet_for_rtp`. Either: (a) add these to the summary dict as temp keys before the emit loop runs, OR (b) pass them as part of `final_acc`. The proposal must specify which approach and include it in Phase C1 deliverables.

**REV-4 (Significant) — Specify the mechanism_registry.py hashing gap explicitly alongside round_classification.py and round_win.py.**
The proposal already acknowledges the `round_classification.py` hash gap at §8.2 and defers it. The same gap exists for `mechanism_registry.py` (outside `core/`, not hashed). The proposal must explicitly state: "changes to `mechanism_registry.py` are not reflected in `effective_analyzer_version`; operators must manually invalidate when the registry detection logic changes." This is a known-and-accepted limitation, not a design flaw — but it must be documented in §8.2.

**REV-5 (Significant) — Phase C2 migration risk for 50 non-666 scatter marker machines must be enumerated in the migration table.**
Phase C2's scatter classification fix is correct and beneficial. But it IS a behavior change for 50 machines that previously showed `cat=paid` for their scatter markers. These machines' `payout_ids_top20` rows for the scatter marker will change from `category: "paid"` to `category: "scatter_trigger"`. If any machine's `rtp_integrity_contract.required_attribution_anchors` depends on the scatter marker being classified as a paid pid, Layer 3 may flip. The proposal's migration table at §11.2 says "additive fields added (notes, trigger_only)" but does not acknowledge the category-field change as a behavioral change.

**REV-6 (Significant) — DECLARED_DEPS topological sort specification: algorithm, cycle detection, missing-dependency behavior.**
The proposal specifies REQUIRES + topological sort at §3 and §4.1 without a reference implementation or specification of edge cases. For the Phase C5 `upstream_feature → collect_mechanic` dependency to be guaranteed correct, the sort algorithm must be specified and its behavior on missing-dependency cases must be defined.

**REV-7 (Informational) — Clarify "107 entities benefit" claim at §11.4.**
The 107-entity benefit comes from universal plugin addition to all 253 manifests (including M273.json), not from "fixing M275 flows to variants." Clarify the mechanism explicitly to avoid confusion at implementation time.

**REV-8 (Informational) — Add EC6/EC7 (effective_bet_for_rtp, total_spins availability) to Phase C1 open questions.**
These are currently undocumented edge cases that will surface immediately when any panel plugin's `emit()` tries to compute `rtp_contribution_pp` without access to the denominator. The current Phase C1 deliverables focus on wiring `extract()` but do not address the finalization-context availability of raw accumulators for `emit()`.
