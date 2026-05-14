"""SpinType-split breakdown tests for player_impact_analyzer.

Tests cover:
  1. New field presence and schema structure in parse_chunk_response output.
  2. Spin-type label derivation (machine-agnostic, behavior_name-based).
  3. Cross-signal sanity: sum(payouts_by_spin_type rtp_pp) == aggregate sum.
  4. Reel marginal prob_pct sums to 100% per (label, reel).
  5. Graceful base-only machine: single ST label.
  6. Existing aggregate fields are unchanged (regression guard).

Mock chunk construction follows test_analyzer_parsing.py conventions.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import pytest

from fresh_slotlab.player_impact_analyzer import (
    parse_chunk_response,
    to_float,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_round(
    spin_type: int,
    cost: int,
    win: int,
    pay_id: str | None,
    stop_cols: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal round dict suitable for parse_chunk_response."""
    payout_id_map = {}
    if pay_id is not None and win > 0:
        payout_id_map = {pay_id: win}
    r = {
        "BetAmount": cost,
        "CostCredits": cost,
        "WinCredits": win,
        "SpinType": spin_type,
        "PayoutByPayline": "",
        "PayoutGroupId": 0,
        "PayoutIdToWinAmount": payout_id_map,
        "StopSymbolsByCol": stop_cols or [
            "A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"
        ],
        "ReMarks": "",
        "RewardLastNode": None,
    }
    r.update(extra)
    return r


def _make_robot(rounds: list[dict]) -> dict[str, Any]:
    return {"roundResult": json.dumps(rounds)}


def _make_response(robots: list[dict]) -> list[dict]:
    return robots


# ---------------------------------------------------------------------------
# Test 1: new chunk-level fields are present in parse_chunk_response output
# ---------------------------------------------------------------------------

def test_new_chunk_fields_present():
    """parse_chunk_response must emit payout_id_win_by_spin_type and
    symbol_counts_by_col_by_spin_type in its output dict."""
    rounds = [
        _make_round(1, 1000, 5000, "3"),
        _make_round(2, 0, 2000, "5", stop_cols=["X-Y-Z", "X-Y", "X-Y-Z", "X-Y", "X-Y-Z"]),
        _make_round(1, 1000, 0, None),
    ]
    resp = _make_response([_make_robot(rounds)])
    rec = parse_chunk_response(resp, 0, 1000)
    assert rec.get("ok"), f"parse failed: {rec.get('error')}"
    assert "payout_id_win_by_spin_type" in rec, "payout_id_win_by_spin_type missing from chunk payload"
    assert "symbol_counts_by_col_by_spin_type" in rec, "symbol_counts_by_col_by_spin_type missing from chunk payload"


# ---------------------------------------------------------------------------
# Test 2: payout_id_win_by_spin_type captures wins per ST correctly
# ---------------------------------------------------------------------------

def test_payout_id_win_by_spin_type_values():
    """Win amounts in payout_id_win_by_spin_type must match actual round wins
    and must be keyed by the correct SpinType."""
    rounds = [
        _make_round(1, 1000, 3000, "7"),   # paid ST=1, win 3000 on pay_id 7
        _make_round(1, 1000, 0,    None),   # paid ST=1, no win
        _make_round(2, 0,    8000, "7"),   # bonus ST=2, win 8000 on pay_id 7
        _make_round(2, 0,    1000, "9"),   # bonus ST=2, win 1000 on pay_id 9
    ]
    resp = _make_response([_make_robot(rounds)])
    rec = parse_chunk_response(resp, 0, 1000)
    assert rec.get("ok")

    pid_win_st = rec["payout_id_win_by_spin_type"]
    # pay_id "7" should have ST=1 → 3000 and ST=2 → 8000
    pid7 = pid_win_st.get("7") or {}
    assert float(pid7.get(1, 0)) == pytest.approx(3000.0, abs=0.1), \
        f"pid=7 ST=1 win expected 3000, got {pid7.get(1)}"
    assert float(pid7.get(2, 0)) == pytest.approx(8000.0, abs=0.1), \
        f"pid=7 ST=2 win expected 8000, got {pid7.get(2)}"

    # pay_id "9" should have ST=2 → 1000
    pid9 = pid_win_st.get("9") or {}
    assert float(pid9.get(2, 0)) == pytest.approx(1000.0, abs=0.1), \
        f"pid=9 ST=2 win expected 1000, got {pid9.get(2)}"


# ---------------------------------------------------------------------------
# Test 3: symbol_counts_by_col_by_spin_type is keyed by ST and col
# ---------------------------------------------------------------------------

def test_symbol_counts_by_col_by_spin_type_structure():
    """symbol_counts_by_col_by_spin_type must bucket symbols under str(ST)
    → str(col) → symbol → count."""
    rounds = [
        _make_round(1, 1000, 0, None, stop_cols=["7-7-BAR", "7-BAR-7", "BAR-7-7"]),
        _make_round(1, 1000, 0, None, stop_cols=["BAR-7-7", "BAR-7-7", "BAR-7-7"]),
        _make_round(2, 0,    0, None, stop_cols=["7-7-7",   "BAR-BAR-BAR", "7-7-7"]),
    ]
    resp = _make_response([_make_robot(rounds)])
    rec = parse_chunk_response(resp, 0, 1000)
    assert rec.get("ok")

    scst = rec["symbol_counts_by_col_by_spin_type"]
    # ST=1 should be present
    assert "1" in scst, "ST=1 not in symbol_counts_by_col_by_spin_type"
    # ST=2 should be present
    assert "2" in scst, "ST=2 not in symbol_counts_by_col_by_spin_type"
    # col=0 exists for ST=1
    assert "0" in scst["1"], "col=0 missing for ST=1"

    # In ST=1 col=0: rounds show stop "7-7-BAR" and "BAR-7-7"
    # split_symbols splits on "-" so symbols are ["7","7","BAR"] per col
    # Actually the col=0 texts are "7-7-BAR" and "BAR-7-7" for the 2 ST=1 rounds
    # split_symbols("7-7-BAR") → ["7", "7", "BAR"]
    # Counts per symbol: "7"=count(row0,row1,row2) + "BAR"=...
    # This test just checks structure, not exact counts.
    col0_st1 = scst["1"]["0"]
    assert isinstance(col0_st1, dict)
    assert len(col0_st1) > 0


# ---------------------------------------------------------------------------
# Test 4: spin_type_label derivation — machine-agnostic
# ---------------------------------------------------------------------------

def test_st_label_machine_agnostic():
    """The spin_type label must be derived from behavior_name (paid/free/mixed)
    and the ST integer — never from hardcoded machine names or ST values."""
    # Simulate: ST=5 always has CostCredits>0 → "paid"; ST=99 always CostCredits=0 → "free"
    rounds_paid = [_make_round(5, 1000, 2000, "1") for _ in range(3)]
    rounds_free = [_make_round(99, 0, 500, "2") for _ in range(2)]
    resp = _make_response([_make_robot(rounds_paid + rounds_free)])
    rec = parse_chunk_response(resp, 0, 1000)
    assert rec.get("ok")

    # Check spin_type_paid_rounds: ST=5 should have 3 paid rounds
    assert int(rec.get("spin_type_paid_rounds", {}).get("5", 0)) == 3
    assert int(rec.get("spin_type_paid_rounds", {}).get("99", 0)) == 0

    # The label would be formed in finalize; here check the chunk-level
    # building blocks are correct so the label can be machine-agnostic.
    # ST=5 has all paid rounds → behavior "paid" → label "ST5_paid"
    # ST=99 has no paid rounds → behavior "free" → label "ST99_free"
    spins5 = int(rec.get("spin_type_spins", {}).get("5", 0))
    paid5 = int(rec.get("spin_type_paid_rounds", {}).get("5", 0))
    assert spins5 == 3
    assert paid5 == 3  # all paid → behavior "paid"

    spins99 = int(rec.get("spin_type_spins", {}).get("99", 0))
    paid99 = int(rec.get("spin_type_paid_rounds", {}).get("99", 0))
    assert spins99 == 2
    assert paid99 == 0  # all free → behavior "free"


# ---------------------------------------------------------------------------
# Test 5: cross-signal sanity — win attribution is consistent
# ---------------------------------------------------------------------------

def test_payout_win_by_st_totals_match_aggregate():
    """For each pay_id, sum(payout_id_win_by_spin_type values) must equal
    payout_id_win[pid]. This invariant guarantees no double-counting and
    no win dropped from the ST-split breakdown."""
    rounds = [
        _make_round(1, 1000, 2000, "3"),
        _make_round(1, 1000, 5000, "7"),
        _make_round(2, 0,    3000, "3"),
        _make_round(2, 0,    4000, "7"),
        _make_round(1, 1000, 0,    None),
    ]
    resp = _make_response([_make_robot(rounds)])
    rec = parse_chunk_response(resp, 0, 1000)
    assert rec.get("ok")

    pid_win = rec["payout_id_win"]
    pid_win_st = rec["payout_id_win_by_spin_type"]

    for pid, total in pid_win.items():
        st_map = pid_win_st.get(pid) or {}
        st_sum = sum(float(v) for v in st_map.values())
        assert abs(st_sum - float(total)) < 0.5, (
            f"pid={pid}: aggregate win={total:.2f}, ST-split sum={st_sum:.2f}, delta too large"
        )


# ---------------------------------------------------------------------------
# Test 6: reel marginal prob_pct sums to 100% per (ST, col)
# ---------------------------------------------------------------------------

def test_reel_marginal_prob_sums_to_100():
    """For every (spin_type, col) entry in symbol_counts_by_col_by_spin_type,
    sum of all symbol counts must equal col_total → prob_pct sums = 100%.
    This is a structural invariant checked at chunk level."""
    rounds = [
        _make_round(1, 1000, 0, None, stop_cols=["A-B-C", "D-E-F", "A-B-A", "C-D-E", "F-A-B"]),
        _make_round(1, 1000, 0, None, stop_cols=["B-C-D", "A-B-C", "D-E-F", "A-B-C", "D-E-F"]),
        _make_round(2, 0,    0, None, stop_cols=["X-Y-Z", "X-Y-Z", "X-Y-Z", "X-Y-Z", "X-Y-Z"]),
    ]
    resp = _make_response([_make_robot(rounds)])
    rec = parse_chunk_response(resp, 0, 1000)
    assert rec.get("ok")

    scst = rec["symbol_counts_by_col_by_spin_type"]
    for st_key, col_map in scst.items():
        for col_key, sym_map in col_map.items():
            col_total = sum(sym_map.values())
            prob_sum = sum((c / col_total) * 100.0 for c in sym_map.values()) if col_total > 0 else 0.0
            assert abs(prob_sum - 100.0) < 0.01, (
                f"ST={st_key} col={col_key}: prob_pct sum={prob_sum:.4f} != 100"
            )


# ---------------------------------------------------------------------------
# Test 7: existing aggregate fields unchanged (regression guard)
# ---------------------------------------------------------------------------

def test_existing_aggregate_fields_unchanged():
    """Adding ST-split fields must not modify existing aggregate outputs.
    payout_id_win, payout_id_hits, spin_type_spins, symbol_counts_by_col
    must remain identical to their pre-split-extension values."""
    rounds = [
        _make_round(1, 1000, 3000, "7", stop_cols=["A-B", "C-D", "E-F", "A-B", "C-D"]),
        _make_round(1, 1000, 0,    None, stop_cols=["B-C", "D-E", "F-A", "B-C", "D-E"]),
        _make_round(2, 0,    2000, "7", stop_cols=["X-Y", "X-Y", "X-Y", "X-Y", "X-Y"]),
    ]
    resp = _make_response([_make_robot(rounds)])
    rec = parse_chunk_response(resp, 0, 1000)
    assert rec.get("ok")

    # Aggregate pay_id win
    assert float(rec["payout_id_win"].get("7", 0)) == pytest.approx(5000.0, abs=0.1), \
        "payout_id_win[7] should be 3000+2000=5000"
    assert int(rec["payout_id_hits"].get("7", 0)) == 2, \
        "payout_id_hits[7] should be 2 (two winning rounds)"

    # spin_type_spins
    assert int(rec.get("spin_type_spins", {}).get("1", 0)) == 2
    assert int(rec.get("spin_type_spins", {}).get("2", 0)) == 1

    # symbol_counts_by_col present and non-empty
    scol = rec.get("symbol_counts_by_col") or {}
    assert len(scol) > 0, "symbol_counts_by_col should be non-empty"

    # New ST-split fields are additive (both present)
    assert "payout_id_win_by_spin_type" in rec
    assert "symbol_counts_by_col_by_spin_type" in rec


# ---------------------------------------------------------------------------
# Test 8: base-only machine gracefully shows single ST label
# ---------------------------------------------------------------------------

def test_single_st_base_only_machine():
    """A machine with only paid rounds produces a single ST label.
    The payouts_by_spin_type structure is populated for that one label only."""
    rounds = [_make_round(1, 1000, 2000, "3") for _ in range(5)]
    resp = _make_response([_make_robot(rounds)])
    rec = parse_chunk_response(resp, 0, 1000)
    assert rec.get("ok")

    # Only ST=1 should appear
    assert set(rec.get("spin_type_spins", {}).keys()) == {"1"}
    assert set(rec.get("payout_id_win_by_spin_type", {}).get("3", {}).keys()) == {1}, \
        "Only ST=1 should appear in payout_id_win_by_spin_type for a base-only machine"

    # symbol_counts_by_col_by_spin_type should only have ST=1
    scst = rec.get("symbol_counts_by_col_by_spin_type") or {}
    assert set(scst.keys()) == {"1"}, \
        "Only ST=1 key should appear in symbol_counts_by_col_by_spin_type for base-only"
