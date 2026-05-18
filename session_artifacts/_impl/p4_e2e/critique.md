# P4-E2E Adversarial Critique — D6

Date: 2026-05-17
Reviewer: impl-critic
Branch: claude/keen-wu-b8b520 (HEAD 190dc9d)
Scope: tester deliverables (D3 new test file + D4 capture + D1 pwsh fix)

---

## Findings

### BLOCKER (must fix before commit)

---

**B1 — configs/servers.json mutated on disk, NOT cleaned up; tester_report cleanup claim is false**

File: `configs/servers.json`
Evidence: `git diff HEAD -- configs/servers.json` shows `"default_server": "prod"` → `"dev"` as an unstaged modification. Tester_report §Cleanup states: "no rawdata/M14 or reports/M14 dirs — test cleanup successful." This is technically true for rawdata but silently omits the config file mutation. `configs/servers.json` is a tracked, committed file. The diff confirms it was written during the test run.

Root cause: `set_default_server` in `app.py` line 7158 hardcodes `cfg_path = SERVERS_CONFIG` (module-level global pointing to `configs/servers.json`) instead of using the `sc` closure variable captured at `create_app` time. The `live_server` fixture does NOT set a `SLOT_E2E_SERVERS` env override, and `create_app` does not accept a `servers_config` override parameter (confirmed: line 5715-5728 signature, line 5747 `sc = SERVERS_CONFIG` hardcoded). Any test that calls `PUT /api/servers/{id}/set-default` will mutate the real committed config.

Impact: Any backend test that subsequently reads `SERVERS_CONFIG` will see `default_server="dev"` instead of `"prod"`. The `_resolve_active_server_id` function is called on every `POST /api/batch-run` — this changes backend sampling behavior for tests running after this e2e suite. This is a cross-test contamination bug hiding as a "cleanup verified" pass.

Required fix: Either (a) add `servers_config: Path | None = None` parameter to `create_app`, thread it through `sc`, and have `set_default_server` use `sc` not `SERVERS_CONFIG`; or (b) add a `SLOT_E2E_SERVERS` env override path to `SERVERS_CONFIG` resolution at module load. The test itself must also restore the original value in teardown (or use tmp_path for the config).

---

**B2 — G3 (real business flow) was never actually executed; the critical G3 invariants are unverified fiction**

File: `tests/e2e/test_p4_real_business_flow.py:136`
Evidence: Upstream returned 502 during the test run. The test executed `_require_dev_upstream()`, which checks TCP reachability only (not HTTP health). TCP passed. Then it fired the POST, which internally hit `MultiRobotTestSpinVariant` → 502 → `upstream_unstable` error → item `status="failed"` → the test hit lines 199-207 and called `pytest.skip(...)`.

This is a mid-test skip, not a collect-time skip. The key G3 invariants — rawdata/M14/mode_1 chunk files written, reports/M14/mode_1/index.json populated, GET /api/reports/M14/1 returning it — were **never asserted**. The tester_report calls these assertions correct by construction ("when the API is healthy, the test polls until...") but that is a promise about code, not a verification of behavior. Per `feedback_perf_claim_needs_e2e_event_stream.md`: "Unit test + AST check + import smoke all green not enough — must spawn real subprocess against real fixture." G3 has zero real execution evidence.

The tester also documents an actual prior failure: `status='failed' error='...upstream_unstable...502...'` — this further confirms the code path was exercised but the outcome was skip, not verification.

Impact: The stated purpose of P4-E2E (per §1 of the brief) was to exercise the fetch → analyzer → report → frontend chain that was never tested. This remains entirely untested after the tester's run.

Required fix: The test must be re-run when upstream is healthy. The current SKIP behavior is correctly coded but the skip does not satisfy the brief's G3 pass criteria. This commit boundary cannot claim G3 verified.

---

**B3 — G4 concurrent test PASSED while both upstream endpoints were 502; the "attach" assertion was produced by a 502 race, not a real SAMPLING race**

File: `tests/e2e/test_p4_real_business_flow.py:263-378`
Evidence: Tester_report §Upstream Status shows `dev MultiRobotTestSpinVariant: 502` during the test run. The G4 test fired two threads at the same `(M14, 1, dev)` POST. Both POSTs reached `start_batch`. Thread A's item was assigned SAMPLING lock in the registry. Thread B's item saw SAMPLING held by A → attach path (lines 3951-3973 in app.py: `try_acquire_cell` fails → `get_active_sampling_info` → same config_id+upstream_md5 → `item["status"] = "attached"`). B returned `"attached"` immediately, before any real upstream call.

The "one_attaches" assertion at line 356 passed because both items returned in <200ms — A because the batch was created synchronously, B because the attach is synchronous. No real upstream chunk was ever fetched. The "CellLockRegistry singleton SAMPLING limit enforced" claim in the tester_report is technically true but misleadingly implies a real race against actual sampling work. What was actually tested is "two near-simultaneous POSTs within a single in-process uvicorn correctly serialize via registry." This is already covered by backend unit tests.

The actual G4 scenario from the brief ("backend log shows only ONE upstream MultiRobotTestSpin batch") was never verifiable because no upstream call succeeded. The tester_report §G4 does not show any backend log evidence of upstream call count.

Note: The test is not broken — it correctly exercises the attach codepath. The problem is the claim that it passed G4 as the brief defined it.

---

**B4 — G5 test uses `?mode=1` workaround, explicitly does NOT exercise the all-modes R1 bug path, yet the test docstring says it addresses G5**

File: `tests/e2e/test_p4_real_business_flow.py:384-397`
Evidence: Lines 390-397 of the test contain a self-documenting note: "NOTE: We use ?mode=1 explicitly rather than DELETE /api/rawdata/M14 (all modes). The all-modes path... modes_to_lock = [] and the 409 guard is never exercised." This is the test correctly identifying and then dodging R1. G5 in the brief states: "Context B issues `DELETE /api/rawdata/M14` → HTTP 409." The brief specifies no mode param. The test uses `?mode=1`. The 409 test passes because it exercises the single-mode path, not the path the brief described. The planner-facing UI uses the all-modes path — this is the path that is broken (R1) and the path that the test deliberately avoids.

The inject-bug for G5 (Bug 3) also only injects against the explicit-mode guard (line 6870). The all-modes bug (lines 6856-6864: disk enumeration skips empty dir → modes_to_lock=[]) is not covered by any inject test.

---

### IMPORTANT (should fix)

---

**I1 — Inject-bug 1 (Bug 1) produces a SKIP not a FAILURE; a skip is not a test failure**

File: `tests/e2e/test_p4_real_business_flow.py:81-87` + tester_report §Bug 1
Evidence: The inject recipe for test_real_fetch_M14_mode1_via_dev_upstream is "change port 15060 → 15061." When injected, `_tcp_reachable(192.168.10.21, 15060)` fails (because the TCP probe checks port 15060, not 15061) → `_require_dev_upstream()` → `pytest.skip(...)`. A skip is recorded as "s" not "F" in pytest output. The inject-bug verification claims "RED confirmed" but a skip is not a red test — it is a yellow test. A CI system that enforces "all tests pass or skip" would not catch this inject. The test should produce FAIL not SKIP when the configured port is wrong. The skip predicate should check whether the configured server endpoint is consistent, not whether TCP connects to a hardcoded constant.

---

**I2 — G4 "single SAMPLING" registry assertion uses a fragile string match on system-state response structure**

File: `tests/e2e/test_p4_real_business_flow.py:346-354`
Evidence: `registry_snap.get("cells") or {}` with `"sampling" in v` where `v` is a string representation of an active_cells value. This is not documented API shape. If `api/system-state` changes its JSON structure or if the cell value is a dict (not a string), `"sampling" in v` is always False and the assertion `<= 1` passes vacuously (empty dict). The entire registry assertion block can silently pass even if CellLockRegistry is completely broken.

---

**I3 — Inject-bug 2 proves "B didn't post" not "concurrent attach semantics are correct"**

File: tester_report §Bug 2
Evidence: Inject: `sleep(200)` before B's POST. This makes `t1.join(timeout=20.0)` return with `results[1] = None` → `AssertionError: Thread 1 produced no result`. This tests that both threads complete within 20s, not that attach behavior is correct. A real concurrency bug (e.g., both threads independently acquire SAMPLING) would also pass this inject because both threads would have returned non-None results. The inject does not exercise the actual invariant it claims to protect.

---

**I4 — configs/machines.json also mutated on disk (not mentioned in tester_report)**

File: `configs/machines.json`
Evidence: `git diff HEAD -- configs/machines.json` shows two `configSummaryMd5` / `codeSummaryMd5` changes for M1 and one other machine. Tester_report does not mention this mutation. The brief's §5 Constraints say "All tests cleanup." This is a second tracked-file contamination beyond servers.json. The mutation likely came from a `POST /api/servers/dev/scan` call or MD5 refresh that ran during setup. Since `test_server_switch_default_and_scan` was skipped due to 502 after the PUT set-default, this may have come from another path (possibly machines.json MD5 refresh as a side effect of the batch-run payload field `skip_md5_refresh: True` being ignored in some code path).

---

**I5 — pytest.ini added without brief authorization; scope creep that touches repo root**

File: `pytest.ini` (untracked, root)
Evidence: Brief §4 D3 says "Conftest setup: Reuse `live_server` fixture from `tests/e2e/conftest.py` if it exists; otherwise extend." It does not authorize adding `pytest.ini`. The marks `real_upstream` and `slow` could instead be registered via `conftest.py` using `pytest_configure`. Adding `pytest.ini` at repo root affects all pytest runs project-wide (e.g., it adds a `[pytest]` config that any developer running backend tests will now see). This is a global side effect for a two-mark registration that belongs in conftest.

---

**I6 — test_server_switch_default_and_scan skipped AFTER already mutating servers.json**

File: `tests/e2e/test_p4_real_business_flow.py:490-543`
Evidence: The test calls `PUT /api/servers/dev/set-default` at line 513 (which writes to the real `configs/servers.json` — see B1). Then at line 518 it calls `POST /api/servers/dev/scan`, gets 502, and calls `pytest.skip(...)` at line 520. The mutation to servers.json was already committed to disk before the skip fired. The skip is not atomic with the mutation. Any test cleanup that only runs in fixture teardown (which is not the case here — no teardown restores servers.json) will miss this.

---

### NICE-TO-HAVE (deferred)

---

**N1 — G4 timing window is fragile on slow intranet**: The concurrent test assumes both POSTs arrive before A's batch completes (1000 spins × 1 robot). On intranet with fast cache, 1000 spins may complete in <500ms. A 200ms barrier sync on two threads on the same host is not guaranteed to beat a fast upstream response. The test_report itself flags this concern (§Concerns item 2). A more robust design would use `max_chunks=5` and a larger spin count to extend the SAMPLING window.

**N2 — No backend log assertion for single upstream call count**: G4 in the brief explicitly states "backend log shows only ONE upstream MultiRobotTestSpin batch." No test currently asserts uvicorn log content. This would require capturing stderr from the live_server subprocess and parsing it — absent in the current implementation.

**N3 — test_prod_endpoint_reachable_but_readonly_probe `assert` on 404 body is loose**: Line 574: `assert "no snapshot" in r2.text.lower() or "404" in r2.text`. The second disjunct `"404" in r2.text` matches on literally anything that contains "404" including an unrelated string in the response body. Should assert on `r2.status_code == 404` only.

---

### CONFIRMED-OK

---

- **A. No mocking of upstream HTTP**: `grep monkeypatch/Mock/requests/patch` in the test file returns zero hits except the docstring comment. All HTTP calls go through real `httpx` → real uvicorn → real app.py logic.
- **B. Same uvicorn process for G4**: `live_server` fixture is `scope="session"` (conftest.py line 42). Both threads in `test_concurrent_fetch_attaches_not_duplicates` share the same `base_url` → same uvicorn process → same `CellLockRegistry` instance. This part is correct.
- **C. D1 pwsh purge is complete**: `grep -c "pwsh" scripts/deploy/README_DEPLOY.md` → 0. `test_deploy_smoke_script.py` line 108 updated. 5 replacements confirmed correct.
- **D. Rollback pre-existing failures are pre-existing**: Both `test_rollback_refuses_with_uncommitted_changes` and `test_rollback_without_force_prompts_before_reset` failures in `test_deploy_rollback_script.py` predate P4-E2E. The tester confirmed via `git stash` + run against HEAD 190dc9d. These failures exist in the committed baseline.
- **E. R1 is a real bug**: The delete_machine_rawdata code path (app.py lines 6854-6864) confirms tester's root cause analysis. When mode=None and rawdata/M14 dir doesn't exist yet, `machine_dir.is_dir()` is False → `modes_to_lock = []` → the 409 guard loop at line 6869 is never entered → DELETE returns 200.
- **F. No requests mocking, no fixture-stubbed upstream**: The G3/G4/G5 tests call the real live_server (real uvicorn) which in turn calls the real dev upstream endpoint via the real sampling subprocess. When upstream returned 502, the 502 propagated faithfully through the stack.

---

## Verdict

**LOOP-BACK**

The tester's work is substantial and structurally correct (real uvicorn, real threads, real HTTP, no mocking). However three blockers prevent commit:

1. B1: committed `configs/servers.json` was mutated and not restored. Any commit that includes this file in its diff, or that leaves it dirty, ships a broken default_server configuration. The root cause (no servers_config override in create_app) is a production code gap that also needs to be addressed.
2. B2: G3 (the primary stated goal of P4-E2E) was never executed due to upstream 502. The brief's §7 commit 2 depends on D3 passing — G3 did not pass.
3. B4: G5 as specified in the brief (all-modes DELETE without ?mode) was explicitly not tested. The test tests a workaround path. R1 (the real bug) is documented but not inject-tested.

B3 is flagged but is less critical than B1/B2/B4 — the concurrent test is still useful even against a 502 upstream because it exercises the registry serialization. However the claim that it satisfied G4 as the brief defined it is false.

---

## Required fixes before commit/merge

1. Restore `configs/servers.json` `default_server` to `"prod"` (revert the unstaged mutation).
2. Restore `configs/machines.json` to HEAD state (revert the unstaged mutation).
3. Add `servers_config: Path | None = None` parameter to `create_app`; thread it through `sc` (line 5747); patch `set_default_server` to use `sc` not `SERVERS_CONFIG`; add a fixture-level teardown in the test to restore servers.json if patching is deferred.
4. Mark the commit as "G3 NOT YET VERIFIED — requires re-run when upstream healthy" in the commit message. Do not claim G3 verified until a real run with `item["status"] == "completed"` is observed and rawdata/reports artifacts are captured.
5. Either replace `pytest.ini` with a `pytest_configure` hook in `tests/e2e/conftest.py`, or document the addition explicitly in the commit scope.

---

## Optional improvements

1. Upgrade inject-bug 1 from "produces SKIP" to "produces FAIL" by making the TCP probe check the configured endpoint in servers.json, not a hardcoded constant. Wrong port → FAIL.
2. Add a `finally:` block in test_server_switch_default_and_scan to restore `default_server` to its pre-test value, regardless of skip/pass/fail.
3. For G4 robustness: increase `max_chunks=5` or add a `sleep(0.1)` after the barrier sync to give the SAMPLING lock time to be visible across threads before the second poll.

---

## Self-critique

I may have underweighted the possibility that machines.json mutation came from an unrelated source (e.g., a background Flask refresh triggered during the live_server boot). I should note that without seeing the actual pytest output (not provided in the tester_report), I cannot rule out a non-test source for the machines.json change. However, the delta in machines.json matches MD5 hashes for M1, which is consistent with a `POST /api/servers/dev/scan` or MD5 refresh side effect, and that is a test-sourced mutation. The servers.json mutation is unambiguous (single field, confirmed by git diff).

I also cannot confirm whether the two rollback test failures are truly pre-existing at 190dc9d without running them against that exact commit. The tester claims `git stash` + run confirmed this, which is the correct methodology, but I am trusting the report rather than re-running.
