# 03_tests.md — impl-tester report for P1-B4 t_critical_95 dedup

## Verdict: sufficient

All 6 brief contracts (C1-C6) are covered by executable tests. Inject-bug TDD verified (24 failures in pre-dedup state; 0 failures post-dedup).

---

## Test files added

| File | Tests |
|---|---|
| `tests/backend/test_t_critical_table_canonical.py` | 1235 total (1200 parametrized C2 range + 35 named tests) |

Breakdown of named (non-parametrized) tests:

| Test | Contract |
|---|---|
| test_c1_single_definition_in_repo | C1 |
| test_c1_player_impact_analyzer_imports_from_sampler | C1 |
| test_c1_virtual_analyzer_imports_from_sampler | C1 |
| test_c1_virtual_analyzer_has_no_local_table | C1 |
| test_c2_full_range_returns_positive_float[1..1200] | C2 (1200 parametrized) |
| test_c2_df_zero_or_negative_returns_inf | C2 |
| test_c2_above_1000_returns_last_sentinel | C2 |
| test_c3_df15_canonical_value | C3 |
| test_c3_df25_canonical_value | C3 |
| test_c3_df80_canonical_value | C3 |
| test_c3_all_three_callers_agree | C3 |
| test_c3_divergence_from_old_analyzer_sparse_table | C3 |
| test_c4_inject_bug_df15_wrong_value | C4 |
| test_c4_inject_bug_does_not_affect_non_target_dfs | C4 |
| test_c6_ci_halfwidth_pp_uses_canonical_t_critical | C6 |
| test_c6_split_path_monkeypatch_proves_sampler_attr_used | C6 |
| test_c6_ci_halfwidth_pp_edge_case_n_leq_1 | C6 |
| test_c6_ci_halfwidth_pp_edge_case_zero_variance | C6 |
| test_table_entries_pinned[df-val × 16] | regression guard |
| test_interpolation_between_table_anchors[df × 3] | regression guard |

---

## Inject-bug verification log

### Experiment 1: Full pre-dedup revert via git stash

Step 1 — Stash implementer's diff (restores pre-dedup state):
```
git stash push -m "impl-tester inject-bug experiment: stash implementer P1-B4 diff"
```
Confirmed pre-dedup: `pia.t_critical_95(15) = 2.157`, `pia is sampler = False`, `va._t_critical_95` attribute exists.

Step 2 — Run full test suite (pre-dedup state): **24 FAILED**
```
FAILED test_c1_single_definition_in_repo
FAILED test_c1_player_impact_analyzer_imports_from_sampler
FAILED test_c1_virtual_analyzer_imports_from_sampler
FAILED test_c1_virtual_analyzer_has_no_local_table
FAILED test_c3_all_three_callers_agree
FAILED test_c6_ci_halfwidth_pp_uses_canonical_t_critical
FAILED test_c6_split_path_monkeypatch_proves_sampler_attr_used
FAILED test_table_entries_pinned[1-12.706]
FAILED test_table_entries_pinned[2-4.303]
FAILED test_table_entries_pinned[5-2.571]
FAILED test_table_entries_pinned[10-2.228]
FAILED test_table_entries_pinned[11-2.201]
FAILED test_table_entries_pinned[12-2.179]
FAILED test_table_entries_pinned[15-2.131]
FAILED test_table_entries_pinned[20-2.086]
FAILED test_table_entries_pinned[25-2.06]
FAILED test_table_entries_pinned[30-2.042]
FAILED test_table_entries_pinned[40-2.021]
FAILED test_table_entries_pinned[80-1.99]
FAILED test_table_entries_pinned[120-1.98]
FAILED test_table_entries_pinned[1000-1.962]
FAILED test_interpolation_between_table_anchors[35-2.031-2.032]
FAILED test_interpolation_between_table_anchors[50-2.01-2.011]
FAILED test_interpolation_between_table_anchors[100-1.984-1.986]
```

Step 3 — Restore implementer's diff:
```
git stash pop
```

Step 4 — Run full test suite (post-dedup): **1235 passed, 0 failed**

Note on C3 sentinels in pre-dedup state: `test_c3_df15_canonical_value`, `test_c3_df25_canonical_value`, `test_c3_df80_canonical_value` pass even in pre-dedup state. This is correct — these tests assert `sampler.t_critical_95(df)` which was always canonical. The divergence-catching tests are `test_c3_all_three_callers_agree` (catches pia and va using different values) and `test_c6_ci_halfwidth_pp_uses_canonical_t_critical` (catches virtual's _ci_halfwidth_pp using the wrong t=1.96 sentinel for n=81/df=80). Both go red in pre-dedup state.

### Experiment 2: In-process synthetic inject (C4 — brief §3 C4 protocol)

`test_c4_inject_bug_df15_wrong_value` monkeypatches `sampler.t_critical_95` to return 2.222 for df=15 and asserts the df=15 value assertion fails with AssertionError. Confirmed: PASSED (the test correctly catches the injected wrong value).

---

## Coverage map: brief §3 contracts → tests

| Contract | Description | Tests |
|---|---|---|
| C1 | Single source of truth (one definition, in sampler.py) | test_c1_single_definition_in_repo, test_c1_player_impact_analyzer_imports_from_sampler, test_c1_virtual_analyzer_imports_from_sampler, test_c1_virtual_analyzer_has_no_local_table |
| C2 | Value parity df 1..1200 | test_c2_full_range_returns_positive_float[1..1200] (parametrized), test_c2_df_zero_or_negative_returns_inf, test_c2_above_1000_returns_last_sentinel |
| C3 | Latent-divergence-fix proof (df=15→2.131, df=25→2.060, df=80→1.990) | test_c3_df15_canonical_value, test_c3_df25_canonical_value, test_c3_df80_canonical_value, test_c3_all_three_callers_agree, test_c3_divergence_from_old_analyzer_sparse_table |
| C4 | Inject-bug TDD | test_c4_inject_bug_df15_wrong_value, test_c4_inject_bug_does_not_affect_non_target_dfs; also the git stash experiment documented above |
| C5 | All existing pytest passes | Verified by impl-verifier in W2 (full suite run). This test file adds no regressions to existing passing tests — confirmed by running with -q after stash restore. |
| C6 | virtual_analyzer._ci_halfwidth_pp uses canonical t_critical_95 | test_c6_ci_halfwidth_pp_uses_canonical_t_critical, test_c6_split_path_monkeypatch_proves_sampler_attr_used, test_c6_ci_halfwidth_pp_edge_case_n_leq_1, test_c6_ci_halfwidth_pp_edge_case_zero_variance |

---

## Open gaps

1. **C5 full suite** — `test_c5_all_existing_pytest_passes` is not a named test here; impl-verifier (W2) owns the full `-x` run across `fresh_slotlab/`, `tests/`, `slot_designer/tests/`. The new test file itself adds no regressions (verified: 1235 green, 0 fails, no impact to other test files).

2. **C6 subprocess-mode** — per brief §3 C6, impl-verifier (W2) spawns virtual_analyzer as a subprocess against an M14 mode 1 cached chunk and asserts CI half-width round-trip. This test file covers the in-process path only. The subprocess path is not covered here per the single-responsibility constraint.

3. **C3 pia-specific divergence guard** — `test_c3_df15_canonical_value` tests sampler directly (always canonical). The pia-specific divergence at df=15 (was 2.157 via interp) is caught by `test_c3_all_three_callers_agree` which asserts pia.t_critical_95 is the same function object. If pia had a different function that happened to return 2.131 coincidentally, this guard would still pass. The function-identity check (`.is`) is the more robust guard and covers this.

4. **slot_designer/tests/test_virtual_analyzer_ci_stop.py** — the brief mentions this test must continue passing (C5). impl-verifier confirms this in W2. It is not in scope for impl-tester to run it here (C5 is verifier's job).

---

## Subprocess vs in-process coverage

| Path | How covered |
|---|---|
| In-process: sampler.t_critical_95 correctness | 1200 parametrized C2 tests + 16 pinned entry tests + 3 interp tests |
| In-process: pia imports from sampler (identity) | test_c1_player_impact_analyzer_imports_from_sampler (`.is` identity check) |
| In-process: virtual_analyzer imports from sampler (identity) | test_c1_virtual_analyzer_imports_from_sampler (`.is` identity check) |
| In-process: virtual_analyzer._ci_halfwidth_pp result matches canonical | test_c6_ci_halfwidth_pp_uses_canonical_t_critical (n=81, df=80 divergence point) |
| In-process: split-path monkeypatch (proves attr used, not coincidence-masked) | test_c6_split_path_monkeypatch_proves_sampler_attr_used |
| Subprocess-mode: virtual_analyzer spawned against real M14 fixture | DEFERRED to impl-verifier W2 per C6 brief and single-responsibility constraint |

The split-path monkeypatch test (`test_c6_split_path_monkeypatch_proves_sampler_attr_used`) addresses the memory `feedback_subprocess_import_suicide_and_module_globals.md` concern: it proves the dedup is effective by patching the sampler attr to a wrong value and asserting `_ci_halfwidth_pp` output changes proportionally (ratio 2.0/1.990). If the old `_T_CRITICAL_95_TABLE` were still present and used, the result would be unchanged by the monkeypatch.
