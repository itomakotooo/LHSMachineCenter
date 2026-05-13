"""Find m5 candidate satisfying m5 hit >= m2 hit (LUCKY-MONO strict)."""
import sys, json
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))
from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine

_M15 = _ROOT / 'slot_designer' / 'machines' / 'M15'
engine, _ = load_engine(_M15 / 'spec.json', _M15 / 'weights' / 'mode_1' / 'weights.json', strips_path=_M15 / 'reel_strips.json')
EV = engine.evaluator
M5_EV = 123.33
M5_P_R1000 = 3.3279e-6


def norm(m):
    out = dict(m)
    nb = sum(v for k, v in out.items() if k != 'blank')
    out['blank'] = max(0, 1-nb)
    return out


# M2 winner CANDIDATE_A marginals
M2 = [
    {'cherry': 0.064, '1bar': 0.21805, '2bar': 0.17798, '3bar': 0.11146, 'high7': 0.12168, 'doublediamond': 0.02755, 'jackpot': 0.004},
    {'cherry': 0.063, '1bar': 0.23774, '2bar': 0.19483, '3bar': 0.10498, 'high7': 0.12248, 'doublediamond': 0.02520, 'jackpot': 0.004},
    {'cherry': 0.05, '1bar': 0.24282, '2bar': 0.19782, '3bar': 0.09882, 'high7': 0.12220, 'doublediamond': 0.02040, 'topdollar': 0.03304, 'jackpot': 0.003},
]
M2 = [norm(m) for m in M2]
m2_prof = analytic_profile_from_marginals(EV, M2)
M2_hit = m2_prof['hit_rate']
M2_pwild = m2_prof['pay_hits']['1']
M2_base = m2_prof['rtp_pct']
print(f"M2: base={M2_base:.3f}pp hit={M2_hit*100:.3f}% pwild={M2_pwild*100:.5f}%")


candidates = []
for c_lift_R1 in [1.00, 1.02, 1.03, 1.05]:
    for c_lift_R3 in [1.00, 1.02, 1.03, 1.05]:
        for b_lift_R1 in [1.00, 1.02, 1.03, 1.05]:
            for b_lift_R3 in [1.00, 1.02, 1.03, 1.05]:
                for dd_R1 in [0.90, 0.95, 1.0, 1.05]:
                    for dd_R2 in [1.0, 1.05, 1.10, 1.15]:
                        for dd_R3 in [1.0, 1.05, 1.10]:
                            for h_lift in [0.92, 0.95, 0.97, 1.0]:
                                # Construct new margs
                                new = []
                                for r_idx, m in enumerate(M2):
                                    n = {}
                                    c_lift = [c_lift_R1, (c_lift_R1+c_lift_R3)/2, c_lift_R3][r_idx]
                                    b_lift = [b_lift_R1, (b_lift_R1+b_lift_R3)/2, b_lift_R3][r_idx]
                                    dd_l = [dd_R1, dd_R2, dd_R3][r_idx]
                                    for sym, mg in m.items():
                                        if sym == 'blank':
                                            continue
                                        if sym == 'doublediamond':
                                            n[sym] = mg * dd_l
                                        elif sym == 'cherry':
                                            n[sym] = mg * c_lift
                                        elif sym in ('1bar', '2bar', '3bar'):
                                            n[sym] = mg * b_lift
                                        elif sym == 'high7':
                                            n[sym] = mg * h_lift
                                        else:
                                            n[sym] = mg
                                    new.append(norm(n))
                                prof = analytic_profile_from_marginals(EV, new)
                                base = prof['rtp_pct']
                                hit = prof['hit_rate']
                                pwild = prof['pay_hits'].get('1', 0)
                                trig = new[2].get('topdollar', 0)
                                tot = base + trig * M5_EV * 100
                                b1 = prof['pay_hits'].get('7', 0)
                                b2 = prof['pay_hits'].get('5', 0)
                                b3 = prof['pay_hits'].get('3', 0)
                                h7w = prof['pay_hits'].get('2', 0)
                                h7p = prof['pay_hits'].get('21', 0)
                                c1 = prof['pay_hits'].get('9', 0)
                                c2 = prof['pay_hits'].get('71', 0)
                                c3 = prof['pay_hits'].get('4', 0)
                                # All constraints
                                fam_pp = {}
                                for pid, rtp in prof['pay_rtp'].items():
                                    famap = {'9': 'cherry1', '71': 'cherry2', '4': 'cherry3', '1': 'wild_pure',
                                             '2': 'high7_wild', '21': 'high7_pure', '3': 'bar3', '5': 'bar2',
                                             '7': 'bar1', '8': 'bar_mixed'}
                                    fam = famap.get(pid)
                                    if fam:
                                        fam_pp[fam] = fam_pp.get(fam, 0) + rtp * 100
                                bar3_sh = fam_pp.get('bar3', 0) / base * 100 if base else 0
                                ok = (
                                    491.5 <= tot <= 508.5 and
                                    0.30 <= hit <= 0.35 and
                                    hit >= M2_hit - 1e-9 and
                                    pwild/M2_pwild >= 1.1 and
                                    b1 > b2 > b3 and
                                    c1 >= c2 - 0.001 and c2 >= c3 - 0.001 and
                                    h7w >= h7p - 0.001 and
                                    new[0]['blank'] >= new[2]['blank'] and
                                    trig * M5_P_R1000 <= 1e-5 and
                                    all(m.get('jackpot', 0) <= 0.006 for m in new) and
                                    5.0 <= bar3_sh <= 22.0
                                )
                                if ok:
                                    candidates.append({
                                        'label': f"c{c_lift_R1:.2f}-{c_lift_R3:.2f}_b{b_lift_R1:.2f}-{b_lift_R3:.2f}_dd{dd_R1:.2f}-{dd_R2:.2f}-{dd_R3:.2f}_h{h_lift:.2f}",
                                        'tot': tot, 'hit': hit, 'pwild': pwild, 'base': base,
                                        'wld_m5_m2': pwild/M2_pwild, 'r1_bl': new[0]['blank']*100,
                                        'r3_bl': new[2]['blank']*100, 'margs': new,
                                        'b1': b1, 'b2': b2, 'b3': b3, 'h7w': h7w, 'h7p': h7p,
                                    })


print(f"Total m5 candidates with hit >= m2: {len(candidates)}")

# Sort by RTP centered + hit closer to m2
def score(c):
    rtp_margin = min(c['tot'] - 490, 510 - c['tot'])
    return rtp_margin - abs(c['hit'] - M2_hit) * 100

candidates.sort(key=lambda c: -score(c))
print()
print("Top 20 m5 candidates:")
for c in candidates[:20]:
    print(f"  {c['label']}: tot={c['tot']:.2f} hit={c['hit']*100:.2f}% (m2 hit was {M2_hit*100:.2f}%) "
          f"wld_m5/m2={c['wld_m5_m2']:.3f} R1bl={c['r1_bl']:.1f} R3bl={c['r3_bl']:.1f}")
