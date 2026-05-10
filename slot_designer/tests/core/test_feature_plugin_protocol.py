"""Phase C target — FeaturePlugin Protocol contract.

ARCHITECTURE.md §3:

  Generic engine + emitter + driver call FeaturePlugin Protocol; concrete
  implementations live in machines/<M>/plugins/. Loaded via importlib at
  load_engine time.

  Plugin contract:
    .trigger_pay_id        : int | None
    .simulate_session(rng) : -> list[Any]   (plugin-private dataclass)
    .emit_extra_rounds(    : -> list[dict]  (rawdata round dicts)
        base_round, feature_rounds, *, last_credits, spin_times,
        rtp_id, bet_amount,
      )
    .classify_round(       : -> tuple[str, int]
        round_dict, next_round_dict,
      )

This test exercises the contract. Ordered red→green:
  1. Pre-Phase-C: feature_protocol.py doesn't exist → import RED.
  2. Implement Protocol → import GREEN, isinstance checks RED.
  3. Implement M15 plugin's build_plugin → isinstance + behavior GREEN.
  4. Wire plugin into load_engine → engine.plugin checks GREEN.
"""
from __future__ import annotations

import json
from pathlib import Path
from random import Random

import pytest


_SLOT_DESIGNER = Path(__file__).resolve().parents[2]
_M1_SPEC = _SLOT_DESIGNER / "machines" / "M1" / "spec.json"
_M1_WEIGHTS_M1 = _SLOT_DESIGNER / "machines" / "M1" / "weights" / "mode_1" / "weights.json"
_M15_SPEC = _SLOT_DESIGNER / "machines" / "M15" / "spec.json"
_M15_WEIGHTS_M1 = _SLOT_DESIGNER / "machines" / "M15" / "weights" / "mode_1" / "weights.json"


# ─────────────────────────────────────────────────────────────────────
# Protocol module + symbol
# ─────────────────────────────────────────────────────────────────────

def test_feature_protocol_module_exists():
    """``slot_designer.core.engine.feature_protocol`` is importable."""
    import slot_designer.core.engine.feature_protocol  # noqa: F401


def test_feature_protocol_class_exposed():
    """The ``FeaturePlugin`` Protocol class is exported from the module."""
    from slot_designer.core.engine.feature_protocol import FeaturePlugin  # noqa: F401


def test_feature_protocol_is_runtime_checkable():
    """``FeaturePlugin`` must be runtime-checkable so isinstance() works
    on plugin instances (used for guard checks in load_engine)."""
    from typing import _ProtocolMeta  # internal — but the right tool

    from slot_designer.core.engine.feature_protocol import FeaturePlugin

    # Runtime-checkable Protocols have _is_runtime_protocol attr set True
    assert getattr(FeaturePlugin, "_is_runtime_protocol", False), (
        "FeaturePlugin must be decorated with @runtime_checkable so "
        "isinstance(plugin, FeaturePlugin) works at load_engine time"
    )


# ─────────────────────────────────────────────────────────────────────
# M15 plugin module exposes build_plugin + satisfies Protocol
# ─────────────────────────────────────────────────────────────────────

def test_m15_plugin_module_exposes_build_plugin():
    """``machines.M15.plugins`` exposes a ``build_plugin(spec, weights_doc)``
    factory."""
    import slot_designer.machines.M15.plugins as m15_plugin

    assert hasattr(m15_plugin, "build_plugin"), (
        "machines/M15/plugins/__init__.py must expose `build_plugin` factory"
    )
    assert callable(m15_plugin.build_plugin)


def test_m15_build_plugin_returns_instance_satisfying_protocol():
    """build_plugin(spec, weights) returns a FeaturePlugin-conforming
    object — checked structurally via isinstance against the runtime-
    checkable Protocol."""
    from slot_designer.core.engine.feature_protocol import FeaturePlugin
    from slot_designer.machines.M15.plugins import build_plugin

    spec = json.loads(_M15_SPEC.read_text(encoding="utf-8"))
    weights = json.loads(_M15_WEIGHTS_M1.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    assert plugin is not None, (
        "M15 declares features in spec — build_plugin must return a plugin"
    )
    assert isinstance(plugin, FeaturePlugin), (
        f"M15 plugin instance does not satisfy FeaturePlugin protocol; "
        f"missing methods/attrs?  got: {type(plugin).__mro__}"
    )


def test_m15_plugin_carries_correct_trigger_pay_id():
    """Per M15 spec, feature triggers when topdollar lands on R3 →
    pay_id 666. Plugin must surface that as ``trigger_pay_id``."""
    from slot_designer.machines.M15.plugins import build_plugin

    spec = json.loads(_M15_SPEC.read_text(encoding="utf-8"))
    weights = json.loads(_M15_WEIGHTS_M1.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    assert plugin.trigger_pay_id == 666, (
        f"M15 trigger_pay_id should be 666, got {plugin.trigger_pay_id}"
    )


def test_m15_plugin_simulate_session_returns_list_with_round_attrs():
    """plugin.simulate_session(rng) returns a list (FeatureRound-like
    objects). Each list entry should have at least ``r_value`` and
    ``accepted`` attributes (plugin-private dataclass shape, but generic
    code never inspects beyond passing the list through)."""
    from slot_designer.machines.M15.plugins import build_plugin

    spec = json.loads(_M15_SPEC.read_text(encoding="utf-8"))
    weights = json.loads(_M15_WEIGHTS_M1.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)

    rng = Random(0)
    rounds = plugin.simulate_session(rng)
    assert isinstance(rounds, list)
    assert len(rounds) >= 1
    # Every M15 session ends on an accepted round
    last = rounds[-1]
    assert hasattr(last, "r_value")
    assert hasattr(last, "accepted")
    assert last.accepted is True, "last feature round must be accepted"


def test_m15_plugin_emit_extra_rounds_produces_st14_st15():
    """plugin.emit_extra_rounds() should produce M15-shaped sub-rounds
    (ST=14 reveals + ST=15 end marker). The hardcoded ST numbers stay
    INSIDE the plugin (not in core/).
    """
    from slot_designer.machines.M15.plugins import build_plugin

    spec = json.loads(_M15_SPEC.read_text(encoding="utf-8"))
    weights = json.loads(_M15_WEIGHTS_M1.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)

    rng = Random(0)
    feature_rounds = plugin.simulate_session(rng)
    base_round = {"WinCredits": 0, "SpinType": 1}  # placeholder

    extras = plugin.emit_extra_rounds(
        base_round,
        feature_rounds,
        last_credits=1_000_000,
        spin_times=10,
        rtp_id=1,
        bet_amount=1000,
    )
    assert isinstance(extras, list)
    assert len(extras) == len(feature_rounds) + 1, (
        "M15 emits one ST=14 per feature round + one ST=15 end marker"
    )
    spin_types = [r.get("SpinType") for r in extras]
    assert spin_types[:-1] == [14] * len(feature_rounds)
    assert spin_types[-1] == 15


def test_m15_plugin_classify_round_handles_st14_st15_normal():
    """plugin.classify_round() returns (feature_name, effective_win)
    matching the M15 production schema."""
    from slot_designer.machines.M15.plugins import build_plugin

    spec = json.loads(_M15_SPEC.read_text(encoding="utf-8"))
    weights = json.loads(_M15_WEIGHTS_M1.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)

    # ST=14 followed by another ST=14 → rejected → "TopDollarSelector"
    name, win = plugin.classify_round(
        {"SpinType": 14, "WinCredits": 50},
        {"SpinType": 14, "WinCredits": 60},
    )
    assert name == "TopDollarSelector"
    assert win == 0

    # ST=14 NOT followed by another ST=14 (= last accepted) → "TopDollar"
    name, win = plugin.classify_round(
        {"SpinType": 14, "WinCredits": 200},
        {"SpinType": 15},
    )
    assert name == "TopDollar"
    assert win == 200

    # ST=15 → end marker → "TopDollarSelector"
    name, win = plugin.classify_round(
        {"SpinType": 15, "WinAmount": 200},
        None,
    )
    assert name == "TopDollarSelector"
    assert win == 0

    # ST=1 paid spin → "Normal"
    name, win = plugin.classify_round(
        {"SpinType": 1, "WinCredits": 5},
        None,
    )
    assert name == "Normal"
    assert win == 5


# ─────────────────────────────────────────────────────────────────────
# Base machines (no plugin)
# ─────────────────────────────────────────────────────────────────────

def test_m1_plugin_module_either_absent_or_returns_none():
    """M1 has no feature → either machines/M1/plugins/ doesn't exist OR
    its build_plugin returns None for any spec."""
    plugin_dir = _SLOT_DESIGNER / "machines" / "M1" / "plugins"
    if not plugin_dir.is_dir():
        return  # acceptable: base machine, no plugins/
    # If the dir exists, build_plugin must explicitly return None.
    import importlib

    module = importlib.import_module("slot_designer.machines.M1.plugins")
    builder = getattr(module, "build_plugin", None)
    if builder is None:
        return  # also acceptable
    spec = json.loads(_M1_SPEC.read_text(encoding="utf-8"))
    weights = json.loads(_M1_WEIGHTS_M1.read_text(encoding="utf-8"))
    plugin = builder(spec, weights)
    assert plugin is None, "M1 has no feature; build_plugin should return None"


# ─────────────────────────────────────────────────────────────────────
# load_engine wiring
# ─────────────────────────────────────────────────────────────────────

def test_load_engine_for_m15_carries_plugin():
    """``load_engine`` for M15 must populate ``engine.plugin`` with a
    FeaturePlugin instance (M15 declares features in spec)."""
    from slot_designer.core.engine.feature_protocol import FeaturePlugin
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M15_SPEC, _M15_WEIGHTS_M1)
    assert engine.plugin is not None, (
        "M15 declares features; load_engine must wire a plugin instance"
    )
    assert isinstance(engine.plugin, FeaturePlugin)
    assert engine.plugin.trigger_pay_id == 666


def test_load_engine_for_m1_has_no_plugin():
    """``load_engine`` for M1 (base, no features in spec) must leave
    ``engine.plugin = None``."""
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M1_SPEC, _M1_WEIGHTS_M1)
    assert engine.plugin is None, (
        "M1 has no feature; load_engine must NOT wire a plugin"
    )


def test_engine_spin_session_routes_through_plugin_when_triggered():
    """When a paid spin's scatter_pays contains plugin.trigger_pay_id,
    engine.spin_session calls plugin.simulate_session and returns the
    result as ``feature_rounds``.

    Use a controlled engine where every spin's evaluator forces a
    scatter pay matching trigger_pay_id, so we deterministically observe
    feature_rounds non-empty.
    """
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M15_SPEC, _M15_WEIGHTS_M1)
    # We can't deterministically force a trigger without rigging RNG /
    # weights; instead, repeat spin_session until we see one trigger.
    rng = Random(42)
    triggered_observed = False
    for _ in range(2000):
        outcome, feature_rounds = engine.spin_session(rng)
        if feature_rounds:
            triggered_observed = True
            assert len(feature_rounds) >= 1
            break
    assert triggered_observed, (
        "2000 spins on M15 mode 1 should produce ≥1 feature trigger "
        "(rate ~1.14% means ~22 expected). spin_session is not wiring "
        "feature_rounds through the plugin."
    )


def test_engine_spin_session_skips_plugin_when_no_trigger():
    """For machines without a plugin, spin_session returns (outcome, [])
    every time."""
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M1_SPEC, _M1_WEIGHTS_M1)
    rng = Random(0)
    for _ in range(100):
        outcome, feature_rounds = engine.spin_session(rng)
        assert feature_rounds == []
