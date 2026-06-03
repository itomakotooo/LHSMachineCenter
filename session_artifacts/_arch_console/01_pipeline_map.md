# 01_pipeline_map — Web Console Render Layer & Summary→Panel Contract

> Branch: `claude/playtype-rearch`. Mapped 2026-06-03.
> Source files: `src/web_console/frontend/app.js` (9221 lines), `src/web_console/frontend/pure.js`, `src/web_console/frontend/compare_diff.js`, `src/web_console/frontend/index.html`, `src/web_console/backend/app.py` (12177 lines), `fresh_slotlab/analyzer/features/*.py`.

---

## 1. Scope & Entry Points

**Pipeline**: analyzer produces `player_impact_summary.json` → backend serves it at `GET /api/runs/{run_id}/report` → frontend `refreshCurrentRun` fetches it → `_paintAnalysisFromSummary(s)` dispatches to ~18 named render calls. Two async panels (`renderPaylineClassification`, `renderPayIdOverview`) make additional API calls inside the panel function itself.

**Data enters the frontend** at two points:
1. **Normal load** (`app.js:7375`): `report = await apiGet(/api/runs/${state.currentRunId}/report)` → `s = report.summary` → `state.latestSummary = s` → `await _paintAnalysisFromSummary(s)`.
2. **Compare mode enter** (`app.js:3765`): `_enterCompareMode(a, b, vA, vB)` sets `state.compareMode = {a, b, vA, vB}` then calls `await _paintAnalysisFromSummary(a)` directly (skipping the API fetch). B summary travels as `state.compareMode.b`.

---

## 2. Render Dispatch Flow

### Central entry function

```
async function _paintAnalysisFromSummary(s)   // app.js:7036
```

Called by:
- `refreshCurrentRun` at `app.js:7397` (normal load, status "completed" or "cancelled")
- `_enterCompareMode` at `app.js:3765` (A/B compare activation)
- `_onCompareExit` at `app.js:3834` (compare exit, repaint single-mode)

### Ordered render-call sequence inside `_paintAnalysisFromSummary`

The function is long (~200 lines); the panel-render tail executes in this order:

| Order | Call | app.js line |
|-------|------|-------------|
| 1 | KPI cards (via `PURE.extractMetricCards`) + `setKpi(...)` loop | 7039–7086 |
| 2 | Tail-dependency 2×2 grid (`kpiTailGrid`) | 7091–7122 |
| 3 | Big-win 4-tile grid (`kpiBigWinGrid`) | 7123–7148 |
| 4 | Bucket distribution table (`bucketTable`) | 7166–7228 |
| 5 | `renderRtpClampWarning(s)` | 7230 |
| 6 | `renderReportSelfCheck(s)` | 7231 |
| 7 | `renderSpinTypeBreakdown(s)` | 7232 |
| 8 | `renderFeatureBreakdownPanel(s)` | 7233 |
| 9 | `renderPaylineClassification(s)` ← **async, fire-and-forget** | 7238 |
| 10 | `renderPayIdOverview(s)` ← **async** | 7239 |
| 11 | `renderPayoutsBySpinType(s)` | 7240 |
| 12 | `renderFieldDiscovery(s)` | 7241 |
| 13 | `renderMachineMechanics(s)` | 7242 |
| 14 | `renderBonusChainDynamicsPanel(s)` | 7243 |
| 15 | `renderCollectCyclePanel(s)` | 7244 |
| 16 | `renderPaylineDrilldown(s)` | 7245 |
| 17 | `renderSymbolDrilldown(s)` | 7246 |
| 18 | `renderReelMarginalBySpinType(s)` | 7247 |
| 19 | `renderBankruptcyAnalysis(s)` | 7248 |

Library ranking fires asynchronously at `app.js:7154–7164` (inside the function, before the panel tail): `await apiGet(/api/library/distributions)` → `applyLibraryRanking(s, dist)`.

**Note**: `renderPaylineClassification` is explicitly fire-and-forget (comment at app.js:7234–7237). Its `await` is NOT inside the parent `await _paintAnalysisFromSummary(...)` call chain.

### How A/B compare threads the second summary

- `state.compareMode` is set by `_enterCompareMode` at app.js:3743: `{ a, b, vA, vB }`.
- Every compare-aware render function opens with: `const cmpB = state.compareMode && state.compareMode.b ? state.compareMode.b : null;` — this pattern appears at lines 3965, 4090, 4300, 4797, 5384, 5523, 5852, 6348, 7043.
- `_paintAnalysisFromSummary` is called with `a` (primary) as its argument `s`. Each panel reads `cmpB` from module state directly, without any parameter passing.
- `compare_diff.js` (loaded as `window.COMPARE_DIFF`): pure-logic module (no DOM, no fetch). Used only at app.js:7074–7075 for the RTP KPI Δ significance chip (`COMPARE_DIFF.isSignificant(d, _ciA, _ciB)`). The file provides `unionKeys`, `alignByKey`, `signDelta`, `isSignificant` but the bulk of A/B cell rendering is done by `_cmpCell` / `_cmpDelta` inline helpers (app.js:4521–4610).

### How variant / multi-current / historical cell selection picks the summary

The cell selection is handled in the catalog/detail-pane layer (not in `_paintAnalysisFromSummary`). When the operator clicks "载入" on a run row, `state.currentRunId` is set and `refreshCurrentRun` fetches `GET /api/runs/{run_id}/report`. The backend `run_report` endpoint at app.py:10237 reads `summary_file` from the run row and returns `{"summary": <full_summary_dict>, ...}`. There is no variant-resolution or cell-selection logic inside the render dispatch; the summary object that reaches `_paintAnalysisFromSummary` is already resolved to one specific machine+mode+version.

---

## 3. Full Panel Inventory Table

Panels are listed in DOM order within the debug tab (matching index.html:89–296), then the retired stubs.

| # | Function | app.js line | Summary path(s) read | Container element id | In central dispatch? | Gating condition | Type |
|---|----------|-------------|----------------------|--------------------|---------------------|-----------------|------|
| 1 | _(inline: KPI tiles)_ | 7036–7086 | `s.rtp.point_pct`, `s.sampling.achieved_halfwidth_pp`, `s.sampling.paid_spins`/`total_spins`, `s.player_impact.hit_and_payout.*`, `s.guideline_assessment.classification.experience_archetype`, `s.guideline_assessment.derived_metrics.*`, `s.player_impact.volatility.*`, `s.player_impact.streaks.*` (via `PURE.extractMetricCards`) | `kpiRtp`, `kpiCi`, `kpiSpins`, `kpiZero`, `kpiTailGrid`, `kpiBigWinGrid`, `kpiVolatilitySub`, `kpiArchetype`, `kpiLossStreak`, `kpiMaxReturn` | Yes (inline code, no function name) | Always rendered | kv-table / multi-tile |
| 2 | _(inline: bucket table)_ | 7166–7228 | `s.player_impact.multiplier_profile.buckets[]` | `bucketTable` (tbody) | Yes (inline code) | Always rendered; empty tbody if no buckets | rows-table |
| 3 | `renderRtpClampWarning` | 4271 | `s.collect_mechanic.clamp_warning.{applicable, pending_robots, total_pending_paid_spins, avg_paid_spins_per_collect}` | `rtpClampWarning` | Yes (line 7230) | Hidden when `!cw.applicable` | banner |
| 4 | `renderReportSelfCheck` | 4179 | `s.rtp_integrity_check.{error, completeness_declared, passed, layer1_invariant_ok, layer1_error, layer2_no_fallback_buckets_ok, layer2_fallback_buckets_found, layer3_anchors_ok, layer3_missing_anchors, layer4_applicable, layer4_per_st_consistency_ok, layer4_inconsistencies, summary_message, suggested_actions}` | `reportSelfCheck` | Yes (line 7231) | Hidden when field absent (old reports) | banner |
| 5 | `renderSpinTypeBreakdown` | 4293 | `s.player_impact.spin_type_breakdown[]` (via `PURE.formatSpinTypeRows`); also `s.player_impact.spin_type_coverage` for heading | `spinTypeTable` (tbody) | Yes (line 7232) | Always rendered; empty-row if no rows | rows-table |
| 6 | `renderFeatureBreakdownPanel` | 5841 | `s.player_impact.upstream_feature_breakdown.{applicable, features[].{feature_name, trigger_only, chain_parent_feature, rtp_contribution_pp, share_of_total_win, fires_spins, fire_rate, buckets[], sub_streams[]}}` | `featureBreakdownInline` | Yes (line 7233) | Hidden (innerHTML="") when no features | bespoke-multi-section |
| 7 | `renderPaylineClassification` | 4626 | `s.machine`, `s.mode`; then fetches `GET /api/classifier/{machine}` for `{modes, per_st_verdicts, feature_delta_from_paid}` | `paylineClassificationPanel`, `paylineClassificationBody` | Yes (line 7238) — fire-and-forget | Hidden if classifier returns no modes | rows-table |
| 8 | `renderPayIdOverview` | 4778 | `s.player_impact.payout_ids_top20[]` (primary), `s.sampling.bet`, `s.machine`, `s.mode`; also fetches `GET /api/paytables/{machine}/mode/{mode}/shape` for shape/wild inference; fetches `GET /api/virtual/paytable/{machine}` for declared pays (virtual console only) | `payIdOverviewPanel`, `payIdOverviewBody` | Yes (line 7239) | Hidden when no payout rows on both A and B | bespoke-multi-section |
| 9 | `renderPayoutsBySpinType` | 5380 | `s.player_impact.payouts_by_spin_type` (dict keyed by `"ST{N}_{behavior}"`, values = arrays of payout rows); `s.sampling.bet` | `payoutsBySpinTypePanel`, `payoutsBySpinTypeBody` | Yes (line 7240) | Hidden when no data on both A and B | drilldown |
| 10 | `renderFieldDiscovery` | 5812 | `s.player_impact.field_discovery.{extra_field_count, extra_fields[].{field, occurrences}}`; `s.sampling.total_spins` | `fieldDiscoveryPanel`, `fieldDiscoveryTable` (tbody) | Yes (line 7241) | Hidden when `!fd.extra_field_count` | rows-table |
| 11 | `renderMachineMechanics` | 4391 | `s.player_impact.machine_mechanics.{lock_lines, lock_symbols, lock_reels, jackpot, free_spin, dollar_pick}` — each sub-key has `.applicable` plus metric fields | `machineMechanicsPanel`, `mechanicsBody` | Yes (line 7242) | Hidden when `!mm` or no sub-key `.applicable` | bespoke-multi-section |
| 12 | `renderBonusChainDynamicsPanel` | 6256 | `s.player_impact.bonus_chain_dynamics.{applicable, chain_count, bonus_round_count, avg_chain_length, chain_length_quantiles, chain_max_ratio_quantiles, self_retrigger_round_rate, by_feature, extra_ratio_histogram[], extra_ratio_by_chain_depth[]}` | `bonusChainDynamicsPanel`, `bonusChainBody` | Yes (line 7243) | Hidden when `!d.applicable` or `!d.chain_count` | bespoke-multi-section |
| 13 | `renderCollectCyclePanel` | 6150 | `s.collect_mechanic.{cycle_observation.{mechanic_detected, reset_observed, cycle_len_lower_bound, warning}, bonus_cycle_correction.{applicable, estimated_correction_pp, detected_cycle_length, completed_cycles_total, robots_with_pending_cycle, avg_bonus_payout, bonus_feature, bonus_feature_source}, feature_match.{bonus_feature, bonus_feature_source, warning}}`; also `s.rtp.point_pct` | `collectCyclePanel`, `collectCycleBody` | Yes (line 7244) | Hidden when `!co.mechanic_detected && !bcc.applicable` | bespoke-multi-section |
| 14 | `renderPaylineDrilldown` | 4081 | `s.player_impact.paylines_top20[]` (via `PURE.formatPaylineRows`): `{payline_id, hit_count, hit_rate, approx_rtp_contribution_pp, win_share_pct, top_symbols[], top_symbols_source}` | `paylineTable` (tbody) | Yes (line 7245) | Always rendered; empty-row if no rows | rows-table |
| 15 | `renderSymbolDrilldown` | 3960 | `s.player_impact.symbols_top20[]` (overall, via `PURE.formatSymbolRows`); `s.player_impact.symbols_by_column_top10`, `s.player_impact.symbols_by_column_top10_payline`, `s.player_impact.payline_rows_per_col` (per-column, via `PURE.symbolByColMatrix`) | `symbolOverallTable` (tbody), `symbolByColMatrix` | Yes (line 7246) | Always rendered; empty-text if no rows | drilldown |
| 16 | `renderReelMarginalBySpinType` | 5519 | `s.player_impact.reel_marginal_by_spin_type` (dict keyed by `"ST{N}_{behavior}"`, values = per-reel-column dicts of symbol arrays) | `reelMarginalBySpinTypePanel`, `reelMarginalBySpinTypeBody` | Yes (line 7247) | Hidden when no data on both A and B | drilldown |
| 17 | `renderBankruptcyAnalysis` | 6340 | `s.player_impact.bankruptcy_simulation.{tiers[].{bankroll_multiplier, robots, completed_robots, bankruptcy_rate, median_spins_completed, fastest_bankruptcy_spins, percentiles}, session_spins, percentile_keys[]}` | `bankruptcyPanel`, `bankruptcyBody` | Yes (line 7248) | Hidden when no tier has `robots > 0` | bespoke-multi-section |

**Panels rendered inline (not by named `render*` fn) inside `_paintAnalysisFromSummary`**:

| # | Description | app.js lines | Summary path(s) | Container id | Type |
|---|-------------|-------------|-----------------|--------------|------|
| 18 | Tail-dep 2×2 grid | 7091–7122 | `s.guideline_assessment.derived_metrics.{tail_dependency_ge10x, _ge20x, _ge50x, _ge100x}` | `kpiTailGrid` | multi-tile |
| 19 | Big-win 4-tile grid | 7123–7148 | `s.player_impact.hit_and_payout.{big_win_x10_rate, x20, x50, x100}` (via `PURE.extractMetricCards().bigWin.tiles`) | `kpiBigWinGrid` | multi-tile |
| 20 | Library ranking sub-lines | 7154–7164 | fetches `GET /api/library/distributions?mode=N`; result applied to KPI sub-text by `applyLibraryRanking` | `kpiVolatilitySub`, `kpiArchetypeSub` | kv-table |

**Retired stubs (present in file, no-op body)**:

| Function | app.js line | Note |
|----------|-------------|------|
| `renderRunHistory` | 3951 | Retired; comment "see above" |
| `updateBatchBar` | 3952 | Retired |
| `renderPayoutGroupDrilldown` | 3958 | Retired 2026-04-20; merged into `renderPayIdOverview`; no-op `/* retired */` |

**Functions named `render*` that are NOT part of the analysis dispatch** (excluded from table above):

| Function | app.js line | Role |
|----------|-------------|------|
| `renderLiveStatusStrip` | 268 | Run status bar; called from `refreshCurrentRun`, not `_paintAnalysisFromSummary` |
| `renderCacheRiskMeta` | 446 | Cache risk metadata; manage tab |
| `renderCatalogFeatureChips` | 856 | Catalog filter chips (uses `state.staticAttrs`, not summary) |
| `renderMachineCatalog` | 908 | Machine catalog list |
| `renderMachineConfigOverride` | 1222 | Local config override toggle |
| `renderDetailPane` | 1337 | Right-pane detail container |
| `renderRawdataBanner` | 1417 | Rawdata overview banner |
| `renderRawdataGlobalTable` | 1503 | Rawdata detail table |
| `renderCatalogFilters` | 1600 | Catalog filter controls |
| `renderFleetOverview` | 2784 | Fleet-level KPI overview |
| `renderSamplingProgress` | 3283 | Sampling progress display |
| `renderServerTable` | 3543 | Server configuration table |
| `renderRunFilterBanner` | 3925 | Run filter UI banner |
| `renderRtpModeBar` | 7699 | RTP mode selector bar |
| `renderHallsRefreshBar` | 7743 | Machine halls refresh bar |
| `renderConfigList` | 8345 | Configuration list |

---

## 4. Summary→Panel Contract

### Top-level summary keys and their panel consumers

| Summary key (top-level) | Panel(s) that read it | Origin |
|------------------------|----------------------|--------|
| `machine` | `renderPayIdOverview` (line 4783), `renderPaylineClassification` (line 4629) | Universal (always written by PIA) |
| `mode` | `renderPaylineClassification` (line 4630), `renderPayIdOverview` (line 4784) | Universal |
| `rtp` (→`point_pct`) | KPI tile (line 7046), `renderCollectCyclePanel` (line 6165), `PURE.extractMetricCards` (line 1577) | Universal |
| `sampling` (→`achieved_halfwidth_pp`, `paid_spins`, `total_spins`, `bet`, `chunk_spin_times`) | KPI tiles, `renderPayoutsBySpinType` (line 5402), `renderFieldDiscovery` (line 5821), `renderCollectCyclePanel` (line 6359), `PURE.extractMetricCards` (line 1578) | Universal |
| `player_impact` (nested) | Most panels — see sub-key table below | Universal skeleton; feature sub-keys vary |
| `collect_mechanic` | `renderRtpClampWarning` (line 4278), `renderCollectCyclePanel` (line 6153) | Feature: `collect_mechanic` FEATURE_ID |
| `rtp_integrity_check` | `renderReportSelfCheck` (line 4188) | Universal (written by PIA integrity gate, not a plugin) |
| `guideline_assessment` | KPI archetype tile (line 7043), tail-dep grid (line 7094), `PURE.extractMetricCards` (line 1583) | Universal |
| `upstream_analysis` | **NOT rendered by any panel** — present in summary (PIA:4108) but no frontend panel reads it | Written by PIA; unmined by frontend |
| `topdollar_choice` | **NOT rendered by any panel** — written by `TopDollarChoice.emit()` at `topdollar_choice.py:324` as `summary["topdollar_choice"]` | Feature: `topdollar_choice` FEATURE_ID |
| `feature_errors` | **NOT rendered by any panel** — present in summary when plugin emit() fails | Written by PIA error handler |
| `analyzer_init_error` | **NOT rendered by any panel** | Written by PIA |
| `guideline_comparison` | **NOT rendered by any panel** — written at PIA:4201 | Written by PIA |
| `config_md5`, `code_md5`, `analyzer_version`, `effective_analyzer_version` | Not rendered in panels; used by backend for staleness logic | Universal |

### `player_impact` sub-key to panel mapping

| `player_impact.*` sub-key | Panel(s) | Feature FEATURE_ID |
|---------------------------|---------|-------------------|
| `spin_type_breakdown[]` | `renderSpinTypeBreakdown` (line 4293) | Universal (written by PIA core F1) |
| `spin_type_coverage` | `renderSpinTypeBreakdown` heading (line 4302) | Universal |
| `hit_and_payout.*` | KPI zero-win + big-win tiles (via `PURE.extractMetricCards`) | Universal |
| `volatility.*` | KPI max-return tile | Universal |
| `streaks.*` | KPI loss-streak tile | Universal |
| `multiplier_profile.buckets[]` | Bucket distribution table (line 7166) | `multiplier_profile` FEATURE_ID |
| `payout_ids_top20[]` | `renderPayIdOverview` (line 4789) | Universal (written by PIA core) |
| `paylines_top20[]` | `renderPaylineDrilldown` (line 4084, via `PURE.formatPaylineRows`) | Universal |
| `symbols_top20[]` | `renderSymbolDrilldown` overall table (line 3970) | Universal |
| `symbols_by_column_top10` | `renderSymbolDrilldown` per-col matrix (line 4031) | Universal |
| `symbols_by_column_top10_payline` | `renderSymbolDrilldown` per-col payline density (line 4058) | Universal |
| `payline_rows_per_col` | `renderSymbolDrilldown` per-col payline (line 4060) | Universal |
| `field_discovery.*` | `renderFieldDiscovery` (line 5815) | Universal |
| `machine_mechanics.*` | `renderMachineMechanics` (line 4394) | `machine_mechanics` FEATURE_ID |
| `upstream_feature_breakdown.*` | `renderFeatureBreakdownPanel` (line 5844) | `upstream_feature_breakdown` FEATURE_ID |
| `payouts_by_spin_type` | `renderPayoutsBySpinType` (line 5385) | `payouts_by_spin_type` FEATURE_ID |
| `reel_marginal_by_spin_type` | `renderReelMarginalBySpinType` (line 5524) | `reel_marginal_by_spin_type` FEATURE_ID |
| `bonus_chain_dynamics.*` | `renderBonusChainDynamicsPanel` (line 6259) | `bonus_chain_dynamics` FEATURE_ID |
| `bankruptcy_simulation.*` | `renderBankruptcyAnalysis` (line 6344) | `bankruptcy_simulation` FEATURE_ID |

### AnalyzerFeature SCHEMA_KEYS vs summary key written

| FEATURE_ID | SCHEMA_KEYS | Actual summary key written | SCHEMA_VERSION | Frontend panel |
|-----------|-------------|---------------------------|----------------|---------------|
| `multiplier_profile` | `("multiplier_profile",)` | `player_impact.multiplier_profile` | 1 | Bucket table (inline, no named fn) |
| `upstream_feature_breakdown` | `("upstream_feature_breakdown",)` | `player_impact.upstream_feature_breakdown` | 1 | `renderFeatureBreakdownPanel` |
| `bonus_chain_dynamics` | `("player_impact.bonus_chain_dynamics",)` | `player_impact.bonus_chain_dynamics` | 1 | `renderBonusChainDynamicsPanel` |
| `machine_mechanics` | `("machine_mechanics",)` | `player_impact.machine_mechanics` | 2 | `renderMachineMechanics` |
| `payouts_by_spin_type` | `("payouts_by_spin_type",)` | `player_impact.payouts_by_spin_type` | 2 | `renderPayoutsBySpinType` |
| `collect_mechanic` | `("collect_mechanic",)` | `collect_mechanic` (top-level) | 2 | `renderCollectCyclePanel` + `renderRtpClampWarning` |
| `reel_marginal_by_spin_type` | `("reel_marginal_by_spin_type",)` | `player_impact.reel_marginal_by_spin_type` | 1 | `renderReelMarginalBySpinType` |
| `bankruptcy_simulation` | `("bankruptcy_simulation", "bankruptcy_probe")` | `player_impact.bankruptcy_simulation` | 1 | `renderBankruptcyAnalysis` |
| `multiplier_wild` | `("multiplier_wild",)` | `multiplier_wild` (top-level? — not confirmed read) | 1 | **No frontend panel** |
| `topdollar_choice` | `("topdollar_choice",)` | `topdollar_choice` (top-level) | 1 | **No frontend panel (new, unrendered)** |

**Observation on SCHEMA_KEYS mismatch**: `bonus_chain_dynamics` lists `SCHEMA_KEYS = ("player_impact.bonus_chain_dynamics",)` using dot-notation to signal nesting (`bonus_chain_dynamics.py:229`). `collect_mechanic` writes to top-level `summary["collect_mechanic"]` but its `SCHEMA_KEYS = ("collect_mechanic",)` — the key lives at top level, not under `player_impact`. Every other plugin that writes into `player_impact` uses a bare key string in `SCHEMA_KEYS` (e.g. `"payouts_by_spin_type"`) with the `player_impact` parent implicit. This naming inconsistency in `SCHEMA_KEYS` is an observation; no normalization exists today.

---

## 5. Backend Serving

### Endpoint that serves the summary

```
GET /api/runs/{run_id}/report         app.py:10236
```

Response shape:
```json
{
  "run_id": "...",
  "summary": { <full player_impact_summary dict> },
  "report_markdown": "...",
  "summary_file": "/path/to/player_impact_summary.json",
  "report_file": "/path/to/player_impact_report.md"
}
```

The backend reads `summary_file` from the run DB row and returns the raw JSON dict without modification. No sub-setting, no field filtering.

### Other endpoints panel functions call directly

| Endpoint | Called by | app.js line |
|----------|-----------|-------------|
| `GET /api/classifier/{machine}` | `renderPaylineClassification` | 4635 |
| `GET /api/paytables/{machine}/mode/{mode}/shape` | `renderPayIdOverview` | 4811 |
| `GET /api/virtual/paytable/{machine}` | `renderPayIdOverview` (virtual console only; 404s in prod) | 4840 |
| `GET /api/library/distributions[?mode=N]` | `applyLibraryRanking` (inside `_paintAnalysisFromSummary`) | 7155–7163 |

### Does the backend expose `analyzer_features` / machine manifest to the frontend?

**No.** The backend has these machine-information endpoints:
- `GET /api/machines` (app.py:7388) — returns `machines.json` content: `{machine, modes, logicClassNames, configSummaryMd5, codeSummaryMd5, available, upstream_key}`. No `analyzer_features`.
- `GET /api/versions/current` (app.py:7392) — returns `{analyzer_version, machines: {config_md5, code_md5}, effective_versions}`. No feature list.
- `GET /api/manifests/review-state` (app.py:7870) — returns `{machine_id: {verified, reviewed, variant}}`. No `analyzer_features`.
- `GET /api/machines/static` (app.py:7949) — returns per-machine static attrs (category, logicClassNames, features observed in summary, mechanics observed in summary). `features` here is extracted from `upstream_feature_breakdown.features[].feature_name` (app.py:3366–3378), not from the manifest's `analyzer_features` list.
- `GET /api/machines/summary` (app.py:7783) — fleet-level best-CI per (machine, mode) summary.

**What is missing**: The frontend has no way to know which `FEATURE_ID` list a machine declares in its manifest (`slot_designer/configs/machine_manifests/<M>.json` → `analyzer_features` field). The manifest files are read only by the analyzer subprocess and by `GET /api/manifests/review-state` (which returns only review state, not the feature list). The `GET /api/machines/static` "features" field is an inferred retrospective list from past summaries, not the forward declaration.

**The `machines.json` file** (`configs/machines.json`) also does not carry `analyzer_features`; that field lives exclusively in the per-machine manifests under `slot_designer/configs/machine_manifests/`.

---

## 6. Shared vs Per-X Boundary Table

| File / Component | Scope | Consumers |
|-----------------|-------|-----------|
| `src/web_console/frontend/app.js` | Fleet-shared (all machines see same render code) | All machines / modes |
| `src/web_console/frontend/pure.js` | Fleet-shared | `app.js` (imports as `PURE.*`) |
| `src/web_console/frontend/compare_diff.js` | Fleet-shared | `app.js` (`window.COMPARE_DIFF`), frontend tests |
| `src/web_console/frontend/index.html` | Fleet-shared | All machines (one page structure) |
| `src/web_console/backend/app.py` | Fleet-shared | All machines / runs |
| `fresh_slotlab/analyzer/features/_base.py` | Fleet-shared (ABC) | All feature plugins |
| `fresh_slotlab/analyzer/feature_registry.py` | Fleet-shared (registry state) | PIA, feature modules |
| `fresh_slotlab/analyzer/features/multiplier_profile.py` | Per-feature (fleet-default, all machines) | Machines with `"multiplier_profile"` in manifest |
| `fresh_slotlab/analyzer/features/upstream_feature_breakdown.py` | Per-feature (fleet-default) | Machines with feature in manifest |
| `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py` | Per-feature | Machines with feature in manifest |
| `fresh_slotlab/analyzer/features/machine_mechanics.py` | Per-feature | Machines with feature in manifest |
| `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` | Per-feature | Machines with feature in manifest |
| `fresh_slotlab/analyzer/features/collect_mechanic.py` | Per-feature (fleet-default: "All 253 base manifests declare collect_mechanic" per PIA:4136) | Nearly all machines |
| `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py` | Per-feature | Machines with feature in manifest |
| `fresh_slotlab/analyzer/features/bankruptcy_simulation.py` | Per-feature | Machines with feature in manifest |
| `fresh_slotlab/analyzer/features/multiplier_wild.py` | Per-feature | Machines with feature in manifest |
| `fresh_slotlab/analyzer/features/topdollar_choice.py` | Per-machine-feature (currently: M15 family only) | M15 (and future TD family) |
| `slot_designer/configs/machine_manifests/<M>.json` → `analyzer_features` | Per-machine config | Analyzer subprocess + manifest_loader |
| `configs/machines.json` | Fleet-shared config (upstream keys, md5, modes) | Backend + frontend bootstrap |

---

## 7. Reuse vs Duplication Audit

### Production vs virtual console

The brief scope includes both; quick audit:

- **Backend**: `src/web_console/backend/app.py` is the production app. Virtual-only routes are registered separately via a `_register_virtual_only_routes` function (referenced in comment at app.js:4835). Virtual-only endpoint `GET /api/virtual/paytable/{machine}` returns 404 in production — `renderPayIdOverview` catches this silently (app.js:4848).
- **Frontend**: single `app.js` and `index.html` serve both prod and virtual. The virtual console difference is that the paytable fetch (app.js:4838–4849) succeeds in virtual and returns declared pay rows; in prod it 404s and `declaredPays` stays `[]`. No parallel implementation — the branch is inside `renderPayIdOverview` at app.js:4838 (`if (!cmpB) { try { const decl = await apiGet(.../api/virtual/paytable/...); ... } catch { declaredPays = []; } }`).

### `_renderPayingFeatureCard` helper reuse

`renderFeatureBreakdownPanel` delegates per-card rendering to `_renderPayingFeatureCard(feat, chains, bFeat)` (app.js:5972). Compare mode and single mode both use the same function; `compareMode` is detected via `state.compareMode` inside the helper (app.js:5980). No duplication.

### Compare-diff cell rendering

`_cmpCell` / `_cmpDelta` (app.js:4521–4610) are shared by all 9 compare-aware panels. `compare_diff.js` provides `isSignificant` only for the RTP KPI chip (used once at app.js:7074). No duplication.

---

## 8. Insertion Points and Hardest Cases

### Where a registry-driven assembler would slot in

The natural insertion point is at the tail of `_paintAnalysisFromSummary` (app.js:7230–7248) — specifically, replacing the hardcoded call sequence with an iteration over a panel registry. The pre-existing render calls at 7230–7248 already follow a uniform `renderXxx(s)` signature. The inline KPI section (7036–7164) is harder: it mixes data-extraction logic (`PURE.extractMetricCards`) with DOM writes across many element IDs.

The bucket table inline block (7166–7228) is also not a named function, so it would need extraction to a `renderBucketDistribution(s)` before it can be registered.

### Hardest cases for a generic assembler

**1. A/B compare-diff: B summary is a module-global (`state.compareMode.b`), not a parameter.**

Every compare-aware panel reads `state.compareMode.b` directly from module state, not from any argument. An assembler that passes `(summary)` as a positional arg would not automatically thread B. The assembler would need to pass `{summaryA, summaryB}` or expose `state.compareMode.b` as a context. This is the structural coupling that would require the most changes across all 9 compare-aware panels.

Evidence: app.js:3965, 4090, 4300, 4797, 5384, 5523, 5852, 6348, 7043 — all open with the same `const cmpB = state.compareMode && state.compareMode.b ? state.compareMode.b : null;` pattern.

**2. ST-split panels reading dynamic dict keys.**

`renderPayoutsBySpinType` and `renderReelMarginalBySpinType` read `s.player_impact.payouts_by_spin_type` and `s.player_impact.reel_marginal_by_spin_type` — both are dicts keyed by dynamic `"ST{N}_{behavior}"` labels. The panel generates one sub-block per label at render time (app.js:5456, 5553). A generic `rows-table` assembler can't cover this; these panels need bespoke render logic.

**3. Panels reading MULTIPLE summary sections.**

`renderCollectCyclePanel` reads both `s.collect_mechanic` (feature-owned) AND `s.rtp.point_pct` (universal) — app.js:6153–6165. A registry entry declaring a single `summaryKey` for this panel would be incomplete.

`renderPayIdOverview` reads `s.player_impact.payout_ids_top20` (core) AND makes two extra API calls (`/api/paytables/.../shape`, `/api/virtual/paytable/...`). It is the only panel that issues additional network requests at render time (two async fetches). This makes it incompatible with a synchronous registry pattern without special-casing.

`renderPaylineClassification` issues a network fetch to `/api/classifier/{machine}` (app.js:4635) — it reads `s.machine` and `s.mode` only to build the URL; the actual data comes from a separate endpoint, not the summary at all. This panel is fundamentally different from the others: it does not render summary data but rather supplementary classifier output.

**4. `renderFeatureBreakdownPanel` maps N features → N card DOM blocks.**

The feature breakdown panel generates one card per `upstream_feature_breakdown.features[]` entry (app.js:5928). The number and identity of features varies per machine. A generic assembler treating this as a single-panel unit would produce correct output, but the internal card layout is bespoke (chain breadcrumbs, per-feature bucket histograms via `_renderFeatureBucketTable`, orphan trigger row).

**5. `renderPaylineClassification` is fire-and-forget in the current dispatch.**

It is called at app.js:7238 without `await`, intentionally (comment: "fire-and-forget so the rest of the debug tab isn't blocked"). Any assembler that iterates panels with `await` would accidentally serialize this panel into the main promise chain, changing the latency profile.

**6. Retired panels are no-ops but still registered as functions.**

`renderRunHistory`, `updateBatchBar`, `renderPayoutGroupDrilldown` all exist at app.js:3951–3958 with empty bodies. If a registry enumerates all `render*` functions by introspection, it would pick these up. A registry would need to explicitly skip them or they would need to be deleted.

**7. Inline rendering blocks (KPI tiles, bucket table, tail-dep grid, big-win grid).**

These are embedded directly inside `_paintAnalysisFromSummary` as inline code rather than named functions. They each read distinct summary paths. Before any registrable panel system can govern them, they must be extracted into named functions.

**8. `renderSymbolDrilldown` renders TWO containers with very different layouts.**

It writes both `symbolOverallTable` (top-20 rows-table) and `symbolByColMatrix` (grid of per-column col-tables) from the same function call (app.js:3960–4079). A 1:1 panel→container mapping would need to accommodate this.

**9. No frontend knowledge of per-machine feature list.**

The backend does not expose which `analyzer_features` a machine declares (see §5 above). A registry assembler that wants to show only panels relevant to the current machine's declared features cannot query this from any existing endpoint. It can infer feature presence from the summary keys actually present in the loaded summary (e.g., `"topdollar_choice" in summary` → show TopDollar panel), but cannot predict which panels are relevant before the summary is loaded.

---

## Open Questions

1. **`upstream_analysis` key** — `summary.upstream_analysis` (written by PIA at player_impact_analyzer.py:4108) contains `{server_total_win, our_total_win, delta, delta_pct, matches, server_robots_seen}`. No frontend panel reads it. It is unclear whether this is intentionally operator-invisible (used only in report markdown) or whether a frontend panel was intended but not built.

2. **`multiplier_wild` feature** — `multiplier_wild.py` registers FEATURE_ID `"multiplier_wild"` and SCHEMA_KEYS `("multiplier_wild",)`. No panel in `app.js` reads `summary.multiplier_wild`. It is unclear if this feature's output is intentionally not surfaced in the console or if a panel was planned but not built.

3. **`guideline_comparison` key** — Written by PIA at player_impact_analyzer.py:4201 into `summary["guideline_comparison"]`. No frontend panel reads it.

4. **`feature_errors` key** — Written by PIA when a feature plugin's `emit()` raises. No frontend panel surfaces this. It would indicate a plugin failure silently to the operator.

5. **`renderPaylineClassification` fire-and-forget ordering** — If the classifier fetch is slow (LAN endpoint), the panel renders after all other panels finish. The panel's visibility depends on the classifier response, not on the summary. It is unclear whether this panel belongs in the same "analysis panel" concept as summary-driven panels, or whether it is a separate "supplementary panel" category.

6. **SCHEMA_KEYS dot-notation inconsistency** — `bonus_chain_dynamics.py:229` uses `SCHEMA_KEYS = ("player_impact.bonus_chain_dynamics",)` with a dot to indicate nesting. All other plugins use a bare string with the nesting implicit. No code in the current system processes this dot-notation; `REGISTERED_FALLBACK_RULES` are also all empty `{}` today. The meaning of this dot-notation for any future "renderer registry" is unresolved.

7. **`collect_mechanic` top-level placement** — All other feature-owned summary keys live under `player_impact.*`. `collect_mechanic` is top-level (not under `player_impact`), matching pre-C5 schema. Two panels read it: `renderRtpClampWarning` and `renderCollectCyclePanel`. A registry entry keying on `"player_impact.*"` would miss this feature's section.
