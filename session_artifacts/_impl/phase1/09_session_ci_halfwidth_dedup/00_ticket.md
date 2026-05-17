# Ticket P1-B3 — Consolidate session-CI half-width formula (real × 2) (Batch 1c)

> Phase 1 / Batch 1c. Pure formula dedup. Cleanly extends P1-B4 (both target `fresh_slotlab/sampler.py` as canonical home).

---

## §1 Ticket scope

Two implementations of session-level CI half-width formula:
- [fresh_slotlab/player_impact_analyzer.py:1012-1034](fresh_slotlab/player_impact_analyzer.py:1012) — `session_halfwidth_pp(ret_count, ret_sum, ret_sq_sum)`
- [slot_designer/core/backend/virtual_analyzer.py:278-291](slot_designer/core/backend/virtual_analyzer.py:278) — `_ci_halfwidth_pp(n, ret_sum, ret_sq_sum)`

Same formula, different names. virtual's comment at lines 280-283 says "Matches the formula used by the real analyzer" — the formulas DO match (unlike t-critical, where they didn't), but the duplication still creates drift risk.

Files expected to change:
- `fresh_slotlab/sampler.py` — add canonical `session_halfwidth_pp(n, ret_sum, ret_sq_sum)` (or extend existing namespace)
- `fresh_slotlab/player_impact_analyzer.py:1012-1034` — drop local, import canonical
- `slot_designer/core/backend/virtual_analyzer.py:278-291` — drop local, import canonical
- `tests/backend/test_session_halfwidth_canonical.py` (new) — regression per §3

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §4` row 3 ("session CI half-width")
- `session_artifacts/_arch/03_coupling_audit.md §4.5` — duplicate primitives
- `session_artifacts/_arch/08_handoff.md §4 Phase 1` — session-CI × 2
- Memory `feedback_invariant_with_fallback_hides_drift.md` — "matches the real analyzer" comments without enforcement = silent drift waiting to happen

---

## §3 Contract (testable invariants)

### C1 — Single source of truth
`grep -rn "def session_halfwidth_pp\b\|def _ci_halfwidth_pp\b" fresh_slotlab/ slot_designer/ src/` returns exactly one definition (in `fresh_slotlab/sampler.py`).

### C2 — Both callsites import
`player_impact_analyzer.py:1012-1034` body becomes import + thin call. `virtual_analyzer.py:278-291` similarly.

### C3 — Numerical parity
For a known input (e.g., `n=1000, ret_sum=950.0, ret_sq_sum=910.0`), the canonical returns the expected value (compute by hand to ~6 decimals). Regression test snapshots this value.

### C4 — t_critical sourcing
Per P1-B4 (already complete): `t_critical_95` lives in `sampler.py`. This ticket's `session_halfwidth_pp` calls the canonical `t_critical_95` — verifies the formula uses ONE consistent t-critical (no redundant inline table).

### C5 — `n<=1` returns None
Per the existing virtual impl + analyzer impl docstrings: when `n<=1`, return `None` (undefined variance). Test asserts.

### C6 — Existing test stays green
`slot_designer/tests/test_virtual_analyzer_ci_stop.py` (which exercises `_ci_halfwidth_pp` via virtual sampling) must continue passing. The dedup is a callsite rerouting, not a formula change.

### C7 — Inject-bug TDD
Tester: revert the dedup, inject a divergent formula (e.g., `t * se * 50.0` instead of `* 100.0`) into one of the two old locations → assert regression test catches the divergence. Document.

---

## §4 Out of scope

- Replacing the formula with a library call (scipy.stats etc.) — out of scope per virtual_analyzer.py:259-261 ("Keeps small-session CIs honest without dragging scipy in")
- Touching `compute_ci_halfwidth_pp` in sampler (chunk-level CI, different formula, different inputs)
- Renaming `session_halfwidth_pp` → anything else (cosmetic; not in scope)

---

## §5 Rollback path

Single commit. `git revert <sha>` restores both local implementations.

---

## §6 Risk + rollback notes

**Risk class**: LOW.

**Dependency**: P1-B4 should be landed first (t_critical_95 canonical location must be in sampler.py before this ticket; otherwise session_halfwidth_pp would have to inline its own t_critical).

**Subprocess mode**: virtual_analyzer runs in subprocess. impl-verifier spawns subprocess + asserts CI half-width returns same value as canonical call.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — moves canonical to sampler, updates 2 callsites
- `impl-tester` — writes regression + inject-bug + existing-test-stays-green proof

### Wave 2 (parallel)
- `impl-verifier` — runs full pytest including `slot_designer/tests/test_virtual_analyzer_ci_stop.py`; spawns virtual analyzer subprocess
- `impl-critic` — checks: does the canonical correctly handle the `n<=1 → None` edge case? Did tester verify the existing CI-stop test path?

Expected wall time: ~25-40 min.
