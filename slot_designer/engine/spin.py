"""SpinEngine — orchestrate a single spin.

Flow:
  1. For each reel (3 for M1), sample a stop via weighted random.
  2. Build 3×3 grid from (top, mid, bot) window of each reel.
  3. Extract payline symbols (middle row for M1's line_id=1).
  4. Evaluate paytable → PayResult | None.
  5. Return SpinOutcome carrying everything the emitter needs.

Future machines add: multi-payline (iterate all lines), bonus respin
(different reel set + state-aware cost), cascading reels (loop until no
wins), etc. All of those live here in new methods, not in a new engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Sequence

from .evaluator import PaytableEvaluator
from .reel_strip import ReelStrip
from .rules import PayResult


@dataclass
class SpinOutcome:
    grid: list[list[str]]              # grid[col][row] = symbol (3×3 for M1)
    pay: PayResult | None
    cost_credits: int
    bet_amount: int
    spin_type: int


class SpinEngine:
    def __init__(
        self,
        reels: Sequence[ReelStrip],
        evaluator: PaytableEvaluator,
        payline_positions: Sequence[tuple[int, int]],
        cost_per_spin: int,
        bet_amount: int,
        spin_type: int = 1,
    ):
        self.reels = list(reels)
        self.evaluator = evaluator
        self.payline_positions = tuple(payline_positions)
        self.cost_per_spin = cost_per_spin
        self.bet_amount = bet_amount
        self.spin_type = spin_type

    @property
    def n_cols(self) -> int:
        return len(self.reels)

    def spin(self, rng: Random) -> SpinOutcome:
        grid: list[list[str]] = []
        for reel in self.reels:
            idx = reel.sample_stop_index(rng.random())
            top, mid, bot = reel.window(idx)
            grid.append([top, mid, bot])

        payline_syms = [grid[c][r] for (c, r) in self.payline_positions]
        pay = self.evaluator.evaluate_payline(payline_syms)

        return SpinOutcome(
            grid=grid,
            pay=pay,
            cost_credits=self.cost_per_spin,
            bet_amount=self.bet_amount,
            spin_type=self.spin_type,
        )
