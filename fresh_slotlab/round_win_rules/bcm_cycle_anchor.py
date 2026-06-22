"""BCMCycleAnchorRule — base-EXCLUDED round-win rule type.

Editing this file re-flags only machines that declare ``"bcm_cycle_anchor"`` in
``configs/machine_round_win_rules.json`` (via the ``rw:bcm_cycle_anchor``
component of their ``effective_version``), never the whole fleet. Logic is
verbatim from the pre-refactor ``fresh_slotlab/round_win.py``.
"""
from __future__ import annotations

from typing import ClassVar

try:
    from fresh_slotlab.round_win import RoundWinRule, is_paid_round
    from fresh_slotlab.round_win_rules import register_rule
except ImportError:  # standalone (cwd=fresh_slotlab/)
    from round_win import RoundWinRule, is_paid_round  # type: ignore[no-redef]
    from round_win_rules import register_rule  # type: ignore[no-redef]


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

    TYPE_STR: ClassVar[str] = "bcm_cycle_anchor"

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


register_rule("bcm_cycle_anchor", BCMCycleAnchorRule)
