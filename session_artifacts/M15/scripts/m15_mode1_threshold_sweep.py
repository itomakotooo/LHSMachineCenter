"""Sweep accept_threshold T for M15 mode 1 to see EV sensitivity.

Question: is T=40 in spec sub-optimal? What fixed T maximizes simulated EV?
What's the gap between best-fixed-T and optimal-per-round-DP?
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path('C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
sys.path.insert(0, str(_ROOT))

from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

X_COUNT = (5, 40, 40, 12, 3)
Y_COUNT = (75, 20, 5)
X_VALUE = (0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684)
Y_VALUE = (1, 1)
MAX_ROUNDS = 4

dist = sorted(_round_payout_distribution(X_COUNT, Y_COUNT, X_VALUE, Y_VALUE), key=lambda rp: rp[0])
U = sum(r * p for r, p in dist)


def sim_ev_fixed_T(T):
    """Simulated EV under fixed threshold T for rounds 1-3, forced round 4."""
    p = sum(p for r, p in dist if r >= T)
    A = (sum(r * p for r, p in dist if r >= T) / p) if p > 0 else 0
    ev = 0
    for k in range(1, MAX_ROUNDS):
        ev += ((1 - p) ** (k - 1)) * p * A
    ev += ((1 - p) ** (MAX_ROUNDS - 1)) * U
    return ev


def optimal_ev():
    """Optimal varying-T-per-round EV."""
    EV_4 = U
    T_3 = EV_4
    p3 = sum(p for r, p in dist if r >= T_3)
    EV_3 = sum(r * p for r, p in dist if r >= T_3) + EV_4 * (1 - p3)
    T_2 = EV_3
    p2 = sum(p for r, p in dist if r >= T_2)
    EV_2 = sum(r * p for r, p in dist if r >= T_2) + EV_3 * (1 - p2)
    T_1 = EV_2
    p1 = sum(p for r, p in dist if r >= T_1)
    EV_1 = sum(r * p for r, p in dist if r >= T_1) + EV_2 * (1 - p1)
    return EV_1


print('=== Mode 1 feature EV vs fixed threshold T ===\n')
print(f'  E[R] unconditional = {U:.4f}× (= the round-4 forced EV)\n')

print(f'{"T":>8}  {"EV":>10}  {"vs spec T=40":>13}  {"vs optimal":>13}')
opt_ev = optimal_ev()
for T in [0, 10, 20, 30, 35, 38, 40, 42, 45, 50, 60, 80, 100, 200, 500]:
    ev = sim_ev_fixed_T(T)
    diff_40 = ev - sim_ev_fixed_T(40)
    diff_opt = ev - opt_ev
    print(f'  {T:>6}    {ev:>8.4f}   {diff_40:>+10.4f}    {diff_opt:>+10.4f}')

print(f'\n  Optimal (varying T per round)      {opt_ev:.4f}× ← real upper bound')
print()

# Find best fixed T by binary search
import scipy.optimize as opt
res = opt.minimize_scalar(lambda T: -sim_ev_fixed_T(T), bounds=(5, 200), method='bounded')
best_T = res.x
best_ev = -res.fun
print(f'=== Best fixed T (single-threshold strategy) ===')
print(f'  Best T          = {best_T:.4f}×')
print(f'  Best fixed EV   = {best_ev:.4f}×')
print(f'  vs spec T=40    = {best_ev - sim_ev_fixed_T(40):+.4f}× ({((best_ev / sim_ev_fixed_T(40)) - 1) * 100:.2f}%)')
print(f'  vs optimal-DP   = {best_ev - opt_ev:+.4f}× (best fixed worse than per-round DP by this much)')

print()
print('=== M15 mode 1 RTP under different player models ===')
M1_TRIGGER = 0.01119
M1_BASE = 42.79
for model, ev in [('Random / accept-always (EV=U)', U),
                   ('Spec simulated T=40', sim_ev_fixed_T(40)),
                   (f'Best fixed-T ({best_T:.1f})', best_ev),
                   ('Optimal varying-T-per-round', opt_ev)]:
    feat_rtp = ev * M1_TRIGGER * 100
    total = M1_BASE + feat_rtp
    print(f'  {model:42s}  EV={ev:6.3f}x  feat_RTP={feat_rtp:5.2f}pp  total={total:5.2f}%')
