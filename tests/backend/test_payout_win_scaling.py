"""Regression tests for the pay_id-scaling aggregation rule.

Some machines report bonus rounds where
``sum(PayoutIdToWinAmount.values()) > WinCredits`` — the Payout
dict enumerates *potential / alternative* rewards, but the player
only actually receives ``WinCredits``. M209 "move" rounds show
this on 103/218 bonus rounds (e.g. ``Win=10000 Payout={'2':20000}``
or ``Win=10000 Payout={'2':10000,'3':5000}``).

Without the scaling rule, the analyzer credits the RAW Payout
values to each pay_id's ``payout_id_win``, so the sum of
``payout_ids_top20.rtp_contribution_pp`` exceeds ``summary.rtp``
by the ratio ``(sum_Payout - WinCredits) / effective_bet_for_rtp``
(M209 live probe: sum=104.43pp vs rtp=95.58% = +8.85pp delta).

Iter 4 fix (2026-04-23): when ``sum(Payout) > WinCredits > 0``,
scale each pay_id's credit to its share of WinCredits. When they
match (normal case, almost every machine / every paid round),
behavior is identical to pre-fix.

These tests hit ``parse_chunk_response`` directly with synthetic
responses — no live HTTP, no fixtures on disk. The scaling rule is
pure round-level code so this is the narrowest possible lock on
the invariant.
"""
from __future__ import annotations

import json

import pytest

from fresh_slotlab.player_impact_analyzer import parse_chunk_response


def _robot(rounds: list[dict]) -> dict:
    """Wrap a list of rounds into the outer robot envelope upstream
    returns (robot dict with ``roundResult`` = JSON string of the
    round list)."""
    return {"roundResult": json.dumps(rounds)}


def _round(
    win: float,
    payout: dict | None,
    *,
    cost: float | None = 1000,
    spin_type: int = 1,
    remarks: str = "",
) -> dict:
    """Minimal round. StopSymbolsByCol required by the analyzer's
    per-round schema check."""
    r = {
        "WinCredits": win,
        "BetAmount": 1000,
        "CostCredits": cost,
        "StopSymbolsByCol": ["a-b-c", "a-b-c", "a-b-c"],
        "SpinType": spin_type,
        "ReMarks": remarks,
    }
    if payout is not None:
        r["PayoutIdToWinAmount"] = payout
    return r


class TestNormalPathUnchanged:
    def test_win_equals_payout_sum_no_scaling(self):
        """M15/M273/most-machines case: sum(Payout) == WinCredits.
        Each pay_id receives its raw value, unchanged from pre-fix."""
        resp = [_robot([
            _round(win=500, payout={"9": 500}),
            _round(win=1500, payout={"1": 1000, "5": 500}),
        ])]
        chunk = parse_chunk_response(resp, 0, 1000)
        pay_win = chunk["payout_id_win"]
        assert pay_win["9"] == 500
        assert pay_win["1"] == 1000
        assert pay_win["5"] == 500

    def test_paid_round_with_payline_win_preserved(self):
        """Normal paid round with one payline: WinCredits == Payout
        sum == one-pay_id's value. Trivially unscaled."""
        resp = [_robot([
            _round(win=2000, payout={"7": 2000}),
        ])]
        chunk = parse_chunk_response(resp, 0, 1000)
        assert chunk["payout_id_win"]["7"] == 2000


class TestM209StylePayoutOverWin:
    """M209 bonus round: Win < sum(Payout). Upstream's Payout lists
    potential alternative rewards; the player receives only
    WinCredits. Crediting raw Payout inflates RTP."""

    def test_two_pay_ids_proportional_scaling(self):
        """M209 sample: Win=10000 Payout={'2':10000,'3':5000} →
        sum(Payout)=15000, ratio 2:1. pay_id 2 credited 10000*(10/15)
        = 6666.67, pay_id 3 credited 10000*(5/15) = 3333.33. Total
        = 10000, matching WinCredits."""
        resp = [_robot([
            _round(win=10000, payout={"2": 10000, "3": 5000},
                   cost=None, spin_type=36, remarks="move"),
        ])]
        chunk = parse_chunk_response(resp, 0, 1000)
        pay_win = chunk["payout_id_win"]
        assert abs(pay_win["2"] - 10000 * (10/15)) < 0.01
        assert abs(pay_win["3"] - 10000 * (5/15)) < 0.01
        # Total credited = WinCredits (the invariant that fixes the
        # sum>rtp bug).
        assert abs(pay_win["2"] + pay_win["3"] - 10000) < 0.01

    def test_single_pay_id_with_payout_over_win(self):
        """M209 sample: Win=10000 Payout={'2':20000}. Payout's single
        value exceeds Win — scaling factor 10000/20000 = 0.5, so
        pay_id 2 gets 10000 not 20000."""
        resp = [_robot([
            _round(win=10000, payout={"2": 20000},
                   cost=None, spin_type=36),
        ])]
        chunk = parse_chunk_response(resp, 0, 1000)
        assert chunk["payout_id_win"]["2"] == 10000

    def test_rtp_parity_across_mixed_rounds(self):
        """Synthetic M209-shaped robot: 1 paid round + 3 move-style
        bonus rounds with Payout > Win. Sum of pay_id credits must
        equal sum of WinCredits (RTP parity at the aggregation
        level, which is the invariant that determines whether
        sum(payout_ids_top20.rtp_pp) ≈ summary.rtp fleet-wide)."""
        resp = [_robot([
            # Paid round, normal 1:1
            _round(win=5000, payout={"9": 5000}),
            # 3 bonus rounds with Win < sum(Payout)
            _round(win=10000, payout={"2": 10000, "3": 5000},
                   cost=None, spin_type=36),
            _round(win=10000, payout={"2": 20000},
                   cost=None, spin_type=36),
            _round(win=3000, payout={"3": 4000, "4": 2000},
                   cost=None, spin_type=36),
        ])]
        chunk = parse_chunk_response(resp, 0, 1000)
        total_win_observed = sum(chunk["payout_id_win"].values())
        total_win_from_rounds = 5000 + 10000 + 10000 + 3000
        assert abs(total_win_observed - total_win_from_rounds) < 0.01, (
            f"pay_id win sum {total_win_observed} diverges from "
            f"actual WinCredits sum {total_win_from_rounds} — "
            f"scaling rule broke RTP parity"
        )


class TestWinGreaterThanPayoutUnchanged:
    def test_win_exceeds_payout_sum_no_upscale(self):
        """Rare edge case: WinCredits > sum(Payout). Means there's
        "uncredited win" not attributed to any specific pay_id. We
        keep the raw Payout values as-is rather than scale up —
        the delta remains untraced at the pay_id level (session-
        level helper or the summary.rtp aggregate still sees it)."""
        resp = [_robot([
            _round(win=10000, payout={"9": 5000}),  # Win > sum(Payout)
        ])]
        chunk = parse_chunk_response(resp, 0, 1000)
        # pay_id 9 keeps its raw 5000 (no upscale).
        assert chunk["payout_id_win"]["9"] == 5000


class TestWinZeroWithPayout:
    def test_zero_win_pay_id_not_scaled(self):
        """Trigger round shape: Win=0, Payout={'666':0}. No scaling
        applies (scaling requires Win > 0). pay_id 666 still gets
        a hit counted."""
        resp = [_robot([
            _round(win=0, payout={"666": 0}, remarks="Trigger"),
        ])]
        chunk = parse_chunk_response(resp, 0, 1000)
        assert chunk["payout_id_win"]["666"] == 0
        assert chunk["payout_id_hits"]["666"] == 1


class TestMalformedInputs:
    def test_non_dict_payout_treated_as_none(self):
        """If upstream returns PayoutIdToWinAmount as a string / list
        / other non-dict, the aggregator should skip it rather than
        crash. Scaling rule doesn't need to cope with that —
        earlier ``isinstance`` check handles it."""
        resp = [_robot([
            {"WinCredits": 1000, "BetAmount": 1000, "CostCredits": 1000,
             "StopSymbolsByCol": ["a-b-c", "a-b-c", "a-b-c"],
             "SpinType": 1, "PayoutIdToWinAmount": "not a dict"},
        ])]
        # Should parse without error; no pay_id credited.
        chunk = parse_chunk_response(resp, 0, 1000)
        assert chunk["payout_id_win"] == {}

    def test_non_numeric_payout_value_treated_as_zero(self):
        """Defensive: to_float coerces non-numeric to 0. Scaling
        denominator becomes 0; rule falls back to raw values.
        Nothing crashes."""
        resp = [_robot([
            _round(win=1000, payout={"9": "not a number"}),
        ])]
        chunk = parse_chunk_response(resp, 0, 1000)
        # to_float("not a number", default=0) → 0 for both paths.
        assert chunk["payout_id_win"]["9"] == 0
