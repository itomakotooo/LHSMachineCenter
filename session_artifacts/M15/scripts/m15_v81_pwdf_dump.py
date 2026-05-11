"""M15 v8.1 — PWDF / window visibility dump per mode per reel per top symbol.

Computes p_mid, p_window, and pwdf_ratio for each top symbol on each reel
for each mode. Used pre/post Mechanism B for the visibility audit.

Top symbols for M15 (per archetype + philosophy §15 definitions):
  - doublediamond (wild, 200x)
  - high7 (30x)
  - topdollar (trigger, R3 only)

Mid-pay (for side-effect tracking):
  - 3bar (20x), 2bar (10x), 1bar (5x), cherry (1x/5x/15x), jackpot (filler)

Usage:
  python session_artifacts/M15/scripts/m15_v81_pwdf_dump.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.engine.loader import load_engine
from slot_designer.core.devtools.player_experience import (
    symbol_mid_probability,
    symbol_window_probability,
    pwdf_ratio,
)


_M15 = _ROOT / "slot_designer" / "machines" / "M15"
_MODES = (1, 2, 5, 7)

TOP_SYMBOLS = ("doublediamond", "high7", "topdollar")
MID_SYMBOLS = ("3bar", "2bar", "1bar", "cherry", "jackpot")


def reel_to_strip_dicts(reel) -> list[dict]:
    """Convert engine ReelStrip → list[dict] for player_experience helpers."""
    return [{"symbol": s.symbol, "weight": int(s.weight)} for s in reel.stops]


def main() -> int:
    print("=" * 78)
    print("M15 v8.1 PWDF / window visibility per top symbol per reel per mode")
    print("=" * 78)
    print()

    for mode in _MODES:
        wpath = _M15 / "weights" / f"mode_{mode}" / "weights.json"
        eng, _ = load_engine(_M15 / "spec.json", wpath, strips_path=_M15 / "reel_strips.json")
        print(f"--- mode {mode} ---")
        # Top symbols
        for sym in TOP_SYMBOLS:
            print(f"  {sym}:")
            best_window = 0.0
            for r_idx, reel in enumerate(eng.reels):
                strip = reel_to_strip_dicts(reel)
                pm = symbol_mid_probability(strip, sym)
                pw = symbol_window_probability(strip, sym)
                pwdf = pwdf_ratio(strip, sym)
                if pw > best_window:
                    best_window = pw
                print(f"    R{r_idx+1}: p_mid={pm*100:.3f}%  p_window={pw*100:.3f}%  PWDF={pwdf:.2f}")
            print(f"    any-reel max p_window = {best_window*100:.3f}%")
        # Mid-pay symbols (side-effect tracking)
        print(f"  --- mid-pay (side-effect window visibility) ---")
        for sym in MID_SYMBOLS:
            wins = []
            for r_idx, reel in enumerate(eng.reels):
                strip = reel_to_strip_dicts(reel)
                pw = symbol_window_probability(strip, sym)
                wins.append((r_idx + 1, pw))
            best = max(wins, key=lambda x: x[1])
            r_idx_max, pw_max = best
            row = "  ".join(f"R{r}={pw*100:.2f}%" for r, pw in wins)
            print(f"    {sym:14s} {row}  max={pw_max*100:.2f}% (R{r_idx_max})")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
