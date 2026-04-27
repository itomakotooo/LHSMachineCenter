"""Trigger session detection — two families covered.

A "trigger session" is the span of rounds that follow a paid round
which activates a bonus feature. The feature's actual payout
doesn't cleanly appear on any single round — it's aggregated at
``analysisResult.FeatureWin`` by the upstream server. This module
recovers the session win at round level so the caller can fold it
back onto the trigger pay_id's RTP contribution.

Two signal families are handled:

**Type 1** (iteration 1) — ``ReMarks`` starts with "Trigger".
  Covers TopDollarSelector (M12/15/90/132/206), QuickDollarSelector
  (M32), FortunesSelector (M6), DancingDrumSelector (M39),
  HoppyHuntingSelector (M86), ChristmasSimpleSelector (M116/210),
  ValentineSimpleSelector (M123).
  Session-win rule: **last non-None WinCredits** across the span.
  Matches the "selector offers N candidates, player accepts one"
  semantics — the final offer round's WinCredits is the accepted
  value; subsequent settlement rounds carry WinCredits=None.

**Type 2** (iteration 2) — paid round has ``WinCredits==0``,
non-empty ``PayoutIdToWinAmount`` with at least one win==0 key,
and its ``ReMarks`` does NOT match Type 1. Covers WheelSelector
(M273 + its 84 sibling 3-of-9 variants), CommonSelector (M201 /
M209 / M257). Their paid trigger round is unmarked in ReMarks —
the bonus structure surfaces through ``SpinType`` transition
only. Session-win rule: **sum of non-None WinCredits** across
the span. Matches "freespin accumulate N wins" semantics where
each freespin round carries its own WinCredits and they're all
kept by the player.

The two rules are mutually exclusive at the session level: the
rule to apply is determined when the session opens and does not
change mid-session.

Paid-round detection is via ``CostCredits > 0`` (upstream reliably
sets it on paid rounds; bonus rounds carry CostCredits in (None,
0)). Session boundary is paid→non-paid→paid: all non-paid rounds
between a paid trigger and the next paid round form one session.

Non-session paid rounds (any paid round whose win==0 pay_id does
NOT lead into a non-paid sequence) are ignored — they're
payline metadata, not trigger signals.
"""
from __future__ import annotations

from typing import Any, Iterable

from fresh_slotlab.round_win import RoundWinRule, extract_round_win


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


def _is_paid_round(r: Any) -> bool:
    """Paid-round classifier used by both Type 1 and Type 2 session
    boundary logic. True iff ``CostCredits > 0``. Bonus rounds
    carry CostCredits in (None, 0) uniformly across every machine
    observed — TopDollar selector, M273 freespin, M201 selector
    result, M209 move, M257 freespin, all non-paid side rounds
    have CostCredits None or 0."""
    if not isinstance(r, dict):
        return False
    cc = r.get("CostCredits")
    if cc is None:
        return False
    try:
        return float(cc) > 0.0
    except (TypeError, ValueError):
        return False


def _to_float_or_zero(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _round_has_credited_win(r: Any) -> bool:
    """True iff this round's WinCredits has already been credited to
    pay_ids by the round-level aggregator — i.e. the round carries
    a non-empty ``PayoutIdToWinAmount`` with at least one nonzero
    value. Such rounds MUST be excluded from the trigger-session
    win sum (else double-count).

    Observed live across probed machines:

      * M273 freespin round ``{'6': 7000, '101': 2000}``,
        WinCredits=9000 → round aggregator credits pay_id 6 (+7000)
        and pay_id 101 (+2000). Folding 9000 into trigger pay_id
        5801's win too would double-count the same 9000.
      * M257 freespin round ``{'1': 33300}``: pay_id 1 already at
        pay_id level; skip for trigger session.
      * M201 bonus round ``{'20102': 11660}``: pay_id 20102 at
        pay_id level, skip.
      * M15 selector offer round ``PayoutIdToWinAmount=None`` (no
        dict at all): NOT filtered — round-level aggregator sees
        nothing here, so the session-level win is the ONLY way to
        attribute the offer value to pay_id 666.
      * M273 ``{}`` empty dict (e.g. "Minigame CellIndexes"): NOT
        filtered — no pay_id got credit.
      * Trigger round's own ``{'666': 0}`` / ``{'5801': 0}``: NOT
        filtered — all zeros mean no pay_id actually got paid.
    """
    if not isinstance(r, dict):
        return False
    p = r.get("PayoutIdToWinAmount")
    if not isinstance(p, dict) or not p:
        return False
    for win in p.values():
        try:
            w = float(win) if win is not None else 0.0
        except (TypeError, ValueError):
            w = 0.0
        if w > 0.0:
            return True
    return False


def compute_trigger_sessions(
    rounds: Iterable[dict],
    round_win_rules: list[RoundWinRule] | None = None,
) -> list[dict]:
    """Scan one robot's round sequence and detect all trigger sessions.

    ``round_win_rules`` (optional, 2026-04-27): when provided, bonus
    rounds' contribution to ``last_non_none`` / ``sum_all`` is read
    via ``fresh_slotlab.round_win.extract_round_win`` instead of the
    raw ``WinCredits`` lookup. With ``rules=None`` (default) behaviour
    is byte-identical to legacy -- machines without an entry in
    ``configs/machine_round_win_rules.json`` see zero change.

    With rules: phantom bonus rounds (e.g. M12 ST=14 selector offer
    preview) contribute 0; settlement rounds (M12 ST=15 carrying real
    payout in WinAmount) contribute their WinAmount. ``last_non_none``
    therefore tracks the rule's view of "this round's actual win",
    which is what the trigger pay_id must be credited with.

    A session opens when a paid round is followed by at least one
    non-paid round AND the paid round carries at least one win==0
    ``PayoutIdToWinAmount`` key (the "trigger pay_id anchor"). The
    session ends at the next paid round (exclusive) or the rounds
    list end.

    The session's ``win_rule`` and ``session_win`` are determined
    by the trigger round's ``ReMarks``:

      * **Type 1** — ``ReMarks`` starts with "Trigger" (but not
        "TriggerAdd..."). ``win_rule = "last_non_none"``, meaning
        ``session_win`` equals the last non-None WinCredits across
        the span. Matches selector/offer semantics (M15 TopDollar:
        last selector offer value is the one the player accepts;
        settlement round has WinCredits=None).

      * **Type 2** — ReMarks does NOT match Type 1, but the paid
        round still anchors a non-paid sequence with trigger pay_ids.
        ``win_rule = "sum_all"``, meaning ``session_win`` is the
        sum of non-None WinCredits across eligible bonus rounds.
        Covers WheelSelector (M273) + CommonSelector (M201/M257).

    Both rules apply the ``_round_has_credited_win`` filter — bonus
    rounds whose WinCredits is already credited to pay_ids at round
    level (non-empty PayoutIdToWinAmount with any nonzero value)
    are EXCLUDED. This is the Iter 3 double-count correction: on
    M273/M257/M201-style machines every freespin round carries its
    own Payout entry, so the round-level aggregator already owns
    those credits. Iter 2 summed them into the trigger pay_id too,
    inflating sum(payout_ids_top20.rtp_pp) above summary.rtp. M15-
    style (Type 1) bonus rounds carry PayoutIdToWinAmount=None /
    empty dict, so the filter doesn't fire and Iter 1's attribution
    to pay_id 666 survives unchanged.

    Verified live:
      - M15 $0$ (Type 1): sum(session_win) over 2238 sessions =
        105,665,000 == FeatureWin.TopDollar.total_win exactly —
        unchanged from Iter 1.
      - M273 $0$ / M257 / M201 (Type 2): session_win ≈ 0 since
        every bonus round's WinCredits is already at pay_id level.
        The freespin-round pay_ids (6 / 101 / 1 / 7 / 20102 / ...)
        absorb the feature RTP naturally through the round-level
        loop. sum(payout_ids_top20.rtp_pp) reaches summary.rtp via
        those pay_ids, not via the trigger pay_id.

    Returns a list of session dicts, one per session:

        [{
          trigger_idx: int,           # index of the paid trigger round
          trigger_pay_ids: [str, ...],# zero-win pay_ids on trigger round
          trigger_spin_type: int|None,# SpinType of the trigger round
          session_end_idx: int,       # exclusive end (index of first
                                      # post-session round or len(rounds))
          session_win: float,         # win per win_rule
          win_rule: "last_non_none"|"sum_all",
          bonus_spin_types: [int|None, ...],  # SpinType sequence of
                                              # bonus rounds (double-check)
        }, ...]

    Non-dict entries are skipped. No mutation of input.
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
        if not _is_paid_round(r):
            i += 1
            continue
        # Peek ahead: is there at least one non-paid round right
        # after this paid one? No → regular paid spin, skip.
        if i + 1 >= n or _is_paid_round(rounds_list[i + 1]):
            i += 1
            continue
        # Has win=0 pay_id anchor? No → can't attribute a session
        # win to any pay_id, skip (still advance past the bonus block
        # so we don't re-scan it).
        trigger_pids = extract_trigger_pay_ids(r.get("PayoutIdToWinAmount"))
        if not trigger_pids:
            # Still find session_end so we don't re-enter mid-bonus.
            j = i + 1
            while j < n and not _is_paid_round(rounds_list[j]):
                j += 1
            i = j
            continue
        # Classify rule from ReMarks.
        remarks = r.get("ReMarks")
        rule = "last_non_none" if is_new_trigger_remark(remarks) else "sum_all"
        trigger_st = r.get("SpinType")
        # Seed from trigger round's own WinCredits (usually 0 for
        # trigger tokens).
        trig_w = r.get("WinCredits")
        last_nonnone_win: float = _to_float_or_zero(trig_w) if trig_w is not None else 0.0
        sum_win: float = _to_float_or_zero(trig_w)
        # Walk the bonus sequence. Rounds whose WinCredits is already
        # credited to pay_ids at round level (non-empty Payout with
        # any nonzero value) are EXCLUDED from last_non_none tracking
        # and sum_win — otherwise the same credit lands in two places
        # (e.g. M273 freespin round Payout={'6':7000,'101':2000}:
        # round aggregator credits pay_id 6/101; session would
        # double-credit pay_id 5801 with the same 9000).
        j = i + 1
        bonus_sts: list = []
        while j < n:
            nr = rounds_list[j]
            if not isinstance(nr, dict):
                j += 1
                continue
            if _is_paid_round(nr):
                break
            bonus_sts.append(nr.get("SpinType"))
            if not _round_has_credited_win(nr):
                if not round_win_rules:
                    # Legacy path -- byte-identical to pre-2026-04-27.
                    # ``WinCredits is None`` skip semantics: a missing
                    # WinCredits field means "this round contributes
                    # nothing observable" so neither last_non_none nor
                    # sum_win moves.
                    w = nr.get("WinCredits")
                    if w is not None:
                        last_nonnone_win = _to_float_or_zero(w)
                        sum_win += _to_float_or_zero(w)
                else:
                    # Rules-driven path: extract_round_win returns the
                    # round's real win contribution per the configured
                    # rule. Phantom rounds give 0 (don't displace a
                    # prior real value because last_non_none updates
                    # to 0 on phantom -- matches behaviour where the
                    # subsequent settlement round overwrites it with
                    # the WinAmount). Settlement rounds give WinAmount
                    # which becomes the session_win for last_non_none
                    # rule. For sum_all rule on rules-equipped machines,
                    # phantom contributes 0 so the sum is unaffected.
                    w = extract_round_win(nr, rules=round_win_rules)
                    last_nonnone_win = w
                    sum_win += w
            j += 1
        session_win = last_nonnone_win if rule == "last_non_none" else sum_win
        sessions.append({
            "trigger_idx": i,
            "trigger_pay_ids": trigger_pids,
            "trigger_spin_type": trigger_st,
            "session_end_idx": j,
            "session_win": session_win,
            "win_rule": rule,
            "bonus_spin_types": bonus_sts,
        })
        i = j
    return sessions
