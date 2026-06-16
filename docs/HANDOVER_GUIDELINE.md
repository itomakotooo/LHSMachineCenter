# Handover Guideline

Guide for engineers taking over this repository. Last reconciled with the
code on **2026-06-05**.

> **⚠ READ FIRST — the system is mid-rebuild.** The report-production
> orchestrator (`fresh_slotlab/player_impact_analyzer.py`) has been **deleted**
> and is being rebuilt SpinType-native. As a result:
> - **Report GENERATION is OFFLINE.** `POST /api/rawdata/{machine}/generate-report`
>   returns **HTTP 503** (`_run_generate_report` in `app.py` raises before doing
>   any work); the RunManager subprocess path still points at the removed module
>   via the dangling `ANALYZER` constant (`app.py` ~line 99) and would also fail.
> - **Report VIEWING still works.** The `/api/reports/...` read endpoints serve
>   `player_impact_summary.json` straight off disk and never import the analyzer,
>   so the dashboard renders existing reports normally.
> - **The reusable analyzer CORE survives** (parser / aggregator / writer /
>   round primitives / manifest + versioning machinery). The new engine is being
>   assembled on top of it. See §9.
> - For the day-to-day "understand + onboard a machine" workflow, the live
>   authority is **`docs/MACHINE_ONBOARDING.md`** — keep it open alongside this
>   file. This guide covers the repo / console / process; that one covers the
>   per-machine analysis method.

## 1. First-Day Setup

- Install dependencies:
  `python -m pip install -r src\web_console\requirements.txt`
  (or run `scripts\start_console.ps1 -Install` once.)
- Start local console:
  `powershell -ExecutionPolicy Bypass -File scripts\start_console.ps1`
  (binds `0.0.0.0:8877`; uvicorn entrypoint `src.web_console.backend.main:app`;
  auto-restarts with backoff on crash.)
- Open:
  `http://127.0.0.1:8877/console/`
- Verify health endpoints:
  `GET /api/health` and `GET /api/system-state`

## 2. Non-Negotiable Product Constraints

- The active sampling server is resolved at runtime from
  `configs/servers.json` (`default_server`, currently `dev` =
  `http://192.168.10.21:15060`; `prod` is an off-site address; `intranet` =
  loopback for single-box deploys). The sampling path appended to that endpoint
  is `POST /MachineTest/MultiRobotTestSpinVariant` (variants rollout, 2026-04-22).
- Every `machines.json` row has two name fields:
  - `machine` — display name (e.g. `M273$WheelSelector$1$1-2-3` for
    variants, `M14` for non-variants). Used for rawdata directory,
    report identity, catalog display, and the analyzer's `--machine` arg.
  - `upstream_key` — raw key for the Variant endpoint's `MachineName`
    field. For variants it's e.g. `M273$1$1-2-3`; for non-variants it
    equals `machine`. (Resolved by `RunManager._resolve_upstream_machine_name`
    in `app.py`.)
- Sampling requests must include `ResetPlayerStateAfterEachSpin=true`
  and `OutputAllRobotResult=true`.
- Sampling stop condition is CI-driven: 95% CI half-width `<= 0.5pp`
  by default (see the fuzzy-tier exception in §8).
- Variants are **independent machines**, not grouped: no parent/child
  relation between `M273` and `M273$WheelSelector$0$`. The only
  cross-machine coupling is md5 fanout (upstream's `MachineConfigMd5`
  reports per underlying, so siblings share the same md5). See
  `project_variants_fleet.md` memory note.
- `configs/machines.json` is a **downloaded upstream cache** (the roster +
  per-machine config/code md5s), refreshed via the console's
  MapMachineOrder / refresh-md5 path. It is **gitignored** — treat it as
  runtime state, not source. Do not hand-edit or commit it.
- RTP parity invariant (a value-agnostic correctness gate, not a value
  pin): the per-payout-id RTP contributions must sum to the summary RTP,
  and our parsed RTP must equal the server's. Any new aggregator that
  adds its own RTP breakdown must preserve this. Lives in
  `fresh_slotlab/analyzer/rtp_integrity.py` (gated by
  `tests/backend/test_rtp_integrity_gate.py`).
- Do not introduce low-value hot/cold-window style metrics.
- Do not persist raw per-spin full data as long-term report assets.

## 3. Safety Rules for Development

- Preserve backend safety interlock behavior: per-cell operation locks
  on write endpoints (`CellLockRegistry`) + the operation mutex.
- Preserve startup recovery behavior: stale `running` rows must be
  auto-corrected on boot.
- Preserve cache cleanup safety: manual trigger only + risk-tier
  confirmation. A version tag (md5/hash) is **never** a destruction
  signal — non-current chunks are tagged `historical`, deletion goes
  through explicit cache-management endpoints
  (`memory/feedback_md5_is_a_tag_not_a_destruction_signal.md`).
- Never commit API keys or local runtime secrets.

## 4. Git Workflow

- Branch from `collab/dev` with small, focused scopes.
- Keep one logical concern per commit. Make surgical commits — do not
  `git add -A` (the working tree carries many local `cache/` scratch dirs).
- Include docs update when behavior/contract changes.
- Prefer PR merge to `main` after checks pass.

## 5. Required Validation Before Merge

- Lint must pass — `scripts\lint.ps1`:
  `compileall` + the AST no-global-state guard (`check_no_global_state.py`)
  + optional `ruff` + `node --check` on the two frontend JS files.
- Tests must pass — `scripts\test.ps1`:
  runs `pytest tests/backend` + Node `pure.test.cjs`. The analyzer suite
  (`tests/analyzer`) is NOT run by the script today — run it explicitly:
  `python -m pytest tests/analyzer tests/backend` (currently **~2335
  passed**, a handful skipped/xfailed).
- For UI-touching changes, add the e2e pass:
  `scripts\test.ps1 -E2E` (Playwright headless Chromium on a free port;
  `-Install` to fetch the browser the first time).
- Data contract: the `player_impact_summary.json` schema is a frozen
  contract the frontend renders directly — do not change emitted field
  shapes without updating the renderers + tests (see §9, §12).
- Operational: confirm `/api/health` and `/api/system-state` stay valid.

## 6. Recommended PR Description Template

- Context: what user/problem this change targets.
- Scope: files/modules changed.
- Safety impact: lock/recovery/cache behavior touched or not touched.
- Test evidence: commands run + results.
- Migration/compatibility: any API/schema/runtime behavior changes.

## 7. Code Review (gates-first; agent teams opt-in)

Review is **gates-first**: every change is gated by objective,
value-agnostic checks before commit — `base_hash` delta (which machines a
change re-flags, via `versioning.py`), targeted tests for the touched
code, a real-rawdata trace for the affected machine(s), and the invariant
gates (`rtp_integrity`, aggregator parity).

The old `arch-*` / `impl-*` multi-agent review teams are now **opt-in**
only, for changes that provably move the thin core / schema / whole fleet.
(Their process docs — `ARCH_TEAM_PROCESS.md` / `IMPL_TEAM_PROCESS.md` —
were deleted; the gates above are the standing requirement.) Local changes
(one machine's manifest, one feature body, docs) ride the gates alone.

Treat findings as merge blockers if they affect data correctness, safety
guarantees, or API-contract stability.

## 8. Run Config Workflow

> NOTE: this drives the console's run-config UI and the sampling
> subprocess, which are **live**. It produces rawdata under
> `rawdata/<machine>/mode_<n>/`. The downstream "generate a report" step
> is the part that is currently offline (§9); sampling itself works.

Console operators build a run payload through these gated steps:

1. Pick machine and RTP mode. M14 exposes modes 1 / 2 / 5 / 7. Mode 2
   and 5 are "RTP-exploding" bonus/freegame paths that require the fuzzy
   CI tier; switching there locks `ciSelect` to value "0" and disables
   every other tier.
2. Pick target CI half-width. Mode 1 / 7 allow 0.5 / 1 / 2 / 5 pp or the
   fuzzy tier. Selecting the fuzzy tier anywhere (value "0") causes the
   backend to (a) size `max_chunks` so sampling targets ~1M spins, and
   (b) pass `--target-halfwidth-pp=999.0` so the CI-stop branch never
   fires. The backend also returns 400 when mode ∈ {2, 5} is paired with
   a non-zero half-width, so the constraint holds even on direct API calls.
3. (Optional) Click "Auto Tune Parallelism" to probe upstream load and get
   a machine-specific recommendation. The probe grid is sized to the
   endpoint kind (`_AUTO_GRIDS` in `app.py`): a larger grid for LAN/RFC1918
   endpoints, a conservative grid for WAN. Loopback endpoints skip probing
   and use a baked-in tuning (`_LOOPBACK_HARDCODED_TUNING`).
   `chunk_robot_count` and `batch_concurrency` are editable inputs with
   preset defaults (robot=20, conc=2); changing machine or mode resets
   them to the preset; a persisted Auto Tune result overrides the preset.
   NOTE: throughput depends heavily on upstream state — a fresh upstream
   sustains a much higher peak than the steady state once per-source
   rate-limiting kicks in, so plans that assume the peak under-budget wall
   time in the rate-limited regime
   (`memory/feedback_upstream_throttle_ceiling.md`).
4. Optionally tweak advanced params (chunk_spin_times / max_chunks /
   timeout) in the collapsed "Advanced parameters" section.
5. Pick bankroll multiplier preset. Only the "Standard" preset aligns
   with the bankruptcy thresholds hard-coded in
   `configs/classic_slots_guideline_rules.json`; Short / Long presets skip
   the bankruptcy rule (the tooltip advertises this caveat).
6. Start.

The backend re-validates everything the frontend validates (mode 2/5 must
be fuzzy; Pydantic `Field(ge=0)` for half-width, `gt=0` for the other
numeric fields). Redundant gates are intentional: the server must stay
safe against a direct curl that skips the UI.

## 9. Analyzer — current state (core survives, orchestrator rebuilding)

This is the part of the system in flux; read it carefully before touching
anything under `fresh_slotlab/`.

### 9.1 What was removed

`fresh_slotlab/player_impact_analyzer.py` — the report-production
entrypoint that ran the emit loop and wrote `player_impact_summary.json` —
is **deleted**. It is being rebuilt around the SpinType-native model
(unit = a protocol-event SpinType, not "a spin"; see the model summary in
`MACHINE_ONBOARDING.md`). Consequences:

- Report generation is OFFLINE (`_run_generate_report` → HTTP 503).
- The whole-fleet **golden / byte-identical** test corpus that used to
  lock the old monolith's output was removed when the "byte-identical vs
  the old engine" constraint was dropped in favour of starting fresh.
  Correctness is now carried by **value-agnostic invariants**
  (`rtp_integrity` + aggregator parity) plus **per-machine report-digest
  manifests** that accrue as machines are confirmed — not a fleet golden.
- The **virtual / `slot_designer/` framework is fully deleted.** Only
  `slot_designer/configs/machine_manifests/<M>.json` (the legacy *flat*
  manifests) remain on disk, read by `versioning.py` (see §9.3). There is
  no virtual console / virtual analyzer anymore.

### 9.2 What survives (the reusable core)

These modules are intact and are the foundation the new engine is built on:

- `fresh_slotlab/analyzer/core/` — `parser.py`, `aggregator.py`,
  `writer.py`, `base_pipeline.py` (+ `_utils.py`). The parse → aggregate →
  write spine.
- `fresh_slotlab/` round/data primitives — `round_win.py`,
  `round_classification.py`, `trigger_sessions.py`, `sampler.py`,
  `batch_dev_sampler.py`, `machine_md5.py`, `rawdata_index.py`,
  `chunk_index.py`.
- `fresh_slotlab/analyzer/` support — `versioning.py`, `rtp_integrity.py`,
  `manifest_loader.py`, `machine_spec.py`, `st_inventory.py`,
  `feature_registry.py`, `topo_sort.py`, `mechanism_registry.py`,
  `parse_state.py`, `pipeline_context.py`, plus the per-feature plugins in
  `fresh_slotlab/analyzer/features/` (e.g. `payouts_by_spin_type`,
  `spin_type_outcomes`, `spin_type_rtp_buckets`, `topdollar_choice`,
  `reel_marginal_by_spin_type`, `bankruptcy_simulation`,
  `multiplier_profile`, `multiplier_wild`, `machine_mechanics`,
  `upstream_feature_breakdown`, `collect_mechanic`, `bonus_chain_dynamics`).
  The feature plugins exist as code but, with the orchestrator gone, there
  is no live entrypoint running them end-to-end yet — that wiring is what
  the rebuild re-establishes.
- `fresh_slotlab/analyzer/play_types/{bcm_cycle,wild_nudge}.py` —
  the two mechanic functions deliberately **carved out** of the base import
  closure so editing one machine's mechanic doesn't re-flag the whole
  fleet's `base_hash` (the core goal of the rearch). They are
  base-EXCLUDED on purpose; the carve is locked by
  `tests/backend/test_{bcm_cycle,wild_nudge}_carve.py`. Do NOT add them to
  `_CLOSURE_FILES`.

### 9.3 Manifests + versioning (live)

Two manifest schemas exist right now during the transition:

- **NEW SpinType-native schema** — `configs/machine_manifests/<M>.json`,
  loaded/validated by `fresh_slotlab/analyzer/machine_spec.py`. This is the
  **locked** target schema: `spin_types{role, play}`,
  `validation{status: auto|confirmed}`, `out_of_engine_mechanics`
  (the M90 "rawdata can't see it" slot). `machine_spec.derive_analyses()`
  derives the analysis set FROM `spin_types` (not hand-listed). Reference
  instance: `configs/machine_manifests/M15.json` (the only one authored so
  far).
- **LEGACY flat schema** — `slot_designer/configs/machine_manifests/<M>.json`,
  still read by `fresh_slotlab/analyzer/versioning.py` (its `analyzer_features`
  key) to compute each machine's `effective_analyzer_version`. Converting +
  relocating these to the new schema is pending the orchestrator rebuild.

Versioning (`fresh_slotlab/analyzer/versioning.py`) is live and unchanged:

- `compute_base_analyzer_version()` — sha256 over the report-production
  import closure (the explicit `_CLOSURE_FILES` tuple, CRLF-normalized),
  minus the carved mechanic files. Editing a closure module flips the base
  hash; editing a carve or a single feature plugin does not. The function
  raises (does not silently swallow) if a production-imported repo-local
  module is missing from `_CLOSURE_FILES` — update the tuple when that
  fires for a legitimate new module.
- `compute_effective_version_for_machine(machine, mode)` — composes
  `base ⊕ {hash of each declared feature} ⊕ mode` into the per-`(machine,
  mode)` value the console uses for report freshness, so changing one
  machine's features invalidates only that machine.
- Do **not** hard-code a base/effective hash value in code or docs; the
  pinned hashes that exist live only in `tests/` as regression guards.
- Backend memoization: `src/web_console/backend/effective_version_cache.py`
  (deliberately outside the closure so importing it can't flip the base
  hash). It distinguishes "no manifest" (UNVERIFIABLE — not stale) from
  "closure file missing" (loud error).

Report-freshness decision (honest + non-destructive): the console compares
a report's stored `effective_analyzer_version` against the current value
for its `(machine, mode)`; a mismatch marks the cell `needs_rebaseline`
and **never deletes** artifacts. (Re-baseline normally re-analyzes on next
open — that path is gated behind the offline generator until the rebuild
lands.)

### 9.4 Adding analyzer support for a new machine

Follow **`docs/MACHINE_ONBOARDING.md`** — it is current and is the method
of record. In short: extract the ST inventory
(`python -m fresh_slotlab.analyzer.st_inventory <M> <mode>`), understand
each SpinType from its own raw fields, derive the gameplay/economy, author
the new-schema manifest (`configs/machine_manifests/<M>.json`), and get
user domain sign-off. The numeric value-agnostic gates (step 5 there) run
against a generated summary and so are **paused** until report generation
is back online; the analysis + manifest are the substance you can do now.

## 10. Test Layout

- `tests/backend/` — FastAPI `TestClient` integration tests that build
  isolated apps via `create_app(state_dir=tmp, ...)`. `conftest.py` stubs
  `subprocess.Popen` via an injected factory on `RunManager` so nothing
  real is spawned. `_seed.py` provides `insert_run_row` for startup
  recovery tests (does NOT import `app.py`).
- `tests/analyzer/` — unit/contract tests for the analyzer core, feature
  plugins, the carve isolation, and versioning. NOT run by `scripts\test.ps1`
  today; run with `python -m pytest tests/analyzer`.
- `tests/integration/` — cross-cutting backend↔analyzer-CLI integration
  (argv / cache-routing contracts).
- `tests/frontend/pure.test.cjs` — Node `node:test` runner against
  `pure.js`. No third-party deps. `node --test tests/frontend/pure.test.cjs`.
- `tests/e2e/` — pytest-playwright + headless Chromium. `live_server`
  fixture spawns `src.web_console.backend.e2e_launch:app` on a free port
  with tmp state dirs and shrunk risk thresholds.

No global state is shared across tests; each uses a `tmp_path`-scoped
directory tree.

## 11. File Ownership (current)

- `fresh_slotlab/` — analyzer core + metrics logic (see §9 for what
  survives vs what is being rebuilt).
- `src/web_console/backend/app.py` — `create_app()` factory, routes, safety
  interlock, persistence. **Side-effect free at module level**; a lint
  guard enforces this (`scripts/check_no_global_state.py`). NOTE: the
  module-level `ANALYZER` constant still points at the deleted
  `player_impact_analyzer.py` and the RunManager subprocess path dangles at
  it — both are inert because generation short-circuits to 503; they get
  re-pointed when the new engine lands.
- `src/web_console/backend/main.py` — production uvicorn entrypoint
  (constructs the default app).
- `src/web_console/backend/e2e_launch.py` — Playwright-only entrypoint
  driven by `SLOT_E2E_*` env vars.
- `src/web_console/frontend/pure.js` — DOM-free helpers (I18N, fmt,
  cacheRiskTier, …) in an IIFE; exposed via `window.PURE` and
  `module.exports`.
- `src/web_console/frontend/app.js` — DOM wiring that reads from `state`
  and delegates to `PURE`.
- `src/web_console/frontend/panel_registry.js` — ordered panel descriptor
  list (`window.PANEL_REGISTRY`) consumed by `_paintAnalysisFromSummary`;
  each descriptor is a thin wrapper around an `app.js` render fn (see §12).
- `configs/` — machine configs, guideline rules, server roster
  (`servers.json`), and the new-schema machine manifests
  (`machine_manifests/`).
- `docs/` — operational and contract documentation. Companions to this
  file: `MACHINE_ONBOARDING.md` (per-machine analysis method),
  `REPORT_SPEC.md` (summary schema), `API_REFERENCE.md`,
  `CONSOLE_OPERATIONS.md`, `MACHINE_TUNING_WORKFLOW.md`, `FOR_DESIGNERS.md`.

## 12. Frontend: the report viewer + summary schema

The dashboard renders an existing `player_impact_summary.json` loaded from
disk — this path is **live** even while generation is offline. Treat the
summary's field shapes as a **frozen contract**: the frontend renders them
directly, and the new analyzer engine must reproduce them.

- `panel_registry.js` defines `window.PANEL_REGISTRY`, an ordered list of
  ~14+ panel descriptors. `_paintAnalysisFromSummary(summary)` walks it and
  invokes each `render(ctx)` — a thin wrapper around a named render fn in
  `app.js` (e.g. `renderKpiTiles`, `renderTailDepGrid`, `renderBigWinGrid`,
  `renderBucketDistribution`, `renderSpinTypeBreakdown`,
  `renderSpinTypeOutcomes`, `renderFeatureBreakdownPanel`,
  `renderPayIdOverview`, `renderLibraryRanking`, `renderRtpClampWarning`).
  Some are `fireAndForget` (their own async API calls — library ranking,
  payline classification, pay-id overview — must not serialize the paint
  chain). When you add a panel, append a descriptor here and keep the
  render logic in `app.js`; do not duplicate render logic in the registry.
- Pure formatters live in `pure.js` (locked by `pure.test.cjs`):
  `summarizeRunEvent`, `computeRunProgressPct`, `formatAutotuneProgress`,
  `prettyBucketLabel`, `computeLibPercentile`, `formatLibRank`, the
  bucket/symbol/payline row formatters, `extractMetricCards`, etc. Extend
  these (and test them) rather than threading raw summary objects through
  DOM code.
- For the authoritative description of every summary surface
  (`hit_and_payout`, `multiplier_profile.buckets`, `streaks`, `volatility`,
  `spin_type_breakdown`, `payout_ids_top20`, `paylines_top20[].top_symbols`,
  `upstream_feature_breakdown`, `bonus_chain_dynamics`, `collect_mechanic`,
  the `guideline_assessment.*` tail-dependency metrics, etc.) and their
  semantics (paid-session metrics, RTP denominators, clamp warnings), see
  **`docs/REPORT_SPEC.md`**. That is the schema the rebuilt engine targets;
  this guide does not re-document it.

E2E selectors that must be preserved across any layout edit (the e2e suite
asserts them):

- Form / control IDs: `#langSelect`, `#machineSelect`, `#modeSelect`,
  `#ciSelect`, `#robotInput`, `#concInput`, `#spinInput`,
  `#maxChunksInput`, `#timeoutInput`, `#bankSessionInput`,
  `#bankMultSelect`, `#startBtn`, `#autotuneBtn`, `#stopBtn`, `#refreshBtn`,
  `#interpretBtn`, `#cacheRefreshBtn`, `#cacheCleanupBtn`, `#tabBtnDebug`,
  `#tabBtnManage`, `#sidebarToggle`.
- Drilldown tables: `#paylineTable`, `#payoutGroupTable`,
  `#symbolOverallTable`, `#symbolByColMatrix`.
- Status surfaces: `#runMeta`, `#autotuneMeta`, `#cacheRiskMeta`,
  `#eventsText`, `#liveStatusStrip`.
- KPI elements: `#kpiRtp / #kpiCi / #kpiSpins / #kpiZero / #kpiTail /
  #kpiGuide / #kpiVolatility / #kpiArchetype / #kpiLossStreak /
  #kpiMaxReturn / #kpiBigWin / #kpiBankruptX500`, plus sub-line divs
  `#kpiTailSub / #kpiVolatilitySub / #kpiArchetypeSub`.
- Inline panels: `#spinTypeTable`, `#featureBreakdownInline`
  (+ `#featureBreakdownMeta` + `#featureBreakdownBody`),
  `#bonusChainDynamicsPanel` (+ `#bonusChainMeta` + `#bonusChainBody`) —
  the last two carry `.hidden` when their summary block is
  `applicable=false`.
- Run-history: `#runListTable`, `#runFilterBanner`, `.load-run-btn` /
  `.delete-run-btn` (per-row). Chart canvas: `#bucketChart`.

## 13. Progress feedback channel

Two HTTP endpoints are the live-data spine for the run / autotune panels.
Both are 1 Hz polled and shaped as simple read snapshots so the backend
stays state-free beyond SQLite + memory.

- `GET /api/runs/{run_id}/progress` — replays the per-run jsonl events
  file. The frontend's 1 s "fast" timer hits it only while
  `currentRunStatus === "running"`; the latest event drives
  `pure.summarizeRunEvent` (status line) + `pure.computeRunProgressPct`
  (progress bar).
- `GET /api/autotune/progress` — in-memory snapshot mutated under
  `app.state.autotune_progress_lock` by the callback `create_app()` injects
  into `run_auto_tune`. Polled at 1 s while `state.autoTuneRunning`;
  rendered via `pure.formatAutotuneProgress`.

Future live surfaces should follow the same shape: a small REST endpoint
returning a snapshot dict + a pure formatter helper.

## 14. Upstream API shape + schema drift

`run_sampling_chunk` does two layers of sanity checking on every chunk
response so an unfamiliar machine or a silently renamed field surfaces as a
clear error instead of all-zero metrics. Both errors propagate through the
main loop's chunk-failure path into `_watch_run`'s `error_message`.

- **Layer 1 — top-level shape** (`response_shape_unexpected:...`):
  reports `expected_list:got_dict_keys=[...]` (dict envelope instead of a
  list), `expected_list:got_type=str` (often an un-decoded error body), or
  `expected_robot_dicts:item_types=[...]` (list with no robot dicts). A
  list with ≥1 robot dict goes through; non-dict items are skipped.
- **Layer 2 — round-level schema** (`schema_drift_missing_fields:...`):
  `_REQUIRED_ROUND_FIELDS = (WinCredits, StopSymbolsByCol)` on every spin;
  `BetAmount` checked via union with `CostCredits` (≥1 must exist).
  `PayoutByPayline` / `PayoutGroupId` are NOT strict-checked (lose / no-payout
  spins legitimately omit them).

When a new machine's response shape differs, update the shape catch + add a
fixture under `tests/backend/test_analyzer_parsing.py`. If you expand
`_REQUIRED_ROUND_FIELDS`, also update the locked-constant test so the
contract change shows up in review.

## 15. Troubleshooting

- **`scripts/lint.ps1` fails on `check_no_global_state.py`**: somebody
  reintroduced module-level `StateStore()` / `RunManager()` /
  `OperationCoordinator()` / `RuntimeModelConfig()` / `FastAPI()` /
  `create_app()` in `app.py`. Move the call into `create_app()` (or
  `main.py` for the default instance).
- **`scripts/test.ps1` exits 1 with 'node is required'**: install Node 18+
  or pass `-AllowMissingNode` to skip the frontend suite (the backend suite
  always runs).
- **`scripts/test.ps1 -E2E` fails 'Playwright chromium not installed'**:
  run `python -m playwright install chromium` (~120 MB one-time) or pass
  `-Install`.
- **E2E test seeds a run row but startup recovery wipes it**: seed AFTER
  the server is up. The `live_server` fixture exposes `db_path` for this.
- **`POST /api/rawdata/{machine}/generate-report` returns 503**: expected — report
  generation is offline pending the SpinType-native engine rebuild (§9).
  Viewing existing reports still works.
- **Bash hooks fail in a worktree** (known env wart): use the PowerShell
  tool for git/build instead (`memory/project_realmachine_tuning_loop.md`).
