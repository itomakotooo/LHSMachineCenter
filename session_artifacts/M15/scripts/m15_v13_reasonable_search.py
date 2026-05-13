"""M15 v13 mode 1 — search restricted to "reasonable-looking" configs.

NOT adding new hardlines (user 2026-05-11 explicit: only 14 stated hardlines).
Just sampling from the philosophy-clean subspace as DIRECTION:

Reasonable sampling ranges (NOT caps, just sampler priors):
  high7 per reel ∈ [4, 12]% (classical seven density, not 0 not 19%)
  Each bar tier per reel ≥ 2% (visible on every reel — no symbol void)
  cherry per reel ∈ [2, 8]%
  doublediamond per reel ∈ [1, 5]%
  jp per reel ∈ [0.2, 0.6]% (user hardline B5)
  td R3 ∈ [0.5, 1.5]% (feature trigger)

Then check ALL 14 USER_HARDLINES.md hardlines:
  hit_session ∈ [15, 18]
  total_rtp ∈ [94, 96]
  R1 blank ∈ [30, 40]
  ge1_lt5 ∈ [10, 12]
  sum_1_20 ∈ [28, 32]
  ge20_lt50 ∈ [22, 32]
  ge50_lt100 ∈ [17, 27]
  ge100_lt200 ∈ [4, 14]
  ge200_lt500 ∈ [0, 7.3]
  jp ≤ 0.6 per reel

Report: any all-pass? Best n_fail?
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path('C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

M15_DIR = _ROOT / 'slot_designer' / 'machines' / 'M15'

# Load engine ONCE
engine, _ = load_engine(
    M15_DIR / 'spec.json',
    M15_DIR / 'weights' / 'mode_1' / 'weights.json',
    strips_path=M15_DIR / 'reel_strips.json',
)
EV = engine.evaluator

# Load feature_params (LOCKED v9, byte-equal)
fp = json.loads((M15_DIR / 'weights' / 'mode_1' / 'weights.json').read_text(encoding='utf-8'))['feature_params']

# Precompute feature bucket EV (constant — feature_params locked)
dist = _round_payout_distribution(tuple(fp['x_count_weights']),
                                   tuple(fp['y_count_weights']),
                                   tuple(fp['x_value_weights']),
                                   tuple(fp['y_value_weights']))
p_accept = sum(p for r, p in dist if r >= fp['accept_threshold'])
accept = [(r, p) for r, p in dist if r >= fp['accept_threshold']]
final = defaultdict(float)
for ri in range(1, fp['max_rounds']):
    b = ((1 - p_accept) ** (ri - 1)) * p_accept
    for r, p in accept:
        final[r] += b * (p / p_accept) if p_accept > 0 else 0
b = (1 - p_accept) ** (fp['max_rounds'] - 1)
for r, p in dist:
    final[r] += b * p
edges = [(5000, 'ge5000'), (1000, 'ge1000_lt5000'),
         (500, 'ge500_lt1000'), (200, 'ge200_lt500'),
         (100, 'ge100_lt200'), (50, 'ge50_lt100'),
         (20, 'ge20_lt50'), (10, 'ge10_lt20'),
         (5, 'ge5_lt10'), (1, 'ge1_lt5'), (0, 'gt0_lt1')]
def buc(r):
    if r <= 0:
        return None
    for e, k in edges:
        if r >= e:
            return k
    return None
FEAT_BUC = defaultdict(float)
for r, p in final.items():
    bb = buc(r)
    if bb:
        FEAT_BUC[bb] += r * p
FEAT_TOTAL = sum(FEAT_BUC.values())


def normalize(d):
    s = sum(d.values())
    return {k: v / s for k, v in d.items() if v > 0}


def sample_reasonable(rng):
    """Sample one reasonable-looking config."""
    # cherry per reel — independent
    c_R1 = rng.uniform(0.02, 0.08)
    c_R2 = rng.uniform(0.02, 0.08)
    c_R3 = rng.uniform(0.02, 0.06)
    # bar densities — each tier visible (≥ 2%), classical pyramid b1≥b2≥b3 within reel optionally
    b1_R1 = rng.uniform(0.04, 0.20)
    b2_R1 = rng.uniform(0.03, 0.18)
    b3_R1 = rng.uniform(0.02, 0.12)
    b1_R2 = rng.uniform(0.02, 0.18)
    b2_R2 = rng.uniform(0.03, 0.18)
    b3_R2 = rng.uniform(0.02, 0.12)
    b1_R3 = rng.uniform(0.02, 0.15)
    b2_R3 = rng.uniform(0.02, 0.15)
    b3_R3 = rng.uniform(0.02, 0.10)
    # high7 — classical range (not 0, not 20)
    h7_R1 = rng.uniform(0.04, 0.12)
    h7_R2 = rng.uniform(0.04, 0.12)
    h7_R3 = rng.uniform(0.02, 0.10)
    # doublediamond (wild) — sparse
    dd_R1 = rng.uniform(0.01, 0.05)
    dd_R2 = rng.uniform(0.01, 0.05)
    dd_R3 = rng.uniform(0.005, 0.04)
    # jackpot — per reel ≤ 0.6 (hardline)
    jp_R1 = rng.uniform(0.001, 0.006)
    jp_R2 = rng.uniform(0.001, 0.006)
    jp_R3 = rng.uniform(0.0005, 0.004)
    td_R3 = rng.uniform(0.008, 0.014)

    R1 = {'cherry': c_R1, '1bar': b1_R1, '2bar': b2_R1, '3bar': b3_R1,
          'high7': h7_R1, 'doublediamond': dd_R1, 'jackpot': jp_R1}
    R2 = {'cherry': c_R2, '1bar': b1_R2, '2bar': b2_R2, '3bar': b3_R2,
          'high7': h7_R2, 'doublediamond': dd_R2, 'jackpot': jp_R2}
    R3 = {'cherry': c_R3, '1bar': b1_R3, '2bar': b2_R3, '3bar': b3_R3,
          'high7': h7_R3, 'doublediamond': dd_R3, 'topdollar': td_R3, 'jackpot': jp_R3}

    # Check non-blank sums ∈ [0.40, 0.70] (R1 blank ∈ [30, 60]) — broad screen
    nb = [sum(R.values()) for R in (R1, R2, R3)]
    if not (0.40 <= nb[0] <= 0.70):
        return None
    if not (0.10 <= nb[1] <= 0.80):
        return None
    if not (0.10 <= nb[2] <= 0.80):
        return None

    # Add blank residual
    for R, n in zip((R1, R2, R3), nb):
        R['blank'] = max(0.001, 1 - n)
    return [normalize(R1), normalize(R2), normalize(R3)]


def evaluate(margs):
    prof = analytic_profile_from_marginals(EV, margs)
    trigger = margs[2].get('topdollar', 0.0)
    base_rtp = prof['rtp_pct']
    base_hit = prof['hit_rate']
    total_rtp = base_rtp + trigger * FEAT_TOTAL * 100
    hit_session = (base_hit + trigger) * 100
    session = {k: v * 100 for k, v in prof['bucket_rtp'].items()}
    for k, ev in FEAT_BUC.items():
        session[k] = session.get(k, 0) + trigger * ev * 100
    return total_rtp, hit_session, margs[0]['blank'] * 100, session


def check14(total_rtp, hit_session, r1_blank, session, margs):
    g15 = session.get('ge1_lt5', 0)
    g510 = session.get('ge5_lt10', 0)
    g1020 = session.get('ge10_lt20', 0)
    sum120 = g15 + g510 + g1020
    fails = []
    if not (94 <= total_rtp <= 96): fails.append(('total_rtp', total_rtp))
    if not (15 <= hit_session <= 18): fails.append(('hit_session', hit_session))
    if not (30 <= r1_blank <= 40): fails.append(('R1_blank', r1_blank))
    if not (10 <= g15 <= 12): fails.append(('ge1_lt5', g15))
    if not (28 <= sum120 <= 32): fails.append(('sum_1_20', sum120))
    g2050 = session.get('ge20_lt50', 0)
    if not (22 <= g2050 <= 32): fails.append(('ge20_lt50', g2050))
    g50100 = session.get('ge50_lt100', 0)
    if not (17 <= g50100 <= 27): fails.append(('ge50_lt100', g50100))
    g100200 = session.get('ge100_lt200', 0)
    if not (4 <= g100200 <= 14): fails.append(('ge100_lt200', g100200))
    g200500 = session.get('ge200_lt500', 0)
    if not (0 <= g200500 <= 7.3): fails.append(('ge200_lt500', g200500))
    for i, m in enumerate(margs):
        jp = m.get('jackpot', 0) * 100
        if jp > 0.6:
            fails.append((f'R{i+1}_jackpot', jp))
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--samples', type=int, default=500_000)
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    by_fail_count = defaultdict(list)
    by_only_fail_label = defaultdict(list)  # which hardline is the lone failure
    best_g15_high = None  # min g15 when g15>12 is sole fail
    best_g15_low = None   # max g15 when g15<10 is sole fail (closest from below)
    n_drawn = 0
    n_feasible = 0
    n_pass = 0
    for i in range(args.samples):
        margs = sample_reasonable(rng)
        if margs is None:
            continue
        n_drawn += 1
        try:
            total_rtp, hit, r1b, sess = evaluate(margs)
        except Exception:
            continue
        n_feasible += 1
        fails = check14(total_rtp, hit, r1b, sess, margs)
        nf = len(fails)
        if nf == 0:
            n_pass += 1
            by_fail_count[0].append((margs, total_rtp, hit, r1b, sess))
            if n_pass <= 5:
                print(f'  PASS sample {i}: tot={total_rtp:.2f} hit={hit:.2f} R1b={r1b:.2f} '
                      f'g15={sess.get("ge1_lt5",0):.2f} sum120={sess.get("ge1_lt5",0)+sess.get("ge5_lt10",0)+sess.get("ge10_lt20",0):.2f}')
        elif nf <= 3:
            by_fail_count[nf].append((margs, total_rtp, hit, r1b, sess, fails))
        if nf == 1:
            lab = fails[0][0]
            by_only_fail_label[lab].append((margs, total_rtp, hit, r1b, sess, fails[0][1]))
            if lab == 'ge1_lt5':
                g15 = sess.get('ge1_lt5', 0)
                if g15 > 12:
                    if best_g15_high is None or g15 < best_g15_high[0]:
                        best_g15_high = (g15, margs, total_rtp, hit, r1b, sess)
                elif g15 < 10:
                    if best_g15_low is None or g15 > best_g15_low[0]:
                        best_g15_low = (g15, margs, total_rtp, hit, r1b, sess)

    print(f'\n=== Summary ===')
    print(f'  drawn={args.samples}  feasible={n_feasible}  pass_all_14={n_pass}')
    for k in sorted(by_fail_count):
        print(f'  n_fail={k}: count={len(by_fail_count[k])}')
    print(f'\n  n_fail=1 by which hardline:')
    for lab, items in sorted(by_only_fail_label.items(), key=lambda x: -len(x[1])):
        vals = [it[5] for it in items]
        print(f'    {lab:14s} count={len(items):4d}  val range [{min(vals):.3f}, {max(vals):.3f}]')

    def dump(name, candidate, target_str):
        g15v, margs, total, hit, r1b, sess = candidate
        print(f'\n=== {name} ===')
        print(f'  total={total:.3f} hit={hit:.3f} R1b={r1b:.3f}')
        print(f'  g15={g15v:.3f}pp ({target_str})')
        print(f'  buckets:')
        for k in ('ge1_lt5','ge5_lt10','ge10_lt20','ge20_lt50','ge50_lt100',
                 'ge100_lt200','ge200_lt500'):
            print(f'    {k:14s} = {sess.get(k,0):7.3f}pp')
        print(f'  marginals (pct):')
        for i, m in enumerate(margs):
            entries = ' '.join(f'{s}={v*100:5.2f}' for s,v in sorted(m.items(), key=lambda x:-x[1]))
            print(f'    R{i+1}: {entries}')

    if best_g15_high:
        dump('Best g15-too-HIGH only-fail (min g15 still > 12)', best_g15_high, 'FAIL g15>12')
    if best_g15_low:
        dump('Best g15-too-LOW only-fail (max g15 still < 10)', best_g15_low, 'FAIL g15<10')

    if n_pass > 0:
        print(f'\n=== Best PASS candidate ===')
        margs, total, hit, r1b, sess = by_fail_count[0][0]
        print(f'  total={total:.3f} hit={hit:.3f} R1b={r1b:.3f}')
        print(f'  buckets:')
        for k in ('ge1_lt5','ge5_lt10','ge10_lt20','ge20_lt50','ge50_lt100',
                 'ge100_lt200','ge200_lt500'):
            print(f'    {k:14s} = {sess.get(k,0):7.3f}pp')
        print(f'  marginals (pct):')
        for i, m in enumerate(margs):
            entries = ' '.join(f'{s}={v*100:5.2f}' for s,v in sorted(m.items(), key=lambda x:-x[1]))
            print(f'    R{i+1}: {entries}')


if __name__ == '__main__':
    main()
