# Phase C2 — Inject-Bug Evidence

> Author: impl-tester (redo pass)
> Date: 2026-05-27
> Protocol: per memory/feedback_enumerate_safety_paths.md

## Summary

All 5 inject-bug cycles completed: inject → RED confirmed → revert → GREEN confirmed.

---

## Table: Test File × Bug Recipe × Result

| # | Test file | Bug recipe | File modified | Code change | RED observed | GREEN restored |
|---|---|---|---|---|---|---|
| 1 | test_c2_payouts_by_spin_type_pattern_b.py | Bug A: emit() writes `{"_INJECTED": True}` sentinel | payouts_by_spin_type.py line 245 | `player_impact["payouts_by_spin_type"] = {"_INJECTED": True}` | test_emit_schema_keys FAILED: `Expected 'ST1_paid' key, got ['_INJECTED']` | PASSED after revert |
| 2 | test_c2_payouts_by_spin_type_pattern_b.py | Bug B: second for-loop in extract() removed (win aggregation) | payouts_by_spin_type.py lines 100-113 | Removed `pid_win_by_st` loop block | test_extract_win_aggregation FAILED: `Expected pid '202' in by_st_win, got: {}` | PASSED after revert |
| 3 | test_c2_payouts_by_spin_type_pattern_b.py | Bug C: constant denominator 1.0 in emit() | payouts_by_spin_type.py line 240 | `(st_win / 1.0) * 100.0` instead of `/ effective_bet_for_rtp` | test_emit_rtp_contribution_pp_formula FAILED: `expected 10.0, got 1000000.0` | PASSED after revert |
| 4 | test_c2_extract_actually_called.py (CRITICAL) | Remove pre-registration block from PIA main() | player_impact_analyzer.py lines 1521-1538 | Entire pre-registration block removed | 4 FAILED: ordering violation + `total hit_count == 0` + `total_win == 0` + `No PIDs with hits` | All 6 PASSED after revert |
| 5 | test_c2_extract_error_capture.py | Comment out `_extract_error_` accumulator append | player_impact_analyzer.py line 2021-2023 | `pass  # silently swallow` replacing append | test_extract_error_captured_in_feature_errors FAILED: `feature_errors must be populated... Got: {}` | PASSED after revert |
| 6 | test_c2_byte_identical_m14.py | extract() returns {} for all but first chunk | payouts_by_spin_type.py lines 81-82 | `if chunk_dict.get("index", 0) > 0: return {}` early return | test_payouts_by_spin_type_total_hits_nonzero FAILED: `Total hit_count == 0` + test_payouts_by_spin_type_rtp_positive FAILED: `total_rtp == 0` | Both PASSED after revert |

---

## Cycle 4 (CRITICAL) — Pre-registration block inject-bug detail

This is the most important inject-bug because it directly proves the test catches the C1 latent bug class.

**Bug injected**: Removed the entire 18-line pre-registration block from PIA main() (lines 1521-1538), replacing with a comment.

**RED output** (4 failures in 19.45s):
```
FAILED TestPreRegistrationBlockExists::test_pre_registration_before_cache_read_loop
  AssertionError: Pre-registration import (line 4850) must appear BEFORE cache loop (line 1522).
  
FAILED TestExtractActuallyCalledOnCachedChunks::test_payouts_by_spin_type_hit_counts_nonzero
  AssertionError: payouts_by_spin_type total hit_count == 0.
  This is the signature of the C1 latent bug: extract() not called because
  ALL_FEATURES was empty during merge loop.
  
FAILED TestExtractActuallyCalledOnCachedChunks::test_payouts_by_spin_type_total_win_nonzero
  AssertionError: payouts_by_spin_type total_win == 0.
  
FAILED TestExtractActuallyCalledOnCachedChunks::test_feature_accs_entry_for_payouts_by_spin_type
  AssertionError: No PIDs with hits in payouts_by_spin_type.
  extract() was likely not called (pre-registration missing).
```

**Mechanism confirmed**: Without the pre-registration block, `ALL_FEATURES` is empty during the merge loop. The subprocess PIA still produces a summary (rc=0) with `payouts_by_spin_type` key present, but all ST labels contain empty lists. This is exactly the silent bug C1 critic flagged.

**GREEN after revert**: All 6 tests passed in 18.57s.

---

## Cycle 5 — Error capture inject-bug detail

**Bug injected**: Replaced `_feature_accs.setdefault(f"_extract_error_{_fc_feat.FEATURE_ID}", []).append(str(_fc_exc))` with `pass` in PIA's from-cache merge loop error handler.

The test injects a forced `ValueError` into the plugin's `extract()` by monkey-patching the plugin file temporarily, then runs a real PIA subprocess.

**RED output**:
```
FAILED TestExtractErrorInSubprocess::test_extract_error_captured_in_feature_errors
  AssertionError: feature_errors must be populated when extract() raises. Got: {}.
```

**GREEN after revert**: 1 passed in 7.08s.

---

## Note on Bug A partial behavior

Bug A (`emit() writes sentinel`) makes `test_emit_writes_payouts_by_spin_type` PASS (sentinel dict is still written to the key) but `test_emit_schema_keys` RED (sentinel has `_INJECTED` key, not `ST1_paid`). This is correct behavior: the first test only checks key presence; the schema test checks content structure. Together they provide full coverage.

## Note on test_pre_registration_import_present_in_pia_source (Cycle 4)

This AST-level test PASSED even with the block removed because the plugin is still imported elsewhere in PIA (around line 4850 — the emit loop imports it lazily). This is the expected asymmetry: the AST check is a soft early-warning; the subprocess-level tests (`test_payouts_by_spin_type_hit_counts_nonzero` etc.) are the definitive proof. Both layers together provide defense-in-depth.
