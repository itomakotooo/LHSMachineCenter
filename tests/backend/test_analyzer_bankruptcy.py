"""Tests for the rawdata-replay bankruptcy simulation.

The simulator pools every robot's rounds in a chunk into one sequential
stream, then chops it into non-overlapping ``session_spins`` windows.
Each window replays from a fresh bankroll (multiplier × bet) at every
tier and contributes one "simulated paid-round session" to the
histogram. Pooling is valid because upstream RNG is stateless per spin
(ContinueAfterBankrupt=True + reset_each_spin=True at sampling time),
so rounds across robots are IID. Bonus rounds (CostCredits=0) don't
drain balance but their wins still land.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fresh_slotlab"))

import player_impact_analyzer as pia  # noqa: E402


def _robot(rounds):
    """Build a robot dict the analyzer's parse_rounds recognizes."""
    return {"roundResult": rounds}


def test_bankruptcy_sim_returns_empty_on_degenerate_inputs():
    # non-list resp
    assert pia.simulate_bankruptcy_from_response({}, 100, 500) == {}
    # zero bet
    assert pia.simulate_bankruptcy_from_response([_robot([])], 0, 500) == {}
    # zero session_spins
    assert pia.simulate_bankruptcy_from_response([_robot([])], 100, 0) == {}


def test_bankruptcy_sim_zero_windows_when_rounds_below_session_spins():
    """Not enough pooled rounds to form a single window → tier stays
    zeroed (no sessions synthesized). Operator sees it as "no samples"
    in the UI rather than a bogus half-window result."""
    rounds = [{"CostCredits": 1, "WinCredits": 0} for _ in range(100)]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=500,
        bankroll_mults=(100, 200, 500),
    )
    for m in (100, 200, 500):
        tier = out[m]
        assert tier["bankrupt"] == 0
        assert tier["survived"] == 0
        assert tier["spins_done_sum"] == 0
        assert sum(tier["bins"]) == 0


def test_bankruptcy_sim_survives_when_wins_match_bets_exactly():
    """Net-zero stream (every spin wins back its bet) survives every
    window at every tier — bankroll never decays below initial."""
    rounds = [
        {"CostCredits": 100, "WinCredits": 100}
        for _ in range(30)
    ]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=100, session_spins=10,
        bankroll_mults=(100, 200, 500),
    )
    for m in (100, 200, 500):
        tier = out[m]
        # 30 pooled rounds / 10 per window = 3 survived windows.
        assert tier["survived"] == 3
        assert tier["bankrupt"] == 0
        assert tier["spins_done_sum"] == 30
        assert all(c == 0 for c in tier["bins"])


def test_bankruptcy_sim_bankrupts_at_bankroll_depletion_point():
    """All-lose stream: each window's balance drops by exactly 1/spin.
    At session_spins=500, tier 100 dies at spin 100 (bin idx 2), tier
    200 at 200 (bin idx 4). Tier 500 reaches cap 500 (spins_done=500,
    survived). Each window independently repeats the same outcome
    because balance resets at every window boundary."""
    # Exactly 2 windows worth of rounds at session_spins=500.
    rounds = [
        {"CostCredits": 1, "WinCredits": 0}
        for _ in range(1000)
    ]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=500,
        bankroll_mults=(100, 200, 500),
    )
    # Tier 100: 2 bankrupt windows, both at bin idx 100//50 = 2
    assert out[100]["bankrupt"] == 2
    assert out[100]["survived"] == 0
    assert out[100]["bins"][2] == 2
    assert sum(out[100]["bins"]) == 2
    # Tier 200: 2 bankrupt at bin idx 4
    assert out[200]["bankrupt"] == 2
    assert out[200]["survived"] == 0
    assert out[200]["bins"][4] == 2
    # Tier 500: both windows hit cap → 2 survived
    assert out[500]["bankrupt"] == 0
    assert out[500]["survived"] == 2
    assert sum(out[500]["bins"]) == 0


def test_bankruptcy_sim_bonus_rounds_dont_drain_balance_but_do_add_wins():
    """Inside a window, bonus rounds (CostCredits=0) should not count
    as paid spins against bankroll, but their wins land on the balance
    — mirroring live play where bonus chains extend survival."""
    # One window of exactly 10 rounds:
    #   3 paid lose + 2 bonus win(+500) + 5 more paid lose
    # Starting balance 100 → after all 8 paid lose rounds: 92.
    # Bonus wins credit 1000 total → final balance 1092 (irrelevant).
    # spins_done = 10 = session_spins → survived.
    rounds = []
    for _ in range(3):
        rounds.append({"CostCredits": 1, "WinCredits": 0})
    for _ in range(2):
        rounds.append({"CostCredits": 0, "WinCredits": 500})
    for _ in range(5):
        rounds.append({"CostCredits": 1, "WinCredits": 0})
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=10,
        bankroll_mults=(100,),
    )
    tier = out[100]
    assert tier["survived"] == 1
    assert tier["bankrupt"] == 0
    assert tier["spins_done_sum"] == 10


def test_bankruptcy_sim_respects_session_spins_cap():
    """spins_done counts every consumed round (paid + bonus). A window
    of 10 mixed rounds with session_spins=10 hits the cap cleanly."""
    rounds = []
    for i in range(10):
        if i % 2 == 0:
            rounds.append({"CostCredits": 1, "WinCredits": 0})
        else:
            rounds.append({"CostCredits": 0, "WinCredits": 0})
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=10,
        bankroll_mults=(100,),
    )
    tier = out[100]
    # 5 paid losses drain balance 100 → 95. Cap reached.
    assert tier["survived"] == 1
    assert tier["bankrupt"] == 0
    assert tier["spins_done_sum"] == 10


def test_bankruptcy_sim_pools_rounds_across_robots():
    """Key property: 3 robots × 100 rounds = 300 pooled rounds. At
    session_spins=100 this yields 3 windows per tier, not 3 sessions
    of 100 rounds each (which would be the case if we kept robots
    isolated)."""
    rounds = [
        {"CostCredits": 10, "WinCredits": 0}
        for _ in range(100)
    ]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds), _robot(rounds), _robot(rounds)],
        bet=10, session_spins=100,
        bankroll_mults=(100,),
    )
    tier = out[100]
    # bankroll = 1000, drain 10/spin → dies exactly at spin 100.
    # spins_done=100 == session_spins → each window counts as SURVIVED
    # (cap check fires simultaneously with balance exhaustion).
    assert tier["survived"] == 3
    assert tier["bankrupt"] == 0
    assert tier["spins_done_sum"] == 300


def test_bankruptcy_sim_bankrupt_bin_classification():
    """With 3 pooled robots and deterministic bankruptcy at spin 40
    in each 50-spin window, all 6 windows (300 pooled / 50 = 6) end up
    in the same bin."""
    rounds = [
        {"CostCredits": 1, "WinCredits": 0}
        for _ in range(100)
    ]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds), _robot(rounds), _robot(rounds)],
        bet=1, session_spins=50,
        bankroll_mults=(40,),
    )
    tier = out[40]
    # bankroll=40, die at spin 40. Bin size = 50/10 = 5 → idx 40//5=8.
    assert tier["bankrupt"] == 6
    assert tier["survived"] == 0
    assert tier["bins"][8] == 6
    assert sum(tier["bins"]) == 6


def test_bankruptcy_sim_tier_isolation():
    """Same pooled stream, different tiers produce different outcomes.
    x500 tier survives the window where x100 bankrupts."""
    rounds = [
        {"CostCredits": 1, "WinCredits": 0}
        for _ in range(200)
    ]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=200,
        bankroll_mults=(100, 500),
    )
    # One window of 200 rounds per tier.
    # x100 bankroll=100, dies at spin 100 → bankrupt, bin idx 100//20=5
    assert out[100]["bankrupt"] == 1
    assert out[100]["survived"] == 0
    assert out[100]["bins"][5] == 1
    # x500 bankroll=500, losing 200 spins keeps balance positive at
    # spin 200 (balance=300); cap reached → survived.
    assert out[500]["bankrupt"] == 0
    assert out[500]["survived"] == 1
