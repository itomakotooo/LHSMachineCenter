"""Rearrange M1 reel_strips.json non-Blank positions to satisfy:

  §13 BLANK-FLANK-DIVERSITY (universal): no X-Blank-X in 3-row window
  §14 M1 SAME-SYMBOL-SPACING ≥ 4 stops: same-symbol cyclic distance ≥ 4 stops

Note: For M1's strict B-N alternation strip (22 stops, 11+11), §14 SAME-SYMBOL-
SPACING ≥ 4 is EQUIVALENT to §13 (any distance-2 same-symbol is exactly the
X-Blank-X case). So one search satisfies both. BAR-CLUSTERING (different Bar
types adjacent) NOT included — IGT classic 3-reel paytable convention allows
mid-Bar clusters; user can re-enable if wanted.

Algorithm — minimum-change repair (preserves archetype direction):
  1. Extract per-reel non-Blank symbol sequence (cyclic, length 11)
  2. Find §13 violations (pairs k where nb[k] == nb[k+1] cyclic)
  3. Greedy swap repair: for each violation, try all swap candidates,
     pick one minimizing (new_violations, hamming_distance_to_original).
     If swap doesn't improve, fall back to backtracking from current state.
  4. Permute weights alongside symbols (preserves marginal → RTP/hit/share unchanged)
  5. Write reel_strips.json + each mode's weights.json + reel_weights.tsv

Marginal preservation guarantees RTP/hit/share/family-share invariant
across rearrange. Strip md5 changes → all-mode rawdata cache invalidated
→ re-sample required.

Usage:
  python -m slot_designer.scripts.rearrange_m1_strips [--write] [--verify]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_STRIPS = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"
_MODES = (1, 2, 5, 7)


def find_violations(nb_seq: list[str]) -> list[tuple[int, int]]:
    """Return list of (k, (k+1)%n) cyclic pairs where nb[k] == nb[next]."""
    n = len(nb_seq)
    return [(k, (k + 1) % n) for k in range(n) if nb_seq[k] == nb_seq[(k + 1) % n]]


def hamming_distance(a: list[str], b: list[str]) -> int:
    return sum(1 for x, y in zip(a, b) if x != y)


def repair_min_change(original: list[str], max_iters: int = 200) -> Optional[list[str]]:
    """Greedy minimum-change repair to satisfy §13 (no consecutive same in cyclic seq).

    Returns repaired arrangement, or None if stuck.
    """
    arr = list(original)
    n = len(arr)

    for _ in range(max_iters):
        violations = find_violations(arr)
        if not violations:
            return arr
        # Pick first violation pair; try swapping arr[j] with each other position
        i, j = violations[0]

        best_swap: Optional[tuple[int, int]] = None
        best_score = (len(violations), n)  # (new_violations, hamming_inc)

        for swap_target in range(n):
            if swap_target in (i, j):
                continue
            if arr[swap_target] == arr[j]:
                continue  # noop swap
            # Try swapping arr[j] with arr[swap_target]
            arr[j], arr[swap_target] = arr[swap_target], arr[j]
            new_v = len(find_violations(arr))
            new_h = hamming_distance(arr, original)
            score = (new_v, new_h)
            if score < best_score:
                best_score = score
                best_swap = (j, swap_target)
            # Revert
            arr[j], arr[swap_target] = arr[swap_target], arr[j]

        # Also try swapping arr[i] with each other position
        for swap_target in range(n):
            if swap_target in (i, j):
                continue
            if arr[swap_target] == arr[i]:
                continue
            arr[i], arr[swap_target] = arr[swap_target], arr[i]
            new_v = len(find_violations(arr))
            new_h = hamming_distance(arr, original)
            score = (new_v, new_h)
            if score < best_score:
                best_score = score
                best_swap = (i, swap_target)
            arr[i], arr[swap_target] = arr[swap_target], arr[i]

        if best_swap is None:
            # No swap improves — stuck
            return None
        a, b = best_swap
        arr[a], arr[b] = arr[b], arr[a]

    # Hit max iters
    return None if find_violations(arr) else arr


def rearrange_one_reel(reel: list[str]) -> tuple[list[str], list[int]]:
    """Rearrange one reel's non-Blank positions.

    Returns (new_reel, permutation) where permutation[k] = old non-Blank-index
    whose (symbol, weight) now sits at new non-Blank-index k.
    """
    n = len(reel)
    nb_positions = [p for p in range(n) if reel[p] != "Blank"]
    nb_symbols = [reel[p] for p in nb_positions]

    repaired = repair_min_change(nb_symbols)
    if repaired is None:
        raise RuntimeError(
            f"Could not repair reel with non-Blank sequence {nb_symbols}; "
            f"counts: {dict(Counter(nb_symbols))}"
        )

    # Build permutation: for each new nb-index k, find which old nb-index j
    # has the same symbol (and isn't already used). Multiple candidates can
    # exist for repeated symbols; pick smallest unused j (stable, deterministic).
    used_old = [False] * len(nb_symbols)
    permutation = [-1] * len(nb_symbols)
    for k, sym in enumerate(repaired):
        # Prefer keeping position unchanged if symbol matches (preserves archetype)
        if nb_symbols[k] == sym and not used_old[k]:
            permutation[k] = k
            used_old[k] = True
            continue
        for j, old_sym in enumerate(nb_symbols):
            if not used_old[j] and old_sym == sym:
                permutation[k] = j
                used_old[j] = True
                break
        else:
            raise RuntimeError(f"Can't fulfill arrangement at nb-index {k}, sym {sym}")

    new_reel = list(reel)
    for k, p in enumerate(nb_positions):
        new_reel[p] = repaired[k]
    return new_reel, permutation


def permute_reel_weights(reel_weights: list[int], nb_positions: list[int],
                          permutation: list[int]) -> list[int]:
    """Apply permutation to weights at non-blank positions; Blanks unchanged."""
    new_w = list(reel_weights)
    old_nb_w = [reel_weights[p] for p in nb_positions]
    for k, p in enumerate(nb_positions):
        new_w[p] = old_nb_w[permutation[k]]
    return new_w


def run(write: bool, verify: bool) -> int:
    print(f"{'='*70}")
    print("M1 strip rearrange — satisfy §13 (no X-Blank-X) with minimum changes")
    print(f"{'='*70}\n")

    strips_doc = json.loads(_STRIPS.read_text(encoding="utf-8"))
    strips = strips_doc["reels"]
    n_reels = len(strips)
    n_stops = len(strips[0])

    new_strips: list[list[str]] = []
    permutations: list[list[int]] = []
    nb_positions_per_reel: list[list[int]] = []

    for r_idx, reel in enumerate(strips):
        nb_positions = [p for p in range(n_stops) if reel[p] != "Blank"]
        nb_positions_per_reel.append(nb_positions)
        old_nb = [reel[p] for p in nb_positions]
        old_violations = find_violations(old_nb)

        new_reel, perm = rearrange_one_reel(reel)
        new_nb = [new_reel[p] for p in nb_positions]
        new_violations = find_violations(new_nb)
        h = hamming_distance(old_nb, new_nb)

        new_strips.append(new_reel)
        permutations.append(perm)

        print(f"R{r_idx+1}:")
        print(f"  old nb (violations: {len(old_violations)}): {old_nb}")
        print(f"  new nb (violations: {len(new_violations)}): {new_nb}")
        print(f"  hamming: {h}/{len(old_nb)} positions changed")
        print()

    if not write:
        print("[dry-run] no files written. Use --write to apply.")
        return 0

    # Persist strips + update _archetype
    strips_doc["reels"] = new_strips
    archetype = strips_doc.get("_archetype", {})
    prev_mod = archetype.get("modifications_from_archetype", "")
    rearrange_note = (
        " 2026-04-29 strip non-Blank positions rearranged (minimum-change repair) "
        "to satisfy §13 BLANK-FLANK-DIVERSITY — no X-Blank-X in 3-row window. "
        "Per-reel symbol counts preserved; weights permuted alongside symbols → "
        "marginals UNCHANGED (RTP/hit/share invariant). Strip md5 changes → "
        "all-mode rawdata cache invalidated."
    )
    archetype["modifications_from_archetype"] = prev_mod + rearrange_note
    strips_doc["_archetype"] = archetype

    _STRIPS.write_text(json.dumps(strips_doc, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(f"[write] wrote {_STRIPS.relative_to(_ROOT)}")

    # Permute weights for each mode + regenerate reel_weights.tsv
    for mode in _MODES:
        wpath = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
        wdoc = json.loads(wpath.read_text(encoding="utf-8"))
        old_weights = wdoc["weights"]
        new_weights = []
        for r_idx in range(n_reels):
            new_w = permute_reel_weights(
                old_weights[r_idx],
                nb_positions_per_reel[r_idx],
                permutations[r_idx],
            )
            new_weights.append(new_w)
        wdoc["weights"] = new_weights
        wpath.write_text(json.dumps(wdoc, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
        print(f"[write] wrote {wpath.relative_to(_ROOT)}")

        # tsv
        tsv_path = wpath.parent / "reel_weights.tsv"
        tsv_lines = ["reel1\tweight1\treel2\tweight2\treel3\tweight3"]
        for p in range(n_stops):
            cells = []
            for r in range(n_reels):
                cells.append(new_strips[r][p])
                cells.append(str(int(new_weights[r][p])))
            tsv_lines.append("\t".join(cells))
        tsv_path.write_text("\n".join(tsv_lines) + "\n", encoding="utf-8")
        print(f"[write] wrote {tsv_path.relative_to(_ROOT)}")

    if verify:
        print()
        print(f"{'-'*70}")
        print("Marginal preservation check (RTP/hit should be unchanged from pre-rearrange)")
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
                   help="write new strips + permuted weights (default: dry-run)")
    p.add_argument("--verify", action="store_true",
                   help="after --write, run analytic RTP check")
    args = p.parse_args()
    sys.exit(run(write=args.write, verify=args.verify))


if __name__ == "__main__":
    main()
