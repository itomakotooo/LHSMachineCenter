"""M31 engine tests — spec/strips/weights load + evaluator correctness.

ARCHITECTURE §5.4 required test: test_<M>_engine.py
Verifies:
  - spec.json + reel_strips.json + weights.json load without error
  - Evaluator computes correct credits for known Tier A + Tier B rounds
  - Scatter detection fires at correct credit amounts
  - FreeSpin chain enqueued on scatter trigger (simulate_session returns sessions)
  - Plugin loads via build_plugin and satisfies FeaturePlugin protocol
  - Engine runs N spins without exception

Test data derived from session_artifacts/M31/01c_field_analysis.md §2 (paytable).
All credit assertions are cross-checked against rawdata observations:
  - Tier A single-payline verified on 12,998 rounds (01c §4, 0 errors)
  - Tier B verified on 60+ single-payline Tier B hits (01c §2)
"""
from __future__ import annotations

import sys
from pathlib import Path
from random import Random

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.engine.loader import load_engine
from slot_designer.core.engine.feature_protocol import FeaturePlugin
from slot_designer.machines.M31.plugins.feature import (
    M31FeaturePlugin,
    M31Session,
    _TIER_B_FIXED_CREDITS,
    _PAY_ID_SCATTER_WIN,
    _PAY_ID_SCATTER_TRIGGER,
    _SCATTER_WIN_CREDITS,
    _FREESPIN_COUNT,
    _REMARKS_TRIGGER,
    _REMARKS_FREE,
    build_plugin,
)

_M31_DIR = _ROOT / "slot_designer" / "machines" / "M31"
_SPEC_PATH = _M31_DIR / "spec.json"
_WEIGHTS_PATH = _M31_DIR / "weights" / "mode_1" / "weights.json"
_STRIPS_PATH = _M31_DIR / "reel_strips.json"

BET = 1000  # M31 production bet amount


# ─────────────────────────────────────────────────────────────────────
# Load-time smoke tests
# ─────────────────────────────────────────────────────────────────────

def test_load_engine_no_exception():
    """Spec + strips + weights load successfully. SpinEngine returned."""
    engine, spec = load_engine(_SPEC_PATH, _WEIGHTS_PATH, spin_type=43)
    assert engine is not None
    assert spec["machine"] == "M31"


def test_spec_machine_name():
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["machine"] == "M31"
    assert spec["mode"] == 1
    assert spec["schema_version"] == 2


def test_spec_has_5_paylines():
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    paylines = spec["grid"]["paylines"]
    assert len(paylines) == 5
    line_ids = [pl["line_id"] for pl in paylines]
    assert sorted(line_ids) == [1, 2, 3, 4, 5]


def test_spec_has_required_pay_ids():
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    pay_ids = {p["pay_id"] for p in spec["pays"]}
    required = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 666}
    assert required == pay_ids, f"Missing pay_ids: {required - pay_ids}"


def test_spec_symbols_complete():
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    expected_symbols = {
        "blank", "Scatter", "1bar", "2bar", "3bar", "bell", "High7",
        "Wild2x", "Wild3x", "Wild5x", "Wild10x",
    }
    assert set(spec["symbols"].keys()) == expected_symbols


def test_plugin_loads_via_build_plugin():
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    assert plugin is not None
    assert isinstance(plugin, M31FeaturePlugin)


def test_plugin_satisfies_feature_protocol():
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    assert isinstance(plugin, FeaturePlugin), (
        "M31 plugin must satisfy FeaturePlugin Protocol (runtime_checkable)"
    )


def test_engine_runs_100_spins_no_exception():
    """Engine runs 100 spins without raising."""
    engine, _ = load_engine(_SPEC_PATH, _WEIGHTS_PATH, spin_type=43)
    rng = Random(42)
    for _ in range(100):
        outcome, feature_rounds = engine.spin_session(rng)
    # If we reach here, no exception was raised.


# ─────────────────────────────────────────────────────────────────────
# Evaluator unit tests — Tier A
# ─────────────────────────────────────────────────────────────────────

def _get_evaluator():
    engine, _ = load_engine(_SPEC_PATH, _WEIGHTS_PATH, spin_type=43)
    return engine.evaluator


def _eval_payline(*syms):
    ev = _get_evaluator()
    return ev.evaluate_payline(list(syms))


def test_tier_a_1bar_no_wild():
    """pay_id=11 (3x 1bar, no wild) = 100 credits (0.1x bet)."""
    r = _eval_payline("1bar", "1bar", "1bar")
    assert r is not None
    assert r.pay_id == 11
    assert int(r.multiplier * BET) == 100


def test_tier_a_1bar_wild2x_wild10x():
    """pay_id=11 (1bar + Wild10x + Wild2x) = 100 * 10 * 2 = 2000 credits.
    Verified: 01c §4 example: '1bar + Wild10x + Wild2x on line 1 = 100 * (10*2) = 2000'.
    """
    r = _eval_payline("1bar", "Wild10x", "Wild2x")
    assert r is not None
    assert r.pay_id == 11
    assert int(r.multiplier * BET) == 2000


def test_tier_a_high7_no_wild():
    """pay_id=7 (3x High7, no wild) = 1600 credits (1.6x bet)."""
    r = _eval_payline("High7", "High7", "High7")
    assert r is not None
    assert r.pay_id == 7
    assert int(r.multiplier * BET) == 1600


def test_tier_a_bell_no_wild():
    """pay_id=8 (3x bell) = 1200 credits."""
    r = _eval_payline("bell", "bell", "bell")
    assert r is not None
    assert r.pay_id == 8
    assert int(r.multiplier * BET) == 1200


def test_tier_a_3bar_no_wild():
    """pay_id=9 (3x 3bar) = 600 credits."""
    r = _eval_payline("3bar", "3bar", "3bar")
    assert r is not None
    assert r.pay_id == 9
    assert int(r.multiplier * BET) == 600


def test_tier_a_2bar_with_wild2x():
    """pay_id=10 (2bar + 2bar + Wild2x) = 200 * 2 = 400 credits."""
    r = _eval_payline("2bar", "2bar", "Wild2x")
    assert r is not None
    assert r.pay_id == 10
    assert int(r.multiplier * BET) == 400


def test_tier_a_blank_is_no_pay():
    """blank anywhere on payline → no Tier A pay (filler kills the line)."""
    r = _eval_payline("1bar", "blank", "1bar")
    assert r is None


# ─────────────────────────────────────────────────────────────────────
# Evaluator unit tests — Tier B
# ─────────────────────────────────────────────────────────────────────

def test_tier_b_3x_wild5x():
    """pay_id=1 (3x Wild5x) = 30000 credits FIXED (not multiplied by wild_mult).

    Grid: only center row (payline 1) has Wild5x; top/bottom rows are blank.
    Paylines 2-5 are killed by blank — only payline 1 fires once.
    Expected: pid_to_win["1"] = 30000 (single payline, fixed Tier B).
    """
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    # grid[col][row] — row 0=top, row 1=center, row 2=bottom.
    # Only center row has Wild5x; top + bottom are blank → only payline 1 fires.
    grid = [["blank", "Wild5x", "blank"],
            ["blank", "Wild5x", "blank"],
            ["blank", "Wild5x", "blank"]]
    pid_to_win, _, _ = plugin._evaluate_grid(grid, BET)
    assert str(1) in pid_to_win, f"pay_id=1 missing from {pid_to_win}"
    assert pid_to_win[str(1)] == 30000, (
        f"pay_id=1 (3x Wild5x) should be 30000 fixed (single payline), "
        f"got {pid_to_win[str(1)]}"
    )


def test_tier_b_3x_wild3x():
    """pay_id=2 (3x Wild3x) = 15000 credits FIXED (single payline hit)."""
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    # Only center row (payline 1) fires — top/bottom blank kill paylines 2-5.
    grid = [["blank", "Wild3x", "blank"],
            ["blank", "Wild3x", "blank"],
            ["blank", "Wild3x", "blank"]]
    pid_to_win, _, _ = plugin._evaluate_grid(grid, BET)
    assert str(2) in pid_to_win, f"pay_id=2 missing from {pid_to_win}"
    assert pid_to_win.get(str(2)) == 15000, (
        f"pay_id=2 (3x Wild3x) should be 15000 fixed, got {pid_to_win.get(str(2))}"
    )


def test_tier_b_wild10x_with_wild2x():
    """pay_id=4 (Wild10x + Wild2x + Wild3x) = 10000 FIXED (NOT multiplied by wild_mult).

    Grid: only center row fires — top/bottom rows are blank.
    Payline: [Wild10x, Wild2x, Wild3x] → matches pure_wild_group alternative
    {"Wild10x":1, "Wild2x":1, "Wild3x":1} → pay_id=4, 10000 FIXED.
    """
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    # Center row: Wild10x, Wild2x, Wild3x per column — qualifies as pay_id=4.
    # Top/bottom rows: blank — kills paylines 2-5.
    grid = [["blank", "Wild10x", "blank"],
            ["blank", "Wild2x",  "blank"],
            ["blank", "Wild3x",  "blank"]]
    pid_to_win, _, _ = plugin._evaluate_grid(grid, BET)
    assert str(4) in pid_to_win, (
        f"pay_id=4 (Wild10x combo) missing from {pid_to_win}. "
        "Expected single payline to produce pay_id=4."
    )
    assert pid_to_win[str(4)] == 10000, (
        f"pay_id=4 should be 10000 fixed (NOT 10000 * wild_mult_product). "
        f"Got {pid_to_win[str(4)]}"
    )


def test_tier_b_wild2x_wild3x_mix():
    """pay_id=6 (Wild2x×2 + Wild3x×1, no Wild5x/Wild10x) = 600 FIXED.

    Grid: only center row fires with 2x Wild2x + 1x Wild3x.
    Top/bottom rows are blank → only payline 1 (center row) fires.
    """
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    # Center row: Wild2x, Wild2x, Wild3x — matches pay_id=6 alternative.
    # Top/bottom: blank — kills paylines 2-5.
    grid = [["blank", "Wild2x", "blank"],
            ["blank", "Wild2x", "blank"],
            ["blank", "Wild3x", "blank"]]
    pid_to_win, _, _ = plugin._evaluate_grid(grid, BET)
    assert str(6) in pid_to_win, (
        f"pay_id=6 (Wild2x×2 + Wild3x) missing from {pid_to_win}"
    )
    assert pid_to_win[str(6)] == 600, (
        f"pay_id=6 should be 600 fixed, got {pid_to_win[str(6)]}"
    )


def test_tier_b_not_multiplied_by_wild_mult():
    """Tier B is FIXED — Wild10x+Wild2x+Wild3x pays 10000, not 10000*60=600000.

    This is the key M31 invariant: pure wild pays are fixed regardless
    of which wild combination is on the payline.

    Uses single center-row grid to isolate exactly one payline hit (unconditional assert).
    wild_mult_product = 10 * 2 * 3 = 60; if multiplied, pay would be 10000*60=600000.
    """
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    # Center row: Wild10x, Wild2x, Wild3x — pay_id=4 (Tier B, fixed).
    # Top/bottom: blank — only payline 1 (center) fires.
    grid = [["blank", "Wild10x", "blank"],
            ["blank", "Wild2x",  "blank"],
            ["blank", "Wild3x",  "blank"]]
    pid_to_win, _, _ = plugin._evaluate_grid(grid, BET)
    assert str(4) in pid_to_win, (
        f"pay_id=4 (Wild10x combo) must fire on center-row payline, got {pid_to_win}"
    )
    assert pid_to_win[str(4)] != 600000, (
        "Tier B pay_id=4 must NOT be multiplied by wild_mult_product (10*2*3=60). "
        "Expected 10000 fixed, not 600000."
    )
    assert pid_to_win[str(4)] == 10000, (
        f"Tier B pay_id=4 FIXED = 10000, got {pid_to_win[str(4)]}"
    )


# ─────────────────────────────────────────────────────────────────────
# Scatter trigger tests
# ─────────────────────────────────────────────────────────────────────

def test_scatter_trigger_awards_5000_and_666():
    """3 Scatter anywhere triggers pay_id=12 (5000 credits) + pay_id=666 (0)."""
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    # Grid: Scatter at (0,0), (1,1), (2,2) — all different reels + rows
    grid = [
        ["Scatter", "blank", "blank"],
        ["blank", "Scatter", "blank"],
        ["blank", "blank", "Scatter"],
    ]
    pid_to_win, payout_by_payline, _ = plugin._evaluate_grid(grid, BET)
    assert str(12) in pid_to_win, f"pay_id=12 missing from {pid_to_win}"
    assert pid_to_win[str(12)] == 5000
    assert str(666) in pid_to_win
    assert pid_to_win[str(666)] == 0


def test_scatter_coexists_with_payline_pay():
    """Scatter pay can fire on same spin as a regular payline pay."""
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)
    # Grid: 1bar on center row + 3 Scatters on top row
    grid = [
        ["Scatter", "1bar", "blank"],
        ["Scatter", "1bar", "blank"],
        ["Scatter", "1bar", "blank"],
    ]
    pid_to_win, _, _ = plugin._evaluate_grid(grid, BET)
    assert str(11) in pid_to_win, "pay_id=11 (1bar center row) should fire"
    assert str(12) in pid_to_win, "pay_id=12 (scatter) should co-fire"
    assert pid_to_win[str(11)] == 100   # 3x 1bar, no wild
    assert pid_to_win[str(12)] == 5000


def test_freespin_chain_enqueued_on_trigger():
    """simulate_session() returns FREESPIN_COUNT=7 FreeSpin outcomes when triggered."""
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)

    # Create a mock outcome with 3 Scatter in grid
    from slot_designer.core.engine.spin import SpinOutcome
    mock_grid = [
        ["Scatter", "blank", "blank"],
        ["blank", "Scatter", "blank"],
        ["blank", "blank", "Scatter"],
    ]
    mock_outcome = SpinOutcome(
        grid=mock_grid,
        pay=None,
        cost_credits=1000,
        bet_amount=1000,
        spin_type=43,
        scatter_pays=[],
    )
    rng = Random(123)
    sessions = plugin.simulate_session(rng, outcome=mock_outcome)
    assert len(sessions) == 1
    session = sessions[0]
    assert session.base_has_scatter is True
    assert len(session.freespin_outcomes) == _FREESPIN_COUNT, (
        f"Expected {_FREESPIN_COUNT} FreeSpin outcomes, got {len(session.freespin_outcomes)}"
    )


def test_no_freespin_without_trigger():
    """simulate_session() returns session with empty freespin_outcomes when no scatter."""
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)

    from slot_designer.core.engine.spin import SpinOutcome
    mock_grid = [
        ["1bar", "blank", "blank"],
        ["1bar", "blank", "blank"],
        ["1bar", "blank", "blank"],
    ]
    mock_outcome = SpinOutcome(
        grid=mock_grid,
        pay=None,
        cost_credits=1000,
        bet_amount=1000,
        spin_type=43,
        scatter_pays=[],
    )
    rng = Random(42)
    sessions = plugin.simulate_session(rng, outcome=mock_outcome)
    assert len(sessions) == 1
    session = sessions[0]
    assert session.base_has_scatter is False
    assert len(session.freespin_outcomes) == 0


def test_freespin_remarks_is_freespin():
    """FreeSpin rounds (ST=44) have ReMarks='FreeSpin'."""
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)

    from slot_designer.core.engine.spin import SpinOutcome
    mock_grid = [
        ["Scatter", "blank", "blank"],
        ["blank", "Scatter", "blank"],
        ["blank", "blank", "Scatter"],
    ]
    mock_outcome = SpinOutcome(
        grid=mock_grid,
        pay=None,
        cost_credits=1000,
        bet_amount=1000,
        spin_type=43,
        scatter_pays=[],
    )
    rng = Random(77)
    sessions = plugin.simulate_session(rng, outcome=mock_outcome)
    session = sessions[0]

    base_round = {
        "WinCredits": 0, "PayoutByPayline": "", "PayoutIdToWinAmount": {},
        "StopSymbolsByCol": [], "RewardLastNode": [], "ReMarks": "",
        "SpinType": 43, "CostCredits": 1000,
    }
    extras = plugin.emit_extra_rounds(
        base_round, sessions,
        last_credits=1000000,
        spin_times=2000,
        rtp_id=1,
        bet_amount=1000,
    )
    assert len(extras) == _FREESPIN_COUNT
    for rd in extras:
        assert rd["SpinType"] == 44
        assert rd["ReMarks"] == _REMARKS_FREE
        assert rd["CostCredits"] == 0


def test_trigger_remarks_on_base_round():
    """emit_extra_rounds mutates base_round ReMarks to 'TriggerFreespin' on scatter trigger."""
    import json
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    plugin = build_plugin(spec, weights)

    from slot_designer.core.engine.spin import SpinOutcome
    mock_grid = [
        ["Scatter", "blank", "blank"],
        ["blank", "Scatter", "blank"],
        ["blank", "blank", "Scatter"],
    ]
    mock_outcome = SpinOutcome(
        grid=mock_grid, pay=None, cost_credits=1000,
        bet_amount=1000, spin_type=43, scatter_pays=[],
    )
    rng = Random(99)
    sessions = plugin.simulate_session(rng, outcome=mock_outcome)
    base_round = {
        "WinCredits": 0, "PayoutByPayline": "", "PayoutIdToWinAmount": {},
        "StopSymbolsByCol": [], "RewardLastNode": [], "ReMarks": "",
        "SpinType": 43, "CostCredits": 1000,
    }
    plugin.emit_extra_rounds(
        base_round, sessions,
        last_credits=1000000, spin_times=2000, rtp_id=1, bet_amount=1000,
    )
    assert base_round["ReMarks"] == _REMARKS_TRIGGER, (
        f"Trigger spin must have ReMarks='{_REMARKS_TRIGGER}', got {base_round['ReMarks']!r}"
    )


# ─────────────────────────────────────────────────────────────────────
# Full chunk emission smoke test
# ─────────────────────────────────────────────────────────────────────

def test_chunk_emission_smoke():
    """Run 100 spins through emit_session; validate schema field count."""
    import json
    from slot_designer.core.emitter.round import emit_session

    engine, spec = load_engine(_SPEC_PATH, _WEIGHTS_PATH, spin_type=43)
    plugin = engine.plugin
    rng = Random(0)

    # We need to verify the emitted schema has 17 fields matching production
    # (fingerprint 5d02773c069fc396, from session_artifacts/M31/01a §3).
    _EXPECTED_FIELDS = {
        "BetAmount", "CostCredits", "CurJackpotStoreWin", "IsLackCreditsSpin",
        "LastCredits", "PayLineGroupId", "PayoutByPayline", "PayoutGroupId",
        "PayoutIdToWinAmount", "RTPId", "ReMarks", "ReelSkin", "RewardLastNode",
        "SpinTimes", "SpinType", "StopSymbolsByCol", "WinCredits",
    }

    spin_count = 0
    schema_checked = False
    for _ in range(100):
        outcome, feature_rounds = engine.spin_session(rng)
        session_dicts = emit_session(
            outcome, feature_rounds,
            last_credits=1_000_000,
            spin_times=2000,
            rtp_id=1,
            plugin=plugin,
        )
        spin_count += 1
        # Check first round schema
        first_round = session_dicts[0]
        assert set(first_round.keys()) >= _EXPECTED_FIELDS, (
            f"Missing fields: {_EXPECTED_FIELDS - set(first_round.keys())}"
        )
        schema_checked = True
    assert schema_checked
    assert spin_count == 100
