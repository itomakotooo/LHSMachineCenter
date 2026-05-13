"""M15 v12 — targeted sweep around v9 marginals.

Starting hypothesis: v9 already satisfies all 20+ bands (under v4 widening).
What v9 fails: R1 blank, hit, g15, sum_1_20.

Strategy:
  1. Lower R1 blank by REDISTRIBUTING: R1 non-blank ↑, R2/R3 non-blank ↓.
  2. Lower cherry uniformly (drops cherry-1 P → g15 ↓, hit ↓).
  3. Lower bars (drops bar_mixed P → g15 ↓, hit ↓).
  4. v4's widened 20+ tolerance gives slack to keep total RTP ∈ [94, 96]
     even with reduced cherry/bar contributions.

Parameters per reel directly (no Dirichlet — controlled by direct ranges).
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


def sample(rng):
    """Direct per-reel marginal sampling around v9."""
    # cherry per reel — sweep low so cherry-1 P controllable
    c_R1 = rng.uniform(0.005, 0.05)
    c_R2 = rng.uniform(0.005, 0.05)
    c_R3 = rng.uniform(0.0, 0.035)

    # 1bar per reel — sweep
    b1_R1 = rng.uniform(0.04, 0.22)
    b1_R2 = rng.uniform(0.03, 0.20)
    b1_R3 = rng.uniform(0.03, 0.20)

    # 2bar per reel
    b2_R1 = rng.uniform(0.04, 0.22)
    b2_R2 = rng.uniform(0.04, 0.22)
    b2_R3 = rng.uniform(0.04, 0.22)

    # 3bar per reel — slightly lower (per pyramid §1)
    b3_R1 = rng.uniform(0.02, 0.16)
    b3_R2 = rng.uniform(0.02, 0.14)
    b3_R3 = rng.uniform(0.02, 0.16)

    # h7 per reel — moderate
    h7_R1 = rng.uniform(0.02, 0.18)
    h7_R2 = rng.uniform(0.02, 0.16)
    h7_R3 = rng.uniform(0.01, 0.10)

    # dd per reel — moderate
    dd_R1 = rng.uniform(0.015, 0.12)
    dd_R2 = rng.uniform(0.01, 0.10)
    dd_R3 = rng.uniform(0.005, 0.05)

    jp_R1 = rng.uniform(0.001, 0.005)
    jp_R2 = rng.uniform(0.001, 0.005)
    jp_R3 = rng.uniform(0.0005, 0.003)
    td_R3 = 0.011

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

    nb1 = sum(R1.values())
    nb2 = sum(R2.values())
    nb3 = sum(R3.values())

    if not (0.60 <= nb1 <= 0.70):  # R1 blank [30, 40]
        return None
    if not (0.30 <= nb2 <= 0.70):
        return None
    if not (0.30 <= nb3 <= 0.70):
        return None
    # §12: R1 non-blank >= R2/R3 non-blank
    if nb1 < nb2 - 0.005 or nb1 < nb3 - 0.005:
        return None

    return [
        {k: v for k, v in m.items() if v > 0}
        for m in (R1, R2, R3)
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=2000000)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--show_best', type=int, default=10)
    args = p.parse_args()

    rng = random.Random(args.seed)
    all_pass = []
    g15_only_fail = []
    near_pass = []
    fail_counts = {}
    total = 0
    skipped = 0
    min_g15_record = None
    min_g15 = float('inf')

    for i in range(args.n):
        if i % 200000 == 0 and i > 0:
            print(f'  ... {i}/{args.n}, feasible {total}, PASS {len(all_pass)}, '
                  f'g15-only-fail {len(g15_only_fail)}, near {len(near_pass)}',
                  flush=True)
        margs_raw = sample(rng)
        if margs_raw is None:
            skipped += 1
            continue
        margs = make_margs(margs_raw[0], margs_raw[1], margs_raw[2])
        total += 1
        r = evaluate(margs)
        items = check_hardlines(r, margs)
        fails = [it for it in items if not it[3]]
        n_fail = len(fails)
        g15 = r['session_bucket'].get('ge1_lt5', 0)
        if g15 < min_g15:
            min_g15 = g15
            min_g15_record = (n_fail, 'min_g15_' + str(i), r, margs, items)

        if n_fail == 0:
            all_pass.append(('rs_' + str(i), r, margs, items))
        elif n_fail <= 2:
            near_pass.append((n_fail, 'rs_' + str(i), r, margs, items))

        if len(fails) == 1 and fails[0][0] == 'ge1_lt5':
            g15_only_fail.append((g15, 'rs_' + str(i), r, margs, items))

        for label, val, target, ok in items:
            if not ok:
                fail_counts[label] = fail_counts.get(label, 0) + 1

    print()
    print(f'Sampled {total} feasible / {args.n} / {skipped} skipped')
    print(f'PASS: {len(all_pass)}, NEAR-PASS (1-2 fails): {len(near_pass)}')
    print(f'g15-only-fail: {len(g15_only_fail)}')
    if g15_only_fail:
        g15_only_fail.sort()
        print(f'  Min g15 with ALL OTHERS PASS: {g15_only_fail[0][0]:.3f}pp')
        print(f'  Top {args.show_best} smallest g15-only-fail:')
        for g15, name, r, margs, items in g15_only_fail[:args.show_best]:
            print_full(name, r, margs, items)
            print()

    if all_pass:
        print(f'=== PASSING (top {args.show_best}) ===')
        for name, r, margs, items in all_pass[:args.show_best]:
            print_full(name, r, margs, items)
            print()
    elif near_pass:
        print(f'=== NEAR-PASS (top {args.show_best}, fewest fails) ===')
        near_pass.sort(key=lambda x: x[0])
        for nf, name, r, margs, items in near_pass[:args.show_best]:
            print_full(name, r, margs, items)
            print()

    print(f'Fail by category:')
    if total > 0:
        for label, c in sorted(fail_counts.items(), key=lambda x: -x[1]):
            print(f'  {label:18s} {c}/{total} ({100*c/total:.1f}%)')


if __name__ == '__main__':
    main()
