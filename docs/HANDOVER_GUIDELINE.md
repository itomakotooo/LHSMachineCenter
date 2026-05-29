# Handover Guideline

Guide for engineers taking over this repository.

## 1. First-Day Setup

- Install dependencies:
  `python -m pip install -r src\web_console\requirements.txt`
- Start local console:
  `powershell -ExecutionPolicy Bypass -File scripts\start_console.ps1`
- Open:
  `http://127.0.0.1:8877/console/`
- Verify health endpoints:
  `GET /api/health` and `GET /api/system-state`

## 2. Non-Negotiable Product Constraints

- Sampling endpoint is `POST /MachineTest/MultiRobotTestSpinVariant`
  (since 2026-04-22 variants rollout). All machine rows in
  `configs/machines.json` route through this endpoint.
  Non-variant `MachineName` (e.g. `M14`) is accepted verbatim per
  upstream spec.
- Every `machines.json` row has two name fields:
  - `machine` — display name (e.g. `M273$WheelSelector$1$1-2-3` for
    variants, `M14` for non-variants). Used for rawdata directory,
    report identity, catalog display, and the analyzer's
    `--machine` arg.
  - `upstream_key` — raw key for the Variant endpoint's
    `MachineName` field. For variants it's e.g. `M273$1$1-2-3`;
    for non-variants it equals `machine`.
- Requests must include:
  `ResetPlayerStateAfterEachSpin=true`
- Requests must include:
  `OutputAllRobotResult=true`
- Sampling stop condition is CI-driven:
  95% CI half-width `<= 0.5pp` by default.
- Player-impact report is the source of truth.
- Variants are **independent machines**, not grouped: no parent/
  child relation between `M273` and `M273$WheelSelector$0$`. The
  only cross-machine coupling is md5 fanout (upstream's
  `MachineConfigMd5` reports per underlying, so siblings share the
  same md5). See `project_variants_fleet.md` memory note.
- RTP parity invariant: `sum(payout_ids_top20.rtp_contribution_pp)
  == summary.rtp.point_pct` must hold (< 0.01pp tolerance). Any new
  aggregator adding its own RTP breakdown must contribute a parity
  test. Locked by `test_payout_ids_top20_rtp_sum_equals_summary_rtp`
  on the M272 fixture.
- Do not introduce low-value hot/cold-window style metrics.
- Do not persist raw per-spin full data as long-term report assets.

## 3. Safety Rules for Development

- Preserve backend safety interlock behavior:
  operation mutex on write endpoints.
- Preserve startup recovery behavior:
  stale `running` rows must be auto-corrected.
- Preserve cache cleanup safety:
  manual trigger only + risk-tier confirmation.
- Never commit API keys or local runtime secrets.

## 4. Git Workflow

- Branch from `main` with small, focused scopes.
- Keep one logical concern per commit.
- Include docs update when behavior/contract changes.
- Prefer PR merge to `main` after checks pass.

## 5. Required Validation Before Merge

- Lint must pass:
  `scripts\lint.ps1` (compileall + AST no-global-state guard + optional ruff + JS syntax).
- Backend tests must pass:
  `scripts\test.ps1` (runs `pytest tests/backend` + Node `pure.test.cjs`).
- For UI-touching changes, add e2e pass:
  `scripts\test.ps1 -E2E` (Playwright headless Chromium on a free port).
- Data contract:
  ensure report schema and API response compatibility unless intentionally changed.
- Operational:
  confirm `/api/health` and `/api/system-state` remain valid.

## 6. Recommended PR Description Template

- Context:
  what user/problem this change targets.
- Scope:
  files/modules changed.
- Safety impact:
  mutex/recovery/cache behavior touched or not touched.
- Test evidence:
  commands run + results.
- Migration/compatibility:
  any API/schema/runtime behavior changes.

## 7. How to Use Codex for Review

- Provide commit hash or PR diff.
- Ask for:
  bug risk, regression risk, missing tests, and safety contract violations.
- Example:
  `review commit <hash>, focus on run safety, restart robustness, and cache cleanup protections`
- Treat review findings as merge blockers if they affect:
  data correctness, safety guarantees, or API contract stability.

## 8. Run Config Workflow

Console operators build a run payload through these gated steps:

1. Pick machine and RTP mode. M14 exposes modes 1 / 2 / 5 / 7.
   Mode 2 and 5 are "RTP-exploding" bonus/freegame paths that require
   the fuzzy CI tier; switching there locks the ciSelect to value "0"
   and disables every other tier.
2. Pick target CI half-width. Mode 1 / 7 allow 0.5 / 1 / 2 / 5 pp or
   the fuzzy tier. Selecting the fuzzy tier anywhere (value "0")
   causes the backend to (a) compute `max_chunks = ceil(1_000_000 /
   (chunk_spin_times * chunk_robot_count))` so sampling targets ~1M
   spins, and (b) pass `--target-halfwidth-pp=999.0` to the analyzer
   so the CI-stop branch never fires. The backend also returns 400
   when mode ∈ {2, 5} is paired with a non-zero half-width, so the
   constraint is enforced server-side even on direct API calls.
3. (Optional) Click "Auto Tune Parallelism" to probe the current upstream
   load and get a machine-specific recommendation. The compact candidate
   grid `[8,16,24]` × `[1,2,4]` (3x3) balances coverage vs wall time; a
   per-robot early-exit skips higher conc once a lower one saturates.
   chunk_robot_count and batch_concurrency are **editable inputs** with
   preset defaults (robot=8, conc=8) — picked 2026-04-24 against
   direct-connect upstream with M14 mode 1 benchmarks (4,411 outer
   spin/s at 8×8 = 64 concurrent requests, well under the robot×conc
   >= 128 upstream ceiling). The operator can Start immediately or
   refine via Auto Tune. Changing machine or mode resets both inputs
   back to the preset so the screen always carries sensible defaults.
   NOTE: throughput heavily depends on upstream path. The 4,411 outer/s
   number is the fresh-upstream peak; per-source rate-limiting caps
   steady-state throughput at ~1,100 outer/s after a few hundred
   requests. Production sampling plans that assume sustained 4k/s
   will be wrong — budget 50-60 min per 3M-spin machine/mode in the
   limited state, not 12 min.
4. Optionally tweak advanced params (chunk_spin_times / max_chunks /
   timeout) in the collapsed "Advanced parameters" section.
5. Pick bankroll multiplier preset. Only "Standard (100x / 200x /
   500x)" aligns with the hard-coded x100 / x200 / x500 thresholds in
   `configs/classic_slots_guideline_rules.json`; Short / Long presets
   skip the A5 bankruptcy rule. The tooltip advertises this caveat.
6. Start.

The backend validates everything the frontend validates (mode 2/5
must be fuzzy, Pydantic `Field(ge=0)` for half-width, `gt=0` for the
other numeric fields). Redundant gates are intentional: the server
must stay safe against a direct curl that skips the UI.

## 9. File Ownership (Current)

- `fresh_slotlab/`:
  analyzer and metrics logic. `player_impact_analyzer.py` is the
  report-production entrypoint; it no longer builds each display
  section inline — it runs a topo-sorted feature **emit loop** over
  plugins registered in `fresh_slotlab/analyzer/feature_registry.py`
  (`ALL_FEATURES`). The 9 display features live as plugins under
  `fresh_slotlab/analyzer/features/` (e.g. `payouts_by_spin_type`,
  `reel_marginal_by_spin_type`, `bankruptcy_simulation`,
  `multiplier_profile`, `multiplier_wild`, `machine_mechanics`,
  `upstream_feature_breakdown`, `collect_mechanic`,
  `bonus_chain_dynamics`); each owns its own extract/reduce/emit.
  Analyzer core/support modules are under `fresh_slotlab/analyzer/core/`
  + `fresh_slotlab/analyzer/` (parser, aggregator, writer, manifest
  loader, topo-sort, versioning). Which features a machine uses is
  declared in its manifest
  (`slot_designer/configs/machine_manifests/<machine>.json` →
  `analyzer_features`).
- `src/web_console/backend/app.py`:
  `create_app()` factory, routes, safety interlock, persistence.
  **Side-effect free at module level**; a lint guard enforces this
  (see `scripts/check_no_global_state.py`).
- `src/web_console/backend/main.py`:
  Production uvicorn entrypoint (constructs the default app).
- `src/web_console/backend/e2e_launch.py`:
  Playwright-only entrypoint driven by `SLOT_E2E_*` env vars.
- `src/web_console/frontend/pure.js`:
  DOM-free helpers (I18N, fmt, cacheRiskTier, ...) in an IIFE;
  exposed via `window.PURE` and `module.exports`.
- `src/web_console/frontend/app.js`:
  DOM wiring that reads from `state` and delegates to `PURE`.
- `configs/`:
  machine configs and guideline rules.
- `docs/`:
  operational and contract documentation.

## 9a. Analyzer plugin model + version / report-freshness (honesty)

The analyzer was historically a single large module that built every
report section inline. It is now plugin-based: each display section is
an `AnalyzerFeature` plugin (`fresh_slotlab/analyzer/features/*.py`,
ABC in `features/_base.py`) that owns its own extract → reduce → emit;
`player_impact_analyzer.py` runs a topo-sorted emit loop over the
plugins a machine declares. Plugins self-register via
`feature_registry.register()`; the machine's manifest
(`slot_designer/configs/machine_manifests/<machine>.json` →
`analyzer_features`) selects which apply. When you add a display
section, write a plugin + add its `FEATURE_ID` to the relevant
manifests — do **not** thread new logic back into the monolith.

Versioning lives in `fresh_slotlab/analyzer/versioning.py`:

- `compute_base_analyzer_version()` — sha256 over the report-production
  import closure (the explicit `_CLOSURE_FILES` tuple, CRLF-normalized)
  **minus** the registered feature-plugin files. Editing a core/closure
  module flips the base hash; editing a single feature plugin does not.
- `compute_effective_version_for_machine(machine, mode)` — composes
  `base ⊕ {hash of each DECLARED feature} ⊕ mode` into the
  per-`(machine, mode)` `effective_analyzer_version`. This is the value
  the console uses for report freshness, so changing one machine's
  features invalidates only that machine, not the whole fleet.
- A drift-guard test (`tests/analyzer/test_honesty2_drift_guard.py`)
  fails if a new repo-local content module joins the production import
  closure but is missing from `_CLOSURE_FILES` — update the tuple when
  the guard fires for a legitimate new module.
- Do **not** hard-code a base/effective hash value in code or docs; the
  pinned hashes that exist live only in `tests/` as regression guards.

Report-freshness decision (honest + non-destructive):

- The console compares a report's stored `effective_analyzer_version`
  (in `player_impact_summary.json`) against the current value for that
  `(machine, mode)`. A mismatch marks the cell `needs_rebaseline`; it
  **never deletes** report artifacts. Re-baseline is lazy (re-analyze
  on next open) plus a rate-limited background sweep. The legacy
  whole-PIA `compute_analyzer_version()` is retained only behind the
  read-only stale-count / validate endpoints, not the delete path.
  For cache eviction, the term for non-current-md5 chunks is
  `historical` (a tag, not a destruction signal — see
  `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md`).
- Backend memoization: `src/web_console/backend/effective_version_cache.py`
  (deliberately outside the closure so importing it can't flip the base
  hash) caches the per-`(machine, mode)` version per request and
  distinguishes "no manifest" (UNVERIFIABLE — not stale) from "closure
  file missing" (loud error).
- Virtual machines have no manifest, so the virtual analyzer
  (`slot_designer/core/backend/virtual_analyzer.py`) stamps the base
  hash + `effective_analyzer_version_kind = "virtual_base_only"` — an
  honest "virtual: no manifest" state, never an empty/swallowed value.
  The prod-vs-virtual contract is in `docs/PROD_VS_VIRTUAL_CONTRACT.md`.

The 2026-05-29/30 unbundle that produced this model kept report output
**byte-identical** (code moved between modules; emitted numbers
unchanged), locked by per-feature `tests/analyzer/test_*byte_identical*`
golden tests.

## 10. Test Layout

- `tests/backend/`:
  FastAPI `TestClient` integration tests that build isolated apps via
  `create_app(state_dir=tmp, ...)`. `conftest.py` stubs
  `subprocess.Popen` via an injected factory on `RunManager` so nothing
  real is spawned. `_seed.py` provides `insert_run_row` for startup
  recovery tests (self-contained; does NOT import app.py).
- `tests/frontend/pure.test.cjs`:
  Node built-in `node:test` runner against `pure.js`. No third-party
  deps. Run via `node --test tests/frontend/pure.test.cjs`.
- `tests/e2e/`:
  pytest-playwright + headless Chromium. `live_server` fixture spawns
  `python -m uvicorn src.web_console.backend.e2e_launch:app` on a free
  port with tmp state dirs and shrunk risk thresholds
  (`SLOT_RISK_MEDIUM_BYTES=2048`, `SLOT_RISK_HIGH_BYTES=8192`).

No global state is shared across tests; each uses a `tmp_path`-scoped
directory tree.

## 11. Progress feedback channel

Two HTTP endpoints serve as the live-data spine for the run / autotune
panels. Both are 1 Hz polled from the frontend and intentionally
shaped like simple read snapshots so the backend stays state-free
beyond what's already in SQLite + memory.

- `GET /api/runs/{run_id}/progress` -- existing endpoint that replays
  the per-run jsonl events file. The frontend's "fast" 1 s timer hits
  this only while `currentRunStatus === "running"`. The latest event
  goes through `pure.summarizeRunEvent` to produce the readable
  status line that lives in the runMeta panel; the same event drives
  `pure.computeRunProgressPct` for the progress bar (chunks/maxChunks
  for normal runs, total_spins/1_000_000 for fuzzy).

- `GET /api/autotune/progress` -- in-memory snapshot mutated under
  `app.state.autotune_progress_lock` by the progress callback that
  `create_app()` injects into `run_auto_tune`. Polled at 1 s by the
  frontend only while `state.autoTuneRunning` is true. Rendered via
  `pure.formatAutotuneProgress` into the autotuneMeta panel.

Whatever future modules (health dashboard, report comparison, ...)
need to push live values to the UI should follow the same shape:
**a small REST endpoint returning a snapshot dict**, with a pure
formatter helper that turns the dict into a localized string.

## 12. Player-impact drilldown data

The summary already carries everything the UI needs; the frontend
just renders it. Three drilldown panels live below the assessment
block:

- `paylines_top20` -> #paylineTable (rendered by
  `pure.formatPaylineRows` + `app.renderPaylineDrilldown`).
- `payout_groups_top20` -> #payoutGroupTable (rendered by
  `pure.formatPayoutGroupRows` + `app.renderPayoutGroupDrilldown`).
  Added in commit 9 -- the analyzer aggregates `PayoutGroupId` per
  spin (group 0 = no payout, kept as a baseline reference row).
- `symbols_top20` + `symbols_by_column_top10` -> #symbolOverallTable
  + #symbolByColMatrix (rendered by `pure.formatSymbolRows` +
  `pure.symbolByColMatrix` + `app.renderSymbolDrilldown`).

All four formatters are pure functions; extend them when adding new
drilldowns rather than threading raw summary objects through DOM
code. Tone classification (good / warn / bad) follows the same
pattern as `pure.extractMetricCards` for the KPI grid.

## 13. Dashboard layout (debug tab)

The debug tab uses a Grafana-style three-region shell. The structure
lives in `src/web_console/frontend/index.html` + `styles.css`. After
the user-feedback follow-up round, mid-area and drilldown tabs were
unrolled into stacked panels (tabs were friction without payoff for
narrative + table content), and only the multiplier-bucket chart
survived.

```
+--------------------------------------------------------+
| topbar (sticky): title | liveStatusStrip | lang/health |
+--------+-----------------------------------------------+
| side-  |  Interpretation  (#interpretationText)        |
| bar    |  KPI strip (3x4; tail dep = 2×2 grid;        |
| 260px  |    volatility + archetype have lib-rank sub)  |
| (drawer|  Assessment      (#assessment)                |
| <1120) |  Bucket distrib  (#bucketTable, TABLE-based,  |
|        |    count + rate% + RTP pp + bar; no Chart.js) |
| order: |  SpinType+Feature (#spinTypeTable +            |
| ctrl   |    #featureBreakdownInline, merged)           |
| -> cfg |  Bonus chain     (#bonusChainDynamicsPanel,   |
| -> mdl |    per-feature cards + depth + histogram)     |
|        |  Paylines drilldown    (#paylineTable)        |
|        |  Pay-ID drilldown      (#payoutGroupTable)    |
|        |  Symbols drilldown     (#symbolOverallTable)  |
|        |  Events panel          (#eventsText)          |
+--------+-----------------------------------------------+
```

Layout-impacting CSS classes:

- `.dashboard` -- 2-column grid (260px sidebar + main); collapses
  to single-column at <=1120px and the sidebar becomes a fixed
  drawer toggled by `.sidebar-toggle` (hamburger). Open state is
  `.dashboard.sidebar-open`.
- `.dash-sidebar` -- sticky column on desktop holding `.run-actions
  / .run-config / .model-config` (in that DOM order). Run-control
  is the FIRST child so Start/Auto are above the fold immediately
  on page load.
- `.dash-topbar` -- sticky topbar; `#liveStatusStrip` mirrors the
  active run summary (1 Hz, fed by `refreshCurrentRun()` calling
  `renderLiveStatusStrip({summary, pct})`) and degrades to a
  `machine . mode . status` brief when no run is active.
- Mid-area panels (`.interpretation`, `.report`, `.logs`) and
  drilldown panels (`.paylines`, `.payout-groups`, `.symbols`) all
  span the full 12-col main row and stack vertically. Per user
  feedback, tabs added friction without earning their cost for these
  text/table-heavy surfaces.
- `.chart-grid--single` -- only `bucketChart` survives; the other
  three (CI / RTP / bankruptcy) were dropped because their data
  already lived in KPI cards. The bucket chart's x-axis labels go
  through `PURE.prettyBucketLabel()` so the analyzer's internal
  keys ("ge100_lt200") render as friendly ranges ("100-200").

Multiplier bucket schema (analyzer + chart): 11 win-bearing bins
(`gt0_lt1` through `ge5000`). Refined from 10 bins to 12 bins during
the dashboard pass (old 10-bin keys `gt0_lt0.5`/`ge0.5_lt1`/`ge1_lt2`/
`ge2_lt5`/`ge100` collapsed into `gt0_lt1` + `ge1_lt5` and the deep
tail split into `ge100_lt200` .. `ge5000`), then the `eq0` row was
dropped because zero-win sessions carry no multiplier signal and
duplicate `hit_and_payout.zero_win_rate`. `return_bucket()` returns
`""` for zero-win and the accumulators skip empty keys, so the
summary never emits an `eq0` bucket. `prettyBucketLabel()` keeps
fallbacks for the legacy keys (including `eq0`) so old reports still
render.

Payline drilldown surfaces a `top_symbols` column populated by an
analyzer heuristic: for every spin where a payline paid, intersect
the leftmost-3 column symbol sets and credit the surviving symbol(s)
(falls back to the leftmost column's first symbol when no
intersection). machine config has no payline -> position mapping,
so this is best-effort but matches the classic 3+ left-to-right
slot pattern.

Interpretation prompt (`backend/app.py build_interpretation_prompt`)
includes `paylines_top20` / `payout_groups_top20` / `symbols_top20`
/ `symbols_by_column_top10` plus a "参照阈值" reference block that
mirrors `classify_volatility` / `classify_experience_archetype` and
the alert thresholds in `classic_slots_guideline_rules.json`. Output
structure has 6 sections; section 4 is "支付线与符号热点" and is
required (regression-locked by `tests/backend/test_interpret_prompt.py`).

E2E selectors that must be preserved across any future layout edits:

- Form / control IDs: `#langSelect`, `#machineSelect`, `#modeSelect`,
  `#ciSelect`, `#robotInput`, `#concInput`, `#spinInput`,
  `#maxChunksInput`, `#timeoutInput`, `#bankSessionInput`,
  `#bankMultSelect`, `#startBtn`, `#autotuneBtn`, `#stopBtn`,
  `#refreshBtn`, `#interpretBtn`, `#cacheRefreshBtn`,
  `#cacheCleanupBtn`, `#tabBtnDebug`, `#tabBtnManage`,
  `#sidebarToggle`.
- Drilldown tables: `#paylineTable`, `#payoutGroupTable`,
  `#symbolOverallTable`, `#symbolByColMatrix`.
- Status surfaces: `#runMeta`, `#autotuneMeta`, `#cacheRiskMeta`,
  `#eventsText`, `#liveStatusStrip`.
- KPI strong elements: `#kpiRtp / #kpiCi / #kpiSpins / #kpiZero /
  #kpiTail / #kpiGuide / #kpiVolatility / #kpiArchetype /
  #kpiLossStreak / #kpiMaxReturn / #kpiBigWin / #kpiBankruptX500`.
- KPI sub-line divs (populated per-card with multi-value or library
  rank text): `#kpiTailSub` (≥10/20/50/100x breakdown),
  `#kpiVolatilitySub` + `#kpiArchetypeSub` (library rank/count
  suffix driven by /api/library/distributions).
- Run-history extras: `#runListTable` (10 cols after Report Versions
  merge), `#runFilterBanner` (shown when a machine filter is active),
  `.load-run-btn` / `.delete-run-btn` (per-row).
- Feature / bonus-chain panels added in the upstream-field-audit
  round: `#featureBreakdownInline` (+ `#featureBreakdownMeta` +
  `#featureBreakdownBody`) and `#bonusChainDynamicsPanel` (+
  `#bonusChainMeta` + `#bonusChainBody`). Both carry `.hidden` when
  their respective summary block reports applicable=false.
- Chart canvas: `#bucketChart` (CI / RTP / bankruptcy canvases were
  removed in the chart-trim commit).

The manage tab (`#tab-manage`) deliberately keeps its single-column
panel stack so the cache-cleanup risk-tier e2e fixtures (which
target `#cacheRefreshBtn` / `#cacheCleanupBtn` and rely on the
manage tab being a flat panel list) keep working without changes.

Run-history table columns (10 cols after the Report Versions merge
in commit 718e955): Run ID / Status / Machine / Mode / Created At /
RTP / CI half-width / Version / Quality / Action (Load + Delete).
The separate "Report Versions" panel (section.versions,
#versionsTable) was removed; all version+quality data now lives on
the run row. RTP / CI / quality_label come from the `achieved_rtp_pct`
/ `achieved_halfwidth_pp` / `quality_label` columns on the `runs`
row, populated by `_update_report_index()` when a run completes and
backfilled on every startup by
`StateStore.backfill_rtp_ci_from_summaries()` (reads each legacy
row's summary.json). Rows where status != "completed" show em-dash
for Version (report_version is pre-allocated even for runs that
eventually fail, pointing to a directory that was never written).
Delete is wired to `DELETE /api/runs/{id}`; the backend refuses
running rows (409), removes per-run artefacts, the report version
directory, and rolls back `index.json` + `latest.json` if the run
had produced a report version. The machine catalog panel above the
run-history table is click-to-filter: each `.catalog-item` is a
button (role=button, keyboard-activatable) that toggles
`state.runFilterMachine`; a `#runFilterBanner` above the table shows
the active filter with a "clear" button. Clicking the currently
active machine or the clear button drops back to the unfiltered
list.

## 13a. Upstream API shape + schema drift

`run_sampling_chunk` does two layers of sanity checking on every
chunk response so that an unfamiliar machine or a silently renamed
field surfaces as a clear error instead of all-zero metrics. Both
errors propagate through the main loop's chunk-failure path and
end up in `_watch_run`'s `error_message`.

Layer 1 -- top-level shape (`response_shape_unexpected:...`):

- `expected_list:got_dict_keys=[...]`: upstream returned a dict
  envelope (e.g. `{roundResult, analysisResult}` instead of
  `[{roundResult, ...}]`). Tells the operator what keys came back
  so we can decide whether to add a wrapper.
- `expected_list:got_type=str`: upstream returned a string (often an
  un-decoded error body). Reports the type for diagnosis.
- `expected_robot_dicts:item_types=[...]`: top-level was a list but
  none of its items were dicts (some malformed envelope). Reports
  what types we did see.

A list with at least one robot dict goes through; non-dict items
mixed in are skipped silently as before so the chunk still completes.

Layer 2 -- round-level schema (`schema_drift_missing_fields:...`):

- `_REQUIRED_ROUND_FIELDS = (WinCredits, StopSymbolsByCol)`: every
  spin must carry these regardless of win state.
- `BetAmount` is checked via union with `CostCredits` -- at least
  one must exist (analyzer's documented fallback chain).
- `PayoutByPayline` / `PayoutGroupId` are NOT strict-checked because
  lose / no-payout spins legitimately omit them (the very first spin
  of most chunks is statistically a lose spin).

When you add support for a new machine and find its response shape
differs (different envelope, extra wrapping, etc.), update the
shape catch + add a fixture under `tests/backend/test_analyzer_parsing.py`.
If you expand `_REQUIRED_ROUND_FIELDS`, also update
`test_check_round_schema_required_fields_constant_locked` so the
contract change shows up in code review.

## 13b. Round-level surfaces in summary.player_impact

> Sections 13b–13g document what each summary surface *contains* and
> why. Several of these surfaces are now produced by analyzer feature
> plugins rather than inline monolith code (see §9a); where a section
> below says "the analyzer emits/aggregates X", the owning plugin under
> `fresh_slotlab/analyzer/features/` is what computes it. The field
> contents and contracts described here are unchanged by that move (the
> unbundle was byte-identical).

After investigating M14 + M272 round-level fields, the analyzer
emits four surfaces that previous versions either missed or showed
as informationally empty:

- `payout_ids_top20` -- ranks PayoutIdToWinAmount entries by total
  win contribution. Both M14 and M272 winning rounds populate
  PayoutIdToWinAmount, so this drilldown is the actual "Pay ID"
  view (the older `payout_groups_top20` was always group 0 because
  PayoutGroupId doesn't differentiate on M14/M272 mode 1/2 and is
  kept only for back-compat).
- `spin_type_breakdown` -- per-SpinType spins/bet/win/hit_rate/
  share/RTP. M14 mode 1 has only SpinType=1; M272 mode 1/2 splits
  140 (main) vs 126 (collect/bonus re-spin). Surfaces M272 mode 2's
  ~36% bonus contribution that the aggregate RTP hides. The
  analyzer hardcodes no SpinType meaning -- new machines/types
  appear automatically.
- `paylines_top20[].top_symbols` -- per-payline winning-symbol
  inference (left-3-col intersection heuristic + blank filter).

Plus two cross-cutting blocks at summary top-level:

- `upstream_analysis` -- server-side analysisResult.TotalWin sum
  cross-checked against our parsed total_win. Reports `matches`
  (boolean within max(1.0, server*1e-6) tolerance) plus delta /
  delta_pct. Real M14 + M272 mode 1 runs both produce `matches:
  true` with delta=0, confirming our aggregator and the upstream
  agree. Future drift would surface here before bad data leaks
  into the report.
- `collect_mechanic` -- M272+ collect bonus tally (CollectCount
  per-robot max sum, peak AccCredits, avg_spins_between_collects).
  M14 emits `applicable: false` so the LLM / future UI can suppress
  the section instead of inventing data.

The interpretation prompt subset (`backend/app.py
build_interpretation_prompt`) carries all four so the LLM can
comment on payout-id hotspots, bonus contribution, server sanity,
and collect mechanic where applicable.

## 13c. Paid-session metrics + trunk-clamp warning

After the M272 round-level investigation surfaced two follow-up
items, the analyzer was refactored from per-spin to per-paid-session
metrics:

- A "paid session" is a paid spin (CostCredits > 0) plus any
  bonus / free spins it triggers, until the next paid spin or the
  end of the robot's rounds. is_paid defaults to True when
  CostCredits is missing so legacy machines without that field
  behave like the pre-refactor (every round = a session).
- Summary's `hit_and_payout` (win_hit_rate, zero_win_rate,
  profit_spin_rate, breakeven_or_more_rate, big_win_x10_rate,
  avg_win_when_hit_x), `multiplier_profile.buckets`, `streaks`
  (loss/win streak quantiles + max), and `volatility` (avg/std/max
  return_x, return_bucket_rate) all read from session-level
  counters now. Bonus chains attribute their wins back to the
  session that triggered them.
- `rtp.point_pct` denominator switched to session_bet_sum (paid
  bet only). The old total_bet also added BetAmount for bonus
  spins -- on bonus-heavy machines (M272 mode 2: 46% bonus rounds)
  this dragged true RTP from ~563% down to ~286%.
- `sampling.paid_spins` + `sampling.bonus_spins` added so the
  paid/bonus split is visible. `total_spins` still records the full
  round count for sample-size gates.
- `collect_mechanic.clamp_warning` flags chunks that ran out of
  SpinTimes mid-collect-cycle: paid spins accumulated past the
  last collect trigger but the next one never fires inside the
  sample. We surface raw signals (pending_robots,
  total_pending_paid_spins, pending_share_of_paid_spins,
  avg_paid_spins_per_collect) instead of fabricating an
  estimated lost RTP -- per-collect bonus payout varies too much
  per machine for a heuristic to be honest.

The frontend's interpretation panel renders the warning text via
`#rtpClampWarning` (pure helper i18n key `rtpClampWarning`) when
`clamp_warning.applicable` is true. The interpretation prompt
subset already passes the full collect_mechanic block to the LLM.

When adding a new machine with a different collect mechanic, no
analyzer change is needed -- CollectCount + AccCredits suffice.
If the machine uses a different field name, surface it via a small
extension to the collect tracking block (see commit history) so
clamp_warning continues to fire for truncated-cycle chunks.

## 13d. Upstream field audit: 4 additional surfaces

Commit c3e7096 mined four fields the previous analyzer was either
ignoring or aggregating too coarsely. All four are
upstream-authoritative (no heuristic / no hardcoded semantics) so
they generalize to any new machine automatically.

- **Tail dependency multi-threshold** -- `guideline_assessment.
  derived_metrics.tail_dependency_ge{10x,20x,50x,100x}` + matching
  `tail_rtp_contribution_pp_ge{10x,20x,50x,100x}`. Shows how fast
  the tail mass decays as x rises. Frontend `kpiTail` primary
  displays ge10x (the canonical classify_volatility input);
  `#kpiTailSub` renders the ≥20/50/100x breakdown as a compact
  sub-line. Legacy `tail_dependency` alias preserved for
  back-compat.

- **Upstream feature breakdown** -- `player_impact.
  upstream_feature_breakdown` parsed from `analysisResult.FeatureWin`
  which groups payouts by a NAMED feature string ("Normal",
  "NormalCollectionSpin", "NewFreespin", ...). Single-feature
  machines (M14: only "Normal") emit applicable=false. Multi-feature
  machines render `#featureBreakdownInline` with per-feature
  total_win / rtp_contribution_pp / share_of_total_win and a
  per-payout_id table with share_of_feature_win bar. The feature
  name itself is the operator-facing "SpinType name" the user asked
  for -- derived from the machine's own labeling, not hardcoded.

- **Bonus chain dynamics** -- `player_impact.bonus_chain_dynamics`
  parsed from the `ReMarks` round field which M272 bonus rounds
  populate with "Freespin N; CollectCount:X; AddCollectCount:Y;
  ExtraRatio:R; [AddFreespins; M]". Per-chain length + peak ratio
  quantiles (p50/p90/p95/max), self_retrigger_round_rate,
  avg_retriggers_per_chain, extra_ratio_histogram, and an
  extra_ratio_by_chain_depth curve that bucketizes chain depth into
  1 / 2-5 / 6-10 / 11-20 / 21+ so the UI can draw the
  energy-ramp view of MapCollection's multiplier escalation.
  M14 rounds carry no Freespin annotations -- applicable=false and
  `#bonusChainDynamicsPanel` hides.

- **RewardLastNode-based winning symbols** -- `paylines_top20[].
  top_symbols` now prefers the RLN numeric symbol codes (from the
  upstream RewardLastNode field on the winning spin) when they're
  present, and falls back to the left-3-col intersection heuristic
  otherwise. `top_symbols_source` ("rln" / "heuristic") labels
  each row so future UI work can badge which path fired.

## 13e. SpinType breakdown RTP denominator fix

The `player_impact.spin_type_breakdown` RTP denominator used to sum
`BetAmount` across all rounds of a given SpinType, which made
free-spin types (M272 SpinType=126: BetAmount=1000 but CostCredits=0
because the player doesn't pay for bonus rounds) look like
rtp_pct=243%. Fix: analyzer now maintains `spin_type_paid_bet`
(sums CostCredits>0 amounts only) and emits `rtp_pct` as null for
all-free types; UI renders "N/A" instead of a meaningless number.
`behavior_name` is also added, derived from per-type paid-round
count: "paid" / "free" / "mixed". The new `#spinTypeTable` has a
`Behavior` column showing the localized label so the operator
immediately sees which rows are free-spin.

## 13f. Graceful Stop + cancelled status

Commit 1714b93 replaced the old hard-terminate cancel with a
cross-platform graceful-stop flow so partial data survives Stop.

- Analyzer: new `--stop-flag-file PATH` arg. Main loop polls the
  file's existence between chunks; on appearance, sets
  `stop_reason="user_stop"` and falls through to the normal
  summary-build path. SIGTERM / SIGINT handlers are also registered
  on platforms that support them. Windows
  subprocess.terminate()==TerminateProcess doesn't deliver a
  catchable signal -- the flag file is what actually works cross-
  platform.
- Backend `cancel_run` writes `{progress_dir}/{run_id}.stop`
  instead of calling process.terminate(); cancel response status
  is "cancelling". Falls back to hard terminate() only if the flag
  write fails.
- `_watch_run` promotes exit-0 + user_stop + total_spins>0 to
  status "cancelled" (NOT failed). The partial summary is written
  to the report index/latest like a completed run. Zero-spin +
  user_stop still flips to cancelled but with an error_message
  noting "cancelled by user before any chunk completed". The
  existing failed path still fires for non-user zero-spin (504 /
  schema drift / network).
- Frontend `refreshCurrentRun` renders the full panel stack for
  status==completed OR cancelled; `interpretBtn` is enabled on
  cancelled too (LLM can meaningfully comment on partial data).
  `statusText()` auto-routes "cancelled" via the existing
  status<Camel> i18n convention.

## 13g. Library-wide relative ranking

Commit ed90aa9 added `GET /api/library/distributions` which walks
every `reports/<machine>/mode_<n>/latest.json` + its linked
summary.json to emit per-metric distribution stats. Frontend calls
this on each summary load (completed / cancelled paths) and feeds
the result into `applyLibraryRanking()` which sets
`#kpiVolatilitySub` ("全库 P87 (15/17)" for big libraries; "全库
N/M" for 2-machine libraries because percentile on n=2 is noise)
and `#kpiArchetypeSub` ("{count}/{total} 机台同类型", categorical).
The volatility score is a composite max(zero_win/0.82,
loss_p95/18, tail_ge10/0.50) -- 1.0 = Very High threshold reached
-- so ranking it exposes continuous intensity the discrete
Very High/High/Medium/Low label can't.

`computeLibPercentile()` + `formatLibRank()` are pure helpers (locked
by tests/frontend/pure.test.cjs) so the ranking logic stays DOM-free
and testable.

## 14. Troubleshooting

- **`scripts/lint.ps1` fails on `check_no_global_state.py`**: somebody
  reintroduced module-level `StateStore()` / `RunManager()` /
  `OperationCoordinator()` / `RuntimeModelConfig()` / `FastAPI()` /
  `create_app()` in `src/web_console/backend/app.py`. Move the call
  into `create_app()` (or `main.py` for the default instance).
- **`scripts/test.ps1` exits 1 with 'node is required'**: install
  Node 18+ (https://nodejs.org) or pass `-AllowMissingNode` to skip
  the frontend `pure.test.cjs` suite. The backend suite always runs.
- **`scripts/test.ps1 -E2E` fails 'Playwright chromium not installed'**:
  run `python -m playwright install chromium` (~120 MB one-time) or
  pass `-Install` so the script installs it for you.
- **E2E test seeds a run row but startup recovery wipes it**: seed
  AFTER the server is up. The `live_server` fixture exposes
  `db_path` precisely for this pattern.
