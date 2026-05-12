"""Dump pid 9 sub-breakdown via engine enumerate_payline + manual categorization.

Main session quick check — does analytic prediction match user-reported empirical?
User reported (real machine 2.62M, May 8 v3 finalized):
  1x minor + 1x wild: 6,112 hits (49.9% RTP share within sub-display)
  1x major + 1x wild: 2,782 hits (45.4%)
  2x wild: 1,769 hits (2.9%)
  1x mini + 1x wild: 546 hits (1.8%)

Main session theoretical estimate was different — verify which is right.
"""
import sys
import json
sys.path.insert(0, '.')

from slot_designer.core.engine.loader import load_engine
from slot_designer.core.devtools.analytic_rtp import enumerate_payline, compute_reel_marginal

spec_path = 'slot_designer/machines/M37/spec.json'
strips_path = 'slot_designer/machines/M37/reel_strips.json'
weights_path = 'slot_designer/machines/M37/weights/mode_1/weights.json'

engine, _ = load_engine(spec_path, weights_path, strips_path=strips_path)

print('=== ALL pay_id 9 combos via enumerate_payline ===')
pid9_total = 0.0
pid9_rtp = 0.0
by_mult = {}
for prob, pid, mult in enumerate_payline(engine):
    if pid == 9:
        pid9_total += prob
        pid9_rtp += prob * mult
        by_mult.setdefault(mult, {'P': 0.0, 'count': 0})
        by_mult[mult]['P'] += prob
        by_mult[mult]['count'] += 1

print(f'pid 9 total P = {pid9_total*100:.4f}%, RTP = {pid9_rtp*100:.4f}pp')
print()
print('Breakdown by mult:')
for mult in sorted(by_mult):
    d = by_mult[mult]
    P_pct = d['P'] * 100
    RTP_pp = d['P'] * mult * 100
    print(f'  mult {mult:>5.1f}x  P={P_pct:.4f}%  RTP={RTP_pp:.4f}pp  ({d["count"]} combos)  -> 2.62M hits = {int(d["P"]*2620000):,}')
print()

# Now manually enumerate (i, j, k) and classify each
print('=== Manual full enumeration with classification ===')
mode_1_weights = json.loads(open(weights_path, 'r', encoding='utf-8').read())['weights']
strips_data = json.loads(open(strips_path, 'r', encoding='utf-8').read())['reels']
R1, R2, R3 = strips_data
sums = [sum(w) for w in mode_1_weights]
print(f'Reel totals: R1={sums[0]} R2={sums[1]} R3={sums[2]}')
print()

# For each combo, classify by what engine returns
pid9_cat = {}

for prob, pid, mult in enumerate_payline(engine):
    if pid != 9:
        continue
    # We can't easily get (i,j,k) from enumerate_payline directly.
    # Need different approach: iterate triples manually and compute pay_id.
    pass

# Use evaluator directly to classify each combo
from slot_designer.core.engine.evaluator import evaluate_payline
from slot_designer.core.engine.loader import load_engine as _load
spec_obj = json.loads(open(spec_path).read())

reel_strips = strips_data
weights = mode_1_weights

# Iterate every triple
triples_pid9 = []
total_prob_check = 0.0
for i, r1_sym in enumerate(reel_strips[0]):
    for j, r2_sym in enumerate(reel_strips[1]):
        for k, r3_sym in enumerate(reel_strips[2]):
            w_prob = (weights[0][i]/sums[0]) * (weights[1][j]/sums[1]) * (weights[2][k]/sums[2])
            total_prob_check += w_prob
            line = [r1_sym, r2_sym, r3_sym]
            try:
                result = evaluate_payline(line, engine)
            except Exception as e:
                # fallback: skip
                continue
            if result is None:
                continue
            try:
                pay_id, mult = result
            except (TypeError, ValueError):
                continue
            if pay_id != 9:
                continue
            triples_pid9.append((w_prob, mult, r1_sym, r2_sym, r3_sym))

print(f'Total prob check: {total_prob_check}')
print(f'Found {len(triples_pid9)} (R1, R2, R3) triples that evaluate to pid 9')
print()

# Categorize triples
def categorize(r1, r2, r3):
    boosters = ('mini', 'minor', 'major', 'grand')
    has_wild_r1 = r1 == 'wild'
    has_wild_r3 = r3 == 'wild'
    r2_is_booster = r2 in boosters

    if has_wild_r1 and has_wild_r3:
        return '2x wild (both sides)'
    if r2_is_booster and (has_wild_r1 or has_wild_r3):
        side = 'R1' if has_wild_r1 else 'R3'
        third = r3 if has_wild_r1 else r1
        return f'1x {r2} + 1x wild ({side}, third={third})'
    if r2_is_booster and not has_wild_r1 and not has_wild_r3:
        return f'1x {r2} alone (R1={r1}, R3={r3})'
    if not r2_is_booster and (has_wild_r1 or has_wild_r3):
        return f'side_wild_alone (R1={r1}, R2={r2}, R3={r3})'
    return f'OTHER (R1={r1}, R2={r2}, R3={r3})'

# Aggregate by category (or by simplified label)
def simplified_label(r1, r2, r3):
    boosters = ('mini', 'minor', 'major', 'grand')
    has_wild_r1 = r1 == 'wild'
    has_wild_r3 = r3 == 'wild'
    r2_is_booster = r2 in boosters
    if has_wild_r1 and has_wild_r3 and not r2_is_booster:
        return '2x wild'
    if r2_is_booster and (has_wild_r1 != has_wild_r3):
        return f'1x {r2} + 1x wild'
    if r2_is_booster and not has_wild_r1 and not has_wild_r3:
        return f'1x {r2} alone'
    if (has_wild_r1 != has_wild_r3) and not r2_is_booster:
        return 'side_wild_alone (no booster)'
    return f'OTHER: {r1}/{r2}/{r3}'

label_agg = {}
for w_prob, mult, r1, r2, r3 in triples_pid9:
    label = simplified_label(r1, r2, r3)
    label_agg.setdefault(label, {'P': 0.0, 'mult_sum_weighted': 0.0, 'count': 0, 'mults': set()})
    label_agg[label]['P'] += w_prob
    label_agg[label]['mult_sum_weighted'] += w_prob * mult
    label_agg[label]['count'] += 1
    label_agg[label]['mults'].add(mult)

print('=== pid 9 sub-categorization (simplified label) ===')
print(f'{"label":<35s} {"P %":>10s} {"RTP-pp":>10s} {"avg mult":>10s} {"% of pid9":>10s} {"combos":>8s} {"@2.62M hits":>14s}')
pid9_P_total = sum(d['P'] for d in label_agg.values())
for label, d in sorted(label_agg.items(), key=lambda x: -x[1]['mult_sum_weighted']):
    P_pct = d['P'] * 100
    RTP_pp = d['mult_sum_weighted'] * 100
    avg_mult = d['mult_sum_weighted']/d['P'] if d['P'] > 0 else 0
    pct_pid9 = d['P']/pid9_P_total*100 if pid9_P_total > 0 else 0
    hits = int(d['P'] * 2620000)
    print(f'{label:<35s} {P_pct:>10.4f} {RTP_pp:>10.4f} {avg_mult:>10.2f} {pct_pid9:>10.2f} {d["count"]:>8d} {hits:>14,}')

print()
print(f'pid 9 total P: {pid9_P_total*100:.4f}%')
print(f'expected hits @ 2.62M spins: {int(pid9_P_total*2620000):,}')

# User reported numbers:
print()
print('=== User-reported empirical (real machine 2.62M) ===')
print('  pid 9 total: 221,359 hits, 8.44% rate, 3.68x avg')
print('  Sub:')
print('    1x minor + 1x wild: 6,112 (mult 5x, 49.9% pid9 RTP)')
print('    1x major + 1x wild: 2,782 (mult 10x, 45.4%)')
print('    2x wild:             1,769 (mult 1x,  2.9%)')
print('    1x mini  + 1x wild:    546 (mult 2x,  1.8%)')
