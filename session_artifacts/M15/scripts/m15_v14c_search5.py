"""Mode 2 search round 5: systematic grid search with adjusted h7 levels.
   Pin dd cube ~0.80x m1 (wild_pure share at cap-edge ~0.30%).
   Vary h7 lift, bar lift, cherry lift to find feasible region."""
import sys, json, itertools
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


def evaluate(r1, r2, r3):
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
    bar_mixed_sh = fam_pp.get('bar_mixed', 0) / base * 100 if base else 0

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
    return {
        'tot': tot, 'base': base, 'hit': hit, 'pwild': pwild, 'h7w': h7w, 'h7p': h7p,
        'b1': b1, 'b2': b2, 'b3': b3, 'c1': c1, 'c2': c2, 'c3': c3,
        'cherry1_sh': cherry1_sh, 'high7_sh': high7_sh, 'wild_sh': wild_sh,
        'bar3_sh': bar3_sh, 'bar_mixed_sh': bar_mixed_sh,
        'r1_bl': margs[0]['blank']*100, 'r3_bl': margs[2]['blank']*100,
        'all_ok': all_ok, 'margs': margs, 'prof': prof,
        'rtp_ok': rtp_ok, 'hit_ok': hit_ok, 'r1r3_ok': r1r3_ok, 'wld_ratio_ok': wld_ratio_ok,
        'h7_ok': h7_ok, 'cherry1_sh_ok': cherry1_sh_ok, 'high7_sh_ok': high7_sh_ok,
        'wild_sh_ok': wild_sh_ok, 'bar_ok': bar_ok,
        'fail_count': sum(1 for k in ['rtp_ok','hit_ok','r1r3_ok','wld_ratio_ok','h7_ok',
                                       'cherry1_sh_ok','high7_sh_ok','wild_sh_ok','bar_ok']
                          if not locals().get(k)),
    }


# Build candidate from lift dict
def build(cherry, bar1, bar2, bar3, h7, dd, td_r3):
    """Each is (R1, R2, R3) lift factor."""
    r1 = {'cherry': 0.04*cherry[0], '1bar': 0.2019*bar1[0], '2bar': 0.1648*bar2[0],
          '3bar': 0.1032*bar3[0], 'high7': 0.0720*h7[0], 'doublediamond': 0.0290*dd[0],
          'jackpot': 0.004}
    r2 = {'cherry': 0.035*cherry[1], '1bar': 0.1651*bar1[1], '2bar': 0.1353*bar2[1],
          '3bar': 0.0729*bar3[1], 'high7': 0.0571*h7[1], 'doublediamond': 0.0280*dd[1],
          'jackpot': 0.004}
    r3 = {'cherry': 0.025*cherry[2], '1bar': 0.1349*bar1[2], '2bar': 0.1099*bar2[2],
          '3bar': 0.0549*bar3[2], 'high7': 0.0470*h7[2], 'doublediamond': 0.0240*dd[2],
          'topdollar': 0.0112*td_r3, 'jackpot': 0.003}
    return r1, r2, r3


# Grid search
candidates = []
counter = 0
for cherry_R3 in [2.0, 2.2, 2.4, 2.6, 2.8]:
    for h7_R3 in [2.2, 2.4, 2.5, 2.6]:
        for bar_R3 in [1.5, 1.6, 1.7, 1.8, 1.9]:
            for dd_R3 in [0.55, 0.70, 0.85]:
                for td in [2.7, 2.85, 2.95]:
                    counter += 1
                    cherry_R1 = cherry_R3 * 0.75  # taper R1
                    cherry_R2 = (cherry_R1 + cherry_R3) / 2
                    bar_R1 = bar_R3 * 0.55
                    bar_R2 = (bar_R1 + bar_R3) / 2
                    h7_R1 = h7_R3 * 0.62
                    h7_R2 = (h7_R1 + h7_R3) / 2
                    dd_R1 = 1.00
                    dd_R2 = 0.95
                    r1, r2, r3 = build(
                        cherry=(cherry_R1, cherry_R2, cherry_R3),
                        bar1=(bar_R1, bar_R2, bar_R3),
                        bar2=(bar_R1, bar_R2, bar_R3),
                        bar3=(bar_R1, bar_R2, bar_R3),
                        h7=(h7_R1, h7_R2, h7_R3),
                        dd=(dd_R1, dd_R2, dd_R3),
                        td_r3=td,
                    )
                    res = evaluate(r1, r2, r3)
                    label = f"c{cherry_R3:.1f}_h7R3{h7_R3:.1f}_bR3{bar_R3:.1f}_ddR3{dd_R3:.2f}_td{td:.2f}"
                    if res['all_ok']:
                        candidates.append((label, res, (r1, r2, r3)))


print(f"Total candidates tested: {counter}")
print(f"Passing candidates: {len(candidates)}")

# Top 20 by RTP-centeredness (closest to 300)
candidates.sort(key=lambda c: abs(c[1]['tot'] - 300))
for label, res, _ in candidates[:30]:
    print(f"  PASS {label}: tot={res['tot']:.2f} base={res['base']:.2f} hit={res['hit']*100:.2f}% "
          f"c1={res['cherry1_sh']:.1f} h7={res['high7_sh']:.1f} wsh={res['wild_sh']:.3f} "
          f"R1bl={res['r1_bl']:.1f} R3bl={res['r3_bl']:.1f}")
