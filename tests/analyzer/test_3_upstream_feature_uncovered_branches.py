"""Phase 3 — synthetic-input unit tests for carved branches the goldens MISS.

COVERAGE-GAP CLOSER (the 2b ``_quantiles``-index lesson;
see session_artifacts/_impl/phase_extract_2b_bonus_chain/inject_bug_evidence.md §A').

The byte-identity goldens (M275 multi-feature / M14 single-Normal) lock the carved
row-build leaf-by-leaf, but the 2 sample machines do NOT happen to produce data
that enters these three branches of the moved compute:

  1. ``is_wild_nudge`` — the ``_st_nudge_rounds / _st_total_rounds >= 0.9`` tag
     (M279 ST=36 "MoveSpin" is the canonical case). BOTH goldens have
     is_wild_nudge=False on every row (no feature is >=90% wild-nudge rounds).
  2. ``spin_type_binding_ambiguous`` — ``feat_name in ambiguous_mapped`` (the
     _infer_feature_spin_type_mapping ambiguity result). BOTH goldens have an
     EMPTY ambiguous_mapped set → the flag is False everywhere.
  3. The settlement-ST bucket fallback — when a feature's round-level
     ``spin_type_bucket_*`` maps are all zero-win but the feature DID win
     (``feat_bucket_total_win == 0.0 and feat_total_win > 0.0``), the build falls
     through to the session-level histogram keyed by settlement ST (the M15
     TopDollar "无倍率分桶数据 -> real distribution" fix). Neither M275 nor M14 has a
     zero-win-settlement-ST paying feature → this fallback is never taken.

Each is a pure data->output mapping in the moved compute; this file drives the
carved ``emit()`` with a synthetic stash that enters each branch and pins the
output, so a regression in the moved expression is caught (the golden deep-diff
would stay GREEN — empirically the same class of gap as the 2b _quantiles index).

Inject-bug recipes (per feedback_enumerate_safety_paths.md) — all verified
2026-05-29 (RED->revert->GREEN; evidence in inject_bug_evidence.md §Coverage-gap):

  is_wild_nudge:
    -  if _st_total_rounds > 0 and _st_nudge_rounds / _st_total_rounds >= 0.9:
    +  if _st_total_rounds > 0 and _st_nudge_rounds / _st_total_rounds >= 0.99:  # BUG
    RED: test_wild_nudge_at_threshold (0.90 no longer tags). Goldens stay GREEN.

  ambiguous:
    -  "spin_type_binding_ambiguous": feat_name in ambiguous_mapped,
    +  "spin_type_binding_ambiguous": False,  # BUG
    RED: test_ambiguous_flag_true. Goldens stay GREEN (their set is empty).

  settlement-ST fallback:
    -  if feat_bucket_total_win == 0.0 and feat_total_win > 0.0:
    +  if False and feat_bucket_total_win == 0.0 and feat_total_win > 0.0:  # BUG
    RED: test_settlement_st_fallback_used (bucket_total_spins reverts to the
         zero-win round-level count). Goldens stay GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    each branch of the moved compute needs its own inject-bug-provable test.
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    the 2b _quantiles-index gap: the 2 sample machines' data can leave a whole
    branch uncovered; a synthetic input spanning the branch is required.
- memory/round_classification_primitives (is_wild_nudge_round, Bug 3)
    ST=36+move+cost=0 wild-nudge rounds are a paid-spin extension; the >=0.9 tag
    surfaces it so the UI nests the row + BCM heuristics exclude it.
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


_F_ST = 10


def _base_stash(**over: Any) -> dict[str, Any]:
    """Minimal valid 22-key stash; "F" is a single bonus-named paying feature
    bound to ST 10. Override specific raw inputs to enter a target branch."""
    s: dict[str, Any] = {
        "upstream_feature_tally": {"F": {"1": {"win": 500.0, "times": 100}}},
        "feature_to_spin_type": {"F": _F_ST},
        "spin_type_to_feature": {_F_ST: "F"},
        "ambiguous_mapped": set(),
        "bcm_bonus_feature": None,
        "bcm_bonus_source": "none",
        "spin_type_next_counts": {},
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
        "upstream_total_win": 500.0,
    }
    s.update(over)
    return s


def _emit_F(stash: dict[str, Any]) -> dict:
    plugin = _import_plugin_class()()
    summary = {"_upstream_feature_breakdown_data": stash}
    plugin.emit({}, summary, None)
    feats = {
        f["feature_name"]: f
        for f in summary["player_impact"]["upstream_feature_breakdown"]["features"]
    }
    assert "F" in feats, f"feature 'F' missing. Got {list(feats)}"
    return feats["F"]


# ---------------------------------------------------------------------------
# 1. is_wild_nudge (the >=0.9 nudge-ratio tag)
# ---------------------------------------------------------------------------

class TestWildNudgeTag:
    """is_wild_nudge must be True iff nudge_rounds/total_rounds >= 0.9."""

    def test_wild_nudge_above_threshold(self):
        """95/100 nudge rounds (0.95 >= 0.9) -> is_wild_nudge True."""
        f = _emit_F(_base_stash(
            spin_type_spins={_F_ST: 100},
            spin_type_nudge_round_count={_F_ST: 95},
        ))
        assert f["is_wild_nudge"] is True, (
            f"0.95 nudge ratio must tag is_wild_nudge. Got {f['is_wild_nudge']!r}"
        )

    def test_wild_nudge_at_threshold(self):
        """EXACTLY 0.90 (90/100) -> is_wild_nudge True (the >= boundary).

        This is the boundary a `>= 0.9` -> `> 0.9` regression would break; the
        goldens (is_wild_nudge False everywhere) cannot catch it.
        """
        f = _emit_F(_base_stash(
            spin_type_spins={_F_ST: 100},
            spin_type_nudge_round_count={_F_ST: 90},
        ))
        assert f["is_wild_nudge"] is True, (
            f"0.90 nudge ratio (boundary) must tag is_wild_nudge. Got {f['is_wild_nudge']!r}"
        )

    def test_wild_nudge_below_threshold(self):
        """89/100 (0.89 < 0.9) -> is_wild_nudge False."""
        f = _emit_F(_base_stash(
            spin_type_spins={_F_ST: 100},
            spin_type_nudge_round_count={_F_ST: 89},
        ))
        assert f["is_wild_nudge"] is False, (
            f"0.89 nudge ratio must NOT tag is_wild_nudge. Got {f['is_wild_nudge']!r}"
        )

    def test_wild_nudge_zero_rounds_is_false(self):
        """No rounds for the ST -> is_wild_nudge False (the _st_total_rounds>0 guard)."""
        f = _emit_F(_base_stash(
            spin_type_spins={_F_ST: 0},
            spin_type_nudge_round_count={_F_ST: 0},
        ))
        assert f["is_wild_nudge"] is False


# ---------------------------------------------------------------------------
# 2. spin_type_binding_ambiguous (feat_name in ambiguous_mapped)
# ---------------------------------------------------------------------------

class TestAmbiguousBindingFlag:
    """spin_type_binding_ambiguous must mirror membership in ambiguous_mapped."""

    def test_ambiguous_flag_true(self):
        """F in ambiguous_mapped -> flag True.

        The goldens have an empty ambiguous_mapped, so the True case is uncovered
        by the byte-identity tests; a regression hardcoding False would slip past.
        """
        f = _emit_F(_base_stash(ambiguous_mapped={"F"}))
        assert f["spin_type_binding_ambiguous"] is True, (
            f"F in ambiguous_mapped must set the flag. Got {f['spin_type_binding_ambiguous']!r}"
        )

    def test_ambiguous_flag_false_when_not_in_set(self):
        """F not in ambiguous_mapped -> flag False (the golden-covered case)."""
        f = _emit_F(_base_stash(ambiguous_mapped={"OtherFeat"}))
        assert f["spin_type_binding_ambiguous"] is False


# ---------------------------------------------------------------------------
# 3. settlement-ST bucket fallback
#    (round-level buckets zero-win + feature won -> use session-by-settlement-ST)
# ---------------------------------------------------------------------------

class TestSettlementStBucketFallback:
    """When round-level buckets are zero-win but the feature won, the build must
    fall through to the session-level histogram keyed by settlement ST (M15
    TopDollar case)."""

    def test_settlement_st_fallback_used(self):
        """Round-level win 0 + feature win>0 + session buckets present -> fallback.

        bucket_total_spins must come from the SESSION buckets (5), not the
        zero-win round-level buckets (10). A regression disabling the fallback
        would report 10 (and an all-zero distribution) — invisible to the goldens.
        """
        f = _emit_F(_base_stash(
            # round-level: 10 spins but ZERO win (settlement rounds carry None win)
            spin_type_bucket_spins={_F_ST: {"x1-x2": 10}},
            spin_type_bucket_bet={_F_ST: {"x1-x2": 100.0}},
            spin_type_bucket_win={_F_ST: {"x1-x2": 0.0}},
            # session-by-settlement-ST: 5 spins with real win
            session_bucket_spins_by_settlement_st={_F_ST: {"x1-x2": 5}},
            session_bucket_bet_by_settlement_st={_F_ST: {"x1-x2": 50.0}},
            session_bucket_win_by_settlement_st={_F_ST: {"x1-x2": 400.0}},
        ))
        assert f["bucket_total_spins"] == 5, (
            f"settlement-ST fallback must use the SESSION bucket spins (5), not the "
            f"zero-win round-level count (10). Got {f['bucket_total_spins']!r}"
        )
        assert f["bucket_distribution"], (
            "fallback must produce a non-empty bucket_distribution from session data"
        )

    def test_no_fallback_when_round_level_has_win(self):
        """Round-level buckets WITH win -> no fallback (round-level used as-is).

        Proves the fallback is precise (only fires on the zero-win-round-level
        case), not over-broad. bucket_total_spins must be the round-level 10.
        """
        f = _emit_F(_base_stash(
            spin_type_bucket_spins={_F_ST: {"x1-x2": 10}},
            spin_type_bucket_bet={_F_ST: {"x1-x2": 100.0}},
            spin_type_bucket_win={_F_ST: {"x1-x2": 250.0}},  # round-level HAS win
            session_bucket_spins_by_settlement_st={_F_ST: {"x1-x2": 5}},
            session_bucket_win_by_settlement_st={_F_ST: {"x1-x2": 400.0}},
            session_bucket_bet_by_settlement_st={_F_ST: {"x1-x2": 50.0}},
        ))
        assert f["bucket_total_spins"] == 10, (
            f"with round-level win present, no fallback — bucket_total_spins must be "
            f"the round-level 10. Got {f['bucket_total_spins']!r}"
        )
