"""Break pid 9 into sub-tiers (mini-alone 2x, minor-alone 5x, major-alone 10x, side-wild-alone 1x)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import compute_reel_marginal
from slot_designer.core.engine.loader import load_engine

MACHINE_DIR = _ROOT / "slot_designer" / "machines" / "M37"
SPEC = MACHINE_DIR / "spec.json"
STRIPS = MACHINE_DIR / "reel_strips.json"
M1_WEIGHTS = MACHINE_DIR / "weights" / "mode_1" / "weights.json"

with STRIPS.open("r", encoding="utf-8") as f:
    _strip_data = json.load(f)
REELS = _strip_data["reels"]
SYM_POS: dict[tuple[int, str], list[int]] = {}
for ri, reel in enumerate(REELS):
    for pi, sym in enumerate(reel):
        SYM_POS.setdefault((ri, sym), []).append(pi)


def load_weights(path):
    with open(path, "r", encoding="utf-8") as f:
        return [list(row) for row in json.load(f)["weights"]]


def pid9_decompose(weights):
    """Compute analytic per-pid9-subtier RTP contribution.

    pid 9 fires in these cases:
      - side_wild_alone: R1 or R3 has wild but no 3-match — flat 1×. Includes:
        * (wild, X, Y) where (wild, X, Y) doesn't form 3-match (with X non-wild, non-mid-wild)
        * (X, Y, wild) where (X, Y, wild) doesn't form 3-match
        * (wild, X, wild) where (wild, X, wild) doesn't form 3-match: wait — pure_wild_with_booster fires for X in {major,minor,mini} (pid 102/103/104). For X in {non-wild non-booster} → 3-of-X via substitution. Actually if X=non-wild ≠ booster: high7/bar/etc, then it forms 3-of-X.
        Actually: (wild, blank, wild) → no 3-match → side_wild_alone, multiplier = 1×1 = ... well "side-wild-alone" = flat 1×.
      - center_booster_alone (with mini/minor/major) → 2× / 5× / 10×
      - center_booster_alone (with grand) → pid 8, NOT pid 9 (separate pay_id)
    """
    margs = []
    for ri, reel_w in enumerate(weights):
        totals = {}
        total = sum(reel_w)
        for pi, w in enumerate(reel_w):
            sym = REELS[ri][pi]
            totals[sym] = totals.get(sym, 0.0) + w
        margs.append({s: w / total for s, w in totals.items()})

    # Enumerate combos (R1, R2, R3) with non-zero marginal each.
    pid9_subtier = {"mini_alone_2x": 0.0, "minor_alone_5x": 0.0, "major_alone_10x": 0.0, "side_wild_alone_1x": 0.0}
    pid8_grand_alone = 0.0
    blocked_p = 0.0
    for r1, p1 in margs[0].items():
        for r2, p2 in margs[1].items():
            for r3, p3 in margs[2].items():
                prob = p1 * p2 * p3
                if prob == 0:
                    continue
                # Block (wild, grand, wild)
                if r1 == "wild" and r2 == "grand" and r3 == "wild":
                    blocked_p += prob
                    continue
                # Determine pay path.
                # pure_wild_with_booster: (wild, mini/minor/major, wild) -> pid 102/103/104
                if r1 == "wild" and r3 == "wild" and r2 in ("mini", "minor", "major"):
                    # those are pid 102 (major)/103(minor)/104(mini), not pid 9
                    continue
                # 3-match line_3_same: all 3 are same non-blank or wild-substitutable.
                # For substitution, a "wild" (R1/R3) or "mini/minor/major/grand" (R2) substitutes for any non-blank.
                # 3-of-X if: each reel is X or wild-substitute.
                # For each candidate target symbol X:
                regular_targets = ["high7", "7bar", "3bar", "2bar", "1bar"]
                three_match = False
                for tgt in regular_targets:
                    def matches(reel_idx, sym):
                        if sym == tgt:
                            return True
                        if reel_idx in (0, 2) and sym == "wild":
                            return True
                        if reel_idx == 1 and sym in ("mini", "minor", "major", "grand"):
                            return True
                        return False
                    if matches(0, r1) and matches(1, r2) and matches(2, r3):
                        three_match = True
                        break
                if three_match:
                    continue
                # line_3_group: any-7 (high7+7bar) or any-bar (1/2/3/7bar) -- substitute counts.
                seven_group = ("high7", "7bar")
                bar_group = ("1bar", "2bar", "3bar", "7bar")
                def in_group(reel_idx, sym, group):
                    if sym in group:
                        return True
                    if reel_idx in (0, 2) and sym == "wild":
                        return True
                    if reel_idx == 1 and sym in ("mini", "minor", "major", "grand"):
                        return True
                    return False
                if in_group(0, r1, seven_group) and in_group(1, r2, seven_group) and in_group(2, r3, seven_group):
                    continue
                if in_group(0, r1, bar_group) and in_group(1, r2, bar_group) and in_group(2, r3, bar_group):
                    continue
                # No 3-match. Now check center_booster_alone vs side_wild_alone.
                # Per spec: evaluation_order = [pure_wild_with_booster, line_3_same, line_3_group, center_booster_alone, side_wild_alone]
                # We've cleared all 3-match. center_booster_alone fires if R2 is mini/minor/major/grand.
                if r2 == "grand":
                    # pid 8 = grand alone
                    pid8_grand_alone += prob
                    continue
                if r2 == "mini":
                    pid9_subtier["mini_alone_2x"] += prob
                    continue
                if r2 == "minor":
                    pid9_subtier["minor_alone_5x"] += prob
                    continue
                if r2 == "major":
                    pid9_subtier["major_alone_10x"] += prob
                    continue
                # Otherwise: side_wild_alone if R1 or R3 is wild.
                if r1 == "wild" or r3 == "wild":
                    pid9_subtier["side_wild_alone_1x"] += prob
                    continue
                # else: 0 win, no pay.

    # Apply reroll renormalization
    renorm = 1.0 / (1.0 - blocked_p) if blocked_p > 0 else 1.0
    for k in pid9_subtier:
        pid9_subtier[k] *= renorm
    pid8_grand_alone *= renorm

    # RTP contributions:
    rtp_contrib = {
        "mini_alone_2x": pid9_subtier["mini_alone_2x"] * 2,
        "minor_alone_5x": pid9_subtier["minor_alone_5x"] * 5,
        "major_alone_10x": pid9_subtier["major_alone_10x"] * 10,
        "side_wild_alone_1x": pid9_subtier["side_wild_alone_1x"] * 1,
    }
    return {
        "freq": pid9_subtier,
        "rtp_pp": {k: v * 100 for k, v in rtp_contrib.items()},
        "pid8_grand_alone_freq": pid8_grand_alone,
        "pid8_grand_alone_rtp_pp": pid8_grand_alone * 100 * 100,  # 100x payout
    }


def main():
    m1 = load_weights(M1_WEIGHTS)
    decomp = pid9_decompose(m1)
    print("M1 v5 baseline — pid 9 subtier breakdown:\n")
    print(f"{'subtier':<25} {'freq':>12} {'rtp_pp':>10} {'%total_rtp':>12}")
    total_rtp_pp = sum(decomp["rtp_pp"].values())
    for k, v in decomp["rtp_pp"].items():
        share = v / 94.092 * 100
        print(f"{k:<25} {decomp['freq'][k]:>12.6f} {v:>10.3f} {share:>11.2f}%")
    print(f"\npid 9 total RTP pp: {total_rtp_pp:.3f}")
    print(f"pid 8 (grand alone) freq: {decomp['pid8_grand_alone_freq']:.6f}, rtp pp: {decomp['pid8_grand_alone_rtp_pp']:.3f}")


if __name__ == "__main__":
    main()
