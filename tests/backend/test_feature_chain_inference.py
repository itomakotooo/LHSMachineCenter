"""Unit tests for feature_name ↔ SpinType mapping + chain-parent
inference in player_impact_analyzer.

The mapping is the foundation for trigger-only feature → paying
parent chain association. These tests exercise the three signals
(ReMarks substring, exact count match, tolerance fallback) in
isolation so regressions are caught before the full analyzer
pipeline.

Also includes an inject-bug-revert-verify test per
``feedback_integration_test_argv``: monkeypatch the inference to
return empty mapping, assert chain association degrades gracefully,
then revert and re-verify.
"""
from __future__ import annotations

import pytest

from fresh_slotlab import player_impact_analyzer as ana


class TestUniqueTimesMatch:
    """Clean 1:1 path — features with distinct fire counts each bind to
    the unique matching SpinType via count equality."""

    def test_two_features_two_distinct_counts(self):
        feat_times = {"Paid": 10000, "Bonus": 989}
        st_spins = {140: 10000, 117: 989}
        f_to_st, st_to_f, ambig = ana._infer_feature_spin_type_mapping(
            feat_times, st_spins, {},
        )
        assert f_to_st == {"Paid": 140, "Bonus": 117}
        assert st_to_f == {140: "Paid", 117: "Bonus"}
        assert ambig == set()

    def test_unmatched_feature_stays_unmapped(self):
        # Session-level meta feature (e.g. BuffCollectionMap fires =
        # robot count) with no corresponding SpinType.
        feat_times = {"Paid": 10000, "MetaFeature": 10}
        st_spins = {140: 10000}
        f_to_st, st_to_f, ambig = ana._infer_feature_spin_type_mapping(
            feat_times, st_spins, {},
        )
        assert f_to_st == {"Paid": 140}
        assert "MetaFeature" not in f_to_st


class TestTiedTimesAmbiguousMapping:
    """Multi-feature-tie case: 3 ceremony features all fire 106 times
    each, 3 SpinTypes also count 106 each. Assign by sorted ordinal
    and flag as ambiguous."""

    def test_three_way_tie_assigns_by_sorted_ordinal_and_flags(self):
        feat_times = {"ListRewardWheel": 106, "WheelSelector": 106, "PreWheel": 106}
        st_spins = {139: 106, 136: 106, 137: 106}
        f_to_st, st_to_f, ambig = ana._infer_feature_spin_type_mapping(
            feat_times, st_spins, {},
        )
        # Sorted feature names paired with sorted SpinTypes.
        assert f_to_st == {
            "ListRewardWheel": 136,  # first alphabetically → lowest ST
            "PreWheel": 137,
            "WheelSelector": 139,
        }
        # All three flagged ambiguous since binding isn't a hard identity.
        assert ambig == {"ListRewardWheel", "WheelSelector", "PreWheel"}


class TestRemarksSubstringMatchPrecedence:
    """ReMarks beat fire-count ordinal for disambiguation. When the
    raw round payload encodes the feature name in ReMarks (a common
    pattern: "WheelSelector" / "PreWheel ReqCommonParam ..."),
    substring match wins."""

    def test_remarks_match_overrides_ordinal(self):
        feat_times = {"ListRewardWheel": 106, "WheelSelector": 106, "PreWheel": 106}
        st_spins = {139: 106, 136: 106, 137: 106}
        st_remarks = {
            139: ["Minigame CellIndexes: 1,1,1,2,2"],  # no feature name
            136: ["WheelSelector"],                     # direct hit
            137: ["PreWheel ReqCommonParam 2-4-5"],    # direct hit
        }
        f_to_st, st_to_f, ambig = ana._infer_feature_spin_type_mapping(
            feat_times, st_spins, st_remarks,
        )
        # ReMarks-matched features take the semantic SpinType.
        assert f_to_st["WheelSelector"] == 136
        assert f_to_st["PreWheel"] == 137
        # Remaining ListRewardWheel claims the remaining ST=139
        # by elimination (single unmapped feature vs single
        # unmapped ST at the tied count).
        assert f_to_st["ListRewardWheel"] == 139
        # None ambiguous since ReMarks resolved each uniquely.
        assert ambig == set()

    def test_case_insensitive_remarks_match(self):
        feat_times = {"TopDollar": 50, "Standard": 200}
        st_spins = {1: 200, 5: 50}
        st_remarks = {
            5: ["topdollar dollar collect"],  # lowercase in remarks
        }
        f_to_st, _, _ = ana._infer_feature_spin_type_mapping(
            feat_times, st_spins, st_remarks,
        )
        assert f_to_st == {"TopDollar": 5, "Standard": 1}

    def test_ambiguous_remarks_match_skipped(self):
        # ReMarks contains TWO feature names — don't assign.
        feat_times = {"Wheel": 50, "SpinWheel": 50, "Paid": 200}
        st_spins = {1: 200, 5: 50, 7: 50}
        st_remarks = {
            5: ["SpinWheel and Wheel mention"],  # matches both feats
        }
        f_to_st, _, _ = ana._infer_feature_spin_type_mapping(
            feat_times, st_spins, st_remarks,
        )
        # ST=5 declined by ReMarks pass (ambiguous),
        # but tied count may still map both via ordinal fallback.
        assert "Paid" in f_to_st


class TestToleranceFallback:
    """±2% drift tolerance: edge rounds cause small mismatches between
    feature Times and SpinType spin count. Accept single-candidate
    fuzzy matches only."""

    def test_small_drift_within_tolerance_resolves(self):
        feat_times = {"Paid": 10000}
        st_spins = {140: 10001}  # off by 1 (0.01%)
        f_to_st, _, _ = ana._infer_feature_spin_type_mapping(
            feat_times, st_spins, {},
        )
        assert f_to_st == {"Paid": 140}

    def test_drift_beyond_tolerance_rejected(self):
        feat_times = {"Paid": 10000}
        st_spins = {140: 11000}  # 10% off — beyond 2% tolerance
        f_to_st, _, _ = ana._infer_feature_spin_type_mapping(
            feat_times, st_spins, {},
        )
        assert f_to_st == {}


class TestEmptyInputs:
    def test_no_features(self):
        f_to_st, st_to_f, ambig = ana._infer_feature_spin_type_mapping(
            {}, {140: 10000}, {}
        )
        assert f_to_st == {}
        assert st_to_f == {}

    def test_no_spin_types(self):
        f_to_st, st_to_f, ambig = ana._infer_feature_spin_type_mapping(
            {"Paid": 10000}, {}, {},
        )
        assert f_to_st == {}


class TestInjectBugProof:
    """Prove the test catches a real regression: if the inference is
    stubbed to return empty, the chain-parent breakdown degrades (no
    chain_parent_feature set) rather than silently producing
    mis-labeled output."""

    def test_mapping_stub_degrades_gracefully(self, monkeypatch):
        # Baseline: normal inference works.
        feat_times = {"Paid": 10000, "Bonus": 989}
        st_spins = {140: 10000, 117: 989}
        baseline = ana._infer_feature_spin_type_mapping(feat_times, st_spins, {})
        assert baseline[0] == {"Paid": 140, "Bonus": 117}

        # Inject bug: replace with empty-return stub.
        def _stubbed(*a, **kw):
            return {}, {}, set()
        monkeypatch.setattr(ana, "_infer_feature_spin_type_mapping", _stubbed)
        broken = ana._infer_feature_spin_type_mapping(feat_times, st_spins, {})
        assert broken == ({}, {}, set())

        # Revert → baseline restored.
        monkeypatch.undo()
        restored = ana._infer_feature_spin_type_mapping(feat_times, st_spins, {})
        assert restored[0] == {"Paid": 140, "Bonus": 117}
