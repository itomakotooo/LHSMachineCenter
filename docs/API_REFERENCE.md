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
  "sampling_strategy": "total",
  "model_id": "gemini-3-flash-preview"
}
```

`sampling_strategy` (default `"total"`):
- `"total"` — if existing rawdata already hits `max_chunks`, skip
  live sampling and use cache. Useful for count-mode dev runs.
- `"incremental"` — add `max_chunks` NEW chunks on top of existing
  cache regardless. Useful when accumulating samples.

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

### `POST /api/rawdata/{machine}/generate-report`

Generate a new report from cached rawdata chunks. Reads chunks from
`RAWDATA_ROOT/{machine}/mode_{mode}/`, pre-loads their `response`
payloads, and runs the analyzer through them end-to-end. Produces a
**new** report version (`rv_<ts>_rawdata`) + **new** run row
(`gen_<uuid>`) — pre-existing runs are never overwritten.

Body:

```json
{ "mode": 1, "async": true }
```

When `async: true` (recommended from UI), the endpoint spawns a
daemon thread and returns immediately with `{run_id, status:
"running"}` — operator polls progress via `GET /api/events` /
`GET /api/runs/{run_id}`. When `async: false` (default — direct API
clients), endpoint blocks until analyzer completes and returns the
full response shape below.

Pre-checks:
- 400 if `mode` is missing or non-integer
- 404 if no rawdata exists for (machine, mode), or if all chunks are
  stale md5 (server upgraded since sampling → resample required)
- 409 if system busy (operation mutex)

Response:

```json
{
  "run_id": "gen_abc123",
  "machine": "M273",
  "mode": 1,
  "report_version": "rv_20260418T091309Z_rawdata",
  "chunks_processed": 51,
  "rtp_point_pct": 52.35,
  "achieved_halfwidth_pp": 0.18,
  "analyzer_version": "269ca1cf0a26"
}
```

This endpoint replaces the retired `POST /api/runs/{run_id}/rebuild`.
The old rebuild was keyed on the transient `cache/chunks/{run_id}/`
directory which the current sampling flow never populates; the new
path is keyed on (machine, mode) where actual chunks live.

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

### `GET /api/reports/stale-count`

Fleet-wide staleness summary for the run-history banner. Walks runs
table (status=completed), compares each row's stored fingerprints
against the current snapshot, buckets into three kinds:

```json
{
  "total_completed_runs": 2013,
  "stale_rawdata": 5,      // server md5 drifted → resample required
  "stale_analyzer": 28,    // analyzer code drifted → batch-regen fixes
  "untagged": 7,           // pre-migration, no fingerprint stored
  "fixable_items": [{"machine": "M14", "mode": 1}, ...],
  "fixable_count": 15,     // dedup'd by (machine, mode)
  "current_analyzer_version": "269ca1cf0a26"
}
```

``fixable_items`` is the set of (machine, mode) pairs where analyzer
is stale AND rawdata is fresh — exactly the payload the UI's
"⟳ 一键重生成" button submits to
``POST /api/rawdata/batch-generate-report``.

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

## Rawdata Management

Rawdata (sampled chunks) lives under `RAWDATA_ROOT` (default
`rawdata/`; prod deploys override via `SLOT_RAWDATA_ROOT` env var).
Chunks are partitioned per (machine, mode) by a retention-quota
classifier into **kept** (md5 matches + within quota), **deletable**
(md5 matches + above quota), and **stale** (md5 drifted from current
machines.json).

### `GET /api/rawdata/{machine}`

Per-mode status. Each mode entry includes:
- `usable_chunks` / `mismatch_chunks` / `total_size_mb` (legacy shape)
- `classified` — `{kept_chunks, deletable_chunks, stale_chunks,
  kept_spins, deletable_spins, stale_spins, min_retention_spins}`
- `versions` — array grouped by (config_md5, code_md5) with
  `is_current` flag, used by the UI to show "current server version"
  vs "outdated" chunk groups.

### `DELETE /api/rawdata/{machine}?mode=N&force=false`

Delete rawdata for a machine (all modes or specific mode).

- `force=false` (default) — respects the retention quota: only
  deletable + stale chunks are removed, kept baseline survives.
- `force=true` — nuclear. UI gates this behind a "DELETE" token prompt.

Response: `{ok, deleted, forced, deleted_chunks, kept_chunks, deleted_bytes}`.

### `POST /api/rawdata/{machine}/generate-report`

Documented above under Run Lifecycle.

### `POST /api/rawdata/batch-generate-report`

Kick off a batch of generate-report runs across multiple (machine,
mode) pairs. Sequential within the batch — analyzer's ``post_json``
is monkey-patched at the module level so concurrent generator calls
would race. Held under the ``ops`` mutex for the full duration.

Body:

```json
{ "items": [{"machine": "M273", "mode": 1}, {"machine": "M14", "mode": 2}] }
```

Response (202-style, batch runs in background):

```json
{ "batch_id": "bgen_abc123", "total": 2, "status": "running" }
```

### `GET /api/rawdata/batch-generate-report/{batch_id}`

Poll a batch's progress. Returns full per-item state:

```json
{
  "batch_id": "bgen_abc123",
  "started_at": "...",
  "finished_at": "...",
  "status": "completed | partial | failed | running | pending",
  "total": 2, "completed": 2, "failed": 0, "pending": 0,
  "error": null,
  "items": [
    {
      "machine": "M273", "mode": 1, "status": "completed",
      "run_id": "gen_xxx", "rtp_point_pct": 92.37,
      "achieved_halfwidth_pp": 0.49, "chunks_processed": 51,
      "error": null
    },
    ...
  ]
}
```

Per-item failure (e.g. no rawdata for that mode) records the error
but the batch keeps processing remaining items; final status =
``partial``. Whole-batch failure (ops mutex contention) marks
every pending item failed and returns ``status: failed``.

### `GET /api/events`

Unified live event feed aggregating every active operation
(sampling runs / generate-report / batch regens / cache cleanup /
hall refresh). Replaces the UI's prior need to poll a dozen
per-operation progress endpoints separately. Frontend's activity
strip polls this at 1.2s cadence.

Response shape:

```json
{
  "ts": "2026-04-19T03:14:09Z",
  "events": [
    {"source": "run:abc123", "kind": "chunk_progress", "ts": "...",
     "machine": "M273", "chunks_done": 12, "total_spins": 1200000},
    {"source": "bgen:bgen_xyz", "kind": "item_completed", "ts": "...",
     "machine": "M14", "mode": 2, "status": "completed"}
  ],
  "operation_busy": false
}
```

### `GET /api/paytables/{machine}/mode/{mode}/shape`

Returns the per-pay_id shape JSON for (machine, mode) from
`configs/paytables/{machine}_mode{mode}.json`. Generated by
`scripts/infer_paytable.py` — pure shape, no multipliers.

```json
{
  "machine": "M273",
  "mode": 1,
  "generated_at": "2026-04-19T02:00:00Z",
  "pay_ids": [
    {
      "pay_id": 2,
      "symbol_set": ["high7"],
      "symbol_purity": 1.0,
      "wild_substitution_rate": 0.0,
      "line_id_sign": "positive",
      "position_cols_covered": 3,
      "confidence": "high",
      "notes": ""
    },
    ...
  ],
  "wilds": [
    {"symbol": "wild_5x", "tier": 5, "confidence": "high"}
  ]
}
```

Response 404 if no shape JSON exists for (machine, mode).

### `GET /api/machines/halls`

Return cached hall grouping for the 按大厅 catalog view. Sourced
from ``configs/machine_halls.json`` (populated by the refresh
endpoint). Missing file → empty halls.

```json
{
  "halls": {"G1": ["M9", "M88", "M51", ...], "G10": ["M70", ...], ...},
  "updated_at": "2026-04-18T13:04:09Z",
  "source": "http://buffalo-debug.citrusjoy.com/MachineTest/MapMachineOrder"
}
```

### `POST /api/machines/halls/refresh`

Operator-triggered upstream fetch. Calls
``POST /MachineTest/MapMachineOrder`` on the configured server,
parses ``localMapMachineCellsJson`` to extract the hall/zone ID
from each machine's ``prefabAssetPath`` (pattern:
``Assets/UIAssets/(SilentLoad/)?MapMachine/{HALL}/...``), writes
the result to disk. Body ``{server_id?: "..."}`` selects a
non-default server.

Guarded by the ``ops`` mutex. Live dev server: 32 halls / 247
machines classified from 252 in machines.json.

## Cache Management

### `GET /api/cache/status`

Response includes both legacy `cache/chunks/` stats and authoritative
rawdata totals:

```json
{
  "cache_root": "...",
  "cache_total_bytes": 0,
  "cache_file_count": 0,
  "rawdata_root": "...",
  "rawdata_total_bytes": 9636025962,
  "rawdata_file_count": 1057,
  "total_bytes": 9636025962,
  "file_count": 1057,
  "running_runs": 0,
  "reclaimable_bytes_estimate": 9636025962,
  "risk_thresholds": {"medium_bytes": ..., "high_bytes": ...}
}
```

`reclaimable_bytes_estimate` is approximated as `rawdata_total_bytes`
for perf (exact classification only runs inside cleanup).

### `POST /api/cache/cleanup`

Tier-based cleanup over `RAWDATA_ROOT`. Deletes stale + deletable
chunks oldest-mtime first, across all (machine, mode) pairs. Baseline
kept quota is never touched (operator must use
`DELETE /api/rawdata/{m}?force=true` per machine for that).

Request:

```json
{
  "max_delete_bytes": 0
}
```

Notes:
- blocked while runs are active
- guarded by the shared operation mutex (409 if busy)
- frontend adds risk-tier confirmation:
  - low risk: one confirm
  - medium/high risk: confirm + `DELETE` token prompt

## Settings

### `GET /api/settings`

Returns operator-tunable knobs persisted in
`state/console/settings.json`. Currently:

```json
{ "min_retention_spins": 100000 }
```

### `PUT /api/settings`

Upsert settings. Invalid values rejected with 400.

```json
{ "min_retention_spins": 50000 }
```

## Versions (for Staleness Detection)

### `GET /api/versions/current`

Snapshot of current fingerprints for the Run History staleness badges:

```json
{
  "analyzer_version": "<12-char hex>",
  "machines": {
    "M14": { "config_md5": "...", "code_md5": "..." }
  }
}
```

`analyzer_version` = SHA256[:12] of `player_impact_analyzer.py` source.
Per-machine md5 comes from `configs/machines.json`.

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

**Current integration**: config MD5 + code MD5 are stored per-chunk
in envelopes (`_config_md5`, `_code_md5`) and per-report in summary
files (`config_md5`, `code_md5`). The classifier compares envelope
md5 vs current machines.json to partition chunks into kept / stale
tiers, and the Run History UI shows a staleness badge when the
report's stored md5 differs from the current server snapshot.

### `POST /MachineTest/RTPTest`

Upstream native batch RTP test across multiple machines. We implement
our own sampling pipeline; this is an alternative for quick checks.

### `POST /MachineTest/HistoryTestResult?machineName=X`

Reads the last `RTPTest` cached result for a machine. No relation to
our run/report system.
