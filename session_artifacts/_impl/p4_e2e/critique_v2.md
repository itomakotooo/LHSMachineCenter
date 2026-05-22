# P4-E2E Adversarial Critique — Round 2

Date: 2026-05-18
Reviewer: impl-critic
Branch: claude/keen-wu-b8b520 (uncommitted working tree, post round-2 impl+tester)
Base: HEAD 190dc9d

---

## Round-2 findings

### BLOCKER (must fix before commit)

**BLOCKER-1 — T5 is marked `@pytest.mark.real_upstream` and uses `live_server`, NOT TestClient + direct registry injection as the round-2 brief summary claimed.**

The coordinator brief for round 2 states: "T5 new: uses TestClient + direct `registry.try_acquire_cell(SAMPLING)` injection, asserts DELETE returns 409." This is false. The actual code at `tests/e2e/test_p4_real_business_flow.py:624-748` uses `live_server` (real uvicorn subprocess) and fires a real `httpx.post("/api/batch-run")` to get the SAMPLING lock active. The test is gated by `_require_dev_upstream()` — it SKIPS when the dev upstream (192.168.10.21:15060) is unreachable or returning 502. In the current environment, dev sampling API is returning 502; T5 therefore SKIPS, not PASSes.

Impact: The R1 regression guard (the only inject-verified test for the all-modes 409 fix) cannot run without a live upstream. If this worktree is run in an environment where dev is down, T5 produces zero coverage of the R1 fix. The brief summary's claim that T5 "uses direct registry injection" was either a description of an earlier design that was not implemented or simply wrong. Either way the actual test has a hard upstream dependency that the summary does not acknowledge.

Required action: Acknowledge the discrepancy explicitly. T5 as written is correct and useful when upstream is healthy — but it is NOT the low-dependency unit-level guard the summary implied. If a network-independent R1 guard is needed, a separate TestClient-level test that directly calls `registry.try_acquire_cell(SAMPLING)` in the app's in-process registry and then fires DELETE is needed. That does not exist.

---

**BLOCKER-2 — R1 "any active op" includes GENERATING, which the design explicitly permits to coexist with future DELETING in a narrower read of INV-2.**

The R1 fix calls `registry.get_active_cells()` with no `op` filter (line 6876 of `app.py`). This returns cells with ANY operation: SAMPLING, GENERATING, or DELETING. The design proposal v2 (`04_deploy_architecture_proposal_v2.md`) §5.1 INV-2 states: "delete_rawdata returns 409 when CellLockRegistry has **any** active registration for (machine, mode)." INV-3 (line 150 of the same doc) confirms GENERATING and DELETING are mutually exclusive. So the implementer's "any op type" reading IS correct per the spec.

However: this means a report-generation job running from existing cache (GENERATING, no new data written, no chunks at risk) blocks the all-modes DELETE with 409. The UX consequence is: operator tries to delete stale data, gets 409 "cell busy", but the cell is only busy generating a PDF — no data is in flux. The design accepted this (INV-2 is explicit), so this is not a new bug. But it is a design decision with real UX friction that was not specifically tested for the GENERATING case.

Confirmed-accepted per design, but the GENERATING-blocks-DELETE path has no test. Flag for coordinator to decide if a test is needed.

---

### IMPORTANT (should fix)

**IMPORTANT-1 — B4 closure correctness: when `servers_config=None`, the closure reads `SERVERS_CONFIG` as a live module attribute lookup, not a frozen value. Monkeypatch works. But when `servers_config=Path(...)`, `sc` is frozen at `create_app` call time.**

Line 7175: `cfg_path = sc if servers_config is not None else SERVERS_CONFIG`

When `servers_config=None` (the default / all existing backend unit tests): the expression evaluates the name `SERVERS_CONFIG` at call time of the route handler. Since Python looks up module globals at call time, `monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)` rebinds the module attribute before the route fires → lookup picks up the patched value. This is correct; existing backend tests in `test_batch_run_server_routing.py` use this pattern and continue to work.

When `servers_config=Path(...)` (e2e tests via SLOT_E2E_SERVERS): `sc` is set inside `create_app` at construction time and captured in closure. Any subsequent `monkeypatch.setattr` of `SERVERS_CONFIG` has no effect because the `sc if servers_config is not None` branch is taken. This is the correct isolation behavior — deliberate.

No bug. Walk-through confirms the two-level lookup is correct and both cases work as intended. Mark CONFIRMED-OK below.

---

**IMPORTANT-2 — T4 skip logic: "upstream_unstable OR (502 AND NOT request_failed)" — is "502 in error_text AND request_failed NOT in error_text" the right predicate?**

The exact stop_reason string a real 502 produces is found in `fresh_slotlab/player_impact_analyzer.py:6000-6003`:

```
upstream_unstable:network_consecutive_batches=3,network_cumulative_chunks=4,last_error=request_failed_http_502
```

This string contains BOTH "upstream_unstable" AND "request_failed_http_502". The test skip predicate at line 223-224:

```python
if ("upstream_unstable" in error_text or
        ("502" in error_text and "request_failed" not in error_text)):
```

For this real 502 string: `"upstream_unstable" in error_text` is True → the condition short-circuits → skip fires. Correct outcome.

The concern from the brief ("502 that also contains 'request_failed_http_502'") would only be an issue if the first disjunct were removed. Since `upstream_unstable` is always in the string when the sampler emits a 502-triggered stop, the logic is safe. However: `sampler.py:228` shows a secondary path: `request_failed_http_502` can appear as a raw chunk error BEFORE the analyzer accumulates enough consecutive failures to emit `upstream_unstable`. If the batch fails on the very first chunk before the consecutive-fail threshold is reached, `stop_reason` could be `upstream_unstable:...,last_error=request_failed_http_502` (still contains "upstream_unstable") OR it could be a direct batch failure with `error=request_failed_http_502` as the item error field (not stop_reason). The test checks `item.get("error") or ""` — not `item.get("stop_reason")`. If the error field contains `request_failed_http_502` without "upstream_unstable" (single-chunk failure before threshold), the second disjunct `"502" in error_text and "request_failed" not in error_text` is False → the outer `assert item["status"] == "completed"` fires → RED. This would be a false positive RED for a real service outage.

Risk: Medium. Depends on whether a 1-chunk failure before the consecutive threshold is reached can produce item["error"] = "request_failed_http_502" without "upstream_unstable". This path is not tested by-inspection and was not exercised in the live run. Tester claim of "T4 verified by inspection only" stands.

---

**IMPORTANT-3 — T5 can SKIP even when R1 fix is present and correct, giving false green signal in CI.**

Because T5 requires dev upstream (real 502 environment), the test SKIPs. In a CI environment where dev is unreachable (common after hours / weekend / maintenance), T5 always SKIPs. The R1 regression — the most critical P4 bug — has its only inject-verified regression guard hidden behind a real-upstream gate. A developer reverts the `registry.get_active_cells()` loop in app.py, pushes, and CI reports "35 skipped" not "1 failed."

This is the `feedback_no_silent_swallow.md` concern: the skip message is loud, but a SKIP when the fix-guard is supposed to protect against regression is structurally equivalent to the "silent-skip masks real failure" anti-pattern at the CI level.

---

**IMPORTANT-4 — T2 (pytest.ini removed, pytest_configure in conftest) creates a marks-scoping gap for any backend test runner that imports e2e conftest explicitly.**

`pytest_configure` in `tests/e2e/conftest.py` only fires when pytest collects from `tests/e2e/`. Running `python -m pytest tests/backend/` alone does not load `tests/e2e/conftest.py`. The grep confirms no backend tests use `@pytest.mark.real_upstream` or `@pytest.mark.slow` — those marks only appear in the e2e test file. So the scoping is currently safe. However: if any future backend test is marked `@pytest.mark.real_upstream` (e.g., a backend integration test that calls the real upstream), running it under `tests/backend/` only will produce "PytestUnknownMarkWarning: Unknown pytest.mark.real_upstream". This is deferred risk, not an active blocker.

---

### NICE-TO-HAVE (deferred)

**NTH-1 — The R1 fix adds `registry.get_active_cells()` (no op filter) but does not filter by DELETING. If cell (M14, 1) already has an active DELETING op (from a prior rollback mid-flight), the new loop adds it to `modes_set`, then `try_acquire_cell(DELETING)` fails because DELETING is already held → 409. This is correct behavior (second simultaneous delete is rejected) but the 409 error message says "SAMPLING or GENERATING" even when the conflict is actually DELETING vs DELETING. Minor message accuracy issue.**

**NTH-2 — `test_server_switch_default_and_scan` still skips mid-test after writing to the tmp `servers.json` (not the committed file, now that T1 isolation is in place). The skip-after-write issue from round-1 B1 is fixed at the path level, but the test still has no `finally` block to restore the tmp copy's `default_server` value to whatever it was before the test. If a subsequent test in the same session reads from the tmp servers.json (e.g., the batch-run server resolver in the live_server process), it sees `default_server=dev` instead of whatever the default was. Low risk since the tmp file is session-scoped and discarded at session end.**

**NTH-3 — The round-2 tester brief summary description of T5 ("TestClient + direct registry injection") does not match the actual implementation (`live_server` + real upstream). This summary is in the coordinator's prompt, not in a file. It cannot cause a test failure, but it creates a misleading audit trail if future agents read the summary as the spec for T5.**

---

### CONFIRMED-FIXED (round-1 issues now closed)

- **B1 (servers.json mutation)**: Fixed. `create_app` now accepts `servers_config: Path | None = None`. `sc` is bound correctly. `e2e_launch.py` reads `SLOT_E2E_SERVERS` env and passes `servers_config=Path(_servers_cfg)`. `conftest.py` copies `configs/servers.json` to a tmp path and sets `SLOT_E2E_SERVERS`. The `set_default_server` handler uses `sc` when `servers_config is not None`, otherwise reads module-level `SERVERS_CONFIG` for backward compat with existing monkeypatch tests. Verified: no `monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)` test calls `create_app` with `servers_config=` — they construct via the existing client fixture which passes no `servers_config` → `servers_config is None` → module-constant path → monkeypatch still works.

- **B2 (servers.json isolation confirmed)**: The structural fix in B1 means `set_default_server` writes to the tmp copy, not `configs/servers.json`. The `configs/machines.json` mutation from round-1 was a scan side-effect; `test_server_switch_default_and_scan` now calls `POST /api/servers/dev/scan` which (when dev returns 502) skips before the scan runs. machines.json is not mutated in round-2 runs.

- **B3 (rollback timeout 30→60)**: Fixed. Both `test_rollback_refuses_with_uncommitted_changes` and `test_rollback_without_force_prompts_before_reset` updated to `timeout=60`. Rationale documented inline: rollback.ps1 Step 2 port-poll loop runs `while ($waited -lt 30)` and can exhaust the full 30s before reaching the dirty-check guard.

- **B4 (servers_config DI)**: Brief asked for `app.state.servers_config_path`; implementer chose closure-only. The closure correctly isolates e2e tests and preserves backward compat for monkeypatch tests. `app.state.servers_config_path` would add introspection but is not needed for any current functionality. Deviation from brief is acceptable.

- **IMPORTANT-3 / T5-3 worktree-dirty skip**: No longer applicable — worktree-dirty behavior is in the existing smoke tests, not the new file.

- **IMPORTANT-4 / LogonType test**: Untouched, pre-existing, confirmed outside this phase's scope.

---

### CONFIRMED-OK (round-2 concerns answered)

**A1 — R1 "any op type" is correct per design.** INV-2 in `04_deploy_architecture_proposal_v2.md §5.1` says "any active registration." INV-3 says GENERATING and DELETING are mutually exclusive. The "any op" behavior is intended. GENERATING blocks DELETE is a known design decision, not a bug.

**A2 — e2e_launch.py in src/ is acceptable scope.** `git grep e2e_launch` shows it is only referenced by `tests/e2e/conftest.py` (the subprocess spawn command). Non-test callers (e.g., production `main.py`) do not reference `e2e_launch`. The `_servers_cfg = os.environ.get("SLOT_E2E_SERVERS")` read is safe for non-test callers: when `SLOT_E2E_SERVERS` is not set (production), `_servers_cfg=None` → `servers_config=None` passed to `create_app` → module-constant path. No behavioral change for non-test use.

**A3 — B4 closure walk-through confirmed correct.** See IMPORTANT-1 above. When `servers_config=None`, `SERVERS_CONFIG` is evaluated as a live module attribute at route-handler call time → monkeypatch works. When `servers_config=Path(...)`, `sc` is frozen at `create_app` time → test isolation works. Both cases are correct.

**A4 — marks scoping (F12).** No backend tests use `@pytest.mark.real_upstream` or `@pytest.mark.slow`. The gap is theoretical / future risk only. Current test suite is clean.

**A5 — T5 registry assertion sufficiency at uvicorn level.** T5 uses the real uvicorn subprocess (same CellLockRegistry singleton). The R1 fix is in the synchronous DELETE handler path — no event-loop scheduling can interleave between the registry lookup and the modes_set construction. The uvicorn test is the correct level for this assertion, not TestClient (though TestClient would also work since the handler is synchronous). Race condition that only appears in real uvicorn does not exist here.

---

## Self-critique

The most significant gap in this review: I cannot verify that T5 was inject-tested (Bug 4 in the docstring) because T5 requires a live upstream. The inject recipe (remove the `get_active_cells` loop, assert returns 200, revert) cannot be executed in the current 502 environment. The coordinator brief says the tester "verified by inspection only" for T4 and did not claim T5 was inject-run. I am trusting that the inject recipe is correct by code inspection — the assert at line 722 (`assert r_b.status_code == 409`) would clearly fire as RED if the loop were removed and the dir is absent. This seems correct but is unconfirmed by live execution.

I may also have underweighted the IMPORTANT-2 risk. If a chunk fails before the consecutive-fail threshold accumulates `upstream_unstable` in stop_reason, and the item["error"] field contains only `request_failed_http_502`, the T4 skip logic produces a false-positive RED for a real outage. This needs a live test with exactly 1 failed chunk before the threshold to confirm.

---

## Verdict

**APPROVE-WITH-COMMENTS**

The blocking concerns from round 1 (B1 servers.json isolation, B3 rollback timeout) are correctly fixed. The R1 code fix (`registry.get_active_cells()` union) is correct per the design invariant. The B4 closure implementation deviates from the brief's `app.state` approach but achieves the same isolation. The T1/T2 conftest changes are clean.

The remaining concerns (BLOCKER-1, BLOCKER-2, IMPORTANT-2, IMPORTANT-3) are structural gaps in test coverage and test reliability, not code correctness bugs. The R1 production code fix is sound. The regime where T5 always skips (no dev upstream) is a known risk that coordinator should explicitly accept or mitigate with a network-independent unit guard.

---

## Required fixes before commit/merge

1. **Document the T5 upstream dependency explicitly in the commit message.** The commit message must state: "T5 (R1 regression guard) requires live dev upstream; SKIPs when upstream is down. R1 code fix is sound and inject-recipe is correct by inspection; live inject-verify deferred until upstream is healthy."
2. **Acknowledge the T5 description discrepancy.** The round-2 coordinator brief said "TestClient + direct registry injection." The actual implementation uses `live_server`. The commit message or coordinator decision log must record this deviation so future readers are not misled.

---

## Optional improvements

1. Add a network-independent TestClient-level R1 unit guard: `app = create_app(...)`, `registry = app.state.registry`, `registry.try_acquire_cell("M14", 1, CellOperation.SAMPLING)`, then `client.delete("/api/rawdata/M14")` → assert 409. This guard would run in every CI sweep regardless of upstream health.
2. Add `finally:` block in `test_server_switch_default_and_scan` to restore tmp servers.json `default_server` to its pre-test value, even though the tmp file is session-scoped and discarded at session end (belt-and-suspenders).
3. Investigate whether a 1-chunk pre-threshold failure can produce `item["error"]` without "upstream_unstable" — if yes, harden T4 skip logic to check both `item["error"]` and `item.get("stop_reason", "")` for the upstream-outage signal.
