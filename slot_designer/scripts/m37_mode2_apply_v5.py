"""Apply M37 mode 2 v5 — balanced bars (user-accepted 2026-05-07).

User feedback: B2 chosen (most balanced bars, peak shifts to ge100-200).
Config: sw=0.10 sLB=1.6 sHB=1.40 sGr=3.5 sBoost=0.95 sR2H7=0.5 sR2bk=0.80
Result: RTP 299.88, hit 32.31, bar ratio 1.32× (was 6.6× in v4).

Scales from 39f0bd3 (v3 baseline — pre-archetype-pivot natural balance).
"""
import sys
import json
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.scripts.redistribute_m37_blanks import redistribute_one_mode


def jload(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


strips = jload(_ROOT / 'slot_designer/weights/M37/reel_strips.json')['reels']

# Scale from v3 baseline (39f0bd3 — bars naturally balanced ~1.16×)
git_base = subprocess.run(
    ['git', 'show', '39f0bd3:slot_designer/weights/M37/mode_2/weights.json'],
    capture_output=True, text=True, encoding='utf-8',
)
m2_base = json.loads(git_base.stdout)


def positions(reel_idx, sym):
    return [i for i, s in enumerate(strips[reel_idx]) if s == sym]


def make_weights(s_wild, s_R1R3_lowbars, s_R1R3_highbars,
                 s_R2_grand, s_booster_uniform, s_R2_high7, s_R2_blank,
                 blank_floor_pct=15.0):
    new_R1 = list(m2_base['weights'][0])
    new_R3 = list(m2_base['weights'][2])
    new_R2 = list(m2_base['weights'][1])
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
            raise ValueError("blank under floor")
        max_cut = cur_blank - min_blank
        if added > max_cut:
            raise ValueError(f"would violate blank floor")
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


# B2 config
new_w = make_weights(
    s_wild=0.10, s_R1R3_lowbars=1.6, s_R1R3_highbars=1.40,
    s_R2_grand=3.5, s_booster_uniform=0.95, s_R2_high7=0.5, s_R2_blank=0.80
)

m2_base['weights'] = new_w
m2_base['_notes'] = [
    "M37 mode 2 v5 (balanced-bars — user-accepted 2026-05-07).",
    "Replaces v4's heavily skewed bars (1bar 29.8% / 7bar 4.4% — ratio 6.6×) with",
    "natural balance (1bar 19.1% / 7bar 12.3% — ratio 1.32×). Trade-off: ge500+ tail",
    "share grows from 4.25% to 8.53% (peak shifts from ge20-50 → ge100-200).",
    "Knobs scale from 39f0bd3 v3 baseline (natural bar 11.92/11.30/11.30/8.79):",
    "  sw=0.10 (wild ×0.10 → 1.5%) — kills side_wild_alone elephant",
    "  sLB=1.6 (1bar+2bar moderate boost), sHB=1.40 (3bar+7bar moderate boost)",
    "  sGr=3.5 (R2 grand ×3.5 → 0.59%) — anchors ge100-200 + ge500+ via line×grand",
    "  sBoost=0.95 (booster ×0.95 — 倒金字塔 hier preserved 1.34/1.36/8.0)",
    "  sR2H7=0.5 (R2 high7 ×0.5 → caps (h7,grand,h7)=1000× freq)",
    "  sR2bk=0.80 (R2 blank shrink for RTP target)",
    "Targets: theoretical RTP 299.88%, hit 32.31%, ge500+ 8.53% (vs baseline 4.28%).",
    "Shape: peak ge100-200=20.2%, secondary ge10-20=21.6%; valley ge50-100 filled to 7.6% (was 3.8% in v4).",
    "Booster mass 22.59% (close to baseline 23%) — preserves fuel for mode 5 grand-amplification path.",
    "M37 mode 2 - RTP-neutral Blank redistribution applied (mechanism B per Section 15).",
    "  ratio T1:T2:T3:T4 = 5:4:2:1 (lucky tilt)",
]

with open(_ROOT / 'slot_designer/weights/M37/mode_2/weights.json', 'w', encoding='utf-8') as f:
    json.dump(m2_base, f, indent=2)
print('Mode 2 v5 written.')

# Quick validation
from slot_designer.engine.loader import load_engine
from slot_designer.devtools.analytic_rtp import analytic_profile
eng, _ = load_engine(
    spec_path=_ROOT / 'slot_designer/specs/M37.spec.json',
    strips_path=_ROOT / 'slot_designer/weights/M37/reel_strips.json',
    weights_path=_ROOT / 'slot_designer/weights/M37/mode_2/weights.json',
)
prof = analytic_profile(eng)
print(f'\nValidate:')
print(f'  RTP={prof["rtp_pct"]:.3f}%  hit={prof["hit_rate"]*100:.3f}%  CV={prof["cv"]:.3f}')
for ri, label in [(0, 'R1'), (1, 'R2'), (2, 'R3')]:
    total = sum(new_w[ri])
    blank = sum(new_w[ri][p] for p in positions(ri, 'blank')) / total * 100
    print(f'  {label} blank={blank:.2f}% total={total}')
