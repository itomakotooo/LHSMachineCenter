"""Symbol registry parsed from spec.

Known kinds (2026-04-24):
  - filler:        blank / decorative stops that never pay
  - cherry_special: M1 cherry (independent count-based pay)
  - regular:       standard paying symbol (high7, bars, etc.)
  - wild:          substitutes for regular symbols (M1 Diamond1/2, M15
                   doublediamond). ``multiplier`` field stacks per-wild
                   when wilds appear on payline.
  - booster (M37+): jackpot-tier symbol on middle reel (mini/minor/major/
                    grand). Acts as a center-cell MULTIPLIER on 3-match
                    payline pays AND a standalone pay by its own tier
                    value. ``multiplier`` is the booster factor (mini=2,
                    minor=5, major=10, grand=100).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str            # "regular" | "wild" | "cherry_special" | "filler" | "booster"
    multiplier: int = 1  # wild: per-wild stack multiplier; booster: tier multiplier
    # M279+ 2026-04-28: nudge anchor metadata for stacked-wild trio.
    # Symbols that are part of a stack carry this; non-stack wilds carry None.
    nudge_anchor: str | None = None  # "up" | "down" | None (mid stack member or
                                     # non-stack wild)

    @property
    def is_wild(self) -> bool:
        return self.kind == "wild"

    @property
    def is_cherry(self) -> bool:
        return self.kind == "cherry_special"

    @property
    def is_filler(self) -> bool:
        return self.kind == "filler"

    @property
    def is_booster(self) -> bool:
        return self.kind == "booster"

    @property
    def is_nudge_anchor(self) -> bool:
        return self.nudge_anchor in ("up", "down")


class SymbolRegistry:
    _KNOWN_KINDS = {"filler", "cherry_special", "regular", "wild", "booster"}

    def __init__(self, spec_symbols: dict):
        self.by_name: dict[str, Symbol] = {}
        for name, attrs in spec_symbols.items():
            kind = attrs["kind"]
            if kind not in self._KNOWN_KINDS:
                raise ValueError(
                    f"symbol {name!r}: kind={kind!r} not supported in Phase 1 engine "
                    f"(known: {sorted(self._KNOWN_KINDS)})"
                )
            mult = int(attrs.get("multiplier", 1))
            anchor = attrs.get("_nudge_anchor")
            if anchor is not None and anchor not in ("up", "down"):
                raise ValueError(
                    f"symbol {name!r}: _nudge_anchor must be 'up' or 'down', "
                    f"got {anchor!r}"
                )
            self.by_name[name] = Symbol(
                name=name, kind=kind, multiplier=mult, nudge_anchor=anchor,
            )

    def get(self, name: str) -> Symbol:
        sym = self.by_name.get(name)
        if sym is None:
            raise KeyError(f"unknown symbol: {name!r}")
        return sym
