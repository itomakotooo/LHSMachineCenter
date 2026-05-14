"""Pay rule definitions + bucketing by kind.

Each pay kind lives in its own dataclass; RuleSet indexes them for O(1)
lookup during evaluation. New kinds are added here + handled in
evaluator.py (not anywhere else).

v5+ additions for single-line slots (2026-04-23):
  - ``line_3_same`` gains optional ``wild_required`` field. Multiple rules
    per symbol become supported: machine high7 splits into pay_id 21 (pure,
    no wild) vs pay_id 2 (wild-boosted, ≥1 wild substitute). machine behavior
    preserved when field is absent (= None = don't care).
  - New ``scatter_trigger`` kind: emits a no-win pay marker when a given
    symbol lands on a specific reel's payline cell. machine uses this for
    pay_id 666 (topdollar on reel 3 payline = feature trigger marker).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


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
    multiplier: float       # widened to float 2026-04-28 for single-line slots pay 7 (0.3× bet)
    # v5 machine: optional constraint on wild participation.
    #   None  = no constraint (machine-era behavior; matches regardless of wilds)
    #   True  = requires ≥1 wild substitute among payline cells
    #   False = requires 0 wild substitutes (all three cells are the base symbol)
    # When two line_3_same rules target the same symbol with opposite
    # wild_required values, the evaluator picks whichever rule matches
    # the actual wild count on the payline.
    wild_required: Optional[bool] = None


@dataclass
class Line3GroupRule:
    pay_id: int
    group: frozenset[str]
    multiplier: float       # widened to float 2026-04-28 for single-line slots pay 7 (0.3× bet)


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


@dataclass
class ScatterTriggerRule:
    """Emit a no-win pay marker when ``symbol`` lands on the ``reel``-th
    reel's payline cell. Used by machine for pay_id 666 (topdollar on reel 3
    payline = Feature Play trigger marker; WinCredits=0 in rawdata).
    """
    pay_id: int
    symbol: str
    reel: int              # 1-indexed reel number (machine: 3 = rightmost)
    multiplier: int = 0    # typically 0 (scatter pay = marker only)


# machine+ booster-tier pay rules (2026-04-24):
#
# machine introduces a "booster" symbol tier (mini/minor/major/grand) on the
# middle reel only. When a booster lands at the payline's center cell,
# it acts as a MULTIPLIER on any 3-match pay that fits the side cells:
#   (target, mini, target)  = pay_id[target] × 2
#   (target, minor, target) = pay_id[target] × 5
#   (target, major, target) = pay_id[target] × 10
#   (target, grand, target) = pay_id[target] × 100
#
# Wilds on side cells substitute for target. A few distinguished cases
# get their OWN pay_id (not just "same pay_id × booster factor"):
#   - pure-wild sides with booster center → pay_id 102/103/104
#     (tracking "all-wild assisted" combos separately from symbol-anchored)
#   - booster standalone (no side match) → pay_id 8 (grand) or 9 (others)
#   - wild standalone on col 0 or col 2, no booster center, no match
#     → pay_id 9 × 1

@dataclass
class PureWildWithBoosterRule:
    """(wild, booster, wild) — both side cells pure wild with specific
    booster tier in center. Gets its own pay_id (102/103/104 on single-line slots)
    separate from symbol-anchored paths (pay_id 1 with booster center).
    Multiplier is explicit (= high7_base × booster_multiplier on single-line slots).
    """
    pay_id: int
    booster_symbol: str    # e.g. "mini" / "minor" / "major"
    multiplier: int        # explicit (not computed from base × booster)


@dataclass
class CenterBoosterAloneRule:
    """pay_id 8/9 on single-line slots — booster in col 1 with side cells NOT forming
    a 3-match and NOT pure-wild. Multiplier = booster's tier value:
    mini=2, minor=5, major=10, grand=100.
    """
    pay_id: int
    booster_symbol: str    # "mini" | "minor" | "major" | "grand"
    multiplier: int


@dataclass
class SideWildAloneRule:
    """pay_id 9 on single-line slots — wild on col 0 or col 2 (or both) with col 1
    neither booster nor matching a 3-match pay. Multiplier is flat
    (usually 1× per machine); 2-wild combos still emit a single pay_id
    with the same flat multiplier (not 2× multiplier).
    """
    pay_id: int
    multiplier: int


@dataclass
class RerollBlockRule:
    """Machine-specific forbidden payline pattern — if the generated
    payline matches, spin.py should re-roll. Used by machine to block
    (wild, grand, wild) from paying the natural 1000× top tier;
    observed in 2.14M rounds of machine rawdata as 0 occurrences,
    confirming the game mechanic rerolls these spins server-side.

    The payline pattern is a list of symbol names (in col order) or
    None for wildcards. For machine: ``pattern = ["wild", "grand", "wild"]``.
    """
    pattern: list  # list of str or None (wildcard)
    reason: str = ""  # docstring-style, not evaluated


class RuleSet:
    """Parse spec.pays into typed rule buckets indexed by kind."""

    _SUPPORTED_KINDS = {
        "cherry_count",
        "line_3_same",
        "line_3_group",
        "pure_wild",
        "pure_wild_group",
        "scatter_trigger",
        # machine+ booster-tier pay kinds (2026-04-24):
        "pure_wild_with_booster",
        "center_booster_alone",
        "side_wild_alone",
        # plugin_handled (2026-05-14): pay_id whose trigger + multiplier
        # logic is entirely implemented in the machine's FeaturePlugin
        # post-evaluator (e.g. M43 pay_id 8 "wild_blank_special").
        # Primary reason this kind exists in core: WITHOUT it, a spec.json
        # entry with kind="plugin_handled" would cause RuleSet.__init__ to
        # raise ValueError at load time ("kind not supported"), breaking
        # spec loading for ANY machine that uses plugin-side pay logic.
        # Secondary: declaring the pay_id in spec.json documents which
        # pay_ids are "owned" by the plugin; RTP tracking reads from
        # emitted PayoutIdToWinAmount (not from spec entries directly).
        "plugin_handled",
    }

    def __init__(self, spec_pays: list[dict], reroll_blocks: list[dict] | None = None):
        self.cherry_by_count: dict[int, CherryCountRule] = {}
        # v5 machine: list-per-symbol (was dict[str, Line3SameRule]) so
        # multiple rules can coexist for the same symbol (e.g., high7
        # pay_id 2 with wild_required=True plus pay_id 21 with
        # wild_required=False).
        self.line_3_same_by_symbol: dict[str, list[Line3SameRule]] = {}
        self.line_3_group: list[Line3GroupRule] = []
        self.pure_wild: list[PureWildRule] = []
        self.pure_wild_group: list[PureWildGroupRule] = []
        self.scatter_triggers: list[ScatterTriggerRule] = []
        # machine+ booster-tier storage
        self.pure_wild_with_booster_by_symbol: dict[str, PureWildWithBoosterRule] = {}
        self.center_booster_alone_by_symbol: dict[str, CenterBoosterAloneRule] = {}
        self.side_wild_alone: SideWildAloneRule | None = None
        # Machine-specific reroll rules (2026-04-24)
        self.reroll_blocks: list[RerollBlockRule] = []
        for rb in (reroll_blocks or []):
            self.reroll_blocks.append(RerollBlockRule(
                pattern=list(rb["pattern"]),
                reason=str(rb.get("reason", "")),
            ))

        for p in spec_pays:
            kind = p["kind"]
            pid = int(p["pay_id"])
            excluded = bool(p.get("rtp_excluded", False))

            if kind not in self._SUPPORTED_KINDS:
                raise ValueError(
                    f"pay_id {pid}: kind={kind!r} not supported in engine "
                    f"(supported: {sorted(self._SUPPORTED_KINDS)})"
                )

            if kind == "cherry_count":
                c = int(p["count"])
                self.cherry_by_count[c] = CherryCountRule(
                    pay_id=pid, count=c, multiplier=int(p["multiplier"])
                )
            elif kind == "line_3_same":
                bucket = self.line_3_same_by_symbol.setdefault(p["symbol"], [])
                bucket.append(Line3SameRule(
                    pay_id=pid,
                    symbol=p["symbol"],
                    multiplier=float(p["multiplier"]),
                    wild_required=p.get("wild_required"),
                ))
            elif kind == "line_3_group":
                self.line_3_group.append(Line3GroupRule(
                    pay_id=pid,
                    group=frozenset(p["group"]),
                    multiplier=float(p["multiplier"]),
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
            elif kind == "scatter_trigger":
                self.scatter_triggers.append(ScatterTriggerRule(
                    pay_id=pid,
                    symbol=p["symbol"],
                    reel=int(p["reel"]),
                    multiplier=int(p.get("multiplier", 0)),
                ))
            elif kind == "pure_wild_with_booster":
                self.pure_wild_with_booster_by_symbol[p["booster_symbol"]] = (
                    PureWildWithBoosterRule(
                        pay_id=pid,
                        booster_symbol=p["booster_symbol"],
                        multiplier=int(p["multiplier"]),
                    )
                )
            elif kind == "center_booster_alone":
                self.center_booster_alone_by_symbol[p["booster_symbol"]] = (
                    CenterBoosterAloneRule(
                        pay_id=pid,
                        booster_symbol=p["booster_symbol"],
                        multiplier=int(p["multiplier"]),
                    )
                )
            elif kind == "side_wild_alone":
                # Only one such rule per machine (machine's pay_id 9 = wild alone 1×).
                # Additional declarations overwrite (spec bug if duplicated).
                self.side_wild_alone = SideWildAloneRule(
                    pay_id=pid,
                    multiplier=int(p["multiplier"]),
                )
            elif kind == "plugin_handled":
                # No-op: trigger + multiplier logic lives entirely in the
                # machine's FeaturePlugin post-evaluator (ARCHITECTURE §3).
                # This branch exists to prevent ValueError at load time for
                # machines that declare plugin-owned pay_ids in spec.json.
                # Core evaluator never fires for this kind. No rule object
                # stored. RTP tracking reads from emitted round data, not
                # from spec entries.
                pass
