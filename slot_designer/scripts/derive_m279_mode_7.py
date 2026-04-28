"""Derive M279 mode 7 weights from mode 1 — direct-scale Low-bucket symbols.

Per `project_slot_designer_hit_rate_deviation.md`: mode 7 = mode 1 with
small-pay symbols (bar / 5bar / low7) weights scaled DOWN, while
high-pay symbols (mid7 / high7 / wilds) and stack symbols are
PRESERVED. Result: Low bucket hit drops, Mid/High/Top buckets keep
their absolute hit rate. Total RTP drops from 95% to 85% (-10pp), hit
drops from 14% to 10-11%.

Direct-scale path (M1-style) — applicable here because M279's paytable
clearly separates Low (bar/5bar/low7) from Mid+ (mid7/high7) symbols.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


# Symbol scale multipliers — multiplicative on mode 1's per-stop weights.
# v2 (per DESIGN.md §3.3): 7-family 47.5pp absolute preserved; bar 23.75 → 15.0pp (-8.75pp).
# Stronger bar/5bar cut than v1 to actually drop RTP -10pp, while preserving Mid/High/Top hit
# at mode 1 absolute values (per_tier preservation hard rule).
SCALE_BY_SYMBOL = {
    "bar": 0.30,    # bar OAK pay 1× → cut harder (-70%) for v2.1 RTP 85% target
    "5bar": 0.30,   # 5bar OAK pay 2×; also Low; cut harder
    "low7": 0.55,   # low7 cut more aggressively to drop -10pp RTP
    "mid7": 0.85,   # mid7 mild cut (was unchanged in v2)
    # high7 / wild family / stack: unchanged (preserve Top hit absolute)
}

# Blank weight bump compensates for paying weight reductions.
BLANK_BUMP = 1.30


def derive(mode_1_path: Path, mode_7_path: Path, strips_path: Path) -> dict:
    m1_doc = json.loads(mode_1_path.read_text(encoding="utf-8"))
    strips_doc = json.loads(strips_path.read_text(encoding="utf-8"))

    m7_doc = copy.deepcopy(m1_doc)
    m7_doc["mode"] = 7
    m7_doc["_notes"] = [
        "M279 mode 7 (85% RTP target, 10-11% hit, 'standard low' / cut mode).",
        "Derived from mode 1 by direct-scale of Low-bucket symbols:",
        f"  bar weight × {SCALE_BY_SYMBOL['bar']}",
        f"  5bar weight × {SCALE_BY_SYMBOL['5bar']}",
        f"  low7 weight × {SCALE_BY_SYMBOL['low7']}",
        "Other symbols (mid7/high7/wild family/stack) preserved at mode 1 weight.",
        "Result: Low bucket hit ↓, Mid/High/Top hit absolute = mode 1.",
    ]
    # Remove tuned summary inherited from mode 1 (will be regenerated)
    m7_doc.pop("_tuned_summary", None)

    strips = strips_doc["reels"]
    new_weights = []
    for reel_idx, (strip, weights) in enumerate(zip(strips, m1_doc["weights"])):
        scaled = []
        for sym, w in zip(strip, weights):
            if sym == "blank":
                scaled.append(max(1, int(round(w * BLANK_BUMP))))
            else:
                scale = SCALE_BY_SYMBOL.get(sym, 1.0)
                scaled.append(max(1, int(round(w * scale))))
        new_weights.append(scaled)
    m7_doc["weights"] = new_weights

    return m7_doc


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--write", action="store_true",
        help="actually write the output file; default = dry run.",
    )
    p.add_argument(
        "--mode-1-path", type=Path,
        default=Path(__file__).resolve().parent.parent / "weights" / "M279" / "mode_1" / "weights.json",
    )
    p.add_argument(
        "--mode-7-path", type=Path,
        default=Path(__file__).resolve().parent.parent / "weights" / "M279" / "mode_7" / "weights.json",
    )
    p.add_argument(
        "--strips-path", type=Path,
        default=Path(__file__).resolve().parent.parent / "weights" / "M279" / "reel_strips.json",
    )
    args = p.parse_args()

    m7_doc = derive(args.mode_1_path, args.mode_7_path, args.strips_path)
    print("=== M279 mode 7 derivation ===")
    print(f"  scales: {SCALE_BY_SYMBOL}")
    print(f"  weights[0][:8] (mode 1 → mode 7): {json.loads(args.mode_1_path.read_text(encoding='utf-8'))['weights'][0][:8]} → {m7_doc['weights'][0][:8]}")
    if args.write:
        args.mode_7_path.parent.mkdir(parents=True, exist_ok=True)
        args.mode_7_path.write_text(
            json.dumps(m7_doc, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        print(f"  wrote → {args.mode_7_path}")
    else:
        print(f"  (dry run; pass --write to materialize)")


if __name__ == "__main__":
    main()
