# Coupling / Blast-Radius Audit — Wave 1

Auditor: arch-coupling-auditor (Wave 1, parallel with arch-mapper + arch-taxonomist).
Date: 2026-05-15.
Spec contract: `session_artifacts/_arch/00_brief.md`.
Role definition: `.claude/agents/arch-coupling-auditor.md`.

This document answers a single question for every shared / fleet-wide function in the production
pipeline: **"If you touch this, exactly which downstream consumers go stale?"** Numbers are
ground-truthed from grep, AST walks of the actual source, and `sqlite3` queries of the live state DB
(`state/console/console.db`) — not inferred. File:line references throughout.

No design opinions. Top-N fan-out tables are informational, not prescriptive.

---

## §1 Scope

Directories audited:

- `fresh_slotlab/` — production analyzer + sampling + round classification + round-win rules
  (9 modules, 22,154 LoC, dominated by `player_impact_analyzer.py` at 8,176 LoC).
- `slot_designer/core/backend/` — virtual-console MD5 hashing + registry + delegator analyzer
  (`machine_version.py`, `virtual_app.py`, `virtual_registry.py`, `virtual_analyzer.py`).
- `slot_designer/core/engine/` + `slot_designer/core/emitter/` — 11 shared files that feed every
  virtual machine's `code_md5`.
- `slot_designer/machines/<M>/plugins/**` — per-machine plugin trees (6 machines: M1, M15, M37,
  M31, M43, M279; of these M1 + M37 are base-only with no plugin dir).
- `src/web_console/backend/` — FastAPI app (`app.py` 8,927 LoC, plus 5 helper modules).
- `src/web_console/frontend/` — `app.js` (7,917 LoC), `pure.js` (2,158 LoC), `index.html`,
  `compare_diff.js`.
- `configs/machines.json` — 421-entry fleet registry (not 393 as brief stated — see §3 for the
  current numbers).
- `slot_designer/configs/machines_virtual.json` — 6-entry virtual registry.
- `reports/<M>/mode_<N>/{index.json, latest.json, versions/*/player_impact_summary.json}` — used
  as ground truth for "what fields the frontend currently consumes" and to corroborate the schema
  rename evidence in §5.

Out-of-scope per brief §2: per-machine specs / weights (`slot_designer/machines/<M>/{spec.json,
weights/, reel_strips.json}`) and `MachineBuilder/` xlsx pipeline.

---

## §2 Fleet-shared symbol table

**Table key**: "Direct callers" = distinct files that grep finds importing or calling the symbol
across the **primary file set** (audit scope above). "Transitive consumers" = downstream artifacts
that change when the symbol's behavior changes — reports, cached chunks, registry entries.
"Estimated invalidation radius" = upper bound of machines whose data goes stale on edit, derived
from the hash-composition map in §3.

### 2.1 — `fresh_slotlab/round_win.py`

| Symbol | Module:line | Direct callers (files) | Transitive consumers | Estimated invalidation radius |
|---|---|---|---|---|
| `RoundWinRule` (ABC) | `round_win.py:102` | analyzer, round_win, trigger_sessions (3 files) | every report that emits per-pay_id attribution = **all 278 machines with historical reports** | API change ⇒ analyzer + 13 rule-using machines (M274, M12$* / M15$* TopDollarSelector variants) silently regress; non-rule machines unaffected if signature held |
| `SettlementWinAmountRule` | `round_win.py:163` | analyzer, round_win, trigger_sessions | M12/M15 TopDollarSelector variants (12 entries in `configs/machine_round_win_rules.json`) | 12 variants |
| `SynthesizePayIdRule` | `round_win.py:230` | analyzer, round_win, trigger_sessions | machines needing pay_id synthesis (no active config rule today; available for future use) | 0 today; opt-in via config |
| `BCMCycleAnchorRule` | `round_win.py:345` | analyzer, round_win, trigger_sessions | M274 (only machine in `applies_to` for `bcm_cycle_anchor_m274`) | 1 (M274) |
| `extract_round_win` | `round_win.py:430` | analyzer (14 occurrences), trigger_sessions (6), round_win (3) | EVERY chunk-parse path: `parse_chunk_response`, bankruptcy sim, trigger sessions — i.e. every report's RTP, every per-pay_id attribution | **Universal**: change ⇒ flip `analyzer_version` ⇒ 2030 completed runs across 1007 (machine,mode) pairs flagged stale_analyzer |
| `extract_round_payouts` | `round_win.py:451` | analyzer (4), round_win (5), trigger_sessions (3) | per-pay_id attribution; `payout_ids_top20`; the rule fallback path `verify_payid_invariant.py` watches | Universal — same blast as `extract_round_win` |
| `extract_round_trigger_anchor` | `round_win.py:481` | round_win (2), trigger_sessions (4) | M274 BCM cycle anchor only; M12/M15 settlement anchors via SettlementWinAmountRule | 13 machines (currently rule-bearing) |
| `round_has_credited_win` | `round_win.py:524` | round_win (1), trigger_sessions (5) | trigger session double-count guard for ALL machines | Universal — wrong filter ⇒ wrong rtp_contribution_pp for every report |
| `load_rules_for_machine` | `round_win.py:557` | analyzer (3), round_win (1) | analyzer subprocess at module main() | Universal hot path |

### 2.2 — `fresh_slotlab/round_classification.py`

| Symbol | Module:line | Direct callers | Transitive consumers | Estimated invalidation radius |
|---|---|---|---|---|
| `is_paid_round` | `round_classification.py:104` | round_classification (4), round_win (3), trigger_sessions (7) | CostCredits>0 paid-vs-bonus split; every aggregate `rtp` and per-ST split | Universal |
| `get_collect_count` | `round_classification.py:118` | round_classification (4) | BCM cycle detection (M274, M260, M268, etc.) | ~25 BCM-feature machines (estimate from `is_wild_nudge_round` reference list) |
| `is_wild_nudge_round` | `round_classification.py:138` | analyzer (6), round_classification (2) | 25 (machine,mode) pairs identified by the 2026-04-27 fleet investigation (M279/M226/M149/M140/M26/M51/M256 and others) | ~25 pairs ⇒ ~7 distinct machines + variants |
| `extract_authoritative_pay_ids` | `round_classification.py:172` | round_classification (2) | `attribute_lines_to_pay_ids` path = every report's payline-to-payid attribution | Universal |
| `parse_payline_records` | `round_classification.py:192` | round_classification (2) | payline parsing for analyzer summary | Universal |
| `attribute_lines_to_pay_ids` | `round_classification.py:232` | round_classification (2), analyzer call site | per-pay_id attribution for ~70% of fleet (direct suffix-match path); affects edge cases for M120/M139/M279 | Universal (with fleet-wide path branches) |
| `detect_cycle_peak` | `round_classification.py:311` | analyzer (4), round_classification (5), round_win (2), trigger_sessions (1) | BCM cycle peak detection | ~25 BCM machines |
| `at_cycle_peak_indices` | `round_classification.py:378` | round_classification (1) | helper internal to BCM logic | ~25 BCM machines |
| `infer_bcm_target_spin_type` | `round_classification.py:394` | round_classification (3) | M274-style BCM ST-mapping | M274 specifically; structure exists for other BCM machines |

### 2.3 — `fresh_slotlab/player_impact_analyzer.py` (selected — full file is 8,176 LoC)

| Symbol | Module:line | Direct callers | Transitive consumers | Estimated invalidation radius |
|---|---|---|---|---|
| `compute_analyzer_version` | `player_impact_analyzer.py:2141` | analyzer (2), backend app.py (8) | EVERY report's `summary.json::analyzer_version`. SHA256 of the FULL analyzer source file. | **Maximum**: a comment-only edit flips this. By design (docstring at line 2147: "Intentionally broad: any edit to player_impact_analyzer.py — including comments — changes the hash"). DB query: `SELECT COUNT(*) FROM runs WHERE status='completed'` returns **2030**, spread across **1007 distinct (machine,mode) pairs** — these all get flagged `stale_analyzer` via `/api/reports/stale-count` on any edit. |
| `_lookup_machine_md5` | `player_impact_analyzer.py:2163` | analyzer (5), batch_dev_sampler (3), virtual_analyzer (2), backend app.py (2) | Stamps `config_md5` + `code_md5` on every saved chunk envelope | Universal |
| `parse_chunk_response` | `player_impact_analyzer.py:2354` | analyzer (5), round_classification (2) | core analyzer hot loop | Universal (every chunk parsed) |
| `load_chunk_envelope` | `player_impact_analyzer.py:2037` | batch_dev_sampler (1), chunk_index (3), analyzer (4) | every cached-chunk read path | Universal |
| `peek_chunk_envelope` (analyzer) | `player_impact_analyzer.py:2083` | analyzer (1), chunk_index defines a separate one at `chunk_index.py:145` | dual implementation footgun — analyzer + chunk_index both have a peek. The chunk_index version is the canonical one per `chunk_index.py` docstring at line 49-51 ("Pure functions, Path-parameterized — shared verbatim between real console + virtual console"). | Coupling-only risk (no live consumer divergence today) |
| `_canonical_payload_bytes` + `_payload_sha256` | `player_impact_analyzer.py:2020, 2032` | analyzer (9 + 2), batch_dev_sampler (4 + 3) | chunk-integrity hash stamped in every envelope | Universal — change shape breaks all replays |
| `_compute_upstream_schema_fingerprint` | `player_impact_analyzer.py:2108` | analyzer (2), batch_dev_sampler (3) | upstream API schema fingerprint in envelope; drives "cache incompat" branch | Universal |
| `select_replay_chunks_by_md5` | `player_impact_analyzer.py:1209` | analyzer (2) | replay-from-cache filtering | Universal cache-replay path |
| `simulate_bankruptcy_from_response` | `player_impact_analyzer.py:1141` | analyzer (2) | `bankruptcy_simulation` block in every report | Universal |
| `_BankruptcyStreamAccumulator` | `player_impact_analyzer.py:1266` | analyzer (5) | same | Universal |
| `compute_bankruptcy_percentiles` | `player_impact_analyzer.py:1373` | analyzer (4) | same | Universal |
| `evaluate_guideline_comparison` | `player_impact_analyzer.py:1591` | analyzer (2) | `guideline_comparison` block in every report | Universal |
| `parse_rounds` | `player_impact_analyzer.py:1037` | analyzer (5) | round iteration for every chunk | Universal |
| `parse_paylines` | `player_impact_analyzer.py:1497` | analyzer (2) | payline parsing fallback | Universal |
| `build_multiplier_bucket_rows` | `player_impact_analyzer.py:1978` | analyzer (5) | `multiplier_profile` block | Universal |
| `return_bucket` | `player_impact_analyzer.py:1946` | analyzer (5) | return-bucket histogram in `hit_and_payout` | Universal |
| `classify_volatility` | `player_impact_analyzer.py:1717` | analyzer (5), backend app.py (2) | `volatility` block + frontend KPI tile | Universal |
| `classify_experience_archetype` | `player_impact_analyzer.py:1727` | analyzer (5), backend app.py (1) | `experience_archetype` block | Universal |
| `session_halfwidth_pp` | `player_impact_analyzer.py:1012` | analyzer (6), virtual_analyzer (1), backend app.py (1) | CI computation for every report | Universal |
| `ci_halfwidth_pp` | `player_impact_analyzer.py:1000` | analyzer (3), sampler (7), backend app.py (4) | sampler convergence loop + analyzer per-chunk CI | Universal |
| `aimd_tune` | `player_impact_analyzer.py:860` | analyzer (4) | sampler concurrency growth | Universal |

### 2.4 — `fresh_slotlab/chunk_index.py` + `rawdata_index.py`

| Symbol | Module:line | Direct callers | Transitive consumers | Estimated invalidation radius |
|---|---|---|---|---|
| `peek_chunk_envelope` | `chunk_index.py:145` | chunk_index (4), analyzer (1) | sidecar build, replay md5 routing | Universal cache layer (sidecar shape is "Pure functions, shared verbatim between real console + virtual console" per module docstring) |
| `get_chunks_index` | `chunk_index.py:407` | chunk_index (8), analyzer (4), rawdata_index (3), virtual_analyzer (2), backend app.py (4) | self-healing sidecar entry point — every "list chunks for machine M mode N" query routes through here | Universal cache layer |
| `update_chunk_entry` | `chunk_index.py:422` | chunk_index (6), analyzer (3) | per-chunk mutation; held under `_sidecar_lock_for(mode_dir)` per `chunk_index.py:91-111` | Universal (called once per chunk write) |
| `bulk_remove_chunk_entries` | `chunk_index.py:548` | chunk_index (7), backend app.py (8) | cleanup paths (DELETE rawdata version, retention pruning) | Universal cache layer |
| `chunks_by_md5` | `chunk_index.py:635` | chunk_index (2), virtual_analyzer (2) | the inverted-md5 lookup that fixed the 14s→10ms hot path for M1sim's 1443-chunk dir (memory `reference_chunk_index_inverted_md5.md`) | Universal cache layer |
| `iter_chunks_matching_md5` | `chunk_index.py:666` | chunk_index (2) | replay-from-cache md5 filtering | Universal cache layer |
| `_rebuild_by_md5` | `chunk_index.py:272` | chunk_index (5), analyzer (3) | lazy backfill of v1 → v2 sidecar layout | Universal cache layer |
| `load_chunks_index` | `chunk_index.py:240` | chunk_index (4) | raw read of `_chunks.json` sidecar | Universal cache layer |
| `summarize_by_md5` | `chunk_index.py:693` | chunk_index (1) | rawdata-status quick summary | Universal cache layer |
| `load_index` (rawdata) | `rawdata_index.py:62` | rawdata_index (3), backend app.py (4) | `<rawdata_root>/_index.json` master index of (machine, mode) data presence | Universal |
| `update_entry` (rawdata) | `rawdata_index.py:182` | analyzer (2), rawdata_index (3), backend app.py (8) | every save/cleanup touches this | Universal |
| `remove_entry` (rawdata) | `rawdata_index.py:206` | rawdata_index (1), backend app.py (8) | every machine/mode wipe | Universal |
| `rebuild_full` (rawdata) | `rawdata_index.py:216` | rawdata_index (1) | cold-start recovery | Universal |
| `_scan_mode_dir` | `rawdata_index.py:104` | helper to `rebuild_full` | Universal |

### 2.5 — `fresh_slotlab/trigger_sessions.py`

| Symbol | Module:line | Direct callers | Transitive consumers | Estimated invalidation radius |
|---|---|---|---|---|
| `is_new_trigger_remark` | `trigger_sessions.py:96` | trigger_sessions (2) | filters trigger session windows — M39 DancingDrum / M14 / M272 etc. all rely on `Trigger` prefix vs `TriggerAdd` distinction | Universal |
| `compute_trigger_sessions` | `trigger_sessions.py:131` | analyzer (3), round_win (3), trigger_sessions (1) | bonus-session aggregation; affects `bonus_chain_dynamics`, `payout_ids_top20` correctness on bonus-chained machines | Universal — change ⇒ every multi-spin-type machine's RTP attribution shifts |
| `_round_has_credited_win` | `trigger_sessions.py:119` (alias of `round_win.round_has_credited_win`) | analyzer (2), round_win (1), trigger_sessions (2) | double-count guard | Universal |

### 2.6 — `fresh_slotlab/sampler.py` + `batch_dev_sampler.py`

`sampler.py` is a STANDALONE script with no consumers in the audit scope; it duplicates several
analyzer primitives (`t_critical_95`, `compute_ci_halfwidth_pp`, `run_one_chunk`). It is
referenced by the backend's batch worker as a fallback, but the production path is
`player_impact_analyzer.py main()`. Treat as side path with no direct fleet-wide invalidation
effect — but the duplication is a coupling smell (§4 silent dependencies).

| Symbol | Module:line | Direct callers | Transitive consumers | Estimated invalidation radius |
|---|---|---|---|---|
| `parse_args` (sampler) | `sampler.py:23` | sampler standalone main | 0 inside audit scope; CLI entry only | n/a |
| `build_payload` | `sampler.py:53` | sampler standalone main | 0 | n/a |
| `post_json` (sampler) | `sampler.py:73` | sampler standalone main | 0 | n/a (analyzer has its own `post_json` at `player_impact_analyzer.py:312`) |
| `compute_ci_halfwidth_pp` | `sampler.py:193` | sampler internal | 0 | n/a (analyzer has `ci_halfwidth_pp` at `player_impact_analyzer.py:1000` — distinct function with different signature) |
| `fetch_machine` (batch_dev_sampler) | `batch_dev_sampler.py:122` | batch_dev_sampler main | dev-only fixture builder | n/a |

### 2.7 — `slot_designer/core/backend/machine_version.py`

| Symbol | Module:line | Direct callers | Transitive consumers | Estimated invalidation radius |
|---|---|---|---|---|
| `compute_code_md5(machine_name)` | `machine_version.py:109` | `machine_version.compute_machine_md5` (1), `machine_version.compute_machine_md5_for_mode` (1) — and 7 test files | Six virtual-registry machines via fanout in `virtual_registry.refresh_machines_virtual` | 6 (virtual-only) — see §3 |
| `compute_config_md5` | `machine_version.py:143` | `machine_version.compute_machine_md5` (1), `machine_version.compute_machine_md5_for_mode` (1) | Six virtual-registry machines | 6 (virtual-only) — see §3 |
| `compute_machine_md5(entry)` | `machine_version.py:251` | virtual_app (1), virtual_registry (1), virtual_analyzer (1), `slot_designer/scripts/{simulate,tune}.py` | aggregate `(config_md5, code_md5)` per virtual entry | 6 (virtual-only) |
| `compute_machine_md5_for_mode(entry, mode)` | `machine_version.py:276` | virtual_registry (1), virtual_analyzer (1) | per-mode `modesMd5` block in virtual registry | 6 (virtual-only); structurally `modesMd5["{mode}"]` per `machines_virtual.json:39-56` |
| `refresh_machines_virtual` | `virtual_registry.py` (re-exported from `virtual_app`) | virtual_app (5), virtual_analyzer (4), virtual_registry (2), machine_version (docstring) | rewrites `slot_designer/configs/machines_virtual.json` on console boot | 6 |

### 2.8 — `slot_designer/core/backend/virtual_*`

| Symbol | Module:line | Direct callers | Transitive consumers | Estimated invalidation radius |
|---|---|---|---|---|
| `build_virtual_app` | `virtual_app.py:176` | uvicorn entrypoint + tests | calls `refresh_machines_virtual` AT IMPORT TIME (line 201: `app = build_virtual_app()`) — see §4.4 | every virtual-console boot |
| `_local_md5_refresh` | `virtual_app.py:56` | override hook in `create_app(md5_refresh_override=...)` | replaces the upstream refresh handler to keep virtual fleet isolated from real-fleet upstream pull | 6 (virtual-only); critical isolation barrier per docstring line 64-68 |
| `_register_virtual_only_routes` | `virtual_app.py:149` | only at `build_virtual_app` time | exposes `/api/virtual/paytable/{machine}` ONLY on port 8878 — real console returns 404 (intentional asymmetry) | virtual-only |
| `_load_declared_pays_from_spec` | `virtual_app.py:97` | `/api/virtual/paytable/{machine}` | renders declared paytable for rwtree zero-hit rows | 6 (virtual-only) |

### 2.9 — `src/web_console/backend/app.py` (selected — full file is 8,927 LoC)

| Symbol | Module:line | Direct callers | Transitive consumers | Estimated invalidation radius |
|---|---|---|---|---|
| `create_app` | `app.py:5289` (signature) | virtual_app + main FastAPI entrypoint (`main.py:?`) | both consoles share one builder; per-instance state lives on `app.state.*` | Universal — both consoles re-instantiate |
| Module global `RAWDATA_ROOT` | `app.py:518` | 11 references inside app.py | **Documented footgun**: see `app.py:3769` comment "Use the BatchRunManager's injected rawdata_root, not the module-level RAWDATA_ROOT global. Virtual console (create_app(rawdata_root=slot_designer/rawdata/)) vs real console (rawdata/ at repo root) have different roots". Per memory `feedback_subprocess_import_suicide_and_module_globals.md` this is the same family as the 2026-04-21 incident. Each remaining `RAWDATA_ROOT` reference is a latent virtual-vs-real coupling bomb. | Both consoles (when wrong root leaks in) |
| Module global `MACHINES_CONFIG` | `app.py:63` | factory default; real callers must inject `machines_config=` | virtual analyzer's md5 lookup; report stamping | Both consoles |
| Module global `CACHE_ROOT` | `app.py:44` | factory default | cached chunk routing | Both consoles |
| `_MACHINES_SUMMARY_CACHE` | `app.py:1987` | in-process memoization (one bag per worker) | machines summary endpoint | per-worker leak surface |
| `_RAWDATA_OVERVIEW_CACHE` | `app.py:2030` | in-process memoization | rawdata overview endpoint | per-worker leak surface |
| `_IN_USE_MODES` + `_IN_USE_LOCK` | `app.py:2152, 2153` | every batch-run + cleanup path | per-PID coordination | per-worker (single-process today) |
| `_STATIC_ATTRS_CACHE` | `app.py:2143` | machines-summary build | per-worker memoization | per-worker leak surface |

### 2.10 — `src/web_console/frontend/app.js` (selected — full file is 7,917 LoC, 129 top-level functions)

Frontend renderers that consume `player_impact.<field>` and therefore become "rotted" by schema
changes:

| Renderer | Function:line | Schema fields consumed | Broken if field renamed |
|---|---|---|---|
| `renderPayIdOverview` | `app.js:4425` | `player_impact.payout_ids_top20[].{payout_id, hit_count, hit_rate, total_win, avg_win_when_hit, rtp_contribution_pp, spin_type_category, dominant_spin_type, spin_type_breakdown}` | Yes — heavy direct path |
| `_renderPayoutRowsHtml` | `app.js:4747` | shared helper extracted by `8411c9d`; consumes `rtp_contribution_pp`, `hit_rate`, with **fallback** `hit_rate ?? hit_rate_pct/100`, `rtp_contribution_pp ?? rtp_pp` (line 4764-4766) — tolerates pre-`8411c9d` reports | Protected by fallback |
| `renderPayoutsBySpinType` | `app.js:5026` | `player_impact.payouts_by_spin_type[label][].{payout_id, hit_count, hit_rate, avg_win_when_hit, rtp_contribution_pp}` | Protected by `_renderPayoutRowsHtml` fallback |
| `renderReelMarginalBySpinType` | `app.js:5165` | `player_impact.reel_marginal_by_spin_type[label]` — same fallback pattern via `_renderReelColumnHtml` | Protected by fallback |
| `_renderReelColumnHtml` | `app.js:5242` | shared helper (column-only) | Protected |
| `_renderFeatureBucketTable` | `app.js:5376` | `bucket.rtp_contribution_pp` (and `b.bucket`) | Yes — no fallback in this path |
| `renderFieldDiscovery` | `app.js:5458` | `player_impact.field_discovery` | Yes |
| `renderFeatureBreakdownPanel` | `app.js:5487` | `player_impact.upstream_feature_breakdown` (3 keys checked) | Yes |
| `_renderPayingFeatureCard` | `app.js:5618` | `feat.rtp_contribution_pp` | Yes |
| `renderCollectCyclePanel` | `app.js:5796` | `player_impact.collect_mechanic` | Yes |
| `renderBonusChainDynamicsPanel` | `app.js:5902` | `player_impact.bonus_chain_dynamics` | Yes |
| `renderBankruptcyAnalysis` | `app.js:5986` | `player_impact.bankruptcy_probe`, `player_impact.bankruptcy_simulation` | Yes |
| `renderSymbolDrilldown` | `app.js:3699` | `player_impact.symbols_by_column_top10`, `symbols_top20`, `symbols_by_column_top10_payline` | Yes |
| `renderPaylineDrilldown` | `app.js:3820` | `player_impact.paylines_top20`, `payline_symbol_top20`, `payline_rows_per_col`, `reel_position_top20` | Yes |
| `renderSpinTypeBreakdown` | `app.js:3940` | `player_impact.spin_type_breakdown[].{spin_type, behavior_name, spins, share_pct, win_rounds, hit_rate, total_win, rtp_pct, rtp_contribution_pp, rare}` (also processed in `pure.js:formatSpinTypeRows`) | Yes — protected for `hit_rate` (multiplied ×100 to `hit_rate_pct` at `pure.js:1233`) but only one-way |
| `renderMachineMechanics` | `app.js:4038` | `player_impact.machine_mechanics.{line_lock, scatter_lock, reel_lock, jackpot, freespin, double_pay}.{rtp_contribution_pp, lock_rtp_contribution_pp}` | Yes (6 sub-objects with `rtp_contribution_pp`) |
| `_renderRwtreeCell` | `app.js:1895` | `info.analyzer_version`, `info.config_md5`, `info.code_md5` — drives the analyzer-stale badge at line 2093 | Yes — depends on analyzer_version field being present |
| `renderPayoutGroupDrilldown` | `app.js:3697` | retired (no-op, kept for back-compat) | safe |

Notes:

- **`compare_diff.js`** consumes the same schema in side-by-side mode — schema changes affect it
  too. `pure.js` mirrors several renderers in pure-functional form (`formatPayoutGroupRows` at
  `pure.js:1202`, `formatSpinTypeRows` at `pure.js:1222`, `formatPayoutIdRows` at `pure.js:1249`).
  Field rename = double touch (app.js + pure.js + compare_diff.js).
- **app.js consumes `r.rtp_pp` 2 times** (line 5713 comment, line 5755 actual read on
  `sub.rtp_contribution_pp`) — the comment at line 5713 is stale; the actual read uses the new
  name with no fallback for THAT specific path. Worth flagging but outside §6 scope.

---

## §3 Hash composition map

### 3.1 — `compute_code_md5(machine_name)` (the brief's "most important single function")

**Defined**: `slot_designer/core/backend/machine_version.py:109` (NOTE: brief §2 listed this as
`slot_designer/core/version.py`; actual path is `core/backend/machine_version.py`).

**Inputs** — concatenated in this order, file by file, sorted by relative path:

1. `slot_designer/core/engine/**/*.py` excluding `__init__.py` and `__pycache__` — **8 files**:
   - `core/engine/evaluator.py` (17,532 bytes)
   - `core/engine/feature_protocol.py` (5,579 bytes) — referenced in `54b7d01`'s docstring scrub
   - `core/engine/loader.py` (10,008 bytes)
   - `core/engine/reel_strip.py` (2,821 bytes)
   - `core/engine/rules.py` (12,326 bytes)
   - `core/engine/spin.py` (7,097 bytes) — referenced in `54b7d01`'s docstring scrub
   - `core/engine/symbol.py` (3,592 bytes) — **edited by `54b7d01`**
2. `slot_designer/core/emitter/**/*.py` — **4 files**:
   - `core/emitter/chunk.py` (2,880 bytes)
   - `core/emitter/driver.py` (7,156 bytes)
   - `core/emitter/robot.py` (5,373 bytes)
   - `core/emitter/round.py` (5,522 bytes)
3. `slot_designer/machines/<machine_name>/plugins/**/*.py` excluding `__init__.py` — per-machine
   plugin tree:
   - M1: 0 files (no `plugins/` dir; base-only)
   - M15: 2 files (`plugins/feature.py` 16,051 bytes, `plugins/plugin.py` 8,612 bytes)
   - M37: 0 files (no `plugins/` dir; base-only)
   - M31: 1 file (`plugins/feature.py` 19,161 bytes) — created in `55a9ce1`
   - M43: 1 file (`plugins/feature.py` 24,524 bytes) — created in `dd65211`
   - M279: 7 files under `plugins/m279/` + `plugins/m279_*.py` (~43 KB total)

**Total core/* always-shared**: 11 files (88 KB).

**Consumers** of the returned hash (downstream of the function):

1. `machine_version.compute_machine_md5(entry)` at `:251` — pairs the code hash with
   `compute_config_md5(spec, weights, strips)` and returns `(cfg, code)`.
2. `machine_version.compute_machine_md5_for_mode(entry, mode)` at `:276` — same, but with single
   per-mode weights file.
3. **`slot_designer/configs/machines_virtual.json`** entries (6 today): `M1sim`, `M15sim`,
   `M37sim`, `M43sim`, `M31sim`, `M279sim` — written by `refresh_machines_virtual` on
   `build_virtual_app()` import (line 201 of `virtual_app.py`).
   Per-entry the hash is stamped in TWO places:
   - `entry.codeSummaryMd5` (machine-aggregate)
   - `entry.modesMd5["{mode}"].codeSummaryMd5` (per-mode, same value across modes of one machine —
     since code hash is mode-agnostic)
4. **Chunk envelopes** under `slot_designer/cache_chunks/<run_id>/chunk_NNNN.json` —
   `_save_chunk_cache` in `player_impact_analyzer.py:2187` stamps `_config_md5` + `_code_md5` into
   every envelope.
5. **Chunk sidecars** `<rawdata_root>/<machine>/mode_<N>/_chunks.json` — `by_md5` inverted index
   keys are `"<cfg_md5>|<code_md5>"` strings (`chunk_index.py:266`).
6. **Reports** `reports/<M>/mode_<N>/versions/<rv>/player_impact_summary.json` — `summary.code_md5`
   field at top level. Confirmed in `rv_st_split_regression`: `"code_md5":
   "536fc5a2a8f2ecf1fd8c6dfcf2c025cc"`.
7. **`reports/<M>/mode_<N>/index.json`** + **`latest.json`** — per-report `rawdata_code_md5`
   stamped by backend's `finalize_run` at `app.py:5063`.
8. **`runs` table in `state/console/console.db`** — `rawdata_code_md5` column populated at
   `app.py:5082`.

**Important fleet-radius caveat**: `compute_code_md5` is **virtual-only**. The 421 entries in
`configs/machines.json` (real fleet) get their `configSummaryMd5` + `codeSummaryMd5` from upstream
via `machine_variants.py:336, 379` — the upstream `/MachineConfigMd5` endpoint, NOT from the local
Python source files. So **editing `core/engine/symbol.py` does NOT flip the real fleet's
machines.json code_md5**.

What it does flip: the 6 virtual-registry machines (M1sim, M15sim, M37sim, M43sim, M31sim,
M279sim). Sample fleet distribution from `slot_designer/configs/machines_virtual.json`:

- M1sim + M37sim + M43sim share `codeSummaryMd5`? No — they have different code md5s because the
  per-machine plugin tree differs:
  - M1sim: `03ff4194e214ad94fa1dc96fbcb00ee8` (M1 has no plugins/)
  - M37sim: `03ff4194e214ad94fa1dc96fbcb00ee8` (M37 has no plugins/, SAME as M1sim — confirming
    plugin-empty machines share hash)
  - M43sim: `92e79f8745268a151bbf9fee5d5ed181`
  - M31sim: `097f10caa8e8ee3c0c2a9c32224ecd80`
  - M15sim: `eb2c523750000ab559262654b1604bdd`
  - M279sim: `7803ae4fe30a889cadc555025901d6f4`

This confirms the Phase B isolation contract from `slot_designer/ARCHITECTURE.md` works at the
boundary: M1 + M37 = identical (both no-plugin), all 4 others distinct.

**Implication**: any edit to `core/engine/symbol.py` or any of the 11 shared files flips ALL 6
virtual machines' `codeSummaryMd5`. Per Phase B docstring at `machine_version.py:118-122`:
"Touching core/* flips every machine's md5 (framework change). Touching machines/<M>/plugins/*
flips only machine's md5."

### 3.2 — `compute_config_md5(spec_path, weights_paths, strips_path=None)`

**Defined**: `machine_version.py:143`. Hash composition:

1. `spec_path` raw bytes (or sentinel `b"<spec_missing>"`).
2. If `strips_path is not None`: separator `b"\x00"` + strips bytes (or `b"<strips_missing>"`).
3. For each `weights_path`: separator `b"\x00"` + weights bytes (or `b"\x00<missing>"`).

Per-mode invocation (`compute_machine_md5_for_mode`) passes ONE weights file → per-mode hash. This
is the post-2026-04-22 fix per memory `feedback_md5_granularity_and_stamping.md`: pre-fix
`compute_machine_md5` mixed all modes' weights into one digest, causing adding mode 2 to flip mode
1's hash and reclassify all old mode-1 chunks as historical.

**Consumers** of returned hash:

1. `entry.configSummaryMd5` + `entry.modesMd5["{mode}"].configSummaryMd5` in
   `machines_virtual.json` (per-entry, per-mode).
2. Chunk envelopes' `_config_md5` field.
3. Sidecar `by_md5` inverted-index key.
4. Reports' `summary.config_md5`.
5. `reports/<M>/mode_<N>/index.json` row's `rawdata_config_md5`.
6. `runs` table's `rawdata_config_md5` column.

### 3.3 — `compute_analyzer_version()` — the universal stale-stamp

**Defined**: `fresh_slotlab/player_impact_analyzer.py:2141`.

**Input**: `Path(__file__).resolve().read_bytes()` — the FULL `player_impact_analyzer.py` source
file. SHA256, first 12 hex chars.

**Per docstring at line 2147**: "Intentionally broad: any edit to player_impact_analyzer.py —
including comments — changes the hash."

**Consumers**:

1. Every report's `summary.analyzer_version` field. Confirmed in `rv_st_split_regression`:
   `"analyzer_version": "47f32f8d4886"`.
2. `reports/<M>/mode_<N>/index.json` row's `analyzer_version` field (added by `finalize_run` at
   `app.py:5064`).
3. `runs` table's `analyzer_version` column (`app.py:1499` schema migration:
   `ALTER TABLE runs ADD COLUMN analyzer_version TEXT`).
4. Frontend at `app.js:306`: `analyzerMatch = String(run.analyzer_version) === String(cvAnalyzer)`
   drives the freshness badge in `_renderRwtreeCell` at `app.js:1895` and the stale-banner.
5. `/api/reports/stale-count` at `app.py:5694` — compares stored `analyzer_version` per run vs
   the freshly computed `cur_analyzer = compute_analyzer_version()` (line 5716) → builds the
   `stale_analyzer` + `fixable_items` counts shown in the run-history banner.

**Live blast-radius measurement** (queried from `state/console/console.db`):

- `SELECT COUNT(*) FROM runs WHERE status='completed'` → **2030**.
- `SELECT COUNT(DISTINCT machine||'|'||mode) FROM runs WHERE status='completed'` → **1007** distinct
  (machine,mode) pairs.

**Conclusion**: any single-character edit to `player_impact_analyzer.py` (including comment
changes that don't alter behavior) flips `analyzer_version` for **every newly-generated report**
and silently invalidates the freshness check for the **2030 existing completed runs across 1007
(machine,mode) pairs**. Per `app.py:5757`, those then count toward `stale_analyzer` and surface as
fixable items via the run-history banner.

This is a **universal stamp**. There is no per-machine or per-feature filtering.

### 3.4 — Real-fleet `codeSummaryMd5` / `configSummaryMd5` (the 421-entry registry)

**Source**: upstream `/MachineConfigMd5` endpoint. Populated by
`src/web_console/backend/machine_variants.py:336, 379` in `_apply_upstream_md5_to_existing` (sketch
of name; the loop runs over `upstream_data` from upstream API and writes `entry.configSummaryMd5`
+ `entry.codeSummaryMd5`).

**`configs/machines.json` distribution** (live count from script):

- **421** total entries (NOT 393 — brief §2 / §6 referenced 393, but current registry is 421).
- **166** variant entries (machine name contains `$`).
- **255** non-variant entries.
- **175** distinct `codeSummaryMd5` values across the 421 entries.
- **255** distinct `configSummaryMd5` values across the 421 entries.

Top fleet-wide `codeSummaryMd5` (showing fan-out structure):

- `c2a4e3be71b798a8...`: **86 machines** (20.4%) — a single upstream code change affecting this
  cohort would invalidate 86 machines' reports.
- `536fc5a2a8f2ecf1...`: **45 machines** (10.7%).
- `cdc5e43eb483145e...`: 9 machines (2.1%).
- `0ab0a6df4456c475...`: 9 machines (2.1%).
- Tail: 171 hashes each owned by 1-8 machines.

The largest cohort (86 machines on the same code hash) is the **blast-radius** of any upstream
engine change that affects that cohort — it would flip
`rawdata_is_stale=True` for all 86 machines simultaneously per `app.py:5750`.

The 6 virtual-registry machines + this 421-entry real registry are **distinct universes**: the
virtual one is auto-refreshed on every console boot from local files (via `compute_code_md5`); the
real one is auto-refreshed by pulling upstream on `/api/machines/refresh-md5`. The boundary is
enforced by `virtual_app._local_md5_refresh` (`virtual_app.py:56`), per the 2026-04-21 incident
described at line 64-68.

### 3.5 — Hash composition map (text diagram)

```
Source file edit
   |
   v
 [a] core/engine/*.py (8 files)           [b] core/emitter/*.py (4 files)
       OR
 [c] machines/<M>/plugins/**/*.py
       OR
 [d] machines/<M>/{spec.json, reel_strips.json, weights/mode_N/weights.json}
       OR
 [e] fresh_slotlab/player_impact_analyzer.py (any byte)
       OR
 [f] upstream server-side build changes <M>'s underlying machine
   |
   v
   |                                                                   [f] flow:
   v                                                                       upstream `/MachineConfigMd5`
 compute_code_md5(machine_name)  ←── [a][b] flip every virtual machine        |
   |                                                                          v
   | [c] flips ONLY machines/<M>                                       _apply_upstream_md5_to_existing
   v                                                                          |
 compute_machine_md5(entry)  /  compute_machine_md5_for_mode(entry, mode)      v
   |                                                                  configs/machines.json
   |       \                                                              .machines[*]
   |        \---> compute_config_md5(spec, weights, strips)               .codeSummaryMd5
   |              ^                                                       .configSummaryMd5
   |              |  [d] flips THIS machine + mode
   v
 slot_designer/configs/machines_virtual.json
       .machines[*].{configSummaryMd5, codeSummaryMd5}
       .machines[*].modesMd5["{mode}"].{configSummaryMd5, codeSummaryMd5}
   |
   v
 Sampling / replay routes md5 into:
   * chunk envelope `_config_md5`, `_code_md5`     ← stamped by _save_chunk_cache
   * sidecar `_chunks.json`.by_md5[cfg|code]       ← stamped by update_chunk_entry
   * rawdata_index.json (per (machine,mode))       ← rawdata_index.update_entry
   |
   v
 Analyzer (player_impact_analyzer.py main)
   * stamps summary.config_md5, summary.code_md5, summary.analyzer_version  ← [e] flips analyzer_version
   |
   v
 reports/<M>/mode_<N>/versions/<rv>/player_impact_summary.json
   |
   v
 BatchRunManager.finalize_run writes:
   * reports/<M>/mode_<N>/index.json[*].{rawdata_config_md5, rawdata_code_md5, analyzer_version}
   * reports/<M>/mode_<N>/latest.json (same fields)
   * runs row in state/console/console.db (analyzer_version, rawdata_config_md5, rawdata_code_md5)
   |
   v
 /api/reports/stale-count compares stored vs current:
   * stale_analyzer ← row.analyzer_version != compute_analyzer_version()
   * stale_rawdata  ← row.rawdata_*_md5 != machines.json current
   * fixable_items  ← stale_analyzer AND !stale_rawdata, deduped by (machine, mode)
```

---

## §4 Silent dependencies inventory

These are bindings that don't appear as imports or call edges but tie code paths together. A
search-and-replace refactor will miss them.

### 4.1 — Module-level globals (per memory `feedback_subprocess_import_suicide_and_module_globals.md`)

`src/web_console/backend/app.py` declares these at module top:

- `APP_STARTED_AT` (`app.py:35`)
- `ROOT`, `STATE_DIR`, `DB_PATH`, `MODEL_CONFIG_PATH`, `PROGRESS_DIR`, `REPORTS_ROOT`,
  `CACHE_ROOT` (`app.py:38-44`)
- `RAWDATA_ROOT_DEFAULT` (`app.py:49`) and `RAWDATA_ROOT` (`app.py:518`) — **footgun explicitly
  flagged in code** at `app.py:3769`: "Use the BatchRunManager's injected rawdata_root, not the
  module-level RAWDATA_ROOT global. Virtual console vs real console have different roots;
  hardcoding the global here made every virtual batch-run target the REAL console's rawdata/ tree."
  Confirmed 11 references to `RAWDATA_ROOT` remain in `app.py`; per the docstring the safe ones
  use `rawdata_root if rawdata_root is not None else RAWDATA_ROOT` fallback (lines 695, 1064,
  3187, 5318) — only safe when the caller is in production mode AND the default is the correct
  one. Virtual-console paths that bypass the fallback are latent bombs.
- `_RAWDATA_MIN_RETENTION_SPINS_DEFAULT` (`app.py:54`)
- `CLASSIFY_DIR`, `PAYTABLES_DIR`, `MACHINES_CONFIG`, `SERVERS_CONFIG` (`app.py:58-64`)
- `MACHINECONFIG_DIR`, `ANALYZER`, `FRONTEND_DIR`, `SLOT_SPIN_ENDPOINT` (`app.py:70-73`)
- `INFER_PAYTABLE_SCRIPT`, `VERIFY_LABELS_SCRIPT` (`app.py:81-82`)
- `PROVIDER_MODELS` (`app.py:197`, annotated)
- `_DEFAULT_ANALYZER_BET` (`app.py:523`)
- `_MACHINES_SUMMARY_CACHE` (`app.py:1987`, annotated dict)
- `_RAWDATA_OVERVIEW_CACHE` (`app.py:2030`, annotated dict)
- `_STATIC_ATTRS_CACHE` (`app.py:2143`, annotated dict)
- `_IN_USE_MODES` (`app.py:2152`) + `_IN_USE_LOCK` (`app.py:2153`)
- `_LOCK_CACHE` (`app.py:2178`)
- `_STATIC_ATTRS_MECH_KEYS` (`app.py:2246`)

`fresh_slotlab/player_impact_analyzer.py` declares these at module top (33 globals):

- `DEFAULT_ENDPOINT_URL`, `ENDPOINT_URL` (`player_impact_analyzer.py:78-79`) — `ENDPOINT_URL` is
  **mutated at runtime** by `--endpoint-url` arg, per comment at line 79: "mutable; overridden by
  --endpoint-url". This is a module-mutation pattern that can leak across subprocess invocations
  if the analyzer is ever re-entered.
- `PAYLINE_RE`, `RETURN_BUCKET_ORDER` (`:87, :94`)
- 4 tail bucket lists `TAIL_GEX{10,20,50,100}_BUCKETS` (`:111, :125, :134, :142`)
- `DEFAULT_GUIDELINE_RULES_PATH` (`:149`)
- `_RETRYABLE_HTTP_CODES` (`:330`)
- 3 retry/circuit-break constants (`:361-363`)
- 4 non-convergence constants (`:373-376`)
- 4 AIMD constants (`:392-395`)
- `PAID_NORMAL_FEATURES` (`:453`)
- `_BCM_CONFIG_PATH` (`:463`)
- `_DEFAULT_BANKRUPTCY_SESSION_SPINS` (`:1080`)
- `_BASELINE_ROUND_FIELDS`, `_REQUIRED_ROUND_FIELDS`, `_REQUIRED_BET_FIELDS_ANY` (`:1444, :1465,
  :1472`) — used by `_check_round_schema` at `:1475`. **These literal field names are silent
  dependencies on the upstream API contract** — see §4.3.
- `_REMARKS_FREESPIN_RE`, `_REMARKS_EXTRARATIO_RE`, `_REMARKS_ADDFREESPINS_COUNT_RE` (`:1756-58`)
- `CHUNK_CACHE_VERSION` (`:2006`) — bump this and every cached envelope's `_cache_version` becomes
  invalid simultaneously.
- `_ENVELOPE_PEEK_BYTES`, `_ENVELOPE_PEEK_RE` (`:2074-75`)

### 4.2 — File-path conventions (no enforcement; pattern-coded across consumers)

Backend uses these literal path templates without a central registry:

- `reports/<machine>/mode_<n>/versions/<rv>/player_impact_summary.json` —
  18+ occurrences in `app.py` (line 1198, 2436, 2767, 4749, 5785, 5881, 6813, 7153, 7599 etc.) and
  in `fresh_slotlab/reporter.py:45`, every test fixture. Rename "versions" → "v" anywhere and the
  fleet's reports become unreadable.
- `reports/<machine>/mode_<n>/index.json` — 8+ occurrences in `app.py` (lines 5013, 5192, 7009,
  7290, 7625, 7779, 8448), `app.js:1738`, `compare_diff.js`. The 393 (read: 421) machines'
  in-flight reports are listed via this file.
- `reports/<machine>/mode_<n>/latest.json` — 9+ occurrences in `app.py` (lines 5014, 5193, 7010,
  7291, 7626, 7852, 8464, 8600, 8546) and `app.js`. Per `app.py:1998`: "We scan version dirs rather
  than `latest.json` mtimes because `/api/reports/import` doesn't rewrite latest.json".
- `<rawdata_root>/<machine>/mode_<n>/_chunks.json` (chunk_index sidecar) and `chunk_NNNN.json`
  cached chunk envelopes — assumed by both production and virtual consoles. Per `chunk_index.py:51`
  the sidecar is "shared verbatim between real console (fresh_slotlab.rawdata) and virtual
  console (slot_designer.rawdata)".
- `<rawdata_root>/_index.json` (rawdata_index master) at `rawdata_index.py:62` etc.
- `slot_designer/cache_chunks/<run_id>/chunk_NNNN.json` — separate per-run cache distinct from
  the rawdata sidecars.
- `slot_designer/machines/<M>/{spec.json, reel_strips.json, weights/mode_<N>/weights.json,
  plugins/**/*.py}` — `machine_version._weights_path_template` / `_strips_path` /
  `_spec_path` fields in `machines_virtual.json` are literal path templates. Misalign these and
  `compute_config_md5` silently hashes `<missing>` sentinels (per `compute_config_md5:171-192`).
- `configs/machines.json`, `configs/servers.json`, `configs/machine_round_win_rules.json`,
  `configs/round_classification.yaml` (if present), `configs/paytables/<M>.json`. Two of these
  are listed in git status as modified — `configs/machines.json` and `configs/servers.json` — so
  any path-shape change ripples across the active session.

### 4.3 — Schema field names (rename = silent break per `feedback_invariant_with_fallback_hides_drift.md`)

**Upstream API schema** (CostCredits, WinCredits, PayoutIdToWinAmount, PayoutByPayline, ReMarks,
SpinType, CollectCount, etc.) — read in:

- `fresh_slotlab/round_classification.py:109, 124, 161, 173, 187, 192-228, etc.`
- `fresh_slotlab/round_win.py:43-68, 211, 220, 396, ...`
- `fresh_slotlab/trigger_sessions.py` (ReMarks via `is_new_trigger_remark`).
- `fresh_slotlab/player_impact_analyzer.py` — `_REQUIRED_ROUND_FIELDS`, `_REQUIRED_BET_FIELDS_ANY`
  (lines 1465 + 1472) trip `_check_round_schema` at `:1475` if any required key disappears.

**Internal `player_impact_summary.json` schema** — same family. Schema fields and the renderers that
break on rename:

| Field path | Producer (analyzer line) | Consumer (app.js / pure.js line) | Fallback? |
|---|---|---|---|
| `summary.machine`, `summary.mode`, `summary.run_id`, `summary.report_id` | analyzer `main()` | many | No — universal |
| `summary.code_md5`, `summary.config_md5`, `summary.analyzer_version` | analyzer `main()` | backend `finalize_run` (`app.py:5036-5038`), frontend `app.js:294, 302, 306, 1738, 2093, 2109, 6411, 7179` | No |
| `summary.rtp.point_pct` | analyzer | `app.py:5025`; `app.js` KPI tiles | No |
| `summary.sampling.{total_spins, achieved_halfwidth_pp}` | analyzer | `app.py:5026, 5039, 5052`; KPI tiles | No |
| `summary.guideline_assessment.data_quality.quality_label` | analyzer | `app.py:5027`; KPI tile | No |
| `player_impact.payout_ids_top20[].{payout_id, hit_count, hit_rate, total_win, avg_win_when_hit, rtp_contribution_pp, spin_type_category, dominant_spin_type, spin_type_breakdown}` | analyzer | `app.js:4425 renderPayIdOverview`, `pure.js:1249 formatPayoutIdRows` | Partial: rendering helper has `r.hit_rate ?? r.hit_rate_pct/100` fallback |
| `player_impact.payouts_by_spin_type[ST{N}_{behavior}][].{payout_id, hit_count, hit_rate, total_win, avg_win_when_hit, rtp_contribution_pp}` | analyzer (added by `729a6ca`; renamed by `8411c9d`) | `app.js:5026 renderPayoutsBySpinType`, `app.js:5083-5113` derives `spin_type_category` from parent label | Fallback `hit_rate_pct/100` + `rtp_pp` at app.js:4764-4766 + 5110 — handles pre-`8411c9d` reports |
| `player_impact.reel_marginal_by_spin_type` | analyzer | `app.js:5165, 5170` | Partial fallback via `_renderReelColumnHtml` |
| `player_impact.spin_type_breakdown` | analyzer | `app.js:3940 renderSpinTypeBreakdown`, `pure.js:1222 formatSpinTypeRows` | Partial: `pure.js:1233` reads `r.hit_rate || 0` |
| `player_impact.payout_groups_top20` | analyzer (legacy) | `app.js:3697 renderPayoutGroupDrilldown` (RETIRED — no-op), `pure.js:1202 formatPayoutGroupRows` | n/a (retired) |
| `player_impact.machine_mechanics.{line_lock,scatter_lock,reel_lock}.lock_rtp_contribution_pp` | analyzer | `app.js:4062, 4073, 4083 renderMachineMechanics` | No |
| `player_impact.machine_mechanics.{jackpot,freespin,double_pay}.rtp_contribution_pp` | analyzer | `app.js:4094, 4107, 4119` | No |
| `player_impact.upstream_feature_breakdown.{rtp_contribution_pp, share_of_total_win, fires_spins}` | analyzer | `app.js:5487 renderFeatureBreakdownPanel`, 5648, 5660-61, 5755 | No |
| `player_impact.bonus_chain_dynamics` | analyzer | `app.js:5902 renderBonusChainDynamicsPanel` | No |
| `player_impact.bankruptcy_*` | analyzer | `app.js:5986 renderBankruptcyAnalysis` | No |
| `player_impact.symbols_by_column_top10` etc. | analyzer | `app.js:3699 renderSymbolDrilldown` | No |
| `player_impact.paylines_top20`, `payline_symbol_top20`, `payline_rows_per_col`, `reel_position_top20` | analyzer | `app.js:3820 renderPaylineDrilldown` | No |
| `player_impact.collect_mechanic` | analyzer | `app.js:5796 renderCollectCyclePanel` | No |
| `player_impact.field_discovery` | analyzer | `app.js:5458 renderFieldDiscovery` | No |
| `player_impact.streaks`, `multiplier_profile`, `volatility`, `session_rtp_curves`, `chain_ratio_sequences` | analyzer | various | No |
| `summary.collect_mechanic` (top-level) | analyzer | derived consumer | No |
| `summary.upstream_analysis` | analyzer | derived consumer | No |
| `summary.storage`, `summary.output_all_robots_result` | analyzer | passthrough | No |

**Key signal from this table**: only the `payouts_by_spin_type` family has frontend fallback for
the `8411c9d` rename. All other schema renames would break renderers silently. The new field
`payouts_by_spin_type` is also the only ST-split panel that survived from `729a6ca`+`8411c9d`
+`4cbcab2` to the frontend.

### 4.4 — Import-time side effects

The known suicide-class footgun lives in **`slot_designer/core/backend/virtual_app.py:201`**:

```python
app = build_virtual_app()
```

This line runs `build_virtual_app()` AT MODULE IMPORT TIME. Inside, it calls:

1. `mkdir` for 7 paths (lines 178-181).
2. `refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)` (line 184) — **rewrites
   `machines_virtual.json` on every import**.
3. `create_app(...)` (line 186) — builds the full FastAPI app, including DB init.

Per memory `feedback_subprocess_import_suicide_and_module_globals.md` this is the same pattern
that caused the 2026-04-21 incident. The comment block at `virtual_app.py:30-38` confirms the
fix: "Registry primitives live in a dedicated module with zero side-effects so subprocess callers
(virtual_analyzer.py) don't have to import this file and trigger build_virtual_app() at import
time (2026-04-21 suicide bug)". So:

- **Safe path**: subprocess callers go through `virtual_registry` (the side-effect-free re-export).
- **Unsafe path**: anyone who imports `slot_designer.core.backend.virtual_app` directly triggers
  `build_virtual_app()`. This is the latent footgun — `git grep -l "from slot_designer.core.backend.virtual_app"`
  shows the surface area.

`virtual_app._local_md5_refresh` (line 56) writes to `machines_virtual.json` on every console boot
AND every `/api/machines/refresh-md5` call. Re-running an analyzer in a worker can race against
this.

`fresh_slotlab/player_impact_analyzer.py` has **mutated module globals** at runtime:

- `ENDPOINT_URL = DEFAULT_ENDPOINT_URL` (line 79) — overridden by `--endpoint-url` CLI arg. If the
  analyzer is re-entered (e.g., by a second `main()` call within a subprocess that imports the
  module twice via different paths), the override leaks.

`fresh_slotlab/chunk_index.py` declares two process-local globals at lines 91-92:

- `_SIDECAR_LOCKS: dict[str, threading.Lock]`
- `_LOCKS_GUARD: threading.Lock`

These are intentionally process-global per the docstring at lines 84-90 — cross-process writers
would need a file lock; this codebase doesn't have any.

`src/web_console/backend/app.py` declares the in-process caches `_MACHINES_SUMMARY_CACHE`,
`_RAWDATA_OVERVIEW_CACHE`, `_STATIC_ATTRS_CACHE`, `_IN_USE_MODES`, `_LOCK_CACHE` — all per-worker
state with no LRU. Multi-worker deployments rely on each worker rebuilding its own copy. Stale
when fleet-shared data changes mid-flight.

### 4.5 — Duplicate primitives (real-vs-virtual coupling)

The brief's question "is the virtual console a thin shell?" maps to detecting duplicated
implementations:

- `fresh_slotlab/sampler.py` defines `post_json`, `t_critical_95`, `compute_ci_halfwidth_pp` —
  `fresh_slotlab/player_impact_analyzer.py` redefines `post_json` (`:312`), `t_critical_95`
  (`:965`), `ci_halfwidth_pp` (`:1000`). Two implementations of essentially the same numerics.
- `fresh_slotlab/player_impact_analyzer.py:2083` defines `peek_chunk_envelope`; so does
  `fresh_slotlab/chunk_index.py:145`. Per the chunk_index docstring at lines 49-51 the chunk_index
  version is the canonical one shared between real and virtual consoles. The analyzer's local copy
  is a latent divergence risk.
- `slot_designer/core/backend/virtual_analyzer.py` delegates to `player_impact_analyzer.main()` via
  subprocess (per memory `feedback_subprocess_import_suicide_and_module_globals.md`) — confirmed:
  imports `compute_machine_md5` + `compute_machine_md5_for_mode` + `chunks_by_md5` directly and
  injects them; doesn't redefine. **GOOD** — this side stays thin.
- `slot_designer/core/backend/virtual_app.py:_register_virtual_only_routes` adds
  `/api/virtual/paytable/{machine}` — port 8878 only. Real console returns 404. Frontend
  `app.js` probes endpoints that 404 and falls back. **Asymmetry IS documented**, but it is
  asymmetry — not pure thin-shell.

---

## §5 Invalidation case studies — the five required commits

### 5.1 — `54b7d01` "feat(slot_designer/core): native 'scatter' symbol kind + scrub M15 tokens"

**Files touched**:

- `slot_designer/core/engine/symbol.py` (+8 lines: added `'scatter'` to `_KNOWN_KINDS`,
  `Symbol.is_scatter` property, docstring).
- `slot_designer/core/engine/evaluator.py` (+8 lines, 3 hunks).
- `slot_designer/core/engine/spin.py` (4 comment edits).
- `slot_designer/core/engine/feature_protocol.py` (2 comment edits).
- `slot_designer/machines/M31/spec.json` (kind: filler → scatter).

**Hash impact**:

Files (a) symbol.py + (b) evaluator.py + (c) spin.py + (d) feature_protocol.py are ALL in
`_core_source_files()` per `machine_version.py:61-86` and contribute to `compute_code_md5(M)` for
every M. Per `compute_code_md5` docstring at `:118-122`: "Touching core/* flips every machine's
md5 (framework change)."

- **Virtual machines (machines_virtual.json)**: ALL 6 entries' `codeSummaryMd5` flips
  simultaneously. Confirmed by the post-commit refresh: `session_artifacts/M43/02b_stage_2_5_notes.md:74-79`
  states "Touching `core/engine/rules.py` flips `codeSummaryMd5` for ALL machines in the fleet,
  because `compute_machine_md5` hashes all `core/engine/*.py` sources. After the rules.py edit,
  `refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)` was run to recompute and write the updated
  hashes. All 5 registered virtual machines had their `codeSummaryMd5` updated".
  Symbol.py is the same shared layer ⇒ same behavior: all 6 virtual machines invalidated.
- **Real fleet (configs/machines.json)**: **0 machines invalidated** by this Python edit.
  `codeSummaryMd5` for the 421 real entries comes from upstream `/MachineConfigMd5`, not from
  `compute_code_md5`. The change is local-only.

**Cached reports stale**:

- Virtual side: cached `slot_designer/cache_chunks/<run_id>/chunk_*.json` envelopes whose
  `_code_md5` was stamped pre-commit are now stale relative to the new `code_md5` in
  `machines_virtual.json`. Per `chunk_index.py:266` (`_md5_key`) sidecar `by_md5` keys flip.
  Sample existing reports under `slot_designer/reports/<Msim>/mode_*/versions/*/` would show
  pre-commit `code_md5` ≠ current.
- Real side: no cached chunks stale (real `codeSummaryMd5` is upstream-controlled).

**`spec.json` impact (M31 specifically)**:

- M31's `_spec_path` → `slot_designer/machines/M31/spec.json` changed (`filler` → `scatter`). Per
  `compute_config_md5:143` the spec bytes feed `configSummaryMd5`. So **M31sim** specifically also
  gets `configSummaryMd5` flipped (not just `codeSummaryMd5`). The other 5 virtual machines only
  see `codeSummaryMd5` flip; their `configSummaryMd5` unchanged.

**Frontend break vs fallback**:

- Frontend doesn't render `symbols[Scatter].kind` directly — symbol kind is internal to spec
  parsing. **No frontend break**.

**Net assessment**: 6 virtual `codeSummaryMd5` flips, 1 virtual `configSummaryMd5` flip (M31sim),
0 real-fleet hash flips, all cached virtual chunks newly tagged "historical" (but not deleted per
memory `feedback_md5_is_a_tag_not_a_destruction_signal.md` — they remain on disk as the
`by_md5["<old>"]` bucket and the operator can replay or delete via surgical endpoint).

### 5.2 — `729a6ca` "feat(analyzer): add SpinType-split breakdowns to player_impact_analyzer"

**Files touched**:

- `fresh_slotlab/player_impact_analyzer.py` (+230 lines, two new accumulators).
- `tests/backend/test_analyzer_st_split.py` (+300 lines).

**Hash impact**:

- `compute_analyzer_version()` is `sha256(player_impact_analyzer.py)[:12]`. The +230 lines flip
  the hash. **`analyzer_version` for every newly-generated report and every existing run row in
  the DB diverges from the new code value.**
- Live measurement: `state/console/console.db` has **2030 completed runs** across **1007 distinct
  (machine, mode) pairs**. Each gets flagged `stale_analyzer` by `/api/reports/stale-count`
  (`app.py:5694`). The fixable-items dedupe per (machine, mode) returns ~1007 entries.
- `code_md5` / `config_md5` (the per-machine ones in `configs/machines.json` and
  `machines_virtual.json`): **unchanged**. The analyzer is not a `_core_source_file()` and not a
  spec/weights file. Real and virtual machine hashes are intact.

**Schema impact**:

- New top-level keys `player_impact.payouts_by_spin_type` (dict by `ST{N}_{behavior}` label) and
  `player_impact.reel_marginal_by_spin_type`. ADDITIVE — old reports don't have these keys, new
  reports do.

**Frontend break vs fallback**:

- Frontend at this commit point has **no consumer** for the two new keys (renderers
  `renderPayoutsBySpinType` and `renderReelMarginalBySpinType` come later in `bee6b31` /
  `53c36df` / `8411c9d`). Old reports show no ST-split panel — silent absence is treated as
  graceful skip. The next commit (`bee6b31`) adds renderers; pre-rename schema (with
  `hit_rate_pct` + `rtp_pp`) lives between `bee6b31` and `8411c9d`.

**Cached chunks**: untouched. `_save_chunk_cache` only stamps `_config_md5` / `_code_md5` /
`_chunk_index` etc.; no analyzer fingerprint goes into chunk envelopes.

**Net assessment**: 0 machines' code_md5 changed; 1007 distinct (machine, mode) reports flagged
`stale_analyzer` via `analyzer_version` flip. Frontend additive — no break.

### 5.3 — `8411c9d` "refactor: extract shared row/column helpers + align ST-split schema"

**Files touched**:

- `fresh_slotlab/player_impact_analyzer.py` (+38/-38 lines).
- `tests/backend/test_analyzer_st_split.py` (9 tests updated).
- `src/web_console/frontend/app.js` (+338/-324 lines).
- `src/web_console/frontend/pure.js` (-12 lines: 6 redundant i18n keys removed).

**Schema impact**:

- `payouts_by_spin_type[label][].hit_rate_pct` → **renamed to** `.hit_rate` (fraction not percent).
- `payouts_by_spin_type[label][].rtp_pp` → **renamed to** `.rtp_contribution_pp`.

Both new field names ALREADY EXIST in the same row positions in `payout_ids_top20`. The rename
aligns split with aggregate (helper `_renderPayoutRowsHtml` can render both).

**Hash impact**:

- `analyzer_version` flips again (it flipped for `729a6ca`; this commit flips it again).
- `code_md5` / `config_md5`: unchanged for both virtual and real.

**Frontend break vs fallback**:

- Pre-`8411c9d` reports on disk still have `hit_rate_pct` + `rtp_pp` schema. The next commit
  `7e5fe32` (committed minutes later) added the explicit fallback at `app.js:4764-4766`:
  ```javascript
  const _rtpOf = (r) => Number(r.rtp_contribution_pp ?? r.rtp_pp ?? 0);
  const _hrOf  = (r) => r.hit_rate ?? (r.hit_rate_pct != null ? r.hit_rate_pct / 100 : NaN);
  ```
- Sample confirmation: `reports/M14/mode_1/versions/rv_st_split_regression/player_impact_summary.json`
  is a **pre-rename fixture** — its `payouts_by_spin_type[ST1_paid][0]` has `hit_rate_pct`, `rtp_pp`
  (NOT `hit_rate`, `rtp_contribution_pp`). So this fixture exercises the fallback path.
- Without the fallback, every renderer call on `r.hit_rate_pct` would have been `undefined` ⇒
  `.toFixed(3)` ⇒ TypeError. The fallback rescued backward-compat for already-on-disk reports.
- `compare_diff.js` likely uses the same field names; rename touches both render targets in
  parallel.

**Cached reports stale**:

- 1007 (machine, mode) pairs flagged `stale_analyzer`; 17 machines with at least one historical
  report on disk (counted from `reports/*/mode_*/versions/*/`); 74 total version dirs across the
  fleet — of these, only **2** (the two `rv_st_split_*` fixtures under M14 mode 1) have the
  `payouts_by_spin_type` keys at all, and **both** are pre-rename schema (rescued by fallback).

**Net assessment**: 0 machines' hash flipped. `analyzer_version` flipped (already-stale by
`729a6ca`). 2 on-disk reports rely on the fallback. New reports use new names. Frontend was
explicitly engineered (`7e5fe32`) for tolerant rendering BEFORE rename so dual-schema is safe.

### 5.4 — `4cbcab2` "fix(analyzer): retain 0-win-but-fired pay_ids" (`st_win==0` → `st_hits==0`)

**Files touched**:

- `fresh_slotlab/player_impact_analyzer.py` line ~6481 (filter changed in the
  `payouts_by_spin_type` generation loop).
- `tests/backend/test_analyzer_st_split.py` (added Test 10 + 11).

**Hash impact**:

- `analyzer_version` flips (1-line change in the analyzer source).
- `code_md5` / `config_md5`: unchanged.

**Semantic impact**:

- Per commit message: M31 pid 666 (FreeSpin scatter trigger marker) fires 2,974 times with
  total_win=0. Before: filter `st_win == 0.0` silently dropped pid 666 from
  `payouts_by_spin_type[ST43_paid]`. After: filter `st_hits == 0` keeps pid 666 (hit_count=2974,
  total_win=0, rtp_contribution_pp=0).
- Aggregate (`payout_ids_top20`) was always fine; this fix aligns the split.
- **Fleet-wide impact**: any machine with a non-paying trigger pay_id (M15 scatter trigger / M279
  bonus enter markers per commit's "Not verified" section) silently had trigger pids dropped
  from the ST-split panel pre-fix. Post-fix they reappear.

**Frontend break vs fallback**:

- Frontend renderer `renderPayoutsBySpinType` (`app.js:5026`) just iterates whatever rows the
  analyzer emits. No break, no fallback needed. The new pid 666 row renders as `[666, 付费, 2,974,
  0.75%, —, —, 0.00pp]` per commit message; the `—` for multiplier comes from `_fmtMult`'s
  "render — for mult=0" rule.

**Cached reports stale**:

- 1007 (machine, mode) pairs flagged `stale_analyzer` again (cumulative — the badge is just "did
  analyzer source change?"; doesn't track which change).
- Reports already on disk: 74 version dirs across 17 machines. Only 2 have `payouts_by_spin_type`
  at all (the M14 ST split fixtures). **Neither has pid 666** in the M14 case. Real-world impact:
  - M31 reports: regenerated locally per commit's "Verified happy path" (untracked .gitignore on
    reports/). User must re-run analyzer on rawdata to see new pid 666 row.
  - M15 / M279 / other trigger-marker machines: must regen analyzer to see corrected ST-split
    panel.

**Net assessment**: 0 hash flips; analyzer_version flipped. Semantic enrichment — old reports stay
correctly renderable but exhibit a **silent drop** of trigger pids in ST-split (the M31 pid 666
class of pids). User-visible only via regen. Fleet-wide audit deferred to validator (per commit
message: "Other machines with similar 0-win trigger markers — should also benefit but fixture
regen not done this session").

### 5.5 — `5c4a111` (REVERTED by `284fd19`) "strict-binary spin_type_category, drop 80% threshold"

**Files touched** (then reverted):

- `fresh_slotlab/player_impact_analyzer.py` lines 6404-6417 — replaced
  `dominant_share >= 0.8 → "paid"` heuristic with `len(active_STs) == 1 → sole_st.behavior;
  len(active_STs) >= 2 → "mixed"`.
- `tests/backend/test_analyzer_st_split.py` (Test 11 added then reverted).

**Hash impact (if it had stuck)**:

- `analyzer_version` would flip; same 1007 (machine, mode) → `stale_analyzer`.
- `code_md5` / `config_md5`: unchanged.

**Semantic impact (if it had stuck)**:

- M31 specifically: pids 10 + 11 with 90.04% / 90.20% paid-share were labeled `paid` under old
  threshold rule; would have flipped to `mixed`. The two pids' badge in `app.js renderPayIdOverview`
  (consumer of `payout_ids_top20[].spin_type_category`) would have shown `混合` instead of `付费`.
- **Fleet-wide unaudited**: per the commit's own "Not verified" section: "Other machines
  (M14/M15/M37/M279) may have similar borderline pids whose aggregate badges flip from 'paid' →
  'mixed' or 'bonus' → 'mixed' after this change. Frontend renders whatever analyzer emits so no
  UI breakage; user may want to regen those reports to see the corrected badges."
- Real impact estimate: across 421 real-fleet machines, any pid with `dominant_share` in the
  [80%, 100%) band would have flipped category. Without a fleet scan we cannot count precisely;
  expected to be hundreds of pid-rows across the fleet.

**Frontend break vs fallback**:

- `app.js renderPayIdOverview` reads `pr.spin_type_category` (line 4841) and uses it directly to
  pick the badge class. **No fallback**: the renderer doesn't know whether the badge it shows is
  pre-fix or post-fix. The CHANGE is silent on the frontend.
- `app.js renderPayoutsBySpinType` derives `spin_type_category` from parent label (`app.js:5083-5113`)
  when missing — separate path, unaffected by the threshold logic.

**Reversion (`284fd19`)**: restores the 80% threshold. `analyzer_version` flips back to a value
close to (but not identical to) pre-`5c4a111` — comments / formatting differences keep it from
matching byte-for-byte even if logic restored. Net: `analyzer_version` movement triggers another
fleet-wide `stale_analyzer` flag cycle.

**Net assessment**: 0 hash flips. `analyzer_version` flips twice (once on commit, once on revert).
Threshold revert is the intended outcome per `00_brief.md` §7 (out of scope for Wave 2).

### 5.6 — Cross-case summary table

| Commit | code_md5 flips (virtual / real) | config_md5 flips | analyzer_version flips | Reports newly stale (analyzer) | Reports newly stale (rawdata) | Frontend break? |
|---|---|---|---|---|---|---|
| `54b7d01` (scatter kind) | 6 virtual / 0 real | 1 virtual (M31sim) | No | 0 | 6 virtual machines' cached chunks tagged historical | No |
| `729a6ca` (ST-split add) | 0 / 0 | 0 | Yes | 2030 runs / 1007 (m,mode) pairs | 0 | Additive — no break |
| `8411c9d` (rename hit_rate_pct → hit_rate) | 0 / 0 | 0 | Yes | (already stale from 729a6ca) | 0 | Protected by fallback (`7e5fe32`) for 2 fixtures on disk |
| `4cbcab2` (st_win → st_hits filter) | 0 / 0 | 0 | Yes | (already stale) | 0 | No |
| `5c4a111` reverted (80% threshold) | 0 / 0 | 0 | Yes (twice; commit + revert) | (already stale) | 0 | No (silent label change in badges) |

**Pattern**: every analyzer source touch flips `analyzer_version`, invalidating 1007 (machine,
mode) pairs unconditionally. Hash flips on the virtual side cascade across all 6 virtual machines
when `core/engine/*.py` is touched. Schema renames are at the mercy of frontend fallback
discipline — the `payouts_by_spin_type` family is the only one with fallback today (and only
because `7e5fe32` was committed specifically for that purpose).

---

## §6 Fragility hotspots — top-10 fan-out (informational)

Ranked by transitive consumer count and structural depth. **Not a recommendation list — purely a
map of which symbols have the largest blast radius today.**

| # | Symbol | Module:line | Reason for top-10 placement |
|---|---|---|---|
| 1 | `compute_analyzer_version` | `player_impact_analyzer.py:2141` | SHA256 of entire analyzer file. By design: comment edit = 2030 completed runs × 1007 (machine, mode) pairs flagged `stale_analyzer`. No filtering, no scope. Maximum non-architectural blast in the system. |
| 2 | `compute_code_md5(machine_name)` | `machine_version.py:109` | Hashes 11 shared `core/engine/*.py` + `core/emitter/*.py` files into every machine's code hash. Touching ANY of those 11 files flips ALL 6 virtual machines' `codeSummaryMd5` simultaneously, marking all cached virtual chunks for those machines as historical. Per Phase B docstring: "Touching core/* flips every machine's md5 (framework change)." |
| 3 | `extract_round_win` / `extract_round_payouts` | `round_win.py:430, 451` | Hot path of every chunk parse; semantics changes ripple through every report's RTP attribution. Currently rule-driven with 13 machines having explicit rules; non-rule machines fall through to legacy default. |
| 4 | `parse_chunk_response` | `player_impact_analyzer.py:2354` | Single-place chunk parser; every cached envelope replay goes through it. Schema-drift detection (upstream API field rename) lives downstream of this. |
| 5 | `_save_chunk_cache` + envelope stamping (`_config_md5`, `_code_md5`, `_chunk_index`, `_analyzer_version` not — only first three) | `player_impact_analyzer.py:2187` | Every chunk on disk inherits stamping decisions made here. Layout change ⇒ sidecar peek regex `chunk_index.py:_PEEK_RE_CORE` (line 123) breaks ⇒ cache layer downgrades to full-load fallback. |
| 6 | `_PEEK_RE_CORE` + `peek_chunk_envelope` | `chunk_index.py:123, 145` | Optimization invariant: envelope writers MUST place `_chunk_index`, `_config_md5`, `_code_md5` BEFORE `response` in the JSON envelope. Pair `_save_chunk_cache` + `peek_chunk_envelope` together — a writer-side reorder silently halves cache-replay throughput. |
| 7 | `is_paid_round` | `round_classification.py:104` | Fundamental classifier: every paid-vs-bonus split downstream depends on `CostCredits > 0` semantics. Used in `round_classification` (4×), `round_win` (3×), `trigger_sessions` (7×). |
| 8 | `compute_trigger_sessions` | `trigger_sessions.py:131` | Bonus-session aggregation: filter changes propagate to `payout_ids_top20` (double-count guard), `bonus_chain_dynamics`, `payouts_by_spin_type` (via the ST-split path). |
| 9 | `get_chunks_index` (+ `update_chunk_entry`, `bulk_remove_chunk_entries`, `chunks_by_md5`) | `chunk_index.py:407, 422, 548, 635` | Sidecar layer used by analyzer (4×), backend app.py (4-8× per function), virtual_analyzer (2×), rawdata_index (3×). Self-healing semantics here — any signature change forces a rebuild migration. Per `chunk_index.py` module docstring, "Pure functions, shared verbatim between real console and virtual console". |
| 10 | Module global `RAWDATA_ROOT` in `app.py:518` | `src/web_console/backend/app.py:518` | Per `app.py:3769` comment, hardcoding this global (vs using injected `self._rawdata_root`) makes virtual batch-run target the REAL console's rawdata tree. The fix discipline is "always use injected `self._rawdata_root`"; 11 references to the module global remain. Each is a coupling tripwire per memory `feedback_subprocess_import_suicide_and_module_globals.md`. |

Honorable mentions (not in top 10 but high fan-out):

- `simulate_bankruptcy_from_response` + `_BankruptcyStreamAccumulator` + `compute_bankruptcy_percentiles`
  (`player_impact_analyzer.py:1141, 1266, 1373`): 4+5+4 internal callers, drives the
  `bankruptcy_simulation` block in every report.
- `classify_volatility` / `classify_experience_archetype` (`player_impact_analyzer.py:1717, 1727`):
  Universal KPIs; consumed by backend at `app.py:5811` and frontend.
- `RoundWinRule` (the ABC at `round_win.py:102`) + rule subclasses (4 implementations, 1 registry):
  API-surface fan-out — any signature change ripples through 13 machines today plus all future
  rule-bearing machines.
- `_REQUIRED_ROUND_FIELDS` / `_REQUIRED_BET_FIELDS_ANY` (`player_impact_analyzer.py:1465, 1472`):
  Schema gate — these literal lists encode the upstream API contract that 421 machines depend on.
  Per `_check_round_schema` (`:1475`) failure here is the canonical "API drift" signal.

---

End of audit. Total LoC audited: ~30,358 across primary files (per `wc -l`). Total shared symbols
tabulated: 76 across §2.1-2.10. Hash stamps mapped: 4 (compute_code_md5, compute_config_md5,
compute_analyzer_version, upstream codeSummaryMd5). Silent dependencies surfaced: 33 module
globals in analyzer + 18 in backend + 7 import-time side-effects + ~50 file-path conventions + ~30
schema fields × 17 renderers. Invalidation case studies: 5 (per brief §3 requirement). Top
fragility hotspot: `compute_analyzer_version` (2030 runs / 1007 (machine, mode) pairs blast radius
on any byte-level analyzer source touch).
