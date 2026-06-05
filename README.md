# Slot Lab

Slot Lab is a local analysis platform for slot-machine math validation and
player-impact reporting.

It contains:

- deterministic spin sampling with CI-based stopping
- report generation focused on player-impact metrics
- deterministic external guideline comparison
- a local web console for run control, progress, visualization, and model-based interpretation

## Current Scope

- test endpoint: the active server from `configs/servers.json`, path
  `/MachineTest/MultiRobotTestSpinVariant` — internal `dev`
  (`http://192.168.10.21:15060`) on the intranet, public `prod`
  (`http://116.232.103.19:10288`) off-site; pick the default via the
  server-management UI. It accepts both variant keys like `M273$1$1-2-3` and
  plain machine names like `M14` — variants get rewritten to
  underlying+selector params upstream, non-variants fall through to plain
  test-spin.
- machine registry from `configs/machines.json` — non-variant machines plus
  one variant row per entry in `machineTestVariantsJson` (from
  `/MapMachineOrder`); see the file for the live roster/count. Each row is an
  independent machine — its own md5, modes, rawdata directory, reports.
  Current default: `M14`, mode `1`.
- report output under `reports/<machine>/mode_<id>/versions/<report_version>/`

## Core Capabilities

1. CI-driven sampling:
   stop when 95% CI half-width reaches target (default `0.5pp`) or when max chunks are hit.
2. Player-impact metrics:
   volatility, hit/profit rates, multiplier buckets, streaks, paylines, symbols, bankruptcy curve.
3. Guideline engine:
   - qualitative guideline in `configs/classic_slots_guideline.md`
   - deterministic rules in `configs/classic_slots_guideline_rules.json`
   - output in `summary.guideline_assessment` and `summary.guideline_comparison`
4. Web console:
   - run start/stop/progress
   - one-click parallelism auto-tune (`/api/autotune`)
   - field-level usage tooltips for all key parameters (CN/EN switch)
   - KPI cards and charts (CI trend, RTP trend, multiplier buckets, bankruptcy curve)
   - operation safety interlock (UI mutex + backend mutex)
   - restart recovery for stale running tasks (with stale process cleanup attempt)
   - cache cleanup risk-tier confirmation (low/medium/high)
   - model interpretation routing (`gemini` / `gpt` / `claude`)

## Repository Layout

- `fresh_slotlab/`:
  analyzer and sampling scripts. The analyzer's 9 display sections are
  feature **plugins** under `fresh_slotlab/analyzer/features/` (each
  owns its own compute/emit); the analyzer core runs a topo-sorted
  feature emit loop rather than building sections inline. Per-machine
  manifests (`slot_designer/configs/machine_manifests/<machine>.json`)
  declare which features a machine uses.
- `src/web_console/`:
  FastAPI backend + frontend console
- `configs/`:
  machine list and guideline/rules
- `reports/`:
  versioned report assets and report indexes
- `cache/chunks/`:
  temporary chunk cache (evictable)
- `state/`:
  local runtime state (db/log/progress, not for git except keep files)
- `scripts/`:
  local startup helpers
- `docs/`:
  operation and interface references

## Quick Start (Local)

**Prerequisites:** Python ≥ 3.10 (the codebase uses PEP 604 union types like `int | None`).

> 策划 / numeric designers: see [docs/FOR_DESIGNERS.md](docs/FOR_DESIGNERS.md) for the
> config-iteration workflow (drop `<M>Cfg.txt` → sample → compare report → repeat).

**One-click (Windows):** double-click `start.bat` in the repo root. It
runs the launcher with `-OpenBrowser` so the console tab opens after
uvicorn is up. On first run pass `/install` to pip-install deps once:

```
start.bat /install
```

Subsequent launches just:

```
start.bat
```

Common variants:

```
start.bat /port 8899         # custom port
start.bat /noopen            # skip auto-open browser
```

**Manual:** if you prefer the raw commands:

1. Install dependencies:

```powershell
python -m pip install -r src\web_console\requirements.txt
```

2. Start console (add `-OpenBrowser` to auto-open the tab, `-Install`
   to pip-install first):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_console.ps1 -OpenBrowser
```

3. Open browser if you didn't pass `-OpenBrowser`:

- `http://127.0.0.1:8877/console/`

Optional custom port:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_console.ps1 -Port 8899 -OpenBrowser
```

The launcher refuses to start if the target port is already in use
(prints the offending PID list) and fails fast with a clear hint if
`fastapi` / `uvicorn` aren't installed yet.

## Local Development Checks

Install dev deps (first time only):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 -Install
```

Lint (Python compileall + AST side-effect guard + ruff if installed + Node syntax check):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\lint.ps1
```

Backend + frontend unit tests (fast):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

Full suite including Playwright end-to-end:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 -E2E
```

Both scripts default to strict mode; pass `-AllowMissingNode` on a
machine without Node 18+ to skip the frontend pure-function suite.

## Analyzer CLI (Direct)

Example run:

```powershell
python fresh_slotlab\player_impact_analyzer.py `
  --machine M14 `
  --rtp-mode 1 `
  --target-halfwidth-pp 0.5 `
  --chunk-spin-times 5000 `
  --chunk-robot-count 20 `
  --batch-concurrency 2 `
  --max-chunks 120 `
  --timeout 300 `
  --bankruptcy-session-spins 500 `
  --bankruptcy-bankroll-multipliers 100,200,500 `
  --output-dir reports\M14\mode_1\versions\manual_test `
  --guideline-rules configs\classic_slots_guideline_rules.json
```

Important request flags used by the analyzer/autotune path:

- `ResetPlayerStateAfterEachSpin=true`
- `OutputAllRobotResult=true`

## Data Lifecycle

1. Chunk source data is temporary and may be cache-evicted.
2. Chunk data that is still needed by an active run must not be deleted.
3. Aggregated metrics and report versions are long-term assets.
4. `reports/<machine>/mode_<id>/index.json` is append-only history.
5. `reports/<machine>/mode_<id>/latest.json` points to current latest version.
6. Report freshness is judged per-`(machine, mode)` via an
   `effective_analyzer_version` (analyzer core + only that machine's
   declared feature plugins). Changing one machine's features no longer
   marks the whole fleet stale — only the affected machine(s). The
   verdict is **non-destructive**: a mismatch flags the report stale and it
   is re-generated on demand — report artifacts are never deleted.

## Model Interpretation

- provider selection: `gemini`, `gpt`, `claude`
- one API key input in UI
- persisted local config file: `state/console/model_config.json`
- interpretation fallback: deterministic rule-based summary if remote call fails

## Documentation Index

- API reference: `docs/API_REFERENCE.md`
- Report schema and metrics: `docs/REPORT_SPEC.md`
- Console operations and troubleshooting: `docs/CONSOLE_OPERATIONS.md`
- Engineering TODO: `docs/TODO.md`
- Handover guideline for new developers: `docs/HANDOVER_GUIDELINE.md`

## Git Boundary

Track:

- code, configs, docs, report outputs/indexes

Do not track:

- runtime db/logs/progress files and local API keys under `state/console/`
- temporary chunk cache under `cache/chunks/`
