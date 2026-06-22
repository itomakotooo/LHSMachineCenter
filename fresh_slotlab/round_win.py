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

Architecture (pluggable rule types)
-----------------------------------
This module holds only the SHARED core: the ``RoundWinRule`` ABC, the
dispatch functions (``extract_round_win`` / ``extract_round_payouts`` /
``extract_round_trigger_anchor`` / ``round_has_credited_win``),
``load_rules_for_machine``, and the small helpers. It is in
``_CLOSURE_FILES`` — changing the ABC contract or the dispatch is a
legitimate fleet-wide base_hash flip.

The rule TYPE classes live as auto-discovered, base-EXCLUDED plugins under
``fresh_slotlab/round_win_rules/`` (mirroring ``features/`` + ``st_extract/``).
Adding OR editing a rule type re-flags only the machines that declare it (via
its ``rw:<type_str>`` ``effective_version`` component), never the whole fleet.

Adding a new rule type:
  1. Create ``fresh_slotlab/round_win_rules/<type_str>.py``.
  2. Subclass ``RoundWinRule`` (import it from ``fresh_slotlab.round_win``);
     set ``TYPE_STR`` and override ``extract_win`` / ``extract_payouts`` /
     ``extract_trigger_anchor`` as needed.
  3. Call ``register_rule("<type_str>", <Class>)`` at the bottom of the file.
  4. Add a config entry in ``machine_round_win_rules.json`` pointing at
     ``type: "<type_str>"`` with an ``applies_to`` list.
  5. Add unit tests.
  No closure file is edited — no base_hash flip.

The 4 built-in rule classes (``SettlementWinAmountRule``,
``SynthesizePayIdRule``, ``WinResidualRule``, ``BCMCycleAnchorRule``) and
``RULE_REGISTRY`` remain importable from ``fresh_slotlab.round_win`` for
backward compatibility via a lazy module-level ``__getattr__`` (they now live
in ``round_win_rules/``).
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


# ---------------------------------------------------------------------------
# Rule TYPE classes + RULE_REGISTRY moved to the base-EXCLUDED, auto-discovered
# package fresh_slotlab/round_win_rules/ (mirrors features/ + st_extract/).
# They remain importable from this module via the lazy __getattr__ at the bottom
# of the file (backward compat), but are no longer defined here — so editing or
# adding a rule type no longer flips base_hash. See the module docstring.
# ---------------------------------------------------------------------------


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
    # Ensure the base-excluded rule-type plugins are discovered before
    # consulting RULE_REGISTRY (idempotent — no-op once run). Lazy import keeps
    # round_win.py free of any module-load dependency on round_win_rules, which
    # would create an import cycle (round_win_rules modules import RoundWinRule
    # from here). Dual-path covers script-mode (cwd=fresh_slotlab/) per
    # memory/feedback_subprocess_import_suicide_and_module_globals.md.
    try:
        from fresh_slotlab.round_win_rules import RULE_REGISTRY, discover_rules
    except ImportError:
        from round_win_rules import RULE_REGISTRY, discover_rules  # type: ignore[no-redef]
    discover_rules()
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


# ---------------------------------------------------------------------------
# Backward-compat lazy re-exports (PEP 562).
#
# The 4 built-in rule classes and RULE_REGISTRY moved to the base-excluded
# round_win_rules/ package. Callers that still do
# ``from fresh_slotlab.round_win import SettlementWinAmountRule`` (or import
# RULE_REGISTRY) keep working: __getattr__ resolves the name on demand, AFTER
# this module is fully loaded, so there is NO module-load import of the package
# and therefore NO import cycle. Every class resolves through the single
# canonical path (the discovered RULE_REGISTRY), so identity assertions like
# ``RULE_REGISTRY["settlement_winamount"] is SettlementWinAmountRule`` hold.
# ---------------------------------------------------------------------------

_LAZY_RULE_EXPORTS: dict[str, str] = {
    "SettlementWinAmountRule": "settlement_winamount",
    "SynthesizePayIdRule": "synthesize_pay_id",
    "WinResidualRule": "win_residual",
    "BCMCycleAnchorRule": "bcm_cycle_anchor",
}


def __getattr__(name: str) -> Any:
    if name == "RULE_REGISTRY" or name in _LAZY_RULE_EXPORTS:
        try:
            from fresh_slotlab import round_win_rules as _pkg
        except ImportError:
            import round_win_rules as _pkg  # type: ignore[no-redef]
        _pkg.discover_rules()
        if name == "RULE_REGISTRY":
            return _pkg.RULE_REGISTRY
        cls = _pkg.RULE_REGISTRY.get(_LAZY_RULE_EXPORTS[name])
        if cls is not None:
            return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
