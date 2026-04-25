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


# ---------- _BankruptcyStreamAccumulator (cross-chunk pooling) ----------
#
# Per-chunk simulation drops chunks below session_spins because they can't
# form even one complete window. With virtual sampling defaults
# (chunk_spin_times=1000 × chunk_robot_count=8 = 8000 paid spins vs
# session_spins=10000), every chunk falls below threshold → the
# bankruptcy panel renders "all robots=0" despite having 5M+ spins on
# disk. The streaming accumulator pools across chunks at merge time.
# These tests pin the cross-chunk pooling behavior so future regressions
# get caught.


def _net_zero_round() -> dict[str, int]:
    """A round that pays back exactly its bet — balance unchanged."""
    return {"CostCredits": 100, "WinCredits": 100}


def test_stream_acc_cross_chunk_pools_below_session_threshold():
    """The regression case: 3 chunks of 4000 paid rounds each (12,000
    total) with session_spins=10000. Per-chunk simulator returns
    nothing for each (4000 < 10000); streaming accumulator should
    produce 1 complete window from the pooled rounds."""
    acc = pia._BankruptcyStreamAccumulator(
        bet=100, session_spins=10000, bankroll_mults=(100, 500),
    )
    # Build 3 chunks of 4000 rounds each, all net-zero (balance stays
    # constant at init_bankroll across the entire stream).
    for _ in range(3):
        reps = [(100, 100)] * 4000
        acc.feed_reps(reps)
    out = acc.finalize()
    # 12,000 reps // 10,000 session = 1 complete window per tier.
    # Tail 2,000 dropped (matches per-chunk simulator drop-tail behavior).
    assert out[100]["survived"] == 1
    assert out[100]["bankrupt"] == 0
    assert out[100]["spins_done"] == []
    assert out[500]["survived"] == 1
    assert out[500]["bankrupt"] == 0


def test_stream_acc_bankrupt_branch_resets_for_next_window():
    """All-lose, bet=100, init_bankroll for tier 100 = 10,000. Each
    window goes 100 successful spins (balance 10,000 → 0 by spin 100),
    then the 101st round can't afford the bet → bankrupt at spins_done
    =100. The 101st round is re-applied to a fresh window. With 600
    all-lose reps, we expect 5 bankruptcies (rounds 101, 201, 301,
    401, 501 trigger them) + 99 reps mid-window at end of stream
    (dropped, matches per-chunk drop-tail semantics)."""
    acc = pia._BankruptcyStreamAccumulator(
        bet=100, session_spins=200, bankroll_mults=(100,),
    )
    losing = [(100, 0)] * 600
    acc.feed_reps(losing)
    out = acc.finalize()
    assert out[100]["bankrupt"] == 5
    assert out[100]["survived"] == 0
    assert out[100]["spins_done"] == [100, 100, 100, 100, 100]


def test_stream_acc_bankrupt_branch_split_across_chunk_boundary():
    """Bankrupt mid-chunk → state should reset cleanly so the NEXT
    chunk's reps start a fresh window. Catches the off-by-one of
    "did the reset apply to the round that triggered bankruptcy?"."""
    acc = pia._BankruptcyStreamAccumulator(
        bet=100, session_spins=500, bankroll_mults=(100,),
    )
    # Tier 100: init_bankroll = 100 × 100 = 10,000. With all-lose
    # bet=100 → bankrupt at spin 100. Feed 50 lose rounds in chunk A
    # (balance dwindles from 10000 → 5000), then 60 in chunk B
    # (balance hits 0 at spin 100 = chunk-A's 50 + chunk-B's first 50,
    # bankrupt on the 51st round of chunk B = global spin 101).
    acc.feed_reps([(100, 0)] * 50)
    acc.feed_reps([(100, 0)] * 60)
    out = acc.finalize()
    assert out[100]["bankrupt"] == 1
    # The bankrupt window survived spin 100 (balance hit 0); spin 101
    # is the failed-to-afford round, so spins_done = 100.
    assert out[100]["spins_done"] == [100]


def test_stream_acc_independent_tiers():
    """Each bankroll multiplier maintains its own balance / spins_done
    state. A tier with higher init_bankroll survives where a smaller
    one bankrupts. bet=100, all-lose, 200 reps:
      - Tier 50:  init=5000. Spins 1-50 deplete → spin 51 bankrupt
                  (spins_done=50). Re-applied to fresh window. Pattern
                  repeats every ~50 reps → 3 bankruptcies + 49 in-flight
                  reps at end of stream (dropped).
      - Tier 200: init=20000. 200 spins consume exactly 20000 →
                  spins_done=200 → survived. Bankroll never hits 0
                  before window completes."""
    acc = pia._BankruptcyStreamAccumulator(
        bet=100, session_spins=200, bankroll_mults=(50, 200),
    )
    acc.feed_reps([(100, 0)] * 200)
    out = acc.finalize()
    assert out[50]["bankrupt"] == 3
    assert out[50]["survived"] == 0
    assert out[50]["spins_done"] == [50, 50, 50]
    assert out[200]["bankrupt"] == 0
    assert out[200]["survived"] == 1


def test_stream_acc_bonus_rounds_do_not_drain_balance():
    """CostCredits=0 (bonus round) should not trigger the bankruptcy
    branch even if balance < cost (the cost > 0 guard short-circuits
    that check). WinCredits still credits, replenishing the balance.
    Matches simulate_bankruptcy_from_response semantics.

    Setup: tier 1, init_bankroll = 1×100 = 100. The stream below
    interleaves bonus rounds at the moments the balance would
    otherwise hit 0, so a 10-round window completes without any
    bankruptcy."""
    acc = pia._BankruptcyStreamAccumulator(
        bet=100, session_spins=10, bankroll_mults=(1,),
    )
    reps = [
        (100, 0),    # spin 1 paid loss: balance 100 → 0
        (0, 200),    # spin 2 bonus: balance 0 → 200 (cost=0 skips bankrupt branch)
        (100, 0),    # spin 3 paid loss: 200 → 100
        (100, 0),    # spin 4 paid loss: 100 → 0
        (0, 1000),   # spin 5 bonus: 0 → 1000
        (100, 0),    # spin 6: 1000 → 900
        (100, 0),    # spin 7: 900 → 800
        (100, 0),    # spin 8: 800 → 700
        (100, 0),    # spin 9: 700 → 600
        (100, 0),    # spin 10: 600 → 500. spins_done=10 → survived.
    ]
    acc.feed_reps(reps)
    out = acc.finalize()
    assert out[1]["survived"] == 1
    assert out[1]["bankrupt"] == 0


def test_stream_acc_partial_tail_dropped():
    """Reps below session_spins at the END of the stream are dropped
    (in-progress window not counted as bankrupt or survived). Matches
    per-chunk simulator drop-tail semantics."""
    acc = pia._BankruptcyStreamAccumulator(
        bet=100, session_spins=100, bankroll_mults=(10,),
    )
    # Net-zero, exactly 250 reps → 2 complete windows + 50-rep tail.
    acc.feed_reps([(100, 100)] * 250)
    out = acc.finalize()
    assert out[10]["survived"] == 2
    assert out[10]["bankrupt"] == 0


def test_stream_acc_has_data_flag():
    """``has_data`` distinguishes "we received reps" from "everything
    was dropped"; finalize uses this to decide whether to prefer the
    streaming result over the per-chunk-merged fallback."""
    acc = pia._BankruptcyStreamAccumulator(
        bet=100, session_spins=10, bankroll_mults=(1,),
    )
    assert acc.has_data is False
    acc.feed_reps([(100, 0)])
    assert acc.has_data is True


def test_stream_acc_degenerate_inputs_no_crash():
    """Zero bet / zero session_spins → applicable=False, feed_reps is
    a no-op, finalize returns zeroed tiers."""
    acc = pia._BankruptcyStreamAccumulator(
        bet=0, session_spins=10, bankroll_mults=(100,),
    )
    acc.feed_reps([(100, 0)] * 100)  # would crash if not guarded
    out = acc.finalize()
    assert out[100]["bankrupt"] == 0
    assert out[100]["survived"] == 0


def test_stream_acc_matches_per_chunk_when_chunk_size_above_threshold():
    """Sanity: when chunk size IS ≥ session_spins, the streaming
    accumulator's result equals per-chunk simulation summed across
    chunks. No regression on the happy path."""
    bet = 100
    session = 200
    rounds = [{"CostCredits": 100, "WinCredits": 100} for _ in range(800)]  # net-zero
    # Per-chunk path: one chunk, 800 reps → 4 survived windows.
    per_chunk = pia.simulate_bankruptcy_from_response(
        [_robot(rounds)], bet=bet, session_spins=session,
        bankroll_mults=(50,),
    )
    # Stream path: same 800 reps fed in one call.
    acc = pia._BankruptcyStreamAccumulator(
        bet=bet, session_spins=session, bankroll_mults=(50,),
    )
    acc.feed_reps([(100, 100)] * 800)
    stream = acc.finalize()
    assert per_chunk[50]["survived"] == stream[50]["survived"] == 4
    assert per_chunk[50]["bankrupt"] == stream[50]["bankrupt"] == 0


# ---------- _extract_bankruptcy_reps (per-chunk reps extraction) --------


def test_extract_reps_handles_normal_response():
    rounds = [
        {"CostCredits": 100, "WinCredits": 0},
        {"CostCredits": 100, "WinCredits": 500},
        {"CostCredits": 0, "WinCredits": 100},  # bonus
    ]
    reps = pia._extract_bankruptcy_reps([_robot(rounds)])
    assert reps == [(100, 0), (100, 500), (0, 100)]


def test_extract_reps_returns_empty_on_invalid_input():
    assert pia._extract_bankruptcy_reps(None) == []
    assert pia._extract_bankruptcy_reps({}) == []
    assert pia._extract_bankruptcy_reps([{"roundResult": None}]) == []


def test_extract_reps_handles_string_encoded_round_result():
    """parse_rounds accepts both list and JSON-string roundResult; the
    extraction helper inherits that. Matches production envelope shape."""
    import json as _json
    rounds = [{"CostCredits": 50, "WinCredits": 25}]
    robot = {"roundResult": _json.dumps(rounds)}
    assert pia._extract_bankruptcy_reps([robot]) == [(50, 25)]


def test_extract_reps_skips_non_dict_robots_and_rounds():
    """Defensive: malformed entries (None, lists, strings) shouldn't
    crash the extractor — they're skipped silently, matching the
    per-chunk simulator's input-tolerance contract."""
    rounds_good = [{"CostCredits": 10, "WinCredits": 5}]
    resp = [
        None,                                       # not a dict — skip
        "garbage",                                  # not a dict — skip
        _robot(rounds_good),                        # valid
        {"roundResult": [None, {"CostCredits": 20, "WinCredits": 10}]},  # mixed
    ]
    reps = pia._extract_bankruptcy_reps(resp)
    assert reps == [(10, 5), (20, 10)]
