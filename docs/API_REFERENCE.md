# API Reference

## Console API (our backend)

Base URL (local):

- `http://127.0.0.1:<port>`

Default port:

- `8877` when started by `scripts/start_console.ps1`

## Health

### `GET /api/health`

Response:

```json
{
  "ok": true,
  "ts": "2026-04-14T03:00:00.000000Z",
  "app_started_at": "2026-04-14T02:58:49.000000Z",
  "operation_busy": false,
  "running_runs_count": 0,
  "startup_recovery_count": 0,
  "startup_terminated_pid_count": 0
}
```

### `GET /api/system-state`

Returns detailed runtime safety state:

- operation mutex snapshot (`operation_busy`, `operation_name`, `operation_since`)
- running run count + ids
- startup recovery result:
  - recovered stale run ids
  - terminated stale process pid list
  - failed-to-terminate stale process pid list

## Machine and Model Metadata

### `GET /api/machines`

Response:

```json
{
  "machines": [
    { "machine": "M14", "modes": [1, 2, 5, 7] },
    { "machine": "M272", "modes": [1, 2, 5, 7] }
  ]
}
```

### `GET /api/models`

Returns provider catalog, active provider, whether API key exists, and default model.

### `POST /api/model-config`

Request:

```json
{
  "provider": "gemini",
  "api_key": "YOUR_KEY"
}
```

Notes:

- provider must be one of `gemini`, `gpt`, `claude`
- config is persisted to `state/console/model_config.json`

## Run Lifecycle

### `POST /api/runs`

Start a sampling+report run.

Request:

```json
{
  "machine": "M14",
  "mode": 1,
  "target_halfwidth_pp": 0.5,
  "chunk_spin_times": 5000,
  "chunk_robot_count": 20,
  "batch_concurrency": 2,
  "max_chunks": 120,
  "timeout": 300,
  "bankruptcy_session_spins": 500,
  "bankruptcy_bankroll_multipliers": "100,200,500",
  "model_id": "gemini-3-flash-preview"
}
```

Response:

```json
{
  "run_id": "410794d3275e",
  "status": "running"
}
```

Safety behavior:

- returns `409` if another run is already active
- returns `409` if system mutex is occupied by another write operation

### `GET /api/runs`

List recent runs with summarized progress.

### `GET /api/runs/{run_id}`

Get a single run with latest progress data.

### `GET /api/runs/{run_id}/progress`

Get run event stream from jsonl progress file.

### `POST /api/runs/{run_id}/cancel`

Request graceful stop. Returns `{run_id, status: "cancelling"}`. The
backend writes a stop-flag file to the run's progress directory; the
analyzer polls this file between chunks and exits 0 with
`stop_reason="user_stop"` in its summary. `_watch_run` then flips
the run status to **`cancelled`** (not failed) when there is partial
data, preserving the summary / report / index / latest like a
completed run. If no chunk had completed before cancel fires, status
still flips to cancelled but `error_message` records "cancelled by
user before any chunk completed".

Cross-platform rationale: the Windows `subprocess.terminate()` maps
to `TerminateProcess` which doesn't deliver a catchable signal, so
the file-flag is the primary channel. Signal handlers (SIGTERM /
SIGINT) are also registered where catchable.

### `GET /api/runs/{run_id}/chunks`

Chunk cache status with compatibility check.

Response:

```json
{
  "run_id": "...",
  "chunk_count": 5,
  "total_bytes": 1250000,
  "fingerprint": "a3f8c2e1b9d04716",
  "compatible": true,
  "incompatible_reason": null,
  "available": true
}
```

`fingerprint` is SHA256[:16] of the first cached round's sorted key
set. `compatible` is false when required fields are missing from the
cached data (upstream schema drift). `available` = has chunks AND
compatible.

### `POST /api/runs/{run_id}/rebuild`

Re-parse cached raw chunks through the current analyzer code and
overwrite the run's summary + report.

Pre-checks:
- 404 if no cached chunks
- 409 if cached chunks are schema-incompatible
- 409 if system busy (operation mutex)

Response:

```json
{
  "run_id": "...",
  "status": "rebuilt",
  "chunks_reprocessed": 5,
  "rtp_point_pct": 95.10
}
```

### `DELETE /api/runs/{run_id}`

Delete a run's DB row and all its on-disk artefacts (progress /
summary / report files + the report version directory under
`reports/<machine>/mode_<n>/versions/<rv>/`). Filters the entry from
`index.json` and rolls `latest.json` back to the newest remaining
version (or removes it if the dropped run was the last version
left). Cascades `interpretations` table cleanup.

Behavior:
- returns `409` if the run's status is `running` (cancel it first)
- returns `404` if no such run_id
- guarded by the shared operation mutex (`delete_run`) so it can't
  race a concurrent start_run / cache_cleanup / _watch_run finish

Response:

```json
{
  "run_id": "...",
  "deleted": true,
  "removed_paths": ["...state/progress/X.jsonl", ...]
}
```

### `GET /api/runs/{run_id}/report`

Return:

- `summary` (JSON object)
- `report_markdown` (text)
- `summary_file`
- `report_file`

## Auto Tune

### `POST /api/autotune`

Run a quick parallelism benchmark and return recommended:

- `chunk_robot_count`
- `batch_concurrency`

Request (defaults shown; frontend uses compact 3x3 grid):

```json
{
  "machine": "M14",
  "mode": 1,
  "spin_times": 120,
  "robot_candidates": [8, 16, 24],
  "concurrency_candidates": [1, 2, 4],
  "rounds": 2,
  "timeout": 30,
  "bet": 1000
}
```

The run_auto_tune loop has a per-robot early-exit: once a
(robot, conc) candidate's success_rate drops below 0.7, all higher
conc with that same robot are skipped (saturation indicator).

Response includes:

- ranked benchmark entries with success rate, throughput, latency
- top recommendation in `recommendation`

Behavior:

- blocked with `409` if there is an active run
- blocked with `409` if system mutex is occupied by another write operation

## Versioned Reports

### `GET /api/reports/{machine}/{mode}`

Returns:

- `versions` (history from `index.json`)
- `latest` (pointer from `latest.json`)

Note: as of the Run History merge (commit 718e955), the frontend no
longer calls this endpoint -- Version + Quality moved onto the runs
table directly via `achieved_rtp_pct` / `achieved_halfwidth_pp` /
`quality_label` columns. Endpoint retained for back-compat / direct
curl usage.

### `GET /api/library/distributions`

Across-library metric distributions for the KPI lib-rank suffix on
Volatility + Archetype cards. Walks every
`reports/<machine>/mode_<n>/latest.json` + its summary JSON and
aggregates into per-metric distributions.

Response:

```json
{
  "machines_count": 17,
  "metrics": {
    "volatility_score":      { "values": [1.33, 1.38, ...], "count": 17 },
    "zero_win_rate":         { "values": [...], "count": 17 },
    "tail_dependency_ge10x": { "values": [...], "count": 17 },
    "big_win_x10_rate":      { "values": [...], "count": 17 },
    "profit_spin_rate":      { "values": [...], "count": 17 }
  },
  "archetype_counts":        { "Boom-Bust": 5, "Balanced": 10, "Grindy": 2 },
  "volatility_class_counts": { "Very High": 4, "High": 8, "Medium": 3, "Low": 2 }
}
```

`volatility_score` is composite:
`max(zero_win/0.82, loss_p95/18, tail_ge10/0.50)`; 1.0 = Very High
threshold reached, so ranking against this gives a continuous
intensity reading the discrete Very High / High / Medium / Low
label can't surface. No caching -- scales linearly with library
size (hundreds of machines still well under a second).

## Cache Management

### `GET /api/cache/status`

Cache size, file count, active-run count, reclaimable estimate.

### `POST /api/cache/cleanup`

Request:

```json
{
  "max_delete_bytes": 0
}
```

Notes:

- cleanup is manual-only
- cleanup is blocked while runs are active
- if system mutex is occupied, endpoint returns `409`
- frontend applies additional risk-tier confirmation before calling this endpoint:
  - low risk: one confirm
  - medium/high risk: confirm + token input (`DELETE`)

## Interpretation

### `POST /api/interpretations`

Request:

```json
{
  "run_id": "410794d3275e",
  "model_id": "gemini-3-flash-preview"
}
```

Returns interpreted content plus:

- `provider`
- `source` (`remote-*` or `rule-based`)
- `warning` (if fallback occurred)

### `GET /api/interpretations/{run_id}`

Get latest interpretation for a run.

---

## Upstream API (GM MachineTest)

Base URL: `http://buffalo-debug.citrusjoy.com` (test env, no auth)
or `http://127.0.0.1:1111` (local GM, auth required).

Full documentation: `MachineTest-TestSpin (3).md` in project root.

### `POST /MachineTest/MultiRobotTestSpin`

The endpoint we use for sampling. Request body = `MachineTestRequest`
with `RobotCount` + `OutputAllRobotResult=true`. Response = array of
robot dicts, each with `roundResult` (JSON string) and
`analysisResult` (JSON string).

Auth: `?token=YOUR_TOKEN` query param required on production GM.

### `POST /MachineTest/MachineConfigMd5`

Returns the current machine config hash. Useful for detecting config
changes between sampling runs.

Request: empty body.
Response: raw `_machineConfigMd5` JToken from `cfg.json`.

**Future integration**: store config MD5 alongside the schema
fingerprint in chunk cache envelopes. On rebuild, compare both —
schema drift = field renames; config drift = machine logic changed.

### `POST /MachineTest/RTPTest`

Upstream native batch RTP test across multiple machines. We implement
our own sampling pipeline; this is an alternative for quick checks.

### `POST /MachineTest/HistoryTestResult?machineName=X`

Reads the last `RTPTest` cached result for a machine. No relation to
our run/report system.
