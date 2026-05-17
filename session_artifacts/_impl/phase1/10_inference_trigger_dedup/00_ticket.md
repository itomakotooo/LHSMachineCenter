# Ticket P1-B5 — Consolidate inference-trigger (real × 2) (Batch 1c)

> Phase 1 / Batch 1c. Subprocess post-hook duplication. Highest risk in Batch 1c due to subprocess paths + memory-flagged silent-swallow pattern.

---

## §1 Ticket scope

Two implementations of "after analyzer writes summary, run paytable-shape + label-classifier inference scripts":
- [src/web_console/backend/app.py:85-194](src/web_console/backend/app.py:85) — `_run_post_analyzer_inference`
- [slot_designer/core/backend/virtual_analyzer.py:561-649](slot_designer/core/backend/virtual_analyzer.py:561) — `_run_inference_scripts`

Same `INFER_PAYTABLE_SCRIPT` + `VERIFY_LABELS_SCRIPT` (via app.py:81-82). Different argument signatures (real takes `paytables_dir` / `classify_dir` params; virtual hardcodes paths). Diverging error reporting.

Files expected to change:
- `fresh_slotlab/post_inference.py` (new) — `run_post_analyzer_inference(summary_path, paytables_dir, classify_dir, opts) -> InferenceResult`
- `src/web_console/backend/app.py:85-194` — call shared helper
- `slot_designer/core/backend/virtual_analyzer.py:561-649` — call shared helper (passing virtual paths)
- `tests/backend/test_post_inference_canonical.py` (new) — regression per §3

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §4` row 5 ("inference scripts trigger")
- `session_artifacts/_arch/03_coupling_audit.md §4.5` — duplicate primitives
- `session_artifacts/_arch/01_pipeline_map.md §5 Q2` — duplication across hooks
- `session_artifacts/_arch/08_handoff.md §4 Phase 1` — inference-trigger × 2
- Memory `feedback_no_silent_swallow.md` — any best-effort post-hook MUST persist failure diagnostic to disk; `except: pass` is forbidden; mode 7 batch 252 items silent-skip 12h precedent
- Memory `feedback_perf_claim_needs_e2e_event_stream.md` — subprocess-mode bugs need subprocess-mode tests

---

## §3 Contract (testable invariants)

### C1 — Single helper with explicit path args
Canonical `run_post_analyzer_inference(summary_path, paytables_dir, classify_dir, opts) -> InferenceResult`. Both callers pass paths explicitly (real passes the real dirs; virtual passes virtual dirs).

### C2 — Both callsites use helper
`app.py:85-194` becomes thin invocation. `virtual_analyzer.py:561-649` similarly.

### C3 — Failure diagnostic on disk
Per memory `feedback_no_silent_swallow.md`: if either subprocess returns rc != 0, helper writes a diagnostic file (e.g., `<summary_dir>/_post_inference_failure.json`) containing:
- `script_name`, `rc`, `stderr_tail` (last 50 lines), `argv`, `cwd`, `wall_time_seconds`
Then logs to stdout + sets `InferenceResult.failed = True`. Helper does NOT raise (post-hook is best-effort). Helper does NOT silently swallow.

### C4 — Worker resource snapshot
Per memory `feedback_no_silent_swallow.md`: if the helper is invoked from a worker context (e.g., subprocess pool), it relies on a module-global snapshot taken at worker `initializer=` time (sys.path, cwd, env) — not on reading live globals at job time. Test verifies behavior under worker context (synthetic worker → assert resource snapshot used).

### C5 — Inject-bug TDD
Tester:
- Inject a script-not-found bug (point `INFER_PAYTABLE_SCRIPT` to nonexistent path) → assert diagnostic file appears on disk + log message visible
- Inject silent-swallow bug (helper wraps subprocess call in `try/except: pass`) → assert C3 test goes red
Document both.

### C6 — Subprocess-mode end-to-end
Per memory `feedback_perf_claim_needs_e2e_event_stream.md`: impl-verifier spawns virtual_analyzer.py as a real subprocess against M14 mode 1 fixture; observes post-inference call happens (via file system trace or log inspection).

### C7 — Regression test template
Per memory `feedback_no_silent_swallow.md`: tests live at `tests/backend/test_post_inference_canonical.py` modeled on `tests/backend/test_batch_worker_post_hook.py` (the precedent regression test for this exact failure mode).

---

## §4 Out of scope

- Adding new inference scripts
- Changing inference script invocation order
- Adding a UI for inference failures (file-on-disk + log is sufficient per the memory)

---

## §5 Rollback path

Single commit. `git revert <sha>` restores both local implementations.

---

## §6 Risk + rollback notes

**Risk class**: MEDIUM. Subprocess paths + best-effort post-hook semantics; easy to introduce silent-swallow regression.

**Dependency**: none functional. P1-A2 parity test stays green throughout.

**Critic-flag pattern**: per memory `feedback_dont_swallow_errors_in_fix.md`: if implementer wraps the new helper in `try/except: pass`, critic REJECTS.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — extracts helper + updates 2 callsites
- `impl-tester` — writes regression modeled on `test_batch_worker_post_hook.py`; verifies inject-bug for both script-not-found AND silent-swallow regressions

### Wave 2 (parallel)
- `impl-verifier` — spawns real virtual_analyzer subprocess against M14 fixture; asserts post-inference call happens; verifies diagnostic file path on failure; runs full pytest
- `impl-critic` — checks: any `try/except: pass` introduced? Diagnostic file format matches memory template? Worker resource snapshot pattern used (not live global reads)?

Expected wall time: ~45-60 min (subprocess testing slower).
