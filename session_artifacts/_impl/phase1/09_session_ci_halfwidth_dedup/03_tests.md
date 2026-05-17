# 03_tests.md — Ticket P1-B3 (phase1/09_session_ci_halfwidth_dedup)

## Verdict

**sufficient**

All 7 brief contracts (C1-C7) are covered by executable tests. Both inject-bug experiments were performed and verified (red → restore → green). The existing `slot_designer/tests/test_virtual_analyzer_ci_stop.py` (11 tests) remains fully green.

---

## Test files added

| File | Tests |
|------|-------|
| `tests/backend/test_session_halfwidth_canonical.py` | 24 |

**Total new tests: 24**

---

## Inject-bug verification log

### Experiment 1 — Wrong multiplier in sampler.session_halfwidth_pp

**Bug injected**: In `fresh_slotlab/sampler.py`, line 255, changed `return t * se * 100.0` to `return t * se * 50.0`.

**Tests that went red**:
- `test_c3_numerical_snapshot` — FAIL: `0.2687951465 != 0.5375902930 ± 1e-9`
- `test_c3_hand_verified_small_n` — FAIL: `6.4359 ≠ expected ~12.871 pp`
- `test_c4_session_halfwidth_pp_uses_canonical_t_critical` — FAIL: spy-returned value `0.2688` doesn't match snapshot

**Tests that stayed green** (correct — they use monkeypatching, not the live function):
- `test_c6_virtual_ci_halfwidth_and_sampler_agree_for_canonical_input` — PASS (because both sampler and va call the same buggy function; the test checks they AGREE, not that they match a constant)
- `test_split_path_sampler_monkeypatch_changes_halfwidth_result` — PASS (test itself patches with a fresh wrong value and verifies the delta)
- All C7 in-process inject-bug tests — PASS (they use monkeypatch, independent of live source)

**Restored**: `return t * se * 100.0`

**Result after restore**: 24/24 PASS

---

### Experiment 2 — Local copy re-injected into player_impact_analyzer.py

**Bug injected**: Added a full local `def session_halfwidth_pp(ret_count, ...)` body back into `fresh_slotlab/player_impact_analyzer.py` at line 1004 (pre-dedup state).

**Tests that went red**:
- `test_c1_no_local_definition_in_player_impact_analyzer` — FAIL: `"def session_halfwidth_pp(" found in non-comment text`
- `test_c1_grep_single_definition_count` — FAIL: `found 2 definitions, expected 1` (locations: player_impact_analyzer.py:1004, sampler.py:219)
- `test_c2_player_impact_analyzer_exposes_session_halfwidth_pp_from_sampler` — FAIL: `pia.session_halfwidth_pp is not sampler.session_halfwidth_pp` (different function objects at different memory addresses)

**Restored**: Local definition removed.

**Result after restore**: 24/24 PASS

---

## Coverage map: brief contracts → tests

| Contract | Description | Tests |
|----------|-------------|-------|
| C1 | Single source of truth — exactly 1 `def session_halfwidth_pp` in repo | `test_c1_session_halfwidth_pp_defined_in_sampler`, `test_c1_no_local_definition_in_player_impact_analyzer`, `test_c1_no_local_definition_in_virtual_analyzer`, `test_c1_grep_single_definition_count` |
| C2 | Both callsites import (pia + va) | `test_c2_player_impact_analyzer_exposes_session_halfwidth_pp_from_sampler`, `test_c2_virtual_analyzer_uses_canonical_session_halfwidth_pp` |
| C3 | Numerical parity: known input snapshot (n=1000, ret_sum=950, ret_sq_sum=910) | `test_c3_numerical_snapshot`, `test_c3_hand_verified_small_n`, `test_c3_zero_variance_returns_zero` |
| C4 | t_critical sourcing: calls canonical `sampler.t_critical_95`, no inline table | `test_c4_session_halfwidth_pp_uses_canonical_t_critical`, `test_c4_no_inline_t_table_in_sampler_function_body` |
| C5 | `n<=1` returns None | `test_c5_n_le_1_returns_none[0-0.0-0.0]`, `test_c5_n_le_1_returns_none[1-0.93-0.86]`, `test_c5_n_le_1_returns_none[1-0.0-0.0]`, `test_c5_n_le_1_returns_none[-1-0.0-0.0]`, `test_c5_n_2_is_defined` |
| C6 | Existing `test_virtual_analyzer_ci_stop.py` stays green | `test_c6_virtual_ci_halfwidth_and_sampler_agree_for_canonical_input`, `test_c6_virtual_ci_n_le_1_returns_none` (+ impl-verifier runs full ci_stop suite in W2) |
| C7 | Inject-bug TDD: divergent formula caught | `test_c7_inject_bug_wrong_multiplier_in_sampler`, `test_c7_inject_bug_divergent_formula_in_virtual_callsite`, `test_c7_inject_bug_t_critical_wrong_value` |

Additional guards (not in brief, per memory requirements):
| Guard | Tests |
|-------|-------|
| Import side-effect free (per `feedback_subprocess_import_suicide_and_module_globals.md`) | `test_sampler_import_is_side_effect_free`, `test_sampler_has_no_top_level_function_call` |
| Split-path monkeypatch proves attr is live (per `feedback_subprocess_import_suicide_and_module_globals.md`) | `test_split_path_sampler_monkeypatch_changes_halfwidth_result` |

---

## Open gaps

**C6 subprocess test**: The brief's C6 requires `slot_designer/tests/test_virtual_analyzer_ci_stop.py` to pass. That test file runs in-process and covers 11 cases. impl-verifier (W2) is responsible for spawning a real virtual_analyzer subprocess and asserting CI half-width returns the same value as `sampler.session_halfwidth_pp`. That subprocess-mode check is not duplicated here per single-responsibility constraint.

**C3 exact snapshot dependence on t_critical_95 interpolation**: The C3 snapshot value (0.5375902929994492) is computed using the canonical `t_critical_95(999)` = 1.9620204545454545 (linear interpolation between df=120 → 1.980 and df=1000 → 1.962). If the t-table in sampler.py ever changes, the snapshot will need to be recomputed. This is intentional — the snapshot locks both the formula AND the t-table in one assertion.

---

## Subprocess vs in-process coverage

All 24 new tests are **in-process**. The session_halfwidth_pp function is a pure math function (no I/O, no subprocesses) so in-process testing fully covers the formula contract.

The subprocess-mode concern (per `feedback_perf_claim_needs_e2e_event_stream.md`) is:
- The function is called from virtual_analyzer.py which runs as a subprocess.
- In-process tests verify the function is importable without side effects (`test_sampler_import_is_side_effect_free`) and the function object is shared across modules (identity tests in C2).
- The actual subprocess invocation end-to-end path (virtual_analyzer spawning, delegating to real analyzer, CI half-width appearing in final JSON) is impl-verifier's scope (W2), not tester's scope (W1).

---

## Hand computation for C3 snapshot (2026-05-18)

```
n = 1000, ret_sum = 950.0, ret_sq_sum = 910.0

mean = ret_sum / n = 950.0 / 1000 = 0.95

var = max(0, (ret_sq_sum - ret_sum^2 / n) / (n - 1))
    = max(0, (910.0 - 950.0^2 / 1000) / 999)
    = max(0, (910.0 - 902.5) / 999)
    = 7.5 / 999
    = 0.0075075075075075...

se = sqrt(var / n) = sqrt(0.0075075075... / 1000)
   = sqrt(7.507507...e-6)
   = 0.002739983121755955

t = t_critical_95(999)
  = linear interp between (120, 1.980) and (1000, 1.962)
  = ratio = (999 - 120) / (1000 - 120) = 879 / 880 = 0.99886...
  = 1.980 + 0.99886... * (1.962 - 1.980)
  = 1.980 + 0.99886... * (-0.018)
  = 1.980 - 0.017979...
  = 1.9620204545454545

halfwidth_pp = t * se * 100.0
             = 1.9620204545454545 * 0.002739983121755955 * 100.0
             = 0.5375902929994492  (Python repr)
```

Verified by running: `python -c "import math, sys; sys.path.insert(0, '.'); from fresh_slotlab.sampler import t_critical_95; n=1000; ret_sum=950.0; ret_sq_sum=910.0; var=max(0.0,(ret_sq_sum-(ret_sum*ret_sum/n))/(n-1)); se=math.sqrt(var/n); t=t_critical_95(n-1); print(t*se*100.0)"` → `0.5375902929994492`
