"""M279 rawdata round emitter.

M279's per-round JSON differs from M1/M15 in 4 ways that ``emit_round``
in round.py doesn't cover:

  1. **Multi-line PayoutByPayline**: 9 paylines on the grid, each can
     fire a separate pay. Format becomes "1:6-6(...);  2:6-6(...);  ..."
     concatenated, with ALL line ids the spin hit.

  2. **Per-pay aggregated PayoutIdToWinAmount**: when multiple paylines
     hit the SAME pay_id, their wins SUM under a single dict key
     (matches production rawdata observation).

  3. **AccCredits / CollectCount / CreditsSymbols**: collect-meter
     fields present on ST=140 paid rounds, omitted on ST=36/2/102
     free rounds. Production rawdata shows these as top-level keys
     on ST=140 only.

  4. **ReelSkin = mode number** (1/2/5/7) per real M279 cfg's skinId
     mapping. M1/M15/M37 use ReelSkin="" (irrelevant for those).

Spin types emitted:
  - ST=140 (paid)              full schema + collect fields + grid + line wins
  - ST=36  (MoveSpin / nudge)  full schema + grid + line wins (no collect)
  - ST=2   (Wheel)             minimal schema (NULL grid, ReMarks=
                               "WheelSpin CellIndex N; WheelId 1;",
                               WinCredits = wheel cell value)
  - ST=102 (BuffMap)           minimal trigger marker (no win, no grid)
"""
from __future__ import annotations

from ..engine.m279.engine import (
    ST_BUFFMAP,
    ST_NUDGE,
    ST_PAID,
    ST_WHEEL,
    M279Round,
)


def _encode_position(col: int, row: int) -> int:
    """Match the M1/M15 position encoding used by the upstream
    analyzer's PAYLINE_RE: pos = (col+1)*100 + (row-1).

    Examples (3-row grid):
      col 0 row 0 → 100*1 + (0-1) = 99
      col 1 row 1 → 100*2 + (1-1) = 200
      col 2 row 2 → 100*3 + (2-1) = 301
    """
    return (col + 1) * 100 + (row - 1)


def _build_payouts_payline(rd: M279Round) -> tuple[str, dict[str, int], list[str]]:
    """Compute (PayoutByPayline string, PayoutIdToWinAmount dict,
    RewardLastNode list) for a multi-line round.

    Multi-line aggregation:
      - PayoutIdToWinAmount: same pay_id across multiple lines → wins
        sum into a single dict key.
      - PayoutByPayline: one record per (line_id, pay_id) pair, in line
        order (1, 2, 3, ...). Positions are the (col, row) cells of
        that pay's positions tuple — already line-specific in M279
        thanks to evaluate_all_paylines's position remapping.
      - RewardLastNode: one entry per pay_id appearing in the round
        (deduped, in first-occurrence order).
    """
    if not rd.pay_results:
        return "", {}, []

    line_records: list[str] = []
    payout_id_to_win: dict[str, int] = {}
    reward_last_node: list[str] = []
    seen_pay_ids: set[int] = set()

    # Sort pay_results by line_id (= the row index from positions[0][1]
    # is not the line_id directly; we infer line_id by matching positions
    # against the spec's payline list — but the engine doesn't pass line_id
    # through. For now assign sequential 1..9 in evaluation order, which
    # matches our spec's evaluate_all_paylines iteration order).
    #
    # SAFER: use the order pay_results came in (evaluate_all_paylines
    # iterates paylines spec order, so list index + 1 = line_id when no
    # paylines are filtered out — but they ARE filtered when None pays
    # drop out). We need the line_id explicitly. Engine passes positions
    # but not line_id; the emitter receives a parallel list of line_ids.
    # → handled by caller via _build_for_paid which has the spec.
    raise NotImplementedError(
        "_build_payouts_payline shouldn't be called directly; use the "
        "build_*_round wrappers which know the line_id mapping."
    )


def _line_id_for_positions(
    positions: tuple,
    paylines_spec: list[list[tuple[int, int]]],
) -> int | None:
    """Given a pay's positions tuple, find which payline it came from.

    Brute-force matches by exact positions equality. This is O(9) per
    pay; on 9-line M279 with typical <5 line wins per spin, total cost
    is negligible.
    """
    pos_set = tuple(tuple(p) for p in positions)
    for line_idx, line_positions in enumerate(paylines_spec):
        line_set = tuple(tuple(p) for p in line_positions)
        if pos_set == line_set:
            return line_idx + 1  # line_ids are 1-indexed
    return None


def _emit_paid_or_nudge_dict(
    rd: M279Round,
    *,
    last_credits: int,
    spin_times: int,
    rtp_id: int,
    paylines_spec: list[list[tuple[int, int]]],
    reel_skin: int | str = "",
) -> dict:
    """Build the round dict for ST=140 (paid) or ST=36 (MoveSpin)."""
    payout_by_payline_parts: list[str] = []
    payout_id_to_win: dict[str, int] = {}
    reward_last_node: list[str] = []
    seen_pay_ids: set[int] = set()

    # Build records in line-id order
    pay_to_lines: dict[int, list[tuple[int, tuple, int]]] = {}
    for pay in rd.pay_results:
        line_id = _line_id_for_positions(pay.positions, paylines_spec)
        if line_id is None:
            # Fallback: pay's positions don't match any spec line — this
            # shouldn't happen if engine + spec are consistent. Skip the
            # line record but still attribute the win to PayoutIdToWinAmount
            # so the analyzer's RTP arithmetic stays correct.
            line_id = 0
        win_credits = int(pay.multiplier * rd.bet_amount)
        pay_to_lines.setdefault(line_id, []).append(
            (pay.pay_id, pay.positions, win_credits)
        )

    for line_id in sorted(pay_to_lines.keys()):
        if line_id == 0:
            continue  # skip unmapped pays in PayoutByPayline string
        for pay_id, positions, win in pay_to_lines[line_id]:
            positions_str = "".join(
                f"{_encode_position(c, r)}," for (c, r) in positions
            )
            payout_by_payline_parts.append(
                f"{line_id}:{pay_id}-{pay_id}({positions_str});  "
            )

    # Aggregate wins by pay_id (multi-line same pay_id → sum)
    for pay in rd.pay_results:
        win = int(pay.multiplier * rd.bet_amount)
        key = str(pay.pay_id)
        payout_id_to_win[key] = payout_id_to_win.get(key, 0) + win
        if pay.pay_id not in seen_pay_ids:
            seen_pay_ids.add(pay.pay_id)
            reward_last_node.append(f"{pay.pay_id}-")

    payout_by_payline = "".join(payout_by_payline_parts)
    grid = rd.grid or [[], [], []]
    stops_by_col = ["-".join(col_symbols) + "-" for col_symbols in grid]

    base = {
        "ReMarks": rd.remarks,
        "LastCredits": last_credits,
        "CostCredits": rd.cost_credits,
        "WinCredits": rd.win_credits,
        "BetAmount": rd.bet_amount,
        "ReelSkin": reel_skin,
        "StopSymbolsByCol": stops_by_col,
        "RewardLastNode": reward_last_node,
        "PayoutByPayline": payout_by_payline,
        "PayoutGroupId": 0,
        "PayLineGroupId": 0,
        "PayoutIdToWinAmount": payout_id_to_win,
        "CurJackpotStoreWin": 0,
        "SpinType": rd.spin_type,
        "SpinTimes": spin_times,
        "RTPId": rtp_id,
        "IsLackCreditsSpin": False,
    }
    # ST=140 carries collect-meter fields; ST=36 omits them per rawdata
    if rd.spin_type == ST_PAID:
        if rd.acc_credits is not None:
            base["AccCredits"] = rd.acc_credits
        if rd.collect_count is not None:
            base["CollectCount"] = rd.collect_count
        if rd.credits_symbols is not None:
            base["CreditsSymbols"] = rd.credits_symbols
        # SymbolIndexToRewards is "{}" string in production for non-bonus
        # paid rounds; emit empty JSON object for analyzer compatibility.
        base["SymbolIndexToRewards"] = "{}"
    return base


def _emit_wheel_dict(
    rd: M279Round,
    *,
    last_credits: int,
    spin_times: int,
    rtp_id: int,
) -> dict:
    """Build ST=2 wheel round (minimal schema — NULL grid, no payouts)."""
    # Wheel pay maps to PayoutIdToWinAmount under the multiplier-keyed
    # pay_id (5/10/20/30/50/100). Compute multiplier from win_credits /
    # bet_amount.
    mult = rd.win_credits // rd.bet_amount if rd.bet_amount else 0
    return {
        "ReMarks": rd.remarks,
        "LastCredits": last_credits,
        "WinCredits": rd.win_credits,
        "StopSymbolsByCol": ["NULL", "NULL", "NULL"],
        "SpinType": rd.spin_type,
        "SpinTimes": spin_times,
        "RTPId": rtp_id,
        "IsLackCreditsSpin": False,
    }


def _emit_buffmap_dict(
    rd: M279Round,
    *,
    last_credits: int,
    spin_times: int,
    rtp_id: int,
) -> dict:
    """Build ST=102 BuffMap round (trigger-only marker; no win, no grid).
    Production rawdata shows minimal field set."""
    return {
        "ReMarks": rd.remarks,
        "LastCredits": last_credits,
        "WinCredits": 0,
        "SpinType": rd.spin_type,
        "SpinTimes": spin_times,
        "RTPId": rtp_id,
        "IsLackCreditsSpin": False,
    }


def emit_m279_session(
    rounds: list[M279Round],
    *,
    last_credits: int,
    spin_times: int,
    rtp_id: int,
    paylines_spec: list[list[tuple[int, int]]],
    reel_skin: int | str = "",
) -> list[dict]:
    """Convert an M279 session (1+ rounds from engine.run_session) into
    a list of round JSON dicts for chunk emission.

    Mirrors emitter/round.py emit_session signature.
    """
    out: list[dict] = []
    for rd in rounds:
        if rd.spin_type == ST_PAID or rd.spin_type == ST_NUDGE:
            d = _emit_paid_or_nudge_dict(
                rd, last_credits=last_credits, spin_times=spin_times,
                rtp_id=rtp_id, paylines_spec=paylines_spec,
                reel_skin=reel_skin,
            )
        elif rd.spin_type == ST_WHEEL:
            d = _emit_wheel_dict(
                rd, last_credits=last_credits, spin_times=spin_times,
                rtp_id=rtp_id,
            )
        elif rd.spin_type == ST_BUFFMAP:
            d = _emit_buffmap_dict(
                rd, last_credits=last_credits, spin_times=spin_times,
                rtp_id=rtp_id,
            )
        else:
            raise ValueError(f"M279 emit: unknown spin_type {rd.spin_type}")
        out.append(d)
    return out
