"""M15 v8.1 Phase B — rearrange reel_strips.json to satisfy §14 thresholds.

Goal: per-(reel, symbol) multiset UNCHANGED → marginals UNCHANGED →
RTP/hit/share UNCHANGED. Only non-blank position ordering on the strip
changes.

§14 thresholds (M15-specific, set in Phase A audit based on archetype +
strip length 36 / 18 non-blank per reel):

  - BAR family max consecutive (in non-blank seq) ≤ 4 symbols
    rationale: 18-non-blank-position reel, 11 bars across 3 tiers; 6-run
    (current R1) reads as "all bar segment"; 5-run (R2) is borderline.
    R3 already at 3 — proves achievable. Target 4 = compromise between
    "1bar-2bar-3bar tier" archetype natural and visual rhythm.
  - TOP-symbol consecutive run (in non-blank seq) ≤ 1
    rationale: current R3 has 1, R1/R2 have 2 (high7+doublediamond
    adjacent at idx 4-5 and 16-17). Top symbols MUST be separated by
    at least one non-top non-blank.
  - Top-symbol pair distance on strip ≥ 8 stops (~22% of reel length)
    rationale: current min is 10-12 stops; want NO doublediamond/high7
    pair tighter than 8 stops to prevent "two diamonds in a flash" feel.
  - Same-symbol min cyclic gap ≥ 5 stops for 3-count symbols (1bar with
    3 instances), ≥ 5 stops for 4-count symbols (2bar/3bar)
    rationale: current min is 6 stops everywhere on R1/R2; R3 has 8+;
    floor 5 leaves some margin.
  - §13 BLANK-FLANK (universal): 0 X-Blank-X violations — invariant.

Algorithm — CSP-style minimum-change repair:
  1. Extract non-blank cyclic sequence per reel (length 18)
  2. While violations exist: pick worst (longest bar-run or top-adjacency),
     try all swaps within sequence; pick swap minimizing (n_violations,
     hamming_distance). Validate §13 holds after swap.
  3. If stuck, randomized restart up to N attempts. Backtracking last
     resort.

Per-(reel, symbol) marginal preserved by ONLY permuting positions of
non-blank stops within each reel. Blanks unchanged (positions + weights).
Non-blank weights are PERMUTED ALONGSIDE symbols so each (symbol, weight)
pair stays bound — total reel marginal = unchanged. Combined with mechanism
B in Phase C (which redistributes BLANK weights only, not non-blank), the
final RTP/hit/share is mathematically invariant.

Usage:
  python session_artifacts/M15/scripts/m15_v81_rearrange_strip.py [--write] [--verify]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_STRIPS_PATH = _ROOT / "slot_designer" / "machines" / "M15" / "reel_strips.json"
_M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
_MODES = (1, 2, 5, 7)

# Symbol families
BAR_FAMILY = {"1bar", "2bar", "3bar"}
TOP_SYMBOLS = {"doublediamond", "high7", "topdollar"}

# §14 thresholds (M15-specific, locked into verify.py [VISUAL-RHYTHM])
MAX_BAR_FAMILY_RUN = 4         # in non-blank seq
MAX_TOP_SYMBOL_RUN = 1         # in non-blank seq  -- top symbols never adjacent in nb seq
MIN_TOP_PAIR_DISTANCE_STOPS = 8  # on strip (counts blanks)
MIN_SAME_SYMBOL_GAP_STOPS = 5    # on strip


def find_bar_family_run(nb_seq: list[str]) -> tuple[int, int]:
    """Find longest cyclic run of bar-family symbols.

    Returns (max_run_length, start_index_in_cyclic_seq).
    """
    n = len(nb_seq)
    doubled = nb_seq + nb_seq
    max_run = 0
    max_start = 0
    cur = 0
    cur_start = 0
    for i in range(2 * n):
        if doubled[i] in BAR_FAMILY:
            if cur == 0:
                cur_start = i
            cur += 1
            if cur > max_run:
                max_run = cur
                max_start = cur_start % n
        else:
            cur = 0
    return min(max_run, n), max_start


def find_top_consecutive(nb_seq: list[str]) -> list[int]:
    """Return list of cyclic indices i where nb_seq[i] and nb_seq[i+1] are both top symbols."""
    n = len(nb_seq)
    out = []
    for i in range(n):
        if nb_seq[i] in TOP_SYMBOLS and nb_seq[(i + 1) % n] in TOP_SYMBOLS:
            out.append(i)
    return out


def count_violations(nb_seq: list[str]) -> dict:
    """Score current sequence.

    Returns dict with:
      bar_run_len, bar_run_excess, top_pairs_count, total_score
    """
    bar_run, bar_start = find_bar_family_run(nb_seq)
    bar_excess = max(0, bar_run - MAX_BAR_FAMILY_RUN)
    top_pairs = find_top_consecutive(nb_seq)
    # Total score: weight top adjacency heavily, then bar excess
    score = bar_excess * 5 + len(top_pairs) * 10
    return {
        "bar_run_len": bar_run,
        "bar_run_start": bar_start,
        "bar_run_excess": bar_excess,
        "top_pairs": top_pairs,
        "top_pairs_count": len(top_pairs),
        "score": score,
    }


def violates_strip_constraints(strip: list[str], nb_positions: list[int],
                                nb_seq: list[str]) -> tuple[bool, str]:
    """Check §13 and other strip-level invariants after a candidate arrangement.

    Returns (violated, reason). Builds the candidate strip by placing nb_seq
    elements at nb_positions, keeping blanks elsewhere.
    """
    n = len(strip)
    candidate = list(strip)
    for k, p in enumerate(nb_positions):
        candidate[p] = nb_seq[k]
    # §13: X-Blank-X = blank at p, candidate[p-1] == candidate[p+1] (both non-blank)
    for p in range(n):
        if candidate[p] == "blank":
            prev = candidate[(p - 1) % n]
            nxt = candidate[(p + 1) % n]
            if prev == nxt and prev != "blank":
                return True, f"X-Blank-X at p={p} ({prev}-blank-{prev})"
    # Top-symbol pair distance check
    for top_sym in TOP_SYMBOLS:
        positions = [i for i, s in enumerate(candidate) if s == top_sym]
        if len(positions) >= 2:
            positions.sort()
            for i in range(len(positions)):
                a = positions[i]
                b = positions[(i + 1) % len(positions)]
                if i == len(positions) - 1:
                    gap = (b + n) - a
                else:
                    gap = b - a
                if gap < MIN_TOP_PAIR_DISTANCE_STOPS:
                    return True, f"top-pair too close: {top_sym} gap={gap} at positions {a},{b}"
    # Same-symbol min cyclic gap
    sym_positions: dict[str, list[int]] = {}
    for i, s in enumerate(candidate):
        if s != "blank":
            sym_positions.setdefault(s, []).append(i)
    for sym, positions in sym_positions.items():
        if len(positions) < 2:
            continue
        positions.sort()
        for i in range(len(positions)):
            a = positions[i]
            b = positions[(i + 1) % len(positions)]
            if i == len(positions) - 1:
                gap = (b + n) - a
            else:
                gap = b - a
            if gap < MIN_SAME_SYMBOL_GAP_STOPS:
                return True, f"same-sym gap too small: {sym} gap={gap} at positions {a},{b}"
    return False, ""


def hamming(a: list[str], b: list[str]) -> int:
    return sum(1 for x, y in zip(a, b) if x != y)


def repair_reel(strip: list[str], nb_positions: list[int],
                seed: int = 42, max_outer: int = 400) -> list[str] | None:
    """Repair one reel's non-blank cyclic sequence by greedy swap + restart.

    Returns the new non-blank sequence (length 18) or None if can't repair.
    """
    rng = random.Random(seed)
    original_nb = [strip[p] for p in nb_positions]
    best_seq = None
    best_score = float("inf")

    for restart in range(max_outer):
        if restart == 0:
            arr = list(original_nb)
        else:
            # Random permutation of the multiset
            arr = list(original_nb)
            rng.shuffle(arr)

        # Inner greedy swap pass
        for inner in range(200):
            v = count_violations(arr)
            strip_violated, _ = violates_strip_constraints(strip, nb_positions, arr)
            total_bad = v["score"] + (100 if strip_violated else 0)

            if total_bad == 0:
                # Done! Compare with original for hamming preference
                h = hamming(original_nb, arr)
                score = (0, h)
                if score < (0, best_score) if isinstance(best_score, int) else True:
                    if best_seq is None or h < best_score:
                        best_seq = list(arr)
                        best_score = h
                break

            # Try all pairwise swaps within arr; pick best
            best_swap = None
            best_swap_score = total_bad
            for i in range(len(arr)):
                for j in range(i + 1, len(arr)):
                    if arr[i] == arr[j]:
                        continue
                    arr[i], arr[j] = arr[j], arr[i]
                    v2 = count_violations(arr)
                    strip_violated2, _ = violates_strip_constraints(strip, nb_positions, arr)
                    new_bad = v2["score"] + (100 if strip_violated2 else 0)
                    if new_bad < best_swap_score:
                        best_swap_score = new_bad
                        best_swap = (i, j)
                    arr[i], arr[j] = arr[j], arr[i]  # revert

            if best_swap is None:
                break  # local minimum, try restart
            i, j = best_swap
            arr[i], arr[j] = arr[j], arr[i]

        # Outer end: if we found a clean one with reasonable hamming, stop early
        if best_seq is not None and best_score <= 6:
            break

    return best_seq


def build_permutation(original_nb: list[str], new_nb: list[str]) -> list[int]:
    """For each new index k, find old index j with same symbol (deterministic)."""
    used = [False] * len(original_nb)
    perm = [-1] * len(new_nb)
    # First pass: preserve identity where possible
    for k, sym in enumerate(new_nb):
        if original_nb[k] == sym and not used[k]:
            perm[k] = k
            used[k] = True
    # Second pass: fill the rest
    for k, sym in enumerate(new_nb):
        if perm[k] != -1:
            continue
        for j, old_sym in enumerate(original_nb):
            if not used[j] and old_sym == sym:
                perm[k] = j
                used[j] = True
                break
        else:
            raise RuntimeError(f"can't fulfill arrangement at idx {k}, sym {sym}")
    return perm


def run(write: bool, verify: bool) -> int:
    print("=" * 78)
    print("M15 v8.1 Phase B — strip rearrange to satisfy §14 thresholds")
    print(f"  bar-family max run = {MAX_BAR_FAMILY_RUN}")
    print(f"  top-symbol max consecutive = {MAX_TOP_SYMBOL_RUN}")
    print(f"  top-pair min distance = {MIN_TOP_PAIR_DISTANCE_STOPS} stops")
    print(f"  same-symbol min cyclic gap = {MIN_SAME_SYMBOL_GAP_STOPS} stops")
    print("=" * 78)
    print()

    strips_doc = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))
    strips = strips_doc["reels"]
    n_stops = len(strips[0])
    n_reels = len(strips)

    new_strips = []
    nb_positions_per_reel = []
    permutations = []

    for r_idx, reel in enumerate(strips):
        nb_positions = [p for p in range(n_stops) if reel[p] != "blank"]
        original_nb = [reel[p] for p in nb_positions]

        print(f"--- Reel {r_idx+1} ---")
        v_orig = count_violations(original_nb)
        s_violated, s_reason = violates_strip_constraints(reel, nb_positions, original_nb)
        print(f"  original nb seq: {original_nb}")
        print(f"  bar-run={v_orig['bar_run_len']} (excess={v_orig['bar_run_excess']}), "
              f"top-pairs={v_orig['top_pairs_count']}")
        if s_violated:
            print(f"  strip-level: {s_reason}")

        # Pick reel-specific seed for reproducibility
        new_nb = repair_reel(reel, nb_positions, seed=42 + r_idx)
        if new_nb is None:
            print(f"  [FAIL] could not repair reel {r_idx+1}")
            return 1

        v_new = count_violations(new_nb)
        s_violated2, s_reason2 = violates_strip_constraints(reel, nb_positions, new_nb)
        h = hamming(original_nb, new_nb)
        print(f"  new nb seq:      {new_nb}")
        print(f"  bar-run={v_new['bar_run_len']} (excess={v_new['bar_run_excess']}), "
              f"top-pairs={v_new['top_pairs_count']}, hamming={h}/{len(original_nb)}")
        if s_violated2:
            print(f"  [WARN] strip-level still violated: {s_reason2}")
            print(f"  This means thresholds may not all be achievable simultaneously.")

        # Build full reel
        new_reel = list(reel)
        for k, p in enumerate(nb_positions):
            new_reel[p] = new_nb[k]
        new_strips.append(new_reel)
        nb_positions_per_reel.append(nb_positions)
        permutations.append(build_permutation(original_nb, new_nb))

        # Confirm multiset preserved
        assert Counter(new_nb) == Counter(original_nb), "MULTISET BROKEN"
        print(f"  multiset preserved: {dict(Counter(new_nb)) == dict(Counter(original_nb))}")
        print()

    if not write:
        print("[dry-run] no files written. Use --write to apply.")
        return 0

    # Persist strips
    strips_doc["reels"] = new_strips
    notes = strips_doc.get("_notes", [])
    if isinstance(notes, list):
        notes.append("")
        notes.append("2026-05-11 v8.1 strip rearrange — §14 visual rhythm thresholds applied:")
        notes.append(f"  bar-family max consecutive run = {MAX_BAR_FAMILY_RUN}")
        notes.append(f"  top-symbol max consecutive run = {MAX_TOP_SYMBOL_RUN}")
        notes.append(f"  top-pair min distance = {MIN_TOP_PAIR_DISTANCE_STOPS} stops")
        notes.append(f"  same-symbol min cyclic gap = {MIN_SAME_SYMBOL_GAP_STOPS} stops")
        notes.append("  Per-(reel,symbol) multiset preserved → marginals unchanged → "
                     "RTP/hit/share invariant. Strip md5 changes (Phase G refresh).")
    strips_doc["_notes"] = notes

    _STRIPS_PATH.write_text(
        json.dumps(strips_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[write] wrote {_STRIPS_PATH.relative_to(_ROOT)}")

    # Permute weights for each mode
    for mode in _MODES:
        wpath = _M15_DIR / "weights" / f"mode_{mode}" / "weights.json"
        wdoc = json.loads(wpath.read_text(encoding="utf-8"))
        old_weights = wdoc["weights"]
        new_weights = []
        for r_idx in range(n_reels):
            old_w = old_weights[r_idx]
            new_w = list(old_w)
            nb_pos = nb_positions_per_reel[r_idx]
            perm = permutations[r_idx]
            # Original non-blank weights, in non-blank order
            old_nb_w = [old_w[p] for p in nb_pos]
            for k, p in enumerate(nb_pos):
                new_w[p] = old_nb_w[perm[k]]
            new_weights.append(new_w)
        wdoc["weights"] = new_weights
        wpath.write_text(
            json.dumps(wdoc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[write] wrote {wpath.relative_to(_ROOT)}")

    if verify:
        print()
        print("-" * 78)
        print("Marginal preservation check (RTP/hit unchanged from pre-rearrange)")
        print("-" * 78)
        from slot_designer.core.engine.loader import load_engine
        from slot_designer.core.devtools.analytic_rtp import analytic_profile
        spec = _M15_DIR / "spec.json"
        for mode in _MODES:
            wpath = _M15_DIR / "weights" / f"mode_{mode}" / "weights.json"
            eng, _ = load_engine(spec, wpath, strips_path=_STRIPS_PATH)
            prof = analytic_profile(eng)
            print(f"  mode {mode}: RTP {prof['rtp_pct']:.4f}%, hit {prof['hit_rate']:.4%}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--write", action="store_true")
    p.add_argument("--verify", action="store_true")
    args = p.parse_args()
    sys.exit(run(write=args.write, verify=args.verify))


if __name__ == "__main__":
    main()
