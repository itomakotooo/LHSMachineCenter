# Critique Report — P1-B5 Inference-Trigger Dedup

**Ticket**: `session_artifacts/_impl/phase1/10_inference_trigger_dedup/00_ticket.md`
**Critic verdict**: APPROVE-WITH-REVISIONS
**Date**: 2026-05-18
**Verifier artifact**: NOT YET PRODUCED (Wave 2 parallel — this critique proceeds without it)

---

## Verdict

**APPROVE-WITH-REVISIONS**

The canonical helper is well-constructed. Both callsites are thin wrappers. C3 diagnostic is correctly written. C4 env-snapshot is correctly threaded. No `except: pass` in the main success/failure path.

However three material issues require revision before commit:

1. **`_maybe_write_log` silently swallows `OSError`** — the log-write path is the *sole* persistence mechanism for the in-process daemon-thread path; swallowing its failure is a direct violation of `feedback_no_silent_swallow.md`.
2. **`app.py` summary_path sentinel writes C3 diagnostic to `Path(".")`** — when `log_to_dir=None` (the production path before a batch run starts), any script failure writes `_post_inference_failure.json` to the process CWD, not alongside the analyzer output, making it effectively unfindable.
3. **Dead module-level constants `INFER_PAYTABLE_SCRIPT` / `VERIFY_LABELS_SCRIPT` in `app.py`** — the refactor orphaned them; no code in `app.py` references them any more. They are misleading and will cause future engineers to believe the wrapper reads them.

Additionally three non-blocking observations are flagged: the C2 test heuristic has a false-negative risk, the `_post_hook.json` format fragmentation is a documented open issue that is genuinely open (not resolved), and the 3rd callsite deferral is defensible but the "known gap" framing must not be allowed to grow stale.

---

## Stress Questions

### SQ1 — `_maybe_write_log` OSError silent swallow (`post_inference.py:448`)

**Question**: `_maybe_write_log` (called when `opts["log_to_dir"]` is set) catches `OSError` and passes silently. Per `feedback_no_silent_swallow.md`, *any best-effort post-hook must persist its failure diagnostic*. For the in-process generate-report path, `_maybe_write_log` writing `_post_hook.json` IS the sole persistence mechanism — the daemon thread drops the return value. If the write fails silently, the failure is invisible. This is exactly the failure mode that triggered the memory rule (mode 7 batch 252 items 12h silent skip).

**Attempted answer**: The comment says "Don't let a log-write failure change the hook's effective outcome." This is true for the OSError itself — you don't want to propagate a disk-full error upward. But the canonical helper already demonstrates the correct pattern: `_write_failure_diagnostic` on `OSError` prints to stderr before returning (line 403-409). `_maybe_write_log` at line 448 does not print anything — pure silent swallow.

**Verdict**: ✗ Not addressed. The `except OSError: pass` in `_maybe_write_log` (line 448) must at minimum print a stderr message. The precedent is set by `_write_failure_diagnostic` five lines earlier in the same file. This is a direct memory-rule violation.

---

### SQ2 — `app.py` summary_path sentinel (`app.py:143`)

**Question**: When `log_to_dir=None` (no explicit output dir), the app.py wrapper synthesizes `_summary_path = Path(".") / "player_impact_summary.json"`. The canonical helper derives the C3 diagnostic directory from `summary_path.parent`. So failure diagnostics go to `Path(".")` — the process CWD at the moment of the call — which is the project root or wherever the web server was started. This is not alongside the analyzer output where an operator would look. Is this defensible or a design defect?

**Attempted answer**: The implementer acknowledges this inline with "Failure stderr logging still fires (C3); on-disk diagnostic is best-effort." That framing is partly correct — stderr logging is indeed C3-compliant. But C3 requires the file at `<summary_dir>/_post_inference_failure.json`. The brief says "Then logs to stderr + sets failed=True. Helper does NOT raise. Helper does NOT silently swallow." — this is about the helper not swallowing, not about the wrapper being allowed to discard the file's location. The real `_run_post_analyzer_inference` in the original code always ran in the context of a known `log_to_dir`. Callers who pass `log_to_dir=None` explicitly opt out of persistence; the question is whether there is a production code path that calls without `log_to_dir` and then relies on the on-disk diagnostic.

**Verdict**: ⚠ Partially addressed. The case where `log_to_dir=None` is the production call (e.g., if any callers pass `log_to_dir=None` expecting failure diagnostics to appear) is a latent defect. The implementer's comment correctly identifies it but marks it as "best-effort." Per the brief's C3 contract, it is a genuine gap if any production caller omits `log_to_dir`. A revision should either (a) require callers to always pass `log_to_dir`, or (b) document clearly that on-disk C3 is only guaranteed when `log_to_dir` is set. Currently the code silently writes to CWD without documenting that behaviour.

---

### SQ3 — `_post_hook.json` format fragmentation (open issue 2)

**Question**: The canonical helper's `_maybe_write_log` writes `_post_hook.json` in the new `{machine, mode, skipped, failed, scripts: [...]}` format. The `app.py` wrapper writes the same filename in the old flat format `{machine, mode, paytable_shape: {ok, returncode, ...}, classifier: {...}}` — and does NOT forward `log_to_dir` to the canonical helper, so both code paths write the same filename but with divergent schemas. If a future caller directly calls the canonical helper with `log_to_dir` set (bypassing the app.py wrapper), it will produce a different `_post_hook.json` format than the one the 8 pre-existing logging tests assert.

**Attempted answer**: The implementer flagged this explicitly as open issue 2, and states it "only affects code that reads `_post_hook.json` directly (currently only operator diagnostics + existing tests)." The claim is that no downstream code depends on the schema. However, the 8 pre-existing tests directly parse `_post_hook.json` by field name (`logged["paytable_shape"]["ok"]`). If any future integration inadvertently calls the canonical helper with `log_to_dir` set, those tests would become stale. More importantly, the `TestC7` regression test for the new module asserts `logged["machine"]` and `logged["mode"]` — but these field names exist in BOTH formats. The new format's `scripts` array vs the old flat `paytable_shape` / `classifier` structure is invisible to C7 tests.

**Verdict**: ⚠ Partially addressed (explicitly flagged but not resolved). The fragmentation is real and the mitigation is "currently no one reads the new-format path." This is a monitoring gap. The new-format `_post_hook.json` written by `_maybe_write_log` is not tested by the pre-existing 8 tests (which only cover the wrapper's old-format path), and C7's `test_log_to_dir_also_writes_post_hook_json` only checks `machine` and `mode` — fields common to both formats. The fragmentation is invisible to the test suite.

---

### SQ4 — Timeout error normalization was NOT an arbitrary choice, but the pre-existing test contains a fragile assertion (`test_post_analyzer_inference_logging.py:89`)

**Question**: The pre-existing test asserts `logged["paytable_shape"]["error"] == "timeout"`. The canonical helper uses `"timeout_after_300.0s"`. The wrapper normalizes by checking `startswith("timeout_after_")`. The `timeout_sec` param can differ from 300.0 — if a caller passes `timeout_sec=60`, the canonical helper writes `"timeout_after_60.0s"`, which the wrapper correctly normalizes to `"timeout"`. BUT: the tester's `03_tests.md` (open gap 4) says this "is an impl-critic issue (API compatibility of the old callsite wrapper), not introduced by my tests." This framing attempts to pass the issue upstream. Is the normalization correct?

**Attempted answer**: The normalization `startswith("timeout_after_")` → `"timeout"` is correct and covers any timeout duration. The pre-existing test passes GREEN per the 57/57 count. This is adequately addressed.

**Verdict**: ✓ Adequately addressed. The normalization logic is correct and general.

---

### SQ5 — `scripts_dir` dual interface (opts dual-key design)

**Question**: The canonical helper accepts EITHER `scripts_dir` (for production callers) OR `infer_paytable_script` / `verify_labels_script` (for tests). This is a dual interface. Per `feedback_no_parallel_panel_impl.md`, dual resolution paths can drift. Does this create a maintenance risk?

**Attempted answer**: The dual interface is explicit and documented in the `opts` docstring. The priority rule is clear: per-script keys take priority over `scripts_dir`, which takes priority over auto-resolution. Tests use the per-script keys because they need to point at tmp fixtures; production uses `scripts_dir`. Auto-resolution (`__file__.parent.parent / "scripts"`) is the fallback for callers that provide neither. This is a reasonable layered default; it is not a parallel implementation because all three resolve to the same type (`Path`). The concern would be if the auto-resolution path diverged from the `scripts_dir` path in production, but the implementer passes `ROOT / "scripts"` explicitly in both callsites, so auto-resolution is a fallback only.

**Verdict**: ✓ Adequately addressed. The dual interface is a layered default, not a parallel impl.

---

### SQ6 — Worker resource snapshot (C4) — is the `env` snapshot sufficient, or is `cwd` also needed?

**Question**: C4 says "if invoked from a worker context, helper relies on a module-global snapshot taken at worker `initializer=` time (sys.path, cwd, env)." The canonical helper reads `opts["env"]` for subprocess env (correct) and derives `_cwd` from `opts.get("worker_snapshot", {}).get("cwd") or os.getcwd()` (line 220). The `virtual_analyzer.py` wrapper passes `"env": env` but does NOT pass `"worker_snapshot"` — so `_cwd` defaults to `os.getcwd()` at call time. In a subprocess (not a pool worker), `os.getcwd()` is the `cwd=_ROOT` used to spawn the subprocess, which is correct. In a pool worker (the batch_gen_worker path — which does NOT use the canonical helper), there's no issue because the canonical helper is not called there. So the concern only applies if a future caller runs the canonical helper in a pool worker without passing `worker_snapshot`.

**Attempted answer**: For the two current callsites (app.py daemon thread and virtual_analyzer subprocess), `os.getcwd()` at call time is correct. The `worker_snapshot` mechanism is a forward-declared slot for future pool-worker callers. The batch_gen_worker does not use the canonical helper. This is adequately addressed for the current scope, with `worker_snapshot` providing the documented extension point.

**Verdict**: ✓ Adequately addressed for current callsites. The `worker_snapshot` slot is future-proof design. No regression risk introduced.

---

### SQ7 — Dead module-level constants in `app.py` (`INFER_PAYTABLE_SCRIPT`, `VERIFY_LABELS_SCRIPT`)

**Question**: `app.py` lines 81-82 define `INFER_PAYTABLE_SCRIPT = ROOT / "scripts" / "infer_paytable.py"` and `VERIFY_LABELS_SCRIPT`. After this refactor, the wrapper function uses `ROOT / "scripts"` hardcoded in the `opts` dict (line 157) and never references these module constants. They are now dead code. The risk: a future engineer reading `app.py` will see these constants and assume they control the scripts used by `_run_post_analyzer_inference`, when they are ignored. The C2 heuristic test (`test_app_py_no_longer_has_inline_subprocess_inference_loop`) checks for `INFER_PAYTABLE_SCRIPT` in the text to detect the old loop pattern — but the constant still appears, so the test's `old_loop_pattern` detection logic is now permanently false-negative (it requires BOTH `for name, script, argv` AND `INFER_PAYTABLE_SCRIPT` to co-appear; the former is gone but the latter remains, so the `and` condition is False, the test never xfails, and the test will always vacuously pass even if the loop is re-introduced without the old constant name).

**Attempted answer**: The dead constants are not removed. No test catches that `INFER_PAYTABLE_SCRIPT` is unused. The C2 test heuristic is now permanently weakened because the constant's presence satisfies half the `and` condition — making the old-loop detector require a specific naming pattern that the refactored code doesn't need.

**Verdict**: ✗ Not addressed. Two problems:
- Dead constants should be removed.
- C2 test heuristic for `app.py` will not catch re-introduction of the inline loop if the loop uses `ROOT / "scripts" / "infer_paytable.py"` (a literal) instead of `INFER_PAYTABLE_SCRIPT`.

---

### SQ8 — `except Exception as exc` in `virtual_analyzer.py` wrapping `_run_inference_scripts` (line 626)

**Question**: `_delegate_to_real_analyzer` wraps the call to `_run_inference_scripts` in `try/except Exception`. Per `feedback_dont_swallow_errors_in_fix.md`, `try/except` is forbidden if it hides bugs. But `_run_inference_scripts` calls the canonical helper, which already never raises. Is this outer guard hiding anything?

**Attempted answer**: The canonical helper guarantees no raises (C3 contract). The outer guard is defensive belt-and-suspenders to protect the subprocess process in case of future import errors or unexpected conditions. It prints to stderr on catch — not silent. Per `feedback_no_silent_swallow.md`, the outer guard satisfies the non-silence requirement. Per `feedback_dont_swallow_errors_in_fix.md`, a guard that is both (a) at a boundary (virtual_analyzer subprocess process boundary) and (b) explicitly logged is justified.

**Verdict**: ✓ Adequately addressed. The outer guard is at a genuine boundary (process exit protection), is non-silent (prints to stderr), and the canonical helper already guarantees no raise so the guard is vacuous in the normal path.

---

### SQ9 — `stderr_tail` truncation: line-count vs character-count safety

**Question**: Line 297: `stderr_tail = "\n".join((proc.stderr or "").splitlines()[-50:])`. This is per-line truncation (last 50 lines). If a single stderr line is very long (e.g., a 1 MB base64 blob in a crash dump), this does not bound memory or disk usage. Is this a real risk?

**Attempted answer**: In practice inference scripts (`infer_paytable.py`, `verify_machine_labels.py`) are Python scripts whose stderr is human-readable log output. A 1 MB single-line stderr is exotic. The `capture_output=True` call buffers the full stderr in memory regardless (Python's `subprocess.run` reads all output before returning), so the tail truncation only affects what is written to disk. The memory concern applies to `subprocess.run` itself, not to the tail truncation. The disk-write concern is real but is bounded by the script's stderr output size, not by the tail logic. For normal inference scripts this is not a production risk.

**Verdict**: ⚠ Acknowledged but not a blocker. The theoretical risk (no character-count bound on individual lines) is real but not a production concern for these specific scripts. A follow-up could add `.encode("utf-8")[:10_000].decode("utf-8", errors="replace")` for safety, but this is not required for approval.

---

### SQ10 — 3rd callsite deferral (`_batch_gen_worker.py`) — is it a defensible punt or a `feedback_enumerate_safety_paths.md` violation?

**Question**: `feedback_enumerate_safety_paths.md` says "enumerate ALL paths when adding a safety carve-out." The brief (§3 C2) says "Both callsites use helper." The batch_gen_worker is a 3rd callsite that is NOT migrated. Per the P1-B1/B2/B3 pattern cited in the prompt, all previous tickets also had 3rd callsites. Is this one different enough to be defensible?

**Attempted answer**: The implementer's reasoning is documented at length: different result format (`list[dict]` vs `InferenceResult`), pool-worker semantics (the worker's `_project_root` module global is not the same `scripts_dir` key), and the pre-existing "KNOWN GAP" comment at line 126-137 of `_batch_gen_worker.py`. Crucially, the `test_batch_worker_post_hook.py` (5 tests) passes GREEN at 57/57, which means the batch_gen_worker's OWN inference hook still works correctly — the non-migration is not a regression. The batch_gen_worker's hook is a parallel implementation that predates P1-B5 and is explicitly documented as a known gap. The brief §4 ("Out of scope: adding new inference scripts, changing invocation order") is narrow but the batch_gen_worker migration would require schema changes to the job dict — a larger-surface change than this ticket's scope.

The `feedback_enumerate_safety_paths.md` rule applies to safety carve-outs (guards that protect data from deletion). The inference trigger is not a safety carve-out in that sense. However, the spirit of the rule — enumerate all paths — does apply: the 3rd callsite is a divergent implementation that continues to accumulate technical debt.

**Verdict**: ✓ Defensible for this ticket's scope, but the recommendation for a follow-up ticket must be in the commit message as an explicit TODO item, not just in the `02_implementation.md` open issue. If the follow-up ticket is not created within Phase 1 completion, this becomes a real risk.

---

## Chain Disagreements

### Disagreement 1 — C6 coverage

**Brief**: "impl-verifier spawns virtual_analyzer.py as a real subprocess against M14 mode 1 fixture; observes post-inference call happens."

**Implementer**: C6 test written but degrades to pytest.skip when no chunks in fixture. Claims "full C6 coverage requires a real cached chunk fixture."

**Tester**: "C6 subprocess test with empty fixture may skip ('no chunks in fixture') if the virtual_analyzer exits before the inference hook fires. The test degrades gracefully to a skip. Full C6 coverage requires a fixture with at least one synthetic chunk — deferred to impl-verifier's Wave 2 task per brief §7."

**Verifier**: NOT YET PRODUCED.

**Assessment**: Both implementer and tester agree the C6 test may skip. The brief explicitly delegates full C6 coverage to impl-verifier's Wave 2. Since the verifier artifact does not exist, this disagreement is with the brief itself: the C6 test as written cannot certify the post-inference hook fires in a real virtual_analyzer subprocess run. The test skips gracefully rather than proving the hook fires. This is a coverage gap accepted by both parties — the critic notes it but does not override the Wave 2 delegation.

### Disagreement 2 — C3 "does not silently swallow" boundary

**Brief**: "Helper does NOT raise (post-hook is best-effort). Helper does NOT silently swallow."

**Implementer**: Implements `_maybe_write_log` with `except OSError: pass` (lines 448-450). Claims "no silent swallow" in risk notes.

**Tester**: Does not test the `_maybe_write_log` failure path (OSError on the log write). The C3 tests use a temp directory that is always writable.

**Assessment**: The implementer's claim of "no silent swallow" is internally inconsistent with the `except OSError: pass` in `_maybe_write_log`. The tester did not catch this. This is a chain blind spot.

---

## Hidden Assumptions

1. **`log_to_dir` is always set in production** — The app.py wrapper uses `Path(".")` as the C3 diagnostic dir when `log_to_dir=None`. If any production caller omits `log_to_dir`, failure diagnostics silently go to CWD. This assumption is unvalidated by the tests (all logging tests pass `log_to_dir`).

2. **The two `_post_hook.json` schemas never co-exist for the same run** — The old-format schema (from app.py wrapper) and the new-format schema (from `_maybe_write_log`) both write to `_post_hook.json`. Anything that currently reads `_post_hook.json` by field name assumes the old format. This assumption is implicit: the implementer claims "only operator diagnostics and existing tests" read the file, but this is not verified by the test suite.

3. **`INFER_PAYTABLE_SCRIPT` / `VERIFY_LABELS_SCRIPT` constants are not used by any external caller** — After the refactor these are dead code in `app.py`. If any test or external code imports them directly, they silently still work (they point at the same path) but the indirection is broken.

---

## Edge Cases Not Covered

1. **`log_to_dir` on a read-only filesystem or permissions-denied directory** — `_maybe_write_log` silently swallows `OSError` with no stderr message. The daemon thread gets no signal that its only persistence mechanism failed.

2. **`summary_path.parent` is not writable** — `_write_failure_diagnostic` will raise `OSError` on the `diag_path.write_text()` call; this is caught and printed (correct). But `summary_dir.mkdir(parents=True, exist_ok=True)` (line 398) on a read-only mount would also raise before the write — this IS caught by the same `except OSError as exc` block.

3. **`_run_inference_scripts` in virtual_analyzer with SLOT_RAWDATA_ROOT already set** — The virtual_analyzer respects the pre-existing value via `setdefault` (line 566). A test that sets `SLOT_RAWDATA_ROOT` to a production path before calling the virtual_analyzer will route inference scripts at the real data tree. No test covers this override path.

4. **Two concurrent batch runs for the same (machine, mode)** — Both call `_write_failure_diagnostic` which reads then rewrites `_post_inference_failure.json`. There is a read-modify-write race condition on the JSON file (read existing list, append, write). Under concurrency, one run's failure entry could overwrite another's. The existing code does not use file locking. This is not new to this refactor (the old implementations did not write this file at all), but the new helper introduces the race.

5. **`str(sr.name)` mapping to `results[s.name]` in app.py wrapper** — The canonical helper uses names `"paytable_shape"` and `"classifier"` (from `jobs` list at line 260). The pre-existing logging test asserts `logged["paytable_shape"]` and `logged["classifier"]`. These names are hardcoded in `post_inference.py` line 261-262. If a future maintenance change renames these in `post_inference.py` without updating `app.py`, the backward-compat dict will have different keys, silently breaking the 8 pre-existing tests. No test locks the name→key mapping contract as a separate assertion.

---

## Required Revisions

### R1 — Fix `_maybe_write_log` silent swallow (SQ1, ✗)

`post_inference.py:448-450`: Replace `except OSError: pass` with:
```python
except OSError as exc:
    print(
        f"post_inference: could not write hook log to {log_path}: {exc}",
        file=sys.stderr,
    )
```
This follows the exact pattern already used in `_write_failure_diagnostic` five lines earlier in the same file. There is no reason for inconsistency.

### R2 — Remove dead constants from `app.py` (SQ7, ✗)

`app.py:81-82`: Remove `INFER_PAYTABLE_SCRIPT` and `VERIFY_LABELS_SCRIPT` constants. They are no longer referenced by any code in `app.py`. Their presence misleads future engineers.

If any test imports them, update the test to reference `ROOT / "scripts" / "infer_paytable.py"` directly. (Grep shows no test imports them — only `test_post_inference_canonical.py` references the string `"INFER_PAYTABLE_SCRIPT"` as a text search target in the heuristic, which will need updating too.)

### R3 — Update C2 heuristic test for `app.py` (SQ7, ✗)

`test_post_inference_canonical.py:273-281`: The `old_loop_pattern` detection uses:
```python
"for name, script, argv" in text and "INFER_PAYTABLE_SCRIPT" in text
```
After R2 removes the constant, the heuristic becomes `False and False = False` (correct) but does not catch re-introduction via literals. The tester should replace this with a stronger assertion: assert that neither `subprocess.run` nor `subprocess.call` appears inside the `_run_post_analyzer_inference` function body (not the whole file). A simple text search for the function body slice would be more precise.

---

## Commit-Message `## Self-critique` Section

```
## Self-critique

- SQ1 (_maybe_write_log silent OSError): OPEN. `except OSError: pass` at
  post_inference.py:448 silently drops failures on the sole persistence path
  for the daemon-thread caller. Memory rule feedback_no_silent_swallow says
  every best-effort post-hook must persist its failure diagnostic. Fixed in R1
  (must add stderr print before commit).

- SQ2 (summary_path sentinel → CWD): PARTIALLY OPEN. When app.py wrapper
  is called with log_to_dir=None, C3 diagnostic writes to Path(".") not
  alongside analyzer output. Accepted as best-effort limitation for the
  log_to_dir=None path; stderr logging still fires. Future callers that want
  reliable on-disk diagnostics must pass log_to_dir.

- SQ3 (_post_hook.json schema fragmentation): OPEN. Two writers (app.py
  wrapper old-format, canonical _maybe_write_log new-format) both write
  _post_hook.json with divergent schemas. Downstream consumers assume old
  format. No test asserts the new-format path's schema fields. Accepted as
  open issue 2; will require a schema-unification ticket.

- SQ4 (timeout normalization): CLOSED. startswith("timeout_after_") is
  general and correct. All 57 tests pass including pre-existing logging tests.

- SQ5 (dual opts interface): CLOSED. Layered defaults with explicit priority
  rule. Not a parallel impl.

- SQ6 (C4 worker snapshot): CLOSED for current callsites. worker_snapshot
  slot provides extension point for future pool-worker callers.

- SQ7 (dead INFER_PAYTABLE_SCRIPT / VERIFY_LABELS_SCRIPT constants): OPEN.
  Must remove before commit (R2) and update C2 test heuristic (R3).

- SQ8 (outer try/except in virtual_analyzer): CLOSED. Boundary guard with
  stderr print; not silent swallow.

- SQ9 (stderr_tail line vs char count): ACKNOWLEDGED, not blocking. Line
  truncation (last 50 lines) is sufficient for inference script stderr.

- SQ10 (3rd callsite _batch_gen_worker.py deferral): CLOSED for this ticket.
  Pre-existing KNOWN GAP comment at _batch_gen_worker.py:126. Follow-up
  ticket required: migrate _batch_gen_worker inference hook to use canonical
  helper after adding scripts_dir to job dict schema.

- Concurrent write race on _post_inference_failure.json (new edge case):
  OPEN. Read-modify-write with no file lock. Low risk for current usage
  (single-machine runs). Filed as known gap for future concurrent-batch work.
```
