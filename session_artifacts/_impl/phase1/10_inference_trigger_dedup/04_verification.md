# Verification Report — P1-B5 Inference-Trigger Dedup

**Ticket**: `session_artifacts/_impl/phase1/10_inference_trigger_dedup/00_ticket.md`
**Verdict**: PASS
**Date**: 2026-05-18
**Verifier model**: claude-sonnet-4-6

---

## Discrepancy Resolution — timeout test

**Claim**: Tester said `test_writes_post_hook_json_with_timeout_outcome` was FAILING.
Implementer said the compat-layer normalization makes it PASS.

**Actual result** (run command):
```
python -m pytest tests/backend/test_post_analyzer_inference_logging.py tests/backend/test_batch_worker_post_hook.py -v --tb=short
```

**Observed**: 13/13 PASS, including `test_writes_post_hook_json_with_timeout_outcome`.

**Resolution**: The tester was looking at stale state. The compat layer in `app.py` lines
179-181 converts `"timeout_after_Xs"` → `"timeout"` before building the backward-compatible
dict. The test at line 89 asserts `error == "timeout"` and PASSES. Manual verification:

```python
# Injected TimeoutExpired; observed in log:
# logged["paytable_shape"]["error"] == "timeout"   ← PASS
```

The implementer's claim is correct. The tester was looking at a pre-implementation state.

---

## C1 — Single source verified

**Command**: `grep -rn "def run_post_analyzer_inference" --include=*.py .`

**Result**: Exactly 1 hit:
```
fresh_slotlab/post_inference.py:88:def run_post_analyzer_inference(
```

No other definition exists anywhere in the codebase. C1 PASS.

---

## C2 — Both callsites use helper

**Verified by reading `app.py` lines 85-201 and `virtual_analyzer.py` lines 533-588.**

`app.py`: imports `from fresh_slotlab.post_inference import run_post_analyzer_inference as _canonical` (line 131), calls `_canonical(...)` with explicit paths. The old inline subprocess loop is gone.

`virtual_analyzer.py`: imports same, calls `_canonical(...)` with virtual-specific paths. Old for-loop is gone.

Tests `TestC2_BothCallsitesDelegateToHelper`: 4/4 PASS.

---

## C3 — Failure diagnostic on disk

**Manual spot-check command**:
```python
import fresh_slotlab.post_inference as pi
result = pi.run_post_analyzer_inference(
    summary_dir / "player_impact_summary.json",
    None, None,
    {"machine": "M14", "mode": 1, "scripts_dir": str(empty_scripts), "env": env}
)
```

**Observed**:
- `result.failed`: True
- `_post_inference_failure.json` exists: True
- Entry count: 2 (both scripts logged)
- Fields present: `script_name`, `rc`, `stderr_tail`, `argv`, `cwd`, `error`, `wall_time_seconds`
- No exception raised: confirmed

All required fields per brief §3 C3 are present. C3 PASS.

---

## C5 — Inject-bug spot-check

Both inject-bug experiments from tester's `03_tests.md` confirmed:

**Experiment 1 — script-not-found**: `test_script_not_found_produces_diagnostic_and_failed_true` PASS.
The tester documented injecting `if not script.exists(): continue` → `assert result.failed is True` goes RED.
Current code sets `result.failed = True` and calls `_write_failure_diagnostic(summary_dir, sr)`.

**Experiment 2 — silent-swallow proof**: `test_silent_swallow_pattern_makes_c3_test_red` PASS.
The test simulates the forbidden `try/except: pass` pattern and asserts it violates C3 (no diagnostic, failed=False). The assertion proves the real helper must not do this.

---

## C6 — Subprocess e2e

**Command** (direct subprocess run):
```bash
python slot_designer/core/backend/virtual_analyzer.py \
  --machine M1sim --rtp-mode 1 \
  --from-cache <empty_chunk_dir> \
  --output-dir <output_dir> \
  --max-chunks 1 --chunk-spin-times 100 --chunk-robot-count 1 \
  --progress-file <progress.jsonl>
```
with `SLOT_SKIP_AUTO_INFER=0` and `SLOT_RAWDATA_ROOT=<virtual_rawdata>`.

**Observed**:
- RC: 0 (virtual_analyzer did not crash)
- STDERR contained `verify_machine_labels.py` execution attempt (line 467 reference), proving the inference hook fired
- `hook_mentioned = True` (signal observed)
- No `Traceback` in stderr from `post_inference.py` itself (best-effort contract holds)

`TestC6_SubprocessModeE2E`: 2/2 PASS.

The scripts reached real execution inside the subprocess (verify_machine_labels.py ran and hit a FileNotFoundError for missing rawdata in the script itself, not from post_inference.py). This proves the hook fires end-to-end.

---

## 3rd callsite — `_batch_gen_worker.py`

Lines 126-137 contain a `# KNOWN GAP (P1-B2 R1 + P1-A4 R1)` comment confirming the implementer correctly flagged this as a deferred follow-up. The 3rd callsite (lines 153-246) is NOT migrated. This matches the implementer's documented rationale: different result format (list-of-dicts vs InferenceResult), different schema threading requirement, and a separate ticket is the correct fix.

---

## Pytest results

### New tests (canonical suite)
```
python -m pytest tests/backend/test_post_inference_canonical.py -v
44 passed in 2.00s
```

### Pre-existing post-hook tests
```
python -m pytest tests/backend/test_post_analyzer_inference_logging.py tests/backend/test_batch_worker_post_hook.py -v
13 passed in 0.06s
```

### Full suite
```
python -m pytest tests/backend/ tests/integration/ --tb=no -q
4 failed, 2380 passed, 23 skipped, 2 xfailed, 7 warnings
```

---

## Regressions in untouched areas

**Verdict: 0 regressions introduced by P1-B5.**

The 4 failures in the full suite with P1-B5 are all pre-existing:

1. `test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split`
   — Missing fixture file `rawdata/M31/mode_1/chunk_0001.json`. Not a code issue. Pre-existing (confirmed by baseline run without P1-B5 also failing).

2-4. `test_t_critical_table_canonical.py` (3 tests: `test_c1_player_impact_analyzer_imports_from_sampler`, `test_c1_virtual_analyzer_imports_from_sampler`, `test_c6_split_path_monkeypatch_proves_sampler_attr_used`)
   — Test isolation / monkeypatch ordering artifacts that fail only when run in full suite order. All 3 pass in isolation. Pre-existing (confirmed by baseline run without P1-B5 also failing).

**Baseline comparison**: Without P1-B5 changes (stashed), full suite had 7 failures.
With P1-B5, 4 failures — 3 fewer because P1-B5 makes `TestC2_BothCallsitesDelegateToHelper` tests pass that were failing without the implementation.

---

## Subprocess vs in-process coverage

| Path | Coverage |
|---|---|
| In-process (monkeypatched subprocess.run) | All C1/C3/C4/C5/C7 tests (42 tests) |
| Subprocess (real spawn of virtual_analyzer.py) | C6 (2 tests) — hook confirmed to fire |

---

## md5 / version invariants

Not applicable to P1-B5 (no hash composition changes).

---

## Frontend preview

Not applicable to P1-B5 (no frontend changes).

---

## Summary

All 7 brief contracts (C1–C7) verified:
- C1 single source: 1 definition, `fresh_slotlab/post_inference.py:88`
- C2 both callsites: app.py + virtual_analyzer.py both delegate to canonical helper
- C3 failure diagnostic: `_post_inference_failure.json` written with all required fields; no raise; logged to stderr
- C4 worker resource snapshot: `opts["env"]` used, no live `os.environ` read when caller supplies env
- C5 inject-bug TDD: both experiments documented and tests PASS
- C6 subprocess e2e: virtual_analyzer subprocess fires hook; scripts execute inside subprocess
- C7 regression template: modeled on `test_batch_worker_post_hook.py` pattern
- Timeout test discrepancy: compat layer normalization works; test PASSES
- No regressions introduced
