# Round-3 Fix Tester Report

**Date**: 2026-05-18
**Tester**: impl-tester
**Tests written**: 9 behavioral tests + 1 xfail placeholder + inject-bug exercises for all 9

---

## 1. Test count per group

| Fix | Test(s) | File |
|-----|---------|------|
| T-B1 | `TestBootstrapStaleRun::test_bootstrap_with_stale_run_still_initializes_p3_panels` + `TestRawdataOverviewErrorToast::test_rawdata_overview_error_shows_visible_feedback` + baseline | `tests/e2e/test_p4_bootstrap_stale_run.py` |
| T-B2 | `test_delete_all_data_returns_409_active_sampling` + `test_delete_all_data_registry_check_blocks_even_without_running_rows` + baseline | `tests/backend/test_round3_fixes.py` |
| T-B3 | `test_system_state_surfaces_md5_refresh_error_when_file_exists` + `test_system_state_returns_null_md5_refresh_error_when_absent` + `test_system_state_surfaces_stale_tag_error_when_file_exists` | `tests/backend/test_round3_fixes.py` |
| T-I1 | `test_batch_run_config_id_routes_chunk_to_correct_bucket` (xfail — Option B chosen or wiring pending) | `tests/backend/test_round3_fixes.py` |
| T-I2 | `test_delete_report_version_blocked_when_sampling_active` | `tests/backend/test_round3_fixes.py` |
| T-I3 | `test_recover_fleet_refresh_writes_diagnostic_on_schema_mismatch` + `test_recover_fleet_refresh_no_diagnostic_for_missing_table` | `tests/backend/test_round3_fixes.py` |
| T-I4 | `test_rawdata_overview_error_shows_visible_feedback` + `test_rawdata_overview_success_shows_normal_banner` | `tests/e2e/test_p4_bootstrap_stale_run.py` |
| T-I5 | `test_configs_upload_dir_di_routes_to_tmp_not_real` + `test_configs_upload_two_uploads_both_isolated` | `tests/backend/test_round3_fixes.py` |
| T-I6 | `test_batch_generate_report_returns_409_when_cell_busy` + `test_batch_generate_report_succeeds_when_no_cell_busy` | `tests/backend/test_round3_fixes.py` |

**Total new tests**: 16 (13 backend + 3 e2e Playwright) + 1 xfail

---

## 2. Inject-bug results (RED → GREEN for each)

| Fix | Bug injected at | Test(s) RED | GREEN after revert |
|-----|----------------|-------------|-------------------|
| T-B1 | `app.js:7037` — removed try/catch around report fetch; `app.js:7944` — removed `finally` block from `boot()` | `test_bootstrap_with_stale_run_still_initializes_p3_panels` FAILED: `/api/configs` never fetched — P3 panel init skipped after 404 crash | PASSED |
| T-B2 | `app.py:7011-7014` — commented out `registry.get_active_cells()` loop in `delete_machine_all_data` | `test_delete_all_data_registry_check_blocks_even_without_running_rows` FAILED: DELETE returned 200 (`rawdata_absent + run.status='completed' in DB, only registry check blocked`) | PASSED |
| T-B3 | `app.py:5655` — removed `"md5_refresh_error": md5_err` from `current_system_state()` return | `test_system_state_surfaces_md5_refresh_error_when_file_exists` + `test_system_state_returns_null_md5_refresh_error_when_absent` FAILED: key missing from response | PASSED (3 tests) |
| T-I1 | N/A — xfail (implementer chose not to wire; Option B follows) | — | — |
| T-I2 | `app.py:8504` — changed `CellOperation.DELETING` back to `CellOperation.GENERATING` in `delete_report_version` | `test_delete_report_version_blocked_when_sampling_active` FAILED: DELETE returned 200 (SAMPLING+GENERATING allowed by INV-3) | PASSED |
| T-I3 | `app.py:1519` — replaced discriminating except with `pass` (swallow all OperationalErrors) | `test_recover_fleet_refresh_writes_diagnostic_on_schema_mismatch` FAILED: fleet_recovery_error.json absent | PASSED |
| T-I4 | `app.js:1362` — removed `state.rawdataOverviewError = String(err?.message...)` from catch | `test_rawdata_overview_error_shows_visible_feedback` FAILED: no visible error text in page | PASSED |
| T-I5 | `app.py:9808` — changed `configs_upload_dir if ... else CONFIGS_UPLOAD_DIR` to always `CONFIGS_UPLOAD_DIR` | `test_configs_upload_dir_di_routes_to_tmp_not_real` + `test_configs_upload_two_uploads_both_isolated` FAILED: files not in injected tmp dir | PASSED (2 tests) |
| T-I6 | `app.py:8287-8306` — removed pre-check registry loop from `batch_generate_report` | `test_batch_generate_report_returns_409_when_cell_busy` FAILED: returned 200 instead of 409 | PASSED |

---

## 3. Final sweep: backend + e2e (not real_upstream)

```
python -m pytest tests/backend/ -m "not real_upstream" -q
```
Result: **1132 passed, 24 skipped, 1 xfailed, 1 failed** (1.8 min)

The 1 failure is pre-existing: `test_zero_win_but_fired_pid_retained_in_split` — missing fixture file `rawdata/M31/mode_1/chunk_0001.json`. Unrelated to round-3 fixes. Was failing before this session.

---

## 4. Tests skipped + why

- **T-I1 (`test_batch_run_config_id_routes_chunk_to_correct_bucket`)** — marked `@pytest.mark.xfail` (strict=False). Implementer chose Option B (UI warning) or wiring is pending. If Option A lands, xfail will auto-pass. If Option B, replace with Playwright banner-visible test.
- **`test_zero_win_but_fired_pid_retained_in_split`** — pre-existing FAIL, not a skip; listed for transparency.
- Playwright tests SKIP gracefully when playwright is not installed (`skipif` guard). On this machine playwright IS installed so they ran.

---

## 5. CRITICAL concern for impl-verifier / impl-critic

**BLOCKING**: The implementer's I6 code has an indentation bug that was present in the worktree:

`app.py` around line 8287 — the pre-check code:
```python
    busy_items = []
    for it in parsed_items:          # ← indentation at function level, not inside batch_generate_report
        ops = registry.peek_cell_status(...)
```

was placed OUTSIDE the `batch_generate_report` function body (after a `return` statement at line 8264, the `else:` parsing branch had no matching `return`, so the pre-check became module-level code inside `create_app`). This caused `NameError: name 'parsed_items' is not defined` at `create_app()` call time.

The code appears corrected in the current version I observed (T-I6 tests pass), but the original failure I saw during initial test run (all tests failing with NameError) indicates the fix was applied mid-session. **Verifier should confirm `create_app()` call succeeds cleanly and the I6 pre-check is inside the `batch_generate_report` function body.**

Also: the `@app.post` at line 8309 (`cancel_batch_generate`) appears as dead code after the stray `return batch_gen_mgr.start(parsed_items)` at line 8307. This is only valid if the current code structure has the pre-check inside the function body. Verifier should confirm all route decorators after batch_generate_report are at the correct indentation level.

---

## 6. Additional notes

- T-B2 has a **second safety net** (running-runs DB check at lines 7038-7053) that also catches the race. The `test_delete_all_data_returns_409_active_sampling` test passes even with the registry bug injected because the DB check fires first. Added `test_delete_all_data_registry_check_blocks_even_without_running_rows` to isolate the registry-specific path (force-marks run as 'completed' in DB then checks DELETE).

- T-B3: The `stale_tag_error` test passes, but `reassociate_error` was not given a separate test (it uses the same pattern as stale_tag_error and is tested implicitly). Could add a `test_system_state_surfaces_reassociate_error` in follow-up.

- T-I1 xfail: if implementer chose Option A but did not land wiring, the xfail will turn XPASS only when real sampling is available (requires real upstream). Consider promoting to strict=True xfail once the decision is finalized.

- T-I4 `test_rawdata_overview_success_shows_normal_banner`: checks that `state.rawdataOverviewError` is cleared on success. Passes but has a minor fragility: if the live_server has no rawdata and returns an empty overview, the assertion may not exercise the error-clear path. Tighten in follow-up.
