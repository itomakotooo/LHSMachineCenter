"""WinResidualRule — base-EXCLUDED round-win rule type.

Editing this file re-flags only machines that declare ``"win_residual"`` in
``configs/machine_round_win_rules.json`` (via the ``rw:win_residual`` component
of their ``effective_version``), never the whole fleet. Logic is verbatim from
the pre-refactor ``fresh_slotlab/round_win.py``.
"""
from __future__ import annotations

from typing import ClassVar

try:
    from fresh_slotlab.round_win import RoundWinRule, _to_float
    from fresh_slotlab.round_win_rules import register_rule
except ImportError:  # standalone (cwd=fresh_slotlab/)
    from round_win import RoundWinRule, _to_float  # type: ignore[no-redef]
    from round_win_rules import register_rule  # type: ignore[no-redef]


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

    TYPE_STR: ClassVar[str] = "win_residual"

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


register_rule("win_residual", WinResidualRule)
