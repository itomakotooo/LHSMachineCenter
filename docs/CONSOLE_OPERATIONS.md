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
2. Set target CI half-width (default `0.5`; mode 2/5 locks to fuzzy).
3. (Optional) Click `Auto Tune Parallelism` to probe per-machine
   optimal robot / concurrency. Not required -- `Chunk Robot Count`
   and `Batch Concurrency` ship with preset defaults (robot=24,
   conc=2) validated against M272 mode 1.
4. (Optional) Tweak advanced params in the collapsed section:
   `chunk_spin_times` / `max_chunks` / `timeout`.
5. Start run and watch progress in runMeta + liveStatusStrip.
   Click `Stop` mid-run for a graceful cancel that preserves the
   already-completed chunks (status becomes `cancelled`; the summary
   is still viewable and interpretation is still available).
6. After completion (or graceful cancellation), review in order:
   - KPI cards (12 cards; Tail Dep shows the ≥10/20/50/100x ladder
     in the sub-line; Volatility + Archetype carry a library-wide
     rank sub when ≥2 machines exist).
   - Multiplier bucket chart (11 win-bearing buckets; zero-win rate
     lives in the KPI grid, not in the chart).
   - Interpretation + Assessment panels, `rtpClampWarning` if the
     collect mechanic truncated.
   - Drilldowns: paylines, Pay ID (from PayoutIdToWinAmount),
     symbols by column, SpinType breakdown (with `Behavior`
     "paid"/"free"/"mixed" labels; free-spin RTP renders N/A), and
     for machines with bonus features:
     - `Upstream feature breakdown` (from analysisResult.FeatureWin;
       M272 shows NormalCollectionSpin + NewFreespin)
     - `Bonus chain dynamics` (from ReMarks Freespin annotations;
       chain length quantiles, peak ExtraRatio, self-retrigger rate,
       energy-ramp curve)
   - Guideline assessment + comparison.
7. Optionally trigger model interpretation. Available on `completed`
   AND `cancelled` runs (LLM can comment on partial data).

## 3a. Rebuild from Cache

When the analyzer code changes (new surfaces, bug fixes, classification
tweaks), you can rebuild an existing run's report from the same raw
data without re-fetching from the upstream API:

1. Go to "Fleet Management" tab.
2. Find the run in the history table. The "Rebuild" button shows:
   - **"N chunks ✓"**: cached data is compatible; click to rebuild.
   - **"N chunks ✗ stale"**: upstream schema changed since sampling;
     the cached data can't be parsed by the current analyzer. Delete
     the stale cache and resample.
   - **Disabled (greyed)**: no cached chunks exist for this run.
3. Click "Rebuild" → the backend re-parses all cached raw API
   responses through the current analyzer → overwrites summary +
   report → updates RTP/CI/quality in the run history.

Raw chunks are saved automatically during every run
(`cache/chunks/{run_id}/chunk_*.json`, ~250KB each). The cache
can be cleaned via the "Chunk Cache" panel at the bottom of the
Fleet Management tab.

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
