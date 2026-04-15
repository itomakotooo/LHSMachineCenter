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

## Work Mode

- Keep report generation deterministic and script-driven.
- Keep LLM usage in interpretation/comparison layer only.
- Never persist raw per-spin full data as long-term report assets.
