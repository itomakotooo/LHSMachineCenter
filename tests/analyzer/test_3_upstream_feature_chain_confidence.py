"""Phase 3 — synthetic-input unit test for the carved chain confidence thresholds.

COVERAGE-GAP CLOSER (the 2b ``_quantiles``-index lesson;
see session_artifacts/_impl/phase_extract_2b_bonus_chain/inject_bug_evidence.md §A').

The byte-identity golden machines (M275 multi-feature applicable=True, M14 single
"Normal" applicable=False) in test_3_byte_identical_upstream_feature_carve.py lock
the carved row-build leaf-by-leaf — but NEITHER exercises the *transition-derived*
``chain_parent_confidence`` / ``chain_predecessor_confidence`` THRESHOLD branches:

  - M275's transition-derived shares are ALL in [0.011, 0.099] → every
    transition-path confidence resolves to "low".  The only "high" in the M275
    golden (BuffCollectionMap, share=1.0) comes from the BCM-fallback OVERRIDE
    (``chain_parent_share = 1.0`` hardcoded), NOT from the
    ``if chain_parent_share >= 0.80`` ladder.
  - M14 has a single feature with no inbound/outbound chain edges → confidence
    "none" (the no-edges early path), threshold ladder never entered.

So a regression in the threshold ladder (e.g. ``>= 0.50`` -> ``>= 0.20`` for the
"medium" band, or ``>= 0.80`` -> ``>= 0.90`` for "high") would leave BOTH goldens
byte-identical (empirically PROVEN by the impl-tester 2026-05-29: mutating the
medium threshold to 0.20 left test_m275_content_byte_identical +
test_m14_content_byte_identical GREEN — see inject_bug_evidence.md §Coverage-gap).

This file closes that gap with SYNTHETIC ``spin_type_next_counts`` whose dominant
edge shares land deliberately in each band (0.90 high / 0.60 medium / 0.30 low) +
the exact threshold boundaries (0.80, 0.50), pinning the resolved confidence label
for BOTH the successor (``chain_parent_*``) and predecessor (``chain_predecessor_*``)
inference — which share the same ladder + same self-loop exclusion.

This is the analog of test_2b_bonus_chain_quantiles_index.py.

Inject-bug recipe (per feedback_enumerate_safety_paths.md)
----------------------------------------------------------
INJECT (upstream_feature_breakdown.py emit(), the chain_parent confidence ladder
~line 404, AND/OR the symmetric chain_predecessor ladder ~line 459):
    -  elif chain_parent_share >= 0.50:
    +  elif chain_parent_share >= 0.20:   # INJECT-BUG (medium band widened)
RED: test_parent_confidence_medium_band / test_predecessor_confidence_medium_band
     fire (a 0.30-share feature now mis-labels "medium" instead of "low").
SIMULTANEOUSLY: the M275 + M14 byte-identity tests STAY GREEN under the same bug
     (their shares never enter the mutated band) — proving the gap is real and that
     THIS test is what catches the regression.
Revert -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    each branch of the moved compute needs its own inject-bug-provable test; the
    golden deep-diff is necessary but NOT sufficient (it only covers the data
    bands the 2 sample machines happen to produce).
- memory/feedback_perf_claim_needs_e2e_event_stream.md (sibling lesson)
    the 2b ``_quantiles``-index gap: uniform/degenerate REAL data can leave a
    whole arithmetic branch uncovered; a synthetic input that spans the branch is
    required.
- memory/feedback_self_verify_output.md
    confidence labels are an analytical-output classification — pin them at the
    band boundaries so a threshold drift can't silently re-bucket.
"""
from __future__ import annotations

from typing import Any

import pytest


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.upstream_feature_breakdown import (
            UpstreamFeatureBreakdown,
        )
    except ImportError:  # running as standalone script
        from analyzer.features.upstream_feature_breakdown import (  # type: ignore[no-redef]
            UpstreamFeatureBreakdown,
        )
    return UpstreamFeatureBreakdown


# Feature → resolved SpinType. The feature-under-test "F" is ST 10; its dominant
# transition target / source maps to a NAMED feature so chain_parent/predecessor
# get populated (the ladder requires parent_feat / pred_feat to be truthy).
_F_ST = 10
_TARGET_ST = 20  # the dominant successor/predecessor SpinType


def _base_stash(spin_type_next_counts: dict) -> dict[str, Any]:
    """A minimal valid 22-key stash whose ONLY non-empty signal is the transition
    table (so the resolved confidence ladder is the thing-under-test).

    "F" is a bonus-named paying feature (win>0 → not trigger_only → single
    aggregate row) bound to ST 10; "TargetFeat" is bound to ST 20 so the dominant
    edge resolves to a named feature.  No buckets / chains / nudge data → those
    branches stay at their empty defaults and don't perturb the confidence fields.
    """
    return {
        "upstream_feature_tally": {
            "F": {"1": {"win": 500.0, "times": 100}},
            "TargetFeat": {"2": {"win": 300.0, "times": 50}},
        },
        "feature_to_spin_type": {"F": _F_ST, "TargetFeat": _TARGET_ST},
        "spin_type_to_feature": {_F_ST: "F", _TARGET_ST: "TargetFeat"},
        "ambiguous_mapped": set(),
        "bcm_bonus_feature": None,
        "bcm_bonus_source": "none",
        "spin_type_next_counts": spin_type_next_counts,
        "chain_chunk_summaries": {},
        "chain_bucket_spins": {},
        "chain_bucket_bet": {},
        "chain_bucket_win": {},
        "spin_type_bucket_spins": {},
        "spin_type_bucket_bet": {},
        "spin_type_bucket_win": {},
        "session_bucket_spins_by_settlement_st": {},
        "session_bucket_bet_by_settlement_st": {},
        "session_bucket_win_by_settlement_st": {},
        "spin_type_spins": {},
        "spin_type_nudge_round_count": {},
        "total_spins": 1000,
        "effective_bet_for_rtp": 1000.0,
        "upstream_total_win": 800.0,
    }


def _emit_and_get_F(spin_type_next_counts: dict) -> dict:
    """Run the carved emit() with a synthetic transition table; return the "F" row."""
    plugin = _import_plugin_class()()
    summary = {"_upstream_feature_breakdown_data": _base_stash(spin_type_next_counts)}
    plugin.emit({}, summary, None)
    feats = {f["feature_name"]: f for f in summary["player_impact"]["upstream_feature_breakdown"]["features"]}
    assert "F" in feats, f"feature 'F' missing. Got {list(feats)}"
    return feats["F"]


# ---------------------------------------------------------------------------
# Forward transitions: chain_parent_* (the successor inference)
#   share = best_cnt / sum(all outbound edges from F's ST, including self-loops)
#   self-loops (F->F, i.e. ST10->ST10) are EXCLUDED from the "ranked" candidates
#   but INCLUDED in total_edges (the divisor). Build inputs accordingly.
# ---------------------------------------------------------------------------

class TestChainParentConfidenceBands:
    """chain_parent_confidence must resolve to high/medium/low per the share ladder."""

    def test_parent_confidence_high_band(self):
        """share 0.90 (>=0.80) -> 'high'.  F->Target 90, F->F(self) 0, total 100? -> no.

        Build: outbound from ST10 = {ST20: 90, ST30: 10}. ST30 has no feature
        mapping (so it's not a candidate winner but still counts in total_edges).
        best=ST20 cnt=90, total=100 -> share 0.90 -> high.
        """
        f = _emit_and_get_F({_F_ST: {_TARGET_ST: 90, 30: 10}})
        assert f["chain_parent_feature"] == "TargetFeat"
        assert f["chain_parent_share"] == pytest.approx(0.90)
        assert f["chain_parent_confidence"] == "high", (
            f"share 0.90 must be 'high'. Got {f['chain_parent_confidence']!r}"
        )

    def test_parent_confidence_high_boundary_exactly_080(self):
        """share EXACTLY 0.80 -> 'high' (the >= boundary)."""
        f = _emit_and_get_F({_F_ST: {_TARGET_ST: 80, 30: 20}})
        assert f["chain_parent_share"] == pytest.approx(0.80)
        assert f["chain_parent_confidence"] == "high", (
            f"share 0.80 (boundary) must be 'high'. Got {f['chain_parent_confidence']!r}"
        )

    def test_parent_confidence_medium_band(self):
        """share 0.60 (>=0.50, <0.80) -> 'medium'.

        This is the band the M275/M14 goldens CANNOT reach (all their shares <0.50).
        """
        f = _emit_and_get_F({_F_ST: {_TARGET_ST: 60, 30: 40}})
        assert f["chain_parent_share"] == pytest.approx(0.60)
        assert f["chain_parent_confidence"] == "medium", (
            f"share 0.60 must be 'medium'. Got {f['chain_parent_confidence']!r}"
        )

    def test_parent_confidence_medium_boundary_exactly_050(self):
        """share EXACTLY 0.50 -> 'medium' (the >= boundary)."""
        f = _emit_and_get_F({_F_ST: {_TARGET_ST: 50, 30: 50}})
        assert f["chain_parent_share"] == pytest.approx(0.50)
        assert f["chain_parent_confidence"] == "medium", (
            f"share 0.50 (boundary) must be 'medium'. Got {f['chain_parent_confidence']!r}"
        )

    def test_parent_confidence_low_band(self):
        """share 0.30 (<0.50) -> 'low' (the band the goldens DO exercise).

        The remainder mass goes to the SELF-loop (ST10->ST10) which is excluded
        from the candidate ranking but counted in total_edges — so TargetFeat
        (cnt 30) stays the winner with share 30/100 = 0.30.  (Routing the
        remainder to another *unmapped* ST would instead make that unmapped ST the
        dominant edge → parent None / confidence 'none', a different branch.)
        """
        f = _emit_and_get_F({_F_ST: {_TARGET_ST: 30, _F_ST: 70}})
        assert f["chain_parent_feature"] == "TargetFeat"
        assert f["chain_parent_share"] == pytest.approx(0.30)
        assert f["chain_parent_confidence"] == "low", (
            f"share 0.30 must be 'low'. Got {f['chain_parent_confidence']!r}"
        )

    def test_parent_confidence_just_below_medium_is_low(self):
        """share 0.49 (<0.50) -> 'low' (just under the medium boundary)."""
        f = _emit_and_get_F({_F_ST: {_TARGET_ST: 49, _F_ST: 51}})
        assert f["chain_parent_feature"] == "TargetFeat"
        assert f["chain_parent_share"] == pytest.approx(0.49)
        assert f["chain_parent_confidence"] == "low", (
            f"share 0.49 must be 'low' (below medium boundary). Got {f['chain_parent_confidence']!r}"
        )

    def test_parent_self_loop_excluded_from_candidate_but_in_divisor(self):
        """A dominant self-loop (F->F) must NOT win the parent (excluded), and the
        share is computed against the FULL edge total (self-loop included).

        Build: ST10->ST10 (self) 70, ST10->ST20 30. Candidate winner = ST20
        (self-loop excluded from ranking) with cnt 30; total_edges = 100 (self
        included) -> share 0.30 -> low. Proves both the self-loop exclusion AND the
        divisor convention survive the carve (a regression that dropped the self
        loop from the divisor would give 30/30=1.0 -> 'high').
        """
        f = _emit_and_get_F({_F_ST: {_F_ST: 70, _TARGET_ST: 30}})
        assert f["chain_parent_feature"] == "TargetFeat", (
            "self-loop ST must be excluded from the parent candidate ranking"
        )
        assert f["chain_parent_share"] == pytest.approx(0.30), (
            f"share must be 30/100 (self-loop IN divisor). Got {f['chain_parent_share']!r}"
        )
        assert f["chain_parent_confidence"] == "low"


# ---------------------------------------------------------------------------
# Reverse transitions: chain_predecessor_* (the predecessor inference)
#   The reverse table is built from spin_type_next_counts: an edge ST_X -> ST10
#   counts as an inbound edge to ST10. Same ladder, same self-loop exclusion.
# ---------------------------------------------------------------------------

class TestChainPredecessorConfidenceBands:
    """chain_predecessor_confidence must resolve to high/medium/low per the ladder."""

    def test_predecessor_confidence_high_band(self):
        """Inbound to ST10: {ST20->ST10: 90, ST30->ST10: 10} -> share 0.90 -> high."""
        f = _emit_and_get_F({_TARGET_ST: {_F_ST: 90}, 30: {_F_ST: 10}})
        assert f["chain_predecessor_feature"] == "TargetFeat"
        assert f["chain_predecessor_share"] == pytest.approx(0.90)
        assert f["chain_predecessor_confidence"] == "high", (
            f"inbound share 0.90 must be 'high'. Got {f['chain_predecessor_confidence']!r}"
        )

    def test_predecessor_confidence_medium_band(self):
        """Inbound share 0.60 -> 'medium' (the goldens cannot reach this band)."""
        f = _emit_and_get_F({_TARGET_ST: {_F_ST: 60}, 30: {_F_ST: 40}})
        assert f["chain_predecessor_share"] == pytest.approx(0.60)
        assert f["chain_predecessor_confidence"] == "medium", (
            f"inbound share 0.60 must be 'medium'. Got {f['chain_predecessor_confidence']!r}"
        )

    def test_predecessor_confidence_low_band(self):
        """Inbound share 0.30 -> 'low' (the band the goldens DO exercise).

        Inbound to ST10: from ST20 (30) + from ST10 self-loop (70). The self-loop
        is excluded from the predecessor candidate ranking but counted in the
        divisor → TargetFeat wins with share 30/100 = 0.30.
        """
        f = _emit_and_get_F({_TARGET_ST: {_F_ST: 30}, _F_ST: {_F_ST: 70}})
        assert f["chain_predecessor_feature"] == "TargetFeat"
        assert f["chain_predecessor_share"] == pytest.approx(0.30)
        assert f["chain_predecessor_confidence"] == "low", (
            f"inbound share 0.30 must be 'low'. Got {f['chain_predecessor_confidence']!r}"
        )

    def test_predecessor_self_loop_excluded(self):
        """A dominant inbound self-loop (ST10->ST10) must not win the predecessor.

        Inbound to ST10: {ST10->ST10: 70 (self), ST20->ST10: 30}. Winner = ST20
        (self excluded from ranking), share 30/100 (self in divisor) -> low.
        """
        f = _emit_and_get_F({_F_ST: {_F_ST: 70, _TARGET_ST: 30}, _TARGET_ST: {_F_ST: 30}})
        # ST10 inbound edges: from ST10(self)=70, from ST20=30 -> winner ST20, share 0.30
        assert f["chain_predecessor_feature"] == "TargetFeat"
        assert f["chain_predecessor_share"] == pytest.approx(0.30)
        assert f["chain_predecessor_confidence"] == "low"


# ---------------------------------------------------------------------------
# No-edge / unmapped-target early paths (the "none" confidence branch)
# ---------------------------------------------------------------------------

class TestChainConfidenceNoneBranch:
    """No transitions / unmapped dominant target -> confidence 'none', feature None."""

    def test_no_transitions_yields_none(self):
        """Empty spin_type_next_counts -> both parent and predecessor 'none'."""
        f = _emit_and_get_F({})
        assert f["chain_parent_feature"] is None
        assert f["chain_parent_confidence"] == "none"
        assert f["chain_parent_share"] == 0.0
        assert f["chain_predecessor_feature"] is None
        assert f["chain_predecessor_confidence"] == "none"
        assert f["chain_predecessor_share"] == 0.0

    def test_dominant_target_with_no_feature_mapping_yields_none(self):
        """If the dominant successor ST has no feature mapping, parent stays None.

        Build: ST10 -> ST99 (cnt 100), but ST99 is NOT in spin_type_to_feature.
        The ladder requires ``parent_feat`` truthy; an unmapped ST leaves parent
        None / confidence 'none' (the ``if parent_feat:`` guard) — even though
        total_edges > 0. Proves the carve preserves that guard (a regression that
        dropped it would set confidence 'high' on share 1.0 with feature None).
        """
        f = _emit_and_get_F({_F_ST: {99: 100}})
        assert f["chain_parent_feature"] is None, (
            "an unmapped dominant target must leave chain_parent_feature None"
        )
        assert f["chain_parent_confidence"] == "none"
