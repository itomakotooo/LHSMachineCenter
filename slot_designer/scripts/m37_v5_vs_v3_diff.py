"""M37 v5 (user-accepted balanced-bars) vs v3 (current layout v3) diff.

v5 commit: 61b81c2 (balanced-bars)
v3 commit: 83be1d7 (layout v3)

Compares: RTP, hit, CV, per-pay_id, bucket dist, per-symbol marginals,
window visibility, big-win cycles, dry-spell, near-miss.
"""
import sys
import json
import subprocess
import tempfile
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.core.engine.loader import load_engine
from slot_designer.core.devtools.analytic_rtp import analytic_profile


def jload_str(s):
    return json.loads(s)


def jload(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def git_show(commit, path):
    r = subprocess.run(['git', 'show', f'{commit}:{path}'], capture_output=True, text=True, encoding='utf-8')
    return r.stdout


def measure_at(strips_path, weights_path):
    eng, _ = load_engine(_ROOT / 'slot_designer/machines/M37/spec.json', weights_path, strips_path=strips_path)
    return analytic_profile(eng), eng


def compute_strip_marginals(strips, weights):
    margs = []
    for ri in range(3):
        total = sum(weights[ri])
        m = {}
        for p, sym in enumerate(strips[ri]):
            m[sym] = m.get(sym, 0) + weights[ri][p]
        margs.append({s: v/total for s, v in m.items()})
    return margs


def compute_window_vis(strips, weights):
    vis_per_reel = []
    for ri in range(3):
        n = len(strips[ri])
        total = sum(weights[ri])
        vis = {}
        for p in range(n):
            cells = (strips[ri][(p-1) % n], strips[ri][p], strips[ri][(p+1) % n])
            for s in set(cells):
                vis[s] = vis.get(s, 0) + weights[ri][p] / total
        vis_per_reel.append(vis)
    return vis_per_reel


# === Load v5 from commit 61b81c2 ===
V5_COMMIT = '61b81c2'
V3_COMMIT = 'HEAD'  # current

# Write v5 strips/weights to temp dir
v5_dir = Path(tempfile.mkdtemp(prefix='m37_v5_'))
v5_strips_path = v5_dir / 'reel_strips.json'
v5_strips_path.write_text(git_show(V5_COMMIT, 'slot_designer/machines/M37/reel_strips.json'), encoding='utf-8')

v5_weights = {}
for mode in [1, 2, 5, 7]:
    v5_w_path = v5_dir / f'mode_{mode}.json'
    v5_w_path.write_text(git_show(V5_COMMIT, f'slot_designer/machines/M37/weights/mode_{mode}/weights.json'), encoding='utf-8')
    v5_weights[mode] = v5_w_path

# Current state (v3 / HEAD)
v3_strips_path = _ROOT / 'slot_designer/machines/M37/reel_strips.json'
v3_weights = {mode: _ROOT / f'slot_designer/machines/M37/weights/mode_{mode}/weights.json' for mode in [1, 2, 5, 7]}


# === Section 1: RTP / hit / CV ===
print('=' * 80)
print('1. CORE METRICS — v5 (你之前 ok 的) vs v3 (current layout v3)')
print('=' * 80)
print(f'{"mode":>4} | {"RTP v5":>9} {"RTP v3":>9} {"Δ":>6} | {"hit v5":>8} {"hit v3":>8} {"Δ":>6} | {"CV v5":>6} {"CV v3":>6} {"Δ":>6}')
print('-' * 90)
for mode in [1, 2, 5, 7]:
    v5p, _ = measure_at(v5_strips_path, v5_weights[mode])
    v3p, _ = measure_at(v3_strips_path, v3_weights[mode])
    drtp = v3p['rtp_pct'] - v5p['rtp_pct']
    dhit = (v3p['hit_rate'] - v5p['hit_rate']) * 100
    dcv = v3p['cv'] - v5p['cv']
    print(f'{mode:>4} | {v5p["rtp_pct"]:>8.2f}% {v3p["rtp_pct"]:>8.2f}% {drtp:>+5.2f} | '
          f'{v5p["hit_rate"]*100:>7.2f}% {v3p["hit_rate"]*100:>7.2f}% {dhit:>+5.2f} | '
          f'{v5p["cv"]:>6.2f} {v3p["cv"]:>6.2f} {dcv:>+5.2f}')


# === Section 2: Per-pay_id frequency ===
print()
print('=' * 80)
print('2. PER-PAY_ID HIT RATE  v5 → v3 (期望: 几乎不变, 仅 layout 影响 P)')
print('=' * 80)
PAY_KIND = {
    1: 'line_3_same(high7) 10x', 2: 'line_3_same(7bar) 6x',
    3: 'line_3_same(3bar) 5x', 4: 'line_3_same(2bar) 4x',
    5: 'line_3_same(1bar) 3x', 6: 'line_3_group(any-7) 2x',
    7: 'line_3_group(any-bar) 1x', 8: 'center_grand_alone 100x',
    9: 'center booster + side-wild', 102: 'pure_wild_with_major 100x',
    103: 'pure_wild_with_minor 50x', 104: 'pure_wild_with_mini 20x',
}
for mode in [1, 2, 5, 7]:
    print(f'  mode {mode}:')
    v5p, _ = measure_at(v5_strips_path, v5_weights[mode])
    v3p, _ = measure_at(v3_strips_path, v3_weights[mode])
    print(f'    {"pay_id":>6}  {"kind":<32}  {"v5_hit%":>8} {"v3_hit%":>8} {"Δhit":>7} | {"v5_RTP":>8} {"v3_RTP":>8} {"ΔRTP":>7}')
    pids = sorted(set(v5p['pay_hits'].keys()) | set(v3p['pay_hits'].keys()), key=int)
    for pid in pids:
        v5h = v5p['pay_hits'].get(pid, 0) * 100
        v3h = v3p['pay_hits'].get(pid, 0) * 100
        v5r = v5p['pay_rtp'].get(pid, 0) * 100
        v3r = v3p['pay_rtp'].get(pid, 0) * 100
        kind = PAY_KIND.get(int(pid), '?')
        flag = ''
        if abs(v3h - v5h) > 0.05:
            flag = ' ←Δ'
        print(f'    {pid:>6}  {kind:<32}  {v5h:>7.3f}% {v3h:>7.3f}% {v3h-v5h:>+6.3f} | {v5r:>7.2f}pp {v3r:>7.2f}pp {v3r-v5r:>+6.2f}{flag}')


# === Section 3: Bucket distribution ===
print()
print('=' * 80)
print('3. BUCKET DISTRIBUTION  v5 → v3')
print('=' * 80)
buckets = ['ge1_lt5', 'ge5_lt10', 'ge10_lt20', 'ge20_lt50', 'ge50_lt100',
           'ge100_lt200', 'ge200_lt500', 'ge500_lt1000', 'ge1000_lt5000']
for mode in [1, 2, 5, 7]:
    v5p, _ = measure_at(v5_strips_path, v5_weights[mode])
    v3p, _ = measure_at(v3_strips_path, v3_weights[mode])
    print(f'  mode {mode}:')
    print(f'    {"bucket":<18} {"v5 hit%":>8} {"v3 hit%":>8} {"Δhit":>6} | {"v5 RTP%":>8} {"v3 RTP%":>8} {"ΔRTP":>6}')
    for b in buckets:
        v5h = v5p['bucket_rate'].get(b, 0) * 100
        v3h = v3p['bucket_rate'].get(b, 0) * 100
        v5r = v5p['bucket_rtp'].get(b, 0) * 100
        v3r = v3p['bucket_rtp'].get(b, 0) * 100
        flag = ' ←Δ' if abs(v3r - v5r) > 0.5 else ''
        print(f'    {b:<18} {v5h:>7.3f}% {v3h:>7.3f}% {v3h-v5h:>+5.3f} | {v5r:>7.2f}pp {v3r:>7.2f}pp {v3r-v5r:>+5.2f}{flag}')


# === Section 4: Per-symbol marginals (R1/R2/R3 cross-mode) ===
print()
print('=' * 80)
print('4. PER-SYMBOL MARGINALS  v5 → v3 (核心: 应该保留)')
print('=' * 80)
v5_strips = jload_str(git_show(V5_COMMIT, 'slot_designer/machines/M37/reel_strips.json'))['reels']
v3_strips = jload(v3_strips_path)['reels']
all_syms = ['blank', 'wild', 'high7', '1bar', '2bar', '3bar', '7bar', 'mini', 'minor', 'major', 'grand']
for mode in [1, 2, 5, 7]:
    print(f'  mode {mode}:')
    v5_w = jload_str(git_show(V5_COMMIT, f'slot_designer/machines/M37/weights/mode_{mode}/weights.json'))['weights']
    v3_w = jload(v3_weights[mode])['weights']
    v5_marg = compute_strip_marginals(v5_strips, v5_w)
    v3_marg = compute_strip_marginals(v3_strips, v3_w)
    for ri, label in [(0, 'R1'), (1, 'R2'), (2, 'R3')]:
        line = f'    {label}:'
        for sym in all_syms:
            v5m = v5_marg[ri].get(sym, 0) * 100
            v3m = v3_marg[ri].get(sym, 0) * 100
            if v5m == 0 and v3m == 0:
                continue
            d = v3m - v5m
            flag = '*' if abs(d) > 0.5 else ''
            line += f' {sym}:{v5m:.1f}→{v3m:.1f}({d:+.1f}){flag}'
        print(line)


# === Section 5: Window visibility ===
print()
print('=' * 80)
print('5. WINDOW VISIBILITY  v5 → v3 (期望: 这是 layout 改动主要影响项)')
print('=' * 80)
for mode in [1, 2, 5, 7]:
    print(f'  mode {mode}:')
    v5_w = jload_str(git_show(V5_COMMIT, f'slot_designer/machines/M37/weights/mode_{mode}/weights.json'))['weights']
    v3_w = jload(v3_weights[mode])['weights']
    v5_vis = compute_window_vis(v5_strips, v5_w)
    v3_vis = compute_window_vis(v3_strips, v3_w)
    for ri, label in [(0, 'R1'), (1, 'R2'), (2, 'R3')]:
        for sym in all_syms:
            v5v = v5_vis[ri].get(sym, 0) * 100
            v3v = v3_vis[ri].get(sym, 0) * 100
            if v5v == 0 and v3v == 0:
                continue
            d = v3v - v5v
            if abs(d) > 1.0:
                print(f'    {label} {sym:6s}: v5={v5v:>5.2f}% → v3={v3v:>5.2f}% ({d:+.2f}pp)')


# === Section 6: Big-win cycles (analytic) ===
print()
print('=' * 80)
print('6. BIG-WIN CYCLES  v5 → v3')
print('=' * 80)
print(f'{"mode":>4} | {"≥50× v5":>10} {"v3":>8} | {"≥100× v5":>10} {"v3":>8} | {"≥200× v5":>10} {"v3":>8} | {"≥500× v5":>10} {"v3":>8} | {"≥1000× v5":>11} {"v3":>9}')
print('-' * 130)
for mode in [1, 2, 5, 7]:
    v5p, _ = measure_at(v5_strips_path, v5_weights[mode])
    v3p, _ = measure_at(v3_strips_path, v3_weights[mode])
    def cycle(p, t):
        ge_buckets = [b for b in buckets if int(b.split('_')[0].replace('ge', '')) >= t]
        f = sum(p['bucket_rate'].get(b, 0) for b in ge_buckets)
        return round(1/f) if f > 0 else 999999
    row = f'{mode:>4} |'
    for t in [50, 100, 200, 500, 1000]:
        c5, c3 = cycle(v5p, t), cycle(v3p, t)
        row += f' 1in{c5:>6} 1in{c3:>5} |'
    print(row)


# === Section 7: Booster co-occurrence (the v3 fix) ===
print()
print('=' * 80)
print('7. BOOSTER CO-OCCURRENCE in window (v3 修的 R2 booster cluster 问题)')
print('=' * 80)
def booster_cooccur(strips, weights):
    n = 26
    p_2 = 0
    p_1 = 0
    total = sum(weights[1])
    for stop in range(n):
        cells = [strips[1][(stop-1) % n], strips[1][stop], strips[1][(stop+1) % n]]
        boosters = sum(1 for c in cells if c in ['mini', 'minor', 'major', 'grand'])
        weight = weights[1][stop] / total
        if boosters >= 2:
            p_2 += weight
        elif boosters == 1:
            p_1 += weight
    return p_2, p_1

print(f'{"mode":>4} | {"v5 P(>=2 boosters)":>20} {"v3 P(>=2 boosters)":>20}')
for mode in [1, 2, 5, 7]:
    v5_w = jload_str(git_show(V5_COMMIT, f'slot_designer/machines/M37/weights/mode_{mode}/weights.json'))['weights']
    v3_w = jload(v3_weights[mode])['weights']
    v5_p2, _ = booster_cooccur(v5_strips, v5_w)
    v3_p2, _ = booster_cooccur(v3_strips, v3_w)
    print(f'{mode:>4} | {v5_p2*100:>18.4f}% {v3_p2*100:>18.4f}%')


# === Cleanup ===
import shutil
shutil.rmtree(v5_dir, ignore_errors=True)
