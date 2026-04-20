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
        positions_str = "".join(f"{(c + 1) * 100 + r}," for (c, r) in pay.positions)
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
