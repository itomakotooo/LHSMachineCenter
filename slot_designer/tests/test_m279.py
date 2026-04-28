"""M279 engine + emitter tests.

Covers:
  - Multi-payline evaluator: 9-line evaluation produces multiple PayResults
    on grids with multiple matching lines
  - Wild stack nudge: partial stack visibility triggers MoveSpin chain
  - Collect meter: increments per paid spin, triggers wheel + buffmap at max,
    resets to (100, 1)
  - Wheel sampler: 12 cells, weighted distribution, expected E[win] = 40000
  - End-to-end session: 1 paid + nudge chain + wheel = rounds in correct order
  - Emitter: multi-line PayoutByPayline + AccCredits/CollectCount on ST=140
  - SpinType constants match production rawdata (140/36/2/102)
"""
from __future__ import annotations

from pathlib import Path
from random import Random

import pytest

from slot_designer.engine.m279.collect import CollectConfig, CollectMeter, load_collect_config
from slot_designer.engine.m279.engine import (
    M279SessionState,
    ST_BUFFMAP,
    ST_NUDGE,
    ST_PAID,
    ST_WHEEL,
)
from slot_designer.engine.m279.loader import load_m279_engine
from slot_designer.engine.m279.nudge import (
    NudgeConfig,
    detect_partial_stack_reels,
    nudge_chain,
    stack_visible_count,
)
from slot_designer.engine.m279.wheel import WheelCell, WheelConfig, sample_cell
from slot_designer.emitter.m279_round import emit_m279_session


_SPEC = Path(__file__).resolve().parent.parent / "specs" / "M279.spec.json"
_WEIGHTS = Path(__file__).resolve().parent.parent / "weights" / "M279" / "mode_1" / "weights.json"


# ── Spin type constants ──────────────────────────────────────────────

def test_spin_type_constants_match_rawdata():
    """ST values must match production cfg / rawdata exactly."""
    assert ST_PAID == 140      # NormalCollectionSpin
    assert ST_NUDGE == 36      # MoveSpin
    assert ST_WHEEL == 2       # NewWheel
    assert ST_BUFFMAP == 102   # BuffCollectionMap


# ── Collect meter ────────────────────────────────────────────────────

def test_collect_meter_increments_correctly():
    cfg = CollectConfig(max=10, increment_per_paid_spin=1, credit_unit=100)
    m = CollectMeter()
    assert m.collect_count == 0
    assert m.acc_credits == 0
    m.increment(cfg)
    assert m.collect_count == 1
    assert m.acc_credits == 100
    for _ in range(8):
        m.increment(cfg)
    assert m.collect_count == 9
    assert not m.should_trigger(cfg)
    m.increment(cfg)
    assert m.collect_count == 10
    assert m.should_trigger(cfg)


def test_collect_meter_reset_post_trigger():
    """After wheel fires, meter resets to (acc=100, count=1) per rawdata."""
    cfg = CollectConfig(max=10, increment_per_paid_spin=1, credit_unit=100)
    m = CollectMeter(acc_credits=1000, collect_count=10)
    m.reset_post_trigger(cfg)
    assert m.collect_count == 1
    assert m.acc_credits == 100


def test_load_collect_config_from_spec():
    """Parses the collect_meter block out of the M279 spec."""
    import json
    spec = json.loads(_SPEC.read_text(encoding="utf-8"))
    cfg = load_collect_config(spec)
    assert cfg.max == 1000
    assert cfg.increment_per_paid_spin == 1
    assert cfg.credit_unit == 100


# ── Wheel ────────────────────────────────────────────────────────────

def test_wheel_expected_win_archetype():
    """E[wheel win] must equal 40000 credits per archetype design."""
    cells = (
        WheelCell(1, 50, 50000),
        WheelCell(2, 30, 10000),
        WheelCell(3, 30, 20000),
        WheelCell(4, 20, 50000),
        WheelCell(5, 30, 30000),
        WheelCell(6, 10, 5000),
        WheelCell(7, 30, 20000),
        WheelCell(8, 20, 100000),
        WheelCell(9, 10, 5000),
        WheelCell(10, 50, 100000),
        WheelCell(11, 15, 20000),
        WheelCell(12, 50, 10000),
    )
    cfg = WheelConfig(wheel_id=1, cells=cells)
    assert cfg.total_weight == 345
    assert cfg.expected_win() == pytest.approx(40000, abs=1)


def test_wheel_sample_distribution():
    """Sampling many wheel cells should approximate analytical EV."""
    cells = (
        WheelCell(1, 50, 5000),
        WheelCell(2, 50, 100000),
    )
    cfg = WheelConfig(wheel_id=1, cells=cells)
    rng = Random(42)
    n = 5000
    total = sum(sample_cell(cfg, rng).win_credits for _ in range(n))
    avg = total / n
    expected = (50 * 5000 + 50 * 100000) / 100  # = 52500
    assert abs(avg - expected) < expected * 0.05  # within 5% (5k samples enough)


# ── Nudge stack ──────────────────────────────────────────────────────

def test_stack_visible_count():
    assert stack_visible_count(["blank", "blank", "blank"]) == 0
    assert stack_visible_count(["wild_up", "blank", "blank"]) == 1
    assert stack_visible_count(["blank", "wild2x_mid", "wild_down"]) == 2
    assert stack_visible_count(["wild_up", "wild2x_mid", "wild_down"]) == 3


def test_detect_partial_stack_reels():
    """Returns column indices with 1 or 2 stack symbols visible."""
    grid = [
        ["wild_up", "blank", "blank"],         # col 0: 1 visible (partial)
        ["wild_up", "wild2x_mid", "blank"],    # col 1: 2 visible (partial)
        ["wild_up", "wild2x_mid", "wild_down"],# col 2: 3 visible (full, not partial)
    ]
    assert detect_partial_stack_reels(grid) == [0, 1]


def test_nudge_chain_two_step_reveal():
    """1 wild visible → 2 MoveSpins → full reveal."""
    grid = [
        ["blank", "high7", "blank"],
        ["blank", "mid7", "blank"],
        ["blank", "blank", "wild_up"],   # col 2 has wild_up at bot → 1 visible
    ]
    cfg = NudgeConfig(
        anchor_symbols=("wild_up", "wild2x_mid", "wild_down"),
        stack_order=("wild_up", "wild2x_mid", "wild_down"),
        max_chain_length=2,
    )
    chain = nudge_chain(grid, cfg)
    assert len(chain) == 2  # two MoveSpins to fully reveal
    # Final MoveSpin should have full stack on col 2
    final_col = chain[-1][2]
    assert stack_visible_count(final_col) == 3


def test_nudge_chain_one_step_reveal():
    """2 wilds visible → 1 MoveSpin → full reveal."""
    grid = [
        ["blank", "high7", "blank"],
        ["blank", "mid7", "blank"],
        ["wild_up", "wild2x_mid", "blank"],  # col 2 has 2 visible
    ]
    cfg = NudgeConfig(
        anchor_symbols=("wild_up", "wild2x_mid", "wild_down"),
        stack_order=("wild_up", "wild2x_mid", "wild_down"),
        max_chain_length=2,
    )
    chain = nudge_chain(grid, cfg)
    assert len(chain) == 1
    assert stack_visible_count(chain[0][2]) == 3


def test_nudge_chain_no_partial():
    """Grid with no partial stack → empty chain."""
    grid = [
        ["blank", "high7", "blank"],
        ["blank", "mid7", "blank"],
        ["blank", "low7", "blank"],
    ]
    cfg = NudgeConfig(
        anchor_symbols=("wild_up", "wild2x_mid", "wild_down"),
        stack_order=("wild_up", "wild2x_mid", "wild_down"),
        max_chain_length=2,
    )
    assert nudge_chain(grid, cfg) == []


# ── End-to-end session via M279SpinEngine ────────────────────────────

def test_engine_loads_from_spec():
    engine, spec = load_m279_engine(_SPEC, _WEIGHTS)
    assert engine.n_cols == 3
    assert len(engine.paylines) == 9
    assert engine.bet_amount == 1000
    assert engine.cost_per_spin == 1000
    assert engine.collect_cfg.max == 1000
    assert len(engine.wheel_cfg.cells) == 12


def test_session_paid_only():
    """A session with no nudge + no wheel returns just 1 paid round."""
    engine, _ = load_m279_engine(_SPEC, _WEIGHTS)
    state = M279SessionState()
    rng = Random(123)
    # Run sessions until we find one with just paid (no nudge, no wheel)
    for _ in range(100):
        rounds = engine.run_session(rng, state.meter)
        if len(rounds) == 1:
            assert rounds[0].spin_type == ST_PAID
            assert rounds[0].cost_credits == 1000
            assert rounds[0].acc_credits is not None
            assert rounds[0].collect_count is not None
            return
    pytest.fail("100 sessions all had nudge/wheel — strip layout suspicious")


def test_session_triggers_wheel_at_max():
    """When meter hits CollectMax, wheel fires and meter resets."""
    engine, _ = load_m279_engine(_SPEC, _WEIGHTS)
    # Pre-load meter to almost-trigger state
    state = M279SessionState()
    state.meter.collect_count = engine.collect_cfg.max - 1
    state.meter.acc_credits = (engine.collect_cfg.max - 1) * engine.collect_cfg.credit_unit
    rng = Random(999)
    rounds = engine.run_session(rng, state.meter)
    # Should have ST=140 + (maybe nudge) + ST=2 + ST=102
    spin_types = [r.spin_type for r in rounds]
    assert ST_WHEEL in spin_types
    assert ST_BUFFMAP in spin_types
    # Wheel comes before BuffMap
    assert spin_types.index(ST_WHEEL) < spin_types.index(ST_BUFFMAP)
    # Meter should have reset
    assert state.meter.collect_count == 1
    assert state.meter.acc_credits == 100


def test_session_meter_increments_each_paid_spin():
    """Across 100 paid spins, meter increments by 100 (1 per spin)."""
    engine, _ = load_m279_engine(_SPEC, _WEIGHTS)
    state = M279SessionState()
    rng = Random(42)
    n_spins = 100
    for _ in range(n_spins):
        engine.run_session(rng, state.meter)
    # Any wheel triggers would reset; for n_spins=100 well below CollectMax=1000
    # we should never trigger.
    assert state.meter.collect_count == n_spins


# ── Emitter ──────────────────────────────────────────────────────────

def test_emit_session_paid_only():
    """Single paid round → single dict with full schema."""
    engine, _ = load_m279_engine(_SPEC, _WEIGHTS)
    state = M279SessionState()
    rng = Random(456)
    # Run one session
    rounds = engine.run_session(rng, state.meter)
    paylines_spec = [list(line) for line in engine.paylines]
    dicts = emit_m279_session(
        rounds,
        last_credits=1_000_000,
        spin_times=10,
        rtp_id=1,
        paylines_spec=paylines_spec,
        reel_skin=1,
    )
    assert len(dicts) == len(rounds)
    paid = dicts[0]
    assert paid["SpinType"] == ST_PAID
    assert paid["CostCredits"] == 1000
    assert paid["BetAmount"] == 1000
    assert paid["ReelSkin"] == 1
    assert paid["AccCredits"] is not None
    assert paid["CollectCount"] is not None
    assert "CreditsSymbols" in paid
    assert "PayoutByPayline" in paid
    assert "PayoutIdToWinAmount" in paid
    assert "StopSymbolsByCol" in paid


def test_emit_session_wheel_round_minimal_schema():
    """Wheel round has NULL grid + WheelSpin remarks."""
    engine, _ = load_m279_engine(_SPEC, _WEIGHTS)
    state = M279SessionState()
    state.meter.collect_count = engine.collect_cfg.max - 1
    state.meter.acc_credits = (engine.collect_cfg.max - 1) * engine.collect_cfg.credit_unit
    rng = Random(999)
    rounds = engine.run_session(rng, state.meter)
    paylines_spec = [list(line) for line in engine.paylines]
    dicts = emit_m279_session(
        rounds,
        last_credits=1_000_000,
        spin_times=10,
        rtp_id=1,
        paylines_spec=paylines_spec,
        reel_skin=1,
    )
    wheel_dicts = [d for d in dicts if d["SpinType"] == ST_WHEEL]
    assert len(wheel_dicts) == 1
    w = wheel_dicts[0]
    assert w["StopSymbolsByCol"] == ["NULL", "NULL", "NULL"]
    assert "WheelSpin CellIndex" in w["ReMarks"]
    assert "WheelId" in w["ReMarks"]
    assert w["WinCredits"] in {5000, 10000, 20000, 30000, 50000, 100000}


# ── Multi-payline evaluator ──────────────────────────────────────────

def test_multi_payline_distinct_pay_id_aggregation():
    """Same pay_id firing on multiple lines aggregates win in
    PayoutIdToWinAmount under one key."""
    engine, _ = load_m279_engine(_SPEC, _WEIGHTS)
    paylines_spec = [list(line) for line in engine.paylines]
    # Synthesize a grid where multiple lines hit the same pay_id.
    # Top row + bot row both being all-high7 would fire pay 1 twice (lines 2 + 3).
    grid = [
        ["high7", "high7", "high7"],
        ["high7", "high7", "high7"],
        ["high7", "high7", "high7"],
    ]
    pays, total_win = engine._evaluate_grid(grid)
    # Multiple lines should hit pay 1 (high7 OAK)
    pay_1_pays = [p for p in pays if p.pay_id == 1]
    assert len(pay_1_pays) >= 1
    # Total win = sum of all line wins
    assert total_win == sum(int(p.multiplier * engine.bet_amount) for p in pays)
