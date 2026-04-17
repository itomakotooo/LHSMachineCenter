# TODO

This file tracks executable next steps for the current phase.

## P0 (user-blocked)

- [ ] **By-hall sort tab + select-all button** (agreed with user, not
      yet implemented). Machine catalog gets a new view tab "按大厅"
      that calls `POST /MachineTest/MapMachineOrder` for ordering;
      plus a "全选" button. Noted; waiting for user go-ahead.

- [ ] **Broken machine tag** (optional). User asked to list machines
      where API returns obvious garbage RTP (see memory). Not
      surfacing in UI yet; if needed, add `configs/broken_machines.json`
      → badge these separately in catalog.

- [ ] Multi-server 实测: 基础设施就绪，等用户提供 test/prod 地址。

- [ ] Consider CI integration when remote build is needed. For now
      the baseline is local-only (`scripts\lint.ps1` +
      `scripts\test.ps1 -E2E`).

## P1 (high-value product improvements)

- [ ] Add auth layer for web console (at least local admin token / company SSO-ready design).
- [ ] Add operation audit log:
  who started/stopped runs, who triggered cache cleanup, timestamps, payload summary.
- [ ] Add report comparison view:
  version-vs-version and machine-vs-machine for key player-impact metrics.
- [ ] Add richer planning metrics cards:
  volatility profile, symbol frequency concentration, streak risk distribution, bankruptcy sensitivity deltas.
- [ ] Add runtime health dashboard:
  queue depth, API failure rate, timeout rate, and endpoint latency percentile.

## P2 (scale and platformization)

- [ ] Multi-machine batch orchestration:
  schedule and track large test campaigns across many machines/modes.
- [ ] Automatic report baseline alerting:
  trigger alerts when new report deviates from baseline thresholds.
- [ ] Config-as-data workflow:
  controlled machine/mode/test profile templates with versioning and approval flow.
- [ ] Deployment packaging:
  produce repeatable deploy assets for company server environment.
- [ ] **Batch state persistence to DB** so "continue last batch" survives
      uvicorn restarts (today the batch object is in-memory; chunks on
      disk survive, but the "which machines did I tell it to sample"
      list is lost). Workaround: user全选 + 点批量, resume-from-cache
      handles the rest.

## Done Recently

- [x] **Sampling quality + UX pass** (2026-04-17, second half, 13 commits):
      - `--resume-from-cache` analyzer mode: seed aggregators from cached
        chunks, continue live sampling from `max_existing_idx + 1` until
        CI target or max_chunks. Replaced read-only `--from-cache` on
        the user's batch-run path.
      - Stop condition uses **session-level** CI (not chunk-level).
        Chunk-level CI can collapse with 2-3 similarly-valued chunks
        and would false-trigger `target_ci_reached` at N=240k spins
        with actual CI of 12pp. Shared `session_halfwidth_pp` helper.
      - Loop continues through single-chunk failures. `run_sampling_chunk`
        retries 5xx/URLError/Timeout; if retry exhausts, failure is
        logged as `chunk_failed` event. Run bails only at
        `_MAX_CONSECUTIVE_FAILED_BATCHES=3` or
        `_MAX_CUMULATIVE_FAILED_CHUNKS=20`.
      - Progress event key alignment: analyzer writes
        `current_halfwidth_pp`; backend now reads both that and the
        legacy `halfwidth_pp`. UI CI gauge live during sampling (was
        stuck at N/A).
      - Completion event carries stop_reason + chunks + total_spins +
        duration so operator sees WHY sampling ended.
      - Per-chunk event log in UI: backend exposes `chunk_events` per
        item; critical events (`chunk_failed` / `resume_from_cache` /
        `disk_guard_stop` / `failed`) never pruned, `chunk_progress`
        rotates (last 8). Frontend partitions + sorts chronologically,
        renders all criticals + last 8 progress.
      - Log freezes on batch completion (`state.batchJustCompleted`
        blocks `renderSamplingProgress`). Prev behavior re-rendered on
        every poll tick, could wipe error rows.
      - Double-click guard: `sampleStartBtn.disabled = true`
        synchronously at handler entry. Page-refresh recovery via
        `GET /api/sampling-status` + localStorage `activeBatchId`.
      - Bet-mismatch warning: `_peek_cache_bets(dir)` scans envelope
        `_bet` values; warns when cache differs from analyzer default
        (1000). CI math stays valid; RTP=value-weighted may drift <1%.
      - `resume_cache` is now the only non-fresh path from batch-run
        (reuse/read-only was removed). `--from-cache` CLI still used
        by `batch_generate_reports.py` for offline re-analysis.
      - Analyzer mid-loop disk guard (2GB threshold) + per-(machine,
        mode) lock in `BatchRunManager` to prevent concurrent batches
        from racing the same chunk dir.
      - Autotune rewired to catalog selection + `sampleMode`
        (no sidebar). Tuned values cached in
        `state.tunedSamplingParams`, persisted to localStorage, picked
        up by the next `startSampling()` as robot_count / batch_concurrency.
      - UI restructure: 调试机台 is display-only (sampling moved to 机台
        管理 / 采样选中机台 panel); left sidebar removed; model config
        folded into 模型解读 panel; "当前运行进度" replaced with compact
        loaded-machine identity header.
      - `/api/runs` default limit 50 → 2000; 运行历史 table width auto;
        `max-height: 620px` so 2000 rows scroll internally.
      - Tests: 244 → 278 passed (+34 new cases) including end-to-end
        `test_batch_analyzer_cli.py` which inspects the actual
        subprocess argv (POST /api/batch-run → analyzer CLI args).

- [x] **Structural hardening pass** (2026-04-17, 10+ commits):
      - Chunk cache v3: `.tmp` + `os.replace` atomic write + `_payload_sha256`
        with `load_chunk_envelope()` validation. `ChunkIntegrityError` surfaces
        corruption as a readable error instead of JSONDecodeError. v2 envelopes
        still load for backwards compat.
      - Rawdata index: `dev_rawdata/_index.json` fast path for
        `check_rawdata_status` — 18× speedup (65ms→3.5ms/call).
        Self-healing on drift; `scripts/rebuild_rawdata_index.py` big-hammer.
      - Import transactionality: 4-step commit
        (read_summary → insert_run status=importing → copytree →
        update_run status=completed). Any step fails → full rollback.
        Response shape `{imported, skipped, failed, failures[]}`.
      - Versions retention: `POST /api/maintenance/prune-versions` +
        `scripts/prune_report_versions.py` (default keep=5). Syncs DB +
        index.json + latest.json. Skips active (running/importing) runs.
      - Sampler retry: exp-backoff (1s→2s→4s ×3) on 5xx / URLError /
        TimeoutError. Non-retryable errors fail-fast.
      - Batch regen: 17min → 54s for 1006 reports (bankruptcy probe
        skipped on `--from-cache` since it hits live HTTP; + mp.Pool
        with pre-imported analyzer worker).
      - Session-level CI: `t × sqrt(Var(ret_x)/N) × 100`. Works on
        single-chunk dev reports; stored as
        `sampling.session_level_halfwidth_pp`. Zero-variance clamp.
      - Badge 4-state: ✓ green (MD5 match + CI≤0.5pp) / 🟡 yellow
        (MD5 match, CI > 0.5pp or null) / ⚠ red (MD5 outdated) /
        ? gray (untagged).
      - Error handling tiered: system-level raises, data-level logs +
        continues, action-level logs visibly. Bare `except Exception:
        pass` narrowed to specific types at 4 sites.
      - E2E test: sample → chunk → analyzer → import → UI one-shot
        covering the full happy path + chunk corruption detection.
      - Tests: 166 → 244 passed (+78 over the session).
- [x] **253-machine platform** (2026-04 build):
      auto-synced `configs/machines.json` from MachineConfigMd5,
      9-category auto-classification, raw-feature filter chips (multi-select OR),
      5-view catalog (category/name/volatility/RTP/mechanic),
      per-machine detail panel with logicClassNames + MD5 + per-mode metrics,
      version history + report comparison, machine mechanics analysis
      (LockLines / LockSymbols / LockReels / Jackpot / FreeSpin / DollarPick).
- [x] **Rawdata MD5 tagging + auto-reuse**:
      chunk envelope v2 stores `_config_md5` + `_code_md5` from machines.json;
      per-chunk MD5 verification on batch-run with auto-delete of stale chunks;
      analyzer `--from-cache` mode when usable chunks exist (skip API sampling).
- [x] **Inline sampling panel**: mode+CI selectors (0.5/1/5pp/fuzzy),
      auto-lock fuzzy for mode 2/5, smart chunk_spin_times per machine
      (detects cycle from historical reports), real-time chunk-level progress,
      detailed event log (info/warn/error/danger), disk-space monitor with
      auto-stop < 2GB, subprocess-kill on cancel.
- [x] **Multi-server architecture**:
      `configs/servers.json` CRUD + scan + MD5 diff; analyzer `--endpoint-url`
      CLI arg; version change detection endpoint.
- [x] **Fleet overview headlines**: mode-completeness + per-mode expected-RTP
      range checks (mode 1 ~90%, mode 7 ~80%, mode 2 >150%, mode 5 > mode 2).
- [x] **CostCredits unreliable fix**: pre-scan chunk; if all CostCredits=0
      but BetAmount>0 (LockReSpin machines M10/M23/M131/M133), treat all
      spins as paid so session metrics don't collapse to zero.
- [x] CN/EN console switch and tabbed layout.
- [x] Field-level parameter help tooltips for newcomer usability.
- [x] UI + backend operation mutex for safer writes.
- [x] Startup stale-run recovery with stale process termination attempt.
- [x] Cache cleanup risk-tier UX (low/medium/high) with manual confirmation flow.
- [x] Backend safety-interlock test suite (6 cases: runs / autotune /
      cache-cleanup active-run + mutex blocking).
- [x] Backend startup-recovery test suite (4 cases: stale row marked
      failed, pid termination success/failure, health/system-state
      exposure).
- [x] Backend cache-cleanup test suite (3 cases: idle cleanup,
      max_delete_bytes budget, mutex 409).
- [x] Frontend pure-function test suite
      (25+ assertions via Node built-in `node:test` against `pure.js`).
- [x] Playwright e2e smoke suite (4 cases: language switch, cache
      low-risk flow, cache high-risk token flow, start-button disable).
- [x] Local lint + test scripts (`scripts/lint.ps1`, `scripts/test.ps1`)
      with strict defaults and `-AllowMissingNode` / `-Install` escape
      hatches. Replaces the earlier "Define CI gates" item (CI is
      deferred per operator decision).
- [x] Backend refactor: `create_app()` factory + `main.py` entrypoint;
      `app.py` is now side-effect free at module level, enforced by
      `scripts/check_no_global_state.py` in the lint pipeline.
- [x] `/api/cache/status` exposes `risk_thresholds` so the frontend
      risk tier can be tuned via `SLOT_RISK_MEDIUM_BYTES` /
      `SLOT_RISK_HIGH_BYTES` env vars (used by e2e fixtures).
- [x] M14 now advertises modes 1 / 2 / 5 / 7 via
      `configs/machines.json`; test API verified for all four.
- [x] CI half-width input replaced with a 5-tier picker (0.5 / 1 / 2
      / 5 / fuzzy). Fuzzy tier (value "0") makes the backend target
      ~1M spins via recomputed `max_chunks` and pass halfwidth=999
      to the analyzer so the CI-stop branch never fires. Mode 2 and
      5 are constrained to fuzzy (frontend forces, backend 400-rejects).
- [x] ~~chunk_robot_count + batch_concurrency are now readonly inputs
      populated only by Auto Tune~~ -- superseded. Those inputs are
      now editable with preset defaults (robot=24, conc=2) validated
      against M272 mode 1 autotune; Auto Tune remains optional for
      machine-specific refinement. See "Preset run-config defaults"
      entry below.
- [x] chunk_spin_times / max_chunks / timeout moved into a collapsed
      "Advanced parameters" section so the primary panel is shorter.
- [x] Bankruptcy multipliers freeform input replaced with a 3-preset
      select (Standard / Short / Long). Tooltip warns that only
      Standard aligns with the x100/x200/x500 thresholds in
      `classic_slots_guideline_rules.json`.
- [x] Backend `_watch_run` failure message now structured: includes
      analyzer exit_code and lists missing summary/report files even
      when stderr/stdout are empty. Frontend "unknown error" gone.
- [x] New `/api/autotune/progress` endpoint exposes a 1 Hz snapshot
      of the autotune candidate grid so the UI can render
      "X/Y candidates done · last result" while the POST is in flight.
- [x] Global warning bar scoped to system + model only. Per-run
      failure / cancellation detail moved into the runMeta panel.
- [x] Frontend split-cadence polling: 4.5 s for system / runs / cache,
      1 s for the active run. Run progress bar driven by chunks/max
      (or total_spins/1M for fuzzy). New live event summary line.
- [x] Auto Tune live progress panel: 1 s polling against
      `/api/autotune/progress`, formatted via `pure.formatAutotuneProgress`.
- [x] KPI grid expanded from 6 to 12 cards (added volatility class /
      experience archetype / loss streak p95 / max return x / 10x+
      big win rate / x500 bankruptcy rate). Tone classification in
      `pure.extractMetricCards`.
- [x] Three new player-impact drilldown panels: paylines (top 20),
      symbols (overall + by column), payout groups (top 20). Analyzer
      now aggregates `PayoutGroupId` per spin and emits
      `summary.player_impact.payout_groups_top20`.
- [x] Dashboard layout refactor (Grafana-style debug tab): three-region
      shell -- sticky topbar with health/lang/liveStatusStrip; sidebar
      (260px column on desktop, drawer below 1120px with hamburger
      toggle) holding params/model/control buttons; main area with
      compact 3x4 KPI strip (whole-card tone bg), 2x2 chart grid,
      tabbed assessment/interpretation/events panel, tabbed drilldown
      (paylines/payouts/symbols) panel. Manage tab kept as single-
      column panel stack so cache-cleanup e2e keeps working unchanged.
- [x] Dashboard follow-up (per user feedback after first pass):
      sidebar reordered so run-actions sits at the top of the column
      (Start/Auto above the fold). Mid-area and drilldown tab groups
      unrolled into stacked panels because tabs added friction without
      payoff for narrative + table content; mid order is now
      interpretation -> assessment -> events.
- [x] Multiplier bucket schema refined from 10 bins to 12: collapses
      sub-1x buckets (gt0_lt1 unifies the old gt0_lt0.5 + ge0.5_lt1;
      ge1_lt5 unifies ge1_lt2 + ge2_lt5) and splits the deep tail
      (ge100 became ge100_lt200 / ge200_lt500 / ge500_lt1000 /
      ge1000_lt5000 / ge5000). pure.prettyBucketLabel renders friendly
      ranges and keeps fallbacks for legacy keys.
- [x] Charts trimmed to bucket-only: CI / RTP / bankruptcy line charts
      removed since their values are already KPI cards. Multiplier
      bucket bar chart spans full panel width.
- [x] Payline winning-symbol inference: analyzer heuristically tags
      each winning payline with the symbol(s) shared by the leftmost
      three stopped columns (classic 3+ left-to-right pattern). Each
      paylines_top20 row carries top_symbols; the drilldown table
      shows the top 3.
- [x] Interpretation prompt overhauled: includes paylines / payouts /
      symbols subsets, prepends a "参照阈值" reference block mirroring
      classify_volatility / classify_experience_archetype / alert
      thresholds, expands output structure to 6 sections with a
      mandatory "支付线与符号热点" narrative.
- [x] Analyzer parsing test suite + upstream schema drift defense:
      `_check_round_schema` validates first parsed round; required set
      narrowed to {WinCredits, StopSymbolsByCol} after lose-spin
      regression (PayoutByPayline / PayoutGroupId legitimately absent
      on lose / no-payout spins). BetAmount checked via union with
      CostCredits. `tests/backend/test_analyzer_parsing.py` (44 cases)
      locks the parsing contract: schema check (incl. lose-spin-first
      regression + CostCredits fallback), 12-bin bucket classification,
      payline winning-symbol heuristic (left-3 intersection + blank
      filter), payout-group aggregation.
- [x] Zero-spin run guard: `_watch_run` promotes "exit 0 + summary +
      report files but sampling.total_spins=0" runs (e.g. upstream API
      504s for the first chunk) from "completed" to "failed" with
      error_message recording the analyzer's stop_reason. Empty
      reports are kept out of the report index / latest.json.
      Locked by `tests/backend/test_run_lifecycle.py` (4 cases) which
      also covers the happy path end-to-end (POST -> mock analyzer
      writes artefacts -> GET /api/runs/{id}/report serves summary +
      index/latest updated).
- [x] Autotune wall-time speedup (per user feedback): default
      candidate grid compacted from 5x4=20 to 3x3=9
      ({8,16,24} x {1,2,4}); per-robot early exit in `run_auto_tune`
      skips higher concurrency for any robot whose lower-concurrency
      candidate falls below success_rate=0.7; frontend default rounds
      dropped from 2 to 1. Combined effect: autotune typically
      completes in well under half the previous wall time. Locked by
      4 new cases in `tests/backend/test_autotune_progress.py`.
- [x] Events panel moved to bottom of debug tab (per user feedback:
      raw jsonl events are low-readability and only consulted when
      something looks off; assessment + drilldowns get screen
      priority).
- [x] M272 added to machines.json (modes 1, 2, 5, 7). Probed all
      four modes, response shape is the same list-of-robots envelope
      M14 uses; round-level schema satisfied (WinCredits +
      StopSymbolsByCol present). Notes: M272 mode 1 is a collect
      mechanic (SpinType 140 + 126 bonus re-spins), so round count
      exceeds SpinTimes by ~10-30%; PayoutByPayline uses a richer
      `id:mult-count(positions);` format that parse_paylines still
      reduces to ids correctly. End-to-end smoke run: 1812 spin /
      RTP=72.4% in 4 seconds.
- [x] Analyzer top-level shape catch: when upstream returns a non-
      list (e.g. single-dict envelope, raw error string) or a list
      with no robot dicts, the chunk now fails with
      `response_shape_unexpected:...` echoing the offending keys/
      types, instead of iterating non-dict items and silently
      producing parse_failed_zero_chunk. Operator can immediately
      see the shape and ask for the new envelope to be supported.
      5 new test cases lock dict / string / list-of-strings /
      partial-corruption paths.
- [x] Round-level field investigation (M14 + M272) surfaces 4 new
      summary blocks that previous versions either missed or showed
      as informationally empty:
      * `player_impact.payout_ids_top20` (PayoutIdToWinAmount-based
        Pay ID drilldown -- M14 also shows 7 distinct ids contributing
        ~RTP; the older payout_groups_top20 was always group 0 so
        the UI now reads from this).
      * `player_impact.spin_type_breakdown` (per-SpinType spins/
        win/RTP -- exposes M272 mode 2's 36% bonus rounds).
      * `paylines_top20[].top_symbols` (left-3-col intersection +
        blank filter).
      * `upstream_analysis` at summary top-level: server-side
        analysisResult.TotalWin cross-checked against our parsed
        total_win. M14 + M272 mode 1 both verified delta=0.
      * `collect_mechanic` at summary top-level: M272 collect
        bonus tally; M14 reports applicable=false.
      Frontend renders payout_ids_top20 (replacing the empty
      PayoutGroupId table) and spin_type_breakdown (new panel).
      Interpretation prompt subset includes all four blocks plus
      the reference thresholds.

- [x] Paid-session refactor (per user feedback): hit_rate / RTP /
      multiplier bucket / streaks / volatility all switched from
      per-spin to per-paid-session math. Bonus / free-spin wins
      attribute back to the paid spin that triggered them, so hit
      rate isn't diluted by bonus chains. rtp.point_pct denominator
      switched to session_bet_sum (paid bet only) -- the old
      total_bet was also adding BetAmount for bonus spins, which the
      player doesn't actually pay. On bonus-heavy machines (M272
      mode 2: 46% bonus rounds) true RTP recovered from ~286% (under-
      reported) to ~563%. sampling.paid_spins + sampling.bonus_spins
      added so the split is visible. 5 new analyzer test cases lock
      session-tracking semantics.
- [x] Trunk-clamp warning: collect_mechanic.clamp_warning surfaces
      raw signals when chunks ran out of SpinTimes mid-collect-cycle
      (pending_robots, total_pending_paid_spins,
      pending_share_of_paid_spins, avg_paid_spins_per_collect). Does
      NOT fabricate an "estimated lost RTP pp" -- per-machine
      collect bonus varies too much for a single heuristic. Frontend
      interpretation panel renders a warning via #rtpClampWarning
      when applicable=true. 4 new analyzer test cases.
- [x] Defensive os._exit(rc) at analyzer main exit so any worker
      thread stuck in a slow socket read can't keep the process
      alive (defense against the orphan-process leak the user
      reported with 3 stuck CLI probes from upstream-trickle).
- [x] Drop `eq0` multiplier bucket (commit 1c17b34). 11 win-bearing
      bins remain; zero-win rate still lives in
      `hit_and_payout.zero_win_rate`. `prettyBucketLabel` keeps the
      legacy-key fallback so old reports still render.
- [x] Preset run-config defaults + unlock robot/conc inputs
      (commit 390e1c0). robot=24 / conc=2 / max_chunks=60 /
      timeout=120 all validated on M272 mode 1 autotune (conc=4
      top-ranked but p95=10s tail → preset conc=2 for safety
      margin). Reset-to-preset on machine/mode change via
      `resetConcurrencyInputsToPreset()` reading input.defaultValue.
- [x] Manage-tab run history: RTP + CI cols, delete button, machine
      filter via catalog click (commit 56903bc). `DELETE
      /api/runs/{id}` cascades row + interpretations + per-run
      artefacts + report version dir + index.json/latest.json
      rollback. Locked by 4 delete tests.
- [x] 4 new analyzer surfaces from upstream field audit
      (commit c3e7096): multi-threshold tail_dependency_ge{10,20,50,
      100}x; upstream_feature_breakdown from analysisResult.
      FeatureWin (machine-named features like "NormalCollectionSpin"
      / "NewFreespin"); bonus_chain_dynamics from ReMarks Freespin
      annotations (chain length + peak ratio quantiles + self-
      retrigger rate + depth-bucketed energy ramp curve);
      RewardLastNode-based authoritative winning-symbol codes with
      heuristic fallback. M272 mode 1 smoke validates all 4.
- [x] SpinType breakdown RTP denominator fix (commit c3e7096): per-
      type bet now uses CostCredits>0 amounts only (was BetAmount
      blindly); free-spin types (M272 126) emit rtp_pct=null so UI
      shows "N/A" instead of 243% nonsense. Analyzer-derived
      behavior_name ("paid"/"free"/"mixed") added as new table col.
- [x] Frontend panels for the 4 new surfaces (commit 94dae2f):
      kpi-sub multi-threshold on tail card; feature breakdown
      panel (#featureBreakdownPanel); bonus-chain dynamics panel
      with 3 KPI pills + depth curve table + ratio histogram.
- [x] Backfill achieved_rtp_pct / _halfwidth_pp / quality_label
      from on-disk summaries on every startup (commit fd30707).
      Legacy rows render "—" until first startup after migration;
      after backfill they show real values.
- [x] Merge Report Versions panel into Run History (commit 718e955).
      Run-history table grew from 8 to 10 columns (added Version +
      Quality). `section.versions` panel removed;
      `refreshVersions()` fn deleted; `/api/reports/{m}/{n}` still
      exists but unused by frontend. quality_label column added via
      ALTER TABLE + populated in `_update_report_index`.
- [x] Graceful Stop + cancelled status (commit 1714b93).
      `--stop-flag-file` path the backend touches on cancel; the
      analyzer polls it between chunks and exits 0 with
      stop_reason="user_stop". `_watch_run` promotes to
      "cancelled" (NOT failed) when there's any completed chunk;
      status viewable, interpretation enabled. Cross-platform
      alternative to SIGTERM (Windows TerminateProcess doesn't
      deliver a catchable signal).
- [x] Cross-library relative ranking (commit ed90aa9).
      `GET /api/library/distributions` walks all latest.json +
      summaries to emit per-metric {values, count} +
      archetype_counts + volatility_class_counts. Frontend KPI
      cards `kpiVolatilitySub` / `kpiArchetypeSub` render "全库 P87
      (15/17)" for big libraries, "全库 N/M" for small ones.
      Composite volatility_score = max(zero_win/0.82, loss_p95/18,
      tail_ge10/0.50).

- [x] RTP denominator bug fix (commit 5ef2562): eq0 drop had
      excluded zero-win session bets from the denominator, inflating
      M272 RTP from 95% to 470%. return_bucket() restored to "eq0"
      internally; RETURN_BUCKET_ORDER still excludes it from output.
- [x] M272 + M14 full-pipeline regression fixtures + tests (commits
      8586afc + a9ecd4e + 6757cf1). Raw API responses as offline
      fixtures; 9 M272 + 7 M14 baseline assertions lock RTP, bucket
      sum, upstream delta, classification, tail dep, output shape.
- [x] Raw chunk cache: analyzer --chunk-cache-dir saves full API
      response per chunk (~250KB each, ~15MB/run). Backend wires
      cache dir; rebuild endpoint re-parses cached data through
      current analyzer code (commit 1c98edd + f23f302).
- [x] Upstream schema fingerprint + rebuild compatibility pre-check
      (commit 199d14e). SHA256 of first round's sorted key set;
      rebuild returns 409 when cached data is incompatible.
- [x] Debug tab reorder: interpretation moved to top (right after
      KPIs/chart); SpinType + Feature merged into one panel
      (commit ccfb2ca). Feature detail only shown for multi-feature
      machines.
- [x] Manage tab overhaul (commit 67771e3 + f347242 + 3ad8f4d):
      checkbox column + batch delete action bar; machine catalog
      multi-select filter (Set); rebuild button per-row with
      async chunk compatibility check (compatible ✓ / stale ✗).
- [x] NewFreespin RTP truncation correction (commit 098fc98):
      dynamic BuffCollectionMap cycle detection from CC resets;
      estimates lost payout from incomplete cycles. M272 mode 1:
      cycle=1000, correction=0pp when chunk_spin_times aligned.
- [x] 4 raw-data analyses (commit ba33480): payline×symbol joint
      top 20, session RTP curves (per-robot ~50 points), chain
      ExtraRatio complete sequences (≤50 chains), reel position
      hit frequency. Near-miss blocked (needs payline definitions).
- [x] Feature bar track container fix (commit f347242): bar width
      is now relative to a grey track div, not the full row.
      Bonus chain depth curve shows share% of total bonus rounds.

- [x] Major UI redesign (commit 979be08): interpretation at very top,
      Chart.js removed → table-based bucket distribution (count +
      rate% + RTP pp + bar), tail dep 2×2 uniform grid, bonus chain
      per-feature only with restored depth/histogram tables, rebuild
      mutex + runMeta progress.
- [x] Bonus chain per-feature split (commit 1ed1e83): NCS random
      (PayId 666) vs NFS forced (empty PID at cycle boundary). prev_
      round_pids indentation bug fixed.
- [x] Bucket count column + restored bonus chain tables (commit
      40dd34b).

## Work Mode

- Keep report generation deterministic and script-driven.
- Keep LLM usage in interpretation/comparison layer only.
- Never persist raw per-spin full data as long-term report assets.
