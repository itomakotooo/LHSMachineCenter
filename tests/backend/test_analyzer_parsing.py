"""Round-level parsing + schema-drift coverage for the player-impact
analyzer. Tests bypass the live HTTP sampling endpoint by monkeypatching
``post_json`` on the analyzer module so a crafted response stands in for
a real chunk.

Goals
-----
1. Lock the schema sanity check (`_check_round_schema`) so a future
   upstream API field rename is caught immediately instead of producing
   silent all-zero metrics.
2. Lock the multiplier-bucket classification against the 12-bin schema.
3. Lock the payline winning-symbol heuristic (leftmost-3-col intersection).
4. Lock the PayoutGroupId aggregation so the payid drilldown stays
   non-empty when the API actually returns the field.
"""
from __future__ import annotations

import pytest

from fresh_slotlab import player_impact_analyzer as ana
from fresh_slotlab.player_impact_analyzer import (
    _REQUIRED_ROUND_FIELDS,
    _check_round_schema,
    return_bucket,
)


# ---------- _check_round_schema ----------


def _full_round(**override):
    """Default round shape mirroring the real test API:
    - PayoutByPayline is "id:winamount" comma-joined (parse_paylines uses
      the regex `(\\d+):` to extract ids).
    - StopSymbolsByCol entries are dash-separated symbol stacks per col
      (split_symbols splits on "-").
    """
    base = {
        "BetAmount": 1,
        "WinCredits": 0,
        "PayoutByPayline": "",
        "StopSymbolsByCol": ["cherry-blank-blank", "blank-blank-blank", "blank-blank-blank", "blank-blank-blank", "blank-blank-blank"],
        "PayoutGroupId": 0,
    }
    base.update(override)
    return base


def test_check_round_schema_empty_or_invalid_returns_empty():
    # Empty list / non-list / no rounds: nothing to validate, downstream
    # parse_failed_zero_chunk will catch the empty case.
    assert _check_round_schema([]) == []
    assert _check_round_schema(None) == []  # type: ignore[arg-type]
    assert _check_round_schema([{}]) == []
    assert _check_round_schema([{"roundResult": []}]) == []


def test_check_round_schema_full_round_passes():
    resp = [{"roundResult": [_full_round()]}]
    assert _check_round_schema(resp) == []


def test_check_round_schema_missing_wincredits_detected():
    # Realistic drift: API renames WinCredits to winCredits.
    bad_round = _full_round()
    bad_round["winCredits"] = bad_round.pop("WinCredits")
    resp = [{"roundResult": [bad_round]}]
    missing = _check_round_schema(resp)
    assert "WinCredits" in missing
    # Other fields still pass through.
    assert "BetAmount" not in missing


def test_check_round_schema_missing_multiple_fields():
    # Drop StopSymbolsByCol AND PayoutGroupId at once.
    bad_round = _full_round()
    bad_round.pop("StopSymbolsByCol")
    bad_round.pop("PayoutGroupId")
    resp = [{"roundResult": [bad_round]}]
    missing = _check_round_schema(resp)
    assert "StopSymbolsByCol" in missing
    assert "PayoutGroupId" in missing
    assert "WinCredits" not in missing


def test_check_round_schema_skips_robots_with_no_rounds():
    # First robot has no rounds; second robot has a valid round.
    resp = [
        {"roundResult": []},
        {"roundResult": [_full_round()]},
    ]
    assert _check_round_schema(resp) == []


def test_check_round_schema_required_fields_constant_locked():
    # If you add a new required field here, make sure run_sampling_chunk
    # actually depends on it (otherwise you break old reports for no
    # reason). This test just locks the current set so additions are
    # explicit code review.
    assert set(_REQUIRED_ROUND_FIELDS) == {
        "BetAmount",
        "WinCredits",
        "PayoutByPayline",
        "StopSymbolsByCol",
        "PayoutGroupId",
    }


# ---------- run_sampling_chunk via monkeypatch ----------


def _stub_chunk_resp(rounds):
    """Wrap a list of round dicts as a single-robot response shape."""
    return [{"roundResult": rounds}]


@pytest.fixture
def patch_post_json(monkeypatch):
    """Yield a setter that pins ana.post_json to return a canned response."""
    def _set(resp):
        monkeypatch.setattr(ana, "post_json", lambda *_a, **_kw: resp)
    return _set


def _run(spin_times=10, bet=1):
    return ana.run_sampling_chunk(
        chunk_index=0,
        machine="M14",
        rtp_mode=1,
        bet=bet,
        spin_times=spin_times,
        robot_count=1,
        timeout=10.0,
    )


def test_run_sampling_chunk_happy_path(patch_post_json):
    rounds = [_full_round(WinCredits=5, PayoutByPayline="1:5", PayoutGroupId=12) for _ in range(10)]
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run()
    assert rec["ok"] is True
    assert rec["spins"] == 10
    assert rec["bet"] == 10  # 10 spins * BetAmount=1
    assert rec["win"] == 50  # 10 * WinCredits=5
    assert rec["win_spins"] == 10
    assert rec["loss_spins"] == 0


def test_run_sampling_chunk_schema_drift_aborts_chunk(patch_post_json):
    """Field-rename drift: WinCredits -> winCredits. The chunk must fail
    fast with a structured schema_drift error rather than silently
    producing 0 RTP.
    """
    bad = _full_round(WinCredits=5)
    bad["winCredits"] = bad.pop("WinCredits")
    patch_post_json(_stub_chunk_resp([bad]))
    rec = _run(spin_times=1)
    assert rec["ok"] is False
    assert rec["error"].startswith("schema_drift_missing_fields:")
    assert "WinCredits" in rec["error"]


def test_run_sampling_chunk_schema_drift_multiple_fields(patch_post_json):
    bad = _full_round()
    bad.pop("StopSymbolsByCol")
    bad.pop("PayoutGroupId")
    patch_post_json(_stub_chunk_resp([bad]))
    rec = _run(spin_times=1)
    assert rec["ok"] is False
    assert "StopSymbolsByCol" in rec["error"]
    assert "PayoutGroupId" in rec["error"]


def test_run_sampling_chunk_empty_response(patch_post_json):
    patch_post_json([])
    rec = _run(spin_times=1)
    assert rec["ok"] is False
    assert rec["error"] == "parse_failed_empty_response"


def test_run_sampling_chunk_zero_chunk_failure(patch_post_json):
    # Robot has no roundResult => existing parse_failed_zero_chunk path.
    patch_post_json([{"roundResult": []}])
    rec = _run(spin_times=1)
    assert rec["ok"] is False
    assert rec["error"] == "parse_failed_zero_chunk"


# ---------- multiplier bucket classification ----------


@pytest.mark.parametrize(
    "ret_x, expected",
    [
        (0.0, "eq0"),
        (0.5, "gt0_lt1"),
        (0.99, "gt0_lt1"),
        (1.0, "ge1_lt5"),
        (4.99, "ge1_lt5"),
        (5.0, "ge5_lt10"),
        (10.0, "ge10_lt20"),
        (20.0, "ge20_lt50"),
        (50.0, "ge50_lt100"),
        (100.0, "ge100_lt200"),
        (200.0, "ge200_lt500"),
        (500.0, "ge500_lt1000"),
        (1000.0, "ge1000_lt5000"),
        (5000.0, "ge5000"),
        (99999.0, "ge5000"),
    ],
)
def test_return_bucket_12_bin_schema(ret_x, expected):
    assert return_bucket(ret_x) == expected


def test_run_sampling_chunk_buckets_classification(patch_post_json):
    # Build spins covering several buckets; assert tally uses new keys.
    rounds = (
        [_full_round(WinCredits=0)]                 # eq0
        + [_full_round(WinCredits=0)]               # eq0 again
        + [_full_round(WinCredits=15, PayoutByPayline="1:15", PayoutGroupId=3)]  # ge10_lt20
        + [_full_round(WinCredits=120, PayoutByPayline="1:120", PayoutGroupId=4)]  # ge100_lt200
        + [_full_round(WinCredits=7000, PayoutByPayline="1:7000", PayoutGroupId=5)]  # ge5000
    )
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=len(rounds))
    assert rec["multiplier_bucket_spins"]["eq0"] == 2
    assert rec["multiplier_bucket_spins"]["ge10_lt20"] == 1
    assert rec["multiplier_bucket_spins"]["ge100_lt200"] == 1
    assert rec["multiplier_bucket_spins"]["ge5000"] == 1


# ---------- payline winning-symbol inference ----------


def test_run_sampling_chunk_payline_winning_symbol_left3_intersection(patch_post_json):
    # 'wild' appears in leftmost 3 cols; line 1 paid -> credit 'wild'.
    rounds = [
        _full_round(
            WinCredits=10,
            PayoutByPayline="1:10",
            StopSymbolsByCol=["wild-blank", "wild-cherry", "wild-blank", "blank-blank", "blank-blank"],
            PayoutGroupId=5,
        )
    ]
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=1)
    assert rec["payline_winning_symbols"] == {"1": {"wild": 1}}


def test_run_sampling_chunk_payline_winning_symbol_no_intersection_fallback(patch_post_json):
    # Leftmost 3 cols don't share any symbol -> falls back to leftmost
    # column's first symbol.
    rounds = [
        _full_round(
            WinCredits=2,
            PayoutByPayline="9:2",
            StopSymbolsByCol=["cherry-blank", "lemon-lemon", "bell-bell", "blank-blank", "blank-blank"],
            PayoutGroupId=2,
        )
    ]
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=1)
    # Fallback picked one symbol from the leftmost column's set
    # ({"cherry", "blank"} since col 0 = "cherry-blank"). Set iteration
    # order isn't guaranteed, so just assert the line was credited with
    # exactly one symbol drawn from that set.
    syms = rec["payline_winning_symbols"]["9"]
    assert sum(syms.values()) == 1
    assert set(syms.keys()).issubset({"cherry", "blank"})


def test_run_sampling_chunk_payline_winning_symbol_multi_line(patch_post_json):
    # Two lines paid in one spin; both get credited with the shared symbol.
    rounds = [
        _full_round(
            WinCredits=10,
            PayoutByPayline="1:5, 5:5",
            StopSymbolsByCol=["7-blank", "7-blank", "7-blank", "blank-blank", "blank-blank"],
            PayoutGroupId=3,
        )
    ]
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=1)
    assert rec["payline_winning_symbols"]["1"] == {"7": 1}
    assert rec["payline_winning_symbols"]["5"] == {"7": 1}


# ---------- PayoutGroupId aggregation ----------


def test_run_sampling_chunk_payout_group_aggregation(patch_post_json):
    # 3 spins to group 12, 2 spins to group 0 (no payout), 1 spin to group 7.
    rounds = (
        [_full_round(WinCredits=5, PayoutByPayline="1:5", PayoutGroupId=12) for _ in range(3)]
        + [_full_round(WinCredits=0, PayoutGroupId=0) for _ in range(2)]
        + [_full_round(WinCredits=20, PayoutByPayline="1:20", PayoutGroupId=7)]
    )
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=len(rounds))
    assert rec["payout_group_hits"]["12"] == 3
    assert rec["payout_group_hits"]["0"] == 2
    assert rec["payout_group_hits"]["7"] == 1
    # Win sums per group: group 12 has 3 spins * 5 = 15; group 7 has 20.
    assert rec["payout_group_win"]["12"] == 15
    assert rec["payout_group_win"]["7"] == 20
    # Group 0 = no payout, win sum stays at 0.
    assert rec["payout_group_win"].get("0", 0) == 0


def test_run_sampling_chunk_payout_group_string_id_normalized(patch_post_json):
    # Some API replays return the id as a string; analyzer must coerce.
    rounds = [_full_round(WinCredits=3, PayoutByPayline="2:3", PayoutGroupId="42")]
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=1)
    assert rec["payout_group_hits"]["42"] == 1


def test_run_sampling_chunk_payout_group_garbage_id_falls_back_to_zero(patch_post_json):
    # Non-numeric id -> caught by try/except in process_chunk, falls to 0.
    rounds = [_full_round(WinCredits=0, PayoutGroupId="bonus")]
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=1)
    assert rec["payout_group_hits"]["0"] == 1
