"""Per-machine round-level overrides for chunk-win aggregation
AND payout-id attribution.

A rule decides two questions about a given round:

  1. ``extract_win(round, ctx) -> float | None``
     What is this round's contribution to ``chunk_win``?
     Return ``None`` to fall through to the legacy
     ``r.get("WinCredits", 0)`` lookup. Used to zero out phantom
     rounds (TopDollar selector ST=14 offers) and to redirect to
     a different field (TopDollar settlement ST=15 ``WinAmount``).

  2. ``extract_payouts(round, ctx) -> dict[str, float] | None``
     Which pay_ids does this round credit, and by how much?
     Return ``None`` to fall through to the round's
     ``PayoutIdToWinAmount`` field. Return ``{}`` (empty dict)
     to explicitly NOT credit any pay_id at the round level
     (delegating to a downstream attribution mechanism, e.g.
     trigger_sessions adding session_win to the trigger pay_id).
     Return a populated dict to override the round's own
     PayoutIdToWinAmount.

Default behaviour (rule list empty / None) is **byte-identical**
to legacy: ``extract_round_win`` returns ``r.get("WinCredits", 0)``
and ``extract_round_payouts`` returns ``r.get("PayoutIdToWinAmount")``
or ``{}``. Machines absent from
``configs/machine_round_win_rules.json`` see zero behavioural change.

Adding a new rule type:
  1. Subclass ``RoundWinRule`` here.
  2. Override ``extract_win`` and/or ``extract_payouts`` as needed.
  3. Register in ``RULE_REGISTRY``.
  4. Add config entry pointing at the new ``type`` string.
  5. Add unit tests.
"""
from __future__ import annotations

from typing import Any


def _to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def is_paid_round(r: Any) -> bool:
    """True iff ``CostCredits > 0``.

    Canonical paid-round predicate for the whole pipeline. Bonus rounds
    (freespin / wheel / settlement / nudge) carry ``CostCredits in
    (None, 0)`` across every probed machine; only paid trigger rounds
    have a positive cost.
    """
    if not isinstance(r, dict):
        return False
    cc = r.get("CostCredits")
    if cc is None:
        return False
    try:
        return float(cc) > 0.0
    except (TypeError, ValueError):
        return False


# Underscored alias kept for callers that already imported the private
# spelling (round_win internals + early trigger_sessions consumers).
_is_paid_round = is_paid_round


def extract_trigger_pay_ids_default(payout_id_to_win: Any) -> list[str]:
    """Default trigger-anchor extraction: pay_id keys whose
    ``PayoutIdToWinAmount`` value is 0 on a paid round.

    Trigger tokens (pay_id 666 on M15 TopDollar, 5801 on M274
    ListRewardWheel, etc.) are pure signal: their value is 0 but their
    presence tells the math machine "activate the bonus feature".
    Pay_ids with nonzero win on the same round are conventional payline
    wins that happen to co-occur and must NOT be treated as trigger
    anchors (they'd absorb the bonus session win that belongs to the
    real trigger).

    Returns a sorted list for deterministic downstream attribution.
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
    out.sort()
    return out


class RoundWinRule:
    """Base class for per-machine round-level overrides.

    Subclasses override ``extract_win`` and/or ``extract_payouts`` and/or
    ``extract_trigger_anchor`` as needed. ``ctx`` is a free-form dict
    passed through by callers. Standard keys:

      * ``"bet"`` — chunk bet amount (used by multiplier-based pay_id
        synthesis, e.g. SynthesizePayIdRule).
      * ``"cycle_peak"`` — per-robot ``detect_cycle_peak`` result
        (used by BCMCycleAnchorRule to detect cycle completion).

    A rule may be stateful per-robot (e.g. summary-vs-sub-round
    dedupe needs to remember the previous round). Stateful rules
    should be instantiated fresh for each robot; the analyzer
    passes the same rule list across all rounds within one robot.
    """

    def extract_win(self, round_dict: dict, ctx: dict | None = None) -> float | None:
        """Override the round's WinCredits-derived chunk_win contribution.
        ``None`` = no override; caller falls through to default WinCredits.
        """
        return None

    def extract_payouts(self, round_dict: dict, ctx: dict | None = None) -> dict[str, float] | None:
        """Override the round's PayoutIdToWinAmount-derived pay_id
        attribution. ``None`` = no override; caller falls through
        to default ``round.PayoutIdToWinAmount``. ``{}`` = explicitly
        suppress round-level credit (caller leaves payout_id_win
        unchanged for this round).
        """
        return None

    def extract_trigger_anchor(self, round_dict: dict, ctx: dict | None = None) -> list[str] | None:
        """Augment trigger-anchor extraction for a paid trigger round.

        Called by ``compute_trigger_sessions`` when a paid round is
        followed by at least one bonus round (cost==0). Lets a machine
        contribute extra anchor pay_ids beyond the
        ``PayoutIdToWinAmount`` win==0 default extraction, for trigger
        mechanics that don't surface through PayoutIdToWinAmount at
        all (e.g. M274 BuffCollectionMap milestone fires at
        ``CollectCount==cycle_peak`` with ``PayoutIdToWinAmount={}``).

        Return value semantics:
          * ``None`` — no contribution from this rule; caller keeps
            whatever default + other-rule anchors it has.
          * ``[]`` — explicit "no anchor from this rule" (rare;
            equivalent to ``None`` for the dispatcher).
          * ``[pid, ...]`` — additional anchors to merge into the
            session's trigger_pay_ids list.

        The dispatcher (``extract_round_trigger_anchor``) merges rule
        contributions into the default extraction; downstream the
        analyzer's anchor-selection heuristic picks the "best" pid (max
        numeric value), so a synthetic anchor like ``"_bcm_cycle"``
        never displaces a real numeric pay_id when both are present.
        """
        return None


class SettlementWinAmountRule(RoundWinRule):
    """TopDollar selector family (M12/M15/M90/M132): bonus rounds
    are ST=14 selector offer (phantom) + ST=15 settlement (real
    payout in WinAmount, no WinCredits / no PayoutIdToWinAmount).

    Win extraction:
      * settlement ST -> ``WinAmount`` (real payout)
      * phantom ST -> ``0`` (selector offer is preview, not paid)
      * paid rounds (CostCredits>0) -> no override (WinCredits truth)

    Payout attribution:
      * Both phantom AND settlement rounds return ``{}`` -- the
        upstream emits no per-round PayoutIdToWinAmount on either,
        so round-level pid aggregation gets nothing to credit.
        Real attribution is done by trigger_sessions.compute_trigger_sessions
        which adds session_win to the trigger pay_id (typically
        '666' on TopDollar machines) found on the paid trigger
        round preceding the bonus block.
    """

    def __init__(
        self,
        phantom_spin_types: list[int] | tuple[int, ...] | None = None,
        settlement_spin_types: list[int] | tuple[int, ...] | None = None,
    ) -> None:
        self.phantom_st: frozenset[int] = frozenset(int(x) for x in (phantom_spin_types or ()))
        self.settlement_st: frozenset[int] = frozenset(int(x) for x in (settlement_spin_types or ()))

    def _matches_bonus(self, round_dict: dict) -> int | None:
        """Return the int SpinType if the round is a non-paid bonus
        round whose SpinType is in either configured group.
        Otherwise None (rule does not apply).
        """
        if not isinstance(round_dict, dict):
            return None
        if _is_paid_round(round_dict):
            return None
        st = round_dict.get("SpinType")
        try:
            st_int = int(st) if st is not None else None
        except (TypeError, ValueError):
            return None
        if st_int is None:
            return None
        if st_int in self.settlement_st or st_int in self.phantom_st:
            return st_int
        return None

    def extract_win(self, round_dict: dict, ctx: dict | None = None) -> float | None:
        st_int = self._matches_bonus(round_dict)
        if st_int is None:
            return None
        if st_int in self.settlement_st:
            return _to_float(round_dict.get("WinAmount"), default=0.0)
        # phantom_st
        return 0.0

    def extract_payouts(self, round_dict: dict, ctx: dict | None = None) -> dict[str, float] | None:
        st_int = self._matches_bonus(round_dict)
        if st_int is None:
            return None
        # Both phantom AND settlement: explicitly suppress round-level
        # pid attribution. Trigger session helper handles the real
        # crediting via session_win on the trigger pay_id.
        return {}


class SynthesizePayIdRule(RoundWinRule):
    """For bonus rounds where the upstream emits ``WinCredits > 0``
    but ``PayoutIdToWinAmount`` is empty / None, synthesize a pay_id
    label so the win shows up in the payid drilldown.

    Three label formats (chosen via ``label_format`` param):

      * ``"multiplier"``: ``str(int(win / bet))`` -- one row per
        bet multiplier, matching upstream FeatureWin's "5"/"10"/
        "20"/"50"/"100" convention. Use when win is a clean integer
        multiple of bet (Wheel bonus on M279/M214/M250/M260 ST=2).
        Falls through to ``None`` if multiplier is fractional.

      * ``"spin_type"``: ``f"st{spin_type}"`` -- one row per
        SpinType. Generic catch-all for mechanics where win is
        not a clean multiplier (Freespin/Respin coin-collect on
        M24/M100/M268/M260; M250 paid spins missing pid).
        Always synthesizes (never falls through).

      * ``"spin_type_multiplier"``: ``f"st{st}_x{mult}"`` if integer
        multiplier else ``f"st{st}"``. Combines the two above.

    Win extraction:
      * Default ``None`` -- upstream WinCredits is correct; only
        pid attribution needs synthesis.

    Payout attribution:
      * For configured SpinTypes with WinCredits > 0:
          if PayoutIdToWinAmount empty: synthesize {label: WinCredits}
          if PayoutIdToWinAmount non-empty: no override (pass through)
      * For non-configured SpinTypes: no override.

    The ``apply_when_pid_present`` param (default False) controls
    whether to override even when PayoutIdToWinAmount is non-empty
    -- useful for machines where the existing pid attribution is
    incomplete or wrong.
    """

    _VALID_FORMATS = frozenset({"multiplier", "spin_type", "spin_type_multiplier"})

    def __init__(
        self,
        spin_types: list[int] | tuple[int, ...] | None = None,
        label_format: str = "spin_type",
        apply_when_pid_present: bool = False,
    ) -> None:
        if label_format not in self._VALID_FORMATS:
            raise ValueError(
                f"label_format={label_format!r} not in {sorted(self._VALID_FORMATS)}"
            )
        self.spin_types: frozenset[int] = frozenset(int(x) for x in (spin_types or ()))
        self.label_format = label_format
        self.apply_when_pid_present = bool(apply_when_pid_present)

    def extract_payouts(self, round_dict: dict, ctx: dict | None = None) -> dict[str, float] | None:
        if not isinstance(round_dict, dict):
            return None
        st = round_dict.get("SpinType")
        try:
            st_int = int(st) if st is not None else None
        except (TypeError, ValueError):
            return None
        if st_int is None or st_int not in self.spin_types:
            return None

        win = _to_float(round_dict.get("WinCredits"), default=0.0)
        if win <= 0:
            return None

        pid = round_dict.get("PayoutIdToWinAmount")
        pid_present = isinstance(pid, dict) and bool(pid) and any(
            _to_float(v, 0.0) != 0.0 for v in pid.values()
        )
        if pid_present and not self.apply_when_pid_present:
            return None

        # Choose label.
        bet = 0.0
        ba = round_dict.get("BetAmount")
        if ba is not None:
            bet = _to_float(ba, default=0.0)
        if bet <= 0 and ctx is not None:
            bet = _to_float(ctx.get("bet"), default=0.0)

        label = self._format_label(st_int, win, bet)
        if label is None:
            return None
        return {label: win}

    def _format_label(self, st: int, win: float, bet: float) -> str | None:
        if self.label_format == "spin_type":
            return f"st{st}"

        # Try integer multiplier
        int_mult: int | None = None
        if bet > 0:
            ratio = win / bet
            # Tolerate tiny float drift; reject anything not within 0.01 of integer.
            if abs(ratio - round(ratio)) < 0.01:
                int_mult = int(round(ratio))

        if self.label_format == "multiplier":
            if int_mult is None:
                # Fractional -- can't synthesize a clean multiplier label,
                # fall through to default (legacy behavior: this win
                # remains unattributed, surfaces as a gap).
                return None
            return str(int_mult)

        # spin_type_multiplier
        if int_mult is None:
            return f"st{st}"
        return f"st{st}_x{int_mult}"


class WinResidualRule(RoundWinRule):
    """Collect-coin attribution: a configured SpinType's round pays a
    payline win (itemized in ``PayoutIdToWinAmount``) PLUS an additional
    coin-collect win that the upstream does NOT itemize per pay_id, so
    ``WinCredits > sum(PayoutIdToWinAmount)``. The unattributed delta
    (the "residual") is the collect-coin win.

    The collect mechanic is per-spin realized (NOT a deferred
    accumulation-settlement): ``WinCredits`` already carries the full
    realized win each round (paylines + coins). Coin fields such as
    ``PigCredits`` / ``CreditsSymbols`` / ``SymbolIndexToRewards`` /
    ``RewardIdToCollectAmount`` only *itemize which symbols paid* — the
    total is in ``WinCredits``. Verified on real rawdata: M24 ST46
    (PigCredits, 98.9% residual), M262 ST140 (AccCredits/CollectCount is
    a SEPARATE BCM metronome that never settles the residual), M254 ST154
    + M125 ST138 (coin JSON itemizes, total in WinCredits). So this rule
    NEVER changes ``chunk_win`` (the RTP) — it is PURE attribution: it
    closes the ``sum(payid)==chunk_win`` invariant so the residual lands
    in a named pid instead of the ``_unattributed_st<N>`` /
    ``_unattributed_residual`` alarm buckets.

    Why a NEW rule and not ``SynthesizePayIdRule``: that rule either
    SKIPS the round when payline pids are present (``apply_when_pid_present``
    False — residual leaks to the fallback bucket) or REPLACES the whole
    payout with a single ``{st<N>: WinCredits}`` (``apply_when_pid_present``
    True — destroys the payline symbol breakdown AND mislabels the payline
    win as collect). This rule does neither: it KEEPS the real payline
    pids and ADDS only the residual under a distinct collect label.

    Win extraction:
      * Default ``None`` — ``WinCredits`` is the correct chunk_win;
        only pid attribution needs the residual closer.

    Payout attribution, for configured SpinTypes with ``WinCredits > 0``:
      * ``residual = WinCredits - sum(real PayoutIdToWinAmount values)``
      * ``residual <= tol`` (round fully payline-attributed, or
        over-attributed) → ``None`` (pass through to the round's own pids).
      * ``residual > tol`` → ``{**real_pids, collect_label: residual}``.
        Subsumes the bare-win case (``real_pids`` empty → the whole win
        is the residual → ``{collect_label: WinCredits}``, identical to
        ``SynthesizePayIdRule`` spin_type on that round).

    Label (``label_format``):
      * ``"spin_type_collect"`` (default): ``f"st{N}_collect"`` — a
        distinct row so the collect total never reads as a payline symbol
        pid. The discrete per-symbol/per-coin collect distribution is a
        dedicated analysis (charter invariant 4: one honest feature row;
        shape lives in an analysis, not spread across pids).
      * ``"spin_type"``: ``f"st{N}"`` — matches the SynthesizePayIdRule
        bare-settlement convention when the collect is the ST's only win.

    Both labels are real pids (no reserved ``_`` prefix) → they pass the
    rtp-integrity Layer-2 fallback-bucket check.
    """

    _VALID_FORMATS = frozenset({"spin_type_collect", "spin_type"})
    # Integer credit values → 0.5 matches the per-round + chunk-level
    # residual closers in core/parser.py (same tolerance, same intent).
    _RESIDUAL_TOL: float = 0.5

    def __init__(
        self,
        spin_types: list[int] | tuple[int, ...] | None = None,
        label_format: str = "spin_type_collect",
    ) -> None:
        if label_format not in self._VALID_FORMATS:
            raise ValueError(
                f"label_format={label_format!r} not in {sorted(self._VALID_FORMATS)}"
            )
        self.spin_types: frozenset[int] = frozenset(int(x) for x in (spin_types or ()))
        self.label_format = label_format

    def _collect_label(self, st: int) -> str:
        if self.label_format == "spin_type":
            return f"st{st}"
        return f"st{st}_collect"

    def extract_payouts(self, round_dict: dict, ctx: dict | None = None) -> dict[str, float] | None:
        if not isinstance(round_dict, dict):
            return None
        st = round_dict.get("SpinType")
        try:
            st_int = int(st) if st is not None else None
        except (TypeError, ValueError):
            return None
        if st_int is None or st_int not in self.spin_types:
            return None

        win = _to_float(round_dict.get("WinCredits"), default=0.0)
        if win <= 0:
            return None

        # Real payline pids on this round (a trigger-token pid with value
        # 0 contributes 0 to the sum, so it is preserved but does not
        # affect the residual).
        pid = round_dict.get("PayoutIdToWinAmount")
        real: dict[str, float] = {}
        if isinstance(pid, dict):
            real = {str(k): _to_float(v, 0.0) for k, v in pid.items()}
        pid_sum = sum(real.values())

        residual = win - pid_sum
        if residual <= self._RESIDUAL_TOL:
            # Fully payline-attributed (or over-attributed) — nothing to
            # add. Pass through to the round's own pids unchanged.
            return None

        label = self._collect_label(st_int)
        out = dict(real)
        # Defensive: a real pid literally named like the collect label is
        # impossible (real pids are numeric symbol ids) but accumulate to
        # be safe rather than clobber.
        out[label] = out.get(label, 0.0) + residual
        return out


class BCMCycleAnchorRule(RoundWinRule):
    """Synthesize a trigger anchor on paid rounds where a buff-collection
    cycle completes (i.e. ``CollectCount == cycle_peak``).

    Covers the ``BuffCollectionMap`` mechanic used by the 159-machine
    BCM family. The bonus feature fires once per cycle when the buff
    counter reaches the peak; the math machine does NOT surface this
    transition through ``PayoutIdToWinAmount`` (the trigger round
    carries ``pid={}`` or only co-occurring regular-payline pids).
    Without this rule, the bonus block's wins fall through every
    layer of pay_id attribution and land in the ``_unattributed_st<N>``
    catch-all -- silently, since the invariant
    ``sum(payid_win)==chunk_win`` is force-closed by the synthesizer.

    Verified 2026-05-12 on M274 mode 1 (8.25% of bonus rounds, 315 of
    315 unattributed blocks deterministically preceded by paid round
    with ``CollectCount==1000``; OLD cfg md5 showed 0% fallback, new
    cfg introduced the milestone path). Fleet sweep across 117 cached
    BCM (machine, mode) pairs found 55 with fallback_sum >0.5% of
    chunk_win -- M250 mode 1/2/5/7 at 100%, M268/M260/M264 at 70-90%.

    The cycle peak is detected by
    ``fresh_slotlab.round_classification.detect_cycle_peak`` over the
    full per-robot rounds list and passed via ``ctx["cycle_peak"]``.
    Pass-through when:

      * ``ctx`` is None or missing ``"cycle_peak"`` -- caller is not
        wired for BCM detection (defensive).
      * ``cycle_peak is None`` -- chunk too short to observe a reset
        (single-chunk machines whose cycle is longer than the chunk).
      * The round is not paid (``CostCredits<=0``) -- bonus rounds
        themselves carry no CollectCount and are never trigger rounds.
      * ``CollectCount != cycle_peak`` -- this paid round is not at
        cycle completion.

    Fires returning ``[anchor_pid]`` (default ``"_bcm_cycle"``). The
    dispatcher merges this into the default ``PayoutIdToWinAmount``
    win==0 extraction; if a paid round has both a real pay_id anchor
    (rare overlap, e.g. M274 has 5/3902 trigger rounds with both '5801'
    and CC==peak) the analyzer's anchor-selection picks max-numeric so
    the real pid wins and the synthetic anchor is dropped harmlessly.
    """

    def __init__(
        self,
        anchor_pid: str = "_bcm_cycle",
        cycle_field: str = "CollectCount",
    ) -> None:
        self.anchor_pid = str(anchor_pid)
        self.cycle_field = str(cycle_field)

    def extract_trigger_anchor(self, round_dict: dict, ctx: dict | None = None) -> list[str] | None:
        if not isinstance(round_dict, dict):
            return None
        if not is_paid_round(round_dict):
            return None
        if not isinstance(ctx, dict):
            return None
        peak = ctx.get("cycle_peak")
        if peak is None:
            return None
        try:
            peak_int = int(peak)
        except (TypeError, ValueError):
            return None
        if peak_int < 1:
            return None
        cv = round_dict.get(self.cycle_field)
        try:
            cv_int = int(cv) if cv is not None else None
        except (TypeError, ValueError):
            return None
        if cv_int != peak_int:
            return None
        return [self.anchor_pid]


# Stable type-string -> class. Add new rule types here.
RULE_REGISTRY: dict[str, type[RoundWinRule]] = {
    "settlement_winamount": SettlementWinAmountRule,
    "synthesize_pay_id": SynthesizePayIdRule,
    "win_residual": WinResidualRule,
    "bcm_cycle_anchor": BCMCycleAnchorRule,
}


def extract_round_win(
    round_dict: Any,
    rules: list[RoundWinRule] | None = None,
    ctx: dict | None = None,
) -> float:
    """Round's contribution to chunk_win.

    With ``rules=None``/``[]`` returns the legacy ``WinCredits`` lookup
    byte-for-byte. With rules: first non-None ``extract_win`` wins,
    else default.
    """
    if not isinstance(round_dict, dict):
        return 0.0
    if rules:
        for rule in rules:
            v = rule.extract_win(round_dict, ctx)
            if v is not None:
                return float(v)
    return _to_float(round_dict.get("WinCredits"), default=0.0)


def extract_round_payouts(
    round_dict: Any,
    rules: list[RoundWinRule] | None = None,
    ctx: dict | None = None,
) -> dict[str, float]:
    """Round's contribution to per-pay_id attribution.

    With ``rules=None``/``[]`` returns ``round.PayoutIdToWinAmount``
    coerced to ``dict[str, float]`` (or empty dict if absent / wrong
    type) byte-equivalent to legacy. With rules: first non-None
    ``extract_payouts`` wins; ``{}`` from a rule means "explicitly
    no round-level pid credit" (distinct from None which means "use
    default"). The empty-dict and default-empty cases produce the
    same effect on the analyzer (no pid increments) but the rule's
    ``{}`` is intentional.
    """
    if not isinstance(round_dict, dict):
        return {}
    if rules:
        for rule in rules:
            v = rule.extract_payouts(round_dict, ctx)
            if v is not None:
                # Normalize keys to str + values to float for the caller.
                return {str(k): _to_float(val, 0.0) for k, val in v.items()}
    pid = round_dict.get("PayoutIdToWinAmount")
    if isinstance(pid, dict):
        return {str(k): _to_float(v, 0.0) for k, v in pid.items()}
    return {}


def extract_round_trigger_anchor(
    round_dict: Any,
    rules: list[RoundWinRule] | None = None,
    ctx: dict | None = None,
) -> list[str]:
    """Round's trigger-anchor pay_id list (sorted, de-duplicated).

    Combines:
      * Default extraction over ``round.PayoutIdToWinAmount`` -- any
        pay_id key with value 0 (matches the historical
        ``extract_trigger_pay_ids`` semantics from trigger_sessions).
      * Each rule's ``extract_trigger_anchor`` contribution -- merged
        into the default. ``None`` / ``[]`` from a rule means "no
        contribution"; a non-empty list adds those pids.

    Order in the returned list is purely lexicographic; the analyzer's
    downstream anchor-selection heuristic (``max(...,
    key=_pid_anchor_sort_key)`` in player_impact_analyzer) picks the
    canonical anchor when multiple are present, with numeric pids
    winning over synthetic underscore-prefixed ones. This means a
    rule-supplied ``"_bcm_cycle"`` anchor never displaces a real
    numeric pid (e.g. ``"5801"``) on rounds where both signals appear.
    """
    if not isinstance(round_dict, dict):
        return []
    anchors: list[str] = list(
        extract_trigger_pay_ids_default(round_dict.get("PayoutIdToWinAmount"))
    )
    if rules:
        seen = set(anchors)
        for rule in rules:
            extra = rule.extract_trigger_anchor(round_dict, ctx)
            if not extra:
                continue
            for a in extra:
                a_str = str(a)
                if a_str not in seen:
                    seen.add(a_str)
                    anchors.append(a_str)
    anchors.sort()
    return anchors


def round_has_credited_win(
    round_dict: Any,
    rules: list[RoundWinRule] | None = None,
    ctx: dict | None = None,
) -> bool:
    """True iff this round's ``WinCredits`` is already credited to
    pay_ids at round level -- i.e. ``extract_round_payouts`` returns
    a non-empty dict with at least one nonzero value.

    Rule-aware unification of the legacy
    ``trigger_sessions._round_has_credited_win`` (which only checked
    raw ``round.PayoutIdToWinAmount``) and the parallel rule-driven
    check trigger_sessions added later (``bool(rule_payouts)``). One
    function, one source of truth: whatever round-level pay_id
    attribution the configured rules + default produce.

    Used by ``compute_trigger_sessions`` to exclude bonus rounds whose
    win is already at pay_id level from the trigger-session sum
    (double-count guard).
    """
    payouts = extract_round_payouts(round_dict, rules=rules, ctx=ctx)
    if not payouts:
        return False
    for v in payouts.values():
        try:
            w = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            w = 0.0
        if w != 0.0:
            return True
    return False


def load_rules_for_machine(
    machine_id: str,
    config: dict | None,
) -> list[RoundWinRule]:
    """Construct the rule list for one machine from the loaded config.

    Returns ``[]`` when:
      * ``config`` is None / empty.
      * Machine has no rule with it in ``applies_to``.
      * All matching rule types are unknown to RULE_REGISTRY (the
        scan + invariant gate will surface the resulting drift).

    Rules are appended in config-iteration order. When multiple
    rules match a round, the first to return non-None wins
    (``extract_round_win`` and ``extract_round_payouts`` both
    short-circuit on first match).
    """
    if not config or not isinstance(config, dict):
        return []
    rules: list[RoundWinRule] = []
    for rule_id, spec in (config.get("rules") or {}).items():
        if not isinstance(spec, dict):
            continue
        applies_to = spec.get("applies_to") or []
        if machine_id not in applies_to:
            continue
        type_str = spec.get("type")
        rule_cls = RULE_REGISTRY.get(type_str)
        if rule_cls is None:
            continue
        params = spec.get("params") or {}
        try:
            rules.append(rule_cls(**params))
        except (TypeError, ValueError):
            continue
    return rules
