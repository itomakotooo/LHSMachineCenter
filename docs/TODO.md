# TODO

This file tracks executable next steps for the current phase.

## P0 (must complete first)

- [ ] Add backend tests for safety interlock:
  verify `POST /api/runs`, `POST /api/autotune`, `POST /api/cache/cleanup` mutual exclusion and active-run blocking.
- [ ] Add backend tests for restart recovery:
  verify stale `running` rows are marked `failed`, and `startup_recovery` fields are exposed in `/api/health` and `/api/system-state`.
- [ ] Add frontend smoke/e2e tests:
  verify critical button disable rules, cache cleanup risk-tier confirmation, and bilingual tooltip rendering.
- [ ] Define CI gates:
  lint + tests must pass before merge to `main`.

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

## Work Mode

- Keep report generation deterministic and script-driven.
- Keep LLM usage in interpretation/comparison layer only.
- Never persist raw per-spin full data as long-term report assets.
