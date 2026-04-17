"""Tests for the BCM-bonus-feature resolver — the logic that decides
which feature name in upstream_feature_tally pairs with
BuffCollectionMap for a given machine.

Strategy: config (configs/bcm_pairings.json) as primary; heuristic
(highest-win non-normal non-BCM feature) as fallback; None + warning
when neither resolves. See
`memory/feedback_prefer_complex_better.md` for why we do C over B.
"""
from __future__ import annotations

import pytest

from fresh_slotlab.player_impact_analyzer import (
    _resolve_bonus_feature,
    collect_feature_match_warning,
    PAID_NORMAL_FEATURES,
)


def _tally(entries: dict[str, float]) -> dict[str, dict]:
    """Build a minimal feature_tally shape: {feature: {pay_id: {win, times}}}."""
    return {
        f: {"1": {"win": w, "times": 10}} for f, w in entries.items()
    }


class TestResolveBonusFeatureConfig:
    def test_config_hit_wins_over_heuristic(self):
        tally = _tally({
            "NormalCollectionSpin": 5_000_000,
            "LockSymbolFreespin": 4_500_000,
            "OtherFeature": 5_000_000,  # heuristic would pick this (tied with Normal excluded)
            "BuffCollectionMap": 0,
        })
        config = {"M273": "LockSymbolFreespin"}
        feat, source = _resolve_bonus_feature("M273", tally, config)
        assert feat == "LockSymbolFreespin"
        assert source == "config"

    def test_config_hit_even_when_feature_has_zero_win(self):
        """If operator explicitly configured a pair, respect it even
        when the feature's win is currently zero (small cache, rare
        feature). Operator knows best."""
        tally = _tally({
            "NormalCollectionSpin": 5_000_000,
            "LockSymbolFreespin": 0,  # configured but no observations yet
            "BuffCollectionMap": 0,
        })
        config = {"M239": "LockSymbolFreespin"}
        feat, source = _resolve_bonus_feature("M239", tally, config)
        assert feat == "LockSymbolFreespin"
        assert source == "config"


class TestResolveBonusFeatureHeuristic:
    def test_heuristic_picks_highest_non_normal_non_bcm(self):
        tally = _tally({
            "NormalCollectionSpin": 5_000_000,   # excluded (paid normal)
            "NewFreespin": 4_830_000,            # top non-normal
            "SecondaryFeature": 1_000_000,
            "BuffCollectionMap": 0,              # excluded (BCM self)
        })
        feat, source = _resolve_bonus_feature("M272", tally, {})
        assert feat == "NewFreespin"
        assert source == "heuristic"

    def test_heuristic_ignores_paid_normal_even_if_highest(self):
        # NormalCollectionSpin has highest win but is paid-normal; skipped.
        tally = _tally({
            "NormalCollectionSpin": 10_000_000,
            "LockReSpin": 4_000_000,
            "BuffCollectionMap": 0,
        })
        feat, source = _resolve_bonus_feature("M227", tally, {})
        assert feat == "LockReSpin"
        assert source == "heuristic"

    def test_heuristic_ignores_bingo_variant_of_paid_normal(self):
        # BingoCollectionNormalSpin is also in PAID_NORMAL_FEATURES.
        tally = _tally({
            "BingoCollectionNormalSpin": 4_700_000,
            "NewFreespin": 3_000_000,
            "BuffCollectionMap": 0,
        })
        feat, source = _resolve_bonus_feature("M249", tally, {})
        assert feat == "NewFreespin"
        assert source == "heuristic"


class TestResolveBonusFeatureNone:
    def test_no_non_normal_candidate_returns_none(self):
        # Only paid-normal + BCM in tally → no candidate.
        tally = _tally({
            "NormalCollectionSpin": 5_000_000,
            "BuffCollectionMap": 0,
        })
        feat, source = _resolve_bonus_feature("MX", tally, {})
        assert feat is None
        assert source == "none"

    def test_all_candidates_zero_win_returns_none(self):
        tally = _tally({
            "NormalCollectionSpin": 5_000_000,
            "NewFreespin": 0,
            "WheelSelector": 0,
            "BuffCollectionMap": 0,
        })
        feat, source = _resolve_bonus_feature("MX", tally, {})
        assert feat is None
        assert source == "none"

    def test_empty_tally_returns_none(self):
        feat, source = _resolve_bonus_feature("MX", {}, {})
        assert feat is None
        assert source == "none"

    def test_none_tally_returns_none_no_crash(self):
        feat, source = _resolve_bonus_feature("MX", None, {})
        assert feat is None
        assert source == "none"


class TestFeatureMatchWarningWithResolver:
    """The warning block now reads the RESOLVED feature + source
    (not a hardcoded 'NewFreespin' check). Warning fires only when
    cycles observed AND no feature resolved (config miss + heuristic
    gave no candidate)."""

    def test_cycles_plus_resolved_feature_no_warning(self):
        out = collect_feature_match_warning(
            cycle_peaks=[1000, 1000, 1001],
            upstream_feature_tally=_tally({"NewFreespin": 4_830_000}),
            resolved_feature="NewFreespin",
            resolved_source="heuristic",
        )
        assert out["applicable"] is True
        assert out["bonus_feature"] == "NewFreespin"
        assert out["bonus_feature_source"] == "heuristic"
        assert out["warning"] is None

    def test_cycles_plus_config_resolved_no_warning(self):
        # Even if the resolved feature has zero observed win (config
        # override path), no warning — operator picked it explicitly.
        out = collect_feature_match_warning(
            cycle_peaks=[1000],
            upstream_feature_tally=_tally({"LockSymbolFreespin": 0}),
            resolved_feature="LockSymbolFreespin",
            resolved_source="config",
        )
        assert out["warning"] is None
        assert out["bonus_feature_source"] == "config"

    def test_cycles_no_resolved_feature_warns(self):
        out = collect_feature_match_warning(
            cycle_peaks=[1000],
            upstream_feature_tally=_tally({
                "NormalCollectionSpin": 5_000_000,
                "BuffCollectionMap": 0,
            }),
            resolved_feature=None,
            resolved_source="none",
        )
        assert out["applicable"] is True
        assert out["warning"] is not None
        assert "could not be resolved" in out["warning"].lower() or \
               "no bonus feature" in out["warning"].lower()

    def test_no_cycles_no_warning_regardless(self):
        out = collect_feature_match_warning(
            cycle_peaks=[],
            upstream_feature_tally={},
            resolved_feature=None,
            resolved_source="none",
        )
        assert out["applicable"] is False
        assert out["warning"] is None


class TestConfigLoader:
    def test_loader_handles_missing_file(self, tmp_path, monkeypatch):
        """Missing config file → empty dict, not crash."""
        from fresh_slotlab.player_impact_analyzer import _load_bcm_pairings
        monkeypatch.setattr(
            "fresh_slotlab.player_impact_analyzer._BCM_CONFIG_PATH",
            tmp_path / "nonexistent.json",
        )
        assert _load_bcm_pairings() == {}

    def test_loader_parses_canonical_config(self, tmp_path, monkeypatch):
        import json
        cfg = tmp_path / "bcm.json"
        cfg.write_text(json.dumps({
            "_generated_by": "test",
            "machines": {
                "M273": {"bonus_feature": "LockSymbolFreespin", "confidence": "high"},
                "M254": {"bonus_feature": "MultiBuffFreespin", "confidence": "high"},
            },
        }), encoding="utf-8")
        monkeypatch.setattr(
            "fresh_slotlab.player_impact_analyzer._BCM_CONFIG_PATH", cfg,
        )
        from fresh_slotlab.player_impact_analyzer import _load_bcm_pairings
        out = _load_bcm_pairings()
        assert out == {"M273": "LockSymbolFreespin", "M254": "MultiBuffFreespin"}

    def test_loader_skips_entries_without_bonus_feature(self, tmp_path, monkeypatch):
        import json
        cfg = tmp_path / "bcm.json"
        cfg.write_text(json.dumps({
            "machines": {
                "M1": {"bonus_feature": "Foo"},
                "M2": {"confidence": "low"},  # missing bonus_feature
                "M3": {"bonus_feature": None},  # explicit null
            },
        }), encoding="utf-8")
        monkeypatch.setattr(
            "fresh_slotlab.player_impact_analyzer._BCM_CONFIG_PATH", cfg,
        )
        from fresh_slotlab.player_impact_analyzer import _load_bcm_pairings
        out = _load_bcm_pairings()
        assert out == {"M1": "Foo"}


class TestCycleObservation:
    """Phase 3D: when collect mechanic is detected but no cycle reset
    was observed in the sample, surface an explicit 'need more data'
    warning rather than silently treating as not-a-collect-machine."""

    def test_import_builder(self):
        from fresh_slotlab.player_impact_analyzer import build_cycle_observation
        assert callable(build_cycle_observation)

    def test_no_mechanic_detected_no_warning(self):
        from fresh_slotlab.player_impact_analyzer import build_cycle_observation
        out = build_cycle_observation(
            collect_robots_seen=0,
            cycle_peaks=[],
            final_cc_values=[],
        )
        assert out["mechanic_detected"] is False
        assert out["reset_observed"] is False
        assert out["warning"] is None

    def test_mechanic_with_reset_observed_no_warning(self):
        from fresh_slotlab.player_impact_analyzer import build_cycle_observation
        out = build_cycle_observation(
            collect_robots_seen=10,
            cycle_peaks=[1000, 1000, 999],
            final_cc_values=[500, 700, 1000],
        )
        assert out["mechanic_detected"] is True
        assert out["reset_observed"] is True
        assert out["warning"] is None

    def test_mechanic_without_reset_warns_with_lower_bound(self):
        # M272-style scenario: 10 robots all ended at CC=1000, no reset.
        from fresh_slotlab.player_impact_analyzer import build_cycle_observation
        out = build_cycle_observation(
            collect_robots_seen=10,
            cycle_peaks=[],
            final_cc_values=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
        )
        assert out["mechanic_detected"] is True
        assert out["reset_observed"] is False
        assert out["cycle_len_lower_bound"] == 1000
        assert out["warning"] is not None
        assert "reset" in out["warning"].lower()
        assert "1000" in out["warning"]

    def test_lower_bound_is_max_of_finals(self):
        from fresh_slotlab.player_impact_analyzer import build_cycle_observation
        out = build_cycle_observation(
            collect_robots_seen=3,
            cycle_peaks=[],
            final_cc_values=[200, 800, 1200],
        )
        assert out["cycle_len_lower_bound"] == 1200
