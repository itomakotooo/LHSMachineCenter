"""M15 v12 mode 1 — random sweep under v4 hardlines.

Searches the marginal space with constraints:
  - R1 blank ∈ [30, 40]%
  - R2/R3 blank > R1 blank (per §12)
  - Jackpot ≤ 0.6% per reel
  - Topdollar R3 = 0.011 (to hit feature trigger 1.127% ≈ v9 — feature shape lock)

Records candidates that PASS all v4 hardlines or are near-pass (≤2 fails).
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from m15_v12_design import (
    evaluate, make_margs, check_hardlines, print_full, print_brief,
)


def sample_candidate(rng):
    """Sample reel marginals satisfying structural constraints.

    Strategy: directly target R1 non-blank ∈ [0.60, 0.70].
    Use parametrized split among symbols.
    """
    # R1 non-blank target
    R1_total = rng.uniform(0.605, 0.695)  # blank ∈ (0.305, 0.395)
    R2_total = rng.uniform(0.40, R1_total - 0.001)  # R2 non-blank LESS than R1 → R2 blank > R1 blank
    R3_total = rng.uniform(0.35, R1_total - 0.001)  # R3 blank > R1 blank

    # Cherry: small fraction of R1/R2 non-blank
    c_R1 = rng.uniform(0.015, 0.06)
    c_R2 = rng.uniform(0.015, 0.06)
    c_R3 = rng.uniform(0.0, 0.04)

    # Allocate R1 non-cherry-non-jp budget across {bars, h7, dd}
    jp_R1 = rng.uniform(0.001, 0.005)
    R1_remain = R1_total - c_R1 - jp_R1
    if R1_remain < 0.10:
        return None
    # Random Dirichlet-ish split: dd_frac ∈ [0.05, 0.25], h7_frac ∈ [0.05, 0.30], rest = bars
    dd_frac_R1 = rng.uniform(0.05, 0.30)
    h7_frac_R1 = rng.uniform(0.05, 0.40)
    bar_frac_R1 = 1.0 - dd_frac_R1 - h7_frac_R1
    if bar_frac_R1 < 0.30:
        return None
    dd_R1 = R1_remain * dd_frac_R1
    h7_R1 = R1_remain * h7_frac_R1
    bars_R1 = R1_remain * bar_frac_R1
    # Split bars across 1/2/3 (random)
    bar_split_R1 = [rng.random(), rng.random(), rng.random()]
    bs = sum(bar_split_R1)
    bar_split_R1 = [x / bs for x in bar_split_R1]
    b1_R1 = bars_R1 * bar_split_R1[0]
    b2_R1 = bars_R1 * bar_split_R1[1]
    b3_R1 = bars_R1 * bar_split_R1[2]

    # R2 similar
    jp_R2 = rng.uniform(0.001, 0.005)
    R2_remain = R2_total - c_R2 - jp_R2
    if R2_remain < 0.08:
        return None
    dd_frac_R2 = rng.uniform(0.05, 0.25)
    h7_frac_R2 = rng.uniform(0.05, 0.40)
    bar_frac_R2 = 1.0 - dd_frac_R2 - h7_frac_R2
    if bar_frac_R2 < 0.30:
        return None
    dd_R2 = R2_remain * dd_frac_R2
    h7_R2 = R2_remain * h7_frac_R2
    bars_R2 = R2_remain * bar_frac_R2
    bar_split_R2 = [rng.random(), rng.random(), rng.random()]
    bs = sum(bar_split_R2)
    bar_split_R2 = [x / bs for x in bar_split_R2]
    b1_R2 = bars_R2 * bar_split_R2[0]
    b2_R2 = bars_R2 * bar_split_R2[1]
    b3_R2 = bars_R2 * bar_split_R2[2]

    # R3 similar but with topdollar 0.011 locked
    td_R3 = 0.011
    jp_R3 = rng.uniform(0.0005, 0.003)
    R3_remain = R3_total - c_R3 - jp_R3 - td_R3
    if R3_remain < 0.08:
        return None
    dd_frac_R3 = rng.uniform(0.02, 0.20)
    h7_frac_R3 = rng.uniform(0.03, 0.35)
    bar_frac_R3 = 1.0 - dd_frac_R3 - h7_frac_R3
    if bar_frac_R3 < 0.30:
        return None
    dd_R3 = R3_remain * dd_frac_R3
    h7_R3 = R3_remain * h7_frac_R3
    bars_R3 = R3_remain * bar_frac_R3
    bar_split_R3 = [rng.random(), rng.random(), rng.random()]
    bs = sum(bar_split_R3)
    bar_split_R3 = [x / bs for x in bar_split_R3]
    b1_R3 = bars_R3 * bar_split_R3[0]
    b2_R3 = bars_R3 * bar_split_R3[1]
    b3_R3 = bars_R3 * bar_split_R3[2]

    R1 = {
        'cherry': c_R1, '1bar': b1_R1, '2bar': b2_R1, '3bar': b3_R1,
        'high7': h7_R1, 'doublediamond': dd_R1, 'jackpot': jp_R1,
    }
    R2 = {
        'cherry': c_R2, '1bar': b1_R2, '2bar': b2_R2, '3bar': b3_R2,
        'high7': h7_R2, 'doublediamond': dd_R2, 'jackpot': jp_R2,
    }
    R3 = {
        'cherry': c_R3, '1bar': b1_R3, '2bar': b2_R3, '3bar': b3_R3,
        'high7': h7_R3, 'doublediamond': dd_R3, 'topdollar': td_R3, 'jackpot': jp_R3,
    }

    return [
        {k: v for k, v in m.items() if v > 0}
        for m in (R1, R2, R3)
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=500000)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--show_best', type=int, default=10)
    p.add_argument('--max_fail_to_keep', type=int, default=2)
    args = p.parse_args()

    rng = random.Random(args.seed)
    all_pass = []
    near_pass = []
    fail_counts = {}
    total = 0
    skipped = 0
    for i in range(args.n):
        if i % 50000 == 0 and i > 0:
            print(f'  ... sampled {i}/{args.n}, feasible {total}, PASS {len(all_pass)}', flush=True)
        margs_raw = sample_candidate(rng)
        if margs_raw is None:
            skipped += 1
            continue
        margs = make_margs(margs_raw[0], margs_raw[1], margs_raw[2])
        total += 1
        r = evaluate(margs)
        items = check_hardlines(r, margs)
        n_fail = sum(1 for it in items if not it[3])
        if n_fail == 0:
            all_pass.append(('rs_' + str(i), r, margs, items))
        elif n_fail <= args.max_fail_to_keep:
            near_pass.append((n_fail, 'rs_' + str(i), r, margs, items))
        for label, val, target, ok in items:
            if not ok:
                fail_counts[label] = fail_counts.get(label, 0) + 1

    print()
    print(f'Sampled {total} feasible / {args.n} total / {skipped} structurally skipped')
    print(f'PASS (all hardlines): {len(all_pass)}')
    print(f'NEAR PASS (1-{args.max_fail_to_keep} fails): {len(near_pass)}')
    if total > 0:
        print(f'Fail count by category:')
        for label, c in sorted(fail_counts.items(), key=lambda x: -x[1]):
            print(f'  {label:18s} fail in {c}/{total} ({100*c/total:.1f}%)')
    print()

    if all_pass:
        print(f'=== PASSING CANDIDATES (top {args.show_best}) ===')
        for name, r, margs, items in all_pass[:args.show_best]:
            print_full(name, r, margs, items)
            print()
    elif near_pass:
        print(f'=== NEAR-PASS CANDIDATES (top {args.show_best}) ===')
        near_pass.sort(key=lambda x: x[0])
        for nf, name, r, margs, items in near_pass[:args.show_best]:
            print_full(name, r, margs, items)
            print()


if __name__ == '__main__':
    main()
