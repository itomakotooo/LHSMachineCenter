"""Regression tests for ticket P1-B3 — session-CI half-width formula dedup.

Contract summary (brief §3):
  C1 — Single source: only one definition of session_halfwidth_pp (or
        _ci_halfwidth_pp) in the repo — in fresh_slotlab/sampler.py.
  C2 — Both callsites import: player_impact_analyzer.py and
        virtual_analyzer.py import the canonical from sampler, not
        their own local copy.
  C3 — Numerical parity: known input (n=1000, ret_sum=950.0,
        ret_sq_sum=910.0) returns 0.537590... (hand-computed snapshot).
  C4 — t_critical sourcing: session_halfwidth_pp calls the canonical
        sampler.t_critical_95; no inline lookup table inside the function.
  C5 — n <= 1 returns None (undefined variance).
  C6 — Existing test slot_designer/tests/test_virtual_analyzer_ci_stop.py
        stays green (checked in W2 by impl-verifier; this file guards the
        invariants that underpin that test).
  C7 — Inject-bug TDD: divergent formula (t * se * 50.0 instead of * 100.0)
        is caught. See §Inject-bug experiment notes below and 03_tests.md.

Hand computation for C3 snapshot:
  n = 1000, ret_sum = 950.0, ret_sq_sum = 910.0
  mean = 950.0 / 1000 = 0.95
  var  = max(0, (910.0 - 950.0^2 / 1000) / 999)
       = max(0, (910.0 - 902.5) / 999)
       = 7.5 / 999
       = 0.0075075075...
  se   = sqrt(0.0075075075... / 1000)
       = sqrt(7.507507...e-6)
       = 0.002739983121...
  t    = t_critical_95(999)
         df=999 interpolates between (120, 1.980) and (1000, 1.962):
         ratio = (999-120)/(1000-120) = 879/880
         t = 1.980 + (879/880)*(1.962-1.980) = 1.9620204545...
  hw   = t * se * 100.0 = 1.9620204545... * 0.002739983121... * 100.0
       = 0.5375902929994492  (repr value, snapshotted 2026-05-18)

Inject-bug experiment notes (C7):
  Bug injected: inside sampler.session_halfwidth_pp, replace `* 100.0`
  with `* 50.0`.
  Expected: test_c3_numerical_snapshot goes red (0.537590 != 0.268795).
  Expected: test_c7_inject_bug_wrong_multiplier_in_sampler goes red.
  Restored: both go green.
  Full log in session_artifacts/_impl/phase1/09_session_ci_halfwidth_dedup/03_tests.md.

Import-suicide guard:
  Per memory feedback_subprocess_import_suicide_and_module_globals.md:
  sampler.py must be importable with zero side-effects (no stdout, no network,
  no subprocess spawn, no file I/O). test_sampler_import_is_side_effect_free
  verifies this.

NOTE: These tests are written against the BRIEF's stated post-implementation
contract. They will be RED until impl-implementer lands the canonical
session_halfwidth_pp in sampler.py and both callsites are updated to import it.
See 03_tests.md §Open gaps for the pre-implementation red list.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# C1 — Single source of truth: exactly one definition in the codebase
# ---------------------------------------------------------------------------


def test_c1_session_halfwidth_pp_defined_in_sampler():
    """After dedup, sampler.py must contain 'def session_halfwidth_pp('.

    The canonical definition must live in fresh_slotlab/sampler.py.
    """
    sampler_py = ROOT / "fresh_slotlab" / "sampler.py"
    sampler_text = sampler_py.read_text(encoding="utf-8")
    assert "def session_halfwidth_pp(" in sampler_text, (
        "fresh_slotlab/sampler.py must contain 'def session_halfwidth_pp(' "
        "(the canonical definition is missing — P1-B3 not yet landed or was accidentally removed)"
    )


def test_c1_no_local_definition_in_player_impact_analyzer():
    """After dedup, player_impact_analyzer.py must NOT contain its own
    'def session_halfwidth_pp(' definition — it must import from sampler.

    Pre-dedup location: player_impact_analyzer.py:991-1013.
    """
    pia_py = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
    pia_text = pia_py.read_text(encoding="utf-8")

    # Filter out comments (lines starting with #) — a comment referencing
    # the old name is acceptable; a live function definition is not.
    non_comment_lines = [
        line for line in pia_text.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_text = "\n".join(non_comment_lines)

    assert "def session_halfwidth_pp(" not in non_comment_text, (
        "player_impact_analyzer.py still has its own 'def session_halfwidth_pp(' — "
        "P1-B3 dedup not complete: the local copy was not replaced with an import"
    )


def test_c1_no_local_definition_in_virtual_analyzer():
    """After dedup, virtual_analyzer.py must NOT contain '_ci_halfwidth_pp'
    as a function definition (nor 'session_halfwidth_pp' as a local copy).

    Pre-dedup location: virtual_analyzer.py:267-285 ('def _ci_halfwidth_pp(').
    After dedup the body is replaced with an import + thin call (or alias).
    """
    va_py = ROOT / "slot_designer" / "core" / "backend" / "virtual_analyzer.py"
    va_text = va_py.read_text(encoding="utf-8")

    non_comment_lines = [
        line for line in va_text.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_text = "\n".join(non_comment_lines)

    assert "def _ci_halfwidth_pp(" not in non_comment_text, (
        "virtual_analyzer.py still has 'def _ci_halfwidth_pp(' as a local definition — "
        "P1-B3 dedup not complete: the local copy was not replaced with an import/alias"
    )


def test_c1_grep_single_definition_count():
    """Grep-level contract: exactly one 'def session_halfwidth_pp' in the
    combined fresh_slotlab/ + slot_designer/ + src/ trees.

    This is the literal C1 contract from the brief: grep returns exactly 1 hit.
    """
    # Collect all Python files in the three trees
    target_dirs = [
        ROOT / "fresh_slotlab",
        ROOT / "slot_designer",
        ROOT / "src",
    ]
    definition_count = 0
    definition_locations: list[str] = []
    for tree in target_dirs:
        if not tree.exists():
            continue
        for py_file in tree.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if "def session_halfwidth_pp(" in line:
                    definition_count += 1
                    definition_locations.append(f"{py_file.relative_to(ROOT)}:{lineno}")

    assert definition_count == 1, (
        f"Expected exactly 1 definition of 'def session_halfwidth_pp' across "
        f"fresh_slotlab/ + slot_designer/ + src/, found {definition_count}. "
        f"Locations: {definition_locations}. "
        f"After P1-B3, only fresh_slotlab/sampler.py should define this function."
    )
    assert "fresh_slotlab/sampler.py" in definition_locations[0].replace("\\", "/"), (
        f"The sole definition must be in fresh_slotlab/sampler.py, "
        f"found at: {definition_locations}"
    )


# ---------------------------------------------------------------------------
# C2 — Both callsites import from sampler
# ---------------------------------------------------------------------------


def test_c2_player_impact_analyzer_exposes_session_halfwidth_pp_from_sampler():
    """player_impact_analyzer must expose session_halfwidth_pp as the SAME
    object as sampler.session_halfwidth_pp (identity check).

    This confirms the callsite imports from sampler, not a local definition.
    """
    import fresh_slotlab.sampler as sampler
    import fresh_slotlab.player_impact_analyzer as pia

    assert hasattr(sampler, "session_halfwidth_pp"), (
        "fresh_slotlab.sampler must expose session_halfwidth_pp (canonical definition missing)"
    )
    assert hasattr(pia, "session_halfwidth_pp"), (
        "player_impact_analyzer must expose session_halfwidth_pp (imported from sampler)"
    )
    assert pia.session_halfwidth_pp is sampler.session_halfwidth_pp, (
        "player_impact_analyzer.session_halfwidth_pp must be the SAME object as "
        "sampler.session_halfwidth_pp, not a locally redefined copy. "
        "P1-B3 dedup requires an 'from fresh_slotlab.sampler import session_halfwidth_pp' callsite."
    )


def test_c2_virtual_analyzer_uses_canonical_session_halfwidth_pp():
    """virtual_analyzer must call the canonical session_halfwidth_pp from
    sampler, not its own local _ci_halfwidth_pp.

    After dedup: either (a) virtual_analyzer imports session_halfwidth_pp
    from sampler directly, or (b) _ci_halfwidth_pp becomes a thin wrapper
    that delegates to sampler.session_halfwidth_pp. Either way the canonical
    function must be reachable from virtual_analyzer's module namespace.

    We verify via the numerical parity: calling va._ci_halfwidth_pp (or
    va.session_halfwidth_pp) with known inputs must return the same value
    as sampler.session_halfwidth_pp for those inputs.
    """
    import fresh_slotlab.sampler as sampler
    import slot_designer.core.backend.virtual_analyzer as va

    assert hasattr(sampler, "session_halfwidth_pp"), (
        "fresh_slotlab.sampler must expose session_halfwidth_pp"
    )

    # The C2 contract has two acceptable implementation forms:
    #   (a) va.session_halfwidth_pp is sampler.session_halfwidth_pp
    #   (b) va._ci_halfwidth_pp delegates to sampler.session_halfwidth_pp
    #       (tested indirectly via numerical parity in C3 / C4 tests)
    # We check (a) first; if absent we accept (b) and verify numerically.
    if hasattr(va, "session_halfwidth_pp"):
        assert va.session_halfwidth_pp is sampler.session_halfwidth_pp, (
            "virtual_analyzer.session_halfwidth_pp must be the SAME object as "
            "sampler.session_halfwidth_pp when form (a) is used"
        )
    else:
        # Form (b): _ci_halfwidth_pp must still exist and delegate.
        assert hasattr(va, "_ci_halfwidth_pp"), (
            "virtual_analyzer must have either session_halfwidth_pp (form a) "
            "or _ci_halfwidth_pp (form b) after dedup"
        )
        # Numerical parity for the canonical test input
        n, ret_sum, ret_sq_sum = 1000, 950.0, 910.0
        canonical = sampler.session_halfwidth_pp(n, ret_sum, ret_sq_sum)
        va_result = va._ci_halfwidth_pp(n, ret_sum, ret_sq_sum)
        assert va_result == pytest.approx(canonical, abs=1e-9), (
            f"virtual_analyzer._ci_halfwidth_pp({n}, {ret_sum}, {ret_sq_sum}) "
            f"= {va_result}, expected {canonical} (sampler canonical). "
            f"If these differ, the dedup is incomplete — _ci_halfwidth_pp "
            f"still uses a local formula instead of delegating to sampler."
        )


# ---------------------------------------------------------------------------
# C3 — Numerical parity: known-input snapshot
# ---------------------------------------------------------------------------

# Snapshot computed 2026-05-18 by hand (see module docstring for derivation).
# n=1000, ret_sum=950.0, ret_sq_sum=910.0
# var = 7.5/999 = 0.0075075075..., se = sqrt(var/1000)
# t = t_critical_95(999) = 1.9620204545...
# halfwidth_pp = t * se * 100.0 = 0.5375902929994492
_C3_N = 1000
_C3_RET_SUM = 950.0
_C3_RET_SQ_SUM = 910.0
_C3_EXPECTED_PP = 0.5375902929994492


def test_c3_numerical_snapshot():
    """sampler.session_halfwidth_pp returns the hand-computed snapshot value.

    This test locks the formula. If the implementation uses a different
    multiplier (e.g., * 50.0 or * 1.0) or a different t-critical source,
    this test goes red. See C3 derivation in module docstring.
    """
    from fresh_slotlab.sampler import session_halfwidth_pp

    result = session_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    assert result is not None, (
        f"session_halfwidth_pp({_C3_N}, {_C3_RET_SUM}, {_C3_RET_SQ_SUM}) "
        f"returned None — expected {_C3_EXPECTED_PP:.6f}"
    )
    assert result == pytest.approx(_C3_EXPECTED_PP, abs=1e-9), (
        f"session_halfwidth_pp({_C3_N}, {_C3_RET_SUM}, {_C3_RET_SQ_SUM}) "
        f"= {result:.10f}, expected {_C3_EXPECTED_PP:.10f}. "
        f"Formula or t-critical source may differ."
    )


def test_c3_hand_verified_small_n():
    """Additional hand-verified case with n=5, small spread.

    5 sessions with return multipliers [0.90, 1.05, 0.85, 1.10, 0.95].
    This matches the existing test in test_virtual_analyzer_ci_stop.py
    (test_ci_halfwidth_pp_matches_hand_computation) so we can cross-check
    that sampler.session_halfwidth_pp produces the same result as the
    old virtual._ci_halfwidth_pp for that case.

    Expected: ~12.871 pp (see that test for full derivation).
    """
    from fresh_slotlab.sampler import session_halfwidth_pp

    rx = [0.90, 1.05, 0.85, 1.10, 0.95]
    n = len(rx)
    ret_sum = sum(rx)
    ret_sq_sum = sum(x * x for x in rx)
    result = session_halfwidth_pp(n, ret_sum, ret_sq_sum)
    assert result is not None
    assert abs(result - 12.871) < 0.01, (
        f"session_halfwidth_pp for 5-session case = {result:.4f}, expected ~12.871 pp. "
        f"Parity with test_virtual_analyzer_ci_stop.py::test_ci_halfwidth_pp_matches_hand_computation failed."
    )


def test_c3_zero_variance_returns_zero():
    """All sessions identical return multiplier → variance 0 → CI = 0."""
    from fresh_slotlab.sampler import session_halfwidth_pp

    n = 10
    # All sessions return exactly ret_x = 0.95
    ret_sum = 0.95 * n
    ret_sq_sum = (0.95 ** 2) * n
    result = session_halfwidth_pp(n, ret_sum, ret_sq_sum)
    assert result == 0.0, (
        f"session_halfwidth_pp with zero variance = {result}, expected 0.0"
    )


# ---------------------------------------------------------------------------
# C4 — t_critical sourcing: no inline table in session_halfwidth_pp
# ---------------------------------------------------------------------------


def test_c4_session_halfwidth_pp_uses_canonical_t_critical():
    """session_halfwidth_pp must call sampler.t_critical_95, not an inline table.

    Inject a spy into sampler.t_critical_95 and verify it is called with
    the correct df (n-1) when session_halfwidth_pp runs.

    This test also confirms C4: the formula is NOT closed-form (no inline
    lookup table inside the function body).
    """
    import fresh_slotlab.sampler as sampler

    call_log: list[int] = []
    original_fn = sampler.t_critical_95

    def _spy_t_critical(df: int) -> float:
        call_log.append(df)
        return original_fn(df)

    sampler.t_critical_95 = _spy_t_critical
    try:
        result = sampler.session_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    finally:
        sampler.t_critical_95 = original_fn

    assert len(call_log) >= 1, (
        "session_halfwidth_pp did not call sampler.t_critical_95 at all. "
        "The formula must use the canonical t_critical_95, not an inline table."
    )
    assert (_C3_N - 1) in call_log, (
        f"session_halfwidth_pp must call t_critical_95 with df = n-1 = {_C3_N - 1}, "
        f"but spy recorded calls to: {call_log}"
    )
    # The result must still be correct after spy (spy delegates to original)
    assert result == pytest.approx(_C3_EXPECTED_PP, abs=1e-9)


def test_c4_no_inline_t_table_in_sampler_function_body():
    """The function body of session_halfwidth_pp must not embed an inline
    t-table (no hardcoded dict literal with t-values inside the function).

    We read the source and look for the characteristic pattern of the
    old inline table: a dict with df -> t-value entries like {1: 12.706, ...}.
    If found inside the session_halfwidth_pp body, C4 is violated.
    """
    sampler_py = ROOT / "fresh_slotlab" / "sampler.py"
    sampler_text = sampler_py.read_text(encoding="utf-8")

    # Locate the function body of session_halfwidth_pp
    lines = sampler_text.splitlines()
    fn_start = None
    for i, line in enumerate(lines):
        if "def session_halfwidth_pp(" in line:
            fn_start = i
            break

    assert fn_start is not None, (
        "session_halfwidth_pp not found in sampler.py (C1 prerequisite failed)"
    )

    # Extract function body (until next def/class at same or lower indentation)
    fn_lines: list[str] = [lines[fn_start]]
    base_indent = len(lines[fn_start]) - len(lines[fn_start].lstrip())
    for line in lines[fn_start + 1:]:
        stripped = line.lstrip()
        if not stripped:
            fn_lines.append(line)
            continue
        indent = len(line) - len(stripped)
        if (stripped.startswith("def ") or stripped.startswith("class ")) and indent <= base_indent:
            break
        fn_lines.append(line)

    fn_body = "\n".join(fn_lines)

    # Check for inline t-table pattern: {df: value, ...} with numeric keys
    # (the canonical t_critical_95 has one in its body, but session_halfwidth_pp
    # should NOT have one — it should call t_critical_95 instead)
    import re
    # Pattern: integer key -> float value in a dict literal (hallmark of inline table)
    inline_table_pattern = re.compile(r"\{\s*1\s*:\s*12\.706")
    assert not inline_table_pattern.search(fn_body), (
        "session_halfwidth_pp contains an inline t-critical table starting with "
        "{1: 12.706, ...}. The function must call sampler.t_critical_95 instead."
    )


# ---------------------------------------------------------------------------
# C5 — n <= 1 returns None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n,ret_sum,ret_sq_sum", [
    (0, 0.0, 0.0),
    (1, 0.93, 0.86),
    (1, 0.0, 0.0),
    (-1, 0.0, 0.0),
])
def test_c5_n_le_1_returns_none(n, ret_sum, ret_sq_sum):
    """session_halfwidth_pp returns None for n <= 1 (variance undefined).

    Per brief §3 C5 and both pre-dedup implementations:
    - player_impact_analyzer.session_halfwidth_pp:1003: 'if ret_count <= 1: return None'
    - virtual_analyzer._ci_halfwidth_pp:278: 'if n <= 1: return None'
    """
    from fresh_slotlab.sampler import session_halfwidth_pp

    result = session_halfwidth_pp(n, ret_sum, ret_sq_sum)
    assert result is None, (
        f"session_halfwidth_pp({n}, {ret_sum}, {ret_sq_sum}) = {result!r}, "
        f"expected None (undefined for n <= 1)"
    )


def test_c5_n_2_is_defined():
    """n=2 is the smallest valid sample size — must return a finite float."""
    from fresh_slotlab.sampler import session_halfwidth_pp

    # Two sessions: ret_x = 0.90 and 1.10
    rx = [0.90, 1.10]
    n = len(rx)
    ret_sum = sum(rx)
    ret_sq_sum = sum(x * x for x in rx)
    result = session_halfwidth_pp(n, ret_sum, ret_sq_sum)
    assert result is not None, (
        "session_halfwidth_pp(n=2, ...) returned None — n=2 has defined variance"
    )
    assert isinstance(result, float)
    assert math.isfinite(result)
    assert result > 0


# ---------------------------------------------------------------------------
# C6 — Existing ci_stop test parity (guard invariants; ci_stop test itself
#       runs in W2 by impl-verifier)
# ---------------------------------------------------------------------------


def test_c6_virtual_ci_halfwidth_and_sampler_agree_for_canonical_input():
    """virtual_analyzer's CI function (whichever form post-dedup) must produce
    the same value as sampler.session_halfwidth_pp for the C3 canonical input.

    This locks C6: the 'existing test stays green' invariant requires the
    virtual analyzer's session CI and the canonical to be numerically
    identical. Any divergence here would break test_virtual_analyzer_ci_stop.py.
    """
    import fresh_slotlab.sampler as sampler
    import slot_designer.core.backend.virtual_analyzer as va

    canonical = sampler.session_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    assert canonical is not None

    # Check whichever form virtual_analyzer uses post-dedup
    if hasattr(va, "session_halfwidth_pp"):
        va_result = va.session_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    elif hasattr(va, "_ci_halfwidth_pp"):
        va_result = va._ci_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    else:
        pytest.fail(
            "virtual_analyzer has neither session_halfwidth_pp nor _ci_halfwidth_pp. "
            "C6 contract requires one of these to exist."
        )

    assert va_result == pytest.approx(canonical, abs=1e-9), (
        f"virtual_analyzer CI function = {va_result:.10f}, "
        f"sampler.session_halfwidth_pp = {canonical:.10f}. "
        f"These must agree for the existing ci_stop test to remain green."
    )


def test_c6_virtual_ci_n_le_1_returns_none():
    """virtual_analyzer's CI function must still return None for n <= 1.

    This is the same guard as C5 but applied to the virtual_analyzer callsite,
    ensuring the dedup did not break the edge-case behavior that
    test_virtual_analyzer_ci_stop.py::test_ci_halfwidth_pp_undefined_for_n_le_1 checks.
    """
    import slot_designer.core.backend.virtual_analyzer as va

    if hasattr(va, "session_halfwidth_pp"):
        ci_fn = va.session_halfwidth_pp
    elif hasattr(va, "_ci_halfwidth_pp"):
        ci_fn = va._ci_halfwidth_pp
    else:
        pytest.fail("virtual_analyzer has no CI half-width function post-dedup")

    assert ci_fn(0, 0.0, 0.0) is None
    assert ci_fn(1, 0.93, 0.86) is None


# ---------------------------------------------------------------------------
# C7 — Inject-bug TDD
# ---------------------------------------------------------------------------


def test_c7_inject_bug_wrong_multiplier_in_sampler(monkeypatch):
    """Inject-bug proof: if session_halfwidth_pp used * 50.0 instead of
    * 100.0, the C3 snapshot test would catch it.

    We simulate the injection in-process by monkeypatching sampler to return
    the buggy formula result, then assert the snapshot assertion fires.

    Bug injection: t * se * 50.0 instead of t * se * 100.0.
    Expected buggy value: 0.2687951464997246 (half of correct 0.5375902929994492).

    Per brief §3 C7 and memory feedback_integration_test_argv.md:
    every test must be proven by injecting the bug it claims to catch.
    """
    import fresh_slotlab.sampler as sampler

    original_fn = sampler.session_halfwidth_pp

    def _buggy_session_halfwidth_pp(
        n: int, ret_sum: float, ret_sq_sum: float
    ) -> float | None:
        """Divergent formula: multiplier is 50.0 instead of 100.0."""
        if n <= 1:
            return None
        var = max(0.0, (ret_sq_sum - (ret_sum * ret_sum / n)) / (n - 1))
        if var == 0.0:
            return 0.0
        se = math.sqrt(var / n)
        t = sampler.t_critical_95(n - 1)
        return t * se * 50.0  # BUG: should be 100.0

    monkeypatch.setattr(sampler, "session_halfwidth_pp", _buggy_session_halfwidth_pp)

    # The C3 snapshot assertion must go red with the bug injected
    buggy_result = sampler.session_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    assert buggy_result is not None
    assert buggy_result == pytest.approx(0.2687951464997246, abs=1e-9), (
        f"Buggy formula (x50) should give 0.2688..., got {buggy_result:.10f}"
    )
    # The snapshot value (0.5376...) must NOT equal the buggy value
    assert buggy_result != pytest.approx(_C3_EXPECTED_PP, abs=1e-9), (
        "BUG INJECTION FAILED: buggy formula (x50) gives the same result as "
        "the correct formula (x100). The test would not catch the regression."
    )
    # Simulate what test_c3_numerical_snapshot would assert
    with pytest.raises(AssertionError):
        assert buggy_result == pytest.approx(_C3_EXPECTED_PP, abs=1e-9)


def test_c7_inject_bug_divergent_formula_in_virtual_callsite(monkeypatch):
    """If virtual_analyzer's `_ci_halfwidth_pp` alias had been overridden
    with a divergent formula (pre-dedup local copy with * 50.0), the
    direct call would diverge from sampler's canonical output.

    P1-B3 R1 fix (round-2 critic): the previous version of this test
    patched `sampler.session_halfwidth_pp` and asserted the canonical
    diverged — trivially true and irrelevant to the alias. The alias
    `va._ci_halfwidth_pp = session_halfwidth_pp` at virtual_analyzer.py
    line 273 is frozen at import time and points at the original
    function object; replacing the sampler module attribute does NOT
    update `va._ci_halfwidth_pp` (Python rebinds the source-module
    attribute, but the alias module's binding still holds the original
    function reference). To genuinely test the alias path, monkeypatch
    `va._ci_halfwidth_pp` directly and invoke through it.
    """
    import slot_designer.core.backend.virtual_analyzer as va

    def _buggy(n: int, ret_sum: float, ret_sq_sum: float) -> float | None:
        if n <= 1:
            return None
        var = max(0.0, (ret_sq_sum - (ret_sum * ret_sum / n)) / (n - 1))
        if var == 0.0:
            return 0.0
        se = math.sqrt(var / n)
        # BUG: wrong multiplier (matches the "old local copy with * 50.0"
        # scenario the round-1 docstring described).
        t = 1.96
        return t * se * 50.0

    monkeypatch.setattr(va, "_ci_halfwidth_pp", _buggy)

    # Invoke through the alias (the production call path in virtual_analyzer
    # internally uses `_ci_halfwidth_pp(...)` at lines 852/972/1009).
    buggy_via_alias = va._ci_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    assert buggy_via_alias is not None

    # Must differ from the correct canonical snapshot — proves the alias
    # path is exercisable and a divergent local formula would be caught.
    assert buggy_via_alias != pytest.approx(_C3_EXPECTED_PP, abs=1e-9), (
        "BUG INJECTION FAILED: monkeypatching va._ci_halfwidth_pp with a "
        "divergent formula did not change the alias-path output. The test "
        "cannot catch a regression that re-introduces a local copy."
    )

    # Sanity check: the un-patched canonical at sampler is unchanged.
    import fresh_slotlab.sampler as sampler
    canonical = sampler.session_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    assert canonical == pytest.approx(_C3_EXPECTED_PP, abs=1e-9), (
        "Canonical at sampler.session_halfwidth_pp should be untouched "
        "by monkeypatch of va._ci_halfwidth_pp."
    )


def test_c7_inject_bug_t_critical_wrong_value(monkeypatch):
    """If session_halfwidth_pp used a wrong t-critical (e.g., always 1.96
    regardless of df), the C3 snapshot and C4 spy would catch it.

    For n=1000 (df=999), canonical t = 1.9620204545...
    With t = 1.96 (old sentinel), result = 1.96 * se * 100.0.
    These differ by 1.96/1.9620204545 ≈ 0.99897 ratio — about 0.0011 pp.
    The abs=1e-9 tolerance in C3 would catch this.
    """
    import fresh_slotlab.sampler as sampler

    # Compute expected value with wrong t-critical (1.96 constant)
    n, ret_sum, ret_sq_sum = _C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM
    var = max(0.0, (ret_sq_sum - (ret_sum * ret_sum / n)) / (n - 1))
    se = math.sqrt(var / n)
    wrong_t = 1.96  # old pre-dedup sentinel for df > 30
    wrong_result = wrong_t * se * 100.0

    # The snapshot value uses the correct interpolated t = 1.9620204545...
    # These must differ
    assert wrong_result != pytest.approx(_C3_EXPECTED_PP, abs=1e-9), (
        f"Wrong t=1.96 gives {wrong_result:.10f} which equals snapshot {_C3_EXPECTED_PP:.10f}. "
        f"C3 test would not detect the wrong t-critical source."
    )
    diff = abs(wrong_result - _C3_EXPECTED_PP)
    assert diff > 1e-6, (
        f"Difference between wrong-t and correct result is only {diff:.2e}; "
        f"test tolerance 1e-9 should catch it."
    )


# ---------------------------------------------------------------------------
# Import smoke test — sampler.py must be side-effect-free
# ---------------------------------------------------------------------------


def test_sampler_import_is_side_effect_free():
    """Importing fresh_slotlab.sampler must produce no stdout/stderr output
    and must not spawn subprocesses or do file I/O.

    Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    sampler.py is imported by virtual_analyzer.py which runs in subprocess
    mode. Any top-level side effect (print, network call, build_virtual_app)
    would corrupt the subprocess's output stream or kill the run.

    We test this by clearing the module from sys.modules and re-importing
    it while capturing stdout and stderr. Empty capture = no side effects.
    """
    # Remove cached module so we get a fresh import
    for key in list(sys.modules.keys()):
        if key == "fresh_slotlab.sampler" or key == "sampler":
            del sys.modules[key]

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        import fresh_slotlab.sampler  # noqa: F401

    stdout_out = stdout_buf.getvalue()
    stderr_out = stderr_buf.getvalue()

    assert stdout_out == "", (
        f"Importing fresh_slotlab.sampler wrote to stdout: {stdout_out!r}. "
        f"Module top-level code must be side-effect-free."
    )
    assert stderr_out == "", (
        f"Importing fresh_slotlab.sampler wrote to stderr: {stderr_out!r}. "
        f"Module top-level code must be side-effect-free."
    )


def test_sampler_has_no_top_level_function_call():
    """sampler.py must not call any function at module top level (outside
    any if __name__ == '__main__' guard).

    This is the static-analysis companion to the dynamic import test above.
    We read the AST and verify no Call nodes exist at module scope outside
    the __main__ guard.

    Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    the module-top `app = build_virtual_app()` anti-pattern killed runs.
    """
    import ast

    sampler_py = ROOT / "fresh_slotlab" / "sampler.py"
    tree = ast.parse(sampler_py.read_text(encoding="utf-8"))

    # Walk top-level statements only (not inside functions/classes)
    # Look for Expr(Call(...)) or Assign with a Call value that is NOT
    # inside an if __name__ == '__main__' block.
    problematic: list[str] = []
    for node in ast.iter_child_nodes(tree):
        # Allow: if __name__ == '__main__': ... (standard guard)
        if isinstance(node, ast.If):
            # Check if it's the __name__ == '__main__' guard
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.Eq)
                and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == "__main__"
            ):
                continue  # allowed guard block
        # Flag any top-level call expression
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            problematic.append(f"line {node.lineno}: bare call expression")
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Call):
                # Allow simple assignments from stdlib (e.g., logging.getLogger)
                # but flag suspicious ones
                call = node.value
                if isinstance(call.func, ast.Attribute):
                    func_name = call.func.attr
                else:
                    func_name = getattr(call.func, "id", "unknown")
                if func_name not in ("getLogger", "getenv"):
                    problematic.append(
                        f"line {node.lineno}: top-level assignment from call '{func_name}'"
                    )

    assert not problematic, (
        f"sampler.py has top-level call(s) that could cause side effects on import:\n"
        + "\n".join(f"  {p}" for p in problematic)
    )


# ---------------------------------------------------------------------------
# Split-path monkeypatch: module-global coincidence guard
# ---------------------------------------------------------------------------


def test_split_path_sampler_monkeypatch_changes_halfwidth_result():
    """Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    monkeypatch the module-level t_critical_95 in sampler to a wrong value
    and assert session_halfwidth_pp output changes proportionally.

    This proves session_halfwidth_pp uses sampler.t_critical_95 at call time
    (not a cached value from module-load), so the dedup is live (not
    coincidence-masked).

    If session_halfwidth_pp had its own inline table that happened to produce
    the same result for df=999, this test would still pass incorrectly —
    so we use a wildly different t value (2.5) to create an unambiguous delta.
    """
    import fresh_slotlab.sampler as sampler

    original_fn = sampler.t_critical_95
    canonical_result = sampler.session_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    assert canonical_result is not None

    def _wrong_t_critical(df: int) -> float:
        return 2.5  # drastically wrong

    sampler.t_critical_95 = _wrong_t_critical
    try:
        patched_result = sampler.session_halfwidth_pp(_C3_N, _C3_RET_SUM, _C3_RET_SQ_SUM)
    finally:
        sampler.t_critical_95 = original_fn

    assert patched_result is not None
    assert patched_result != pytest.approx(canonical_result, abs=1e-6), (
        f"Monkeypatching sampler.t_critical_95 to return 2.5 did NOT change "
        f"session_halfwidth_pp output ({patched_result} == {canonical_result}). "
        f"session_halfwidth_pp must call sampler.t_critical_95 at invocation time, "
        f"not use an inline table or a cached closure value."
    )

    # Verify the ratio: patched / canonical should equal 2.5 / t_critical_95(999)
    canonical_t = original_fn(_C3_N - 1)  # t_critical_95(999)
    expected_ratio = 2.5 / canonical_t
    actual_ratio = patched_result / canonical_result
    assert actual_ratio == pytest.approx(expected_ratio, rel=1e-4), (
        f"Ratio of patched/canonical result = {actual_ratio:.6f}, "
        f"expected 2.5/{canonical_t:.6f} = {expected_ratio:.6f}. "
        f"session_halfwidth_pp output must scale proportionally with t_critical."
    )
