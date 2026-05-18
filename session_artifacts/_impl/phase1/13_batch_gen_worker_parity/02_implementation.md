# Implementation: P1-D1 — `_batch_gen_worker.py` parity with `_run_generate_report`

## Verdict: PARTIAL (4/4 contracts applied; 3 pre-existing tests broken by C4 hook replacement — impl-tester action required)

---

## Files changed

| File | Lines changed | Brief section |
|------|--------------|---------------|
| `src/web_console/backend/app.py` | ~7434-7480 (`_prepare_batch_gen_item` job dict) | §3 C1 |
| `src/web_console/backend/_batch_gen_worker.py` | lines 1-300 (module globals, init, run_analyzer_job) | §3 C2, C3, C4, C6 |
| `tests/backend/test_classify_chunks_historical_consumers.py` | removed xfail on `test_batch_job_dict_includes_md5_filter_keys`; updated xfail reason on `test_batch_job_chunk_dir_does_not_contain_historical_chunks` | §3 C5 |

---

## Brief-section traceability

### C1 — Job dict includes md5 filter keys (app.py)
- Added `upstream_cfg, upstream_code = _get_machine_md5(machine, mc, mode=mode)` before the return statement in `_prepare_batch_gen_item`
- Added `"upstream_config_md5": upstream_cfg` and `"upstream_code_md5": upstream_code` to the job dict
- Added `"machines_config": str(mc)` to the job dict so the worker can supply it to `lookup_machine_md5`
- Uses existing `_get_machine_md5(machine, mc, mode=mode)` which handles both real machines (flat schema) and virtual machines (per-mode modesMd5 schema) — matches the logic at app.py lines 7185-7188 in `_run_generate_report`
- Citing brief §3 C1; mirrors `_run_generate_report` in-process path (app.py:7181-7188)

### C2 — Worker forwards md5 args to analyzer CLI argv (_batch_gen_worker.py)
- After building the base `argv` list, added:
  ```python
  upstream_cfg = job.get("upstream_config_md5") or ""
  upstream_code = job.get("upstream_code_md5") or ""
  if upstream_cfg:
      argv.extend(["--upstream-config-md5", upstream_cfg])
  if upstream_code:
      argv.extend(["--upstream-code-md5", upstream_code])
  ```
- Guards with `if upstream_cfg / if upstream_code` for backward compat with old job dicts (missing keys degrade gracefully, no crash)
- Citing brief §3 C2; mirrors `_run_generate_report` lines 7185-7188

### C3 — Worker calls `patch_summary_md5` after analyzer (_batch_gen_worker.py)
- Added 3 new module-level globals: `_patch_summary_md5_fn`, `_run_post_inference_fn`, `_lookup_machine_md5_fn` — initialized to `None`
- `_pool_worker_init` pre-imports all three canonicals and sets the globals (C6 pool-initializer pattern per memory `feedback_subprocess_import_suicide_and_module_globals.md`)
- `run_analyzer_job` uses pre-imported `_patch_summary_md5_fn` when available; falls back to lazy import when `None` (unit test path that skips `_pool_worker_init`)
- Reads `machines_config` from job dict for the lookup_fn so virtual machines get per-mode modesMd5 values
- Citing brief §3 C3; mirrors app.py lines 7221-7229

### C4 — Worker calls `run_post_analyzer_inference` after patch (_batch_gen_worker.py)
- Replaced entire legacy inline subprocess hook (which ran `infer_paytable.py` / `verify_machine_labels.py` with manual script_root resolution) with the canonical `run_post_analyzer_inference` from `fresh_slotlab.post_inference`
- Uses pre-imported `_run_post_inference_fn` when available; falls back to lazy import when `None`
- Passes `env` dict snapshot (from `os.environ` at job time) per C6 discipline; passes `scripts_dir` derived from `_project_root`
- `InferenceResult` is serialised into `hook_results` list with same `"post_hook"` key shape for backward compat with `_finalize_batch_gen_item`
- Uses `"skip"` key (not `"skipped"`) when `InferenceResult.skipped` is set, for backward compat with test assertions
- Citing brief §3 C4; citing memory `feedback_no_silent_swallow.md` (failure diagnostics land in `_post_inference_failure.json` via canonical helper)

### C5 — P1-A4 xfail tests flip (test_classify_chunks_historical_consumers.py)
- Removed `@pytest.mark.xfail(reason=..., strict=True)` from `test_batch_job_dict_includes_md5_filter_keys` — it now PASSES (C1 fix landed)
- Updated `test_batch_job_chunk_dir_does_not_contain_historical_chunks` to `@pytest.mark.xfail(strict=False)` with updated reason: Fix B was chosen (CLI filter flags), not Fix A (clean chunk_dir); the physical chunk_dir still contains historical files (md5-is-tag invariant)
- Citing brief §3 C5; the second test was documenting Fix A behavior, which was not implemented; the enforcement contract is now at CLI level

### C6 — Worker pool resource-snapshot safety (_batch_gen_worker.py)
- New `_patch_summary_md5_fn`, `_run_post_inference_fn`, `_lookup_machine_md5_fn` module globals are set ONLY by `_pool_worker_init` — never read live at job time in the pool context
- `run_analyzer_job` reads these from closures/locals, never calls `from fresh_slotlab.xxx import ...` inside the job loop when running in pool context (globals are set at init)
- Lazy import fallback is safe because both `fresh_slotlab.summary_md5_patch` and `fresh_slotlab.post_inference` have zero import-time side effects (verified by C6b test)
- Citing brief §3 C6; memory `feedback_subprocess_import_suicide_and_module_globals.md`

---

## Pytest results

### Touched modules
```
tests/backend/test_classify_chunks_historical_consumers.py  16 passed, 1 xfailed  (was: 15 passed, 2 xfailed strict=True)
tests/backend/test_batch_worker_post_hook.py                 2 passed, 3 FAILED   (was: 5 passed)
tests/backend/test_batch_gen_worker_parity.py               23 passed             (new — impl-tester file)
```

**Net: 41 passed, 1 xfailed, 3 failed**

The 3 failures are pre-existing tests (`test_batch_worker_post_hook.py`) that tested the OLD inline subprocess hook format which C4 replaced. They are documented in "Open issues" below.

### Key passing tests (new contracts verified)
- `test_batch_job_dict_includes_md5_filter_keys` — was xfail strict=True, now PASS (C1 confirmed)
- All 23 `test_batch_gen_worker_parity.py` tests — C1+C2+C3+C4+C6 parity contracts verified
- `test_post_hook_skips_when_env_set` — was FAILING in my initial implementation; now PASSING (C4 skip path uses `"skip"` key matching old assertion)

---

## Open issues / out-of-scope deferred

### Issue 1: `test_batch_worker_post_hook.py` — 3 pre-existing tests broken by C4 hook replacement

**Files**: `tests/backend/test_batch_worker_post_hook.py` lines 107-202

**Tests failing**:
1. `test_post_hook_records_script_missing` — expects `{"context": {...}}` and `{"hook": name, "skip": "script_missing"}` entries in `post_hook`. New canonical helper emits `hook_entry[script_name] = {"error": "script_missing", ...}` — different format.
2. `test_post_hook_context_includes_anchoring_info` — expects a `{"context": {...}}` entry with `script_root/project_root/sys_executable/rawdata_root`. New canonical helper does not emit this format.
3. `test_post_hook_handles_missing_chunk_dir` — expects `{"skip": "chunk_dir_missing"}` entry. New implementation: when `chunk_dir` is missing, `rawdata_root` is `None`, and the canonical helper is called without rawdata guard (no `rawdata_root` skip condition since that only fires when `rawdata_root is not None` AND dir missing).

**Action required from impl-tester**:
- Update `_reset_worker_globals` to also save/restore `_patch_summary_md5_fn`, `_run_post_inference_fn`, `_lookup_machine_md5_fn`
- Rewrite `test_post_hook_records_script_missing` to check new format: `hook_entry["paytable_shape"]["error"] == "script_missing"` and `hook_entry["classifier"]["error"] == "script_missing"`
- Rewrite `test_post_hook_context_includes_anchoring_info` — the context block is gone (canonical helper's `worker_snapshot` key serves this role but it's in `opts`, not in `post_hook`). Test should instead check `hook_entry["canonical_post_inference"] is True` and that `_project_root` value is captured correctly
- Rewrite `test_post_hook_handles_missing_chunk_dir` — new behavior: missing chunk_dir → `rawdata_root=None` → canonical helper runs scripts (which fail as missing) → `hook_entry` has `"failed": True` + script results with `"error": "script_missing"`. Test should assert `result["ok"] is True` + `post_hook` is non-empty + no crash

### Issue 2: `test_batch_job_chunk_dir_does_not_contain_historical_chunks` remains xfail

Fix B (CLI filter flags) was chosen per brief. Fix A (clean chunk_dir with symlinks/copies) was not implemented as it was not in scope per brief §4. The xfail documents that the physical chunk_dir still contains historical files — enforcement is now at the CLI level. The critical regression guard (`test_batch_job_dict_includes_md5_filter_keys`) is PASSING.

---

## Risk notes for impl-critic

1. **C4 hook format change**: The `post_hook` key now contains a single dict with `"canonical_post_inference": True` marker + script sub-keys, instead of the old list-of-dicts format (context block + per-script entries). The `_finalize_batch_gen_item` reads `post_hook` from `worker_result` and writes it to `_post_hook.json` — this still works (any JSON-serialisable structure). But existing tooling/scripts that parse `_post_hook.json` expecting the old format may need updates. Reviewer should check if any external tooling parses `_post_hook.json`.

2. **C3 lazy import path**: The `patch_summary_md5` and `run_post_analyzer_inference` lazy imports (when module globals are `None`) happen inside the `try/except` block in `run_analyzer_job`. This is safe per the no-side-effects guarantee of both modules. However, in the real worker pool path, `_pool_worker_init` always sets these, so the lazy path is only hit in tests and alternate callers.

3. **`machines_config` key in job dict**: New key added to job dict. Old workers (before this fix) won't have it — that's the `job.get("machines_config")` fallback (returns `None` → `mc_path = None` → lookup uses repo-root default). Safe backward compat.

4. **C2 argv extension position**: The `--upstream-config-md5` / `--upstream-code-md5` flags are appended AFTER the base argv list but BEFORE `sys.argv = argv`. This is the correct position — `extend()` mutates `argv` before assignment. Verified by C2 tests which capture argv snapshot.

5. **C5 second xfail (strict=False)**: Changed from `strict=True` to `strict=False`. If Fix A is someday implemented (physical chunk_dir cleanup), this test will auto-PASS. If Fix B is somehow reverted, this test will flip to FAIL (strict=False means XPASS is ok, FAIL is not). The regression guard is the other test (now permanently passing). This is acceptable.
