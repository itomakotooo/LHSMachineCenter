"""Shared pure-utility helpers for the fresh_slotlab analyzer core.

P2-B2: created to consolidate 9 symbols that P2-B1b duplicated into
``core/parser.py`` to break a cycle.  Both ``parser.py`` and
``aggregator.py`` import from here; PIA re-exports all 9.

Module contract (per memory feedback_subprocess_import_suicide_and_module_globals.md):
  - No I/O at import time.
  - No module-top side effects.
  - Only stdlib imports at module level PLUS a dual-path import for
    ``fresh_slotlab.round_win`` (needed by ``_extract_bankruptcy_reps``).
    That module is NOT ``core/parser.py``, NOT ``core/aggregator.py``,
    NOT ``fresh_slotlab.player_impact_analyzer`` — C5 prohibitions are
    respected.

C5 cycle-freedom (ticket §3):
  - MUST NOT import from ``core/parser.py``.
  - MUST NOT import from ``core/aggregator.py``.
  - MUST NOT import from ``fresh_slotlab.player_impact_analyzer``.
"""
from __future__ import annotations

import json
from typing import Any

# Dual-path import for extract_round_win / RoundWinRule consumed by
# _extract_bankruptcy_reps.  Mirrors the pattern in parser.py: package
# mode in the try arm, standalone-script fallback in the except arm.
# C5: round_win is NOT in the prohibited list; this does NOT create a
# cycle through parser.py, aggregator.py, or player_impact_analyzer.
try:
    from fresh_slotlab.round_win import (
        RoundWinRule,
        extract_round_win,
    )
except ImportError:  # running as a standalone script
    from round_win import (  # type: ignore[no-redef]
        RoundWinRule,
        extract_round_win,
    )


# ---------------------------------------------------------------------------
# Pure utility helpers (no project imports needed beyond stdlib)
# ---------------------------------------------------------------------------

def to_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return float(text)
            except ValueError:
                return default
    return default


def blank_like_symbol(symbol: str) -> bool:
    s = symbol.lower()
    return ("blank" in s) or ("empty" in s) or (s == "none")


def bonus_chain_depth_bucket(fs_idx: int) -> str:
    """Bucket a freespin index into a small depth class so the
    bonus_chain_dynamics extra_ratio_by_depth curve stays compact."""
    if fs_idx <= 1:
        return "1"
    if fs_idx <= 5:
        return "2-5"
    if fs_idx <= 10:
        return "6-10"
    if fs_idx <= 20:
        return "11-20"
    return "21+"


def return_bucket(ret_x: float) -> str:
    # Zero-win sessions return "eq0" so the internal bet/win/spin
    # accumulators keep correct totals (session_bet_sum, mb_total_bet,
    # tail calculations all derive from bucket sums). The eq0 key is
    # NOT in RETURN_BUCKET_ORDER, so build_multiplier_bucket_rows()
    # skips it when building the output rows -- the user never sees a
    # zero-info bucket in the chart.
    if ret_x <= 0.0:
        return "eq0"
    if ret_x < 1.0:
        return "gt0_lt1"
    if ret_x < 5.0:
        return "ge1_lt5"
    if ret_x < 10.0:
        return "ge5_lt10"
    if ret_x < 20.0:
        return "ge10_lt20"
    if ret_x < 50.0:
        return "ge20_lt50"
    if ret_x < 100.0:
        return "ge50_lt100"
    if ret_x < 200.0:
        return "ge100_lt200"
    if ret_x < 500.0:
        return "ge200_lt500"
    if ret_x < 1000.0:
        return "ge500_lt1000"
    if ret_x < 5000.0:
        return "ge1000_lt5000"
    return "ge5000"


# ---------------------------------------------------------------------------
# Bankruptcy simulation helpers
# ---------------------------------------------------------------------------

_DEFAULT_BANKROLL_MULTIPLIERS: tuple[int, ...] = (100, 200, 500)
_DEFAULT_BANKRUPTCY_SESSION_SPINS = 10000


def _empty_bankruptcy_tier() -> dict[str, Any]:
    return {
        "bankrupt": 0,
        "survived": 0,
        # Exact spins-done at bankruptcy, one entry per bankrupt
        # window. Sorted on read (see percentile / median helpers).
        # Survivors are NOT in this list — they're summed in the
        # `survived` counter.
        "spins_done": [],
    }


def _extract_bankruptcy_reps(
    resp: Any,
    round_win_rules: list[RoundWinRule] | None = None,
) -> list[tuple[int, int]]:
    """Flatten (cost_bet, cost_win) tuples across every robot+round in a
    chunk response. Shared by per-chunk simulation and the global
    streaming accumulator (see _BankruptcyStreamAccumulator).

    ``round_win_rules`` (optional, 2026-04-27): when provided, win is
    sourced via ``extract_round_win`` so phantom-offer rounds (M12 ST=14)
    don't credit the simulated bankroll with un-paid offer values, and
    settlement rounds (M12 ST=15 carrying WinAmount but no WinCredits)
    correctly credit the actual payout. Default ``None`` is byte-
    identical to legacy ``r.get("WinCredits", 0)`` lookup.

    Note: ``parse_rounds`` is inlined here (stdlib-only: ``json``) to
    avoid importing from ``core/parser.py`` (C5 cycle-freedom constraint).
    """
    reps: list[tuple[int, int]] = []
    if not isinstance(resp, list):
        return reps
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        # Inline of parse_rounds() — avoids importing from core/parser.py
        # (C5 cycle-freedom).  Body is byte-identical to parse_rounds.
        rr = robot.get("roundResult")
        if not rr:
            rounds: list[Any] = []
        elif isinstance(rr, str):
            try:
                parsed = json.loads(rr)
                rounds = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                rounds = []
        else:
            rounds = rr if isinstance(rr, list) else []
        if not rounds:
            continue
        for r in rounds:
            if not isinstance(r, dict):
                continue
            try:
                c_bet = int(r.get("CostCredits", 0) or 0)
            except (TypeError, ValueError):
                c_bet = 0
            if round_win_rules:
                try:
                    c_win = int(extract_round_win(r, rules=round_win_rules))
                except (TypeError, ValueError):
                    c_win = 0
            else:
                # Legacy path -- byte-identical to pre-2026-04-27.
                try:
                    c_win = int(r.get("WinCredits", 0) or 0)
                except (TypeError, ValueError):
                    c_win = 0
            reps.append((c_bet, c_win))
    return reps


def simulate_bankruptcy_from_response(
    resp: Any,
    bet: int,
    session_spins: int,
    bankroll_mults: tuple[int, ...] = _DEFAULT_BANKROLL_MULTIPLIERS,
    round_win_rules: list[RoundWinRule] | None = None,
) -> dict[int, dict[str, Any]]:
    """Pool all robots' rounds in a chunk into one sequential stream,
    then chop into non-overlapping ``session_spins`` windows. Each
    window replays from a fresh bankroll at every tier, independently.

    Returns a dict keyed by bankroll multiplier. Each entry has:
      - bankrupt:   windows that ran out of balance before the cap
      - survived:   windows that consumed all ``session_spins``
      - spins_done: list of EXACT spin counts reached at bankruptcy,
                    one entry per bankrupt window. Survivors are NOT
                    in this list — tallied in ``survived``. Unsorted
                    on per-chunk return; finalize sorts after merge.

    Degenerate inputs (non-list resp, non-positive bet/session_spins,
    or fewer rounds than a single session_spins window) return {} or
    zeroed tiers so finalize never crashes.

    NOTE 2026-04-25: per-chunk simulation alone produces empty results
    when chunk_total_paid_spins < session_spins (e.g. virtual machines
    sampled with chunk_spin_times=1000 × chunk_robot_count=8 = 8000 vs
    session_spins=10000). Cross-chunk pooling is now handled by
    ``_BankruptcyStreamAccumulator`` at merge time; this per-chunk
    function stays for backward compat with cached chunk records that
    pre-date the streaming-accumulator fix.
    """
    if not isinstance(resp, list) or bet <= 0 or session_spins <= 0:
        return {}
    out: dict[int, dict[str, Any]] = {
        int(m): _empty_bankruptcy_tier() for m in bankroll_mults
    }
    reps = _extract_bankruptcy_reps(resp, round_win_rules=round_win_rules)
    if not reps:
        return out
    # Chop into windows. Any trailing spins shorter than session_spins
    # are dropped — a partial window would bias the bankruptcy
    # distribution toward "bankrupt" since it can't ever survive.
    window_count = len(reps) // session_spins
    if window_count <= 0:
        return out
    for m in bankroll_mults:
        tier = out[int(m)]
        init_bankroll = int(m) * int(bet)
        for w in range(window_count):
            balance = init_bankroll
            spins_done = 0
            start = w * session_spins
            end = start + session_spins
            for i in range(start, end):
                c_bet, c_win = reps[i]
                if c_bet > 0 and balance < c_bet:
                    break  # bankrupt — can't afford the next paid round
                balance -= c_bet
                balance += c_win
                spins_done += 1
            if spins_done >= session_spins:
                tier["survived"] += 1
            else:
                tier["bankrupt"] += 1
                tier["spins_done"].append(int(spins_done))
    return out
