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

### `GET /api/machines/static`

Per-fleet static attributes cache (added 2026-04-19 round 2).
Decoupled from report lifecycle — survives report deletes. File-
backed at `configs/machines_static.json`, in-memory cached by
file mtime_ns.

```json
{
  "machines": {
    "M273": {
      "category": "Collect",
      "logicClassNames": ["BuffCollectionDataGenerator", ...],
      "features": ["NormalCollectionSpin", "LockSymbolFreespin", ...],
      "mechanics": ["lock_symbols", "free_spin", ...],
      "config_md5": "070d2f9...", "code_md5": "ecd...",
      "modes": [1, 2, 5, 7],
      "updated_at": "2026-04-19T..."
    },
    ...
  },
  "feature_distribution": { "Normal": 140, "Wheel": 51, ... },
  "mechanics_distribution": { "lock_symbols": 27, ... },
  "drift": ["M14", "M15"],
  "updated_at": "..."
}
```

Populated on first call via `_bootstrap_static_attrs` (walks
machines.json + existing report summaries). Updated on every
successful generate-report + /api/reports/import. `drift` list =
machines whose cached md5 differs from current machines.json md5
(operator should regenerate after refreshing MD5).

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

Notable `summary` sub-trees consumed by the UI:

`summary.rtp` — new fields 2026-04-20:
- `numerator_source`: "our_total_win" (default) or
  "server_total_win_override" (set when our per-round WinCredits
  sum diverges from analysisResult.TotalWin by >1%; point_pct
  is then computed from the server value instead)
- `our_total_win`: sum from per-round WinCredits
- `server_total_win`: sum from analysisResult.TotalWin (or null
  if the server didn't populate analysisResult on this machine)

The override prevents RTP inflation on machines like M112 where
the server emits BOTH a summary round (ST 98 FinalMinigame) AND
its detail sub-rounds (ST 97 WheelSpin × 5) carrying the same
payout — naive round-sum counts the payout twice. Per-SpinType
contributions (`spin_type_breakdown[*].rtp_contribution_pp`) still
reflect the raw aggregation and may sum above 100%; consult
`upstream_feature_breakdown` for an authoritative per-feature
slice on those machines.

`summary.sampling.bet` — per-spin bet used during sampling (int,
default 1000). Added 2026-04-20 so the PayID 总览 UI can render the
multiplier column (avg_win / bet) without fetching run metadata.

`summary.player_impact.payout_ids_top20[*]` — per-pay_id drilldown.
Added 2026-04-20: `spin_type_category` ∈ {paid, bonus, mixed, null},
`dominant_spin_type` (int or null), `spin_type_breakdown` (list of
`{spin_type, count}`) — UI renders the 类型 badge from this and
tooltip-attributes the paid-vs-bonus provenance without JOINing
across the SpinType panel.

`summary.player_impact.hit_and_payout` — paid-round-level rate block.
Added 2026-04-20: `big_win_x20_rate`, `big_win_x50_rate`,
`big_win_x100_rate` alongside the existing `big_win_x10_rate`. Each
is the share of paid rounds with win ≥ Nx the round's bet
(monotonically decreasing across the four thresholds).

`summary.player_impact.bankruptcy_simulation` — rawdata-replay
survival histogram (new shape 2026-04-20, replaces the old
`bankruptcy_probe` scalar rates; the legacy key still exists as a
backward-compat alias pointing at the same tier list):

```json
{
  "source": "rawdata_replay",
  "session_spins": 10000,
  "percentile_keys": [10, 20, 30, 40, 50, 60, 70, 80, 90],
  "tiers": [
    {
      "bankroll_multiplier": 100,
      "init_credits": 100000,
      "session_spins": 10000,
      "robots": 767,
      "bankrupt_robots": 757,
      "completed_robots": 10,
      "bankruptcy_rate": 0.987,
      "median_spins_completed": 365,
      "fastest_bankruptcy_spins": 117,
      "percentiles": {
        "10": 161, "20": 189, "30": 232, "40": 278, "50": 365,
        "60": 489, "70": 677, "80": 1131, "90": 2308
      }
    },
    ...
  ]
}
```

Implementation notes:
- Each chunk simulates ``len(pooled_rounds) // session_spins`` windows
  per tier (rounds across robots pooled into one IID stream; valid
  because upstream RNG is stateless per spin given
  ContinueAfterBankrupt=True + reset_each_spin=True during sampling).
- Per-window: start balance = ``multiplier × bet``, consume rounds
  debiting CostCredits and crediting WinCredits; bankrupt = balance
  can't cover the next paid bet. Bonus rounds (CostCredits=0) don't
  drain balance but still credit wins.
- Per-tier storage is an exact ``spins_done`` list (1-spin precision);
  at finalize the list is sorted and percentiles are resolved by
  rank index. Percentiles past the bankrupt share pin to
  ``session_spins`` — so a tier with 11% survival shows its P90 at
  session_spins once cumulative rank exceeds the bankrupt count.
- ``fastest_bankruptcy_spins`` is ``None`` when the tier had zero
  bankruptcies (giant bankroll always survived).
- ``median_spins_completed`` is a convenience alias for P50.

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

### `GET /api/library/distributions?mode=N`

Across-library metric distributions for the KPI lib-rank suffix on
Volatility + Archetype cards. Walks every
`reports/<machine>/mode_<n>/latest.json` + its summary JSON and
aggregates into per-metric distributions.

`mode` query param (optional, added 2026-04-20) restricts the
aggregation to a single mode — required for meaningful comparison
since mode 1 baseline machines have a different RTP / volatility
range than mode 5 bonus-mode machines. Without the filter,
distributions mix all modes (legacy behavior preserved).

Response:

```json
{
  "machines_count": 17,
  "mode": 1,
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

`mode` echoes the filter used (null when omitted).

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

### `POST /api/rawdata/{machine}/mode/{mode}/lock`

### `DELETE /api/rawdata/{machine}/mode/{mode}/lock`

Operator-controlled "never touch this" lock on one (machine, mode)
pair. Registry lives at `configs/rawdata_locks.json` (atomic writes).
Locked pairs are skipped by:
- `_auto_cleanup_for_space` (disk-pressure auto-cleanup loop)
- `POST /api/cache/cleanup` (manual 一键清理)
- `check_rawdata_status(auto_delete_mismatched=True)` md5-drift
  auto-delete (ecc7c92 regression fix — previously ignored lock)

Operator surfaces:
- `GET /api/rawdata/{m}` response now carries `locked: bool` per
  mode entry so the UI can render the lock indicator.
- Lock/unlock endpoints are idempotent — POST on an already-locked
  pair is a no-op 200; DELETE on an unlocked pair is a no-op 200.

Response: `{ok: true, machine, mode, locked: <bool>}`

Related disk-pressure env vars (set in the uvicorn shell):
- `SLOT_DISK_LOW_WATER_GB=5` — below this free space, batch sampling
  triggers auto-cleanup + wait loop
- `SLOT_TARGET_FREE_GB=10` — cleanup aims to free until ≥ this
- `SLOT_HARD_STOP_GB=2` — below this, batch items fail (after wait
  retries exhausted)
- `SLOT_WAIT_RETRIES=30` — max 10s waits before failing an item

### `POST /api/rawdata/{machine}/generate-report`

Documented above under Run Lifecycle.

### `POST /api/rawdata/batch-generate-report`

Kick off a batch of generate-report runs. Items run in a
`ProcessPoolExecutor` of N worker subprocesses (default 4, env
`SLOT_BATCH_GEN_WORKERS`); each worker has its own interpreter
state so analyzer's module-level `post_json` monkey-patch no
longer forces sequential. Held under the ops mutex.

Body (two variants):

```json
{ "items": [{"machine": "M273", "mode": 1}, {"machine": "M14", "mode": 2}] }
```

```json
{ "scope": "all_with_rawdata" }
```

`scope: "all_with_rawdata"` auto-collects every (machine, mode)
pair under `RAWDATA_ROOT` with at least one chunk file. Used by
the "⟳ 全 fleet 重建" button. On the dev fleet expands to ~1006.

Response (202-style):

```json
{ "batch_id": "bgen_abc123", "total": 1006, "status": "running" }
```

### `GET /api/rawdata/batch-generate-report/{batch_id}`

Poll a batch's progress:

```json
{
  "batch_id": "bgen_abc123",
  "started_at": "...", "finished_at": "...",
  "status": "completed | partial | failed | running | pending | cancelled",
  "total": 1006, "completed": 998, "failed": 3, "pending": 5,
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

Per-item failures record the error; batch status → `partial` on
any item failure, `completed` on all success. Mutex contention at
kickoff → `failed` immediately with every item marked failed.

### `POST /api/rawdata/batch-generate-report/{batch_id}/cancel`

Graceful cancel. Takes effect at the next item boundary — queued
futures get `future.cancel()`d, in-flight workers complete their
current item naturally (analyzer calls aren't killable mid-run).
Remaining pending items flip to `status=cancelled`; batch status
→ `cancelled`.

Response: `{ok: true, batch_id: "..."}`. 404 if batch not found
or already finished.

### `GET /api/rawdata/overview`

Fleet-wide rawdata breakdown (added 2026-04-19 round 2). Backs
the `💾 rawdata` topbar banner + the `[明细]` drill-down table.

```json
{
  "total_bytes": 9636025962,
  "baseline_bytes": 5980012345,
  "deletable_bytes": 3600000000,
  "stale_bytes": 56013617,
  "reclaimable_bytes": 3656013617,
  "per_machine": [
    {
      "machine": "M273",
      "kept_bytes": 180000000, "deletable_bytes": 20000000, "stale_bytes": 0,
      "kept_chunks": 21, "deletable_chunks": 30, "stale_chunks": 0,
      "last_sample_mtime": 1745000000.0
    },
    ...
  ]
}
```

Cached with mtime_ns fingerprint across all mode_dirs — warm
reads <1ms, cold walk ~5s on 9k chunks across 1006 modes.

### `GET /api/report-validate/{machine}`

Per-version md5 + analyzer status (extended 2026-04-19 round 2 to
include analyzer fields alongside md5).

```json
{
  "machine": "M273",
  "unverifiable": false,
  "upstream_config_md5": "070d2f9...", "upstream_code_md5": "ecd...",
  "current_analyzer_version": "badf2e2c3d4e",
  "reports": [
    {
      "mode": 1, "version": "rv_20260419T002849Z_rawdata",
      "md5_status": "match",
      "analyzer_status": "match",
      "report_config_md5": "070d2f9...", "report_code_md5": "ecd...",
      "report_analyzer_version": "badf2e2c3d4e"
    },
    ...
  ]
}
```

md5_status / analyzer_status values: `"match" | "outdated" | "untagged"`.

### `POST /api/reports/cleanup`

Aggressive cleanup (rewritten 2026-04-19 round 2). Partitions each
(machine, mode)'s versions into match / stale / untagged based on
summary.analyzer_version. Keeps newest match (or newest untagged
as baseline) per mode, deletes every tagged-stale version + their
runs DB rows. Second pass sweeps any remaining DB runs with
stale analyzer_version tag.

Response:

```json
{
  "ok": true,
  "deleted": 1005,     // disk dirs removed
  "kept": 1,           // survivors across fleet
  "runs_deleted": 23   // DB rows dropped
}
```

Driving behavior: the "⚠ N analyzer 过期" banner zeros after
click (stale_count reads DB which now matches disk).

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
`scripts/infer_paytable.py` — auto-triggered post generate-report
(daemon thread, ~60-120s on large machines like M1 with 384 chunks).

```json
{
  "machine": "M1",
  "mode": 1,
  "chunks_scanned": 384,
  "grid": {"n_cols": 3, "n_rows": 3},
  "wild_inference": {
    "status": "inferred",
    "wilds": ["Diamond1", "Diamond2"],
    "evidence": {"Diamond1": {"confidence": "high", ...}, ...},
    "review_needed": false,
    "stem_count": 0
  },
  "rows": [
    {
      "pay_id": 9,
      "match_count": 3,
      "fires": 41284,
      "avg_win": 20101.25,
      "line_ids_fired": [1, 2, 3, ...],
      "shape": {
        "symbol_set": ["Bar1"],
        "symbol_purity": 1.0,
        "wild_substitution_rate": 0.49,
        "line_id_sign": "positive",
        "position_cols_covered": [0, 1, 2],
        "confidence": "high",
        "notes": [],
        "composition_breakdown": [
          {"label": "3× Bar1", "fires": 20943, "avg_win": 10000,
           "win_total": 209430000, "composition": {"Bar1": 3},
           "has_wild": false},
          {"label": "2× Bar1 + 1× Diamond1", "fires": 10115,
           "avg_win": 20000, "win_total": 202300000,
           "composition": {"Bar1": 2, "Diamond1": 1}, "has_wild": true},
          ... (top 10 + optional aggregate tail row
               {"label": "其他 N 种组合", "is_aggregate_tail": true})
        ]
      }
    }, ...
  ],
  "machine_flags": []
}
```

Key 2026-04-20 additions:
- `avg_win` at the row top-level (mirrors analyzer payout_ids_top20
  but from the script's own rawdata scan)
- `shape.composition_breakdown`: emitted for every pay_id whose
  `symbol_tuples` counter has ≥2 distinct multisets (base + wild
  variants for line-pays; distinct wild compositions for all-wild
  pays like pay_id 3). Each entry carries `label / fires / avg_win
  / win_total / composition / has_wild`. Top 10 by fires shown
  directly; overflow bucketed into a trailing `"其他 N 种组合"`
  aggregate row (`is_aggregate_tail: true`).
- `shape.wild_composition_breakdown`: alias for
  `composition_breakdown` kept for backward compat.

Response shape stays `status="not_run"` + empty `rows` when the
file is missing (e.g. the auto-trigger subprocess timed out or
the operator never ran the script manually).

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

**Locked + in-use (m, mode) pairs are skipped** — the response
surfaces `skipped_locked` / `skipped_in_use` counts so the UI's
batch-log can explain "10 GB reclaimable, but X locked + Y sampling
right now, so actual free = Z."

Request:

```json
{
  "max_delete_bytes": 0
}
```

Response (added 2026-04-20): `{ok, freed_bytes, deleted_chunks,
skipped_locked, skipped_in_use, ...}`.

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
