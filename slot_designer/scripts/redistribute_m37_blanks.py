"""RTP-neutral Blank weight redistribution for M37 — boost top-symbol window
visibility WITHOUT changing RTP, hit, or any family marginal.

Per universal §15.7 + §15.8 + M37/DESIGN.md §7.

Mechanism (per reel, per mode):
  Identify each Blank position's "tier" by adjacency to top symbol(s):
    R1: T1 high7-adj | T2 wild-adj | T3 mid-pay-adj only | T4 none
    R2: T1 grand-adj | T2 high7-adj | T3 booster-adj | T4 bar-adj only
    R3: T1 high7-adj | T2 wild-adj | T3 mid-pay-adj only | T4 none

  Conflict (blank adj to multi priority symbols): take highest priority.

  Allocate Blank weight per tier with mode-specific ratio:
    mode 1 / 7: T1:T2:T3:T4 = 4:3:2:1 (standard visibility)
    mode 2 / 5: T1:T2:T3:T4 = 5:4:2:1 (lucky tilt)

Why RTP-neutral:
  - Total Blank weight per (reel, mode) preserved → blank marginal unchanged
  - All non-Blank weights unchanged → all non-Blank marginals unchanged
  - Total reel weight per mode unchanged → all marginals invariant
  - All bucket distributions, hit rates, RTP, MODE7-LOCK, MODE5-BASE-LOCK preserved

Usage:
  python -m slot_designer.scripts.redistribute_m37_blanks --write --verify
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_STRIPS = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"
_MODES = (1, 2, 5, 7)

# Per-reel priority list (highest priority first → tier 1, 2, 3 by group; tier 4 = none)
# Tier mapping: index 0 = T1, index 1 = T2, etc. Each entry is a list of "priority symbols at this tier"
PRIORITY_BY_REEL = {
    0: [["high7"], ["wild"], ["1bar", "2bar", "3bar", "7bar"]],  # R1
    1: [["grand"], ["high7"], ["mini", "minor", "major"]],        # R2 (booster reel)
    2: [["high7"], ["wild"], ["1bar", "2bar", "3bar", "7bar"]],  # R3
}

# Mode-specific tier ratio T1:T2:T3:T4
MODE_RATIOS = {
    1: (4, 3, 2, 1),   # standard
    7: (4, 3, 2, 1),   # cut mode = standard (per universal §15.7)
    2: (5, 4, 2, 1),   # lucky tilt
    5: (5, 4, 2, 1),   # super-lucky = lucky (base byte-eq mode 2)
}


def _classify_blank_tiers(strip_reel: list[str], priority_groups: list[list[str]]) -> list[int]:
    """For each Blank position on this reel, return its tier (0-indexed: 0=T1, 1=T2, 2=T3, 3=T4).

    A blank at position p has neighbors strip[p-1] and strip[p+1] (cyclic).
    Tier = best (lowest index) tier across both neighbors.
    """
    n = len(strip_reel)
    tiers: list[int] = []
    blank_positions: list[int] = []
    for p in range(n):
        if strip_reel[p] != "blank":
            continue
        blank_positions.append(p)
        prev_sym = strip_reel[(p - 1) % n]
        next_sym = strip_reel[(p + 1) % n]
        # Find best tier (lowest index) for each neighbor
        best_tier = len(priority_groups)  # default = T4 (= len(priority_groups))
        for sym in (prev_sym, next_sym):
            for tier_idx, group in enumerate(priority_groups):
                if sym in group:
                    if tier_idx < best_tier:
                        best_tier = tier_idx
                    break  # priority found, no need to check lower-priority groups for this neighbor
        tiers.append(best_tier)
    return blank_positions, tiers


def redistribute_one_mode(
    strips: list[list[str]],
    weights: list[list[int]],
    mode: int,
) -> list[list[int]]:
    """Apply per-reel redistribution for one mode. Returns new weights array.

    Per (reel, mode): partition blanks by tier, assign weight per tier such that
    sum is preserved AND tier ratio is honored (rounding leftover distributed
    to highest tiers first).
    """
    ratio = MODE_RATIOS[mode]
    new_weights = [list(reel) for reel in weights]

    for reel_idx in range(len(strips)):
        priority_groups = PRIORITY_BY_REEL[reel_idx]
        blank_positions, tiers = _classify_blank_tiers(strips[reel_idx], priority_groups)
        if not blank_positions:
            continue

        # Total existing blank weight (must be preserved)
        total_blank = sum(weights[reel_idx][p] for p in blank_positions)

        # Collect counts per tier (T1..T4)
        n_tiers = len(ratio)  # 4
        tier_counts = [0] * n_tiers
        tier_blanks = [[] for _ in range(n_tiers)]
        for p, t in zip(blank_positions, tiers):
            t_clamped = min(t, n_tiers - 1)
            tier_counts[t_clamped] += 1
            tier_blanks[t_clamped].append(p)

        # base_w = total / sum(count_i * ratio_i)
        units = sum(c * r for c, r in zip(tier_counts, ratio))
        if units == 0:
            continue  # no blanks at all (shouldn't happen)

        base_w = total_blank // units
        leftover = total_blank - base_w * units

        # Initial weights per tier
        tier_w = [base_w * r for r in ratio]

        # Distribute leftover by adding +1 to each blank starting from highest tier
        # Round-robin until leftover exhausted
        flat_blanks = []  # list of (tier_idx, position) in order T1, T2, T3, T4
        for t_idx in range(n_tiers):
            for p in tier_blanks[t_idx]:
                flat_blanks.append((t_idx, p))

        # Apply weights
        per_blank_extra = [0] * len(flat_blanks)
        i = 0
        while leftover > 0:
            per_blank_extra[i % len(flat_blanks)] += 1
            leftover -= 1
            i += 1

        for (t_idx, p), extra in zip(flat_blanks, per_blank_extra):
            new_weights[reel_idx][p] = tier_w[t_idx] + extra

        # Sanity: total preserved
        new_total = sum(new_weights[reel_idx][p] for p in blank_positions)
        assert new_total == total_blank, (
            f"redistribution drift: reel {reel_idx+1} mode {mode} "
            f"total {total_blank} → {new_total}"
        )

    return new_weights


def _compute_marginals(weights: list[list[int]], strips: list[list[str]]) -> list[dict[str, float]]:
    """Per-reel symbol marginals (probability)."""
    marginals = []
    for reel_idx in range(len(strips)):
        sym_weight = {}
        total = 0
        for p, sym in enumerate(strips[reel_idx]):
            sym_weight[sym] = sym_weight.get(sym, 0) + weights[reel_idx][p]
            total += weights[reel_idx][p]
        marginals.append({s: w / total for s, w in sym_weight.items()})
    return marginals


def _compute_window_visibility(weights: list[list[int]], strips: list[list[str]],
                                target_symbols: list[str]) -> dict[int, dict[str, float]]:
    """For each reel, compute P(symbol visible in 3-row window) for target_symbols.

    P(X visible in window of reel R) = sum over stop position p of (weight[p]/total) ×
        [strip[p-1]==X OR strip[p]==X OR strip[p+1]==X]
    """
    out = {}
    for reel_idx in range(len(strips)):
        n = len(strips[reel_idx])
        total = sum(weights[reel_idx])
        vis = {sym: 0.0 for sym in target_symbols}
        for p in range(n):
            window = {strips[reel_idx][(p - 1) % n], strips[reel_idx][p], strips[reel_idx][(p + 1) % n]}
            for sym in target_symbols:
                if sym in window:
                    vis[sym] += weights[reel_idx][p] / total
        out[reel_idx] = vis
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true", help="write redistributed weights to mode_*/weights.json")
    p.add_argument("--verify", action="store_true", help="verify per-reel marginals byte-identical pre/post")
    p.add_argument("--modes", nargs="+", type=int, default=list(_MODES), help="modes to apply (default: all 4)")
    args = p.parse_args()

    print("=" * 80)
    print("M37 RTP-neutral Blank redistribution (Mechanism B per §15)")
    print("=" * 80)
    print()

    strips_doc = json.loads(_STRIPS.read_bytes().decode("utf-8"))
    strips = strips_doc["reels"]

    target_symbols_per_reel = {
        0: ["high7", "wild", "1bar", "2bar", "3bar", "7bar"],   # R1
        1: ["grand", "high7", "mini", "minor", "major", "1bar", "2bar", "3bar", "7bar"],  # R2
        2: ["high7", "wild", "1bar", "2bar", "3bar", "7bar"],   # R3
    }

    for mode in args.modes:
        wpath = _ROOT / "slot_designer" / "weights" / "M37" / f"mode_{mode}" / "weights.json"
        wdoc = json.loads(wpath.read_bytes().decode("utf-8"))
        old_weights = wdoc["weights"]

        # Pre-state
        pre_marginals = _compute_marginals(old_weights, strips)
        all_targets = sorted(set().union(*target_symbols_per_reel.values()))
        pre_vis = _compute_window_visibility(old_weights, strips, all_targets)

        # Apply redistribution
        new_weights = redistribute_one_mode(strips, old_weights, mode)
        post_marginals = _compute_marginals(new_weights, strips)
        post_vis = _compute_window_visibility(new_weights, strips, all_targets)

        # Display
        print(f"--- Mode {mode} (ratio T1:T2:T3:T4 = {':'.join(map(str, MODE_RATIOS[mode]))}) ---")
        print()
        # Marginal preservation check
        if args.verify:
            for ri in range(len(strips)):
                for sym in pre_marginals[ri]:
                    pre = pre_marginals[ri][sym]
                    post = post_marginals[ri].get(sym, 0)
                    if abs(pre - post) > 1e-9:
                        print(f"  MARGINAL DRIFT R{ri+1} {sym}: pre {pre*100:.6f}% vs post {post*100:.6f}%")
                        return 1
            print(f"  Marginals byte-identical pre/post ✓")
            print()

        # Window visibility lift (per reel target symbols)
        for ri in range(len(strips)):
            print(f"  R{ri+1} window visibility (top → mid-pay):")
            for sym in target_symbols_per_reel[ri]:
                pre = pre_vis[ri].get(sym, 0)
                post = post_vis[ri].get(sym, 0)
                delta = (post - pre) * 100
                arrow = "↑" if delta > 0.5 else ("↓" if delta < -0.5 else "≈")
                print(f"    {sym:>6s}: {pre*100:6.2f}% → {post*100:6.2f}%  ({delta:+5.2f}pp) {arrow}")
            print()

        # Blank weight ratio check (BLANK-RATIO-CAP)
        for ri in range(len(strips)):
            blank_weights = [new_weights[ri][p] for p, sym in enumerate(strips[ri]) if sym == "blank"]
            if not blank_weights:
                continue
            ratio = max(blank_weights) / min(blank_weights)
            print(f"  R{ri+1} blank weight max/min ratio: {ratio:.2f}x")
        print()

        if args.write:
            # IDEMPOTENT: skip write if weights already byte-identical to redistribute output
            # (prevents md5 churn when script run repeatedly)
            if old_weights == new_weights:
                print(f"  weights already redistributed (byte-identical) — skip write to preserve md5")
            else:
                wdoc["weights"] = new_weights
                # REPLACE _notes (not append) to keep file content stable across re-runs
                # Filter existing notes: keep non-redistribute lines, then add the redistribute marker
                redistribute_marker = "M37 mode {} — RTP-neutral Blank redistribution".format(mode)
                preserved_notes = [n for n in wdoc.get("_notes", []) if redistribute_marker not in n
                                    and "ratio T1:T2:T3:T4" not in n
                                    and "marginals byte-identical pre/post" not in n]
                wdoc["_notes"] = preserved_notes + [
                    f"M37 mode {mode} — RTP-neutral Blank redistribution applied (mechanism B per §15).",
                    f"  ratio T1:T2:T3:T4 = {':'.join(map(str, MODE_RATIOS[mode]))}",
                    f"  marginals byte-identical pre/post; only Blank position weights changed.",
                ]
                wpath.write_text(json.dumps(wdoc, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"  wrote → {wpath}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
