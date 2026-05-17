# P1-B2 Implementation — Consolidate summary md5 patcher (real x 2)

## Verdict: pass

---

## Files changed (3)

### 1. `fresh_slotlab/summary_md5_patch.py` — NEW (lines 1-130)

Canonical `patch_summary_md5(summary_path, md5_lookup_fn, *, machine, mode)` helper.

- Brief §1 "create `fresh_slotlab/summary_md5_patch.py` (new)"
- Brief §3 C1: injectable `md5_lookup_fn` — zero-argument callable returning `(config_md5, code_md5)`
- Brief §3 C4: fills only falsy fields (empty string, None, missing key); non-empty fields NOT overwritten
- Brief §3 C5 citing `feedback_no_silent_swallow.md`: lookup failure, read failure, and write failure each log to `sys.stderr` with `machine=`, `mode=`, `error=` context — does NOT silently swallow
- `feedback_subprocess_import_suicide_and_module_globals.md`: zero import-time side effects (no app construction, no global mutation, no subprocess spawn)

### 2. `src/web_console/backend/app.py` — lines 7069-7089 (was 7069-7097)

Old: 28-line inline block with `try/except Exception: pass` (silent swallow).
New: 6-line thin callsite via shared helper.

- Brief §1 "app.py:6955-6973 — call shared helper" (brief's line numbers are offset from actual 7069)
- Brief §3 C2: "no body-level duplication remaining"
- Cites `03_coupling_audit.md §4.5` in comment
- Injects lookup via `lambda: _get_machine_md5(machine, mc, mode=mode)` — the existing `_get_machine_md5` wrapper which handles both real-machine flat schema and virtual-machine modesMd5 per-mode block
- Lazy import (`from fresh_slotlab.summary_md5_patch import ...` inside the function) matches app.py's existing style for fresh_slotlab imports

### 3. `slot_designer/core/backend/virtual_analyzer.py` — `_patch_summary_md5_tags` (lines 500-542)

Old: 53-line standalone implementation with try/except OSError: pass (silent swallow on write failure; silent return on read failure).
New: 12-line thin wrapper around shared helper.

- Brief §1 "virtual_analyzer.py:506-558 — call shared helper"
- Brief §3 C2: "no body-level duplication remaining"
- Cites `03_coupling_audit.md §4.5` in docstring
- Public signature preserved (positional `output_dir, config_md5, code_md5`) — backwards compatible with all existing callers and P1-A2 tests
- Added `machine` and `mode` keyword-only parameters with defaults `"<unknown>"` — enables richer failure logging in C5
- `_delegate_to_real_analyzer` updated to pass `machine=original_args.machine, mode=original_args.rtp_mode` when calling `_patch_summary_md5_tags`

---

## Brief-section traceability

| Change | Brief section |
|---|---|
| New `summary_md5_patch.py` | §1 "create fresh_slotlab/summary_md5_patch.py (new)" |
| `patch_summary_md5(summary_path, md5_lookup_fn)` signature | §3 C1 |
| app.py thin callsite | §1 "app.py:6955-6973 — call shared helper", §3 C2 |
| virtual_analyzer thin wrapper | §1 "virtual_analyzer.py:506-558 — call shared helper", §3 C2 |
| Only fills empty fields | §3 C4 |
| Failure logging to stderr | §3 C5 citing `feedback_no_silent_swallow.md` |
| No import-time side effects | §2 citing `feedback_subprocess_import_suicide_and_module_globals.md` |
| Per-mode granularity passed through | §3 C3 citing `feedback_md5_granularity_and_stamping.md` |
| arch artifact refs in comments | §2 citing `01_pipeline_map.md §4`, `03_coupling_audit.md §4.5`, `08_handoff.md §4` |

---

## Pytest results (touched modules)

```
tests/backend/test_summary_md5_writer_parity.py  — 30/30 passed  (P1-A2)
tests/backend/test_lookup_machine_md5_canonical.py — 39/39 passed  (P1-B1)
Total: 69/69 passed in 0.41s
```

P1-A2 parity test stays GREEN after both callsite changes. Specifically:
- `test_gamma_patcher_is_callable` — imports `_patch_summary_md5_tags` from virtual_analyzer; backwards-compatible 3-positional-arg call still works
- `test_gamma_patcher_fills_empty_summary` and `test_gamma_patcher_does_not_overwrite_existing_md5` — behaviour preserved by shared helper
- `test_gamma_patcher_no_op_when_both_md5s_empty_input` — `patch_summary_md5` early-returns on falsy both results
- `test_gamma_patcher_no_op_when_summary_missing` — `patch_summary_md5` early-returns when `summary_path` doesn't exist

---

## Behaviour change notes

**Failure logging upgrade (C5)**

The old implementations silently swallowed failures:
- `app.py` old: `except Exception: pass`
- `virtual_analyzer.py` old: `except OSError: pass` on write; bare `return` on read

The new shared helper logs every failure path to `sys.stderr`:
- `md5_lookup_fn()` raises → logs `"patch_summary_md5: md5 lookup failed for machine=... mode=...: ..."`
- Read fails → logs `"patch_summary_md5: could not read summary for ..."`
- Write fails → logs `"patch_summary_md5: could not write patched summary for ..."`

This is a behavioural improvement per `feedback_no_silent_swallow.md`. Primary report artefacts still succeed — only the metadata tagging is best-effort.

**`_patch_summary_md5_tags` signature extended**

Added `machine` and `mode` kwargs with defaults. `_delegate_to_real_analyzer` now passes them through. The P1-A2 parity test's existing calls `(output_dir, cfg, code)` remain valid (backwards compatible).

---

## Open issues / out-of-scope

1. **`write_json` vs `json.dumps`**: app.py uses `write_json` (which adds `indent=2`) while virtual_analyzer used `json.dumps(no indent)`. The new shared helper uses `json.dumps(ensure_ascii=False)` without indent — matching the original virtual_analyzer behaviour. This is a cosmetic difference (non-indented summary JSON) which was always the virtual_analyzer's output. Flagging for impl-critic: if app.py's generate-report summaries should retain `indent=2`, the shared helper can add an `indent` parameter. Not changing without brief direction since both old callsites disagree on this.

2. **`test_summary_md5_patcher_canonical.py`** — impl-tester's parallel deliverable. Not written here per brief §7 Wave 1 task split.

3. **Batch worker path** (`_batch_gen_worker.py`) — does not patch md5. That path is out of scope per §4 "Eliminating the 'patch after the fact' pattern (broader analyzer rewrite)". Flagged for future ticket.

---

## Risk notes

- **Backward compatibility**: `_patch_summary_md5_tags` public signature extended with `machine`/`mode` defaults. All 30 P1-A2 tests importing and calling this function pass without modification.
- **Import cycle**: `fresh_slotlab/summary_md5_patch.py` imports only `json`, `sys`, `pathlib.Path`, `typing` — no fresh_slotlab or slot_designer imports. Safe for use from virtual_analyzer subprocess.
- **Silent swallow removal**: The behaviour change (log vs silent swallow) is safe — no caller checks the return value or catches exceptions from the patcher.
- **Lazy import in app.py**: `from fresh_slotlab.summary_md5_patch import ...` inside `_run_generate_report` follows the established app.py pattern for fresh_slotlab imports (matches existing `from fresh_slotlab.player_impact_analyzer import main` at line 7055). Avoids any circular-import risk at module load.
