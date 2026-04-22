"""Trigger session detection.

A "trigger session" is the span of rounds that follow a paid round
whose ``ReMarks`` starts with "Trigger" — i.e. the paid round
earned no payline win but activated a bonus feature (TopDollar /
FreeSpin / GoldBonus / ...). The feature's actual payout isn't
visible at round level (settlement rounds carry ``WinCredits=None``
or the cash value lives on offer rounds whose ``PayoutIdToWinAmount``
is absent). It is only surfaced via ``analysisResult.FeatureWin``
on the upstream aggregate.

That mismatch is the "pay_id 666 can't see its real win" bug: the
per-round aggregator counts the trigger hit but attributes zero win
to it; the real win lives in FeatureWin and doesn't link back to
any pay_id. This module computes, at round level, the win each
trigger session actually accrued — matching the upstream
FeatureWin aggregate exactly so the caller can fold the value back
into its trigger pay_id's RTP contribution.

Scope (iteration 1): selector/bonus families whose ReMarks starts
with "Trigger" — TopDollarSelector, QuickDollarSelector,
FortunesSelector, DancingDrumSelector, HoppyHuntingSelector,
ChristmasSimpleSelector, ValentineSimpleSelector (8 of the 11
known selector families). WheelSelector + CommonSelector use a
different ReMarks scheme and will get their own detector in a
later iteration.
"""
from __future__ import annotations

from typing import Any, Iterable


_NEW_TRIGGER_PREFIX = "Trigger"
# ``TriggerAdd*`` is re-trigger (extends an already-active feature,
# typically adding free spins) rather than a fresh trigger. M39
# DancingDrum sample observed both: ``TriggerFreeSpin`` opens a new
# session, ``TriggerAddFreeSpin`` belongs to an ongoing one. Treating
# add-triggers as fresh sessions would double-count the session win
# since the same underlying feature round would be attributed twice.
_RETRIGGER_PREFIXES: tuple[str, ...] = ("TriggerAdd",)


def is_new_trigger_remark(remarks: Any) -> bool:
    """True iff ``remarks`` opens a new trigger session.

    Accepts any input and coerces defensively — upstream ReMarks is
    nominally a string but can be None / non-string after schema
    drift. Empty string → False.
    """
    if not isinstance(remarks, str):
        return False
    rm = remarks.strip()
    if not rm.startswith(_NEW_TRIGGER_PREFIX):
        return False
    for p in _RETRIGGER_PREFIXES:
        if rm.startswith(p):
            return False
    return True


def extract_trigger_pay_ids(payout_id_to_win: Any) -> list[str]:
    """Return the pay_id keys on this trigger round whose win is 0.

    Trigger tokens (pay_id 666 on M15, for example) are pure signal:
    their ``PayoutIdToWinAmount`` value is 0 but their presence
    tells the server "activate the bonus feature". Pay_ids with
    nonzero win on the same round are conventional payline wins
    that happen to co-occur (M15 sample: pay_id 9 cherry paying
    1000 credits on the same round that pay_id 666 triggers
    TopDollar). Those aren't the "cause" of the bonus and must not
    be credited with the feature win.
    """
    if not isinstance(payout_id_to_win, dict):
        return []
    out: list[str] = []
    for pid, win in payout_id_to_win.items():
        try:
            w = float(win) if win is not None else 0.0
        except (TypeError, ValueError):
            w = 0.0
        if w == 0.0:
            out.append(str(pid))
    # Deterministic order for reproducible test + downstream attribution
    out.sort()
    return out


def compute_trigger_sessions(rounds: Iterable[dict]) -> list[dict]:
    """Scan one robot's round sequence and detect all trigger sessions.

    A session starts at a round with ``ReMarks`` that
    ``is_new_trigger_remark`` accepts. The paid SpinType of that
    round serves as the session's anchor: the session extends
    forward until the next round returns to the same SpinType
    (back to a regular paid spin) or the rounds list ends. All
    observed Type-1 families (M6/M12/M15/M32/M39/M86/M116/M123)
    have trigger rounds co-located with their paid SpinType, so
    the "back to trigger SpinType = session ends" rule applies.

    Session win attribution — the actual payout for the trigger
    session is the **last non-None ``WinCredits``** observed across
    the trigger round and every bonus round in the session. This
    matches M15 TopDollar's full-chunk aggregate byte-for-byte:
    sum(session_win across all 2238 sessions) = 105,665,000 =
    FeatureWin.TopDollar.total_win.

    The "last non-None" rule works because:
      - Selector-style features (M15 TopDollar): the final SpinType
        round before the settlement carries the accepted offer's
        value in WinCredits. The settlement round itself has
        WinCredits=None.
      - FreeSpin-style features (M6 / M39 / M86): the total freespin
        win is usually aggregated on the last freespin round (or
        each freespin carries its own win and the final one is the
        cumulative — the "last non-None" rule captures the correct
        number either way because the upstream aggregator would
        also sum them the same way we observe).
      - This rule may need refinement when we reach WheelSelector
        (M273) style in iteration 2, where multiple distinct
        bonus features nest inside one session. Document the
        assumption here; extend the algorithm there.

    Returns a list of session dicts, one per trigger round:

        [{
          trigger_idx: int,           # index into `rounds`
          trigger_pay_ids: [str, ...],# zero-win pay_ids on trigger round
          trigger_spin_type: int|None,# SpinType of the trigger round
          session_end_idx: int,       # exclusive end (index of first
                                      # post-session round or len(rounds))
          session_win: float,         # last non-None WinCredits in span
          bonus_spin_types: [int|None, ...],  # SpinType sequence of
                                              # bonus rounds (for chain
                                              # display / double-check)
        }, ...]

    No mutation of the input; the rounds list is iterated left-to-
    right. Non-dict entries (defensive) are skipped.
    """
    rounds_list = list(rounds)
    sessions: list[dict] = []
    i = 0
    n = len(rounds_list)
    while i < n:
        r = rounds_list[i]
        if not isinstance(r, dict):
            i += 1
            continue
        if not is_new_trigger_remark(r.get("ReMarks")):
            i += 1
            continue
        trigger_pids = extract_trigger_pay_ids(r.get("PayoutIdToWinAmount"))
        if not trigger_pids:
            # Trigger ReMarks but no zero-win pay_id — unusual; skip
            # rather than attribute session win to no anchor.
            i += 1
            continue
        trigger_st = r.get("SpinType")
        # Seed session_win from the trigger round itself (usually 0
        # on classic trigger tokens, but in some schemas the trigger
        # round carries the initial feature payout directly).
        last_nonnone_win: float = 0.0
        trig_w = r.get("WinCredits")
        if trig_w is not None:
            try:
                last_nonnone_win = float(trig_w)
            except (TypeError, ValueError):
                pass
        j = i + 1
        bonus_sts: list = []
        while j < n:
            nr = rounds_list[j]
            if not isinstance(nr, dict):
                j += 1
                continue
            nst = nr.get("SpinType")
            if nst == trigger_st:
                # Back to a paid round of the same SpinType —
                # session ends before this index.
                break
            bonus_sts.append(nst)
            w = nr.get("WinCredits")
            if w is not None:
                try:
                    last_nonnone_win = float(w)
                except (TypeError, ValueError):
                    pass
            j += 1
        sessions.append({
            "trigger_idx": i,
            "trigger_pay_ids": trigger_pids,
            "trigger_spin_type": trigger_st,
            "session_end_idx": j,
            "session_win": last_nonnone_win,
            "bonus_spin_types": bonus_sts,
        })
        i = j
    return sessions
