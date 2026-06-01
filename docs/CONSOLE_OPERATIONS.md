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
   and `Batch Concurrency` ship with preset defaults (robot=20,
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

## 3a. Regenerate Report from Rawdata

When the analyzer code changes (new surfaces, bug fixes, classification
tweaks), you can regenerate a report from the same cached rawdata without
re-fetching from the upstream API. This is keyed on **(machine, mode)** —
on the cached chunks under `RAWDATA_ROOT/{machine}/mode_{mode}/`, where
actual chunks live — not on a per-run cache directory.

1. Go to "Fleet Management" tab. The run-history banner shows an
   "⚠ N analyzer 过期" count when reports were built with older analyzer
   code than the current per-(machine, mode) `effective_analyzer_version`.
2. Click "⟳ 一键重生成" (batch regen for the fixable set) — or trigger a
   single (machine, mode) regen — which submits to
   `POST /api/rawdata/{machine}/generate-report` (single) /
   `POST /api/rawdata/batch-generate-report` (fleet).
3. The backend re-parses the cached raw API responses through the current
   analyzer → writes a **new** report version (`rv_<ts>_rawdata`) + a new
   run row (`gen_<uuid>`). Pre-existing runs are never overwritten or
   deleted.

Staleness is **non-destructive**: a stale verdict is a read-only
classification (the staleness badge / banner counts), never a deletion
trigger — `POST /api/reports/cleanup` no longer deletes versions on an
analyzer-tag mismatch, and `check_rawdata_status` never unlinks chunks.
Re-baselining is on-demand: the operator regenerates via the buttons above
(an auto_sweep / auto-inspect background mechanism + per-mode settings also
exist to drive bounded re-analysis; see `/api/settings`). If a machine's
chunks were sampled against an older server md5 (rawdata stale, not just
analyzer stale), regeneration from the current-md5 chunks needs fresh
sampling first — those land in `needs_rawdata_items` from
`/api/reports/stale-count` rather than the fixable set. Historical-md5
chunks are kept on disk (not deleted); a report can still be generated from
a specific historical md5 by passing `config_md5`+`code_md5` to the
generate-report endpoint.

The old per-run "Rebuild" button + `POST /api/runs/{run_id}/rebuild`
endpoint (keyed on the transient `cache/chunks/{run_id}/` directory) are
RETIRED — that directory is no longer populated by the current sampling
flow.

## 4. Auto Tune Notes

Auto tune endpoint:

- `POST /api/autotune`

Selection objective:

- prioritize high success rate and high throughput
- use latency as tie-breaker

Safety:

- auto tune is blocked while any run is active

## 5. Rawdata Cache and Retention

- rawdata (sampled chunks) lives under `RAWDATA_ROOT` (default `rawdata/`;
  prod overrides via `SLOT_RAWDATA_ROOT`). The legacy `cache/chunks/` root
  is kept only for back-compat reporting and is empty in the current flow.
- chunks are classified per (machine, mode) into **kept** (current md5,
  within retention quota), **deletable** (current md5, above quota), and
  **historical** (md5 drifted from current machines.json). md5 is a
  classification tag, NOT a destruction signal — historical chunks are
  never auto-deleted.
- cache cleanup is manual-only from UI; only deletable + historical chunks
  are removed (oldest-mtime first). The kept baseline quota is never
  touched by cleanup.
- cleanup is blocked while runs are active and has risk-tier confirmation:
  - low risk: one confirmation dialog
  - medium/high risk: confirmation + token input (`DELETE`)
- operators can **lock** a (machine, mode) pair
  (`POST /api/rawdata/{m}/mode/{n}/lock`) to exempt its chunks from
  disk-pressure auto-cleanup, manual cleanup, and the default
  (non-forced) per-machine delete. `force=true` deletion is the explicit
  escape hatch that bypasses the lock.
- report assets are stored in `reports/` and intended for long-term
  retention; report staleness is non-destructive — it is a read-only
  classification signal and never deletes report artifacts (operators
  regenerate on demand; see §3a).

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
