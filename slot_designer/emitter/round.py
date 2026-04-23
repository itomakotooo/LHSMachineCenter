"""Emit one round dict matching existing rawdata schema exactly.

Schema reverse-engineered from rawdata/M1/mode_1/chunk_*.json. Field set
is 17 keys — see tests/fixtures/M1_field_analysis.md. Analyzer's only
hard dependencies on PayoutByPayline / PayoutIdToWinAmount format are:
- ``PAYLINE_RE = r"(\\d+):"`` extracts line_ids from strings like ``"1:14-13(...)"``
- ``_POSITION_RE = r"\\(([0-9,]+)\\)"`` extracts position tuples.

So ``"1:<pid>-<pid>(<positions,>);  "`` is valid. Analyzer reads pay_id
from the PayoutIdToWinAmount dict, not the string.

v5+ M15 (2026-04-23): added SpinType=14 (feature sub-round) and
SpinType=15 (feature end marker) emission. When ``emit_session()`` is
called with a non-empty feature_rounds list, the output is a list of
multiple round dicts: [main trigger spin ST=1 (ReMarks='Trigger'),
ST=14 × N rounds, ST=15 end marker]. Production M15 rawdata uses this
exact structure (verified against rawdata/M15$TopDollarSelector$0$).
"""
from __future__ import annotations

from ..engine.feature_m15 import FeatureRound
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


def emit_feature_round(
    fr: FeatureRound,
    *,
    bet_amount: int,
    last_credits: int,
    spin_times: int,
    rtp_id: int,
) -> dict:
    """Emit a SpinType=14 feature sub-round matching production format.

    Fields align with observed production rawdata for M15 feature rounds:
    12 keys (subset of the ST=1 schema, StopSymbolsByCol is null).
    WinCredits = fr.r_value × bet_amount (the offer value revealed this
    round; analyzer downstream decides sum vs accepted-only semantics).
    """
    return {
        "ReMarks": "",
        "LastCredits": last_credits,
        "CostCredits": 0,
        "WinCredits": int(fr.r_value * bet_amount),
        "BetAmount": 0,
        "StopSymbolsByCol": None,
        "RewardLastNode": [],
        "PayoutByPayline": "",
        "PayoutIdToWinAmount": {},
        "SpinType": 14,
        "SpinTimes": spin_times,
        "RTPId": rtp_id,
    }


def emit_feature_end(*, spin_times: int, rtp_id: int) -> dict:
    """Emit a SpinType=15 feature end marker (production: 5 minimal keys)."""
    return {
        "WinCredits": 0,
        "SpinType": 15,
        "SpinTimes": spin_times,
        "RTPId": rtp_id,
        "IsLackCreditsSpin": False,
    }


def emit_session(
    outcome: SpinOutcome,
    feature_rounds: list[FeatureRound],
    *,
    last_credits: int,
    spin_times: int,
    rtp_id: int,
    feature_trigger_pay_id: int | None = None,
) -> list[dict]:
    """Emit a full spin session as a list of round dicts.

    When feature_rounds is empty → returns a single [ST=1] dict.
    When feature_rounds is non-empty → returns:
      [ST=1 trigger (ReMarks='Trigger'), ST=14 × N rounds, ST=15 end marker]

    Matches production M15$TopDollarSelector$0$ rawdata structure exactly.
    The trigger spin's ReMarks is set to 'Trigger' automatically when its
    scatter_pays contains ``feature_trigger_pay_id`` AND feature_rounds is
    non-empty (i.e., the feature actually fired).
    """
    is_trigger = bool(feature_rounds) and (
        feature_trigger_pay_id is not None
        and any(
            sp.pay_id == feature_trigger_pay_id
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

    if feature_rounds:
        lc = last_credits  # feature rounds don't actually change LC in production;
                           # we keep it flat to mirror observed behavior.
        bet = outcome.bet_amount
        for fr in feature_rounds:
            session.append(emit_feature_round(
                fr,
                bet_amount=bet,
                last_credits=lc,
                spin_times=spin_times,
                rtp_id=rtp_id,
            ))
        session.append(emit_feature_end(spin_times=spin_times, rtp_id=rtp_id))

    return session
