"""SynthesizePayIdRule — base-EXCLUDED round-win rule type.

Editing this file re-flags only machines that declare ``"synthesize_pay_id"``
in ``configs/machine_round_win_rules.json`` (via the ``rw:synthesize_pay_id``
component of their ``effective_version``), never the whole fleet. Logic is
verbatim from the pre-refactor ``fresh_slotlab/round_win.py``.
"""
from __future__ import annotations

from typing import ClassVar

try:
    from fresh_slotlab.round_win import RoundWinRule, _to_float
    from fresh_slotlab.round_win_rules import register_rule
except ImportError:  # standalone (cwd=fresh_slotlab/)
    from round_win import RoundWinRule, _to_float  # type: ignore[no-redef]
    from round_win_rules import register_rule  # type: ignore[no-redef]


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

    TYPE_STR: ClassVar[str] = "synthesize_pay_id"

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


register_rule("synthesize_pay_id", SynthesizePayIdRule)
