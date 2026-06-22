"""SettlementWinAmountRule — base-EXCLUDED round-win rule type.

Editing this file re-flags only machines that declare ``"settlement_winamount"``
in ``configs/machine_round_win_rules.json`` (via the ``rw:settlement_winamount``
component of their ``effective_version``), never the whole fleet. Logic is
verbatim from the pre-refactor ``fresh_slotlab/round_win.py``.
"""
from __future__ import annotations

from typing import ClassVar

try:
    from fresh_slotlab.round_win import RoundWinRule, _is_paid_round, _to_float
    from fresh_slotlab.round_win_rules import register_rule
except ImportError:  # standalone (cwd=fresh_slotlab/)
    from round_win import RoundWinRule, _is_paid_round, _to_float  # type: ignore[no-redef]
    from round_win_rules import register_rule  # type: ignore[no-redef]


class SettlementWinAmountRule(RoundWinRule):
    """TopDollar selector family (M12/M15/M90/M132): bonus rounds
    are ST=14 selector offer (phantom) + ST=15 settlement (real
    payout in WinAmount, no WinCredits / no PayoutIdToWinAmount).

    Win extraction:
      * settlement ST -> ``WinAmount`` (real payout)
      * phantom ST -> ``0`` (selector offer is preview, not paid)
      * paid rounds (CostCredits>0) -> no override (WinCredits truth)

    Payout attribution (``settlement_label_format`` controls it):
      * Default (``None``): both phantom AND settlement rounds return
        ``{}`` -- the upstream emits no per-round PayoutIdToWinAmount on
        either, so round-level pid aggregation gets nothing to credit.
        Real attribution is done by trigger_sessions.compute_trigger_sessions
        which adds session_win to the trigger pay_id (typically '666' on
        TopDollar machines) found on the paid trigger round preceding the
        bonus block. This is the SESSION-CENTRIC mode (M12/M15/M90/M132).
      * ``"spin_type"``: settlement rounds attribute their ``WinAmount`` to
        a round-level synthetic pid ``f"st{N}"`` instead of delegating to the
        trigger session. Use when the bonus can be triggered from a NON-paid
        round (e.g. M206: a respin ST=50 carries the '666' trigger, so the
        paid opener has no anchor and the trigger-session attribution misses
        those settlements -> orphan _unattributed_stN). Round-level attribution
        captures EVERY settlement regardless of where the trigger sits.
        Phantom rounds still return ``{}`` (offers never pay). RTP is identical
        either way (extract_win is unchanged); only the pid the win lands on
        differs, and the session-dim KPI still books to the trigger session.
    """

    TYPE_STR: ClassVar[str] = "settlement_winamount"

    _VALID_SETTLEMENT_FORMATS = frozenset({"spin_type"})

    def __init__(
        self,
        phantom_spin_types: list[int] | tuple[int, ...] | None = None,
        settlement_spin_types: list[int] | tuple[int, ...] | None = None,
        settlement_label_format: str | None = None,
    ) -> None:
        if settlement_label_format is not None and settlement_label_format not in self._VALID_SETTLEMENT_FORMATS:
            raise ValueError(
                f"settlement_label_format={settlement_label_format!r} not in "
                f"{sorted(self._VALID_SETTLEMENT_FORMATS)} (or None)"
            )
        self.phantom_st: frozenset[int] = frozenset(int(x) for x in (phantom_spin_types or ()))
        self.settlement_st: frozenset[int] = frozenset(int(x) for x in (settlement_spin_types or ()))
        self.settlement_label_format = settlement_label_format

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
        # Settlement ST with round-level attribution requested: mint a synthetic
        # pid for the WinAmount so the settlement is credited at round level
        # (captures bonuses triggered from a non-paid round, which the trigger-
        # session delegate would miss). Phantom rounds always suppress (offers
        # never pay). Default (no settlement_label_format): suppress both and let
        # trigger_sessions credit the trigger pay_id (session-centric).
        if (
            self.settlement_label_format is not None
            and st_int in self.settlement_st
        ):
            win = _to_float(round_dict.get("WinAmount"), default=0.0)
            if win <= 0:
                return {}
            if self.settlement_label_format == "spin_type":
                return {f"st{st_int}": win}
        return {}


register_rule("settlement_winamount", SettlementWinAmountRule)
