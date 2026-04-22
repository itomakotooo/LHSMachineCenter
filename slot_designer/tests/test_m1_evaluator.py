"""Unit tests for the M1 evaluator.

Covers every distinct (payline, pay_id, multiplier) combination observed
in rawdata/M1/mode_1/ (see slot_designer/tests/fixtures/M1_field_analysis.md).
Runnable standalone (``python slot_designer/tests/test_m1_evaluator.py``)
or via pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.engine.loader import load_engine

_SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "reel_weights.json"

_engine, _ = load_engine(_SPEC, _WEIGHTS)
EV = _engine.evaluator


def _eval(*payline_syms):
    return EV.evaluate_payline(list(payline_syms))


def _assert_pay(payline_syms, expected_pid, expected_mult):
    r = _eval(*payline_syms)
    assert r is not None, f"{payline_syms}: expected pay_id {expected_pid}, got None"
    assert r.pay_id == expected_pid, f"{payline_syms}: expected pay_id {expected_pid}, got {r.pay_id}"
    assert r.multiplier == expected_mult, (
        f"{payline_syms}: expected multiplier {expected_mult}, got {r.multiplier}"
    )


# ------------------------------------------------------------------ Cherry
def test_1_cherry_blank_blank():
    _assert_pay(["Blank", "Cherry", "Blank"], 14, 1)


def test_1_cherry_with_bars():
    # (Bar1, Blank, Cherry) — most common pay_id 14 pattern in M1 rawdata
    _assert_pay(["Bar1", "Blank", "Cherry"], 14, 1)


def test_2_cherry():
    _assert_pay(["Cherry", "Blank", "Cherry"], 13, 2)


def test_2_cherry_with_bar():
    _assert_pay(["Bar1", "Cherry", "Cherry"], 13, 2)


def test_3_cherry():
    _assert_pay(["Cherry", "Cherry", "Cherry"], 12, 10)


def test_cherry_blocks_wild_pure_pay():
    """(Cherry, D1, D1) must be 1-Cherry pay, not 2 D1 anything — the
    cherry precedence rule that distinguishes M1 from most slots."""
    _assert_pay(["Cherry", "Diamond1", "Diamond1"], 14, 1)


def test_cherry_blocks_wild_substitution():
    # Would otherwise be 3 Seven1 via D1 substituting for Seven1
    _assert_pay(["Cherry", "Seven1", "Seven1"], 14, 1)


# ---------------------------------------------------------- Blanks / no pay
def test_blank_kills_non_cherry_pay():
    assert _eval("Bar1", "Blank", "Bar1") is None


def test_all_blank():
    assert _eval("Blank", "Blank", "Blank") is None


def test_mixed_groups_no_pay():
    assert _eval("Bar1", "Seven1", "Seven1") is None


def test_mixed_groups_with_wild_still_no_pay():
    # 1 Bar + 1 Seven + 1 Wild — no group contains both Bar and Seven
    assert _eval("Bar1", "Seven1", "Diamond1") is None


# --------------------------------------------------- 3-of-a-kind (clean)
def test_3_bar1_clean():
    _assert_pay(["Bar1", "Bar1", "Bar1"], 9, 10)


def test_3_bar2_clean():
    _assert_pay(["Bar2", "Bar2", "Bar2"], 8, 15)


def test_3_bar3_clean():
    _assert_pay(["Bar3", "Bar3", "Bar3"], 7, 20)


def test_3_seven1_clean():
    _assert_pay(["Seven1", "Seven1", "Seven1"], 6, 40)


def test_3_seven2_clean():
    _assert_pay(["Seven2", "Seven2", "Seven2"], 5, 50)


# -------------------------------- 3-of-a-kind with wild substitution + mult
def test_bar1_bar1_wild2x():
    # base 10 × wild2x = 20, observed pattern in rawdata
    _assert_pay(["Bar1", "Bar1", "Diamond1"], 9, 20)


def test_bar1_bar1_wild3x():
    _assert_pay(["Bar1", "Bar1", "Diamond2"], 9, 30)


def test_bar1_wild2x_wild3x():
    # 10 × 2 × 3 = 60
    _assert_pay(["Bar1", "Diamond1", "Diamond2"], 9, 60)


def test_bar1_wild2x_wild2x():
    # 10 × 2 × 2 = 40
    _assert_pay(["Bar1", "Diamond1", "Diamond1"], 9, 40)


def test_bar1_wild3x_wild3x():
    # 10 × 3 × 3 = 90
    _assert_pay(["Bar1", "Diamond2", "Diamond2"], 9, 90)


def test_seven1_wild2x_wild3x():
    # base 40 × 2 × 3 = 240
    _assert_pay(["Seven1", "Diamond1", "Diamond2"], 6, 240)


def test_bar3_wild3x_single():
    # observed: (Bar3, Bar3, Diamond2) → pay_id 7, 60x
    _assert_pay(["Bar3", "Bar3", "Diamond2"], 7, 60)


# ----------------------------------------------------------------- Mixed
def test_mixed_bars_clean():
    _assert_pay(["Bar1", "Bar2", "Bar3"], 11, 5)


def test_mixed_bars_repeat_clean():
    _assert_pay(["Bar1", "Bar1", "Bar2"], 11, 5)


def test_mixed_sevens_clean():
    _assert_pay(["Seven1", "Seven1", "Seven2"], 10, 25)


def test_mixed_bars_with_wild2x():
    # non-wilds = {Bar1, Bar2}, not all-same → line_3_group × wild2x = 5 × 2 = 10
    _assert_pay(["Bar1", "Bar2", "Diamond1"], 11, 10)


def test_mixed_bars_with_wild3x():
    _assert_pay(["Bar1", "Bar2", "Diamond2"], 11, 15)


def test_mixed_sevens_with_wild2x():
    # observed: (Seven1, Seven2, Diamond1) → pay_id 10, 50x
    _assert_pay(["Seven1", "Seven2", "Diamond1"], 10, 50)


def test_mixed_sevens_with_wild3x():
    # (Seven1, Seven2, Diamond2) — 25 × 3 = 75
    _assert_pay(["Seven1", "Seven2", "Diamond2"], 10, 75)


def test_prefer_3_same_over_group():
    # (Bar1, Bar1, Diamond1) could be 3-Bar1×2 (pay_id 9, 20x) or mixed bars×2
    # (pay_id 11, 10x). Engine must pick 3-Bar1 (max multiplier).
    r = _eval("Bar1", "Bar1", "Diamond1")
    assert r.pay_id == 9 and r.multiplier == 20


# -------------------------------------------------------------- Pure wild
def test_pure_wild_3_d1():
    _assert_pay(["Diamond1", "Diamond1", "Diamond1"], 2, 500)


def test_pure_wild_2d1_1d2():
    _assert_pay(["Diamond1", "Diamond1", "Diamond2"], 3, 240)


def test_pure_wild_1d1_2d2():
    _assert_pay(["Diamond1", "Diamond2", "Diamond2"], 3, 360)


def test_grand_jackpot_is_blocked():
    """3× Diamond2 matches pay_id 4 (grand jackpot) but ``rtp_excluded=true``
    means the engine suppresses it — no pay emitted, rawdata shows losing
    spin despite the all-Diamond2 payline."""
    r = _eval("Diamond2", "Diamond2", "Diamond2")
    assert r is None


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
    passed = 0
    failed: list[tuple[str, BaseException]] = []
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            failed.append((t.__name__, e))

    print(f"{passed}/{len(tests)} tests passed")
    for name, err in failed:
        print(f"  FAIL {name}: {err}")
    sys.exit(0 if not failed else 1)
