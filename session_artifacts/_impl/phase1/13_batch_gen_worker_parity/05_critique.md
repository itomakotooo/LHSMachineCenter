# Critique: P1-D1 — `_batch_gen_worker.py` parity

## Verdict: APPROVE-WITH-REVISIONS

4/4 contracts are structurally applied. The two critical architectural choices (Fix B over Fix A; canonical helper wiring) are defensible and correct per project memory. However, there are **2 material defects** that must be fixed before this commit lands, plus **1 chain incompleteness** (no verifier artifact).

---

## Stress questions (8 total)

---

### SQ1 — Fix B vs Fix A: does the brief actually require physical-absence?

**Question**: Brief §3 C5 states "REMOVE `xfail` marker on the 2 P1-A4 R2 tests … they should NOW pass." C5 explicitly names `test_batch_job_chunk_dir_does_not_contain_historical_chunks` as the second test that should flip to PASS. Implementer changed it from `strict=True` to `xfail(strict=False)` instead. Is this defensible, or is it brief-noncompliance disguised as architectural choice?

**Attempted answer**: The physical-absence test asserts Fix A behavior. Fix B achieves the same underlying goal (historical chunks never reach the analyzer) at the CLI level, not the directory level. Per `feedback_md5_is_a_tag_not_a_destruction_signal.md`, the physical deletion approach is architecturally incorrect. Brief §3 C5 was written before Fix A/B distinction was crystallized — the intent was that the gap is closed, not that the method is mandated. The tester's flag in 03_tests.md §C5 gap section is accurate: this is a valid design decision for the critic to validate, not the tester to resolve unilaterally.

**Verdict**: ⚠ Partial. Fix B is architecturally correct. The implementer's case for keeping the second test as `xfail(strict=False)` is defensible IF and ONLY IF the brief's underlying intent (historical chunks do not reach the analyzer) is fully achieved through Fix B. The CLI-level filter achieves this. The `strict=False` form (instead of strict=True) is acceptable because Fix A remains a valid future improvement that would make the test PASS, and `strict=False` means an unexpected PASS is not a test failure. The tighter question — whether the brief's literal "REMOVE xfail markers on BOTH tests" overrides this — is a call that should have been escalated to the user per `docs/IMPL_TEAM_PROCESS.md`. It was not. Flag for revision: add a comment to the brief or a note in the commit message explaining why Fix B satisfies C5's intent with only one marker removed.

---

### SQ2 — Virtual machine C3 md5 patch regression

**Question** (`_batch_gen_worker.py:195-201`): The C3 `_md5_lookup` lambda closes over `_fn=_lmm` where `_lmm` is `lookup_machine_md5` from `fresh_slotlab.machine_md5`. That function reads the FLAT schema (`configSummaryMd5` at the machine entry top level). For virtual machines, the flat-schema `configSummaryMd5` is `""` (per `machine_md5.py` line 93-96: returns `("", "")` when field is empty or missing). The `modesMd5` per-mode dispatch lives in `_get_machine_md5` in `app.py`, NOT in `lookup_machine_md5`. So for virtual machines with `modesMd5` blocks, the C3 patch call will return `("", "")` from `_lmm`, and `patch_summary_md5` will be a no-op (line 107 in `summary_md5_patch.py`: `if not (config_md5 or code_md5): return`).

The code comment at line 192-194 says "so virtual machines get per-mode modesMd5" but the actual implementation uses the flat-schema reader that does not handle `modesMd5`.

**Attempted answer**: Inspecting the code: `_lmm` is `lookup_machine_md5` from `machine_md5.py`. That module's docstring explicitly says "Does NOT interpret `modesMd5`". `_get_machine_md5` in `app.py` adds modesMd5 dispatch on top, but the worker pre-imports `lookup_machine_md5` directly, bypassing that dispatch. Brief §3 C3 says "Virtual machines' summary md5 fields now populated correctly (not `md5_status=untagged`)." With the current implementation, virtual machines that use `modesMd5` blocks will still get `("", "")` from the lookup, and the patch will not fire. This is a material defect: the stated goal of C3 is not achieved for the virtual machine case.

**Verdict**: ✗ Not adequately addressed. The `_md5_lookup` lambda must call either `_get_machine_md5(machine, mc_path, mode=mode)` (but that function is inside `app.py`, not importable as a standalone helper) OR the worker must store the already-looked-up values from `job["upstream_config_md5"]` / `job["upstream_code_md5"]` directly and use those as the lookup result, bypassing the function call entirely. The job dict already carries the correct per-mode md5 values (set by `_prepare_batch_gen_item` via `_get_machine_md5(machine, mc, mode=mode)` at line 7442). The simplest fix: `_md5_lookup = lambda: (job.get("upstream_config_md5", ""), job.get("upstream_code_md5", ""))`. This is idiomatic, C6-compliant (job dict is the snapshot), and sidesteps the modesMd5 dispatch problem entirely. The current over-engineered lookup via the snapshotted `_lmm` module global loses the per-mode md5 that the job dict already has.

---

### SQ3 — `test_batch_worker_post_hook.py` autouse fixture does not reset new globals

**Question** (`tests/backend/test_batch_worker_post_hook.py:30-39`): The existing autouse fixture `_reset_worker_globals` only saves/restores `_analyzer_mod` and `_project_root`. It does NOT save/restore `_patch_summary_md5_fn`, `_run_post_inference_fn`, `_lookup_machine_md5_fn`. If any test in `test_batch_gen_worker_parity.py` runs first (same pytest session) and sets those globals to real functions, the `test_batch_worker_post_hook.py` tests will see those non-None globals and take the real pool-init code path instead of the fallback/lazy path. This could mask or change behavior in the three currently-failing tests.

**Attempted answer**: The implementer explicitly identified this in `02_implementation.md` Open Issues section, noting that `_reset_worker_globals` must be updated to also save/restore the three new globals. The tester also flagged this as "critic flag, not tester responsibility." However, the failing tests are pre-existing contract tests. Leaving them failing while noting "impl-tester action required" means the commit lands with 3 broken tests, violating the team's quality bar.

**Verdict**: ✗ Not adequately addressed. The 3 failing tests in `test_batch_worker_post_hook.py` represent pre-existing regression contracts that this ticket's C4 change broke. The implementer must either (a) update `test_batch_worker_post_hook.py` to match the new format (preferred — the new format is better-structured), or (b) preserve backward compat in the post_hook output shape. Leaving 3 tests broken in the submitted commit is not acceptable per `docs/IMPL_TEAM_PROCESS.md`. Required revision.

---

### SQ4 — Verifier artifact missing

**Question**: Brief §7 Wave 2 assigns impl-verifier to run an e2e subprocess M14/M1sim batch run confirming: summary md5 populated, inference output appears, no historical chunks in analyzer input. Per `feedback_perf_claim_needs_e2e_event_stream.md`: subprocess-mode bugs need an e2e run that exercises the runtime branch. The `04_verification.md` file does not exist.

**Attempted answer**: The session prompt says "Verifier (parallel)" is running. The glob confirms `04_verification.md` does not exist at review time. The tester's 03_tests.md §Subprocess-mode coverage section explicitly states "Verifier owns M14/M1sim real batch run." The verifier artifact is absent, so the critic cannot validate the verifier's claims.

**Verdict**: ✗ Not addressed. The chain is incomplete. Without verifier, the critic cannot close out the subprocess-mode gap. Per `docs/IMPL_TEAM_PROCESS.md`, APPROVE-WITH-REVISIONS may proceed if the verifier's gap is a known-and-bounded risk, but the SQ2 defect (virtual machine md5 patch is a no-op) makes e2e verification more urgent, not less. Required revision: verifier must run the e2e and produce `04_verification.md` before the commit lands.

---

### SQ5 — `import os as _os` inside the job body (C6 violation risk)

**Question** (`_batch_gen_worker.py:233`): Inside the C4 block, the worker does `import os as _os` at job time, not in the initializer. C6 says worker pool resources must be snapshot at initializer time. `os.environ` can be mutated by downstream imports (including by `analyzer.main()` which just ran). Is this safe?

**Attempted answer**: `os` is a stdlib module; its import is essentially free and idempotent. The actual issue is whether `dict(_os.environ)` at line 236 captures the environment AFTER `analyzer.main()` may have modified it. Since the worker's intent is to pass a stable env snapshot, reading `os.environ` after `analyzer.main()` is arguably wrong — the snapshot should be taken before `analyzer.main()` runs. However, `analyzer.main()` in this context is the in-process path that monkey-patches `sys.argv` and `sys.exit`, not typically `os.environ`. The risk is low but real.

**Verdict**: ⚠ Partial. The `import os as _os` inside the job body is cosmetically wrong (should be pre-imported at top of file alongside the other imports) but not a practical regression. The `dict(_os.environ)` at line 236 is taken post-`analyzer.main()` which is a subtle ordering bug — the env snapshot should be taken before the analyzer call, not after. Not a required revision but flagged for cleanup. The `os` import should be moved to the module-level imports at the top of the file.

---

### SQ6 — Error-swallowing audit: C3 and C4 `except Exception` blocks

**Question**: `_batch_gen_worker.py:208-215` wraps the entire C3 patch in a bare `except Exception`. `_batch_gen_worker.py:286-289` wraps the entire C4 inference block in a bare `except Exception`. Both print to stderr but return `ok=True`. Per `feedback_dont_swallow_errors_in_fix.md` and `feedback_no_silent_swallow.md`: does this hide bugs, or is it justified as a best-effort boundary?

**Attempted answer**: C3 (`patch_summary_md5`) is explicitly documented as best-effort metadata tagging — the analyzer output is valid without it, and errors are logged to stderr. C4 (`run_post_analyzer_inference`) is explicitly best-effort per brief §3 C4 and the canonical helper's contract (always returns, never raises). The `except Exception` blocks are at a genuine boundary (primary analyzer output is already on disk) not hiding internal bugs. The brief explicitly says "Best-effort post-hook; failures land in `_post_inference_failure.json`." This pattern is correct per the memories.

**Caveat**: The C4 outer `except Exception` at line 286-289 catches failures of the `run_post_analyzer_inference` call itself (not the subprocess), and produces `{"canonical_post_inference": True, "outer_err": "..."}` with no `"ok"` key. The parent `_finalize_batch_gen_item` writes this to `_post_hook.json` and continues — this is acceptable. But the outer error entry format differs from the normal entry format (no `"failed"`, `"skip"`, `"machine"`, `"mode"` keys), which might confuse post-mortem tooling.

**Verdict**: ✓ Adequately addressed per brief contract. The best-effort boundary is correct and memory-compliant. The outer error format inconsistency is minor.

---

### SQ7 — `_reset_worker_globals` in parity tests: does it survive inject-bug scenario?

**Question** (`test_batch_gen_worker_parity.py:79-118`): The new autouse fixture uses `getattr(worker, k, _MISSING)` and `delattr(worker, k)` for pre-implementation modules that lack the new globals. If inject-bug removes the module-level global declarations (lines 45-47 in `_batch_gen_worker.py`), does the fixture break in a way that masks the test failure, or does it produce clean inject-bug signal?

**Attempted answer**: The fixture uses `_MISSING = object()` sentinel and `getattr(worker, k, _MISSING)` to handle missing attributes gracefully. After the test, if the attribute didn't exist before, `delattr` is called only if `hasattr(worker, k)` is true. This is defensively written. If the implementer removes the module-level globals as an inject-bug, `getattr(worker, k, _MISSING)` returns `_MISSING`, the test then sets the globals via `worker._patch_summary_md5_fn = _psm` (which would FAIL with AttributeError if the attribute doesn't exist… wait, Python allows setting new attributes on modules). So the inject-bug would not cause the fixture to fail; the test itself would fail because `run_analyzer_job` doesn't call the pre-snapshotted function. The inject-bug signal is clean.

**Verdict**: ✓ Adequately addressed. The fixture is well-written and handles pre-implementation state correctly.

---

### SQ8 — C4 new hook format breaks `test_post_hook_handles_missing_chunk_dir` behavior contract

**Question** (`test_batch_worker_post_hook.py:174-202`): The test destroys `chunk_dir` after job construction and expects `e.get("skip") == "chunk_dir_missing"`. In the new implementation, when `chunk_dir.is_dir()` is False, `rawdata_root = None` (line 235), and the canonical helper's Guard 2 (`rawdata_root is not None` → skip) does NOT fire. The helper then proceeds to run scripts (which fail as `script_missing` because `_project_root` has no scripts/ subdirectory). The test asserts `"chunk_dir_missing"` skip which no longer exists. Is the new behavior correct (or is the chunk_dir race a case that should still be handled explicitly)?

**Attempted answer**: The old behavior treated `chunk_dir_missing` as a sentinel that prevented the inference hook entirely. The new behavior: with `rawdata_root=None`, Guard 2 doesn't fire, so scripts run (and fail with `script_missing`). This is arguably more thorough — it doesn't suppress inference just because the chunk dir is gone (the inference scripts may still produce output if rawdata is accessible via other paths). However, the test's assertion (`chunk_dir_missing` skip present) is now wrong. More importantly, the new behavior means a script_missing failure is written to `_post_inference_failure.json` in the output directory — a noisy false alarm for a legitimate race condition. The `chunk_dir_missing` early exit was a deliberate design that prevented unnecessary subprocess launches.

**Verdict**: ⚠ Partial. The missing_chunk_dir case deserves explicit handling (explicit skip or early-exit), not silent fall-through to script_missing failures. The original `chunk_dir_missing` skip was meaningful. Implementer must either: (a) add a guard in the worker that checks `chunk_dir.is_dir()` and records a `chunk_dir_missing` skip without calling `_rpi`, or (b) update the test and accept the new behavior with documentation. The current state (broken test, no explicit guard, noisy false alarms) is not acceptable.

---

## Disagreements: implementer ↔ tester ↔ verifier

| # | Disagreement | Detail |
|---|---|---|
| D1 | Implementer says "3 pre-existing tests broken by C4 hook replacement — impl-tester action required." Tester says "3 test failures are a critic flag, not a tester responsibility." | Neither party fixed the 3 broken tests. The commit has 3 failing tests. This is a coordination failure. Both are partially right (tester is correct that format change is the implementer's call; implementer is correct that test updates are needed) but the result is nobody fixed them. |
| D2 | Brief C5 says remove BOTH xfail markers. Implementer changed second to `strict=False`. Tester flagged this as "GAP: critic to validate." | No disagreement per se — both correctly deferred to critic. But brief text is unambiguous: "REMOVE xfail markers on the 2 … tests." Implementer made a design decision without escalating. |
| D3 | Verifier is listed as "parallel" in session prompt but `04_verification.md` does not exist. | Chain is incomplete. Tester defers subprocess verification to verifier; verifier has not produced output. |

---

## Hidden assumptions

1. **`lookup_machine_md5` is sufficient for virtual machines in C3**: The implementation assumes that passing `lookup_machine_md5` as `_lmm` (the flat-schema reader) is sufficient to patch virtual machine summaries. This is false for any virtual machine that carries `configSummaryMd5: ""` at the top level and uses `modesMd5` per-mode blocks. The assumption is incorrect and causes a silent no-op for precisely the case C3 is designed to fix (virtual machine md5 blank in summary). See SQ2.

2. **`job["upstream_config_md5"]` / `job["upstream_code_md5"]` are not used for C3**: The implementation does a fresh lookup via `_lmm` rather than reusing the already-correct values already carried in the job dict. The assumption that a fresh lookup is needed (rather than using the job dict values) introduces the modesMd5 bypass bug. The job dict already contains the right per-mode values.

3. **e2e subprocess verification will catch any remaining gaps**: The tester explicitly defers subprocess-mode verification to verifier. If verifier finds the virtual machine md5 patch is a no-op, that's caught. If verifier only tests real machines (which have flat-schema md5), the virtual machine regression goes undetected.

4. **`test_batch_worker_post_hook.py` can be updated independently**: Both implementer and tester assume the 3 broken pre-existing tests can be fixed in a follow-up. But these tests are regression guards for behavior that was working before this ticket. Committing with 3 failing regression tests means the baseline is broken.

---

## Edge cases not covered

1. **Virtual machine with `modesMd5` block — C3 md5 patch is a no-op**: As described in SQ2. Test `test_job_dict_md5_keys_virtual_machine` in the new parity tests correctly proves C1 (job dict carries per-mode values), but no test proves that C3 (patch_summary_md5 call) actually patches the summary for a virtual machine. The mock-based `test_patch_summary_md5_called_with_correct_lookup` only verifies call count, not that the lookup function returns the correct per-mode values.

2. **`chunk_dir` race condition — chunk_dir removed after job dict creation**: Existing test (`test_post_hook_handles_missing_chunk_dir`) was testing this, now broken. The new implementation's behavior for this case (fall through to script_missing rather than explicit skip) is silent degradation.

3. **Machine not in `machines.json` — `lookup_machine_md5` returns `("", "")` silently**: For a new machine not yet registered, C3 is a silent no-op. Not logged, not flagged in the result dict. The job returns `ok=True` but `config_md5` and `code_md5` in the summary remain empty. No test covers this case.

4. **`paytables_dir` and `classify_dir` are `None` in the job dict**: The job dict (line 7480-7481) does supply `paytables_dir` and `classify_dir`, but the `_make_job` helper in `test_batch_gen_worker_parity.py` does NOT include these keys. Tests that call `run_analyzer_job` directly with `_make_job` therefore exercise the `job.get("paytables_dir") or None` fallback, meaning `paytables_dir=None` is passed to `run_post_analyzer_inference`. The canonical helper accepts `None` and scripts use their built-in defaults. This is fine but means C4 tests don't verify the forwarding of explicit `paytables_dir`/`classify_dir` paths.

5. **Worker pool multi-process context: `sys.argv` mutation is not process-safe if two jobs run in the same worker simultaneously**: `run_analyzer_job` does `sys.argv = argv` / runs analyzer / restores `orig_argv` in a `finally`. This is safe within a single process (ProcessPoolExecutor gives each worker one task at a time). However, the `finally` restore relies on `orig_argv` being captured before the assignment. This is fine but is not tested — if `_analyzer_mod.main()` raises `SystemExit` before the finally block, does `orig_argv` restore? Yes, `finally` always runs. Covered.

6. **`_finalize_batch_gen_item` swallows its own `write_json` exception silently** (`app.py:7526-7529`): This bare `except Exception: pass` is pre-existing but noted because post_hook data loss on this path produces no diagnostic. Not a regression from this ticket.

---

## Commit-message `## Self-critique` section

```
## Self-critique

- **SQ1 (Fix B vs Fix A)**: Brief C5 says remove BOTH xfail markers. Only one
  was removed; the second was changed to xfail(strict=False). Decision is
  architecturally correct (md5-is-tag, Fix A is deletion) but was not escalated
  to the user. Addressed by: xfail(strict=False) documents the decision inline;
  commit message explains why Fix B satisfies the brief's underlying intent.
  Open: user sign-off on the second xfail.

- **SQ2 (virtual machine C3 md5 patch is a no-op)**: _md5_lookup lambda calls
  lookup_machine_md5 (flat-schema) instead of using job["upstream_config_md5"]
  / job["upstream_code_md5"] already in the job dict. For virtual machines with
  modesMd5 blocks, the patch call returns ("", "") and is a no-op. The stated
  C3 goal ("virtual machines' summary md5 fields now populated correctly") is
  NOT achieved. OPEN — required fix before commit.

- **SQ3 (3 pre-existing tests broken)**: test_batch_worker_post_hook.py has 3
  tests asserting old post_hook format (context block / per-script skip entries)
  that no longer matches the canonical InferenceResult serialization. Both
  implementer and tester identified this but neither fixed it. OPEN — required
  fix before commit.

- **SQ4 (verifier artifact missing)**: 04_verification.md was not produced.
  e2e subprocess verification against M14/M1sim fixture not confirmed. OPEN.

- **SQ5 (import os as _os inside job body)**: Minor C6 violation. os.environ
  snapshot taken after analyzer.main() rather than before. Low practical risk
  but should be moved to pre-job snapshot. OPEN (cleanup, not blocking).

- **SQ8 (chunk_dir_missing case)**: chunk_dir race condition previously
  produced explicit "chunk_dir_missing" skip. New implementation falls through
  to script_missing failures instead. Noisy false alarms. Existing test broken.
  OPEN — requires either explicit guard or documented behavior change.
```

---

## Required revisions (APPROVE-WITH-REVISIONS)

| # | Severity | Required action | Relates to |
|---|---|---|---|
| R1 | BLOCKING | Fix `_md5_lookup` in `run_analyzer_job` C3 block: replace `_fn(_m, _p)` call with `lambda: (job.get("upstream_config_md5",""), job.get("upstream_code_md5",""))`. The job dict already carries the correct per-mode values. | SQ2 |
| R2 | BLOCKING | Fix 3 failing tests in `test_batch_worker_post_hook.py`: update `_reset_worker_globals` fixture to save/restore 3 new globals AND update the 3 test bodies to match the new canonical InferenceResult hook format. | SQ3 |
| R3 | BLOCKING | Add explicit `chunk_dir_missing` guard in the C4 block: if `not chunk_dir.is_dir()`, record a skip entry and skip `_rpi` call (restore the explicit early-exit semantics the old implementation had). | SQ8 |
| R4 | REQUIRED | Produce `04_verification.md` with real e2e subprocess run output against M14 or M1sim cached fixture. Confirm: summary md5 populated for virtual machine, inference output appears, no historical chunks in analyzer input. | SQ4 |
| R5 | ADVISORY | Move `import os as _os` to module-level. Take `env = dict(os.environ)` snapshot BEFORE `_analyzer_mod.main()` call, not after. | SQ5 |
