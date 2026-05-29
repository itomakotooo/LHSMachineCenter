"""R1 Phase 2 d3 — 'unique' confidence for exactly 1 scatter feature.

Invariants asserted (AC#5)
--------------------------
1. 1-feature stash → trigger_target_confidence == "unique".
2. trigger_target == features[0] (the only feature name).
3. No RuntimeError even when scatter_feature_chain_counts is absent —
   the len-first dispatch (coordinator CR-1) goes to the "unique" branch
   before ever consulting chain_counts.
4. 0-feature stash → trigger_target_confidence == "unknown"
   (scatter markers exist but no feature data — distinct from "unique").
5. "unique" is emitted only for the trigger-marker pid; non-marker pids
   have no trigger_target_confidence key in their notes.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug d3 stash-first anti-pattern: change dispatch to check stash BEFORE len.
  In bonus_chain_dynamics.py emit(), in the "n > 1 branches need chain_counts" block,
  move the scatter_feature_chain_counts check BEFORE the "if n == 1:" check:
    # WRONG: stash-first
    if "scatter_feature_chain_counts" not in stash:
        raise RuntimeError(...)
    if n == 1:
        return features[0], "unique"
  RED: test_single_feature_no_chain_counts_no_runtime_error fails —
       RuntimeError is raised even for len==1 when chain_counts absent.
  Revert (restore len-first: if n == 1 check BEFORE chain_counts check) → GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_no_silent_swallow.md
  (unique branch must never raise on missing chain_counts — len-first is correct)
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


def _raw_inputs() -> dict:
    """Phase 2b RAW dict-build inputs (empty/applicable=False shape).

    Phase 2b carve (test_2b_*): the plugin now BUILDS the bonus_chain_dynamics
    dict from these 9 raw accumulator inputs (it no longer reads a pre-built
    dict).  These d3 tests assert the trigger_target INFERENCE (which reads
    scatter_feature_names / scatter_feature_chain_counts, downstream of and
    independent from the dict-build), so an empty raw set is sufficient — it
    builds a valid applicable=False dict and lets the inference run unchanged.
    Every key is present so the plugin's fail-loud guard (test_2b_bonus_chain_
    fail_loud_stash.py) is satisfied.
    """
    return {
        "bonus_chain_lengths": [],
        "bonus_chain_max_ratios": [],
        "bonus_total_rounds_global": 0,
        "bonus_retrigger_rounds_global": 0,
        "bonus_chain_retrigger_events": [],
        "bonus_extra_ratio_counts": {},
        "bonus_depth_ratio_count": {},
        "bonus_depth_ratio_sum": {},
        "all_chains_by_feature": {},
    }


def _make_single_feature_stash(feature_name: str, include_chain_counts: bool = False) -> dict:
    """Build stash with exactly 1 scatter feature.

    include_chain_counts controls whether scatter_feature_chain_counts is present.
    The 'unique' branch should fire regardless (len-first dispatch).
    """
    stash: dict = {
        **_raw_inputs(),  # Phase 2b: plugin builds the dict from raw inputs
        "scatter_feature_names": [feature_name],
    }
    if include_chain_counts:
        stash["scatter_feature_chain_counts"] = {feature_name: 0}
    return stash


def _make_zero_feature_stash() -> dict:
    """Build stash with 0 scatter features (unknown branch)."""
    return {
        **_raw_inputs(),  # Phase 2b: plugin builds the dict from raw inputs
        "scatter_feature_names": [],
    }


# ---------------------------------------------------------------------------
# T1: Single-feature → "unique" confidence
# ---------------------------------------------------------------------------

class TestSingleFeatureUniqueConfidence:
    """1-feature stash must produce 'unique' confidence and correct trigger_target."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_single_feature_confidence_unique(self, plugin):
        """trigger_target_confidence must be 'unique' for 1-feature stash.

        R1 Phase 2 d3 fix: len-first dispatch sets confidence="unique"
        for single-feature stashes.
        """
        scatter_pid = "666"
        stash = _make_single_feature_stash("NormalCollectionSpin")
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

        row = pid_rows[0]
        confidence = row["notes"].get("trigger_target_confidence")
        assert confidence == "unique", (
            f"1-feature stash must produce 'unique' confidence (d3 fix). "
            f"Got: {confidence!r}"
        )

    def test_single_feature_trigger_target_is_that_feature(self, plugin):
        """trigger_target must be the single feature name."""
        scatter_pid = "666"
        feature = "NormalCollectionSpin"
        stash = _make_single_feature_stash(feature)
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

        row = pid_rows[0]
        target = row["notes"].get("trigger_target")
        assert target == feature, (
            f"trigger_target must be {feature!r} (only feature). Got: {target!r}"
        )

    def test_single_feature_no_chain_counts_no_runtime_error(self, plugin):
        """1-feature + no chain_counts → NO RuntimeError (len-first dispatch).

        INJECT-BUG (stash-first anti-pattern): move chain_counts check before len check.
        RED: RuntimeError raised even for len==1 → this test fails.
        Revert (restore len-first: check n==1 BEFORE chain_counts) → GREEN.

        This verifies the coordinator CR-1 resolution: the len-first ordering means
        single-feature machines don't need the R1 d2 stash extension deployed.
        """
        scatter_pid = "666"
        stash = _make_single_feature_stash("MyFeature", include_chain_counts=False)
        pid_rows = [{"payout_id": scatter_pid, "hit_count": 50, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))

        # Must not raise RuntimeError (len==1 → unique branch; chain_counts not checked)
        try:
            plugin.emit({}, summary, ctx)
        except RuntimeError as e:
            pytest.fail(
                f"1-feature stash must NOT raise RuntimeError even without chain_counts. "
                f"The len-first dispatch (CR-1) means len==1 is handled before the "
                f"chain_counts-required branch. Got: RuntimeError({e})"
            )

        row = pid_rows[0]
        assert row["notes"]["trigger_target_confidence"] == "unique"

    def test_single_feature_with_chain_counts_still_unique(self, plugin):
        """1-feature WITH chain_counts present → still 'unique' confidence.

        chain_counts being present is fine; the len-first dispatch still
        picks 'unique' for n==1 (chain_counts are consulted only for n>=2).
        """
        scatter_pid = "666"
        stash = _make_single_feature_stash("MyFeature", include_chain_counts=True)
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

        row = pid_rows[0]
        assert row["notes"]["trigger_target_confidence"] == "unique", (
            f"Even with chain_counts present, n==1 must produce 'unique'. "
            f"Got: {row['notes'].get('trigger_target_confidence')!r}"
        )


# ---------------------------------------------------------------------------
# T2: Zero-feature → "unknown" confidence (distinct from "unique")
# ---------------------------------------------------------------------------

class TestZeroFeatureUnknownConfidence:
    """0-feature scatter stash → 'unknown' (scatter pids exist, no chain data)."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_zero_features_confidence_unknown(self, plugin):
        """0-feature stash with scatter markers → 'unknown' confidence, not 'unique'.

        Per the docstring: "unknown" = scatter markers exist but scatter_feature_names empty.
        This is distinct from "unique" (which requires exactly 1 feature).
        """
        scatter_pid = "666"
        stash = _make_zero_feature_stash()
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

        row = pid_rows[0]
        confidence = row["notes"].get("trigger_target_confidence")
        # The "unknown" branch fires when scatter_marker_pids is non-empty
        # but scatter_feature_names is empty (len==0).
        # Per the code: elif scatter_marker_pids: → confidence = "unknown"
        # then step 4 notes block: trigger_target_confidence or "unknown" = "unknown".
        # This is deterministic — always "unknown", never None for trigger rows.
        assert confidence == "unknown", (
            f"0-feature stash with scatter markers must produce 'unknown' confidence. "
            f"Got: {confidence!r}. "
            f"The elif scatter_marker_pids branch sets confidence='unknown' deterministically."
        )


# ---------------------------------------------------------------------------
# T3: "unique" is emitted only for trigger-marker rows (scatter pids)
# ---------------------------------------------------------------------------

class TestUniqueConfidenceOnlyOnTriggerRow:
    """Non-trigger rows must NOT have trigger_target_confidence in notes."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_non_trigger_row_no_confidence_key(self, plugin):
        """Regular pid must not have trigger_target_confidence in notes (explicit absence).

        Per memory/feedback_invariant_with_fallback_hides_drift.md:
        explicit omission for non-trigger rows.
        """
        scatter_pid = "666"
        regular_pid = "1"
        stash = _make_single_feature_stash("NormalCollectionSpin")
        pid_rows = [
            {"payout_id": regular_pid, "hit_count": 100, "total_win": 500},
            {"payout_id": scatter_pid, "hit_count": 50, "total_win": 0},
        ]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))
        plugin.emit({}, summary, ctx)

        row_1 = next(r for r in pid_rows if str(r["payout_id"]) == regular_pid)
        notes_1 = row_1.get("notes", {})
        assert "trigger_target_confidence" not in notes_1, (
            f"Regular pid {regular_pid!r} must not have trigger_target_confidence. "
            f"notes: {notes_1}"
        )

        row_666 = next(r for r in pid_rows if str(r["payout_id"]) == scatter_pid)
        notes_666 = row_666.get("notes", {})
        assert notes_666.get("trigger_target_confidence") == "unique", (
            f"Scatter pid {scatter_pid!r} must have 'unique' confidence. "
            f"notes: {notes_666}"
        )
