# 01 Pipeline Map — Carry-forward Round 1 (Cluster A + D + E)

> **Produced by**: arch-mapper (W1)
> **Date**: 2026-05-28
> **Scope**: Cluster A (error surfacing), Cluster D (4 plugin fixes), Cluster E (test refactor)
> **Baseline**: `session_artifacts/_arch_analyzer_unbundle/01_pipeline_map.md` (C-phase map)
> **Delta approach**: this map documents only the sections that change from the C-phase baseline; unaffected pipeline layers are referenced but not re-documented.

---

## §1 Scope and Entry Points

### What is new in this round vs the C-phase baseline

The C-phase baseline (C1–C6) shipped:
- Plugin infrastructure: `topo_sort.py`, `pipeline_context.py`, `feature_registry.py`
- 9 plugins registered in `ALL_FEATURES`: `payouts_by_spin_type`, `reel_marginal_by_spin_type`, `bankruptcy_simulation`, `multiplier_profile`, `multiplier_wild`, `machine_mechanics`, `upstream_feature_breakdown`, `collect_mechanic`, `bonus_chain_dynamics`
- C2 extract/reduce error capture in merge loop
- C6 gap #3 scatter-trigger annotation on `payout_ids_top20`

**Carry-forward Round 1 scope** — three independent clusters, all within `fresh_slotlab/`:

| Cluster | Files changed | Nature |
|---------|-------------|--------|
| A | `player_impact_analyzer.py` | Control flow: error surfacing contract |
| D (d1) | `analyzer/features/payouts_by_spin_type.py` | Data: paylines sort key fix |
| D (d2) | `analyzer/features/bonus_chain_dynamics.py` | Data: trigger_target heuristic |
| D (d3) | `analyzer/features/bonus_chain_dynamics.py` | Data: new confidence value "unique" |
| D (d4) | `player_impact_analyzer.py` (inline F9 stash) | Data: avg_bonus_payout None semantics |
| E | `tests/analyzer/` (5–8 files) | Tests only: dynamic hex replacement |

---

## §2 Cluster A — Unified Error Surfacing Contract

### §2.1 Pipeline position: where error surfacing occurs

The error surfacing code lives entirely in the tail of `main()` in `player_impact_analyzer.py`, in the block collectively labeled "Wave 2c / Phase C1 + C2" (lines 4903–5118). This block runs AFTER all chunk accumulation, finalization, and feature build-up — but BEFORE `write_summary_json()` which is called at `pia:5210`.

```
main() tail sequence:
  [4903] C1 imports: topo_sort, PipelineContext, MechanismRegistry, ParseState
  [5042] _sorted_features = _topological_sort(_machine_features)  ← ERROR PATH 1 (topo)
  [5072] for _feature in _sorted_features:
  [5075]     for _dep_key in _feature.DECLARED_DEPS:              ← ERROR PATH 2 (DECLARED_DEPS)
  [5076]         if _dep_key not in summary: raise RuntimeError
  [5081]     try: _feature.emit(...)                              ← ERROR PATH 3 (emit)
  [5083]     except Exception: summary["feature_errors"][fid] = ...
  [5098] for _feat_key in _feature_accs:                         ← EXTRACT ERROR SURFACE
  [5099]     if _feat_key.startswith("_extract_error_"): ...
  [5115] for _tmp_key in summary: summary.pop(temp keys)
  [5210] write_summary_json(summary, args.output_dir)            ← ONLY JSON WRITE
```

### §2.2 Path 1: Topo-sort error (current behavior)

**Location**: `pia:5042–5065`

```python
try:
    _sorted_features = _topological_sort(_machine_features)   # pia:5043
except (_PluginCyclicDependencyError, _PluginMissingDependencyError) as _topo_exc:
    _topo_error_dict = {
        "error_type": type(_topo_exc).__name__,
        "message": str(_topo_exc),
        "plugin_dep_graph": {f.FEATURE_ID: list(f.REQUIRES) for f in _machine_features},
        "timestamp": _dt.now(_tz.utc).isoformat(),
    }
    summary["analyzer_init_error"] = _topo_error_dict          # pia:5058 — IN MEMORY
    print(..., file=_sys.stderr)
    raise SystemExit(1) from _topo_exc                         # pia:5065 — EXIT
```

**Error data written to**: `summary["analyzer_init_error"]` at `pia:5058`.

**JSON write call**: `write_summary_json(summary, args.output_dir)` at `pia:5210`.

**GAP**: `raise SystemExit(1)` at `pia:5065` fires BEFORE `write_summary_json` at `pia:5210`. The `summary["analyzer_init_error"]` dict is set in memory but never persisted to disk. The backend receives rc=1 from the subprocess but has no JSON to inspect.

**topo_sort exceptions** defined at:
- `PluginCyclicDependencyError` — `topo_sort.py:42`
- `PluginMissingDependencyError` — `topo_sort.py:63`
- Both are raised by `topological_sort()` — `topo_sort.py:90`

### §2.3 Path 2: DECLARED_DEPS missing-key error (current behavior)

**Location**: `pia:5073–5080`

```python
for _feature in _sorted_features:
    for _dep_key in _feature.DECLARED_DEPS:          # pia:5075
        if _dep_key not in summary:
            raise RuntimeError(                       # pia:5077
                f"Feature '{_feature.FEATURE_ID}' declared dep "
                f"'{_dep_key}' absent from summary. Ordering error or typo."
            )
```

**What gets raised**: bare `RuntimeError` — not the same exception class as the topo errors.

**What happens when this raises**: the `RuntimeError` is NOT caught by the `except (_PluginCyclicDependencyError, _PluginMissingDependencyError)` block at `pia:5044`. It propagates up `main()` as an uncaught exception.

**GAP**: This `RuntimeError` is neither caught nor written to `summary["analyzer_init_error"]`. It exits the process without:
1. Setting any summary key with diagnostic info
2. Calling `write_summary_json()`
3. Emitting a meaningful rc=1 vs uncaught-exception exit

**Where DECLARED_DEPS is currently declared**:
- `PayoutsBySpinType.DECLARED_DEPS = ()` — `payouts_by_spin_type.py:86`
- `CollectMechanic.DECLARED_DEPS = ()` — `collect_mechanic.py:184`
- `BonusChainDynamics.DECLARED_DEPS = ()` — `bonus_chain_dynamics.py:151`
- All current plugins declare empty DECLARED_DEPS. The check at `pia:5075` is defensive code for future plugins.

### §2.4 Path 3: emit() exception (current behavior)

**Location**: `pia:5081–5091`

```python
try:
    _feature.emit(_feature_accs.get(_feature.FEATURE_ID, {}), summary, _c1_ctx)
except Exception as _emit_exc:                        # pia:5083
    import sys as _sys
    print(f"ERROR: feature '{_feature.FEATURE_ID}' emit() failed: {_emit_exc}", file=_sys.stderr)
    if "feature_errors" not in summary:
        summary["feature_errors"] = {}                # pia:5089
    summary["feature_errors"][_feature.FEATURE_ID] = str(_emit_exc)   # pia:5091
```

**Behavior**: emit() exceptions are CAUGHT. They are written to `summary["feature_errors"][fid]`. The loop continues to the next feature. The run does NOT exit early — `write_summary_json` at `pia:5210` still fires.

**GAP**: `summary["feature_errors"]` is a sub-key, NOT `summary["analyzer_init_error"]`. The backend checking only for rc=1 (Path 1 behavior) would miss this. The JSON is written (good), but the key name is inconsistent with Path 1.

### §2.5 Path 4: extract/reduce error (C2, current behavior)

**Location**: `pia:2018–2031` (inside merge loop) + `pia:5098–5106` (surface to summary)

**During merge loop** (per chunk, per feature):
```python
except Exception as _fc_exc:                           # pia:2018
    print(f"WARNING: feature '{_fc_feat.FEATURE_ID}' extract()/reduce() failed...", file=stderr)
    _feature_accs.setdefault(
        f"_extract_error_{_fc_feat.FEATURE_ID}", []
    ).append(str(_fc_exc))                             # pia:2029-2031
```

**After emit loop** (surface to summary):
```python
for _feat_key, _feat_errs in list(_feature_accs.items()):
    if _feat_key.startswith("_extract_error_") and _feat_errs:
        _fid = _feat_key[len("_extract_error_"):]
        summary["feature_errors"][f"extract_{_fid}"] = "; ".join(...)  # pia:5104
```

**Behavior**: these errors land in `summary["feature_errors"]["extract_{fid}"]`, which does survive `write_summary_json` at `pia:5210`.

**Note**: the outer guard block at `pia:2032–2036` is a `bare except: pass` that catches infrastructure errors (import failures, ParseState construction failures). These ARE silently swallowed.

### §2.6 Three-path inconsistency summary (concrete table)

| Error type | Key written | JSON write fires? | rc | Detectable by backend? |
|------------|-------------|-------------------|----|------------------------|
| Topo cycle / missing dep | `summary["analyzer_init_error"]` (in memory only) | NO — SystemExit before pia:5210 | 1 | rc=1 only; no JSON detail |
| DECLARED_DEPS RuntimeError | nothing | NO — uncaught exception before pia:5210 | uncontrolled | none |
| emit() exception | `summary["feature_errors"][fid]` | YES — pia:5210 runs | 0 (success!) | JSON only; no rc signal |
| extract/reduce exception | `summary["feature_errors"]["extract_{fid}"]` | YES — pia:5210 runs | 0 (success!) | JSON only; no rc signal |

**Key file:line refs**:
- Topo error dict set: `pia:5058`
- Topo SystemExit: `pia:5065`
- DECLARED_DEPS RuntimeError raised: `pia:5077`
- emit() error captured to feature_errors: `pia:5089–5091`
- extract/reduce error captured to _extract_error_*: `pia:2029–2031`
- extract/reduce surfaced to feature_errors: `pia:5098–5106`
- write_summary_json call: `pia:5210`

### §2.7 `summary["feature_errors"]` — does it survive write_summary_json?

`feature_errors` is NOT a `_`-prefixed temp key. The temp-key cleanup at `pia:5115–5117` only removes keys starting with `_`:
```python
for _tmp_key in list(summary.keys()):
    if _tmp_key.startswith("_"):
        summary.pop(_tmp_key, None)
```
`feature_errors` starts with `f`, so it survives the cleanup and is written to disk by `write_summary_json` at `pia:5210`. Confirmed: `feature_errors` persists to JSON for Path 3 (emit errors) and Path 4 (extract errors).

---

## §3 Cluster D — 4 Small Fleet-Plugin Fixes

### §3.1 d1: paylines list string sort wrong for 10+ payline machines

**Exact location**: `payouts_by_spin_type.py:424–436`

Current code (two sort sites):
```python
# Site 1 (trigger marker path — line 424):
paylines: list[dict[str, Any]] = sorted(
    [{"payline_id": pl_id, "hit_count": cnt}
     for pl_id, cnt in pl_map.items()],
    key=lambda x: x["payline_id"],          # ← sorts payline_id as STRING
)

# Site 2 (regular pid path — line 431):
paylines = sorted(
    [{"payline_id": pl_id, "hit_count": cnt}
     for pl_id, cnt in pl_map.items()
     if pl_id != "-1"],
    key=lambda x: x["payline_id"],          # ← sorts payline_id as STRING
)
```

**Input type**: `pl_id` is a string (e.g. `"1"`, `"2"`, `"10"`, `"11"`). String sort produces: `"1", "10", "11", "2", "3"` — incorrect for 10+ paylines. Int sort produces: `1, 2, 3, 10, 11` — correct.

**Exception for `-1` carve-out**: the trigger-marker path includes `"-1"` entries. When sorting as int, `-1` (the scatter line sentinel) must remain sortable. `-1` as int sorts correctly before positive integers.

**Affected machines**: any machine with 10 or more paylines. M14 has ~20 paylines (standard). M275 and M37 are unclear. The brief names M14/M275/M37 as unaffected "so far" — meaning their current data coincidentally sorts correctly under string order OR they have fewer than 10 paylines. Future machines with 10+ paylines will produce wrong sort.

**Consumer of paylines list**: `summary["player_impact"]["payouts_by_spin_type"][label][i]["paylines"]` — read by the frontend for display. No other file reads this sub-field directly (confirmed: no other grep hits for `payline_id` in consumers outside the plugin itself).

**What changes**: both sort sites at `payouts_by_spin_type.py:427` and `payouts_by_spin_type.py:435` — change `key=lambda x: x["payline_id"]` to `key=lambda x: int(x["payline_id"])`.

### §3.2 d2: trigger_target alphabetical-first heuristic (M275 NewFreespin bug)

**Exact location**: `bonus_chain_dynamics.py:204–212`

Current code:
```python
trigger_target: str | None = None
if scatter_marker_pids and scatter_feature_names:
    trigger_target = sorted(scatter_feature_names)[0]   # ← alphabetical first
    trigger_target_confidence = "data_inferred"
elif scatter_marker_pids:
    trigger_target = None
    trigger_target_confidence = "unknown"
```

**What `scatter_feature_names` contains**: names from `all_chains_by_feature` keys that have non-empty `lengths` data. This is written to the stash by the PIA inline F6 block before the emit loop.

**The bug**: for a machine with features `["NormalCollectionSpin", "NewFreespin"]`, alphabetical sort picks `"NewFreespin"` over `"NormalCollectionSpin"`. For M275, the scatter trigger (pid 666) activates `NormalCollectionSpin`, not `NewFreespin`. The alphabetical heuristic picks the wrong feature.

**Where `scatter_marker_pids` comes from**: `ctx.mechanism_registry.scatter_marker_pids` — `bonus_chain_dynamics.py:202`. This is a `frozenset[str]` built by `MechanismRegistry.build()` at `mechanism_registry.py:142–153`. The registry is constructed in PIA main() before the emit loop.

**d3 gap (unique confidence)**: the brief notes that when `len(scatter_feature_names) == 1`, the confidence should be `"unique"` rather than `"data_inferred"`. Currently there is no branch distinguishing the 1-feature vs multi-feature case:

```python
if scatter_marker_pids and scatter_feature_names:
    trigger_target = sorted(scatter_feature_names)[0]   # same whether 1 or N features
    trigger_target_confidence = "data_inferred"          # always "data_inferred"
```

The `"unique"` branch is a dead spec case — the string `"unique"` does not appear anywhere in the codebase (confirmed: no grep hit in `fresh_slotlab/`).

**The d2 fix** (per brief): use `mechanism_registry.scatter_marker_pids` inverse mapping to look up which bonus feature's `first_st` matches the scatter marker's ST. This requires extending the stash or the inference logic to include chain-level first_st data per feature.

**Consumers of `trigger_target`**: only `summary["player_impact"]["payout_ids_top20"][i]["notes"]["trigger_target"]`. No other reader in `fresh_slotlab/` reads this field (confirmed: `trigger_target` only appears in `bonus_chain_dynamics.py` and test files).

**Consumers of `scatter_marker_pids`**:
- `bonus_chain_dynamics.py:202` — in emit(), reads from ctx
- `mechanism_registry.py:89, 142–153, 236, 247` — defined/built/serialized
- `mechanism_registry.py:173, 177` — used during jackpot detection to exclude scatter pids from jackpot set
- No other consumers in `fresh_slotlab/` (confirmed via grep)

### §3.3 d3: trigger_target_confidence "unique" dead spec branch

**Exact location**: `bonus_chain_dynamics.py:208` — the string `"data_inferred"` is always emitted when `scatter_feature_names` is non-empty, regardless of whether there is exactly 1 or multiple features.

**Current branch structure**:
```python
if scatter_marker_pids and scatter_feature_names:
    trigger_target = sorted(scatter_feature_names)[0]
    trigger_target_confidence = "data_inferred"    # ← line 208, always this
elif scatter_marker_pids:
    ...
    trigger_target_confidence = "unknown"
else:
    trigger_target_confidence = None
```

**What changes for d3**: add a sub-branch inside the first `if`:
- `len(scatter_feature_names) == 1` → `trigger_target_confidence = "unique"`
- `len(scatter_feature_names) > 1` → `trigger_target_confidence = "data_inferred"` (existing)

**Test coverage gap**: no existing test asserts the string `"unique"` anywhere. No test file references this confidence level.

### §3.4 d4: avg_bonus_payout None vs 0.0 behavioral delta

**Exact location in PIA inline stash block**: `pia:4817–4825`

```python
"avg_bonus_payout": (
    (
        sum(
            float(e.get("win", 0.0))
            for e in (upstream_feature_tally.get(_cm_bonus_feat) or {}).values()
        ) / total_completed_cycles
        if total_completed_cycles > 0 else None
    ) if _cm_bonus_feat else None
),
```

**Current behavior analysis**:
- `_cm_bonus_feat is None` → `avg_bonus_payout = None` (correct — no bonus feature identified)
- `_cm_bonus_feat is not None` AND `total_completed_cycles == 0` → `avg_bonus_payout = None` (correct — no cycles to average over)
- `_cm_bonus_feat is not None` AND `total_completed_cycles > 0` AND `sum(win) == 0.0` → `avg_bonus_payout = 0.0` (BEHAVIORAL ISSUE — 0.0 is not None, and the correction formula uses this value)

**The 0.0 issue**: `0.0 / total_completed_cycles = 0.0`. This happens when the bonus feature tally has entries but all `e["win"]` values are 0.0. This could indicate a data issue (bonus feature fired but no win tracked in tally) rather than a genuine zero-payout bonus. `None` is more semantically accurate in this case ("not computable") vs `0.0` ("bonus pay exactly zero per cycle").

**Where avg_bonus_payout is consumed**:
- Written to stash: the value goes into the `_collect_mechanic_data` stash dict at `pia:~4817`, then into `summary["collect_mechanic"]["bonus_cycle_correction"]["avg_bonus_payout"]` after `CollectMechanic.emit()` in `collect_mechanic.py:310`.
- Used in `_compute_bonus_correction()` at `parser.py:296, 323, 328`: this function takes `avg_bonus_payout` as a computed local value (not from the stash); the stash's `avg_bonus_payout` is for display only in the summary panel.
- Frontend reads `collect_mechanic.bonus_cycle_correction.avg_bonus_payout` for display.

**The downstream null-safe need**: the brief says "downstream needs null-safe". The `_compute_bonus_correction` function at `parser.py:321` already handles the None/zero case:
```python
if completed_cycles <= 0 or bonus_total_win <= 0:
    return None            # parser.py:322
```
This guard fires before `avg_bonus_payout = bonus_total_win / completed_cycles` at `parser.py:323`. So the correction formula is already null-safe. The display field at `pia:4817` is a separate computation and its `0.0` vs `None` distinction is about accuracy of reporting, not about the correction formula.

**What changes**: add a `and sum(...) > 0` guard so `avg_bonus_payout` returns `None` when the feature tally produces zero total win (even with cycles > 0). This means the schema field is `None` in three cases: no bonus feature, no completed cycles, zero total feature win.

**Note**: this change is in the PIA inline stash-writing block at `pia:4817`, which is pre-emit code. It will be reflected in the stash consumed by `CollectMechanic.emit()` — no change needed to `collect_mechanic.py` itself.

---

## §4 Cluster E — Test Refactor: Dynamic effective_version Assertions

### §4.1 Files with hardcoded effective_version or base_hash hex strings

Grep result: 8 files in `tests/analyzer/` contain 12-char hex patterns:

| File | Hex constant(s) | What is asserted |
|------|----------------|-----------------|
| `test_c3_5_isolation_m275_only.py` | `fa440e3eb5f6` (base_hash), `5c78f3834a1e` (M275 ev), `6aae41144cea` (non-M275 ev) | Hardcoded equality asserts against module output |
| `test_c3_5_m14_no_multiplier_wild.py` | `6aae41144cea` (non-M275 ev at line 241) | Hardcoded string equality; also calls `compute_effective_version_for_machine` dynamically but compares to hardcoded |
| `test_c3_base_hash_flips_for_round_level_enrichment.py` | `b0ba0ce7c7e2` (C2 value), `fa440e3eb5f6` (C3 value) | Asserts current != old AND current == expected |
| `test_c3_5_m275_e2e.py` | `2ef11cd69c8d` (C3.5 value, in docstring) | In test_effective_version_matches_c3_5(): actually uses `compute_effective_version_for_machine("M275", 1)` dynamically — assertion is `actual == expected` where expected is the module output. The hardcoded `2ef11cd69c8d` appears only in the docstring. |
| `test_c6_carve_completion.py` | `fa440e3eb5f6` (base_hash) | Hardcoded equality: `assert actual == "fa440e3eb5f6"` |
| `test_c6_byte_identical_bonus_chain.py` | `fa440e3eb5f6` (base_hash) | Hardcoded equality: `assert actual == "fa440e3eb5f6"` |
| `test_c5_byte_identical_unrelated_fields.py` | `fa440e3eb5f6` (base_hash) | Hardcoded equality: `assert actual == "fa440e3eb5f6"` |
| `test_c1_byte_identical_m14.py` | `90e36d27df98`, `baf56e2f9f6e` (in comment only) | Comment only; the test body calls `compute_effective_version_for_machine("M14", 1)` dynamically |

### §4.2 Detailed per-file breakdown

#### test_c3_5_isolation_m275_only.py

**File**: `tests/analyzer/test_c3_5_isolation_m275_only.py`

Three module-level hex constants (`pia:81, 93, 109` in test file numbering):
```python
_C3_BASE_HASH = "fa440e3eb5f6"                  # line 81
_M275_C3_5_EFFECTIVE_VERSION = "5c78f3834a1e"   # line 93
_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"     # line 109
```

These constants are used in assertions at:
- `test_base_hash_unchanged_from_c3`: `assert _compute_base_hash() == _C3_BASE_HASH` (line ~156)
- `test_m275_effective_version_is_c3_5_value`: `assert ev == _M275_C3_5_EFFECTIVE_VERSION` (line ~199)
- `test_m14_effective_version_unchanged`: `assert ev == _NON_M275_EFFECTIVE_VERSION` (line ~250)
- `test_m37_effective_version_unchanged`: `assert ev == _NON_M275_EFFECTIVE_VERSION` (line ~293)
- `test_m272_effective_version_unchanged`: `assert ev == _NON_M275_EFFECTIVE_VERSION` (line ~314)

The test file already has a helper `_compute_effective_version(machine_id, mode)` at line 126 that calls `compute_effective_version_for_machine`. The assertions compare against hardcoded constants rather than a fresh call to `_compute_effective_version`.

**Comment history on `_M275_C3_5_EFFECTIVE_VERSION`** (lines 83–92): this constant was updated 3 times across C-phases (C3.5 → C4 → C5 → C6) as each new plugin changed M275's hash. The comment block documents the version history.

**Dynamic replacement pattern**: replace the hardcoded equality asserts with calls to the module function, e.g.:
```python
# Old:
assert ev == _M275_C3_5_EFFECTIVE_VERSION
# New (option A — fully dynamic):
expected = _compute_effective_version("M275", 1)
assert ev == expected  # (trivially true — ev IS the return value)
```
But this defeats the purpose: the test would always pass because `ev = _compute_effective_version("M275", 1)` and the assertion compares `ev` to itself. The value of the test is asserting the STRUCTURE of the version (M275 != M14, both are valid hex) + DIFFERENTIAL assertions ("M275 has one more plugin than M14"). The brief mentions "differential assertions: M275 differs from M14 by exactly multiplier_wild contribution."

**Differential assertion shape** (what the test should verify):
- `M275_ev != M14_ev` (isolation)
- `base_hash == compute_base_analyzer_version()` (dynamic, no pin)
- `M14_ev == M37_ev == M272_ev` (they have identical feature sets)
- If any new plugin is added to M275's manifest, `M275_ev` changes (inject-bug still works without hardcoded pin)

#### test_c3_5_m14_no_multiplier_wild.py

**File**: `tests/analyzer/test_c3_5_m14_no_multiplier_wild.py`

One hardcoded hex at line 241:
```python
_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"  # C4 value
```
Used at line 243: `assert actual == _NON_M275_EFFECTIVE_VERSION`

The same test also calls `compute_effective_version_for_machine("M14", 1)` at line 222 for a dynamic comparison in `test_m14_effective_version_matches_versioning_module`. The hardcoded constant is in the SECOND test `test_m14_effective_version_is_c3_non_m275_value` which pins the exact value.

#### test_c3_base_hash_flips_for_round_level_enrichment.py

**File**: `tests/analyzer/test_c3_base_hash_flips_for_round_level_enrichment.py`

Two hex constants:
```python
_C2_BASE_HASH = "b0ba0ce7c7e2"         # line 72 — used in test_base_hash_is_not_c2_value
_EXPECTED_C3_BASE_HASH = "fa440e3eb5f6" # line 77 — used in test_base_hash_matches_expected_c3_value
```

`_C2_BASE_HASH` is used as a "not equal" assertion — checking that the C3 flip happened. This is a historical landmark value; it should NOT be replaced dynamically (it anchors the test's purpose).

`_EXPECTED_C3_BASE_HASH` pins the current expected value. If any C-phase touches core/*.py, this value would change and the test would need updating.

**Note**: this file has a comment at line 77: "Update if parser.py is edited further before C3 commit." This is the exact pattern that Cluster E aims to resolve — the constant needs manual update after every core change.

#### test_c3_5_m275_e2e.py

**File**: `tests/analyzer/test_c3_5_m275_e2e.py`

The hex `2ef11cd69c8d` appears only in the docstring of `test_effective_version_matches_c3_5` (as documentation of the old C3.5 value). The actual assertion is:
```python
expected = compute_effective_version_for_machine("M275", 1)  # dynamic
actual = m275_c3_5_summary.get("effective_analyzer_version", "")
assert actual == expected
```
This test is ALREADY DYNAMIC. No change needed. The hex in the docstring is informational only.

#### test_c6_carve_completion.py

**File**: `tests/analyzer/test_c6_carve_completion.py`

One hardcoded hex at line 114:
```python
assert actual == "fa440e3eb5f6"
```
This is a `base_hash` assertion. `base_hash = compute_base_analyzer_version()` is the `actual`. The assertion pins the expected value as a literal string rather than calling `compute_base_analyzer_version()` on the right-hand side (which would make the test trivially true).

**Purpose of the assertion**: verify that C6 did NOT touch `core/*.py`. If the value changes, someone edited a core file. The hardcoded pin IS the test's signal — a dynamic RHS would remove the signal.

#### test_c6_byte_identical_bonus_chain.py

**File**: `tests/analyzer/test_c6_byte_identical_bonus_chain.py`

Same pattern as `test_c6_carve_completion.py`:
```python
assert actual == "fa440e3eb5f6"   # line 113
```
Same reasoning: base_hash pin is intentional, not an accident.

#### test_c5_byte_identical_unrelated_fields.py

**File**: `tests/analyzer/test_c5_byte_identical_unrelated_fields.py`

Same pattern:
```python
assert actual == "fa440e3eb5f6"   # line 102
```
Same reasoning.

#### test_c1_byte_identical_m14.py

**File**: `tests/analyzer/test_c1_byte_identical_m14.py`

The hex strings `90e36d27df98` and `baf56e2f9f6e` appear only in a comment (line 184) documenting version history. The actual test body is dynamic:
```python
expected = compute_effective_version_for_machine("M14", 1)
```
This file is already dynamic. No change needed.

### §4.3 The actual update-burden problem

Every time a plugin is added or a core file is changed, the following test constants need manual updates:
1. `_M275_C3_5_EFFECTIVE_VERSION` in `test_c3_5_isolation_m275_only.py` — updated 3 times in C-phases (lines 87–92 document history)
2. `_NON_M275_EFFECTIVE_VERSION` in `test_c3_5_isolation_m275_only.py` — same 3 updates
3. `_NON_M275_EFFECTIVE_VERSION` in `test_c3_5_m14_no_multiplier_wild.py` (line 241) — same
4. `_EXPECTED_C3_BASE_HASH` in `test_c3_base_hash_flips_for_round_level_enrichment.py` (line 77) — updates when core changes
5. The three `"fa440e3eb5f6"` base_hash pins in C5/C6 byte-identical tests — update when core changes

Constants 4 and 5 (`base_hash` pins) serve as regression guards against accidental core changes. Making them dynamic defeats their purpose. The brief notes "differential assertions" as the right replacement for effective_version pins (1–3 above).

**Differential assertion pattern** (for effective_version):
```python
# Instead of:
assert compute_effective_version("M275", 1) == "5c78f3834a1e"

# Use:
m275_ev = compute_effective_version("M275", 1)
m14_ev  = compute_effective_version("M14", 1)
assert m275_ev != m14_ev, "M275 and M14 must differ (multiplier_wild is M275-only)"
# And for the 'unique' contribution assertion:
# m275 has one more plugin than m14 — can be verified by manifest inspection
```

**What cannot be made dynamic safely**: the base_hash pin tests. Their entire value is catching the case where someone accidentally modifies `core/*.py`. A dynamic RHS (`actual == compute_base_analyzer_version()`) would always pass even after a core modification.

**What CAN be made dynamic**: the per-machine effective_version pins in `test_c3_5_isolation_m275_only.py` and `test_c3_5_m14_no_multiplier_wild.py` — replace with structural/differential assertions.

---

## §5 Shared vs Per-X Boundary Table

*Delta from C-phase baseline: only rows affected by Carry-forward Round 1 clusters.*

| File / Function | Scope | Changes in Round 1 | Consumers |
|----------------|-------|---------------------|-----------|
| `fresh_slotlab/player_impact_analyzer.py` lines 5042–5065 | Fleet-shared | Cluster A: topo error path — currently exits before JSON write | backend rc=1 handler, subprocess caller |
| `fresh_slotlab/player_impact_analyzer.py` lines 5073–5080 | Fleet-shared | Cluster A: DECLARED_DEPS RuntimeError — currently uncaught | none (unhandled) |
| `fresh_slotlab/player_impact_analyzer.py` lines 5081–5091 | Fleet-shared | Cluster A: emit() errors — currently caught, written to feature_errors, NOT analyzer_init_error | JSON reader |
| `fresh_slotlab/player_impact_analyzer.py` lines 5210 | Fleet-shared | Cluster A: write_summary_json call site — JSON write must precede ANY SystemExit | backend |
| `fresh_slotlab/player_impact_analyzer.py` lines 4817–4825 | Fleet-shared | Cluster D (d4): avg_bonus_payout None vs 0.0 — affects all BCM machines | collect_mechanic display |
| `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` lines 424–436 | Fleet-shared (all manifested machines) | Cluster D (d1): paylines sort key | frontend payouts_by_spin_type panel |
| `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py` lines 204–212 | Fleet-shared (machines declaring bonus_chain_dynamics) | Cluster D (d2+d3): trigger_target + unique confidence | payout_ids_top20 notes |
| `fresh_slotlab/analyzer/topo_sort.py` | Fleet-shared | No code change in Round 1; error types raised here | PIA main() catch block pia:5044 |
| `fresh_slotlab/analyzer/mechanism_registry.py` | Fleet-shared | No code change in Round 1; scatter_marker_pids read by BCD plugin | bonus_chain_dynamics.py:202 |
| `tests/analyzer/test_c3_5_isolation_m275_only.py` | Test-only | Cluster E: 3 hardcoded hex constants to replace with differential asserts | CI |
| `tests/analyzer/test_c3_5_m14_no_multiplier_wild.py` | Test-only | Cluster E: 1 hardcoded hex constant (line 241) | CI |
| `tests/analyzer/test_c3_base_hash_flips_for_round_level_enrichment.py` | Test-only | Cluster E: `_EXPECTED_C3_BASE_HASH` pin — partially dynamic | CI |
| `tests/analyzer/test_c6_carve_completion.py` | Test-only | Cluster E: base_hash pin — intentional (regression guard) | CI |
| `tests/analyzer/test_c6_byte_identical_bonus_chain.py` | Test-only | Cluster E: base_hash pin — intentional | CI |
| `tests/analyzer/test_c5_byte_identical_unrelated_fields.py` | Test-only | Cluster E: base_hash pin — intentional | CI |

---

## §6 Reuse vs Duplication Audit

### Audit finding 1: Three base_hash pin assertions are byte-identical

`test_c5_byte_identical_unrelated_fields.py`, `test_c6_byte_identical_bonus_chain.py`, and `test_c6_carve_completion.py` each contain:
```python
assert actual == "fa440e3eb5f6"
```
with identical surrounding context (import `compute_base_analyzer_version`, call it, compare). They serve the same guard ("C5/C6 did not touch core/*.py"). Currently three independent copies.

**Potential consolidation**: a single shared test in a new file `test_base_hash_invariant.py` would cover all three. However, they each belong to a different C-phase test class, so consolidation would decouple them from the per-phase byte-identical test structure. This is a judgment call for the designer.

### Audit finding 2: Two effective_version helper functions are near-identical

`test_c3_5_isolation_m275_only.py:126–131` defines `_compute_effective_version(machine_id, mode)` calling `compute_effective_version_for_machine`.

`test_c3_5_m275_e2e.py` does the same via inline import at line 451.

`test_c3_5_m14_no_multiplier_wild.py` does the same via inline import at line 218.

All three import the same function from `fresh_slotlab.analyzer.versioning`. No shared helper exists across test files. Each test file rediscovers the import pattern independently.

### Audit finding 3: `trigger_target` inference in bonus_chain_dynamics uses only `scatter_feature_names`

The d2 fix requires using `mechanism_registry.scatter_marker_pids` to map pids → feature. Currently:
- `scatter_marker_pids` is available via `ctx.mechanism_registry.scatter_marker_pids` — `bonus_chain_dynamics.py:202`
- `scatter_feature_names` is from the stash (F6 inline computed values from `all_chains_by_feature`)
- The inference does NOT cross-reference between the two: it only checks if any scatter marker exists, then picks from `scatter_feature_names` alphabetically

A correct inverse mapping would require knowing which `first_st` each chain feature uses, then matching against the scatter marker pid's triggering ST. This data is available in `all_chains_by_feature` entries (each has `first_st` field) but is not currently stashed.

**Grep confirming no other consumer of scatter_marker_pids** (outside mechanism_registry.py itself):
- `bonus_chain_dynamics.py:202` — reads `ctx.mechanism_registry.scatter_marker_pids`
- `mechanism_registry.py:89, 142–153, 173, 177, 236, 247` — defines, builds, and serializes
- No other files in `fresh_slotlab/` reference this attribute

---

## §7 Open Questions

1. **Cluster A: try/finally pattern scope**. The brief proposes `try/finally` in `main()` so `write_summary_json` fires even on `SystemExit`. The Path 2 error (`DECLARED_DEPS RuntimeError`) is currently outside any try block. If `write_summary_json` is moved into a `finally` block, the question is: which lines of `main()` are inside the `try`? The topo-sort block starts at `pia:5042`. All preceding code (chunk accumulation, finalization blocks F1–F9) would need to be INSIDE the try block for the finally to catch errors raised there too. The C-phase map noted that earlier `raise SystemExit()` calls exist at `pia:1083`, `pia:1085`, `pia:1477`, `pia:1595`, `pia:1633`, `pia:1641` — these are pre-summarization exits where no summary has been built yet. The designer must decide the boundary of the try block.

2. **Cluster A: `feature_errors` vs `analyzer_init_error`**. Currently two separate keys with different semantics: `feature_errors[fid]` for per-plugin errors (emit + extract), `analyzer_init_error` for infra-level errors (topo). The brief proposes unifying to `analyzer_init_error` as a top-level key. If so, `feature_errors` becomes a sub-key of `analyzer_init_error`, or `feature_errors` remains separate (runtime errors) and only infra errors go to `analyzer_init_error`. The designer must define the schema.

3. **Cluster A: DECLARED_DEPS RuntimeError exception type**. Currently raises `RuntimeError` (line 5077) while the topo errors are `PluginCyclicDependencyError` / `PluginMissingDependencyError`. If the unified handler catches all three, the catch clause must include `RuntimeError` too, or the DECLARED_DEPS check must raise one of the existing plugin error types (or a new named type).

4. **Cluster D d1: int("-1") edge case**. For trigger-marker paylines (line_id == -1), the `pl_id` string is `"-1"`. `int("-1")` returns `-1` correctly. No exception. But the designer should confirm: are there any other non-integer payline_id strings that could appear in the data? The `payline_id` keys come from `PayoutByPayline` field parsing in parser.py. If a machine sends non-numeric payline IDs, `int(x["payline_id"])` would raise `ValueError`. The fix should include a try/except or a pre-filter.

5. **Cluster D d2: `all_chains_by_feature` first_st availability in stash**. The d2 fix requires knowing which `first_st` each chain feature uses to match against the scatter marker's triggering ST. Currently, the stash at `_STASH_KEY` carries `scatter_feature_names` (a list of feature names) but NOT the `first_st` per feature. To implement the inverse mapping, the stash must be extended OR the inference must use a different signal. The designer must specify what additional data the F6 inline block puts into the stash.

6. **Cluster E: base_hash pin tests — should they be made dynamic?** The three base_hash pin assertions in C5/C6 test files (`"fa440e3eb5f6"`) serve as regression guards. Making them dynamic would remove their value as guards. The brief says "replace with dynamic calls + differential assertions" but this may not apply to base_hash pins (which are intentionally pinned). The designer should specify which hex pins become dynamic vs which remain pinned.

7. **Cluster E: `_C2_BASE_HASH = "b0ba0ce7c7e2"` in test_c3_base_hash_flips**. This pin is a historical anchor — the test asserts `current != C2_value`. Replacing it with a dynamic call would be nonsensical (you can't dynamically compute the C2 value without a git checkout). This value must remain hardcoded. The designer should confirm scope: Cluster E refactor applies only to `effective_version` pins, not all historical hash anchors.

8. **Cluster D d4: which machines set `_cm_bonus_feat` but have zero feature tally win?** The `avg_bonus_payout = 0.0` case fires when `_cm_bonus_feat` is not None (a bonus feature was identified) but `sum(win)` over the feature tally is 0.0. This could happen for machines where the collect mechanic's bonus feature name doesn't match any tally key exactly. The designer should check M11/M14/M37/M272/M275 to see if any currently produce `avg_bonus_payout = 0.0` (as opposed to `None`).
