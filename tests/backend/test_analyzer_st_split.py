"""SpinType-split breakdown tests for player_impact_analyzer.

Tests cover:
  1. New field presence and schema structure in parse_chunk_response output.
  2. Spin-type label derivation (machine-agnostic, behavior_name-based).
  3. Cross-signal sanity: sum(payouts_by_spin_type rtp_pp) == aggregate sum.
  4. Reel marginal prob_pct sums to 100% per (label, reel).
  5. Graceful base-only machine: single ST label.
  6. Existing aggregate fields are unchanged (regression guard).
  9. payouts_by_spin_type rows use payout_ids_top20-aligned field names
     (hit_rate fraction, rtp_contribution_pp) — schema parity guard.

Mock chunk construction follows test_analyzer_parsing.py conventions.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from fresh_slotlab.player_impact_analyzer import (
    parse_chunk_response,
    to_float,
)

ROOT = Path(__file__).resolve().parents[2]


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


# ---------------------------------------------------------------------------
# Test 9: payouts_by_spin_type schema parity with payout_ids_top20
# (integration test — runs the full finalize path via subprocess on M31 cache)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (ROOT / "rawdata" / "M31" / "mode_1" / "chunk_0001.json").exists(),
    reason="M31 mode 1 rawdata cache not present",
)
def test_payouts_by_spin_type_field_names_match_payout_ids_top20(tmp_path):
    """payouts_by_spin_type rows must have hit_rate (fraction) and
    rtp_contribution_pp — matching payout_ids_top20 field names.
    Regression guard: ensures hit_rate_pct / rtp_pp are NOT emitted."""
    cache_dir = ROOT / "rawdata" / "M31" / "mode_1"
    # Discover the cfg_md5 + code_md5 from the first chunk so the
    # analyzer accepts it without a filter mismatch.
    chunk0 = cache_dir / "chunk_0001.json"
    with open(chunk0, encoding="utf-8") as f:
        env = json.load(f)
    cfg_md5 = env.get("config_md5", "")
    code_md5 = env.get("code_md5", "")

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    progress_file = tmp_path / "progress.jsonl"
    cmd = [
        sys.executable, "-m", "fresh_slotlab.player_impact_analyzer",
        "--machine", "M31",
        "--rtp-mode", "1",
        "--bet", "1000",
        "--output-dir", str(output_dir),
        "--target-halfwidth-pp", "99",    # exit after 1 chunk
        "--max-chunks", "1",
        "--chunk-spin-times", "100",
        "--chunk-robot-count", "2",
        "--batch-concurrency", "1",
        "--timeout", "10",
        "--bankruptcy-session-spins", "100",
        "--bankruptcy-bankroll-multipliers", "10",
        "--from-cache", str(cache_dir),
        "--upstream-config-md5", cfg_md5,
        "--upstream-code-md5", code_md5,
        "--progress-file", str(progress_file),
        "--run-id", "test_schema_parity",
    ]
    result = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Analyzer subprocess failed:\nSTDOUT={result.stdout[-2000:]}\n"
        f"STDERR={result.stderr[-2000:]}"
    )

    # Find the emitted player_impact_summary.json.
    summaries = list(output_dir.rglob("player_impact_summary.json"))
    assert summaries, "No player_impact_summary.json emitted"
    with open(summaries[0], encoding="utf-8") as f:
        summary = json.load(f)

    pi = summary.get("player_impact", {})

    # --- payout_ids_top20 reference schema ---
    top20 = pi.get("payout_ids_top20", [])
    assert top20, "payout_ids_top20 must be non-empty for regression check"
    ref_row = top20[0]
    assert "hit_rate" in ref_row, "payout_ids_top20 must have hit_rate (fraction)"
    assert "rtp_contribution_pp" in ref_row, "payout_ids_top20 must have rtp_contribution_pp"

    # --- payouts_by_spin_type schema must match ---
    pbst = pi.get("payouts_by_spin_type", {})
    assert pbst, "payouts_by_spin_type must be non-empty for M31 (has ST43_paid + ST44_free)"
    for label, rows in pbst.items():
        assert rows, f"payouts_by_spin_type[{label}] must be non-empty"
        row = rows[0]
        assert "hit_rate" in row, (
            f"payouts_by_spin_type[{label}] row must have 'hit_rate' (fraction), "
            f"got keys: {list(row.keys())}"
        )
        assert "hit_rate_pct" not in row, (
            f"payouts_by_spin_type[{label}] must NOT have 'hit_rate_pct' (old name)"
        )
        assert "rtp_contribution_pp" in row, (
            f"payouts_by_spin_type[{label}] row must have 'rtp_contribution_pp', "
            f"got keys: {list(row.keys())}"
        )
        assert "rtp_pp" not in row, (
            f"payouts_by_spin_type[{label}] must NOT have 'rtp_pp' (old name)"
        )
        # hit_rate must be a fraction (< 1.0 for typical pay_ids; grand
        # jackpots may be ~1e-6; only bonus rounds can exceed ~50% hit_rate).
        # Value > 2.0 almost certainly means the old percent form leaked.
        assert float(row["hit_rate"]) <= 2.0, (
            f"payouts_by_spin_type[{label}].hit_rate={row['hit_rate']} looks like "
            f"a percentage (> 2.0); expected fraction"
        )


def test_zero_win_but_fired_pid_retained_in_split(tmp_path):
    """Trigger-marker pay_ids (M31 pid 666: always win=0 but fires on
    every scatter-trigger paid round) MUST be retained in
    payouts_by_spin_type[ST43_paid] despite their 0 total_win + 0 RTP
    contribution. Regression guard: previous filter ``if st_win == 0.0:
    continue`` silently dropped these rows; correct filter is on hits."""
    cache_dir = ROOT / "rawdata" / "M31" / "mode_1"
    chunk0 = cache_dir / "chunk_0001.json"
    with open(chunk0, encoding="utf-8") as f:
        env = json.load(f)
    cfg_md5 = env.get("config_md5", "")
    code_md5 = env.get("code_md5", "")

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    progress_file = tmp_path / "progress.jsonl"
    cmd = [
        sys.executable, "-m", "fresh_slotlab.player_impact_analyzer",
        "--machine", "M31",
        "--rtp-mode", "1",
        "--bet", "1000",
        "--output-dir", str(output_dir),
        "--target-halfwidth-pp", "99",
        "--max-chunks", "1",
        "--chunk-spin-times", "100",
        "--chunk-robot-count", "2",
        "--batch-concurrency", "1",
        "--timeout", "10",
        "--bankruptcy-session-spins", "100",
        "--bankruptcy-bankroll-multipliers", "10",
        "--from-cache", str(cache_dir),
        "--upstream-config-md5", cfg_md5,
        "--upstream-code-md5", code_md5,
        "--progress-file", str(progress_file),
        "--run-id", "test_zero_win_pid_retained",
    ]
    result = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Analyzer subprocess failed:\nSTDOUT={result.stdout[-2000:]}\n"
        f"STDERR={result.stderr[-2000:]}"
    )

    summaries = list(output_dir.rglob("player_impact_summary.json"))
    assert summaries, "No player_impact_summary.json emitted"
    with open(summaries[0], encoding="utf-8") as f:
        summary = json.load(f)
    pi = summary.get("player_impact", {})

    # Step 1: confirm pid 666 IS in aggregate (analyzer must have seen it).
    top20 = pi.get("payout_ids_top20", [])
    pid666_agg = next((r for r in top20 if str(r.get("payout_id")) == "666"), None)
    assert pid666_agg is not None, (
        "pid 666 expected in payout_ids_top20 for M31 (FreeSpin trigger marker; "
        "if missing, this machine doesn't exercise the regression — fixture issue)"
    )
    assert pid666_agg.get("hit_count", 0) > 0, (
        f"pid 666 in aggregate must have hit_count > 0 (got {pid666_agg.get('hit_count')}). "
        "Without observed fires this test cannot exercise the regression."
    )
    assert float(pid666_agg.get("total_win", 1)) == 0.0, (
        f"pid 666 expected to have total_win == 0 (trigger marker), got "
        f"{pid666_agg.get('total_win')}. Test assumption broken."
    )

    # Step 2: pid 666 MUST appear in ST43_paid split table despite 0 win.
    pbst = pi.get("payouts_by_spin_type", {})
    st43 = pbst.get("ST43_paid", [])
    pid666_split = next((r for r in st43 if str(r.get("payout_id")) == "666"), None)
    assert pid666_split is not None, (
        "pid 666 MUST be retained in payouts_by_spin_type['ST43_paid'] even "
        "with total_win=0. Previous filter on st_win silently dropped this row "
        "and the aggregate panel showed a pid (666) that the split panel did not — "
        "the data inconsistency user observed as '拆分跟总览不一样'. "
        f"Current ST43_paid pid list: {[r.get('payout_id') for r in st43]}"
    )
    # Step 3: pid 666 split row must carry hits but 0 RTP contribution.
    assert pid666_split.get("hit_count", 0) > 0
    assert float(pid666_split.get("rtp_contribution_pp", 1.0)) == 0.0


def test_spin_type_category_strict_binary(tmp_path):
    """spin_type_category in payout_ids_top20 must be strictly derived
    from the number of distinct SpinTypes in which the pay_id fired:
      • exactly 1 firing ST → that ST's category (paid / bonus / mixed)
      • ≥2 firing STs       → 'mixed' — no fuzzy threshold

    Regression guard: previous logic used a 0.8 dominant-share threshold
    which labeled pay_ids 'paid' when ≥80% of firings were on paid spins,
    hiding bonus firings from the aggregate badge (M31 pid 10/11 case)."""
    cache_dir = ROOT / "rawdata" / "M31" / "mode_1"
    chunk0 = cache_dir / "chunk_0001.json"
    with open(chunk0, encoding="utf-8") as f:
        env = json.load(f)
    cfg_md5 = env.get("config_md5", "")
    code_md5 = env.get("code_md5", "")

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    progress_file = tmp_path / "progress.jsonl"
    cmd = [
        sys.executable, "-m", "fresh_slotlab.player_impact_analyzer",
        "--machine", "M31",
        "--rtp-mode", "1",
        "--bet", "1000",
        "--output-dir", str(output_dir),
        "--target-halfwidth-pp", "99",
        "--max-chunks", "1",
        "--chunk-spin-times", "100",
        "--chunk-robot-count", "2",
        "--batch-concurrency", "1",
        "--timeout", "10",
        "--bankruptcy-session-spins", "100",
        "--bankruptcy-bankroll-multipliers", "10",
        "--from-cache", str(cache_dir),
        "--upstream-config-md5", cfg_md5,
        "--upstream-code-md5", code_md5,
        "--progress-file", str(progress_file),
        "--run-id", "test_category_strict_binary",
    ]
    result = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Analyzer subprocess failed:\nSTDOUT={result.stdout[-2000:]}\n"
        f"STDERR={result.stderr[-2000:]}"
    )

    summaries = list(output_dir.rglob("player_impact_summary.json"))
    assert summaries, "No player_impact_summary.json emitted"
    with open(summaries[0], encoding="utf-8") as f:
        summary = json.load(f)
    pi = summary.get("player_impact", {})
    top20 = pi.get("payout_ids_top20", [])
    assert top20, "payout_ids_top20 must be non-empty"

    for row in top20:
        pid = row.get("payout_id")
        cat = row.get("spin_type_category")
        breakdown = row.get("spin_type_breakdown", [])
        # Count active STs (those with hits > 0).
        active_sts = [b for b in breakdown if int(b.get("count", 0)) > 0]
        n_active = len(active_sts)
        if n_active == 0:
            # No firings at all — category may be None (never emitted to top20 in practice).
            continue
        if n_active >= 2:
            assert cat == "mixed", (
                f"pid {pid} fired in {n_active} SpinTypes ({[b['spin_type'] for b in active_sts]}) "
                f"but spin_type_category='{cat}'. Strict binary rule: ≥2 STs → must be 'mixed'. "
                f"Old threshold logic (≥80% dominant share) is forbidden."
            )
        # n_active == 1 → either "paid", "bonus", or "mixed" (per the sole ST's behavior).
        # Specific value is implementation detail; here we only enforce the ≥2 → mixed rule.
