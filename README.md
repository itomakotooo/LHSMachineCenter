# Slot Lab

Slot Lab is a local analysis platform for slot-machine math validation and
player-impact reporting.

It contains:

- deterministic spin sampling with CI-based stopping
- report generation focused on player-impact metrics
- deterministic external guideline comparison
- a local web console for run control, progress, visualization, and model-based interpretation

## Current Scope

- test endpoint: `http://buffalo-debug.citrusjoy.com/MachineTest/MultiRobotTestSpin`
- machine registry from `configs/machines.json` (current default: `M14`, mode `1`)
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
  analyzer and sampling scripts
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

1. Install dependencies:

```powershell
python -m pip install -r src\web_console\requirements.txt
```

2. Start console:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_console.ps1
```

3. Open browser:

- `http://127.0.0.1:8877/console/`

Optional custom port:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_console.ps1 -Port 8899
```

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
