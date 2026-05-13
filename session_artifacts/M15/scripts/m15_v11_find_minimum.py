"""Find the minimum session ge1_lt5 across the feasible space.

Goal: determine if ge1_lt5 ∈ [10, 12] is even POSSIBLE alongside other hardlines.

We search: vary all marginals widely; for each candidate, compute session ge1_lt5
and ALL other hardlines. We log the minimum ge1_lt5 conditional on:
  (a) all other hardlines PASS (excl. ge1_lt5) → does any pass exist?
  (b) hit_session + total_rtp + R1_blank pass (relaxed 20+ bucket targets)
  (c) hit_session pass alone (loosest)
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
    evaluate, make_margs, check_hardlines, print_full,
)


def sample_wide(rng):
    """Wide sampling — explore the whole space."""
    c_R1 = rng.uniform(0.0, 0.15)
    c_R2 = rng.uniform(0.0, 0.10)
    c_R3 = rng.uniform(0.0, 0.06)

    b1_R1 = rng.uniform(0.05, 0.40)
    b1_R2 = rng.uniform(0.05, 0.35)
    b1_R3 = rng.uniform(0.05, 0.35)
    b2_R1 = rng.uniform(0.0, 0.20)
    b2_R2 = rng.uniform(0.0, 0.20)
    b2_R3 = rng.uniform(0.0, 0.20)
    b3_R1 = rng.uniform(0.0, 0.15)
    b3_R2 = rng.uniform(0.0, 0.15)
    b3_R3 = rng.uniform(0.0, 0.15)

    h7_R1 = rng.uniform(0.0, 0.20)
    h7_R2 = rng.uniform(0.0, 0.20)
    h7_R3 = rng.uniform(0.0, 0.15)
    dd_R1 = rng.uniform(0.0, 0.08)
    dd_R2 = rng.uniform(0.0, 0.08)
    dd_R3 = rng.uniform(0.0, 0.04)

    jp_R1 = 0.004
    jp_R2 = 0.004
    jp_R3 = 0.001
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
    if not (0.60 <= nb1 <= 0.70):
        return None
    if not (0.35 <= nb2 <= 0.65):
        return None
    if not (0.35 <= nb3 <= 0.65):
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
    p.add_argument('--n', type=int, default=500000)
    p.add_argument('--seed', type=int, default=42)
    args = p.parse_args()

    rng = random.Random(args.seed)
    total = 0
    feasible = 0
    best_min_g15 = float('inf')
    best_min_g15_data = None

    # Track: candidates where everything else passes
    min_g15_others_pass = float('inf')
    min_g15_others_pass_data = None

    # Track: min g15 given hit/total/R1 pass
    min_g15_basic_pass = float('inf')
    min_g15_basic_pass_data = None

    # All g15 distribution sample (last 100 pass cases)
    g15_when_hit_pass = []

    for i in range(args.n):
        margs = sample_wide(rng)
        if margs is None:
            total += 1
            continue
        margs = [{k: v / sum(m.values()) for k, v in m.items()} for m in margs]
        total += 1
        feasible += 1
        r = evaluate(margs)
        items = check_hardlines(r, margs)

        g15 = r['session_bucket'].get('ge1_lt5', 0)

        # Track absolute min g15
        if g15 < best_min_g15:
            best_min_g15 = g15
            best_min_g15_data = (r, margs, items)

        # Check basic 3: hit, total, R1
        basic_pass = (
            15 <= r['hit_session'] <= 18 and
            94 <= r['total_rtp'] <= 96 and
            30 <= margs[0]['blank'] * 100 <= 40
        )
        if basic_pass and g15 < min_g15_basic_pass:
            min_g15_basic_pass = g15
            min_g15_basic_pass_data = (r, margs, items)

        if basic_pass:
            g15_when_hit_pass.append(g15)

        # Check all others (excl g15)
        non_g15_pass = all(
            (label == 'ge1_lt5' or ok) for label, val, target, ok in items
        )
        if non_g15_pass and g15 < min_g15_others_pass:
            min_g15_others_pass = g15
            min_g15_others_pass_data = (r, margs, items)

    print(f'Sampled {feasible} feasible / {total} total')
    print()
    print(f'Min session ge1_lt5 (across all feasible): {best_min_g15:.3f}pp')
    if best_min_g15_data:
        r, margs, items = best_min_g15_data
        print(f'  This candidate: hit={r["hit_session"]:.2f}, RTP={r["total_rtp"]:.2f}, R1b={margs[0]["blank"]*100:.2f}')
    print()
    print(f'Min ge1_lt5 given basic 3 pass (hit+total+R1blank): {min_g15_basic_pass:.3f}pp')
    if min_g15_basic_pass_data:
        r, margs, items = min_g15_basic_pass_data
        print(f'  This candidate:')
        print_full('min_g15_basic', r, margs, items)
    print()
    print(f'Min ge1_lt5 given ALL non-g15 hardlines pass: {min_g15_others_pass:.3f}pp')
    if min_g15_others_pass_data:
        r, margs, items = min_g15_others_pass_data
        print(f'  This candidate:')
        print_full('min_g15_others_pass', r, margs, items)
    print()
    print(f'Distribution of g15 when basic-3 pass ({len(g15_when_hit_pass)} samples):')
    if g15_when_hit_pass:
        sorted_g15 = sorted(g15_when_hit_pass)
        n = len(sorted_g15)
        print(f'  min={sorted_g15[0]:.3f}, p5={sorted_g15[n//20]:.3f}, p50={sorted_g15[n//2]:.3f}, p95={sorted_g15[19*n//20]:.3f}, max={sorted_g15[-1]:.3f}')


if __name__ == '__main__':
    main()
