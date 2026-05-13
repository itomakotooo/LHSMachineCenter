"""Compute shipped v9 m2 / m5 marginals so we can document the reference lucky
carve-out direction (R1 blank >= R3 blank — R3 trigger-reel busy).

Reads weights/mode_2/weights.json and weights/mode_5/weights.json + reel_strips.json.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_M15 = _ROOT / "slot_designer" / "machines" / "M15"
STRIPS = json.loads((_M15 / "reel_strips.json").read_text(encoding="utf-8"))["reels"]

for mode in (1, 2, 5, 7):
    w = json.loads((_M15 / "weights" / f"mode_{mode}" / "weights.json").read_text(encoding="utf-8"))["weights"]
    print(f"\n=== Mode {mode} marginals ===")
    for r_idx, (reel, weights) in enumerate(zip(STRIPS, w)):
        total = sum(weights)
        by_sym = defaultdict(float)
        for sym, wt in zip(reel, weights):
            by_sym[sym] += wt
        margs = {s: round(v / total * 100, 3) for s, v in by_sym.items()}
        print(f"  R{r_idx+1}: " + ", ".join(f"{s}={m:.2f}%" for s, m in sorted(margs.items())))
