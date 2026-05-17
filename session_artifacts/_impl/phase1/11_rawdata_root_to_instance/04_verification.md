# 04_verification.md — P1-B6 RAWDATA_ROOT global -> instance attribute

**Verdict: FAIL**

The implementer documented the fix in 02_implementation.md but the actual code change was never applied to src/web_console/backend/app.py. The prod bug is still present in the working tree.

---

## Current test state: 18 green / 2 RED on test_rawdata_root_split_path.py

Command:
    python -m pytest tests/backend/test_rawdata_root_split_path.py -v --tb=short

Result: 2 failed, 18 passed in 0.41s

Failures:
- TestStartBatchUsesInstanceRoot::test_start_batch_check_rawdata_status_receives_instance_root FAILED
- TestStartBatchProdBugGuard::test_start_batch_scans_injected_root_not_module_global FAILED

Exact failure message (primary prod-bug guard):
  AssertionError: start_batch called check_rawdata_status with rawdata_root=None
  instead of virtual_rawdata.
  The prod bug (P1-B6 original line 3259) is still present:
  start_batch is not passing self._rawdata_root.

---

## Implementer claim: "only 1 real bug" — analysis correct, fix NOT APPLIED

The implementer analysis in 02_implementation.md is accurate. There is exactly 1 functional bug
at app.py:3393. The analysis of all other 10 refs is correct. However the code fix was never
committed to app.py.

Evidence:
1. git status shows src/web_console/backend/app.py is NOT in the modified files list.
   Only slot_designer/configs/machines_virtual.json is modified. The test file
   tests/backend/test_rawdata_root_split_path.py is untracked (new).
2. git log --oneline -10 shows no P1-B6 commit. HEAD is:
   f4fb94d refactor(slotlab): P1-B5 dedup post-inference trigger to fresh_slotlab/post_inference.py
3. Direct read of app.py:3393 confirms:
     raw_status = check_rawdata_status(it.machine, it.mode)
   No rawdata_root argument. Bug is live.

---

## End-to-end checks

### E1 — Prod bug at app.py:3393 GENUINELY FIXED: NO

Command: python -m pytest tests/backend/test_rawdata_root_split_path.py::TestStartBatchProdBugGuard::test_start_batch_scans_injected_root_not_module_global -v
Observed: FAILED
Expected (post-fix): PASSED

Bug: app.py:3393 reads:
    raw_status = check_rawdata_status(it.machine, it.mode)

Required fix (per 02_implementation.md):
    raw_status = check_rawdata_status(
        it.machine, it.mode,
        rawdata_root=self._rawdata_root,
        machines_config=self._machines_config,
    )

### E2 — C1 ref enumeration (10 refs + 1 declaration): ANALYSIS VERIFIED, FIX ABSENT

All 10 non-bug refs confirmed via grep:
- Line 528: module-level declaration (C6 backward-compat default) — correct, kept
- Line 721: check_rawdata_status — already has fallback pattern
- Line 1198: delete_rawdata — already has fallback pattern
- Line 3321: BatchRunManager.__init__ — already stores to self._rawdata_root
- Line 3393: check_rawdata_status call — BUG: no rawdata_root arg passed
- Lines 3902, 4939, 7615, 8861, 8902: all comments/docstrings — no change needed
- Line 5452: create_app — already has fallback pattern

Implementer claim of "only 1 real bug" is correct. But fix is not in the file.

### E3 — C2 Split-path regression tests: PASS

test_batch_manager_stores_injected_rawdata_root: PASSED
test_batch_manager_rawdata_root_independent_of_global_mutation: PASSED
(Constructor already stores self._rawdata_root correctly. These were GREEN before the ticket.)

### E4 — C5 _recover_orphan_running_runs safety: PASS

Commands:
  python -m pytest tests/backend/test_rawdata_root_split_path.py::TestRecoverOrphanRunningRuns -v
Both tests PASS:
- test_recover_orphan_does_not_crash_with_bad_rawdata_root: PASSED
- test_recover_orphan_source_does_not_reference_rawdata_root_global: PASSED

RunManager._recover_orphan_running_runs confirmed to use only DB + PID operations,
no rawdata coupling. C5 satisfied independently of fix status.

### E5 — C6 Module-level RAWDATA_ROOT preserved: PASS

test_rawdata_root_module_constant_exists: PASSED
test_rawdata_root_is_path_instance: PASSED
test_rawdata_root_default_set_from_env_var: PASSED
Module-level global at line 528 preserved as backward-compat default.

### E6 — Virtual app architecture verified: PASS (architecture correct, bug in call chain)

slot_designer/core/backend/virtual_app.py:187-199 confirms build_virtual_app() calls
create_app(rawdata_root=VIRTUAL_RAWDATA_ROOT, ...) — wires instance root correctly.
However BatchRunManager.start_batch then calls check_rawdata_status without passing
self._rawdata_root, causing the module global to fire. This is the exact virtual-console
incident documented in the ticket.

### E7 — C4 Subprocess smoke: NOT RUN

Deferred per tester. In-process tests conclusively prove the bug is present and the fix
is absent. Subprocess confirmation is not needed to reach FAIL verdict.

---

## Subprocess vs in-process coverage

Layer                        | Coverage                                  | Verdict
In-process unit (spy/mono)   | 20 tests — structural invariants + guards | 18 PASS / 2 FAIL
Subprocess virtual_app       | Not run — deferred per tester             | N/A

---

## Full pytest regression suite

Command: python -m pytest tests/backend/ tests/integration/ -v --tb=line -q
Result: 6 failed, 2398 passed, 23 skipped, 2 xfailed, 5 warnings in 128.57s

Failures:

Test                                                                    | Cause                                | Pre-existing
test_analyzer_st_split::test_zero_win_but_fired_pid_retained_in_split  | Missing fixture rawdata/M31/...      | YES
test_rawdata_root_split_path::test_start_batch...receives_instance_root | P1-B6 prod bug not fixed             | NO (new test)
test_rawdata_root_split_path::test_start_batch...not_module_global      | P1-B6 prod bug not fixed             | NO (new test)
test_t_critical_table_canonical::test_c1_player_impact...               | Test-ordering isolation (pre-existing)| YES
test_t_critical_table_canonical::test_c1_virtual_analyzer...            | Test-ordering isolation (pre-existing)| YES
test_t_critical_table_canonical::test_c6_split_path...                  | Test-ordering isolation (pre-existing)| YES

Regressions in untouched areas: 0
New failures caused by this ticket: 0 (the 2 RED tests are NEW tests correctly detecting the pre-existing bug)

---

## Stop reason: FAIL — fix not applied to source

The implementer described what needs to happen but did not write the change to app.py.

Required action: Apply the following change to src/web_console/backend/app.py:3393:

BEFORE (line 3393):
    raw_status = check_rawdata_status(it.machine, it.mode)

AFTER:
    raw_status = check_rawdata_status(
        it.machine, it.mode,
        rawdata_root=self._rawdata_root,
        machines_config=self._machines_config,
    )

After applying, run:
    python -m pytest tests/backend/test_rawdata_root_split_path.py -v
Expected: 20/20 PASSED
