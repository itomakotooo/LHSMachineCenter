"""M15 v12 mode 1 redesign — wider tolerance under v4 hardlines (option C).

USER_HARDLINES v4 changes from v11:
  - sum_1_20 session ∈ [28, 32]pp (was ~30 with ±... unclear; now ±2 explicit)
  - 20+ each bucket ±5pp around v9:
      ge20_lt50 ∈ [22, 32]pp (v9 27 ± 5)
      ge50_lt100 ∈ [17, 27]pp (v9 22 ± 5)
      ge100_lt200 ∈ [4, 14]pp  (v9 9 ± 5)
      ge200_lt500 ∈ [0, 7.3]pp (v9 2.3 ± 5, floor 0)

Other hardlines unchanged:
  - Total RTP ∈ [94, 96]
  - Hit session ∈ [15, 18]
  - R1 blank ∈ [30, 40]
  - ge1_lt5 ∈ [10, 12]pp
  - Jackpot per reel ≤ 0.6%
  - Paytable + feature_params LOCKED (v9 byte-equal)

Key v12 insight (math)
======================

Feature contribution at v9 feature_params (LOCKED), trigger 1.127%:
    ge1_lt5      0.000pp
    ge5_lt10     0.076pp
    ge10_lt20    1.663pp
    ge20_lt50   18.180pp
    ge50_lt100  20.263pp
    ge100_lt200  8.334pp
    ge200_lt500  2.022pp
    >=500        0.062pp
    total       50.6pp

Base RTP target = [94, 96] - 50.6 = [43.4, 45.4]pp

Per bucket base targets (session - feature):
    ge1_lt5      base ∈ [10, 12]pp  (feature 0)
    ge5_lt10     base ∈ [3, 22]pp  (soft, sum constraint dominates)
    ge10_lt20    base ∈ [1, 25]pp  (soft, sum constraint dominates)
    sum_1_20     base ∈ [26.3, 30.3]pp
    ge20_lt50    base ∈ [3.82, 13.82]pp (v9 was 8.67, ±5 of 27 session)
    ge50_lt100   base ∈ [0, 6.74]pp   (v9 was 1.82; floor 0 since feature dominates)
    ge100_lt200  base ∈ [0, 5.67]pp   (v9 was 0.74)
    ge200_lt500  base ∈ [0, 5.28]pp   (v9 was 0.33)

Hit decomposition (base, need ≥ 13.87% for session ≥ 15%):
    cherry-1 (1×, ge1_lt5)            → ge1_lt5 contribution = P_ch1
    bar_mixed_pure (2×, ge1_lt5)      → ge1_lt5 = 2 × P_bm
    bar_mixed + 1 wild (4×, ge1_lt5)  → ge1_lt5 = 4 × P
    bar1_pure (5×, ge5_lt10)
    cherry-2 (5×, ge5_lt10)
    bar1+1wild (10×, ge10_lt20)
    bar2_pure (10×, ge10_lt20)
    cherry-3 (15×, ge10_lt20)
    bar2+1wild (20×, ge20_lt50)
    bar3_pure (20×, ge20_lt50)
    bar1+2wild (20×, ge20_lt50)
    h7_pure (30×, ge20_lt50)
    h7+1wild (60×, ge50_lt100)
    bar3+1wild (40×, ge20_lt50)
    bar2+2wild (40×, ge20_lt50)
    bar3+2wild (80×, ge50_lt100)
    h7+2wild (120×, ge100_lt200)
    wild_pure (200×, ge200_lt500)

Strategy:
  - Cherry uniform low ~3.5% (cherry-1 ~ 9-10pp ge1_lt5, hit ~10pp)
  - bars asymmetric per reel (R1=1bar heavy, R2=2bar heavy, R3=3bar heavy)
    to push bar_pures while keeping bar_mixed low.
  - Higher h7 marginal (lifts h7_pure 30× → ge20_lt50, h7+wild 60× → ge50_lt100)
  - Higher dd marginal (lifts wild_pure 200× → ge200_lt500 — room available
    in v4 latitude up to 7.3pp from 2.36pp v9).
  - Lower bar2/bar3 R3 to avoid 3bar > 2bar > 1bar share inversion (pyramid §1).
  - R1 blank target 35-39% (within band, lowest of 3 per §12).
"""
from __future__ import annotations

import argparse
import json
import random
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
    """Return list of (label, value, target_str, ok)."""
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
    items.append(('sum_1_20', s120, '[28, 32]', 28 <= s120 <= 32))

    # v4 widened 20+ tolerances:
    # ge20_lt50 ∈ [22, 32], ge50_lt100 ∈ [17, 27],
    # ge100_lt200 ∈ [4, 14], ge200_lt500 ∈ [0, 7.3]
    band_20plus = [
        ('ge20_lt50', 22, 32),
        ('ge50_lt100', 17, 27),
        ('ge100_lt200', 4, 14),
        ('ge200_lt500', 0, 7.3),
    ]
    for k, lo, hi in band_20plus:
        v = r['session_bucket'].get(k, 0)
        items.append((k, v, f'[{lo}, {hi}]', lo <= v <= hi))

    # Jackpot per-reel <= 0.6%
    for i, m in enumerate(margs):
        jp = m.get('jackpot', 0) * 100
        items.append((f'R{i+1}_jackpot', jp, '<= 0.6', jp <= 0.6))

    return items


def normalize(margs):
    return [{k: v / sum(m.values()) for k, v in m.items() if v > 0}
            for m in margs]


def make_margs(R1, R2, R3):
    """Convert per-reel non-blank specs to normalized marginals.

    Inputs: dict mapping symbol → desired marginal (excluding 'blank').
    'blank' is derived as 1 - sum(non-blank) so inputs map directly to
    final marginals after construction.
    """
    out = []
    for d in (R1, R2, R3):
        m = {s: 0.0 for s in (
            'blank', 'cherry', '1bar', '2bar', '3bar', 'high7',
            'doublediamond', 'topdollar', 'jackpot'
        )}
        m.update(d)
        # Always re-derive blank as residual so inputs == final marginals.
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
        f'{name:38s} {fail_tag:8s} '
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
# v12 candidate library
# =========================================================================
#
# A: tilt toward 20+ buckets (use v4's new latitude on g50_100, g100_200, g200_500)
#    via higher doublediamond marginal (more wild_pure 200× and bar+wild paths).

# Strategy: each reel R1/R2 needs blank ∈ [30, 40]% (R1) and some ≤ R1 R3 blank.
# Non-blank per reel must total ~60-70% for R1/R2, ~50-60% for R3.
#
# Key levers:
#   - cherry uniform ~3% : cherry-1 P ~ 8.5pp ge1_lt5
#   - each reel ONE bar type (suppress bar_mixed): R1=1bar, R2=2bar, R3=3bar
#     P(bar_mixed) = b1_R1 × b2_R2 × b3_R3 (single ordering)
#     With b ~ 30% each: P = 0.027 → 2 × 0.027 = 5.4pp ge1_lt5 from bar_mixed_pure
#     → g15 = 8.5 + 5.4 ≈ 14pp — STILL too high
#     Need to drop bar_mixed below ~1pp: bar_min ≤ 0.20 each.
#   - bar1_pure (5×) g510, bar2_pure (10×) g1020, bar3_pure (20×) g2050
#     These provide hit at higher mults without g15 cost.
#   - h7 ≥ 10% pushes h7_pure 30× g2050 + h7+1wild 60× g50100 + h7+2wild 120× g100200
#   - dd ≥ 5% pushes wild_pure 200× g200500 + bar wild combos
#
# Each-reel-1bar config (no bar_mixed except cross-reel ordering):
#   Total per reel: cherry + bar_type + h7 + dd + jackpot + (topdollar R3 only)
#   R1 non-blank = 0.6 → blank 40%; R3 non-blank = 0.5 → blank 50%

# A1: each-reel-1bar + cherry 3% + bars 30/30/25 + h7 ~12 + dd ~5
#   bar_mixed_pure P = 0.30 × 0.30 × 0.25 = 0.0225 → 4.5pp ge1_lt5 (too much g15)
#   But also bar_mixed with 1 wild substitution adds more.
#   So bars in 30 range too high for g15 cap.

# A1: each-reel-1bar + cherry 3% uniform + bars 22/22/18 + h7 ~15 + dd ~6
#   bar_mixed_pure P = 0.22 × 0.22 × 0.18 = 0.0087 → 1.7pp ge1_lt5
#   cherry-1 P = 3 × 0.03 × 0.97² = 0.0847 → 8.47pp ge1_lt5
#   g15 base from cherry + bar_mixed = 8.47 + 1.74 = 10.2pp ✓ at lower bound
#   R1 non-blank = 0.03 + 0.22 + 0.15 + 0.06 + 0.005 = 0.465 → blank 53.5% (still too high)

add("A1_each_reel_1bar_cherry_3_h7_15_dd_6",
    {'cherry': 0.03, '1bar': 0.22, 'high7': 0.15, 'doublediamond': 0.06, 'jackpot': 0.005},
    {'cherry': 0.03, '2bar': 0.22, 'high7': 0.15, 'doublediamond': 0.06, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.18, 'high7': 0.10, 'doublediamond': 0.035, 'topdollar': 0.011, 'jackpot': 0.001})

# A2: bars 30/30/25, h7 12/12/8, dd 5/5/3 — R1 non-blank = 0.685
add("A2_bars_30_h7_12",
    {'cherry': 0.03, '1bar': 0.30, 'high7': 0.12, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.03, '2bar': 0.30, 'high7': 0.12, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.25, 'high7': 0.08, 'doublediamond': 0.03, 'topdollar': 0.011, 'jackpot': 0.001})

# A3: bars 25/25/22, h7 18/18/10, dd 5
add("A3_bars_25_h7_18",
    {'cherry': 0.03, '1bar': 0.25, 'high7': 0.18, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.03, '2bar': 0.25, 'high7': 0.18, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.22, 'high7': 0.10, 'doublediamond': 0.03, 'topdollar': 0.011, 'jackpot': 0.001})

# A4: bars 23/23/20, h7 20/20/13, dd 6/6/4
add("A4_bars_23_h7_20",
    {'cherry': 0.03, '1bar': 0.23, 'high7': 0.20, 'doublediamond': 0.06, 'jackpot': 0.005},
    {'cherry': 0.03, '2bar': 0.23, 'high7': 0.20, 'doublediamond': 0.06, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.20, 'high7': 0.13, 'doublediamond': 0.04, 'topdollar': 0.011, 'jackpot': 0.001})

# A5: bars 25/25/22, h7 15/15/10, dd 8/8/5 — push wild
add("A5_bars_25_h7_15_dd_8",
    {'cherry': 0.03, '1bar': 0.25, 'high7': 0.15, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.03, '2bar': 0.25, 'high7': 0.15, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.22, 'high7': 0.10, 'doublediamond': 0.045, 'topdollar': 0.011, 'jackpot': 0.001})

# B: cherry uniform 2.5% (lower g15 cherry → more room for bars/wild)
add("B1_cherry_2p5_bars_25_h7_18",
    {'cherry': 0.025, '1bar': 0.25, 'high7': 0.18, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.025, '2bar': 0.25, 'high7': 0.18, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.22, 'high7': 0.10, 'doublediamond': 0.03, 'topdollar': 0.011, 'jackpot': 0.001})

# B2: cherry 2.5 bars 28 h7 18 dd 7
add("B2_cherry_2p5_bars_28_h7_18_dd_7",
    {'cherry': 0.025, '1bar': 0.28, 'high7': 0.18, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.025, '2bar': 0.28, 'high7': 0.18, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.24, 'high7': 0.10, 'doublediamond': 0.035, 'topdollar': 0.011, 'jackpot': 0.001})

# B3: cherry 2% bars 30 h7 18 dd 7
add("B3_cherry_2_bars_30_h7_18_dd_7",
    {'cherry': 0.02, '1bar': 0.30, 'high7': 0.18, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.02, '2bar': 0.30, 'high7': 0.18, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.25, 'high7': 0.10, 'doublediamond': 0.035, 'topdollar': 0.011, 'jackpot': 0.001})

# C: cherry asymm 4/3/2, bars 23/23/20, push h7+dd higher
add("C1_cherry_4_3_2_bars_25_h7_15_dd_5",
    {'cherry': 0.04, '1bar': 0.25, 'high7': 0.15, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.03, '2bar': 0.25, 'high7': 0.15, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.22, 'high7': 0.10, 'doublediamond': 0.03, 'topdollar': 0.011, 'jackpot': 0.001})

# C2: cherry 4/3/2, h7 high
add("C2_cherry_4_3_2_bars_22_h7_20_dd_6",
    {'cherry': 0.04, '1bar': 0.22, 'high7': 0.20, 'doublediamond': 0.06, 'jackpot': 0.005},
    {'cherry': 0.03, '2bar': 0.22, 'high7': 0.20, 'doublediamond': 0.06, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.20, 'high7': 0.13, 'doublediamond': 0.04, 'topdollar': 0.011, 'jackpot': 0.001})

# D: cherry uniform 3% but RAISE non-blank via dd higher (~8-10%)
add("D1_cherry_3_dd_high_h7_15",
    {'cherry': 0.03, '1bar': 0.22, 'high7': 0.15, 'doublediamond': 0.10, 'jackpot': 0.005},
    {'cherry': 0.03, '2bar': 0.22, 'high7': 0.15, 'doublediamond': 0.10, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.20, 'high7': 0.10, 'doublediamond': 0.05, 'topdollar': 0.011, 'jackpot': 0.001})

# E: balanced — cherry 3 + small bars + medium h7
add("E1_cherry_3_bars_20_h7_25",
    {'cherry': 0.03, '1bar': 0.20, 'high7': 0.25, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.03, '2bar': 0.20, 'high7': 0.25, 'doublediamond': 0.05, 'jackpot': 0.005},
    {'cherry': 0.02, '3bar': 0.18, 'high7': 0.15, 'doublediamond': 0.03, 'topdollar': 0.011, 'jackpot': 0.001})

# F: asymm bars heavily + cherry 3 uniform + moderate h7/dd
# R1 mostly 1bar, leakage 2bar/3bar small. R2 mostly 2bar. R3 mostly 3bar. h7 moderate.

add("F1_R1_1bar25_h7_18_dd_7_cherry_3",
    {'cherry': 0.03, '1bar': 0.25, '2bar': 0.02, '3bar': 0.01, 'high7': 0.18, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.02, '2bar': 0.25, '3bar': 0.01, 'high7': 0.18, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.01, '2bar': 0.02, '3bar': 0.22, 'high7': 0.12, 'doublediamond': 0.05, 'topdollar': 0.011, 'jackpot': 0.001})

# F2: smaller bars (suppress bar_mixed) + higher h7
add("F2_bars_15_h7_22",
    {'cherry': 0.03, '1bar': 0.15, '2bar': 0.02, '3bar': 0.01, 'high7': 0.22, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.02, '2bar': 0.15, '3bar': 0.01, 'high7': 0.22, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.01, '2bar': 0.02, '3bar': 0.14, 'high7': 0.14, 'doublediamond': 0.05, 'topdollar': 0.011, 'jackpot': 0.001})

# F3: even smaller bars, h7 dominant
add("F3_bars_12_h7_25",
    {'cherry': 0.03, '1bar': 0.12, '2bar': 0.02, '3bar': 0.01, 'high7': 0.25, 'doublediamond': 0.10, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.02, '2bar': 0.12, '3bar': 0.01, 'high7': 0.25, 'doublediamond': 0.10, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.01, '2bar': 0.02, '3bar': 0.11, 'high7': 0.15, 'doublediamond': 0.06, 'topdollar': 0.011, 'jackpot': 0.001})

# F4: bars 10, h7 28, dd 12
add("F4_bars_10_h7_28_dd_12",
    {'cherry': 0.03, '1bar': 0.10, '2bar': 0.02, '3bar': 0.01, 'high7': 0.28, 'doublediamond': 0.12, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.02, '2bar': 0.10, '3bar': 0.01, 'high7': 0.28, 'doublediamond': 0.12, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.01, '2bar': 0.02, '3bar': 0.09, 'high7': 0.18, 'doublediamond': 0.07, 'topdollar': 0.011, 'jackpot': 0.001})

# G: cherry uniform 2.5% (lower g15) + asymm bars + push h7/dd
add("G1_cherry_2p5_bars_asym_20",
    {'cherry': 0.025, '1bar': 0.20, '2bar': 0.02, '3bar': 0.01, 'high7': 0.18, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.025, '1bar': 0.02, '2bar': 0.20, '3bar': 0.01, 'high7': 0.18, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.01, '2bar': 0.02, '3bar': 0.16, 'high7': 0.12, 'doublediamond': 0.05, 'topdollar': 0.011, 'jackpot': 0.001})

# G2: cherry uniform 2 + asymm bars + h7 high
add("G2_cherry_2_bars_asym_20",
    {'cherry': 0.02, '1bar': 0.20, '2bar': 0.02, '3bar': 0.01, 'high7': 0.22, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.02, '2bar': 0.20, '3bar': 0.01, 'high7': 0.22, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.018, '1bar': 0.01, '2bar': 0.02, '3bar': 0.16, 'high7': 0.13, 'doublediamond': 0.045, 'topdollar': 0.011, 'jackpot': 0.001})

# H: v9-anchored — start from v9 marginals, adjust cherry down + dd/h7 up to fix R1 blank
# v9 R1: 1bar 10.6%, 2bar 14.8%, 3bar 7.7%, cherry 6.1%, h7 3.0%, dd 3.2%, jp 0.08% (sum 45.5% non-blank, blank 54.5%)
# Want R1 blank 38% → R1 non-blank 62% → add 16.5pp more non-blank. Cherry down 2pp + add h7/dd ~18pp.
# v9 R2: 1bar 9.5%, 2bar 14.2%, 3bar 6.3%, cherry 6.1%, h7 5.0%, dd 3.7%, jp 0.5% (sum 45.3%)
# v9 R3: 1bar 12.5%, 2bar 16.6%, 3bar 8.7%, cherry 3.1%, h7 2.0%, dd 1.4%, jp 0.14%, topdollar 1.13% (sum 45.6%)
# Want R3 blank ~50% (lowest of 3 to satisfy R1≤R3 universal direction)

# H1: cherry cut to 2.5/2.5/2 uniform, add dd uniform 8/8/4, h7 uniform 8/8/4 (more visible). Keep bars v9-like.
add("H1_v9_anchored_cherry_down_dd_h7_up",
    {'cherry': 0.025, '1bar': 0.106, '2bar': 0.148, '3bar': 0.077, 'high7': 0.08, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.025, '1bar': 0.095, '2bar': 0.142, '3bar': 0.063, 'high7': 0.08, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.018, '1bar': 0.125, '2bar': 0.166, '3bar': 0.087, 'high7': 0.04, 'doublediamond': 0.03, 'topdollar': 0.011, 'jackpot': 0.001})

# H2: cherry 2 uniform, h7 6/6/3, dd 6/6/3, bars unchanged
add("H2_v9_cherry_2_dd_h7_6",
    {'cherry': 0.02, '1bar': 0.106, '2bar': 0.148, '3bar': 0.077, 'high7': 0.06, 'doublediamond': 0.06, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.095, '2bar': 0.142, '3bar': 0.063, 'high7': 0.06, 'doublediamond': 0.06, 'jackpot': 0.005},
    {'cherry': 0.015, '1bar': 0.125, '2bar': 0.166, '3bar': 0.087, 'high7': 0.03, 'doublediamond': 0.02, 'topdollar': 0.011, 'jackpot': 0.001})

# H3: cherry 2.5/2.5/1.5, h7 7/7/3.5, dd 7/7/3.5, bars 0.85x v9
add("H3_v9_cherry_2p5_dd_h7_7",
    {'cherry': 0.025, '1bar': 0.090, '2bar': 0.126, '3bar': 0.065, 'high7': 0.07, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.025, '1bar': 0.081, '2bar': 0.121, '3bar': 0.054, 'high7': 0.07, 'doublediamond': 0.07, 'jackpot': 0.005},
    {'cherry': 0.015, '1bar': 0.106, '2bar': 0.141, '3bar': 0.074, 'high7': 0.035, 'doublediamond': 0.025, 'topdollar': 0.011, 'jackpot': 0.001})

# H4: cherry 3, bars 0.7x v9, h7 9/9/4, dd 9/9/4 — bars cut hard to suppress bar_mixed
add("H4_bars_cut_hard_h7_dd_9",
    {'cherry': 0.03, '1bar': 0.074, '2bar': 0.104, '3bar': 0.054, 'high7': 0.09, 'doublediamond': 0.09, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.066, '2bar': 0.099, '3bar': 0.044, 'high7': 0.09, 'doublediamond': 0.09, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.087, '2bar': 0.116, '3bar': 0.061, 'high7': 0.045, 'doublediamond': 0.035, 'topdollar': 0.011, 'jackpot': 0.001})

# H5: cherry 2.5/2.5/1.5, bars 0.7x v9, h7 8/8/4, dd 8/8/4
add("H5_cherry_2p5_bars_cut_h7_dd_8",
    {'cherry': 0.025, '1bar': 0.074, '2bar': 0.104, '3bar': 0.054, 'high7': 0.08, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.025, '1bar': 0.066, '2bar': 0.099, '3bar': 0.044, 'high7': 0.08, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.015, '1bar': 0.087, '2bar': 0.116, '3bar': 0.061, 'high7': 0.04, 'doublediamond': 0.03, 'topdollar': 0.011, 'jackpot': 0.001})

# H6: cherry 2/2/1, bars 0.7x v9, h7 8/8/4, dd 8/8/4
add("H6_cherry_2_bars_cut_h7_dd_8",
    {'cherry': 0.02, '1bar': 0.074, '2bar': 0.104, '3bar': 0.054, 'high7': 0.08, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.066, '2bar': 0.099, '3bar': 0.044, 'high7': 0.08, 'doublediamond': 0.08, 'jackpot': 0.005},
    {'cherry': 0.012, '1bar': 0.087, '2bar': 0.116, '3bar': 0.061, 'high7': 0.04, 'doublediamond': 0.03, 'topdollar': 0.011, 'jackpot': 0.001})

# H7: cherry 2.5/2.5/1.5, bars 0.6x v9, h7 9/9/4.5, dd 9/9/4.5
add("H7_bars_60pct_h7_dd_9",
    {'cherry': 0.025, '1bar': 0.064, '2bar': 0.089, '3bar': 0.046, 'high7': 0.09, 'doublediamond': 0.09, 'jackpot': 0.005},
    {'cherry': 0.025, '1bar': 0.057, '2bar': 0.085, '3bar': 0.038, 'high7': 0.09, 'doublediamond': 0.09, 'jackpot': 0.005},
    {'cherry': 0.015, '1bar': 0.075, '2bar': 0.100, '3bar': 0.052, 'high7': 0.045, 'doublediamond': 0.035, 'topdollar': 0.011, 'jackpot': 0.001})

# H8: cherry 3, bars 0.5x v9, h7 11/11/6, dd 10/10/5
add("H8_bars_50pct_h7_11_dd_10",
    {'cherry': 0.03, '1bar': 0.053, '2bar': 0.074, '3bar': 0.039, 'high7': 0.11, 'doublediamond': 0.10, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.048, '2bar': 0.071, '3bar': 0.032, 'high7': 0.11, 'doublediamond': 0.10, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.063, '2bar': 0.083, '3bar': 0.044, 'high7': 0.06, 'doublediamond': 0.04, 'topdollar': 0.011, 'jackpot': 0.001})


# I: target distribution Y — ge1_lt5 11, sum_1_20 31, ge20_lt50 27, ge50_lt100 23,
#    ge100_lt200 10, ge200_lt500 4. Base totals to ~44.5pp.
# Goal: R1 blank ~38%, R1 non-blank ~62%. Plus uniform marginals across reels mostly.

# I1: cherry 3 uniform, bars uniform 12/12/12 per reel (bsum 36, bar_mixed too high?)
# bar_mixed_pure = 0.12³ × 6_orderings - 3×0.12³ = 0.12³ × (6-3) = 3 × 0.001728 = 0.0052 → 1.04pp g15
# Cherry-1 8.47pp. g15 ≈ 9.5pp ✓ in band (could push slightly more bar)
# R1 non-blank = 3 + 12+12+12 + h7 + dd + 0.5 = 39.5 + h7 + dd. For 62% non-blank: h7+dd = 22.5pp.
# h7 13, dd 9: h7_pure 30×0.0022 = 0.066pp; h7+1wild 60×3×0.0169×0.09 = 0.27pp;
# h7+2wild 120×3×0.13×0.0081 = 0.38pp; wild_pure 200×0.000729 = 0.146pp
# Total wild/h7 ~ 0.86pp

add("I1_uniform_bars_12_h7_13_dd_9",
    {'cherry': 0.03, '1bar': 0.12, '2bar': 0.12, '3bar': 0.12, 'high7': 0.13, 'doublediamond': 0.09, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.12, '2bar': 0.12, '3bar': 0.12, 'high7': 0.13, 'doublediamond': 0.09, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.12, '2bar': 0.12, '3bar': 0.12, 'high7': 0.08, 'doublediamond': 0.04, 'topdollar': 0.011, 'jackpot': 0.001})

# I2: uniform bars 10/10/10, h7 15/15/9, dd 10/10/4
add("I2_uniform_bars_10_h7_15_dd_10",
    {'cherry': 0.03, '1bar': 0.10, '2bar': 0.10, '3bar': 0.10, 'high7': 0.15, 'doublediamond': 0.10, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.10, '2bar': 0.10, '3bar': 0.10, 'high7': 0.15, 'doublediamond': 0.10, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.10, '2bar': 0.10, '3bar': 0.10, 'high7': 0.10, 'doublediamond': 0.05, 'topdollar': 0.011, 'jackpot': 0.001})

# I3: bars 8/8/8 uniform (very low), h7 18/18/10, dd 12/12/6
add("I3_bars_8_h7_18_dd_12",
    {'cherry': 0.03, '1bar': 0.08, '2bar': 0.08, '3bar': 0.08, 'high7': 0.18, 'doublediamond': 0.12, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.08, '2bar': 0.08, '3bar': 0.08, 'high7': 0.18, 'doublediamond': 0.12, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.08, '2bar': 0.08, '3bar': 0.08, 'high7': 0.12, 'doublediamond': 0.06, 'topdollar': 0.011, 'jackpot': 0.001})

# J: v9-anchored but bars REDUCED to suppress bar_mixed; add dd to R1 to fix blank
# v9 R1 bars 33.1%, cherry 6.1, h7 3.0, dd 3.2 — non-blank 45.5
# Reduce bars to 20% per reel, keep h7 5%, push dd to 10%. cherry 2.5
# R1 non-blank: 2.5 + 20 + 5 + 10 + 0.5 = 38 → blank 62% (too high)
# Push more: cherry 3, bars 18, h7 8, dd 12, jp 0.5: 41.5 + non-blank → blank 58.5 (still high)
# Need h7+dd ~25-30 combined. Try h7 12, dd 15:
# I think I need to combine higher h7 and dd despite RTP risk.

# J1: cherry 3 uniform, bars uniform 10, h7 16/16/8, dd 14/14/5 — push R1 non-blank ~63%
add("J1_uniform_bars_10_h7_16_dd_14",
    {'cherry': 0.03, '1bar': 0.10, '2bar': 0.10, '3bar': 0.10, 'high7': 0.16, 'doublediamond': 0.14, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.10, '2bar': 0.10, '3bar': 0.10, 'high7': 0.16, 'doublediamond': 0.14, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.10, '2bar': 0.10, '3bar': 0.10, 'high7': 0.08, 'doublediamond': 0.05, 'topdollar': 0.011, 'jackpot': 0.001})

# J2: cherry 2.5, bars 8 uniform, h7 18/18/10, dd 12/12/4
add("J2_cherry_2p5_bars_8_h7_18_dd_12",
    {'cherry': 0.025, '1bar': 0.08, '2bar': 0.08, '3bar': 0.08, 'high7': 0.18, 'doublediamond': 0.12, 'jackpot': 0.005},
    {'cherry': 0.025, '1bar': 0.08, '2bar': 0.08, '3bar': 0.08, 'high7': 0.18, 'doublediamond': 0.12, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.08, '2bar': 0.08, '3bar': 0.08, 'high7': 0.10, 'doublediamond': 0.05, 'topdollar': 0.011, 'jackpot': 0.001})

# K: asym blank — R1 blank 38, R2 blank 48, R3 blank 52
# So R1 non-blank 62, R2 38 = wait R2 non-blank 52, R3 non-blank 48.
# Diff R1 vs R2/R3 in non-blank density. Adds more visibility to R1.

# K1: R1 boosted h7+dd, R2 v9-like, R3 v9-like
add("K1_R1_boosted_R2R3_v9like",
    # R1 non-blank 62
    {'cherry': 0.03, '1bar': 0.13, '2bar': 0.10, '3bar': 0.07, 'high7': 0.15, 'doublediamond': 0.13, 'jackpot': 0.005},
    # R2 non-blank 45 (v9-like)
    {'cherry': 0.03, '1bar': 0.095, '2bar': 0.142, '3bar': 0.063, 'high7': 0.07, 'doublediamond': 0.045, 'jackpot': 0.005},
    # R3 non-blank 45
    {'cherry': 0.02, '1bar': 0.125, '2bar': 0.166, '3bar': 0.087, 'high7': 0.03, 'doublediamond': 0.02, 'topdollar': 0.011, 'jackpot': 0.001})

# K2: R1+R2 both boosted, R3 v9-like
add("K2_R1R2_boosted_R3_v9like",
    {'cherry': 0.03, '1bar': 0.13, '2bar': 0.10, '3bar': 0.07, 'high7': 0.14, 'doublediamond': 0.13, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.12, '2bar': 0.10, '3bar': 0.06, 'high7': 0.14, 'doublediamond': 0.13, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.125, '2bar': 0.166, '3bar': 0.087, 'high7': 0.03, 'doublediamond': 0.02, 'topdollar': 0.011, 'jackpot': 0.001})

# K3: bars reduced even more, h7 mid
add("K3_bars_8_h7_12_dd_15",
    {'cherry': 0.03, '1bar': 0.08, '2bar': 0.08, '3bar': 0.06, 'high7': 0.12, 'doublediamond': 0.15, 'jackpot': 0.005},
    {'cherry': 0.03, '1bar': 0.08, '2bar': 0.08, '3bar': 0.06, 'high7': 0.12, 'doublediamond': 0.15, 'jackpot': 0.005},
    {'cherry': 0.02, '1bar': 0.10, '2bar': 0.10, '3bar': 0.08, 'high7': 0.06, 'doublediamond': 0.05, 'topdollar': 0.011, 'jackpot': 0.001})


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--full', action='store_true')
    p.add_argument('--best', type=int, default=5)
    args = p.parse_args()

    print('Feature bucket EV per trigger (LOCKED v9 feature_params):')
    for k, ev in sorted(FEATURE_BUCKET_EV.items(), key=lambda x: -x[1]):
        print(f'  {k:18s} = {ev:7.4f}x')
    print(f'  TOTAL          = {FEATURE_EV_TOTAL:.4f}x  ({FEATURE_EV_TOTAL * 100 * 0.01127:.3f}pp at 1.127% trigger)')
    print()

    results = []
    for name, R1, R2, R3 in CANDIDATES:
        margs = make_margs(R1, R2, R3)
        r = evaluate(margs)
        items = check_hardlines(r, margs)
        n_fail = sum(1 for it in items if not it[3])
        results.append((n_fail, name, r, margs, items))

    print('=' * 140)
    print('M15 v12 mode 1 candidate brief — v4 hardlines, ge20+ ±5pp around v9')
    print('=' * 140)
    for nf, name, r, margs, items in results:
        print_brief(name, r, margs, items)

    print()
    print('=' * 140)
    print(f'Top {args.best} candidates (lowest n_fail)')
    print('=' * 140)
    for nf, name, r, margs, items in sorted(results, key=lambda x: x[0])[:args.best]:
        print_full(name, r, margs, items)
        print()
