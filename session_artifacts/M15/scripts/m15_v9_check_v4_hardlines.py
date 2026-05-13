"""Check current sd-disk v9 mode 1 weights against v4 hardlines.

Determines whether v9 (already on disk + xlsx) is the same as v12 best-found
§3.3 candidate in terms of which hardlines pass.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path('C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

M15_DIR = _ROOT / 'slot_designer' / 'machines' / 'M15'

# Compute v9 marginals from actual disk reel_strips + weights/mode_1
import json
strips = json.loads((M15_DIR / 'reel_strips.json').read_text(encoding='utf-8'))['reels']
weights_doc = json.loads((M15_DIR / 'weights' / 'mode_1' / 'weights.json').read_text(encoding='utf-8'))
sd_w = weights_doc['weights']

margs = []
for r in range(3):
    by_sym = defaultdict(float)
    for stop, sym in enumerate(strips[r]):
        by_sym[sym] += sd_w[r][stop]
    tot = sum(by_sym.values())
    margs.append({s: w / tot for s, w in by_sym.items()})

engine, _spec = load_engine(
    M15_DIR / 'spec.json',
    M15_DIR / 'weights' / 'mode_1' / 'weights.json',
    strips_path=M15_DIR / 'reel_strips.json',
)
prof = analytic_profile_from_marginals(engine.evaluator, margs)

trigger = margs[2].get('topdollar', 0.0)
base_rtp = prof['rtp_pct']
base_hit = prof['hit_rate']

# Feature EV from v9 feature_params (in weights.json)
fp = weights_doc['feature_params']
xc = tuple(fp['x_count_weights'])
yc = tuple(fp['y_count_weights'])
xv = tuple(fp['x_value_weights'])
yv = tuple(fp['y_value_weights'])
thresh = fp['accept_threshold']
maxR = fp['max_rounds']

dist = _round_payout_distribution(xc, yc, xv, yv)
p_accept = sum(p for r, p in dist if r >= thresh)
accept_dist = [(r, p) for r, p in dist if r >= thresh]
final = defaultdict(float)
for round_idx in range(1, maxR):
    branch = ((1 - p_accept) ** (round_idx - 1)) * p_accept
    for r, p in accept_dist:
        final[r] += branch * (p / p_accept) if p_accept > 0 else 0
branch = (1 - p_accept) ** (maxR - 1)
for r, p in dist:
    final[r] += branch * p

bucket_edges = [(5000, 'ge5000'), (1000, 'ge1000_lt5000'),
                (500, 'ge500_lt1000'), (200, 'ge200_lt500'),
                (100, 'ge100_lt200'), (50, 'ge50_lt100'),
                (20, 'ge20_lt50'), (10, 'ge10_lt20'),
                (5, 'ge5_lt10'), (1, 'ge1_lt5'), (0, 'gt0_lt1')]
def to_bucket(r):
    if r <= 0:
        return None
    for edge, k in bucket_edges:
        if r >= edge:
            return k
    return None

feat_bucket_ev = defaultdict(float)
for r, p in final.items():
    b = to_bucket(r)
    if b:
        feat_bucket_ev[b] += r * p

feature_ev_total = sum(feat_bucket_ev.values())
total_rtp = base_rtp + trigger * feature_ev_total * 100
hit_session = (base_hit + trigger) * 100
session_bucket = {k: v * 100 for k, v in prof['bucket_rtp'].items()}
for k, ev in feat_bucket_ev.items():
    session_bucket[k] = session_bucket.get(k, 0) + trigger * ev * 100

print(f'=== V9 mode 1 (current sd-disk state, ALREADY in xlsx) ===')
print(f'Base RTP    = {base_rtp:.3f}pp')
print(f'Feature RTP = {trigger*feature_ev_total*100:.3f}pp')
print(f'Total RTP   = {total_rtp:.3f}pp')
print(f'Hit session = {hit_session:.3f}%')
print(f'R1 blank    = {margs[0]["blank"]*100:.3f}%')
print()
print('Session buckets:')
for k in ('ge1_lt5','ge5_lt10','ge10_lt20','ge20_lt50','ge50_lt100',
         'ge100_lt200','ge200_lt500','ge1000_lt5000','ge5000'):
    v = session_bucket.get(k, 0)
    print(f'  {k:18s} = {v:7.3f}pp')
s120 = (session_bucket.get('ge1_lt5',0) + session_bucket.get('ge5_lt10',0)
        + session_bucket.get('ge10_lt20',0))
print(f'  sum_1_20         = {s120:7.3f}pp')
print()
print('USER_HARDLINES.md v4 check:')
def chk(label, val, lo, hi):
    ok = lo <= val <= hi
    print(f'  {"PASS" if ok else "FAIL"}  {label:18s} = {val:8.3f}  target [{lo}, {hi}]')
chk('total_rtp', total_rtp, 94, 96)
chk('hit_session', hit_session, 15, 18)
chk('R1_blank', margs[0]['blank']*100, 30, 40)
chk('ge1_lt5', session_bucket.get('ge1_lt5',0), 10, 12)
chk('sum_1_20', s120, 28, 32)
chk('ge20_lt50', session_bucket.get('ge20_lt50',0), 22, 32)
chk('ge50_lt100', session_bucket.get('ge50_lt100',0), 17, 27)
chk('ge100_lt200', session_bucket.get('ge100_lt200',0), 4, 14)
chk('ge200_lt500', session_bucket.get('ge200_lt500',0), 0, 7.3)
for i, m in enumerate(margs):
    chk(f'R{i+1}_jackpot', m.get('jackpot',0)*100, 0, 0.6)
