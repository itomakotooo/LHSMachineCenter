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
    scatter_pays = outcome.scatter_pays or []
    total_win = 0
    payout_by_payline_parts: list[str] = []
    payout_id_to_win: dict[str, int] = {}
    reward_last_node: list[str] = []

    # Main payline pay (at most 1 per spin for single-payline machines).
    # Upstream position formula (see scripts/infer_paytable._decode_position):
    #   pos = (col+1) * 100 + (row-1),  col & row 0-indexed with
    #   row=1 = middle row (payline for M1-style single-line slots).
    if pay is not None:
        win = int(pay.multiplier * outcome.bet_amount)
        total_win += win
        positions_str = "".join(
            f"{(c + 1) * 100 + (r - 1)}," for (c, r) in pay.positions
        )
        payout_by_payline_parts.append(
            f"1:{pay.pay_id}-{pay.pay_id}({positions_str});  "
        )
        payout_id_to_win[str(pay.pay_id)] = win
        reward_last_node.append(f"{pay.pay_id}-")

    # v5 M15: scatter-triggered pays coexist in PayoutIdToWinAmount. M15's
    # pay_id 666 fires with win=0 on topdollar landing reel 3 payline.
    # line_id=-1 in production rawdata for scatter pays — encoded in the
    # PayoutByPayline string as the negative line prefix.
    for sp in scatter_pays:
        sp_win = int(sp.multiplier * outcome.bet_amount)
        total_win += sp_win
        # Accumulate into existing pay_id if already present (rare; scatter
        # symbols typically have distinct pay_ids from payline pays).
        payout_id_to_win[str(sp.pay_id)] = (
            payout_id_to_win.get(str(sp.pay_id), 0) + sp_win
        )
        sp_positions_str = "".join(
            f"{(c + 1) * 100 + (r - 1)}," for (c, r) in sp.positions
        )
        # Scatter pays use negative line_id in upstream encoding:
        payout_by_payline_parts.append(
            f"-1:{sp.pay_id}-{sp.pay_id}({sp_positions_str});  "
        )
        reward_last_node.append(f"{sp.pay_id}-")

    payout_by_payline = "".join(payout_by_payline_parts)
    stops_by_col = ["-".join(col_symbols) + "-" for col_symbols in outcome.grid]

    return {
        "ReMarks": "",
        "LastCredits": last_credits,
        "CostCredits": outcome.cost_credits,
        "WinCredits": total_win,
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
