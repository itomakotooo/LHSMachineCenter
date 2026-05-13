"""Inspect winning candidates from search6."""
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


def build(cherry, bar1, bar2, bar3, h7, dd, td_r3):
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


def inspect(label, cherry_taper, cherry_R3, h7_taper, h7_R3, bar_taper, bar_R3, dd_R1, dd_R3, td):
    cherry_R1 = cherry_R3 * cherry_taper
    cherry_R2 = (cherry_R1 + cherry_R3) / 2
    bar_R1 = bar_R3 * bar_taper
    bar_R2 = (bar_R1 + bar_R3) / 2
    h7_R1 = h7_R3 * h7_taper
    h7_R2 = (h7_R1 + h7_R3) / 2
    dd_R2 = (dd_R1 + dd_R3) / 2
    r1, r2, r3 = build(
        cherry=(cherry_R1, cherry_R2, cherry_R3),
        bar1=(bar_R1, bar_R2, bar_R3),
        bar2=(bar_R1, bar_R2, bar_R3),
        bar3=(bar_R1, bar_R2, bar_R3),
        h7=(h7_R1, h7_R2, h7_R3),
        dd=(dd_R1, dd_R2, dd_R3),
        td_r3=td,
    )
    margs = [normalize(r1), normalize(r2), normalize(r3)]
    prof = analytic_profile_from_marginals(EV, margs)
    base = prof['rtp_pct']
    feat_rtp = td*0.0112 * M2_EV * 100
    tot = base + feat_rtp
    print(f"\n=== {label} ===")
    print(f"Total RTP: {tot:.3f}pp (base {base:.3f}pp + feature {feat_rtp:.3f}pp)")
    print(f"Margin to band [290, 310]: floor +{tot-290:.2f}pp, ceil +{310-tot:.2f}pp")
    print(f"Hit: {prof['hit_rate']*100:.3f}%   Trigger: {td*0.0112*100:.3f}%")
    print(f"Per-reel marginals (%):")
    for i, m in enumerate(margs):
        line = f"  R{i+1}: " + " ".join(f"{s}={v*100:.3f}" for s, v in sorted(m.items()))
        print(f"{line}   sum={sum(m.values())*100:.6f}")
    print(f"\nPer-pay-id:")
    for pid in sorted(prof['pay_hits'].keys(), key=int):
        p = prof['pay_hits'][pid]
        rtp = prof['pay_rtp'][pid] * 100
        fam = PAY_FAM.get(pid, '?')
        print(f"  pay_id {pid} ({fam}): P={p*100:.5f}% RTP={rtp:.4f}pp 1/{1/p:.0f}")
    print(f"\nHierarchy:")
    b1 = prof['pay_hits']['7']
    b2 = prof['pay_hits']['5']
    b3 = prof['pay_hits']['3']
    c1 = prof['pay_hits']['9']
    c2 = prof['pay_hits']['71']
    c3 = prof['pay_hits']['4']
    h7w = prof['pay_hits']['2']
    h7p = prof['pay_hits']['21']
    print(f"  Bar §1: P(b1) {b1*100:.4f}% > P(b2) {b2*100:.4f}% > P(b3) {b3*100:.4f}%   "
          f"{'PASS' if b1>b2>b3 else 'FAIL'}")
    print(f"  Cherry: P(c1) {c1*100:.4f}% >= P(c2) {c2*100:.4f}% >= P(c3) {c3*100:.4f}%   "
          f"{'PASS' if c1>=c2-1e-3 and c2>=c3-1e-3 else 'FAIL'}")
    print(f"  H7: P(h7w) {h7w*100:.4f}% >= P(h7p) {h7p*100:.4f}% (tol 0.10pp)   "
          f"{'PASS' if h7w>=h7p-0.001 else 'FAIL'} (diff {(h7p-h7w)*100:.4f}pp)")
    print(f"\nFamily shares (of base RTP {base:.2f}pp):")
    fam_pp = {}
    for pid, rtp in prof['pay_rtp'].items():
        fam = PAY_FAM.get(pid)
        if fam:
            fam_pp[fam] = fam_pp.get(fam, 0) + rtp * 100
    for fam in sorted(fam_pp, key=lambda k: -fam_pp[k]):
        sh = fam_pp[fam]/base*100
        print(f"  {fam:<12} {sh:6.2f}%   {fam_pp[fam]:6.3f}pp")
    h7_combined = fam_pp.get('high7_wild',0) + fam_pp.get('high7_pure',0)
    print(f"  {'high7':<12} {h7_combined/base*100:6.2f}%   {h7_combined:6.3f}pp")
    print(f"\nWild_pure: P={prof['pay_hits']['1']*100:.5f}% 1/{1/prof['pay_hits']['1']:.0f}  "
          f"ratio m2/m1={prof['pay_hits']['1']/M1_PWILD:.3f}")
    p_r1k = td*0.0112 * M2_P_R1000_PER_TRIG
    print(f"P(R>=1000)/spin: {p_r1k:.3e}")
    return margs, prof


# Top candidates from search6
inspect("CANDIDATE_A (best center)", cherry_taper=0.80, cherry_R3=2.0,
        h7_taper=0.65, h7_R3=2.6, bar_taper=0.60, bar_R3=1.8,
        dd_R1=0.95, dd_R3=0.85, td=2.95)

inspect("CANDIDATE_B (highest score)", cherry_taper=0.70, cherry_R3=2.4,
        h7_taper=0.65, h7_R3=2.6, bar_taper=0.55, bar_R3=1.8,
        dd_R1=1.00, dd_R3=0.75, td=2.95)

inspect("CANDIDATE_C (alt 296)", cherry_taper=0.80, cherry_R3=2.0,
        h7_taper=0.65, h7_R3=2.6, bar_taper=0.55, bar_R3=1.9,
        dd_R1=0.95, dd_R3=0.85, td=2.95)
