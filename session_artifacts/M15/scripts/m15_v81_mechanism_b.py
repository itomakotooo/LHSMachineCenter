"""M15 v8.1 Phase C — mechanism B: RTP-neutral Blank weight redistribution.

Per philosophy §15.4 / §15.5: shift weight from non-top-adj Blanks to
top-adj Blanks (top = doublediamond / high7 / topdollar). Total Blank
weight per reel UNCHANGED → Blank marginal UNCHANGED → all family marginals
UNCHANGED → RTP / hit / share UNCHANGED.

Visibility lift mechanism: a top symbol at position p is "visible" in the
3-row window whenever the reel stops at p-1, p, or p+1. Stops p-1 and p+1
are Blanks (strict alternation per §13). Heavier weight on those Blanks
=> reel often stops there => window includes the top symbol => lift in
p_window.

Mid-pay side effect (per §15.9 backport): Blanks NOT adjacent to top
symbols (i.e. adjacent only to mid-pay symbols cherry/bar*/jackpot) get
floored to weight 1. Mid-pay window visibility DROPS as a consequence —
user explicitly said in v8.1 brief "不算副作用,甚至是需求" (welcomed).

Usage:
  python session_artifacts/M15/scripts/m15_v81_mechanism_b.py [--write] [--verify] [--floor 1]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_M15 = _ROOT / "slot_designer" / "machines" / "M15"
_MODES = (1, 2, 5, 7)

TOP_SYMBOLS = ("doublediamond", "high7", "topdollar")


def classify_blank_positions(strip: list[str]) -> tuple[list[int], list[int]]:
    """Return (top_adj, non_top_adj) lists of Blank stop indices."""
    n = len(strip)
    top_adj, non_top_adj = [], []
    for p in range(n):
        if strip[p] != "blank":
            continue
        prev = strip[(p - 1) % n]
        nxt = strip[(p + 1) % n]
        if prev in TOP_SYMBOLS or nxt in TOP_SYMBOLS:
            top_adj.append(p)
        else:
            non_top_adj.append(p)
    return top_adj, non_top_adj


def redistribute_one_reel(weights: list[int], strip: list[str],
                          non_top_adj_floor: int = 1) -> list[int]:
    """Redistribute Blank weight on this reel: non-top-adj → floor, top-adj absorbs.

    Total Blank weight preserved exactly (rounding distributed to first few top-adj).
    """
    top_adj, non_top_adj = classify_blank_positions(strip)
    if not top_adj or not non_top_adj:
        return list(weights)  # nothing to redistribute

    total_blank = sum(weights[p] for p in top_adj + non_top_adj)
    n_top = len(top_adj)
    n_non = len(non_top_adj)
    budget_for_top = total_blank - n_non * non_top_adj_floor
    if budget_for_top <= n_top:
        return list(weights)  # floor too aggressive

    new_w = list(weights)
    base = budget_for_top // n_top
    leftover = budget_for_top - base * n_top
    for i, p in enumerate(top_adj):
        new_w[p] = base + (1 if i < leftover else 0)
    for p in non_top_adj:
        new_w[p] = non_top_adj_floor
    return new_w


def run(write: bool, verify: bool, floor: int) -> int:
    print("=" * 78)
    print(f"M15 v8.1 Phase C — Mechanism B Blank redistribute (floor={floor})")
    print("=" * 78)
    print()

    strips_doc = json.loads((_M15 / "reel_strips.json").read_text(encoding="utf-8"))
    strips = strips_doc["reels"]

    for mode in _MODES:
        wpath = _M15 / "weights" / f"mode_{mode}" / "weights.json"
        wdoc = json.loads(wpath.read_text(encoding="utf-8"))
        old_weights = wdoc["weights"]
        new_weights = []

        print(f"--- mode {mode} ---")
        for r_idx in range(len(strips)):
            top_adj, non_top_adj = classify_blank_positions(strips[r_idx])
            old_blank_top = [old_weights[r_idx][p] for p in top_adj]
            old_blank_non = [old_weights[r_idx][p] for p in non_top_adj]
            old_total_b = sum(old_blank_top) + sum(old_blank_non)

            new_w = redistribute_one_reel(old_weights[r_idx], strips[r_idx], floor)
            new_blank_top = [new_w[p] for p in top_adj]
            new_blank_non = [new_w[p] for p in non_top_adj]
            new_total_b = sum(new_blank_top) + sum(new_blank_non)
            new_weights.append(new_w)

            print(f"  R{r_idx+1}: n_top_adj={len(top_adj)}  n_non={len(non_top_adj)}")
            print(f"        old top_adj weights: {old_blank_top}")
            print(f"        new top_adj weights: {new_blank_top}")
            print(f"        old non-top weights: {old_blank_non}  (sum={sum(old_blank_non)})")
            print(f"        new non-top weights: {new_blank_non}  (sum={sum(new_blank_non)})")
            print(f"        total Blank weight: {old_total_b} -> {new_total_b} "
                  f"({'EQUAL' if old_total_b == new_total_b else 'DRIFT!'})")

        if write:
            wdoc["weights"] = new_weights
            mb_meta = {
                "method": "mechanism_b_rtp_neutral_blank_redistribute",
                "non_top_adj_floor": floor,
                "top_symbols": list(TOP_SYMBOLS),
                "rationale": (
                    "Per philosophy §15.4 / §15.5: shift weight from non-top-adj "
                    "Blanks to top-adj Blanks. Total Blank weight per reel preserved "
                    "→ marginals unchanged → RTP/hit/share invariant. Top symbol "
                    "any-reel window visibility lifted. Mid-pay window visibility "
                    "drop is intentional (user-confirmed side effect)."
                ),
            }
            wdoc["_v81_mechanism_b"] = mb_meta
            wpath.write_text(
                json.dumps(wdoc, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"  [write] wrote {wpath.relative_to(_ROOT)}")
        print()

    if not write:
        print("[dry-run] no files written. Use --write to apply.")
        return 0

    if verify:
        print("-" * 78)
        print("Post-redistribution RTP/hit verification")
        print("-" * 78)
        from slot_designer.core.engine.loader import load_engine
        from slot_designer.core.devtools.analytic_rtp import analytic_profile
        for mode in _MODES:
            wpath = _M15 / "weights" / f"mode_{mode}" / "weights.json"
            eng, _ = load_engine(_M15 / "spec.json", wpath,
                                 strips_path=_M15 / "reel_strips.json")
            prof = analytic_profile(eng)
            print(f"  mode {mode}: RTP {prof['rtp_pct']:.4f}%, hit {prof['hit_rate']:.4%}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--write", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--floor", type=int, default=1,
                   help="non-top-adj Blank weight floor (default 1)")
    args = p.parse_args()
    sys.exit(run(write=args.write, verify=args.verify, floor=args.floor))


if __name__ == "__main__":
    main()
