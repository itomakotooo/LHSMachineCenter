"""Wheel feature — 12-cell weighted sampler.

Spec: 12 fixed cells (cellIndex 1-12), each carries (weight, win_credits).
Win is paid as raw credits (not multiplier × bet); the rawdata
PayoutIdToWinAmount field uses pay_id keyed by multiplier (5/10/20/30/
50/100x bet → pay_id "5"/"10"/"20"/"30"/"50"/"100").

User constraint (2026-04-28): 12 cell count is FIXED — LHS cannot
change. Weights are tunable per mode but cellIndex layout is locked.

E[wheel_win] for the default cells = 40,000 credits = 40× bet (at
bet=1000). With ~1 wheel trigger per 1140 paid spins, wheel RTP
contribution ≈ 40 / 1140 ≈ 3.5%.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass


@dataclass(frozen=True)
class WheelCell:
    cell_index: int
    weight: float
    win_credits: int


@dataclass
class WheelConfig:
    wheel_id: int
    cells: tuple[WheelCell, ...]

    def __post_init__(self):
        if len(self.cells) == 0:
            raise ValueError("WheelConfig: cells must be non-empty")
        if any(c.weight <= 0 for c in self.cells):
            raise ValueError("WheelConfig: all cell weights must be positive")

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.cells)

    def expected_win(self) -> float:
        """Analytic E[wheel win] in credits."""
        tw = self.total_weight
        return sum(c.weight * c.win_credits for c in self.cells) / tw if tw > 0 else 0.0


def load_wheel_config(spec: dict) -> WheelConfig:
    """Parse the wheel block out of an M279 spec dict.

    Raises ValueError when no wheel block (M279 always has one; this
    catches misconfigured specs early rather than running into KeyError
    deep in spin_session).
    """
    block = (spec.get("_m279_features") or {}).get("wheel")
    if not block:
        raise ValueError("M279 spec missing _m279_features.wheel block")
    cells = tuple(
        WheelCell(
            cell_index=int(c["cellIndex"]),
            weight=float(c["weight"]),
            win_credits=int(c["win_credits"]),
        )
        for c in block["cells"]
    )
    return WheelConfig(
        wheel_id=int(block.get("wheel_id", 1)),
        cells=cells,
    )


def sample_cell(cfg: WheelConfig, rng) -> WheelCell:
    """Draw one cell via cumulative-weight inverse-CDF sampling."""
    cum: list[float] = []
    acc = 0.0
    for c in cfg.cells:
        acc += c.weight
        cum.append(acc)
    target = rng.random() * acc
    idx = bisect.bisect_right(cum, target)
    if idx >= len(cfg.cells):
        idx = len(cfg.cells) - 1
    return cfg.cells[idx]
