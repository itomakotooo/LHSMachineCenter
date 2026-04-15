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

import json

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
    # Drop StopSymbolsByCol AND WinCredits at once.
    bad_round = _full_round()
    bad_round.pop("StopSymbolsByCol")
    bad_round.pop("WinCredits")
    resp = [{"roundResult": [bad_round]}]
    missing = _check_round_schema(resp)
    assert "StopSymbolsByCol" in missing
    assert "WinCredits" in missing


def test_check_round_schema_payout_by_payline_missing_is_ok():
    # Lose spins legitimately omit PayoutByPayline; the schema check must
    # NOT flag it as drift -- otherwise the very first chunk's first
    # spin (statistically usually a lose spin) would abort every run.
    bad_round = _full_round()
    bad_round.pop("PayoutByPayline")
    resp = [{"roundResult": [bad_round]}]
    assert _check_round_schema(resp) == []


def test_check_round_schema_payout_group_id_missing_is_ok():
    # No-payout spins legitimately omit PayoutGroupId. Same reasoning.
    bad_round = _full_round()
    bad_round.pop("PayoutGroupId")
    resp = [{"roundResult": [bad_round]}]
    assert _check_round_schema(resp) == []


def test_check_round_schema_bet_amount_alone_falls_back_to_cost_credits():
    # BetAmount missing but CostCredits present -> analyzer's existing
    # fallback chain handles it; schema must NOT flag it.
    bad_round = _full_round()
    bad_round.pop("BetAmount")
    bad_round["CostCredits"] = 1
    resp = [{"roundResult": [bad_round]}]
    assert _check_round_schema(resp) == []


def test_check_round_schema_bet_amount_and_cost_credits_both_missing():
    # When neither BetAmount nor CostCredits is present, the analyzer
    # would silently fall back to the chunk-level `bet` argument. That
    # is acceptable but is also the most likely sign of a wholesale
    # rename of both fields, so the schema check flags it.
    bad_round = _full_round()
    bad_round.pop("BetAmount")
    resp = [{"roundResult": [bad_round]}]
    missing = _check_round_schema(resp)
    assert "BetAmount|CostCredits" in missing


def test_check_round_schema_skips_robots_with_no_rounds():
    # First robot has no rounds; second robot has a valid round.
    resp = [
        {"roundResult": []},
        {"roundResult": [_full_round()]},
    ]
    assert _check_round_schema(resp) == []


def test_check_round_schema_required_fields_constant_locked():
    # The required set is intentionally narrow: only fields that should
    # appear on EVERY spin regardless of win/lose state. PayoutByPayline
    # / PayoutGroupId are legitimately absent on lose / no-payout spins
    # so they're checked elsewhere (via empty drilldown signals) rather
    # than as hard schema requirements. Adding here forces explicit code
    # review of false-positive risk.
    assert set(_REQUIRED_ROUND_FIELDS) == {"WinCredits", "StopSymbolsByCol"}


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
    bad.pop("WinCredits")
    patch_post_json(_stub_chunk_resp([bad]))
    rec = _run(spin_times=1)
    assert rec["ok"] is False
    assert "StopSymbolsByCol" in rec["error"]
    assert "WinCredits" in rec["error"]


def test_run_sampling_chunk_lose_spin_first_does_not_abort(patch_post_json):
    """Regression for the 'every run aborts on the first lose spin'
    bug. Lose spins legitimately omit PayoutByPayline + PayoutGroupId;
    the schema check must let them through and treat them as normal
    zero-win rounds."""
    lose_round = _full_round()
    lose_round.pop("PayoutByPayline")
    lose_round.pop("PayoutGroupId")
    patch_post_json(_stub_chunk_resp([lose_round]))
    rec = _run(spin_times=1)
    assert rec["ok"] is True
    assert rec["spins"] == 1
    assert rec["loss_spins"] == 1


def test_run_sampling_chunk_bet_falls_back_to_cost_credits(patch_post_json):
    """BetAmount missing but CostCredits present must NOT abort the
    chunk -- analyzer's existing fallback chain consumes CostCredits."""
    rd = _full_round(WinCredits=2)
    rd.pop("BetAmount")
    rd["CostCredits"] = 5
    patch_post_json(_stub_chunk_resp([rd]))
    rec = _run(spin_times=1)
    assert rec["ok"] is True
    assert rec["bet"] == 5  # CostCredits used as bet


def test_run_sampling_chunk_empty_response(patch_post_json):
    patch_post_json([])
    rec = _run(spin_times=1)
    assert rec["ok"] is False
    assert rec["error"] == "parse_failed_empty_response"


# ---------- top-level shape catches ----------


def test_run_sampling_chunk_top_level_dict_response(patch_post_json):
    """Some upstream machines could return a single robot dict instead of
    a list-of-robots envelope. We don't silently accept it -- we want a
    descriptive error so the operator can ask for support to be added."""
    patch_post_json({"roundResult": "[]", "analysisResult": "..."})
    rec = _run(spin_times=1)
    assert rec["ok"] is False
    assert rec["error"].startswith("response_shape_unexpected:expected_list")
    # The dict's keys are echoed so the operator can see what we actually got.
    assert "roundResult" in rec["error"]
    assert "analysisResult" in rec["error"]


def test_run_sampling_chunk_top_level_string_response(patch_post_json):
    """If the upstream returns a string (e.g. error body that wasn't
    parsed), report the type instead of crashing on iteration."""
    patch_post_json("Internal Server Error")
    rec = _run(spin_times=1)
    assert rec["ok"] is False
    assert rec["error"].startswith("response_shape_unexpected:expected_list")
    assert "got_type=str" in rec["error"]


def test_run_sampling_chunk_list_of_strings(patch_post_json):
    """A list of non-dict items (some malformed envelope) must also be
    caught -- the parsing loop's `for robot in resp` would otherwise
    iterate strings and skip everything, producing parse_failed_zero_chunk
    without telling the operator the real shape problem."""
    patch_post_json(["robot1", "robot2"])
    rec = _run(spin_times=1)
    assert rec["ok"] is False
    assert rec["error"].startswith("response_shape_unexpected:expected_robot_dicts")
    assert "str" in rec["error"]


def test_run_sampling_chunk_list_with_one_dict_passes(patch_post_json):
    """A list with at least one robot dict goes through normally even
    if the rest are non-dicts (defensive against partial corruption).
    The non-dict items are skipped by the existing isinstance check."""
    patch_post_json([{"roundResult": json.dumps([_full_round(WinCredits=5,
                                                              PayoutByPayline="1:5",
                                                              PayoutGroupId=1)])},
                     "garbage"])
    rec = _run(spin_times=1)
    assert rec["ok"] is True
    assert rec["spins"] == 1


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


# ---------- PayoutIdToWinAmount aggregation ----------


def test_run_sampling_chunk_payout_id_basic_aggregation(patch_post_json):
    # 3 winning rounds at PayoutId=6 (300 each), 1 at PayoutId=2 (50),
    # 2 lose rounds (no PayoutIdToWinAmount).
    rounds = (
        [_full_round(WinCredits=300, PayoutByPayline="1:300", PayoutGroupId=0,
                     PayoutIdToWinAmount={"6": 300}) for _ in range(3)]
        + [_full_round(WinCredits=50, PayoutByPayline="2:50", PayoutGroupId=0,
                       PayoutIdToWinAmount={"2": 50})]
        + [_full_round(WinCredits=0) for _ in range(2)]
    )
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=len(rounds))
    assert rec["payout_id_hits"]["6"] == 3
    assert rec["payout_id_hits"]["2"] == 1
    assert rec["payout_id_win"]["6"] == 900  # 3 * 300
    assert rec["payout_id_win"]["2"] == 50
    # Lose rounds don't add anything.
    assert "0" not in rec["payout_id_hits"]


def test_run_sampling_chunk_payout_id_multi_id_per_round(patch_post_json):
    """A single round can win multiple payout ids at once (e.g. wild
    triggers two payouts). Each id gets its own hit_count tick."""
    rounds = [_full_round(
        WinCredits=420, PayoutByPayline="1:200, 5:220", PayoutGroupId=0,
        PayoutIdToWinAmount={"3": 200, "5": 220},
    )]
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=1)
    assert rec["payout_id_hits"] == {"3": 1, "5": 1}
    assert rec["payout_id_win"] == {"3": 200, "5": 220}


def test_run_sampling_chunk_payout_id_zero_amount_still_counts(patch_post_json):
    """PayoutId 666 shows up with amount 0 in real M272 data (special
    indicator). hit_count should still tick so the operator sees that
    the id appeared, even though it doesn't move RTP."""
    rounds = [_full_round(
        WinCredits=0, PayoutByPayline="", PayoutGroupId=0,
        PayoutIdToWinAmount={"666": 0},
    )]
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=1)
    assert rec["payout_id_hits"] == {"666": 1}
    assert rec["payout_id_win"] == {"666": 0}


def test_run_sampling_chunk_payout_id_string_amounts_coerced(patch_post_json):
    """API replays sometimes deliver numeric fields as strings; to_float
    must coerce so the tally stays numeric."""
    rounds = [_full_round(
        WinCredits=100, PayoutByPayline="1:100", PayoutGroupId=0,
        PayoutIdToWinAmount={"4": "100"},
    )]
    patch_post_json(_stub_chunk_resp(rounds))
    rec = _run(spin_times=1)
    assert rec["payout_id_win"]["4"] == 100.0


def test_run_sampling_chunk_payout_id_missing_dict_is_safe(patch_post_json):
    """Old reports / unfamiliar machines may omit PayoutIdToWinAmount
    entirely; the chunk still completes with an empty payout_id tally."""
    rd = _full_round(WinCredits=100)
    rd.pop("PayoutIdToWinAmount", None)
    patch_post_json(_stub_chunk_resp([rd]))
    rec = _run(spin_times=1)
    assert rec["ok"] is True
    assert rec["payout_id_hits"] == {}
    assert rec["payout_id_win"] == {}
