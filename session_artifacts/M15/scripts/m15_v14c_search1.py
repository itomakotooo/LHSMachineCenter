"""Mode 2 search round 1: refine to pass FAMILY_SHARE bands (cherry1, wild_pure)."""
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

M1_PWILD = 1.9484e-5  # m1 wild_pure P from analytic
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
          f"shares c1={cherry1_sh:.1f} b3={bar3_sh:.1f} h7={high7_sh:.1f} wld={wild_sh:.3f} ALL_OK={all_ok}")
    if not all_ok:
        fails = []
        if not rtp_ok: fails.append(f'RTP {tot:.2f}')
        if not hit_ok: fails.append(f'hit {hit*100:.2f}%')
        if not r1r3_ok: fails.append(f'R1blank<R3 ({margs[0]["blank"]*100:.2f} vs {margs[2]["blank"]*100:.2f})')
        if not wld_ratio_ok: fails.append(f'wld_m2/m1 {pwild/M1_PWILD:.3f}')
        if not h7_ok: fails.append(f'h7w/h7p {h7w/h7p:.3f}')
        if not bar_ok: fails.append('bar hier')
        if not c_ok: fails.append('cherry hier')
        if not p_r1k_ok: fails.append('P>=1k')
        if not cherry1_sh_ok: fails.append(f'cherry1_sh {cherry1_sh:.2f}')
        if not bar3_sh_ok: fails.append(f'bar3_sh {bar3_sh:.2f}')
        if not high7_sh_ok: fails.append(f'h7_sh {high7_sh:.2f}')
        if not wild_sh_ok: fails.append(f'wld_sh {wild_sh:.3f}')
        print(f"    FAIL: {fails}")
    return margs, prof


# W1: dd reduced (cube ~0.9x m1)
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.55, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.30, '2bar': 0.1353*1.30, '3bar': 0.0729*1.30,
      'high7': 0.0571*1.85, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.4, '1bar': 0.1349*1.95, '2bar': 0.1099*1.95, '3bar': 0.0549*1.95,
      'high7': 0.0470*2.40, 'doublediamond': 0.0240*1.10, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('W1_dd_modest', r1, r2, r3)

# W2: cherry strong
r1 = {'cherry': 0.04*2.0, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.50, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*2.2, '1bar': 0.1651*1.30, '2bar': 0.1353*1.30, '3bar': 0.0729*1.30,
      'high7': 0.0571*1.80, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.8, '1bar': 0.1349*1.85, '2bar': 0.1099*1.85, '3bar': 0.0549*1.85,
      'high7': 0.0470*2.30, 'doublediamond': 0.0240*1.10, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('W2_cherry_strong', r1, r2, r3)

# W3: cherry+h7 balanced
r1 = {'cherry': 0.04*1.9, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.55, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*2.0, '1bar': 0.1651*1.25, '2bar': 0.1353*1.25, '3bar': 0.0729*1.25,
      'high7': 0.0571*1.85, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.6, '1bar': 0.1349*1.85, '2bar': 0.1099*1.85, '3bar': 0.0549*1.85,
      'high7': 0.0470*2.40, 'doublediamond': 0.0240*1.05, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('W3_balanced', r1, r2, r3)

# W4: same as V2 but dd lower
r1 = {'cherry': 0.04*1.4, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.55, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.6, '1bar': 0.1651*1.30, '2bar': 0.1353*1.30, '3bar': 0.0729*1.30,
      'high7': 0.0571*1.85, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.2, '1bar': 0.1349*1.95, '2bar': 0.1099*1.95, '3bar': 0.0549*1.95,
      'high7': 0.0470*2.40, 'doublediamond': 0.0240*1.10, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('W4_V2_dd_low', r1, r2, r3)

# W5: cherry centered + bars + h7 strong
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.60, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.30, '2bar': 0.1353*1.30, '3bar': 0.0729*1.30,
      'high7': 0.0571*1.90, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.5, '1bar': 0.1349*1.90, '2bar': 0.1099*1.90, '3bar': 0.0549*1.90,
      'high7': 0.0470*2.50, 'doublediamond': 0.0240*1.05, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('W5_h7_strong', r1, r2, r3)

# W6: trigger 3.0 variant
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.60, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.30, '2bar': 0.1353*1.30, '3bar': 0.0729*1.30,
      'high7': 0.0571*1.90, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.5, '1bar': 0.1349*1.90, '2bar': 0.1099*1.90, '3bar': 0.0549*1.90,
      'high7': 0.0470*2.50, 'doublediamond': 0.0240*1.05, 'topdollar': 0.0112*2.7, 'jackpot': 0.003}
check('W6_trig300', r1, r2, r3)

# W7: trigger 3.1
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.60, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.30, '2bar': 0.1353*1.30, '3bar': 0.0729*1.30,
      'high7': 0.0571*1.90, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.5, '1bar': 0.1349*1.90, '2bar': 0.1099*1.90, '3bar': 0.0549*1.90,
      'high7': 0.0470*2.50, 'doublediamond': 0.0240*1.05, 'topdollar': 0.0112*2.80, 'jackpot': 0.003}
check('W7_trig313', r1, r2, r3)

# W8: balanced with h7 1.5/1.8/2.4 (less aggressive)
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.50, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.30, '2bar': 0.1353*1.30, '3bar': 0.0729*1.30,
      'high7': 0.0571*1.80, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.5, '1bar': 0.1349*1.90, '2bar': 0.1099*1.90, '3bar': 0.0549*1.90,
      'high7': 0.0470*2.40, 'doublediamond': 0.0240*1.05, 'topdollar': 0.0112*2.85, 'jackpot': 0.003}
check('W8_h7_milder', r1, r2, r3)

# W9: balanced - 295pp target
r1 = {'cherry': 0.04*1.7, '1bar': 0.2019*1.10, '2bar': 0.1648*1.10, '3bar': 0.1032*1.10,
      'high7': 0.0720*1.55, 'doublediamond': 0.0290*1.0, 'jackpot': 0.004}
r2 = {'cherry': 0.035*1.9, '1bar': 0.1651*1.30, '2bar': 0.1353*1.30, '3bar': 0.0729*1.30,
      'high7': 0.0571*1.85, 'doublediamond': 0.0280*0.95, 'jackpot': 0.004}
r3 = {'cherry': 0.025*2.5, '1bar': 0.1349*1.90, '2bar': 0.1099*1.90, '3bar': 0.0549*1.90,
      'high7': 0.0470*2.45, 'doublediamond': 0.0240*1.05, 'topdollar': 0.0112*2.80, 'jackpot': 0.003}
check('W9_295target', r1, r2, r3)
