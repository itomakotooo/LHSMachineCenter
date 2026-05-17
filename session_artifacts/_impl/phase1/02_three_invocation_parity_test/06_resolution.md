# Ticket P1-A1 — Resolution

> Main session consolidation of W1 + W2 rounds 1+2 + main-session RR clarifications.

---

## Decision: **SHIP** (round 2 closed R1+R2+R3 blockers; round-2 critic RR1-RR4 addressed inline by main session)

| Source | Round 1 | Round 2 |
|---|---|---|
| impl-tester | sufficient (16 tests, 3/3 inject-bug, ~20.3 min) | sufficient (23 tests +7, 4/5 inject-bug, ~32.7 min) |
| impl-verifier | PASS (16/16, paths exercised genuinely) | PASS (23/23 + marker gating, prod bug surfaced) |
| impl-critic | APPROVE-WITH-REVISIONS (R1 BatchRunManager bypass / R2 bankruptcy divergence / R3 missing marker) | APPROVE-WITH-REVISIONS (RR1 prod bug / RR2 inject-bug runnable form / RR3 docstring / RR4 stale count) |

---

## Round 1 → Round 2 deltas (impl-tester)

**R1 (BatchRunManager genuine exercise)**: `_run_path_b` now drives `POST /api/batch-run` via FastAPI TestClient. Full stack invoked: route → `batch_mgr.start_batch` → daemon `_run_batch` → `_run_one` → `RunManager.start_run` → real subprocess. Verified empirically: path (b) produces 800 spins (1 cached + 1 live via budget-repair) with sentinel `config_md5` proving injected `rawdata_root` is used.

Scope pivot: `TestThreeInvocationParity` compares (a) vs (c) for ALL fields (both pure 400-spin replay); `TestBatchManagerMetadataParity` (5 new tests) covers path (b) metadata invariants (config_md5, code_md5, analyzer_version). Pivot is JUSTIFIED — BatchRunManager's `--resume-from-cache` + budget-repair inherently produces different spin counts than `--from-cache`, a genuine behavioral difference (verifier confirmed: "not floor-relaxation"). Path (b) inject-bug `TestInjectBugR1BatchRunManagerPath` proves `self._rawdata_root` injection is used via sentinel md5 mechanism.

**R2 (bankruptcy params aligned)**: `_common_subprocess_args` defaults updated to `bankruptcy_session_spins=10000` + 4-tier multipliers (production defaults at `app.py:6846-6847` and `app.py:314-315`). New `test_bankruptcy_simulation_identical_across_paths_a_and_c` asserts agreement. Inject-bug honestly deferred: 400-spin fixture produces `None` for any session_spins value (analyzer skips simulation on insufficient data). The test guards the contract long-term; on a future larger fixture, it would catch param drift.

**R3 (CI marker)**: `pytestmark = pytest.mark.integration` at module level; `pytest_configure` hook in `tests/conftest.py` registering the marker. `pytest -m "not integration"` deselects all 23 tests in 0.21s.

---

## Round 2 RR fixes (main session inline)

**RR1 (real prod bug surfaced)** → DEFERRED to P1-B6 with explicit brief update.
Round-2 critic identified that `check_rawdata_status` at `src/web_console/backend/app.py:3259`
reads the module-global `RAWDATA_ROOT` directly (not `self._rawdata_root`). This is
exactly the failure pattern memory `feedback_subprocess_import_suicide_and_module_globals.md`
warns about. The P1-A1 test exercises the path but does not currently catch the bug
(it would require asserting RTP > 0 with monkeypatched global + different injected
root, which is more elaborate than the current sentinel-only test).

Main session inline fix: updated [P1-B6 brief §3 C1](../11_rawdata_root_to_instance/00_ticket.md)
to explicitly enumerate this ref and flag it as a real prod bug. P1-B6 will land
both the migration AND the regression test that catches this bug.

Also corrected tester's prior 03_tests.md text "test's isolated tmp dir is
independent of the global" which was wrong (described the bug, not the fix).

**RR2 (inject-bug runnable form)** → clarified mechanism in 03_tests.md.
Critic noted `TestInjectBugR1BatchRunManagerPath` contains only the positive case;
the "monkeypatch RAWDATA_ROOT global" inject was described in prose, not as standalone
test code.

Main session clarification: the **sentinel approach IS the standing regression guard**.
The test creates a temp rawdata dir with unique sentinel md5 stamps and passes that
dir as `rawdata_root=` to `create_app`. If `_run_one` used the global `RAWDATA_ROOT`
instead, chunks in the real dir would have different md5s, the filter would drop
them all, and `rtp > 0` would fail. So the test naturally distinguishes global-vs-
injected paths without explicit monkeypatching — sentinel acts as the negative-case
witness. Functionally equivalent to monkeypatch test, more elegant. The ad-hoc
inject-step described in 03_tests.md lines 45-60 was a one-time dev verification
confirming the mechanism works; the permanent guard is the sentinel test itself.

Documentation updated in 03_tests.md "Round 2 RR clarifications" section.

**RR3 (bankruptcy docstring weak)** → strengthened.
Docstring of `test_bankruptcy_simulation_identical_across_paths_a_and_c` now clearly
states the 400-spin fixture produces null for ANY session_spins value, assertion is
vacuously satisfied today, but locks the contract for future larger fixtures.

**RR4 (stale "21 deselected" count)** → corrected to "23 deselected" matching final
test count. Round-2 verifier independently confirmed 23 deselected in 0.21s.

---

## Pytest results

- Targeted with `-m integration` (`tests/integration/test_analyzer_three_invocation_parity.py`): 23/23 pass in 18.46s
- Targeted with `-m "not integration"`: 0 collected (23 deselected) in 0.21s — marker gate works
- Full suite: 2239/2280 (8 pre-existing baseline failures; 0 regressions per round-2 verifier baseline comparison)

---

## Real production bug surfaced (deferred to P1-B6)

`check_rawdata_status` at `src/web_console/backend/app.py:3259` reads `RAWDATA_ROOT`
global directly, bypassing the `self._rawdata_root` injection pattern that the rest
of `BatchRunManager` uses. This is the exact footgun that caused the 2026-04-XX
virtual-batch-targeting-real-tree incident per memory.

P1-B6 brief §3 C1 now flags this ref explicitly. P1-B6 will:
1. Migrate `check_rawdata_status` to take `rawdata_root` as a parameter (or use
   instance attribute if it has class access)
2. Add a regression test that exercises the bug pre-migration and confirms post-
   migration fix

---

## Architectural finding (path b behavior)

`BatchRunManager` uses `--resume-from-cache` + budget-repair, which inherently
produces MORE spins than paths (a)/(c) which use `--from-cache` (pure replay,
no budget repair). On 400-spin fixture: path (a)/(c) = 400 spins; path (b) =
800 spins. This is by design — `BatchRunManager` tops up to target spin count
even when partial cache is available.

Consequence: any tests that compare path (b) summary against (a)/(c) MUST scope
to metadata-only fields (config_md5, code_md5, analyzer_version), not analytical
(RTP, payout_ids). Documented in P1-A1's TestBatchManagerMetadataParity scoping.

---

## Commit reference

Commit `<sha>` on `claude/stoic-napier-f0ea00`. Includes:
- `tests/integration/test_analyzer_three_invocation_parity.py` (NEW, 23 tests)
- `tests/integration/__init__.py` (NEW, init file)
- `tests/conftest.py` (MODIFIED, +pytest_configure hook for `integration` marker)
- 6 markdown artifacts in `session_artifacts/_impl/phase1/02_three_invocation_parity_test/`
- `session_artifacts/_impl/phase1/11_rawdata_root_to_instance/00_ticket.md` (MODIFIED, P1-B6 brief flag for `check_rawdata_status` prod bug per RR1)
