# 03 — Coupling Audit: Analyzer Unbundle (M275-driven)

> **Date**: 2026-05-25
> **Auditor**: arch-coupling-auditor (W1)
> **Topic dir**: `session_artifacts/_arch_analyzer_unbundle/`
> **Scope trigger**: touches fleet-shared `fresh_slotlab/analyzer/`, changes hash composition, restructures schema fields for 393 live machines × N modes.

---

## §1 Scope

**Directories audited**:
- `fresh_slotlab/player_impact_analyzer.py` (5500+ lines, the monolith)
- `fresh_slotlab/analyzer/versioning.py`
- `fresh_slotlab/analyzer/feature_registry.py`
- `fresh_slotlab/analyzer/manifest_loader.py`
- `fresh_slotlab/analyzer/rtp_integrity.py`
- `fresh_slotlab/analyzer/features/*.py` (4 plugin files)
- `fresh_slotlab/analyzer/core/*.py` (6 files: `__init__.py`, `_utils.py`, `aggregator.py`, `base_pipeline.py`, `parser.py`, `writer.py`)
- `fresh_slotlab/round_classification.py`
- `fresh_slotlab/round_win.py`
- `fresh_slotlab/trigger_sessions.py`
- `fresh_slotlab/post_inference.py`
- `fresh_slotlab/machine_md5.py`
- `slot_designer/configs/machine_manifests/*.json` (420 files, 419 manifest + 1 schema)
- `configs/machines.json` (422 machine entries, 393 with `available` field)
- `configs/machine_round_win_rules.json`
- `src/web_console/frontend/app.js`, `pure.js`, `compare_diff.js`, `index.html`
- `src/web_console/backend/app.py`
- `src/web_console/backend/_batch_gen_worker.py`
- `reports/*/mode_*/versions/*/player_impact_summary.json` (336 existing on disk)
- `reports/*/mode_*/{index.json, latest.json}`

**Fleet baseline at audit time**:
- 422 machine entries in `machines.json`; 393 with `available` flag
- 420 manifest files; 419 proper manifests + 1 schema file
  - 253 non-variant (fully populated) manifests
  - 166 variant manifests (`inherits_from` set)
  - 1 schema file (`manifest_schema.json`)
- 336 `player_impact_summary.json` files across 305 machine report dirs

---

## §2 Fleet-Shared Symbol Table

### 2.1 Versioning Surface

---

#### Symbol 1: `compute_base_analyzer_version`
**Module**: `fresh_slotlab/analyzer/versioning.py:48`

**What it hashes**: every `*.py` file in `fresh_slotlab/analyzer/core/` in sorted alphabetical order, concatenated as raw bytes, SHA-256, truncated to 12 hex chars. Currently hashes 6 files:
```
__init__.py, _utils.py, aggregator.py, base_pipeline.py, parser.py, writer.py
```

**Direct callers**:
- `fresh_slotlab/analyzer/versioning.py:184` — called inside `compute_effective_version_for_machine`
- `tests/backend/test_analyzer_core_aggregator.py:114` — test-only (import smoke + reference check)
- `tests/backend/test_analyzer_core_base_pipeline.py:34` — test-only

**Transitive consumers** (via `compute_effective_version_for_machine` → `compute_effective_analyzer_version`):
- `fresh_slotlab/player_impact_analyzer.py:4284` — stamps `summary["effective_analyzer_version"]`; written to every `player_impact_summary.json`
- 336 on-disk `player_impact_summary.json` files, field `effective_analyzer_version`
- `reports/*/mode_*/latest.json` (14-key file includes `effective_analyzer_version`)
- `reports/*/mode_*/index.json` (per-run list entries include `effective_analyzer_version`)
- `src/web_console/backend/app.py:2392,2438` — SQLite `runs` table column `effective_analyzer_version`; also read by backfill loop

**Blast radius (computed)**:
- Change any single file in `core/*.py` → `compute_base_analyzer_version` flips → `compute_effective_analyzer_version` flips for ALL 393 machines × all modes → all 336 existing reports become "stale" (historical, not current) from the perspective of `effective_analyzer_version` matching.

**Breakage mode**: `cache-invalidation` — reports are not deleted; they remain readable. The `is_current` predicate in `app.py:7568` uses `(config_md5, code_md5)` pairing, not `effective_analyzer_version`, so UI does not break. But any logic comparing `effective_analyzer_version` against the current value (e.g. freshness badges in `app.js:343–347`) will show all 336 reports as stale.

**Migration sensitivity**: `rename-safe` (pure Path arithmetic, no external schema). Adding a new `.py` file to `core/` changes the hash even if file content is empty. Removing a file also changes it. Renaming a file in `core/` changes the sorted order and therefore the hash even with identical bytes.

---

#### Symbol 2: `compute_effective_analyzer_version`
**Module**: `fresh_slotlab/analyzer/versioning.py:202`

**Composition algorithm** (verbatim from source):
```
h = sha256(base_hash)
for fid in sorted(set(machine_features)):
    h.update(b"\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
if mode is not None:
    h.update(b"\x00mode=" + str(mode).encode())
return h.hexdigest()[:12]
```

**Input dimensions**:
1. `base_hash` — 12-hex from `compute_base_analyzer_version()` (all of `core/*.py`)
2. `feature_hashes[fid]` — 12-hex from `AnalyzerFeature.compute_hash()` for each feature the machine declares
3. `machine_features` — list from `manifest["analyzer_features"]` (currently identical for all 253 non-variant machines: `["bankruptcy_simulation", "multiplier_profile", "payouts_by_spin_type", "reel_marginal_by_spin_type"]`)
4. `mode` — integer mode number, included in the digest

**Direct callers**:
- `fresh_slotlab/analyzer/versioning.py:194` — called inside `compute_effective_version_for_machine`
- `tests/backend/test_analyzer_foundation.py:582,600,617,623,644,650,666,672,691` — 9 direct test invocations

**Transitive consumers**:
- `fresh_slotlab/player_impact_analyzer.py:4284` — `_summary_effective_analyzer_version` stamped to summary
- `summary["effective_analyzer_version"]` → `reports/.../player_impact_summary.json` (275 of 336 have a non-empty value; 6 have empty string; 55 pre-Phase-3 are absent)
- `src/web_console/backend/app.py:2438` — backfill reads `summary.get("effective_analyzer_version")`; writes to SQLite `runs.effective_analyzer_version`
- `reports/*/mode_*/latest.json:effective_analyzer_version` — consumed by `app.js:343–347` (freshness badge)
- `reports/*/mode_*/index.json` — consumed by backend run-list endpoints

**Blast radius (quantified)**:
- Change to ANY `core/*.py` → base_hash flips → `effective_analyzer_version` changes for ALL 393 machines × all modes (because base_hash is in every machine's composition).
- Change to a single feature plugin (e.g. `payouts_by_spin_type.py`) → only machines declaring that feature are affected. Currently: all 253 non-variant machines declare all 4 features, so one plugin change affects 253 machines' versions (each mode separately).
- Adding a new feature to `machine_manifests/M275.json["analyzer_features"]` → M275's version changes; no other machine affected. **This is the surgical invalidation the architecture intends.**

**Breakage mode**: `cache-invalidation`. Report files remain on disk; summary JSON readable. The `effective_analyzer_version` mismatch surfaces as a "stale" indicator in UI, not a hard failure.

**Migration sensitivity**: `behavior-stable` for current consumers (they treat it as an opaque 12-char string). `schema-bump-required` if the composition algorithm itself changes (e.g. adding a new dimension like per-machine inference config hash) because old and new values are not comparable.

---

#### Symbol 3: `compute_analyzer_version` (legacy)
**Module**: `fresh_slotlab/player_impact_analyzer.py:1007`

**What it hashes**: the entire `player_impact_analyzer.py` source file as raw bytes, SHA-256, 12-hex truncated.

**Direct callers**:
- `fresh_slotlab/player_impact_analyzer.py:4260` — `_summary_analyzer_version = compute_analyzer_version()`
- `tests/backend/test_stale_count.py:68,107,139` — 3 test call sites (import + call)
- `tests/backend/test_versions_plumbing.py:23,24,31` — test call + smoke

**Landing fields**:
- `summary["analyzer_version"]` → `player_impact_summary.json` (332 of 336 on-disk summaries have it; 4 pre-date it)
- `reports/*/mode_*/latest.json:analyzer_version`
- `reports/*/mode_*/index.json` — per-run entries include it
- SQLite `runs.analyzer_version` — `app.py:1996` (column schema), `app.py:2391` (SELECT), `app.py:2437` (backfill read)

**Frontend consumers**:
- `app.js:83` — `currentVersions: { analyzer_version: "", machines: {} }` — used to compare run freshness
- `app.js:343–347` — freshness check: `run.analyzer_version && cvAnalyzer && run.analyzer_version === cvAnalyzer`
- `pure.js:2061` — `curAnalyzer` for staleness detection in `summarizeRunEvent`
- `compare_diff.js` — consumed (grep hit in file)

**Blast radius**:
- Any edit to `player_impact_analyzer.py` (including comments) flips `analyzer_version`. All 336 on-disk reports were built with one version; a PIA edit marks them all stale in the UI freshness badge.
- This is intentionally broad ("any edit → false-stale is cheap to resolve"). The new `effective_analyzer_version` is the surgical replacement.

**Migration sensitivity**: `rename-safe` — field name `"analyzer_version"` is hardcoded in `latest.json`, `index.json`, SQLite schema, `app.py`, `app.js`, `pure.js`. The brief explicitly states this field is kept for backward-compat.

---

#### Symbol 4: `AnalyzerFeature.compute_hash`
**Module**: `fresh_slotlab/analyzer/features/_base.py:190`

**What it does**: reads `sys.modules[cls.__module__].__file__` → hashes that file's bytes → returns 12-hex. Each subclass hashes its own plugin `.py` source file.

**Current 4 implementations**:
| Plugin class | File | FEATURE_ID |
|---|---|---|
| `PayoutsBySpinType` | `features/payouts_by_spin_type.py` | `"payouts_by_spin_type"` |
| `ReelMarginalBySpinType` | `features/reel_marginal_by_spin_type.py` | `"reel_marginal_by_spin_type"` |
| `BankruptcySimulation` | `features/bankruptcy_simulation.py` | `"bankruptcy_simulation"` |
| `MultiplierProfile` | `features/multiplier_profile.py` | `"multiplier_profile"` |

**Callers of `compute_hash()`**:
- `fresh_slotlab/analyzer/versioning.py:192` — `feature_hashes = {f.FEATURE_ID: f.compute_hash() for f in registry.ALL_FEATURES}` — called inside `compute_effective_version_for_machine`

**Effect on `effective_analyzer_version`**:
- Changing `payouts_by_spin_type.py` (e.g. Pattern A → B): hash of that plugin flips → `effective_analyzer_version` changes for all 253 machines that declare `"payouts_by_spin_type"` (currently all 253 non-variant machines).
- Since all 4 features are declared by all 253 machines identically, changing ANY of the 4 plugin files invalidates 253 machines' `effective_analyzer_version`.

**Migration sensitivity**: `behavior-stable` for the hash contract. Adding a new plugin class requires the new class to be importable and registered before `compute_effective_version_for_machine` is called — otherwise the manifest declares a feature ID for which no hash exists and a `KeyError` is raised at line `versioning.py:254`.

---

### 2.2 Plugin / Registry Surface

---

#### Symbol 5: `feature_registry.ALL_FEATURES`
**Module**: `fresh_slotlab/analyzer/feature_registry.py:63`

**Populated by**: module-import time `register()` calls in each plugin file. Currently populated only when one of these is imported:
- `fresh_slotlab/analyzer/features/payouts_by_spin_type.py:65` — `register(PayoutsBySpinType())`
- `fresh_slotlab/analyzer/features/bankruptcy_simulation.py:143` — `register(BankruptcySimulation())`
- `fresh_slotlab/analyzer/features/multiplier_profile.py:72` — `register(MultiplierProfile())`
- `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py:65` — `register(ReelMarginalBySpinType())`

**Silent dependency (import-time side effect)**: `ALL_FEATURES` starts EMPTY at module import. It is populated only when the plugin module is imported. If `compute_effective_version_for_machine` is called before importing the plugin modules, `feature_hashes` will be `{}`, and all machines' `effective_analyzer_version` will equal just `sha256(base_hash + "\x00mode=N")[:12]` — silently wrong, no error.

**Who triggers the imports**:
1. `fresh_slotlab/analyzer/versioning.py:165–176` — manually imports all 4 plugins inside `compute_effective_version_for_machine`
2. `fresh_slotlab/player_impact_analyzer.py:4816–4827` — manually imports all 4 plugins before invoking `feature.emit()`
3. `scripts/validate_manifests.py:43–47` — imports all 4 plugins at module top

**Readers of `ALL_FEATURES`**:
- `fresh_slotlab/analyzer/versioning.py:192` — hash computation loop
- `fresh_slotlab/analyzer/feature_registry.py:154` — `get_features_for_machine` fallback (stub behavior when `manifest=None`)
- `fresh_slotlab/player_impact_analyzer.py:4830` — `for _feature in ALL_FEATURES: _feature.emit(None, summary)`
- `fresh_slotlab/analyzer/manifest_loader.py:622,648,664` — `validate_manifest` reads `registry.ALL_FEATURES` for Rules 2, 4, 5, 8

**Blast radius**:
- If a new plugin is registered but NOT imported before `compute_effective_version_for_machine`, its hash is silently absent → `effective_analyzer_version` computed without it → wrong version for all machines that declare that feature ID.
- `ALL_FEATURES` is a mutable module-level list. Tests must save/restore it (seen in `test_analyzer_foundation.py:844–850`). In production: since plugins are imported once per process, mutation during the process lifetime is the only risk.

**Migration sensitivity**: `behavior-stable` for the list-append contract. Renaming `ALL_FEATURES` would break 4 direct read sites.

---

#### Symbol 6: `get_features_for_machine`
**Module**: `fresh_slotlab/analyzer/feature_registry.py:112`

**Call sites**: tests only (`test_analyzer_foundation.py:1004,1029,1047,1063,1084`). The symbol is not called in production PIA code — PIA calls `ALL_FEATURES` directly at line 4830, then invokes `emit()` unconditionally on all registered features without manifest filtering.

**Implication**: The registry's manifest-based filtering (`get_features_for_machine`) is currently unused in the production path. The emit loop (`for _feature in ALL_FEATURES: _feature.emit(None, summary)`) runs ALL registered features for ALL machines, regardless of what the manifest declares. This is safe today because all 253 non-variant machines declare the same 4 features — but if a new feature is added to `ALL_FEATURES` and only some machines declare it, the emit loop will call that feature's `emit()` on machines that don't declare it, which is a silent logic error.

**Breakage mode if Pattern B promotes a feature**: `silent-wrong-result` — the emit runs even for machines that don't declare the feature.

**Migration sensitivity**: `signature-stable`. The function signature is unlikely to change. The behavior gap (unused in production) is the real risk.

---

#### Symbol 7: `AnalyzerFeature.{extract, reduce, emit}` ABC
**Module**: `fresh_slotlab/analyzer/features/_base.py:119,144,169`

**Current state of 4 implementations**:
| Plugin | Pattern | extract | reduce | emit |
|---|---|---|---|---|
| `PayoutsBySpinType` | A (scaffold) | no-op `return {}` | no-op | asserts key in `summary["player_impact"]` |
| `ReelMarginalBySpinType` | A (scaffold) | no-op `return {}` | no-op | asserts key in `summary["player_impact"]` |
| `BankruptcySimulation` | B (logic extracted) | no-op | no-op | reads `_bankruptcy_rows` temp key, writes `bankruptcy_simulation` + `bankruptcy_probe`, deletes temp keys |
| `MultiplierProfile` | A (scaffold) | no-op `return {}` | no-op | asserts key in `summary["player_impact"]` |

**Existing inline aggregation that a Pattern B promotion would need to absorb**:
- `payouts_by_spin_type`: built inline in PIA at lines 3306–3349 from accumulators `payout_id_win`, `payout_id_win_by_spin_type_total`, `payout_id_by_spin_type_total`, `spin_type_spins`, `spin_type_paid_bet`, `effective_bet_for_rtp`, `_st_label`. The Pattern A emit asserts this key is already present in `summary["player_impact"]` — it does NOT write it.
- `reel_marginal_by_spin_type`: built inline from `symbol_counts_by_col_by_spin_type_total` accumulators (referenced in PIA around lines 3380-3420). Same Pattern A emit guard.
- `multiplier_profile`: built inline as `player_impact["multiplier_profile"]` around PIA line 4329–4337 from `multiplier_bucket_rows`, `tail_*` vars. Pattern A emit guard.

**Double-computation risk if Pattern A → B**:
- When a plugin's `emit()` is promoted to Pattern B and takes over writing the key, PIA's inline block must be removed. If both remain (PIA inline + plugin emit), the result is the last writer wins — currently plugin emit runs after the summary dict is constructed, so the plugin would overwrite PIA's inline value. For Pattern B plugins, this is the intent; for Pattern A scaffolds it is a no-op assertion.

**Migration sensitivity**: `schema-bump-required` (SCHEMA_VERSION ClassVar must be bumped when emit shape changes). `signature-stable` for the ABC itself.

---

### 2.3 Aggregation Surface (PIA inline)

---

#### Symbol 8: `payout_id_win`, `payout_id_hits`, `payout_id_by_spin_type_total`, `payout_id_win_by_spin_type_total`

**Declaration** (PIA `main()` body):
- `payout_id_hits`: `fresh_slotlab/player_impact_analyzer.py:1280` — `defaultdict(int)`
- `payout_id_win`: `fresh_slotlab/player_impact_analyzer.py:1281` — `defaultdict(float)`
- `payout_id_by_spin_type_total`: line 1282 — `defaultdict(lambda: defaultdict(int))`
- `payout_id_win_by_spin_type_total`: line 1286 — `defaultdict(lambda: defaultdict(float))`

**Reduce path** (chunk merge loop, lines 1725–1747):
- `payout_id_hits[str(pid)] += int(c)` (from each chunk record's `payout_id_hits`)
- `payout_id_win[str(pid)] += float(w)` (from each chunk record's `payout_id_win`)
- `payout_id_by_spin_type_total[str(pid)][_st_int] += int(cnt)` (from `payout_id_by_spin_type`)
- `payout_id_win_by_spin_type_total[str(pid)][_st_int] += float(win_val)` (from `payout_id_win_by_spin_type`, added 2026-05-14)

**Emission path** — these accumulators feed:
1. `payout_id_rows` list (lines 3224–3290) → `summary["player_impact"]["payout_ids_top20"]`
2. `payouts_by_spin_type` dict (lines 3306–3349) → `summary["player_impact"]["payouts_by_spin_type"]`
3. `rtp_integrity.py:_get_payout_id_win()` / `_get_payout_id_hits()` / `_get_payout_id_by_spin_type_total()` — L1/L2/L3/L4 integrity gate (dual-layout support)

**Downstream summary keys written**:
- `summary["player_impact"]["payout_ids_top20"]` — list of dicts with: `payout_id`, `hit_count`, `hit_rate`, `total_win`, `avg_win_when_hit`, `rtp_contribution_pp`, `spin_type_category`, `dominant_spin_type`, `spin_type_breakdown`
- `summary["player_impact"]["payouts_by_spin_type"]` — dict of spin-type-label → list of row dicts (same field names as payout_ids_top20 for renderer reuse)

**Frontend consumers**:
- `app.js:4789` — reads `s.player_impact.payout_ids_top20`
- `pure.js:1288` — same key
- `app.js:5385–5386` — reads `summary.player_impact.payouts_by_spin_type`

**Backend consumers**:
- `app.py:5567` — `"payout_ids_top20": pi.get("payout_ids_top20")`
- `rtp_integrity.py` — Layer 1: `sum(payout_id_win.values()) == chunk_win_total`; Layer 2: prefix check on keys; Layer 3: anchor hit check; Layer 4: dispatch comparison

**Blast radius**: Any rename or restructuring of these 4 accumulators affects:
- PIA inline (3 separate aggregation blocks)
- `core/parser.py:parse_chunk_response` (which populates per-chunk records that PIA merges)
- `rtp_integrity.py` dual-layout extraction helpers
- Frontend renderer at `app.js` and `pure.js`
- `app.py` LLM API endpoint at line 5567
- All 336 on-disk `player_impact_summary.json` files via field name change

**Migration sensitivity**: `schema-bump-required`. Field names in `payout_ids_top20` row dicts are consumed by frontend JS directly. Renaming `hit_count` → `hits` would break `app.js:4789` and `pure.js:1288` without coordinated JS update.

---

#### Symbol 9: `payouts_by_spin_type`
**Declaration**: local dict in PIA `main()` at line 3306.
**Written to summary**: `summary["player_impact"]["payouts_by_spin_type"]` at line 4436.

**Reads at build time**:
- `payout_id_win` (master accumulator)
- `payout_id_win_by_spin_type_total` (per-ST win totals)
- `payout_id_by_spin_type_total` (per-ST hit counts)
- `spin_type_spins`, `spin_type_paid_bet` (per-ST denominators)
- `effective_bet_for_rtp` (global denominator for `rtp_contribution_pp`)
- `_st_label` (maps ST int → `"ST{N}_{behavior}"` string key)

**Frontend consumers**:
- `app.js:5385–5386` — reads for ST-split payout panel; `5440` — notes that trigger-marker rows have no "%" sign since `payouts_by_spin_type` rows don't carry `rtp_pct`

**Backend consumers**:
- `app.py:5557` (no direct hit on `payouts_by_spin_type` key — confirmed absent from grep; the field is present in summary written to disk and read by frontend directly via `/api/runs/{id}/summary`)

**RTP integrity gate**: NOT directly read by `rtp_integrity.py`. The integrity gate uses `payout_ids_top20` (nested layout) or `payout_id_win` (flat layout) — not `payouts_by_spin_type`.

**Blast radius**: Field schema change (e.g. adding `shape`, `cols`, `paylines`, `notes` as called out in Brief gap #7) affects `app.js:5385` rendering logic. Since `app.js` renders this with its own rendering block (not `_renderPayoutRowsHtml` exactly — `5349` comment says "field names intentionally match `payout_ids_top20` schema"), adding new fields is additive; removing existing fields would break the renderer.

**Migration sensitivity**: `rename-safe` for the top-level key `payouts_by_spin_type`. Row field additions are additive. Row field renames require coordinated JS update.

---

#### Symbol 10: `payout_ids_top20` / `payout_groups_top20`
**Written to summary**: `summary["player_impact"]["payout_ids_top20"]` (line 4428), `summary["player_impact"]["payout_groups_top20"]` (line 4427).

**Consumers**:
- `app.js:4789,4799` — primary pay_id panel renderer
- `pure.js:1241,1284,1288` — `payout_groups_top20` (fallback) and `payout_ids_top20`
- `app.py:5567` — LLM API: `"payout_ids_top20": pi.get("payout_ids_top20")`
- `app.py:2760` — comment mentioning comparison against `payout_ids_top20[*].avg_win_when_hit`
- `rtp_integrity.py` (nested layout): `_get_payout_id_win()` reads `player_impact.payout_ids_top20[*].total_win`, `_get_payout_id_hits()` reads `hit_count`, `_get_payout_id_by_spin_type_total()` reads `spin_type_breakdown`

**Note**: Despite the `_top20` suffix, as of 2026-05-12 truncation was removed (PIA line 4419–4426 comment). The field name is preserved for backward compat with old reports and LLM prompts that hardcode the key.

**Migration sensitivity**: Field name `payout_ids_top20` is load-bearing across 5 consumers. The `spin_type_breakdown` sub-field (list of `{spin_type, count}`) is specifically consumed by `rtp_integrity.py:_get_payout_id_by_spin_type_total()`. Removing or renaming it breaks Layer 4.

---

#### Symbol 11: `_st_label`, `_st_behavior`
**Declaration**: `_st_behavior` at PIA line 3219; `_st_label` at PIA line 3302.
**Scope**: local temp dicts in `main()`, not written to summary.

**`_st_behavior`** — maps `{st_int: "paid"|"free"|"mixed"}` — consumed by:
- Line 3251: `st_behavior = _st_behavior.get(int(dominant_st), "mixed")` — feeds `category` field in `payout_id_rows`
- Line 3251 leads to `"spin_type_category": category` in `payout_ids_top20` rows

**`_st_label`** — maps `{st_int: "ST{N}_{behavior}"}` — consumed by:
- Line 3307: outer loop `for st_int, label in sorted(_st_label.items())`
- Line 3319: inner loop to pull wins from `payout_id_win_by_spin_type_total` by ST
- Produces `payouts_by_spin_type` dict keys (the ST labels are the dict keys)
- Line 3384 (implied): same label set drives `reel_marginal_by_spin_type` construction

**Downstream summary fields depending on `_st_label` / `_st_behavior`**:
- `payout_ids_top20[*].spin_type_category` (`"paid"`, `"bonus"`, `"mixed"`)
- `payout_ids_top20[*].dominant_spin_type`
- `payouts_by_spin_type` — the keys of this dict are the `_st_label` values
- `reel_marginal_by_spin_type` — keys are also ST labels (verified by `reel_marginal_by_spin_type.py:emit()` comment referencing PIA line 4383)

**Blast radius**: If the labeling convention `"ST{N}_{behavior}"` changes, the keys of `payouts_by_spin_type` and `reel_marginal_by_spin_type` change → frontend JS at `app.js:5385,5524` iterates these dicts and renders per-key panels; the iteration is order-preserving but the key strings may be shown in UI labels.

**Migration sensitivity**: `behavior-stable` for the two-dict pattern. Renaming the label format (e.g. `"ST140_paid"` → `"paid_ST140"`) is a schema change.

---

### 2.4 Manifest Surface

---

#### Symbol 12: `slot_designer/configs/machine_manifests/M*.json`

**Fleet statistics** (from grep audit of 420 files):
| Field | Count (of 419 proper manifests) |
|---|---|
| `machine_id` | 419 |
| `manifest_version` | 419 |
| `inherits_from` | 419 (field present; 166 non-null, 253 null) |
| `modes` | 419 |
| `_generator_notes` | 419 |
| `console_diagnostic_complete` | 253 (non-variant only) |
| `layer4_applicable` | 253 (all `true`; `false` = 0) |
| `spin_type_convention` | 253 |
| `trigger_session_pattern` | 253 (all `null`) |
| `analyzer_features` | 253 (all identical: 4-feature set) |
| `rtp_integrity_contract` | 253 |
| `bcm_target_feature` | 0 (field exists in schema, but no manifest carries it yet) |

**Feature set distribution**: 100% of the 253 non-variant manifests declare exactly the same 4 features: `["bankruptcy_simulation", "multiplier_profile", "payouts_by_spin_type", "reel_marginal_by_spin_type"]`. There is no machine-specific feature variation today.

**Fields read by each consumer**:

| Field | Reader | Where |
|---|---|---|
| `analyzer_features` | `versioning.py:191` | hash composition input |
| `analyzer_features` | `feature_registry.py:156` | `get_features_for_machine` filter |
| `analyzer_features` | `manifest_loader.py:622,648,664` | Rules 2/4/5/8 validation |
| `console_diagnostic_complete` | `manifest_loader.py:700,716,752` | Rule 6/8 validation |
| `console_diagnostic_complete` | `rtp_integrity.py:631` | `completeness_declared` field |
| `console_diagnostic_complete` | `app.py:7403` | `/api/manifests/review-state` endpoint |
| `inherits_from` | `manifest_loader.py:156,161,175` | `resolve_inheritance` |
| `inherits_from` | `versioning.py:186` | variant cascade check |
| `inherits_from` | `app.py:7402,7409` | variant detection in review-state |
| `layer4_applicable` | `rtp_integrity.py:655–662` | Layer 4 gate |
| `trigger_session_pattern` | `rtp_integrity.py:661` | Layer 4 gate (derives `layer4_applicable` when field absent) |
| `trigger_session_pattern` | `manifest_loader.py:481,801` | `resolve_layer4_applicable` + Rule 11 |
| `rtp_integrity_contract` | `rtp_integrity.py:314` | `_get_required_attribution_anchors` |
| `rtp_integrity_contract` | `manifest_loader.py:731` | Rule 7 (non-empty `expected_paid_st`) |
| `spin_type_convention` | `manifest_loader.py:770` | Rule 9 (rawdata cross-check) |
| `per_mode_overrides` | `manifest_loader.py:291–350` | `resolve_per_mode` |
| `modes_supported` | `manifest_loader.py:667` | Rule 5 mode coverage |
| `_generator_notes` | `manifest_loader.py:605` | Rule 1 template exclusion |
| `_generator_notes` | `app.py:7395,7397,7404` | review-state endpoint |
| `round_win_rules` | `manifest_loader.py:637` | Rule 3 structural check |

**Silent dependency**: `app.py:7378` resolves `manifests_root` as a hardcoded relative path from `app.py`'s `__file__`. Moving the manifests directory would break the review-state endpoint without a code change.

**Migration sensitivity**: `schema-bump-required` for any new required field. Adding optional fields is additive. Renaming `analyzer_features` would break 4 consumers. The `_generator_notes.synthetic_template` boolean is the sole mechanism to exclude template-only manifests from Rule 1 validation and the review-state endpoint.

---

#### Symbol 13: `manifest_loader.{load_manifest, resolve_inheritance, resolve_per_mode}`
**Module**: `fresh_slotlab/analyzer/manifest_loader.py`

**`load_manifest`**:
- `fresh_slotlab/player_impact_analyzer.py:4875` — called in the RTP integrity gate setup
- `fresh_slotlab/analyzer/versioning.py:186` — called inside `compute_effective_version_for_machine`
- `scripts/validate_manifests.py:94` — fleet validation

**`resolve_inheritance`**:
- `fresh_slotlab/player_impact_analyzer.py:4877` — called after `load_manifest` when `inherits_from` is set
- `fresh_slotlab/analyzer/versioning.py:187` — called after `load_manifest`
- `scripts/validate_manifests.py:96`

**`resolve_per_mode`**:
- `fresh_slotlab/player_impact_analyzer.py:4878` — applied for `args.rtp_mode`
- `fresh_slotlab/analyzer/versioning.py:189` — applied for the mode argument
- `manifest_loader.py:669` — called internally by Rule 5 validation

**Blast radius**: All 3 functions are called in both the production PIA path (lines 4875–4878) and the versioning path (versioning.py:185–189). A signature change propagates to 4+ call sites. A behavior change (e.g. resolving a different field in `resolve_per_mode`) propagates to all 253 machines' version hashes and integrity gate results.

**Migration sensitivity**: `signature-stable`. The `manifests_dir: Path` parameter means the root path must be known at call time — this is computed at module-top as `_CORE_DIR = Path(__file__).parent / "core"` equivalent in versioning.py lines 181–182.

---

#### Symbol 14: `rtp_integrity.py`
**Module**: `fresh_slotlab/analyzer/rtp_integrity.py`

**Manifest fields consumed**:
- `manifest["layer4_applicable"]` (line 655) — gates Layer 4
- `manifest["trigger_session_pattern"]` (lines 661, 665) — derives `layer4_applicable` if field absent
- `manifest["rtp_integrity_contract"]["required_attribution_anchors"]` (via `_get_required_attribution_anchors()`) — Layer 3 anchor list
- `manifest["console_diagnostic_complete"]` (line 631) — populates `completeness_declared`

**Called from**:
- `fresh_slotlab/player_impact_analyzer.py:4851,4881` — in the post-summary-build integrity gate block. This is the only production call site.
- `fresh_slotlab/analyzer/rtp_integrity.py:843` — CLI `main()` for operator direct use

**Summary dict fields consumed** (nested layout via `_get_*` helpers):
- `summary["rtp"]["our_total_win"]` — Layer 1 total
- `summary["player_impact"]["payout_ids_top20"][*].total_win` — Layer 1 sum
- `summary["player_impact"]["payout_ids_top20"][*].hit_count` — Layer 3 anchor check
- `summary["player_impact"]["payout_ids_top20"][*].spin_type_breakdown` — Layer 4 Step A dispatch table

**Output landing in summary**:
- `summary["rtp_integrity_check"]` — dict with 12 fields (PIA lines 4884–4897)

**Blast radius**: If `payout_ids_top20` is renamed or restructured, Layer 1/2/3/4 break because `rtp_integrity.py` reconstructs all data from that field in nested-layout mode. This is the primary coupling risk for any payout ID schema change.

**Migration sensitivity**: `behavior-stable` for the 4-layer check. `schema-bump-required` if the output `rtp_integrity_check` sub-dict structure changes (consumed by frontend and backend).

---

#### Symbol 15: Manifest review state — `/api/manifests/review-state`
**Module**: `src/web_console/backend/app.py:7350`

**Manifest fields consumed**: `console_diagnostic_complete`, `_generator_notes.synthetic_template`, `_generator_notes.config_not_reviewed`, `inherits_from`, `machine_id`

**Generator script**: `scripts/generate_machine_manifests.py` (scope: not audited in detail; produces the 253 non-variant + 166 variant manifests in `slot_designer/configs/machine_manifests/`)

**Frontend consumer**: Not confirmed as a direct JS consumer from grep (no `manifests/review-state` hit in `app.js`); likely polled by a route or catalog page (out of scope for this grep pass).

**Blast radius**: Renaming `console_diagnostic_complete` → any other field would silently make `verified` return `False` for all 393 machines in the review-state endpoint. This is a `silent-wrong-result` mode because the endpoint returns `{}` for errors, not an exception.

---

### 2.5 Inference / Config Surface

---

#### Symbol 16: `round_classification.{detect_cycle_peak, is_wild_nudge_round}`

**Imported into production paths**:
- `fresh_slotlab/player_impact_analyzer.py:47–50` (and duplicate at 84–87) — top-level dual-path import
- `fresh_slotlab/analyzer/core/parser.py:71,79` — imported for use inside `parse_chunk_response`

**`detect_cycle_peak`** — call sites:
- `core/parser.py:1152` — `_cycle_peak_for_ctx = detect_cycle_peak(rounds)` — called once per robot-response during chunk parsing
- `core/parser.py:1727` (comment mentions `robot_cycle_peak comes from detect_cycle_peak`)
- `round_classification.py:383` — self-reference inside `at_cycle_peak_indices`

**`is_wild_nudge_round`** — call sites:
- `core/parser.py:1562` — `if is_wild_nudge_round(r):`
- `core/parser.py:1604` — `_is_wild_nudge_for_chain = is_wild_nudge_round(r)`
- `fresh_slotlab/player_impact_analyzer.py:3459` (comment references it)

**Other `round_classification` symbols** (NOT currently imported by PIA or parser):
- `attribute_lines_to_pay_ids` — called in `scripts/infer_paytable.py:66,628` (outside the analyzer pipeline)
- `parse_payline_records` — called in `round_classification.py:262` internally and tests only
- `infer_bcm_target_spin_type` — called in `scripts/infer_bcm_pairing.py:67,144` (outside the analyzer pipeline)
- `_detect_cycle_anchor_st` — no external callers found outside `round_classification.py` itself

**Blast radius**: `detect_cycle_peak` is called once per robot-response in `parse_chunk_response`. Any change to its return type or semantics propagates to all `collect_mechanic` panel outputs for BCM machines (M272 family, M275, etc.). `is_wild_nudge_round` affects the `chain_spins` counting for the `bonus_chain_dynamics` panel.

**Migration sensitivity**: `behavior-stable` for the current call signature `(rounds: list) -> int | None`. Any change to the return value semantics (e.g. returning a tuple instead of int) requires coordinated update in both `parser.py` and `player_impact_analyzer.py`.

---

#### Symbol 17: `round_win.{extract_round_win, extract_round_payouts}` + `RoundWinRule` subclasses
**Module**: `fresh_slotlab/round_win.py`

**Config**: `configs/machine_round_win_rules.json` — 2 active rules:
- `bcm_cycle_anchor_m274`: type `bcm_cycle_anchor`, applies to `["M274"]`
- `topdollar_selector_settlement`: type `settlement_winamount`, applies to 12 machines (`M12/M15/M90/M132` × 3 variants each)

**Production call sites**:
- `fresh_slotlab/player_impact_analyzer.py:4,1121` — `load_rules_for_machine(args.machine, _rules_config)` at startup
- `fresh_slotlab/analyzer/core/parser.py:72–84` — import only (the parser uses `RoundWinRule`, `extract_round_payouts`, `extract_round_win` inside `parse_chunk_response`)

**`load_rules_for_machine`**: reads `configs/machine_round_win_rules.json` at PIA startup (line 1119), silently returns `[]` on parse error or machine not in `applies_to`.

**Blast radius**: Adding a new rule to `machine_round_win_rules.json` for machine X affects:
- X's `payout_id_win` distribution (wins re-attributed to different pay_ids)
- X's `rtp_integrity_check.layer1_invariant_ok` (must still hold after re-attribution)
- X's `payouts_by_spin_type` and `payout_ids_top20` panels

**Migration sensitivity**: `behavior-stable` for the `RoundWinRule` base class contract. The `configs/machine_round_win_rules.json` schema (dict keyed by rule_id, with `type`, `params`, `applies_to`) is consumed only by `load_rules_for_machine` — a single function.

---

#### Symbol 18: `post_inference.run_post_analyzer_inference`
**Module**: `fresh_slotlab/post_inference.py:88`

**Production call sites**:
- `src/web_console/backend/_batch_gen_worker.py:73,235,237` — called after each PIA subprocess completes; writes inferred paytable shape + classifier results into the summary

**What it infers**: paytable shape (symbol set, payline topology, wild positions) — per `session_artifacts/_impl/STATUS.md` and the paused multiplier inference state.

**Blast radius**: Currently called on every completed run for all 393 machines. It mutates `player_impact_summary.json` in place (or writes a sidecar). Any schema change to what it writes affects all future summaries.

**Migration sensitivity**: `behavior-stable` for the function signature. The output schema is not part of the `effective_analyzer_version` hash — it operates post-PIA and its outputs are not version-stamped in the same way.

---

#### Symbol 19: `trigger_sessions.compute_trigger_sessions`
**Module**: `fresh_slotlab/trigger_sessions.py:131`

**Production call sites**:
- `fresh_slotlab/analyzer/core/parser.py:70` — imported; called inside `parse_chunk_response` for trigger-session machines
- `fresh_slotlab/player_impact_analyzer.py:37–39` — dual-path import at module top

**SpinType binding semantics**: win on bonus spins is attributed to the triggering paid spin. This affects `payout_id_win` accumulator for trigger-session machines (M272, etc.). The `layer4_applicable: false` manifest flag gates whether Layer 4 cross-checks trigger-session routing.

**Blast radius**: Any change to trigger-session win attribution logic affects:
- `payout_id_win` for all trigger-session machines
- `effective_bet_for_rtp` denominator logic (already accounts for this)
- Layer 1 invariant (`sum(payout_id_win) == chunk_win_total`) — must still hold

**Migration sensitivity**: `behavior-stable` for current signature. A signature change requires coordinated update in both `parser.py` and `player_impact_analyzer.py` (2 call-site locations).

---

## §3 Hash Composition Map

### 3.1 `config_md5` / `code_md5` (machine config hash)

**Source**: `configs/machines.json` fields `configSummaryMd5` / `codeSummaryMd5` per machine entry (422 entries). Stamped upstream by the engine/deployment pipeline; not computed in this codebase.

**Computed by**: `fresh_slotlab/machine_md5.py:lookup_machine_md5()` for real machines; `slot_designer/core/backend/machine_version.py:compute_machine_md5_for_mode()` for virtual machines (reads `machines_virtual.json`).

**Consumers**:
- `fresh_slotlab/player_impact_analyzer.py:4259` — `_lookup_machine_md5(args.machine)` → `summary["config_md5"]`, `summary["code_md5"]`
- `fresh_slotlab/batch_dev_sampler.py:184` — `config_md5, code_md5 = _lookup_machine_md5(machine)` — passed as CLI flags to PIA subprocess
- `reports/*/mode_*/latest.json:rawdata_config_md5, rawdata_code_md5`
- `reports/*/mode_*/index.json[*].rawdata_config_md5, rawdata_code_md5`
- `rawdata/*/mode_*/_chunks.json:chunks[*].cfg_md5, code_md5` — chunk sidecar, used by `select_replay_chunks_by_md5` to filter matching chunks
- `src/web_console/backend/app.py:333,394,2391,2435,2449–2453` — SQLite `runs` table columns; also in `BatchRunRequest` schema
- `src/web_console/frontend/app.js:343–347` — freshness badge (compares run's config/code md5 vs current)
- `src/web_console/frontend/pure.js:2043–2044` — same freshness comparison
- `src/web_console/frontend/compare_diff.js` — comparison mode uses md5 to bucket runs

**Invalidation radius**: If `configs/machines.json` is updated with new `configSummaryMd5` or `codeSummaryMd5` for machine X, existing reports for X become "historical" (their stored config/code md5 no longer matches the current value). This is the intended mechanism — rawdata from old config is stale.

**Granularity note** (per `feedback_md5_granularity_and_stamping.md`): `lookup_machine_md5` returns a single `(config_md5, code_md5)` pair per machine, not per mode. Per-mode granularity is provided only for virtual machines via `compute_machine_md5_for_mode`. This means adding a new mode to a real machine does not change the hash for other modes.

### 3.2 `analyzer_version` (legacy PIA hash)

**Computed by**: `compute_analyzer_version()` at `player_impact_analyzer.py:1007`
**Inputs**: entire `player_impact_analyzer.py` source file bytes
**Consumers**: 332 of 336 on-disk summaries; `latest.json`; `index.json`; SQLite `runs.analyzer_version`; `app.js:343–347`; `pure.js:2061`; `compare_diff.js`

**Invalidation scope**: Any edit to `player_impact_analyzer.py` (including whitespace) changes the hash → all 336 reports appear stale for this dimension. This is by design; it is broad but cheap to recover (re-run from cache).

### 3.3 `effective_analyzer_version` (per-machine surgical hash)

**Computed by**: `compute_effective_analyzer_version()` at `versioning.py:202`
**Input dimensions**:
| Dimension | Source | Scope change |
|---|---|---|
| `base_hash` | sha256 of `core/*.py` (6 files) | Flips for ALL 253 machines when any core file changes |
| Feature hashes (×4) | sha256 of each plugin `.py` | Flips only for machines declaring that feature |
| `machine_features` list | `manifest["analyzer_features"]` | Changes when machine's manifest is updated |
| `mode` | integer mode argument | Per-mode uniqueness |

**Consumers**: 275 of 336 on-disk summaries have non-empty value; `latest.json`; `index.json`; SQLite `runs.effective_analyzer_version`; `app.js:83,343–347`

**Current state**: Because all 253 non-variant machines declare the same 4 features, adding a new machine-specific feature to M275's manifest changes only M275's `effective_analyzer_version`. This is the surgical invalidation property the architecture intends, but it only works once feature sets diverge.

---

## §4 Silent Dependencies Inventory

### 4.1 Module-Level Globals

| Global | Module | Type | Risk |
|---|---|---|---|
| `ALL_FEATURES` | `feature_registry.py:63` | `list[AnalyzerFeature]` | Starts EMPTY. Not populated until plugin modules are imported. Calling `get_features_for_machine` or reading `ALL_FEATURES` before importing plugins returns empty list → silently wrong version hashes and no `emit()` calls. |
| `_CORE_DIR` | `versioning.py:45` | `Path` | Computed at import as `Path(__file__).parent / "core"`. If `versioning.py` is moved, the `core/*.py` discovery fails with `FileNotFoundError`. |
| `_REPO_ROOT` | `machine_md5.py:38` | `Path` | `Path(__file__).resolve().parent.parent`. Moving `machine_md5.py` breaks the `configs/machines.json` auto-discovery. |
| `_DEFAULT_MANIFEST_ROOT` | `player_impact_analyzer.py` | `Path` | Computed from `__file__` — auto-discovers `slot_designer/configs/machine_manifests/`. If PIA or that directory moves, the manifest load silently falls back to `{}`. |
| `_DEFAULT_MACHINES_CONFIG` | `machine_md5.py:42` | `Path` | Same pattern for `configs/machines.json`. |

### 4.2 File-Path Conventions (Silent Structural Coupling)

| Convention | Readers | Risk if changed |
|---|---|---|
| `reports/<M>/mode_<N>/versions/<rv_id>/player_impact_summary.json` | `app.py:2418` (backfill), `rtp_integrity.py:917–938` (CLI auto-discovery), `app.py:7568` (run list) | Changing the directory structure breaks the CLI auto-discovery and backfill loop. |
| `reports/<M>/mode_<N>/latest.json` | `app.py` (multiple endpoints), `app.js` (freshness) | If `latest.json` is renamed or restructured, all freshness checks break. |
| `reports/<M>/mode_<N>/index.json` | `app.py` (run history list) | Same. |
| `rawdata/<M>/mode_<N>/_chunks.json` | `chunk_index.py:get_chunks_index`, `base_pipeline.py:select_replay_chunks_by_md5` | Sidecar name is hardcoded. |
| `rawdata/<M>/mode_<N>/chunk_*.json` | `base_pipeline.py:select_replay_chunks_by_md5`, `rtp_integrity.py:_run_layer4_step_b` | Glob pattern `chunk_*.json` is hardcoded. |
| `slot_designer/configs/machine_manifests/` | `versioning.py:182`, `player_impact_analyzer.py` (_DEFAULT_MANIFEST_ROOT), `app.py:7377–7379`, `scripts/validate_manifests.py:MANIFEST_DIR` | 4 independent path computations pointing to the same directory. Moving it requires updating all 4. |
| `configs/machines.json` | `machine_md5.py:42`, `scripts/validate_manifests.py:MACHINES_JSON`, `app.py` | 3+ independent `machines.json` path computations. |
| `configs/machine_round_win_rules.json` | `player_impact_analyzer.py:1117` | Hardcoded relative path from `__file__`. |

### 4.3 Import-Time Side Effects

| Effect | Where | Risk |
|---|---|---|
| `register(PayoutsBySpinType())` | `features/payouts_by_spin_type.py:65` | Mutates `ALL_FEATURES` on import. Safe (idempotent), but order-dependent. |
| `register(BankruptcySimulation())` | `features/bankruptcy_simulation.py:143` | Same. |
| `register(MultiplierProfile())` | `features/multiplier_profile.py:72` | Same. |
| `register(ReelMarginalBySpinType())` | `features/reel_marginal_by_spin_type.py:65` | Same. |
| Pattern A `emit()` asserts | `payouts_by_spin_type.py:53–58`, `multiplier_profile.py:55–65`, `reel_marginal_by_spin_type.py:53–58` | `assert` statements in `emit()` — these fire at runtime, not import time. But if PIA calls `emit()` before populating `summary["player_impact"]["payouts_by_spin_type"]`, they raise `AssertionError`, crashing the summary build. |
| `summary["_bankruptcy_rows"]` temp key | `bankruptcy_simulation.py:104` | `BankruptcySimulation.emit()` reads a temp key set by PIA's main() at line 4811. If the emit loop runs before this stash, `KeyError` at line 104. This is a hidden ordering contract: PIA must set temp keys before calling the feature loop. |

### 4.4 Schema Version Fields (SCHEMA_VERSION ClassVar)

All 4 current plugins have `SCHEMA_VERSION = 1`. The `REGISTERED_FALLBACK_RULES` ClassVar is `{}` for all 4 (no fallback rules defined). This means:
- No backward-compatibility rendering is currently possible for historical summaries if a plugin bumps its schema version.
- `REGISTERED_FALLBACK_RULES` is defined in `_base.py` but not yet consumed by any production code — the frontend renderer registry referenced in `_base.py:115` ("Wave 2e RTP gate reads this") is listed in the original `04_v5` as Phase 4 / deferred.

---

## §5 Invalidation Case Studies

### Case Study A: Add a new core module `fresh_slotlab/analyzer/core/mechanism_registry.py`

**Change**: Create `mechanism_registry.py` in `core/` with 0 bytes initially.

**Direct effect**: `compute_base_analyzer_version()` hashes 7 files instead of 6 → `base_hash` changes.

**Cascade**:
1. `base_hash` flips → `compute_effective_analyzer_version()` produces new value for every machine/mode
2. All 253 machines × all modes get new `effective_analyzer_version` values
3. All 275 on-disk summaries with non-empty `effective_analyzer_version` become "historical"
4. `app.js:343–347` freshness badge shows all reports as potentially stale
5. SQLite `runs.effective_analyzer_version` rows have old values; new runs produce new values; the backfill loop does NOT re-run (it only fills NULL rows)
6. No hard failure — reports remain readable; UI freshness indicators change

**Machines affected**: 393 (all declared machines)
**Reports affected**: 275 (those with non-empty `effective_analyzer_version`)
**Hard failures**: None
**Operator-visible breakage**: Freshness badges flip

---

### Case Study B: Promote `payouts_by_spin_type` from Pattern A to Pattern B

**Change**: Modify `features/payouts_by_spin_type.py` so that `extract()` does per-round work and `emit()` writes `summary["player_impact"]["payouts_by_spin_type"]` instead of asserting it.

**Direct effect**: `AnalyzerFeature.compute_hash()` returns a different 12-hex value for `PayoutsBySpinType` because the source file bytes changed.

**Cascade**:
1. Feature hash for `"payouts_by_spin_type"` flips
2. `compute_effective_analyzer_version` produces new value for all 253 machines that declare `"payouts_by_spin_type"` (currently all 253)
3. All 275 on-disk summaries with `effective_analyzer_version` become stale
4. PIA's inline block at lines 3306–3349 must be REMOVED; if not, both PIA-inline and plugin.emit() write the key → last writer wins (plugin.emit() runs after summary dict construction, so it overwrites PIA's value)
5. PIA must REMOVE the Pattern A emit assertion from `PayoutsBySpinType.emit()`
6. Pattern A emit asserts `"payouts_by_spin_type" in player_impact` — if PIA removes the inline build but forgets to change the plugin, the assert fires → `AssertionError` → report build crashes

**Double-count risk**: If PIA inline is NOT removed and plugin `emit()` writes the same key, the frontend renders whichever was written last. The Pattern A assert becomes incorrect (it would succeed even if the plugin's data is different).

**Machines affected**: 253 (those declaring the feature)
**Reports affected**: 275 (those with `effective_analyzer_version`)
**Hard failures**: Potential `AssertionError` if transition is incomplete
**RTP invariant**: Must verify `sum(payouts_by_spin_type[*][*].rtp_contribution_pp)` still converges with `summary.rtp.point_pct` after the move.

---

### Case Study C: Add new manifest field `mechanism_portrait` to M275.json

**Change**: Add a new top-level key `mechanism_portrait: { "jackpot": [...], "freespin": [...] }` to `slot_designer/configs/machine_manifests/M275.json`.

**Direct effect**: `load_manifest("M275", root)` returns a dict with the new key. Consumers that read it: currently none (no code reads `mechanism_portrait` from the manifest). Validation: `validate_manifest` runs 11 rules — none of them check for unknown keys (there is no `additionalProperties: false` enforcement in the Python code, only in the JSON schema file `manifest_schema.json`).

**Cascade**:
1. `compute_effective_version_for_machine("M275", mode=1)` calls `manifest.get("analyzer_features")` — unaffected (new field is not in `analyzer_features`)
2. `effective_analyzer_version` for M275 does NOT change (the hash is not derived from arbitrary manifest content, only from `analyzer_features` list)
3. No reports become stale

**Implication**: Manifest fields beyond `analyzer_features`, `per_mode_overrides`, and the inheritance/validation fields are INVISIBLE to the version hash. Adding `mechanism_portrait` to a manifest does not trigger a re-run. This is the correct behavior if the new field is operator-provided config (not analyzed code), but it means a plugin consuming `mechanism_portrait` at run time would produce different results without the `effective_analyzer_version` reflecting the change.

**Migration sensitivity**: If a new plugin reads `mechanism_portrait` from the manifest AND the field controls report output, the hash composition must be extended to include manifest non-feature-list fields (a new dimension: `manifest_config_hash`).

---

### Case Study D: Rename `payout_ids_top20` to `payout_id_summary` in the summary schema

**Change**: Change the key written at PIA line 4428 from `"payout_ids_top20"` to `"payout_id_summary"`.

**Consumer breakage**:
| Consumer | File:Line | Breakage mode |
|---|---|---|
| `app.js` | `4789` — `s.player_impact.payout_ids_top20` | `undefined` → empty payout panel |
| `pure.js` | `1288` — `s.player_impact.payout_ids_top20` | Same |
| `app.py` | `5567` — `pi.get("payout_ids_top20")` | `None` → LLM API returns null for payout field |
| `rtp_integrity.py` | `_get_payout_id_win()`, `_get_payout_id_hits()`, `_get_payout_id_by_spin_type_total()` | Nested layout extraction reads `player_impact.payout_ids_top20` → returns empty → Layer 1 fails (sum=0 ≠ chunk_win_total) for all new reports |
| 336 on-disk summaries | n/a | Old summaries have `payout_ids_top20`; new summaries have `payout_id_summary` → UI shows no data for new runs; `rtp_integrity_check` in new summaries shows L1 FAIL |

**Blast radius quantified**: Immediate hard failure for ALL new reports' Layer 1 check. All 336 existing reports remain readable under old key. Frontend shows empty payout panel for all new runs. This is a `compile-fail` equivalent — the rename cannot go undetected.

**Estimated total invalidation scope**: 393 machines × N modes (all new reports) + 5 consumer files requiring coordinated update.

---

### Case Study E: Change `detect_cycle_peak` to return `None` instead of `0` when no cycle found

**Change**: `round_classification.py:detect_cycle_peak()` currently returns `0` (or some sentinel) when no cycle is detected. Changing it to return `None` affects callers.

**Consumer breakage**:
| Consumer | File:Line | Breakage mode |
|---|---|---|
| `core/parser.py:1152` | `_cycle_peak_for_ctx = detect_cycle_peak(rounds)` | Downstream code that does `if _cycle_peak_for_ctx:` passes for `0` but also for `None`; code that does `_cycle_peak_for_ctx == 0` would fail to match |
| `core/parser.py:1727` | Comment references `robot_cycle_peak` usage | BCM cycle peak stored per-robot; aggregated into `all_cycle_peaks` list |
| `player_impact_analyzer.py` | Collects `cycle_peaks` from chunk records, computes median | If `None` values are in `all_cycle_peaks`, `sorted(all_cycle_peaks)[len//2]` would raise `TypeError` (comparing `None` vs `int`) |

**Blast radius**: All machines that have BCM mechanics (cycle peaks observed). The `collect_mechanic.bonus_cycle_correction.detected_cycle_length` field in the report would become `None` or crash. For M250/M260/M264/M268/M274/M279/M11 (BCM Tier-1 hard family per Brief §3), this affects correct cycle length detection.

**Migration sensitivity**: `behavior-stable` — changing the sentinel value requires coordinated update in 2 files.

---

## §6 Fragility Hotspots (Top 10 by Fan-Out)

Ranked by: (number of distinct consumer files) × (criticality of the contract), informational only.

| Rank | Symbol | Module | Direct callers | Transitive consumers | Estimated invalidation radius | Primary risk |
|---|---|---|---|---|---|---|
| 1 | `compute_base_analyzer_version` | `versioning.py:48` | 1 production + 2 test | ALL 253 machines × modes via `effective_analyzer_version` | 275 on-disk reports go stale; all future reports get new version | Adding any file to `core/` invalidates entire fleet |
| 2 | `payout_ids_top20` (schema key) | PIA:4428 → summary | `app.js:4789`, `pure.js:1288`, `app.py:5567`, `rtp_integrity.py` (nested layout), `compare_diff.js` | 336 on-disk summaries; all future reports; Layer 1/2/3/4 integrity gate | 5 consumer files require coordinated update; `rtp_integrity` Layer 1 fails for all new reports if renamed | Most connected schema key in the system |
| 3 | `ALL_FEATURES` (module global) | `feature_registry.py:63` | 3 production import sites (PIA, versioning, validate_manifests) | `compute_effective_version_for_machine`, feature `emit()` loop, manifest validation | Silent wrong version if populated out of order; wrong emit coverage if new plugin not imported | Empty-by-default + 3 independent import trigger sites = ordering risk |
| 4 | `compute_effective_analyzer_version` | `versioning.py:202` | 1 production (via `compute_effective_version_for_machine`) + 9 test | 253 machines × modes → 275 on-disk summary stamps + SQLite + `latest.json` + `index.json` | Any composition change invalidates 275 reports | Hash composition is contract — any dimension change is a breaking change |
| 5 | `analyze_features` manifest field | 253 manifest files | `versioning.py:191`, `feature_registry.py:156`, `manifest_loader.py` Rules 2/4/5/8 | All 253 machines' `effective_analyzer_version` | Changing which features a machine declares changes its `effective_analyzer_version` and which plugin `emit()` calls run | Only hook from manifests into version hash — all other manifest content is version-invisible |
| 6 | `detect_cycle_peak` + `is_wild_nudge_round` | `round_classification.py:311,138` | `core/parser.py:1152,1562,1604` | All BCM machines' `collect_mechanic.bonus_cycle_correction`, `bonus_chain_dynamics` panels | BCM family (~33 machines) affected on any semantics change | Called inside inner chunk-parse loop — performance-sensitive; semantics change = fleet-wide BCM report drift |
| 7 | `manifest_loader.{load_manifest,resolve_inheritance,resolve_per_mode}` | `manifest_loader.py` | PIA (3 calls), `versioning.py` (3 calls), `scripts/validate_manifests.py` (3 calls) | All 253 machine manifests + 166 variant manifests | Signature/behavior change propagates to 6 call sites across 3 modules | Shared by both the version hash path and the integrity gate path |
| 8 | `compute_trigger_sessions` | `trigger_sessions.py:131` | `core/parser.py:70`, `player_impact_analyzer.py:37,76` | All trigger-session machines' `payout_id_win` attribution; Layer 4 skip gate | All trigger-session machines affected on semantics change | Win attribution logic — errors are silent (Layer 4 is skipped for these machines) |
| 9 | `payouts_by_spin_type` (summary key + accumulator chain) | PIA:3306–3349 | `app.js:5385`, `rtp_integrity` (indirectly via `payout_ids_top20`) | 253 machines × modes | Pattern A → B transition has ordering risk (temp key contract, PIA inline removal) | Accidental coupling: 5 accumulators feed 1 output; all must be migrated together |
| 10 | `BankruptcySimulation.emit()` temp key contract | `bankruptcy_simulation.py:104` | PIA:4811 (stash) → PIA:4830 (emit loop) | `summary["bankruptcy_simulation"]`, `summary["bankruptcy_probe"]` for 253 machines | KeyError if ordering violated; `bankruptcy_probe` is a back-compat alias consumed by `app.py:4699` and `app.js:6069` | Hidden ordering contract between PIA and feature plugin; not enforced by type system |

---

## §7 Report / Cache Surface

### 7.1 Existing on-disk summary schema (backward-compat surface)

From inspection of 336 `player_impact_summary.json` files, 50-file sample:

**Keys present in 50/50 samples** (must not be removed without fallback rendering rule):
- `summary["analyzer_version"]` — 50/50
- `summary["player_impact"]["bankruptcy_simulation"]` — 50/50
- `summary["player_impact"]["bankruptcy_probe"]` — 50/50 (back-compat alias)
- `summary["player_impact"]["multiplier_profile"]` — 50/50
- `summary["player_impact"]["payout_ids_top20"]` — 50/50

**Keys present in 43/50 samples** (newer, may be absent in older reports):
- `summary["player_impact"]["payouts_by_spin_type"]` — 43/50
- `summary["player_impact"]["reel_marginal_by_spin_type"]` — 43/50
- `summary["effective_analyzer_version"]` — 43/50

**Keys absent in 55 of 336 on-disk summaries**:
- `summary["effective_analyzer_version"]` — absent in pre-Phase-3 reports

### 7.2 `reports/<M>/mode_<N>/{index.json, latest.json, versions/*}`

**`latest.json`** — 14 keys (verified from M14/mode_1 inspection):
```
report_version, run_id, created_at, summary_file, report_file,
rtp_point_pct, achieved_rtp_pct, achieved_halfwidth_pp, total_spins,
quality_label, rawdata_config_md5, rawdata_code_md5,
analyzer_version, effective_analyzer_version
```
**Consumers**: `app.js` freshness comparison; `app.py` run-list endpoints; SQLite backfill

**`index.json`** — list of same 14-key objects, one per historical run.

**SQLite `runs` table**: columns include `analyzer_version` (TEXT, nullable) + `effective_analyzer_version` (TEXT, nullable, added via `ALTER TABLE` in Phase 3). Schema is ALTER-TABLE extended — old rows have NULL for the newer column. The backfill loop populates nulls on next startup.

**Recovery path if schema key disappears**: The `summary_file` path is stored in SQLite. If `player_impact_summary.json` is missing a key that `app.py` reads with `.get("key")`, the result is `None`, not an exception — the UI renders `None` silently. The only hard failure is if `rtp_integrity.py` reads a missing key and fails its Layer 1 check (which would surface as `rtp_integrity_check.passed: False` in the summary).

### 7.3 Chunk envelope `_chunks.json` sidecar

**Schema** (verified from live sidecar):
- `_version`, `_updated_at`
- `chunks`: `{filename → {idx, cfg_md5, code_md5, spin_times, robot_count, saved_at, size_bytes}}`
- `by_md5`: inverted index `{(cfg_md5|code_md5) → [filenames]}`
- `by_config_id`: additional index

**Tie to analyzer version**: chunk entries do NOT store `analyzer_version` or `effective_analyzer_version`. Chunks are keyed by `(cfg_md5, code_md5)` — the machine config hash. A change to the analyzer code does NOT invalidate chunks (chunks are rawdata, not report data). The `select_replay_chunks_by_md5` in `base_pipeline.py` filters by machine config md5 only.

**Rebuild-from-cache path**: if `effective_analyzer_version` changes (e.g. due to a plugin update), the system does NOT delete chunks. The operator re-runs the report generation from existing chunks with the new analyzer code. This is the correct behavior per `feedback_md5_is_a_tag_not_a_destruction_signal.md`.

---

## §8 Summary Statistics

| Metric | Count |
|---|---|
| Shared symbols audited (§2) | 19 |
| Hash/version stamps mapped (§3) | 3 (`config_md5`/`code_md5`, `analyzer_version`, `effective_analyzer_version`) |
| Silent dependencies surfaced (§4) | 4 module globals + 8 file-path conventions + 4 import-time side effects + 4 SCHEMA_VERSION gaps |
| Invalidation case studies (§5) | 5 |
| Top fragility hotspot | `compute_base_analyzer_version` (fan-out: ALL 253 machines × modes invalidated per any `core/*.py` change) |
| On-disk reports at risk per fleet-wide change | 275–336 depending on the change |
| Manifest files processed | 419 (420 minus schema file) |
| Round-win rules in config | 2 (applies to 13 machines) |
