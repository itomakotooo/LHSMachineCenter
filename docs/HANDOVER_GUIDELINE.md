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

- Sampling endpoint is the provided test API.
- Requests must include:
  `ResetPlayerStateAfterEachSpin=true`
- Requests must include:
  `OutputAllRobotResult=true`
- Sampling stop condition is CI-driven:
  95% CI half-width `<= 0.5pp` by default.
- Player-impact report is the source of truth.
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
3. Click "Auto Tune Parallelism". The first click uses a wide default
   candidate grid `[8,12,16,20,24]` × `[1,2,3,4]`; subsequent clicks
   refine around the last recommendation. chunk_robot_count and
   batch_concurrency inputs are readonly -- the autotune result is
   the only way to populate them. Changing machine or mode clears
   both inputs and re-disables Start.
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
  analyzer and metrics logic.
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
| side-  |  KPI strip (3x4 compact, whole-card tone bg)  |
| bar    |  Charts (1x1, multiplier bucket only)         |
| 260px  |  Interpretation panel  (#interpretationText)  |
| (drawer|  Assessment panel      (#assessment)          |
| <1120) |  Events panel          (#eventsText)          |
|        |  Paylines drilldown    (#paylineTable)        |
| order: |  Pay-ID drilldown      (#payoutGroupTable)    |
| ctrl   |  Symbols drilldown     (#symbolOverallTable)  |
| -> cfg |                                               |
| -> mdl |                                               |
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

Multiplier bucket schema (analyzer + chart): refined from 10 to 12
bins. Old 10-bin keys (`gt0_lt0.5`, `ge0.5_lt1`, `ge1_lt2`,
`ge2_lt5`, `ge100`) collapsed into `gt0_lt1` + `ge1_lt5` and the
deep tail split into `ge100_lt200` / `ge200_lt500` / `ge500_lt1000` /
`ge1000_lt5000` / `ge5000`. `prettyBucketLabel()` keeps fallbacks
for the legacy keys so old reports still render.

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
- Chart canvas: `#bucketChart` (CI / RTP / bankruptcy canvases were
  removed in the chart-trim commit).

The manage tab (`#tab-manage`) deliberately keeps its single-column
panel stack so the cache-cleanup risk-tier e2e fixtures (which
target `#cacheRefreshBtn` / `#cacheCleanupBtn` and rely on the
manage tab being a flat panel list) keep working without changes.

## 13a. Upstream API schema drift

`run_sampling_chunk` now sanity-checks the first parsed round of every
chunk against `_REQUIRED_ROUND_FIELDS` (`BetAmount`, `WinCredits`,
`PayoutByPayline`, `StopSymbolsByCol`, `PayoutGroupId`). If the
upstream test API silently renames or drops one of these, the chunk
returns
`{ok: False, error: "schema_drift_missing_fields:WinCredits,..."}`,
the main loop aborts the run, and `_watch_run` surfaces the field
list in `error_message` so the operator sees exactly what changed
instead of debugging an all-zero RTP report.

If you intentionally add or drop a required field, update both
`_REQUIRED_ROUND_FIELDS` in `fresh_slotlab/player_impact_analyzer.py`
AND `tests/backend/test_analyzer_parsing.py::
test_check_round_schema_required_fields_constant_locked` so the
contract change is explicit in code review.

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
