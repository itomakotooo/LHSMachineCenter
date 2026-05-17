# 05_critique.md — Ticket P1-A2: Three Summary MD5 Writers Parity

**Critic**: impl-critic
**Date**: 2026-05-17
**Chain read**: 00_ticket.md, 03_tests.md, `tests/backend/test_summary_md5_writer_parity.py` (production source for α, β, γ read directly). `04_verification.md` — NOT PRESENT (verifier running in parallel; reviewed without it).

---

## Verdict

**APPROVE-WITH-REVISIONS**

The 29 tests are structured, inject-bug TDD is documented, and the core C4/C5 coverage is real. However there are three issues that must be addressed before this lands as a dedup baseline:

1. `_patched_alpha_lookup` is a reimplementation of α — it does NOT call the real function. The "three-writer agreement" test under C2 tests the reimplementation-of-α vs β, not α vs β. The regression net is incomplete for α.
2. The C5 module-global split-path test only proves monkeypatch takes effect on the module attribute — it does not prove that `main()` uses the module-level call site rather than a cached local. The test is structurally vacuous for its stated purpose.
3. The P1-B1 brief (downstream dedup ticket) documents the canonical function signature as `-> (code_md5, config_md5)` (reversed order vs current). The P1-A2 parity test encodes `(config_md5, code_md5)` tuple order in all assertions. If P1-B1 ships as documented, P1-A2 will break immediately after dedup — defeating its purpose as the regression net.

---

## Stress Questions (10)

### SQ1 — `_patched_alpha_lookup` vs real α: is this testing agreement between the functions that actually run?

**Question**: C2's `test_alpha_beta_agree_m14_mode1` (line 207) and `test_alpha_beta_agree_m14_real_config` (line 220) call `_patched_alpha_lookup("M14", machines_json)` on the left side. `_patched_alpha_lookup` (lines 168–185) is a local test-helper reimplementation of `_lookup_machine_md5`'s logic; it is NOT a call to `pia._lookup_machine_md5`. The real α function at `player_impact_analyzer.py:2138-2159` hardcodes `Path(__file__).resolve().parent.parent / "configs" / "machines.json"` and accepts no path argument, so the only way to call it against a fixture is via monkeypatch. Does this mean C2 is testing the agreement between a test-helper-copy-of-α and β, rather than between the real α and β?

**Attempted answer**: Yes. `_patched_alpha_lookup` mirrors the logic of `_lookup_machine_md5` at the time it was written, but it is a separate Python function. If someone edits `_lookup_machine_md5` (e.g., adds a fallback, changes key names, changes the exception handler) and forgets to update `_patched_alpha_lookup`, the C2 test continues to pass even though the real α diverged. The only test that calls the real α via its module attribute is `test_c5_module_global_split_path_alpha_uses_call_not_global` — and that test monkeypatches it to a sentinel, so it never actually tests the real lookup logic against β.

**Verdict**: FAIL — C2 does not adequately cover "real α agrees with β". The tester should call `pia._lookup_machine_md5` directly (with `monkeypatch` to redirect its hardcoded path to the fixture) rather than calling a reimplementation.

---

### SQ2 — C5 module-global split-path test: does it actually prove main() uses the module-level call?

**Question**: `test_c5_module_global_split_path_alpha_uses_call_not_global` (line 709) does `monkeypatch.setattr(pia, "_lookup_machine_md5", lambda machine: sentinel)` and then asserts `pia._lookup_machine_md5("M14") == sentinel`. This trivially passes for any module-level function — `monkeypatch.setattr` always works on module attributes. The docstring claims this "proves that the call site in main() calls the module-level function". But `main()` is never invoked in this test. The test proves only that attribute assignment on the `pia` module works, not that `main()` reaches through the module attribute rather than a cached local reference. Is this test vacuous for its stated purpose?

**Attempted answer**: Yes. The memory `feedback_subprocess_import_suicide_and_module_globals.md` specifies the dangerous pattern: a function defined at module top has a reference captured in a local or closure at import time, so monkeypatching the module attribute has no effect on the running code. The correct test for this pattern must either: (a) call `main()` after monkeypatching and observe that `main()` used the patched value, or (b) inspect the call site in `main()` AST to confirm it calls `_lookup_machine_md5(...)` rather than a local alias. Neither is done here. The test as written would pass even if `main()` had `_lmm = _lookup_machine_md5` at its start and never read through the module attribute again.

**Verdict**: FAIL — the test asserts the wrong thing. The module-global split-path guard is only meaningful if it actually invokes the call site that would fail in production.

---

### SQ3 — C3 real-machine granularity pivot: is "real machines share md5 by design" correctly grounded?

**Question**: The brief explicitly says C3 should test "M14 mode 1 md5 ≠ M14 mode 2 md5". Tester pivoted: M14 modes share md5 (documented as "flat schema by design"), and the per-mode granularity regression is tested on M1sim. The memory `feedback_md5_granularity_and_stamping.md` says per-mode md5 was added "because aggregating across modes invalidated mode 1 chunks when mode 2 weights changed". Does the real `configs/machines.json` actually have a single md5 for all modes of real machines, confirming the pivot is architecturally correct and not a workaround for a missing feature?

**Attempted answer**: Confirmed by direct inspection. `configs/machines.json` entry for M14 (line 1516–1531) has only `configSummaryMd5` and `codeSummaryMd5` at the top level — no `modesMd5` block. Real machines are stamped once at build time by the upstream system; virtual machines compute per-mode md5 locally from their weights files. The schema asymmetry is real. The pivot to M1sim for per-mode granularity testing is architecturally correct. What was NOT done: the brief's literal intent ("M14 mode 1 md5 ≠ M14 mode 2 md5") cannot be satisfied for real machines. The tester chose to document and assert the real behavior (`test_real_machine_m14_modes_share_md5`) rather than fail. That is the right call — but it means the test file contradicts the brief's C3 contract literally. Downstream reviewers reading the brief after looking at the test will encounter this inconsistency.

**Verdict**: PARTIAL — the pivot is architecturally correct and well-documented in the test. The brief's literal C3 language is unmet. This is not a defect in the test, but the brief should be amended (or the test comment should explicitly note "brief's C3 literally unachievable for real machines; see M1sim tests for the invariant that matters").

---

### SQ4 — β's `except Exception: pass` (app.py:6969): is there a missing error-surfacing test?

**Question**: The β writer path in `_run_generate_report` (lines 6955–6973) wraps the entire patch operation in `except Exception: pass` with the comment "Best-effort patch — never fail the whole generate-report over a metadata hole." Per memory `feedback_no_silent_swallow.md`, any best-effort post-hook must persist diagnostic to disk. The test `test_alpha_beta_both_handle_malformed_json` (line 768) checks that malformed JSON returns `("", "")` from `_get_machine_md5`, but it does not test the generate-report `try/except` wrapper. Is the silent swallow in β's write path adequately tested?

**Attempted answer**: Not tested. The test file tests `_get_machine_md5` in isolation (correctly returns `("", "")` on malformed JSON). But the `except Exception: pass` at line 6969 wraps a different scope — it catches any failure in the entire patch block including `read_json`, `write_json`, dict mutation, etc. If `write_json` raises (permissions, disk-full), the exception is silently swallowed and no diagnostic is written. The memory `feedback_no_silent_swallow.md` was specifically written to prevent this pattern. The existing β test does not guard against it.

**Verdict**: FAIL — missing test. The `except Exception: pass` at app.py:6969 is a pre-existing error-swallow, but P1-A2 is the parity baseline and should at minimum document this gap explicitly (it doesn't appear in 03_tests.md's open-gaps section).

---

### SQ5 — Return-order mismatch between P1-A2 fixture assertions and P1-B1 canonical signature: will dedup break this test?

**Question**: `P1-B1` brief (`07_lookup_machine_md5_dedup/00_ticket.md` line 16) specifies the canonical function signature as `lookup_machine_md5(machine, machines_config_path) -> (code_md5, config_md5)` — note the order: `code_md5` first, then `config_md5`. But both current implementations return `(config_md5, code_md5)` (config first), and all of P1-A2's assertions encode `(config_md5, code_md5)` tuple order (e.g., `md5_alpha[0]` checks `config_md5` throughout). If P1-B1 implements the canonical function with the documented reversed tuple order, every C2/C5 assertion in this test file that destructures the tuple will silently invert config and code md5 values — the test may still pass because both M14 config and code md5 values happen to be different strings, but the semantic meaning will be swapped. Is this an undetected contract collision between P1-A2 and P1-B1?

**Attempted answer**: Yes, this appears to be a forward-compatibility issue. The P1-B1 brief says `-> (code_md5, config_md5)` but the current impl returns `(config_md5, code_md5)`. P1-A2's fixture has `configSummaryMd5 = "4fcf00c48b3d6979aef058fed9ed5f94"` and `codeSummaryMd5 = "536fc5a2a8f2ecf1fd8c6dfcf2c025cc"`. If the canonical function in P1-B1 reverses the tuple, the test's `assert md5_alpha[0]` non-empty check would pass (because code md5 is non-empty too), but assertions like `test_virtual_machine_m1sim_modes_differ`'s `assert md5_mode1[0] != md5_mode2[0]` (line 380: "config_md5 must differ across modes") would now be asserting code_md5, which is documented to be the SAME across modes (line 384). That assertion would flip from passing to failing. This is a cross-ticket contract collision. Either the P1-B1 brief has a typo in the tuple order, or P1-A2 needs a clear annotation that its tuple order matches the current (pre-dedup) convention.

**Verdict**: FAIL — this cross-ticket inconsistency is not documented anywhere in the chain. The tester's 03_tests.md makes no mention of P1-B1's canonical signature or tuple order. The verifier (absent) would likely not catch this either since it runs the test file in isolation.

---

### SQ6 — Subprocess gap for α: does `test_full_pipeline_m14.py` cover it?

**Question**: 03_tests.md Gap 1 defers the subprocess-level α test to the verifier, suggesting it might already be covered by `test_full_pipeline_m14.py`. Direct inspection of `tests/backend/test_full_pipeline_m14.py` (via grep) shows zero mentions of `config_md5`, `code_md5`, or `summary_md5`. Is the subprocess gap for α actually covered by any existing test?

**Attempted answer**: No. `test_full_pipeline_m14.py` does not assert md5 fields in the output summary. The tester's assumption that this might be covered is unverified. The real α function runs inside the analyzer subprocess at `player_impact_analyzer.py:7394` (`_summary_config_md5, _summary_code_md5 = _lookup_machine_md5(args.machine)`), and no test spawns a real subprocess and asserts the summary's `config_md5` field is non-empty. The subprocess gap is real.

**Verdict**: FAIL — the deferred assumption in Gap 1 is incorrect. This is documented as a gap but the verifier was asked to confirm whether it's covered elsewhere; it is not.

---

### SQ7 — C1 harness: does `test_alpha_lookup_is_callable` actually invoke a writer path or just the monkeypatched module attribute?

**Question**: `TestThreeWriterHarness::test_alpha_lookup_is_callable` (line 136) does `monkeypatch.setattr(pia, "_lookup_machine_md5", lambda machine: _patched_alpha_lookup(machine, m14_machines_json))` and then calls `pia._lookup_machine_md5("M14")`. This does not call the real `_lookup_machine_md5` at all — it calls the lambda, which calls `_patched_alpha_lookup`. The test asserts `isinstance(result, tuple) and len(result) == 2`. This is a tautology: it's asserting that a lambda returns a tuple of length 2, which it always will. Is this a meaningful C1 harness test for α?

**Attempted answer**: No, it is not. The test as written asserts only that the test helper (lambda + `_patched_alpha_lookup`) returns a 2-tuple — which is guaranteed by construction. It does not assert anything about the real `_lookup_machine_md5` function. A real C1 harness test for α should either call `pia._lookup_machine_md5("M14")` directly (monkeypatching the hardcoded path), or omit α from C1 and document why (noting α cannot be called with a fixture path without significant monkeypatching).

**Verdict**: FAIL — the C1 harness test for α is vacuous. It demonstrates the test infrastructure (importing pia + calling a lambda) rather than the α writer path.

---

### SQ8 — C4 "does not overwrite" contract: is it tested against the correct scenario?

**Question**: `test_gamma_patcher_does_not_overwrite_existing_md5` (line 478) asserts that γ does not overwrite non-empty md5 fields. This tests a defensive guard in `_patch_summary_md5_tags` (lines 535–538: `if config_md5 and not payload.get("config_md5")`). The test creates a summary with pre-filled md5 fields and calls the patcher. The test passes because the guard is `not payload.get("config_md5")` — if the field is non-empty, the patcher skips it. But the test does not test the partial-fill case: what if `config_md5` is empty but `code_md5` is non-empty? In that case, the patcher should fill `config_md5` but leave `code_md5` alone. Is this edge case covered?

**Attempted answer**: Not directly. The test `test_gamma_patcher_no_op_when_both_md5s_empty_input` (line 549) tests the case where both INPUT md5s (the ones being written) are empty. But there is no test where the EXISTING summary has `config_md5 = ""` and `code_md5 = "existing_value"` — the partial-fill scenario. This is a known edge case from the patcher's logic: the guard operates independently on each field. The missing test leaves the partial-fill behavior unverified.

**Verdict**: PARTIAL — the overwrite-protection test is present but incomplete. Partial-fill case is unverified.

---

### SQ9 — Agreement for M14 mode 2, 5, 7: is the parity contract tested beyond mode 1?

**Question**: The brief says "For M14 mode 1: `md5_α == md5_β == md5_γ`". For real machines, mode does not affect the md5 value (flat schema). But the agree test only explicitly tests mode 1. If a future change to β or α introduced mode-conditional branching for real machines (e.g., a bug where β returns empty for modes other than 1), would the C2 tests catch it?

**Attempted answer**: No. All C2 tests for real-machine M14 use mode=1. Given that the real-machine schema is flat (all modes return the same value), testing mode 2/5/7 would be redundant today — but is not redundant as a regression guard for β's `modesMd5` branch logic. If β's `modesMd5` lookup code introduced a bug that incorrectly matched against mode 2 even for real machines (which have no `modesMd5` block), a mode-2 test would catch it. The test `test_beta_mode_aware_with_modesMd5_block` (line 780) covers β's mode-aware path via a synthetic fixture, which is adequate for unit-testing β's logic. However it does not test that real machine M14 mode 2 returns the correct flat value from the REAL config file.

**Verdict**: PARTIAL — the mode-2/5/7 real-machine agreement is not tested directly; coverage is adequate for the current schema but creates a gap if β's modesMd5 branch logic regresses.

---

### SQ10 — Real-vs-virtual schema asymmetry: is it intentional architecture or accidental drift, and does the test settle this?

**Question**: Per memory `feedback_md5_granularity_and_stamping.md`, per-mode md5 was introduced because the aggregate md5 invalidated mode-1 chunks when mode-2 weights changed. Virtual machines have `modesMd5` (per-mode). Real machines have only flat md5. The memory says "per-mode IS the right thing" but real machines have flat. Is this an upstream API constraint (real machines' md5 is computed by the upstream build system and stamped into `machines.json`, so the console has no say) or is it incomplete migration (real machines should also have per-mode md5 but nobody has done it)?

**Attempted answer**: Based on context: the flat md5 for real machines is an upstream API constraint. `configs/machines.json` is generated by the upstream build system and provides a single `configSummaryMd5` per machine, covering all modes. The console does not recompute this — it reads what the upstream provides. Virtual machines have locally-computed per-mode md5 because the console computes their weights itself. The memory `feedback_md5_granularity_and_stamping.md` discusses `compute_machine_md5` vs `compute_machine_md5_for_mode` — both of which are virtual-machine functions in `slot_designer/core/backend/`. The per-mode problem described in that memory was a virtual-machine bug. Real machines were never affected because their md5 was always computed externally (once per machine, not per mode). The test `test_real_machine_m14_modes_share_md5` correctly documents this distinction. The chain's treatment of this as "intentional by-design" is correct. However, 03_tests.md does not explicitly call out the upstream-constraint reason — it says "flat schema, by design" without explaining WHY (upstream build artifact vs local choice). This leaves future readers uncertain.

**Verdict**: PARTIAL — the architectural reason is underdocumented. The test's docstring should say "upstream build artifact — real machines' md5 is stamped externally; console cannot compute per-mode" to prevent future implementers from thinking this is a missing feature.

---

## Chain Disagreements (2)

### Disagreement 1: Brief C3 vs tester's scope

Brief C3 says: "Run the test on M14 with mode 1 AND mode 2. Test asserts mode 1's md5 ≠ mode 2's md5."
Tester's result: M14 mode 1 and mode 2 share the same md5 by design (flat schema). Tester pivoted to M1sim for the per-mode assertion.

This is a real brief-vs-test mismatch. The tester's call is architecturally correct, but the brief was written with a false assumption. The brief's C3 is literally unmet. This should be documented in the brief as an amendment, or the test docstring should clearly note "brief §C3 literal form unachievable for real M14 — see per-mode tests on M1sim for the invariant that matters".

### Disagreement 2: P1-B1 canonical function signature vs P1-A2 tuple order

Brief P1-B1 (`07_lookup_machine_md5_dedup/00_ticket.md` line 16) documents the canonical signature as returning `(code_md5, config_md5)` — reversed from current `(config_md5, code_md5)`. P1-A2's test file and 03_tests.md both assume `(config_md5, code_md5)` order throughout. These two tickets will silently conflict if P1-B1 is implemented as documented. Neither 03_tests.md nor the brief for P1-A2 mentions this. This is a cross-ticket brief inconsistency that must be resolved before P1-B1 starts.

---

## Hidden Assumptions (4)

1. **`_patched_alpha_lookup` stays in sync with `_lookup_machine_md5`**: The entire α test strategy depends on `_patched_alpha_lookup` being an accurate mirror of the real α function. There is no mechanism to detect if they diverge (no test calls both and compares output against the same input). Any change to `_lookup_machine_md5` (e.g., adding mode awareness in P1-B1) that doesn't also update `_patched_alpha_lookup` will cause silent false-green tests for C2.

2. **M1sim mode 1 and mode 2 genuinely differ in weights**: C3's assertion `md5_mode1 != md5_mode2` will only catch the per-mode granularity regression if M1sim actually has different weights for mode 1 and mode 2. If M1sim's `machines_virtual.json` entry happens to have the same `modesMd5` values for modes 1 and 2 (or if the `modesMd5` block for mode 2 is missing and β falls through to flat), the test would pass vacuously. The test does not assert that the underlying weights files differ before asserting the md5s differ.

3. **γ's `_load_virtual_registry` reads the same file β uses for virtual lookups**: The C2 test `test_beta_gamma_agree_virtual_m1sim_mode1` calls `_load_virtual_registry()` (which hardcodes `_ROOT / "slot_designer" / "configs" / "machines_virtual.json"`) and also calls `_get_machine_md5("M1sim", virtual_config, mode=1)` where `virtual_config = ROOT / "slot_designer" / "configs" / "machines_virtual.json"`. These two paths are computed differently (one uses `_ROOT` from virtual_analyzer.py, one uses `ROOT` from the test file). If they resolve to different paths (e.g., in a different checkout layout), the agreement test would compare md5s from different registries and could pass or fail spuriously.

4. **The three-way agreement test assumes α is correctly ignorant of virtual machines**: `test_three_way_agreement_virtual_m1sim_mode1` asserts `md5_alpha == ("", "")` for M1sim — i.e., that M1sim is NOT in `configs/machines.json`. This is true today, but there is no runtime enforcement preventing someone from accidentally adding M1sim to the real registry. If M1sim were ever added to `configs/machines.json` with wrong md5 values, the test would fail in an unexpected direction (α returns non-empty, assertion fails, but reason is not obvious).

---

## Edge Cases Not Covered

1. **Partial-fill scenario for γ patcher**: summary has `config_md5 = ""` but `code_md5 = "existing_value"`. Patcher should fill only `config_md5`.

2. **γ patcher with partially-empty md5 input**: called with `config_md5 = "something"` but `code_md5 = ""`. The guard `if not (config_md5 or code_md5)` passes, patcher proceeds. Result: `config_md5` filled, `code_md5` not filled (because input code was empty). Is this correct? No test covers it.

3. **Mode-aware β for real machines — modes 2, 5, 7**: β's `modesMd5` branch lookup is tested via a synthetic fixture (`test_beta_mode_aware_with_modesMd5_block`), but never against the real `configs/machines.json` for modes 2/5/7 of M14. If a future schema change added a `modesMd5` block to real machines, the tests would not detect β's behavior change.

4. **α call site at `player_impact_analyzer.py:7394` with `--upstream-config-md5` override**: when `args.upstream_config_md5` is non-empty, α is bypassed entirely (lines 7390–7394). No test covers this code path or verifies that the bypass produces a non-empty summary md5 in the produced JSON.

5. **`_compute_md5s(entry, mode=None)` fallback (aggregate md5) path**: `_compute_md5s` at line 444 falls through to `compute_machine_md5(entry)` when mode is None. No test calls γ's `_compute_md5s` with `mode=None`. This is documented as "rare; legacy callers" but is untested.

6. **Trigger-session machine / variant-machine (`$` selector) entries**: `configs/machines.json` contains entries like `"M15$TopDollarSelector$0$"`. α's lookup iterates machines by `m.get("machine") == machine`. If a variant machine name were passed to α, would it match correctly? Not tested. β has the same issue — variant names are separate rows and would be found, but α is not tested for variant machine names.

7. **Agreement for machines with `codeSummaryMd5 == configSummaryMd5`**: The inject-bug test (Bug 1 in 03_tests.md) relies on M1 and M14 having different `configSummaryMd5`. It happens to work because they differ. If both machines had the same `configSummaryMd5`, the inject-bug test would silently pass even with the bug injected (the "wrong machine" lookup would return the same value as the correct lookup). This brittle fixture dependency is undocumented.

---

## Required Revisions (APPROVE-WITH-REVISIONS)

### R1 — C2 must call the real `_lookup_machine_md5`, not `_patched_alpha_lookup`

Corresponds to SQ1 and SQ7. The "α agrees with β" tests must call `pia._lookup_machine_md5("M14")` directly, using `monkeypatch` to redirect α's hardcoded path to the fixture. `_patched_alpha_lookup` can remain as a convenience helper for inject-bug tests, but it cannot be the primary test vehicle for real-α coverage.

### R2 — C5 module-global split-path must invoke main() or equivalent

Corresponds to SQ2. The `test_c5_module_global_split_path_alpha_uses_call_not_global` test must either: (a) call `pia.main()` with monkeypatched `_lookup_machine_md5` and assert the written summary has the sentinel value, or (b) be renamed to something honest like `test_monkeypatch_setattr_works_on_pia_module` and a separate, correct split-path test be added. If invoking `main()` is too expensive for a unit test, the test comment must be amended to say "this test does not verify the call site in main(); subprocess-mode test deferred to P1-A1 (three-invocation parity)".

### R3 — Cross-ticket tuple-order collision must be resolved before P1-B1

Corresponds to SQ5. P1-B1's brief documents `-> (code_md5, config_md5)` (reversed). P1-A2's test file assumes `(config_md5, code_md5)` throughout. This discrepancy must be resolved: either P1-B1 brief is corrected to `-> (config_md5, code_md5)`, or P1-A2's tests are annotated with "NOTE: tuple order will change in P1-B1; update assertions post-dedup". Without resolution, P1-A2 will silently swap semantics after P1-B1 lands.

---

## Commit-Message `## Self-critique` Section

```
## Self-critique

- SQ1 — Does C2 test the real `_lookup_machine_md5` or a reimplementation?
  A: `_patched_alpha_lookup` in the test file mirrors the real α logic but is
  a separate function. C2 tests the reimplementation-of-α vs β. Real α is
  only exercised via monkeypatch in C5. OPEN — R1 required: C2 should call
  `pia._lookup_machine_md5` directly via path-redirect monkeypatch.

- SQ2 — Does the module-global split-path test prove main() uses the
  module-level call site?
  A: No. The test proves `monkeypatch.setattr(pia, ...)` works (trivially
  true for any module attr). It does not call `main()`. OPEN — R2 required:
  either invoke `main()` with monkeypatched α or honestly rename the test.

- SQ3 — Brief C3 says M14 mode 1 md5 ≠ mode 2 md5. Real M14 has flat md5.
  A: Real machines have upstream-stamped flat md5 (no `modesMd5` block).
  Per-mode granularity is a virtual-machine feature. Pivot to M1sim is
  architecturally correct. Test documents this explicitly.
  ADDRESSED — brief C3 literal form unachievable for real M14; test and
  03_tests.md both document the pivot.

- SQ4 — β's `except Exception: pass` at app.py:6969 not tested.
  A: Pre-existing swallow. No test in this file asserts failure is surfaced.
  OPEN — documented as undocumented gap; future P1-B2 (summary-patcher dedup)
  should add a failure-mode test per memory feedback_no_silent_swallow.md.

- SQ5 — P1-B1 brief documents reversed tuple order `(code_md5, config_md5)`.
  P1-A2 assumes `(config_md5, code_md5)` throughout. Cross-ticket collision.
  A: Not resolved in this ticket. OPEN — R3 required: one of the two briefs
  must be corrected before P1-B1 starts.

- SQ6 — Is subprocess gap for α covered by test_full_pipeline_m14.py?
  A: No. `test_full_pipeline_m14.py` contains zero assertions on `config_md5`
  or `code_md5` fields. Gap is real, not covered elsewhere.
  OPEN — 03_tests.md Gap 1 documents this but the assumption that existing
  tests cover it is incorrect.

- SQ7 — Is test_alpha_lookup_is_callable a meaningful C1 harness test?
  A: No. It calls a lambda (wrapping _patched_alpha_lookup) and asserts the
  result is a 2-tuple. Tautological given the lambda definition.
  OPEN — needs to call the real `_lookup_machine_md5` to be meaningful.

- SQ8 — Is γ patcher's partial-fill edge case (one field empty, one non-empty)
  covered?
  A: No. Tests cover all-empty and all-non-empty input/output; partial-fill
  (output config empty, code non-empty) is untested.
  OPEN — minor gap, edge case documented in 05_critique.md.

- SQ9 — Is M14 mode 2/5/7 agreement tested?
  A: No. C2 tests only mode 1 for real M14. β's modesMd5 branch logic tested
  via synthetic fixture only.
  OPEN — partial coverage, low priority for flat-schema real machines.

- SQ10 — Real-vs-virtual schema asymmetry: upstream constraint or incomplete
  migration?
  A: Upstream constraint. Real machines' md5 is computed by the upstream
  build system and stored in machines.json; console cannot recompute per-mode.
  Virtual machines compute locally. Distinction is architecturally correct but
  underdocumented in test docstrings.
  OPEN — suggest adding "upstream build artifact" explanation to
  test_real_machine_m14_modes_share_md5 docstring.
```

---

## Summary

- **Verdict**: APPROVE-WITH-REVISIONS
- **Blocking revisions**: R1 (real α coverage), R2 (split-path test validity), R3 (cross-ticket tuple order)
- **Non-blocking gaps documented**: SQ4 (β silent swallow), SQ6 (subprocess gap), SQ7 (C1 vacuous harness), SQ8 (partial-fill edge), SQ9 (mode 2/5/7 real-machine), SQ10 (upstream-constraint doc)
- **Verifier note**: `04_verification.md` was absent when this critique was written. If verifier confirms any of R1/R2/R3 are already addressed in the actual test run (e.g., verifier found the real α is called somewhere I missed), main session may override the relevant revision requirement.
