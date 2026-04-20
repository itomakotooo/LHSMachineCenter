"""Symbol registry parsed from spec."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str            # "regular" | "wild" | "cherry_special" | "filler"
    multiplier: int = 1  # only meaningful for kind="wild"

    @property
    def is_wild(self) -> bool:
        return self.kind == "wild"

    @property
    def is_cherry(self) -> bool:
        return self.kind == "cherry_special"

    @property
    def is_filler(self) -> bool:
        return self.kind == "filler"


class SymbolRegistry:
    _KNOWN_KINDS = {"filler", "cherry_special", "regular", "wild"}

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
            self.by_name[name] = Symbol(name=name, kind=kind, multiplier=mult)

    def get(self, name: str) -> Symbol:
        sym = self.by_name.get(name)
        if sym is None:
            raise KeyError(f"unknown symbol: {name!r}")
        return sym
