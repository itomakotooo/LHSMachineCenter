# 04_verification.md -- impl-verifier for P1-A2 Three Summary MD5 Writers Parity

## Verdict: PASS

All 5 brief contracts (C1-C5) verified. 29/29 targeted tests pass (3 independent runs, no flakiness).
Full suite shows 0 new regressions vs P1-B4 baseline. Real-vs-virtual asymmetry confirmed. All inject-bug scenarios verified.

---

## C1 -- Three-writer harness

Contract: Test invokes paths alpha, beta, gamma on same (machine, mode).

Reproducer: python -m pytest tests/backend/test_summary_md5_writer_parity.py::TestThreeWriterHarness -v

Observed (all 3 tests PASS):
- test_alpha_lookup_is_callable: imports _lookup_machine_md5 from fresh_slotlab.player_impact_analyzer.
- test_beta_lookup_is_callable: imports _get_machine_md5 from src.web_console.backend.app.
- test_gamma_patcher_is_callable: imports _patch_summary_md5_tags from slot_designer.core.backend.virtual_analyzer.

Verdict: PASS

---

## C2 -- Agreement: md5_alpha == md5_beta == md5_gamma for M14 mode 1

Contract: Byte-identical strings across all three writer paths.

Reproducer: python -m pytest tests/backend/test_summary_md5_writer_parity.py::TestThreeWriterAgreement -v

Observed (all 4 tests PASS):
- test_alpha_beta_agree_m14_mode1 (fixture): alpha == beta == (4fcf00c48b3d6979aef058fed9ed5f94, 536fc5a2a8f2ecf1fd8c6dfcf2c025cc). Both non-empty.
- test_alpha_beta_agree_m14_real_config (real configs/machines.json): both return same tuple from live config.
- test_beta_gamma_agree_virtual_m1sim_mode1: beta == gamma for M1sim mode 1 from virtual registry. Both non-empty.
- test_three_way_agreement_virtual_m1sim_mode1: alpha returns empty for M1sim (correct -- not in real config); beta == gamma.

Design: real machine = alpha==beta (gamma not invoked); virtual machine = beta==gamma (alpha correctly ignorant).

Verdict: PASS

---

## C3 -- Per-mode granularity

Contract: Per memory feedback_md5_granularity_and_stamping.md, per-mode md5 must NOT collapse modes.

Reproducer: python -m pytest tests/backend/test_summary_md5_writer_parity.py::TestPerModeGranularity -v

Observed (all 6 tests PASS):
- test_real_machine_m14_modes_share_md5: M14 flat schema; mode 1 == mode 2 by design (no modesMd5). Documented.
- test_virtual_machine_m1sim_modes_differ: M1sim beta(mode=1) != beta(mode=2). config_md5 differs; code_md5 shared.
- test_virtual_gamma_per_mode_granularity_m1sim: gamma _compute_md5s returns mode 1 != mode 2 for M1sim.
- test_virtual_gamma_all_mode_pairs_differ[mode_pair0] (modes 1,2): config_md5 differs. PASS.
- test_virtual_gamma_all_mode_pairs_differ[mode_pair1] (modes 1,5): config_md5 differs. PASS.
- test_virtual_gamma_all_mode_pairs_differ[mode_pair2] (modes 2,7): config_md5 differs. PASS.

Brief asks M14 mode 1 != M14 mode 2. Actual: real machines use flat schema (by design -- no modesMd5 block).
Tester correctly tested the meaningful variant (M1sim per-mode granularity). Correct semantic finding, not a gap.

Verdict: PASS (scope clarification documented -- see Asymmetry section)

---

## C4 -- Virtual path coverage

Contract: Virtual delegate path md5 must be filled. Regression guard on 2026-04-XX untagged issue.

Reproducer: python -m pytest tests/backend/test_summary_md5_writer_parity.py::TestVirtualPathCoverage -v

Observed (all 5 tests PASS):
- test_gamma_patcher_fills_empty_summary: patcher fills empty config_md5/code_md5; other fields preserved.
- test_gamma_patcher_does_not_overwrite_existing_md5: patcher is no-op when md5 already set.
- test_gamma_compute_m1sim_mode1_non_empty: _compute_md5s returns non-empty for M1sim mode 1.
- test_gamma_compute_m15sim_mode1_non_empty: same for M15sim mode 1.
- test_gamma_patcher_no_op_when_both_md5s_empty_input: patcher with empty inputs is safe no-op.

Gamma path exercised on actual virtual machine entries (M1sim, M15sim) from real machines_virtual.json.

Verdict: PASS

---

## C5 -- Inject-bug TDD

Contract: Inject divergent lookup, assert test catches divergence.

Reproducer: python -m pytest tests/backend/test_summary_md5_writer_parity.py::TestInjectBugDivergence -v

Observed (all 6 tests PASS).

Bug 1 -- Alpha returns wrong machine md5 (C5 core):
  RED: _patched_alpha_lookup(M1) = (f61f85932f314aff5f11e278931dde1d, 536fc5a2a8f2ecf1fd8c6dfcf2c025cc)
       vs beta(M14) = (4fcf00c48b3d6979aef058fed9ed5f94, 536fc5a2a8f2ecf1fd8c6dfcf2c025cc) -- Diverge: True.
  GREEN: alpha(M14) == beta(M14) -- Agree: True.
  Tests: test_injected_wrong_machine_alpha_diverges + test_c5_reverted_alpha_agrees_with_beta. Both PASS.
  03_tests.md documents exact observed values. VERIFIED.

Bug 2 -- Monkeypatched alpha via module attr:
  INJECT: monkeypatch.setattr(pia, _lookup_machine_md5, lambda machine: m1_md5).
  buggy_md5_alpha != md5_beta -- divergence detected.
  Tests: test_c5_monkeypatched_alpha_divergence_is_caught + test_c5_module_global_split_path_alpha_uses_call_not_global. Both PASS.
  Per memory feedback_subprocess_import_suicide_and_module_globals.md. VERIFIED.

Bug 3 -- Gamma patcher called with wrong values:
  INJECT: _patch_summary_md5_tags(tmp_path, wrong_cfg=f61f85...). M1 value instead of M14.
  payload[config_md5] != expected M14 value -- Diverge: True.
  REVERT: fresh summary + correct values. payload[config_md5] == expected -- Agree: True.
  Test: test_c5_gamma_patcher_divergence_caught_via_wrong_value. PASS. 03_tests.md documents both phases. VERIFIED.

Verdict: PASS

---

## Pytest Results

Targeted test file (3 independent runs -- flakiness check):
  python -m pytest tests/backend/test_summary_md5_writer_parity.py -v
  Run 1: 29 passed in 0.09s
  Run 2: 29 passed in 0.09s
  Run 3: 29 passed in 0.10s
  No flakiness observed.

Full tests/ suite:
  python -m pytest tests/ -q --tb=short
  8 failed, 2254 passed, 33 skipped (~297s)

slot_designer/tests/:
  python -m pytest slot_designer/tests/ -q --tb=short
  2 failed, 304 passed

---

## Regression Analysis

All failures pre-existing. 0 new regressions from P1-A2.

Failures in tests/ (8 total), all confirmed in P1-B4 baseline:
  test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split -- missing rawdata/M31 fixture
  test_cache_cleanup.py::test_cleanup_keeps_baseline_deletes_excess -- pre-existing flaky
  test_M15_verify_inject_bug.py x4 -- pre-existing M15 verifier logic mismatch
  test_M43_engine.py x2 -- missing rawdata/M43 fixture

Note: test_chunk_index::test_bulk_remove_entries_single_write appeared in one full-suite run
(mtime precision on Windows; passes in isolation). Same class as test_cache_cleanup flakiness. Not introduced by P1-A2.

Failures in slot_designer/tests/ (2 total), both in P1-B4 baseline:
  test_analytic_vs_sim.py::test_m37_mode5_analytic_includes_reroll_correction
  test_phase5_ordering.py::test_pwdf_sensible_range

Total: 10 failures (8 tests/ + 2 slot_designer/) = exact match to P1-B4 baseline count.

---

## Real-vs-Virtual Asymmetry Finding

Verified architectural fact. Relevant for downstream P1-B1/P1-B2 dedup.

Reproducer -- M14 in configs/machines.json (run from repo root):
  python -c "import json; d=json.load(open(chr(39)configs/machines.json chr(39),encoding=chr(39)utf-8chr(39))); m14=next(m for m in d[chr(39)machineschr(39)] if m[chr(39)machinechr(39)]==chr(39)M14chr(39)); print(sorted(m14.keys())); print(chr(39)Has modesMd5:chr(39), chr(39)modesMd5chr(39) in m14)"

Observed (M14 in configs/machines.json):
  Keys: [available, codeSummaryMd5, configSummaryMd5, logicClassNames, machine, modes, upstream_key]
  Has modesMd5: False
  configSummaryMd5: 4fcf00c48b3d6979aef058fed9ed5f94
  codeSummaryMd5:   536fc5a2a8f2ecf1fd8c6dfcf2c025cc

Observed (M1sim in slot_designer/configs/machines_virtual.json):
  Has modesMd5: True
  mode 1: 3ba67532c820a578357379fbf13c1362
  mode 2: c26f72c011e54d9c85cdf6074eba5c05
  mode 5: 667318683366b757eaa3bd7cd981bd80
  mode 7: 53537044ca4343f49240bf67333d4050

Summary:
  configs/machines.json (real machines): FLAT schema. Single configSummaryMd5 + codeSummaryMd5 per machine.
  No modesMd5 block. Alpha and beta return same tuple for all modes (mode-agnostic).

  slot_designer/configs/machines_virtual.json (virtual machines): PER-MODE schema.
  modesMd5 block with distinct configSummaryMd5 per mode. Gamma reads these per-mode values.

Consequence for P1-B1/P1-B2: any unified writer must handle both schema variants.
_get_machine_md5 (beta) in app.py already has the modesMd5 branch check.
Dedup must preserve this branching -- otherwise virtual machines regress to flat value instead of per-mode value.

---

## Subprocess Verification

Alpha path sanity (in-process):
  from fresh_slotlab.player_impact_analyzer import _lookup_machine_md5
  _lookup_machine_md5(M14)
  Observed: (4fcf00c48b3d6979aef058fed9ed5f94, 536fc5a2a8f2ecf1fd8c6dfcf2c025cc)
  Type: tuple with non-empty strings. PASS.

All three writers are pure JSON file-read + file-write functions. No subprocess spawn required to test core behavior.
Module-global split-path test guards against import-time caching bugs (only subprocess-mode risk for alpha).

Gap 1 from 03_tests.md (no subprocess spawn of full analyzer): assessed acceptable for this ticket.
P1-B4 verifier C6 subprocess run already asserted correct summary md5 for M14 mode 1.
This ticket adds parity checks between the three writers (all in-process pure-function paths).

---

## Frontend Impact

N/A -- test-only ticket. No frontend files modified.

---

## md5 Round-Trip Sanity

M14 live config: _lookup_machine_md5(M14) = (4fcf00c48b3d6979aef058fed9ed5f94, 536fc5a2a8f2ecf1fd8c6dfcf2c025cc). No drift.
M1sim virtual: _compute_md5s(entry, mode=1) == _get_machine_md5(M1sim, virtual_config, mode=1). Non-empty, per-mode distinct.

---

## Summary Table

| Suite                                   | Pass | Fail | Skip | Duration |
|---|---|---|---|---|
| test_summary_md5_writer_parity.py run 1 | 29   | 0    | 0    | 0.09s    |
| test_summary_md5_writer_parity.py run 2 | 29   | 0    | 0    | 0.09s    |
| test_summary_md5_writer_parity.py run 3 | 29   | 0    | 0    | 0.10s    |
| tests/ full suite                       | 2254 | 8    | 33   | 297s     |
| slot_designer/tests/                    | 304  | 2    | 0    | 9.72s    |

New regressions from P1-A2: 0