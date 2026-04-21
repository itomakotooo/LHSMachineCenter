"""Emit one round dict matching existing rawdata schema exactly.

Schema reverse-engineered from rawdata/M1/mode_1/chunk_*.json. Field set
is 17 keys — see tests/fixtures/M1_field_analysis.md. Analyzer's only
hard dependencies on PayoutByPayline / PayoutIdToWinAmount format are:
- ``PAYLINE_RE = r"(\\d+):"`` extracts line_ids from strings like ``"1:14-13(...)"``
- ``_POSITION_RE = r"\\(([0-9,]+)\\)"`` extracts position tuples.

So ``"1:<pid>-<pid>(<positions,>);  "`` is valid. Analyzer reads pay_id
from the PayoutIdToWinAmount dict, not the string.
"""
from __future__ import annotations

from ..engine.spin import SpinOutcome


def emit_round(
    outcome: SpinOutcome,
    *,
    last_credits: int,
    spin_times: int,
    rtp_id: int,
) -> dict:
    pay = outcome.pay
    win = 0
    payout_by_payline = ""
    payout_id_to_win: dict[str, int] = {}
    reward_last_node: list[str] = []

    if pay is not None:
        win = int(pay.multiplier * outcome.bet_amount)
        # Upstream position formula (see scripts/infer_paytable._decode_position):
        #   pos = (col+1) * 100 + (row-1),  col & row 0-indexed with
        #   row=1 = middle row (payline for M1-style single-line slots).
        # Real M1 rawdata shows middle-row cells encoded as 100/200/300
        # for col 0/1/2. We were emitting 101/201/301 — off by +1 — which
        # caused infer_paytable to read the TOP row instead of middle,
        # mis-tagging symbol_set as 'Blank' and wild inference as
        # Bar*/Cherry/Seven*. Fixed 2026-04-21.
        positions_str = "".join(
            f"{(c + 1) * 100 + (r - 1)}," for (c, r) in pay.positions
        )
        payout_by_payline = f"1:{pay.pay_id}-{pay.pay_id}({positions_str});  "
        payout_id_to_win = {str(pay.pay_id): win}
        reward_last_node = [f"{pay.pay_id}-"]

    stops_by_col = ["-".join(col_symbols) + "-" for col_symbols in outcome.grid]

    return {
        "ReMarks": "",
        "LastCredits": last_credits,
        "CostCredits": outcome.cost_credits,
        "WinCredits": win,
        "BetAmount": outcome.bet_amount,
        "ReelSkin": "",
        "StopSymbolsByCol": stops_by_col,
        "RewardLastNode": reward_last_node,
        "PayoutByPayline": payout_by_payline,
        "PayoutGroupId": 0,
        "PayLineGroupId": 0,
        "PayoutIdToWinAmount": payout_id_to_win,
        "CurJackpotStoreWin": 0,
        "SpinType": outcome.spin_type,
        "SpinTimes": spin_times,
        "RTPId": rtp_id,
        "IsLackCreditsSpin": False,
    }
