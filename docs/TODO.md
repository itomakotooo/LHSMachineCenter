# TODO

This file tracks executable next steps for the current phase.

## P0 (must complete first)

- [ ] Consider CI integration when remote build is needed.
  For now the baseline is local-only (`scripts\lint.ps1` + `scripts\test.ps1 -E2E`).

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

## Done Recently

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
- [x] chunk_robot_count + batch_concurrency are now readonly inputs
      populated only by Auto Tune; Start button is disabled until
      both are filled. Mode/machine change clears them to force a
      fresh Auto Tune.
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

## Work Mode

- Keep report generation deterministic and script-driven.
- Keep LLM usage in interpretation/comparison layer only.
- Never persist raw per-spin full data as long-term report assets.
