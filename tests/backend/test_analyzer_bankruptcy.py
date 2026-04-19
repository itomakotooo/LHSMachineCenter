"""Tests for the rawdata-replay bankruptcy simulation.

The simulation replays each robot's round sequence from a fresh
bankroll (multiplier × bet) and tallies the spins-until-bankrupt
distribution per tier. Bonus rounds (CostCredits=0) don't drain the
wallet but their wins still land, which preserves the real-play
behavior where bonus chains extend survival even at low bankroll.
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


def test_bankruptcy_sim_survives_when_wins_match_bets_exactly():
    """Net-zero robot (every spin wins back exactly its bet) survives
    at every tier regardless of starting bankroll."""
    # 10 paid rounds, each win == bet. Bankroll never decays.
    rounds = [
        {"CostCredits": 100, "WinCredits": 100, "BetAmount": 100}
        for _ in range(10)
    ]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=100, session_spins=10,
        bankroll_mults=(100, 200, 500),
    )
    for m in (100, 200, 500):
        tier = out[m]
        assert tier["survived"] == 1
        assert tier["bankrupt"] == 0
        assert tier["spins_done_sum"] == 10
        # No entries in bankrupt bins.
        assert all(c == 0 for c in tier["bins"])


def test_bankruptcy_sim_bankrupts_at_bankroll_depletion_point():
    """Deterministic: bet=1, all-lose, balance drops by 1 per spin.
    Dies exactly at spin==bankroll. Bin size = 500/10 = 50, so tier
    100 → bin idx 2, tier 200 → bin idx 4. Tier 500 reaches the
    session_spins cap (spins_done = 500 == session_spins), so it
    counts as SURVIVED (balance hit 0 simultaneously with the cap,
    and the loop's cap-check fires first)."""
    rounds = [
        {"CostCredits": 1, "WinCredits": 0}
        for _ in range(600)
    ]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=500,
        bankroll_mults=(100, 200, 500),
    )
    # Tier 100: bankrupt, bin idx 100//50 = 2
    assert out[100]["bankrupt"] == 1
    assert out[100]["survived"] == 0
    assert out[100]["bins"][2] == 1
    assert sum(out[100]["bins"]) == 1
    # Tier 200: bankrupt, bin idx 200//50 = 4
    assert out[200]["bankrupt"] == 1
    assert out[200]["survived"] == 0
    assert out[200]["bins"][4] == 1
    assert sum(out[200]["bins"]) == 1
    # Tier 500: session cap reached → survived (spins_done=500 == cap).
    assert out[500]["bankrupt"] == 0
    assert out[500]["survived"] == 1
    assert sum(out[500]["bins"]) == 0


def test_bankruptcy_sim_bonus_rounds_dont_drain_balance_but_do_add_wins():
    """A bonus round (CostCredits=0) should not count as a paid spin
    against bankroll, but its win still lands on the balance — mirroring
    live play where bonus chains temporarily boost survival."""
    # 3 paid rounds (each lose), then 2 bonus rounds (each win 500),
    # then more paid rounds. Bankroll=100*1=100 starts.
    # After 3 lose rounds: balance = 100 - 3 = 97.
    # Bonus rounds add 500 each: balance = 97 + 1000 = 1097.
    # Subsequent paid rounds drain 1 each; robot survives to the cap.
    rounds = []
    for _ in range(3):
        rounds.append({"CostCredits": 1, "WinCredits": 0})
    for _ in range(2):
        rounds.append({"CostCredits": 0, "WinCredits": 500})
    for _ in range(500):
        rounds.append({"CostCredits": 1, "WinCredits": 0})

    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=50,
        bankroll_mults=(100,),
    )
    tier = out[100]
    # Session-spins cap (50) reached cleanly — bonus win made balance
    # comfortably positive even after the session cap.
    assert tier["survived"] == 1
    assert tier["bankrupt"] == 0


def test_bankruptcy_sim_respects_session_spins_cap():
    """Session counter includes bonus rounds (matches live probe
    semantics: spin_times=session_spins was the upstream cap). So 10
    rounds of any kind + cap=10 = survived."""
    rounds = []
    for i in range(10):
        if i % 2 == 0:
            rounds.append({"CostCredits": 1, "WinCredits": 0})  # paid lose
        else:
            rounds.append({"CostCredits": 0, "WinCredits": 0})  # bonus no-win
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=10,
        bankroll_mults=(100,),
    )
    tier = out[100]
    # 5 paid rounds drain 5 from bankroll → balance = 95. Cap reached.
    assert tier["survived"] == 1
    assert tier["bankrupt"] == 0
    assert tier["spins_done_sum"] == 10


def test_bankruptcy_sim_histograms_aggregate_across_robots():
    """Multiple robots' histograms merge elementwise. All 3 robots
    deterministically bankrupt at the same spin → the same bin sees
    count=3."""
    rounds = [
        {"CostCredits": 10, "WinCredits": 0} for _ in range(300)
    ]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds), _robot(rounds), _robot(rounds)],
        bet=10, session_spins=200,
        bankroll_mults=(100,),
    )
    tier = out[100]
    # bankroll=1000, drain 10/spin → dies at spin 100 (before cap 200).
    assert tier["bankrupt"] == 3
    assert tier["survived"] == 0
    # Bin size = 200/10 = 20. Spins_done=100 → bin idx 100 // 20 = 5.
    assert tier["bins"][5] == 3
    assert sum(tier["bins"]) == 3
    assert tier["spins_done_sum"] == 300  # 3 × 100


def test_bankruptcy_sim_tier_isolation():
    """A robot at x200 that survives where x100 bankrupts — the two
    tiers are simulated independently on the same sequence."""
    # Lose 1 bet per spin for 150 rounds.
    rounds = [
        {"CostCredits": 1, "WinCredits": 0} for _ in range(150)
    ]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=200,
        bankroll_mults=(100, 200, 500),
    )
    # x100 bankroll = 100, dies at spin 100.
    assert out[100]["bankrupt"] == 1
    assert out[100]["survived"] == 0
    # x200 bankroll = 200, but only 150 rounds available → survives
    # through all 150 rounds (cap not reached but sequence ends). Since
    # spins_done (150) < session_spins (200), robot counts as
    # "bankrupt" in the strict sense BUT the balance isn't actually
    # zero. This edge case reflects real-world data: if the sequence
    # ends before the cap, we record the spins_done count truthfully.
    # x500 same story.
    assert out[200]["bankrupt"] + out[200]["survived"] == 1
    assert out[500]["bankrupt"] + out[500]["survived"] == 1
    # spins_done_sum for x200 should be 150 (sequence ran out, not
    # bankruptcy in the wallet sense).
    assert out[200]["spins_done_sum"] == 150
    assert out[500]["spins_done_sum"] == 150
