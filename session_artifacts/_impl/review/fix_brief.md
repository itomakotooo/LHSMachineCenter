# Round-3 Fix Brief — pre-merge gap-fill

> **Date**: 2026-05-18
> **HEAD**: `c095180` (P4-E2E follow-up)
> **Sources**: `session_artifacts/_impl/review/{critic_round3.md, ui_audit.md}` + verifier output
> **Goal**: Close 3 BLOCKERs + 6 IMPORTANTs so user's local environment "works perfectly", then merge to `collab/dev`.

---

## §1 What this fixes

### BLOCKER (must close before merge)

**B1 — UI bootstrap chain crash → P3 panels silently disabled**
- `src/web_console/frontend/app.js` L7029 — `apiGet('/api/runs/<id>/report')` has NO try/catch
- 404 propagates → `loadBootstrap` throws → `boot()` catch → skips L7304-7305 (`_initConfigUploadPanel()` + `_initFleetRefreshPanel()`)
- Result: in any user environment with stale console.db (completed run + deleted report = common after cleanup), P3 "config upload" + "fleet refresh" buttons render but click handlers never bind. Silent failure.
- Fix: wrap L7029 in try/catch with 404 → `state.currentRunId=""; return` mirroring L6916-6946; ALSO restructure `boot()` so `_initConfigUploadPanel()` + `_initFleetRefreshPanel()` are in a `finally` block (defense in depth).

**B2 — `delete_machine_all_data` still has the R1-class race**
- `src/web_console/backend/app.py` lines 6940-6949 — enumerates `rd_root / machine` on disk only, does NOT call `registry.get_active_cells()`
- Same race that R1 fixed in `delete_machine_rawdata` (now lines 6859-6879): SAMPLING active + empty rawdata dir → DELETE returns 200 → corrupts in-progress run
- Fix: mirror the R1 fix pattern. Build `modes_set` from disk union with `registry.get_active_cells()` filtered by machine; iterate that set for the 409 guard.

**B3 — P1 commit claim vs reality: `md5_refresh_error` not in `/api/system-state`**
- `app.py:6377` docstring + P1 commit message both claim "Picked up by GET /api/system-state md5_refresh_error field (Phase 1 deliverable #11)"
- `current_system_state()` at lines 5580-5607 does NOT include this field. Diagnostic is write-only.
- Fix: add `md5_refresh_error` (and while at it, `stale_tag_error`, `reassociate_error` for completeness — P3 known gap) reads to `current_system_state`. Use `_md5_refresh_error_path(sd)` / similar helper. Surface `None` when file doesn't exist.

### IMPORTANT (should close)

**I1 — `_item_config_id = "null"` hardcoded (config_id wiring not connected)**
- `app.py:3935-3944` — explicit "TODO: wire config_id"
- Effect: user uploads config → chunks land in `"null"` bucket regardless of which config selected. UI shows "config upload" feature but it's inert for sampling.
- TWO options:
  - **Option A — true wiring** (preferred per user "work perfectly"): thread `config_id` from `BatchRunRequest.config_id` (new field) → `BatchRunItem` (per-item override) → `_run_one` → sampler subprocess via `--config-id` arg → `update_chunk_entry(config_id=...)` → sidecar `by_config_id` bucket. Scope: ~80-150 LOC across `app.py`, `fresh_slotlab/sampler.py`, `fresh_slotlab/chunk_index.py`.
  - **Option B — prominent UI warning** (fallback if wiring is too big): add a banner above "config upload" panel: "⚠️ 当前 config 选择对采样无效 — 改动只影响后续手动用 `--config-id` 的脚本"。配套:文档化为 follow-up.
- Implementer evaluates scope first. If Option A is <200 LOC and test coverage feasible, do A. If larger, do B + open follow-up ticket.

**I2 — `delete_report_version` uses GENERATING instead of DELETING**
- `app.py:8451` — `registry.try_acquire_cell(machine, mode, CellOperation.GENERATING)`
- Two destructive ops on same cell can race (one DELETING rawdata, one "GENERATING-as-proxy-delete" report).
- Fix: change to `CellOperation.DELETING`. Verify no test depends on the old GENERATING acquisition (`grep delete_report_version tests/`).

**I3 — `_recover_fleet_refresh` silent swallow on corrupted DB**
- `app.py:1519` — `except sqlite3.OperationalError: pass` catches "table doesn't exist" (intentional, pre-P3 DB) AND "DB corrupted" (silent, bad).
- Fix: distinguish via exception message OR introspect `sqlite_master` first. On corruption (anything other than `no such table: fleet_refresh_queue`), persist diagnostic to `state/console/fleet_recovery_error.json` per `memory/feedback_no_silent_swallow.md`.

**I4 — `refreshRawdataOverview` silent UI on fetch failure**
- `src/web_console/frontend/app.js` L1359-1362 — catch sets `state.rawdataOverview = null` and renders blank banner.
- Fix: capture last error in state (`state.rawdataOverviewError = err.message`), render error toast or inline warning in the banner area when set.

**I5 — `configs_upload_dir` not injectable via `create_app`**
- Same pattern as servers_config DI from round-2.
- Fix: add `configs_upload_dir: Path | None = None` to `create_app`; replace hardcoded `UPLOADED_CONFIGS_DIR` references with closure.
- conftest.py `live_server` updated to pass tmp_path/uploaded_configs.

**I6 — `batch_generate_report` doesn't pre-check registry**
- `app.py:8158-8220` — queues all items synchronously; 409 only surfaces async when worker picks up.
- Fix: in `start_batch_report` (or whatever the submit handler is), iterate items, call `registry.try_acquire_cell(machine, mode, GENERATING, dry_run=True)` (if such API exists; otherwise add a `is_cell_busy(machine, mode)` helper). For each busy cell, return 409 OR mark item status=`skipped_cell_busy` at submit time. Mirror P2 INV-2 semantics.
- If `try_acquire_cell` doesn't have a peek mode, add one (`registry.peek_cell_status(machine, mode) -> set[CellOperation]`).

### NICE-TO-HAVE (deferred; document in commit message)

Per critic + verifier reports, these are tracked as follow-up:
- A2 partial: pending_batch_configs orphan rows on crash (recovery already exists)
- B1 corollary: `pytest.mark.real_upstream` tests SKIP in CI (no CI intranet) — by design
- B2 (smoke test): `test_smoke_passes_against_live_create_app` permanent skip
- E2: `refreshAll` swallows render errors (defense-in-depth, low impact)
- E3-E5: console.error-only paths
- G1: stop_reason 60-char truncation in UI

---

## §2 Test plan (impl-tester deliverables)

### T-B1 — UI bootstrap test (Playwright)

New file: `tests/e2e/test_p4_bootstrap_stale_run.py`

```python
def test_bootstrap_with_stale_run_still_initializes_p3_panels(live_server, page):
    # Setup: insert a fake "completed" run into console.db, point at non-existent
    # report file (simulates report cleanup leaving stale state.currentRunId).
    # Boot the page.
    # Assert: config upload click + fleet refresh click both fire requests
    # (handlers bound). Pre-fix this would silently fail.
```

Inject-bug: comment out the new try/catch around L7029 → test goes RED (handlers not bound).

### T-B2 — `delete_machine_all_data` R1 race regression guard

New test in `tests/e2e/test_p4_real_business_flow.py` OR `tests/backend/test_delete_endpoints.py`:

```python
def test_delete_all_data_returns_409_with_empty_dir_active_sampling(live_server):
    # Acquire SAMPLING on (M14, 1) via direct registry call.
    # Verify rawdata/M14 does NOT exist on disk.
    # DELETE /api/machines/M14/all-data.
    # Assert: 409.
    # Inject-bug recipe: remove registry.get_active_cells() loop in delete_machine_all_data → test goes RED with 200.
```

### T-B3 — `/api/system-state` md5_refresh_error field

New test in `tests/backend/test_system_state.py`:

```python
def test_system_state_surfaces_md5_refresh_error(tmp_path, monkeypatch):
    # Write a fake md5_refresh_error.json to state/console/.
    # GET /api/system-state.
    # Assert: response.md5_refresh_error is the parsed JSON content.
```

Plus `test_system_state_omits_md5_refresh_error_when_file_absent` (clean state).

### T-I1 (if Option A) — config_id wiring end-to-end

```python
def test_batch_run_with_config_id_lands_chunks_in_config_bucket(live_server):
    # Upload a config → get config_id.
    # POST /api/batch-run with items=[{machine: M14, mode: 1}], config_id=<that>.
    # After completion, sidecar `by_config_id[<that_id>]` includes the new chunk.
    # `by_config_id["null"]` does NOT include it.
```

If Option B (UI warning only): a frontend smoke test that asserts the warning banner is visible above the config upload panel.

### T-I2..I6 — one regression guard each per spec above.

### Inject-bug for each new mutex / state-machine change

Per `memory/feedback_enumerate_safety_paths.md`:
- T-B1: comment out new try/catch → P3 panel test RED
- T-B2: remove registry loop → DELETE returns 200 RED
- T-B3: comment out md5_refresh_error read in current_system_state → field missing → RED
- T-I1 (Option A): hardcode `_item_config_id = "null"` → chunk lands in null bucket → RED
- T-I2: change DELETING back to GENERATING → concurrent destructive race test passes when it shouldn't → RED
- T-I3: re-raise OperationalError to bypass diagnostic write → diagnostic missing → RED
- T-I4: revert error toast → test asserting visible error → RED
- T-I5: revert configs_upload_dir DI → test that `configs/uploaded_configs/` is not mutated → mutated → RED
- T-I6: revert pre-check → batch-generate-report with busy cell returns 200 → expected 409 → RED

---

## §3 Constraints

- **No production code edits beyond the 9 fixes listed**. If a fix surfaces another bug, document in critic notes, don't expand scope.
- **Schema-forward-only**: any new `current_system_state` field is optional; clients that don't read it ignore. No new DB tables required.
- **Memory feedback adherence**:
  - `feedback_no_silent_swallow.md` — I3 fix directly addresses
  - `feedback_no_parallel_panel_impl.md` — I4 UI toast reuses existing toast renderer
  - `feedback_enumerate_safety_paths.md` — every fix above gets inject-bug RED→GREEN
  - `feedback_impl_team_required.md` — full team for this round
- **All fix code paths cleanup**: tests must leave `git status --porcelain` matching baseline + new test files only.

---

## §4 Files map

```
src/web_console/backend/app.py       — B2, B3, I1 (if Option A), I2, I3, I5, I6
src/web_console/frontend/app.js      — B1, I4
fresh_slotlab/sampler.py             — I1 if Option A
fresh_slotlab/chunk_index.py         — I1 if Option A
tests/e2e/test_p4_bootstrap_stale_run.py    — new for B1
tests/e2e/test_p4_real_business_flow.py     — T-B2 added test
tests/backend/test_system_state.py          — new for B3 (or extend existing)
tests/backend/test_batch_run_config_id_wiring.py — new for I1 Option A
tests/backend/test_delete_report_version_lock.py — new or extend for I2
tests/backend/test_fleet_refresh_recovery.py — new for I3
tests/e2e/conftest.py                       — I5 DI extension
tests/backend/test_batch_generate_report_precheck.py — new for I6
session_artifacts/_impl/review/{implementer,tester,verifier,critic}_round3_fix.md
```

---

## §5 Commit boundary

Single commit at the end of this loop:
`fix(p4-merge-prep): UI bootstrap chain + all-data DELETE 409 + system-state diagnostic + 6 IMPORTANTs`

Coordinator commits after impl-critic APPROVE.

Commit message MUST acknowledge:
1. B3 closes the P1 commit's false "md5_refresh_error surfaced" claim
2. B2 closes the gap left by the R1 fix in `c095180` (sibling endpoint missed)
3. If I1 went Option B (warning only), explicit follow-up issue noted
