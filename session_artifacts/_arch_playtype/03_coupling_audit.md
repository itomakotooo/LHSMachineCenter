# Coupling / Blast-Radius Audit — Wave 1 (Play-Type Re-Architecture)

Auditor: arch-coupling-auditor (Wave 1, parallel with arch-mapper + arch-taxonomist).
Date: 2026-06-01.
Direction: `session_artifacts/_arch_playtype/DIRECTION.md`.
Prior audit reference: `session_artifacts/_arch/03_coupling_audit.md` (2026-05-15, pre-Phase-6).

> **Mission**: quantify the BLAST RADIUS of the current shared analyzer code — prove and size the exact
> problem this refactor exists to solve. All numbers are ground-truthed from grep, file inspection, and
> git log against the live `collab/dev` tree. Prior audit numbers are verified against current code and
> staleness is flagged.

---

## §1 Scope

**Live tree only** (ignoring `.claude/worktrees/*` per DIRECTION §9 grounding).

Directories audited:

- `fresh_slotlab/` — the production analyzer (monolith + 3 core mechanic modules + 9 display plugins +
  supporting infrastructure).
- `fresh_slotlab/analyzer/` — post-Phase-6 carved modules: `core/` (parser, pipeline, aggregator, writer),
  `features/` (9 display plugins), `versioning.py`, `feature_registry.py`, `manifest_loader.py`,
  `mechanism_registry.py`, `rtp_integrity.py`.
- `slot_designer/configs/machine_manifests/` — 420 per-machine manifest JSON files.
- `configs/machines.json` — live fleet registry (422 entries).
- `configs/machine_round_win_rules.json` — per-machine rule overrides (2 rule definitions).
- `configs/bcm_pairings.json` — BCM bonus-feature pairings (30 machines).

**Post-Phase-6 delta from prior audit**: The monolith shrunk from 8,176 LoC (prior audit, 2026-05-15) to
5,135 LoC today. `parse_chunk_response` and the 6 display feature build functions were carved into
`analyzer/core/parser.py` (2,405 LoC) and the 9 `features/*.py` plugins. The THREE CORE MECHANIC MODULES
(`round_classification.py`, `round_win.py`, `trigger_sessions.py`) were NOT carved — they remain in
`_CLOSURE_FILES` and therefore in `base_hash`. This is the fundamental coupling this refactor addresses.

---

## §2 Base-hash closure inventory

### 2.1 What `_CLOSURE_FILES` contains

`fresh_slotlab/analyzer/versioning.py` line 114 defines the authoritative explicit closure set. The 25
files hashed in sorted order to produce `base_hash` (with CRLF normalization per FIX-2):

| File | Size (bytes) | Category |
|------|-------------|----------|
| `fresh_slotlab/analyzer/__init__.py` | 761 | infrastructure |
| `fresh_slotlab/analyzer/core/__init__.py` | 1,729 | infrastructure |
| `fresh_slotlab/analyzer/core/_utils.py` | 9,978 | infrastructure |
| `fresh_slotlab/analyzer/core/aggregator.py` | 21,548 | universal math (bankruptcy, volatility, guideline) |
| `fresh_slotlab/analyzer/core/base_pipeline.py` | 27,907 | infrastructure (sampling, HTTP) |
| `fresh_slotlab/analyzer/core/parser.py` | **121,850** | **MECHANIC: parse_chunk_response, all SpinType/CostCredits logic** |
| `fresh_slotlab/analyzer/core/writer.py` | 9,393 | infrastructure (file write) |
| `fresh_slotlab/analyzer/feature_registry.py` | 6,205 | infrastructure (plugin registry) |
| `fresh_slotlab/analyzer/features/__init__.py` | 283 | infrastructure |
| `fresh_slotlab/analyzer/features/_base.py` | 11,812 | infrastructure (AnalyzerFeature ABC) |
| `fresh_slotlab/analyzer/manifest_loader.py` | 37,946 | infrastructure (manifest resolve) |
| `fresh_slotlab/analyzer/mechanism_registry.py` | 13,436 | **MECHANIC: machine mechanism detection** |
| `fresh_slotlab/analyzer/parse_state.py` | 3,506 | infrastructure |
| `fresh_slotlab/analyzer/pipeline_context.py` | 4,460 | infrastructure |
| `fresh_slotlab/analyzer/rtp_integrity.py` | 43,959 | universal math (RTP invariant gate) |
| `fresh_slotlab/analyzer/topo_sort.py` | 9,123 | infrastructure (plugin dependency ordering) |
| `fresh_slotlab/analyzer/versioning.py` | 18,550 | infrastructure (hash composition) |
| `fresh_slotlab/chunk_index.py` | 40,577 | infrastructure (cache sidecar) |
| `fresh_slotlab/machine_md5.py` | 4,064 | infrastructure (real-fleet md5 lookup) |
| `fresh_slotlab/player_impact_analyzer.py` | **271,957** | **MECHANIC: orchestration, BCM logic, bonus feature resolution** |
| `fresh_slotlab/rawdata_index.py` | 17,710 | infrastructure |
| `fresh_slotlab/round_classification.py` | **18,320** | **MECHANIC: paid/bonus classification, BCM cycle detection** |
| `fresh_slotlab/round_win.py` | **23,279** | **MECHANIC: win extraction, payid attribution, rule engine** |
| `fresh_slotlab/sampler.py` | 14,576 | infrastructure (t_critical_95, session_halfwidth_pp — imported by PIA) |
| `fresh_slotlab/trigger_sessions.py` | **17,261** | **MECHANIC: bonus trigger session detection** |
| **Total** | **750,190 bytes (732 KB)** | |

**Mechanic code in base**: `parser.py` (122 KB) + `round_classification.py` (18 KB) + `round_win.py`
(23 KB) + `trigger_sessions.py` (17 KB) + mechanic portions of `player_impact_analyzer.py` + `mechanism_registry.py` (13 KB) = approximately 215 KB of mechanic logic locked into `base_hash`. Any byte
change to any of these flips `base_hash` → every machine's `effective_analyzer_version` changes → **all
420 machines re-flag**.

### 2.2 What is excluded from base (the 9 display feature plugins)

`R-4 exclusion`: the files in `feature_registry.ALL_FEATURES` are NOT hashed into `base_hash`. Each is
hashed independently via `f.compute_hash()` and folded into `effective_analyzer_version` only for
machines whose manifest declares that feature ID.

The 9 registered display plugins (base-excluded):

| Plugin file | Size (bytes) | FEATURE_ID |
|-------------|-------------|-----------|
| `features/payouts_by_spin_type.py` | 23,926 | `payouts_by_spin_type` |
| `features/reel_marginal_by_spin_type.py` | 13,350 | `reel_marginal_by_spin_type` |
| `features/bankruptcy_simulation.py` | 15,677 | `bankruptcy_simulation` |
| `features/multiplier_profile.py` | 11,125 | `multiplier_profile` |
| `features/multiplier_wild.py` | 13,857 | `multiplier_wild` |
| `features/machine_mechanics.py` | 22,629 | `machine_mechanics` |
| `features/upstream_feature_breakdown.py` | 38,618 | `upstream_feature_breakdown` |
| `features/collect_mechanic.py` | 29,881 | `collect_mechanic` |
| `features/bonus_chain_dynamics.py` | 30,156 | `bonus_chain_dynamics` |

### 2.3 The two co-existing version stamps in each report

Each `player_impact_summary.json` carries two version fields:

1. **`summary.analyzer_version`** — SHA256 of `player_impact_analyzer.py` source bytes only (the legacy,
   intentionally broad stamp). Computed by `compute_analyzer_version()` at `player_impact_analyzer.py:926`.
   This hashes ONLY the monolith, not the full closure.

2. **`summary.effective_analyzer_version`** — 12-hex hash computed by `compute_effective_version_for_machine()`
   from `versioning.py`. Hashes all 25 `_CLOSURE_FILES` (base_hash) then folds in each machine's declared
   feature plugin hashes and mode. This is the post-Phase-3 mechanism for per-machine isolation at the
   DISPLAY axis.

**Important**: the backend staleness check (`/api/reports/stale-count`) uses `analyzer_version` (the legacy
field), not `effective_analyzer_version`. The newer `effective_analyzer_version` exists in the report JSON
but is not yet the primary staleness signal driving UI re-flag behavior. This means the display-axis
isolation of Phase-3 has NOT yet replaced the fleet-wide staleness signal in the backend.

---

## §3 Blast radius of shared mechanic code (the core problem)

### 3.1 Quantified invalidation table

| Change | Files affected | base_hash flips? | Machines re-flagged | (machine,mode) pairs re-flagged |
|--------|---------------|-----------------|--------------------|---------------------------------|
| Edit `round_classification.py` (any byte) | 1 file in closure | YES | **420 (all)** | **all cached** |
| Edit `round_win.py` (any byte) | 1 file in closure | YES | **420 (all)** | **all cached** |
| Edit `trigger_sessions.py` (any byte) | 1 file in closure | YES | **420 (all)** | **all cached** |
| Edit `analyzer/core/parser.py` (any byte) | 1 file in closure | YES | **420 (all)** | **all cached** |
| Edit `player_impact_analyzer.py` (any byte) | 1 file in closure | YES | **420 (all)** | **all cached** |
| Edit `mechanism_registry.py` (any byte) | 1 file in closure | YES | **420 (all)** | **all cached** |
| Edit `rtp_integrity.py` (any byte) | 1 file in closure | YES | **420 (all)** | **all cached** |
| Edit any other closure file | 1 file in closure | YES | **420 (all)** | **all cached** |
| Edit `features/payouts_by_spin_type.py` | base-EXCLUDED | no | 252 machines (all with 8-feature set) | ~252 × modes |
| Edit `features/multiplier_wild.py` | base-EXCLUDED | no | **1 machine** (M275 only) | M275 modes only |
| Edit any of the other 7 universal display plugins | base-EXCLUDED | no | 252 machines | ~252 × modes |
| Add new SpinType rule for ONE machine in `round_classification.py` | base file | YES | **420** | **all cached** |
| Fix M274 BCM attribution in `round_win.py` | base file | YES | **420** | **all cached** |
| Fix trigger session logic for WheelSelector in `trigger_sessions.py` | base file | YES | **420** | **all cached** |

**Fleet size at time of audit**: 422 entries in `configs/machines.json` (256 non-variant, 166 variant).
420 manifests in `slot_designer/configs/machine_manifests/`. 327 machines have cached rawdata in
`rawdata/`. 1,088 cached `(machine, mode)` pairs with rawdata on disk.

**Consequence**: under the current model, every mechanic fix (adding support for a new machine's SpinType
behavior, fixing a BCM cycle detection bug, fixing a trigger session attribution error) re-flags the
entire fleet. The only edits that scope properly to a subset of machines are edits to the 9 BASE-EXCLUDED
display feature plugins — but those plugins contain zero mechanic logic.

### 3.2 Git churn evidence — change likelihood × blast radius

| Module | Commits (total) | Commits (post 2026-04-01) | Blast radius | Product (churn × radius) |
|--------|----------------|--------------------------|--------------|--------------------------|
| `player_impact_analyzer.py` | 132 | 132 | 420 (all) | **MAXIMUM** |
| `trigger_sessions.py` | 8 | 8 | 420 (all) | Very high |
| `round_win.py` | 3 | 3 | 420 (all) | High |
| `round_classification.py` | 3 | 3 | 420 (all) | High |
| `analyzer/core/parser.py` | 4 | 4 | 420 (all) | High |
| Any display feature plugin | varies | varies | 252 (or 1 for `multiplier_wild`) | Scoped |

**Reading**: the player_impact_analyzer.py monolith has 132 commits — every one of those re-flagged all
420 machines. The three core mechanic modules (round_classification, round_win, trigger_sessions) had 14
total commits, each fleet-wide. The display plugins, once created, scope to 252 or 1 machine.

---

## §4 Contrast: what the target model must achieve

### 4.1 Current display-axis isolation (proven, working)

Edit `multiplier_wild.py` → only M275 re-flags. This is the isolation the play-type mechanic axis
must replicate, but for mechanic code.

Feature plugin usage across 420 manifests:

| Feature ID | Manifests declaring it | Machines re-flagged on edit |
|------------|----------------------|----------------------------|
| `payouts_by_spin_type` | 253 | 253 (252 non-variants + M275) |
| `reel_marginal_by_spin_type` | 253 | 253 |
| `bankruptcy_simulation` | 253 | 253 |
| `multiplier_profile` | 253 | 253 |
| `machine_mechanics` | 253 | 253 |
| `upstream_feature_breakdown` | 253 | 253 |
| `collect_mechanic` | 253 | 253 |
| `bonus_chain_dynamics` | 253 | 253 |
| `multiplier_wild` | **1** | **1** (M275 only) |

**Distribution**: 252 manifests carry all 8 universal features (identical effective version beyond base +
mode); 167 variants have no features declared directly (inherit parent's feature set at runtime via
`resolve_inheritance`); 1 machine (M275) adds `multiplier_wild` for a total of 9.

**The current display plugins do NOT achieve mechanic isolation** because:
- All 9 plugins are DISPLAY logic (building report blocks like `payouts_by_spin_type`, `collect_mechanic`
  summaries from already-parsed data).
- The PARSING of that data — which SpinType rounds count as paid, how BCM cycles are detected, how trigger
  session wins are attributed — lives in `parser.py`, `round_classification.py`, `trigger_sessions.py`,
  `round_win.py` inside `base_hash`.

### 4.2 Target isolation (play-type plugins on mechanic axis)

Under `effective(machine,mode) = base ⊕ {play-type plugin hashes} ⊕ per-machine-payid-config-hash ⊕ mode`:

| Hypothetical change | Current blast radius | Target blast radius |
|--------------------|---------------------|---------------------|
| Fix free-spin trigger attribution (currently in `trigger_sessions.py`) | 420 machines | Only machines with the free-spin play-type |
| Add BCM cycle peak detection fix (currently in `round_classification.py`) | 420 machines | Only machines with the BCM play-type |
| Fix TopDollar selector settlement rule (currently in `round_win.py`) | 420 machines | Only 13 TopDollar variant machines |
| Fix `is_wild_nudge_round` logic (currently in `round_classification.py`) | 420 machines | ~25 (machine,mode) pairs with wild-nudge mechanic |
| Fix M274's specific payid rule (currently in `configs/machine_round_win_rules.json`) | 1 machine today (config change) | 1 machine (per-machine-payid-config-hash scopes it) |

---

## §5 Hash composition map (current state)

```
REPORT STALENESS CHAIN — current model

[A] Edit any of 25 _CLOSURE_FILES
         |
         v
    compute_base_analyzer_version()          <- versioning.py:148
    (SHA256 over all 25 files, sorted, CRLF-normalized)
         |
         v
    compute_effective_analyzer_version()     <- versioning.py:345
    = SHA256(base_hash) then fold in feature hashes for this machine
         |
         v
    summary.effective_analyzer_version       <- player_impact_analyzer.py:3874
    (12-hex, per machine+mode)

[B] Edit player_impact_analyzer.py (any byte)   <- ALSO IN [A]
         |
         +-> compute_analyzer_version()      <- player_impact_analyzer.py:926
             (SHA256 of ONLY player_impact_analyzer.py source)
             |
             v
             summary.analyzer_version        <- player_impact_analyzer.py:3871
             (LEGACY: 12-hex, fleet-wide single value)

[C] Backend staleness signal
    /api/reports/stale-count compares:
      stale_analyzer: stored run.analyzer_version != compute_analyzer_version() [CURRENT ACTIVE SIGNAL]
      (effective_analyzer_version stored but NOT used in staleness check as of this audit)

[D] Feature plugin edit (base-EXCLUDED)
    Edit features/bonus_chain_dynamics.py
         |
         v
    f.compute_hash() changes for that plugin    <- features/_base.py: each feature hashes its own source
         |
         v
    compute_effective_analyzer_version() folds in the new hash
         ONLY for machines whose manifest lists 'bonus_chain_dynamics' in analyzer_features
         |
         v
    effective_analyzer_version changes for 252 machines only
    (but LEGACY analyzer_version is unchanged — no stale signal fires today)

[E] Per-machine-payid-config (TARGET model only — not yet implemented)
    Edit per-machine payid semantics (round_win rules, payid anchors)
         |
         v
    per-machine-payid-config-hash changes
         |
         v
    effective_analyzer_version changes for 1 machine only
```

**Staleness gap**: The `effective_analyzer_version` computation (closed-loop isolation per machine) was
built in Phase 3 and is written to every report summary. But the backend's ACTIVE staleness check still
uses the legacy `analyzer_version` (SHA256 of `player_impact_analyzer.py` only). This means:

- The per-machine isolation of display plugins IS captured in `effective_analyzer_version` in the JSON.
- The UI's "stale" badge uses `analyzer_version` — a fleet-wide signal that changes when the monolith changes.
- Two independent signals exist; the staleness UI is wired to only one of them (the broader one).

---

## §6 Silent dependencies inventory

### 6.1 Mechanic logic encoded in `parser.py` (base, 122 KB)

`parser.py` is the most mechanic-laden file in base. It contains:

- **`parse_chunk_response`** (the main parse loop, ~800 lines): calls `is_paid_round`,
  `is_wild_nudge_round`, `detect_cycle_peak`, `compute_trigger_sessions`, `extract_round_win`,
  `extract_round_payouts` — all from the shared mechanic modules.
- **SpinType-specific branches**: 13 direct ST number comparisons in the loop body (STs 0, 1, 3, 5, 13,
  14, 15, 136, 137, 273). ST=13 (LockReSpin) has a special `cost_credits_unreliable` bypass for machines
  M10/M23/M131/M133.
- **Per-machine mechanic accumulators**: `lock_lines_*`, `lock_symbols_*`, `jackpot_*`, `lock_reels_*`
  — all allocated unconditionally and populated when the corresponding upstream fields are present.
- **`_load_bcm_pairings()`** in `player_impact_analyzer.py:441`: reads `configs/bcm_pairings.json` (30
  machines) at runtime to drive BCM bonus-feature pairing. This is a SILENT DATA DEPENDENCY: editing
  `bcm_pairings.json` changes behavior for those 30 machines without flipping any code hash.
- **`_infer_feature_spin_type_mapping()`** at `player_impact_analyzer.py:498`: per-SpinType heuristic
  inference. Lives in the monolith, runs for every machine, contained in `base_hash`.
- **`_resolve_bonus_feature()`** at `player_impact_analyzer.py:681`: resolves BCM bonus feature per
  (machine, mode). Reads the bcm_pairings config. Also in `base_hash`.

### 6.2 `configs/bcm_pairings.json` — silent data dependency

30 machines are listed with per-mode bonus-feature pairings (e.g., M273, M227, M233, M237, M250, M274).
This config file is NOT in `_CLOSURE_FILES` and NOT in any hash. It is a pure RUNTIME data dependency:

- Editing it changes which bonus feature is attributed to BCM cycle events.
- No hash flip occurs — no stale signal fires.
- This is accidental coupling: configuration affecting 30 machines' attribution correctness has zero
  observability in the version model.

### 6.3 `configs/machine_round_win_rules.json` — similar silent dependency

2 rule definitions (`bcm_cycle_anchor_m274`, `topdollar_selector_settlement`) covering 13 machines
(M274 + 12 TopDollar variants). NOT in `_CLOSURE_FILES`. Not hashed.

- Editing the rule config changes win attribution for those 13 machines.
- No hash flip occurs.
- The ENGINE that reads and applies these rules (`round_win.py:load_rules_for_machine`) IS in base —
  so a bug fix to the engine re-flags 420; a config-only change to a per-machine rule has zero visibility.

### 6.4 Variant inheritance and feature resolution

167 variant manifests carry no `analyzer_features` directly. At runtime, `resolve_inheritance()` copies
the parent machine's feature list into the variant's merged manifest. This means:

- A variant's `effective_analyzer_version` is computed from the parent's feature set (correct behavior).
- BUT: editing a display plugin re-flags the parent machine AND all its variants together. M273 has 85
  variants — editing `bonus_chain_dynamics.py` re-flags all 86 (M273 + 85 variants).
- Under the target model, play-type plugins will work the same way: if M273 and its 85 variants share a
  play-type, editing that play-type's plugin re-flags all 86.

### 6.5 The `sampler.py` closure inclusion

`sampler.py` (14,576 bytes) is in `_CLOSURE_FILES` because `player_impact_analyzer.py` imports
`t_critical_95` and `session_halfwidth_pp` from it at module top. It is primarily a standalone sampling
script, but two functions from it are on the import path. Editing `sampler.py` (e.g., to fix the
standalone sampling CLI) flips `base_hash` → 420 machines re-flag. This is a COMPUTED coupling: the
two functions could in principle be extracted to a math-only module that `sampler.py` also imports,
breaking the coupling.

---

## §7 Version-model implications for the designer

### 7.1 What must move OUT of `base_hash`

The following code is mechanic-specific and should become play-type plugin content:

| Current location | Content | Play-type scope |
|-----------------|---------|----------------|
| `round_classification.py:is_paid_round` | universal paid/bonus classifier | Universal (NOT a candidate for per-play-type — every machine needs this) |
| `round_classification.py:is_wild_nudge_round` | wild-nudge round detection | ~25 (machine,mode) pairs — good plugin candidate |
| `round_classification.py:get_collect_count` | BCM collect counter | BCM-family (~25+ machines) — good plugin candidate |
| `round_classification.py:detect_cycle_peak` | BCM cycle detection | BCM-family — good plugin candidate |
| `round_classification.py:infer_bcm_target_spin_type` | BCM ST mapping | BCM-family — good plugin candidate |
| `round_win.py:RoundWinRule` ABC | rule framework | Universal (base) |
| `round_win.py:SettlementWinAmountRule` | TopDollar selector settlement logic | TopDollar family (13 machines) — good plugin candidate |
| `round_win.py:BCMCycleAnchorRule` | BCM anchor synthesis | BCM-family — good plugin candidate |
| `round_win.py:extract_round_win/extract_round_payouts` | universal win extraction dispatch | Universal (base) — shared win-attribution ENGINE |
| `trigger_sessions.py:compute_trigger_sessions` | Type 1 + Type 2 bonus trigger sessions | Multiple play-types (free-spin machines, selector machines) |
| `trigger_sessions.py:is_new_trigger_remark` | Type 1 trigger marker | Machines with "Trigger" ReMarks |
| `parser.py:parse_chunk_response` ST branches | per-ST analysis branches | Various play-types |
| `player_impact_analyzer.py:_load_bcm_pairings` | BCM config reader | BCM-family |
| `player_impact_analyzer.py:_resolve_bonus_feature` | BCM bonus feature resolver | BCM-family |
| `mechanism_registry.py:MechanismRegistry.build` | mechanism detection logic | All machines (but per-machine results) |

**IMPORTANT**: `is_paid_round` and the base `extract_round_win`/`extract_round_payouts` dispatch are
UNIVERSAL — they belong in base because every machine needs them. Only the MECHANIC-SPECIFIC extensions
(BCM detection, wild-nudge detection, trigger-session logic, TopDollar settlement rules) are play-type
plugin candidates.

### 7.2 Residual coupling risk: win-attribution engine vs per-machine payid config

The current `round_win.py:extract_round_win` is a UNIVERSAL dispatcher that:
1. Calls `load_rules_for_machine(machine_name)` to get per-machine rules.
2. Tries each rule's `extract_win()` in order.
3. Falls back to `r.get("WinCredits", 0)` if no rule fires.

**Risk**: the DISPATCHER ENGINE is in base. A bug fix to the dispatcher logic (e.g., the fallback
semantics, rule priority ordering) re-flags 420 machines, even though the fix may only matter for the 13
machines with special rules. Under the target model:

- The UNIVERSAL part (WinCredits fallback + rule dispatch skeleton) should stay in base.
- The PER-MACHINE RULE CLASSES (`SettlementWinAmountRule`, `BCMCycleAnchorRule`) should move to
  play-type plugins, so fixing a rule only re-flags the machines using that play-type.

**Risk 2**: per-machine payid config in `configs/machine_round_win_rules.json` is NOT hashed today.
Under the target model, `per-machine-payid-config-hash` must include this file (or the relevant rule
entry for that machine) so a config edit properly scopes to that machine. Otherwise a payid rule change
has no staleness signal at all.

### 7.3 `effective_analyzer_version` vs `analyzer_version` — the active staleness gap

The backend currently computes staleness from `analyzer_version` (SHA256 of `player_impact_analyzer.py`
only). `effective_analyzer_version` (the per-machine scoped signal) is written to every report but NOT
used by `/api/reports/stale-count`. The play-type refactor must:

1. Migrate the active staleness check from `analyzer_version` to `effective_analyzer_version`.
2. Ensure `effective_analyzer_version` covers the new play-type plugin hashes (not just the 9 display
   plugins).
3. Handle the transition: existing reports with `effective_analyzer_version=""` (blank, from before
   Phase 3) should be treated as historical, not as matching the current version.

---

## §8 Invalidation case studies

### Case A: Fix BCM cycle detection bug for one machine (e.g., M274)

**Current behavior**:
- Bug is in `round_classification.py:detect_cycle_peak` or `player_impact_analyzer.py:_resolve_bonus_feature`.
- Either file is in `_CLOSURE_FILES` → `base_hash` flips.
- ALL 420 machines get new `effective_analyzer_version`.
- All 1,088 `(machine, mode)` pairs with rawdata show as stale.
- Operator must regenerate ALL reports (or accept a fleet-wide re-flag).

**Under target model**:
- BCM detection logic moved to a `BCMPlayType` plugin.
- Editing the plugin flips only that plugin's hash.
- `effective_analyzer_version` changes only for machines with the BCM play-type.
- Per `bcm_pairings.json`: 30 machines listed. The fleet sweep identified ~55 (machine, mode) pairs
  with BCM-like behavior (fallback_sum >0.5% per the M274 investigation).
- **Target blast radius**: ~30–55 machines vs 420 today.

### Case B: Add support for a new machine's wild-nudge play-type

**Current behavior**:
- New machine brings ST=36 + ReMarks="move" rounds. Support means editing `round_classification.py`.
- `round_classification.py` is in closure → base_hash flips → 420 machines re-flag.

**Under target model**:
- `is_wild_nudge_round` logic lives in a `WildNudgePlayType` plugin.
- New machine is detected as having this play-type from its rawdata (auto-detection per DIRECTION §4).
- Plugin edit re-flags the 25+ (machine,mode) pairs with wild-nudge, NOT the other 395.
- **Target blast radius**: ~25 (machine,mode) pairs vs 420 machines today.

### Case C: Fix TopDollar selector settlement attribution

**Current behavior**:
- Bug is in `round_win.py:SettlementWinAmountRule` or `trigger_sessions.py` logic for Type-1 sessions.
- Both files in closure → base_hash flips → 420 machines re-flag.
- Only 13 TopDollar variant machines are actually affected by the fix.

**Under target model**:
- `SettlementWinAmountRule` becomes part of a `SelectorPlayType` plugin.
- Editing the plugin re-flags the 13 TopDollar machines.
- M273's 85 WheelSelector variants would be in a DIFFERENT plugin (or same if they share the mechanic).
- **Target blast radius**: 13 machines vs 420 today.

### Case D: Add a new universal infrastructure feature (e.g., new sampling parameter)

**Current behavior**:
- Edit `base_pipeline.py` or `player_impact_analyzer.py:main()` — in closure → 420 re-flag.

**Under target model**:
- Infrastructure changes remain in base → still 420 re-flag.
- This is CORRECT: a sampling infrastructure change affects all machines' data quality equally.
- The refactor does NOT improve blast radius for genuinely universal changes.

### Case E: Change per-machine payid config (e.g., add a new rule for M274)

**Current behavior**:
- Edit `configs/machine_round_win_rules.json` — NOT hashed → zero stale signal.
- M274's behavior changes silently with no version bump.

**Under target model**:
- `per-machine-payid-config-hash` covers M274's rule entry.
- Editing M274's rule flips its payid-config hash → M274's `effective_analyzer_version` changes.
- Other machines unaffected.
- **Target blast radius**: 1 machine vs 0 (silent) today.

---

## §9 Fragility hotspots — top-10 highest fan-out symbols

Ranked by (change frequency × machines affected). Informational only.

| Rank | Symbol | Location | Base or Plugin | Change re-flags | Why fragile |
|------|--------|----------|---------------|-----------------|-------------|
| 1 | `parse_chunk_response` | `analyzer/core/parser.py:485` | BASE (122 KB file) | 420 | Main analysis loop; all mechanic branches here; 132 recent commits on the parent monolith from which this was carved |
| 2 | `compute_trigger_sessions` | `trigger_sessions.py:131` | BASE | 420 | Core bonus session win attribution; 8 commits total; every multi-ST machine depends on correct attribution |
| 3 | `_CLOSURE_FILES` tuple | `versioning.py:114` | BASE | 420 | Adding or removing any file re-pins base_hash for the entire fleet; the drift-guard test catches additions but not removals |
| 4 | `extract_round_win` | `round_win.py:430` | BASE | 420 | Universal win extraction dispatcher; called in every chunk's parse loop |
| 5 | `is_paid_round` | `round_classification.py:104` | BASE | 420 | Fundamental paid/bonus classifier; wrong = wrong RTP for everyone |
| 6 | `BCMCycleAnchorRule` | `round_win.py:345` | BASE (but only M274 in config) | 420 (base flip) vs 1 (actual effect) | Maximum disconnect between blast radius and actual effect |
| 7 | `detect_cycle_peak` | `round_classification.py:311` | BASE | 420 | BCM cycle detection; ~30+ machines affected; any bug fix re-flags all |
| 8 | `SettlementWinAmountRule` | `round_win.py:163` | BASE (but 13 machines in config) | 420 (base flip) vs 13 (effect) | Same disconnect as BCMCycleAnchorRule |
| 9 | `player_impact_analyzer.py main()` | `player_impact_analyzer.py:965` | BASE | 420 | 3300-line main function; orchestration + BCM + bonus feature resolution + summary build |
| 10 | `MechanismRegistry.build` | `mechanism_registry.py:100` | BASE | 420 | Mechanism detection; the comment in the module says it was placed OUTSIDE core/ precisely to avoid base_hash flip, but it IS in `_CLOSURE_FILES` — so the intent (line 7-9 of the file's docstring) was already violated when versioning.py was written |

**Hotspot 10 note**: `mechanism_registry.py` docstring line 7-9 states: "The class is defined here
(outside core/) so changes to detection logic do NOT flip compute_base_analyzer_version() for the
entire fleet — only machines that declare the machine_mechanics plugin will be affected." This intent
is INCORRECT as implemented: `mechanism_registry.py` IS in `_CLOSURE_FILES` line 126 and therefore
IS in `base_hash`. The docstring claim is aspirational but not realized. This is a staleness/confusion
risk surfaced here as a flagged disagreement per DIRECTION §9.

---

## §10 Summary for W2 designer

### What the target model must change in the version composition

1. **Move mechanic modules out of `_CLOSURE_FILES`**: `round_classification.py`, `round_win.py`,
   `trigger_sessions.py`, and mechanic-bearing portions of `parser.py` should become play-type plugin
   content. When a play-type plugin is edited, only machines with that play-type re-flag.

2. **Add `per-machine-payid-config-hash`**: hash the per-machine entries in
   `machine_round_win_rules.json` (and any future payid config) per machine. This gives visibility to
   config-only payid changes without touching the engine code. Today these changes are completely silent.

3. **Wire `effective_analyzer_version` as the primary staleness signal**: the backend uses `analyzer_version`
   (monolith-only SHA256). Switch to `effective_analyzer_version` (closure + play-type plugins + payid
   config + mode) as the live staleness source of truth.

4. **Fix `mechanism_registry.py`'s aspirational vs actual closure membership**: either remove it from
   `_CLOSURE_FILES` (it SHOULD be excluded per its own docstring) and register it as a plugin, or
   accept the mismatch. The designer must resolve this.

5. **Handle variant fan-out**: under play-type plugins, M273 + 85 variants sharing a WheelSelector
   play-type will ALL re-flag when that play-type plugin changes. This is correct and accepted (DIRECTION
   §4: hash-level isolation, not output-level). The 86-machine cohort is the natural blast radius for a
   WheelSelector mechanic fix.

6. **Residual risk — universal dispatch engine**: even after moving `SettlementWinAmountRule` and
   `BCMCycleAnchorRule` to play-type plugins, the dispatcher skeleton (`extract_round_win`,
   `load_rules_for_machine`, the fallback to `WinCredits`) must remain in base (called by all machines).
   A bug fix to the DISPATCHER itself still re-flags all 420. This is unavoidable for a truly universal
   primitive — the isolation gain is in fixing the PER-MECHANIC rules without touching the dispatcher.

---

*Audit end. Data sources: `versioning.py` (_CLOSURE_FILES), `configs/machines.json` (422 entries),
`slot_designer/configs/machine_manifests/` (420 files), `configs/machine_round_win_rules.json` (2 rules,
13 machines), `configs/bcm_pairings.json` (30 machines), `rawdata/` (327 machines, 1,088 (machine,mode)
pairs), git log on key files.*
