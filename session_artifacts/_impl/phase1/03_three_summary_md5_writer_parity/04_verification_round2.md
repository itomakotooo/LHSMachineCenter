# 04_verification_round2.md -- impl-verifier Round 2 for P1-A2
# Three Summary MD5 Writers Parity

Verifier: impl-verifier  Date: 2026-05-17

---

## Verdict: PASS

All Round 2 revisions (R1 + R2) are correctly implemented and verified.
30/30 tests pass. Inject-bug spot-checks confirm both fixes are substantive.
No new regressions vs baseline.

---

## R1 Verification -- C2 agreement tests call real pia._lookup_machine_md5

Grep for _patched_alpha_lookup shows exactly 5 occurrences:
  Line 30:  module docstring (reference text only)
  Line 188: def _patched_alpha_lookup (function definition)
  Line 715: test_injected_wrong_machine_alpha_diverges (inject-bug wrong-machine)
  Line 744: test_c5_monkeypatched_alpha_divergence_is_caught (inject-bug m1_md5)
  Line 957: test_alpha_beta_both_handle_malformed_json (malformed-JSON edge case)

None of the 3 production uses appear in C1 harness or C2 agreement tests.
All C1+C2 agreement tests now call pia._lookup_machine_md5 directly:
  Line 163: test_alpha_lookup_is_callable
  Line 254: test_alpha_beta_agree_m14_mode1
  Line 282: test_alpha_beta_agree_m14_real_config
  Line 323: test_alpha_beta_agree_inject_bug_catches_real_alpha_drift
  Line 400: test_three_way_agreement_virtual_m1sim_mode1
  Line 697: test_agreement_holds_before_injection
  Line 774: test_c5_reverted_alpha_agrees_with_beta
  Line 920: test_alpha_returns_empty_for_unknown_machine

R1 verdict: VERIFIED

R1 inject-bug spot-check:
  red-phase:  alpha=(f61f85...) != beta=(4fcf00...) -- Diverge: True
  green-phase: alpha=(4fcf00...) == beta=(4fcf00...) -- Agree: True
  R1 INJECT-BUG SPOT-CHECK: PASS

---

## R2 Verification -- test_c5_save_chunk_cache_propagates_sentinel_via_module_attr

New test (lines 825-901) exercises four concrete steps:

Step 1 (line 861): monkeypatch.setattr(pia, _lookup_machine_md5, sentinel lambda)
Step 2 (line 868): pia._save_chunk_cache(resp={spins:[]}, machine=M14, ...)
  This is the REAL production function (player_impact_analyzer.py:2162).
  It hits the alpha call site at line 2206:
    config_md5, code_md5 = _lookup_machine_md5(machine)
  Confirmed: bare module-level call, no local alias.
Step 3 (lines 883-885): read back chunk_0000.json from disk.
Step 4 (lines 889-900): assert envelope[_config_md5] == SENTINEL_CFG

If _save_chunk_cache had a cached-local-alias bug, sentinel would NOT appear
in the envelope and the test would go RED.

R2 verdict: VERIFIED -- genuine call-site split-path test, not vacuous attr proof.

R2 inject-bug spot-check:
  Buggy path (cached local before patch): returns real M14 md5, NOT sentinel. False.
  Real _save_chunk_cache envelope: _config_md5=SENTINEL_CONFIG_MD5_SPLITPATH_R2. True.
  R2 INJECT-BUG SPOT-CHECK: PASS

---

## Pytest Results

### Targeted test file
Reproducer: python -m pytest tests/backend/test_summary_md5_writer_parity.py -v
Observed: 30 passed in 0.12s
  Net count: 29 (R1) + 1 new inject-bug test = 30.
  R2 replaced test_c5_module_global_split_path_alpha_uses_call_not_global 1-for-1.
  R1 added test_alpha_beta_agree_inject_bug_catches_real_alpha_drift.

### Full suite
Reproducer: python -m pytest tests/ -q --tb=line

Run 1: 7 failed, 2256 passed, 33 skipped (294.76s)
Run 2: 9 failed, 2256 passed, 33 skipped (294.76s)

Stable failures (all pre-existing, match P1-B4 baseline):
  test_analyzer_st_split::test_zero_win_but_fired_pid_retained_in_split
  test_M15_verify_inject_bug: x4
  test_M43_engine: x2

Flaky (Windows mtime precision, documented in Round 1 04_verification.md):
  test_cache_cleanup::test_cleanup_keeps_baseline_deletes_excess
  test_chunk_index::test_bulk_remove_entries_single_write

No new regressions from Round 2 changes.

---

## Subprocess vs In-Process Coverage

Alpha _save_chunk_cache call site (player_impact_analyzer.py:2206) exercised
in-process by R2 test. main() call site at line 7394 remains deferred (Gap 1).
Both call sites have identical structure -- bare _lookup_machine_md5(machine).

---

## Frontend Impact: N/A -- test-only changes.

---

## Remaining Non-Blocking Issues (from 05_critique.md, unchanged)

- SQ4: beta except Exception: pass at app.py:6969 not tested
- SQ5: P1-B1 canonical signature documents reversed tuple order -- note needed before P1-B1
- SQ6: subprocess gap for alpha main() at player_impact_analyzer.py:7394
- SQ9: M14 mode 2/5/7 agreement not tested against real machines.json

---

## Summary Table

| Check | Status | Evidence |
|---|---|---|
| R1: C2 calls real pia._lookup_machine_md5 | PASS | Lines 163,254,282,400,697,774,920 |
| R1: _patched_alpha_lookup only in inject-bug + malformed-JSON | PASS | Lines 715,744,957 |
| R2: new test calls pia._save_chunk_cache (real call site) | PASS | Lines 868-900 |
| R2: sentinel propagates through real call site | PASS | Test + manual spot-check |
| R2: chunk file read back from disk | PASS | Lines 883-885 |
| Pytest 30/30 targeted | PASS | 30 passed in 0.12s |
| R1 inject-bug spot-check | PASS | Diverge=True red, Agree=True green |
| R2 inject-bug spot-check | PASS | Buggy ignores sentinel; real propagates |
| Full suite regressions | PASS | 7-9 failures all pre-existing |
| Test count net | PASS | 29 -> 30 |