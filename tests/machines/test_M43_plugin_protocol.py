"""M43 plugin satisfies the FeaturePlugin Protocol (ARCHITECTURE §3, §5.4).

Tests:
  1. ``isinstance(PLUGIN, FeaturePlugin)`` — runtime-checkable Protocol
     conformance.
  2. Three required methods present with the expected callable signature.
  3. ``trigger_pay_id is None`` (M43 is outcome-conditional, not
     scatter-pay-triggered).
  4. ``simulate_session(rng, outcome=...)`` returns a list and never
     raises for arbitrary outcomes.
  5. ``emit_extra_rounds`` returns rawdata-shaped dicts (ST=50/51 only).
  6. ``classify_round`` returns (str, int).
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from random import Random

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_M43_SPEC = _REPO_ROOT / "slot_designer" / "machines" / "M43" / "spec.json"
_M43_WEIGHTS_M1 = (
    _REPO_ROOT / "slot_designer" / "machines" / "M43" / "weights" / "mode_1" / "weights.json"
)


def _build_plugin():
    from slot_designer.machines.M43.plugins import build_plugin

    spec = json.loads(_M43_SPEC.read_text(encoding="utf-8"))
    weights = json.loads(_M43_WEIGHTS_M1.read_text(encoding="utf-8"))
    return build_plugin(spec, weights)


def test_build_plugin_returns_non_none():
    plugin = _build_plugin()
    assert plugin is not None


def test_plugin_satisfies_feature_plugin_protocol():
    from slot_designer.core.engine.feature_protocol import FeaturePlugin

    plugin = _build_plugin()
    assert isinstance(plugin, FeaturePlugin), (
        "M43 plugin must satisfy FeaturePlugin Protocol "
        f"(runtime-checkable). Got: {type(plugin).__mro__}"
    )


def test_plugin_has_required_methods():
    plugin = _build_plugin()
    for name in ("simulate_session", "emit_extra_rounds", "classify_round"):
        assert hasattr(plugin, name), f"plugin missing method {name}"
        assert callable(getattr(plugin, name)), f"{name} not callable"


def test_plugin_trigger_pay_id_is_none():
    """M43 fires via outcome-conditional trigger, not scatter pay."""
    plugin = _build_plugin()
    assert plugin.trigger_pay_id is None


def test_simulate_session_accepts_outcome_kwarg():
    """Protocol added 2026-05-14: outcome-conditional plugins receive
    a SpinOutcome kwarg from the engine."""
    plugin = _build_plugin()
    # Inspect signature includes 'outcome'
    sig = inspect.signature(plugin.simulate_session)
    assert "outcome" in sig.parameters


def test_simulate_session_returns_list_with_none_outcome():
    """When outcome is None (defensive call), plugin returns empty list."""
    plugin = _build_plugin()
    rng = Random(0)
    result = plugin.simulate_session(rng, outcome=None)
    assert isinstance(result, list)
    assert result == []


def test_simulate_session_returns_list_with_real_outcome():
    """When the plugin sees a SpinOutcome with a pay, occasional rounds
    fire (probabilistic). Run enough trials to see at least one fire."""
    from slot_designer.core.engine.spin import SpinOutcome
    from slot_designer.core.engine.rules import PayResult

    plugin = _build_plugin()
    rng = Random(2025)
    fake_pay = PayResult(pay_id=6, multiplier=10.0, positions=((0, 1), (1, 1), (2, 1)))
    fake_outcome = SpinOutcome(
        grid=[["1bar", "blank", "blank"]] * 3,
        pay=fake_pay,
        cost_credits=1000, bet_amount=1000, spin_type=1,
    )
    fired_at_least_once = False
    for _ in range(500):
        result = plugin.simulate_session(rng, outcome=fake_outcome)
        assert isinstance(result, list)
        if result:
            fired_at_least_once = True
            for fr in result:
                assert isinstance(fr, dict)
                assert fr.get("kind") in {"respin", "minigame"}
    assert fired_at_least_once, (
        "post-win plugin did not fire respin/minigame in 500 trials — "
        "either trigger probs are zero or RNG draw is broken"
    )


def test_emit_extra_rounds_produces_st50_st51_dicts():
    from slot_designer.core.engine.spin import SpinOutcome
    from slot_designer.core.engine.rules import PayResult

    plugin = _build_plugin()
    rng = Random(99)
    fake_pay = PayResult(pay_id=6, multiplier=10.0, positions=((0, 1), (1, 1), (2, 1)))
    fake_outcome = SpinOutcome(
        grid=[["1bar", "1bar", "1bar"], ["1bar", "1bar", "1bar"], ["1bar", "1bar", "1bar"]],
        pay=fake_pay,
        cost_credits=1000, bet_amount=1000, spin_type=1,
    )

    saw_st50 = False
    saw_st51 = False
    base_round = {"WinCredits": 10000, "SpinType": 1, "BetAmount": 1000}
    for _ in range(2000):
        fr = plugin.simulate_session(rng, outcome=fake_outcome)
        if not fr:
            continue
        extras = plugin.emit_extra_rounds(
            base_round, fr,
            last_credits=1_000_000,
            spin_times=10,
            rtp_id=1,
            bet_amount=1000,
        )
        for r in extras:
            st = r.get("SpinType")
            if st == 50:
                saw_st50 = True
                assert r.get("ReMarks") == "ReSpin"
                assert r.get("ReelSkin") == 6
            elif st == 51:
                saw_st51 = True
                rm = r.get("ReMarks", "")
                assert rm.startswith("MiniGame[")
            else:
                pytest.fail(f"unexpected SpinType in emit_extra_rounds: {st!r}")
        if saw_st50 and saw_st51:
            break

    assert saw_st50 and saw_st51, (
        f"expected both ST=50 and ST=51 in 2000 trials; got "
        f"st50={saw_st50}, st51={saw_st51}"
    )


def test_classify_round_returns_str_int_tuple():
    plugin = _build_plugin()
    name, win = plugin.classify_round(
        {"SpinType": 1, "WinCredits": 10000}, None,
    )
    assert isinstance(name, str)
    assert isinstance(win, int)
    assert name == "Normal"
    assert win == 10000

    name, win = plugin.classify_round(
        {"SpinType": 50, "WinCredits": 5000}, None,
    )
    assert name == "ReSpin"
    assert win == 5000

    name, win = plugin.classify_round(
        {"SpinType": 51, "WinCredits": 20000}, None,
    )
    assert name == "MiniGame"
    assert win == 20000
