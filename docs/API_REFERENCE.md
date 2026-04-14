# API Reference

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
  "ts": "2026-04-14T03:00:00.000000Z"
}
```

## Machine and Model Metadata

### `GET /api/machines`

Response:

```json
{
  "machines": [
    { "machine": "M14", "modes": [1] }
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

### `GET /api/runs`

List recent runs with summarized progress.

### `GET /api/runs/{run_id}`

Get a single run with latest progress data.

### `GET /api/runs/{run_id}/progress`

Get run event stream from jsonl progress file.

### `POST /api/runs/{run_id}/cancel`

Terminate a running job.

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

Request:

```json
{
  "machine": "M14",
  "mode": 1,
  "spin_times": 120,
  "robot_candidates": [8, 12, 16, 20, 24],
  "concurrency_candidates": [1, 2, 3, 4],
  "rounds": 2,
  "timeout": 30,
  "bet": 1000
}
```

Response includes:

- ranked benchmark entries with success rate, throughput, latency
- top recommendation in `recommendation`

Behavior:

- blocked with `409` if there is an active run

## Versioned Reports

### `GET /api/reports/{machine}/{mode}`

Returns:

- `versions` (history from `index.json`)
- `latest` (pointer from `latest.json`)

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

