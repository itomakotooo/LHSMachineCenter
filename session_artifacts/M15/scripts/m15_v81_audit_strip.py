"""M15 v8.1 Phase A — strip §14 visual rhythm audit (per-symbol per-reel).

Dump for each reel:
  - non-blank symbol sequence (cyclic, 18 positions on M15)
  - same-family cluster stats (bar family = {1bar, 2bar, 3bar})
  - same-symbol repeat distances (min cyclic gap)
  - top-symbol pair distances (doublediamond <-> doublediamond, high7 <-> high7)
  - brand symbol (cherry) cross-reel distribution

Output: ASCII to stdout — pipe to v81_visual_rhythm_audit.md.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_STRIPS_PATH = _ROOT / "slot_designer" / "machines" / "M15" / "reel_strips.json"

BAR_FAMILY = {"1bar", "2bar", "3bar"}
TOP_SYMBOLS = {"doublediamond", "high7", "topdollar"}
MID_BAR = {"2bar", "3bar"}  # mid-pay bars
FILLER = {"jackpot"}


def cyclic_min_gap(positions: list[int], n: int) -> int:
    """Min cyclic gap between consecutive positions in sorted list."""
    if len(positions) < 2:
        return n  # only one or zero -- gap is full reel
    sorted_p = sorted(positions)
    gaps = []
    for i in range(len(sorted_p)):
        a = sorted_p[i]
        b = sorted_p[(i + 1) % len(sorted_p)]
        if i == len(sorted_p) - 1:
            gap = (b + n) - a
        else:
            gap = b - a
        gaps.append(gap)
    return min(gaps)


def cyclic_pair_distances(positions: list[int], n: int) -> list[int]:
    """All pair-wise cyclic shortest distances between positions."""
    if len(positions) < 2:
        return []
    sorted_p = sorted(positions)
    out = []
    for i in range(len(sorted_p)):
        a = sorted_p[i]
        b = sorted_p[(i + 1) % len(sorted_p)]
        if i == len(sorted_p) - 1:
            gap = (b + n) - a
        else:
            gap = b - a
        out.append(gap)
    return out


def max_same_family_consecutive(non_blank_seq: list[str], family: set[str]) -> tuple[int, list[int]]:
    """Given cyclic non-blank sequence, find max run length where every element in family.

    Returns (max_run_length, run_start_indices).
    """
    n = len(non_blank_seq)
    # Walk through cyclic, find runs
    # Use double-traversal to handle wrap-around
    doubled = non_blank_seq + non_blank_seq
    max_run = 0
    max_starts = []
    cur_run = 0
    cur_start = 0
    for i in range(2 * n):
        if doubled[i] in family:
            if cur_run == 0:
                cur_start = i
            cur_run += 1
            if cur_run > max_run:
                max_run = cur_run
                max_starts = [cur_start % n]
            elif cur_run == max_run:
                if (cur_start % n) not in max_starts:
                    max_starts.append(cur_start % n)
        else:
            cur_run = 0
    # Cap max_run at n (can't exceed cyclic length)
    max_run = min(max_run, n)
    return max_run, max_starts


def audit_reel(reel_idx: int, reel: list[str], strip_length: int) -> dict:
    """Per-reel audit metrics."""
    # Extract non-blank sequence (cyclic)
    non_blank_with_pos = [(p, s) for p, s in enumerate(reel) if s != "blank"]
    nb_seq = [s for _, s in non_blank_with_pos]
    nb_positions = [p for p, _ in non_blank_with_pos]

    # Per-symbol positions on strip
    sym_positions: dict[str, list[int]] = {}
    for p, s in enumerate(reel):
        if s != "blank":
            sym_positions.setdefault(s, []).append(p)

    out = {
        "reel": reel_idx + 1,
        "strip_length": strip_length,
        "non_blank_seq": nb_seq,
        "non_blank_positions": nb_positions,
        "symbol_counts": dict(Counter(nb_seq)),
        "symbol_positions": sym_positions,
    }

    # Max bar-family consecutive run (in non-blank cyclic seq)
    bar_run_len, bar_run_starts = max_same_family_consecutive(nb_seq, BAR_FAMILY)
    out["bar_family_max_run"] = bar_run_len
    out["bar_family_max_run_starts"] = bar_run_starts

    # Top symbol consecutive run
    top_run_len, top_run_starts = max_same_family_consecutive(nb_seq, TOP_SYMBOLS)
    out["top_symbol_max_run"] = top_run_len
    out["top_symbol_max_run_starts"] = top_run_starts

    # Same-symbol min gap on strip (cyclic, in stops including blanks)
    same_sym_min_gap: dict[str, int] = {}
    for sym, positions in sym_positions.items():
        if len(positions) > 1:
            same_sym_min_gap[sym] = cyclic_min_gap(positions, strip_length)
    out["same_symbol_min_gap_stops"] = same_sym_min_gap

    # Top-symbol pair distances (when 2+ instances)
    top_pair_distances: dict[str, list[int]] = {}
    for sym in TOP_SYMBOLS:
        if sym in sym_positions and len(sym_positions[sym]) > 1:
            top_pair_distances[sym] = cyclic_pair_distances(sym_positions[sym], strip_length)
    out["top_symbol_pair_distances_stops"] = top_pair_distances

    # X-Blank-X count (§13 sanity, should be 0)
    n = len(reel)
    xbx = 0
    xbx_examples = []
    for p in range(n):
        if reel[p] == "blank":
            prev = reel[(p - 1) % n]
            nxt = reel[(p + 1) % n]
            if prev == nxt and prev != "blank":
                xbx += 1
                if len(xbx_examples) < 3:
                    xbx_examples.append((p, prev))
    out["xbx_violations"] = xbx
    out["xbx_examples"] = xbx_examples

    return out


def cross_reel_uniformity(strips: list[list[str]], symbol: str) -> dict:
    """Brand symbol cross-reel distribution: per-reel position list + half-of-reel skew."""
    out = {}
    for r_idx, reel in enumerate(strips):
        n = len(reel)
        positions = [p for p, s in enumerate(reel) if s == symbol]
        first_half = sum(1 for p in positions if p < n // 2)
        second_half = sum(1 for p in positions if p >= n // 2)
        out[f"R{r_idx+1}"] = {
            "positions": positions,
            "count": len(positions),
            "first_half_count": first_half,
            "second_half_count": second_half,
        }
    return out


def main() -> int:
    strips_doc = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))
    strips = strips_doc["reels"]
    n_stops = len(strips[0])

    print("=" * 78)
    print("M15 v8 strip — §14 visual rhythm audit (Phase A baseline)")
    print("=" * 78)
    print(f"Strip length per reel: {n_stops} stops")
    print(f"Per-reel: 18 blank + 18 non-blank (strict alternation per §13)")
    print()

    audits = []
    for r_idx, reel in enumerate(strips):
        audit = audit_reel(r_idx, reel, n_stops)
        audits.append(audit)

    # === per-reel dump ===
    for a in audits:
        r = a["reel"]
        print(f"--- Reel {r} ---")
        print(f"  non-blank cyclic sequence ({len(a['non_blank_seq'])}):")
        print(f"    {a['non_blank_seq']}")
        print(f"  symbol counts: {a['symbol_counts']}")
        print(f"  X-Blank-X violations: {a['xbx_violations']}  (§13 universal hard rule)")
        print(f"  max bar-family consecutive run (in non-blank seq): "
              f"{a['bar_family_max_run']} symbols  starts={a['bar_family_max_run_starts']}")
        print(f"  max top-symbol consecutive run: "
              f"{a['top_symbol_max_run']} symbols  starts={a['top_symbol_max_run_starts']}")
        print(f"  same-symbol min cyclic gap (stops):")
        for sym in sorted(a["same_symbol_min_gap_stops"].keys()):
            gap = a["same_symbol_min_gap_stops"][sym]
            ct = a["symbol_counts"][sym]
            print(f"    {sym:14s} count={ct} min_gap={gap} stops")
        if a["top_symbol_pair_distances_stops"]:
            print(f"  top-symbol pair distances (stops, cyclic, between consecutive instances):")
            for sym in sorted(a["top_symbol_pair_distances_stops"].keys()):
                dists = a["top_symbol_pair_distances_stops"][sym]
                print(f"    {sym:14s} dists={dists}  min={min(dists)} max={max(dists)}")
        print()

    # === cross-reel brand (cherry) uniformity ===
    print("--- Cross-reel brand (cherry) distribution ---")
    cherry_dist = cross_reel_uniformity(strips, "cherry")
    for k, v in cherry_dist.items():
        print(f"  {k}: positions={v['positions']}  count={v['count']}  "
              f"first_half={v['first_half_count']}  second_half={v['second_half_count']}")
    print()

    # === jackpot distribution (filler) ===
    print("--- Filler (jackpot) distribution ---")
    jack_dist = cross_reel_uniformity(strips, "jackpot")
    for k, v in jack_dist.items():
        print(f"  {k}: positions={v['positions']}  count={v['count']}  "
              f"first_half={v['first_half_count']}  second_half={v['second_half_count']}")
    print()

    # === topdollar (R3 only) distribution ===
    print("--- Trigger (topdollar, R3 only) distribution ---")
    td_dist = cross_reel_uniformity(strips, "topdollar")
    for k, v in td_dist.items():
        print(f"  {k}: positions={v['positions']}  count={v['count']}")
    print()

    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
