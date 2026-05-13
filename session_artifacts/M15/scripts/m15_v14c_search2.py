"""Mode 2 search round 2: dd lower (cube 0.7-0.8x m1), h7 higher share, hit closer to 33%."""
import sys, json
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))
from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine

_M15 = _ROOT / 'slot_designer' / 'machines' / 'M15'
engine, _ = load_engine(_M15 / 'spec.json', _M15 / 'weights' / 'mode_1' / 'weights.json', strips_path=_M15 / 'reel_strips.json')
EV = engine.evaluator


def normalize(m):
    out = dict(m)
    nb = sum(v for k, v in out.items() if k != 'blank')
    out['blank'] = max(0.0, 1.0 - nb)
    return out


PAY_FAM = {'9': 'cherry1', '71': 'cherry2', '4': 'cherry3', '1': 'wild_pure',
           '2': 'high7_wild', '21': 'high7_pure', '3': 'bar3', '5': 'bar2',
           '7': 'bar1', '8': 'bar_mixed'}

M1_PWILD = 1.9484e-5
M2_EV = 59.99
M2_P_R1000_PER_TRIG = 4.6569e-5


def check(label, r1, r2, r3):
    margs = [normalize(r1), normalize(r2), normalize(r3)]
    prof = analytic_profile_from_marginals(EV, margs)
    base = prof['rtp_pct']
    hit = prof['hit_rate']
    pwild = prof['pay_hits'].get('1', 0)
    h7w = prof['pay_hits'].get('2', 0)
    h7p = prof['pay_hits'].get('21', 0)
    b1 = prof['pay_hits'].get('7', 0)
    b2 = prof['pay_hits'].get('5', 0)
    b3 = prof['pay_hits'].get('3', 0)
    c1 = prof['pay_hits'].get('9', 0)
    c2 = prof['pay_hits'].get('71', 0)
    c3 = prof['pay_hits'].get('4', 0)
    trig = r3.get('topdollar', 0)
    feat_rtp = trig * M2_EV * 100
    tot = base + feat_rtp
    p_r1k = trig * M2_P_R1000_PER_TRIG

    fam_pp = {}
    for pid, rtp in prof['pay_rtp'].items():
        fam = PAY_FAM.get(pid)
        if fam is None:
            continue
        fam_pp[fam] = fam_pp.get(fam, 0) + rtp * 100
    cherry1_sh = fam_pp.get('cherry1', 0) / base * 100 if base else 0
    bar3_sh = fam_pp.get('bar3', 0) / base * 100 if base else 0
    high7_sh = (fam_pp.get('high7_wild', 0) + fam_pp.get('high7_pure', 0)) / base * 100 if base else 0
    wild_sh = fam_pp.get('wild_pure', 0) / base * 100 if base else 0

    TOL = 0.001
    h7_ok = h7w >= h7p - TOL
    c_ok = (c1 >= c2 - TOL) and (c2 >= c3 - TOL)
    rtp_ok = 292 <= tot <= 308
    hit_ok = 0.30 <= hit <= 0.35
    r1r3_ok = margs[0]['blank'] >= margs[2]['blank']
    wld_ratio_ok = pwild / M1_PWILD <= 1.5
    bar_ok = b1 > b2 > b3
    p_r1k_ok = p_r1k <= 1e-5
    jp_ok = all(m.get('jackpot', 0) <= 0.006 for m in margs)
    cherry1_sh_ok = 15.0 <= cherry1_sh <= 25.0
    bar3_sh_ok = 5.0 <= bar3_sh <= 22.0
    high7_sh_ok = 14.0 <= high7_sh <= 30.0
    wild_sh_ok = 0.08 <= wild_sh <= 0.30

    all_ok = all([rtp_ok, hit_ok, r1r3_ok, wld_ratio_ok, h7_ok, c_ok, bar_ok,
                  p_r1k_ok, jp_ok, cherry1_sh_ok, bar3_sh_ok, high7_sh_ok, wild_sh_ok])
    print(f"{label}: tot={tot:.2f} base={base:.2f} hit={hit*100:.2f}% wld_m2/m1={pwild/M1_PWILD:.3f} "
          f"c1={cherry1_sh:.1f} h7={high7_sh:.1f} wld={wild_sh:.3f} bars=({b1*100:.3f}|{b2*100:.3f}|{b3*100:.3f}) "
          f"OK={all_ok}")
    if not all_ok:
        fails = []
        if not rtp_ok: fails.append(f'RTP={tot:.2f}')
        if not hit_ok: fails.append(f'hit={hit*100:.2f}%')
        if not r1r3_ok: fails.append('R1<R3blank')
        if not wld_ratio_ok: fails.append(f'wld_ratio={pwild/M1_PWILD:.3f}')
        if not h7_ok: fails.append(f'h7w<h7p {h7w/h7p:.3f}')
        if not bar_ok: fails.append('bar hier')
        if not c_ok: fails.append('cherry hier')
        if not p_r1k_ok: fails.append('P>=1k')
        if not cherry1_sh_ok: fails.append(f'c1_sh={cherry1_sh:.1f}')
        if not bar3_sh_ok: fails.append(f'b3_sh={bar3_sh:.1f}')
        if not high7_sh_ok: fails.append(f'h7_sh={high7_sh:.1f}')
        if not wild_sh_ok: fails.append(f'wld_sh={wild_sh:.3f}')
        print(f"    FAIL: {fails}")
    return all_ok, margs, prof


# Strategy: dd reduced (cube ~0.7x m1) → wild_sh below 0.30 cap
# h7 lifted MORE (need share >=14% → h7 RTP >=14.7pp at base 105)
# bars moderate, cherry adjusted to push cherry1 share

# Calculate target h7 lift: m1 h7 RTP = 3.32pp share 7.8% of m1 base 42.77pp.
# For m2 base 105 and h7 share 14% → h7 RTP 14.7pp = 4.43x m1.
# h7 lift cube (uniform) of 4.43 → cube_lift = 4.43^(1/3) = 1.64x per reel.
# So h7 lifted ~1.6x average — earlier I had 1.5/1.85/2.4 (cube 6.7x base h7 RTP).
# Wait — h7 RTP scales not just by cube of h7 marg but also wild_subst boost.
# Let me try more h7 lift.

# Z1: h7 1.7/2.0/2.5 (closer to shipped m2 h7 9.12/13.79/11.96 vs m1 7.20/5.71/4.70)
# Shipped m2 lift: R1=1.27x, R2=2.41x, R3=2.54x — non-uniform with R2 peak.
# This is a "h7 R2-dominant lift" pattern.

r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.05, '2bar': 0.1648*1.05, '3bar': 0.1032*1.05,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.25, '2bar': 0.1353*1.25, '3bar': 0.0729*1.25,
      'high7': 0.0571*2.40, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*1.85, '2bar': 0.1099*1.85, '3bar': 0.0549*1.85,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('Z1_h7_R2peak_dd_low', r1, r2, r3)

# Z2: same but with bar lift cooler (lower hit)
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.00, '2bar': 0.1648*1.00, '3bar': 0.1032*1.00,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.20, '2bar': 0.1353*1.20, '3bar': 0.0729*1.20,
      'high7': 0.0571*2.40, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*1.80, '2bar': 0.1099*1.80, '3bar': 0.0549*1.80,
      'high7': 0.0470*2.50, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('Z2_h7_R2peak_lower_bar', r1, r2, r3)

# Z3: trigger up to 3.1% so feature contributes more
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.00, '2bar': 0.1648*1.00, '3bar': 0.1032*1.00,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.20, '2bar': 0.1353*1.20, '3bar': 0.0729*1.20,
      'high7': 0.0571*2.40, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*1.80, '2bar': 0.1099*1.80, '3bar': 0.0549*1.80,
      'high7': 0.0470*2.50, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.95, 'jackpot': 0.003}
check('Z3_trig329', r1, r2, r3)

# Z4: similar but full lift on R3 (R3 dense)
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.00, '2bar': 0.1648*1.00, '3bar': 0.1032*1.00,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.20, '2bar': 0.1353*1.20, '3bar': 0.0729*1.20,
      'high7': 0.0571*2.40, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*1.85, '2bar': 0.1099*1.85, '3bar': 0.0549*1.85,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('Z4_R3_dense', r1, r2, r3)

# Z5: cherry lifted more for share
r1 = {'cherry': 0.04*1.8, '1bar': 0.2019*1.00, '2bar': 0.1648*1.00, '3bar': 0.1032*1.00,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*2.0, '1bar': 0.1651*1.20, '2bar': 0.1353*1.20, '3bar': 0.0729*1.20,
      'high7': 0.0571*2.40, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.8, '1bar': 0.1349*1.85, '2bar': 0.1099*1.85, '3bar': 0.0549*1.85,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('Z5_cherry_lift_more', r1, r2, r3)

# Z6: uniform h7 lift (avoid R2 peak)
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.00, '2bar': 0.1648*1.00, '3bar': 0.1032*1.00,
      'high7': 0.0720*1.85, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.20, '2bar': 0.1353*1.20, '3bar': 0.0729*1.20,
      'high7': 0.0571*2.00, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*1.85, '2bar': 0.1099*1.85, '3bar': 0.0549*1.85,
      'high7': 0.0470*2.40, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('Z6_h7_uniform', r1, r2, r3)

# Z7: balanced cherry+h7+bar with R3 emphasis
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.00, '2bar': 0.1648*1.00, '3bar': 0.1032*1.00,
      'high7': 0.0720*1.50, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.20, '2bar': 0.1353*1.20, '3bar': 0.0729*1.20,
      'high7': 0.0571*2.20, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*1.85, '2bar': 0.1099*1.85, '3bar': 0.0549*1.85,
      'high7': 0.0470*2.50, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('Z7_balanced', r1, r2, r3)

# Z8: cherry-anchored heavy R3 - try to push c1 share
r1 = {'cherry': 0.04*2.0, '1bar': 0.2019*1.00, '2bar': 0.1648*1.00, '3bar': 0.1032*1.00,
      'high7': 0.0720*1.40, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*2.2, '1bar': 0.1651*1.20, '2bar': 0.1353*1.20, '3bar': 0.0729*1.20,
      'high7': 0.0571*2.20, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*3.0, '1bar': 0.1349*1.80, '2bar': 0.1099*1.80, '3bar': 0.0549*1.80,
      'high7': 0.0470*2.50, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('Z8_cherry_heavy', r1, r2, r3)
