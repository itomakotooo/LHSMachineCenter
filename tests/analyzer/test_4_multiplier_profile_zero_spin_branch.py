"""Phase 4 — synthetic-input unit test for the carved branch the goldens MISS.

COVERAGE-GAP CLOSER (the 2b ``_quantiles``-index lesson / the 3
chain-confidence-ladder lesson; see
session_artifacts/_impl/phase_extract_2b_bonus_chain/inject_bug_evidence.md §A' and
session_artifacts/_impl/phase_extract_3_upstream_feature/inject_bug_evidence.md §A').

The byte-identity goldens (M275 + M14 in
test_4_byte_identical_multiplier_profile_carve.py) lock the carved dict-build
leaf-by-leaf, but BOTH sample machines have ``mb_total_spins > 0`` (verified:
M275 tail_spin_rate_ge10x=0.0106375, M14=0.0273826 — both > 0).  So the ONLY
conditional in the moved build —

    "tail_spin_rate_ge10x": (
        tail_spins_ge10 / mb_total_spins if mb_total_spins > 0 else 0.0
    ),

takes the DIVISOR arm on both machines.  The ``else 0.0`` ZERO-SPIN arm is NEVER
exercised by either golden.  A regression that broke the zero-spin default
(e.g. dropped the guard → ZeroDivisionError on an empty machine, or changed the
default from ``0.0`` to ``None``) would leave BOTH byte-identity deep-diffs GREEN.
This is the same class of gap as the 2b ``_quantiles`` index.

Branch enumeration of the moved build (deliverable #3 "hunt for any OTHER
unexercised branch")
---------------------------------------------------------------------------------
The carved dict (multiplier_profile.py emit(), the
``player_impact["multiplier_profile"] = {...}`` literal) has exactly ONE
conditional — the ``if mb_total_spins > 0 else 0.0`` above.  The other four leaves
are unconditional pass-throughs:
  - ``metric``                          : constant string literal
  - ``buckets``                         : direct assignment of multiplier_bucket_rows
  - ``tail_rtp_contribution_pp_ge10x``  : direct assignment of the raw input
  - ``tail_win_share_ge10x``            : direct assignment of the raw input
No other branch exists in the moved code, so the zero-spin arm is the sole
golden-missed branch.  (The pass-throughs are still covered byte-identically by
the goldens AND pinned here as fast-localized regression signals.)

Inject-bug recipes (per feedback_enumerate_safety_paths.md) — verified 2026-05-30
(RED->revert->GREEN; evidence in inject_bug_evidence.md §Coverage-gap):

  zero-spin default (the divisor guard):
    -  tail_spins_ge10 / mb_total_spins if mb_total_spins > 0 else 0.0
    +  tail_spins_ge10 / mb_total_spins if mb_total_spins > 0 else None  # BUG
    RED: test_zero_spin_rate_is_float_zero (None != 0.0). Goldens stay GREEN
         (both machines have mb_total_spins > 0).

  divisor-guard removal (would crash on an empty machine):
    -  tail_spins_ge10 / mb_total_spins if mb_total_spins > 0 else 0.0
    +  tail_spins_ge10 / mb_total_spins                                   # BUG
    RED: test_zero_spin_does_not_divide_by_zero (ZeroDivisionError surfaces as a
         Runtime/feature error instead of 0.0). Goldens stay GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    each branch of the moved compute needs its own inject-bug-provable test; the
    ``else 0.0`` divisor-guard arm is a safety path (prevents ZeroDivisionError on
    a zero-spin machine) and must be pinned.
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    the 2b _quantiles-index gap: the 2 sample machines' data can leave a whole
    branch uncovered; a synthetic input spanning the branch is required.
- memory/feedback_invariant_with_fallback_hides_drift.md
    a None-vs-0.0 flip in the zero-spin default is exactly the silent-attribution
    drift the structural goldens miss but a typed assertion catches.
"""
from __future__ import annotations

from typing import Any

import pytest


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.multiplier_profile import MultiplierProfile
    except ImportError:  # running as standalone script
        from analyzer.features.multiplier_profile import (  # type: ignore[no-redef]
            MultiplierProfile,
        )
    return MultiplierProfile


def _base_stash(**over: Any) -> dict[str, Any]:
    """Minimal valid 5-key stash. Override raw inputs to enter a target branch."""
    s: dict[str, Any] = {
        "multiplier_bucket_rows": [
            {
                "bucket": "gt0_lt1",
                "spin_count": 100,
                "spin_rate": 0.1,
                "rtp_contribution_pp": 5.0,
                "win_share": 0.05,
                "avg_return_x_in_bucket": 0.5,
            }
        ],
        "tail_spins_ge10": 10,
        "mb_total_spins": 1000,
        "tail_rtp_contribution_pp_ge10x": 23.4,
        "tail_win_share_ge10x": 0.26,
    }
    s.update(over)
    return s


def _emit(stash: dict[str, Any]) -> dict:
    plugin = _import_plugin_class()()
    summary = {"_multiplier_profile_data": stash}
    plugin.emit({}, summary, None)
    return summary["player_impact"]["multiplier_profile"]


# ---------------------------------------------------------------------------
# 1. The zero-spin `else 0.0` arm (the golden-missed branch)
# ---------------------------------------------------------------------------

class TestZeroSpinTailRate:
    """tail_spin_rate_ge10x must be the float 0.0 when mb_total_spins == 0.

    BOTH goldens have mb_total_spins > 0, so this arm is uncovered by the
    byte-identity tests — a regression here is invisible to them.
    """

    def test_zero_spin_rate_is_float_zero(self):
        """mb_total_spins == 0 -> tail_spin_rate_ge10x is exactly the float 0.0.

        Pins the None-vs-0.0 form (the byte-identity contract preserves 0.0, not
        None / not int 0). A regression flipping the default to None would slip
        past the goldens (whose machines never hit this arm).
        """
        mp = _emit(_base_stash(mb_total_spins=0, tail_spins_ge10=0))
        v = mp["tail_spin_rate_ge10x"]
        assert v == 0.0, f"zero-spin tail rate must be 0.0, got {v!r}"
        assert isinstance(v, float), (
            f"zero-spin tail rate must be a float (not int / not None), got "
            f"{type(v).__name__}: {v!r}"
        )

    def test_zero_spin_does_not_divide_by_zero(self):
        """mb_total_spins == 0 with tail_spins_ge10 > 0 -> 0.0, NOT ZeroDivisionError.

        The ``if mb_total_spins > 0`` guard is a safety path: a zero-spin machine
        with a (degenerate) non-zero tail count must NOT crash the dict-build. A
        regression removing the guard would raise ZeroDivisionError (surfacing as a
        feature error / wrong report) — the goldens cannot catch it because both
        their machines have mb_total_spins > 0.
        """
        # No exception must escape; the guard yields 0.0.
        mp = _emit(_base_stash(mb_total_spins=0, tail_spins_ge10=50))
        assert mp["tail_spin_rate_ge10x"] == 0.0, (
            f"the >0 guard must short-circuit to 0.0 even when tail_spins_ge10>0; "
            f"got {mp['tail_spin_rate_ge10x']!r}"
        )

    def test_divisor_arm_computes_ratio(self):
        """mb_total_spins > 0 -> tail_spin_rate_ge10x = tail_spins_ge10 / mb_total_spins.

        The positive arm (the one the goldens exercise) — pinned here too so the
        two arms are covered side-by-side and a swapped operand is caught locally.
        """
        mp = _emit(_base_stash(mb_total_spins=1000, tail_spins_ge10=10))
        assert mp["tail_spin_rate_ge10x"] == 10 / 1000, mp["tail_spin_rate_ge10x"]


# ---------------------------------------------------------------------------
# 2. The unconditional pass-through leaves (verbatim-move regression signals)
# ---------------------------------------------------------------------------

class TestVerbatimPassThroughLeaves:
    """The non-conditional leaves must pass the raw inputs through verbatim.

    These are also covered by the goldens, but a localized unit catches a
    swapped-source regression (e.g. assigning tail_win_share to
    tail_rtp_contribution_pp) instantly, without a full subprocess run.
    """

    def test_metric_is_the_canonical_constant(self):
        mp = _emit(_base_stash())
        assert mp["metric"] == "ret_x = session_win / session_bet (paid bet only)"

    def test_buckets_is_the_raw_rows_verbatim(self):
        rows = [{"bucket": "ge5000", "spin_count": 7, "spin_rate": 0.007}]
        mp = _emit(_base_stash(multiplier_bucket_rows=rows))
        assert mp["buckets"] == rows, (
            f"buckets must be the multiplier_bucket_rows raw input verbatim; "
            f"got {mp['buckets']!r}"
        )

    def test_tail_rtp_contribution_passed_through(self):
        mp = _emit(_base_stash(tail_rtp_contribution_pp_ge10x=99.5))
        assert mp["tail_rtp_contribution_pp_ge10x"] == 99.5

    def test_tail_win_share_passed_through(self):
        mp = _emit(_base_stash(tail_win_share_ge10x=0.815))
        assert mp["tail_win_share_ge10x"] == 0.815

    def test_pass_through_leaves_are_not_swapped(self):
        """rtp_contribution and win_share must not be cross-assigned.

        Distinct sentinel values so a swap (assigning win_share into the rtp leaf
        or vice-versa) fails — the kind of verbatim-move slip the deep-diff catches
        on real data but this pins directly.
        """
        mp = _emit(_base_stash(
            tail_rtp_contribution_pp_ge10x=11.0,
            tail_win_share_ge10x=0.22,
        ))
        assert mp["tail_rtp_contribution_pp_ge10x"] == 11.0
        assert mp["tail_win_share_ge10x"] == 0.22


# ---------------------------------------------------------------------------
# 3. Build determinism (the dict-build is a pure function of the stash)
# ---------------------------------------------------------------------------

class TestBuildKeyOrderStable:
    """The verbatim build must always emit the 5 keys in the same order."""

    @pytest.mark.parametrize("mb_total_spins", [0, 1000])
    def test_key_order_is_stable_across_both_arms(self, mb_total_spins):
        """Key insertion order must be identical whether the divisor or else arm
        fires (the byte-identity contract depends on stable key order)."""
        mp = _emit(_base_stash(mb_total_spins=mb_total_spins))
        assert list(mp.keys()) == [
            "metric",
            "buckets",
            "tail_spin_rate_ge10x",
            "tail_rtp_contribution_pp_ge10x",
            "tail_win_share_ge10x",
        ]
