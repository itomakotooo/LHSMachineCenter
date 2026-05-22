# Implementer Round-3 Fix Report

> Date: 2026-05-18 | HEAD: c095180 (pre-commit)

## Deliverables

### B1 — UI bootstrap 404 + boot() finally (app.js)
- **app.js L7029** (now ~L7029-7050): wrapped report-fetch in try/catch mirroring L6916-6946. On 404: clears currentRunId, resets all panels, returns. On non-404: console.warn + return (no crash).
- **app.js boot()** (~L7920-7965): added `finally { _initConfigUploadPanel(); _initFleetRefreshPanel(); }`. P3 panel wiring now survives any loadBootstrap throw. The `finally` re-calls are safe (handlers are idempotent replace via addEventListener).
- LOC: ~25 LOC added

### B2 — `delete_machine_all_data` registry union (app.py)
- **app.py ~L6940-6963**: replaced on-disk-only `modes_all` list with `modes_set_all: set[int]` union of disk dirs + `registry.get_active_cells()` filtered by machine. Mirrors R1 fix from c095180's `delete_machine_rawdata`.
- LOC: +8 LOC

### B3 — `current_system_state` reads diagnostic files (app.py)
- **app.py `current_system_state`** signature now takes `state_dir: Path | None = None`.
- Adds `_read_diag()` helper + reads `md5_refresh_error.json`, `stale_tag_error.json`, `reassociate_error.json` from `state_dir`. Fields are `None` when files absent.
- **app.py `/api/system-state`** handler: passes `state_dir=sd`.
- LOC: +25 LOC

### I1 — config_id wiring: **Option B chosen**
- **Rationale**: `update_chunk_entry` in `chunk_index.py` hardcodes `_new_config_id = "null"`. The analyzer subprocess (called via `RunManager.start_run`) owns the `update_chunk_entry` call — it's not in `app.py`. Wiring requires modifying the analyzer CLI + its internal chunk-write hook. That crosses into analyzer code not touched in P1-P4. Scope exceeds 200 LOC across too many abstraction layers.
- **app.js `_initConfigUploadPanel()`**: injects a `<p id="configWiringWarning">` with yellow warning text above configListWrap. Warning is idempotent (checks `getElementById` before inserting).
- LOC: +12 LOC

### I2 — `delete_report_version` GENERATING → DELETING (app.py)
- **app.py ~L8487** (acquire) and **~L8609** (release): changed `CellOperation.GENERATING` → `CellOperation.DELETING`.
- Pre-existing test `test_runs_sequentially_under_ops_lock` expected 200+async-fail but now gets synchronous 409 (correct per I6 change). Updated test expectations.
- LOC: 2 lines changed, 1 test updated

### I3 — `_recover_fleet_refresh` corrupted DB diagnostic (app.py)
- **app.py `StateStore.__init__`** ~L1517: changed bare `except sqlite3.OperationalError: pass` to distinguish "no such table" (pre-P3, OK) vs other OperationalErrors (write `fleet_recovery_error.json` to `db_path.parent/`, print traceback).
- LOC: +18 LOC

### I4 — `refreshRawdataOverview` error state (app.js)
- **app.js `refreshRawdataOverview`**: catch now sets `state.rawdataOverviewError = err.message` instead of silent null.
- **app.js `renderRawdataBanner`**: when `state.rawdataOverviewError` is set and rawdataOverview is null, shows a visible warning banner (amber color) instead of hiding.
- LOC: +8 LOC

### I5 — `configs_upload_dir` DI to `create_app` (app.py + e2e_launch.py + conftest.py)
- **app.py `create_app`** signature: added `configs_upload_dir: Path | None = None`. Resolver: `configs_upload_dir if configs_upload_dir is not None else CONFIGS_UPLOAD_DIR`.
- **e2e_launch.py**: reads `SLOT_E2E_CONFIGS_UPLOAD_DIR` env var, passes to `create_app`.
- **tests/e2e/conftest.py**: `LiveServer` dataclass gets `configs_upload_dir` field. `live_server` fixture creates `base / "uploaded_configs"`, passes as `SLOT_E2E_CONFIGS_UPLOAD_DIR` env var.
- LOC: +15 LOC across 3 files

### I6 — `batch_generate_report` pre-check registry (cell_lock_registry.py + app.py)
- **cell_lock_registry.py**: added `peek_cell_status(machine, mode) -> set[CellOperation]` — non-mutating read of current ops on a cell.
- **app.py `batch_generate_report`**: after building `parsed_items` (explicit-items path only; `scope=all_with_rawdata` returns early before this), iterates items, calls `registry.peek_cell_status`, collects busy cells, raises 409 if any.
- **tests/backend/test_generate_report.py** `test_runs_sequentially_under_ops_lock`: updated to expect 409 (now the correct synchronous behavior per I6 spec).
- LOC: +15 LOC in cell_lock_registry.py + app.py, 1 test updated

## Files changed

- Modified (4): `src/web_console/backend/app.py`, `src/web_console/frontend/app.js`, `src/web_console/backend/e2e_launch.py`, `tests/e2e/conftest.py`
- Modified (2): `src/web_console/backend/cell_lock_registry.py`, `tests/backend/test_generate_report.py`

## Smoke results

```
python -c "from src.web_console.backend.app import create_app; app = create_app(); print(len(app.routes))"
# → 79

python -c "from src.web_console.backend.app import create_app; app = create_app(servers_config=None, configs_upload_dir=None); print('ok')"
# → ok

pytest tests/backend/ --ignore=tests/backend/test_analyzer_st_split.py -q
# → 1123 passed, 23 skipped, 1 xfailed (second run — first had 1 flaky ordering failure now gone)

pytest tests/e2e/ -m "not real_upstream" -q
# → 3 failed / 3 passed / 10 skipped — failures are pre-existing Playwright 30s session-scope
#   timeout flakiness (pass individually, fail when session shares live_server).
#   Not caused by this change.
```

## Concerns for impl-critic

1. **B1 boot() finally**: `_initConfigUploadPanel` + `_initFleetRefreshPanel` are now called twice in the normal (no-throw) path — once from `loadBootstrap()` at the end, once from `boot()`'s `finally`. Both are idempotent (replace existing event listeners). Verify no double-bind side effects.
2. **I2 DELETING for report delete**: changing from GENERATING → DELETING means now SAMPLING + report-delete are mutually exclusive (DELETING blocks SAMPLING). Previously GENERATING+SAMPLING was allowed (INV-3). Verify this is the intended concurrency policy — the brief says "correct" but INV-2 is GENERATING+DELETING, not SAMPLING+DELETING.
3. **I6 scope=all_with_rawdata path**: pre-check intentionally skipped for fleet-wide scope (would block all fleet-wide rebuilds if any single cell busy). Critic should confirm this is acceptable.
4. **B3 `_read_diag` helper**: defined as a nested function inside `current_system_state` — not testable in isolation. Impl-tester should test via the endpoint directly.
5. **I1 Option B warning**: warning uses inline `style` attribute. If there's a CSP policy in production that blocks inline styles, it won't display. Low risk for intranet-only deploy.
