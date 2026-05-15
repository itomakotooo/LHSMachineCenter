# 01 Deploy Pipeline Map — Current State

> Wave 1 of deploy review. Observation only — no proposals.
> Date: 2026-05-15

---

## §1 Process Topology

```
Browser(s)
    │  HTTP/polling (4.5s / 1.2s / 1s)
    ▼
uvicorn  ──────────────────────────────────────────────────────────────────────
│  FastAPI app                                    port 8877 (real console)
│  created by  main.py:app = create_app()         port 8878 (virtual console)
│                src/web_console/backend/main.py:15
│                src/web_console/backend/app.py:5286
│
│  Singletons (per create_app() call):
│    StateStore  → state/console/console.db   (SQLite WAL)
│    RunManager  → tracks running analyzer subprocesses
│    BatchRunManager → orchestrates multi-machine sampling in threads
│    BatchGenerateManager → batch-regen in ProcessPoolExecutor
│    OperationCoordinator → coarse single-busy-operation lock (in-memory)
│    RuntimeModelConfig → persisted to state/console/model_config.json
│
├─── Thread A: _prewarm_machines_summary()          (daemon, fires at startup)
│
├─── Per batch-run: BatchRunManager._run_batch()    (daemon thread)
│       Semaphore(concurrency)
│       Per item: BatchRunManager._run_one()
│           → RunManager.start_run()
│               → subprocess.Popen(fresh_slotlab/player_impact_analyzer.py)
│                   ↕ PIPE (stdout/stderr)          child PID stored in DB
│               → daemon thread: RunManager._watch_run()
│                   waits proc.communicate() → updates SQLite row
│               → (on completion) daemon thread: _run_post_analyzer_inference()
│                   → subprocess.run(scripts/infer_paytable.py)
│                   → subprocess.run(scripts/verify_machine_labels.py)
│
├─── Per generate-report (async=true):              (daemon thread)
│       → RunManager.start_run() → analyzer subprocess
│
├─── Per batch-generate-report:                     (daemon thread)
│       BatchGenerateManager._run()
│           ProcessPoolExecutor(spawn, max_workers=SLOT_BATCH_GEN_WORKERS=4)
│           worker: _batch_gen_worker.run_analyzer_job()
│               calls analyzer.main() in-process (module imported once per worker)
│               then subprocess.run(infer_paytable.py)
│               then subprocess.run(verify_machine_labels.py)
│
├─── Pre-batch md5 refresh:                         (daemon thread)
│       _do_refresh_machines_md5()
│           → HTTP POST upstream/MachineTest/MachineConfigMd5
│
├─── Autotune:                                      (foreground, ops lock held)
│       run_auto_tune() in request thread
│
└─── State / persistence:
      rawdata/       <machine>/mode_<N>/chunk_NNNN.json
                                        _chunks.json    (per-mode sidecar)
                     _index.json                        (fleet-level cache)
      reports/       <machine>/mode_<N>/index.json
                                        latest.json
                                        versions/<rv_...>/player_impact_summary.json
                                                         player_impact_report.md
      state/console/ console.db                         (SQLite)
                     model_config.json
                     settings.json
                     progress/<run_id>.jsonl
                     progress/<run_id>.stop             (graceful stop flag)
      configs/       machines.json
                     servers.json
                     rawdata_locks.json
                     machines_static.json
```

---

## §2 Backend Stack

**Server framework**: FastAPI (>=0.111.0) + uvicorn (>=0.30.0) + pydantic (>=2.7.0)
Source: `src/web_console/requirements.txt:1-3`

**Runtime deps (stdlib only, no extras)**: sqlite3, threading, subprocess, concurrent.futures, urllib.request, uuid, json, pathlib, shutil, signal

**Entry point (production)**: `src/web_console/backend/main.py:15`
```python
app = create_app()
```
`create_app()` defined at `src/web_console/backend/app.py:5286`

**Virtual console entry point**: `slot_designer/core/backend/virtual_app.py:201`
```python
app = build_virtual_app()
```
`build_virtual_app()` calls `create_app()` with injected paths at `virtual_app.py:186`

**Uvicorn launch command (real console)**:
```
python -m uvicorn src.web_console.backend.main:app --host 127.0.0.1 --port 8877 --log-level info
```
Source: `scripts/start_console.ps1:67`

**Uvicorn launch command (virtual console)**:
```
python -m uvicorn slot_designer.core.backend.virtual_app:app --host 127.0.0.1 --port 8878
```
Source: `slot_designer/scripts/start_virtual_console.ps1` (mirrors pattern)

**Host binding**: `127.0.0.1` (loopback only — single-user localhost; no LAN exposure currently)
Source: `scripts/start_console.ps1:67`, `src/web_console/backend/main.py:23`

**Port guard**: PowerShell `Get-NetTCPConnection` check before uvicorn start
Source: `scripts/start_console.ps1:25-36`

**Module-level globals set at import time** (create_app closure captures these at call time):
- `RAWDATA_ROOT = Path(os.getenv("SLOT_RAWDATA_ROOT", str(RAWDATA_ROOT_DEFAULT)))` — `app.py:518`
- `SLOT_SPIN_ENDPOINT = "http://192.168.10.21:15060/MachineTest/MultiRobotTestSpinVariant"` — `app.py:73`
- `_IN_USE_MODES: set` — module-global, `app.py:2152`
- `_LOCK_CACHE: dict` — module-global mtime-invalidated cache, `app.py:2178`
- `_STATIC_ATTRS_CACHE: dict` — module-global, referenced near `app.py:2252`

**Environment variables controlling runtime behavior**:
- `SLOT_RAWDATA_ROOT` — override rawdata root path (default: `rawdata/` at repo root)
- `SLOT_BATCH_GEN_WORKERS` — ProcessPoolExecutor size for batch-regen (default: 4)
- `SLOT_DISK_LOW_WATER_GB` — disk pressure trigger (default: 5)
- `SLOT_DISK_TARGET_FREE_GB` — disk pressure cleanup target (default: 10)
- `SLOT_DISK_HARD_STOP_GB` — per-item hard bail (default: 2)
- `SLOT_DISK_WAIT_RETRIES` — max wait loops for disk (default: 30)
- `SLOT_SKIP_AUTO_INFER` — skip post-hook inference scripts (default: unset)
- `SLOT_RISK_MEDIUM_BYTES` / `SLOT_RISK_HIGH_BYTES` — cache cleanup risk thresholds
- `MODEL_PROVIDER` — AI interpretation provider (default: `gemini`)
- `MODEL_API_KEY` — AI interpretation key

---

## §3 Frontend Stack

**Build tool**: None. Static files served directly — no Vite, no Webpack, no compilation step.

**Source layout**:
```
src/web_console/frontend/
    index.html        entry HTML with {{ASSET_HASH}} placeholder
    app.js            all frontend logic (~9000+ lines, single file)
    pure.js           utility/pure functions
    styles.css        all styles
    compare_diff.js   report comparison
```
Source: confirmed by `ls` — no `package.json`, no `node_modules`, no build artifacts

**External CDN dependency**: `chart.js` loaded from `cdn.jsdelivr.net` at runtime
Source: `frontend/index.html:8`

**Serving mechanism**: FastAPI `StaticFiles` mount + explicit route
- `app.py:5392`: `app.mount("/console", StaticFiles(directory=FRONTEND_DIR), name="console")`
- `app.py:5383-5390`: `@app.get("/console/")` and `@app.get("/console")` — serve `index.html` with `{{ASSET_HASH}}` substituted at request time
- Cache-bust token: `max(mtime)` of `pure.js`, `app.js`, `styles.css` — computed per request, `app.py:5366-5376`

**No separate static server** — same uvicorn process serves both API and frontend files.

**Frontend polling model** (no SSE, no WebSocket):
- Slow timer (`state.timer`): 4500ms — hits `/api/system-state`, `/api/runs`, `/api/cache/status` — `app.js:7760`
- Activity timer (`state.activityTimer`): 1200ms — hits `/api/events` — `app.js:7769`
- Fast timer (`state.fastTimer`): 1000ms — hits `/api/runs/{run_id}` only when `currentRunStatus == running` — `app.js:7891`
- One-shot guard `state._autoRefreshedForRunId` prevents duplicate rwtree refresh on `running→completed` transition — `app.js:6958`

---

## §4 HTTP/WS/SSE Endpoints

All endpoints registered inside `create_app()` via closures; no SSE or WebSocket. All polling.

| Method | Path | R/W | State Touched | Subprocess/Upstream | Concurrency Assumption |
|--------|------|-----|---------------|--------------------|-----------------------|
| GET | `/` or `/console/` | R | reads `frontend/index.html` | none | pure read |
| GET | `/api/health` | R | SQLite read (running runs), OperationCoordinator snapshot | none | safe |
| GET | `/api/system-state` | R | SQLite read, OperationCoordinator | none | safe |
| GET | `/api/machines` | R | reads `configs/machines.json`, scans `reports/` dirs | none | safe |
| GET | `/api/versions/current` | R | reads `configs/machines.json`, imports analyzer | none | safe |
| GET | `/api/machines/halls` | R | reads `configs/machine_halls.json` | none | safe |
| POST | `/api/machines/halls/refresh` | W | fetches from upstream server, writes `configs/machine_halls.json` | HTTP GET to upstream `/MachineConfigMd5`-adjacent | no mutex |
| GET | `/api/reports/stale-count` | R | scans `reports/` dirs + reads summary files | none | safe |
| GET | `/api/machines/summary` | R | `_build_machines_summary()` scans all summary.json | none | safe (mtime-cached) |
| POST | `/api/batch-run` | W | creates in-memory batch dict, spawns daemon thread + analyzer subprocesses | async md5 refresh thread + N analyzer `subprocess.Popen` | per-key lock (_busy_keys); OperationCoordinator NOT held for sampling |
| GET | `/api/disk-space` | R | `shutil.disk_usage` | none | safe |
| GET | `/api/machines/static` | R | reads `configs/machines_static.json` | none | safe (mtime-cached) |
| GET | `/api/rawdata/overview` | R | glob scan over `rawdata/` tree | none | safe |
| GET | `/api/machines/{machine}/cfg-availability` | R | filesystem check for `machineconfig/<u>Cfg.txt` | none | safe |
| GET | `/api/rawdata/{machine}` | R | `check_rawdata_status()` per mode, reads `_chunks.json` sidecar + `_index.json` | none | safe (read-only) |
| POST | `/api/rawdata/{machine}/mode/{mode}/lock` | W | writes `configs/rawdata_locks.json` via `os.replace` | none | no concurrent-write guard |
| DELETE | `/api/rawdata/{machine}/mode/{mode}/lock` | W | writes `configs/rawdata_locks.json` | none | no concurrent-write guard |
| DELETE | `/api/rawdata/{machine}/mode/{mode}/version` | W | unlinks chunk files, updates `_chunks.json`, updates `_index.json` | none | ops mutex held |
| GET | `/api/events` | R | SQLite reads + reads `progress/*.jsonl` files | none | safe |
| DELETE | `/api/rawdata/{machine}` | W | unlinks chunk files, updates sidecar/index | none | no mutex |
| DELETE | `/api/machines/{machine}/all-data` | W | unlinks rawdata + report dirs + SQLite rows | none | no mutex |
| GET | `/api/settings` | R | reads `state/console/settings.json` | none | safe |
| PUT | `/api/settings` | W | writes `state/console/settings.json` via `os.replace` | none | no concurrent-write guard |
| GET | `/api/classifier/{machine}` | R | reads `dev_reports/_classify/*.json` | none | safe |
| GET | `/api/paytables/{machine}/mode/{mode}/shape` | R | reads `configs/paytables/<machine>_mode<N>.json` | none | safe |
| GET | `/api/batch-run/{batch_id}` | R | in-memory `_batches` dict + SQLite reads + reads progress files | none | threading.Lock on `_batches` |
| GET | `/api/sampling-status` | R | in-memory `_batches` + `_busy_keys` | none | threading.Lock |
| POST | `/api/batch-run/{batch_id}/cancel` | W | sets `cancel_requested=True` + writes `.stop` file + calls taskkill | none | threading.Lock |
| GET | `/api/servers` | R | reads `configs/servers.json` | none | safe |
| POST | `/api/servers` | W | writes `configs/servers.json` | none | no guard |
| PUT | `/api/servers/{server_id}` | W | writes `configs/servers.json` | none | no guard |
| PUT | `/api/servers/{server_id}/set-default` | W | writes `configs/servers.json` | none | no guard |
| POST | `/api/servers/{server_id}/scan` | W | HTTP POST to upstream `/MachineTest/MachineConfigMd5`; writes `.probe/server_snapshots/<id>.json` | HTTP upstream | no mutex |
| GET | `/api/servers/{server_id}/snapshot` | R | reads `.probe/server_snapshots/<id>.json` | none | safe |
| GET | `/api/servers/compare` | R | reads snapshot files | none | safe |
| POST | `/api/servers/{server_id}/check-changes` | W | HTTP fetch + compares to snapshot | HTTP upstream | no mutex |
| DELETE | `/api/servers/{server_id}` | W | writes `configs/servers.json` | none | no guard |
| GET | `/api/models` | R | in-memory RuntimeModelConfig snapshot | none | threading.Lock |
| POST | `/api/model-config` | W | writes `state/console/model_config.json` | none | threading.Lock on RuntimeModelConfig |
| POST | `/api/runs` | W | inserts SQLite row, spawns analyzer subprocess | `subprocess.Popen(analyzer)` | ops mutex (OperationCoordinator) |
| POST | `/api/autotune` | W | runs `run_auto_tune()` synchronously | HTTP upstream calls in request thread | ops mutex |
| GET | `/api/autotune/progress` | R | in-memory `app.state.autotune_progress` | none | threading.Lock |
| GET | `/api/runs` | R | SQLite read | none | safe |
| GET | `/api/runs/{run_id}` | R | SQLite read + reads progress file | none | safe |
| GET | `/api/runs/{run_id}/progress` | R | SQLite read + reads `progress/<run_id>.jsonl` | none | safe |
| POST | `/api/runs/{run_id}/cancel` | W | writes `.stop` file + taskkill | none | threading.Lock on `_running` |
| POST | `/api/rawdata/{machine}/generate-report` | W | async=false: runs analyzer in request thread; async=true: daemon thread + pre-allocates run row | `subprocess.Popen(analyzer)` or in-process | ops mutex |
| POST | `/api/rawdata/batch-generate-report` | W | spawns `ProcessPoolExecutor` workers | `ProcessPoolExecutor(spawn)` | ops mutex (held for entire batch) |
| POST | `/api/rawdata/batch-generate-report/{batch_id}/cancel` | W | sets cancel flag in in-memory dict | none | threading.Lock |
| GET | `/api/rawdata/batch-generate-report/{batch_id}` | R | in-memory `_batches` dict | none | threading.Lock |
| DELETE | `/api/runs/{run_id}` | W | SQLite delete + unlinks progress/output files | none | ops mutex |
| GET | `/api/runs/{run_id}/report` | R | reads `player_impact_report.md` from disk | none | safe |
| GET | `/api/reports/{machine}/{mode}` | R | reads `reports/<m>/mode_<N>/index.json` + backfills from summary.json | none | safe |
| GET | `/api/reports/{machine}/{mode}/{version}` | R | reads summary.json from report version dir | none | safe |
| DELETE | `/api/reports/{machine}/{mode}/{version}` | W | rmtree on version dir + updates index.json + tags SQLite rows | none | ops mutex |
| POST | `/api/reports/import` | W | reads uploaded archive, writes to reports/ tree | none | no guard |
| POST | `/api/maintenance/prune-versions` | W | scans + deletes old version dirs per retention policy | none | ops mutex |
| POST | `/api/machines/refresh-md5` | W | HTTP fetch from upstream MachineConfigMd5 + writes `configs/machines.json` | HTTP upstream | no mutex |
| GET | `/api/report-validate/{machine}` | R | reads all summary.json files for machine | none | safe |
| POST | `/api/reports/cleanup` | W | scans all reports + deletes according to rules | none | ops mutex |
| GET | `/api/fleet/export-csv` | R | scans all summary.json files | none | safe |
| GET | `/api/library/distributions` | R | reads summary.json + aggregates | none | safe |
| GET | `/api/cache/status` | R | `folder_bytes()` scan over rawdata/ | none | safe |
| POST | `/api/cache/cleanup` | W | tiered delete over rawdata/, updates sidecar + index | none | ops mutex |
| POST | `/api/interpretations` | W | reads summary.json, calls AI provider or rule-based, writes SQLite | optional HTTP to AI provider | threading.Lock on RuntimeModelConfig |
| GET | `/api/interpretations/{run_id}` | R | SQLite read | none | safe |

**Virtual-console-only route** (port 8878 only):
| GET | `/api/virtual/paytable/{machine}` | R | reads `slot_designer/configs/<machine>_spec.json` | none | safe |

---

## §5 Process Spawn Model

### 5.1 Analyzer subprocess (sampling + from-cache generate-report)

`RunManager.start_run()` — `app.py:4739`

Spawns via `_default_popen_factory()` at `app.py:4603`:
```python
subprocess.Popen(cmd, cwd=str(ROOT), stdout=PIPE, stderr=PIPE, text=True)
```
Child process: `fresh_slotlab/player_impact_analyzer.py`

CLI arguments assembled at `app.py:4769-4863`:
- `--machine`, `--rtp-mode`, `--target-halfwidth-pp`, `--chunk-spin-times`, `--chunk-robot-count`, `--batch-concurrency`, `--max-chunks`, `--timeout`, `--bankruptcy-*`, `--output-dir`, `--run-id`, `--progress-file`, `--stop-flag-file`, `--chunk-cache-dir`
- Optional: `--endpoint-url`, `--from-cache`, `--resume-from-cache`, `--upstream-config-md5`, `--upstream-code-md5`, `--upstream-machine-name`, `--machine-config-file`

IPC: child writes JSONL events to `progress/<run_id>.jsonl`; parent (`_watch_run` daemon thread) waits on `proc.communicate()` then reads summary.json from disk.

Stop mechanism: parent writes `progress/<run_id>.stop` file; child polls between chunks. Fallback: `taskkill /PID /T /F` (Windows tree kill) — `app.py:4043-4054`.

PID stored in SQLite `runs.process_pid` — `app.py:4903`. On restart, `_recover_orphan_running_runs()` terminates stale PIDs — `app.py:4686-4725`.

### 5.2 BatchRunManager sampling orchestration

`BatchRunManager._run_batch()` — `app.py:3647`

Runs in a single daemon thread. Uses `threading.Semaphore(concurrency)` (default 3 from `BatchRunRequest.concurrency`) to limit parallel items. Each item calls `RunManager.start_run()` which spawns its own analyzer subprocess. Items can therefore have up to `concurrency` subprocesses running simultaneously.

Per-key lock (`_busy_keys`, `app.py:3198`) prevents two batches from concurrently sampling the same `(machine, mode)` — the second attempt is rejected with status=failed.

The entire sampling batch is NOT under the `OperationCoordinator` ops mutex — sampling and report generation can coexist (ops mutex only covers generate-report, delete-run, cache-cleanup, and autotune).

### 5.3 BatchGenerateManager (batch regen from cached chunks)

`BatchGenerateManager._run()` — `app.py:2968`

Runs in a daemon thread. Acquires `OperationCoordinator` ops mutex for entire duration.

Spawns a `ProcessPoolExecutor` with `mp_context=spawn` — `app.py:3047`:
```python
ctx = _mp.get_context("spawn")
with ProcessPoolExecutor(max_workers=SLOT_BATCH_GEN_WORKERS, mp_context=ctx,
                         initializer=_pool_worker_init, initargs=(str(ROOT),)) as pool:
```

Pool initializer `_pool_worker_init()` in `_batch_gen_worker.py:37`:
- Inserts `ROOT` into `sys.path`
- Imports `fresh_slotlab.player_impact_analyzer` once per worker process
- Caches reference in module-global `_analyzer_mod`

Worker `run_analyzer_job()` in `_batch_gen_worker.py:53`:
- Calls `_analyzer_mod.main()` in-process (not subprocess)
- Swaps `sys.argv` around the call
- Redirects stdout during call
- Then spawns `subprocess.run(infer_paytable.py)` and `subprocess.run(verify_machine_labels.py)` as subprocesses

### 5.4 Module-global propagation hazards

Cross-reference: `memory/feedback_subprocess_import_suicide_and_module_globals.md`

Documented hazards:

1. `_IN_USE_MODES` (set) at `app.py:2152`, guarded by `_IN_USE_LOCK` at `app.py:2153` — in-memory only; NOT propagated to subprocesses. Subprocess (analyzer) has no knowledge of which modes are in-use in the parent.

2. `_LOCK_CACHE` (dict) at `app.py:2178` — mtime-invalidated cache for `configs/rawdata_locks.json`; module-global (not instance-level). Two concurrent writers to `rawdata_locks.json` could cause stale cache state.

3. `RAWDATA_ROOT` at `app.py:518` — set once at module import from `SLOT_RAWDATA_ROOT` env. `BatchRunManager` has its own `self._rawdata_root` (injected at construction, `app.py:3186`) and uses `self._rawdata_root` correctly. But module-level `RAWDATA_ROOT` is used in `_IN_USE_MODES` path and as default in some standalone functions.

4. `virtual_app.py:201` — `app = build_virtual_app()` at module top level. The fix for the "suicide bug" is documented: `virtual_registry.py` separates the registry primitives from `virtual_app.py` so subprocess import of registry doesn't trigger `build_virtual_app()`. Source: `virtual_app.py:30-37` comment.

5. `_pool_worker_init()` captures `_project_root` as module-global in `_batch_gen_worker.py:34` to avoid `sys.path` reordering by `analyzer.main()` during the job — `_batch_gen_worker.py:33-34`.

### 5.5 Virtual console vs real console process model

Both call `create_app()`. The virtual console passes different paths for all stateful singletons (`state_dir`, `reports_root`, `rawdata_root`, `machines_config`, `analyzer_path`, `classify_dir`, `paytables_dir`) plus an `md5_refresh_override` callable.

The virtual console's `analyzer_path` points to `slot_designer/backend/virtual_analyzer.py` — a wrapper that delegates to the real analyzer after simulation. The real console's analyzer is `fresh_slotlab/player_impact_analyzer.py`.

Both consoles can run simultaneously (ports 8877 and 8878); their state directories, rawdata trees, and SQLite databases are fully disjoint.

---

## §6 State Persistence

### 6.1 SQLite database

**Path**: `state/console/console.db` (real) / `slot_designer/state/console.db` (virtual)
Source: `app.py:39-40`, `app.py:5309`

**Tables** (from `StateStore._init_db()`, `app.py:1441`):

`runs` table — one row per analyzer invocation:
```
run_id TEXT PK, machine TEXT, mode INTEGER, status TEXT,
model_id TEXT, created_at TEXT, started_at TEXT, finished_at TEXT,
target_halfwidth_pp REAL, chunk_spin_times INTEGER,
chunk_robot_count INTEGER, batch_concurrency INTEGER, max_chunks INTEGER,
timeout REAL, bankruptcy_session_spins INTEGER,
bankruptcy_bankroll_multipliers TEXT, report_version TEXT,
output_dir TEXT, progress_file TEXT, summary_file TEXT,
report_file TEXT, error_message TEXT,
-- added via ALTER TABLE (migration):
process_pid INTEGER, achieved_rtp_pct REAL, achieved_halfwidth_pp REAL,
quality_label TEXT, rawdata_config_md5 TEXT, rawdata_code_md5 TEXT,
analyzer_version TEXT, total_spins INTEGER
```

`interpretations` table:
```
id INTEGER PK AUTOINCREMENT, run_id TEXT, model_id TEXT,
source TEXT, warning TEXT, content TEXT, created_at TEXT
```

SQLite opened via `sqlite3.connect(db_path)` without WAL mode or busy timeout — each operation creates and closes a connection. No connection pool. Concurrent writes go through Python's GIL + OS file locking (SQLite's default serialized mode).

### 6.2 Rawdata directory structure

```
rawdata/                                       (RAWDATA_ROOT)
  _index.json                                  fleet-level cached index
  <machine>/mode_<N>/
    _chunks.json                               per-mode chunk sidecar
    chunk_0001.json                            data chunk (can be 70MB+)
    chunk_0002.json
    ...
```

`_index.json` schema (fleet-level, `rawdata_index.py`):
```json
{
  "_version": 1,
  "_updated_at": "ISO ts",
  "entries": {
    "M14|1": {
      "chunks": 4,
      "total_size_bytes": 17200000,
      "last_saved_at": "ISO ts",
      "config_md5": "4fcf...",
      "code_md5": "536f...",
      "mixed_md5": false
    }
  }
}
```

`_chunks.json` schema (per-mode sidecar, `chunk_index.py`):
```json
{
  "_version": 1,
  "_updated_at": "ISO ts",
  "chunks": {
    "chunk_0001.json": {
      "idx": 1, "cfg_md5": "...", "code_md5": "...",
      "spin_times": 1000, "robot_count": 8,
      "saved_at": "...", "size_bytes": 8500000
    }
  },
  "by_md5": {
    "cfg_a|code_x": ["chunk_0001.json", "chunk_0002.json"],
    "cfg_b|code_x": ["chunk_0003.json"]
  }
}
```

Cross-reference: `memory/reference_chunk_index_inverted_md5.md`

Dedup key today (single-user): `(machine, mode, config_md5, code_md5)` — new chunks land in `rawdata/<machine>/mode_<N>/` and are bucketed by md5 via `_chunks.json:by_md5`. The deploy requirement adds `config_id` as a fourth dedup axis (not yet implemented).

### 6.3 Reports directory structure

```
reports/
  <machine>/mode_<N>/
    index.json           list of all version entries for this (machine, mode)
    latest.json          most recent version entry
    versions/
      rv_<ts>_<hex>/
        player_impact_summary.json
        player_impact_report.md
        machine_config.json        (present only if local cfg override was used)
```

`index.json` is a JSON array; each element has: `report_version`, `run_id`, `created_at`, `summary_file`, `report_file`, `rtp_point_pct`, `achieved_rtp_pct`, `achieved_halfwidth_pp`, `total_spins`, `quality_label`.

### 6.4 State/lock files

| File | Purpose | Writer | Reader |
|------|---------|--------|--------|
| `state/console/console.db` | Run metadata + interpretations | SQLite via StateStore | SQLite via StateStore |
| `state/console/model_config.json` | AI provider + key | `RuntimeModelConfig._persist()` | `RuntimeModelConfig._load_from_disk()` |
| `state/console/settings.json` | `min_retention_spins` | `_save_settings()` via `os.replace` | `_load_settings()` |
| `state/console/progress/<run_id>.jsonl` | Analyzer progress events | analyzer subprocess (JSONL append) | parent via `read_progress_events()` |
| `state/console/progress/<run_id>.stop` | Graceful stop signal | `RunManager.cancel_run()` | analyzer subprocess (polls between chunks) |
| `configs/rawdata_locks.json` | Operator-set per-(machine,mode) locks | `_save_rawdata_locks()` via `os.replace` tmp | `_load_rawdata_locks()` (mtime-cached) |
| `configs/machines.json` | Fleet registry + md5 | `_do_refresh_machines_md5()` | all read paths |
| `configs/servers.json` | Server endpoints | server CRUD endpoints | `load_servers()`, sampling startup |
| `configs/machines_static.json` | Cached static attrs (category/md5) | `_merge_machine_static()`, `_bootstrap_static_attrs()` | `GET /api/machines/static` |
| `.probe/server_snapshots/<id>.json` | MachineConfigMd5 snapshots | `POST /api/servers/{id}/scan` | `GET /api/servers/{id}/snapshot` |

### 6.5 In-memory (process-local) state

| Name | Type | Purpose | Survives crash? |
|------|------|---------|-----------------|
| `OperationCoordinator._busy` | bool + threading.Lock | coarse single-operation gate | No — reset on restart |
| `BatchRunManager._batches` | dict + threading.Lock | active/recent batch state | No |
| `BatchRunManager._busy_keys` | set + threading.Lock | per-(machine,mode) sampling lock | No |
| `_IN_USE_MODES` | set + threading.Lock | prevents cleanup of in-flight rawdata | No |
| `_LOCK_CACHE` | dict (mtime-invalidated) | rawdata_locks.json cache | No |
| `_STATIC_ATTRS_CACHE` | dict (mtime-invalidated) | machines_static.json cache | No |
| `RunManager._running` | dict[run_id, ManagedRun] + threading.Lock | live subprocess handles | No — recovered via `_recover_orphan_running_runs()` on restart |
| `app.state.autotune_progress` | dict + threading.Lock | autotune snapshot | No |

### 6.6 Auth/session model

**None.** No user concept, no cookies, no tokens, no sessions, no user table.

The `CORSMiddleware` is configured with `allow_origins=["*"]` — `app.py:5356-5362`. Any origin can call any endpoint. No auth layer of any kind.

The server binds to `127.0.0.1` (loopback only), so network-layer "auth" is currently provided by the OS. The deploy target (internal Windows server, LAN access) will require the server to bind to `0.0.0.0` or a specific LAN interface — at which point any LAN client can reach any endpoint.

---

## §7 Upstream Fetch + Rate-Limit

### 7.1 Upstream endpoint

**Default**: `http://192.168.10.21:15060/MachineTest/MultiRobotTestSpinVariant`
Source: `fresh_slotlab/player_impact_analyzer.py:78`, `app.py:73`

The endpoint is a mutable module-global `ENDPOINT_URL` in `player_impact_analyzer.py:79` — overridden by `--endpoint-url` CLI arg passed from `RunManager.start_run()` at `app.py:4816`.

`configs/servers.json` stores named servers with endpoints. `GET /api/servers`, `PUT /api/servers/{id}` manage them. `_resolve_active_server_id()` at `app.py:1306` picks the active server; `get_server_endpoint()` at `app.py:1331` resolves its URL.

### 7.2 Upstream call path

Each analyzer subprocess makes calls independently:
1. `RunManager.start_run()` spawns analyzer subprocess
2. Inside subprocess: `player_impact_analyzer.py` calls `post_json_with_retry(payload, timeout)` at `player_impact_analyzer.py:2321`
3. `post_json_with_retry()` at `player_impact_analyzer.py:901` wraps `post_json()` at `player_impact_analyzer.py:312`
4. `post_json()` uses `urllib.request.urlopen()` — stdlib only, no HTTP client library

### 7.3 Retry policy

`post_json_with_retry()` — `player_impact_analyzer.py:901`:
- `max_attempts=3`, `initial_backoff_s=1.0`, `max_backoff_s=5.0`
- Retryable: HTTP 500/502/503/504, URLError, TimeoutError, socket.timeout, IncompleteRead, RemoteDisconnected, ConnectionError
- Non-retryable: HTTP 4xx, JSONDecodeError, parse failures → raise immediately

### 7.4 Rate-limit handling

**No explicit token bucket or rate limiter exists in the codebase.**

The original external upstream (`buffalo-debug.citrusjoy.com`) had per-IP throttling — documented in `memory/feedback_upstream_throttle_ceiling.md`. The current internal upstream (`192.168.10.21:15060`) reportedly has no per-IP rate limit per code comments at `player_impact_analyzer.py:345-346`.

The AIMD adaptive tuner in the analyzer (`player_impact_analyzer.py:378-395`) halves `batch_concurrency` on a network-class fully-failed batch and pauses for `CIRCUIT_PAUSE_S=3.0` seconds. This is an implicit rate-limit response but not a proactive token bucket.

Concurrent runs from multiple users would each spawn their own analyzer subprocess, each making independent upstream calls. The backend has no shared rate-limit bucket. Up to `batch_concurrency` (default 8) concurrent HTTP requests per running analyzer subprocess, times the number of concurrent batch-runs.

### 7.5 Dedup logic

Current dedup is per-analyzer-run via `--resume-from-cache` + `--upstream-config-md5` / `--upstream-code-md5` filtering:
- Analyzer resumes from `rawdata/<machine>/mode_<N>/` directory
- Reads `_chunks.json:by_md5` to find chunks matching current md5 pair — `chunk_index.py`
- Only merges matching-md5 chunks into running stats
- New chunks written with sequential index (max existing + 1)

No cross-run dedup: if two concurrent batch-runs target the same `(machine, mode)`, `BatchRunManager._busy_keys` rejects the second at the batch level (`app.py:3675`). But two separate `POST /api/batch-run` calls from different (hypothetical) users could each acquire different batch IDs and both run concurrently for the same machine+mode — the per-key lock only applies within `BatchRunManager._run_one()` — `app.py:3675-3682`.

### 7.6 md5 computation path

Cross-reference: `memory/feedback_md5_granularity_and_stamping.md`

`_get_machine_md5(machine, machines_config, mode=mode)` — `app.py:548`:
- Reads `configs/machines.json`
- Per-mode md5 from `modesMd5[str(mode)]` when present (virtual machines)
- Falls back to top-level `configSummaryMd5` / `codeSummaryMd5` (real machines)

Local cfg override md5 computed by `_derive_local_cfg_md5(content)` — `app.py:426`:
- `sha1(cfg_content.encode()).hexdigest()[:8]` prefixed `localcfg_`

---

## §8 Concurrency Primitives in Use Today

| Primitive | Location | Protects | Granularity |
|-----------|----------|----------|-------------|
| `threading.Lock` on `StateStore` | Not present — each method opens/closes its own `sqlite3.connect()` | SQLite writes serialize via OS + SQLite internal | Per-call (connection per operation) |
| `OperationCoordinator._lock` + `_busy` flag | `app.py:4000-4028` | `start_run`, `generate_report`, `delete_run`, `cache_cleanup`, `batch_generate_report`, `autotune` — coarse single-operation gate | Process-global (one op at a time) |
| `BatchRunManager._lock` | `app.py:3189` | `_batches` dict + `_busy_keys` set | In-memory batch state |
| `threading.Semaphore(concurrency)` in `_run_batch` | `app.py:3655` | max parallel items within one batch | Per-batch |
| `BatchRunManager._busy_keys` set | `app.py:3198`, guarded by `_lock` | prevents two concurrent batch-runs on same (machine, mode) | Per-(machine, mode) |
| `_IN_USE_LOCK` + `_IN_USE_MODES` set | `app.py:2153` | prevents auto-cleanup from deleting rawdata while analyzer runs | Per-(machine, mode), in-memory |
| `_sidecar_lock_for(mode_dir)` — per-path `threading.Lock` | `chunk_index.py:91-103` | `_chunks.json` sidecar writes within one process | Per `(mode_dir)` path |
| `RuntimeModelConfig._lock` | `app.py:213` | reads/writes to `model_config.json` and in-memory state | Per-instance |
| `app.state.autotune_progress_lock` | `app.py:5409` | in-memory autotune progress snapshot | Global to app instance |
| `threading.Lock` on `RunManager._running` | `app.py:4661` | `_running` dict of live `ManagedRun` handles | Per-instance |
| `os.replace(tmp, target)` atomic rename | `app.py:841`, `chunk_index.py`, `rawdata_index.py`, `_save_rawdata_locks()` | atomic file writes (JSON state files, sidecar) | Per-file |
| No lock on `configs/rawdata_locks.json` writes | `app.py:2213-2228` | `rawdata_locks.json` is read-modify-write with a tmp+replace but no process-level mutex — two concurrent writers race the read | None |
| No lock on `configs/servers.json` | server CRUD endpoints | concurrent PUT /api/servers writes race | None |
| No lock on `configs/machines.json` | `_do_refresh_machines_md5()` | concurrent md5 refresh + server config writes race | None |
| No cross-process lock on `_chunks.json` | `chunk_index.py` comment `app.py:89` | within one process: serialized by `_sidecar_lock_for`; across processes (two subprocesses writing same mode_dir): race | Per-thread within one process |

---

## §9 Dev Launch Command

**Real console (single-user, current baseline)**:

Prerequisites:
1. Python >= 3.10 on PATH
2. `python -m pip install -r src\web_console\requirements.txt` (fastapi, uvicorn, pydantic)

Launch:
```bat
start.bat
```
Or directly:
```powershell
python -m uvicorn src.web_console.backend.main:app --host 127.0.0.1 --port 8877 --log-level info
```
Working directory: repo root (required — `main.py` uses `Path(__file__).resolve().parents[3]` to find repo root; uvicorn launches with `cwd=str(ROOT)`).

**Relevant env vars for single-user dev** (all have defaults, none required):
- `SLOT_RAWDATA_ROOT` — point to a non-repo rawdata location (unset = `rawdata/` at repo root)
- `MODEL_PROVIDER` / `MODEL_API_KEY` — AI interpretation (optional)
- `SLOT_SKIP_AUTO_INFER=1` — skip post-hook inference scripts (faster during dev)

**Port guard**: the `.bat` wrapper checks that port 8877 is free before launching.

**No service / daemon wrapper** — uvicorn runs in the foreground terminal. Process dies when terminal is closed.

**Install (one-time)**:
```bat
install.bat
```
Source: `install.bat` — installs deps with Tsinghua mirror fallback.

---

## §10 Items Deferred to Taxonomist/Coupling-Auditor

The following observations are factual but require classification or hazard-level judgment (W2 scope):

1. `OperationCoordinator` is a **single process-global boolean flag** (`app.py:4000-4028`). `generate_report`, `delete_run`, `cache_cleanup`, and `batch_generate_report` all share it — they are mutually exclusive with each other AND with `start_run`. Under multi-user, two planners cannot simultaneously generate reports for different machines. The taxonomist should classify this as a concurrency bottleneck.

2. **Sampling (`POST /api/batch-run`) does NOT acquire the `OperationCoordinator` mutex**. Sampling and report generation can run simultaneously. Per-key `_busy_keys` only protects the same `(machine, mode)`. The coupling auditor should note whether `generate_report` + concurrent sampling on the same machine create write races on `_chunks.json`.

3. **`_chunks.json` sidecar lock is thread-only** (`chunk_index.py:91`). Comment says "cross-process writers would need a file lock." The `BatchGenerateManager` runs `ProcessPoolExecutor(spawn)` workers — each worker is a separate process. If two workers write the same `mode_dir`'s sidecar simultaneously, the per-thread lock provides no protection. The coupling auditor should confirm whether the batch-generate code prevents this (ops mutex holds the entire batch, so only one batch runs at a time — but a concurrent sampling run from another user could race the sidecar).

4. **`rawdata_locks.json`, `servers.json`, `machines.json`** have no write mutex — concurrent endpoint calls race on the tmp+replace pattern. The coupling auditor should flag these as write-contention points under multi-user.

5. **`_IN_USE_MODES` is in-memory only** — does not propagate to subprocess workers. If a `ProcessPoolExecutor` worker (batch-generate) runs on the same `(machine, mode)` that a sampling subprocess is writing to, `_IN_USE_MODES` in the parent process cannot stop the worker from entering that mode. The coupling auditor should map the exact call path.

6. **No cross-user dedup of concurrent same-cell fetches** — two planners triggering `POST /api/batch-run` for the same `(machine, mode)` simultaneously. The `_busy_keys` check at `app.py:3675` only prevents within-process duplicate batch items. If two separate batch submissions both have the same item, and the second submission's `_run_one` checks `_try_acquire_key` before the first has started its subprocess, both could pass. The taxonomist should classify the exact race window.

7. **`state/console/console.db` SQLite concurrency**: SQLite's default journal mode is DELETE (not WAL). With multiple readers/writers from the main uvicorn process (which is single-process, multi-thread), SQLite serializes via the same connection semantics. Under multi-user with high API call rate, SQLite busy timeouts are possible. The coupling auditor should check whether WAL mode is needed.

8. **`chart.js` loaded from CDN** (`index.html:8`). On an intranet server without internet access, this load will fail. The coupling auditor should flag this as a deployment dependency.

9. **`uvicorn` binds to `127.0.0.1`** (start_console.ps1:67). For multi-user LAN access, this must change to `0.0.0.0` or the machine's LAN IP. The taxonomist should confirm this is the only binding change needed (no proxy, no nginx).

10. **Process manager for uvicorn on Windows**: currently none — uvicorn dies if the terminal closes. The coupling auditor should note that an auto-restart wrapper (Windows service, NSSM, or equivalent using existing Windows tools) is needed for server deployment. The brief prohibits proposing new tools; W2 will specify minimum-delta approach.
