"""M15 v11 mode 1 — heavy random search with structured priors.

Lessons from sweep2 (100% ge1_lt5 fails):
  - With v9-anchored h7/dd and any cherry+bars combo satisfying hit floor 15%, ge1_lt5 ≥ ~18pp.
  - Closed-form bound: hit_session ≥ 15% requires cherry-1 + bar_mixed P ≥ ~11.4% in
    ge1_lt5 (other paths contribute small hit). With those mults (cherry-1=1x,
    bar_mixed=2-4x), ge1_lt5 RTP ≥ ~14pp.

Mathematical floor (closed-form):
  ge1_lt5 = P_cherry_1 + 2*P_bar_mixed_pure + 4*P_bar_mixed_w1wild
  hit_base = P_cherry_1 + P_bar_mixed (all mults) + bar_pures + cherry-2/3 + wild paths + h7
  hit_session = hit_base + trigger

  All hit_in_ge1_lt5 P = P_cherry_1 + P_bar_mixed_2x + P_bar_mixed_4x = P_in_g15
  hit_session ≥ 15% AND P_in_g15_excl ≤ 2.5% (max possible from g510+g1020+higher) →
  P_in_g15 ≥ 11.4% with trigger 1.1% feature.

  ge1_lt5 RTP = P_cherry_1 * 1 + P_bar_mixed_2x * 2 + P_bar_mixed_4x * 4
              ≥ P_in_g15 * 1 = 11.4pp
  Upper bound by user: 12pp. So band is tight: 10-12 ≥ 11.4.

  Iff we maximize P_cherry_1 (mult 1x) share of P_in_g15. To get P_cherry_1
  close to P_in_g15, we need bar_mixed to be 0 — but then bar_mixed P = 0 too.
  Then P_cherry_1 ≥ 11.4 means cherry P_ch1 ≥ 11.4%, which with 3-reel cherry-1
  formula 3c(1-c)² ≥ 0.114, requires c ≥ 4.4% uniform per reel.

  At c = 4.4% uniform: P_ch2 = 3*0.044²*(1-0.044) = 0.555% → cherry-2 RTP = 2.8pp ge5_lt10
  P_ch3 = 0.044³ = 0.0085% → cherry-3 RTP = 0.13pp ge10_lt20

  bar_mixed = 0 means bars are all-zero OR only one bar type exists on each reel.
  Wait: bar_mixed_pure = prod(b1+b2+b3) - prod(b1) - prod(b2) - prod(b3). This = 0 iff
  for each reel, at most one bar_type has non-zero density (since cross-product cancels).

  Strategy: per-reel only ONE bar type. E.g., R1 = 1bar only, R2 = 1bar only, R3 = 1bar only.
  Then bar1_pure exists, bar_mixed_pure = 0.

  But wait, bar_mixed with WILD substitution: e.g. (1bar, wild, 1bar) — all sides 1bar,
  matches line_3_same with mult 5*wild_product. So pay_id 7 fires not pay_id 8.

  So if all 3 reels only have 1bar, bar_mixed pay_id 8 NEVER fires.
  Then ge1_lt5 = ONLY cherry-1 RTP.

  Try: R1 = 1bar only, R2 = 1bar only, R3 = 1bar only.
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


def sample_candidate(rng):
    """Strategy: each reel has ONE dominant bar type to suppress bar_mixed."""
    # Cherry per reel — vary widely to find sweet spot
    c_R1 = rng.uniform(0.02, 0.10)
    c_R2 = rng.uniform(0.02, 0.08)
    c_R3 = rng.uniform(0.0, 0.05)

    # Bar strategy: each reel has 1bar dominant.
    # R1 1bar high to lift R1 non-blank (R1 blank must be 30-40)
    b1_R1 = rng.uniform(0.18, 0.35)
    b1_R2 = rng.uniform(0.12, 0.28)
    b1_R3 = rng.uniform(0.12, 0.28)
    # b2 small
    b2_R1 = rng.uniform(0.0, 0.08)
    b2_R2 = rng.uniform(0.0, 0.08)
    b2_R3 = rng.uniform(0.0, 0.08)
    # b3 small
    b3_R1 = rng.uniform(0.0, 0.06)
    b3_R2 = rng.uniform(0.0, 0.06)
    b3_R3 = rng.uniform(0.0, 0.06)

    # h7 (drives ge20_lt50 pure + h7+wild)
    h7_R1 = rng.uniform(0.03, 0.15)
    h7_R2 = rng.uniform(0.03, 0.15)
    h7_R3 = rng.uniform(0.02, 0.10)
    # dd
    dd_R1 = rng.uniform(0.01, 0.06)
    dd_R2 = rng.uniform(0.01, 0.06)
    dd_R3 = rng.uniform(0.005, 0.03)

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
    if not (0.605 <= nb1 <= 0.70):  # R1 blank [30, 39.5]
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
    p.add_argument('--n', type=int, default=200000)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--show_best', type=int, default=10)
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
        margs = [{k: v / sum(m.values()) for k, v in m.items()} for m in margs]
        total += 1
        r = evaluate(margs)
        items = check_hardlines(r, margs)
        n_fail = sum(1 for it in items if not it[3])
        if n_fail == 0:
            all_pass.append(('rs3_' + str(i), r, margs, items))
        elif n_fail <= 2:
            near_pass.append((n_fail, 'rs3_' + str(i), r, margs, items))
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
        print(f'=== NEAR-PASS CANDIDATES (top {args.show_best}) ===')
        near_pass.sort(key=lambda x: x[0])
        for nf, name, r, margs, items in near_pass[:args.show_best]:
            print_full(name, r, margs, items)
            print()


if __name__ == '__main__':
    main()
