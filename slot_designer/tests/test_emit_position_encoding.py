"""Regression: emit round position encoding matches upstream formula.

The upstream / real-analyzer / infer_paytable stack all encode payline
positions as ``pos = (col+1)*100 + (row-1)`` with col & row 0-indexed
where row=1 is the middle (payline) row. We had an off-by-one bug
(2026-04-21) that emitted ``(col+1)*100 + row`` instead, which caused
infer_paytable to read the TOP row (index 0 of StopSymbolsByCol split)
instead of the middle (index 1) — wild inference + symbol_set tagging
all went wrong for virtual machines.

This test locks the encoding: middle-row cells on a 3-col slot map to
positions 100/200/300 (not 101/201/301).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.emitter.round import emit_round
from slot_designer.core.engine.spin import SpinOutcome
from slot_designer.core.engine.rules import PayResult


def _make_outcome(payline_syms, pay_result):
    """Fake a 3x3 outcome where mid row = payline_syms, top/bot = Blank."""
    grid = [["Blank", sym, "Blank"] for sym in payline_syms]
    return SpinOutcome(
        grid=grid,
        pay=pay_result,
        cost_credits=1000,
        bet_amount=1000,
        spin_type=1,
    )


def test_middle_row_encoded_as_100s():
    """Pay at (col=0, row=1), (col=1, row=1), (col=2, row=1) — all middle.
    Must encode as 100, 200, 300."""
    pay = PayResult(
        pay_id=11, multiplier=5,
        positions=((0, 1), (1, 1), (2, 1)),
    )
    out = _make_outcome(["Bar1", "Bar2", "Bar3"], pay)
    r = emit_round(out, last_credits=1_000_000, spin_times=1000, rtp_id=1)
    pbp = r["PayoutByPayline"]
    # Should be "1:11-11(100,200,300,);  " — NOT 101/201/301.
    assert "(100,200,300,)" in pbp, (
        f"middle-row positions must be 100/200/300; got PayoutByPayline={pbp!r}"
    )


def test_single_cherry_encodes_as_100():
    """(0, 1) = col 0 middle → position 100."""
    pay = PayResult(pay_id=14, multiplier=1, positions=((0, 1),))
    out = _make_outcome(["Cherry", "Blank", "Blank"], pay)
    r = emit_round(out, last_credits=1_000_000, spin_times=1000, rtp_id=1)
    assert "(100,)" in r["PayoutByPayline"], (
        f"col 0 middle should encode as 100; got {r['PayoutByPayline']!r}"
    )


def test_stop_symbols_order_top_mid_bot():
    """Verify StopSymbolsByCol dash-encodes [top, mid, bot] in that order,
    so position decoding (which indexes split('-')[row] for row 0/1/2)
    matches what we emitted.
    """
    pay = PayResult(pay_id=14, multiplier=1, positions=((0, 1),))
    # grid[0] = [top, mid, bot] = [Bar2, Cherry, Seven1]
    out = SpinOutcome(
        grid=[["Bar2", "Cherry", "Seven1"], ["Blank"] * 3, ["Blank"] * 3],
        pay=pay, cost_credits=1000, bet_amount=1000, spin_type=1,
    )
    r = emit_round(out, last_credits=1_000_000, spin_times=1000, rtp_id=1)
    assert r["StopSymbolsByCol"][0] == "Bar2-Cherry-Seven1-", (
        f"dash order must be top-mid-bot; got {r['StopSymbolsByCol'][0]!r}"
    )


def test_roundtrip_emit_then_decode_lands_on_middle():
    """End-to-end: emit a round with cherry at (col=0, row=1=middle), then
    use the decode logic from infer_paytable to recover the symbol at the
    emitted position. Must land on Cherry (the middle cell), not Blank
    (top) or Blank (bot).
    """
    from scripts.infer_paytable import _decode_position

    pay = PayResult(pay_id=14, multiplier=1, positions=((0, 1),))
    out = SpinOutcome(
        grid=[["Bar1", "Cherry", "Blank"], ["Blank"] * 3, ["Blank"] * 3],
        pay=pay, cost_credits=1000, bet_amount=1000, spin_type=1,
    )
    r = emit_round(out, last_credits=1_000_000, spin_times=1000, rtp_id=1)

    # Extract position from emitted PayoutByPayline (it's "(100,)" or whatever)
    import re
    m = re.search(r"\(([0-9,]+)\)", r["PayoutByPayline"])
    assert m, f"no position group found: {r['PayoutByPayline']!r}"
    positions = [int(p) for p in m.group(1).split(",") if p]
    assert positions == [100], f"expected [100], got {positions}"

    # Now decode and look up the symbol
    col, row = _decode_position(100)
    assert (col, row) == (0, 1), f"decode(100) should be (0, 1); got ({col}, {row})"
    # StopSymbolsByCol[0] = "Bar1-Cherry-Blank-" → split('-')[1] = "Cherry"
    sym = r["StopSymbolsByCol"][col].split("-")[row]
    assert sym == "Cherry", (
        f"symbol at decoded position should be Cherry (middle); got {sym!r}"
    )


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
    passed, failures = 0, []
    for t in tests:
        try:
            t()
            print(f"ok  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failures.append((t.__name__, e))
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if not failures else 1)
