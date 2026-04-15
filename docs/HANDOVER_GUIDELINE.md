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

## 8. File Ownership (Current)

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

## 9. Test Layout

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

## 10. Troubleshooting

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
