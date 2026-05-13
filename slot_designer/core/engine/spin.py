"""SpinEngine — orchestrate a single spin.

Flow:
  1. For each reel, sample a stop via weighted random.
  2. Build 3-row × n-cols grid from each reel's (top, mid, bot) window.
  3. Extract payline symbols.
  4. Evaluate paytable → PayResult | None.
  5. Return SpinOutcome carrying everything the emitter needs.

Plugin extension (ARCHITECTURE.md §3): SpinEngine optionally carries a
``plugin: FeaturePlugin`` instance loaded from ``machines/<M>/plugins/``.
When present, ``spin_session()`` returns the main spin plus N feature
rounds (plugin-private dataclass) when the main spin's scatter_pays
includes ``plugin.trigger_pay_id``. Generic core never imports the
concrete plugin class — only the FeaturePlugin Protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, Sequence

from .evaluator import PaytableEvaluator
from .feature_protocol import FeaturePlugin
from .reel_strip import ReelStrip
from .rules import PayResult, RerollBlockRule


def _matches_any_reroll(
    payline_syms: list[str],
    rules: list[RerollBlockRule],
) -> bool:
    """Return True if payline_syms matches any reroll pattern (with None
    as wildcard). Patterns must be exact length (same # of cols).
    """
    for rule in rules:
        if len(rule.pattern) != len(payline_syms):
            continue
        if all(p is None or p == s for p, s in zip(rule.pattern, payline_syms)):
            return True
    return False


@dataclass
class SpinOutcome:
    grid: list[list[str]]              # grid[col][row] = symbol
    pay: PayResult | None
    cost_credits: int
    bet_amount: int
    spin_type: int
    # Scatter-triggered pays that coexist with the main payline pay.
    # Empty list for machines without scatter_trigger rules.
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
        plugin: FeaturePlugin | None = None,
    ):
        self.reels = list(reels)
        self.evaluator = evaluator
        self.payline_positions = tuple(payline_positions)
        self.cost_per_spin = cost_per_spin
        self.bet_amount = bet_amount
        self.spin_type = spin_type
        # Optional FeaturePlugin (machines/<M>/plugins/) for feature-bearing
        # machines. None for base-only machines.
        self.plugin: FeaturePlugin | None = plugin

    @property
    def n_cols(self) -> int:
        return len(self.reels)

    def spin(self, rng: Random) -> SpinOutcome:
        """Draw one spin; re-roll if the payline pattern hits a spec-
        declared block rule.

        Re-roll cap = 50 attempts; beyond that, raise (indicates a spec
        with over-constrained blocks or an impossible strip layout).
        """
        reroll_rules = (
            self.evaluator.rules.reroll_blocks
            if getattr(self.evaluator, "rules", None) is not None
            else []
        )
        max_rerolls = 50

        for _attempt in range(max_rerolls + 1):
            grid: list[list[str]] = []
            for reel in self.reels:
                idx = reel.sample_stop_index(rng.random())
                top, mid, bot = reel.window(idx)
                grid.append([top, mid, bot])

            payline_syms = [grid[c][r] for (c, r) in self.payline_positions]

            if reroll_rules and _matches_any_reroll(payline_syms, reroll_rules):
                continue  # re-draw the spin

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

        raise RuntimeError(
            f"spin re-rolled {max_rerolls}+ times without finding an allowed "
            f"payline; spec reroll_blocks may be over-constraining the strip "
            f"(last payline: {payline_syms!r})"
        )

    def spin_session(self, rng: Random) -> tuple[SpinOutcome, list[Any]]:
        """Run one paid spin + any triggered feature rounds.

        Two trigger modes:

          1. **Scatter-pay trigger** (``plugin.trigger_pay_id`` is set):
             plugin fires when ``outcome.scatter_pays`` contains the
             configured ``pay_id`` (e.g. M15 topdollar on reel 3 →
             pay_id 666). This is the historical M15-style trigger.

          2. **Outcome-conditional trigger** (``plugin.trigger_pay_id``
             is ``None``): plugin fires every paid spin and decides
             internally whether to emit feature rounds based on the
             paid spin's outcome. Returning ``[]`` from
             ``simulate_session`` means "no extra rounds this spin".
             Used by post-win mechanics like M43's respin / mini-game
             (which fire probabilistically after wins, not on a scatter
             symbol).

        For backward compatibility, ``simulate_session(rng)`` is called
        with positional ``rng`` only in mode 1; in mode 2 we additionally
        pass ``outcome=<SpinOutcome>`` as a keyword argument. Plugins
        that don't need outcome may simply ignore the kwarg (Python
        permits **kwargs absorption or explicit ``outcome=None`` default).

        Returns:
          (outcome, feature_rounds)
            outcome — the paid spin (may also have regular payline pay).
            feature_rounds — plugin-private list (e.g. M15FeatureRound
              objects). Empty list when no plugin OR no trigger.
        """
        outcome = self.spin(rng)
        feature_rounds: list[Any] = []
        if self.plugin is not None:
            if self.plugin.trigger_pay_id is not None:
                # Scatter-pay trigger (M15-style).
                if any(
                    sp.pay_id == self.plugin.trigger_pay_id
                    for sp in (outcome.scatter_pays or [])
                ):
                    feature_rounds = self.plugin.simulate_session(rng)
            else:
                # Outcome-conditional trigger (M43-style). Plugin sees
                # the outcome and decides itself whether to emit extras.
                feature_rounds = self.plugin.simulate_session(
                    rng, outcome=outcome,
                )
        return outcome, feature_rounds
