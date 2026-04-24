"""Regression: M37 payline evaluator correctness.

M37 introduces booster-tier symbols (mini/minor/major/grand on middle
reel) with multi-way pay logic. This test locks in every pay_id / mult
combination against the reverse-engineered paytable from
``tests/fixtures/M37_field_analysis.md``.

Cases cover:
  - Regular 3-match (pay_id 1-5) with wild substitution
  - line_3_group (pay_id 6 high7+7bar mix, pay_id 7 mixed bars)
  - Booster center + 3-match anchor (pay_id 1-7 × booster_mult)
  - Pure wild + booster (pay_id 102/103/104 separate from pay_id 1)
  - Booster alone (pay_id 8 for grand, pay_id 9 for mini/minor/major)
  - Side wild alone (pay_id 9 flat × 1)
  - No-pay (blank payline, partial combos)
  - Re-roll: (wild, grand, wild) blocked at spin level

If the evaluator regresses, these 35+ cases fail with a clear message
pinning the expected pay_id × multiplier.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.engine.evaluator import PaytableEvaluator
from slot_designer.engine.rules import RuleSet
from slot_designer.engine.symbol import SymbolRegistry
from slot_designer.engine.spin import _matches_any_reroll


_SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M37.spec.json"


def _build_evaluator() -> PaytableEvaluator:
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    symbols = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"], reroll_blocks=spec.get("reroll_blocks"))
    return PaytableEvaluator(symbols, rules, spec["evaluation_order"])


# (payline_middle_row, expected_pay_id, expected_multiplier)
# None means "no pay". Payline is middle row of col 0, col 1, col 2.
_CASES = [
    # === A. Regular 3-match with wild substitution ===
    (["high7", "high7", "high7"], 1, 10),
    (["wild", "high7", "high7"], 1, 10),
    (["high7", "high7", "wild"], 1, 10),
    (["wild", "high7", "wild"], 1, 10),
    (["7bar", "7bar", "7bar"], 2, 6),
    (["3bar", "3bar", "3bar"], 3, 5),
    (["2bar", "2bar", "2bar"], 4, 4),
    (["1bar", "1bar", "1bar"], 5, 3),

    # === line_3_group ===
    (["high7", "7bar", "high7"], 6, 2),
    (["7bar", "high7", "7bar"], 6, 2),
    (["1bar", "2bar", "3bar"], 7, 1),
    (["3bar", "1bar", "7bar"], 7, 1),

    # === B. Booster center + 3-match anchor (pay_id × booster_mult) ===
    (["high7", "mini", "high7"], 1, 20),      # 10 × 2
    (["high7", "minor", "high7"], 1, 50),     # 10 × 5
    (["high7", "major", "high7"], 1, 100),    # 10 × 10
    (["high7", "grand", "high7"], 1, 1000),   # 10 × 100 — TOP pay
    (["wild", "minor", "high7"], 1, 50),      # wild sub + minor
    (["7bar", "grand", "7bar"], 2, 600),      # 6 × 100
    (["3bar", "mini", "3bar"], 3, 10),        # 5 × 2
    (["1bar", "major", "3bar"], 7, 10),       # mixed bars + major

    # === C. Pure wild + booster (separate pay_id 102/103/104) ===
    (["wild", "mini", "wild"], 104, 20),      # = high7 × mini
    (["wild", "minor", "wild"], 103, 50),     # = high7 × minor
    (["wild", "major", "wild"], 102, 100),    # = high7 × major
    # (wild, grand, wild) blocked by re-roll — tested separately below

    # === D. Booster alone (no side 3-match) ===
    (["blank", "mini", "blank"], 9, 2),
    (["blank", "minor", "blank"], 9, 5),
    (["blank", "major", "blank"], 9, 10),
    (["blank", "grand", "blank"], 8, 100),    # grand has own pay_id 8
    (["blank", "minor", "7bar"], 9, 5),       # only 1 non-wild side → no match → alone
    (["3bar", "minor", "1bar"], 7, 5),        # mixed bars + minor → pay_id 7 × 5

    # === E. Side wild alone (col 1 non-booster non-target) ===
    (["wild", "blank", "blank"], 9, 1),
    (["blank", "blank", "wild"], 9, 1),
    (["wild", "blank", "wild"], 9, 1),        # 2 wilds still flat 1×

    # === No pay ===
    (["blank", "blank", "blank"], None, None),
    (["blank", "2bar", "blank"], None, None),
    (["3bar", "blank", "high7"], None, None), # no 3-match, no wild, no booster
]


def test_m37_evaluator_matches_reverse_engineered_paytable():
    """Every case in _CASES must produce the expected (pay_id, mult)."""
    ev = _build_evaluator()
    failures = []
    for payline, exp_pid, exp_mult in _CASES:
        result = ev.evaluate_payline(payline)
        if exp_pid is None:
            if result is not None:
                failures.append(
                    f"{payline} expected None but got pay_id={result.pay_id} mult={result.multiplier}"
                )
            continue
        if result is None:
            failures.append(
                f"{payline} expected pay_id={exp_pid} mult={exp_mult} but got None"
            )
            continue
        if result.pay_id != exp_pid or result.multiplier != exp_mult:
            failures.append(
                f"{payline} expected pay_id={exp_pid} mult={exp_mult} but got "
                f"pay_id={result.pay_id} mult={result.multiplier}"
            )
    assert not failures, "\n".join(failures)


def test_m37_reroll_blocks_wild_grand_wild():
    """(wild, grand, wild) must be in spec's reroll_blocks; engine
    re-rolls at spin time (verified via the _matches_any_reroll helper).
    """
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    rules = RuleSet(spec["pays"], reroll_blocks=spec.get("reroll_blocks"))

    # The forbidden pattern exists in spec
    assert rules.reroll_blocks, "spec must declare reroll_blocks"
    patterns = [tuple(r.pattern) for r in rules.reroll_blocks]
    assert ("wild", "grand", "wild") in patterns, (
        f"expected (wild, grand, wild) in reroll_blocks; got {patterns}"
    )

    # The helper matches this pattern
    assert _matches_any_reroll(["wild", "grand", "wild"], rules.reroll_blocks), (
        "spin.py _matches_any_reroll must trigger on (wild, grand, wild)"
    )
    # Other patterns (including similar but non-matching) do NOT match
    assert not _matches_any_reroll(["wild", "major", "wild"], rules.reroll_blocks)
    assert not _matches_any_reroll(["high7", "grand", "high7"], rules.reroll_blocks)
    assert not _matches_any_reroll(["wild", "grand", "blank"], rules.reroll_blocks)


def test_m37_max_payout_is_1000x_via_high7_grand():
    """The TOP bucket tier is 1000× via pay_id 1 × grand booster.
    Only reachable through ``(high7|wild, grand, high7|wild)`` paths —
    the pure-wild path is blocked by re-roll, per design brief.
    """
    ev = _build_evaluator()
    # All 4 ways to hit 1000× (high7 and wild interchangeable on sides)
    combos = [
        ["high7", "grand", "high7"],
        ["wild", "grand", "high7"],
        ["high7", "grand", "wild"],
        # ["wild", "grand", "wild"] is blocked — engine would re-roll; evaluator-level
        # would compute pay_id 8 (grand alone = 100×) if it somehow ran
    ]
    for payline in combos:
        result = ev.evaluate_payline(payline)
        assert result is not None, f"{payline} should pay"
        assert result.pay_id == 1, f"{payline} pay_id expected 1 got {result.pay_id}"
        assert result.multiplier == 1000, (
            f"{payline} multiplier expected 1000 got {result.multiplier}"
        )


def test_m37_boosters_only_on_reel_2_semantic():
    """Paytable doesn't declare pays that fire when booster is on col 0
    or col 2 (would be illegal per the strip layout — boosters only on
    reel 2). The evaluator's booster-center check is explicitly keyed
    to col 1; booster on col 0/2 falls through.
    """
    ev = _build_evaluator()
    # Booster on col 0 with high7 in middle: col 1 is high7 (regular),
    # side logic doesn't detect booster → line_3_same check with
    # non_wilds = {mini, high7}, len(set) = 2, no line_3_same match.
    # → falls through to side_wild_alone (no wild on sides) → None
    result = ev.evaluate_payline(["mini", "high7", "high7"])
    assert result is None, (
        f"mini on col 0 should not pay (boosters are reel-2-only in "
        f"M37); evaluator returned {result}"
    )


if __name__ == "__main__":
    test_m37_evaluator_matches_reverse_engineered_paytable()
    print("ok  paytable")
    test_m37_reroll_blocks_wild_grand_wild()
    print("ok  reroll")
    test_m37_max_payout_is_1000x_via_high7_grand()
    print("ok  max payout")
    test_m37_boosters_only_on_reel_2_semantic()
    print("ok  booster position")
    print("4/4 passed")
