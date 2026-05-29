"""R1 Phase 2 d2 — fallback_no_chain_data + CR-2 companion warning.

Invariants asserted (AC#3)
--------------------------
1. When 2+ scatter features exist and ALL chain counts are zero,
   trigger_target_confidence must be "fallback_no_chain_data".
2. trigger_target is still emitted (alphabetical-first for determinism).
3. A companion warning MUST be written to summary["feature_errors"]
   under the key "bonus_chain_dynamics_fallback_{pids}".
4. The companion warning dict has: type="alphabetical_fallback",
   reason (string), pids, chosen_target, candidates (list of features).
5. Non-zero chain-count case must NOT write companion warning
   (data_inferred confidence does not trigger CR-2 warning).

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug CR-2: remove the companion warning write in bonus_chain_dynamics.py emit().
  Find the block starting:
    if trigger_target_confidence == "fallback_no_chain_data" and fallback_pid_str is not None:
  Delete that entire if-block (lines ~301-317 in bonus_chain_dynamics.py).
  RED: test_fallback_companion_warning_present fails — feature_errors["bonus_chain_dynamics_fallback_..."]
       is absent even though confidence == "fallback_no_chain_data".
  Revert (restore if-block) -> GREEN.

Memory files cited
------------------
- memory/feedback_invariant_with_fallback_hides_drift.md
  (fallback MUST surface in feature_errors, not just the confidence field)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_no_silent_swallow.md
  (silent alphabetical fallback without warning = swallowed degradation signal)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.bonus_chain_dynamics import BonusChainDynamics
    except ImportError:
        from analyzer.features.bonus_chain_dynamics import BonusChainDynamics  # type: ignore[no-redef]
    return BonusChainDynamics


def _make_ctx(scatter_marker_pids: frozenset[str]) -> Any:
    ctx = MagicMock()
    ctx.mechanism_registry.scatter_marker_pids = scatter_marker_pids
    return ctx


def _raw_inputs(features: list[str]) -> dict:
    """Phase 2b RAW dict-build inputs the plugin re-sources to BUILD the dict.

    Phase 2b carve (test_2b_*): the plugin now BUILDS the bonus_chain_dynamics
    dict from these 9 raw accumulator inputs (it no longer reads a pre-built
    dict).  These d2 tests assert the trigger_target INFERENCE + the CR-2
    companion warning (step 3, which reads scatter_feature_chain_counts DIRECTLY
    from the stash) — that runs AFTER the dict-build (step 2) and is independent
    of all_chains_by_feature.  So the raw inputs just need to be present + valid
    for the build to succeed; one chain per feature keeps by_feature non-empty.
    NOTE: scatter_feature_chain_counts is supplied SEPARATELY by each builder
    below (all-zero vs non-zero) — that injected value is the thing under test,
    and is read independently of these raw all_chains_by_feature inputs.
    """
    all_chains = {
        f: {"lengths": [5], "max_ratios": [1], "total_rounds": 5, "retrigger_rounds": 0}
        for f in features
    }
    n = len(features)
    return {
        "bonus_chain_lengths": [5] * n,
        "bonus_chain_max_ratios": [1] * n,
        "bonus_total_rounds_global": 5 * n,
        "bonus_retrigger_rounds_global": 0,
        "bonus_chain_retrigger_events": [0] * n,
        "bonus_extra_ratio_counts": {},
        "bonus_depth_ratio_count": {},
        "bonus_depth_ratio_sum": {},
        "all_chains_by_feature": all_chains,
    }


def _make_all_zero_stash(features: list[str]) -> dict:
    """Build stash where scatter_feature_chain_counts has all-zero values.

    This exercises branch 3 of the len-first dispatch:
      len >= 2 AND chain_counts present AND all-zero → "fallback_no_chain_data"
    """
    return {
        **_raw_inputs(features),  # Phase 2b: plugin builds the dict from raw inputs
        "scatter_feature_names": sorted(features),  # sorted per PIA stash construction
        "scatter_feature_chain_counts": {f: 0 for f in features},  # all zero (the path under test)
    }


def _make_data_inferred_stash(features: list[str], counts: dict[str, int]) -> dict:
    """Build stash where chain_counts has at least one non-zero value.

    This exercises branch 2: len >= 2 AND chain_counts present AND max > 0.
    """
    return {
        **_raw_inputs(features),  # Phase 2b: plugin builds the dict from raw inputs
        "scatter_feature_names": sorted(features),
        "scatter_feature_chain_counts": counts,  # the path under test
    }


# ---------------------------------------------------------------------------
# T1: fallback_no_chain_data confidence + companion warning
# ---------------------------------------------------------------------------

class TestFallbackNoChainDataConfidence:
    """All-zero chain counts → fallback_no_chain_data + companion warning."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    @pytest.fixture
    def all_zero_summary(self, plugin):
        """Run emit() with 2 features and all-zero chain counts."""
        scatter_pid = "666"
        features = ["AlphaFeature", "ZetaFeature"]
        stash = _make_all_zero_stash(features)
        pid_rows = [{"payout_id": scatter_pid, "hit_count": 50, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))
        plugin.emit({}, summary, ctx)
        return summary

    def test_fallback_confidence_set(self, all_zero_summary):
        """trigger_target_confidence must be 'fallback_no_chain_data' when all counts are zero.

        This is the main branch 3 signal — alphabetical fallback used, but not silently.
        """
        row_666 = next(
            r for r in all_zero_summary["player_impact"]["payout_ids_top20"]
            if str(r.get("payout_id")) == "666"
        )
        confidence = row_666["notes"].get("trigger_target_confidence")
        assert confidence == "fallback_no_chain_data", (
            f"All-zero chain counts must produce 'fallback_no_chain_data' confidence. "
            f"Got: {confidence!r}"
        )

    def test_fallback_trigger_target_is_alphabetical_first(self, all_zero_summary):
        """trigger_target must be alphabetical-first of sorted feature names ('AlphaFeature')."""
        row_666 = next(
            r for r in all_zero_summary["player_impact"]["payout_ids_top20"]
            if str(r.get("payout_id")) == "666"
        )
        target = row_666["notes"].get("trigger_target")
        assert target == "AlphaFeature", (
            f"Alphabetical-first of ['AlphaFeature','ZetaFeature'] is 'AlphaFeature'. "
            f"Got: {target!r}"
        )

    def test_fallback_companion_warning_present(self, all_zero_summary):
        """feature_errors must contain the companion warning entry (CR-2 requirement).

        INJECT-BUG (CR-2): delete the companion warning if-block in emit().
        RED: feature_errors["bonus_chain_dynamics_fallback_..."] is absent → this test fails.
        Revert → GREEN.

        Per memory/feedback_invariant_with_fallback_hides_drift.md: fallback signals
        MUST surface in feature_errors so operators scanning that panel see degradation.
        """
        fe = all_zero_summary.get("feature_errors", {})
        # Key is "bonus_chain_dynamics_fallback_{pids}" where pids = joined sorted scatter pids
        matching_keys = [k for k in fe if k.startswith("bonus_chain_dynamics_fallback_")]
        assert matching_keys, (
            f"feature_errors must contain a 'bonus_chain_dynamics_fallback_*' key "
            f"when confidence=='fallback_no_chain_data'. "
            f"feature_errors: {fe}. "
            f"This is the CR-2 companion warning requirement. "
            f"Inject-bug: delete the if-block at the end of emit() "
            f"in bonus_chain_dynamics.py → test RED. Revert → GREEN."
        )

    def test_fallback_warning_has_correct_type(self, all_zero_summary):
        """Companion warning dict must have type='alphabetical_fallback'."""
        fe = all_zero_summary.get("feature_errors", {})
        matching_keys = [k for k in fe if k.startswith("bonus_chain_dynamics_fallback_")]
        assert matching_keys, "Companion warning absent — see test_fallback_companion_warning_present"
        warning = fe[matching_keys[0]]
        assert warning.get("type") == "alphabetical_fallback", (
            f"Companion warning type must be 'alphabetical_fallback'. Got: {warning!r}"
        )

    def test_fallback_warning_has_chosen_target(self, all_zero_summary):
        """Companion warning must include chosen_target matching the emitted trigger_target."""
        fe = all_zero_summary.get("feature_errors", {})
        matching_keys = [k for k in fe if k.startswith("bonus_chain_dynamics_fallback_")]
        assert matching_keys, "Companion warning absent"
        warning = fe[matching_keys[0]]
        assert warning.get("chosen_target") == "AlphaFeature", (
            f"chosen_target must be 'AlphaFeature' (alphabetical-first). Got: {warning!r}"
        )

    def test_fallback_warning_has_candidates(self, all_zero_summary):
        """Companion warning must include candidates list with all scatter features."""
        fe = all_zero_summary.get("feature_errors", {})
        matching_keys = [k for k in fe if k.startswith("bonus_chain_dynamics_fallback_")]
        assert matching_keys, "Companion warning absent"
        warning = fe[matching_keys[0]]
        candidates = warning.get("candidates")
        assert isinstance(candidates, list), (
            f"candidates must be a list, got: {type(candidates).__name__}"
        )
        assert set(candidates) == {"AlphaFeature", "ZetaFeature"}, (
            f"candidates must include all scatter features. Got: {candidates!r}"
        )

    def test_fallback_warning_has_reason_string(self, all_zero_summary):
        """Companion warning must include a non-empty reason string."""
        fe = all_zero_summary.get("feature_errors", {})
        matching_keys = [k for k in fe if k.startswith("bonus_chain_dynamics_fallback_")]
        assert matching_keys, "Companion warning absent"
        warning = fe[matching_keys[0]]
        reason = warning.get("reason")
        assert isinstance(reason, str) and reason, (
            f"reason must be a non-empty string. Got: {reason!r}"
        )


# ---------------------------------------------------------------------------
# T2: data_inferred case must NOT write companion warning
# ---------------------------------------------------------------------------

class TestDataInferredNoCompanionWarning:
    """Non-zero chain counts → data_inferred confidence; no companion warning."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    @pytest.fixture
    def data_inferred_summary(self, plugin):
        """Run emit() with 2 features and non-zero chain counts."""
        scatter_pid = "666"
        features = ["AlphaFeature", "ZetaFeature"]
        counts = {"AlphaFeature": 100, "ZetaFeature": 1}
        stash = _make_data_inferred_stash(features, counts)
        pid_rows = [{"payout_id": scatter_pid, "hit_count": 101, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))
        plugin.emit({}, summary, ctx)
        return summary

    def test_data_inferred_confidence(self, data_inferred_summary):
        """trigger_target_confidence must be 'data_inferred' when max count > 0."""
        row_666 = next(
            r for r in data_inferred_summary["player_impact"]["payout_ids_top20"]
            if str(r.get("payout_id")) == "666"
        )
        confidence = row_666["notes"].get("trigger_target_confidence")
        assert confidence == "data_inferred", (
            f"Non-zero chain counts must produce 'data_inferred' confidence. Got: {confidence!r}"
        )

    def test_no_companion_warning_for_data_inferred(self, data_inferred_summary):
        """feature_errors must NOT contain fallback warning for data_inferred case."""
        fe = data_inferred_summary.get("feature_errors", {})
        fallback_keys = [k for k in fe if k.startswith("bonus_chain_dynamics_fallback_")]
        assert not fallback_keys, (
            f"No companion warning must be written for 'data_inferred' confidence. "
            f"Got unexpected fallback keys: {fallback_keys}"
        )


# ---------------------------------------------------------------------------
# T3: Three-feature fallback — all-zero with 3 features
# ---------------------------------------------------------------------------

class TestThreeFeatureFallback:
    """All-zero with 3 scatter features still produces companion warning."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_three_feature_all_zero_confidence(self, plugin):
        """3 features, all-zero chain counts → fallback_no_chain_data."""
        scatter_pid = "999"
        features = ["FeatureA", "FeatureB", "FeatureC"]
        stash = _make_all_zero_stash(features)
        pid_rows = [{"payout_id": scatter_pid, "hit_count": 30, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))
        plugin.emit({}, summary, ctx)

        row = next(
            r for r in summary["player_impact"]["payout_ids_top20"]
            if str(r.get("payout_id")) == scatter_pid
        )
        assert row["notes"]["trigger_target_confidence"] == "fallback_no_chain_data"

        fe = summary.get("feature_errors", {})
        fallback_keys = [k for k in fe if k.startswith("bonus_chain_dynamics_fallback_")]
        assert fallback_keys, (
            f"3-feature all-zero must still produce companion warning. "
            f"feature_errors: {fe}"
        )
