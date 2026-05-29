"""R1 Phase 2 d2 — missing scatter_feature_chain_counts stash → RuntimeError.

Invariants asserted (AC#4)
--------------------------
1. When 2+ scatter features exist and scatter_feature_chain_counts is ABSENT
   from the stash (not present at all), emit() must raise RuntimeError.
2. The RuntimeError message must reference "scatter_feature_chain_counts"
   (schema drift identification per feedback_capture_drift.md).
3. The RuntimeError must NOT be silently swallowed — no alphabetical fallback
   may be produced (per feedback_no_silent_swallow.md).
4. The C2 existing feature_errors handler (except Exception in PIA emit loop)
   catches this RuntimeError and writes to feature_errors. This is tested
   directly via the RuntimeError assertion + note about C2 path.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug d2-missing-stash: change emit() to silently fall back to sorted(features)[0]
  when scatter_feature_chain_counts is missing, instead of raising RuntimeError.
  In bonus_chain_dynamics.py emit(), find:
    if "scatter_feature_chain_counts" not in stash:
        raise RuntimeError(...)
  Change to:
    if "scatter_feature_chain_counts" not in stash:
        # silent fallback (WRONG — violates feedback_no_silent_swallow.md)
        trigger_target = sorted(scatter_feature_names)[0]
        trigger_target_confidence = "fallback_no_chain_data"
  RED: test_missing_chain_counts_raises_runtime_error fails — RuntimeError
       is NOT raised; a result is silently returned instead.
  Revert (restore the raise) → GREEN.

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md
  (must raise, not silently fall back — silent swallow hides schema drift)
- memory/feedback_capture_drift.md
  (RuntimeError with descriptive message identifies schema drift)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
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


def _raw_inputs(features: list[str] | None = None) -> dict:
    """Phase 2b RAW dict-build inputs the plugin re-sources to BUILD the dict.

    Phase 2b carve (test_2b_*): the plugin now BUILDS the bonus_chain_dynamics
    dict from these 9 raw accumulator inputs (it no longer reads a pre-built
    dict).  These d2 tests assert the trigger_target INFERENCE (step 3, which
    raises on missing scatter_feature_chain_counts) — that runs AFTER the
    dict-build (step 2), so the raw inputs just need to be present + valid for
    the build to succeed and the step-3 raise to be the one under test.  When
    ``features`` is given, all_chains_by_feature carries one chain per feature so
    the build's by_feature filter passes; scatter_feature_chain_counts is
    deliberately NOT included here (the caller controls its presence).
    """
    feats = features or []
    all_chains = {
        f: {"lengths": [5], "max_ratios": [1], "total_rounds": 5, "retrigger_rounds": 0}
        for f in feats
    }
    lengths = [5] * len(feats)
    return {
        "bonus_chain_lengths": lengths,
        "bonus_chain_max_ratios": [1] * len(feats),
        "bonus_total_rounds_global": 5 * len(feats),
        "bonus_retrigger_rounds_global": 0,
        "bonus_chain_retrigger_events": [0] * len(feats),
        "bonus_extra_ratio_counts": {},
        "bonus_depth_ratio_count": {},
        "bonus_depth_ratio_sum": {},
        "all_chains_by_feature": all_chains,
    }


def _make_stash_missing_chain_counts(features: list[str]) -> dict:
    """Build a stash with 2+ scatter features but NO scatter_feature_chain_counts key.

    This simulates the case where the PIA stash extension at pia:4862 (R1 d2)
    is not deployed — old PIA code would write a stash without the key.
    """
    return {
        **_raw_inputs(features),  # Phase 2b: plugin builds the dict from raw inputs
        "scatter_feature_names": sorted(features),
        # NOTE: scatter_feature_chain_counts is intentionally ABSENT here
    }


# ---------------------------------------------------------------------------
# T1: RuntimeError when chain_counts missing for 2+ features
# ---------------------------------------------------------------------------

class TestMissingChainCountsRaisesRuntimeError:
    """2+ features + missing scatter_feature_chain_counts → RuntimeError."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_missing_chain_counts_raises_runtime_error(self, plugin):
        """emit() must raise RuntimeError when scatter_feature_chain_counts absent.

        INJECT-BUG: replace the raise RuntimeError(...) with a silent fallback.
        RED: this test fails — RuntimeError is NOT raised.
        Revert → GREEN.

        Per memory/feedback_no_silent_swallow.md: silent swallow of schema drift
        means operators never see the stash-extension deployment gap.
        Per memory/feedback_capture_drift.md: error must reference the missing key.
        """
        scatter_pid = "666"
        features = ["FeatureA", "FeatureB"]
        stash = _make_stash_missing_chain_counts(features)
        pid_rows = [{"payout_id": scatter_pid, "hit_count": 50, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))

        with pytest.raises(RuntimeError, match="scatter_feature_chain_counts"):
            plugin.emit({}, summary, ctx)

    def test_error_message_references_feature_count(self, plugin):
        """RuntimeError message must mention the number of scatter features."""
        scatter_pid = "666"
        features = ["FeatureA", "FeatureB"]
        stash = _make_stash_missing_chain_counts(features)
        pid_rows = [{"payout_id": scatter_pid, "hit_count": 50, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))

        with pytest.raises(RuntimeError) as exc_info:
            plugin.emit({}, summary, ctx)

        # Message must be informative enough for operators to diagnose
        msg = str(exc_info.value)
        assert "scatter_feature_chain_counts" in msg, (
            f"RuntimeError message must reference 'scatter_feature_chain_counts'. "
            f"Got: {msg!r}"
        )

    def test_three_features_also_raises(self, plugin):
        """RuntimeError applies for 3+ features too — any len>=2 case."""
        scatter_pid = "666"
        features = ["Alpha", "Beta", "Gamma"]
        stash = _make_stash_missing_chain_counts(features)
        pid_rows = [{"payout_id": scatter_pid, "hit_count": 30, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))

        with pytest.raises(RuntimeError, match="scatter_feature_chain_counts"):
            plugin.emit({}, summary, ctx)

    def test_no_result_emitted_when_error_raised(self, plugin):
        """When RuntimeError is raised, no trigger_target must be silently written.

        This confirms no partial state leaks from the exception path.
        """
        scatter_pid = "666"
        features = ["FeatureA", "FeatureB"]
        stash = _make_stash_missing_chain_counts(features)
        pid_rows = [{"payout_id": scatter_pid, "hit_count": 50, "total_win": 0}]
        original_row_copy = dict(pid_rows[0])
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))

        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, ctx)

        # RuntimeError fires in step 3 (trigger_target inference) BEFORE step 4
        # (payout_ids_top20 augmentation). Therefore no "notes" key is written to
        # the row at all — notes must be None, not partially populated.
        row_after = pid_rows[0]
        notes = row_after.get("notes")
        assert notes is None, (
            f"notes must not be written to the row when RuntimeError fires in step 3 "
            f"(before step 4 augmentation). Got notes: {notes!r}. "
            f"If notes is non-None, step 4 ran before the error — dispatch order is wrong."
        )


# ---------------------------------------------------------------------------
# T2: 1-feature case does NOT raise (len-first dispatch)
# ---------------------------------------------------------------------------

class TestSingleFeatureNoRaise:
    """len==1 case uses 'unique' branch — never needs chain_counts; no RuntimeError.

    This verifies the len-first dispatch (coordinator CR-1): the check for
    scatter_feature_chain_counts is only reached when len >= 2.
    """

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_single_feature_no_chain_counts_does_not_raise(self, plugin):
        """1-feature stash without chain_counts must not raise RuntimeError.

        This is the CR-1 len-first dispatch guarantee: n==1 → "unique" branch →
        chain_counts never consulted. If dispatch were stash-first (checking
        chain_counts before len), this would raise — proving the dispatch order
        matters.

        INJECT-BUG (stash-first anti-pattern): change dispatch to check
        chain_counts BEFORE len:
          if "scatter_feature_chain_counts" not in stash:
              raise RuntimeError(...)  # fires for len==1 too
          if n == 1:
              return features[0], "unique"
        RED: this test raises RuntimeError unexpectedly.
        Revert (restore len-first: if n == 1: → no chain_counts check) → GREEN.
        """
        scatter_pid = "666"
        stash = {
            **_raw_inputs(["OnlyFeature"]),  # Phase 2b: plugin builds the dict from raw inputs
            "scatter_feature_names": ["OnlyFeature"],
            # scatter_feature_chain_counts intentionally ABSENT
        }
        pid_rows = [{"payout_id": scatter_pid, "hit_count": 50, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                # Phase 2b: NOT pre-populated — plugin builds it from raw stash
                "payout_ids_top20": pid_rows,
            },
        }
        ctx = _make_ctx(frozenset({scatter_pid}))

        # Must NOT raise — len==1 hits the "unique" branch before chain_counts check
        plugin.emit({}, summary, ctx)

        row_666 = pid_rows[0]
        assert row_666["notes"]["trigger_target_confidence"] == "unique", (
            f"Single-feature stash must produce 'unique' confidence even without "
            f"chain_counts. Got: {row_666['notes'].get('trigger_target_confidence')!r}"
        )
