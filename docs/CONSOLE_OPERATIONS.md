# Console Operations

Operational guide for local Slot Console usage.

## 1. Prerequisites

- Python available in PATH
- network access to test endpoint
- dependencies:

```powershell
python -m pip install -r src\web_console\requirements.txt
```

## 2. Start and Stop

Start console:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_console.ps1
```

Custom port:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_console.ps1 -Port 8899
```

Open:

- `http://127.0.0.1:<port>/console/`

Stop:

- terminate the running PowerShell/uvicorn process

## 3. Recommended Run Workflow

1. Select machine and mode.
   - hover/focus the `i` hint beside each field to view usage guidance
2. Click `Run Auto Tune` first.
3. Use returned recommended:
   - `Chunk Robot Count`
   - `Batch Concurrency`
4. Set target CI half-width (default `0.5`).
5. Start run and watch progress charts.
6. After completion, review:
   - KPI cards
   - multiplier bucket chart
   - bankruptcy curve
   - guideline assessment and comparison
7. Optionally trigger model interpretation.

## 4. Auto Tune Notes

Auto tune endpoint:

- `POST /api/autotune`

Selection objective:

- prioritize high success rate and high throughput
- use latency as tie-breaker

Safety:

- auto tune is blocked while any run is active

## 5. Cache and Retention

- cache path: `cache/chunks/`
- cache cleanup is manual-only from UI
- cleanup is blocked while runs are active
- cleanup has risk-tier confirmation:
  - low risk: one confirmation dialog
  - medium/high risk: confirmation + token input (`DELETE`)
- report assets are stored in `reports/` and intended for long-term retention

## 6. Safety Interlock and Recovery

- UI layer:
  - write actions are mutex-controlled to avoid conflicting clicks
  - cache cleanup button is marked as dangerous and risk-highlighted
- backend layer:
  - write endpoints use an operation mutex (`start_run`, `auto_tune`, `cache_cleanup`)
  - duplicate run start is hard-blocked
- restart recovery:
  - stale `running` rows are auto-marked `failed` at service startup
  - system attempts to terminate stale worker processes using stored `process_pid`
  - recovery summary is exposed via `/api/health` and `/api/system-state`

## 7. Model Routing

Providers:

- `gemini`, `gpt`, `claude`

Config persistence:

- local file: `state/console/model_config.json`

Fallback:

- if remote model fails or no key is set, system falls back to deterministic rule-based interpretation

## 8. Troubleshooting

### UI opens but no data

- check `GET /api/health` first
- ensure endpoint connectivity for spin requests

### Start run fails

- verify analyzer script path: `fresh_slotlab/player_impact_analyzer.py`
- verify machine/mode exists in `configs/machines.json`

### Auto tune fails with 409

- active run exists; stop/cancel current run first

### Cache cleanup not clickable

- check `reclaimable_est` in cache panel; button is disabled when reclaimable bytes are zero
- cleanup remains disabled while any run is active or system is busy

### No interpretation text

- verify provider/model mapping and API key
- check if fallback warning is returned from `/api/interpretations`

## 9. Local Runtime Files

Expected local runtime files under `state/console/`:

- `console.db`
- `progress/*.jsonl`
- `*.out.log`, `*.err.log`
- `model_config.json`

These are local operational artifacts and should not contain in-repo report truth.
