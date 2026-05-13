"""Main-session independent cross-check of v12 agent's best §3.3 candidate.

Per WORKFLOW §2.6, don't trust agent self-grade. Reimplement the analytic
pipeline using only slot_designer.core primitives and confirm:
  - g15 = 17.23pp (or close)
  - all other v4 hardlines pass
  - feature EV per-bucket independent recompute matches agent's table

Marginals from v12_escalation.md §3.3 best-found candidate.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
engine, _spec = load_engine(
    M15_DIR / "spec.json",
    M15_DIR / "weights" / "mode_1" / "weights.json",
    strips_path=M15_DIR / "reel_strips.json",
)

# §3.3 marginals as percentages — feed back through the same engine evaluator
# without using m15_v12_design helpers.
def margs_from_pct(pct_R1, pct_R2, pct_R3):
    def reel(d):
        non_blank = sum(d.values())
        d = dict(d)
        d['blank'] = 100 - non_blank
        s = sum(d.values())
        return {k: v / s for k, v in d.items()}
    return [reel(pct_R1), reel(pct_R2), reel(pct_R3)]

R1_pct = {'cherry': 4.29, '1bar': 19.61, '2bar': 16.62, '3bar': 4.66,
          'high7': 19.44, 'doublediamond': 2.25, 'jackpot': 0.41}
R2_pct = {'cherry': 4.27, '1bar': 3.87, '2bar': 19.43, '3bar': 0.35,
          'high7': 4.37, 'doublediamond': 3.88, 'jackpot': 0.46}
R3_pct = {'cherry': 1.47, '1bar': 4.40, '2bar': 23.27, '3bar': 8.08,
          'high7': 1.12, 'doublediamond': 2.89, 'topdollar': 1.10, 'jackpot': 0.23}

margs = margs_from_pct(R1_pct, R2_pct, R3_pct)
prof = analytic_profile_from_marginals(engine.evaluator, margs)

trigger = margs[2].get('topdollar', 0.0)
base_rtp = prof['rtp_pct']
base_hit = prof['hit_rate']

# Feature EV from spec (LOCKED v9 feature_params)
_X_COUNT = (5, 40, 40, 12, 3)
_Y_COUNT = (75, 20, 5)
_X_VAL = (0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998,
          40.9684, 40.9684)
_Y_VAL = (1, 1)
_ACCEPT_THRESHOLD = 40
_MAX_ROUNDS = 4

dist = _round_payout_distribution(_X_COUNT, _Y_COUNT, _X_VAL, _Y_VAL)
p_accept = sum(p for r, p in dist if r >= _ACCEPT_THRESHOLD)
accept_dist = [(r, p) for r, p in dist if r >= _ACCEPT_THRESHOLD]
final = defaultdict(float)
for round_idx in range(1, _MAX_ROUNDS):
    branch = ((1 - p_accept) ** (round_idx - 1)) * p_accept
    for r, p in accept_dist:
        final[r] += branch * (p / p_accept) if p_accept > 0 else 0
branch = (1 - p_accept) ** (_MAX_ROUNDS - 1)
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

# Session-centric: base + feature attributed to triggering spin
total_rtp = base_rtp + trigger * feature_ev_total * 100
hit_session = (base_hit + trigger) * 100

session_bucket = {k: v * 100 for k, v in prof['bucket_rtp'].items()}
for k, ev in feat_bucket_ev.items():
    session_bucket[k] = session_bucket.get(k, 0) + trigger * ev * 100

print('=== Main-session crosscheck of v12 §3.3 best candidate ===\n')
print(f'Feature EV total (per trigger): {feature_ev_total:.4f}x')
print('Feature bucket EV per trigger:')
for k in ('ge1_lt5', 'ge5_lt10', 'ge10_lt20', 'ge20_lt50', 'ge50_lt100',
          'ge100_lt200', 'ge200_lt500', 'ge1000_lt5000', 'ge5000'):
    ev = feat_bucket_ev.get(k, 0)
    print(f'  {k:18s} {ev:8.4f}x   feature_rtp@trig={trigger*ev*100:7.3f}pp')
print()
print(f'Base RTP        = {base_rtp:.3f}pp')
print(f'Feature RTP     = {trigger*feature_ev_total*100:.3f}pp')
print(f'Total RTP       = {total_rtp:.3f}pp')
print(f'Base hit        = {base_hit*100:.3f}%')
print(f'Trigger         = {trigger*100:.3f}%')
print(f'Hit session     = {hit_session:.3f}%')
print(f'R1 blank        = {margs[0]["blank"]*100:.3f}%')
print()
print('Session buckets:')
for k in ('ge1_lt5', 'ge5_lt10', 'ge10_lt20', 'ge20_lt50', 'ge50_lt100',
          'ge100_lt200', 'ge200_lt500', 'ge1000_lt5000', 'ge5000'):
    v = session_bucket.get(k, 0)
    print(f'  {k:18s} = {v:7.3f}pp')
sum_120 = (session_bucket.get('ge1_lt5', 0)
           + session_bucket.get('ge5_lt10', 0)
           + session_bucket.get('ge10_lt20', 0))
print(f'  sum_1_20         = {sum_120:7.3f}pp')

print('\n=== Hardline check (USER_HARDLINES.md v4) ===')
def chk(label, val, lo, hi):
    ok = lo <= val <= hi
    tag = 'PASS' if ok else 'FAIL'
    print(f'  {tag}  {label:18s} = {val:8.3f}  target [{lo}, {hi}]')

chk('total_rtp', total_rtp, 94, 96)
chk('hit_session', hit_session, 15, 18)
chk('R1_blank', margs[0]['blank']*100, 30, 40)
chk('ge1_lt5', session_bucket.get('ge1_lt5', 0), 10, 12)
chk('sum_1_20', sum_120, 28, 32)
chk('ge20_lt50', session_bucket.get('ge20_lt50', 0), 22, 32)
chk('ge50_lt100', session_bucket.get('ge50_lt100', 0), 17, 27)
chk('ge100_lt200', session_bucket.get('ge100_lt200', 0), 4, 14)
chk('ge200_lt500', session_bucket.get('ge200_lt500', 0), 0, 7.3)
for i, m in enumerate(margs):
    chk(f'R{i+1}_jackpot', m.get('jackpot', 0)*100, 0, 0.6)
