# 02 Deploy Surface Taxonomy

> Wave 1 — Deploy Review (2026-05-15)
> Agent: arch-taxonomist
> Mapper output: `01_deploy_pipeline_map.md` not yet produced; classification sourced from direct codebase discovery.
> Primary source file: `src/web_console/backend/app.py` (401 KB)
> Supporting files: `src/web_console/backend/_batch_gen_worker.py`, `fresh_slotlab/chunk_index.py`, `fresh_slotlab/rawdata_index.py`, `src/web_console/backend/main.py`

---

## §1 Methodology

**Discovery method.** Read `app.py` in six 300-line passes (lines 1–8928 total) plus full reads of `_batch_gen_worker.py`, `chunk_index.py`, `rawdata_index.py`, and `main.py`. Enumerated every `@app.get/post/put/delete` decorator, every `threading.Thread(target=...)` spawn, every `subprocess.run / Popen`, every `ProcessPoolExecutor` use, every file-path constant and read/write site.

**Dimensions applied.** Ten columns per surface (see brief §"Dimensions to classify"). For file-state surfaces the "persistence" column names the actual file path pattern found in code. Claims cite `app.py:LINE` or `chunk_index.py:LINE` where the fact is sourced.

**What is not yet available.** `01_deploy_pipeline_map.md` was not produced before this agent ran. The `_recover_orphan_running_runs` startup-recovery path and the `_auto_cleanup_for_space` disk-pressure loop are classified here but their blast-radius under multi-user concurrent execution is deferred to the coupling-auditor (§5).

**Gap surfaces.** Three new surfaces required by the brief (config upload, fleet refresh, delete-rawdata+tag-report-stale) do not exist today. They are classified under `new_required` surface type with the dimensions that would apply once built.

---

## §2 Master Taxonomy Table

Columns: Surface | Type | R/W | Scope | Persistence | Cross-restart durable | Triggers upstream | Concurrency safety (today) | Lock granularity needed | Cleanup-on-failure | Multi-user impact

**Abbreviation key**

- `http_ep` = http_endpoint
- `bg_task` = background_task
- `file_st` = file_state
- `new_req` = new_required
- `ro` = read_only, `wo` = write_only, `rw` = read_write
- `global` = fleet-wide, `per_run` = per run_id, `per_cell` = per (machine,mode,md5), `per_proc` = per_process
- `file(PATH)` = file-based persistence at that path pattern
- `CR` = cross-restart durable (yes/no)
- `TU` = triggers upstream
- `CS` = current concurrency safety
- `LG` = lock granularity needed
- `CF` = cleanup-on-failure

---

### 2.1 Static / Read-Only Endpoints

| Surface | Type | R/W | Scope | Persistence | CR | TU | CS | LG | CF | Multi-user impact |
|---|---|---|---|---|---|---|---|---|---|---|
| `GET /` | http_ep | ro | global | file(`frontend/index.html`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /console/` | http_ep | ro | global | file(`frontend/index.html`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/health` | http_ep | ro | global | db(`state/console/console.db`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/system-state` | http_ep | ro | global | db(`console.db`) + in_memory | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/machines` | http_ep | ro | global | file(`configs/machines.json`) + file(`reports/`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/versions/current` | http_ep | ro | global | file(`fresh_slotlab/player_impact_analyzer.py`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/machines/halls` | http_ep | ro | global | file(`configs/machine_halls.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/machines/summary` | http_ep | ro | global | file(`reports/*/mode_*/latest.json`) + in_memory cache | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/machines/static` | http_ep | ro | global | file(`configs/machines_static.json`) + in_memory cache | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/rawdata/overview` | http_ep | ro | global | file(`rawdata/`) + in_memory cache | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/rawdata/{machine}` | http_ep | ro | per_cell | file(`rawdata/<M>/mode_<N>/`) + file(`rawdata/_index.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/machines/{machine}/cfg-availability` | http_ep | ro | global | file(`machineconfig/<u>Cfg.txt`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/disk-space` | http_ep | ro | global | OS stat | no | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/sampling-status` | http_ep | ro | global | in_memory_only (BatchRunManager._batches) | no | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/batch-run/{batch_id}` | http_ep | ro | per_run | in_memory_only | no | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/runs` | http_ep | ro | global | db(`console.db`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/runs/{run_id}` | http_ep | ro | per_run | db(`console.db`) + file(`progress/*.jsonl`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/runs/{run_id}/progress` | http_ep | ro | per_run | file(`state/console/progress/<run_id>.jsonl`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/runs/{run_id}/report` | http_ep | ro | per_run | file(`reports/<M>/mode_<N>/versions/<rv>/player_impact_summary.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/reports/{machine}/{mode}` | http_ep | ro | per_cell | file(`reports/<M>/mode_<N>/index.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/reports/{machine}/{mode}/{version}` | http_ep | ro | per_cell | file(`reports/<M>/mode_<N>/versions/<v>/player_impact_summary.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/reports/stale-count` | http_ep | ro | global | db(`console.db`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/events` | http_ep | ro | global | db(`console.db`) + file(`progress/*.jsonl`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/settings` | http_ep | ro | global | file(`state/console/settings.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/models` | http_ep | ro | global | file(`state/console/model_config.json`) + env | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/classifier/{machine}` | http_ep | ro | per_cell | file(`dev_reports/_classify/*.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/paytables/{machine}/mode/{mode}/shape` | http_ep | ro | per_cell | file(`configs/paytables/<M>_mode<N>.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/servers` | http_ep | ro | global | file(`configs/servers.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/servers/{id}/snapshot` | http_ep | ro | global | file(`.probe/server_snapshots/<id>.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/servers/compare` | http_ep | ro | global | file(`.probe/server_snapshots/*.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/interpretations/{run_id}` | http_ep | ro | per_run | db(`console.db`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/autotune/progress` | http_ep | ro | per_proc | in_memory_only (`app.state.autotune_progress`) | no | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/library/distributions` | http_ep | ro | global | file(`reports/*/mode_*/latest.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/report-validate/{machine}` | http_ep | ro | per_cell | file(`reports/<M>/`) + file(`configs/machines.json`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `GET /api/fleet/export-csv` | http_ep | ro | global | file(`reports/`) | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |

---

### 2.2 Write / Mutating HTTP Endpoints

| Surface | Type | R/W | Scope | Persistence | CR | TU | CS | LG | CF | Multi-user impact |
|---|---|---|---|---|---|---|---|---|---|---|
| `POST /api/runs` | http_ep | rw | per_run | db(`console.db`) + file(`reports/<M>/mode_<N>/versions/`) + file(`progress/*.jsonl`) | yes | always | contended_at_cell | per_cell | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/batch-run` | http_ep | rw | per_run | db(`console.db`) + file(`rawdata/<M>/mode_<N>/`) | yes | always | contended_at_cell | per_cell | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/rawdata/{machine}/generate-report` (sync) | http_ep | rw | per_cell | db(`console.db`) + file(`reports/<M>/mode_<N>/versions/`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/rawdata/{machine}/generate-report` (async) | http_ep | rw | per_cell | db(`console.db`) + file(`reports/<M>/mode_<N>/versions/`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/rawdata/batch-generate-report` | http_ep | rw | global | db(`console.db`) + file(`reports/`) + file(`rawdata/_index.json`) + file(`configs/machines_static.json`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/rawdata/batch-generate-report/{id}/cancel` | http_ep | rw | per_run | in_memory_only | no | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `POST /api/machines/halls/refresh` | http_ep | rw | global | file(`configs/machine_halls.json`) + external snapshot | yes | always | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/machines/refresh-md5` | http_ep | rw | global | file(`configs/machines.json`) + file(`.probe/server_snapshots/<id>.json`) | yes | always | global_mutation_unsafe | global | atomic_rename | unsafe_today_needs_fix |
| `POST /api/runs/{run_id}/cancel` | http_ep | rw | per_run | db(`console.db`) + process signal | yes | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `POST /api/batch-run/{batch_id}/cancel` | http_ep | rw | per_run | in_memory_only | no | never | safe_for_N_callers | none | N/A | none_shared_readonly |
| `POST /api/autotune` | http_ep | rw | per_proc | in_memory_only + db(`console.db`) | yes | always | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/interpretations` | http_ep | rw | per_run | db(`console.db`) | yes | conditional | safe_for_N_callers | none | atomic_rename | safe_with_lock |
| `POST /api/model-config` | http_ep | rw | global | file(`state/console/model_config.json`) | yes | never | safe_with_lock | global | atomic_rename | safe_with_lock |
| `POST /api/servers` | http_ep | rw | global | file(`configs/servers.json`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `PUT /api/servers/{id}` | http_ep | rw | global | file(`configs/servers.json`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `PUT /api/servers/{id}/set-default` | http_ep | rw | global | file(`configs/servers.json`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `DELETE /api/servers/{id}` | http_ep | rw | global | file(`configs/servers.json`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/servers/{id}/scan` | http_ep | rw | global | file(`.probe/server_snapshots/<id>.json`) | yes | always | safe_for_N_callers | none | partial_safe | none_shared_readonly |
| `POST /api/servers/{id}/check-changes` | http_ep | rw | global | file(`.probe/server_snapshots/<id>.json`) | yes | always | safe_for_N_callers | none | partial_safe | none_shared_readonly |
| `PUT /api/settings` | http_ep | rw | global | file(`state/console/settings.json`) | yes | never | global_mutation_unsafe | global | atomic_rename | unsafe_today_needs_fix |
| `POST /api/rawdata/{machine}/mode/{mode}/lock` | http_ep | rw | per_cell | file(`configs/rawdata_locks.json`) | yes | never | global_mutation_unsafe | global | atomic_rename | unsafe_today_needs_fix |
| `DELETE /api/rawdata/{machine}/mode/{mode}/lock` | http_ep | rw | per_cell | file(`configs/rawdata_locks.json`) | yes | never | global_mutation_unsafe | global | atomic_rename | unsafe_today_needs_fix |
| `DELETE /api/rawdata/{machine}/mode/{mode}/version` | http_ep | rw | per_cell | file(`rawdata/<M>/mode_<N>/`) + file(`rawdata/_chunks.json`) + file(`rawdata/_index.json`) + db | yes | never | contended_at_cell | per_cell | partial_unsafe | unsafe_today_needs_fix |
| `DELETE /api/rawdata/{machine}` | http_ep | rw | per_cell | file(`rawdata/<M>/`) + sidecars | yes | never | contended_at_cell | per_cell | partial_unsafe | unsafe_today_needs_fix |
| `DELETE /api/machines/{machine}/all-data` | http_ep | rw | global | file(`rawdata/<M>/`) + file(`reports/<M>/`) + db | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `DELETE /api/runs/{run_id}` | http_ep | rw | per_run | db(`console.db`) + file(`reports/<M>/mode_<N>/versions/<rv>/`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `DELETE /api/reports/{machine}/{mode}/{version}` | http_ep | rw | per_cell | file(`reports/<M>/mode_<N>/versions/<v>/`) + file(`index.json`) + file(`latest.json`) + db | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/reports/import` | http_ep | rw | global | file(`reports/`) + db(`console.db`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `POST /api/reports/cleanup` | http_ep | rw | global | file(`reports/`) + db(`console.db`) | yes | never | global_mutation_unsafe | global | partial_safe | unsafe_today_needs_fix |
| `POST /api/maintenance/prune-versions` | http_ep | rw | global | file(`reports/`) + db(`console.db`) | yes | never | global_mutation_unsafe | global | partial_safe | unsafe_today_needs_fix |
| `POST /api/cache/cleanup` | http_ep | rw | global | file(`rawdata/`) + sidecars | yes | never | global_mutation_unsafe | global | partial_safe | unsafe_today_needs_fix |

---

### 2.3 Background Tasks (Threads / Processes)

| Surface | Type | R/W | Scope | Persistence | CR | TU | CS | LG | CF | Multi-user impact |
|---|---|---|---|---|---|---|---|---|---|---|
| `RunManager` sampling subprocess (`player_impact_analyzer.py` via `Popen`) | bg_task | rw | per_run | file(`rawdata/<M>/mode_<N>/chunk_*.json`) + file(`rawdata/_chunks.json`) + file(`rawdata/_index.json`) + file(`progress/<run_id>.jsonl`) | yes | always | contended_at_cell | per_cell | partial_unsafe | unsafe_today_needs_fix |
| `RunManager._watch_run` thread | bg_task | rw | per_run | db(`console.db`) + file(`reports/<M>/mode_<N>/`) | yes | never | safe_for_N_callers | none | partial_safe | none_shared_readonly |
| `_run_generate_report` in-process analyzer (daemon thread for async path) | bg_task | rw | per_cell | db(`console.db`) + file(`reports/<M>/mode_<N>/versions/`) + file(`configs/machines_static.json`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `BatchGenerateManager._run` thread | bg_task | rw | global | db(`console.db`) + file(`reports/`) + file(`rawdata/_index.json`) + file(`configs/machines_static.json`) | yes | never | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `ProcessPoolExecutor` workers (via `_batch_gen_worker.run_analyzer_job`) | bg_task | rw | per_cell | file(`rawdata/<M>/mode_<N>/`) + file(`reports/<M>/mode_<N>/versions/`) + file(`progress/<run_id>.jsonl`) | yes | never | safe_at_file_granularity | per_cell | partial_unsafe | safe_with_lock |
| Post-analyzer inference daemon thread (`_run_post_analyzer_inference`) | bg_task | rw | per_cell | file(`configs/paytables/<M>_mode<N>.json`) + file(`dev_reports/_classify/<M>_mode<N>.json`) + file(`reports/<M>/mode_<N>/versions/<rv>/_post_hook.json`) | yes | never | contended_at_cell | per_cell | partial_safe | unsafe_today_needs_fix |
| Disk-pressure auto-cleanup (`_auto_cleanup_for_space`, called from `BatchRunManager._run_item`) | bg_task | rw | global | file(`rawdata/<M>/mode_<N>/chunk_*.json`) + file(`rawdata/_chunks.json`) | yes | never | global_mutation_unsafe | global | partial_safe | unsafe_today_needs_fix |
| `RunManager._recover_orphan_running_runs` (startup) | bg_task | rw | global | db(`console.db`) | yes | never | safe_for_N_callers | none | partial_safe | none_shared_readonly |
| `StateStore.backfill_rtp_ci_from_summaries` (startup) | bg_task | rw | global | db(`console.db`) | yes | never | safe_for_N_callers | none | partial_safe | none_shared_readonly |
| `autotune` thread (`_autotune_bg`) | bg_task | rw | per_proc | in_memory_only (`app.state.autotune_progress`) + upstream calls | no | always | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |

---

### 2.4 File State Locations

| Surface | Type | R/W | Scope | Persistence | CR | TU | CS | LG | CF | Multi-user impact |
|---|---|---|---|---|---|---|---|---|---|---|
| `rawdata/<M>/mode_<N>/chunk_<NNNN>.json` | file_st | rw | per_cell | file | yes | N/A | safe_at_file_granularity | per_cell | partial_unsafe | unsafe_today_needs_fix |
| `rawdata/<M>/mode_<N>/_chunks.json` (sidecar) | file_st | rw | per_cell | file | yes | N/A | safe_at_file_granularity | per_cell | atomic_rename | unsafe_today_needs_fix |
| `rawdata/_index.json` (fleet-wide chunk index) | file_st | rw | global | file | yes | N/A | global_mutation_unsafe | global | atomic_rename | unsafe_today_needs_fix |
| `reports/<M>/mode_<N>/versions/<rv>/player_impact_summary.json` | file_st | rw | per_run | file | yes | N/A | safe_at_file_granularity | per_cell | partial_safe | safe_with_lock |
| `reports/<M>/mode_<N>/versions/<rv>/player_impact_report.md` | file_st | rw | per_run | file | yes | N/A | safe_at_file_granularity | per_cell | partial_safe | safe_with_lock |
| `reports/<M>/mode_<N>/index.json` | file_st | rw | per_cell | file | yes | N/A | contended_at_cell | per_cell | partial_unsafe | unsafe_today_needs_fix |
| `reports/<M>/mode_<N>/latest.json` | file_st | rw | per_cell | file | yes | N/A | contended_at_cell | per_cell | partial_unsafe | unsafe_today_needs_fix |
| `state/console/console.db` (SQLite) | file_st | rw | global | db | yes | N/A | safe_for_N_callers | none | atomic_rename | safe_with_lock |
| `state/console/progress/<run_id>.jsonl` | file_st | wo | per_run | file | yes | N/A | safe_at_file_granularity | per_run | partial_safe | safe_with_lock |
| `state/console/settings.json` | file_st | rw | global | file | yes | N/A | global_mutation_unsafe | global | atomic_rename | unsafe_today_needs_fix |
| `state/console/model_config.json` | file_st | rw | global | file | yes | N/A | safe_with_lock | global | atomic_rename | safe_with_lock |
| `configs/machines.json` | file_st | rw | global | file | yes | N/A | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `configs/machines_static.json` | file_st | rw | global | file | yes | N/A | global_mutation_unsafe | global | atomic_rename | unsafe_today_needs_fix |
| `configs/rawdata_locks.json` | file_st | rw | global | file | yes | N/A | global_mutation_unsafe | global | atomic_rename | unsafe_today_needs_fix |
| `configs/servers.json` | file_st | rw | global | file | yes | N/A | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `configs/machine_halls.json` | file_st | rw | global | file | yes | N/A | global_mutation_unsafe | global | partial_unsafe | unsafe_today_needs_fix |
| `configs/paytables/<M>_mode<N>.json` | file_st | rw | per_cell | file | yes | N/A | contended_at_cell | per_cell | partial_safe | unsafe_today_needs_fix |
| `dev_reports/_classify/<M>_mode<N>.json` | file_st | rw | per_cell | file | yes | N/A | contended_at_cell | per_cell | partial_safe | unsafe_today_needs_fix |
| `.probe/server_snapshots/<id>.json` | file_st | rw | global | file | yes | N/A | safe_at_file_granularity | global | partial_safe | safe_with_lock |
| `machineconfig/<u>Cfg.txt` | file_st | ro | global | file | yes | N/A | safe_for_N_callers | none | N/A | none_shared_readonly |
| `cache/chunks/<run_id>/` (transient scratch) | file_st | rw | per_run | file | no | N/A | safe_at_file_granularity | per_run | partial_safe | safe_with_lock |
| `state/console/progress/<run_id>.stop` (stop flag) | file_st | rw | per_run | file | yes | N/A | safe_at_file_granularity | per_run | partial_safe | safe_with_lock |

---

### 2.5 In-Memory State

| Surface | Type | R/W | Scope | Persistence | CR | TU | CS | LG | CF | Multi-user impact |
|---|---|---|---|---|---|---|---|---|---|---|
| `_IN_USE_MODES` set + `_IN_USE_LOCK` (app.py:2152) | file_st | rw | per_proc | in_memory_only | no | N/A | safe_for_N_callers | none | N/A | none_shared_readonly |
| `_LOCK_CACHE` dict (app.py:2178) | file_st | rw | per_proc | in_memory_only | no | N/A | safe_for_N_callers | none | N/A | none_shared_readonly |
| `_MACHINES_SUMMARY_CACHE` dict (app.py:1987) | file_st | rw | per_proc | in_memory_only | no | N/A | safe_for_N_callers | none | N/A | none_shared_readonly |
| `_RAWDATA_OVERVIEW_CACHE` dict (app.py:2030) | file_st | rw | per_proc | in_memory_only | no | N/A | safe_for_N_callers | none | N/A | none_shared_readonly |
| `_STATIC_ATTRS_CACHE` dict (app.py:2143) | file_st | rw | per_proc | in_memory_only | no | N/A | safe_for_N_callers | none | N/A | none_shared_readonly |
| `OperationCoordinator` (app.py:4000) — `ops` | file_st | rw | per_proc | in_memory_only | no | N/A | safe_for_N_callers | none | N/A | none_shared_readonly |
| `BatchRunManager._batches` dict (app.py:3190) | file_st | rw | per_proc | in_memory_only | no | N/A | safe_for_N_callers | none | N/A | none_shared_readonly |
| `BatchGenerateManager._batches` dict (app.py:2899) | file_st | rw | per_proc | in_memory_only | no | N/A | safe_for_N_callers | none | N/A | none_shared_readonly |
| `app.state.autotune_progress` (app.py:6674) | file_st | rw | per_proc | in_memory_only | no | N/A | global_mutation_unsafe | global | N/A | unsafe_today_needs_fix |

---

### 2.6 Subprocess / Upstream API Call Points

| Surface | Type | R/W | Scope | Persistence | CR | TU | CS | LG | CF | Multi-user impact |
|---|---|---|---|---|---|---|---|---|---|---|
| `RunManager.start_run` — `subprocess.Popen(analyzer)` (app.py:4769) | bg_task | rw | per_run | file(`rawdata/`) + file(`progress/`) | yes | always | contended_at_cell | per_cell | partial_unsafe | unsafe_today_needs_fix |
| `ProcessPoolExecutor` worker — `run_analyzer_job` calling `_analyzer_mod.main()` (_batch_gen_worker.py:111) | bg_task | rw | per_cell | file(`rawdata/`) + file(`reports/`) | yes | never | safe_at_file_granularity | per_cell | partial_unsafe | safe_with_lock |
| Worker post-hook — `subprocess.run(infer_paytable.py)` (_batch_gen_worker.py:207) | bg_task | rw | per_cell | file(`configs/paytables/`) | yes | never | contended_at_cell | per_cell | partial_safe | unsafe_today_needs_fix |
| Worker post-hook — `subprocess.run(verify_machine_labels.py)` (_batch_gen_worker.py:207) | bg_task | rw | per_cell | file(`dev_reports/_classify/`) | yes | never | contended_at_cell | per_cell | partial_safe | unsafe_today_needs_fix |
| `_fetch_machine_config_md5` — upstream HTTP POST /MachineTest/MachineConfigMd5 (app.py:1247) | bg_task | ro | global | external | no | always | safe_for_N_callers | none | N/A | none_shared_readonly |
| Upstream sampling — `/MultiRobotTestSpinVariant` via analyzer subprocess (app.py:73) | bg_task | ro | per_run | external | no | always | safe_for_N_callers | none | N/A | unsafe_today_needs_fix |
| Upstream halls — POST /MachineTest/MapMachineOrder (app.py:5613) | bg_task | ro | global | external | no | always | safe_for_N_callers | none | N/A | none_shared_readonly |
| `call_remote_interpreter` — external AI provider API (app.py:8893) | http_ep | ro | per_run | external | no | conditional | safe_for_N_callers | none | N/A | none_shared_readonly |

---

### 2.7 New Required Surfaces (Not Yet Built)

| Surface | Type | R/W | Scope | Persistence | CR | TU | CS | LG | CF | Multi-user impact |
|---|---|---|---|---|---|---|---|---|---|---|
| `POST /api/configs/upload` — config upload | new_req | rw | global | file(`configs/uploads/<config_id>.json`) + db | yes | never | unknown | per_cell | atomic_rename | new_feature_required |
| `GET /api/configs` — list uploaded configs | new_req | ro | global | file(`configs/uploads/`) + db | yes | never | safe_for_N_callers | none | N/A | new_feature_required |
| `GET /api/configs/{config_id}` — get specific config | new_req | ro | global | file(`configs/uploads/<config_id>.json`) | yes | never | safe_for_N_callers | none | N/A | new_feature_required |
| `POST /api/fleet/refresh` — trigger full-fleet sampling | new_req | rw | global | file(`state/console/fleet_refresh_queue.json`) + db | yes | always | unknown | global | partial_unsafe | new_feature_required |
| `GET /api/fleet/refresh` — poll fleet refresh progress | new_req | ro | global | file(`state/console/fleet_refresh_queue.json`) | yes | never | safe_for_N_callers | none | N/A | new_feature_required |
| `DELETE /api/fleet/refresh` — cancel fleet refresh | new_req | rw | global | file(`state/console/fleet_refresh_queue.json`) | yes | never | unknown | global | partial_safe | new_feature_required |
| Fleet refresh crash-recovery (background task) | new_req | rw | global | file(`state/console/fleet_refresh_queue.json`) | yes | always | unknown | global | partial_unsafe | new_feature_required |
| Report stale-tagging on rawdata delete | new_req | rw | per_cell | file(`reports/<M>/mode_<N>/versions/<rv>/player_impact_summary.json`) | yes | never | unknown | per_cell | atomic_rename | new_feature_required |
| Dedup key `(config_id, machine, mode, upstream_md5)` registry | new_req | rw | global | file or db | yes | never | unknown | per_cell | atomic_rename | new_feature_required |

---

## §3 Hazards by Multi-user Impact Category

### 3.1 Safe Today (none_shared_readonly)

These surfaces have no shared mutable state and are safe for N concurrent callers with no changes:

- All `GET` endpoints that read from stable files (`/api/machines`, `/api/reports/{m}/{mode}`, `/api/runs`, `/api/events`, etc.)
- Static file serving (`GET /`, `GET /console/`)
- Server snapshot reads (`GET /api/servers/{id}/snapshot`, `GET /api/servers/compare`)
- `machineconfig/<u>Cfg.txt` — operator-maintained, never written by the backend
- `_IN_USE_MODES`, `_LOCK_CACHE`, all summary caches — all guarded by `threading.Lock` within one process; safe for concurrent readers
- `OperationCoordinator` — thread-safe single-process mutex; `acquire/release` atomic under `threading.Lock`
- Upstream-read calls: `/MachineConfigMd5`, `/MapMachineOrder`, AI provider — read-only, no shared local state mutated by concurrent calls
- `POST /api/runs/{run_id}/cancel` / `POST /api/batch-run/{batch_id}/cancel` — signal only, idempotent
- Server scan (`POST /api/servers/{id}/scan`) and check-changes (`POST /api/servers/{id}/check-changes`) — write only to per-server snapshot file; file-granularity safe

---

### 3.2 Safe With Lock (specify granularity)

These are safe in single-user today because only one caller exists; under multi-user, the named lock granularity is sufficient to make them safe:

**SQLite `console.db` — per-DB connection serialization**

SQLite in WAL mode handles concurrent reads and serialized writes natively. The `StateStore._connect()` opens a new connection per call; SQLite's built-in write serialization makes DB reads/writes safe for N concurrent HTTP workers. No additional lock needed.

- `GET /api/runs`, `GET /api/runs/{run_id}`, `GET /api/reports/stale-count` — read-only, safe
- `POST /api/interpretations` — writes to `interpretations` table; SQLite serializes automatically; safe with SQLite WAL lock
- `POST /api/model-config` — writes `model_config.json` via `RuntimeModelConfig` which has its own `threading.Lock`; safe at global granularity

**ProcessPoolExecutor worker writes — per_cell safe**

Each `run_analyzer_job` worker runs in its own subprocess; multiple workers writing to *different* `(machine, mode)` cells do not contend. Multiple workers writing to the *same* cell would contend (this is guarded by `BatchRunManager._busy_keys` for the current batch, but not across concurrent batches — see §3.3).

Lock granularity needed: per_cell (already partially implemented via `_busy_keys` within one batch).

**Per-run file writes — per_run safe**

- `state/console/progress/<run_id>.jsonl` — one writer per run_id; no contention possible
- `reports/<M>/mode_<N>/versions/<rv>/player_impact_summary.json` — written exactly once per version directory; no contention
- `cache/chunks/<run_id>/` — per-run scratch; isolated

**`_post_hook.json` diagnostic** — written once after worker completes; per-cell, no lock needed beyond ensuring the run directory exists

---

### 3.3 Unsafe Today, Needs Fix

These surfaces have hazards that are invisible in single-user operation but break under concurrent multi-user load:

**1. `OperationCoordinator` is process-local, single-flag mutex**

Source: `app.py:4000-4028`. `OperationCoordinator` has one `_busy` boolean. Every mutating operation (`generate_report`, `batch_generate_report`, `delete_run`, `delete_report_version`, `cache_cleanup`, `refresh_machine_halls`) acquires this single flag. Under multi-user:
- User A starts `batch-generate-report` (holds `ops` for the entire batch duration)
- User B's `delete_rawdata` → `delete_machine_rawdata` → attempts `ops.acquire("delete_rawdata")` → gets HTTP 409
- All write operations globally queue behind one another regardless of whether they actually share any (machine, mode) data

The flag is `in_memory_only` with no cross-restart durability. A crash mid-operation leaves the flag effectively released (new process starts fresh). This is by design but means in-flight writes have no atomic rollback guarantee.

**2. `reports/<M>/mode_<N>/index.json` and `latest.json` writes are not atomic at the endpoint level**

Source: `app.py:7031-7033` (`_run_generate_report`), `app.py:7312-7314` (`_finalize_batch_gen_item`). Both paths do `write_json(index_path, ...)` + `write_json(latest_path, ...)` as two separate `path.write_text()` calls — not wrapped in `os.replace` from a temp file. Two concurrent generate-report calls for the *same* (machine, mode) cell would interleave their writes. Today the `OperationCoordinator` prevents this for single-machine generate, but batch-generate runs N items in parallel through the `ProcessPoolExecutor` and its finalize callbacks run in the parent thread sequentially per completed future — still effectively serialized via `as_completed`. However, two *batches* running simultaneously (if `ops` is ever extended to allow per-cell rather than global lock) would race on these files.

**3. `rawdata/_index.json` global index has no per-entry lock**

Source: `rawdata_index.py`. The index is a single JSON file at `rawdata_root/_index.json`. `update_entry` does read-modify-write + `os.replace` (atomic at filesystem level). But two concurrent writers for *different* (machine, mode) pairs still race on the same file: writer A reads `{M14|1, M15|1}`, writer B reads `{M14|1, M15|1}`, A writes `{M14|1, M15|1, M273|2}`, B writes `{M14|1, M15|1, M101|3}` — A's write is lost. Under batch-generate with N workers completing simultaneously, this is a realistic race.

**4. `rawdata/<M>/mode_<N>/_chunks.json` sidecar has per-mode threading lock but not cross-process lock**

Source: `chunk_index.py:81-111`. The `_SIDECAR_LOCKS` dict provides one `threading.Lock` per `(mode_dir)` within one process. The comment at line 90 explicitly states: *"cross-process writers would need a file lock, but this codebase doesn't have any."* Under batch-generate using `ProcessPoolExecutor` with `spawn` context, each worker process has its own `_SIDECAR_LOCKS` dict — no cross-process coordination. Two workers writing to the same `(machine, mode)` would race on `_chunks.json`. Today `_busy_keys` within one `BatchRunManager` prevents same-cell concurrent workers, but this is only enforced within one batch session, not across concurrent HTTP requests.

**5. `configs/machines.json` write-path is not atomic**

Source: `app.py:8216`. `_do_refresh_machines_md5` writes machines.json with `Path(mc).write_text(...)` — no temp+replace. A crash mid-write leaves a truncated file. Concurrent calls from two planners both triggering `POST /api/machines/refresh-md5` simultaneously race on the same file.

**6. `configs/servers.json` has no atomic write or lock**

Source: `app.py:510-515` (`save_servers`). `target.write_text(...)` — not atomic. Any concurrent server add/update/delete races.

**7. `configs/rawdata_locks.json` uses atomic rename but no lock across the read-modify-write**

Source: `app.py:2213-2228` (`_save_rawdata_locks`). The write uses `os.replace(tmp, path)` which is atomic at filesystem level. However, `_set_rawdata_lock` does read-load-modify-save without holding a mutex. Two concurrent lock/unlock calls for different (machine, mode) pairs race on the same read-modify-write cycle and one update can overwrite the other.

**8. `app.state.autotune_progress` written without lock**

Source: `app.py:6674`. `app.state.autotune_progress` is set/read in the autotune background thread and read in `GET /api/autotune/progress` without a lock. Under concurrent callers, reads may see partial state.

**9. `_auto_cleanup_for_space` runs without the `ops` mutex**

Source: `app.py:2455`, called from `BatchRunManager._run_item`. The disk-pressure cleanup path deletes chunks and updates sidecars without acquiring `OperationCoordinator`. If a second planner's generate-report is running simultaneously (if ops-mutex is later made per-cell), the auto-cleanup could unlink chunks the generate-report is actively reading.

**10. `POST /api/runs` — concurrent same-cell sampling not blocked**

Source: `app.py:3160-3342` (`BatchRunManager.start_batch`). `_busy_keys` only prevents the same (machine, mode) appearing twice within a single batch. Two separate `POST /api/batch-run` requests from different planners with the same machine in both lists will each acquire `_busy_keys` independently and both spawn analyzer subprocesses writing to `rawdata/<M>/mode_<N>/`. The `chunk_index.py` per-mode threading lock does not help here because each subprocess has its own lock dict.

**11. Upstream rate-limit shared bucket not enforced**

Source: `memory/feedback_upstream_throttle_ceiling.md`, `memory/reference_sampling_api.md`. The upstream endpoint has a per-IP rate ceiling (~1k outer/s sustained). Multiple concurrent analyzer subprocesses spawned by different planners share the same IP and collectively hit the ceiling without any coordination, causing throttling for all. No token bucket or concurrency governor exists today.

---

### 3.4 New Feature Required

These surfaces do not exist and must be built:

**`POST /api/configs/upload`**

Currently absent. Config upload as a first-class operation requires: (a) content-addressed storage keyed by `hash(content)` = `config_id`; (b) a registry mapping `config_id` → `{content, display_name, uploaded_at}`; (c) dedup invariant: same content → same `config_id`, return existing entry; (d) connection to rawdata buckets via the four-tuple `(config_id, machine, mode, upstream_md5)`. Today the closest analog is `machine_config: str` on `BatchRunItem` (app.py:1351) which passes inline JSON but has no persistent registry, no `config_id`, and no dedup. The `_derive_local_cfg_md5` helper (app.py:426) hashes content to `localcfg_<8hex>` — this is the seed of the config_id concept but it is ephemeral.

**`POST /api/fleet/refresh` + crash recovery**

Currently absent as a first-class endpoint. The nearest analog is `POST /api/rawdata/batch-generate-report` with `scope=all_with_rawdata` (app.py:7479-7520) but that generates reports from *existing* rawdata; it does not trigger new sampling. A fleet-wide sampling run (393 machines × N modes each) spanning hours/days requires: (a) a persisted queue file (`state/console/fleet_refresh_queue.json`) with per-(machine,mode) status; (b) startup recovery that resumes incomplete queue on process restart; (c) per-machine failure retry + final skip; (d) foreground-priority mechanism sharing the upstream rate-limit bucket with ad-hoc runs.

**Report stale-tagging on rawdata delete**

Currently absent. `delete_rawdata` (app.py:1040) and `DELETE /api/rawdata/{machine}` (app.py:6253) remove chunk files but do not update report files to signal `underlying_removed=true`. The brief (§5 constraint 6) requires reports to remain but become tagged. Today: if rawdata is deleted, the report still renders normally — there is no visual or metadata signal that its source data is gone. The `_update_report_index` pattern (app.py:7007-7033) writes `index.json` and `latest.json` but carries no `underlying_removed` field.

**Dedup key registry for `(config_id, machine, mode, upstream_md5)`**

Currently rawdata is keyed by `(machine, mode, cfg_md5, code_md5)` but `cfg_md5` is derived from the upstream global machine config, not from an operator-uploaded config. Adding `config_id` as a fourth axis means: (a) the rawdata directory path must encode `config_id` or a registry must map paths; (b) chunk sidecar must tag chunks with `config_id`; (c) cache dedup check must compare all four dimensions before deciding to reuse. Nothing in the current schema supports `config_id`.

---

## §4 Cross-References to Memory Files

The following memory files document existing concurrency behaviors that directly inform the hazard classifications above:

- `memory/feedback_subprocess_import_suicide_and_module_globals.md` — module-global leaks in subprocess paths; `_recover_orphan_running_runs` was fixed after this incident. Relevant to §3.3 item 10.
- `memory/reference_chunk_index_inverted_md5.md` — `_chunks.json` sidecar layout + `by_md5` index; confirms per-mode threading lock scope and cross-process limitation. Relevant to §3.3 item 4.
- `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md` — rawdata delete semantics; confirms that deletion should not cascade. Relevant to §3.4 stale-tagging gap.
- `memory/feedback_md5_granularity_and_stamping.md` — per-mode md5 and virtual machine delegate path md5. Relevant to configs/machines.json write hazard (§3.3 item 5).
- `memory/feedback_no_silent_swallow.md` — post-hook diagnostic requirement; confirms `_post_hook.json` write pattern is intentional. Relevant to §2.3 post-inference daemon.
- `memory/feedback_enumerate_safety_paths.md` — all unlink/rmtree paths must be guarded; confirmed that three delete paths exist today (`_auto_cleanup_for_space`, `delete_rawdata`, `check_rawdata_status` — last one now read-only). Relevant to §3.3 item 9.
- `memory/feedback_upstream_throttle_ceiling.md` — upstream per-IP rate limit; confirms no shared token bucket today. Relevant to §3.3 item 11.
- `memory/reference_sampling_api.md` — upstream endpoint + throughput regimes; 3.7k/s fresh, 0.7k/s limited. Relevant to §3.3 item 11.
- `memory/feedback_no_proactive_fetch.md` — dev side uses cache; confirms upstream calls happen only on explicit operator action or batch run.
- `memory/feedback_error_branch_resets_all_state.md` — UI state reset on error; relevant to `GET /api/runs/{run_id}` 404 path.
- `memory/feedback_fasttimer_overlap_needs_oneshot.md` — polling overlap protection; relevant to `GET /api/events` as the polled endpoint under concurrent users.

---

## §5 Items Deferred to Coupling-Auditor

The following require scenario walk-through or blast-radius quantification beyond a surface classification:

1. **Two concurrent `POST /api/batch-run` calls with overlapping (machine, mode)**: what exactly breaks in the `rawdata/_chunks.json` sidecar under cross-process concurrent writes? Does the `by_md5` inverted index get silently truncated or does `os.replace` atomicity prevent partial reads while allowing write-loss?

2. **`BatchGenerateManager._run` holds `ops` for entire batch**: if a batch has 393 items and takes hours, no other mutating operation can proceed. What is the dependency graph of operations that wait on `ops`? Does any health-critical operation (e.g. rawdata delete for disk reclamation) get permanently blocked?

3. **`_auto_cleanup_for_space` + concurrent generate-report**: is there any window where auto-cleanup can unlink a chunk that `_run_generate_report` has already opened but not yet fully read? The `_acquire_in_use` guard protects against cleanup-during-generate for the current cell, but auto-cleanup only checks `_get_in_use_snapshot()` which is an in-memory set. If two backend processes (e.g. prod + dev instance on same machine) share the rawdata directory, the in-use guard provides zero cross-process protection.

4. **`rawdata/_index.json` lost-update under N concurrent batch workers**: concrete frequency estimate given the observed batch sizes (393 machines) and ProcessPoolExecutor concurrency (default 4 workers). How many index entries would realistically be lost per fleet-wide batch run?

5. **Upstream rate-limit shared among N concurrent analyzer subprocesses**: given M planners each triggering a 1-machine sample at `chunk_robot_count=8, batch_concurrency=8` (64 concurrent upstream calls per planner), what is the effective total upstream request rate and when does throttling start degrading all planners' sampling?
