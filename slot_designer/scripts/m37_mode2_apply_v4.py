"""Apply M37 mode 2 v4 — HIER-preserved hit-cut (user-accepted 2026-05-07).

Config: sw=0.15 sLB=2.5 sHB=0.5 sGr=3.0 sBoost=0.95 sR2H7=0.5 sR2bk=0.85
With blank-floor constraint enforced (no degenerate reels).
Result: RTP ≈297.82, hit ≈32.40, hier preserved, 500+ ≈4.25.
"""
import sys
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.scripts.redistribute_m37_blanks import redistribute_one_mode


def jload(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


strips = jload(_ROOT / 'slot_designer/weights/M37/reel_strips.json')['reels']
m2 = jload(_ROOT / 'slot_designer/weights/M37/mode_2/weights.json')


def positions(reel_idx, sym):
    return [i for i, s in enumerate(strips[reel_idx]) if s == sym]


def make_weights(s_wild, s_R1R3_lowbars, s_R1R3_highbars,
                 s_R2_grand, s_booster_uniform, s_R2_high7, s_R2_blank,
                 blank_floor_pct=15.0):
    new_R1 = list(m2['weights'][0])
    new_R3 = list(m2['weights'][2])
    new_R2 = list(m2['weights'][1])
    for reel_idx, weights in [(0, new_R1), (2, new_R3)]:
        wild_pos = positions(reel_idx, 'wild')
        blank_pos = positions(reel_idx, 'blank')
        lowbars_pos = positions(reel_idx, '1bar') + positions(reel_idx, '2bar')
        highbars_pos = positions(reel_idx, '3bar') + positions(reel_idx, '7bar')
        old_w = sum(weights[i] for i in wild_pos)
        new_wt = max(1, int(round(old_w * s_wild)))
        freed = old_w - new_wt
        wild_per = new_wt // len(wild_pos)
        for j, i in enumerate(wild_pos):
            weights[i] = wild_per + (1 if j < (new_wt - wild_per * len(wild_pos)) else 0)
        be = freed // len(blank_pos)
        for j, i in enumerate(blank_pos):
            weights[i] += be + (1 if j < (freed - be * len(blank_pos)) else 0)
        added = 0
        for sym_pos, scale in [(lowbars_pos, s_R1R3_lowbars), (highbars_pos, s_R1R3_highbars)]:
            if scale != 1.0:
                old = sum(weights[i] for i in sym_pos)
                new = int(round(old * scale))
                added += new - old
                for i in sym_pos:
                    weights[i] = max(1, int(round(weights[i] * scale)))
        non_blank_w = sum(weights[i] for i in range(len(weights)) if i not in blank_pos)
        floor = blank_floor_pct / 100
        min_blank = max(len(blank_pos), int(round(floor * non_blank_w / (1 - floor))))
        cur_blank = sum(weights[i] for i in blank_pos)
        if cur_blank < min_blank:
            raise ValueError("Initial blank already under floor")
        max_cut = cur_blank - min_blank
        if added > max_cut:
            raise ValueError(f"Added {added} > max_cut {max_cut} — would violate blank floor")
        if added > 0:
            blank_total = cur_blank
            for i in blank_pos:
                cut = int(round(weights[i] * added / blank_total))
                weights[i] = max(1, weights[i] - cut)
        elif added < 0:
            blank_total = cur_blank
            for i in blank_pos:
                weights[i] += int(round(weights[i] * (-added) / blank_total))
    for sym, scale in [('grand', s_R2_grand), ('major', s_booster_uniform),
                       ('minor', s_booster_uniform), ('mini', s_booster_uniform),
                       ('high7', s_R2_high7), ('blank', s_R2_blank)]:
        for i in positions(1, sym):
            new_R2[i] = max(1, int(round(new_R2[i] * scale)))
    new_w = [new_R1, new_R2, new_R3]
    new_w = redistribute_one_mode(strips, new_w, 2)
    return new_w


# Apply config
new_w = make_weights(
    s_wild=0.15, s_R1R3_lowbars=2.5, s_R1R3_highbars=0.5,
    s_R2_grand=3.0, s_booster_uniform=0.95, s_R2_high7=0.5, s_R2_blank=0.85
)

m2['weights'] = new_w
m2['_notes'] = [
    "M37 mode 2 v4 (HIER-preserved hit-cut — user-accepted 2026-05-07).",
    "Strategy A pareto-min: hit ≤30 hard cap is structurally infeasible at RTP=300 with sane reel + R1≥R3 + hier (m37_mode2_math_proof.py).",
    "Min achievable hit at sane structure ≈ 32.40% (vs baseline 44.98%, -12.6pp).",
    "Knobs: sw=0.15 (wild ×0.15→2.2%), sLB=2.5 (1bar+2bar boost ×2.5), sHB=0.5 (3bar+7bar cut ×0.5),",
    "sGr=3.0 (R2 grand ×3 → ~0.44% feeds ge200-500 via low_bar×grand path),",
    "sBoost=0.95 (mini/minor/major uniform ×0.95 — preserves 倒金字塔 hier 1.34/1.36/13.2),",
    "sR2H7=0.5 (R2 high7 ×0.5 → cuts (high7,grand,high7)=1000× freq), sR2bk=0.85 (R2 blank shrink for RTP target).",
    "Targets: theoretical RTP 297.82%, hit 32.40%, ge500+ 4.25% (≤ baseline 4.28%).",
    "Shape pivot: peak at ge20-50 (19.9), strong ge200-500 (11.0%), valley at ge50-100 (3.8% — line_3_same(7bar) collapsed by 7bar cut).",
    "Booster mass 24.55% (close to baseline 23%) — preserves fuel for mode 5 grand-amplification path.",
    "M37 mode 2 - RTP-neutral Blank redistribution applied (mechanism B per Section 15).",
    "  ratio T1:T2:T3:T4 = 5:4:2:1 (lucky tilt)",
]

with open(_ROOT / 'slot_designer/weights/M37/mode_2/weights.json', 'w', encoding='utf-8') as f:
    json.dump(m2, f, indent=2)
print('Mode 2 v4 written.')

# Validate
from slot_designer.engine.loader import load_engine
from slot_designer.devtools.analytic_rtp import analytic_profile
eng, _ = load_engine(
    spec_path=_ROOT / 'slot_designer/specs/M37.spec.json',
    strips_path=_ROOT / 'slot_designer/weights/M37/reel_strips.json',
    weights_path=_ROOT / 'slot_designer/weights/M37/mode_2/weights.json',
)
prof = analytic_profile(eng)
R2_t = sum(new_w[1])
print(f'\nValidate:')
print(f'  RTP={prof["rtp_pct"]:.3f}%  hit={prof["hit_rate"]*100:.3f}%')
for ri, label in [(0, 'R1'), (1, 'R2'), (2, 'R3')]:
    total = sum(new_w[ri])
    blank = sum(new_w[ri][p] for p in positions(ri, 'blank')) / total * 100
    print(f'  {label} blank={blank:.2f}%')
mini_m = sum(new_w[1][i] for i in positions(1, 'mini')) / R2_t * 100
minor_m = sum(new_w[1][i] for i in positions(1, 'minor')) / R2_t * 100
major_m = sum(new_w[1][i] for i in positions(1, 'major')) / R2_t * 100
grand_m = sum(new_w[1][i] for i in positions(1, 'grand')) / R2_t * 100
print(f'  R2 booster: mini={mini_m:.2f}% minor={minor_m:.2f}% major={major_m:.2f}% grand={grand_m:.4f}%')
print(f'  hier: mini/minor={mini_m/minor_m:.2f} minor/major={minor_m/major_m:.2f} major/grand={major_m/grand_m:.2f}')
