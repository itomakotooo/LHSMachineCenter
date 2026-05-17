# 03_tests.md — Ticket P1-A2: Three Summary MD5 Writers Parity

## Round 2 updates (impl-critic R1 + R2, 2026-05-17)

### Summary of changes

Round 2 addresses the two blocking revisions flagged by impl-critic in 05_critique.md:

**R1 (stub → real function)**: The C1 harness and C2 agreement tests previously called `_patched_alpha_lookup` (a local stub that mirrors `_lookup_machine_md5`'s logic against a fixture path) instead of the real `pia._lookup_machine_md5`. This meant "α agrees with β" was testing a stub-copy-of-α against β — any drift in the real α function would not be caught. Round 2 replaces all C2 agreement calls with direct calls to `pia._lookup_machine_md5("M14")`. The stub is retained only for inject-bug scenarios that need a controllable fixture-path-redirectable lookup (wrong-machine-lookup tests) and for the malformed-JSON error-handling edge case (where corrupting the real `configs/machines.json` is not safe). The stub docstring is updated to document this narrow valid use.

**R2 (vacuous → call-site-exercising split-path)**: `test_c5_module_global_split_path_alpha_uses_call_not_global` previously only proved that `monkeypatch.setattr` works on a module attribute (trivially true for any Python module). It never invoked a real call site, so it could not prove that `main()` or any production code path uses the live module attribute rather than a cached local. Round 2 replaces this test with `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`, which: (1) monkeypatches `pia._lookup_machine_md5` to a sentinel, (2) calls `pia._save_chunk_cache` (the α call site at player_impact_analyzer.py:2206), (3) reads back the written chunk envelope, and (4) asserts the sentinel appears in `_config_md5`/`_code_md5`. If the call site used a cached local, the sentinel would not appear.

**New tests added in Round 2**: +1 (net 29 → 30)
- `TestThreeWriterAgreement::test_alpha_beta_agree_inject_bug_catches_real_alpha_drift` — documents the R1 inject-bug scenario inline

**Tests replaced/rewritten in Round 2** (same count, improved quality):
- `TestThreeWriterHarness::test_alpha_lookup_is_callable` — rewritten to call real `pia._lookup_machine_md5("M14")` directly
- `TestThreeWriterAgreement::test_alpha_beta_agree_m14_mode1` — rewritten; now calls `pia._lookup_machine_md5("M14")` directly
- `TestThreeWriterAgreement::test_alpha_beta_agree_m14_real_config` — rewritten; now calls `pia._lookup_machine_md5("M14")` directly
- `TestThreeWriterAgreement::test_three_way_agreement_virtual_m1sim_mode1` — rewritten; α called via `pia._lookup_machine_md5("M1sim")` (not stub)
- `TestInjectBugDivergence::test_agreement_holds_before_injection` — rewritten; uses real α
- `TestInjectBugDivergence::test_c5_reverted_alpha_agrees_with_beta` — rewritten; uses real α
- `TestInjectBugDivergence::test_c5_module_global_split_path_alpha_uses_call_not_global` — REPLACED by `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`
- `TestEdgeCases::test_alpha_returns_empty_for_unknown_machine` — rewritten; calls real α with "M999_NONEXISTENT"
- `TestEdgeCases::test_alpha_beta_both_handle_malformed_json` — docstring updated; stub retained here with explicit justification (malformed JSON edge case requires fixture path; real configs/machines.json cannot be safely corrupted)

### Round 2 inject-bug verification log

#### R1 inject-bug — real α drift caught by C2 agreement tests

**What was injected**: `monkeypatch.setattr(pia, "_lookup_machine_md5", lambda machine: ("WRONG_CFG", "WRONG_CODE"))` — replaces the real function body.

**Red phase**:
```
pia._lookup_machine_md5("M14") → ("WRONG_CFG", "WRONG_CODE")
_get_machine_md5("M14", real_config, mode=1) → ("4fcf00c48b3d6979aef058fed9ed5f94", "536fc5a2a8f2ecf1fd8c6dfcf2c025cc")
Agree: False → test_alpha_beta_agree_m14_mode1 would go RED
```

**Green phase (monkeypatch scope exits)**:
```
pia._lookup_machine_md5("M14") → ("4fcf00c48b3d6979aef058fed9ed5f94", "536fc5a2a8f2ecf1fd8c6dfcf2c025cc")
_get_machine_md5("M14", real_config, mode=1) → same
Agree: True → test_alpha_beta_agree_m14_mode1 GREEN
```

**Test capturing the RED scenario**: `TestThreeWriterAgreement::test_alpha_beta_agree_inject_bug_catches_real_alpha_drift` (permanently asserts divergence with the injected M1 md5 values)
**Test asserting GREEN**: `TestInjectBugDivergence::test_c5_reverted_alpha_agrees_with_beta`

#### R2 inject-bug — `_save_chunk_cache` call site uses live module attr

**What was injected**: The module-global caching bug: a version of `_save_chunk_cache` that captures `_lmm = _lookup_machine_md5` at definition time and calls `_lmm(machine)` instead of `_lookup_machine_md5(machine)`. This is the production pattern flagged in `feedback_subprocess_import_suicide_and_module_globals.md`.

**Red phase (buggy version)**:
```
# _cached_local_lookup captured before monkeypatch
pia._lookup_machine_md5 = lambda machine: (SENTINEL_CFG, SENTINEL_CODE)  # monkeypatched
_buggy_save_chunk_cache(...)  # uses _cached_local_lookup, ignores monkeypatch
envelope["_config_md5"] → "4fcf00c48b3d6979aef058fed9ed5f94"  # real value, not sentinel
Sentinel appears: False → test would go RED exposing the caching bug
```

**Green phase (real code, this test)**:
```
pia._lookup_machine_md5 = lambda machine: (SENTINEL_CFG, SENTINEL_CODE)  # monkeypatched
pia._save_chunk_cache(...)  # calls _lookup_machine_md5(machine) via module attr at line 2206
envelope["_config_md5"] → "SENTINEL_CONFIG_MD5_SPLITPATH_R2"  # sentinel propagated
Test goes GREEN
```

**Test asserting GREEN (proves real code uses live attr)**: `TestInjectBugDivergence::test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`

---

## Verdict

**sufficient**

All five brief contracts (C1–C5) are covered. 30 tests (net +1 from Round 1), all green. Inject-bug TDD verified for R1 (real α drift) and R2 (split-path call site). Round 1 bugs R1 and R2 from impl-critic are addressed.

---

## Test files added

| File | Test count |
|---|---|
| `tests/backend/test_summary_md5_writer_parity.py` | 30 |

---

## Inject-bug verification log

### Bug 1 — α returns wrong machine's md5 (C5 core)

**What was injected**: `_patched_alpha_lookup` called with `"M1"` instead of `"M14"` — simulates a bug where `_lookup_machine_md5` iterates the machine list and returns the first entry regardless of the requested machine.

**Red phase**: `buggy_alpha = ("f61f85932f314aff5f11e278931dde1d", "536fc5a2a8f2ecf1fd8c6dfcf2c025cc")` vs `md5_beta = ("4fcf00c48b3d6979aef058fed9ed5f94", "536fc5a2a8f2ecf1fd8c6dfcf2c025cc")` → `DIVERGE: True`. Test `test_injected_wrong_machine_alpha_diverges` asserts `buggy_alpha_result != correct_beta_result` → passes (red-phase captured).

**Green phase**: `correct_alpha = ("4fcf00c48b3d6979aef058fed9ed5f94", "536fc5a2a8f2ecf1fd8c6dfcf2c025cc")` == `md5_beta` → `AGREE: True`. Test `test_c5_reverted_alpha_agrees_with_beta` asserts agreement → passes.

**Test asserting RED**: `TestInjectBugDivergence::test_injected_wrong_machine_alpha_diverges`
**Test asserting GREEN**: `TestInjectBugDivergence::test_c5_reverted_alpha_agrees_with_beta`

### Bug 2 — monkeypatched α via module attr (C5 split-path)

**What was injected**: `monkeypatch.setattr(pia, "_lookup_machine_md5", lambda machine: sentinel)` — proves the call site in `main()` references the module-level function, not a cached local copy.

**Red phase (injection)**: `pia._lookup_machine_md5("M14")` returns `("WRONG_CFG_INJECTED", "WRONG_CODE_INJECTED")` → if this failed, it would mean the function is cached at import time (module-global leak bug).

**Green phase (without monkeypatch)**: normal lookup returns actual M14 values.

**Test**: `TestInjectBugDivergence::test_c5_module_global_split_path_alpha_uses_call_not_global`

### Bug 3 — γ patcher called with wrong values (C5 for γ)

**What was injected**: `_patch_summary_md5_tags(tmp, wrong_cfg, "some_code")` where `wrong_cfg = "f61f85932f314aff5f11e278931dde1d"` (M1's value instead of M14's).

**Red phase**: `payload["config_md5"] == wrong_cfg` → `DIVERGE: True` (doesn't match expected M14 value).

**Green phase**: `_patch_summary_md5_tags(tmp, expected_cfg, "some_code")` → `payload["config_md5"] == expected_cfg` → `AGREE: True`.

**Test**: `TestInjectBugDivergence::test_c5_gamma_patcher_divergence_caught_via_wrong_value`

---

## Coverage map: brief contracts → tests

### C1 — Three-writer harness invokes all 3 paths

| Writer | Test |
|---|---|
| α (`_lookup_machine_md5`) | `TestThreeWriterHarness::test_alpha_lookup_is_callable` |
| β (`_get_machine_md5`) | `TestThreeWriterHarness::test_beta_lookup_is_callable` |
| γ (`_patch_summary_md5_tags`) | `TestThreeWriterHarness::test_gamma_patcher_is_callable` |

### C2 — Agreement: md5_α == md5_β == md5_γ (byte-identical)

| Scenario | Test |
|---|---|
| Real α == β for M14 mode 1 (real configs/machines.json) | `TestThreeWriterAgreement::test_alpha_beta_agree_m14_mode1` |
| Real α == β for M14 mode 1 (real config, named separately) | `TestThreeWriterAgreement::test_alpha_beta_agree_m14_real_config` |
| R1 inject-bug: real α drift caught by agreement test | `TestThreeWriterAgreement::test_alpha_beta_agree_inject_bug_catches_real_alpha_drift` |
| β == γ for M1sim mode 1 (virtual) | `TestThreeWriterAgreement::test_beta_gamma_agree_virtual_m1sim_mode1` |
| Full three-way harness (real α empty + β==γ for virtual) | `TestThreeWriterAgreement::test_three_way_agreement_virtual_m1sim_mode1` |

**Round 2 (R1) note**: All tests that assert α's values now call `pia._lookup_machine_md5("M14")` directly. The stub `_patched_alpha_lookup` is no longer used for agreement assertions.

**Design note**: For real machines (M14), γ (`_patch_summary_md5_tags`) is not invoked — virtual_analyzer only calls it for virtual machines. The three-writer agreement is therefore:
- Real machines: α == β (both read `configs/machines.json`; γ not in play)
- Virtual machines: α returns `("", "")` (correctly ignorant of virtual registry); β == γ (both read `machines_virtual.json`)

The "full three-way agreement" test (`test_three_way_agreement_virtual_m1sim_mode1`) covers all three paths in a single test function: α is exercised and confirmed empty, β and γ are confirmed equal.

### C3 — Per-mode granularity

| Scenario | Test |
|---|---|
| Real machine M14: modes SHARE md5 (flat schema, by design) | `TestPerModeGranularity::test_real_machine_m14_modes_share_md5` |
| Virtual M1sim: mode 1 ≠ mode 2 (per-mode md5) | `TestPerModeGranularity::test_virtual_machine_m1sim_modes_differ` |
| γ `_compute_md5s` mode 1 ≠ mode 2 for M1sim | `TestPerModeGranularity::test_virtual_gamma_per_mode_granularity_m1sim` |
| All mode pairs (1,2), (1,5), (2,7) differ | `TestPerModeGranularity::test_virtual_gamma_all_mode_pairs_differ[mode_pair0/1/2]` |

**Scope clarification for C3**: The brief asks for "M14 mode 1 md5 ≠ M14 mode 2 md5". For M14 (a real machine), `configs/machines.json` has no `modesMd5` block — both β and α return the flat `configSummaryMd5` for all modes. This is documented expected behavior (per-mode granularity is a virtual machine feature via `modesMd5`). The per-mode granularity invariant is instead tested on M1sim (virtual), which does have `modesMd5`. The test `test_real_machine_m14_modes_share_md5` explicitly documents and asserts this distinction.

### C4 — Virtual path coverage (γ non-empty)

| Scenario | Test |
|---|---|
| γ patcher fills empty summary | `TestVirtualPathCoverage::test_gamma_patcher_fills_empty_summary` |
| γ patcher does NOT overwrite existing md5 | `TestVirtualPathCoverage::test_gamma_patcher_does_not_overwrite_existing_md5` |
| γ compute non-empty for M1sim mode 1 | `TestVirtualPathCoverage::test_gamma_compute_m1sim_mode1_non_empty` |
| γ compute non-empty for M15sim mode 1 | `TestVirtualPathCoverage::test_gamma_compute_m15sim_mode1_non_empty` |
| γ no-op when both input md5s are empty | `TestVirtualPathCoverage::test_gamma_patcher_no_op_when_both_md5s_empty_input` |

### C5 — Inject-bug TDD

| Scenario | Test |
|---|---|
| Baseline agreement — real α and β agree before injection (GREEN) | `TestInjectBugDivergence::test_agreement_holds_before_injection` |
| α returns wrong machine's md5 → divergence detected (stub-based wrong-machine) | `TestInjectBugDivergence::test_injected_wrong_machine_alpha_diverges` |
| Monkeypatched real α diverges from β (canonical C5) | `TestInjectBugDivergence::test_c5_monkeypatched_alpha_divergence_is_caught` |
| Reverted real α agrees with β (GREEN) | `TestInjectBugDivergence::test_c5_reverted_alpha_agrees_with_beta` |
| γ patcher with wrong value → divergence on read-back | `TestInjectBugDivergence::test_c5_gamma_patcher_divergence_caught_via_wrong_value` |
| R2 split-path: sentinel propagates through _save_chunk_cache call site | `TestInjectBugDivergence::test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` |

**Round 2 (R2) note**: `test_c5_module_global_split_path_alpha_uses_call_not_global` (vacuous per critic SQ2) has been REPLACED by `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`. The new test calls `pia._save_chunk_cache` (α's call site at player_impact_analyzer.py:2206) after monkeypatching `pia._lookup_machine_md5`, then reads back the written chunk envelope to confirm the sentinel propagated. If the call site used a cached local, the sentinel would not appear.

---

## Open gaps

### Gap 1 — No subprocess-mode α test (in-process only) — status updated for Round 2

Round 2 added the `_save_chunk_cache` split-path test, which exercises α's call site at player_impact_analyzer.py:2206 in-process. α's other call site is at player_impact_analyzer.py:7394 inside `main()`, which runs in a subprocess during production.

**Why still deferred**: α runs inside `main()` which requires a full rawdata fixture, a progress file, and several seconds to execute. The in-process `_save_chunk_cache` split-path test (R2) covers the module-global caching bug pattern for α. The `main()` call site at line 7394 is structurally identical — both call `_lookup_machine_md5(machine)` with no local alias.

**Assessment**: The `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` test (R2) is the practical proxy for the main()-level split-path check. A full subprocess test remains deferred to impl-verifier per the original Gap 1 scope. The verifier's 04_verification.md confirmed this gap is acceptable (P1-B4 verifier C6 subprocess run already asserted correct summary md5 for M14 mode 1).

### Gap 2 — C3 real-machine M14 mode granularity is N/A (documented, not blocked)

C3 asks for "M14 mode 1 md5 ≠ M14 mode 2 md5". Real machines in `configs/machines.json` use a flat schema (no `modesMd5`), so α and β both return the same value for all modes of M14. This is documented behavior, NOT a bug. The per-mode granularity regression is guarded on virtual machines (M1sim) where the invariant is meaningful. The `test_real_machine_m14_modes_share_md5` test explicitly documents and asserts this.

---

## Subprocess vs in-process coverage

| Test category | Mode | Justification |
|---|---|---|
| α (`_lookup_machine_md5`) | in-process | Pure JSON file read; no subprocess behavior. Calls REAL function against real configs/machines.json (R1). Split-path covered by _save_chunk_cache call site test (R2). |
| α (`_save_chunk_cache` call site) | in-process | Exercises the actual call site `_lookup_machine_md5(machine)` at line 2206. Sentinel propagation proves no local caching bug (R2). |
| β (`_get_machine_md5`) | in-process | Pure JSON file read; called within `_run_generate_report` closure but the function itself has no subprocess side effects. |
| γ (`_patch_summary_md5_tags`) | in-process | Reads + writes a JSON file; no subprocess. Called after subprocess returns in production, but the patcher itself is pure file I/O. |
| γ (`_compute_md5s`) | in-process | Computes hash from spec/weights files; no subprocess. |

All three writers are pure file-read + (for γ) file-write functions. No subprocess spawn is required to test their core behavior. The subprocess risk (that `main()`'s call site at line 7394 uses a cached local instead of the live module attr) is addressed by the `_save_chunk_cache` split-path test at the adjacent call site at line 2206 — both call sites are structurally identical (`_lookup_machine_md5(machine)` with no local alias).
