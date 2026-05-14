"""M31 plugin protocol test.

ARCHITECTURE §5.4 required test: test_<M>_plugin_protocol.py
Verifies:
  - Plugin can be imported via standard importlib path
  - Plugin satisfies isinstance(PLUGIN, FeaturePlugin) (runtime_checkable)
  - Plugin exposes required method signatures (simulate_session,
    emit_extra_rounds, classify_round)
  - trigger_pay_id is None (outcome-conditional mode)
  - build_plugin returns correct type
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_M31_DIR = _ROOT / "slot_designer" / "machines" / "M31"
_SPEC_PATH = _M31_DIR / "spec.json"
_WEIGHTS_PATH = _M31_DIR / "weights" / "mode_1" / "weights.json"

from slot_designer.core.engine.feature_protocol import FeaturePlugin


@pytest.fixture(scope="module")
def plugin():
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    from slot_designer.machines.M31.plugins.feature import build_plugin
    p = build_plugin(spec, weights)
    assert p is not None, "build_plugin returned None — spec has features, plugin must load"
    return p


# ─────────────────────────────────────────────────────────────────────
# importlib loading (ARCHITECTURE §3: plugin via importlib, not static import)
# ─────────────────────────────────────────────────────────────────────

def test_plugin_importlib_loadable():
    """Plugin can be imported via importlib.import_module path.

    ARCHITECTURE §3: loader.py uses importlib for plugin loading.
    This test verifies the import path is resolvable.
    """
    module = importlib.import_module("slot_designer.machines.M31.plugins")
    assert module is not None
    assert hasattr(module, "build_plugin"), (
        "Plugin module must expose build_plugin(spec_dict, weights_doc) factory"
    )


def test_build_plugin_callable():
    module = importlib.import_module("slot_designer.machines.M31.plugins")
    assert callable(module.build_plugin)


def test_build_plugin_returns_plugin_instance():
    """importlib build_plugin(spec, weights) returns a non-None plugin."""
    module = importlib.import_module("slot_designer.machines.M31.plugins")
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = module.build_plugin(spec, weights)
    assert plugin is not None


# ─────────────────────────────────────────────────────────────────────
# FeaturePlugin Protocol conformance
# ─────────────────────────────────────────────────────────────────────

def test_plugin_isinstance_feature_plugin(plugin):
    """Plugin satisfies FeaturePlugin runtime_checkable Protocol."""
    assert isinstance(plugin, FeaturePlugin), (
        f"M31 plugin {type(plugin).__name__} must satisfy "
        "isinstance(plugin, FeaturePlugin) — Protocol not met."
    )


def test_plugin_has_trigger_pay_id(plugin):
    """Plugin has trigger_pay_id attribute (may be None or int)."""
    assert hasattr(plugin, "trigger_pay_id"), (
        "Plugin must have trigger_pay_id attribute (None or int)"
    )
    # M31 uses outcome-conditional mode (trigger_pay_id=None)
    assert plugin.trigger_pay_id is None, (
        f"M31 uses outcome-conditional mode, trigger_pay_id should be None, "
        f"got {plugin.trigger_pay_id!r}"
    )


def test_plugin_has_simulate_session(plugin):
    """Plugin has simulate_session(rng, *, outcome=None) method."""
    assert hasattr(plugin, "simulate_session"), (
        "Plugin must have simulate_session method"
    )
    assert callable(plugin.simulate_session)


def test_plugin_has_emit_extra_rounds(plugin):
    """Plugin has emit_extra_rounds method."""
    assert hasattr(plugin, "emit_extra_rounds")
    assert callable(plugin.emit_extra_rounds)


def test_plugin_has_classify_round(plugin):
    """Plugin has classify_round method."""
    assert hasattr(plugin, "classify_round")
    assert callable(plugin.classify_round)


# ─────────────────────────────────────────────────────────────────────
# Method signature / return type checks
# ─────────────────────────────────────────────────────────────────────

def test_simulate_session_returns_list(plugin):
    """simulate_session returns a list (even with outcome=None)."""
    from random import Random
    from slot_designer.core.engine.spin import SpinOutcome
    mock_grid = [
        ["1bar", "blank", "blank"],
        ["1bar", "blank", "blank"],
        ["1bar", "blank", "blank"],
    ]
    outcome = SpinOutcome(
        grid=mock_grid, pay=None, cost_credits=1000,
        bet_amount=1000, spin_type=43, scatter_pays=[],
    )
    result = plugin.simulate_session(Random(0), outcome=outcome)
    assert isinstance(result, list)
    assert len(result) >= 1, "simulate_session must return non-empty list (M31 always needs base_grid)"


def test_emit_extra_rounds_returns_list(plugin):
    """emit_extra_rounds returns a list of dicts."""
    from random import Random
    from slot_designer.core.engine.spin import SpinOutcome
    mock_grid = [
        ["1bar", "blank", "blank"],
        ["1bar", "blank", "blank"],
        ["1bar", "blank", "blank"],
    ]
    outcome = SpinOutcome(
        grid=mock_grid, pay=None, cost_credits=1000,
        bet_amount=1000, spin_type=43, scatter_pays=[],
    )
    sessions = plugin.simulate_session(Random(1), outcome=outcome)
    base_round = {
        "WinCredits": 0, "PayoutByPayline": "", "PayoutIdToWinAmount": {},
        "StopSymbolsByCol": [], "RewardLastNode": [], "ReMarks": "",
        "SpinType": 43, "CostCredits": 1000,
    }
    result = plugin.emit_extra_rounds(
        base_round, sessions,
        last_credits=1000000, spin_times=2000, rtp_id=1, bet_amount=1000,
    )
    assert isinstance(result, list)


def test_classify_round_returns_tuple(plugin):
    """classify_round(round_dict, next) returns (str, int) tuple."""
    rd = {"SpinType": 43, "WinCredits": 1000}
    result = plugin.classify_round(rd, None)
    assert isinstance(result, tuple)
    assert len(result) == 2
    feature_name, eff_win = result
    assert isinstance(feature_name, str)
    assert isinstance(eff_win, int)


def test_classify_paid_spin(plugin):
    """ST=43 classified as 'NormalFreeSpin' with win = WinCredits."""
    rd = {"SpinType": 43, "WinCredits": 5000}
    feat_name, win = plugin.classify_round(rd, None)
    assert feat_name == "NormalFreeSpin"
    assert win == 5000


def test_classify_freespin(plugin):
    """ST=44 classified as 'FreeSpin' with win = WinCredits."""
    rd = {"SpinType": 44, "WinCredits": 12000}
    feat_name, win = plugin.classify_round(rd, None)
    assert feat_name == "FreeSpin"
    assert win == 12000


# ─────────────────────────────────────────────────────────────────────
# analysisResult bucket names match production 01a §3
# ─────────────────────────────────────────────────────────────────────

def test_feature_names_match_production():
    """Feature names match production analysisResult.FeatureWin keys.

    01a §3: FeatureWin inner keys = 'FreeSpin', 'NormalFreeSpin'.
    These are the exact strings the analyzer uses to route RTP attribution.
    """
    expected_feature_names = {"FreeSpin", "NormalFreeSpin"}
    # Check classify_round returns the right names
    st43_rd = {"SpinType": 43, "WinCredits": 0}
    st44_rd = {"SpinType": 44, "WinCredits": 0}
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    from slot_designer.machines.M31.plugins.feature import build_plugin
    p = build_plugin(spec, weights)
    name_43, _ = p.classify_round(st43_rd, None)
    name_44, _ = p.classify_round(st44_rd, None)
    returned_names = {name_43, name_44}
    assert returned_names == expected_feature_names, (
        f"Plugin returns feature names {returned_names!r}, expected "
        f"{expected_feature_names!r} (must match production analysisResult keys)"
    )
