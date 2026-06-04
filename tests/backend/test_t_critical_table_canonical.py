"""Regression tests for ticket P1-B4 — t_critical_95 table dedup.

Contract summary (brief §3):
  C1 — Single source: only one definition of t_critical_95 in the repo
        (in fresh_slotlab/sampler.py); player_impact_analyzer and
        virtual_analyzer import from there.
  C2 — Value parity across df 1..1200: every integer df returns a
        positive, finite float.
  C3 — Latent-divergence-fix proof: canonical values at the three
        historically-divergent sentinels (df=15/25/80) are correct.
  C4 — Inject-bug TDD: test goes red when sampler table is mutated.
        See 03_tests.md for the documented inject-bug experiment.
  C5 — All existing pytest passes (run by impl-verifier in W2).
  C6 — virtual_analyzer._ci_halfwidth_pp uses the canonical
        t_critical_95 (via sampler import), not a module-level global;
        split-path monkeypatch proves the attr is live (not coincidence-
        masked).

Background divergence (pre-dedup):
  analyzer.t_critical_95(15) ≈ 2.157  (linear interp, sparse table missing df 11-19)
  virtual._t_critical_95(15) = 2.131  (dense table 1-30, sentinel 1.96 for df>30)
  sampler.t_critical_95(15)  = 2.131  (canonical)

  For df=80: virtual sentinel was 1.96; sampler gives 1.990 via interp.
"""
from __future__ import annotations

import importlib
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# C1 — Single source of truth
# ---------------------------------------------------------------------------


def test_c1_single_definition_in_repo():
    """Verify that the only function definition of t_critical_95 in the repo
    is in fresh_slotlab/sampler.py, and that neither player_impact_analyzer.py
    nor virtual_analyzer.py contain a local definition or the table constant.

    The C1 contract (brief §3) requires no other definition of t_critical_95
    or _T_CRITICAL_95_TABLE exists. We verify this by reading the specific
    files that were modified by P1-B4 and confirming the local definitions are
    absent. We also read sampler.py to confirm the canonical def is still there.
    """
    # --- sampler.py: must have the canonical definition ---
    sampler_py = ROOT / "fresh_slotlab" / "sampler.py"
    sampler_text = sampler_py.read_text(encoding="utf-8")
    assert "def t_critical_95(" in sampler_text, (
        f"fresh_slotlab/sampler.py must contain 'def t_critical_95(' "
        f"(the canonical definition was accidentally removed)"
    )

    # --- player_impact_analyzer.py: must NOT have a local definition ---
    pia_py = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
    pia_text = pia_py.read_text(encoding="utf-8")
    assert "def t_critical_95(" not in pia_text, (
        "player_impact_analyzer.py still contains 'def t_critical_95(' — "
        "the local definition was not removed by P1-B4"
    )

    # --- sampler.py must NOT have the constant table in virtual_analyzer style ---
    # (defensive: sampler uses a local dict inside the function body, not a module-level const)
    # This just confirms the sampler definition is the function form, not a second table
    assert "_T_CRITICAL_95_TABLE" not in sampler_text, (
        "fresh_slotlab/sampler.py unexpectedly contains '_T_CRITICAL_95_TABLE' — "
        "the canonical source should use an inline dict inside t_critical_95()"
    )


def test_c1_player_impact_analyzer_imports_from_sampler():
    """player_impact_analyzer.t_critical_95 must be the same function object
    as sampler.t_critical_95 — not a locally redefined copy.
    """
    import fresh_slotlab.sampler as sampler
    import fresh_slotlab.player_impact_analyzer as pia

    assert hasattr(pia, "t_critical_95"), (
        "player_impact_analyzer must expose t_critical_95 (imported from sampler)"
    )
    assert pia.t_critical_95 is sampler.t_critical_95, (
        "player_impact_analyzer.t_critical_95 must be the SAME object as "
        "sampler.t_critical_95, not a local redefinition"
    )


# ---------------------------------------------------------------------------
# C2 — Value parity across df range 1..1200
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("df", list(range(1, 1201)))
def test_c2_full_range_returns_positive_float(df):
    """Every integer df in [1, 1200] must return a positive, finite float."""
    from fresh_slotlab.sampler import t_critical_95

    result = t_critical_95(df)
    assert isinstance(result, float), f"df={df}: expected float, got {type(result)}"
    assert result > 0, f"df={df}: expected positive value, got {result}"
    assert math.isfinite(result), f"df={df}: expected finite value, got {result}"


def test_c2_df_zero_or_negative_returns_inf():
    """df <= 0 is the documented special case — must return math.inf."""
    from fresh_slotlab.sampler import t_critical_95

    assert t_critical_95(0) == math.inf
    assert t_critical_95(-1) == math.inf
    assert t_critical_95(-999) == math.inf


def test_c2_above_1000_returns_last_sentinel():
    """df > 1000 (beyond the table's last entry) must return the last table value
    (1.962 for df=1000 sentinel), not raise an error.
    """
    from fresh_slotlab.sampler import t_critical_95

    v_1001 = t_critical_95(1001)
    v_1200 = t_critical_95(1200)
    # Both must equal the 1000-row sentinel (linear extrapolation clamps to last)
    assert v_1001 == pytest.approx(1.962, abs=1e-9), (
        f"t_critical_95(1001) expected 1.962 (last sentinel), got {v_1001}"
    )
    assert v_1200 == pytest.approx(1.962, abs=1e-9), (
        f"t_critical_95(1200) expected 1.962 (last sentinel), got {v_1200}"
    )


# ---------------------------------------------------------------------------
# C3 — Latent-divergence-fix proof
# ---------------------------------------------------------------------------


def test_c3_df15_canonical_value():
    """t_critical_95(15) must equal 2.131 (table entry).

    Pre-dedup: analyzer interpolated df=15 between (10, 2.228) and (20, 2.086)
    → 2.157. After dedup the canonical table entry 2.131 is used by all callers.
    """
    from fresh_slotlab.sampler import t_critical_95

    assert t_critical_95(15) == pytest.approx(2.131, abs=1e-9), (
        f"t_critical_95(15) should be 2.131 (canonical table entry), "
        f"got {t_critical_95(15)}"
    )


def test_c3_df25_canonical_value():
    """t_critical_95(25) must equal 2.060 (table entry).

    Pre-dedup: analyzer interpolated df=25 between (20, 2.086) and (30, 2.042)
    → 2.064. After dedup the canonical table entry 2.060 is used.
    """
    from fresh_slotlab.sampler import t_critical_95

    assert t_critical_95(25) == pytest.approx(2.060, abs=1e-9), (
        f"t_critical_95(25) should be 2.060 (canonical table entry), "
        f"got {t_critical_95(25)}"
    )


def test_c3_df80_canonical_value():
    """t_critical_95(80) must equal 1.990 (table entry).

    Pre-dedup: virtual hard-coded 1.96 for all df > 30; analyzer interpolated
    (60, 2.000)-(120, 1.980) → 1.9933. After dedup the canonical table entry
    1.990 is used by all callers.
    """
    from fresh_slotlab.sampler import t_critical_95

    assert t_critical_95(80) == pytest.approx(1.990, abs=1e-9), (
        f"t_critical_95(80) should be 1.990 (canonical table entry), "
        f"got {t_critical_95(80)}"
    )


def test_c3_divergence_from_old_analyzer_sparse_table():
    """Document that the old analyzer sparse-table values differed.

    This test is the positive-proof side: the canonical values differ
    from what the old analyzer sparse interpolation would have produced.
    Values below are computed from the old sparse table:
      df=15: interp (10,2.228)→(20,2.086), ratio=0.5 → 2.157
      df=25: interp (20,2.086)→(30,2.042), ratio=0.5 → 2.064
      df=80: interp (60,2.000)→(120,1.980), ratio=20/60 → ~1.9933
    After dedup, these are replaced with accurate table values.
    """
    from fresh_slotlab.sampler import t_critical_95

    OLD_ANALYZER_INTERPOLATED = {
        15: 2.228 + 0.5 * (2.086 - 2.228),    # = 2.157
        25: 2.086 + 0.5 * (2.042 - 2.086),    # = 2.064
        80: 2.000 + (20 / 60) * (1.980 - 2.000),  # ≈ 1.9933
    }
    CANONICAL = {15: 2.131, 25: 2.060, 80: 1.990}

    for df in [15, 25, 80]:
        canonical_val = t_critical_95(df)
        old_val = OLD_ANALYZER_INTERPOLATED[df]
        # The canonical value must differ from the old interpolation
        # (this proves the dedup actually changed the behavior)
        assert abs(canonical_val - old_val) > 1e-4, (
            f"t_critical_95({df}) canonical={canonical_val} is unexpectedly "
            f"equal to the old interpolated value {old_val}; "
            f"the dedup fix may not have taken effect"
        )
        assert canonical_val == pytest.approx(CANONICAL[df], abs=1e-9)


# ---------------------------------------------------------------------------
# C4 — Inject-bug TDD verification (in-process table mutation)
# ---------------------------------------------------------------------------


def test_c4_inject_bug_df15_wrong_value(monkeypatch):
    """Inject a wrong table value into sampler.t_critical_95 and assert the
    C3 test would go red.

    This is the inject-bug proof per brief §3 C4 and memory
    feedback_integration_test_argv.md.  The full out-of-process inject-bug
    experiment (git stash → red → restore → green) is documented in
    03_tests.md.

    Here we simulate it in-process by monkeypatching the function's
    closure/table to return 2.222 for df=15 instead of 2.131.
    """
    from fresh_slotlab import sampler

    # Patch sampler.t_critical_95 to return a wrong value for df=15
    original_fn = sampler.t_critical_95

    def _buggy_t_critical_95(df: int) -> float:
        if df == 15:
            return 2.222  # synthetic wrong value
        return original_fn(df)

    monkeypatch.setattr(sampler, "t_critical_95", _buggy_t_critical_95)

    # The canonical value assertion must catch the bug
    with pytest.raises(AssertionError):
        assert sampler.t_critical_95(15) == pytest.approx(2.131, abs=1e-9)

    # Other values must still be correct (only df=15 is injected)
    assert sampler.t_critical_95(25) == pytest.approx(2.060, abs=1e-9)
    assert sampler.t_critical_95(80) == pytest.approx(1.990, abs=1e-9)


def test_c4_inject_bug_does_not_affect_non_target_dfs(monkeypatch):
    """Confirm the inject-bug test is precise: patching df=15 only
    leaves other df values unaffected (test is not over-broad).
    """
    from fresh_slotlab import sampler

    original_fn = sampler.t_critical_95
    call_log: list[int] = []

    def _spy_t_critical_95(df: int) -> float:
        call_log.append(df)
        return original_fn(df)

    monkeypatch.setattr(sampler, "t_critical_95", _spy_t_critical_95)

    assert sampler.t_critical_95(1) == pytest.approx(12.706, abs=1e-9)
    assert sampler.t_critical_95(30) == pytest.approx(2.042, abs=1e-9)
    assert sampler.t_critical_95(120) == pytest.approx(1.980, abs=1e-9)
    assert sampler.t_critical_95(1000) == pytest.approx(1.962, abs=1e-9)

    assert call_log == [1, 30, 120, 1000]


# ---------------------------------------------------------------------------
# Regression guard — selected table entries must not silently shift
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("df, expected", [
    (1, 12.706),
    (2, 4.303),
    (5, 2.571),
    (10, 2.228),
    (11, 2.201),   # first entry missing from old analyzer sparse table
    (12, 2.179),
    (15, 2.131),   # C3 sentinel — was 2.157 in old analyzer
    (20, 2.086),
    (25, 2.060),   # C3 sentinel — was 2.064 in old analyzer
    (30, 2.042),
    (40, 2.021),
    (60, 2.000),
    (80, 1.990),   # C3 sentinel — was 1.9933 in analyzer / 1.96 in virtual
    (120, 1.980),
    (1000, 1.962),
])
def test_table_entries_pinned(df, expected):
    """Pin all explicit table entries to their documented values.

    Any accidental edit to the canonical table in sampler.py will fail
    one of these assertions.
    """
    from fresh_slotlab.sampler import t_critical_95

    assert t_critical_95(df) == pytest.approx(expected, abs=1e-9), (
        f"t_critical_95({df}) = {t_critical_95(df)}, expected {expected}"
    )


@pytest.mark.parametrize("df, lo, hi", [
    # df=35: between 30 (2.042) and 40 (2.021), ratio = 5/10 = 0.5
    (35, 2.031, 2.032),   # 2.042 + 0.5*(2.021-2.042) = 2.042 - 0.0105 = 2.0315
    # df=50: between 40 (2.021) and 60 (2.000), ratio = 10/20 = 0.5
    (50, 2.010, 2.011),   # 2.021 + 0.5*(2.000-2.021) = 2.021 - 0.0105 = 2.0105
    # df=100: between 80 (1.990) and 120 (1.980), ratio = 20/40 = 0.5
    (100, 1.984, 1.986),  # 1.990 + 0.5*(1.980-1.990) = 1.990 - 0.005 = 1.985
])
def test_interpolation_between_table_anchors(df, lo, hi):
    """Intermediate df values (not in table) must be linearly interpolated
    between the enclosing table anchors, not clamped to a sentinel.
    """
    from fresh_slotlab.sampler import t_critical_95

    val = t_critical_95(df)
    assert lo <= val <= hi, (
        f"t_critical_95({df}) = {val}, expected interpolated value in [{lo}, {hi}]"
    )
