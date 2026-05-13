"""M15 v11 random sweep — find candidates satisfying all session-centric user hardlines.

This is a broad random sweep over per-reel marginals. Goal: find any candidate
passing all 11 user hardline checks (total_rtp, hit_session, R1_blank, ge1_lt5,
sum_1_20, 4x 20+ buckets near v9, 3x jackpot caps).

Strategy:
  - Per-reel marginal sampled uniformly in physically-plausible ranges
  - R1 blank locked [30, 40]
  - R2/R3 blank locked [40, 60]
  - cherry per reel sampled
  - bar densities sampled with structure (b1 > b2 > b3 typical, but flexible)
  - high7 / doublediamond sampled
  - jackpot fixed at small (0.4% R1/R2, 0.1% R3)
  - topdollar R3 = 1.1% (locked by trigger rule)
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
    FEATURE_BUCKET_EV, FEATURE_EV_TOTAL,
)


def sample_reel(rng, reel_idx):
    """Sample a per-reel marginal."""
    # blank
    if reel_idx == 0:  # R1
        blank = rng.uniform(0.30, 0.40)
    else:
        blank = rng.uniform(0.40, 0.55)

    # cherry: per-reel up to 6%
    cherry = rng.uniform(0.0, 0.06)

    # bars: total bar density (1bar+2bar+3bar) per reel sampled
    bar_total = rng.uniform(0.05, 0.35)
    # Split: 1bar share dominant typically
    s1 = rng.uniform(0.4, 0.7)
    s2 = rng.uniform(0.2, min(0.5, 1 - s1))
    s3 = max(0.05, 1 - s1 - s2)
    s_sum = s1 + s2 + s3
    b1 = bar_total * s1 / s_sum
    b2 = bar_total * s2 / s_sum
    b3 = bar_total * s3 / s_sum

    # high7 / doublediamond
    high7 = rng.uniform(0.02, 0.18)
    dd = rng.uniform(0.01, 0.08)

    # jackpot
    if reel_idx == 2:
        jackpot = 0.001
    else:
        jackpot = rng.uniform(0.001, 0.006)

    # topdollar only on R3, fixed
    topdollar = 0.011 if reel_idx == 2 else 0.0

    m = {
        'blank': blank,
        'cherry': cherry,
        '1bar': b1,
        '2bar': b2,
        '3bar': b3,
        'high7': high7,
        'doublediamond': dd,
        'topdollar': topdollar,
        'jackpot': jackpot,
    }
    # Re-normalize to 1 (blank becomes residual)
    nb = sum(v for k, v in m.items() if k != 'blank')
    if nb > 1 - 0.001:
        return None  # infeasible
    m['blank'] = max(0.001, 1 - nb)
    if not (0.30 <= m['blank'] <= 0.55) and reel_idx == 0:
        # Slack: try once more by rescaling
        m['blank'] = blank
        scale = (1 - blank) / nb
        for k in list(m.keys()):
            if k != 'blank':
                m[k] *= scale
    return m


def sample_candidate(rng):
    margs = []
    for i in range(3):
        m = sample_reel(rng, i)
        if m is None:
            return None
        margs.append(m)
    # Make sure topdollar is on R3
    # Renormalize each reel to 1
    out = []
    for m in margs:
        s = sum(m.values())
        out.append({k: v / s for k, v in m.items()})
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=20000)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--show_best', type=int, default=20)
    p.add_argument('--verbose', action='store_true')
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
        # Filter early: check R1 blank in [30,40]
        if not (0.30 <= margs[0]['blank'] <= 0.40):
            continue
        total += 1
        r = evaluate(margs)
        items = check_hardlines(r, margs)
        n_fail = sum(1 for it in items if not it[3])
        if n_fail == 0:
            all_pass.append(('random_' + str(i), r, margs, items))
        elif n_fail <= 2:
            near_pass.append((n_fail, 'random_' + str(i), r, margs, items))
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
