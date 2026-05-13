"""M15 v11 focused random sweep — lock h7/dd close to v9, vary cherry/bars only.

Key insight: v9 already passes 20+ bucket targets. Total RTP must be ~94-96pp =
base ~43-45 + feature ~51. If we vary h7/dd much, base RTP swings widely. To preserve
the 20+ bucket targets AND total RTP, KEEP h7/dd close to v9 and only redistribute
the cherry/bars to push ge1_lt5 down without breaking other things.
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

from m15_v11_design import (
    evaluate, make_margs, check_hardlines, print_full, print_brief,
)


def sample_candidate(rng, h7_jitter=0.02, dd_jitter=0.015):
    """v9 reference:
       R1: blank=50.25, 1bar=13.81, 2bar=13.53, 3bar=8.81, h7=5.00, cherry=5.00, dd=3.20, jp=0.40
       R2: blank=50.28, 1bar=12.82, 2bar=12.49, 3bar=7.09, h7=8.21, cherry=5.01, dd=3.70, jp=0.40
       R3: blank=52.07, 1bar=14.80, 2bar=14.49, 3bar=9.52, h7=4.00, cherry=2.50, dd=1.40, td=1.10, jp=0.10
    """
    # Cherry per reel
    c_R1 = rng.uniform(0.0, 0.12)
    c_R2 = rng.uniform(0.0, 0.08)
    c_R3 = rng.uniform(0.0, 0.04)

    # Bars: per-reel TOTAL bar density
    def sample_bars(reel_idx):
        # R1 needs LOTS of non-blank: bars [0.15, 0.50]
        # R2/R3 need [0.10, 0.40]
        if reel_idx == 0:
            bt = rng.uniform(0.20, 0.50)
        else:
            bt = rng.uniform(0.15, 0.40)
        # 1bar dominant typically
        s1 = rng.uniform(0.35, 0.65)
        s2 = rng.uniform(0.20, 0.45)
        s3 = max(0.05, 1 - s1 - s2)
        s_total = s1 + s2 + s3
        return bt * s1 / s_total, bt * s2 / s_total, bt * s3 / s_total

    b1_1, b2_1, b3_1 = sample_bars(0)
    b1_2, b2_2, b3_2 = sample_bars(1)
    b1_3, b2_3, b3_3 = sample_bars(2)

    # h7: jitter around v9
    h7_R1 = max(0.005, 0.05 + rng.uniform(-h7_jitter, h7_jitter))
    h7_R2 = max(0.005, 0.082 + rng.uniform(-h7_jitter, h7_jitter))
    h7_R3 = max(0.005, 0.04 + rng.uniform(-h7_jitter, h7_jitter))

    # dd: jitter around v9
    dd_R1 = max(0.005, 0.032 + rng.uniform(-dd_jitter, dd_jitter))
    dd_R2 = max(0.005, 0.037 + rng.uniform(-dd_jitter, dd_jitter))
    dd_R3 = max(0.005, 0.014 + rng.uniform(-dd_jitter, dd_jitter))

    # jackpot fixed
    jp_R1 = 0.004
    jp_R2 = 0.004
    jp_R3 = 0.001

    # topdollar locked
    td_R3 = 0.011

    R1 = {
        'cherry': c_R1, '1bar': b1_1, '2bar': b2_1, '3bar': b3_1,
        'high7': h7_R1, 'doublediamond': dd_R1, 'jackpot': jp_R1,
    }
    R2 = {
        'cherry': c_R2, '1bar': b1_2, '2bar': b2_2, '3bar': b3_2,
        'high7': h7_R2, 'doublediamond': dd_R2, 'jackpot': jp_R2,
    }
    R3 = {
        'cherry': c_R3, '1bar': b1_3, '2bar': b2_3, '3bar': b3_3,
        'high7': h7_R3, 'doublediamond': dd_R3, 'topdollar': td_R3, 'jackpot': jp_R3,
    }

    # Check non-blank doesn't exceed certain limit per reel
    nb1 = sum(R1.values())
    nb2 = sum(R2.values())
    nb3 = sum(R3.values())
    # R1 blank must be [30, 40] -> nb1 in [60, 70]
    if not (0.60 <= nb1 <= 0.70):
        return None
    # R2/R3 blank in [40, 65] reasonable -> nb in [35, 60]
    if not (0.35 <= nb2 <= 0.60):
        return None
    if not (0.35 <= nb3 <= 0.60):
        return None

    R1['blank'] = 1 - nb1
    R2['blank'] = 1 - nb2
    R3['blank'] = 1 - nb3

    return [
        {k: v for k, v in m.items() if v > 0}
        for m in (R1, R2, R3)
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=100000)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--show_best', type=int, default=20)
    args = p.parse_args()

    rng = random.Random(args.seed)
    all_pass = []
    near_pass = []
    fail_counts = {}
    total = 0
    skipped = 0
    for i in range(args.n):
        margs = sample_candidate(rng)
        if margs is None:
            skipped += 1
            continue
        # Normalize each reel
        margs = [{k: v / sum(m.values()) for k, v in m.items()} for m in margs]
        total += 1
        r = evaluate(margs)
        items = check_hardlines(r, margs)
        n_fail = sum(1 for it in items if not it[3])
        if n_fail == 0:
            all_pass.append(('rs2_' + str(i), r, margs, items))
        elif n_fail <= 2:
            near_pass.append((n_fail, 'rs2_' + str(i), r, margs, items))
        for label, val, target, ok in items:
            if not ok:
                fail_counts[label] = fail_counts.get(label, 0) + 1

    print(f'Sampled {total} feasible / {args.n} total / {skipped} skipped')
    print(f'PASS (all hardlines): {len(all_pass)}')
    print(f'NEAR PASS (1-2 fails): {len(near_pass)}')
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
        print(f'=== NEAR-PASS CANDIDATES (top {args.show_best}, 1-2 fails) ===')
        near_pass.sort(key=lambda x: x[0])
        for nf, name, r, margs, items in near_pass[:args.show_best]:
            print_full(name, r, margs, items)
            print()


if __name__ == '__main__':
    main()
