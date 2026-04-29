"""RTP-neutral Blank weight redistribution for M1 — boost top-symbol window
visibility WITHOUT changing RTP, hit, or any family marginal.

Mechanism:
  Per reel, identify "top-adjacent" Blank positions (those whose strip
  neighbor is a top-prize symbol: Diamond1/Diamond2/Seven1/Seven2).
  Shift weight FROM non-top-adj Blank positions (down to floor=1) TO
  top-adj Blank positions, preserving total Blank weight per reel.

Why RTP-neutral:
  - Total Blank weight per reel = unchanged → Blank family marginal unchanged
  - All non-Blank weights = unchanged → all non-Blank family marginals unchanged
  - Total reel weight = unchanged → marginals invariant
  - All bucket distributions, hit rates, RTP = unchanged
  - ONLY visibility changes (which is per-position, not per-marginal)

Why visibility goes up:
  - P(top symbol in 3-row window) = sum of weight at positions where window
    includes top symbol (= top symbol's stop position + 2 adjacent stops)
  - Adjacent stops are the 2 Blank positions flanking the top symbol
  - These Blank positions now have heavier weight → reel often stops there →
    window often includes the top symbol

Trade-off:
  - Cherry / Bar visibility may drop (their adjacent Blanks lose weight)
  - For M1: Cherry drops ~57% → ~38% (still well above 28% regression floor)
  - Top-prize symbols (Diamond1/Diamond2/Seven2) gain ~9-11pp each
  - Net: top-prize "almost won" psychology much stronger

NOT a Harrigan virtual-reel mapping. Harrigan's 50%+ uses 64-stop virtual reels
mapped to 22 physical via weight-table — fundamentally different architecture
that allows visibility ≫ marginal × constant. This redistribution stays within
physical-reel constraints but extracts maximum visibility per the available
weight budget.

Usage:
  python -m slot_designer.scripts.redistribute_m1_blanks [--write] [--verify]
  python -m slot_designer.scripts.redistribute_m1_blanks --floor 3 --write   # less aggressive
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_STRIPS = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"
_MODES = (1, 2, 5, 7)

TOP_PRIZE_SYMBOLS = ("Diamond1", "Diamond2", "Seven1", "Seven2")


def _classify_blank_positions(strip_reel: list[str]) -> tuple[list[int], list[int]]:
    """Return (top_adj_positions, non_top_adj_positions) for Blank stops on this reel."""
    n = len(strip_reel)
    top_adj = []
    non_top_adj = []
    for p in range(n):
        if strip_reel[p] != "Blank":
            continue
        prev = strip_reel[(p - 1) % n]
        nxt = strip_reel[(p + 1) % n]
        if prev in TOP_PRIZE_SYMBOLS or nxt in TOP_PRIZE_SYMBOLS:
            top_adj.append(p)
        else:
            non_top_adj.append(p)
    return top_adj, non_top_adj


def redistribute_blanks(weights: list[list[int]], strips: list[list[str]],
                        non_top_adj_floor: int = 1) -> list[list[int]]:
    """Apply RTP-neutral redistribution per reel. Returns new weights array.

    Algorithm: per reel, set non-top-adj Blank weights to `non_top_adj_floor`,
    pour the freed weight into top-adj Blank positions evenly. Total Blank
    weight per reel preserved (rounding-distributed via leftover).
    """
    new_w = [list(reel) for reel in weights]
    for r in range(len(strips)):
        top_adj, non_top_adj = _classify_blank_positions(strips[r])
        if not top_adj or not non_top_adj:
            continue  # nothing to redistribute
        # Total existing Blank weight (must be preserved)
        total_blank = sum(new_w[r][p] for p in top_adj + non_top_adj)
        n_top = len(top_adj)
        n_non_top = len(non_top_adj)
        # New non-top-adj = floor; top-adj absorbs the rest evenly
        budget_for_top = total_blank - n_non_top * non_top_adj_floor
        if budget_for_top <= n_top:
            # Floor too aggressive — keep current distribution
            continue
        new_top_base = budget_for_top // n_top
        leftover = budget_for_top - new_top_base * n_top
        # Distribute leftover across first `leftover` top-adj positions (+1 each)
        for i, p in enumerate(top_adj):
            new_w[r][p] = new_top_base + (1 if i < leftover else 0)
        for p in non_top_adj:
            new_w[r][p] = non_top_adj_floor
    return new_w


def run(write: bool, verify: bool, floor: int) -> int:
    print(f"{'='*70}")
    print(f"M1 RTP-neutral Blank redistribution (floor={floor})")
    print(f"{'='*70}\n")

    strips_doc = json.loads(_STRIPS.read_text(encoding="utf-8"))
    strips = strips_doc["reels"]

    for mode in _MODES:
        wpath = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
        wdoc = json.loads(wpath.read_text(encoding="utf-8"))
        old_weights = wdoc["weights"]
        new_weights = redistribute_blanks(old_weights, strips, non_top_adj_floor=floor)

        # Show per-reel impact
        print(f"--- mode {mode} ---")
        for r in range(len(strips)):
            top_adj, non_top_adj = _classify_blank_positions(strips[r])
            old_top_w = [old_weights[r][p] for p in top_adj]
            new_top_w = [new_weights[r][p] for p in top_adj]
            old_non = [old_weights[r][p] for p in non_top_adj]
            new_non = [new_weights[r][p] for p in non_top_adj]
            old_total_b = sum(old_top_w) + sum(old_non)
            new_total_b = sum(new_top_w) + sum(new_non)
            print(f"  R{r+1}: top-adj Blank weights {old_top_w} -> {new_top_w[:3]}...")
            print(f"        non-top-adj         {old_non} -> {new_non}")
            print(f"        total Blank weight  {old_total_b} -> {new_total_b}  (must match)")

        if write:
            wdoc["weights"] = new_weights
            wdoc["_pwdf_redistribution"] = {
                "method": "rtp_neutral_blank_redistribution",
                "non_top_adj_floor": floor,
                "rationale": "Shift weight from non-top-adj Blanks to top-adj "
                             "Blanks, preserving total Blank weight per reel. "
                             "Marginals invariant → RTP/hit/share unchanged. "
                             "Top-symbol window visibility increases.",
            }
            wpath.write_text(json.dumps(wdoc, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
            print(f"  [write] wrote {wpath.relative_to(_ROOT)}")

            # Regenerate reel_weights.tsv
            tsv_path = wpath.parent / "reel_weights.tsv"
            n_stops = len(strips[0])
            tsv_lines = ["reel1\tweight1\treel2\tweight2\treel3\tweight3"]
            for p in range(n_stops):
                cells = []
                for r in range(len(strips)):
                    cells.append(strips[r][p])
                    cells.append(str(int(new_weights[r][p])))
                tsv_lines.append("\t".join(cells))
            tsv_path.write_text("\n".join(tsv_lines) + "\n", encoding="utf-8")
            print(f"  [write] wrote {tsv_path.relative_to(_ROOT)}")
        print()

    if not write:
        print("[dry-run] no files written. Use --write to apply.")
        return 0

    if verify:
        print(f"{'-'*70}")
        print(f"Post-redistribution verification")
        print(f"{'-'*70}")
        from slot_designer.engine.loader import load_engine
        from slot_designer.devtools.analytic_rtp import analytic_profile
        spec = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
        for mode in _MODES:
            wpath = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
            eng, _ = load_engine(spec, wpath)
            prof = analytic_profile(eng)
            print(f"  mode {mode}: RTP {prof['rtp_pct']:.3f}%, hit {prof['hit_rate']:.3%}")

    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--write", action="store_true",
                   help="write new weights (default: dry-run)")
    p.add_argument("--verify", action="store_true",
                   help="run analytic verification post-write")
    p.add_argument("--floor", type=int, default=1,
                   help="non-top-adj Blank weight floor (default 1, max aggressive)")
    args = p.parse_args()
    sys.exit(run(write=args.write, verify=args.verify, floor=args.floor))


if __name__ == "__main__":
    main()
