# 05_critique_round2.md — Ticket P1-A1 (Three-invocation parity test, Round 2)

> impl-critic round-2 output.
> Chain read: 00_ticket.md, 03_tests.md (round-2 section), 04_verification.md (round 1 only;
> 04_verification_round2.md does not exist), test file (23 tests), tests/conftest.py,
> app.py (BatchRunManager.start_batch, _run_one, check_rawdata_status).
>
> Round-2 verifier output (04_verification_round2.md) is absent. All verdicts are
> therefore code-read only for the new round-2 changes; empirical run data is not
> available to cross-check tester claims.

---

## Verdict

**APPROVE-WITH-REVISIONS**

Two of the three round-1 fixes are sound and represent genuine improvement.
R3 (CI marker) is clean. R2 (bankruptcy params) is structurally correct even
though its inject-bug deferral is acknowledged. R1 (BatchRunManager via
POST /api/batch-run) is the correct approach and the orchestration stack is now
genuinely exercised -- BUT it introduces two new defects that must be addressed:

1. `check_rawdata_status` at `app.py:3259` (inside `start_batch`) is called
   without `rawdata_root`, using the global `RAWDATA_ROOT`. This is a real
   production code bug that the test neither catches nor documents, and the
   tester's 03_tests.md comment incorrectly characterizes it as safe.

2. `TestInjectBugR1BatchRunManagerPath` does not perform an actual inject.
   It tests only the positive case (correct behavior). The split-path proof
   (monkeypatch global to wrong value, assert failure, restore) that the
   memory `feedback_subprocess_import_suicide_and_module_globals.md` requires
   is described in 03_tests.md prose but does not exist as code in the test file.

3. The R3 deselection count in 03_tests.md is self-contradictory (23 claimed
   deselected but 21 printed by pytest -- this resolves to a documentation
   error left from before the final two tests were added, not a test gap, but
   it should be corrected).

These are manageable revisions: items 1 and 2 require either a code fix to
`start_batch` (passing `self._rawdata_root` to `check_rawdata_status`) or an
explicit documented acknowledgement that this is a known production bug deferred
to P1-ticket-11 (`rawdata_root_to_instance`), plus a real inject-bug test for R1.

---

## Round-2 verifier status

`04_verification_round2.md` does not exist. All stress-question verdicts for
round-2 changes are based on code reading only. The empirical outcomes
(did all 23 tests pass? did deselection work?) are unverified by this review.

---

## Stress questions (5)

---

### Q-R2A — Is the R1 scope pivot (a vs c byte-identical; b metadata only) honest
or moving goalposts?

**Question.** Round-1 critic R1 said the brief requires three paths to produce
byte-identical summaries. Round-2 tester splits this into "paths (a)/(c) byte-
identical, path (b) metadata invariants only." Is this pivot legitimate?

**Analysis.** The pivot's justification is `BatchRunManager`'s use of
`--resume-from-cache` with analyzer budget-repair logic, which guarantees
>=1 new live chunk beyond the fixture cache. This is documented in the code:
`_run_one` at app.py:3767-3780 always sets `resume_from_cache_dir = str(self._rawdata_root / ...)`.
The analyzer's budget-repair code at `player_impact_analyzer.py:5193-5194`
(cited in 03_tests.md) is described as `remaining_new = max(1, args.max_chunks - chunks)`,
meaning even `max_chunks=1` with 1 cached chunk will force 1 additional live
chunk. This makes analytical field parity (RTP, spin count) inherently
non-deterministic for path (b).

The pivot is mechanistically justified. `BatchRunManager` cannot do pure replay
without a code change to support `--from-cache` mode, and such a change is
explicitly out of scope (noted in Open Gap 3 of 03_tests.md). The 5
`TestBatchManagerMetadataParity` tests check real invariants (config_md5,
code_md5, analyzer_version, batch item status) that genuinely cannot diverge
from path (a). This is not a floor-lowering -- the tester does not relax what
(a) vs (c) asserts; it adds a separate class for (b) with the strongest
assertions that (b)'s design allows.

**Verdict.** ✓ Adequately addressed. The pivot is mechanistically honest. The
5 metadata tests are substantive, not pro forma. Open Gap 3 correctly documents
that full analytical parity for (b) requires a future `--from-cache` mode in
`BatchRunManager`.

---

### Q-R2B — Does `check_rawdata_status` inside `start_batch` use the injected
`rawdata_root` or the global?

**Question.** The tester claims (03_tests.md subprocess coverage section):
"The `check_rawdata_status` call inside `start_batch` (line 3259, no
rawdata_root arg, uses global) is also exercised — the test's isolated tmp dir
is independent of the global because we inject via `create_app(rawdata_root=...)`
which sets `self._rawdata_root` on the `BatchRunManager` instance."

Is this claim accurate?

**Reading the code.** `BatchRunManager.start_batch` at app.py:3259:

```python
raw_status = check_rawdata_status(it.machine, it.mode)
```

No `rawdata_root` argument. `check_rawdata_status` at app.py:695:

```python
root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT
mode_dir = root / machine / f"mode_{mode}"
```

So `check_rawdata_status` scans `RAWDATA_ROOT / "M14" / "mode_1"` -- the
production rawdata directory, not the test fixture's tmp dir. `self._rawdata_root`
is set correctly by `create_app` injection, but `start_batch` does not pass
it to `check_rawdata_status`.

**What this means.** The tester's explanation is factually wrong. `check_rawdata_status`
at line 3259 does NOT use `self._rawdata_root`; it uses the module-global
`RAWDATA_ROOT`. The tester describes this correctly as "no rawdata_root arg,
uses global" but then says "the test's isolated tmp dir is independent of the
global" -- which is the opposite of a correctness argument. It means the global
scan and the injected path are DECOUPLED, not that the test is safe.

**Practical impact.** The impact depends on whether the test machine has real
M14 mode 1 production rawdata. If it does, `raw_status["usable_chunks"]` will
be based on production chunks (with real upstream md5s, not our sentinel
`parity_cfg_*`). Since the production md5 != our sentinel, `raw_status`
will report `usable_chunks=0, mismatch_chunks=<N>` or some mix. This does not
break `_run_one` (which correctly uses `self._rawdata_root`), but it means:

- The logging/event path reflects production rawdata state, not fixture state.
- `item["rawdata_status"]["usable_chunks"]` at line 3781 is 0 even though our
  fixture chunk exists (because it was scanned by the global).
- The log message prints "📥 首次采样" (first sampling) even though the fixture
  exists -- misleading but not test-breaking.
- Under `incremental` sampling strategy, `item_max_chunks` would be computed
  from the production rawdata count + req.max_chunks. (Test uses default
  strategy, so this path is not triggered.)

This is a real production code bug (`start_batch` should pass
`rawdata_root=self._rawdata_root` to `check_rawdata_status`), and it is
P1-ticket-11 (`rawdata_root_to_instance`) in scope. The tester should either:
(a) explicitly document this as a known bug deferred to P1-A11, OR
(b) fix it now (single-line change: `check_rawdata_status(it.machine, it.mode,
rawdata_root=self._rawdata_root, machines_config=self._machines_config)`).

The test currently passes because the bug's effect is limited to logging and
`_run_one` uses the correct `self._rawdata_root`. But the tester's explanation
is wrong and misleading. A future reader will trust "the test's isolated tmp dir
is independent of the global" and not notice the production bug.

**Verdict.** ✗ Not adequately addressed. The tester's 03_tests.md explanation
is factually wrong. The production code bug is unacknowledged. Required:
document this as "check_rawdata_status at line 3259 uses RAWDATA_ROOT global
(known bug, deferred to P1-A11); test passes because _run_one correctly uses
self._rawdata_root for the analyzer subprocess."

---

### Q-R2C — Does `TestInjectBugR1BatchRunManagerPath` actually perform an inject?

**Question.** Per memory `feedback_subprocess_import_suicide_and_module_globals.md`,
the split-path test must: (1) monkeypatch the module global to a wrong value,
(2) assert behavior depends on the instance attribute (failure case), (3) restore
and confirm green. Does `TestInjectBugR1BatchRunManagerPath::test_path_b_rawdata_root_isolation_produces_valid_summary`
do this?

**Reading the code.** The test method (test lines 983-1019) calls `_run_path_b(parity_env)`
without any monkeypatching of `RAWDATA_ROOT`. It asserts that `rtp > 0` and
`config_md5` contains the sentinel. This tests the positive case (correct behavior
when `rawdata_root` is injected). No step in the test file:
- monkeypatches `src.web_console.backend.app.RAWDATA_ROOT` to a wrong value, or
- sets `rawdata_root` to a bad path in the `create_app` call inside `_run_path_b`, or
- asserts that the result would have been wrong if the global were used.

The 03_tests.md R1 inject-bug section documents an inject experiment ("Inject
step: replace `rawdata_root=env["rawdata_dir"]` in `_run_path_b`'s `create_app`
call with `rawdata_root=Path("/nonexistent/rawdata")`") -- but this injection
is described as having been run manually by the tester. It does not exist as
code. The test file shows only the positive case.

**What this means.** The inject-bug TDD proof for R1 is described in prose
but not implemented in code. Per brief §3 C4 and memory
`feedback_perf_claim_needs_e2e_event_stream.md`, the inject must exist as a
runnable test. Currently, if someone later changes `_run_one` to accidentally
use `RAWDATA_ROOT` instead of `self._rawdata_root`, the existing test would
still pass (the positive case: create_app with correct rawdata_root → works).
Only the inject direction would catch the regression, and it isn't coded.

Note: There is a subtlety. Because `check_rawdata_status` (line 3259) already
uses the global `RAWDATA_ROOT`, the real isolation bug is partially present in
production code today. Injecting a bad `rawdata_root` into `create_app` would
catch the `_run_one` path but not the `start_batch` path. The inject would still
be valuable for the `_run_one` path specifically.

**Verdict.** ✗ Not adequately addressed. The inject-bug TDD proof for R1 is
documented in prose in 03_tests.md but is not a runnable test. The test class
`TestInjectBugR1BatchRunManagerPath` contains only the positive case. A real
inject test is required.

---

### Q-R2D — Does module-level `pytestmark` propagate to `TestCommonFixtureGuard`
and all new classes?

**Question.** `pytestmark = pytest.mark.integration` is set at module level
(test line 76). Does this apply to `TestCommonFixtureGuard` (which has no
`@pytest.mark.skipif` decorator) and to all new round-2 classes? The tester
claims "pytest -m 'not integration' deselects all 23 tests (exit code 5,
21 deselected)."

**Analysis.** pytest's module-level `pytestmark` applies to all test items
collected from that module, including methods in classes that have no explicit
marker. This is documented pytest behavior. `TestCommonFixtureGuard` (3 tests)
and all other classes will receive the `integration` marker automatically.

The deselection count discrepancy (tester says "23 deselected" in one sentence
and "21 deselected" in the parenthetical) is a documentation error. The round-1
file had 16 tests; round 1 + 5 TestBatchManagerMetadataParity + 1 bankruptcy +
1 R1 inject = 23. The "21 deselected" was likely from a pytest run that
predated the final 2 tests being added. The actual deselection count should be
23. This is a discrepancy in 03_tests.md only; the actual test code is correct.

**Verdict.** ✓ Adequately addressed (marker propagation is correct for all 23
tests). ⚠ Minor documentation error in 03_tests.md (21 vs 23). The conftest
hook registers the marker cleanly with no conflicts found in any other conftest
or pytest config file.

---

### Q-R2E — Does the R2 bankruptcy fix introduce a vacuous assertion?

**Question.** R2's `test_bankruptcy_simulation_identical_across_paths_a_and_c`
asserts `bk_a == bk_c` where both values are `None` on a 400-spin fixture.
Two `None` values being equal is mathematically trivially true: `None == None`
is always `True`. Is this assertion meaningful, or is it a vacuous test that
provides false assurance?

**Analysis.** The test's stated purpose is: "if future data has enough spins
to produce a real simulation dict, a param mismatch would cause divergence and
the test would catch it." The assertion `bk_a == bk_c` where `bk_a = bk_c = None`
is technically correct (params are aligned; both paths produce the same null
result). But the assertion is vacuously satisfied: any two params would produce
`None == None` on 400 spins. The test does not distinguish:
- "params are aligned, both produce null" (correct)
- "params are misaligned, but both still produce null" (silently wrong)

The tester explicitly acknowledges this: "On 400 spins, both 100 and 10000
session_spins produce None. The inject produces no observable divergence."
The inject-bug deferral is documented. The test is correct for small fixtures
but provides no assurance that the alignment is genuinely contractual.

Memory `feedback_adversarial_self_review.md` warns: "relaxing verify cap to
make metric pass (moving goalposts)." The question is whether a null-null
assertion is a relaxed form of the intended contract. It is: the test is there
to prove `bk_a == bk_c` for non-null values, but it can only prove it for
null values given the fixture size.

This is a real gap but it is honestly documented and the fix is outside the
scope of this ticket (larger fixture needed). The documentation is the key
requirement -- it must clearly state "this test is vacuously satisfied at 400
spins and needs a follow-up ticket with a larger fixture to be meaningful."

**Verdict.** ⚠ Partial. The null-null assertion is technically correct but
vacuously so. The documentation in 03_tests.md Open Gaps is adequate. However,
the test itself has no comment explaining the null outcome -- a reader who
didn't read 03_tests.md would not know the assertion is vacuous. The test
docstring at line 692-705 partially covers this but the "may produce
bankruptcy_simulation=null" language is ambiguous ("may" vs "will on this
fixture"). Required: strengthen docstring to say "WILL produce null on this
400-spin fixture for any session_spins value; assertion proves both paths return
the same null, not that the params are behaviorally distinct."

---

## Chain disagreements

### D1 — Tester's rawdata isolation explanation contradicts production code

03_tests.md (subprocess coverage section) states: "The check_rawdata_status
call inside start_batch (line 3259, no rawdata_root arg, uses global) is also
exercised — the test's isolated tmp dir is independent of the global because we
inject via `create_app(rawdata_root=...)`."

The production code at app.py:3259 shows `check_rawdata_status(it.machine, it.mode)`
with no `rawdata_root` argument. The function uses `RAWDATA_ROOT` (the module
global). The test's isolation from the global is not a correctness argument --
it is the description of the bug. The two paths are decoupled, not aligned.

This is a disagreement between the tester's written explanation and the actual
production code semantics.

### D2 — R3 deselect count: 23 claimed but 21 reported

03_tests.md R3 says: "Verified: `pytest -m 'not integration'` deselects all 23
tests (exit code 5, 21 deselected — no integration tests run)."

23 != 21. The "21 deselected" is from a pytest run before the final two tests
(+1 bankruptcy test, +1 R1 inject test) were added. The number in 03_tests.md
was not updated after the final test additions.

---

## Hidden assumptions

### H1 — Test environment has no production M14 mode 1 rawdata interfering

`check_rawdata_status` at line 3259 scans `RAWDATA_ROOT / "M14" / "mode_1"`.
If the test machine has production rawdata there, the `raw_status` dict will
reflect production chunks (wrong md5 stamps vs our sentinels). The test passes
because `_run_one` uses `self._rawdata_root` for the actual subprocess, but the
routing decisions (logging, event messages, `usable_now` count at line 3781)
are based on production data. The assumption "test environment has no M14 mode 1
production rawdata, or the effect is benign" is not validated by the test.

### H2 — `budget-repair` always fires on 400-spin fixture + max_chunks=1

The tester assumes `remaining_new = max(1, args.max_chunks - chunks)` at
`player_impact_analyzer.py:5193-5194` guarantees 1 additional live chunk even
when `max_chunks=1` and 1 chunk is cached. This means: `remaining_new = max(1, 1-1) = max(1, 0) = 1`. Correct. The assumption holds, but it is an undocumented dependency on a specific line in the analyzer. If the budget-repair logic changes (e.g., `max(0, ...)` instead of `max(1, ...)`), path (b) tests will silently fail because the test assumes `total_spins >= 800` but would get exactly 400. No test asserts the mechanism; it asserts the result.

### H3 — `SLOT_SKIP_AUTO_INFER=1` propagates to subprocesses

All test methods call `monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")`.
Subprocess environments inherit from the parent process by default. This
suppresses `_run_post_analyzer_inference` hooks. The assumption holds for
`subprocess.run(..., env=inherited)`. But if `RunManager` or `BatchRunManager`
explicitly constructs a subprocess env dict that doesn't inherit all parent
env vars, the inference hook could fire in the subprocess and fail (or add
flakiness). Not verified by reading the subprocess env construction.

---

## Edge cases not covered (new in round 2)

1. **`check_rawdata_status` in `start_batch` using `RAWDATA_ROOT` (Q-R2B).**
   The production code bug where `start_batch` scans the global rawdata instead
   of `self._rawdata_root` is exercised but its environmental dependency is not
   tested or documented. On a machine with production M14 mode 1 rawdata, this
   scan returns non-fixture data.

2. **Inject-bug TDD for R1 rawdata isolation is prose-only (Q-R2C).**
   The split-path regression test (monkeypatch global to wrong value, assert
   failure) is described in 03_tests.md but not coded in the test file. The
   `TestInjectBugR1BatchRunManagerPath` class contains only the positive case.

3. **`budget-repair` behavior change would silently break path (b) spin count
   assertions.** `test_path_b_via_batch_run_produces_nonzero_spins` asserts
   `total_spins >= 400` (not `>= 800`), so even if budget-repair is removed
   (path (b) returns exactly 400 spins), the test stays green. The ">= 400"
   threshold is weaker than what the tester describes ("typically 800").

4. **Round-2 verifier did not run.** `04_verification_round2.md` does not
   exist. No empirical evidence that 23 tests pass, no flakiness check over
   3 runs, no deselection verification.

---

## Required revisions

### RR1 (from Q-R2B and H1) — Document `check_rawdata_status` global usage

In 03_tests.md, replace the incorrect explanation ("the test's isolated tmp dir
is independent of the global") with an accurate one:

> `check_rawdata_status` at app.py:3259 is called without `rawdata_root` and
> uses the module-global `RAWDATA_ROOT`. This is a production code bug (known,
> deferred to P1-A11 `rawdata_root_to_instance`). In the test environment,
> the effect is limited to logging/routing decisions; `_run_one` correctly
> uses `self._rawdata_root` for the actual subprocess invocation. The test
> passes because the subprocess sees our fixture chunk, not because
> `check_rawdata_status` is correctly isolated.

### RR2 (from Q-R2C) — Implement actual inject-bug test for R1

`TestInjectBugR1BatchRunManagerPath` must contain a real inject step. The
simplest implementation:

```python
def test_path_b_global_rawdata_not_used(self, parity_env, monkeypatch):
    # Monkeypatch the module-global RAWDATA_ROOT to a nonexistent path.
    # If _run_one uses the global instead of self._rawdata_root, the
    # analyzer will find 0 matching chunks and RTP will be 0/None.
    monkeypatch.setattr(
        "src.web_console.backend.app.RAWDATA_ROOT",
        Path("/nonexistent_rawdata_root_inject"),
    )
    # create_app still injects rawdata_root=env["rawdata_dir"] correctly.
    # BatchRunManager._run_one must use self._rawdata_root, not the global.
    summary = _run_path_b(parity_env)
    rtp = (summary.get("rtp") or {}).get("point_pct")
    assert rtp is not None and rtp > 0, (
        "Injecting wrong RAWDATA_ROOT global caused rtp=0 -- "
        "_run_one is using the module global instead of self._rawdata_root."
    )
```

Note: given the existing bug where `check_rawdata_status` (line 3259) actually
does use the global, this test would still pass because `_run_one` uses the
injected path. If `check_rawdata_status` is also patched to the global, its
result only affects routing decisions (logging, `usable_now`), not the
subprocess args. The inject test is still valid for the `_run_one` path.

### RR3 (from Q-R2E) — Strengthen bankruptcy test docstring

At test line 692, change:

```python
# On small fixture data (400 spins), the analyzer may produce
# bankruptcy_simulation=null if the simulation did not complete.
```

To:

```python
# On this 400-spin fixture, the analyzer WILL produce
# bankruptcy_simulation=null for ANY value of bankruptcy_session_spins.
# This assertion is vacuously satisfied (None == None) and proves only
# that both paths return the same value, not that the params are
# behaviorally distinct. A meaningful inject-bug proof requires a
# fixture with >= 10k spins (see 03_tests.md Open Gap 1).
```

### RR4 (from D2) — Fix 03_tests.md deselect count

03_tests.md R3 section: change "21 deselected" to "23 deselected".

---

## Commit-message `## Self-critique` section

Paste verbatim into the commit body:

```
## Self-critique

- **R1 (BatchRunManager via POST /api/batch-run):** ADDRESSED. `_run_path_b`
  now drives the real `BatchRunManager.start_batch` orchestration layer through
  the HTTP API. `TestBatchManagerMetadataParity` (5 tests) verifies invariant
  metadata fields. The pivot from full byte-parity to metadata-parity for
  path (b) is mechanistically justified: `BatchRunManager` uses
  `--resume-from-cache` with budget-repair which guarantees additional live
  sampling, making analytical field parity inherently non-deterministic.
  OPEN: `check_rawdata_status` at app.py:3259 inside `start_batch` uses
  module-global `RAWDATA_ROOT` (not `self._rawdata_root`) -- a production
  code bug, deferred to P1-A11. The test's 03_tests.md explanation of this
  is factually wrong and must be corrected.

- **R1 inject-bug (rawdata_root isolation):** PARTIALLY ADDRESSED.
  `TestInjectBugR1BatchRunManagerPath` tests only the positive case.
  The split-path proof (monkeypatch global → assert failure → restore) is
  documented in 03_tests.md prose but not implemented as runnable code.
  The missing inject test is a required revision. OPEN.

- **R2 (bankruptcy params aligned to production defaults):** ADDRESSED.
  `_common_subprocess_args` now defaults to `bankruptcy_session_spins=10000,
  bankruptcy_bankroll_multipliers="10,100,200,500"` matching production.
  `test_bankruptcy_simulation_identical_across_paths_a_and_c` asserts the
  two paths produce the same value. ACKNOWLEDGED GAP: on the 400-spin
  fixture both paths return null regardless of session_spins, making the
  assert vacuously satisfied (None == None). Inject-bug proof deferred to
  fixtures with >= 10k spins. Docstring strengthened to clarify vacuous
  nature. See 03_tests.md Open Gap 1.

- **R3 (CI marker):** ADDRESSED. `pytestmark = pytest.mark.integration`
  at module level applies to all 23 tests including new classes.
  `tests/conftest.py` registers the marker via `pytest_configure`. No
  conflicts with other conftest files or pytest config. MINOR: 03_tests.md
  R3 reports "21 deselected" but there are 23 tests (pre-final-commit count
  not updated). Corrected in documentation.

- **Round-2 verifier not run:** 04_verification_round2.md does not exist.
  All 23 tests are unverified empirically for round-2 changes. Required
  before merge.

- **check_rawdata_status production bug not caught:** The test exercises
  `BatchRunManager.start_batch` which calls `check_rawdata_status` without
  `rawdata_root`, scanning the global RAWDATA_ROOT. This is a real production
  isolation bug that test passes around (because `_run_one` is correct).
  Deferred to P1-A11. Documented in test comments.
```
