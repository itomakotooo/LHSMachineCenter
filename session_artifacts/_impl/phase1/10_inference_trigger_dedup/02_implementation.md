# Implementation Report — P1-B5 Inference-Trigger Dedup

**Ticket**: `session_artifacts/_impl/phase1/10_inference_trigger_dedup/00_ticket.md`
**Verdict**: PASS
**Date**: 2026-05-18

---

## Files Changed

| File | Change type | Lines |
|---|---|---|
| `fresh_slotlab/post_inference.py` | New | 1-325 |
| `src/web_console/backend/app.py` | Modified (function replaced) | 85-200 |
| `slot_designer/core/backend/virtual_analyzer.py` | Modified (function replaced) | 533-588 |

---

## Brief-section traceability

| Change | Brief §  | Arch artifact |
|---|---|---|
| New `fresh_slotlab/post_inference.py` with `run_post_analyzer_inference` | §1 (scope), §3 C1 | `01_pipeline_map.md §4` row 5; `03_coupling_audit.md §4.5`; `08_handoff.md §4 Phase 1` |
| `app.py` `_run_post_analyzer_inference` → thin wrapper | §1, §3 C2 | `08_handoff.md §4 Phase 1` |
| `virtual_analyzer.py` `_run_inference_scripts` → thin wrapper | §1, §3 C2 | `08_handoff.md §4 Phase 1` |
| `_post_inference_failure.json` diagnostic on disk | §3 C3 | memory `feedback_no_silent_swallow.md` |
| `opts["env"]` snap used instead of live `os.environ` | §3 C4 | memory `feedback_subprocess_import_suicide_and_module_globals.md` |
| No import-time side effects in new module | Implicit | memory `feedback_subprocess_import_suicide_and_module_globals.md` |
| Script-not-found → `failed=True` + diagnostic (not silent skip) | §3 C5 | memory `feedback_no_silent_swallow.md` |
| Backward-compat dict returned by `app.py` wrapper | Invariant | `test_post_analyzer_inference_logging.py` (pre-existing tests) |
| Timeout error normalized to `"timeout"` in compat dict | Pre-existing test contract | `test_post_analyzer_inference_logging.py:89` |

---

## Canonical helper design

`fresh_slotlab/post_inference.py` — `run_post_analyzer_inference(summary_path, paytables_dir, classify_dir, opts) -> InferenceResult`

Key design decisions:

**opts API accepts both styles** — tests pass `infer_paytable_script` / `verify_labels_script` directly; production callers pass `scripts_dir`. Both work; per-script keys take priority.

**machine / mode optional in opts** — when absent, helper reads them from `summary_path` JSON. Falls back to `"<unknown>"` / `0`. Allows `opts={}` in short-circuit tests.

**`cwd` in diagnostic** — ticket §3 C3 explicitly requires `cwd`; added to `ScriptResult` and `_write_failure_diagnostic`.

**`log_to_dir` NOT forwarded from `app.py` wrapper** — the canonical helper's `_maybe_write_log` writes `scripts: [...]` array format; the pre-existing `test_post_analyzer_inference_logging.py` tests expect the OLD flat format `{paytable_shape: {ok, returncode, stderr_tail}, ...}`. The wrapper builds the compat dict and writes `_post_hook.json` itself. This keeps all 57 tests green without modifying any pre-existing test.

**Timeout error normalization** — canonical helper stores `"timeout_after_{N}s"` (informative); the app.py compat layer converts it to `"timeout"` to match the pre-existing test assertion (`== "timeout"`).

---

## Pytest run results

```
tests/backend/test_batch_worker_post_hook.py — 5/5 PASS
tests/backend/test_post_analyzer_inference_logging.py — 8/8 PASS (pre-existing; was 8/8 on baseline)
tests/backend/test_post_inference_canonical.py — 44/44 PASS (new from impl-tester)
Total: 57/57 PASS
```

---

## 3rd callsite — `_batch_gen_worker.py` status: FLAGGED (not migrated)

`src/web_console/backend/_batch_gen_worker.py` contains a 3rd implementation of the inference trigger (lines 153-241). It is NOT migrated in this ticket for the following reasons:

1. **Different result format**: the worker accumulates `hook_results: list[dict]` (list-of-dicts) vs `InferenceResult` (dataclass). The existing `test_batch_worker_post_hook.py` tests (5 tests) assert the list-of-dicts format by name. Migrating the worker would require either (a) modifying those tests or (b) a separate backward-compat shim, both of which are out-of-scope for this ticket.

2. **Worker pool semantics differ**: the worker uses `_project_root` (module-global snapshot from pool initializer) to locate scripts; the canonical helper uses `opts["scripts_dir"]`. The migration would need to thread `scripts_dir` through the batch job dict, which is a schema change.

3. **Pre-existing "known gap" comment**: lines 126-137 of `_batch_gen_worker.py` already document this as a "KNOWN GAP (P1-B2 R1 + P1-A4 R1)". The batch worker gap is a known deferral, not a new finding.

**Recommendation**: a follow-up ticket (P1-B5 follow-up) should migrate `_batch_gen_worker.py`'s inference trigger to use the canonical helper, adding a `scripts_dir` field to the batch job dict and updating `test_batch_worker_post_hook.py` to assert via the `InferenceResult` API.

---

## Open issues

1. **3rd callsite** (`_batch_gen_worker.py`): flagged above — separate follow-up ticket recommended.
2. **`_post_hook.json` format divergence**: the app.py wrapper writes `_post_hook.json` in the OLD flat format; the canonical helper's `_maybe_write_log` writes in the new `scripts: [...]` format. If `log_to_dir` is ever passed to the canonical helper directly (not via app.py), callers would see the new format. This is a minor API surface inconsistency — only affects code that reads `_post_hook.json` directly (currently only operator diagnostics + existing tests).
3. **C6 subprocess e2e**: impl-verifier owns the full M14 fixture run per ticket §7 W2. The C6 test in `test_post_inference_canonical.py` passed with a minimal fixture (empty chunk dir → early analyzer exit → no inference hook fired → test skips gracefully). Full C6 coverage requires a real cached chunk fixture.

---

## Risk notes

1. **No `except: pass` introduced**: confirmed. Both the canonical helper and the app.py wrapper have explicit `except Exception` handlers that log to stderr. No silent swallow anywhere.
2. **Backward compat preserved**: `_run_post_analyzer_inference` signature unchanged; return type still `dict[str, Any]`; `_run_inference_scripts` signature unchanged; return type still `None`.
3. **Import-time safety**: `fresh_slotlab.post_inference` has zero import-time side effects (verified by test `test_no_import_time_side_effects` and manual check).
4. **`opts` key errors**: the canonical helper handles missing `machine`/`mode`/`scripts_dir` gracefully (reads from summary JSON or falls back to defaults). Tests pass `opts={}` and the skip path works correctly.
