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

- Backend:
  run tests for API behavior touched by your change.
- Frontend:
  verify main flows in browser:
  run start/stop, auto tune, report view, cache cleanup protections, language switch.
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

## 8. File Ownership (Current)

- `fresh_slotlab/`:
  analyzer and metrics logic.
- `src/web_console/backend/`:
  API, orchestration, safety interlock, persistence.
- `src/web_console/frontend/`:
  console UI, interaction guards, bilingual UX.
- `configs/`:
  machine configs and guideline rules.
- `docs/`:
  operational and contract documentation.
