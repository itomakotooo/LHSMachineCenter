# P3 Implementation Brief: New Features (Config Upload + Fleet Refresh Queue + Report Stale Tagging)

> **Date**: 2026-05-17
> **Phase**: 3 of 4 (per `session_artifacts/_arch/deploy/07_deploy_decision.md`)
> **Design source**: `04_deploy_architecture_proposal_v2.md` §4.3 (config upload + 4-tuple dedup) + §4.4 (fleet refresh queue) + §4.6 (report stale tagging) + §6 Phase 3
> **Baseline**: commit `ff93557` (P2 done — CellLockRegistry + ConcurrencyLimiter ready for use)
> **Coordinator**: main session
> **Agent flow**: `impl-implementer` → `impl-tester` → `impl-verifier` → `impl-critic`
> **Commit boundary**: single atomic commit

---

## §1 Context

P3 is the **new features** phase. Adds 3 user-facing capabilities not present in single-user dev workflow:

1. **Config upload**: planner uploads a config JSON file → 4-tuple dedup `(config_id, machine, mode, upstream_md5)` for rawdata fetches
2. **Fleet refresh queue**: 393-machine on-demand batch with SQLite persistence + crash-recoverable resume + cell-busy timeout
3. **Report stale tagging**: rawdata delete tags reports `underlying_removed=true` instead of cascade-deleting

P2 produced the concurrency primitives (`CellLockRegistry` + `ConcurrencyLimiter`); P3 wires them into the new feature endpoints. The `_disk_monitor_loop` daemon already exists (P2 D11); P3 adds a parallel `FleetRefreshManager.run_queue` daemon for fleet refresh.

---

## §2 Scope — 12 deliverables (per 04_v2 §6 Phase 3)

### D1 — Config Upload Endpoints (3 endpoints)

```
POST /api/configs/upload    — accept JSON file; compute config_id = sha1(content); write to configs/uploaded_configs/<config_id>.json; update _registry.json
GET  /api/configs           — list all uploaded configs (config_id + display_name + uploaded_at)
GET  /api/configs/{config_id} — return single config metadata + content
```

Files / locations:
- New dir: `configs/uploaded_configs/` (gitignored)
- New file: `configs/uploaded_configs/_registry.json` — `[{config_id, display_name, uploaded_at}, ...]`
- All writes via `atomic_json_write` + per-file lock (re-uses P1-fix infra)
- Endpoints in `app.py` near other config-related endpoints (search for `machines.json` write paths)

Design ref: 04_v2 §4.3 "Config Object Design".

### D2 — Write-Config-First Ordering + `pending_batch_configs` Table (R8)

R8 from 04_v2 §4.3:

- New SQLite table:
  ```sql
  CREATE TABLE IF NOT EXISTS pending_batch_configs (
      batch_run_id TEXT NOT NULL,
      machine TEXT NOT NULL,
      mode INTEGER NOT NULL,
      config_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY (batch_run_id, machine, mode)
  );
  ```
- `BatchRunManager._run_one`: BEFORE calling `RunManager.start_run()`, write the `pending_batch_config` record. AFTER the analyzer subprocess completes (chunks written + sidecar updated), DELETE the record.
- On startup: `StateStore.__init__` scans `pending_batch_configs` and re-associates orphaned chunks with their `config_id` (assign `config_id` field on chunks whose sidecar `by_config_id` doesn't include them).

### D3 — `config_id` Sidecar Field + `by_config_id` Inverted Index + Lazy Migration (R10)

Per 04_v2 §4.3 + critique m3 fix:

- Extend `fresh_slotlab/chunk_index.py` `_chunks.json` schema:
  ```json
  {
    "chunks": {
      "chunk_0001.json": {..., "config_id": "null"}
    },
    "by_config_id": {
      "null": ["chunk_0001.json"],
      "<config_id_sha1>": ["chunk_0002.json"]
    }
  }
  ```
- `load_chunks_index()` detects sidecars missing `by_config_id`; runs migration in-place: assigns all existing chunks to `config_id="null"` bucket; backfills `config_id="null"` on each chunk entry; persists v3 layout. One-time migration per mode_dir on first read post-P3.

### D4 — `fleet_refresh_queue` + `fleet_refresh_items` SQLite Tables

Schema from 04_v2 §4.4 (already in brief there). Add via `StateStore._init_db`:

```sql
CREATE TABLE IF NOT EXISTS fleet_refresh_queue (
    queue_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL,
    total_items INTEGER NOT NULL,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    skipped_items INTEGER NOT NULL DEFAULT 0,
    config_source TEXT NOT NULL DEFAULT "server_default",
    server_id TEXT,
    cancelled_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS fleet_refresh_items (
    queue_id TEXT NOT NULL REFERENCES fleet_refresh_queue(queue_id),
    machine TEXT NOT NULL,
    mode INTEGER NOT NULL,
    queue_position INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT "pending",
    run_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (queue_id, machine, mode)
);
```

### D5 — `FleetRefreshManager` Class

New file: `src/web_console/backend/fleet_refresh.py`

Design from 04_v2 §4.4 `run_queue` pseudocode. Key parts:
- `start_queue(machines_to_refresh)` — creates new queue row; populates items with `queue_position` derived from `machines.json` order
- `run_queue(queue_id)` background daemon thread method:
  - Polls `_next_pending_item` (ORDER BY queue_position ASC for determinism)
  - For each: try `registry.try_acquire_cell(SAMPLING)` with 30-min cell-busy timeout (`SLOT_FLEET_CELL_BUSY_TIMEOUT_S`); on timeout → mark `status='skipped', reason='cell_busy_timeout'`
  - Acquire `ConcurrencyLimiter(priority="background", cancel_flag=lambda: _is_cancelled(queue_id))`
  - Run `_start_batch_run_item(machine, mode, queue_id)` (similar to existing batch path but per-item)
  - On completion: `_mark_item_completed`; on failure: increment `attempt_count`; if `attempt_count >= MAX_RETRIES`, mark skipped with reason; else re-queue as pending
- `cancel_queue(queue_id)` — sets cancellation flag; `_is_cancelled` polled by `run_queue` loop
- `MAX_RETRIES = 3` (configurable via env)

### D6 — `_recover_fleet_refresh()` in `StateStore.__init__` (with OperationalError guard)

After WAL pragma init, before main table CREATEs (so the recover can use existing tables OR fail gracefully on pre-P3 databases):

```python
try:
    row = conn.execute(
        "SELECT queue_id FROM fleet_refresh_queue WHERE status='running' LIMIT 1"
    ).fetchone()
    if row:
        queue_id = row[0]
        # Re-queue any in-flight items (they crashed mid-fetch)
        conn.execute(
            "UPDATE fleet_refresh_items SET status='pending', run_id=NULL "
            "WHERE queue_id=? AND status='running'",
            (queue_id,)
        )
        # Schedule the queue to resume on app startup (FleetRefreshManager.run_queue called via daemon)
        self._pending_resume_queue_id = queue_id  # picked up by create_app
except sqlite3.OperationalError:
    pass  # Pre-P3 database — tables don't exist yet, nothing to recover
```

### D7 — Fleet Refresh Endpoints (3 endpoints)

```
POST /api/fleet/refresh    — trigger new fleet refresh; check no existing 'running' queue; insert queue + items; spawn daemon
GET  /api/fleet/refresh    — poll current queue progress (total/completed/failed/skipped + per-item statuses if requested)
DELETE /api/fleet/refresh  — cancel current queue
```

Single-instance enforcement: POST returns 409 if any queue has `status='running'`.

### D8 — `ConcurrencyLimiter` Wired into `FleetRefreshManager.run_queue` (Background Priority)

P2 already wired `ConcurrencyLimiter.acquire("foreground", timeout=30)` into `BatchRunManager._run_one`. P3 adds the background complement: `FleetRefreshManager.run_queue` calls `acquire("background", cancel_flag=lambda: _is_cancelled(queue_id))`. Foreground reserve (2 slots) is honored — fleet refresh cannot block ad-hoc planner fetches.

### D9 — `_tag_reports_stale()` on All 4 Rawdata Delete Paths (INV-7 v2 + R6 + R7)

Per 04_v2 §4.6 + P2 D8 status — DELETING locks are in place; now add the stale-tagging side effect:

- `delete_rawdata(machine, mode)` at app.py:1040 (both force=False and force=True branches)
- `DELETE /api/rawdata/{machine}` at app.py:6253
- `DELETE /api/rawdata/{machine}/mode/{mode}` (if separate endpoint)
- `DELETE /api/rawdata/{machine}/mode/{mode}/version` at app.py:6043 — only when delete empties the mode (last chunk removed)

**Exempt** (INV-7 v2 carve-out per R6): `DELETE /api/machines/{machine}/all-data` — deletes both rawdata + reports entirely; reports do not survive to tag.

Implementation (04_v2 §4.6 pseudocode):
- `_tag_reports_stale(machine, mode, reports_root, store, state_dir)` helper:
  - Uses `atomic_json_read_modify_write` on `reports/<m>/mode_<n>/index.json` to set `underlying_removed=True` on each entry
  - Calls `store.mark_runs_underlying_removed(machine, mode)` to update SQLite `runs.underlying_removed` column
  - On failure: persist diagnostic to `state/console/stale_tag_error.json` per `feedback_no_silent_swallow.md`
  - **Raises** the underlying exception (does NOT swallow) — caller decides

### D10 — `underlying_removed` Column in `runs` Table

`StateStore._init_db`: `ALTER TABLE runs ADD COLUMN underlying_removed INTEGER NOT NULL DEFAULT 0`. Forward-only schema migration (existing rows default to 0).

`StateStore.mark_runs_underlying_removed(machine, mode)` method: `UPDATE runs SET underlying_removed=1 WHERE machine=? AND mode=?`.

`StateStore.list_runs` / report-list endpoints surface this in API response so frontend can display the "underlying rawdata removed" badge.

### D11 — Frontend Config Upload Panel + Fleet Refresh Progress Panel

`src/web_console/frontend/`:

- **Config upload panel**: form with file picker + display name input → POST /api/configs/upload → display in a config list
- **Fleet refresh panel**: 
  - "Run full refresh" button → POST /api/fleet/refresh
  - Progress display (total / completed / failed / skipped) — polled via setInterval
  - **Per `memory/feedback_fasttimer_overlap_needs_oneshot.md`**: use `_autoRefreshedForFleetRefreshId` one-shot guard so each completion fires side-effect once
  - Cancel button → DELETE /api/fleet/refresh

Reuse existing renderer helpers per `memory/feedback_no_parallel_panel_impl.md`. No new i18n keys without checking existing ones first.

### D12 — Virtual Console: `fleet_refresh_enabled=False`

Per 04_v2 §9 OQ-2:

- `create_app(fleet_refresh_enabled: bool = True, ...)` — add new parameter
- When `fleet_refresh_enabled=False`: don't construct `FleetRefreshManager`, don't spawn `run_queue` daemon, don't register `/api/fleet/refresh` endpoints
- `build_virtual_app()` (in `slot_designer/core/backend/virtual_app.py`) passes `fleet_refresh_enabled=False`

---

## §3 Out of scope for P3

- **P4**: deploy script, Task Scheduler, LAN bind (uvicorn `--host 0.0.0.0`). Separate phase.
- **`_MACHINES_SUMMARY_CACHE` / `_RAWDATA_OVERVIEW_CACHE` TOCTOU**: still deferred (different access pattern from P1-fix `_LOCK_CACHE`).
- **POSIX `fcntl_flock_failed` test**: P1-fix carryover; defer.
- **Test quality concerns from P2 critic** (e.g. success-path ConcurrencyLimiter release verification): defer.
- **Per-cell sidecar sharding for same-machine different-config concurrent SAMPLING**: INV-1 limitation documented; deferred to future arch review.

---

## §4 Constraints (must hold)

1. **Backward-compat**: P1 + P2 functionality unchanged. New tables / endpoints are additive. Existing chunks lazy-migrate to `config_id="null"` bucket transparently.
2. **No tech stack replacement**: same FastAPI + uvicorn + SQLite + ProcessPoolExecutor + threading.
3. **No silent failures**: every new `except: pass` requires explicit justification.
4. **Atomic SQLite migrations**: forward-only `ALTER TABLE ADD COLUMN`; safe to re-run on already-migrated DB.
5. **Stack-locked imports**: `threading`, `pathlib`, `json`, `sqlite3`, `hashlib`, `os` — no new dependencies.
6. **Memory feedback adherence**: see §5 below.

---

## §5 Memory feedback files to honor

- `memory/feedback_enumerate_safety_paths.md` — inject-bug verification for each new mutex / state machine
- `memory/feedback_no_silent_swallow.md` — failure paths persist diagnostic
- `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md` — `_tag_reports_stale` tags but does NOT delete reports; stale tagging is observability, not destruction
- `memory/feedback_no_parallel_panel_impl.md` — frontend reuses sibling renderers + existing helpers; no parallel impl
- `memory/feedback_fasttimer_overlap_needs_oneshot.md` — fleet refresh polling uses `_autoRefreshedForFleetRefreshId` one-shot guard
- `memory/feedback_chunk_index_inverted_md5.md` — sidecar pattern (already followed by chunk_index.py); extend with `by_config_id`
- `memory/feedback_subprocess_import_suicide_and_module_globals.md` — new modules (`fleet_refresh.py`) must have no import-time side effects
- `memory/feedback_respect_existing_codebase.md` — minimum-delta extensions; reuse atomic_json_write, CellLockRegistry, ConcurrencyLimiter
- `memory/feedback_adversarial_self_review.md` + `memory/feedback_impl_team_required.md` — full impl-* loop required

---

## §6 Test plan (impl-tester deliverables)

### Group P3-T1: Config upload + dedup tests

New file: `tests/backend/test_config_upload.py`

- `test_post_upload_creates_config_with_correct_hash_id` — upload content; assert config_id == sha1(content)
- `test_post_upload_dedups_identical_content` — upload same content twice with different display names; assert one config_id, two display names recorded (alias)
- `test_get_configs_lists_uploaded` — upload N configs; GET /api/configs returns N entries
- `test_get_config_by_id_returns_content` — upload; GET /api/configs/{config_id}; verify content + metadata
- `test_upload_invalid_json_returns_400` — upload non-JSON; assert 400
- `test_concurrent_upload_same_content_no_duplicate_files` — 5 threads upload same content; assert only one file in uploaded_configs/, registry has one entry

### Group P3-T2: 4-tuple dedup invariant tests

Extend `tests/backend/test_p2_cutover.py`:

- `test_attach_response_includes_config_id_in_match_logic` — batch run with config_id=X; second batch with config_id=X + same upstream_md5 → attach
- `test_different_config_id_same_machine_mode_serializes` — INV-1 from P2; documented limitation; same `(machine, mode)` with different `config_id` → second batch fails (registry SAMPLING singleton per cell)

### Group P3-T3: Fleet refresh queue + recovery tests

New file: `tests/backend/test_fleet_refresh.py`

- `test_post_fleet_refresh_creates_queue` — POST /api/fleet/refresh; assert queue_id in DB; items populated
- `test_get_fleet_refresh_returns_progress` — start queue; poll GET; verify total/completed/etc
- `test_delete_fleet_refresh_cancels_queue` — DELETE; assert status='cancelled'
- `test_only_one_running_queue_at_a_time` — POST while running → 409
- `test_recover_fleet_refresh_resumes_in_flight_items` — simulate crash: write queue with status='running' + some items 'running'; call _recover_fleet_refresh; assert in-flight items revert to 'pending'
- `test_recover_fleet_refresh_safe_on_pre_p3_db` — fresh DB without tables; recover should not crash (OperationalError swallow)
- `test_cell_busy_timeout_marks_skipped` — register SAMPLING on cell M14|1; trigger fleet refresh; assert M14|1 marked status='skipped', reason='cell_busy_timeout' after 30 min (mocked timeout)
- `test_fleet_refresh_yields_to_foreground` — ConcurrencyLimiter background priority; verify fleet refresh blocks when only foreground_reserve slots available
- `test_failed_item_retried_then_skipped` — mock per-item failure 3 times; assert MAX_RETRIES then skip
- `test_cancel_during_token_wait_returns_promptly` — fleet refresh in cancel_flag wait; trigger cancel; assert exits within 1s

### Group P3-T4: Report stale tagging tests

New file: `tests/backend/test_report_stale_tagging.py`

- `test_delete_rawdata_tags_reports_stale` — seed report at <m>/mode_<n>/index.json; delete rawdata; assert index.json entries have `underlying_removed=True`
- `test_delete_rawdata_marks_runs_in_db` — same; assert `runs.underlying_removed=1` for matching rows
- `test_per_version_delete_only_tags_when_empties_mode` — N>1 versions; delete one → not tagged; delete last → tagged
- `test_all_data_delete_does_not_tag` — DELETE /api/machines/{m}/all-data → reports DELETED (not tagged); INV-7 v2 carve-out
- `test_stale_tag_failure_persists_diagnostic` — monkey-patch atomic_json_read_modify_write to raise; assert stale_tag_error.json written
- `test_tag_reports_stale_raises_on_failure` — caller can detect; not silently swallowed

### Group P3-T5: Sidecar `by_config_id` migration tests

New file: `tests/backend/test_sidecar_by_config_id_migration.py`

- `test_load_chunks_index_migrates_existing_sidecar` — pre-P3 sidecar (no `by_config_id`); call load_chunks_index; assert `by_config_id={"null": [all_chunks]}` + each chunk has `config_id="null"`; sidecar persisted to disk in v3 layout
- `test_load_chunks_index_idempotent_on_v3_sidecar` — already-migrated; second load no-op
- `test_new_chunk_with_config_id_indexed_correctly` — write chunk with config_id="X"; assert `by_config_id["X"]` contains it

### Group P3-T6: Frontend tests (Playwright)

Per `memory/feedback_perf_claim_needs_e2e_event_stream.md` + brief T11. Smaller scope than P2 if time-constrained:

- `test_config_upload_panel_renders` — Playwright headless; load page; assert upload form visible
- `test_fleet_refresh_button_triggers_endpoint` — click button; assert POST /api/fleet/refresh fired; progress panel appears
- `test_fleet_refresh_one_shot_guard_on_completion` — simulate completion; assert side-effect fires once per tab + transition (per `feedback_fasttimer_overlap_needs_oneshot.md`)

### Group P3-T7: Inject-bug for each new mutex / state-machine

Per `feedback_enumerate_safety_paths.md`:

- **D2 pending_batch_configs**: remove the record-before-start line → recovery test should fail (orphan chunks not re-associated)
- **D3 sidecar migration**: remove the `by_config_id` migration step → existing sidecars stay v2; new chunk lookups via `by_config_id` empty
- **D6 _recover_fleet_refresh**: remove the `UPDATE ... SET status='pending'` → in-flight items stay running after restart; test fails
- **D9 _tag_reports_stale**: replace stale-tag call with pass → test_delete_rawdata_tags_reports_stale fails
- **D10 underlying_removed**: don't include column in API response → frontend "stale" badge would not render (or test for the field would fail)

---

## §7 Verification plan (impl-verifier deliverables)

1. **Full P3-related test sweep**: T1-T7 + P2 (must remain green) + P1-fix
2. **Full broader sweep**: target >= 1100 passed (1043 P2 baseline + ~60 P3 new tests = ~1100)
3. **Grep audits**:
   - `grep -rn "fleet_refresh_queue\|fleet_refresh_items\|pending_batch_configs" src/web_console/backend/` → presence confirmed
   - `grep -rn "_tag_reports_stale" src/web_console/backend/app.py` → calls present at 4 call sites
   - `grep -rn "underlying_removed" src/web_console/backend/` → column referenced
   - `grep -rn "by_config_id" fresh_slotlab/chunk_index.py` → migration code present
4. **Smoke**:
   - `create_app()` → 73 + N new routes (probably 79-80 routes)
   - `create_app(fleet_refresh_enabled=False)` → 73 + fewer routes (no fleet endpoints)
   - Module imports: `fleet_refresh.py`
5. **SQLite schema check**: open `console.db`; verify new tables + columns present
6. **Failure-injection walks**:
   - Crash mid-queue: simulate kill, restart, verify recovery
   - Cell busy stall: SAMPLING active 30+ min, verify item skipped not stuck
   - Cancel during cell-busy wait: verify prompt exit
   - all-data delete: verify reports actually deleted (not tagged)

---

## §8 Commit message draft (for impl-critic fact-check)

```
feat(phase3-deploy): config upload + fleet refresh queue + report stale tagging

Phase 3 of 4-phase deploy migration per 07_deploy_decision.md. New user-facing
features built on P2 concurrency primitives.

New modules:
- src/web_console/backend/fleet_refresh.py: FleetRefreshManager with
  run_queue daemon + cell-busy timeout + retry policy

SQLite schema additions (forward-only ALTER):
- fleet_refresh_queue + fleet_refresh_items tables
- pending_batch_configs table
- runs.underlying_removed column

New endpoints:
- POST/GET /api/configs/upload + /api/configs + /api/configs/{id}
- POST/GET/DELETE /api/fleet/refresh

Backend wiring:
- BatchRunManager: write-config-first ordering via pending_batch_configs
- chunk_index.py: by_config_id inverted index + lazy migration on first read
- delete_rawdata + 3 other delete paths: _tag_reports_stale
- all-data delete: exempt from INV-7 (deletes reports entirely)
- StateStore._recover_fleet_refresh: in-flight items re-queued on restart
- create_app(fleet_refresh_enabled=True): virtual console passes False
- ConcurrencyLimiter wired into FleetRefreshManager (background priority)

Frontend additions:
- Config upload panel
- Fleet refresh progress panel with _autoRefreshedForFleetRefreshId one-shot

## Verified happy path
- N tests green: P3 T1-T7 (~50-60 new) + P2 (66) + P1-fix (existing) +
  broader sweep (~1100 total). All stable across runs.
- Smoke: create_app() → N routes (P2 73 + new fleet/config endpoints)
- SQLite schema: new tables + column verified via PRAGMA
- Module imports: fleet_refresh OK
- Crash-recovery: kill mid-queue + restart → resume verified
- Lazy sidecar migration: existing _chunks.json → by_config_id="null" bucket

## Verified failure paths
- N inject-bug exercises (5+ for new mutex/state machine)
- Cell busy timeout: SAMPLING active 30 min → item marked skipped
- Cancel during cell-busy wait: prompt exit (<1s)
- Concurrent same-content config upload: dedup correct
- all-data delete: reports actually removed (INV-7 carve-out)
- Stale-tag failure: diagnostic persisted

## Not verified
- ...

## Tests added
- ...
```

---

## §9 Out-of-loop after this commit

P4: deploy script + Task Scheduler + LAN bind. Smaller scope. Optionally still impl-* loop or direct edit for small parts (scripts only, no production code).
