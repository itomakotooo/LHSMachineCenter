"""Pay rule definitions + bucketing by kind.

Each pay kind lives in its own dataclass; RuleSet indexes them for O(1)
lookup during evaluation. New kinds are added here + handled in
evaluator.py (not anywhere else).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PayResult:
    pay_id: int
    multiplier: float                             # final multiplier applied to bet
    positions: tuple[tuple[int, int], ...]        # winning (col, row) cells


@dataclass
class CherryCountRule:
    pay_id: int
    count: int
    multiplier: int


@dataclass
class Line3SameRule:
    pay_id: int
    symbol: str
    multiplier: int


@dataclass
class Line3GroupRule:
    pay_id: int
    group: frozenset[str]
    multiplier: int


@dataclass
class PureWildRule:
    pay_id: int
    multiset: dict[str, int]
    multiplier: int
    rtp_excluded: bool = False


@dataclass
class PureWildGroupRule:
    pay_id: int
    alternatives: list[dict[str, Any]]  # [{"multiset": {sym: n}, "multiplier": int}, ...]
    rtp_excluded: bool = False


class RuleSet:
    """Parse spec.pays into typed rule buckets indexed by kind."""

    _SUPPORTED_KINDS = {
        "cherry_count",
        "line_3_same",
        "line_3_group",
        "pure_wild",
        "pure_wild_group",
    }

    def __init__(self, spec_pays: list[dict]):
        self.cherry_by_count: dict[int, CherryCountRule] = {}
        self.line_3_same_by_symbol: dict[str, Line3SameRule] = {}
        self.line_3_group: list[Line3GroupRule] = []
        self.pure_wild: list[PureWildRule] = []
        self.pure_wild_group: list[PureWildGroupRule] = []

        for p in spec_pays:
            kind = p["kind"]
            pid = int(p["pay_id"])
            excluded = bool(p.get("rtp_excluded", False))

            if kind not in self._SUPPORTED_KINDS:
                raise ValueError(
                    f"pay_id {pid}: kind={kind!r} not supported in Phase 1 engine "
                    f"(supported: {sorted(self._SUPPORTED_KINDS)})"
                )

            if kind == "cherry_count":
                c = int(p["count"])
                self.cherry_by_count[c] = CherryCountRule(
                    pay_id=pid, count=c, multiplier=int(p["multiplier"])
                )
            elif kind == "line_3_same":
                self.line_3_same_by_symbol[p["symbol"]] = Line3SameRule(
                    pay_id=pid, symbol=p["symbol"], multiplier=int(p["multiplier"])
                )
            elif kind == "line_3_group":
                self.line_3_group.append(Line3GroupRule(
                    pay_id=pid,
                    group=frozenset(p["group"]),
                    multiplier=int(p["multiplier"]),
                ))
            elif kind == "pure_wild":
                self.pure_wild.append(PureWildRule(
                    pay_id=pid,
                    multiset={k: int(v) for k, v in p["multiset"].items()},
                    multiplier=int(p["multiplier"]),
                    rtp_excluded=excluded,
                ))
            elif kind == "pure_wild_group":
                self.pure_wild_group.append(PureWildGroupRule(
                    pay_id=pid,
                    alternatives=[
                        {
                            "multiset": {k: int(v) for k, v in alt["multiset"].items()},
                            "multiplier": int(alt["multiplier"]),
                        }
                        for alt in p["alternatives"]
                    ],
                    rtp_excluded=excluded,
                ))
