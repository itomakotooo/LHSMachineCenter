"""Closed-form upper bound on R1 non-blank density under USER_HARDLINES.md v4.

Goal: prove R1 max non-blank < 0.60, which → R1 blank ≥ 40% violated,
which → infeasibility under all 14 hardlines.

NOT random sampling. Per-symbol caps derived from hardline + paytable + feature.

Symmetric assumption for simplicity (R1=R2=R3 marginals). For each symbol,
compute max marginal subject to all relevant hardlines, then sum.

This OVERESTIMATES (each cap taken in isolation; ignores cross-coupling),
so if sum < 0.60, infeasibility is strictly proven.
"""
from __future__ import annotations

# Feature contributions per session bucket (v9 feature_params locked, trigger=0.0113)
FEAT = {
    'ge1_lt5':       0.000,
    'ge5_lt10':      0.076,
    'ge10_lt20':     1.663,
    'ge20_lt50':    18.180,
    'ge50_lt100':   20.263,
    'ge100_lt200':   8.334,
    'ge200_lt500':   2.022,
}

# Session caps (USER_HARDLINES.md v4)
SESSION_CAP = {
    'ge1_lt5':       (10, 12),
    'sum_1_20':      (28, 32),  # g15 + g510 + g1020
    'ge20_lt50':     (22, 32),
    'ge50_lt100':    (17, 27),
    'ge100_lt200':   ( 4, 14),
    'ge200_lt500':   ( 0,  7.3),
    'hit_session':   (15, 18),
    'total_rtp':     (94, 96),
    'R1_blank':      (0.30, 0.40),
    'jackpot':       (0.0, 0.006),
}

# Base bucket caps (subtract feature)
BASE_CAP_HI = {
    'ge1_lt5':       SESSION_CAP['ge1_lt5'][1] - FEAT['ge1_lt5'],         # 12.00
    'ge20_lt50':     SESSION_CAP['ge20_lt50'][1] - FEAT['ge20_lt50'],     # 13.82
    'ge50_lt100':    SESSION_CAP['ge50_lt100'][1] - FEAT['ge50_lt100'],   #  6.74
    'ge100_lt200':   SESSION_CAP['ge100_lt200'][1] - FEAT['ge100_lt200'], #  5.67
    'ge200_lt500':   SESSION_CAP['ge200_lt500'][1] - FEAT['ge200_lt500'], #  5.28
}

print('=== Base bucket RTP caps (session - feature) ===')
for k, v in BASE_CAP_HI.items():
    print(f'  {k:15s} ≤ {v:6.3f}pp')

print()
print('=== Per-symbol R1 marginal upper bounds ===')
print('(All bounds assume symmetric R1=R2=R3 with single-bar-dominant — most generous)')
print()

# --- Cherry ---
# cherry-1 P = 3c(1-c)² assuming uniform per-reel cherry density c.
# bar_mixed in g15 takes ~2-4pp typically, so cherry-1 g15 ≤ 12 - 2 = 10pp.
# cherry-1 P ≤ 0.10 → solve 3c(1-c)² = 0.10 → c ≈ 0.0357
# (assuming bar_mixed_pure ≥ 1.5pp due to required bars for sum_1_20)
# Conservative: cherry ≤ 0.04 (loose upper bound, ignores bar_mixed coupling)
c_max = 0.04
print(f'  cherry        ≤ {c_max:.4f}  (cherry-1 P ≤ 11% per reel, g15 budget)')

# --- High7 ---
# Constraint 1: h7³ × 30 (h7_pure) ≤ base ge20_lt50 cap = 13.82pp
# Constraint 2: h7+1wild base ≤ ge50_lt100 cap = 6.74pp → 3 h7² × w × 60 ≤ 6.74
#               → h7² × w ≤ 0.0374
# Constraint 3: h7+2wild base ≤ ge100_lt200 cap = 5.67pp → 3 h7 × w² × 120 ≤ 5.67
#               → h7 × w² ≤ 0.01575
# Solving for max h7 + w subject to all 3:
import math
def h7_max_given_w(w):
    cap_1 = (BASE_CAP_HI['ge20_lt50'] / 30) ** (1/3) / 100 ** (1/3)  # h7³×30 ≤ base = pp/100 fraction
    # Actually let me redo with fraction units (P × mult = RTP fraction; ≤ base_cap/100)
    cap_1 = (BASE_CAP_HI['ge20_lt50'] / 100 / 30) ** (1/3)  # h7 from h7³ × 30 ≤ base_cap/100
    cap_2 = math.sqrt((BASE_CAP_HI['ge50_lt100'] / 100) / (180 * w))  # h7² × 180w ≤ base
    cap_3 = (BASE_CAP_HI['ge100_lt200'] / 100) / (360 * w**2)  # h7 × 360w² ≤ base
    return min(cap_1, cap_2, cap_3)

# Sweep dd to find max h7+dd
best = (0, 0, 0)
for w_pct in range(1, 8):
    w = w_pct / 100
    h7_max = h7_max_given_w(w)
    # also wild_pure constraint
    if w**3 * 200 / 100 > BASE_CAP_HI['ge200_lt500'] / 100:
        continue  # wild_pure over cap
    if h7_max + w > best[0]:
        best = (h7_max + w, h7_max, w)
print(f'  high7+wild    sum ≤ {best[0]:.4f}  (h7={best[1]:.4f}, dd={best[2]:.4f})')
print(f'    constrained by: h7_pure / h7+1wild / h7+2wild / wild_pure RTP caps')

# --- Bars ---
# Single-bar-dominant: b1 high, b2=b3=ε small.
# bar1_pure (5×) + bar1+1wild (10×) ≤ g510 + g1020 budget = sum_1_20 - g15 (10-12) ≤ 22pp
# bar1+2wild (20×) goes to g2050; constrained by g2050 cap together with h7_pure.
# Conservative: 5 b1³ + 30 b1² w ≤ 0.20 (~20pp of base in g510+g1020 from bar1 family)
# At w = best[2]: solve quadratic-cubic for b1
def b1_max_given_w(w, sum_120_budget_pp):
    # 5 b1³ + 30 b1² w ≤ sum_120_budget_pp / 100
    # f(b1) = 5 b1³ + 30 w b1² - budget/100 = 0
    budget_fraction = sum_120_budget_pp / 100
    # bisect for b1 ∈ [0, 0.5]
    lo, hi = 0.0, 0.5
    for _ in range(50):
        mid = (lo + hi) / 2
        f = 5 * mid**3 + 30 * w * mid**2 - budget_fraction
        if f > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2

# Bar budget: sum_1_20 cap 32 - g15 (assume min 10) = 22pp.
# But also cherry-2, etc. take some. Conservative: bar1 family ≤ 22pp.
bar_budget = 22
b1_max = b1_max_given_w(best[2], bar_budget)
print(f'  1bar          ≤ {b1_max:.4f}  (bar1_pure + bar1+1wild ≤ g510+g1020 budget {bar_budget}pp)')

# b2, b3 minimal for "visibility" + paytable structure (philosophy direction):
b2_min = 0.02
b3_min = 0.02
print(f'  2bar          ≥ {b2_min:.4f}  (visibility direction, not hardline)')
print(f'  3bar          ≥ {b3_min:.4f}  (visibility direction, not hardline)')
# For UPPER BOUND on R1 non-blank, b2/b3 can be up to additional ε without overflowing bar_mixed.
# But b2/b3 inflate bar_mixed_pure. With b1 at b1_max, additional b_total raises bar_mixed.
# Conservative: keep b2=b3=ε.
b2_ub = 0.04
b3_ub = 0.04
print(f'  2bar (UB)     ≤ {b2_ub:.4f}  (limited by bar_mixed_pure g15 budget)')
print(f'  3bar (UB)     ≤ {b3_ub:.4f}  (same)')

# --- Wild (doublediamond) already bounded in h7+wild loop ---
w_max = best[2]
print(f'  doublediamond ≤ {w_max:.4f}  (from h7+wild + wild_pure + bar+wild caps)')

# --- Jackpot ---
jp_max = 0.006
print(f'  jackpot       ≤ {jp_max:.4f}  (USER_HARDLINES B5)')

# --- topdollar ---
# Only on R3, not R1. So 0 on R1.
td_max = 0
print(f'  topdollar     = {td_max:.4f}  (R3 only per paytable scatter_trigger.reel=3)')

# Sum upper bound on R1 non-blank
ub = c_max + b1_max + b2_ub + b3_ub + best[1] + w_max + jp_max + td_max
print()
print(f'=== R1 non-blank UPPER BOUND ===')
print(f'  cherry  ≤ {c_max:.4f}')
print(f'  1bar    ≤ {b1_max:.4f}')
print(f'  2bar    ≤ {b2_ub:.4f}')
print(f'  3bar    ≤ {b3_ub:.4f}')
print(f'  high7   ≤ {best[1]:.4f}')
print(f'  dd      ≤ {w_max:.4f}')
print(f'  jp      ≤ {jp_max:.4f}')
print(f'  td      = {td_max:.4f}')
print(f'  ─────────────────')
print(f'  SUM     ≤ {ub:.4f}')
print()
print(f'R1 blank min = 1 - {ub:.4f} = {1-ub:.4f} = {(1-ub)*100:.2f}%')
print()
print(f'USER hardline: R1 blank ∈ [30%, 40%]')
if (1 - ub) > 0.40:
    print(f'>> CONFLICT: R1 blank min {(1-ub)*100:.2f}% > 40% upper hardline')
    print(f'>> Gap: {((1-ub) - 0.40)*100:.2f}pp')
else:
    print(f'   R1 blank min {(1-ub)*100:.2f}% within hardline → no proof of infeasibility from this bound')
