"""Round-level win extraction with per-machine rule overrides.

Default behaviour (no rules) is byte-identical to the legacy
``r.get("WinCredits", 0)`` lookup so machines without an entry in
``configs/machine_round_win_rules.json`` see zero change.

Rule registry pattern: each rule type implements
``RoundWinRule.extract(round_dict, ctx) -> float | None``. Returning
``None`` means "this rule doesn't apply to this round, fall through".
The first rule that returns a non-None value wins; if all return None,
the default ``WinCredits`` lookup is used.

Adding a new rule type (e.g. for M112-style sub-round duplication):
  1. Subclass ``RoundWinRule`` in this file.
  2. Register it in ``RULE_REGISTRY`` with a stable ``type`` string.
  3. Add a config entry in ``configs/machine_round_win_rules.json``
     with the new ``type`` string + its params + ``applies_to``.
  4. Add unit tests in ``tests/backend/test_round_win.py``.

The analyzer + trigger_sessions helper are the only callers; they
load rules per-machine via ``load_rules_for_machine`` once at chunk
parse start and pass the list into every per-round call.
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
    """Paid round classifier — same predicate as
    ``trigger_sessions._is_paid_round`` (CostCredits > 0). Duplicated
    here to avoid a circular import; both modules need the predicate.
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


class RoundWinRule:
    """Base class. Subclasses override ``extract``.

    A rule may be stateful across rounds within one robot (e.g.
    summary-vs-sub-round dedupe needs to remember the previous round).
    Stateful rules should be instantiated per-robot, not per-chunk —
    callers pass a fresh list to ``extract_round_win`` for each robot.
    Stateless rules can be reused.
    """

    def extract(self, round_dict: dict, ctx: dict | None = None) -> float | None:
        """Return overridden round win, or None if rule doesn't apply.

        ``ctx`` is a free-form dict the caller passes through (currently
        unused by all built-in rules, but reserved for stateful future
        rules that need round_index / prev_round / robot_id).
        """
        raise NotImplementedError


class SettlementWinAmountRule(RoundWinRule):
    """Handles TopDollar-selector style ``ST=14 phantom offer →
    ST=15 settlement WinAmount`` machines (M12 / M15 / M90 / M132 …).

    Two SpinType groups are configured:

      * ``settlement_spin_types``: bonus rounds carrying the real
        payout in the ``WinAmount`` field (no ``WinCredits``).
        Override returns ``WinAmount``.
      * ``phantom_spin_types``: bonus rounds whose ``WinCredits`` is
        the player-facing offer-preview value, NOT the actual payout.
        Override returns ``0`` so they don't pollute round-level win
        sums; the trigger-session helper attributes the real win to
        the trigger pay_id via the matching settlement round.

    Paid rounds (CostCredits > 0) are NOT touched even if their
    SpinType happens to coincide with a configured group — paid
    WinCredits is always authoritative on those machines.
    """

    def __init__(
        self,
        phantom_spin_types: list[int] | tuple[int, ...] | None = None,
        settlement_spin_types: list[int] | tuple[int, ...] | None = None,
    ) -> None:
        self.phantom_st: frozenset[int] = frozenset(int(x) for x in (phantom_spin_types or ()))
        self.settlement_st: frozenset[int] = frozenset(int(x) for x in (settlement_spin_types or ()))

    def extract(self, round_dict: dict, ctx: dict | None = None) -> float | None:
        if not isinstance(round_dict, dict):
            return None
        # Paid rounds: never override — WinCredits is truth.
        if _is_paid_round(round_dict):
            return None
        st = round_dict.get("SpinType")
        try:
            st_int = int(st) if st is not None else None
        except (TypeError, ValueError):
            return None
        if st_int is None:
            return None
        if st_int in self.settlement_st:
            return _to_float(round_dict.get("WinAmount"), default=0.0)
        if st_int in self.phantom_st:
            return 0.0
        return None


# Stable ``type`` string → class. Add new rule types here.
RULE_REGISTRY: dict[str, type[RoundWinRule]] = {
    "settlement_winamount": SettlementWinAmountRule,
}


def extract_round_win(
    round_dict: Any,
    rules: list[RoundWinRule] | None = None,
    ctx: dict | None = None,
) -> float:
    """Return this round's contribution to chunk_win.

    With ``rules=None`` or ``rules=[]`` returns the legacy
    ``WinCredits`` lookup byte-for-byte — machines without a config
    entry see zero behavioral change.

    With rules: first rule whose ``extract`` returns non-None wins.
    Otherwise falls through to default WinCredits lookup.
    """
    if not isinstance(round_dict, dict):
        return 0.0
    if rules:
        for rule in rules:
            v = rule.extract(round_dict, ctx)
            if v is not None:
                return float(v)
    return _to_float(round_dict.get("WinCredits"), default=0.0)


def load_rules_for_machine(
    machine_id: str,
    config: dict | None,
) -> list[RoundWinRule]:
    """Construct the rule list for one machine from the loaded config.

    Returns ``[]`` when:
      * ``config`` is None / empty (file missing or empty).
      * Machine has no rule with it in ``applies_to``.
      * All matching rule types are unknown to RULE_REGISTRY (callers
        should treat this as a config error; we log + skip rather than
        crash so a typo doesn't take down a fleet run).

    Rules are appended in config-iteration order, so the first matching
    rule's verdict wins on overlapping SpinTypes (intentional —
    operator can layer rules by ordering them in the JSON).
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
            # Unknown rule type — config drift / typo. Skip rather than
            # crash; the fleet drift scan + per-machine invariant log
            # will surface the resulting mismatch.
            continue
        params = spec.get("params") or {}
        try:
            rules.append(rule_cls(**params))
        except TypeError:
            # Bad params for known rule type — same skip-and-log policy.
            continue
    return rules
