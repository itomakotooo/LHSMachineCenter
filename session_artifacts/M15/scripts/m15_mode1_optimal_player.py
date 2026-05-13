"""Compute optimal-player Feature Play EV for M15 mode 1.

Top Dollar Feature Play: 4 rounds, each round draws R = sum(X) × prod(Y).
Player decision rounds 1-3: accept current R OR reject and reroll.
Round 4: forced accept.

OPTIMAL strategy (dynamic programming):
  E[V_4] = E[R]                          # forced accept
  T_3 = E[V_4]                           # threshold to maximize EV
  E[V_3] = E[R | R ≥ T_3] × P(R ≥ T_3) + T_3 × P(R < T_3)
  T_2 = E[V_3]
  E[V_2] = E[R | R ≥ T_2] × P(R ≥ T_2) + E[V_3] × P(R < T_2)
  T_1 = E[V_2]
  E[V_1] = E[R | R ≥ T_1] × P(R ≥ T_1) + E[V_2] × P(R < T_1)

E[V_1] is the optimal feature EV per trigger.

Compare to:
  - Simulated player (T=40 fixed): current spec strategy → feature EV 46× (mode 1 v9)
  - Optimal: E[V_1] per above DP

Strategy gap = E[V_1] - simulated EV → additional feature RTP per trigger.

Mode 1 shipped trigger = 1.119% (R3 topdollar marginal v14 C38).
Mode 1 shipped total RTP = 94.26%.

If optimal_total_RTP > 96% → feature EV needs to be cut for safety.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path('C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
sys.path.insert(0, str(_ROOT))

from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

# Mode 1 / Mode 7 feature_params (byte-equal v9 locked)
X_COUNT = (5, 40, 40, 12, 3)
Y_COUNT = (75, 20, 5)
X_VALUE = (0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684)
Y_VALUE = (1, 1)
ACCEPT_THRESHOLD_SIM = 40
MAX_ROUNDS = 4

# Mode 1 shipped trigger (v14 C38 engine-realized)
M1_TRIGGER = 0.01119
M1_BASE_RTP = 43.66  # base RTP from C38 (engine, see design_v14.md)
# = 94.26 - 50.6 ≈ 43.66 (m1 ship doc shows base 42.77 analytic but engine 43.66; use shipped engine total - feature 50.6 = base ~43.66)
# Let me recompute: total = base + trigger × feature_EV × 100
# 94.26 = base + 0.01119 × 46 × 100 → base = 94.26 - 51.47 = 42.79
M1_BASE_RTP = 42.79  # engine-realized for C38


def main():
    print('=== M15 Mode 1/7 Feature Play optimal-player EV ===\n')

    # Step 1: get the per-round R distribution
    dist = _round_payout_distribution(X_COUNT, Y_COUNT, X_VALUE, Y_VALUE)
    dist = sorted(dist, key=lambda rp: rp[0])  # by r ascending
    print(f'Per-round distribution: {len(dist)} unique R values')
    print(f'  min R = {min(r for r, p in dist):.4f}')
    print(f'  max R = {max(r for r, p in dist):.4f}')
    print(f'  sum of P = {sum(p for r, p in dist):.6f}')

    U = sum(r * p for r, p in dist)  # unconditional E[R]
    print(f'  E[R] (unconditional) = {U:.4f}×')

    # Step 2: simulated player EV (T=40 fixed)
    # Round 1-3 strategy: accept if R ≥ 40, else reroll. Round 4 forced.
    # E[V_sim] = compute by simulation/expected value forward
    p_accept_sim = sum(p for r, p in dist if r >= ACCEPT_THRESHOLD_SIM)
    E_R_given_accept_sim = (sum(r * p for r, p in dist if r >= ACCEPT_THRESHOLD_SIM)
                            / p_accept_sim if p_accept_sim > 0 else 0)
    print(f'\nSimulated player (fixed T={ACCEPT_THRESHOLD_SIM}×):')
    print(f'  P(R ≥ {ACCEPT_THRESHOLD_SIM}) = {p_accept_sim*100:.3f}%')
    print(f'  E[R | accept] = {E_R_given_accept_sim:.4f}×')

    # E[V_sim] = (sum over rounds 1-3 of (1-p)^(k-1) × p × E[R|accept]) + (1-p)^3 × U
    p = p_accept_sim
    A = E_R_given_accept_sim
    EV_sim = 0
    for k in range(1, MAX_ROUNDS):
        EV_sim += ((1 - p) ** (k - 1)) * p * A
    EV_sim += ((1 - p) ** (MAX_ROUNDS - 1)) * U
    print(f'  EV (simulated, 4-round) = {EV_sim:.4f}× bet')

    # Step 3: optimal player EV (dynamic threshold backward DP)
    print(f'\nOptimal player (dynamic threshold):')

    EV_4 = U  # forced accept on round 4

    # round 3: threshold T_3 = EV_4
    T_3 = EV_4
    p_accept_3 = sum(p for r, p in dist if r >= T_3)
    sum_r_3 = sum(r * p for r, p in dist if r >= T_3)
    EV_3 = sum_r_3 + EV_4 * (1 - p_accept_3)

    # round 2: threshold T_2 = EV_3
    T_2 = EV_3
    p_accept_2 = sum(p for r, p in dist if r >= T_2)
    sum_r_2 = sum(r * p for r, p in dist if r >= T_2)
    EV_2 = sum_r_2 + EV_3 * (1 - p_accept_2)

    # round 1: threshold T_1 = EV_2
    T_1 = EV_2
    p_accept_1 = sum(p for r, p in dist if r >= T_1)
    sum_r_1 = sum(r * p for r, p in dist if r >= T_1)
    EV_1 = sum_r_1 + EV_2 * (1 - p_accept_1)

    print(f'  Round 4 (forced): E[V_4] = {EV_4:.4f}×')
    print(f'  Round 3: T_3 = {T_3:.4f}×  P(accept) = {p_accept_3*100:.3f}%  E[V_3] = {EV_3:.4f}×')
    print(f'  Round 2: T_2 = {T_2:.4f}×  P(accept) = {p_accept_2*100:.3f}%  E[V_2] = {EV_2:.4f}×')
    print(f'  Round 1: T_1 = {T_1:.4f}×  P(accept) = {p_accept_1*100:.3f}%  E[V_1] = {EV_1:.4f}×')
    print(f'\n  Optimal EV per trigger = {EV_1:.4f}× bet')

    # Step 4: strategy gap & RTP impact
    gap = EV_1 - EV_sim
    print(f'\n=== Strategy gap ===')
    print(f'  Simulated EV     = {EV_sim:.4f}× (≈46× per shipped spec)')
    print(f'  Optimal EV       = {EV_1:.4f}×')
    print(f'  Gap              = {gap:.4f}× per trigger (+{gap/EV_sim*100:.2f}%)')

    sim_feature_rtp = EV_sim * M1_TRIGGER * 100
    opt_feature_rtp = EV_1 * M1_TRIGGER * 100
    sim_total_rtp = M1_BASE_RTP + sim_feature_rtp
    opt_total_rtp = M1_BASE_RTP + opt_feature_rtp

    print(f'\nMode 1 (trigger {M1_TRIGGER*100:.3f}%, base RTP {M1_BASE_RTP:.2f}pp):')
    print(f'  Simulated feature RTP    = {sim_feature_rtp:.2f}pp')
    print(f'  Optimal player feature RTP = {opt_feature_rtp:.2f}pp')
    print(f'  Simulated total RTP        = {sim_total_rtp:.2f}%  (target [94, 96])')
    print(f'  Optimal player total RTP   = {opt_total_rtp:.2f}%  {"✗ OVER 96 ceiling!" if opt_total_rtp > 96 else "✓ within band"}')

    if opt_total_rtp > 96:
        # Compute target EV per trigger to bring optimal RTP back to 95% center
        target_total = 95.0
        target_opt_feature_rtp = target_total - M1_BASE_RTP
        target_EV_optimal = target_opt_feature_rtp / (M1_TRIGGER * 100)
        # Scale current EV proportionally (rough — actual reduce_feature would need re-tune)
        scale = target_EV_optimal / EV_1
        print(f'\n=== Suggested feature EV cut to bring optimal RTP to {target_total}% ===')
        print(f'  Target EV (optimal player) = {target_EV_optimal:.4f}× per trigger')
        print(f'  Reduction factor = {scale*100:.2f}% (cut feature payouts by {(1-scale)*100:.2f}%)')
        print(f'  Equivalent simulated EV after cut ≈ {EV_sim * scale:.4f}× per trigger')
        print(f'  Equivalent simulated total RTP after cut ≈ {M1_BASE_RTP + EV_sim * scale * M1_TRIGGER * 100:.2f}%')


if __name__ == '__main__':
    main()
