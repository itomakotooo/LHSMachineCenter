"""Mode 2 search round 3: per-bar non-uniform lifts (mirror shipped m2's bar2-heavy pattern)
but preserve §1 P(bar1)>P(bar2)>P(bar3)."""
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
    print(f"{label}: tot={tot:.2f} base={base:.2f} hit={hit*100:.2f}% wld={pwild/M1_PWILD:.3f} "
          f"c1={cherry1_sh:.1f} h7={high7_sh:.1f} b3={bar3_sh:.1f} wsh={wild_sh:.3f} "
          f"R1bl={margs[0]['blank']*100:.1f} R3bl={margs[2]['blank']*100:.1f} "
          f"bars={b1*100:.3f}|{b2*100:.3f}|{b3*100:.3f} OK={all_ok}")
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


# Strategy: heavy lift on bar1/bar2/3bar but maintain P(bar1)>P(bar2)>P(bar3) via marginal ordering
# m1: 1bar 20.19/16.51/13.49, 2bar 16.48/13.53/10.99, 3bar 10.32/7.29/5.49
# To preserve §1 marginal: 1bar > 2bar > 3bar per reel.
# Heavy lift: bar1 1.3-1.7x, bar2 1.4-1.8x, bar3 1.5-2.0x ALL with constraint 1bar_marg > 2bar_marg > 3bar_marg.

# AA1: heavy R3 lift bars + dd low
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.15, '2bar': 0.1648*1.15, '3bar': 0.1032*1.15,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.45, '2bar': 0.1353*1.45, '3bar': 0.0729*1.45,
      'high7': 0.0571*2.30, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*1.95, '2bar': 0.1099*1.95, '3bar': 0.0549*1.95,
      'high7': 0.0470*2.50, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('AA1', r1, r2, r3)

# AA2: bars uniformly more lifted on R3, including bar3 (helps wild substitution on 3bar+wild)
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.40, '2bar': 0.1353*1.40, '3bar': 0.0729*1.40,
      'high7': 0.0571*2.30, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*2.00, '2bar': 0.1099*2.00, '3bar': 0.0549*2.00,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('AA2', r1, r2, r3)

# AA3: trigger higher 3.2%
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.40, '2bar': 0.1353*1.40, '3bar': 0.0729*1.40,
      'high7': 0.0571*2.30, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*2.00, '2bar': 0.1099*2.00, '3bar': 0.0549*2.00,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.55, 'topdollar': 0.0112*2.95, 'jackpot': 0.003}
check('AA3_trig329', r1, r2, r3)

# AA4: dd slightly higher (cube 0.7x m1)
# dd lifts: R1=0.95, R2=0.95, R3=0.78 → cube = 0.95 * 0.95 * 0.78 = 0.704
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*0.95, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.40, '2bar': 0.1353*1.40, '3bar': 0.0729*1.40,
      'high7': 0.0571*2.30, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*2.00, '2bar': 0.1099*2.00, '3bar': 0.0549*2.00,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.78, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('AA4_dd_07x', r1, r2, r3)

# AA5: more aggressive R3 lift
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.05, '2bar': 0.1648*1.05, '3bar': 0.1032*1.05,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*0.95, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.35, '2bar': 0.1353*1.35, '3bar': 0.0729*1.35,
      'high7': 0.0571*2.30, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*2.05, '2bar': 0.1099*2.05, '3bar': 0.0549*2.05,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.78, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('AA5_R3_max', r1, r2, r3)

# AA6: R3 push HARD bars (close to 30% non-blank from bars alone)
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.05, '2bar': 0.1648*1.05, '3bar': 0.1032*1.05,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*0.95, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.35, '2bar': 0.1353*1.35, '3bar': 0.0729*1.35,
      'high7': 0.0571*2.30, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*2.10, '2bar': 0.1099*2.10, '3bar': 0.0549*2.10,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.78, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('AA6_R3_more_bars', r1, r2, r3)

# AA7: trigger 3.2 + heavier
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.05, '2bar': 0.1648*1.05, '3bar': 0.1032*1.05,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*0.95, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.35, '2bar': 0.1353*1.35, '3bar': 0.0729*1.35,
      'high7': 0.0571*2.30, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*2.05, '2bar': 0.1099*2.05, '3bar': 0.0549*2.05,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.78, 'topdollar': 0.0112*2.95, 'jackpot': 0.003}
check('AA7_trig329_R3_max', r1, r2, r3)

# AA8: combine dd 0.8x + R3 max
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.05, '2bar': 0.1648*1.05, '3bar': 0.1032*1.05,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.35, '2bar': 0.1353*1.35, '3bar': 0.0729*1.35,
      'high7': 0.0571*2.30, 'doublediamond': 0.0280*1.0, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*2.00, '2bar': 0.1099*2.00, '3bar': 0.0549*2.00,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.78, 'topdollar': 0.0112*2.95, 'jackpot': 0.003}
check('AA8_dd_balanced_R3_max', r1, r2, r3)

# AA9: dd uniform 0.93 → cube 0.81x m1 (well within share cap)
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.05, '2bar': 0.1648*1.05, '3bar': 0.1032*1.05,
      'high7': 0.0720*1.30, 'doublediamond': 0.0290*0.93, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.35, '2bar': 0.1353*1.35, '3bar': 0.0729*1.35,
      'high7': 0.0571*2.30, 'doublediamond': 0.0280*0.93, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*2.00, '2bar': 0.1099*2.00, '3bar': 0.0549*2.00,
      'high7': 0.0470*2.55, 'doublediamond': 0.0240*0.93, 'topdollar': 0.0112*2.95, 'jackpot': 0.003}
check('AA9_dd_uniform_0.93', r1, r2, r3)
