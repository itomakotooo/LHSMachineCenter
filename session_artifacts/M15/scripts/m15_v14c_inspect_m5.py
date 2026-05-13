"""Inspect m5 winning candidates."""
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
M5_EV = 123.33
M5_P_R1000_PER_TRIG = 3.3279e-6

# Mode 2 winner (CANDIDATE_A):
M2_MARGS = [
    {'1bar': 0.21805, '2bar': 0.17798, '3bar': 0.11146, 'blank': 0.27528,
     'cherry': 0.064, 'doublediamond': 0.02755, 'high7': 0.12168, 'jackpot': 0.004},
    {'1bar': 0.23774, '2bar': 0.19483, '3bar': 0.10498, 'blank': 0.24777,
     'cherry': 0.063, 'doublediamond': 0.02520, 'high7': 0.12248, 'jackpot': 0.004},
    {'1bar': 0.24282, '2bar': 0.19782, '3bar': 0.09882, 'blank': 0.23190,
     'cherry': 0.05, 'doublediamond': 0.02040, 'high7': 0.12220, 'topdollar': 0.03304,
     'jackpot': 0.003},
]


def m5_from_m2(*, dd_lift, td_lift, cherry_lift, bar_lift, h7_lift):
    def to_tuple(s):
        return s if isinstance(s, (tuple, list)) else (s, s, s)
    dl = to_tuple(dd_lift)
    tl = to_tuple(td_lift)
    cl = to_tuple(cherry_lift)
    bl = to_tuple(bar_lift)
    hl = to_tuple(h7_lift)
    new_margs = []
    for r_idx, m in enumerate(M2_MARGS):
        new = {}
        for sym, mg in m.items():
            if sym == 'blank':
                continue
            elif sym == 'doublediamond':
                new[sym] = mg * dl[r_idx]
            elif sym == 'topdollar':
                new[sym] = mg * tl[r_idx]
            elif sym == 'cherry':
                new[sym] = mg * cl[r_idx]
            elif sym in ('1bar', '2bar', '3bar'):
                new[sym] = mg * bl[r_idx]
            elif sym == 'high7':
                new[sym] = mg * hl[r_idx]
            else:
                new[sym] = mg
        new_margs.append(normalize(new))
    return new_margs


def inspect(label, **lifts):
    margs = m5_from_m2(**lifts)
    prof = analytic_profile_from_marginals(EV, margs)
    base = prof['rtp_pct']
    trig = margs[2].get('topdollar', 0)
    feat_rtp = trig * M5_EV * 100
    tot = base + feat_rtp
    p_r1k = trig * M5_P_R1000_PER_TRIG

    print(f"\n=== {label} ===")
    print(f"Total RTP: {tot:.3f}pp (base {base:.3f}pp + feature {feat_rtp:.3f}pp)")
    print(f"Margin to band [490, 510]: floor +{tot-490:.2f}pp, ceil +{510-tot:.2f}pp")
    print(f"Hit: {prof['hit_rate']*100:.3f}%   Trigger: {trig*100:.3f}%")
    print(f"P(R>=1000)/spin: {p_r1k:.3e}")
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
    b1 = prof['pay_hits']['7']; b2 = prof['pay_hits']['5']; b3 = prof['pay_hits']['3']
    c1 = prof['pay_hits']['9']; c2 = prof['pay_hits']['71']; c3 = prof['pay_hits']['4']
    h7w = prof['pay_hits']['2']; h7p = prof['pay_hits']['21']
    print(f"\nHierarchy:")
    print(f"  Bar §1: P(b1) {b1*100:.4f}% > P(b2) {b2*100:.4f}% > P(b3) {b3*100:.4f}%   "
          f"{'PASS' if b1>b2>b3 else 'FAIL'}")
    print(f"  Cherry: P(c1) {c1*100:.4f}% >= P(c2) {c2*100:.4f}% >= P(c3) {c3*100:.4f}%   "
          f"{'PASS' if c1>=c2-1e-3 and c2>=c3-1e-3 else 'FAIL'}")
    print(f"  H7: P(h7w) {h7w*100:.4f}% >= P(h7p) {h7p*100:.4f}% (tol 0.10pp)   "
          f"{'PASS' if h7w>=h7p-0.001 else 'FAIL'} (diff {(h7p-h7w)*100:.4f}pp)")
    fam_pp = {}
    for pid, rtp in prof['pay_rtp'].items():
        fam = PAY_FAM.get(pid)
        if fam: fam_pp[fam] = fam_pp.get(fam, 0) + rtp * 100
    print(f"\nFamily shares (of base RTP {base:.2f}pp):")
    for fam in sorted(fam_pp, key=lambda k: -fam_pp[k]):
        sh = fam_pp[fam]/base*100
        print(f"  {fam:<12} {sh:6.2f}%   {fam_pp[fam]:6.3f}pp")
    h7_combined = fam_pp.get('high7_wild',0) + fam_pp.get('high7_pure',0)
    print(f"  {'high7':<12} {h7_combined/base*100:6.2f}%   {h7_combined:6.3f}pp")
    wld_m5_m2 = prof['pay_hits']['1'] / 1.4203e-5  # M2 winner pwild = 1.42e-5
    print(f"\nWild_pure: P={prof['pay_hits']['1']*100:.5f}% 1/{1/prof['pay_hits']['1']:.0f}  "
          f"ratio m5/m2={wld_m5_m2:.3f} (need >=1.1)")
    print(f"R1 blank {margs[0]['blank']*100:.2f}% >= R3 blank {margs[2]['blank']*100:.2f}%: "
          f"{'PASS' if margs[0]['blank']>=margs[2]['blank'] else 'FAIL'}")
    return margs, prof


# Top candidate from search
print("Inspecting top mode-5 candidates...")
inspect("M5_TOP (dd1.05-1.15-1.10/td1.0/c0.95/b0.95/h1.0)",
        dd_lift=(1.05, 1.15, 1.10), td_lift=1.0, cherry_lift=0.95, bar_lift=0.95, h7_lift=1.0)

inspect("M5_ALT_HIGH7 (dd1.05-1.05-1.10/td1.0/c1.0/b0.95/h1.0)",
        dd_lift=(1.05, 1.05, 1.10), td_lift=1.0, cherry_lift=1.0, bar_lift=0.95, h7_lift=1.0)

inspect("M5_DD_STRONG (dd1.20-1.15-1.10/td1.0/c1.0/b0.95/h0.9)",
        dd_lift=(1.20, 1.15, 1.10), td_lift=1.0, cherry_lift=1.0, bar_lift=0.95, h7_lift=0.9)

inspect("M5_DD_MODEST (dd1.05-1.05-1.05/td1.0/c1.0/b0.95/h1.02)",
        dd_lift=(1.05, 1.05, 1.05), td_lift=1.0, cherry_lift=1.0, bar_lift=0.95, h7_lift=1.02)
