# Pipeline Map — play-type refactor lens

> Wave 1 / arch-mapper output (play-type refactor session, 2026-06-01).
> Mission: map every significant function/section through the A/B/C lens:
>   (A) BASE-UNIVERSAL — stays in base regardless of mechanic
>   (B) MECHANIC-SPECIFIC — must become a play-type plugin
>   (C) PER-MACHINE CONFIG — lives with machine data, not code
>
> Prior map (`session_artifacts/_arch/01_pipeline_map.md`, 2026-05-15) used as
> bootstrap. Verified against current code on branch `claude/analyzer-unbundle-c2`.
> Stale items from the prior map are flagged explicitly.

---

## §1 Scope and entry points

### Pipeline

```
Upstream slot server → raw chunk JSON
  → fresh_slotlab/analyzer/core/parser.py:parse_chunk_response()
      round classification  (round_classification.py)
      win attribution       (round_win.py + rules config)
      trigger-session det.  (trigger_sessions.py)
      mechanism detection   (inline in parse_chunk_response)
  → main() merge loop aggregates N chunks
  → finalize: BCM/feature inference, guideline, archetype
  → stash keys written to summary dict
  → 9 feature-plugin emit() loop (topo-sorted)
  → write_summary_json + report.md
  → FastAPI backend (app.py) serves; frontend (app.js) renders
```

Entry points are unchanged from prior map (§1 / Layer 4 routes / Layer 5
frontend). No staleness in those sections.

### Key file-size facts (current)

| File | Lines |
|---|---|
| `fresh_slotlab/player_impact_analyzer.py` | 5135 |
| `fresh_slotlab/analyzer/core/parser.py` | ~1900 (parse_chunk_response + helpers) |
| `fresh_slotlab/round_classification.py` | 455 |
| `fresh_slotlab/round_win.py` | 593 |
| `fresh_slotlab/trigger_sessions.py` | 361 |
| `fresh_slotlab/analyzer/core/aggregator.py` | (several hundred) |
| `fresh_slotlab/analyzer/core/base_pipeline.py` | (sampling loop, HTTP) |

---

## §2 End-to-end call graph with A/B/C tags

### Stage 0: chunk ingestion + file write (A)

| Function | File:line | A/B/C | Justification |
|---|---|---|---|
| `_save_chunk_cache` | `analyzer/core/writer.py` (re-exported from `player_impact_analyzer.py:228`) | A | Writes envelope to disk; envelope format is universal, no mechanic logic |
| `_compute_upstream_schema_fingerprint` | `analyzer/core/parser.py` | A | Hashes round-field key set; pure format check |
| `update_chunk_entry` | `chunk_index.py:422` | A | Inverted-index sidecar maintenance; no mechanic knowledge |
| `update_entry` | `rawdata_index.py:182` | A | Per-mode summary index; no mechanic knowledge |

### Stage 1: per-chunk parse — `parse_chunk_response` (mixed B + A)

Located in `fresh_slotlab/analyzer/core/parser.py` (moved from PIA in Phase
P2-B1b). Called once per chunk in both live-sampling and cache-replay paths.

#### Sub-stages inside parse_chunk_response:

| Sub-stage | Function(s) | File:line | A/B/C | Justification |
|---|---|---|---|---|
| Envelope decode | `load_chunk_envelope`, `peek_chunk_envelope` | `parser.py` | A | Format only; applies to every machine identically |
| Schema sanity | `_check_round_schema` | `parser.py` | A | Required-field check; machine-agnostic |
| `analysisResult` parse | inline | `parser.py` | A | Sums `TotalWin.WinCredits`, builds `feature_chunk_tally`; field names universal |
| CostCredits reliability probe | inline | `parser.py` (was `pia.py:2495-2517`) | **B** | Detects LockReSpin-style machines (M10/M23/M131/M133) by sampling first 200 rounds; this is mechanic detection embedded in parse |
| Round-win extraction | `round_win.extract_round_win` | `round_win.py:430` | **B** | Core mechanic logic: decides what a round contributes to chunk_win; rule-driven for machines with special bonus semantics |
| Round-payouts extraction | `round_win.extract_round_payouts` | `round_win.py:451` | **B** | Same; decides which pay_ids a round credits |
| Trigger-anchor extraction | `round_win.extract_round_trigger_anchor` | `round_win.py:481` | **B** | Mechanic: which pay_id signals a bonus trigger |
| Trigger-session detection | `trigger_sessions.compute_trigger_sessions` | `trigger_sessions.py:131` | **B** | Full mechanic logic: two session-detection families (Type 1 Trigger-ReMarks, Type 2 win==0 anchor); determines which bonus rounds' wins belong to which trigger |
| Wild-nudge detection | `round_classification.is_wild_nudge_round` | `round_classification.py:138` | **B** | Mechanic: classifies ST=36 + ReMarks=move rounds; specific to wild-auto-nudge machines |
| Cycle-peak detection | `round_classification.detect_cycle_peak` | `round_classification.py:311` | **B** | Mechanic: BCM-family cycle detection from CollectCount resets |
| BCM cycle indices | `round_classification.at_cycle_peak_indices` | `round_classification.py:378` | **B** | Mechanic: identifies which paid rounds trigger BCM bonus |
| Pay-id attribution | `round_classification.attribute_lines_to_pay_ids` + `parse_payline_records` | `round_classification.py:192-303` | **B** | Mechanic: 3-pass line→pay_id resolution (direct / suffix / single-remaining); machine-specific symbol-id→pay_id mapping |
| Authoritative pay_ids | `round_classification.extract_authoritative_pay_ids` | `round_classification.py:172` | A | Reads `PayoutIdToWinAmount`; universal field read (no mechanic decision) |
| Session-level rollups | `_close_session`, `_flush_bonus_chain` | `parser.py` (inlined) | **B** | Builds session histograms and chain summaries; depends on trigger-session output (itself B) |
| Symbol / payline counting | inline loops | `parser.py` | A | Counts symbols per column and payline hits; universal |
| Bankruptcy rep extraction | `_extract_bankruptcy_reps` | `_utils.py` | A | Produces (bet, win) tuples for simulation; no mechanic knowledge |
| Result assembly | `return {...}` | `parser.py` (end of function) | A | Flattens accumulated dicts; the KEYS are universal, VALUES come from B-stage logic above |

### Stage 2: main() accumulation loop (A + B + C)

`player_impact_analyzer.py:main()` iterates chunks, merges per-chunk dicts,
then runs finalize. The accumulation itself is pure arithmetic (A). The
finalize stage contains significant B.

#### Finalize functions:

| Function | File:line | A/B/C | Justification |
|---|---|---|---|
| `ci_halfwidth_pp` | `player_impact_analyzer.py:765` | A | CI math; universal statistical formula |
| `_infer_feature_spin_type_mapping` | `player_impact_analyzer.py:498-678` | **B** | 5-pass heuristic that maps upstream feature names to SpinType ints; mechanic inference that differs by machine |
| `_resolve_bonus_feature` | `player_impact_analyzer.py:681-741` | **B** | BCM bonus-feature pairing via config → heuristic → none; reads `bcm_pairings.json` (per-machine) + `PAID_NORMAL_FEATURES` (heuristic constant) |
| `_load_bcm_pairings` | `player_impact_analyzer.py:441-495` | **C** | Reads `configs/bcm_pairings.json`; data is per-machine config, loading code is glue |
| `classify_volatility` | `aggregator.py` | A | RTP distribution math; universal |
| `classify_experience_archetype` | `aggregator.py` | A | Threshold classification; universal |
| `build_multiplier_bucket_rows` | `aggregator.py` | A | Bucket math; universal |
| `evaluate_guideline_comparison` | `aggregator.py` | A | Reads `classic_slots_guideline_rules.json`; applies universal thresholds |
| `_compute_bonus_correction` | `parser.py` (re-exported) | **B** | BCM correction math — estimates RTP from truncated collect cycles |
| `_compute_nf_correction` | `parser.py` (re-exported) | **B** | NewFreespin correction; mechanic-specific |
| Bankruptcy finalize | `_BankruptcyStreamAccumulator.finalize` + `compute_bankruptcy_percentiles` | `aggregator.py` | A | Percentile math over session windows; universal |

### Stage 3: stash pattern — data handoff to feature plugins (A)

After the summary dict is assembled, PIA writes stash keys (`_bankruptcy_rows`,
`_collect_mechanic_data`, `_bonus_chain_dynamics_data`, `_upstream_feature_breakdown_data`,
`_multiplier_profile_data`, `_reel_marginal_by_spin_type_data`, `_mechanism_registry`)
into the summary dict. This handoff is pure data plumbing — no mechanic logic.
Tag: **A** (the stash keys are A; the values they carry may have been produced by B).

### Stage 4: feature plugin emit loop (currently A only)

Located in `player_impact_analyzer.py:4437-4754` (topo-sort + emit loop).

| Step | Code location | A/B/C | Justification |
|---|---|---|---|
| Load manifests | `_c1_load_manifest`, `resolve_inheritance`, `resolve_per_mode` | A | Plumbing to read which features apply |
| Topo-sort | `topo_sort.topological_sort` | A | Pure dependency ordering; no mechanic knowledge |
| `MechanismRegistry.build()` | `mechanism_registry.py` | A (base-excluded) | Detection logic of jackpot/freespin/scatter; currently outside closure but in base-excluded plugin. Under the play-type refactor this would become a play-type classifier |
| `PipelineContext` construction | `pipeline_context.py` | A | Immutable data bag; universal |
| Feature emit loop | `_feature.emit(...)` × 9 plugins | A (each plugin is base-excluded) | The 9 existing plugins are DISPLAY features (see §3) |

### Stage 5: current 9 feature plugins — all DISPLAY features, all base-excluded

The 9 plugins that ship today are all classified **A** under the play-type lens.
They compute display metrics (payouts by spin type, reel distributions, multiplier
profile, etc.) that are universal across play-types. They are NOT mechanic logic.

| Plugin | FEATURE_ID | File | Current A/B/C (play-type lens) |
|---|---|---|---|
| PayoutsBySpinType | `payouts_by_spin_type` | `features/payouts_by_spin_type.py` | A (display aggregation) |
| ReelMarginalBySpinType | `reel_marginal_by_spin_type` | `features/reel_marginal_by_spin_type.py` | A (symbol distribution by ST) |
| BankruptcySimulation | `bankruptcy_simulation` | `features/bankruptcy_simulation.py` | A (session simulation math) |
| MultiplierProfile | `multiplier_profile` | `features/multiplier_profile.py` | A (return-bucket histogram) |
| MultiplierWild | `multiplier_wild` | `features/multiplier_wild.py` | A (wild-multiplier surface) |
| MachineMechanics | `machine_mechanics` | `features/machine_mechanics.py` | A (detection-result display; reads MechanismRegistry output) |
| UpstreamFeatureBreakdown | `upstream_feature_breakdown` | `features/upstream_feature_breakdown.py` | A (renders pre-computed feature tally) |
| CollectMechanic | `collect_mechanic` | `features/collect_mechanic.py` | A (BCM stats display; reads pre-computed cycle data) |
| BonusChainDynamics | `bonus_chain_dynamics` | `features/bonus_chain_dynamics.py` | A (chain histogram display) |

All 9 are currently base-excluded (each has its own hash, does not flip
`compute_base_analyzer_version()`). They are declared per-machine via
`slot_designer/configs/machine_manifests/M*.json`. The 420-manifest set
lists all 9 for nearly every machine — meaning today these are effectively
fleet-universal, not per-play-type.

---

## §3 A/B/C classification table — mechanic-bearing modules

This is the centerpiece for the W2 designer: exactly which code is B
(trapped in shared base, must become a play-type plugin).

### `fresh_slotlab/round_classification.py` (455 lines, entirely in `_CLOSURE_FILES`)

| Function | Lines | A/B/C | Justification |
|---|---|---|---|
| `is_paid_round` | `104-115` | A | Universal predicate: `CostCredits > 0`; the same semantic applies on every observed machine |
| `get_collect_count` | `118-130` | **B** | BCM-family only: reads `CollectCount` field; returns `None` on machines without it; part of BCM cycle mechanic |
| `is_wild_nudge_round` | `138-164` | **B** | Wild-nudge mechanic only: `ST=36 + ReMarks=move/nudge + cost=0`; verified on M279/M226/M149/M140/M26/M51/M256; returns `False` on all other machines |
| `extract_authoritative_pay_ids` | `172-189` | A | Universal: reads `PayoutIdToWinAmount` as-is; no mechanic-specific logic |
| `parse_payline_records` | `192-229` | A | Universal: parses `PayoutByPayline` string format; format is fleet-wide |
| `attribute_lines_to_pay_ids` | `232-303` | **B** | Mechanic-adjacent: 3-pass line→pay_id resolution handles idiosyncratic symbol-id namespaces (M120 "109"→"9", M139 "55"→"5", M279 "27905"→"104"); the passes themselves are universal logic but the problem they solve is machine-specific namespace drift |
| `detect_cycle_peak` | `311-375` | **B** | BCM mechanic: detects `CollectCount` reset pattern; only meaningful on BCM-family machines |
| `at_cycle_peak_indices` | `378-391` | **B** | BCM mechanic: indices of paid rounds at peak |
| `infer_bcm_target_spin_type` | `394-455` | **B** | BCM mechanic: observes which SpinType fires after cc=peak |

Summary for `round_classification.py`: 6 of 9 functions are B; 3 are A.
The entire module is in `_CLOSURE_FILES` — any change to B functions
flips `base_hash` for the whole fleet.

### `fresh_slotlab/round_win.py` (593 lines, entirely in `_CLOSURE_FILES`)

| Function / Class | Lines | A/B/C | Justification |
|---|---|---|---|
| `is_paid_round` | `50-66` | A | Universal: same `CostCredits > 0` predicate |
| `extract_trigger_pay_ids_default` | `74-99` | A | Universal: win==0 keys from `PayoutIdToWinAmount`; default extraction applied on all machines |
| `RoundWinRule` (ABC) | `102-161` | A | Base class / protocol; pure abstraction |
| `SettlementWinAmountRule` | `163-227` | **B** | TopDollar-selector mechanic: handles ST=14 phantom + ST=15 settlement semantics (M12/M15/M90/M132); no relevance to non-selector machines |
| `SynthesizePayIdRule` | `230-342` | **B** | Attribution synthesis for bonus rounds missing `PayoutIdToWinAmount`; mechanic-specific for machines where upstream doesn't surface per-round pay_ids |
| `BCMCycleAnchorRule` | `345-419` | **B** | BCM-family mechanic: synthesizes trigger anchor from `CollectCount==peak` signal |
| `RULE_REGISTRY` | `423-427` | A | Dispatch table; pure registry plumbing |
| `extract_round_win` | `430-448` | A | Rule dispatcher; the dispatch logic is universal; the rules it dispatches to are B |
| `extract_round_payouts` | `451-478` | A | Same — universal dispatcher |
| `extract_round_trigger_anchor` | `481-521` | A | Same — universal dispatcher; merges default + rule contributions |
| `round_has_credited_win` | `524-554` | A | Universal: "does this round's credit belong to pay_ids already?" gate |
| `load_rules_for_machine` | `557-592` | **C** | Config-driven loader: reads `configs/machine_round_win_rules.json`; the function is loader glue; the config data is per-machine |

Summary for `round_win.py`: 3 concrete rule classes are B; the 3-class
`RULE_REGISTRY` map and dispatcher functions are A; `load_rules_for_machine`
is config glue (C). The rule classes (SettlementWinAmountRule,
SynthesizePayIdRule, BCMCycleAnchorRule) are the primary B carve candidates
because they encode mechanic-specific win semantics for TopDollar-selector,
unattributed-bonus, and BCM families respectively.

### `fresh_slotlab/trigger_sessions.py` (361 lines, entirely in `_CLOSURE_FILES`)

| Function | Lines | A/B/C | Justification |
|---|---|---|---|
| `is_new_trigger_remark` | `96-111` | **B** | Mechanic: detects "Trigger" prefix in ReMarks; specific to machines using the Type 1 trigger-session pattern (M12/M15/M90/M132/M32/M6/M39...) |
| Back-compat aliases | `117-119` | A | Re-exports only |
| `_to_float_or_zero` | `122-128` | A | Pure arithmetic |
| `compute_trigger_sessions` | `131-360` | **B** | Entire function is mechanic logic: detects two trigger-session families (Type 1 last_non_none, Type 2 sum_all), manages session open/close semantics, applies double-count filter; this function's behavior differs fundamentally by machine mechanic (selector vs wheel vs freespin-accumulate). The `round_win_rules` param allows per-machine override injection. |

Summary for `trigger_sessions.py`: `compute_trigger_sessions` (230 lines)
is entirely B. It is the single largest B function in the fleet.

### `fresh_slotlab/player_impact_analyzer.py` — B functions still in the monolith

Even after the Phase 6 unbundle, the following significant B-class functions
remain in PIA proper (and therefore in `_CLOSURE_FILES`):

| Function | Lines | A/B/C | Justification |
|---|---|---|---|
| `_infer_feature_spin_type_mapping` | `498-678` | **B** | 5-pass heuristic to bind feature names → SpinType ints; its 5 passes encode observations from specific machine families (M15/M102/M273/M272/M275); editing it for a new machine changes base_hash |
| `_resolve_bonus_feature` | `681-741` | **B** | BCM bonus-feature pairing; reads bcm_pairings.json + applies PAID_NORMAL_FEATURES exclusion |
| `_load_bcm_pairings` | `441-495` | C/B (loader+B) | Loading glue (C) + parsing logic that handles v1/v2 schema differences (B) |
| `PAID_NORMAL_FEATURES` | `426-431` | **B** | Hard-coded set of BCM-normal feature names; machine-family knowledge embedded in base |
| CostCredits-reliability probe | inline `parser.py` | **B** | Detects LockReSpin-style machines (M10/M23/M131/M133) by sampling first 200 rounds; mechanic-detection embedded in the universal parse loop |
| `ci_halfwidth_pp` | `765-774` | A | CI math |
| `safe_div` | `849-850` | A | Arithmetic |
| `append_jsonl` | `853-858` | A | I/O primitive |
| `compute_analyzer_version` | `926-945` | A | Source hash |
| `main()` accumulation math | ~3500-3700 | A | Sum, average, CI calculations |
| Summary dict assembly | ~3800-4200 | A (structure) + **B** (fields derived from B stages) | The dict literal is A; values like `collect_robots_seen_total`, `all_cycle_peaks`, BCM-correction fields are produced by B stages |

---

## §4 The base/plugin boundary today and how plugins plug in

### Current base: what `_CLOSURE_FILES` pins (all change → fleet-wide re-flag)

```
fresh_slotlab/player_impact_analyzer.py       ← contains B functions (§3 above)
fresh_slotlab/analyzer/core/parser.py         ← contains parse_chunk_response with B embedded
fresh_slotlab/round_classification.py         ← majority B
fresh_slotlab/round_win.py                    ← 3 rule classes are B
fresh_slotlab/trigger_sessions.py             ← compute_trigger_sessions is B
fresh_slotlab/analyzer/core/aggregator.py     ← A (math only)
fresh_slotlab/analyzer/core/base_pipeline.py  ← A (HTTP/sampling)
fresh_slotlab/analyzer/core/writer.py         ← A (file I/O)
fresh_slotlab/analyzer/core/_utils.py         ← A (arithmetic helpers)
fresh_slotlab/analyzer/versioning.py          ← A (hash composition)
fresh_slotlab/analyzer/feature_registry.py    ← A (registry plumbing)
fresh_slotlab/analyzer/features/_base.py      ← A (ABC definition)
fresh_slotlab/analyzer/features/__init__.py   ← A (empty init)
fresh_slotlab/analyzer/manifest_loader.py     ← A (manifest I/O)
fresh_slotlab/analyzer/mechanism_registry.py  ← A (base-excluded in versioning, but in _CLOSURE_FILES)
fresh_slotlab/analyzer/parse_state.py         ← A (data container)
fresh_slotlab/analyzer/pipeline_context.py    ← A (frozen dataclass)
fresh_slotlab/analyzer/rtp_integrity.py       ← A (validator)
fresh_slotlab/analyzer/topo_sort.py           ← A (dependency ordering)
fresh_slotlab/chunk_index.py                  ← A (sidecar management)
fresh_slotlab/machine_md5.py                  ← A (md5 lookup)
fresh_slotlab/rawdata_index.py                ← A (index management)
fresh_slotlab/sampler.py                      ← A (CI / t-critical)
```

Note on `mechanism_registry.py`: per its docstring ("outside core/ so changes
do NOT flip compute_base_analyzer_version()") it was INTENDED to be
base-excluded, but it IS listed in `_CLOSURE_FILES` at
`versioning.py:130`. This is an inconsistency — the docstring claim is
wrong relative to the actual `_CLOSURE_FILES` set. Changes to
`MechanismRegistry` DO flip `base_hash`. Flagged as an open question
(see §6 Q5).

### How the 9 display-feature plugins plug in (the pattern play-type plugins will reuse)

```
1. Plugin module defines class subclassing AnalyzerFeature ABC (_base.py)
2. Module top calls register(MyFeature()) → appends to feature_registry.ALL_FEATURES
3. main() imports all 9 plugin modules (lines 4441-4449) → triggers register()
4. _c1_load_manifest(machine, _DEFAULT_MANIFEST_ROOT) loads M*.json
   → resolve_inheritance() → resolve_per_mode(mode)
   → manifest["analyzer_features"] = [list of FEATURE_ID strings]
5. get_features_for_machine(machine, manifest) → filters ALL_FEATURES by manifest list
6. topological_sort(machine_features) → ordered by REQUIRES graph
7. for feature in sorted_features:
       check DECLARED_DEPS keys present in summary
       feature.emit(feature_accs[feature.FEATURE_ID], summary, ctx)
8. compute_effective_analyzer_version():
       base_hash = sha256 of _CLOSURE_FILES (sorted, CRLF-normalized)
       for fid in sorted(machine_features):
           h.update(fid + "=" + sha256(plugin_source_file))
       h.update("mode=" + str(mode))
       → 12-hex effective_analyzer_version stamped in summary
```

The stash pattern (B-derived data → `summary["_key"]` → plugin `emit()` reads it):
- `_bankruptcy_rows` → `BankruptcySimulation.emit()`
- `_collect_mechanic_data` → `CollectMechanic.emit()`
- `_bonus_chain_dynamics_data` → `BonusChainDynamics.emit()`
- `_upstream_feature_breakdown_data` → `UpstreamFeatureBreakdown.emit()`
- `_multiplier_profile_data` → `MultiplierProfile.emit()`
- `_reel_marginal_by_spin_type_data` → `ReelMarginalBySpinType.emit()`
- `_mechanism_registry` → `MachineMechanics.emit()`

The play-type refactor will reuse the same protocol:
`AnalyzerFeature` ABC + `register()` + manifest → `get_features_for_machine()` →
topo-sorted `emit()` + effective hash composition.

### Config files that carry per-machine mechanic data (C)

| File | Role | How consumed |
|---|---|---|
| `configs/machine_round_win_rules.json` | Per-machine rule list (type + params + applies_to) | `round_win.load_rules_for_machine()` at `main():4275-4283` |
| `configs/bcm_pairings.json` | Per-(machine,mode) BCM bonus-feature name | `_load_bcm_pairings()` at `player_impact_analyzer.py:441` |
| `slot_designer/configs/machine_manifests/M*.json` | Per-machine feature list + spin_type_convention + rtp_integrity_contract | `manifest_loader.load_manifest()` |
| `configs/machines.json` | Fleet registry with md5 fingerprints | `machine_md5.lookup_machine_md5()` |

The `machine_round_win_rules.json` and `bcm_pairings.json` are the primary
per-machine config stores for mechanic-specific behavior today. Under the
play-type refactor, rule selection would be automatic (from rawdata) rather
than manually maintained.

---

## §5 Shared vs per-X boundary table

| File / Function | Scope | Consumers |
|---|---|---|
| `fresh_slotlab/round_classification.py` (all) | fleet-shared base (in `_CLOSURE_FILES`) | `parser.py:parse_chunk_response`; `scripts/infer_paytable.py`; `scripts/infer_bcm_pairing.py` |
| `fresh_slotlab/round_win.py` (all) | fleet-shared base (in `_CLOSURE_FILES`) | `parser.py:parse_chunk_response`; `trigger_sessions.py` |
| `fresh_slotlab/trigger_sessions.py` (all) | fleet-shared base (in `_CLOSURE_FILES`) | `parser.py:parse_chunk_response` |
| `fresh_slotlab/analyzer/core/parser.py:parse_chunk_response` | fleet-shared base | `main()` live + cache loops; `_batch_gen_worker.run_analyzer_job` |
| `fresh_slotlab/player_impact_analyzer.py:main()` | fleet-shared orchestrator | spawned by `RunManager.start_run`; in-process by `_run_generate_report`; subprocess by `_batch_gen_worker` |
| `configs/machine_round_win_rules.json` | per-machine config (12 rules, 2 types, sparse coverage) | `load_rules_for_machine()` |
| `configs/bcm_pairings.json` | per-machine config | `_load_bcm_pairings()` |
| `slot_designer/configs/machine_manifests/M*.json` | per-machine config (421 files) | `manifest_loader.load_manifest()` |
| `fresh_slotlab/analyzer/features/*.py` (9 plugins) | base-excluded per-machine-declared (but effectively all machines) | topo-sorted emit loop in `main()` |
| `fresh_slotlab/analyzer/core/{aggregator,base_pipeline,writer,_utils}.py` | fleet-shared base | `main()`, `parse_chunk_response` |
| `fresh_slotlab/chunk_index.py` | fleet-shared primitive | analyzer write hooks; backend `_classify_chunks`; virtual emitter |
| `fresh_slotlab/machine_md5.py` | fleet-shared | `player_impact_analyzer.py:_lookup_machine_md5` |
| `src/web_console/backend/app.py:create_app` | fleet-shared (prod + virtual) | `src/web_console/backend/main.py`; `slot_designer/core/backend/virtual_app.py` |
| `slot_designer/core/backend/virtual_analyzer.py` | virtual-only | virtual RunManager subprocess |
| `slot_designer/configs/machines_virtual.json` | virtual-only registry | virtual_app, virtual_analyzer |

---

## §6 Integration points the refactor must not break

1. **Web console routes / backend** (`src/web_console/backend/app.py`):
   - `POST /api/runs` → `RunManager.start_run` → spawns analyzer subprocess.
     The subprocess interface is `--machine / --rtp-mode / --from-cache / ...` CLI args.
     Play-type plugins run inside the analyzer; the CLI surface does not change.
   - `POST /api/rawdata/{m}/generate-report` → `_run_generate_report` calls `pia.main()`
     in-process. The monkey-patching of `pia.post_json` + `sys.argv` + `os._exit`
     at `app.py:6873-6875` must remain stable across the refactor.
   - `GET /api/runs/{rid}/report` → reads `player_impact_summary.json`.
     Schema contract with `pure.js:extractMetricCards` is the critical invariant.
     Play-type plugin output keys that ARE new schema additions must have fallback rules
     (backward compat with old reports on disk).

2. **Virtual analyzer delegate** (`slot_designer/core/backend/virtual_analyzer.py`):
   - `_delegate_to_real_analyzer:652-687` calls `[python, REAL_ANALYZER, --from-cache, ...]`
     passing virtual rawdata chunks. The real analyzer's `parse_chunk_response` must
     continue to process virtual chunks whose SpinType/field structure may differ from
     production machines.
   - `_patch_summary_md5_tags:506-558` patches md5 fields post-delegate. Must still
     work if summary schema gains new top-level keys.

3. **Sampling / chunk-index sidecar**:
   - `chunk_index.py:update_chunk_entry` and `rawdata_index.py:update_entry` are called
     by `_save_chunk_cache` inside every chunk write. The sidecar schema (`_chunks.json`
     v2 with `by_md5` inverted index) is a hard dependency for `select_replay_chunks_by_md5`.

4. **Honest staleness model** (`versioning.py:compute_effective_version_for_machine`):
   - `base_hash` = sha256 of `_CLOSURE_FILES` (explicit list, version-controlled).
     The refactor moves B functions OUT of the closure → `_CLOSURE_FILES` shrinks →
     `base_hash` changes once → all existing reports re-flag once.
   - Play-type plugins become new entries in the hash composition:
     `effective(m,mode) = base ⊕ {play-type plugin hashes for m} ⊕ per-machine-payid-hash ⊕ mode`
   - The manifests currently have 421 JSON files declaring the 9 display features.
     Per DIRECTION §4 these 421 manifests are DISCARDED (greenfield). Detection becomes
     automatic. If the refactor is greenfield, the manifest_loader / feature_registry /
     topo_sort / pipeline_context machinery can be reused or replaced.

5. **RTP integrity gate** (`fresh_slotlab/analyzer/rtp_integrity.py`):
   - Layer 4 reads `manifest["rtp_integrity_contract"]["required_attribution_anchors"]`.
     If manifests are discarded, this gate needs a new source for its contract (derived
     from the auto-detected play-type set).

---

## §7 Stale items from prior map (2026-05-15)

The prior `session_artifacts/_arch/01_pipeline_map.md` was written before the
Phase 5/6 unbundle completed. The following items are now stale:

1. **`parse_chunk_response` location**: Prior map says "Lines `2354-3961`" in
   `player_impact_analyzer.py`. STALE. As of P2-B1b it is in
   `fresh_slotlab/analyzer/core/parser.py` and re-exported from PIA. PIA lines
   `2354+` no longer exist at that offset.

2. **`collect_feature_match_warning` and `build_cycle_observation` in PIA**:
   Prior map shows these in PIA. STALE. As of Phase C5 they live in
   `fresh_slotlab/analyzer/features/collect_mechanic.py` (moved per C5 carve).

3. **`main()` at `4211-8159`**: Prior map lines will be wrong after the P2-B1b
   carve reduced PIA. Current PIA is 5135 lines; `main()` starts at `965`.

4. **`open questions §5 Q4` (reporter.py orphaned)**: Still valid. `reporter.py`
   is confirmed dead (no production callers).

---

## §8 Open questions (observation only, no design proposals)

**Q1** — `_infer_feature_spin_type_mapping` (5 passes, `player_impact_analyzer.py:498`)
stays in PIA because it has a "second consumer on the bonus-chain path" (per
`player_impact_analyzer.py:4220-4225` comment). The actual second consumer is
not named in the comment. The function's output (`feature_to_spin_type`,
`spin_type_to_feature`, `ambiguous_mapped`) feeds the `_upstream_feature_breakdown_data`
stash. Cannot determine from observation which code path outside of that stash also
uses it — the claim that there is a second consumer needs verification.

**Q2** — `parse_chunk_response` (in `parser.py`) currently embeds the
CostCredits-reliability probe (LockReSpin detection) as an inline block. The
comment names specific machines (M10/M23/M131/M133). This is B-class logic
inside the universal parse function. If play-type plugins run AFTER parsing, this
probe either needs to move to a pre-parse stage or the parse function needs a
hook for mechanic-specific probes.

**Q3** — `BCMCycleAnchorRule` in `round_win.py` and `get_collect_count`,
`detect_cycle_peak`, `at_cycle_peak_indices`, `infer_bcm_target_spin_type` in
`round_classification.py` are all BCM-mechanic code. But they are called
from inside `parse_chunk_response` (which is universal). If the BCM functions
are moved to a play-type plugin, `parse_chunk_response` cannot call them
directly (the parse function runs before play-type dispatch). The current
call pattern (`detect_cycle_peak` per robot inside parse → passes `cycle_peak`
into `BCMCycleAnchorRule` via `ctx`) is tightly coupled to the parse loop
ordering. How the play-type refactor decouples this is unclear from current
code structure.

**Q4** — `compute_trigger_sessions` is called per-robot inside `parse_chunk_response`.
Trigger-session detection is B (mechanic-specific), but it runs in the middle of
the chunk parse (which produces the per-chunk output dict). If trigger-session
detection becomes a play-type plugin, it needs a per-robot hook in the parse loop
or the parse loop itself must be restructured. Currently there is no such hook.

**Q5** — `fresh_slotlab/analyzer/mechanism_registry.py` docstring says "changes do
NOT flip `compute_base_analyzer_version()`" but `_CLOSURE_FILES` in `versioning.py:130`
explicitly lists it. These two claims are contradictory. If `MechanismRegistry`
changes, `base_hash` DOES change today.

**Q6** — The play-type refactor DIRECTION §4 says "the current 420 machine_manifests
are DISCARDED (greenfield)". But the current `AnalyzerFeature` emit protocol
(`manifest_loader`, `feature_registry`, `topo_sort`, `pipeline_context`) is designed
around those manifests. If manifests are discarded, it is unclear whether the emit
protocol is retained (with auto-detected play-type replacing the manifest list) or
also discarded. This is a design decision for the W2 designer, but the mapper
notes that the machinery is tightly coupled to `_c1_manifest` (constructed at
`player_impact_analyzer.py:4501-4512` from `_DEFAULT_MANIFEST_ROOT`).

**Q7** — `configs/bcm_pairings.json` is loaded by `_load_bcm_pairings()` to supply
the (machine, mode) → bonus_feature_name mapping. This file has 159 BCM machines
in it. Under the play-type refactor, this per-machine config role would be played
by auto-detection from rawdata (per DIRECTION §3). The question is whether the
existing `BCMCycleAnchorRule` mechanics (embedded in base) provide enough signal
for auto-detection, or whether the auto-detection requires new rawdata inspection.
Cannot determine from code alone.

**Q8** — `PAID_NORMAL_FEATURES` (`player_impact_analyzer.py:426`) is a hard-coded
frozenset of BCM-normal feature names (`{"NormalCollectionSpin", "BingoCollectionNormalSpin",
"ReelCollectionNormal", "HalloweenReelCollectionNormal"}`). This is B-class
knowledge (BCM-family feature naming conventions) embedded in base. The comment says
"mirrored in `scripts/infer_bcm_pairing.py` — keep in sync", which implies it is
duplicated.

---

## §9 Quantitative summary of B-class code trapped in base

| Module | Total lines | Lines classified B | % in base that is B |
|---|---|---|---|
| `round_classification.py` | 455 | ~290 (get_collect_count + is_wild_nudge_round + attribute_lines_to_pay_ids + detect_cycle_peak + at_cycle_peak_indices + infer_bcm_target_spin_type) | ~64% |
| `round_win.py` | 593 | ~220 (SettlementWinAmountRule + SynthesizePayIdRule + BCMCycleAnchorRule) | ~37% |
| `trigger_sessions.py` | 361 | ~250 (compute_trigger_sessions + is_new_trigger_remark) | ~70% |
| `player_impact_analyzer.py` (B functions) | 5135 | ~280 (_infer_feature_spin_type_mapping + _resolve_bonus_feature + _load_bcm_pairings + PAID_NORMAL_FEATURES) | ~5% of PIA (but disproportionate fleet impact: every edit re-flags fleet) |
| `analyzer/core/parser.py` (embedded B) | ~1900 | ~30 (CostCredits reliability probe) | ~2% |

Total B-class code in base: approximately 1070 lines across 4 files.
The B code is concentrated in three modules: `round_classification.py`,
`round_win.py`, `trigger_sessions.py` — which are the primary carve candidates
for the play-type refactor.

---

End of pipeline map.

Prior map `session_artifacts/_arch/01_pipeline_map.md` remains valid for
the backend / frontend / virtual-console / reuse audit sections (§2 L4-L6,
§3, §4, §5 Q1-Q8 except Q4 which is now resolved by the Phase-6 unbundle).
This document supersedes that map's §2 L1-L3 (parse/transform/classify layers)
for the play-type refactor context.
