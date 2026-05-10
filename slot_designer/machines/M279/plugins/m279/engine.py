"""M279SpinEngine — multi-payline + nudge + collect + wheel session model.

Distinct from core ``SpinEngine`` (engine/spin.py) which is single-line
+ optional M15-style feature. M279's session is richer:

  Session = 1 paid spin (ST=140) + N MoveSpin (ST=36) + maybe 1 Wheel
  (ST=2) + maybe 1 BuffMap (ST=102), in that order.

Per-spin / per-MoveSpin: evaluate ALL 9 paylines, collect all line
wins into a list of PayResult.

Persistent state (collect meter) lives in M279SessionState carried by
the caller across sessions in a robot's spin loop.

Run signature returns a list of round dicts ready for the M279 emitter
to write into rawdata. Bypassing the M15 (outcome, feature_rounds)
tuple pattern keeps M279 plumbing simpler — emit_round is structurally
different (multi-line PayoutByPayline, AccCredits/CollectCount/etc).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Sequence

from slot_designer.core.engine.evaluator import PaytableEvaluator
from slot_designer.core.engine.reel_strip import ReelStrip
from slot_designer.core.engine.rules import PayResult
from .collect import CollectConfig, CollectMeter
from .nudge import NudgeConfig, detect_partial_stack_reels, nudge_chain
from .wheel import WheelConfig, sample_cell


# Spin type constants matching production rawdata SpinType field.
ST_PAID = 140        # NormalCollectionSpin (cfg logic ST=1)
ST_NUDGE = 36        # MoveSpin
ST_WHEEL = 2         # NewWheel
ST_BUFFMAP = 102     # BuffCollectionMap (UI overlay; trigger only)


@dataclass
class M279Round:
    """One round in an M279 session, ready for emission.

    Maps 1:1 to a JSON dict in upstream rawdata roundResult list.
    """
    spin_type: int
    cost_credits: int
    bet_amount: int
    grid: list[list[str]] | None
    pay_results: list[PayResult]
    win_credits: int
    remarks: str = ""
    # Collect-meter rawdata fields (ST=140 only; None for free spins
    # so the emitter can omit them on non-paid rounds — matches rawdata)
    acc_credits: int | None = None
    collect_count: int | None = None
    credits_symbols: str | None = None
    # Wheel-specific fields (ST=2 only)
    wheel_id: int | None = None
    wheel_cell_index: int | None = None


class M279SpinEngine:
    """Multi-payline + bidirectional nudge + collect-meter + 12-cell wheel."""

    def __init__(
        self,
        reels: Sequence[ReelStrip],
        evaluator: PaytableEvaluator,
        paylines: Sequence[Sequence[tuple[int, int]]],
        cost_per_spin: int,
        bet_amount: int,
        nudge_cfg: NudgeConfig,
        collect_cfg: CollectConfig,
        wheel_cfg: WheelConfig,
    ):
        if len(reels) == 0:
            raise ValueError("M279SpinEngine: no reels provided")
        if len(paylines) == 0:
            raise ValueError("M279SpinEngine: no paylines provided")
        self.reels = list(reels)
        self.evaluator = evaluator
        self.paylines = tuple(tuple(tuple(p) for p in line) for line in paylines)
        self.cost_per_spin = cost_per_spin
        self.bet_amount = bet_amount
        self.nudge_cfg = nudge_cfg
        self.collect_cfg = collect_cfg
        self.wheel_cfg = wheel_cfg

    @property
    def n_cols(self) -> int:
        return len(self.reels)

    @property
    def feature_trigger_pay_id(self) -> int | None:
        """Compatibility shim for emitter callers expecting this attribute
        (M15 feature engines have it; M279 doesn't have a single pay_id
        trigger — collect meter triggers the wheel, no scatter pay).
        """
        return None

    # ── Per-spin grid sampling ────────────────────────────────────
    def _sample_grid(self, rng: Random) -> list[list[str]]:
        """Sample one stop per reel; return 3-row window per column."""
        grid: list[list[str]] = []
        for reel in self.reels:
            idx = reel.sample_stop_index(rng.random())
            top, mid, bot = reel.window(idx)
            grid.append([top, mid, bot])
        return grid

    def _evaluate_grid(self, grid: list[list[str]]) -> tuple[list[PayResult], int]:
        """Evaluate all 9 paylines on the grid. Returns (pay_results,
        total_win_credits)."""
        pays = self.evaluator.evaluate_all_paylines(grid, self.paylines)
        total_win = sum(int(p.multiplier * self.bet_amount) for p in pays)
        return pays, total_win

    # ── Session orchestration ─────────────────────────────────────
    def run_session(
        self,
        rng: Random,
        meter: CollectMeter,
    ) -> list[M279Round]:
        """Run one paid spin + (chained MoveSpins) + (maybe Wheel + BuffMap).

        Mutates ``meter`` in place. Returns list of M279Round in emit
        order. Always non-empty (at least the paid round).
        """
        rounds: list[M279Round] = []

        # 1. Paid spin (ST=140)
        grid = self._sample_grid(rng)
        pays, paid_win = self._evaluate_grid(grid)

        # Increment collect meter ON the paid spin (rawdata shows the
        # post-increment value attached to this round).
        meter.increment(self.collect_cfg)
        will_trigger_wheel = meter.should_trigger(self.collect_cfg)

        rounds.append(M279Round(
            spin_type=ST_PAID,
            cost_credits=self.cost_per_spin,
            bet_amount=self.bet_amount,
            grid=grid,
            pay_results=pays,
            win_credits=paid_win,
            remarks="",
            acc_credits=meter.acc_credits,
            collect_count=meter.collect_count,
            credits_symbols=f"{self.collect_cfg.credit_unit}:{self.collect_cfg.max} | ",
        ))

        # 2. Nudge chain (ST=36 free spins) — operates on the paid grid
        partial_reels = detect_partial_stack_reels(grid)
        if partial_reels:
            chain = nudge_chain(grid, self.nudge_cfg)
            for nudge_grid in chain:
                nudge_pays, nudge_win = self._evaluate_grid(nudge_grid)
                rounds.append(M279Round(
                    spin_type=ST_NUDGE,
                    cost_credits=0,
                    bet_amount=self.bet_amount,
                    grid=[list(col) for col in nudge_grid],
                    pay_results=nudge_pays,
                    win_credits=nudge_win,
                    remarks="move",
                ))

        # 3. Wheel (ST=2) + BuffMap (ST=102) when meter triggered
        if will_trigger_wheel:
            cell = sample_cell(self.wheel_cfg, rng)
            rounds.append(M279Round(
                spin_type=ST_WHEEL,
                cost_credits=0,
                bet_amount=self.bet_amount,
                grid=None,  # Wheel rounds carry no grid (NULL in rawdata)
                pay_results=[],
                win_credits=cell.win_credits,
                remarks=f"WheelSpin CellIndex {cell.cell_index}; WheelId {self.wheel_cfg.wheel_id};",
                wheel_id=self.wheel_cfg.wheel_id,
                wheel_cell_index=cell.cell_index,
            ))
            rounds.append(M279Round(
                spin_type=ST_BUFFMAP,
                cost_credits=0,
                bet_amount=0,  # BuffMap is trigger-only with bet=0 per rawdata
                grid=None,
                pay_results=[],
                win_credits=0,
                remarks="",
            ))
            # Reset meter to post-trigger state (mirrors rawdata: next
            # paid spin's meter shows acc_credits=100, count=1).
            meter.reset_post_trigger(self.collect_cfg)

        return rounds


@dataclass
class M279SessionState:
    """Per-robot persistent state across sessions in a chunk.

    For M279, the only persistent state across sessions is the
    collect meter (which carries between paid spins until the wheel
    fires).
    """
    meter: CollectMeter = field(default_factory=CollectMeter)
