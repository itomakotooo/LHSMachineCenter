"""Tests for the rawdata-replay bankruptcy simulation + adaptive
histogram + median survival helpers.

Architecture: the per-chunk simulator stores a fine-resolution
histogram (100 bins of session_spins/100 spins each) keyed by bankroll
multiplier. At finalize, the analyzer pools the histograms across all
tiers to derive shared equal-mass bin edges, rebases each tier's fine
histogram to those edges for display, and computes median survival
per tier from the fine histogram + survivor count.
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


def test_bankruptcy_sim_pools_rounds_and_survives_on_net_zero():
    """30 paid rounds with win==bet → 3 survived windows at session=10."""
    rounds = [{"CostCredits": 100, "WinCredits": 100} for _ in range(30)]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=100, session_spins=10,
        bankroll_mults=(100,),
    )
    tier = out[100]
    assert tier["survived"] == 3
    assert tier["bankrupt"] == 0
    assert sum(tier["fine_bins"]) == 0


def test_bankruptcy_sim_bankruptcy_lands_in_expected_fine_bin():
    """bet=1 all-lose, 2 windows of session_spins=1000 → every window
    dies at spin 100 (bankroll 100). Fine bin size = 1000/100 = 10,
    so spins_done=100 → idx=10. Two windows → fine_bins[10] = 2.

    (We pick session_spins=1000 and 2 windows to keep arithmetic clean
    while still exercising the pool → chop path.)"""
    rounds = [{"CostCredits": 1, "WinCredits": 0} for _ in range(2000)]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=1000,
        bankroll_mults=(100,),
    )
    tier = out[100]
    assert tier["bankrupt"] == 2
    assert tier["survived"] == 0
    # Fine bin size = 1000/100 = 10 spins; spins_done=100 → idx 10
    assert tier["fine_bins"][10] == 2
    assert sum(tier["fine_bins"]) == 2


def test_bankruptcy_sim_bonus_rounds_do_not_drain_balance():
    """3 paid lose + 2 bonus win + 5 paid lose in a 10-spin window."""
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


# ---------- compute_bankruptcy_adaptive_edges ---------------------------


def test_adaptive_edges_linear_fallback_when_pooled_is_empty():
    """No bankruptcy mass anywhere → uniform linear edges over [0, S]."""
    edges = pia.compute_bankruptcy_adaptive_edges(
        [0] * FINE_N, session_spins=1000, target_bins=8,
    )
    assert len(edges) == 9
    assert edges[0] == 0
    assert edges[-1] == 1000
    # Linear spacing: edges[i] = i * 1000 / 8 = i * 125
    for i, e in enumerate(edges):
        assert abs(e - i * 125) <= 1


def test_adaptive_edges_equal_mass_on_uniform_distribution():
    """Pooled histogram is flat → adaptive edges should be ~linear."""
    pooled = [10] * FINE_N
    edges = pia.compute_bankruptcy_adaptive_edges(
        pooled, session_spins=1000, target_bins=8,
    )
    assert len(edges) == 9
    assert edges[0] == 0
    assert edges[-1] == 1000
    # Strictly monotonic.
    for i in range(1, len(edges)):
        assert edges[i] > edges[i - 1]
    # Each bin should carry ~1/8 of the 1000 total mass (=125).
    # With uniform spacing of the fine bins, edges should be near
    # [0, 125, 250, ..., 1000].
    for i, expected in enumerate([0, 125, 250, 375, 500, 625, 750, 875, 1000]):
        assert abs(edges[i] - expected) <= 20  # loose tolerance for rounding


def test_adaptive_edges_concentrate_where_mass_lives():
    """Left-skewed pooled distribution (mass in first 10% of fine bins)
    → adaptive edges crowd into the left so each display bin still has
    equal mass."""
    pooled = [0] * FINE_N
    # Put 100 counts in each of the first 8 fine bins, 0 elsewhere.
    for i in range(8):
        pooled[i] = 100
    edges = pia.compute_bankruptcy_adaptive_edges(
        pooled, session_spins=1000, target_bins=8,
    )
    assert len(edges) == 9
    assert edges[0] == 0
    assert edges[-1] == 1000
    # The 8 bankrupt bins' edges should all fall within the first ~10%
    # of the spin range (mass lives in spins 0-80). fine_bin_size=10,
    # so edges[1..8] should sit near 10, 20, ..., 80 (though the last
    # edge is forced to session_spins=1000 and the 7th "soft" edge may
    # pad out).
    # At minimum: most mass-carrying edges cluster in first 100 spins.
    tight_edges = [e for e in edges[1:-1] if e <= 100]
    assert len(tight_edges) >= 6


def test_adaptive_edges_strictly_monotonic():
    """Contrived: only fine bin 50 carries mass. Adaptive logic must
    still produce 9 strictly-increasing edges."""
    pooled = [0] * FINE_N
    pooled[50] = 1000
    edges = pia.compute_bankruptcy_adaptive_edges(
        pooled, session_spins=1000, target_bins=8,
    )
    assert len(edges) == 9
    assert edges[0] == 0
    assert edges[-1] == 1000
    for i in range(1, len(edges)):
        assert edges[i] > edges[i - 1], f"edges not monotonic at i={i}: {edges}"


# ---------- rebase_fine_histogram_to_edges ------------------------------


def test_rebase_maps_fine_bins_by_midpoint():
    """Simple mapping: 100 fine bins over [0, 1000], edges=[0, 500, 1000]
    → first 50 fine bins (midpoints 5, 15, ..., 495) fall in bin 0."""
    fine = [1] * FINE_N  # 1 count per fine bin
    edges = [0, 500, 1000]
    out = pia.rebase_fine_histogram_to_edges(fine, session_spins=1000, edges=edges)
    assert len(out) == 2
    assert out[0] == 50
    assert out[1] == 50


def test_rebase_preserves_total_mass():
    fine = [5, 10, 3, 0, 8] + [0] * (FINE_N - 5)
    edges = [0, 200, 500, 1000]  # 3 bins
    out = pia.rebase_fine_histogram_to_edges(fine, session_spins=1000, edges=edges)
    assert sum(out) == sum(fine)


# ---------- median_spins_from_fine_hist ---------------------------------


def test_median_all_survivors_returns_session_spins():
    fine = [0] * FINE_N
    assert pia.median_spins_from_fine_hist(fine, survived=100, session_spins=1000) == 1000


def test_median_inside_bankrupt_bins():
    """100 bankrupt sessions, all in fine bin 20 (midpoint=205 at
    session_spins=1000 / fine_n=100). Median = 205 regardless of
    survivors count as long as >50% are bankrupt in that bin."""
    fine = [0] * FINE_N
    fine[20] = 100
    # No survivors → all bankrupt → median in fine bin 20.
    m = pia.median_spins_from_fine_hist(fine, survived=0, session_spins=1000)
    assert 200 <= m <= 210


def test_median_falls_in_survivor_bucket_when_majority_survive():
    fine = [10, 10, 10]  # 30 bankrupt
    # Pad to full length.
    fine += [0] * (FINE_N - len(fine))
    # 100 survivors >> 30 bankrupt → median in survivor group.
    m = pia.median_spins_from_fine_hist(fine, survived=100, session_spins=1000)
    assert m == 1000


def test_median_zero_total_returns_zero():
    assert pia.median_spins_from_fine_hist([0] * FINE_N, 0, 1000) == 0
