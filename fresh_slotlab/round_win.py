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


def _is_paid_round(r: Any) -> bool:
    """Paid round classifier mirroring trigger_sessions._is_paid_round
    (CostCredits > 0). Duplicated to avoid circular import; both
    modules need the predicate."""
    if not isinstance(r, dict):
        return False
    cc = r.get("CostCredits")
    if cc is None:
        return False
    try:
        return float(cc) > 0.0
    except (TypeError, ValueError):
        return False


class RoundWinRule:
    """Base class for per-machine round-level overrides.

    Subclasses override ``extract_win`` and/or ``extract_payouts``.
    ``ctx`` is a free-form dict passed through by callers; current
    callers populate ``{"bet": int}`` for rules that need the chunk
    bet amount (e.g. multiplier-based pay_id synthesis).

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


# Stable type-string -> class. Add new rule types here.
RULE_REGISTRY: dict[str, type[RoundWinRule]] = {
    "settlement_winamount": SettlementWinAmountRule,
    "synthesize_pay_id": SynthesizePayIdRule,
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
