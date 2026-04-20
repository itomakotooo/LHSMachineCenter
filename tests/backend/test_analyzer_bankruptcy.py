"""Tests for the rawdata-replay bankruptcy simulation + percentile /
fastest-bankruptcy helpers.

Architecture: per-chunk simulator stores an EXACT list of spins-done
values at bankruptcy (one entry per bankrupt window) plus a ``survived``
counter keyed by bankroll multiplier. Finalize sorts the combined list
once and computes per-tier:
  * median_spins_completed (= P50 over all sessions)
  * fastest_bankruptcy_spins (min of sorted list)
  * percentiles map (P10..P90) — denominator = ALL sessions; past the
    bankrupt mass they pin to session_spins so the UI transition reads
    as the survival complement.

Precision is 1 spin (no histogram quantization).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fresh_slotlab"))

import player_impact_analyzer as pia  # noqa: E402


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
    assert tier["spins_done"] == []


def test_bankruptcy_sim_pools_across_robots_with_net_zero_survival():
    rounds = [{"CostCredits": 100, "WinCredits": 100} for _ in range(30)]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=100, session_spins=10,
        bankroll_mults=(100,),
    )
    tier = out[100]
    assert tier["survived"] == 3
    assert tier["bankrupt"] == 0
    assert tier["spins_done"] == []


def test_bankruptcy_sim_records_exact_spins_done():
    """bet=1, all-lose, 2 windows of 1000 rounds → every window dies at
    EXACTLY spin 100 (bankroll 100 drained 1-per-spin). No histogram
    quantization — spins_done == 100 exactly."""
    rounds = [{"CostCredits": 1, "WinCredits": 0} for _ in range(2000)]
    out = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=1, session_spins=1000,
        bankroll_mults=(100,),
    )
    tier = out[100]
    assert tier["bankrupt"] == 2
    assert tier["survived"] == 0
    assert tier["spins_done"] == [100, 100]


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


# ---------- fastest_bankruptcy_spins_from_list --------------------------


def test_fastest_bankruptcy_none_when_empty_list():
    assert pia.fastest_bankruptcy_spins_from_list([]) is None


def test_fastest_bankruptcy_returns_exact_minimum():
    """Sorted list input → first element is the fastest."""
    sd_sorted = [42, 100, 250, 500, 900]
    assert pia.fastest_bankruptcy_spins_from_list(sd_sorted) == 42


# ---------- compute_bankruptcy_percentiles (exact) ----------------------


def test_percentiles_all_survive_pins_every_decile_to_session_spins():
    out = pia.compute_bankruptcy_percentiles([], survived=200, session_spins=1000)
    for p in (10, 20, 30, 40, 50, 60, 70, 80, 90):
        assert out[p] == 1000


def test_percentiles_resolve_to_distinct_values_at_spin_precision():
    """This is the regression guard for the old histogram bug: when
    the bankruptcy distribution has distinct spin-level values at low
    deciles, each P{k} should report its OWN exact spin count — no
    collapsing to shared bin midpoints.

    Construct 100 bankrupt sessions with spins_done 1..100. P10 should
    be 10 (rank 9 in 0-indexed sorted list), P20=20, ..., P90=90.
    Exact precision: NO two deciles share a value."""
    sd = sorted(range(1, 101))  # 1..100
    out = pia.compute_bankruptcy_percentiles(
        sd, survived=0, session_spins=200,
    )
    values = [out[p] for p in (10, 20, 30, 40, 50, 60, 70, 80, 90)]
    # Every decile is distinct (exact precision — no collapses).
    assert len(set(values)) == 9
    # P10 hits rank 10*99/100 = 9.9 → round → 10 (value at sorted[10] = 11).
    # P50 hits rank 49.5 → round → 50 (value = 51). Allow ±1 slack for rounding.
    assert abs(values[0] - 11) <= 1
    assert abs(values[4] - 51) <= 1
    assert abs(values[-1] - 90) <= 1


def test_percentiles_transition_to_survivor_at_bankruptcy_complement():
    """80% bankrupt / 20% survived tier: percentiles past P80 land in
    the survivor group → pin to session_spins."""
    sd_sorted = [50 * (i + 1) for i in range(80)]  # 50..4000, 80 entries
    out = pia.compute_bankruptcy_percentiles(
        sd_sorted, survived=20, session_spins=5000,
    )
    # P80 rank = 0.8 * 99 = 79.2 → 79 → sorted[79] = 50*80 = 4000
    assert out[80] == 4000
    # P90 rank = 89.1 → 89 → past bankrupt list (80 entries, last index
    # 79), so idx 89 lands in survivor tier → session_spins.
    assert out[90] == 5000


def test_percentiles_monotonic_non_decreasing():
    sd_sorted = sorted([10, 50, 100, 200, 500, 800, 1500, 3000, 7000])
    out = pia.compute_bankruptcy_percentiles(
        sd_sorted, survived=5, session_spins=10000,
    )
    values = [out[p] for p in (10, 20, 30, 40, 50, 60, 70, 80, 90)]
    for i in range(1, len(values)):
        assert values[i] >= values[i - 1]


# ---------- median_spins_from_list (P50 convenience) --------------------


def test_median_equals_p50():
    sd = sorted([100, 200, 300, 400, 500, 600, 700])
    pct = pia.compute_bankruptcy_percentiles(
        sd, survived=0, session_spins=1000, percentiles=(50,),
    )
    assert pia.median_spins_from_list(sd, 0, 1000) == pct[50]


def test_median_all_survivors_returns_session_spins():
    assert pia.median_spins_from_list([], survived=100, session_spins=1000) == 1000


def test_median_zero_total_returns_zero():
    assert pia.median_spins_from_list([], 0, 1000) == 0


# ---------- merge semantics (finalize contract) -------------------------


def test_merged_spins_done_list_stays_precise_across_chunks():
    """Simulate two chunks' output, merge, compute percentiles from
    the combined exact list. Verify no quantization."""
    chunk_a = pia.simulate_bankruptcy_from_response(
        [_robot([{"CostCredits": 1, "WinCredits": 0}] * 2000)],
        bet=1, session_spins=1000,
        bankroll_mults=(100,),
    )
    chunk_b = pia.simulate_bankruptcy_from_response(
        [_robot([{"CostCredits": 1, "WinCredits": 0}] * 2000)],
        bet=1, session_spins=1000,
        bankroll_mults=(100,),
    )
    merged = pia._empty_bankruptcy_tier()
    for c in (chunk_a, chunk_b):
        merged["bankrupt"] += c[100]["bankrupt"]
        merged["survived"] += c[100]["survived"]
        merged["spins_done"].extend(c[100]["spins_done"])
    assert merged["spins_done"] == [100, 100, 100, 100]
    assert merged["bankrupt"] == 4
    sd_sorted = sorted(merged["spins_done"])
    out = pia.compute_bankruptcy_percentiles(
        sd_sorted, survived=0, session_spins=1000,
    )
    # All 4 sessions died at spin 100 → every percentile = 100.
    for p in (10, 50, 90):
        assert out[p] == 100
