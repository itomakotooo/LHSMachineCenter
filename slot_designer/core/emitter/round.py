"""Emit one round dict matching existing rawdata schema exactly.

Schema reverse-engineered from single-line-style production rawdata. Field set
is 17 keys. Analyzer's only hard dependencies on PayoutByPayline /
PayoutIdToWinAmount format are:
- ``PAYLINE_RE = r"(\\d+):"`` extracts line_ids from strings like ``"1:14-13(...)"``
- ``_POSITION_RE = r"\\(([0-9,]+)\\)"`` extracts position tuples.

So ``"1:<pid>-<pid>(<positions,>);  "`` is valid. Analyzer reads pay_id
from the PayoutIdToWinAmount dict, not the string.

Plugin extension (ARCHITECTURE.md §3): when ``emit_session`` is called
with a non-empty ``feature_rounds`` list, the plugin's
``emit_extra_rounds`` produces the per-machine sub-round + end-marker
dicts (machine-specific SpinTypes + field schema). Generic emitter
never hardcodes machine-specific spin type numbers.
"""
from __future__ import annotations

from typing import Any

from ..engine.feature_protocol import FeaturePlugin
from ..engine.spin import SpinOutcome


def emit_round(
    outcome: SpinOutcome,
    *,
    last_credits: int,
    spin_times: int,
    rtp_id: int,
    remarks: str = "",
) -> dict:
    pay = outcome.pay
    scatter_pays = outcome.scatter_pays or []
    total_win = 0
    payout_by_payline_parts: list[str] = []
    payout_id_to_win: dict[str, int] = {}
    reward_last_node: list[str] = []

    # Main payline pay (at most 1 per spin for single-payline machines).
    # Upstream position formula:
    #   pos = (col+1) * 100 + (row-1),  col & row 0-indexed with
    #   row=1 = middle row (payline for single-line slots).
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

    # Scatter-triggered pays coexist in PayoutIdToWinAmount alongside the
    # main payline pay. Scatter pays use line_id=-1 in upstream encoding
    # (negative line prefix in PayoutByPayline string).
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
        "ReMarks": remarks,
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


def emit_session(
    outcome: SpinOutcome,
    feature_rounds: list[Any],
    *,
    last_credits: int,
    spin_times: int,
    rtp_id: int,
    plugin: FeaturePlugin | None = None,
) -> list[dict]:
    """Emit a full spin session as a list of round dicts.

    When ``feature_rounds`` is empty → returns ``[main_paid_round]``.
    When ``feature_rounds`` is non-empty → returns
    ``[main_paid_round (ReMarks='Trigger'), <plugin extras>]``
    where ``<plugin extras>`` is whatever the machine plugin's
    ``emit_extra_rounds`` produces (ST=14 reveals + ST=15 end marker
    in the machine case; some other machine could emit different schemas).

    The trigger spin's ReMarks is set to 'Trigger' when feature_rounds
    is non-empty AND its scatter_pays contains the plugin's
    trigger_pay_id (i.e., the feature actually fired).
    """
    is_trigger = bool(feature_rounds) and (
        plugin is not None
        and plugin.trigger_pay_id is not None
        and any(
            sp.pay_id == plugin.trigger_pay_id
            for sp in (outcome.scatter_pays or [])
        )
    )
    remarks = "Trigger" if is_trigger else ""

    main = emit_round(
        outcome,
        last_credits=last_credits,
        spin_times=spin_times,
        rtp_id=rtp_id,
        remarks=remarks,
    )
    session = [main]

    if feature_rounds and plugin is not None:
        extras = plugin.emit_extra_rounds(
            main,
            feature_rounds,
            last_credits=last_credits,
            spin_times=spin_times,
            rtp_id=rtp_id,
            bet_amount=outcome.bet_amount,
        )
        session.extend(extras)

    return session
