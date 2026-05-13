"""M15 mode 1 — exact optimal stopping EV with full precision.

Optimal stopping theorem (backward induction):
  E[V_N] = E[R]  (last round forced accept)
  E[V_k] = T_k · P(R < T_k) + E[R · 1{R ≥ T_k}]
       where T_k = E[V_{k+1}]
  (i.e., accept if observed R ≥ E[future value], else reject)

This is THE unique optimal under the assumption of iid rounds + decision based on
observed R only. No randomized strategy or "lookahead" can do better.

Outputs full-precision optimal EV + per-round thresholds + per-round P(accept) +
mode 1 / 7 RTP under optimal play.
"""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

_ROOT = Path('C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
sys.path.insert(0, str(_ROOT))

from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

X_COUNT = (5, 40, 40, 12, 3)
Y_COUNT = (75, 20, 5)
X_VALUE = (0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684)
Y_VALUE = (1, 1)
N_ROUNDS = 4

# M15 mode 1 (v14 C38_C14 shipped) engine-realized
M1_TRIGGER = 0.0111873   # exact trigger from C38 engine
M1_BASE_RTP_PP = 42.7867  # exact base RTP pp engine-realized (= 94.2622 - 51.4755)

# Mode 7 (v14b M7_F110 shipped) engine-realized (shares feature_params)
M7_TRIGGER = 0.01121      # mode 7 engine trigger
M7_BASE_RTP_PP = 33.84    # mode 7 base RTP pp engine-realized


def optimal_stopping_ev(dist, n_rounds):
    """Backward DP. Returns list [E[V_N], E[V_{N-1}], ..., E[V_1]] of expected values."""
    # Round N (last): forced accept → E[V_N] = E[R]
    EV = [sum(r * p for r, p in dist)]
    thresholds = [None]  # round N has no threshold (forced)
    p_accepts = [1.0]

    for round_back in range(2, n_rounds + 1):
        # threshold for round (N - round_back + 1) = E[V from previous iter]
        T = EV[-1]
        p_acc = sum(p for r, p in dist if r >= T)
        sum_r_acc = sum(r * p for r, p in dist if r >= T)
        new_EV = sum_r_acc + T * (1 - p_acc)
        EV.append(new_EV)
        thresholds.append(T)
        p_accepts.append(p_acc)

    # Reverse to get [E[V_1], E[V_2], ..., E[V_N]]
    EV.reverse()
    thresholds.reverse()
    p_accepts.reverse()
    return EV, thresholds, p_accepts


def main():
    print('=== M15 Mode 1/7 Feature — exact optimal stopping ===\n')

    dist = sorted(_round_payout_distribution(X_COUNT, Y_COUNT, X_VALUE, Y_VALUE),
                  key=lambda rp: rp[0])
    sum_p = sum(p for _, p in dist)
    assert abs(sum_p - 1.0) < 1e-9, f'Distribution does not sum to 1: {sum_p}'

    print(f'Round R distribution: {len(dist)} unique values')
    print(f'  E[R] (unconditional, = E[V_4] forced accept) = {sum(r*p for r,p in dist):.10f}×')
    print()

    EV, thresholds, p_accepts = optimal_stopping_ev(dist, N_ROUNDS)

    print('Backward DP results (round 1 → 4):\n')
    print(f'  {"round":>6} {"E[V_k]":>15} {"T_k threshold":>16} {"P(accept|T_k)":>16}')
    for k, (ev, t, pa) in enumerate(zip(EV, thresholds, p_accepts), start=1):
        t_s = f'{t:.10f}' if t is not None else '— (forced)'
        print(f'  {k:>6} {ev:>15.10f} {t_s:>16} {pa*100:>14.6f}%')

    EV_optimal = EV[0]
    print(f'\n  OPTIMAL EV per trigger = {EV_optimal:.10f}×')
    print(f'  Optimal EV per trigger ≈ {EV_optimal:.4f}× (4 decimals)')

    # Mode 1 RTP under optimal play
    print(f'\n=== Mode 1 (trigger {M1_TRIGGER*100:.4f}%, base {M1_BASE_RTP_PP:.4f}pp) ===')
    feat_rtp_optimal = EV_optimal * M1_TRIGGER * 100
    total_optimal = M1_BASE_RTP_PP + feat_rtp_optimal
    print(f'  Optimal feature RTP = {feat_rtp_optimal:.6f}pp')
    print(f'  Optimal total RTP   = {total_optimal:.6f}%')
    print(f'  vs band [94, 96]    : margin to 94 floor = {total_optimal - 94:+.4f}pp; margin to 96 ceiling = {96 - total_optimal:+.4f}pp')

    # Mode 7 (shares feature_params, byte-equal)
    print(f'\n=== Mode 7 (trigger {M7_TRIGGER*100:.4f}%, base {M7_BASE_RTP_PP:.4f}pp) ===')
    feat_rtp_m7 = EV_optimal * M7_TRIGGER * 100
    total_m7 = M7_BASE_RTP_PP + feat_rtp_m7
    print(f'  Optimal feature RTP = {feat_rtp_m7:.6f}pp')
    print(f'  Optimal total RTP   = {total_m7:.6f}%')
    print(f'  vs band [83, 87]    : margin to 83 floor = {total_m7 - 83:+.4f}pp; margin to 87 ceiling = {87 - total_m7:+.4f}pp')

    # Strategy gap analysis
    print(f'\n=== Strategy gap (optimal vs spec simulated T=40) ===')
    T_spec = 40
    p_spec = sum(p for r, p in dist if r >= T_spec)
    A_spec = sum(r * p for r, p in dist if r >= T_spec) / p_spec if p_spec > 0 else 0
    EV_sim_4round = 0
    for k in range(1, N_ROUNDS):
        EV_sim_4round += ((1 - p_spec) ** (k - 1)) * p_spec * A_spec
    EV_sim_4round += ((1 - p_spec) ** (N_ROUNDS - 1)) * sum(r * p for r, p in dist)
    print(f'  Spec simulated EV (T=40, 4 rounds) = {EV_sim_4round:.10f}×')
    print(f'  Optimal EV                          = {EV_optimal:.10f}×')
    print(f'  Strategy gap                        = {EV_optimal - EV_sim_4round:.10f}× per trigger')
    print(f'  Strategy gap (%)                    = {(EV_optimal/EV_sim_4round - 1)*100:.6f}%')

    # M1 RTP gap
    rtp_gap_m1 = (EV_optimal - EV_sim_4round) * M1_TRIGGER * 100
    print(f'  Mode 1 RTP gap (optimal - sim)      = {rtp_gap_m1:.6f}pp')

    # Show the R values near optimal thresholds (which discrete payouts cluster)
    print(f'\n=== Payout structure near optimal thresholds ===')
    print(f'  Top thresholds: T_1 = {thresholds[0]:.4f}, T_2 = {thresholds[1]:.4f}, T_3 = {thresholds[2]:.4f}')
    print(f'  Nearby R values (within ±5× of thresholds):')
    seen = set()
    for T in thresholds[:3]:
        for r, p in dist:
            if T - 5 < r < T + 5 and r not in seen:
                seen.add(r)
                print(f'    R={r:8.4f}  P={p*100:.5f}%')


if __name__ == '__main__':
    main()
