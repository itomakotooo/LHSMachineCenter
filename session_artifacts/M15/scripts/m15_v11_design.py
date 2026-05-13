"""M15 v11 mode 1 redesign — SESSION-centric bucket targets.

User v3 hardlines (machines/M15/USER_HARDLINES.md):
  - Total RTP in [94, 96]
  - Hit (session-centric incl. feature trigger) in [15, 18]
  - R1 blank in [30, 40]
  - ge1_lt5 session-centric RTP in [10, 12]pp
  - sum(ge1_lt5+ge5_lt10+ge10_lt20) session ~ 30pp
  - 20+ buckets preserve v9 levels:
      ge20_lt50 ~27pp, ge50_lt100 ~22pp, ge100_lt200 ~9pp, ge200_lt500 ~2pp
  - Jackpot any-reel marginal <= 0.6%
  - Paytable LOCKED, feature_params LOCKED (v9 byte-equal)

Levers (from brief):
  - Cherry per-reel density (cherry-1/2/3 hit rate)
  - Bar mixed via 1bar/2bar/3bar mix and densities
  - doublediamond marginal (wild_pure 200x cadence + bar wild-boost)
  - high7 marginal (pure 30x ge20_lt50 contribution)
  - R3 topdollar marginal = trigger rate (LOCKED at ~1.1% per feature shape rule)

Approach:
  1. Closed-form feature contribution at v9 feature_params (44pp total, 0pp ge1_lt5)
  2. Sweep per-reel marginals via:
     - cherry per reel (low, R1 vs R2 vs R3 asymmetric)
     - 1bar/2bar/3bar per reel (bar split tunable)
     - high7 per reel (push ge20_lt50 base)
     - doublediamond per reel (wild_pure ge200 + bar_mult)
     - blank per reel (R1 lowest)
     - jackpot per reel (cap 0.6%, treat as decoration)
     - topdollar R3 (~1.1% for trigger)
  3. Reject if fails any user hardline; iterate.
  4. Convert top candidate to integer weights respecting strip stop structure.

Note: this generates marginals; strip stops are fixed (18+18 blank/non-blank
alternation). We map marginals to integer weights per stop in the post-processing
step (preserving strip layout).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"


_engine, _ = load_engine(
    M15_DIR / "spec.json",
    M15_DIR / "weights" / "mode_1" / "weights.json",
    strips_path=M15_DIR / "reel_strips.json",
)
_EV = _engine.evaluator


# v9 feature_params LOCKED — closed-form feature bucket contribution
_X_COUNT = (5, 40, 40, 12, 3)
_Y_COUNT = (75, 20, 5)
_X_VAL = (0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684)
_Y_VAL = (1, 1)
_ACCEPT_THRESHOLD = 40
_MAX_ROUNDS = 4

_BUCKETS = [
    (5000, 'ge5000'), (1000, 'ge1000_lt5000'), (500, 'ge500_lt1000'),
    (200, 'ge200_lt500'), (100, 'ge100_lt200'), (50, 'ge50_lt100'),
    (20, 'ge20_lt50'), (10, 'ge10_lt20'), (5, 'ge5_lt10'),
    (1, 'ge1_lt5'), (0, 'gt0_lt1'),
]


def _bucket(r):
    if r <= 0:
        return None
    for edge, k in _BUCKETS:
        if r >= edge:
            return k
    return None


def _compute_feature_bucket_ev():
    """Closed-form: P(R lands in bucket k | feature triggered) * E[R | bucket k]
    Output: dict bucket -> EV contribution per trigger (x bet).
    """
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

    bucket_ev = defaultdict(float)
    for r, p in final.items():
        b = _bucket(r)
        if b is None:
            continue
        bucket_ev[b] += r * p
    return dict(bucket_ev)


FEATURE_BUCKET_EV = _compute_feature_bucket_ev()
FEATURE_EV_TOTAL = sum(FEATURE_BUCKET_EV.values())


def evaluate(margs):
    """Compute session-centric profile given normalized per-reel marginals."""
    prof = analytic_profile_from_marginals(_EV, margs)
    trigger = margs[2].get('topdollar', 0.0)
    feature_rtp = trigger * FEATURE_EV_TOTAL * 100  # pp
    base_rtp = prof['rtp_pct']
    total = base_rtp + feature_rtp
    hit_session = (prof['hit_rate'] + trigger) * 100
    session_bucket = {}
    for k, v in prof['bucket_rtp'].items():
        session_bucket[k] = v * 100
    for k, ev in FEATURE_BUCKET_EV.items():
        session_bucket[k] = session_bucket.get(k, 0) + trigger * ev * 100
    return {
        'total_rtp': total,
        'base_rtp': base_rtp,
        'feature_rtp': feature_rtp,
        'hit_session': hit_session,
        'base_hit': prof['hit_rate'] * 100,
        'trigger': trigger * 100,
        'session_bucket': session_bucket,
        'profile': prof,
    }


def check_hardlines(r, margs):
    """Return list of (label, value, target, status) - status: PASS/FAIL."""
    items = []
    items.append(('total_rtp', r['total_rtp'], '[94, 96]',
                  94 <= r['total_rtp'] <= 96))
    items.append(('hit_session', r['hit_session'], '[15, 18]',
                  15 <= r['hit_session'] <= 18))
    R1b = margs[0]['blank'] * 100
    items.append(('R1_blank', R1b, '[30, 40]', 30 <= R1b <= 40))

    g15 = r['session_bucket'].get('ge1_lt5', 0)
    items.append(('ge1_lt5', g15, '[10, 12]', 10 <= g15 <= 12))

    s120 = (r['session_bucket'].get('ge1_lt5', 0) +
            r['session_bucket'].get('ge5_lt10', 0) +
            r['session_bucket'].get('ge10_lt20', 0))
    items.append(('sum_1_20', s120, '[27, 33]', 27 <= s120 <= 33))

    # 20+ preserve v9 (target ~27/22/9/2, allow +/- 2pp absolute)
    targets = [('ge20_lt50', 27, 2.5), ('ge50_lt100', 22, 2.5),
               ('ge100_lt200', 9, 2.5), ('ge200_lt500', 2.3, 1.0)]
    for k, t, tol in targets:
        v = r['session_bucket'].get(k, 0)
        items.append((k, v, f'~{t} +/- {tol}', abs(v - t) <= tol))

    # Jackpot per-reel <= 0.6%
    for i, m in enumerate(margs):
        jp = m.get('jackpot', 0) * 100
        items.append((f'R{i+1}_jackpot', jp, '<= 0.6', jp <= 0.6))

    # Soft: ge5_lt10 / ge10_lt20 "排除极端" - exclude extreme. Reasonable bands:
    # not zero, not crazy. Treat informational, not hard.
    return items


def normalize(margs):
    return [{k: v / sum(m.values()) for k, v in m.items() if v > 0}
            for m in margs]


def make_margs(R1, R2, R3):
    out = []
    for d in (R1, R2, R3):
        m = {s: 0.0 for s in (
            'blank', 'cherry', '1bar', '2bar', '3bar', 'high7',
            'doublediamond', 'topdollar', 'jackpot'
        )}
        m.update(d)
        if 'blank' not in d:
            nb = sum(v for k, v in m.items() if k != 'blank')
            m['blank'] = max(0.001, 1 - nb)
        out.append(m)
    return normalize(out)


CANDIDATES: list = []


def add(name, R1, R2, R3):
    CANDIDATES.append((name, R1, R2, R3))


def print_brief(name, r, margs, fails):
    g15 = r['session_bucket'].get('ge1_lt5', 0)
    g510 = r['session_bucket'].get('ge5_lt10', 0)
    g1020 = r['session_bucket'].get('ge10_lt20', 0)
    g2050 = r['session_bucket'].get('ge20_lt50', 0)
    g50100 = r['session_bucket'].get('ge50_lt100', 0)
    g100200 = r['session_bucket'].get('ge100_lt200', 0)
    g200500 = r['session_bucket'].get('ge200_lt500', 0)
    R1b = margs[0]['blank'] * 100
    sum_120 = g15 + g510 + g1020
    n_fail = sum(1 for it in fails if not it[3])
    fail_tag = 'PASS' if n_fail == 0 else f'FAIL_{n_fail}'
    print(
        f'{name:30s} {fail_tag:8s} '
        f'tot={r["total_rtp"]:5.2f} hit={r["hit_session"]:5.2f} R1b={R1b:5.2f} '
        f'g15={g15:5.2f} s120={sum_120:5.2f} '
        f'g2050={g2050:5.2f} g50100={g50100:5.2f} g100200={g100200:5.2f} g200500={g200500:5.2f}'
    )


def print_full(name, r, margs, items):
    print(f'--- {name} ---')
    print(f'  total_rtp={r["total_rtp"]:.3f}  base={r["base_rtp"]:.3f}  feature={r["feature_rtp"]:.3f}')
    print(f'  hit_session={r["hit_session"]:.3f}  base_hit={r["base_hit"]:.3f}  trigger={r["trigger"]:.3f}')
    print(f'  Session buckets:')
    for k in ('ge1_lt5', 'ge5_lt10', 'ge10_lt20', 'ge20_lt50', 'ge50_lt100',
             'ge100_lt200', 'ge200_lt500', 'ge500_lt1000', 'ge1000_lt5000'):
        v = r['session_bucket'].get(k, 0)
        print(f'    {k:18s} = {v:7.3f}pp')
    print(f'  Marginals:')
    for i, m in enumerate(margs):
        entries = ', '.join(f'{s}={v*100:5.2f}' for s, v in sorted(m.items(), key=lambda x: -x[1]))
        print(f'    R{i+1}: {entries}')
    print(f'  Hardline checks:')
    for label, val, target, ok in items:
        tag = 'PASS' if ok else 'FAIL'
        print(f'    {tag}  {label:18s} = {val:8.3f}   target {target}')


# =========================================================================
# Candidate library — sweep multiple strategies
# =========================================================================
#
# Goal arithmetic (closed-form):
#   target session 20+ buckets PRESERVED (v9 already passes):
#     ge20_lt50 ~27, ge50_lt100 ~22, ge100_lt200 ~9, ge200_lt500 ~2
#     these are dominated by feature (16.5/18.4/7.6/1.8 per trigger × 1.1% trigger
#     = 18.2/20.3/8.3/2.0pp feature). Base contributes 9.0/2.9/1.3/0.3pp v9. Total ~v9.
#   target session ge1_lt5 in [10, 12]pp = base ge1_lt5 must drop from 22.3 → ~11pp.
#   target session ge5_lt10 + ge10_lt20 must move so sum 1-20 ~ 30pp.
#     Currently 3.8 + 5.8 = 9.6. Need ~19pp combined (drop 10pp from g15, add 10pp here).
#   target total RTP ~ 94-96pp = base 43-45pp + feature 51pp.
#
# Levers:
#   - cherry density: cherry-1 (1x, ge1_lt5), cherry-2 (5x, ge5_lt10), cherry-3 (15x, ge10_lt20)
#     Reducing cherry on R1 (where it's high) drops cherry-1 hit massively.
#     Pulling cherry to R2/R3 with R1=low: cherry-2/3 P drops too. Tricky.
#   - bar densities: bar_mixed pure mostly ge1_lt5; bar1_pure ge5_lt10; bar2_pure ge10_lt20.
#   - 3bar: bar3_pure 20x = ge20_lt50 (already filled by feature).
#   - doublediamond: contributes to bar wild-substitution and pure_wild (200x ge200).
#
# Key insight: bar_mixed = prod(b1+b2+b3) - prod(b1) - prod(b2) - prod(b3) per-reel.
# If we keep total bar density similar to v9 but SHIFT toward unbalanced bars per reel,
# pure pays grow and mixed pays drop. e.g. R1 mostly 1bar, R2 mostly 2bar, R3 mostly 3bar.
# Then bar_mixed P remains high (cross-reel mix still happens) but pure pays also grow.

# Strategy A: drop cherry on R1 (~3%), keep low on R2 (~3%), zero R3. Drops cherry-1 ~7pp.
#   Base v9 bar contrib unchanged → keeps 20+ near v9. Lower base RTP fits.

add("A1_cherry_R1_3_R2_3_R3_0_bars_v9",
    {'blank': 0.45, 'cherry': 0.03, '1bar': 0.14, '2bar': 0.13, '3bar': 0.09, 'high7': 0.05, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.46, 'cherry': 0.03, '1bar': 0.13, '2bar': 0.125, '3bar': 0.07, 'high7': 0.082, 'doublediamond': 0.037, 'jackpot': 0.004},
    {'blank': 0.52, 'cherry': 0.0, '1bar': 0.148, '2bar': 0.145, '3bar': 0.095, 'high7': 0.04, 'doublediamond': 0.014, 'topdollar': 0.011, 'jackpot': 0.001})

# A2: cherry R1=2%, R2=2%, R3=0%. Slight bar cut.
add("A2_cherry_2_2_0_bars_slight_cut",
    {'blank': 0.45, 'cherry': 0.02, '1bar': 0.135, '2bar': 0.125, '3bar': 0.085, 'high7': 0.06, 'doublediamond': 0.033, 'jackpot': 0.005},
    {'blank': 0.47, 'cherry': 0.02, '1bar': 0.125, '2bar': 0.12, '3bar': 0.068, 'high7': 0.085, 'doublediamond': 0.038, 'jackpot': 0.004},
    {'blank': 0.52, 'cherry': 0.0, 'doublediamond': 0.014, '1bar': 0.148, '2bar': 0.145, '3bar': 0.095, 'high7': 0.04, 'topdollar': 0.011, 'jackpot': 0.001})

# A3: cherry R1=4, R2=0, R3=0
add("A3_cherry_R1_only_4pct",
    {'blank': 0.45, 'cherry': 0.04, '1bar': 0.135, '2bar': 0.125, '3bar': 0.085, 'high7': 0.05, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.0, '1bar': 0.128, '2bar': 0.125, '3bar': 0.07, 'high7': 0.082, 'doublediamond': 0.037, 'jackpot': 0.004},
    {'blank': 0.52, 'cherry': 0.0, '1bar': 0.148, '2bar': 0.145, '3bar': 0.095, 'high7': 0.04, 'doublediamond': 0.014, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy B: pure bar cut (reduce all bars by ~25-30% to drop bar_mixed).
#   Side effect: drops bar pure pays too. Need to compensate via cherry-2/3.

add("B1_bars_minus_25pct_cherry_3_3_3",
    {'blank': 0.50, 'cherry': 0.03, '1bar': 0.105, '2bar': 0.10, '3bar': 0.065, 'high7': 0.05, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.03, '1bar': 0.10, '2bar': 0.095, '3bar': 0.053, 'high7': 0.082, 'doublediamond': 0.037, 'jackpot': 0.004},
    {'blank': 0.55, 'cherry': 0.025, '1bar': 0.115, '2bar': 0.11, '3bar': 0.072, 'high7': 0.04, 'doublediamond': 0.014, 'topdollar': 0.011, 'jackpot': 0.001})

# B2: bars -30% cut, cherry pulled to R1 only @ 5%
add("B2_bars_minus_30pct_cherry_R1_5",
    {'blank': 0.43, 'cherry': 0.05, '1bar': 0.10, '2bar': 0.095, '3bar': 0.062, 'high7': 0.05, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.0, '1bar': 0.10, '2bar': 0.087, '3bar': 0.050, 'high7': 0.082, 'doublediamond': 0.037, 'jackpot': 0.004},
    {'blank': 0.55, 'cherry': 0.0, '1bar': 0.11, '2bar': 0.10, '3bar': 0.068, 'high7': 0.04, 'doublediamond': 0.014, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy C: asymmetric bars per reel (R1=1bar heavy, R2=2bar heavy, R3=3bar heavy).
#   Idea: bar_mixed remains but pure pays grow.

add("C1_bar_asym",
    {'blank': 0.45, 'cherry': 0.03, '1bar': 0.22, '2bar': 0.08, '3bar': 0.04, 'high7': 0.13, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.46, 'cherry': 0.03, '1bar': 0.08, '2bar': 0.22, '3bar': 0.06, 'high7': 0.10, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.52, 'cherry': 0.0, '1bar': 0.07, '2bar': 0.10, '3bar': 0.22, 'high7': 0.06, 'doublediamond': 0.014, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy D: cherry-3 path. cherry on all 3 reels at LOW density (~2%), boosting
#   cherry-3 (15x ge10_lt20) and cherry-2 (5x ge5_lt10) — moving RTP away from cherry-1.
#   Also drop bars proportionally.

add("D1_cherry_uniform_2_bars_v9",
    {'blank': 0.45, 'cherry': 0.02, '1bar': 0.135, '2bar': 0.13, '3bar': 0.085, 'high7': 0.07, 'doublediamond': 0.035, 'jackpot': 0.005},
    {'blank': 0.47, 'cherry': 0.02, '1bar': 0.125, '2bar': 0.12, '3bar': 0.07, 'high7': 0.085, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.51, 'cherry': 0.02, '1bar': 0.142, '2bar': 0.138, '3bar': 0.09, 'high7': 0.06, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy E: minimal cherry + minimal 3bar (bar_mixed mostly from b1+b2)
#  3bar small density → bar_mixed P drops because (b1+b2+b3)^3 has smaller bar3 term

add("E1_cherry_2_3_2_3bar_low",
    {'blank': 0.46, 'cherry': 0.02, '1bar': 0.16, '2bar': 0.15, '3bar': 0.03, 'high7': 0.07, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.46, 'cherry': 0.03, '1bar': 0.15, '2bar': 0.14, '3bar': 0.03, 'high7': 0.10, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.52, 'cherry': 0.02, '1bar': 0.16, '2bar': 0.15, '3bar': 0.03, 'high7': 0.06, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy F: like E1 but cherry-heavy on R1 + 3bar=0
add("F1_cherry_R1_5_3bar_0",
    {'blank': 0.42, 'cherry': 0.05, '1bar': 0.18, '2bar': 0.16, 'high7': 0.10, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.0, '1bar': 0.15, '2bar': 0.14, 'high7': 0.13, 'doublediamond': 0.04, 'jackpot': 0.005, '3bar': 0.04},
    {'blank': 0.54, 'cherry': 0.0, '1bar': 0.16, '2bar': 0.15, 'high7': 0.06, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001, '3bar': 0.04})

# Strategy G: like A but tune for hit floor.
#  In A1: hit was ~12% session. Need ≥ 15. Add cherry on R3 to bring cherry-1 back.

add("G1_cherry_R1_4_R2_3_R3_1",
    {'blank': 0.45, 'cherry': 0.04, '1bar': 0.135, '2bar': 0.125, '3bar': 0.085, 'high7': 0.05, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.46, 'cherry': 0.03, '1bar': 0.125, '2bar': 0.12, '3bar': 0.07, 'high7': 0.082, 'doublediamond': 0.037, 'jackpot': 0.004},
    {'blank': 0.51, 'cherry': 0.01, '1bar': 0.148, '2bar': 0.145, '3bar': 0.095, 'high7': 0.04, 'doublediamond': 0.014, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy H: leverage low R1 blank for hit. R1 cherry @ 6%, R1 bars high.
add("H1_R1_blank_38_cherry_6",
    {'blank': 0.38, 'cherry': 0.06, '1bar': 0.15, '2bar': 0.14, '3bar': 0.10, 'high7': 0.07, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.0, '1bar': 0.125, '2bar': 0.12, '3bar': 0.06, 'high7': 0.082, 'doublediamond': 0.037, 'jackpot': 0.004},
    {'blank': 0.52, 'cherry': 0.0, '1bar': 0.148, '2bar': 0.145, '3bar': 0.095, 'high7': 0.04, 'doublediamond': 0.014, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy I: R1 cherry @ 5%, R2 cherry @ 2%, R3 cherry @ 0. Bars cut 10%.
add("I1_cherry_5_2_0",
    {'blank': 0.42, 'cherry': 0.05, '1bar': 0.125, '2bar': 0.12, '3bar': 0.08, 'high7': 0.08, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.02, '1bar': 0.115, '2bar': 0.11, '3bar': 0.06, 'high7': 0.082, 'doublediamond': 0.037, 'jackpot': 0.004},
    {'blank': 0.52, 'cherry': 0.0, '1bar': 0.138, '2bar': 0.135, '3bar': 0.085, 'high7': 0.04, 'doublediamond': 0.014, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy J: cherry R1 = 5%, R2 = 5%, R3 = 0%. Bars at v9.
add("J1_cherry_5_5_0_bars_v9",
    {'blank': 0.45, 'cherry': 0.05, '1bar': 0.14, '2bar': 0.13, '3bar': 0.09, 'high7': 0.05, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.46, 'cherry': 0.05, '1bar': 0.13, '2bar': 0.125, '3bar': 0.07, 'high7': 0.082, 'doublediamond': 0.037, 'jackpot': 0.004},
    {'blank': 0.52, 'cherry': 0.0, '1bar': 0.148, '2bar': 0.145, '3bar': 0.095, 'high7': 0.04, 'doublediamond': 0.014, 'topdollar': 0.011, 'jackpot': 0.001})

# K1: cherry R1 = 5, R2 = 3, R3 = 0; bars cut 15%
add("K1_cherry_5_3_0_bars_minus_15",
    {'blank': 0.43, 'cherry': 0.05, '1bar': 0.118, '2bar': 0.115, '3bar': 0.075, 'high7': 0.08, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.48, 'cherry': 0.03, '1bar': 0.11, '2bar': 0.107, '3bar': 0.06, 'high7': 0.085, 'doublediamond': 0.038, 'jackpot': 0.004},
    {'blank': 0.52, 'cherry': 0.0, '1bar': 0.13, '2bar': 0.123, '3bar': 0.082, 'high7': 0.05, 'doublediamond': 0.025, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy L: cherry uniform 3-4% per reel + LOW bars (to suppress bar_mixed).
#   Math: cherry uniform 4% → cherry-1 P ~ 11%, cherry-2 P ~ 0.46%, cherry-3 P ~ 0.006%.
#   ge1_lt5 cherry contribution = 11pp. Bar_mixed must add ≤ 1pp.
#   Hit ≈ cherry-1 11% + cherry-2 0.46% + bar_pures small + bar_mixed 0.2% = ~12%
#   Session hit ~ 13.1% - below floor.
#   Need more hit from g5+ bucket pays. → bar2 higher, wild paths, h7.

add("L1_cherry_4_4_4_bars_low",
    {'blank': 0.45, 'cherry': 0.04, '1bar': 0.12, '2bar': 0.06, '3bar': 0.03, 'high7': 0.12, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.45, 'cherry': 0.04, '1bar': 0.12, '2bar': 0.06, '3bar': 0.03, 'high7': 0.12, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.04, '1bar': 0.13, '2bar': 0.06, '3bar': 0.03, 'high7': 0.10, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# L2: cherry 4% + bars even smaller (b1=10, b2=5, b3=2)
add("L2_cherry_4_4_4_bars_very_low",
    {'blank': 0.45, 'cherry': 0.04, '1bar': 0.10, '2bar': 0.05, '3bar': 0.02, 'high7': 0.18, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.45, 'cherry': 0.04, '1bar': 0.10, '2bar': 0.05, '3bar': 0.02, 'high7': 0.18, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.04, '1bar': 0.12, '2bar': 0.05, '3bar': 0.02, 'high7': 0.16, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# L3: cherry 3.5% uniform + low bars + more wild
add("L3_cherry_3p5_bars_low_more_wild",
    {'blank': 0.43, 'cherry': 0.035, '1bar': 0.11, '2bar': 0.05, '3bar': 0.025, 'high7': 0.14, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'blank': 0.45, 'cherry': 0.035, '1bar': 0.11, '2bar': 0.05, '3bar': 0.025, 'high7': 0.14, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.035, '1bar': 0.13, '2bar': 0.05, '3bar': 0.025, 'high7': 0.12, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# L4: cherry 3% uniform (cherry-1 ~ 8.46pp), bigger bars permitted to make up hit
add("L4_cherry_3_3_3_more_bars",
    {'blank': 0.45, 'cherry': 0.03, '1bar': 0.16, '2bar': 0.10, '3bar': 0.04, 'high7': 0.08, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.46, 'cherry': 0.03, '1bar': 0.15, '2bar': 0.09, '3bar': 0.035, 'high7': 0.10, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.03, '1bar': 0.16, '2bar': 0.10, '3bar': 0.04, 'high7': 0.07, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# L5: cherry 4 4 2 (R3 lower) + small bar
add("L5_cherry_4_4_2_bars_low",
    {'blank': 0.45, 'cherry': 0.04, '1bar': 0.12, '2bar': 0.06, '3bar': 0.03, 'high7': 0.10, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.45, 'cherry': 0.04, '1bar': 0.12, '2bar': 0.06, '3bar': 0.03, 'high7': 0.10, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.52, 'cherry': 0.02, '1bar': 0.13, '2bar': 0.06, '3bar': 0.03, 'high7': 0.10, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# M: cherry 3.5 + b1=15% b2=8% b3=3% (push 1bar pure into g510)
add("M1_cherry_3p5_b1_dominant",
    {'blank': 0.43, 'cherry': 0.035, '1bar': 0.15, '2bar': 0.08, '3bar': 0.03, 'high7': 0.08, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.43, 'cherry': 0.035, '1bar': 0.15, '2bar': 0.08, '3bar': 0.03, 'high7': 0.08, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.035, '1bar': 0.16, '2bar': 0.08, '3bar': 0.03, 'high7': 0.07, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# M2: same but R3 cherry=2%
add("M2_cherry_3p5_3p5_2_b1_dominant",
    {'blank': 0.43, 'cherry': 0.035, '1bar': 0.15, '2bar': 0.08, '3bar': 0.03, 'high7': 0.08, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.43, 'cherry': 0.035, '1bar': 0.15, '2bar': 0.08, '3bar': 0.03, 'high7': 0.08, 'doublediamond': 0.04, 'jackpot': 0.005},
    {'blank': 0.51, 'cherry': 0.02, '1bar': 0.16, '2bar': 0.08, '3bar': 0.03, 'high7': 0.07, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# N: cherry 4 4 3, b1=14% b2=7% b3=3%
add("N1_cherry_4_4_3_b1_high",
    {'blank': 0.40, 'cherry': 0.04, '1bar': 0.14, '2bar': 0.07, '3bar': 0.03, 'high7': 0.09, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.42, 'cherry': 0.04, '1bar': 0.14, '2bar': 0.07, '3bar': 0.03, 'high7': 0.09, 'doublediamond': 0.03, 'jackpot': 0.005},
    {'blank': 0.50, 'cherry': 0.03, '1bar': 0.16, '2bar': 0.07, '3bar': 0.03, 'high7': 0.07, 'doublediamond': 0.022, 'topdollar': 0.011, 'jackpot': 0.001})

# Strategy I: random sweep on top candidates


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--full', action='store_true')
    p.add_argument('--best', type=int, default=5)
    args = p.parse_args()

    results = []
    for name, R1, R2, R3 in CANDIDATES:
        margs = make_margs(R1, R2, R3)
        r = evaluate(margs)
        items = check_hardlines(r, margs)
        n_fail = sum(1 for it in items if not it[3])
        results.append((n_fail, name, r, margs, items))

    print('=' * 130)
    print('M15 v11 mode 1 candidate sweep — SESSION-centric hardlines')
    print('=' * 130)
    for nf, name, r, margs, items in results:
        print_brief(name, r, margs, items)

    print()
    print('=' * 130)
    print(f'Top {args.best} candidates (lowest n_fail)')
    print('=' * 130)
    for nf, name, r, margs, items in sorted(results, key=lambda x: x[0])[:args.best]:
        print_full(name, r, margs, items)
        print()
