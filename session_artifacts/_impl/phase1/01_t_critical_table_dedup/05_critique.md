# 05_critique.md — impl-critic for P1-B4 t_critical_95 dedup

> Reviewer mindset: senior on-call engineer paged when this breaks in production.
> Chain read: 00_ticket.md + 02_implementation.md + 03_tests.md + (04_verification.md ABSENT).

---

## Verdict

**APPROVE-WITH-REVISIONS**

The core dedup is mechanically correct and the test suite is strong. One revision is required before commit: OI-1 (`test_virtual_analyzer_ci_stop.py`) must be resolved, not deferred. The 04_verification.md is absent, which means the verifier subprocess-mode round-trip (brief §3 C6) has not been executed. These together prevent a clean APPROVE.

---

## Stress Questions (10 total)

### Q1 — OI-1: "flag don't fix" is the right call, but implementer's verdict "pass (with OI-1)" is not

**Question**: The implementer flagged `test_virtual_analyzer_ci_stop.py:44` imports `_t_critical_95` which no longer exists, causing an ImportError at collection — meaning ALL 9 tests in that file fail collection, not just `test_t_critical_matches_small_n_table`. Implementer's `02_implementation.md` says "flag per brief §6" and verdict is "pass (with OI-1)". Brief §6 says "do NOT silently update the test" and "main session decides". Is escalating to main session without resolution the right call here, or is the implementer punting on real work?

**Attempted answer**: Brief §6 explicitly says "flag in `04_verification.md`, do NOT silently update the test to match new value. Main session decides whether to update the test." Memory `feedback_adversarial_self_review.md` warns that claiming "structural" or "I flagged it" without fixing is an anti-pattern. Here the test is not testing the correct behavior — it is testing the OLD bug (sentinel 1.96 for df>30, sentinel df=0 returning 12.706 instead of math.inf). Brief §3 C5 requires "all existing pytest passes." An ImportError-based collection failure on 9 tests is NOT "existing pytest passes."

However, the brief specifically calls this scenario out in §6 and §3 C5's parenthetical says "(In particular `slot_designer/tests/test_virtual_analyzer_ci_stop.py` … must continue passing)." The brief §6 says do NOT silently update — implying the implementer should escalate the judgment call, not unilaterally update. This is a correct escalation, not a punt.

**BUT**: the implementer's overall verdict of "pass (with OI-1)" is wrong. The brief's §3 C5 is a CONTRACT, and an importerror collection failure on 9 tests is a contract breach. The implementer should have said "PARTIAL — C5 open, requires main-session decision before commit." The "pass" verdict misleads the main session into thinking W2 can proceed to commit.

**Verdict**: PARTIAL — the escalation procedure is correct but the "pass" verdict label is wrong. C5 is not met.

---

### Q2 — OI-1 scope: 9 tests fail collection, not 1

**Question**: The implementer's OI-1 says "test `test_t_critical_matches_small_n_table` (lines 68–80) additionally asserts OLD divergent behavior." Does the importerror affect only that test, or all 9 tests in the file?

**Attempted answer**: The import at lines 40–45 of `test_virtual_analyzer_ci_stop.py` is a module-level import block. `_t_critical_95` is listed inside it. Python fails the entire module at collection time with ImportError when any name in the import block doesn't exist. All 9 tests (`test_t_critical_matches_small_n_table`, `test_ci_halfwidth_pp_undefined_for_n_le_1`, `test_ci_halfwidth_pp_zero_variance`, `test_ci_halfwidth_pp_matches_hand_computation`, `test_session_returns_from_chunk_dict_extracts_per_robot`, `test_session_returns_skips_robots_with_zero_bet`, `test_session_returns_handles_list_roundResult`, `test_load_existing_session_stats_accumulates_across_chunks`, `test_load_existing_session_stats_respects_md5_filter`, `test_load_existing_session_stats_empty_dir`, `test_load_existing_session_stats_pre_filter_no_match`) all fail collection.

The implementer's OI-1 description implies only 1 test is "additionally asserting old behavior" — this is accurate about value assertions but obscures the fact that the remaining 8+ tests are also broken due to collection failure, even though their logic is fine and they test behavior unrelated to t-critical. The main session needs to know: the fix is removing `_t_critical_95` from the import block (one line), not rewriting the test.

**Verdict**: PARTIAL — OI-1 is flagged but its scope is understated. The 1-line fix is obvious and non-controversial.

---

### Q3 — Subprocess-mode import: sampler.py is safe to import as a leaf module

**Question**: `virtual_analyzer.py` now imports `from fresh_slotlab.sampler import t_critical_95` at line 77. Per memory `feedback_subprocess_import_suicide_and_module_globals.md`, does importing `sampler.py` trigger any module-top side effect (app building, subprocess calls, DB access) when used inside the virtual_analyzer subprocess?

**Attempted answer**: Inspected `fresh_slotlab/sampler.py` lines 1–50 and 370–381. The module top defines only constants (`ENDPOINT_URL`, `MACHINE_NAME`, `RTP_MODE`, `BET_ORIGIN`, `INIT_CREDITS_STR`) and function definitions. There is no `app = build_app()` pattern, no `RunManager.__init__`, no `_recover_orphan_running_runs`, no subprocess spawn, no DB access. The `if __name__ == "__main__":` guard at line 380 properly guards `main(sys.argv[1:])`. Import of sampler.py is clean and side-effect-free.

**Verdict**: ADEQUATELY ADDRESSED — implementer's 02_implementation.md §Risk note 2 states this explicitly and correctly.

---

### Q4 — Script-mode except-block: is `from sampler import t_critical_95` actually reachable and correct?

**Question**: In `player_impact_analyzer.py` lines 59–80, the except-block fallback does `from sampler import t_critical_95` (line 80). Under what conditions is this path reachable? If reachable, is `sampler` (unqualified) importable? And — critically — is `sampler` guaranteed to be findable at that point?

**Attempted answer**: The except-block fires when `fresh_slotlab.sampler` is not importable as a package — i.e., when the script is run as `python fresh_slotlab/player_impact_analyzer.py` without the repo root on PYTHONPATH. In that case, Python adds `fresh_slotlab/` itself to `sys.path[0]`, making bare module names like `sampler`, `trigger_sessions`, `round_win`, etc. importable. This is consistent with all the other sibling fallbacks in the same block (`from trigger_sessions import ...`, `from round_win import ...`, etc.). The pattern is established and correct. The question of whether `sampler` can be found as a bare name when running from within `fresh_slotlab/` is: yes, because `sys.path[0]` will be the `fresh_slotlab/` directory when invoked that way.

However, there is a subtle risk: if the script is invoked from an unusual CWD where neither `fresh_slotlab.sampler` nor `sampler` is resolvable (e.g., `python /absolute/path/to/player_impact_analyzer.py` from a directory outside the repo), both paths fail. This is a pre-existing condition of the try/except pattern — not introduced by P1-B4. The test suite cannot exercise this in-process (it runs as a package), so it remains a deployment-mode assumption.

There is also NO test for this script-mode except-block path — `test_c1_player_impact_analyzer_imports_from_sampler` only tests in-process package import. Per memory `feedback_perf_claim_needs_e2e_event_stream.md`, script-mode is not covered. This is a gap.

**Verdict**: PARTIAL — the script-mode path is probably correct and consistent with pre-existing patterns, but neither the tester nor verifier executed the except-block path.

---

### Q5 — Comment integrity: "Matches the formula used by the real analyzer" — stale or updated?

**Question**: The brief (§2 memory note and §6 risk section) calls out `virtual_analyzer.py:280-283` which previously said "Matches the formula used by the real analyzer" as a textbook stale-comment case. Did the implementer update this comment?

**Attempted answer**: Reading `virtual_analyzer.py` lines 267–286: the updated `_ci_halfwidth_pp` docstring says "Matches the formula used by the real analyzer so virtual sampling's stop decision and the delegated report's reported CI agree." This sentence is carried over but now it's accurate — after P1-B4, both analyzer and virtual_analyzer do use the same formula (same t-critical source). The updated docstring also adds at line 273–276: "t-critical lookup delegated to `fresh_slotlab.sampler.t_critical_95` (canonical, P1-B4). Values for df 31-1000 now use linear interpolation…" This makes the behavior explicit.

**Verdict**: ADEQUATELY ADDRESSED — the comment was updated, not left stale.

---

### Q6 — Hidden coupling: other consumers of t_critical_95 not in the 3 changed files

**Question**: Are there any other callers of `t_critical_95` or `_t_critical_95` in the codebase outside the 3 changed files? Did the implementer accidentally miss a fourth consumer?

**Attempted answer**: Full grep across all `.py` files for `t_critical_95|_t_critical_95|_T_CRITICAL_95_TABLE` showed results in exactly: `fresh_slotlab/sampler.py` (canonical def + internal call), `fresh_slotlab/player_impact_analyzer.py` (import + call at line 981 and 1008), `slot_designer/core/backend/virtual_analyzer.py` (import + call at line 284), `slot_designer/tests/test_virtual_analyzer_ci_stop.py` (the OI-1 broken import), and `tests/backend/test_t_critical_table_canonical.py` (new test). No other files.

The brief cited 3 sources (sampler, pia, virtual_analyzer). The grep confirms exactly 3 callers. No hidden fourth consumer was missed.

**Verdict**: ADEQUATELY ADDRESSED.

---

### Q7 — Test count padding: are 1200 parametrized df tests adding value or ceremony?

**Question**: 1200 of the 1235 tests are `test_c2_full_range_returns_positive_float[df=1..1200]`. Is this 1200-test density catching anything that 35 sentinel assertions wouldn't? Or is it ceremonial test-count padding?

**Attempted answer**: The C2 contract (brief §3) requires the function returns a positive finite float for every integer df in [1,1200]. The canonical table covers df=1..30 + sparse (40, 60, 80, 120, 1000). For df outside those entries (31-39, 41-59, 61-79, 81-119, 121-999, 1001-1200), the function uses linear interpolation or clamping. The parametrized range tests every one of those — confirming no accidental `return None` or exception is thrown at any point. It is not testing specific values (the pinned-entries tests do that) — it is testing that the function doesn't crash or return a non-positive value for any argument in the range.

This is legitimate for a lookup function with branching interp logic: a bug in one of the `zip(points, points[1:])` loop branches could produce 0.0 or a negative result for a specific df range. The 1200 parametrized tests catch that. Not ceremony.

**Verdict**: ADEQUATELY ADDRESSED — the 1200 tests serve a distinct contract from the 16 pinned-entry tests.

---

### Q8 — Floor relaxation / moving goalposts: were any assertions relaxed?

**Question**: Did the implementer or tester relax any existing assertion (change `==` to `pytest.approx`, change a specific value to a range, lower a threshold) to make tests pass after the dedup?

**Attempted answer**: Grep of test code. The new test file uses `pytest.approx(expected, abs=1e-9)` throughout — this is precision tolerance on floating-point comparison, which is the correct idiom (exact float equality on `1.990` would be fragile). The existing tests were not modified: `test_virtual_analyzer_ci_stop.py` was NOT updated by the implementer (that is the OI-1 issue — they correctly left it alone). `test_analyzer_resume.py:108` uses `8.0 < hw < 9.5` which is a pre-existing loose range; n=10,000 means df=9999, and `t_critical_95(9999) ≈ 1.962`, which is close enough to the 1.96 comment that the `8.0–9.5` range still passes. No moving goalposts detected.

**Verdict**: ADEQUATELY ADDRESSED — no floor-lowering or assertion relaxation.

---

### Q9 — Parallel impl detection: did the implementer add any duplicate helper?

**Question**: Per memory `feedback_no_parallel_panel_impl.md`: did the implementer add any new helper that re-implements interpolation already in sampler, or any other parallel impl?

**Attempted answer**: The change removes code (drops `_T_CRITICAL_95_TABLE` and `_t_critical_95` from virtual_analyzer; drops local `t_critical_95` from player_impact_analyzer) and adds import statements. No new helper was added anywhere. The tombstone comments at `player_impact_analyzer.py:969–972` and `virtual_analyzer.py:260–264` are documentation comments, not code.

**Verdict**: ADEQUATELY ADDRESSED — this is explicitly an anti-parallel-impl ticket; the diff correctly collapses two duplicates into one canonical.

---

### Q10 — Verifier absent; subprocess C6 contract unverified

**Question**: `04_verification.md` does not exist. Brief §3 C6 requires a subprocess-mode round-trip: impl-verifier spawns virtual_analyzer against M14 mode 1 cached chunk and asserts CI half-width matches canonical `t_critical_95`. This is not covered by the tester's in-process tests. Is this a blocking gap?

**Attempted answer**: Memory `feedback_perf_claim_needs_e2e_event_stream.md` is explicit: "Unit test + AST check + `import x; print(x.attr)` smoke all GREEN is not enough — must spawn true subprocess against true fixture." The tester's `03_tests.md §Open gaps` item 2 explicitly defers this to impl-verifier. The verifier did not produce output. Therefore, C6's subprocess path is untested.

The implementer's `02_implementation.md §Risk note 2` argues that the `sys.path` setup at lines 51–53 makes the subprocess import safe. This is plausible reasoning but it is not empirical verification. The subprocess could fail to import `fresh_slotlab.sampler` if the virtual_analyzer subprocess working directory differs from the repo root at runtime, or if there is a `__init__.py` configuration issue specific to the subprocess environment.

**Verdict**: NOT ADDRESSED — 04_verification.md is absent. The subprocess round-trip mandated by brief §3 C6 and IMPL_TEAM_PROCESS.md §5 invariant 6 has not been executed.

---

## Chain Disagreements

**Disagreement 1 — Implementer "pass" vs brief C5 "must continue passing"**:
- Brief §3 C5: "all existing pytest passes… `slot_designer/tests/test_virtual_analyzer_ci_stop.py` must continue passing."
- Implementer 02_implementation.md: "pass (with OI-1)."
- Tester 03_tests.md §Open gaps item 4: "impl-verifier confirms this in W2."
- Neither implementer nor tester treats OI-1 as a C5 contract breach. But a collection-level ImportError on 9 tests IS a breach of C5. The tester explicitly assigns C5 verification responsibility to impl-verifier who is absent.

**Disagreement 2 — C6 subprocess: tester deferred it, verifier didn't do it**:
- Brief §3 C6 says impl-verifier owns the subprocess spawn.
- Tester 03_tests.md §Open gaps item 2: "DEFERRED to impl-verifier W2 per C6 brief."
- 04_verification.md: absent.
- The subprocess round-trip is neither tested by the tester nor verified by the verifier. This is a gap that was designed into the plan (tester correctly deferred), but verifier didn't close it.

---

## Hidden Assumptions

1. **Script-mode sampler reachability**: the except-block path (`from sampler import t_critical_95`) assumes `sampler` is reachable as a bare module name when `player_impact_analyzer.py` runs in standalone mode. This is consistent with pre-existing patterns but is not exercised by any test. The assumption holds when the script is invoked from within `fresh_slotlab/`, but not from arbitrary CWDs.

2. **sys.path setup precedes t_critical import in subprocess**: `virtual_analyzer.py` sets up `sys.path` at lines 51–53, then imports `t_critical_95` at line 77. This assumes the order is respected at subprocess startup. It is — Python executes top-level statements in order. But no subprocess test verifies the end-to-end path.

3. **Table values in sampler.py are mathematically correct**: the canonical table (df=1: 12.706, df=2: 4.303, …, df=1000: 1.962) is assumed to be the authoritative statistical values. The tests pin these values but do not cross-check them against scipy or any external reference. If the table has a typo (e.g., df=60: 2.000 should be 2.001 per actual Student's t-distribution), the tests would pass but produce wrong CI outputs. This is accepted pre-existing risk documented in brief §4 ("scipy/numpy replacement is out of scope").

4. **OI-1 test is "testing the bug"**: the implementer asserts `_t_critical_95(0) == 12.706` in `test_virtual_analyzer_ci_stop.py:80` is "testing the bug." This is mostly correct — the canonical `t_critical_95(0) = math.inf` is the right behavior. However, the caller `_ci_halfwidth_pp` guards `n <= 1` before calling t_critical, so df=0 is never reached in practice in either old or new code. The behavioral change for df=0 (12.706 → math.inf) has no runtime impact. The implementer should note this distinction.

---

## Edge Cases Not Covered

1. **df=0 behavior change on direct call**: `t_critical_95(0)` now returns `math.inf`; old `_t_critical_95(0)` returned `12.706`. The callers (`_ci_halfwidth_pp`, `session_halfwidth_pp`) both guard `n <= 1` before calling t_critical, so df=0 never reaches the function in practice. But any external code calling `t_critical_95(0)` directly would get `math.inf` instead of `12.706`. No test covers the behavioral difference for external callers — only the guard-path is tested.

2. **player_impact_analyzer.py `ci_halfwidth_pp` (not `session_halfwidth_pp`)**: `ci_halfwidth_pp` at line 975–984 also calls `t_critical_95`. Its df is `len(chunk_rtps_pct) - 1`. If a chunk has 2 robots (df=1), 5 robots (df=4), etc., this calls t_critical with small df where old and new tables agree. If a chunk has 31+ robots, it now uses interpolation instead of whatever the old table did. No specific test for `ci_halfwidth_pp` behavior is present in the new test suite — it is tested indirectly by the existing full-pipeline tests if they run.

3. **Concurrent module caching**: if `fresh_slotlab.sampler` is imported in a process that also imports `fresh_slotlab.player_impact_analyzer`, Python's module cache ensures both use the same `t_critical_95` object. The identity test `pia.t_critical_95 is sampler.t_critical_95` confirms this. But in the split-path monkeypatch test (`test_c6_split_path_monkeypatch_proves_sampler_attr_used` lines 454–457), the test manually assigns `sampler.t_critical_95 = _wrong_t` and then `va.t_critical_95 = _wrong_t`. This works because both are module-level name bindings. However, it also means `_ci_halfwidth_pp` calls `t_critical_95` (the local name), not `sampler.t_critical_95` — the local binding at import time is what matters. The test correctly patches both bindings, but this is subtle: if `_ci_halfwidth_pp` had been written as `sampler.t_critical_95(n-1)` instead of `t_critical_95(n-1)`, only patching the sampler binding would suffice. The test happens to be correct but its comment at line 450–453 is slightly misleading about why patching `va.t_critical_95` is necessary.

4. **No subprocess path tested by any agent (C6 gap)**: virtual_analyzer is the only module that runs as a subprocess in production. The import of `fresh_slotlab.sampler` at line 77 must succeed in the subprocess environment. This is documented as a gap but not tested.

---

## Required Revisions (for APPROVE-WITH-REVISIONS)

### Revision R1 (blocking) — Resolve OI-1 before commit

`slot_designer/tests/test_virtual_analyzer_ci_stop.py` causes an ImportError at collection. This breaks ALL 9 tests in the file, not just `test_t_critical_matches_small_n_table`. This is a C5 contract breach.

The minimum fix is: remove `_t_critical_95` from the import block at line 44. The remaining 8 tests (`_ci_halfwidth_pp`, `_session_returns_from_chunk_dict`, `_load_existing_session_stats` variants) are unaffected by P1-B4 and should pass after the import is cleaned.

`test_t_critical_matches_small_n_table` must be rewritten to test `t_critical_95` from `fresh_slotlab.sampler` with canonical values (consistent with brief §3 C3). Its current assertions for df=100→1.96 and df=500→1.96 were testing the bug; they should be updated to the canonical interp values (~1.9873 and ~1.9627 respectively), or simply removed in favor of the new `test_t_critical_table_canonical.py` coverage.

Main session must decide the update and ensure C5 passes before commit. This is not a "flag and defer" — it is a gate.

### Revision R2 (blocking) — Run impl-verifier before commit; confirm C6 subprocess path

`04_verification.md` is absent. Per IMPL_TEAM_PROCESS.md §3 and §5 invariant 6, verifier must spawn a real virtual_analyzer subprocess against a real M14 mode 1 fixture and assert CI half-width matches canonical `t_critical_95`. If verifier cannot be run before the commit, the main session must explicitly waive C6 with justification.

### Revision R3 (non-blocking; flag for next review cycle)

The implementer's verdict in `02_implementation.md` should be changed from "pass (with OI-1)" to "PARTIAL — C5 breach open (OI-1) + C6 subprocess unverified (impl-verifier not yet run)." This is a documentation accuracy issue, not a code issue, but it matters for future reviewers reading the artifact chain.

---

## Commit-message `## Self-critique` section (paste-ready)

```
## Self-critique

- Q: Does dropping `_t_critical_95` from virtual_analyzer break any other callers?
  A: Grep confirmed the only caller was `_ci_halfwidth_pp:284`; updated in the same commit. No hidden callers.

- Q: Is `from sampler import t_critical_95` in the except-block actually reachable, and is `sampler` findable?
  A: Yes — reachable when script is run as `python fresh_slotlab/player_impact_analyzer.py`; `fresh_slotlab/` is on sys.path[0] in that mode. Consistent with all other sibling fallbacks in the same block. Not covered by subprocess test (pre-existing gap in script-mode testing).

- Q: Does importing `sampler.py` inside the virtual_analyzer subprocess trigger any side effect?
  A: No. sampler.py top-level is constants + function defs only; `__main__` guard protects main(). Import is safe.

- Q: Did the implementer relax any existing assertion?
  A: No. `test_virtual_analyzer_ci_stop.py` was left untouched (OI-1 escalated). No existing assertion values were modified.

- Q: OI-1 — `test_virtual_analyzer_ci_stop.py` ImportError: blocking or deferrable?
  A: BLOCKING. It is a C5 contract breach (9 tests fail collection). Fix: remove `_t_critical_95` from the import block; update `test_t_critical_matches_small_n_table` to use canonical sampler values. This must be resolved before commit.

- Q: Was C6 subprocess verification (virtual_analyzer spawned against M14 fixture) completed?
  A: No — impl-verifier did not produce 04_verification.md. C6 subprocess path unverified. This must be completed before commit or explicitly waived by main session.

- Q: Could a future engineer add a local `t_critical_95` back to one of these files?
  A: `test_c1_single_definition_in_repo` would catch it by reading the source files directly. The identity checks (`pia.t_critical_95 is sampler.t_critical_95`) would catch a redefinition that coincidentally returns the same values.

OPEN: OI-1 (C5 breach — test_virtual_analyzer_ci_stop.py import error, 9 tests failing collection).
OPEN: C6 subprocess verification not run (verifier absent).
```
