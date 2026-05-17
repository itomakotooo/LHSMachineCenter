# 05_critique.md — P1-B6 `RAWDATA_ROOT` module global → instance attribute

**Ticket**: `session_artifacts/_impl/phase1/11_rawdata_root_to_instance/00_ticket.md`
**Critic date**: 2026-05-18
**Chain read**: 00_ticket.md + 02_implementation.md + 03_tests.md + direct source reads (app.py)
**04_verification.md**: DOES NOT EXIST — verifier has not run yet (this critique precedes Wave 2 verification)

---

## Verdict: REJECT

The implementer's single claimed fix — adding `rawdata_root=self._rawdata_root, machines_config=self._machines_config` to `check_rawdata_status(it.machine, it.mode)` at app.py line 3393 — **is not present in the actual source file**. The file still reads `check_rawdata_status(it.machine, it.mode)` with no injected arguments. The prod bug is unfixed. The commit did not land.

The test infrastructure (20 tests) is well-constructed and the two key prod-bug guards (`TestStartBatchProdBugGuard`, `TestStartBatchUsesInstanceRoot`) correctly go RED against the current buggy state. The injected-bug cycle described in `02_implementation.md` — "stash → RED, apply fix → GREEN, re-stash → RED" — is internally consistent, but the final state (fix landed) is not what the working tree shows.

Additional structural concerns are documented in the stress questions below.

---

## Stress Questions

### Q1 — Is the fix actually committed to the working tree? (FATAL)

**Question**: `02_implementation.md` §"Files changed" claims `app.py line 3393` was changed to pass `rawdata_root=self._rawdata_root, machines_config=self._machines_config`. Did the implementer actually commit/apply this change?

**Investigation**: Direct read of `src/web_console/backend/app.py` at line 3393:

```python
            raw_status = check_rawdata_status(it.machine, it.mode)
```

No `rawdata_root` or `machines_config` arguments are present. The Grep for `check_rawdata_status` returns 4 matches total; only the one at line 6102 passes `rawdata_root=rd_root`. Line 3393 is still the unfixed call site.

**Attempted answer**: The implementer described the fix accurately in the implementation doc, including an inject-bug verify cycle. However the actual source file does not reflect the fix. The most likely explanation is the implementer performed the verification on a local stash/apply cycle and reported the results, but then did not commit the final application of the fix before the worktree was snapshotted for this review pass. Alternatively, an error in the apply step reverted the file silently.

**Verdict**: FAIL. The core deliverable of this ticket — the single functional fix — is absent from the working tree. All the test infrastructure correctly guards this fix, but the fix is not there. This is a REJECT-level defect; the ticket cannot APPROVE without the actual code change being present.

---

### Q2 — Is the per-line audit of the "9 non-bug" refs credible? (CRITICAL NUANCE)

**Question**: The implementer claims 9 of the 10 functional refs in the brief were already correct (either fallback pattern or comment-only). Is this correct?

**Investigation**: Independent source reads confirm:

| Brief ref | Actual line | Actual content | Critic finding |
|---|---|---|---|
| L49 | 49 | `RAWDATA_ROOT_DEFAULT = ROOT / "rawdata"` | Constant declaration — not a functional ref. Correct. |
| L165 | ~142 | `env["SLOT_RAWDATA_ROOT"] = str(rawdata_root)` | Passes the injected param; subprocess env injection. **But wait** — the Grep for `env["SLOT_RAWDATA_ROOT"]` returns NO matches. The actual text at line ~142 is unrelated code (`_summary_path` handling). The implementer may have misidentified this ref. PARTIAL CONCERN — the subprocess env injection is likely elsewhere; brief's line estimate was off. |
| L518 | 528 | `RAWDATA_ROOT = Path(os.getenv(...))` | Module declaration. Correct. |
| L695 | 721 | `root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` | Fallback pattern. Confirmed correct at source. |
| L1064 | 1198 | `root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` | Fallback in `delete_rawdata`. Confirmed correct. |
| L3187 | 3321 | `self._rawdata_root = (rawdata_root if rawdata_root is not None else RAWDATA_ROOT)` | Constructor stores injected root. Confirmed correct. |
| **L3259** | **3393** | `check_rawdata_status(it.machine, it.mode)` | **THE BUG — NOT FIXED** |
| L4805 | 4805 | Comment in `_resolve_upstream_machine_name` docstring | Comment only. Confirmed. |
| L5318 | 5452 | `rd_root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` | Fallback in `create_app`. Confirmed correct. |
| L7489 | 7615 | `scope=all_with_rawdata walks RAWDATA_ROOT` | This is a docstring/comment. Confirmed comment. |
| L8735 | 8861 | Comment in `cache_status` docstring | Comment. Confirmed. |
| L8776 | 8902 | Comment in `cache_cleanup` docstring | Comment. Confirmed. |

For the L165 subprocess env ref: Grep for `SLOT_RAWDATA_ROOT` in app.py would be needed but the brief claims it is at ~line 165. The actual content at line 142 is `_summary_path` handling, not subprocess env injection. This is a mismatch the implementer didn't flag — the actual subprocess env injection may be elsewhere or the brief's line count was wrong. This deserves a separate audit by the verifier.

**Verdict**: PARTIAL. The core "9 non-bugs" claim is mostly correct for refs that CAN be verified (721, 1198, 3321, 5452, 4805, 8861, 8902). The L165 subprocess env ref claim needs independent verification. The fatal issue remains Q1.

---

### Q3 — Is `test_check_rawdata_status_uses_passed_root_not_global` a genuinely discriminating test?

**Question**: The test at `TestSplitPath::test_check_rawdata_status_uses_passed_root_not_global` (test file line 154) patches `RAWDATA_ROOT` to `SENTINEL_WRONG_ROOT` and then calls `check_rawdata_status(machine, mode, rawdata_root=real_rawdata)`. It asserts only `isinstance(result, dict)`. Can this test distinguish "used the injected root" from "fell through to the nonexistent sentinel"?

**Investigation**: Looking at `check_rawdata_status` line 721-724:
```python
root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT
mode_dir = root / machine / f"mode_{mode}"
if not mode_dir.is_dir():
    return _empty_rawdata_status()
```

`_empty_rawdata_status()` returns a dict with `{"exists": False, "usable_chunks": 0, ...}`. If the bug were present (ignoring `rawdata_root` param, using `SENTINEL_WRONG_ROOT`), the `mode_dir` would not exist, and the function would return `_empty_rawdata_status()` — which is also a dict. The test asserts `isinstance(result, dict)`, which passes in BOTH the correct case AND the buggy case.

The test has a real chunk at `mode_dir` in `real_rawdata`, but it does not assert that the result has `usable_chunks > 0` or that `mode_dir.is_dir()` was consulted in the right location. The only assertion that distinguishes correct from buggy behavior would be checking `result["usable_chunks"] > 0` or `result["exists"] == True` — neither of which is done.

**Verdict**: FAIL (structural weakness). The test `test_check_rawdata_status_uses_passed_root_not_global` does not discriminate between correct path and bug path. It would pass whether or not the function uses the injected root. This violates the inject-bug discipline in memory `feedback_enumerate_safety_paths.md`. Experiment 3 in `03_tests.md` acknowledges the inject-bug simulation but does not confirm the test actually catches it (because the "crash" they predict doesn't occur — `_empty_rawdata_status()` is returned instead). The inject-bug claim for this ref is incorrect.

---

### Q4 — `_recover_orphan_running_runs` (C5): does `test_recover_orphan_does_not_crash_with_bad_rawdata_root` actually exercise the function?

**Question**: The test at line 493 creates a `RunManager`, checks `rm._startup_recovery`, and asserts `recovered_count == 1`. But `_startup_recovery` is set in `__init__` at line 4797: `self._startup_recovery = self._recover_orphan_running_runs()`. Does the `insert_run_row` call at line 509 (after the `RunManager` constructor) affect the result?

**Investigation**: The test inserts the stale row at line 509, but the `RunManager` constructor at line 514-521 runs `_recover_orphan_running_runs` during `__init__`. The `insert_run_row` happens BEFORE `RunManager(...)` is constructed — reading the test from line 506:

```python
db_path = tmp_path / "state" / "console.db"
db_path.parent.mkdir(parents=True, exist_ok=True)
store = StateStore(db_path)
# Inject a stale running row using the seed helper.
insert_run_row(db_path, run_id="stale_c5_001", status="running", process_pid=12345)

...
rm = RunManager(
    store,
    ...
)
result = rm._startup_recovery
```

The seed happens at line 509 (before `RunManager` is constructed). `RunManager.__init__` calls `_recover_orphan_running_runs` which reads `store.list_runs_by_status("running")`. But the `StateStore` at line 507 and the direct sqlite3 write at line 509 operate on the same `db_path`, so the row should be present when the constructor reads it. The assertion `recovered_count == 1` should be correct.

However: the `machines_config` at line 519 is `tmp_path / "machines.json"` which does not exist. `RunManager.__init__` may require this file. Whether this causes a constructor failure or is handled gracefully needs checking.

**Verdict**: PARTIAL. The ordering looks correct. The `machines_config` nonexistent-file concern is minor if `RunManager` lazy-loads it. The more fundamental C5 check — the static source inspection test at line 529 — is solid and does correctly verify `_recover_orphan_running_runs` has no `RAWDATA_ROOT` reference (confirmed independently).

---

### Q5 — `test_start_batch_auto_cleanup_uses_instance_root` has a timing race

**Question**: The test at `TestStartBatchUsesInstanceRoot::test_start_batch_auto_cleanup_uses_instance_root` (line 316) calls `bm.start_batch(req)` (which spawns a background thread), then polls `received_cleanup_roots` for 3 seconds. If the cleanup loop does NOT fire within 3 seconds, the test silently passes — because of the `if received_cleanup_roots:` guard at line 377.

**Investigation**: Lines 377-383:
```python
if received_cleanup_roots:
    for root in received_cleanup_roots:
        assert root == injected, ...
```

This means: if the cleanup spy is NEVER called, the test passes unconditionally. The test would pass on a machine where the disk-pressure logic doesn't fire within 3 seconds, OR on a slow CI runner, OR if the background thread terminates early before reaching the cleanup check. This is a silent-false-positive scenario.

The disk condition is simulated via `_fake_disk_info` returning `free_gb=0.5` and `monkeypatch.setenv("SLOT_DISK_WAIT_RETRIES", "1")`. Whether `SLOT_DISK_WAIT_RETRIES` is actually read by the code to limit retries — or whether it's a different env var name — is not verified in the test.

**Verdict**: FAIL (structural weakness — timing race with unconditional pass on timeout). The test should assert `assert received_cleanup_roots, "cleanup spy was never called"` to catch the case where the thread never reached the cleanup path. The current conditional guard means the test provides zero coverage when the path is not exercised.

---

### Q6 — `delete_rawdata` fallback ref omitted from `TestPerRefFallbackPattern` (C3 partial)

**Question**: `03_tests.md §"Open gaps"` explicitly states that `delete_rawdata` (line ~1198) was excluded from `TestPerRefFallbackPattern` because "it triggers actual disk deletions and needs a more complex fixture". Is this omission acceptable?

**Investigation**: The brief (§3 C1) lists line 1064 (actual line 1198) as a functional ref requiring verification. The tester excluded it by design. The inject-bug simulation in `03_tests.md` Experiment 3 only covers `check_rawdata_status`, not `delete_rawdata`.

The `delete_rawdata` function has the same `root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` fallback pattern (confirmed at line 1198). When called from the route at line 6410, it receives `rawdata_root=rd_root` (the injected value from `create_app`). So it is functionally correct. But unlike `check_rawdata_status`, there is no per-ref inject-bug test for it.

This is a legitimate C3 gap. The brief's C3 contract requires inject-bug verification per migrated ref. The tester acknowledges the gap. Since `delete_rawdata` was not actively migrated (it was already correct before this ticket), the risk is lower, but it is still a stated contract gap.

**Verdict**: PARTIAL (documented gap; functionally low-risk because the call site at line 6410 already uses `rd_root` correctly, but C3 is formally incomplete).

---

### Q7 — No `04_verification.md` exists: C4 virtual-console subprocess smoke is fully unverified

**Question**: Brief §3 C4 requires the verifier to spawn `virtual_app` as a subprocess and confirm rawdata writes land in `VIRTUAL_RAWDATA_ROOT`, not `RAWDATA_ROOT`. No verifier has run yet. Is this gap appropriately documented and does the Wave 2 design ensure it will be covered?

**Investigation**: Neither `02_implementation.md` nor `03_tests.md` dispute that C4 is deferred to verifier. The `03_tests.md §"Open gaps"` proposes `tests/integration/test_virtual_console_rawdata_isolation.py`. But:

1. No `04_verification.md` file exists — the verifier has not acted.
2. The brief says the verifier runs C4 as part of Wave 2 (alongside the critic). But the critic is reviewing a chain that is incomplete (verifier hasn't run).
3. If the verifier cannot run `virtual_app` (e.g., missing deps, no test mode), this escalation path says "escalate to main session" — but that's a vague handoff with no concrete owner.

Separately: C4 is also the only contract that tests the original production symptom (virtual batch writing to real rawdata tree). The in-process unit tests correctly guard the structural invariant (the argument is passed), but they do not verify that a real subprocess + real virtual_app uses the injected root at the OS level. Per memory `feedback_subprocess_import_suicide_and_module_globals.md`, the original bug was a subprocess import side-effect; unit-level spies can miss subprocess-specific failure modes.

**Verdict**: FAIL (C4 is completely unverified — verifier has not run, no test file exists, and the Wave 2 coordination assumption has not been executed).

---

### Q8 — Brief stated `RAWDATA_ROOT` global REMOVAL as an option (§3 C6); implementer chose preservation without full analysis of residual risk

**Question**: Brief §3 C6 gave the implementer a choice: keep `RAWDATA_ROOT` as backward-compat default OR delete it entirely (forcing all callers to pass param). The implementer chose to keep it. Is this decision justified, and does the remaining global create ongoing risk?

**Investigation**: The implementer's rationale (02_implementation.md §"Module-level RAWDATA_ROOT decision"): "No functional codepath reads it directly without the fallback pattern." This is claimed to be true post-fix — but since the fix is not in the working tree (Q1), line 3393 is still a direct read that bypasses the fallback. If the fix were applied, the claim would be correct.

More importantly: the fallback pattern `rawdata_root if rawdata_root is not None else RAWDATA_ROOT` at lines 721, 1198, 5452 means any caller that passes `rawdata_root=None` silently falls back to the module global. For `check_rawdata_status` and `delete_rawdata` as free functions called from route closures inside `create_app`, the closures do inject `rd_root` (confirmed at lines 6102 and 6410). But nothing prevents a future caller from accidentally calling `check_rawdata_status(machine, mode)` without the root arg and silently picking up the module global — exactly the bug this ticket was meant to prevent.

The brief's observation "keep... but ensure no functional code path reads it directly anymore — only used at module-init for setting `RawdataRootRegistry.DEFAULT` or similar" is NOT fully implemented. There is no `RawdataRootRegistry`; the global remains a live fallback trigger for any caller that omits the param.

**Verdict**: PARTIAL. The preservation decision is pragmatically reasonable given backward compat, but the residual risk of future accidental direct reads is not mitigated beyond the tests (which only guard the current call sites, not future ones).

---

### Q9 — `TestCreateAppWiresRawdataRoot` relies on `app_factory` fixture which may hide the real wiring

**Question**: `test_create_app_batch_mgr_rawdata_root_matches_param` and `test_create_app_batch_mgr_rawdata_root_is_not_module_global` both use the `app_factory` fixture. If `app_factory` injects the rawdata root itself (via `create_app(rawdata_root=tmp_rawdata)`), the test is verifying that `create_app` forwards the param — which it does at line 5452. But does this actually exercise the `BatchRunManager` constructor call inside `create_app`?

**Investigation**: `create_app` at line 5452 sets `rd_root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT`. The `BatchRunManager` constructor is called later with `rawdata_root=rd_root` (confirmed at lines ~5485-5510). The `app_factory` fixture passes `rawdata_root=tmp_rawdata` to `create_app`. So `app.state.batch_manager._rawdata_root` should equal `tmp_rawdata`. This wiring IS exercised by the test.

The test `test_create_app_batch_mgr_rawdata_root_is_not_module_global` also patches `RAWDATA_ROOT` to `SENTINEL_WRONG_ROOT` BEFORE calling `app_factory()`. Since the monkeypatch is applied before `create_app` is called, and `create_app` receives `rawdata_root=tmp_rawdata` explicitly, the fallback at line 5452 is bypassed (non-None value). This correctly tests that the instance attr is not the module global.

**Verdict**: PASS. The create_app wiring tests are sound.

---

### Q10 — `03_tests.md` inject-bug table for Experiment 3 is logically incorrect

**Question**: Experiment 3 in `03_tests.md` claims: "Inject-bug simulation: If line 721 was `root = RAWDATA_ROOT` (hardcoded): With RAWDATA_ROOT pointing at SENTINEL_WRONG_ROOT (nonexistent), the function would crash (`mode_dir = root / machine / ...` on nonexistent path) → Test asserts no crash and returns dict when real root is passed → would go RED."

**Investigation**: `Path` concatenation (`Path("/nonexistent") / "M14" / "mode_1"`) does NOT crash in Python — it returns a Path object pointing to a nonexistent location. The `mode_dir.is_dir()` call at line 723 returns `False` for a nonexistent path, and the function returns `_empty_rawdata_status()` (a dict) at line 724. No exception is raised. So the "crash" prediction is wrong. The test asserts `isinstance(result, dict)` — which is satisfied by `_empty_rawdata_status()` in the bug case. Therefore `test_check_rawdata_status_uses_passed_root_not_global` would NOT go RED in the inject-bug case.

The tester's inject-bug analysis for this reference is factually incorrect. The test does not discriminate the bug from correct behavior. This was also flagged in Q3 above.

**Verdict**: FAIL. The inject-bug claim for Experiment 3 in `03_tests.md` is wrong. The test would not go RED when the bug is injected. This is a C3 contract failure for the `check_rawdata_status` free-function ref.

---

## Chain Disagreements

### Disagreement 1 — Implementation claims fix is landed; source does not reflect it

`02_implementation.md` §"Split-path regression confirmation" reports both key prod-bug tests as PASSED after the fix. But the current source at app.py line 3393 still shows the unfixed call. If the tests were run after the fix and reported PASS, the fix was present at test-run time but absent now — meaning it was not committed or was subsequently lost/reverted.

This is an implementer ↔ source disagreement of the most critical kind.

### Disagreement 2 — Tester says "2 RED before impl-landing"; implementation claims those same 2 tests went GREEN after fix

`03_tests.md` table shows `TestStartBatchProdBugGuard` and `TestStartBatchUsesInstanceRoot` as RED before impl fix, GREEN after. `02_implementation.md §"Split-path regression confirmation"` confirms this. But since the fix is not in the working tree, any verifier running the tests now would see both tests as RED — the post-fix GREEN state reported in both documents is not reproducible from the current state.

### Disagreement 3 — Tester excludes `delete_rawdata` from C3 inject-bug table; brief C3 requires every migrated ref

`00_ticket.md §3 C3` says "tester writes one inject-bug experiment per migrated ref." `03_tests.md §"Open gaps"` omits `delete_rawdata` with a justification ("needs more complex fixture"). Since `delete_rawdata` was not actively migrated by this ticket (it was already correct), the omission is defensible but creates a formal C3 gap.

---

## Hidden Assumptions

1. **Fix-was-applied assumption**: Both implementer and tester assume the fix was applied to the working tree. The implementation doc describes it, the tests guard it, but the actual source file does not contain it. The entire chain rests on this unverified assumption.

2. **Subprocess env injection ref is safe**: `02_implementation.md` claims brief line L165 is "subprocess env `env["SLOT_RAWDATA_ROOT"] = str(rawdata_root)`" and marks it "SAFE AS-IS". However, a Grep for this string in app.py returns no matches, and the content at line 142 is unrelated. The actual location of this subprocess env injection has not been verified by the critic. If it does not exist or is elsewhere, the assumption "this ref is already correct" may be wrong.

3. **`SLOT_DISK_WAIT_RETRIES` env var assumption**: The cleanup test uses `monkeypatch.setenv("SLOT_DISK_WAIT_RETRIES", "1")`. If the code does not actually read this env var name, the monkeypatch does nothing and the disk retry loop may sleep longer than 3 seconds, causing the test to silently pass without exercising cleanup.

4. **`machines_config` path for RunManager construction in C5 test**: The C5 test constructs `RunManager(... machines_config=tmp_path / "machines.json")` where `machines.json` does not exist. If `RunManager.__init__` reads this file eagerly (not lazily), the test would raise `FileNotFoundError` during construction, not reaching `_recover_orphan_running_runs` at all. The test would then ERROR rather than PASS.

---

## Edge Cases Not Covered

1. **`start_batch` called with `reports_root` param overriding `REPORTS_ROOT`**: `start_batch` also reads `REPORTS_ROOT` via `rr = reports_root or REPORTS_ROOT` (line 3378). This is a second module global that is not injected through the instance. If `REPORTS_ROOT` is the wrong one for virtual consoles, the same bug pattern repeats. Not in scope for this ticket, but the test suite does not document this as a known gap.

2. **Concurrent `start_batch` calls**: The prod bug fires once per item in `req.items`. If two concurrent `start_batch` calls race on the same `BatchRunManager`, and the fix is applied, the injected root is correct for both. But no test covers concurrent access to `_rawdata_root` — though this is safe since `_rawdata_root` is set once in `__init__` and read-only thereafter.

3. **`BatchRunManager` constructed with `rawdata_root=None` (fallback to global)**: The `test_init_none_falls_back_to_rawdata_root_global` test verifies this. But in production, `create_app` always passes `rawdata_root=rd_root` (non-None). The fallback-to-global path in the constructor is only exercised if someone constructs `BatchRunManager` without the arg — a scenario not covered by any integration test.

4. **Virtual console import suicide scenario**: The original 2026-04-XX incident involved subprocess import running `_recover_orphan_running_runs` against the wrong tree. The C5 tests correctly verify the function doesn't touch `RAWDATA_ROOT`. But the import-side-effect path (module-top code running during subprocess import) is not separately tested here. The brief pointed to `feedback_subprocess_import_suicide_and_module_globals.md` for this; the C4 smoke test (unexecuted) was supposed to catch it.

5. **`check_rawdata_status` `machines_config` param not injected at line 3393**: The implementer's claimed fix passes both `rawdata_root=self._rawdata_root` AND `machines_config=self._machines_config`. The missing `machines_config` means `check_rawdata_status` uses `MACHINES_CONFIG` (another module global) at line 728: `up_config, up_code = _get_machine_md5(machine, machines_config, mode=mode)`. If virtual and real consoles use different machines configs, the MD5 classification is also wrong. The tests do not guard `machines_config` injection separately from `rawdata_root`.

---

## Required Revisions (specific, pointing to stress questions)

**REJECT reasons:**

1. **[Q1 — FATAL]** The single functional fix (adding `rawdata_root=self._rawdata_root, machines_config=self._machines_config` to `check_rawdata_status` at app.py line 3393) is not present in the working tree. The implementer must apply the fix and confirm it is committed before re-submission.

2. **[Q3 / Q10 — SERIOUS]** The inject-bug claim for `test_check_rawdata_status_uses_passed_root_not_global` is wrong — the test would pass even in the bug state because `_empty_rawdata_status()` returns a dict. The test must be strengthened to assert a discriminating property (e.g., `result["usable_chunks"] > 0` or `result.get("mode_dir_found") == True` or a directory-scan-count assertion). The inject-bug table in `03_tests.md` Experiment 3 must be corrected.

3. **[Q5 — SERIOUS]** `test_start_batch_auto_cleanup_uses_instance_root` must add `assert received_cleanup_roots, "cleanup spy was never called"` before the per-root assertion loop. The current `if received_cleanup_roots:` guard turns the test into a no-op when the cleanup path is not exercised within the 3-second deadline.

**Required before APPROVE (send back to implementer + tester):**

- Re1: Apply the fix (Q1). Confirm with `grep "rawdata_root=self._rawdata_root" src/web_console/backend/app.py` returning a hit at line ~3393.
- Re2: Strengthen `test_check_rawdata_status_uses_passed_root_not_global` to assert a discriminating result field (Q3/Q10).
- Re3: Remove the `if received_cleanup_roots:` guard and add a hard `assert received_cleanup_roots` (Q5).
- Re4: Verify the subprocess env injection ref (brief L165) actually exists in app.py and document its actual line number (Q2).

**Deferred (do not block this ticket, but document as open):**

- De1: C4 virtual-console subprocess smoke (Q7) — assign to verifier explicitly; do not let it fall through.
- De2: `delete_rawdata` inject-bug test (Q6) — document as known gap in ticket resolution note.

---

## Commit-message `## Self-critique` section

Paste verbatim into the commit body after Re1–Re4 revisions are applied:

```
## Self-critique

- Q1: Was the fix actually in the working tree when I committed?
  Addressed: Verified `check_rawdata_status(it.machine, it.mode, rawdata_root=self._rawdata_root, machines_config=self._machines_config)` appears at app.py line ~3393 via grep after commit. Previously the fix was described but not applied.

- Q2: Did I independently verify the subprocess env injection ref (brief L165) exists at the claimed line?
  Addressed: Grepped for `SLOT_RAWDATA_ROOT` assignment in app.py; found at line <N>; confirmed it uses the injected rawdata_root param, not the global.

- Q3/Q10: Is `test_check_rawdata_status_uses_passed_root_not_global` actually discriminating?
  Addressed: Test now asserts `result["usable_chunks"] > 0` (chunk created in real_rawdata; sentinel has no chunks) in addition to `isinstance(result, dict)`. Inject-bug simulation confirmed: reverting line 721 to `root = RAWDATA_ROOT` with global=SENTINEL_WRONG_ROOT yields `usable_chunks=0`; test fails as expected.

- Q5: Does `test_start_batch_auto_cleanup_uses_instance_root` silently pass when cleanup is never called?
  Addressed: Replaced `if received_cleanup_roots:` guard with `assert received_cleanup_roots, "cleanup spy was never called"`. Test now fails if the path is not exercised within the deadline.

- Q7: Is C4 (virtual-console subprocess smoke) adequately handled?
  Open: Deferred to verifier; documented in resolution note. If verifier cannot run virtual_app subprocess, escalate to main session.

- Q6: Is `delete_rawdata` missing from the inject-bug table acceptable?
  Open: Documented gap. `delete_rawdata` was not actively migrated by this ticket; the call site at line 6410 already passes `rawdata_root=rd_root`. Gap is lower-risk than C4.
```
