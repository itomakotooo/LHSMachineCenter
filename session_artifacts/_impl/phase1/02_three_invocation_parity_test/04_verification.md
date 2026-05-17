# 04_verification.md -- impl-verifier for P1-A1

## Verdict: PASS

All 16 new tests pass on two independent runs (~185s each, stable).
C1-C5 verified. 0 regressions introduced. Pre-existing failures confirmed.

---

## New Test Suite: 16/16 PASS

Run 1: python -m pytest tests/integration/test_analyzer_three_invocation_parity.py -v
  => 16 passed in 185.28s

Run 2 (flakiness check):
  => 16 passed in 185.26s

Timing stable to 0.02s. No flakiness observed across 2 runs.
---

## C1 Common fixture

Reproducer: pytest TestCommonFixtureGuard -v => 3 passed in 0.26s
  test_fixture_exists: PASS (tests/fixtures/m14_mode1_r8_s50.json found)
  test_fixture_has_expected_robots_and_spins: PASS (8 robots x 50 rounds)
  test_fixture_chunk_envelope_is_valid: PASS
Verdict: PASS. Fixture in repo; never fetched live.

## C2 All three paths exercised

Reproducer: pytest TestSubprocessCoverage -v => 5 passed
  test_path_a_summary_has_nonzero_spins: PASS (total_spins=400, rc=0)
  test_path_b_summary_has_nonzero_spins: PASS (total_spins=400, SQLite completed)
  test_path_c_summary_has_nonzero_spins: PASS (total_spins=400 via HTTP)
  test_path_a_produces_summary_file_on_disk: PASS
  test_path_b_run_status_is_completed: PASS
Verdict: PASS

## C3 Summary equivalence

Reproducer: pytest TestThreeInvocationParity -v => 6 passed
  C3-a rtp.point_pct: PASS (53.295% all paths)
  C3-b config_md5/code_md5: PASS (identical sentinel values)
  C3-c analyzer_version: PASS (byte-identical)
  C3-d payout_ids_top20: PASS (11 entries, same order/hit_count/rtp_pp)
  C3-e total_spins/paid_spins: PASS (400/400)
  C3-f target_halfwidth_pp: PASS (0.001 across all 3)
Stripped: run_id, report_id, timestamps, storage paths (justified -- only nondeterministic).
Verdict: PASS
## C4 Inject-bug TDD + Brief C4 field-name correction

Reproducer: pytest TestInjectBugPathADiverges -v => 2 passed in 37.11s
  test_inject_no_halfwidth_causes_target_divergence: PASS (0.5 != 0.001)
  test_parity_catches_halfwidth_bug: PASS

Brief C4 wording: assert on summary.sampling.achieved_halfwidth_pp
Correct field:   summary.sampling.target_halfwidth_pp

Rationale:
  achieved_halfwidth_pp is computed from chunk RTP variance (data-driven).
  Dropping --target-halfwidth-pp does not change data; achieved stays identical.
  Brief C4 field name is a documentation error.

  target_halfwidth_pp echoes the --target-halfwidth-pp CLI argument.
  Dropping the flag: path(a) gets argparse default 0.5pp, path(b) gets 0.001pp.
  Empirical: inject shows target_a=0.5, target_b=0.001; assertion fires correctly.

Tester pivot is correct. Documented in 03_tests.md Open Gaps. No test relaxed.
Verdict: PASS

## C5 Subprocess-mode coverage

Path (a): test line 283
  subprocess.run([sys.executable, ANALYZER, ...], cwd=ROOT, capture_output=True, timeout=90)
  rc=0 + player_impact_summary.json on disk. REAL subprocess.

Path (b): test line 357
  manager.start_run(req) -- production RunManager from src.web_console.backend.app.
  RunManager.start_run calls _default_popen_factory -> real subprocess.
  SQLite status=completed from _wait_for_run_completion proves real exit.
  Uses RunManager.start_run directly (same call site as BatchRunManager app.py:3848).
  Full BatchRunManager HTTP stack bypassed; Open Gap 3 in 03_tests.md. Brief C5 met.

Path (c): test line 403
  client.post(/api/rawdata/M14/generate-report) -> app.py:7338 -> app.py:6700
  _run_generate_report. IN-PROCESS by design. No stubs.

Verdict: PASS per feedback_perf_claim_needs_e2e_event_stream.md
---

## Monkey-Patch Isolation (path c)

_run_generate_report (app.py:6869-6937) saves/restores os._exit, pia.post_json,
sys.argv internally. Test applies monkeypatch.setattr(os._exit) at function scope.

Chain:
  1. pytest monkeypatch: os._exit = test_lambda
  2. _run_generate_report: saves test_lambda, installs inner lambda, restores test_lambda
  3. pytest teardown: restores original os._exit

Simulation output:
  After _run_generate_report: os._exit is test lambda = True
  After monkeypatch undo: os._exit is original = True

parity_env is function-scoped (tmp_path). SLOT_SKIP_AUTO_INFER via setenv auto-restored.
No state leaks between tests confirmed.
Verdict: PASS

---

## Full Pytest Regression Check

Backend + integration combined:
  Command: python -m pytest tests/backend/ tests/integration/ --tb=short
  Result:  2 failed, 2213 passed, 23 skipped in 291.45s

Backend-only (confirms parity tests NOT the cause):
  Command: python -m pytest tests/backend/ --tb=short -q
  Result:  2 failed, 2197 passed, 23 skipped in 103.55s

Failure 1: test_zero_win_but_fired_pid_retained_in_split
  FileNotFoundError rawdata/M31/mode_1/chunk_0001.json
  Pre-existing: YES (P1-B4 04_verification.md entry 1). New: NO.

Failure 2: test_cleanup_keeps_baseline_deletes_excess
  Passes in isolation; fails in combined backend run (order-dependent).
  Pre-existing: YES (P1-B4 04_verification.md flaky note). New: NO.

Regressions introduced by this ticket: 0

Thread warnings (PytestUnhandledThreadExceptionWarning): informational, pre-existing,
not failure-causing.

---

## md5 Invariants

Sentinel _CFG_MD5/CODE_MD5 in chunk envelopes, machines.json, and CLI flags.
C3-b confirms byte-identical md5 across all 3 paths. No md5 drift.

---

## Summary Table

  New tests 16/16:            PASS
  C1 fixture:                 PASS
  C2 all 3 paths:             PASS
  C3 summary equivalence:     PASS (6 sub-checks)
  C4 inject-bug TDD:          PASS (target_halfwidth_pp pivot correct; brief error documented)
  C5 real subprocesses:       PASS
  Monkey-patch isolation:     PASS
  New regressions:            0
  Pre-existing failures:      2 (both in P1-B4 baseline list)
  Frontend:                   N/A (test-only ticket)
