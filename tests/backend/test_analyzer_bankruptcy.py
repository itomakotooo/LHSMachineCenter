"""Tests for the rawdata-replay bankruptcy simulation + percentile /
fastest-bankruptcy helpers.

Architecture: per-chunk simulator stores a fine-resolution histogram
(100 bins over ``[0, session_spins)``) plus a ``survived`` counter
keyed by bankroll multiplier. Finalize derives per-tier:
  * median_spins_completed (= P50 over all sessions)
  * fastest_bankruptcy_spins (midpoint of first non-empty fine bin)
  * percentiles map (P10..P90) whose denominator is ALL sessions
    (bankrupt + survived); past the bankrupt mass they pin to
    session_spins so the UI reads the transition as the survival
    rate's complement.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fresh_slotlab"))

import player_impact_analyzer as pia  # noqa: E402


FINE_N = pia._BANKRUPTCY_FINE_BIN_COUNT


def _robot(rounds):
    return {"roundResult": rounds}


# ---------- simulate_bankruptcy_from_response (per-chunk) -------------


def test_bankruptcy_sim_degenerate_inputs_return_empty():
    assert pia.simulate_bankruptcy_from_response({}, 100, 500) == {}
    assert pia.simulate_bankruptcy_from_response([_robot([])], 0, 500) == {}
    assert pia.simulate_bankruptcy_from_response([_robot([])], 100, 0) == {}


def test_bankruptcy_sim_zero_windows_when_rounds_below_session_spins():
    rounds = [{"CostCredits": 1, "WinCredits": 0} for _ in range(100)]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=500,
        bankroll_mults=(100,),
    )
    tier = out[100]
    assert tier["bankrupt"] == 0
    assert tier["survived"] == 0
    assert sum(tier["fine_bins"]) == 0


def test_bankruptcy_sim_pools_across_robots_with_net_zero_survival():
    rounds = [{"CostCredits": 100, "WinCredits": 100} for _ in range(30)]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=100, session_spins=10,
        bankroll_mults=(100,),
    )
    tier = out[100]
    assert tier["survived"] == 3
    assert tier["bankrupt"] == 0
    assert sum(tier["fine_bins"]) == 0


def test_bankruptcy_sim_records_deterministic_bankruptcy_in_fine_bin():
    """bet=1, 2 windows of 1000 rounds each all lose → every window
    dies at spin 100 (bankroll 100). Fine bin size 1000/100=10, so
    spins_done=100 → idx=10 (counted in 2 windows)."""
    rounds = [{"CostCredits": 1, "WinCredits": 0} for _ in range(2000)]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=1000,
        bankroll_mults=(100,),
    )
    tier = out[100]
    assert tier["bankrupt"] == 2
    assert tier["survived"] == 0
    assert tier["fine_bins"][10] == 2


def test_bankruptcy_sim_bonus_rounds_do_not_drain_balance():
    rounds = (
        [{"CostCredits": 1, "WinCredits": 0}] * 3
        + [{"CostCredits": 0, "WinCredits": 500}] * 2
        + [{"CostCredits": 1, "WinCredits": 0}] * 5
    )
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=10,
        bankroll_mults=(100,),
    )
    tier = out[100]
    assert tier["survived"] == 1
    assert tier["bankrupt"] == 0


# ---------- fastest_bankruptcy_spins_from_fine_hist ---------------------


def test_fastest_bankruptcy_none_when_no_bankruptcies():
    fine = [0] * FINE_N
    assert pia.fastest_bankruptcy_spins_from_fine_hist(fine, 1000) is None


def test_fastest_bankruptcy_returns_first_non_empty_bin_midpoint():
    """Earliest bankruptcy sits in fine bin 3 at session_spins=1000
    (bin size 10) → midpoint = 3.5 * 10 = 35."""
    fine = [0] * FINE_N
    fine[3] = 5
    fine[20] = 100  # later bin; should NOT be the fastest
    assert pia.fastest_bankruptcy_spins_from_fine_hist(fine, 1000) == 35


def test_fastest_bankruptcy_handles_degenerate_inputs():
    assert pia.fastest_bankruptcy_spins_from_fine_hist([], 1000) is None
    assert pia.fastest_bankruptcy_spins_from_fine_hist([0] * FINE_N, 0) is None


# ---------- compute_bankruptcy_percentiles ------------------------------


def test_percentiles_all_survive_pins_every_decile_to_session_spins():
    fine = [0] * FINE_N
    out = pia.compute_bankruptcy_percentiles(fine, survived=200, session_spins=1000)
    for p in (10, 20, 30, 40, 50, 60, 70, 80, 90):
        assert out[p] == 1000, f"P{p} should pin to session_spins: {out}"


def test_percentiles_all_bankrupt_uniform_distribution():
    """1000 bankrupt sessions uniformly across 10 fine bins (100 each).
    At P50, cumulative = 500 → hit in fine bin 4 (cum after bin 4 = 500).
    Fine bin 4 midpoint = 4.5 * 10 = 45. Reasonable for a 1000-spin
    horizon / 100 fine bins."""
    fine = [0] * FINE_N
    # Put 100 counts in each of the first 10 fine bins.
    for i in range(10):
        fine[i] = 100
    out = pia.compute_bankruptcy_percentiles(fine, survived=0, session_spins=1000)
    # P10: cumulative target = 100 → bin 0 (cum=100 hits at bin 0).
    assert out[10] == 5  # midpoint of bin 0 at size 10
    # P50: cumulative target = 500 → bin 4 (cum after bin 4 = 500).
    assert 40 <= out[50] <= 50
    # P90: cumulative target = 900 → bin 8 (cum after bin 8 = 900).
    assert 80 <= out[90] <= 90


def test_percentiles_transition_to_survivor_at_bankruptcy_complement():
    """80% bankrupt / 20% survived tier: P10–P70 stay in bankrupt range,
    P90 lands in survivor bucket = session_spins."""
    fine = [0] * FINE_N
    # 800 bankrupts spread across fine bins 0-9 (80 per bin).
    for i in range(10):
        fine[i] = 80
    out = pia.compute_bankruptcy_percentiles(
        fine, survived=200, session_spins=1000,
    )
    # P80 = cum target 800 → last bin carrying bankrupts (bin 9, cum=800).
    assert out[80] <= 100
    # P90 = cum target 900 → past all bankrupts (total bankrupt=800),
    # lands in survivor group → pins to session_spins.
    assert out[90] == 1000


def test_percentiles_monotonic_non_decreasing():
    """Arbitrary distribution — percentile values should never decrease
    as P increases."""
    fine = [0] * FINE_N
    fine[5] = 50
    fine[20] = 200
    fine[50] = 100
    out = pia.compute_bankruptcy_percentiles(
        fine, survived=10, session_spins=1000,
    )
    values = [out[p] for p in (10, 20, 30, 40, 50, 60, 70, 80, 90)]
    for i in range(1, len(values)):
        assert values[i] >= values[i - 1], f"monotonicity broken at P{i*10}: {values}"


# ---------- median_spins_from_fine_hist (P50 convenience) ---------------


def test_median_equals_p50():
    fine = [0] * FINE_N
    for i in range(10):
        fine[i] = 100
    pct = pia.compute_bankruptcy_percentiles(
        fine, survived=0, session_spins=1000, percentiles=(50,),
    )
    assert pia.median_spins_from_fine_hist(fine, 0, 1000) == pct[50]


def test_median_all_survivors_returns_session_spins():
    fine = [0] * FINE_N
    assert pia.median_spins_from_fine_hist(fine, survived=100, session_spins=1000) == 1000


def test_median_zero_total_returns_zero():
    assert pia.median_spins_from_fine_hist([0] * FINE_N, 0, 1000) == 0
