# Dimension Framework — Coupling / Blast-Radius Audit

**Date:** 2026-06-15
**Branch:** `claude/playtype-rearch`
**Auditor role:** arch-coupling-auditor
**Premise:** making every per-ST metric (ST, dimension)-keyed, where a "dimension" is a
trigger-path split declared in the manifest's `spin_types[st].trigger_paths` block.

Ground-truth sources: code grep + AST + live golden files
(`cache/_fwpass_gate/{M15,M43,M43_7,M279,M275}_1.json` — the byte-gate regression contract).

---

## 1. Scope

Directories audited:

- `fresh_slotlab/analyzer/core/parser.py` — ST-keyed accumulators + st_extractors hook
- `fresh_slotlab/analyzer/report_engine.py` — chunk-reduction loop + stash assembly
- `fresh_slotlab/analyzer/st_extract/{__init__,_base,trigger_path}.py` — extraction layer
- `fresh_slotlab/analyzer/machine_spec.py` — manifest schema + derive_analyses
- `fresh_slotlab/analyzer/versioning.py` — `_CLOSURE_FILES` + base_hash algorithm
- `fresh_slotlab/analyzer/features/` — all 19 plugin files
- `src/web_console/frontend/app.js` — `SPINTYPE_DIMENSIONS` + `_stDim*` renderers
- `src/web_console/frontend/pure.js` — i18n keys
- `configs/machine_manifests/{M15,M43,M279,M275}.json` — 4 registered machines

---

## 2. Fleet-shared symbol table

### 2a. Parser accumulators (ST-keyed, closure-resident)

These live in `fresh_slotlab/analyzer/core/parser.py` (a `_CLOSURE_FILES` member,
versioning.py line 120) and in `fresh_slotlab/analyzer/report_engine.py` (a
`_CLOSURE_FILES` member, versioning.py line 136). Any change to these accumulators
flips `base_hash` for ALL machines.

| Symbol | Defined in | Direct consumers (features reading the chunk dict key) | Machines affected by base_hash flip |
|--------|-----------|------------------------------------------------------|-------------------------------------|
| `spin_type_bucket_spins[st][bucket]` | `parser.py:886-893` / `report_engine.py:641` | `freespin_dynamics`, `respin_dynamics`, `minigame_dynamics`, `wheel_dynamics`, `upstream_feature_breakdown` (via stash key), `spin_type_rtp_buckets` (via `spin_type_rtp_buckets` chunk key) | ALL 4 registered machines (fleet-wide base_hash flip) |
| `spin_type_bucket_win[st][bucket]` | `parser.py:892-894` / `report_engine.py:643` | same 5 features as above | ALL 4 |
| `spin_type_next_counts[st][next_st]` | `parser.py:852` / `report_engine.py:638` | `freespin_dynamics`, `respin_dynamics`, `minigame_dynamics`, `upstream_feature_breakdown` | ALL 4 |
| `spin_type_paid_bucket_{spins,bet,win}[st][bucket]` | `parser.py:902-910` | `spin_type_rtp_buckets` (reads `spin_type_rtp_buckets` chunk dict key) | ALL 4 |
| `spin_type_spins[st]` | `parser.py:840` / `report_engine.py:637` | `upstream_feature_breakdown` | ALL 4 |
| `spin_type_win[st]`, `spin_type_wins[st]`, `spin_type_paid_rounds[st]`, `spin_type_bet[st]`, `spin_type_paid_bet[st]` | `parser.py:840-845` / `report_engine.py:653-657` | `report_engine.py` inline `spin_type_breakdown` rows, all per-ST features via `spin_type_breakdown` | ALL 4 |
| `spin_type_paid_bucket_*` emitted as `chunk_dict["spin_type_rtp_buckets"]` | `parser.py:2619-2628` | `spin_type_rtp_buckets` feature only | ALL 4 |

**Invalidation radius:** editing any of the above accumulator shapes in parser.py or
their merge loops in report_engine.py flips `compute_base_analyzer_version()` → ALL
4 registered machines re-flag + ALL served reports become stale.

### 2b. st_extract framework (closure-resident, base.py + __init__.py)

| Symbol | File | Direct callers | Invalidation radius |
|--------|------|---------------|---------------------|
| `STExtractor` ABC | `st_extract/_base.py` (in `_CLOSURE_FILES`) | `TriggerPathExtractor` (trigger_path.py, base-excluded) | All machines that declare `trigger_paths` (currently M275 only, 1 machine) |
| `discover_extractors()` / `get_extractors_for_manifest()` / `register_extractor()` | `st_extract/__init__.py` (in `_CLOSURE_FILES`) | `report_engine.py:442-504` | ALL 4 machines (base_hash flip if `__init__.py` changes) |
| `extractor_hashes()` | `st_extract/__init__.py` | `versioning.py` (compute_effective_analyzer_version) | ALL 4 machines |

### 2c. TriggerPathExtractor (base-EXCLUDED)

| Symbol | File | Direct callers | Invalidation radius |
|--------|------|---------------|---------------------|
| `TriggerPathExtractor` | `st_extract/trigger_path.py` (base-excluded) | `freespin_dynamics.extract()` reads `chunk_dict["st_extract"]["trigger_path"]` | Only machines declaring `trigger_paths`: currently M275 (1 machine, 1 report per mode/md5 bucket) |
| `TriggerPathExtractor.observe_round()` | trigger_path.py | `parser.py` per-round extractor hook | M275 only |
| `TriggerPathExtractor.finalize_chunk()` | trigger_path.py | `parser.py` end-of-chunk | M275 only |

### 2d. machine_spec.py symbols (NOT in `_CLOSURE_FILES`)

`machine_spec.py` is explicitly noted in the module docstring as "NOT imported by the
report-production closure". Verified: it is absent from `versioning._CLOSURE_FILES`.
Editing it does NOT flip `base_hash`.

| Symbol | Callers | Invalidation radius |
|--------|---------|---------------------|
| `KNOWN_ROLES` | `machine_spec.py` internal; `report_engine.py:~510-515` (derive_analyses); `MACHINE_ONBOARDING.md` process | Adding a role changes which analyses `derive_analyses()` returns → changes that machine's `effective_version`, not `base_hash` |
| `ROLE_ANALYSES`, `PLAY_ANALYSES`, `CROSS_CUTTING`, `PER_SPINTYPE` | `derive_analyses()` → `report_engine.py` | Per-machine `effective_version` only; no fleet base_hash flip |
| `derive_analyses(manifest)` | `report_engine.py:~510` | Per-machine; base-excluded |
| `derive_mechanism_flags(manifest)` | `report_engine.py:~520` (`bonus_chain_dynamics`, `machine_mechanics` plugins) | Per-machine |

### 2e. Feature plugins (all base-EXCLUDED under R-4)

Every plugin in `fresh_slotlab/analyzer/features/*.py` (19 files) is auto-discovered via
`feature_registry.discover_features()` and excluded from `_CLOSURE_FILES` by the R-4 rule
(`feature_registry.py:_CLOSURE_FILES` note). Editing any plugin changes only
`feature_hashes[FEATURE_ID]` and re-flags only machines that declare that analysis.

| Plugin | FEATURE_ID | Reads per-ST chunk keys | Currently declared by (machines) |
|--------|-----------|------------------------|----------------------------------|
| `payouts_by_spin_type` | `payouts_by_spin_type` | `payout_id_by_spin_type`, `payout_id_win_by_spin_type` | M15, M43, M279, M275 (all 4) |
| `reel_marginal_by_spin_type` | `reel_marginal_by_spin_type` | stash `_reel_marginal_by_spin_type_data` (from `symbol_counts_by_col_by_spin_type`) | M15, M43, M279, M275 (all 4) |
| `spin_type_outcomes` | `spin_type_outcomes` | reads `payouts_by_spin_type` + `spin_type_breakdown` in emit() | M15, M43, M279, M275 (all 4) |
| `spin_type_rtp_buckets` | `spin_type_rtp_buckets` | `spin_type_rtp_buckets` chunk key | M15, M43, M279, M275 (all 4) |
| `upstream_feature_breakdown` | `upstream_feature_breakdown` | stash `_upstream_feature_breakdown_data` (contains `spin_type_next_counts`, `spin_type_bucket_spins/bet/win`, `spin_type_spins`, etc.) | M15, M43, M279, M275 (all 4) |
| `bonus_chain_dynamics` | `bonus_chain_dynamics` | stash `_bonus_chain_dynamics_data` | M15, M43, M279, M275 (all 4) |
| `collect_mechanic` | `collect_mechanic` | stash `_collect_mechanic_data` | M15, M43, M279, M275 (all 4) |
| `machine_mechanics` | `machine_mechanics` | stash keys (lock_lines, jackpot etc.) | M15, M43, M279, M275 (all 4) |
| `structure_drift` | `structure_drift` | `chunk_dict["st_extract"]["signature_audit"]` | M15, M43, M279, M275 (all 4) |
| `freespin_dynamics` | `freespin_dynamics` | `spin_type_next_counts`, `spin_type_bucket_{spins,win}`, `st_extract["trigger_path"]` | M275 only (role=freespin declared only in M275.json) |
| `respin_dynamics` | `respin_dynamics` | `spin_type_next_counts`, `spin_type_bucket_{spins,win}` | M43, M279 (role=respin) |
| `minigame_dynamics` | `minigame_dynamics` | `spin_type_next_counts`, `spin_type_bucket_{spins,win}` | M43 only (play=WinMiniGame) |
| `wheel_dynamics` | `wheel_dynamics` | `spin_type_bucket_{spins,win}` | M279 only (play=Wheel) |
| `topdollar_choice` | `topdollar_choice` | `topdollar_sessions` chunk key | M15 only (role=player_choice) |

### 2f. Frontend renderers (app.js, not in versioning)

The frontend reads `player_impact_summary.json` off disk. Its versioning is orthogonal
to `base_hash` — changes to `app.js` affect rendering without touching any Python hash.

| Symbol | File:line | Reads from summary | Machines it visibly affects |
|--------|-----------|-------------------|----------------------------|
| `_stDimFreespin(stCtx)` | `app.js:5100` | `summary.player_impact.freespin_dynamics` + `freespin_dynamics.trigger_paths` (F6 section) | M275 (only machine with freespin_dynamics) |
| `_stDimRespin(stCtx)` | `app.js:4766` | `summary.player_impact.respin_dynamics` | M43, M279 |
| `_stDimMinigame(stCtx)` | `app.js:4908` | `summary.player_impact.minigame_dynamics` | M43 |
| `_stDimWheel(stCtx)` | `app.js:5009` | `summary.player_impact.wheel_dynamics` | M279 |
| `_stDimSelectorChoice(stCtx)` | `app.js:4740` | `summary.topdollar_choice` | M15 |
| `_stDimSettlement(stCtx)` | `app.js:4751` | `summary.topdollar_choice` (settlement sub-view) | M15 |
| `_stDimOverview(stCtx)` | `app.js:4618` | `stCtx.row` (spin_type_breakdown row) | All 4 machines |
| `_stDimWinDistribution(stCtx)` | `app.js:4646` | `summary.player_impact.spin_type_outcomes[label]` | All 4 machines |
| `_stDimPayid(stCtx)` | `app.js:4719` | `stCtx.payRows` (payouts_by_spin_type rows) | All 4 machines |
| `renderSpinTypeOutcomes(summary)` | `app.js:5326` | `spin_type_breakdown`, `spin_type_outcomes`, `payouts_by_spin_type` | All 4 machines |
| `renderStructureDriftPanel(summary)` | `app.js:4271` | `summary.structure_drift` | All 4 machines |
| `SPINTYPE_DIMENSIONS` list | `app.js:5315` | drives per-ST render loop | All 4 machines |

---

## 3. Hash composition map

### 3a. base_hash

```
compute_base_analyzer_version()   [versioning.py:170]
  Inputs: sha256 of every file in _CLOSURE_FILES (sorted, CRLF-normalized)
  _CLOSURE_FILES (25 entries):
    fresh_slotlab/analyzer/__init__.py
    fresh_slotlab/analyzer/core/__init__.py
    fresh_slotlab/analyzer/core/_utils.py
    fresh_slotlab/analyzer/core/aggregator.py
    fresh_slotlab/analyzer/core/base_pipeline.py
    fresh_slotlab/analyzer/core/parser.py          ← ST-keyed accumulators live here
    fresh_slotlab/analyzer/core/writer.py
    fresh_slotlab/analyzer/feature_registry.py
    fresh_slotlab/analyzer/features/__init__.py
    fresh_slotlab/analyzer/features/_base.py
    fresh_slotlab/analyzer/st_extract/__init__.py  ← discovery/registry for extractors
    fresh_slotlab/analyzer/st_extract/_base.py     ← STExtractor ABC
    fresh_slotlab/analyzer/parse_state.py
    fresh_slotlab/analyzer/pipeline_context.py
    fresh_slotlab/analyzer/report_engine.py        ← accumulator merge loops live here
    fresh_slotlab/analyzer/rtp_integrity.py
    fresh_slotlab/analyzer/topo_sort.py
    fresh_slotlab/analyzer/versioning.py
    fresh_slotlab/chunk_index.py
    fresh_slotlab/machine_md5.py
    fresh_slotlab/rawdata_index.py
    fresh_slotlab/round_classification.py
    fresh_slotlab/round_win.py
    fresh_slotlab/sampler.py
    fresh_slotlab/trigger_sessions.py

  Current value: 916ed8021606  (per ANALYZER_ARCHITECTURE.md §6 phase 5D)

  Downstream consumers:
    - ALL 4 registered machines' effective_version is seeded with base_hash
    - ALL reports served by the console carry analyzer_version derived from it
    - Stale-check: console UI marks every report stale when base_hash changes
    - Estimated report count re-flagged on a base_hash flip: all cached reports
      across all machines, all modes, all md5 buckets (exact count = sum of
      cache/_fwpass_gate entries times real md5 buckets per machine; currently
      5 golden files represent 5 (machine,mode) combinations)
```

**Computed coupling — base_hash:** editing `parser.py` (which carries the ST-keyed
accumulator definitions and the per-round accumulation loop at lines 840-1830) flips
`base_hash` for ALL 4 registered machines.

**Consequential coupling — base_hash:** a base_hash flip marks ALL reports stale in the
console rwtree for ALL 4 machines. Users see the "历史" (stale/historical) cell for
every previously-generated report until reports are regenerated.

### 3b. effective_version (per-machine)

```
compute_effective_version_for_machine(machine_id, mode)
  h = sha256(base_hash)
  for fid in sorted(set(machine_features)):        ← from derive_analyses(manifest)
      h.update("\x00" + fid + "=" + feature_hashes[fid])
  if mode is not None:
      h.update("\x00mode=" + str(mode))
  return h.hexdigest()[:12]

  Inputs:
    base_hash (above)
    feature_hashes[fid] = sha256(plugin_file_bytes)[:12] for each plugin
    machine_features = derive_analyses(manifest) result (sorted list)
    mode (int)

  Downstream consumers per machine:
    M15:  8 PER_SPINTYPE + role-keyed topdollar_choice + CROSS_CUTTING = ~18 analyses
    M43:  8 PER_SPINTYPE + respin_dynamics + minigame_dynamics + CROSS_CUTTING = ~19 analyses
    M279: 8 PER_SPINTYPE + respin_dynamics + wheel_dynamics + CROSS_CUTTING = ~19 analyses
    M275: 8 PER_SPINTYPE + freespin_dynamics + CROSS_CUTTING = ~18 analyses
```

**Computed coupling — effective_version:** editing `freespin_dynamics.py` changes
`feature_hashes["freespin_dynamics"]` → re-flags effective_version for M275 only (1
machine). Editing `spin_type_outcomes.py` re-flags all 4 machines' effective_version but
does NOT flip base_hash.

### 3c. Extractor hashes (per-machine, for machines declaring extractors)

```
extractor_hashes()  [st_extract/__init__.py:185]
  Returns {EXTRACTOR_ID: TriggerPathExtractor.compute_hash()}
  = sha256(trigger_path.py bytes)[:12]

  Consumers:
    versioning.compute_effective_analyzer_version  ← folds "xt:trigger_path" into
    the effective_version of machines that declare trigger_paths.
    Currently: M275 only.
```

Editing `trigger_path.py` changes only M275's effective_version (1 machine, 1 mode,
however many md5 buckets M275/mode_1 has).

---

## 4. Silent dependencies inventory

### 4a. Module-level globals

| Global | Module:line | Effect if modified |
|--------|------------|-------------------|
| `_CLOSURE_FILES` tuple | `versioning.py:114` | Adding/removing an entry re-computes base_hash at next call — fleet-wide report re-flag. The CI drift guard (`tests/analyzer/test_honesty2_drift_guard.py`) fails if a new closure module is imported but absent from this tuple. |
| `ALL_EXTRACTORS` list | `st_extract/__init__.py:57` | Module-global; adding an extractor at import time is safe (idempotent). Risk: a module that imports `st_extract` at a non-discovery callsite could register a duplicate. Protected by the `EXTRACTOR_ID` duplicate-no-op guard (line 86-88). |
| `KNOWN_ROLES` frozenset | `machine_spec.py:53` | Adding a role changes which `ROLE_ANALYSES` analyses are derived for manifests declaring that role. Does NOT flip base_hash (machine_spec.py is base-excluded). |
| `ROLE_ANALYSES`, `PLAY_ANALYSES`, `CROSS_CUTTING`, `PER_SPINTYPE` | `machine_spec.py:59-109` | Same as KNOWN_ROLES — affects derive_analyses output, hence each machine's analysis set and effective_version. Not base_hash. |
| `SPINTYPE_DIMENSIONS` list | `app.js:5315` | Adding a new dimension function to this list causes it to fire for every ST in every machine's renderSpinTypeOutcomes call. Self-guards (the dimension functions return `""` when their data is absent). |
| `_TRIGGER_PATH_EXTRACTOR_ID = "trigger_path"` | `freespin_dynamics.py:127` | Hard-codes the extractor ID string. If `TriggerPathExtractor.EXTRACTOR_ID` were renamed, this module would silently not find the extractor output. Not a base_hash dependency but a naming coupling. |

### 4b. File-path conventions (silent structural coupling)

| Convention | Defined by | Consumers |
|-----------|-----------|-----------|
| `configs/machine_manifests/<M>.json` | `report_engine.py:_DEFAULT_MANIFESTS_ROOT` | `report_engine.generate_report_from_chunks`, `versioning.compute_effective_version_for_machine`, `app.py` badge map iteration. Adding a manifest at this path REGISTERS the machine (it starts generating reports). |
| `chunk_dict["st_extract"]["<EXTRACTOR_ID>"]` | `parser.py` finalize block (parser.py:2590+) + `STExtractor.EXTRACTOR_ID` | `freespin_dynamics.extract()` reads `chunk_dict.get("st_extract")` then `.get("trigger_path")`. The string literal `"trigger_path"` appears at `freespin_dynamics.py:127` as `_TRIGGER_PATH_EXTRACTOR_ID`. |
| `chunk_dict["spin_type_rtp_buckets"]` | `parser.py:2616-2628` (key name) | `spin_type_rtp_buckets` feature reads it at `extract()`. String literal must match between producer (parser) and consumer (plugin). Both are in sync today; a rename in parser.py is a closure change that flips base_hash. |
| `summary["player_impact"]["freespin_dynamics"]` | `freespin_dynamics.emit()` writes it | `_stDimFreespin(stCtx)` reads `stCtx.summary.player_impact.freespin_dynamics`. String is duplicated in: plugin SCHEMA_KEYS ClassVar + app.js line 5101. |
| `summary["player_impact"]["spin_type_breakdown"]` | `report_engine.py:1326, 1649` inline block | 7 features and the frontend renderer all read this exact key string. It is the most-consumed per-ST key in the system. |
| `summary["structure_drift"]` | `structure_drift.emit()` | `renderStructureDriftPanel(summary)` reads `summary.structure_drift` (app.js:4271). |
| `cache/_fwpass_gate/{M}_*.json` | hand-written or regen'd by `_p5_gate.py` | The byte-gate regression contract. They are the ground truth for "schema has not changed". The _fwpass_gate directory currently holds 5 files: M15_1, M43_1, M43_7, M275_1, M279_1. |

### 4c. Import-time side effects

| Side effect | Location | Risk |
|------------|----------|------|
| `register_extractor(TriggerPathExtractor({}))` | `st_extract/trigger_path.py` bottom (line 505) | Fires at first import of `trigger_path.py`. Idempotent (duplicate-no-op guard). Safe if `discover_extractors()` is called once per process — which `report_engine.py:447` does. |
| Feature plugin `register()` calls | Each `features/*.py` bottom | Same pattern as extractors; auto-discovered once per process. |
| `ALL_PLAY_TYPE_PLUGINS` (old, deleted) | Deleted in phase D | Historical risk; no longer present. |

---

## 5. Invalidation case studies

### Case 1: Add a second machine with a multi-path ST (e.g. M999 with ST50 having `trigger_paths`)

**What changes:**
- New file: `configs/machine_manifests/M999.json` — REGISTERS the machine.
- Manifest declares `spin_types["50"]["trigger_paths": {...}]` — activates `TriggerPathExtractor` for this machine via `get_extractors_for_manifest()`.
- If M999 has a `freespin` role: `machine_spec.ROLE_ANALYSES["freespin"]` already maps to `freespin_dynamics` — no new code needed.
- `freespin_dynamics.extract()` already reads `chunk_dict["st_extract"]["trigger_path"]` generically.

**What does NOT change:**
- `parser.py` — not touched.
- `report_engine.py` — not touched.
- `st_extract/trigger_path.py` — not touched.
- `freespin_dynamics.py` — not touched.
- `base_hash` — UNCHANGED (all 5 files above are either base-excluded or untouched).

**Invalidation radius:**
- base_hash: NO CHANGE.
- M999 effective_version: NEW (first computation).
- M15/M43/M279/M275 effective_version: UNCHANGED.
- M275's `_fwpass_gate` golden: UNCHANGED.
- Reports staled: 0 existing reports staled.

### Case 2: Extend trigger_path.py to support a new discriminator kind (e.g. `"kind": "session_field"`)

**What changes:**
- `st_extract/trigger_path.py` — `_resolve_labels()` gains a new branch.

**What does NOT change:**
- `parser.py`, `report_engine.py` — unchanged (extractor is called via stable hook).
- `st_extract/__init__.py`, `st_extract/_base.py` — unchanged.
- `base_hash`: UNCHANGED (`trigger_path.py` is base-excluded).

**Invalidation radius:**
- `extractor_hashes()["trigger_path"]` changes → effective_version changes for every machine declaring `trigger_paths`.
- Currently: M275 only (1 machine, mode 1, however many md5 buckets).
- M275's existing reports: staled (effective_version changes). User sees "历史" cell until regenerated.
- M15, M43, M279: UNCHANGED (they declare no `trigger_paths`).
- `_fwpass_gate/M275_1.json` byte-gate: will diverge in numbers if the new path fires on M275's chunks. The gate test would red-flag this change — intentional and correct.

### Case 3: Add a new per-ST accumulator to parser.py (e.g. `spin_type_win_by_path[st][path_label]`)

This is the core change required to make every per-ST metric (ST, dimension)-keyed in the
parser itself, rather than in the downstream extraction layer.

**What changes:**
- `parser.py` — new accumulator definition + per-round update + emission into chunk dict.
- `report_engine.py` — new merge loop for the new accumulator + stash key.

**What does NOT change in terms of file identity:**
- Both files are already in `_CLOSURE_FILES`.

**Invalidation radius:**
- `base_hash` FLIPS (both parser.py and report_engine.py are in `_CLOSURE_FILES`).
- ALL 4 registered machines' effective_version re-flags.
- ALL existing reports across ALL (machine, mode, md5) combinations are staled in the console rwtree.
- `_fwpass_gate/{M15,M43,M43_7,M275,M279}_1.json` byte-gate: will diverge unless new keys are purely ADDITIVE (new chunk dict key not yet consumed by emit). If additive (no existing key changes), BYTE-IDENTICAL for the 5 goldens (the new key is ignored by existing emit paths). But `base_hash` STILL FLIPS because the file bytes changed. One-time re-baseline of `_fwpass_gate` goldens is required.
- **This is the reason the current design uses the base-excluded `st_extract` layer instead**: parser.py modifications are the highest-cost change in this system.

### Case 4: Rename `spin_type_breakdown` key to `spin_type_summary` in the player_impact_summary schema

**What changes:**
- `report_engine.py:1649` (writer of `summary["player_impact"]["spin_type_breakdown"]`).
- 7 feature plugins that read `summary["player_impact"]["spin_type_breakdown"]` in their `emit()`: `payouts_by_spin_type`, `reel_marginal_by_spin_type`, `spin_type_outcomes`, `spin_type_rtp_buckets`, `upstream_feature_breakdown`, `freespin_dynamics`, `respin_dynamics`, `minigame_dynamics`, `wheel_dynamics` = 9 plugin files.
- `app.js:5331` (`pi.spin_type_breakdown || []`).
- `app.js:5337` (`pi.spin_type_outcomes || {}`).

**Invalidation radius:**
- `base_hash` FLIPS (report_engine.py is in `_CLOSURE_FILES`).
- ALL 4 machines' effective_version re-flags.
- ALL 9 plugin files (base-excluded) change → their feature_hashes all change.
- ALL existing reports staled.
- `_fwpass_gate` byte-gate: ALL 5 goldens diverge (the key is renamed → schema changed). New goldens required.
- Frontend renders broken until `app.js` is updated simultaneously.
- This is the highest fan-out change possible in the system (9 plugin files + 1 closure file + app.js + all reports staled).

### Case 5: Add `trigger_paths` to a CURRENTLY SINGLE-DIMENSION ST (e.g. add `trigger_paths` to M43 ST50)

**What changes:**
- `configs/machine_manifests/M43.json` — add `trigger_paths` block to ST50.
- `freespin_dynamics` / `respin_dynamics` plugin: IF the existing mechanic plugin does not already read `st_extract["trigger_path"]`, a new version must. (`respin_dynamics.extract()` does NOT currently read `st_extract` — verified by grep showing it only reads `spin_type_next_counts`, `spin_type_bucket_{spins,win}`.) So `respin_dynamics.py` would need to be extended.

**What does NOT change:**
- `parser.py` — unchanged (extractor hook already exists).
- `trigger_path.py` — unchanged (generic, zero machine-specific code).
- `base_hash` — UNCHANGED (only manifest + plugin file changed; both base-excluded).

**Invalidation radius:**
- `respin_dynamics.py` change → `feature_hashes["respin_dynamics"]` changes → M43 and M279 effective_version re-flags (both use respin_dynamics).
- M279's reports staled even though M279's manifest was not changed — this is the CONSEQUENTIAL coupling of a shared plugin. Editing `respin_dynamics.py` to support trigger_paths for M43 re-flags M279 even though M279 does not declare `trigger_paths`.
- M43 reports staled (expected, manifest changed).
- M275, M15: UNCHANGED.
- `_fwpass_gate/M43_{1,7}.json` + `_fwpass_gate/M279_1.json` byte-gates: M43 diverges in content (new trigger_paths output); M279 will be byte-identical if the new code path is conditional on `trigger_paths` being declared. Test must verify this.

---

## 6. Fragility hotspots (top 10 by fan-out, informational only)

| Rank | Symbol | File | Fan-out | Nature of coupling |
|------|--------|------|---------|-------------------|
| 1 | `summary["player_impact"]["spin_type_breakdown"]` | `report_engine.py:1649` (write) | 9 plugin emit() readers + 1 frontend renderer = **10 direct consumers** | CONSEQUENTIAL: the inline-built ST breakdown is the shared data bus for all per-ST analyses. Renaming this key breaks all 10 consumers simultaneously. |
| 2 | `parser.py` (entire file) | `core/parser.py` | In `_CLOSURE_FILES` → ANY edit flips base_hash → ALL 4 machines + ALL reports stale | COMPUTED: changing any of the ~40 accumulator definitions or the per-round update loop (lines 1797-1900) propagates to the entire fleet. |
| 3 | `report_engine.py` (chunk merge loops, lines 838-1034) | `report_engine.py` | In `_CLOSURE_FILES` → same as parser.py | COMPUTED: the ~50 separate merge loops for chunk accumulators are all single-file with base_hash coupling. |
| 4 | `spin_type_bucket_spins/win[st][bucket]` accumulator | `parser.py:886-894` + `report_engine.py:641-643` | Read by 5 plugin `extract()` methods: freespin_dynamics, respin_dynamics, minigame_dynamics, wheel_dynamics, upstream_feature_breakdown | CONSEQUENTIAL: these are the primary per-ST window into round-level outcomes; reshaping the bucket schema (e.g. adding a dimension axis) cascades to all 5 plugins. |
| 5 | `spin_type_next_counts[st][next_st]` | `parser.py:852` + `report_engine.py:638` | 4 plugin `extract()` readers: freespin_dynamics, respin_dynamics, minigame_dynamics, upstream_feature_breakdown | CONSEQUENTIAL: the ST-transition tally is shared across 4 mechanics. A shape change requires 4 plugin updates. |
| 6 | `_CLOSURE_FILES` tuple | `versioning.py:114` | Adding/removing an entry changes `compute_base_analyzer_version()` → ALL machines re-flag | COMPUTED: the closure definition itself is the fleet-wide version lock. It is self-referential (versioning.py is in its own closure set). |
| 7 | `SPINTYPE_DIMENSIONS` list + `renderSpinTypeOutcomes()` | `app.js:5315, 5326` | Every ST section in the console renders by iterating this list → ALL machines' ST sections are affected by any item added here | CONSEQUENTIAL: the dimension render loop is fleet-wide; a new dimension fn that has a bug fires for every ST on every machine. |
| 8 | `derive_analyses(manifest)` | `machine_spec.py:112` | Called by `report_engine.py` and `versioning.py` for every registered machine; determines which plugins run | COMPUTED: adding a new `CROSS_CUTTING` analysis extends the plugin set for ALL 4 machines simultaneously. |
| 9 | `freespin_dynamics.py` | `features/freespin_dynamics.py` | Sole consumer of `st_extract["trigger_path"]`; its `trigger_paths` output section is the ONLY currently-live per-path split in any analysis | CONSEQUENTIAL: all per-path logic in the frontend (`_stDimFreespin` F6 section) is coupled to this single plugin's output schema. A schema change here breaks the frontend renderer. |
| 10 | `configs/machine_manifests/<M>.json` schema version `"spintype-native/1"` | All 4 manifest files | `report_engine.py` reads `schema` field at line ~510 to validate; `machine_spec.load_manifest` checks `SCHEMA_VERSION` | COMPUTED: changing the schema version string in `machine_spec.SCHEMA_VERSION` would break all 4 registered manifests simultaneously. |

---

## 7. Frontend contract — player_impact_summary.json schema change and backward-compat risk

### 7a. Current per-ST output keys (ground truth from goldens)

All keys below are nested under `summary["player_impact"]` and are keyed by a string
label `"ST<N>_<behavior_name>"` (e.g. `"ST126_free"`, `"ST140_paid"`):

| Key | Present in goldens | Per-ST keyed by label |
|-----|---------------------|----------------------|
| `spin_type_breakdown` | M15, M43, M275, M279 (all) | YES — list of rows, each row has `spin_type` int |
| `payouts_by_spin_type` | all 4 | YES — dict keyed by label |
| `spin_type_outcomes` | all 4 | YES — dict keyed by label |
| `spin_type_rtp_buckets` | all 4 (paid STs only) | YES — dict keyed by label |
| `reel_marginal_by_spin_type` | all 4 | YES — dict keyed by label |
| `freespin_dynamics` | M275 only | NO — flat dict (single ST); trigger_paths is inside it |
| `respin_dynamics` | M43, M279 | NO — flat dict (single respin ST) |
| `minigame_dynamics` | M43 | NO — flat dict |
| `wheel_dynamics` | M279 | NO — flat dict |
| `upstream_feature_breakdown` | all 4 | NO — feature-keyed, not ST-keyed |
| `bonus_chain_dynamics` | all 4 | NO — global |

### 7b. Current trigger_path output location (freespin_dynamics only)

The ONLY currently-live per-path split is nested inside `freespin_dynamics`:
```
summary["player_impact"]["freespin_dynamics"]["trigger_paths"]
  {
    "available": true,
    "paths": [{"path": "scatter", ...}, {"path": "collect_peak", ...}],
    "total_sessions": int,
    "unknown_paths": [...],
    "multi_buckets": [...],
    ...
  }
```
This is NOT a fleet-wide key. It only appears in M275 summaries (the only machine where
`freespin_dynamics` is emitted).

### 7c. Backward-compat rule (single-dimension ST must be byte-identical)

The architecture doc (ANALYZER_ARCHITECTURE.md §5 gate 1, §8) and the task spec both
state: a single-dimension ST (one with no `trigger_paths` declared, OR an ST on a
machine that uses the default accumulator shape) must render BYTE-IDENTICALLY to today.

Current enforcement point: the `_fwpass_gate` goldens for M15/M43/M43_7/M279 (which
have no `trigger_paths` declared) are the regression contract. Any implementation of
the dimension framework must keep these 4 goldens byte-identical.

For M275: the golden already contains `trigger_paths` within `freespin_dynamics`. The
M275 golden is the source for the multi-path case — it is NOT a byte-identical
regression target but a semantic-correctness target.

**Schema extension rule (the only safe path):**
- New per-path sub-keys added to existing per-ST analysis outputs MUST be additive
  (present only when paths are declared; absent — key not present at all — when single-
  dimension). The frontend `_stDim*` functions already enforce this: every section
  guards on data presence before rendering.
- The `payouts_by_spin_type` / `spin_type_outcomes` / `spin_type_rtp_buckets` /
  `reel_marginal_by_spin_type` keys are currently flat per-label dicts with no path
  dimension. A dimension-keyed variant would need to be a NEW sub-key (e.g.
  `payouts_by_spin_type_by_path`) rather than replacing the existing flat structure —
  or the existing structure must remain as the aggregate/collapsed view while the
  per-path breakdown is additive.

---

## 8. base_hash impact: _CLOSURE_FILES vs base-excluded, re-baseline necessity

### Files that ARE in `_CLOSURE_FILES` (touching any = fleet base_hash flip)

The full list is in section 3a above. The relevant ones for the dimension framework:

| File | Why it would be touched | base_hash consequence |
|------|------------------------|----------------------|
| `core/parser.py` | If per-round accumulation needs a `(st, path)` key in the parser | FLIP — ALL 4 machines + ALL reports staled |
| `report_engine.py` | If the chunk merge loop needs to merge a new `(st, path)` accumulator | FLIP — ALL 4 machines + ALL reports staled |
| `st_extract/__init__.py` | Only if discovery mechanism changes | FLIP |
| `st_extract/_base.py` | Only if STExtractor ABC interface changes | FLIP |
| `rtp_integrity.py` | If new per-path integrity checks are added | FLIP |
| `trigger_sessions.py` | If session-window computation is path-aware | FLIP |

### Files that are base-EXCLUDED (touching = only declaring machines re-flag)

| File | Declaring machines re-flagged |
|------|-------------------------------|
| `st_extract/trigger_path.py` | M275 only (currently sole `trigger_paths` declarer) |
| `features/freespin_dynamics.py` | M275 only |
| `features/respin_dynamics.py` | M43, M279 |
| `features/minigame_dynamics.py` | M43 |
| `features/wheel_dynamics.py` | M279 |
| `features/spin_type_outcomes.py` | All 4 |
| `features/payouts_by_spin_type.py` | All 4 |
| `features/spin_type_rtp_buckets.py` | All 4 |
| `features/reel_marginal_by_spin_type.py` | All 4 |
| `features/upstream_feature_breakdown.py` | All 4 |
| `features/bonus_chain_dynamics.py` | All 4 |
| `features/collect_mechanic.py` | All 4 |
| `features/structure_drift.py` | All 4 |
| `machine_spec.py` | Not in versioning at all — changes affect analysis set derivation without changing any hash directly |
| `configs/machine_manifests/*.json` | Per-machine effective_version via analysis set re-derivation |

### Re-baseline necessity assessment

A one-time re-baseline is **unavoidable if and only if** the dimension framework requires
a change to `parser.py` or `report_engine.py`. Specifically:

- **Path A (pure extraction layer — NO parser.py change):** The current architecture
  already supports per-path accumulation ENTIRELY within `st_extract/trigger_path.py`
  (base-excluded), which the `freespin_dynamics` plugin reads. If the dimension framework
  extends per-ST analyses by having each mechanic plugin read `st_extract["trigger_path"]`
  from the chunk dict, then ONLY the plugin files change. `parser.py` and `report_engine.py`
  are untouched. `base_hash` stays at `916ed8021606`. No re-baseline required. The
  `_fwpass_gate` goldens for M15/M43/M43_7/M279 remain byte-identical (those machines have
  no `trigger_paths` declared → `st_extract` key absent from their chunks → plugins get
  empty trigger_paths data → conditional path not taken → output unchanged).

- **Path B (parser accumulator change — adds `(st, path)` accumulator in parser.py):**
  `parser.py` in `_CLOSURE_FILES` → `base_hash` FLIPS ONCE. ALL reports stale. One-time
  re-baseline of `_fwpass_gate` goldens required. This is the higher-impact path.

The DIRECTION.md §3 and the framework precedent (sub-pass B that added the `st_extract`
layer) both favor Path A: the extraction layer was designed precisely to avoid parser.py
changes for per-round accumulation.

---

## 9. How many machines/reports re-flag

### Registered machines: 4

M15, M43, M279, M275 (the only entries in `configs/machine_manifests/`).

### Per scenario

| Change | base_hash flip | Machines re-flagging | Reports staled (all md5 buckets) |
|--------|---------------|---------------------|----------------------------------|
| Edit `trigger_path.py` only | NO | M275 only (1 machine) | M275/mode_1 reports only |
| Edit `freespin_dynamics.py` only | NO | M275 only | M275/mode_1 reports only |
| Edit `respin_dynamics.py` only | NO | M43, M279 (2 machines) | All M43 + M279 mode reports |
| Edit `spin_type_outcomes.py` | NO | All 4 machines | All reports across all 4 machines |
| Edit `parser.py` | YES | All 4 machines (via base_hash) | ALL reports — every (machine, mode, md5 bucket) |
| Edit `report_engine.py` | YES | All 4 machines | ALL reports |
| Add new extractor module (new .py under st_extract/) | NO (new extractor is base-excluded) | Only machines whose manifest declares the new extractor | Only those machines' reports |
| Add new CROSS_CUTTING analysis to machine_spec.py | NO (machine_spec.py is base-excluded) | All 4 machines' effective_version changes (analysis set grows) | All existing reports for all 4 machines stale |

### Isolation boundary summary

Per-machine isolation (editing one machine's dimension declaration must not re-flag
others) is ALREADY ENFORCED by the current architecture for:
- Manifest changes (base-excluded, per-machine effective_version only)
- Extractor module changes (base-excluded, per-EXTRACTOR_ID hash)
- Plugin file changes (base-excluded, per-FEATURE_ID hash)

Fleet-wide coupling remains for:
- `parser.py` / `report_engine.py` / `rtp_integrity.py` / other `_CLOSURE_FILES` members
- `machine_spec.CROSS_CUTTING` additions (affect all machines' analysis sets)
- `SPINTYPE_DIMENSIONS` list in `app.js` (renders for every machine)

---

## Appendix: Verification data

Golden files used as ground truth (cache/_fwpass_gate/):
- `M15_1.json` — ST1 paid / ST14 player_choice / ST15 settlement; no trigger_paths
- `M43_1.json` — ST1 paid / ST50 respin / ST51 minigame; no trigger_paths
- `M43_7.json` — same manifest, different skin; byte-gate for multi-mode isolation
- `M279_1.json` — ST140 paid / ST36 respin / ST2 wheel; no trigger_paths
- `M275_1.json` — ST140 paid / ST126 freespin with trigger_paths (scatter/collect_peak)

Key structural facts verified from goldens:
- `payouts_by_spin_type` keys: `{M275: ["ST126_free","ST140_paid"], M43: ["ST1_paid","ST50_free","ST51_free"], M15: ["ST1_paid","ST14_free","ST15_free"]}`
- `spin_type_rtp_buckets` keys: paid STs only (`ST140_paid` for M275; ST1_paid for M15/M43; ST140_paid for M279)
- `freespin_dynamics.trigger_paths.paths[*].path` in M275_1: `["scatter","collect_peak"]`
- `freespin_dynamics` absent from M15_1, M43_1, M43_7, M279_1 (correct isolation)
- `spin_type_breakdown` present and list-shaped in all 5 goldens (the most-consumed key)
