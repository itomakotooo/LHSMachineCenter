"""M37 layout v3 — comprehensive review dump.

Sections:
  A. Cross-mode summary + design contracts
  B. Per-mode bucket distribution (full table)
  C. Per-pay_id frequency + RTP contribution (cross-mode)
  D. Big-win cycles + dry-spell stats
  E. Per-window session RTP distribution
  F. Reel marginal table (cross-mode, all symbols)
  G. Window visibility full table (cross-reel × cross-symbol)
  H. Booster co-occurrence audit (window-level)
  I. Near-miss & phantom win analysis
  J. PWDF tier audit (actual blank weights per tier)
  K. §15.8 anti-假 cap audit (numerical headroom)
  L. Cross-mode invariants: HIER / MODE7-LOCK / MODE5-BASE-LOCK
  M. Engine sim 2M validation (analytic vs empirical)
  N. Top-jackpot path P(1000×) decomposition
  O. Strip layout visualization
"""
import sys
import json
from pathlib import Path
from random import Random
from collections import Counter, defaultdict
from itertools import product

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.core.engine.loader import load_engine
from slot_designer.core.devtools.analytic_rtp import analytic_profile


def jload(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


SPEC = _ROOT / 'slot_designer/machines/M37/spec.json'
STRIPS_PATH = _ROOT / 'slot_designer/machines/M37/reel_strips.json'
strips = jload(STRIPS_PATH)['reels']
modes_data = {}
for mode in [1, 2, 5, 7]:
    eng, _ = load_engine(SPEC, _ROOT / f'slot_designer/machines/M37/weights/mode_{mode}/weights.json',
                          strips_path=STRIPS_PATH)
    prof = analytic_profile(eng)
    weights = jload(_ROOT / f'slot_designer/machines/M37/weights/mode_{mode}/weights.json')['weights']
    modes_data[mode] = {'eng': eng, 'prof': prof, 'weights': weights}


# === A. Cross-mode summary ===
print('=' * 70)
print('A. Cross-mode summary & design contracts')
print('=' * 70)
print(f'{"mode":>4} {"target":>7} {"theory":>8} {"hit":>7} {"CV":>5} {"avg_win":>8}')
TARGETS = {1: 95, 2: 300, 5: 500, 7: 85}
for mode in [1, 2, 5, 7]:
    p = modes_data[mode]['prof']
    rtp = p['rtp_pct']
    hit = p['hit_rate'] * 100
    cv = p['cv']
    avg = rtp / hit if hit > 0 else 0
    delta = rtp - TARGETS[mode]
    print(f'{mode:>4} {TARGETS[mode]:>6}% {rtp:>7.2f}% {hit:>6.2f}% {cv:>5.2f} {avg:>7.2f}× (Δ from target {delta:+.2f}pp)')

# === B. Per-mode bucket distribution ===
print()
print('=' * 70)
print('B. Per-mode bucket distribution')
print('=' * 70)
buckets = ['ge1_lt5', 'ge5_lt10', 'ge10_lt20', 'ge20_lt50', 'ge50_lt100',
           'ge100_lt200', 'ge200_lt500', 'ge500_lt1000', 'ge1000_lt5000']
print(f'{"bucket":<18} | {"m1 hit/RTP":>17} | {"m2 hit/RTP":>17} | {"m5 hit/RTP":>17} | {"m7 hit/RTP":>17}')
print('-' * 100)
for b in buckets:
    row = f'{b:<18}'
    for mode in [1, 2, 5, 7]:
        p = modes_data[mode]['prof']
        h = p['bucket_rate'].get(b, 0) * 100
        r = p['bucket_rtp'].get(b, 0) * 100
        row += f' | {h:>5.2f}% / {r:>6.2f}pp'
    print(row)
print()
print('  (RTP shares per mode):')
for mode in [1, 2, 5, 7]:
    p = modes_data[mode]['prof']
    rtp = p['rtp_pct']
    shares = [(b, p['bucket_rtp'].get(b, 0) * 100 / rtp * 100) for b in buckets]
    s_str = ' / '.join(f'{s:.1f}' for _, s in shares)
    print(f'  m{mode}: {s_str}')


# === C. Per-pay_id (cross-mode) ===
print()
print('=' * 70)
print('C. Per-pay_id frequency + RTP contribution (cross-mode)')
print('=' * 70)
PAY_KIND = {
    1: 'line_3_same(high7) 10x', 2: 'line_3_same(7bar) 6x',
    3: 'line_3_same(3bar) 5x', 4: 'line_3_same(2bar) 4x',
    5: 'line_3_same(1bar) 3x', 6: 'line_3_group(any-7) 2x',
    7: 'line_3_group(any-bar) 1x', 8: 'center_grand_alone 100x',
    9: 'center booster + side-wild', 102: 'pure_wild_with_major 100x',
    103: 'pure_wild_with_minor 50x', 104: 'pure_wild_with_mini 20x',
}
print(f'{"pay_id":>4} {"kind":<32} | {"m1 hit% / RTPpp":>18} | {"m2":>18} | {"m5":>18} | {"m7":>18}')
print('-' * 120)
all_pids = sorted(set().union(*(set(modes_data[m]['prof']['pay_hits'].keys()) for m in [1, 2, 5, 7])), key=int)
for pid in all_pids:
    kind = PAY_KIND.get(int(pid), '?')
    row = f'{pid:>4} {kind:<32}'
    for mode in [1, 2, 5, 7]:
        p = modes_data[mode]['prof']
        h = p['pay_hits'].get(pid, 0) * 100
        r = p['pay_rtp'].get(pid, 0) * 100
        row += f' | {h:>6.3f}% / {r:>7.2f}pp'
    print(row)


# === D. Big-win cycles + dry-spell stats ===
print()
print('=' * 70)
print('D. Big-win cycles + dry-spell stats (1M sim per mode)')
print('=' * 70)
print(f'{"mode":>4} | {"50×+":>10} {"100×+":>10} {"200×+":>10} {"500×+":>10} {"1000×":>10} | {"dry p50/p99/max":>20}')
sim_data = {}
for mode in [1, 2, 5, 7]:
    eng = modes_data[mode]['eng']
    rng = Random(0xDEADBEEF + mode)
    N = 1_000_000
    wins = []
    consecutive_losses = []
    cur_dry = 0
    for _ in range(N):
        out = eng.spin(rng)
        win = (out.pay.multiplier * out.bet_amount) if out.pay else 0
        for sp in (out.scatter_pays or []):
            win += sp.multiplier * out.bet_amount
        wins.append(win)
        if win == 0:
            cur_dry += 1
        else:
            if cur_dry > 0:
                consecutive_losses.append(cur_dry)
            cur_dry = 0
    if cur_dry > 0:
        consecutive_losses.append(cur_dry)
    bet = 1000  # M37 cost_per_spin
    multipliers = [w / bet for w in wins]
    p = modes_data[mode]['prof']
    bk = p['bucket_rate']
    def freq_above(t):
        ge_buckets = [b for b in buckets if int(b.split('_')[0].replace('ge', '')) >= t]
        return sum(bk.get(b, 0) for b in ge_buckets)
    cycle_50 = round(1 / freq_above(50)) if freq_above(50) > 0 else 999999
    cycle_100 = round(1 / freq_above(100)) if freq_above(100) > 0 else 999999
    cycle_200 = round(1 / freq_above(200)) if freq_above(200) > 0 else 999999
    cycle_500 = round(1 / freq_above(500)) if freq_above(500) > 0 else 999999
    cycle_1000 = round(1 / freq_above(1000)) if freq_above(1000) > 0 else 999999
    sorted_dry = sorted(consecutive_losses)
    p50 = sorted_dry[len(sorted_dry)//2] if sorted_dry else 0
    p99 = sorted_dry[int(len(sorted_dry)*0.99)] if sorted_dry else 0
    max_dry = sorted_dry[-1] if sorted_dry else 0
    print(f'{mode:>4} | 1in{cycle_50:>6} 1in{cycle_100:>7} 1in{cycle_200:>7} 1in{cycle_500:>7} 1in{cycle_1000:>6} | {p50:>3} / {p99:>3} / {max_dry:>3}')
    sim_data[mode] = {'wins': wins, 'multipliers': multipliers}


# === E. Per-window session RTP distribution ===
print()
print('=' * 70)
print('E. Per-window session RTP distribution (player feel)')
print('=' * 70)
for mode in [1, 2, 5, 7]:
    print(f'  mode {mode}:')
    bet = 1000
    for window in [10, 50, 100, 500]:
        wins = sim_data[mode]['wins']
        windows = [sum(wins[i:i+window]) / (window * bet) * 100 for i in range(0, len(wins), window)]
        windows.sort()
        wp10 = windows[len(windows)//10]
        wp50 = windows[len(windows)//2]
        wp90 = windows[int(len(windows)*0.9)]
        win_count = sum(1 for w in windows if w > 100) / len(windows) * 100
        print(f'    N={window:>3} spins: p10={wp10:>5.0f}% p50={wp50:>5.0f}% p90={wp90:>5.0f}%   ({win_count:>4.1f}% sessions over 100% RTP)')


# === F. Reel marginal table ===
print()
print('=' * 70)
print('F. Reel marginal (mid-row symbol probability) — cross-mode')
print('=' * 70)
all_syms = ['blank', 'wild', 'high7', '1bar', '2bar', '3bar', '7bar', 'mini', 'minor', 'major', 'grand']
for ri, label in [(0, 'R1'), (1, 'R2'), (2, 'R3')]:
    print(f'  {label}:')
    print(f'    {"sym":<6} | ' + ' | '.join(f'{f"m{m}":>7}' for m in [1, 2, 5, 7]))
    for sym in all_syms:
        row = f'    {sym:<6} |'
        for mode in [1, 2, 5, 7]:
            w = modes_data[mode]['weights'][ri]
            total = sum(w)
            m = sum(w[p] for p, s in enumerate(strips[ri]) if s == sym) / total * 100
            row += f' {m:>6.2f}% |'
        print(row)


# === G. Window visibility full table ===
print()
print('=' * 70)
print('G. Window visibility (P symbol shown anywhere in 3-row window)')
print('=' * 70)
for mode in [1, 2, 5, 7]:
    print(f'  mode {mode}:')
    print(f'    {"reel":<4} | ' + ' '.join(f'{s:>6}' for s in all_syms))
    for ri in range(3):
        n = len(strips[ri])
        total = sum(modes_data[mode]['weights'][ri])
        vis = {s: 0.0 for s in all_syms}
        for p in range(n):
            cells = (strips[ri][(p-1) % n], strips[ri][p], strips[ri][(p+1) % n])
            for s in set(cells):
                if s in vis:
                    vis[s] += modes_data[mode]['weights'][ri][p] / total
        row = f'    R{ri+1:<3} |'
        for s in all_syms:
            v = vis[s] * 100
            row += f' {v:>5.2f}%' if v > 0 else f' {"-":>6}'
        print(row)


# === H. Booster co-occurrence audit ===
print()
print('=' * 70)
print('H. R2 booster co-occurrence (multiple boosters in same window)')
print('=' * 70)
booster_pos = {sym: [i for i, s in enumerate(strips[1]) if s == sym]
               for sym in ['mini', 'minor', 'major', 'grand']}
booster_positions = sorted(p[0] for p in booster_pos.values())
print(f'  R2 booster positions: {booster_positions}')
print(f'  cyclic gaps: {[(booster_positions[(i+1)%4] - booster_positions[i]) % 26 for i in range(4)]}')
# For each window stop, count boosters visible
n = 26
for mode in [1, 2, 5, 7]:
    total = sum(modes_data[mode]['weights'][1])
    p_2_boosters = 0
    p_1_booster = 0
    for stop in range(n):
        cells = [strips[1][(stop-1) % n], strips[1][stop], strips[1][(stop+1) % n]]
        boosters_in_window = sum(1 for c in cells if c in ['mini', 'minor', 'major', 'grand'])
        weight = modes_data[mode]['weights'][1][stop] / total
        if boosters_in_window >= 2:
            p_2_boosters += weight
        elif boosters_in_window == 1:
            p_1_booster += weight
    print(f'  mode {mode}: P(>=2 boosters in window) = {p_2_boosters*100:.4f}%   P(exactly 1 booster) = {p_1_booster*100:.2f}%')


# === I. Near-miss & phantom win analysis ===
print()
print('=' * 70)
print('I. Near-miss patterns + phantom-row wins')
print('=' * 70)
def reel_marg(ri, mode):
    w = modes_data[mode]['weights'][ri]
    total = sum(w)
    m = {}
    for p, s in enumerate(strips[ri]):
        m[s] = m.get(s, 0) + w[p] / total
    return m

for mode in [1, 2, 5, 7]:
    print(f'  mode {mode}:')
    m1, m2, m3 = [reel_marg(r, mode) for r in range(3)]
    p_3h7_pay = m1.get('high7', 0) * m2.get('high7', 0) * m3.get('high7', 0)
    # 2-h7 + 1 non-substituting (non-wild non-booster non-h7)
    def non_sub(m):
        return 1 - m.get('wild', 0) - m.get('high7', 0) - sum(m.get(s, 0) for s in ['mini','minor','major','grand'])
    p_tease_R3 = m1.get('high7', 0) * m2.get('high7', 0) * non_sub(m3)
    p_tease_R1 = non_sub(m1) * m2.get('high7', 0) * m3.get('high7', 0)
    p_tease_R2 = m1.get('high7', 0) * non_sub(m2) * m3.get('high7', 0)
    p_tease = p_tease_R1 + p_tease_R2 + p_tease_R3
    # Top-row 3-h7 phantom
    def per_reel_top_bot_h7(ri):
        n = len(strips[ri])
        total = sum(modes_data[mode]['weights'][ri])
        p_top = sum(modes_data[mode]['weights'][ri][p] for p in range(n) if strips[ri][(p-1) % n] == 'high7') / total
        p_bot = sum(modes_data[mode]['weights'][ri][p] for p in range(n) if strips[ri][(p+1) % n] == 'high7') / total
        return p_top, p_bot
    top_R1, bot_R1 = per_reel_top_bot_h7(0)
    top_R2, bot_R2 = per_reel_top_bot_h7(1)
    top_R3, bot_R3 = per_reel_top_bot_h7(2)
    p_phantom_top = top_R1 * top_R2 * top_R3
    p_phantom_bot = bot_R1 * bot_R2 * bot_R3
    print(f'    mid 3-h7 paying:           1in{round(1/p_3h7_pay) if p_3h7_pay > 0 else "∞":>6}   ({p_3h7_pay*100:.4f}%)')
    print(f'    2-h7 tease near-miss:      1in{round(1/p_tease) if p_tease > 0 else "∞":>6}   ({p_tease*100:.4f}%)')
    print(f'    3-h7 phantom (top row):    1in{round(1/p_phantom_top) if p_phantom_top > 0 else "∞":>6}   ({p_phantom_top*100:.6f}%)')
    print(f'    3-h7 phantom (bot row):    1in{round(1/p_phantom_bot) if p_phantom_bot > 0 else "∞":>6}   ({p_phantom_bot*100:.6f}%)')
    # R2 grand near-miss
    nm = len(strips[1])
    grand_top = sum(modes_data[mode]['weights'][1][p] for p in range(nm) if strips[1][(p-1) % nm] == 'grand') / sum(modes_data[mode]['weights'][1])
    grand_bot = sum(modes_data[mode]['weights'][1][p] for p in range(nm) if strips[1][(p+1) % nm] == 'grand') / sum(modes_data[mode]['weights'][1])
    grand_visible_off_payline = grand_top + grand_bot
    print(f'    R2 grand off-payline visible: {grand_visible_off_payline*100:.2f}%   1in{round(1/grand_visible_off_payline) if grand_visible_off_payline > 0 else "∞":>3}')
    print()


# === J. PWDF tier audit ===
print()
print('=' * 70)
print('J. PWDF blank tier audit (per-tier weight & ratio)')
print('=' * 70)
PRIORITY = {
    0: [['high7'], ['wild'], ['1bar', '2bar', '3bar', '7bar']],
    1: [['grand'], ['high7'], ['mini', 'minor', 'major']],
    2: [['high7'], ['wild'], ['1bar', '2bar', '3bar', '7bar']],
}
for mode in [1, 2, 5, 7]:
    print(f'  mode {mode}:')
    expected_ratio = (4, 3, 2, 1) if mode in [1, 7] else (5, 4, 2, 1)
    print(f'    expected ratio T1:T2:T3:T4 = {expected_ratio[0]}:{expected_ratio[1]}:{expected_ratio[2]}:{expected_ratio[3]}')
    for ri in range(3):
        groups = PRIORITY[ri]
        n = len(strips[ri])
        tier_weights = {0: [], 1: [], 2: [], 3: []}
        for p in range(n):
            if strips[ri][p] != 'blank':
                continue
            prev_sym = strips[ri][(p-1) % n]
            next_sym = strips[ri][(p+1) % n]
            best_tier = 3
            for sym in (prev_sym, next_sym):
                for t_idx, group in enumerate(groups):
                    if sym in group:
                        if t_idx < best_tier:
                            best_tier = t_idx
                        break
            tier_weights[best_tier].append(modes_data[mode]['weights'][ri][p])
        line = f'    R{ri+1}: '
        unit_w = []
        for t in range(4):
            n_pos = len(tier_weights[t])
            avg_w = sum(tier_weights[t]) / n_pos if n_pos > 0 else 0
            unit_w.append(avg_w / expected_ratio[t] if expected_ratio[t] > 0 and avg_w > 0 else 0)
            line += f'T{t+1} {n_pos}×{avg_w:.0f}w  '
        max_min_ratio = max(tier_weights[0] + tier_weights[1] + tier_weights[2] + tier_weights[3]) / min(w for tw in tier_weights.values() for w in tw if w > 0)
        line += f' | max/min = {max_min_ratio:.2f}x'
        print(line)


# === K. §15.8 anti-假 cap audit ===
print()
print('=' * 70)
print('K. §15.8 anti-假 cap audit (numerical headroom)')
print('=' * 70)
for mode in [1, 2, 5, 7]:
    print(f'  mode {mode}:')
    # Top symbol max visibility
    max_vis = 0
    max_sym = ''
    for ri in range(3):
        n = len(strips[ri])
        total = sum(modes_data[mode]['weights'][ri])
        for sym in ['high7', 'wild', 'mini', 'minor', 'major', 'grand']:
            v = sum(modes_data[mode]['weights'][ri][p] / total for p in range(n)
                    if sym in (strips[ri][(p-1) % n], strips[ri][p], strips[ri][(p+1) % n]))
            if v > max_vis:
                max_vis = v
                max_sym = f'R{ri+1} {sym}'
    print(f'    max top-symbol visibility: {max_vis*100:.2f}% ({max_sym})  [cap 50%, headroom {(0.5 - max_vis)*100:.1f}pp]')
    # Mid-pay min visibility
    min_vis = 1.0
    min_sym = ''
    for ri in range(3):
        n = len(strips[ri])
        total = sum(modes_data[mode]['weights'][ri])
        for sym in ['1bar', '2bar', '3bar', '7bar']:
            v = sum(modes_data[mode]['weights'][ri][p] / total for p in range(n)
                    if sym in (strips[ri][(p-1) % n], strips[ri][p], strips[ri][(p+1) % n]))
            if v > 0 and v < min_vis:
                min_vis = v
                min_sym = f'R{ri+1} {sym}'
    floor = 0.07 if mode in [2, 5] else 0.08
    print(f'    min mid-pay visibility: {min_vis*100:.2f}% ({min_sym})  [floor {floor*100}%, headroom {(min_vis - floor)*100:.2f}pp]')
    # Blank tier ratio
    max_ratio = 0
    max_ri = ''
    for ri in range(3):
        blanks = [modes_data[mode]['weights'][ri][p] for p, s in enumerate(strips[ri]) if s == 'blank']
        r = max(blanks) / min(blanks) if min(blanks) > 0 else 0
        if r > max_ratio:
            max_ratio = r
            max_ri = f'R{ri+1}'
    print(f'    max blank max/min ratio: {max_ratio:.2f}x ({max_ri})  [cap 5.0x, headroom {(5.0 - max_ratio):.2f}x]')


# === L. Cross-mode invariants ===
print()
print('=' * 70)
print('L. Cross-mode invariants')
print('=' * 70)
def get_R2_marg(mode, sym):
    w = modes_data[mode]['weights'][1]
    total = sum(w)
    return sum(w[p] for p, s in enumerate(strips[1]) if s == sym) / total

print('  HIER (倒金字塔 mini > minor > major > grand, ratio ≥ 1.3):')
for mode in [1, 2, 5, 7]:
    mini = get_R2_marg(mode, 'mini')
    minor = get_R2_marg(mode, 'minor')
    major = get_R2_marg(mode, 'major')
    grand = get_R2_marg(mode, 'grand')
    print(f'    m{mode}: mini={mini*100:.3f}% minor={minor*100:.3f}% major={major*100:.3f}% grand={grand*100:.4f}%   '
          f'mi/mn={mini/minor:.2f} mn/mj={minor/major:.2f} mj/gd={major/grand:.2f}')

print()
print('  MODE7-LOCK (m7 R2 booster within 0.5pp of m1):')
for sym in ['mini', 'minor', 'major', 'grand']:
    m1 = get_R2_marg(1, sym) * 100
    m7 = get_R2_marg(7, sym) * 100
    drift = abs(m1 - m7)
    print(f'    R2 {sym:6s}: m1={m1:.4f}% m7={m7:.4f}% drift={drift:.4f}pp  [{"✓" if drift < 0.5 else "✗"}]')

print()
print('  MODE5-BASE-LOCK (m5 base byte-eq m2 except R2 grand):')
for ri in range(3):
    diffs = []
    for p in range(len(modes_data[2]['weights'][ri])):
        if modes_data[2]['weights'][ri][p] != modes_data[5]['weights'][ri][p]:
            diffs.append((p, strips[ri][p], modes_data[2]['weights'][ri][p], modes_data[5]['weights'][ri][p]))
    print(f'    R{ri+1}: {len(diffs)} differing positions  {diffs if diffs else "byte-eq ✓"}')

print()
print('  RTP/HIT monotonicity:')
rtps = {m: modes_data[m]['prof']['rtp_pct'] for m in [1, 2, 5, 7]}
hits = {m: modes_data[m]['prof']['hit_rate'] * 100 for m in [1, 2, 5, 7]}
print(f'    RTP m7={rtps[7]:.1f} < m1={rtps[1]:.1f} < m2={rtps[2]:.1f} < m5={rtps[5]:.1f}   '
      f'[{"✓" if rtps[7] < rtps[1] < rtps[2] < rtps[5] else "✗"}]')
print(f'    HIT m7={hits[7]:.1f} < m1={hits[1]:.1f} < m2={hits[2]:.1f} ≈ m5={hits[5]:.1f}   '
      f'[{"✓" if hits[7] < hits[1] < hits[2] else "✗"}]')


# === M. Engine sim 2M validation ===
print()
print('=' * 70)
print('M. Engine sim 2M validation (analytic vs empirical)')
print('=' * 70)
print(f'{"mode":>4} | {"theory":>8} {"sim2M":>9} {"Δ":>6} | {"theory_hit":>11} {"sim_hit":>9} {"Δ":>6}')
for mode in [1, 2, 5, 7]:
    eng = modes_data[mode]['eng']
    rng = Random(0xCAFEBABE + mode)
    N = 2_000_000
    total_win, total_bet, hits = 0, 0, 0
    for _ in range(N):
        out = eng.spin(rng)
        total_bet += out.bet_amount
        win = (out.pay.multiplier * out.bet_amount) if out.pay else 0
        for sp in (out.scatter_pays or []):
            win += sp.multiplier * out.bet_amount
        if win > 0:
            total_win += win; hits += 1
    sim_rtp = total_win/total_bet*100
    sim_hit = hits/N*100
    th_rtp = modes_data[mode]['prof']['rtp_pct']
    th_hit = modes_data[mode]['prof']['hit_rate'] * 100
    print(f'{mode:>4} | {th_rtp:>7.2f}% {sim_rtp:>8.2f}% {sim_rtp-th_rtp:>+5.2f} | {th_hit:>10.2f}% {sim_hit:>8.2f}% {sim_hit-th_hit:>+5.2f}')


# === N. Top-jackpot path P(1000×) decomposition ===
print()
print('=' * 70)
print('N. Top-jackpot 1000× path decomposition')
print('=' * 70)
for mode in [1, 2, 5, 7]:
    m1, m2, m3 = [reel_marg(r, mode) for r in range(3)]
    # Top 1000× = (high7|wild, grand, high7|wild) with line_3_same(high7) × grand_mult 100
    p_h7_grand_h7 = m1.get('high7', 0) * m2.get('grand', 0) * m3.get('high7', 0)
    p_w_grand_h7 = m1.get('wild', 0) * m2.get('grand', 0) * m3.get('high7', 0)
    p_h7_grand_w = m1.get('high7', 0) * m2.get('grand', 0) * m3.get('wild', 0)
    p_w_grand_w = m1.get('wild', 0) * m2.get('grand', 0) * m3.get('wild', 0)  # blocked by reroll
    p_total = p_h7_grand_h7 + p_w_grand_h7 + p_h7_grand_w + p_w_grand_w
    # post-reroll: (w, grand, w) blocked
    p_actual = p_h7_grand_h7 + p_w_grand_h7 + p_h7_grand_w
    print(f'  mode {mode}: P(h7,G,h7)={p_h7_grand_h7*100:.4f}% + (w,G,h7)={p_w_grand_h7*100:.4f}% + '
          f'(h7,G,w)={p_h7_grand_w*100:.4f}% (blocked w,G,w={p_w_grand_w*100:.4f}%)  → 1in{round(1/p_actual) if p_actual > 0 else "∞"}')


# === O. Strip layout visualization ===
print()
print('=' * 70)
print('O. Strip layout visualization')
print('=' * 70)
short = {'blank':'B','wild':'W','high7':'H','1bar':'1','2bar':'2','3bar':'3','7bar':'7','mini':'m','minor':'n','major':'M','grand':'G'}
for ri, label in [(0, 'R1'), (1, 'R2'), (2, 'R3')]:
    line = ''.join(short[s] for s in strips[ri])
    pos_indicator = ''.join(str(i % 10) for i in range(26))
    print(f'  pos: {pos_indicator}')
    print(f'  {label}:  {line}')
    print()
