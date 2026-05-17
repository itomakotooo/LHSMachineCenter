# 05_critique.md — P1-B3 Session CI Half-Width Dedup

## Verdict

**APPROVE-WITH-REVISIONS**

One mechanically incorrect test (`test_c7_inject_bug_divergent_formula_in_virtual_callsite`) makes a false claim about what it proves, and a third callsite consumer (`test_analyzer_resume.py::TestSessionHalfwidthHelper`) was not flagged by the implementer. Neither is a production regression, but the test gap is a real coverage hole against memory `feedback_enumerate_safety_paths.md`.

---

## Stress Questions (6)

---

### SQ1 — Alias vs. monkeypatching: does `test_c7_inject_bug_divergent_formula_in_virtual_callsite` prove what it claims?

**Question**: `virtual_analyzer.py` line 273 sets `_ci_halfwidth_pp = session_halfwidth_pp` at import time. This binds `va._ci_halfwidth_pp` to the function object. Later, `test_c7_inject_bug_divergent_formula_in_virtual_callsite` patches `sampler.session_halfwidth_pp` via `monkeypatch.setattr(sampler, "session_halfwidth_pp", _buggy)` and conditionally patches `va.session_halfwidth_pp` (only if `hasattr(va, "session_halfwidth_pp")`). After dedup the attribute `va.session_halfwidth_pp` exists (it is re-imported from sampler on line 78 of virtual_analyzer.py). So the conditional `if hasattr(va, "session_halfwidth_pp")` branch IS taken and `va.session_halfwidth_pp` is also patched. However: does calling `va._ci_halfwidth_pp(...)` after these patches exercise the buggy function?

**Analysis**: `va._ci_halfwidth_pp` was set at import time to the original `session_halfwidth_pp` function object. Patching `sampler.session_halfwidth_pp` replaces the binding in `sampler.__dict__` but does NOT update `va._ci_halfwidth_pp`, which still holds the direct reference to the original (non-buggy) function. Patching `va.session_halfwidth_pp` replaces that separate name in `va.__dict__`, also not touching `va._ci_halfwidth_pp`. The test docstring says "patching sampler also patches virtual's result (they share the same function object)" — this is correct for the case where you call the function through `sampler.session_halfwidth_pp`, but it is false for calling `va._ci_halfwidth_pp()`. The test's assertions only check `sampler.session_halfwidth_pp(...)` output, not `va._ci_halfwidth_pp(...)` output, so the test body happens to pass. But it does not prove the injected bug would be caught if the bug were only in `va._ci_halfwidth_pp`'s path.

**Attempted answer**: The test is mechanically green (its assertions are about `sampler.session_halfwidth_pp` output and do correctly show divergence there). But the test's stated purpose — "injecting a wrong value at the virtual callsite makes test_c6 fail" — is not substantiated. The C6 test (`test_c6_virtual_ci_halfwidth_and_sampler_agree_for_canonical_input`) calls `va._ci_halfwidth_pp(...)` which post-dedup calls the original un-patched function. To actually prove the C7 claim for the virtual alias path, the test would need to also patch `va._ci_halfwidth_pp` directly (not just `va.session_halfwidth_pp`).

**Verdict**: ✗ Not adequately addressed. The test is not a false positive (it passes for correct reasons), but its stated proof claim for the virtual path is wrong. A real divergent formula injected via `monkeypatch.setattr(va, "_ci_halfwidth_pp", _buggy)` would NOT be caught by any current test in the set.

---

### SQ2 — Inject experiment restore discipline: was the file genuinely restored?

**Question**: Experiment 1 (wrong multiplier in sampler.py) and Experiment 2 (local definition re-injected into player_impact_analyzer.py) both claim "Restored … Result after restore: 24/24 PASS." Per memory `feedback_integration_test_argv.md`, inject experiments must be genuine file-edit → run-red → restore → run-green, not in-process simulations.

**Analysis**: Experiment 1 involves an edit to `fresh_slotlab/sampler.py`. The current file at line 255 reads `return t * se * 100.0` (confirmed by direct read), consistent with a clean restore. Experiment 2 claims the local definition was added to `player_impact_analyzer.py:1004` and then removed. The current file (read at lines 980-1013) confirms no local `def session_halfwidth_pp(` exists in non-comment text. So both restores appear to have happened. However: neither experiment provides a hash, git diff, or subprocess run log — the evidence is just the tester's claim. The 03_tests.md log says "Result after restore: 24/24 PASS" but there is no verifier-generated output confirming this.

**Attempted answer**: Restores are consistent with the current file state. Cannot prove they went through red between the two green states from artifacts alone — but current file state is correct, and the tests themselves are mechanically correct about what they would catch.

**Verdict**: ⚠ Partial. The restore is plausible from file state, but the experiment log lacks subprocess output (per `feedback_integration_test_argv.md` discipline). For a third consecutive dedup ticket this is a recurring artifact gap.

---

### SQ3 — Third callsite hunt: did the implementer enumerate all consumers?

**Question**: `02_implementation.md` lists 3 internal callers in virtual_analyzer (lines 852, 972, 1009) and the test import at `test_virtual_analyzer_ci_stop.py:45`. Brief `feedback_enumerate_safety_paths.md` says: when adding a safety carve-out, grep every path. P1-B1 and P1-B2 both surfaced 3rd callsites. Did P1-B3 miss any?

**Analysis**: Grepping the whole repo for `session_halfwidth_pp|_ci_halfwidth_pp` in `.py` files returns 9 files. The implementer flagged: `sampler.py` (canonical), `player_impact_analyzer.py` (callsite 1), `virtual_analyzer.py` (callsite 2), `test_virtual_analyzer_ci_stop.py` (existing test consumer), and `test_session_halfwidth_canonical.py` (new test). Not mentioned in `02_implementation.md`:

- `tests/backend/test_analyzer_resume.py::TestSessionHalfwidthHelper` — 4 tests that do `from fresh_slotlab.player_impact_analyzer import session_halfwidth_pp`. This import still works after dedup (Python re-exports the imported name), so there is no runtime regression. But the implementer did not enumerate this consumer, and the tester did not add it to the consumer map.
- `tests/backend/test_t_critical_table_canonical.py` — exercises `va._ci_halfwidth_pp` in 4 tests under C6. This was listed implicitly as "existing tests" but not explicitly enumerated in the traceability table.
- `tests/backend/test_batch_analyzer_cli.py` — one comment-only reference (no live callsite).
- `src/web_console/backend/app.py` — one comment-only reference.

**Attempted answer**: The `test_analyzer_resume.py` consumer is a genuine miss. It is not a production bug (re-export works), but it is a consumer whose behavior under the dedup was not verified or acknowledged.

**Verdict**: ⚠ Partial. The un-enumerated consumer (`test_analyzer_resume.py`) passes in practice but was not audited. The traceability table in `02_implementation.md` is incomplete.

---

### SQ4 — C4 spy test: is monkeypatching `sampler.t_critical_95` mechanically valid for a function defined in the same module?

**Question**: `test_c4_session_halfwidth_pp_uses_canonical_t_critical` patches `sampler.t_critical_95` (via direct attribute assignment) and then calls `sampler.session_halfwidth_pp`. Inside `session_halfwidth_pp`, line 254 calls `t_critical_95(n - 1)` as a bare name. Python resolves bare names via the function's `__globals__`, which is `sampler.__dict__`. Patching `sampler.t_critical_95 = _spy` DOES rebind that dict entry. So the spy intercepts the call correctly.

**Analysis**: The mechanism is sound. Python's LEGB name resolution for module-level functions uses `__globals__` (the module dict) at call time, not at definition time. Replacing `sampler.t_critical_95` in the module dict before calling `sampler.session_halfwidth_pp` is the correct way to spy on a same-module function reference.

**Attempted answer**: Mechanically correct. The spy will be called, the call_log will be populated, and the assertions are valid.

**Verdict**: ✓ Adequately addressed.

---

### SQ5 — C3 snapshot: was the value hand-verified before being used, or is it self-referential?

**Question**: The C3 snapshot value `0.5375902929994492` is the critical anchor for regression. Was it computed independently (before running the new code) or snapshotted from the first run of the new code (vacuously correct if the new code has the same bug as the old)?

**Analysis**: `03_tests.md` provides a full hand-computation derivation at lines 98-127, showing each arithmetic step with intermediate values (mean, var, se, t, product). The Python one-liner at the end claims `python -c "…"` gives `0.5375902929994492`. The derivation is independently checkable:
- `var = (910.0 - 950.0^2/1000) / 999 = 7.5/999`
- `se = sqrt(7.5/999/1000)` — arithmetic matches
- `t_critical_95(999)` = linear interp between (120, 1.980) and (1000, 1.962) at ratio 879/880 — arithmetic matches
- `t * se * 100.0 = 1.9620204545... * 0.002739983121... * 100.0` — the product is consistent with the stated snapshot

The derivation was done independently of the code (it uses the t_critical formula from the canonical table, not from executing the new function). The one-liner verification (`python -c "..."`) computes the value by hand-calling `t_critical_95` from sampler directly, not by calling `session_halfwidth_pp`. This is a genuine out-of-process cross-check, not a self-referential snapshot.

**Verdict**: ✓ Adequately addressed. The hand computation is independent and checkable.

---

### SQ6 — Import-time side effects in sampler.py: does the 42-line addition introduce any?

**Question**: `sampler.py` is imported by `virtual_analyzer.py` which runs as a subprocess. Memory `feedback_subprocess_import_suicide_and_module_globals.md` says any import-time side effect corrupts the subprocess output stream. The implementer added 42 lines (the `session_halfwidth_pp` function body + docstring). Does this introduce any module-level execution?

**Analysis**: The added code is a pure `def` statement (function definition). There are no module-level calls, no `build_virtual_app()` calls, no top-level assignments from calls. The tester added two tests specifically checking this:
- `test_sampler_import_is_side_effect_free`: dynamic import after cache clear, captures stdout/stderr
- `test_sampler_has_no_top_level_function_call`: AST walker checking for bare calls at module scope (excluding `__main__` guard)

The `math` module was already imported in sampler.py (line 6). No new imports added.

**Verdict**: ✓ Adequately addressed. The added function is a pure def with no side effects. Two tests guard this.

---

## Chain Disagreements

**Implementer ↔ Tester on alias monkeypatching scope**: The implementer notes in `02_implementation.md` risk section: "monkeypatching `va._ci_halfwidth_pp` in tests would shadow only the alias, not `session_halfwidth_pp` itself." This is correct and clearly stated. However, the tester's `test_c7_inject_bug_divergent_formula_in_virtual_callsite` does the opposite: it patches `sampler.session_halfwidth_pp` and claims this "patches virtual's result." The tester's claim is approximately true for `va.session_halfwidth_pp` (which is a separate import in `va.__dict__`), but it is false for `va._ci_halfwidth_pp` (the alias). The implementer identified the risk; the tester wrote a test that does not actually guard that risk path.

**Implementer enumerated 3 internal callers; tester's coverage map does not cross-reference**: `02_implementation.md` says internal callers are at lines 864, 984, 1021 (post-edit). The tester's C6 tests only check numerical parity for the alias as a callable from outside; they do not verify that the internal callers in the CI-stop loop remain functionally unchanged. This is partially covered by `test_virtual_analyzer_ci_stop.py` (existing tests), but the explicit mapping from internal caller lines to specific test assertions is absent.

---

## Hidden Assumptions

1. **`va.session_halfwidth_pp` and `va._ci_halfwidth_pp` both exist post-dedup**: The C7 inject test conditionally patches `va.session_halfwidth_pp`, assuming it is a distinct module-level attribute. It is — virtual_analyzer imports it on line 78 (`from fresh_slotlab.sampler import session_halfwidth_pp`). But `va._ci_halfwidth_pp` is the alias that the three internal callers actually use. The assumption that patching `va.session_halfwidth_pp` tests the same code path as calling `va._ci_halfwidth_pp` is wrong.

2. **`test_analyzer_resume.py::TestSessionHalfwidthHelper` will keep passing**: The 4 tests import `session_halfwidth_pp` from `player_impact_analyzer`. After dedup, `player_impact_analyzer` no longer defines it locally — it imports it. Python module namespaces re-export imported names, so the import works. But this consumer was never explicitly audited in this ticket, and a future refactor that changes the import structure in `player_impact_analyzer` could silently break `test_analyzer_resume.py` in a way not caught by this ticket's C1-C7 contracts.

3. **The subprocess verifier (W2) will exist**: The tester explicitly delegates subprocess coverage to `impl-verifier`. The verifier artifact (`04_verification.md`) does not exist at critique time. This ticket's safety argument has a pending external dependency.

---

## Edge Cases Not Covered

1. **Direct call to `va._ci_halfwidth_pp` with a buggy alias replacement**: If future code does `va._ci_halfwidth_pp = some_other_fn` (directly reassigning the alias in va's namespace), no test catches the subsequent divergence because no test currently calls `va._ci_halfwidth_pp` via a path that would observe the breakage in isolation from `va.session_halfwidth_pp`.

2. **n=2 boundary for the alias path**: `test_c5_n_2_is_defined` checks `session_halfwidth_pp` directly from sampler. No test checks `va._ci_halfwidth_pp(2, ...)` specifically — the existing `test_virtual_analyzer_ci_stop.py` tests cover `n=5` and `n=10`, but not the n=2 boundary via the alias.

3. **Floating-point corner: `ret_sq_sum < ret_sum^2/n` before `max(0.0, ...)`**: The `max(0.0, ...)` guard is present in the implementation and tested via `test_c3_zero_variance_returns_zero`. No test exercises the case where the raw numerator is slightly negative (floating-point catastrophic cancellation), verifying the `max(0.0, ...)` clamp actually fires and returns `0.0` rather than attempting `math.sqrt` of a negative.

4. **`player_impact_analyzer` standalone-script path**: The `except ImportError` block at line 87 imports `from sampler import session_halfwidth_pp`. This is the path taken when the file is run as `python player_impact_analyzer.py` (not as a package member). No inject-bug test exercises this path — both inject experiments patch the package-mode import. The standalone path is functionally equivalent but untested in this ticket.

---

## Required Revisions

### R1 (SQ1 — Required): Fix `test_c7_inject_bug_divergent_formula_in_virtual_callsite`

The test's stated proof — "injecting a wrong value at the virtual callsite makes test_c6 fail" — is not demonstrated. The test only asserts that `sampler.session_halfwidth_pp` returns the buggy value after patching, which is trivially true. It does not call `va._ci_halfwidth_pp` to verify the alias path is guarded.

The test must be extended to call `va._ci_halfwidth_pp(...)` after the patch and assert it returns the buggy value (i.e., `va._ci_halfwidth_pp` must also be patched, since the alias holds the original function object and patching `sampler.session_halfwidth_pp` does not update it).

Specifically: add `monkeypatch.setattr(va, "_ci_halfwidth_pp", _buggy)` alongside the existing patches, then call `va._ci_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)` and assert the result matches the buggy value. Without this, the C7 inject test does not prove the virtual alias path is covered.

### R2 (SQ3 — Required): Enumerate `test_analyzer_resume.py::TestSessionHalfwidthHelper` as a known consumer

`02_implementation.md` should list this as a known indirect consumer of `session_halfwidth_pp` via `player_impact_analyzer`. The tester should verify that `TestSessionHalfwidthHelper` passes under the dedup (which it does, since module re-export works) and that C1's grep of the repo does not need to be extended to cover this consumer. A one-line entry in the coverage map or risk section suffices.

---

## Commit Message `## Self-critique` Section (paste-ready)

```
## Self-critique (adversarial review)

- Q: Does `_ci_halfwidth_pp = session_halfwidth_pp` alias in virtual_analyzer.py
  mean that monkeypatching `sampler.session_halfwidth_pp` also updates the alias?
  A: No. The alias is frozen at import time. `va._ci_halfwidth_pp` holds the
  original function object. Patching `sampler.session_halfwidth_pp` does not
  update it. The C7 virtual-callsite inject test (test_c7_inject_bug_divergent_
  formula_in_virtual_callsite) currently proves the sampler path is guarded but
  not the va._ci_halfwidth_pp path. OPEN: impl-tester must patch va._ci_halfwidth_pp
  directly in that test to close the gap.

- Q: Did the implementer enumerate all consumers of session_halfwidth_pp / 
  _ci_halfwidth_pp in the repo?
  A: Not completely. test_analyzer_resume.py::TestSessionHalfwidthHelper imports
  session_halfwidth_pp from player_impact_analyzer (4 tests). These still pass
  since player_impact_analyzer re-exports the imported name. Not flagged in
  02_implementation.md. OPEN: tester should acknowledge this consumer.

- Q: Is the C3 snapshot value self-referential or independently verified?
  A: Independently verified. 03_tests.md shows full arithmetic derivation
  (mean → var → se → t-interp → product) without running the new code.
  CLOSED.

- Q: Is the C4 spy test mechanically valid for same-module name resolution?
  A: Yes. session_halfwidth_pp resolves t_critical_95 via sampler.__dict__
  at call time. Replacing sampler.t_critical_95 before the call intercepts it.
  CLOSED.

- Q: Does the 42-line addition to sampler.py introduce any import-time
  side effects for the virtual_analyzer subprocess?
  A: No. The addition is a pure def. Two tests guard it (dynamic import
  + AST walker). CLOSED.

- Q: Were the inject experiment restores genuine file-level operations?
  A: Consistent with current file state (no local def in pia.py, correct
  multiplier in sampler.py). No subprocess log artifact. PARTIAL.
```

---

## Process Notes

- **Verifier gap**: `04_verification.md` does not exist at critique time. The subprocess-mode check (spawning virtual_analyzer and asserting CI half-width in final JSON) is the tester's only delegated open item. If verifier does not produce this artifact, the ticket cannot move to APPROVE.
- **No error swallowing**: No new `try/except` in the diff. Clean.
- **No parallel impl**: `session_halfwidth_pp` was deduplicated to a single canonical location, not duplicated alongside the old definitions.
- **No floor lowering**: The formula was not changed, only consolidated. All numerical contracts are unchanged.
