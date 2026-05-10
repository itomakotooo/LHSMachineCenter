"""Reel strip with weighted stop sampling.

A reel has N stops; each stop has (symbol, weight). Sampling picks a stop
via weighted random (probability = weight / total). The display window
at a given stop is stops[(idx-1) % N], stops[idx], stops[(idx+1) % N]
— (top, mid, bot). This matches what StopSymbolsByCol[i] encodes in the
existing rawdata: "<top>-<mid>-<bot>-".
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Stop:
    symbol: str
    weight: float   # v5 2026-04-23: widened from int to float to support
                    # machine's fractional topdollar weight (6.44 for exact
                    # 1/88 trigger rate). Pre-v5 int weights still work
                    # (stored as float internally).


class ReelStrip:
    def __init__(self, stops: Sequence[Stop]):
        if not stops:
            raise ValueError("reel has no stops")
        if any(s.weight < 0 for s in stops):
            raise ValueError("stop weights must be non-negative")
        self.stops = list(stops)
        self._cum_weights: list[float] = []
        acc = 0.0
        for s in stops:
            acc += s.weight
            self._cum_weights.append(acc)
        self.total_weight = acc
        if self.total_weight <= 0:
            raise ValueError("at least one stop must have positive weight")
        # 2026-05-08: zero-weight stops are allowed — production cfgs use
        # weight=0 to "remove" a symbol from sampling while keeping it on
        # the visual strip (it shows in top/bot windows but never at mid).
        # bisect_right naturally skips zero-weight stops as a landing
        # position. Engine analytic + simulate both honor this.

    def __len__(self) -> int:
        return len(self.stops)

    def sample_stop_index(self, rng_float: float) -> int:
        """``rng_float`` in [0, 1). Returns index of sampled stop via inverse CDF."""
        target = rng_float * self.total_weight
        return bisect.bisect_right(self._cum_weights, target)

    def window(self, idx: int) -> tuple[str, str, str]:
        """(top, mid, bot) symbols for the stop at idx, cyclical."""
        n = len(self.stops)
        return (
            self.stops[(idx - 1) % n].symbol,
            self.stops[idx].symbol,
            self.stops[(idx + 1) % n].symbol,
        )

    def symbol_marginal_prob(self, symbol: str) -> float:
        """P(picked stop's payline symbol == `symbol`). For machine this is reel 1's
        middle-row marginal (probability that the payline cell shows `symbol`).
        """
        w = sum(s.weight for s in self.stops if s.symbol == symbol)
        return w / self.total_weight if self.total_weight else 0.0
