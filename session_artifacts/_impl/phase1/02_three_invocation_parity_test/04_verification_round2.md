# 04_verification_round2.md -- Ticket P1-A1 (Three-invocation parity test)

> impl-verifier Round 2. Addresses R1/R2/R3 from critic 05_critique.md. Verified: 2026-05-17.

## Verdict: PASS

23/23 integration tests pass. 8 pre-existing failures confirmed on collab/dev baseline. No regressions.

---

## R1 -- BatchRunManager genuinely invoked: VERIFIED

_run_path_b posts to POST /api/batch-run (test line 421). Route at app.py:5791-5850:

  start_batch_run(req) -> batch_mgr.start_batch(req, rr)  [app.py:5840]
    -> BatchRunManager._run_batch(batch_id)  [daemon thread]
      -> _run_one(item) -> RunManager.start_run(req)  [real subprocess, --resume-from-cache]

app.py:3163-3188: BatchRunManager.__init__ stores self._rawdata_root from injected arg.
create_app (app.py:5349-5352) passes rawdata_root=rd_root to BatchRunManager.
_run_one (app.py:3777-3780) uses self._rawdata_root -- NOT module-level RAWDATA_ROOT.
check_rawdata_status, _try_acquire_key busy-key lock, _run_batch daemon thread all exercised.

### Empirical path (b) run

  POST /api/batch-run -> status 200
  item status: completed  run_id: b54f65b4a76d
  total_spins: 800  (1 cached + 1 live via budget-repair)
  config_md5: parity_cfg_aaaaaaaaaaaaaaaaaaaaaa  (sentinel, not production md5)
  rtp: 87.595
  bankruptcy_simulation: None

### Scope-pivot rationale: HONEST

BatchRunManager uses --resume-from-cache. Budget-repair (analyzer:5193-5194) forces >=1 live chunk.
Analytical parity with --from-cache paths is impossible. TestBatchManagerMetadataParity (metadata
fields only) is scope-limited by genuine behavioral difference, not floor-relaxation.

R1 inject-bug VERIFIED: wrong rawdata_root -> 0 matching chunks -> rtp>0 fires RED. Restore -> GREEN.

---

## R2 -- Bankruptcy param alignment: VERIFIED

_common_subprocess_args defaults (test lines 263-272): bankruptcy_session_spins=10000, multipliers=10,100,200,500
_run_generate_report (app.py:6846-6847): bankruptcy_session_spins=10000, multipliers=10,100,200,500
RunCreateRequest defaults (app.py:314-315): bankruptcy_session_spins=Field(default=10000)

All three paths use identical production defaults. Previous mismatch (100/10 in paths a/b) eliminated.
test_bankruptcy_simulation_identical_across_paths_a_and_c passes: both produce bankruptcy_simulation=None.

### R2 inject-bug deferral: HONEST

On 400-spin fixture, both bankruptcy_session_spins=100 and 10000 produce None -- no observable divergence.
Deferred to 10k+ spin fixture. The structural alignment (all paths use same params) is the real fix.

---

## R3 -- Integration marker: VERIFIED

Command: pytest tests/integration/test_analyzer_three_invocation_parity.py --collect-only -m integration -q
Result:  23 tests collected in 0.21s

Command: pytest tests/integration/test_analyzer_three_invocation_parity.py --collect-only -m not-integration -q
Result:  no tests collected (23 deselected) in 0.21s

tests/conftest.py adds ONLY pytest_configure registering the marker. No other behavior change.
No existing pytest.ini or pyproject.toml registration was present. Minimal and correct.

---

## Full integration suite (23 tests)

Command: python -m pytest tests/integration/test_analyzer_three_invocation_parity.py -v -m integration
Result:  23 passed in 19.58s

TestThreeInvocationParity (7 tests): PASS
TestBatchManagerMetadataParity (5 tests): PASS
TestInjectBugPathADiverges (2 tests): PASS
TestInjectBugR1BatchRunManagerPath (1 test): PASS
TestSubprocessCoverage (5 tests): PASS
TestCommonFixtureGuard (3 tests): PASS

---

## Full regression suite (integration excluded)

Command: python -m pytest tests/ -m not-integration -q
Result:  2239 passed, 33 skipped, 23 deselected, 8 failed in 110.16s

Pre-existing failures confirmed via git stash -> run on collab/dev -> git stash pop:
  test_zero_win_but_fired_pid_retained_in_split    pre-existing on collab/dev
  test_cleanup_keeps_baseline_deletes_excess       flaky in full-suite ordering, pre-existing
  test_M15_verify_inject_bug (4 tests)             pre-existing on collab/dev
  test_M43_engine (2 tests)                        pre-existing (missing rawdata/M43/mode_1/chunk_0001.json)

Ticket modifies only: tests/integration/*, tests/conftest.py.
None of the 8 failing test files are touched. Zero regressions introduced.

---

## Subprocess vs in-process coverage

Per memory feedback_perf_claim_needs_e2e_event_stream.md.

Path (a): real subprocess via subprocess.run, --from-cache, 400 spins. VERIFIED.
Path (b): POST /api/batch-run -> BatchRunManager.start_batch -> _run_one -> real subprocess,
  --resume-from-cache, 800 spins (1 cached + 1 live), sentinel config_md5 confirmed. VERIFIED.
Path (c): in-process pia import via POST /api/rawdata/M14/generate-report, 400 spins. VERIFIED.

---

## md5 / version invariants

Sentinel md5 values (parity_cfg_* / parity_code_*) are not real hex.
_classify_chunks accepts them without error -- tests pass.
Sentinel propagates: chunk envelope -> analyzer stamp -> config_md5/code_md5 in summary.
Path (b) empirical: config_md5=parity_cfg_aaaaaaaaaaaaaaaaaaaaaa confirms injected rawdata_root used.

---

## Open gaps (carried forward from 03_tests.md)

1. R2 inject-bug for bankruptcy_simulation deferred: null on both param values at 400 spins. Honest.
2. Path (b) analytical parity: budget-repair adds >=1 live chunk; RTP/payout_ids differ from (a)/(c).
3. sampling.stop_reason not asserted: may differ between --from-cache and in-process iterator.

---

## Verdict summary

  R1: POST /api/batch-run routes to BatchRunManager.start_batch invoked        VERIFIED
  R1: self._rawdata_root used (not module-global RAWDATA_ROOT)                 VERIFIED
  R1: inject-bug (wrong rawdata_root -> RED, correct -> GREEN)                 VERIFIED
  R1: scope-pivot (metadata only for path b)                                   HONEST, not floor-relaxation
  R2: bankruptcy_session_spins=10000 all paths                                 VERIFIED
  R2: bankruptcy_bankroll_multipliers=10,100,200,500 all paths                 VERIFIED
  R2: inject-bug deferral (null on both at 400-spin fixture)                   HONEST, documented
  R3: pytest.mark.integration gates 23 tests                                   VERIFIED
  R3: -m not-integration -> 0 collected                                        VERIFIED
  R3: tests/conftest.py change minimal (+pytest_configure only)                VERIFIED
  23/23 integration tests pass                                                 PASS (19.58s)
  Regressions in untouched areas                                               0 (8 pre-existing)

Final verdict: PASS