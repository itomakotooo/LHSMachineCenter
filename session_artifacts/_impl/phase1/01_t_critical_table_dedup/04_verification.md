# 04_verification.md -- impl-verifier for P1-B4 t_critical_95 dedup

## Verdict: PARTIAL

Core dedup correct; all new tests pass; subprocess verified; no new regressions.
OI-1 (test_virtual_analyzer_ci_stop.py collection error) is the sole non-pre-existing failure.
Flagged by implementer as known open issue requiring main-session decision.

---

## C1 -- Single source of truth

Reproducer: grep -rn def_t_critical_95 --include=*.py . | grep -v __pycache__

Observed: Only one match: fresh_slotlab/sampler.py:139:def t_critical_95
  virtual_analyzer.py:260 is comment tombstone only.
  Import identity: pia.t_critical_95 is sampler.t_critical_95 -> True
                   va.t_critical_95  is sampler.t_critical_95 -> True

Verdict: PASS

---

## C2 -- Value parity df 1..1200

Reproducer: python -m pytest tests/backend/test_t_critical_table_canonical.py -q
Observed: 1235 passed (1200 parametrized + 35 named tests)
Verdict: PASS

---

## C3 -- Latent-divergence-fix proof

Verified in-process:
  t_critical_95(15) = 2.131   (was 2.157 in old pia sparse interp)
  t_critical_95(25) = 2.060   (was different in old analyzer)
  t_critical_95(80) = 1.990   (was 1.96 sentinel in old virtual_analyzer)
  All three callers return same value via function-identity (is True).

Verdict: PASS

---

## C4 -- Inject-bug TDD verification

Reproducer: git stash 3 impl files; pytest canonical tests; git stash pop
Observed: 24 failures pre-dedup; 0 failures post-dedup.
Verdict: PASS

---

## C5 -- All existing pytest passes

Observed (3 independent full-suite runs): 10 failed, 2502 passed, 33 skipped

All 10 failures confirmed pre-existing in baseline stash run:
  test_analyzer_st_split    -- missing rawdata/M31/mode_1/chunk_0001.json
  test_cache_cleanup (flaky)-- passes in isolation; pre-existing in baseline full runs
  test_M15_verify_inject_bug x4 -- pre-existing M15 verifier logic mismatch
  test_M43_engine x2        -- missing rawdata/M43/mode_1/chunk_0001.json
  test_analytic_vs_sim      -- pre-existing reroll correction failure
  test_phase5_ordering      -- pre-existing PWDF range failure

test_virtual_analyzer_ci_stop.py FAILS AT COLLECTION (OI-1, see below).

Verdict: PARTIAL -- OI-1 collection error flagged to main session.

---

## C6 -- Subprocess-mode verification

Setup: M14 fixture wrapped in chunk envelope, written to tmpdir/rawdata/M14/mode_1/

Command: python -m fresh_slotlab.player_impact_analyzer
  --machine M14 --rtp-mode 1
  --from-cache tmpdir/rawdata/M14/mode_1
  --output-dir tmpdir/output --max-chunks 1

Observed (rc=0, stderr=empty):
  stop_reason: from_cache_complete
  session_level_halfwidth_pp: 22.704342112027224
  paid_spins: 400, rtp.point_pct: 53.295

Round-trip: df=399, canonical t_critical_95(399)=1.9742931818,
  se=0.11499985, hw=1.9743*se*100=22.704342  -- exact match
  Old PIA: t=2.0390, hw=23.448 pp (was overestimate; now corrected)

Child subprocess import: rc=0, t(7)=2.365, t(399)=1.9742931818181817

Verdict: PASS

---

## OI-1 Status -- CONFIRMED COLLECTION FAILURE

Command: python -m pytest slot_designer/tests/test_virtual_analyzer_ci_stop.py

Observed (exit code 2):
  ImportError: cannot import name _t_critical_95 from virtual_analyzer
  (line 44, module-level import)

Root cause: Line 44 imports _t_critical_95 deleted by this ticket.

Tests-testing-the-bug (test_t_critical_matches_small_n_table lines 68-80):
  assert _t_critical_95(100) == 1.96  -- wrong; canonical approx 1.987
  assert _t_critical_95(500) == 1.96  -- wrong; canonical approx 1.963
  assert _t_critical_95(0) == 12.706  -- wrong; canonical: math.inf
  Per brief S6: tested old divergent behavior. Flagged, not fixed.

Other tests in file remain valid; only line 44 kills collection.

Main session action: remove _t_critical_95 from line 44; update assertions
  to use t_critical_95 from fresh_slotlab.sampler with canonical values.

---

## Full Pytest Summary

Run                              | Pass | Fail | Skip
---------------------------------|------|------|------
Backend-only (post-dedup)        | 2169 |    1 |   23
Full suite (OI-1 excluded)       | 2502 |   10 |   33
Baseline (stash, OI-1 excluded)  | 2478 |   34 |   33
Canonical test file only         | 1235 |    0 |    0

Baseline 34 failures vs post-dedup 10; 24 improvement = canonical tests now passing.

Last 10 lines of full-suite run (10 failed, 2502 passed, 33 skipped, 126s):
  FAILED tests/backend/test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split
  FAILED tests/backend/test_cache_cleanup.py::test_cleanup_keeps_baseline_deletes_excess
  FAILED tests/machines/test_M15_verify_inject_bug.py::test_inject_pwdf_floor_breach
  FAILED tests/machines/test_M15_verify_inject_bug.py::test_baseline_v2_iter0_pattern
  FAILED tests/machines/test_M15_verify_inject_bug.py::test_inject_r1_blank_out_of_band
  FAILED tests/machines/test_M15_verify_inject_bug.py::test_inject_bucket_rtp_out_of_band
  FAILED tests/machines/test_M43_engine.py::test_chunk_schema_fingerprint_matches_production
  FAILED tests/machines/test_M43_engine.py::test_chunk_envelope_keys_match_production
  FAILED slot_designer/tests/test_analytic_vs_sim.py::test_m37_mode5_analytic_includes_reroll_correction
  FAILED slot_designer/tests/test_phase5_ordering.py::test_pwdf_sensible_range
  10 failed, 2502 passed, 33 skipped, 8 warnings in 126.23s

---

## Subprocess vs In-Process Coverage

Path                                   | Method                               | Result
---------------------------------------|--------------------------------------|-------
In-process: sampler.t_critical_95      | pytest 1200 parametrized C2 tests    | PASS
In-process: pia imports sampler        | function-identity test               | PASS
In-process: va imports sampler         | function-identity test               | PASS
In-process: va._ci_halfwidth_pp canon  | monkeypatch C6 test                  | PASS
Subprocess: player_impact_analyzer M14 | real subprocess --from-cache M14     | PASS
Subprocess: virtual_analyzer import    | child-process import + call          | PASS

---

## md5 Round-Trip Sanity

_lookup_machine_md5 at player_impact_analyzer.py:2138; no t_critical dependency.
Sanity: M14 -> (4fcf00c48b3d6979aef058fed9ed5f94, 536fc5a2a8f2ecf1fd8c6dfcf2c025cc)
No md5 drift. configs/machines.json concurrent mods NOT in P1-B4 scope.

---

## Frontend Impact

N/A -- backend dedup only. No frontend files modified. 0 t_critical references in JS.

---

## Regressions in Untouched Areas

Count: 0 new regressions.
All post-dedup failures pre-existing in baseline. OI-1 flagged per brief S6.

---

## Stop Reasons / Escalation

OI-1 requires main-session decision: update test_virtual_analyzer_ci_stop.py.
Until fixed, pytest slot_designer/tests/ aborts collection on that file.

Verdict (PARTIAL not FAIL): core dedup correct; C1/C2/C3/C4/C6 pass; subprocess OK;
no new regressions. PARTIAL = C5 partial violation (OI-1 known open issue).