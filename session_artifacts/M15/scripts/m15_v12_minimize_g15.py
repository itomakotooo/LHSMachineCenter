"""M15 v12 — minimize g15 while satisfying all OTHER hardlines.

If min g15 (under all other hardlines pass) is > 12pp, this is v11's wall:
  - hit ≥ 15% structurally requires cherry-1 + bar_mixed ≥ ~10% (with feature trigger)
  - cherry-1 P ≤ 12% caps cherry hit at 12%
  - non-cherry hit lift requires bars/h7/dd → side-effect of raising g510/g1020
  - But v4 wider tolerance allows higher g510/g1020 → may unlock candidates not seen in v11.

Restrict cherry uniform low + push other hit paths.
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


def sample_g15_focused(rng):
    """Target g15 ≤ 12pp: cherry uniform low + extreme bar asymm (each reel 1 bar type mostly).
    Suppress bar_mixed via asymmetric bar marginals.
    """
    # Cherry per reel — moderate so cherry-1 P can be 7-10%
    c_R1 = rng.uniform(0.015, 0.045)
    c_R2 = rng.uniform(0.015, 0.045)
    c_R3 = rng.uniform(0.005, 0.035)

    # Each reel mostly one bar type (cuts bar_mixed orderings)
    b1_R1 = rng.uniform(0.10, 0.30)  # R1 dominant 1bar
    b2_R1 = rng.uniform(0.00, 0.04)
    b3_R1 = rng.uniform(0.00, 0.04)

    b1_R2 = rng.uniform(0.00, 0.04)
    b2_R2 = rng.uniform(0.10, 0.28)  # R2 dominant 2bar
    b3_R2 = rng.uniform(0.00, 0.04)

    b1_R3 = rng.uniform(0.00, 0.04)
    b2_R3 = rng.uniform(0.00, 0.04)
    b3_R3 = rng.uniform(0.08, 0.25)  # R3 dominant 3bar

    # h7 per reel
    h7_R1 = rng.uniform(0.05, 0.25)
    h7_R2 = rng.uniform(0.04, 0.22)
    h7_R3 = rng.uniform(0.02, 0.15)

    # dd per reel
    dd_R1 = rng.uniform(0.03, 0.15)
    dd_R2 = rng.uniform(0.02, 0.12)
    dd_R3 = rng.uniform(0.005, 0.06)

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
    if not (0.25 <= nb3 <= 0.70):
        return None
    # §12 R1 winners-friendly: R1 blank ≤ R2 blank, R1 blank ≤ R3 blank
    # i.e. R1 non-blank ≥ R2 non-blank AND ≥ R3 non-blank
    if nb1 < nb2 - 0.005 or nb1 < nb3 - 0.005:
        return None

    return [
        {k: v for k, v in m.items() if v > 0}
        for m in (R1, R2, R3)
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=500000)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--show_best', type=int, default=10)
    args = p.parse_args()

    rng = random.Random(args.seed)
    all_pass = []
    near_pass = []
    # Track candidates that pass everything EXCEPT g15
    g15_only_fail = []  # those with only g15 fail
    fail_counts = {}
    total = 0
    skipped = 0
    min_g15 = float('inf')
    min_g15_record = None

    for i in range(args.n):
        if i % 100000 == 0 and i > 0:
            print(f'  ... {i}/{args.n}, feasible {total}, PASS {len(all_pass)}, '
                  f'g15-only-fail {len(g15_only_fail)}, min_g15 {min_g15:.2f}',
                  flush=True)
        margs_raw = sample_g15_focused(rng)
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
            other_fails = [it for it in fails if it[0] != 'ge1_lt5']
            min_g15 = g15
            min_g15_record = (n_fail, len(other_fails), 'min_g15', r, margs, items)
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
    print(f'g15-only-fail (all others pass): {len(g15_only_fail)}')
    if g15_only_fail:
        g15_only_fail.sort()
        print(f'  Min g15 with ALL OTHERS PASS: {g15_only_fail[0][0]:.3f}pp')
        print(f'  Top {args.show_best} smallest g15:')
        for g15, name, r, margs, items in g15_only_fail[:args.show_best]:
            print_full(name, r, margs, items)
            print()

    if all_pass:
        print(f'=== PASSING (top {args.show_best}) ===')
        for name, r, margs, items in all_pass[:args.show_best]:
            print_full(name, r, margs, items)
            print()

    print()
    print(f'Fail by category:')
    for label, c in sorted(fail_counts.items(), key=lambda x: -x[1]):
        print(f'  {label:18s} {c}/{total} ({100*c/total:.1f}%)')


if __name__ == '__main__':
    main()
