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

# Dual-import for sibling ``round_win``: backend launches analyzer
# as a script (``sys.executable <path>/player_impact_analyzer.py``,
# see app.py self._analyzer wiring), which puts ``fresh_slotlab/``
# on sys.path[0] but provides NO ``fresh_slotlab`` package — so the
# package-prefix import below raises ModuleNotFoundError. Fall
# through to the bare-import path the analyzer.py module-top
# already uses for the same reason (sibling import works because
# the directory is on path).
#
# Without this fallback any M sampling that pulls trigger_sessions
# crashes the subprocess at import time with the misleading-looking
# "ModuleNotFoundError: No module named 'fresh_slotlab'" trace
# (regression introduced 2026-04-26 by 21357b3 + 6043b6f when
# round_win was first wired into trigger_sessions).
try:
    from fresh_slotlab.round_win import (
        RoundWinRule,
        extract_round_payouts,
        extract_round_trigger_anchor,
        extract_round_win,
        extract_trigger_pay_ids_default,
        is_paid_round,
        round_has_credited_win,
    )
except ImportError:  # running as a standalone script, not a package member
    from round_win import (  # type: ignore[no-redef]
        RoundWinRule,
        extract_round_payouts,
        extract_round_trigger_anchor,
        extract_round_win,
        extract_trigger_pay_ids_default,
        is_paid_round,
        round_has_credited_win,
    )


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


# Back-compat alias: pre-refactor callers imported these names from
# trigger_sessions. The canonical definitions live in round_win now;
# re-export so external scripts / older test imports keep working.
extract_trigger_pay_ids = extract_trigger_pay_ids_default
_is_paid_round = is_paid_round
_round_has_credited_win = round_has_credited_win


def _to_float_or_zero(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def compute_trigger_sessions(
    rounds: Iterable[dict],
    round_win_rules: list[RoundWinRule] | None = None,
    ctx: dict | None = None,
) -> list[dict]:
    """Scan one robot's round sequence and detect all trigger sessions.

    ``round_win_rules`` (optional, 2026-04-27): when provided, bonus
    rounds' contribution to ``last_non_none`` / ``sum_all`` is read
    via ``fresh_slotlab.round_win.extract_round_win`` instead of the
    raw ``WinCredits`` lookup. With ``rules=None`` (default) behaviour
    is byte-identical to legacy -- machines without an entry in
    ``configs/machine_round_win_rules.json`` see zero change.

    ``ctx`` (optional, 2026-05-12): forwarded to the rule dispatcher
    on every call to ``extract_round_trigger_anchor`` /
    ``extract_round_payouts`` / ``extract_round_win``. Standard keys:

      * ``"bet"`` -- chunk bet amount (multiplier-based pid synthesis).
      * ``"cycle_peak"`` -- per-robot ``detect_cycle_peak`` result; lets
        ``BCMCycleAnchorRule`` synthesize a trigger anchor on paid
        rounds at cycle completion (e.g. M274 ``CollectCount==1000``
        rounds with ``PayoutIdToWinAmount={}``). Without this hook 55
        of 117 cached BCM (machine, mode) pairs leak bonus-feature
        win into the ``_unattributed_st<N>`` catch-all.

    With rules: phantom bonus rounds (e.g. M12 ST=14 selector offer
    preview) contribute 0; settlement rounds (M12 ST=15 carrying real
    payout in WinAmount) contribute their WinAmount. ``last_non_none``
    therefore tracks the rule's view of "this round's actual win",
    which is what the trigger pay_id must be credited with.

    A session opens when a paid round is followed by at least one
    non-paid round AND the paid round carries at least one trigger
    anchor pay_id (from default ``PayoutIdToWinAmount`` win==0
    extraction OR a rule's ``extract_trigger_anchor`` contribution).
    The session ends at the next paid round (exclusive) or the rounds
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
        if not is_paid_round(r):
            i += 1
            continue
        # Peek ahead: is there at least one non-paid round right
        # after this paid one? No → regular paid spin, skip.
        if i + 1 >= n or is_paid_round(rounds_list[i + 1]):
            i += 1
            continue
        # Has any trigger anchor? Default extraction = PayoutIdToWinAmount
        # win==0 keys; rules may augment with synthetic anchors
        # (e.g. BCMCycleAnchorRule contributes "_bcm_cycle" on paid
        # rounds at cycle completion). No anchor → can't attribute a
        # session win to any pay_id, skip (still advance past the bonus
        # block so we don't re-scan it).
        trigger_pids = extract_round_trigger_anchor(r, rules=round_win_rules, ctx=ctx)
        if not trigger_pids:
            # Still find session_end so we don't re-enter mid-bonus.
            j = i + 1
            while j < n and not is_paid_round(rounds_list[j]):
                j += 1
            i = j
            continue
        # Classify rule from ReMarks.
        remarks = r.get("ReMarks")
        rule = "last_non_none" if is_new_trigger_remark(remarks) else "sum_all"
        trigger_st = r.get("SpinType")
        # Session-win seed: 0. The trigger round's own WinCredits (when
        # nonzero) reflects a co-occurring regular payline win (e.g.
        # M15 cherry pay_id 9 paying 1000 on the same round that pay_id
        # 666 triggers TopDollar; M53 freespin trigger paying 4000 on
        # pay_id 81 alongside pay_id 300 trigger token). That regular
        # win is ALREADY credited to its specific pay_id by the
        # analyzer's round-level aggregation loop. Seeding session_win
        # with the trigger round's WinCredits would attribute the same
        # win to BOTH pay_id 9/81 AND the trigger pay_id 666/300 ->
        # ~24% pid over-attribution observed on M53/M27/M174/M196 etc
        # in the fleet payid invariant scan (2026-04-27). Fix: seed=0;
        # session_win counts only the bonus block's contribution.
        last_nonnone_win: float = 0.0
        sum_win: float = 0.0
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
            if is_paid_round(nr):
                break
            bonus_sts.append(nr.get("SpinType"))
            # Skip rounds whose win is ALREADY credited at round level.
            # ``round_has_credited_win`` is rule-aware -- it checks the
            # union of:
            #   (a) raw round.PayoutIdToWinAmount has nonzero values
            #       (M273/M257/M201 freespin attribution).
            #   (b) Rule-driven (2026-04-27): a SynthesizePayIdRule
            #       maps the round to a non-empty synthetic pid dict
            #       (M279 wheel ST=2 -> {'st2': WinCredits}; M272 freespin
            #       ST=126 -> {'st126': WinCredits}); the analyzer's
            #       round-level pid aggregator already credits 'st<N>'.
            #       Adding the same win to session_win and attributing
            #       it to the trigger pay_id would double-count.
            #
            # Empty-dict rule output (SettlementWinAmountRule on
            # ST=14/15) is intentionally NOT a "credited" signal -- it
            # explicitly DELEGATES attribution to session_win on the
            # trigger pay_id (e.g., '666' for TopDollar). So empty
            # dict from the rule still falls through to accumulation.
            if not round_has_credited_win(nr, rules=round_win_rules, ctx=ctx):
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
                    # rule. Phantom rounds give 0; settlement rounds
                    # give WinAmount; ordinary rounds fall through to
                    # legacy WinCredits.
                    w = extract_round_win(nr, rules=round_win_rules, ctx=ctx)
                    last_nonnone_win = w
                    sum_win += w
            j += 1
        # Session-win selection.
        #
        # Legacy path (no rules): respect the ReMarks-derived rule
        # classification -- "Trigger" -> last_non_none (selector
        # accepts last offer), other -> sum_all (freespin aggregate).
        #
        # Rules-driven path (2026-04-27 fix for M132 multi-settlement):
        # ALWAYS use sum_win. The rule is the authoritative source for
        # each round's contribution -- phantom rounds give 0, settlement
        # rounds give WinAmount, freespin rounds give WinCredits etc.
        # Summing is correct for both 1-settlement (M12 v1 single pick)
        # and N-settlement (M132 v2 has 2 ST=15 rounds per session) cases,
        # because phantoms add 0 either way. last_non_none is wrong on
        # multi-settlement: it picks only the last settlement WinAmount
        # and silently drops earlier ones -- M132 v2 measured this as
        # a 7% gap on payid attribution.
        if round_win_rules:
            session_win = sum_win
        else:
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
