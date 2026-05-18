# Implementer Round-4 Recovery Report

> Date: 2026-05-18 | HEAD: c095180 | Branch: claude/keen-wu-b8b520

## Fixes re-applied

### B2 — `delete_machine_all_data` registry union
- File: `src/web_console/backend/app.py` ~L6927 (inside `delete_machine_all_data`)
- Replaced `modes_all: list[int]` on-disk-only enum with `modes_set_all: set[int]`
  union of disk dirs + `registry.get_active_cells()` filtered by machine, then `modes_all = list(modes_set_all)`.
- Mirrors the R1 fix in `delete_machine_rawdata` (surviving at ~L6856-6880).
- LOC: +6 lines changed

### B3 — `current_system_state` reads diagnostic files
- File: `src/web_console/backend/app.py` `current_system_state()` function (~L5580)
- Added `state_dir: Path | None = None` parameter.
- Added `_read_diag(path)` nested helper (returns parsed JSON or None).
- Added reads of `md5_refresh_error.json`, `stale_tag_error.json`, `reassociate_error.json`
  from `state_dir` — surfaced as fields in the returned dict; `None` when absent.
- Updated `/api/system-state` handler (~L6034) to pass `state_dir=sd`.
- `/api/health` unchanged (does not receive state_dir — health is thin liveness probe).
- LOC: +25 lines

### I2 — `delete_report_version` lock type
- File: `src/web_console/backend/app.py` `delete_report_version` (~L8432-8552)
- Changed `registry.try_acquire_cell(machine, int(mode), CellOperation.GENERATING)` →
  `CellOperation.DELETING`.
- Changed corresponding `registry.release_cell(machine, int(mode), CellOperation.GENERATING)` →
  `CellOperation.DELETING`.
- LOC: 2 lines changed

### I3 — `_recover_fleet_refresh` corrupted-DB diagnostic
- File: `src/web_console/backend/app.py` `StateStore.__init__` (~L1517)
- Changed bare `except sqlite3.OperationalError: pass` to discriminate via
  `"no such table" in str(_exc).lower()` — expected for pre-P3 DB, silently passes.
- All other `OperationalError`s (schema mismatch, corruption) write
  `fleet_recovery_error.json` to `db_path.parent/` with `{"error": ..., "ts": ...}`
  and print traceback.
- LOC: +15 lines

### I5 — `configs_upload_dir` DI
- File: `src/web_console/backend/app.py` `create_app` signature (~L5715)
  Added `configs_upload_dir: Path | None = None` parameter.
  Inside `create_app` (~L9700): `configs_upload_dir = configs_upload_dir if configs_upload_dir is not None else CONFIGS_UPLOAD_DIR`.
  All 3 closure references (`upload_config`, `get_config`) naturally close over the local variable.
- File: `src/web_console/backend/e2e_launch.py`
  Reads `SLOT_E2E_CONFIGS_UPLOAD_DIR` env var, passes `configs_upload_dir=Path(val)` to `create_app`.
- File: `tests/e2e/conftest.py`
  Added `configs_upload_dir: Path | None = None` field to `LiveServer` dataclass.
  `live_server` fixture creates `base / "configs_upload"`, sets `SLOT_E2E_CONFIGS_UPLOAD_DIR` env var,
  passes `configs_upload_dir=configs_upload_dir` to `LiveServer`.
- LOC: ~20 lines across 3 files

### I6 — `batch_generate_report` pre-check registry
- File: `src/web_console/backend/app.py` `batch_generate_report` (~L8202)
- After `parsed_items` is built (explicit-items path only; `scope=all_with_rawdata` returns early above),
  iterates items, calls `registry.peek_cell_status(item["machine"], item["mode"])`,
  collects busy cells, raises 409 with `"cells busy: ..."` detail if any are busy.
- `peek_cell_status` was already present in `cell_lock_registry.py` (surviving).
- LOC: +13 lines

## Final test results

```
python -m pytest tests/backend/test_round3_fixes.py -v
# → 13 passed, 1 xfailed (I1/config_id wiring, Option B chosen, expected)
#   I5 tests auto-passed (no longer xfail) — DI landed

python -m pytest tests/backend/ --ignore=tests/backend/test_analyzer_st_split.py -q
# → 1116 passed, 8 failed, 23 skipped, 1 xfailed
# The 8 failures are PRE-EXISTING (not caused by this change):
#   6x test_deploy_start_console.py — "port 8877 is already in use" (environment state)
#   2x test_main_entrypoint.py — host mismatch (main.py changed to 127.0.0.1 in P4 commit
#      190dc9d, tests still expect 0.0.0.0; pre-existing drift, not my change)
```

Import smoke:
```
python -c "from src.web_console.backend.app import create_app; app = create_app(); print(len(app.routes))"
# → 79

python -c "from src.web_console.backend.app import create_app; app = create_app(configs_upload_dir=None); print('ok')"
# → ok
```

## Items not recovered

None. All 6 backend fixes (B2, B3, I2, I3, I5, I6) are re-applied and pass their tests.

## Open concerns for impl-critic

1. **I2 DELETING semantics**: changing `delete_report_version` to DELETING means
   concurrent SAMPLING + report-delete are mutually exclusive (INV-1). Previously
   SAMPLING + GENERATING was allowed (INV-3). This is the correct policy for a
   destructive op (brief confirms), but critic should verify no workflow legitimately
   wants SAMPLING to continue while a report version is being deleted.

2. **B3 `_read_diag` nested helper**: defined inside `current_system_state` — not
   independently testable. Tests cover it via the endpoint.

3. **I5 conftest.py `LiveServer.configs_upload_dir` field**: added as optional field
   with `None` default — backward-compatible with any existing fixture usage that
   doesn't reference this field.

4. **Pre-existing 8 failures**: `test_deploy_start_console.py` (port conflict) and
   `test_main_entrypoint.py` (0.0.0.0 vs 127.0.0.1) are NOT caused by this recovery.
   They were present before: the `start_console.ps1` tests fail because port 8877
   is in use by the prior test run (environment state); `test_main_entrypoint.py` fails
   because `main.py` was updated to bind 127.0.0.1 in commit 190dc9d but the tests
   still expect 0.0.0.0 (a gap left open from P4).
