"""SpinEngine — orchestrate a single spin.

Flow:
  1. For each reel (3 for M1), sample a stop via weighted random.
  2. Build 3×3 grid from (top, mid, bot) window of each reel.
  3. Extract payline symbols (middle row for M1's line_id=1).
  4. Evaluate paytable → PayResult | None.
  5. Return SpinOutcome carrying everything the emitter needs.

v5+ (2026-04-23): SpinEngine optionally carries a ``feature_spec``
(FeatureSpec) that enables ``spin_session()`` — returns the main spin
plus N feature round outputs when the main spin triggers the feature.
M15 uses this to emit production-matching SpinType=14/15 sub-rounds.

Future machines add: multi-payline (iterate all lines), bonus respin
(different reel set + state-aware cost), cascading reels (loop until no
wins), etc. All of those live here in new methods, not in a new engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Sequence

from .evaluator import PaytableEvaluator
from .feature_m15 import FeatureRound, FeatureSpec, simulate_feature_session
from .reel_strip import ReelStrip
from .rules import PayResult


@dataclass
class SpinOutcome:
    grid: list[list[str]]              # grid[col][row] = symbol (3×3 for M1)
    pay: PayResult | None
    cost_credits: int
    bet_amount: int
    spin_type: int
    # v5 M15: scatter-triggered pays that coexist with the main payline
    # pay (e.g. pay_id 666 topdollar trigger, WinCredits=0). Empty list
    # for machines without scatter_trigger rules (M1).
    scatter_pays: list[PayResult] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.scatter_pays is None:
            self.scatter_pays = []


class SpinEngine:
    def __init__(
        self,
        reels: Sequence[ReelStrip],
        evaluator: PaytableEvaluator,
        payline_positions: Sequence[tuple[int, int]],
        cost_per_spin: int,
        bet_amount: int,
        spin_type: int = 1,
        feature_spec: FeatureSpec | None = None,
        feature_trigger_pay_id: int | None = None,
    ):
        self.reels = list(reels)
        self.evaluator = evaluator
        self.payline_positions = tuple(payline_positions)
        self.cost_per_spin = cost_per_spin
        self.bet_amount = bet_amount
        self.spin_type = spin_type
        # v5+: optional feature engine for M15-style bonus mechanics.
        # When present, spin_session() runs feature rounds when the main
        # spin's scatter_pays contains ``feature_trigger_pay_id``.
        self.feature_spec = feature_spec
        self.feature_trigger_pay_id = feature_trigger_pay_id

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
        scatter_pays = self.evaluator.evaluate_scatters(grid, self.payline_positions)

        return SpinOutcome(
            grid=grid,
            pay=pay,
            scatter_pays=scatter_pays,
            cost_credits=self.cost_per_spin,
            bet_amount=self.bet_amount,
            spin_type=self.spin_type,
        )

    def spin_session(self, rng: Random) -> tuple[SpinOutcome, list[FeatureRound]]:
        """Run one paid spin + any triggered feature rounds.

        If the main spin has a scatter pay matching ``feature_trigger_pay_id``,
        simulate the feature session (up to ``max_rounds`` rounds with
        accept/reject logic per ``FeatureSpec``). Returns:
          - Main SpinOutcome (the paid spin, may have regular payline pay too)
          - List of FeatureRound, one per round played (empty if no trigger
            OR engine has no feature_spec configured).

        Rawdata emission (downstream emitter handles):
          main outcome → ST=1 (with ReMarks='Trigger' when feature_rounds
          non-empty); each feature round → ST=14 with WinCredits=r_value×bet;
          followed by ST=15 end marker.
        """
        outcome = self.spin(rng)
        feature_rounds: list[FeatureRound] = []
        if (
            self.feature_spec is not None
            and self.feature_trigger_pay_id is not None
            and any(
                sp.pay_id == self.feature_trigger_pay_id
                for sp in (outcome.scatter_pays or [])
            )
        ):
            feature_rounds = simulate_feature_session(self.feature_spec, rng)
        return outcome, feature_rounds
