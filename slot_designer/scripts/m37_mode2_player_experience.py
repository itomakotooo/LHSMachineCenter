"""M37 player experience analysis (all 4 modes).

Dump comprehensive player-felt metrics for review:
  - Bucket distribution (where RTP comes from + where hits happen)
  - Per-pay_id breakdown (which paths fire most)
  - Big-win frequencies (200×/500×/1000× cycles)
  - Volatility (CV, dry-spell stats, max-loss percentile via simulation)
  - Per-N-spins RTP variance (10/50/100/500)
  - REEL ANALYSIS (per universal §12-§15):
    * per-reel symbol marginals
    * window visibility (top/mid/bot row for each symbol)
    * near-miss patterns (2-of-3 on payline, phantom wins on top/bot row)
    * REEL-ASYMMETRY check (R1 vs R3 top-prize, blank distribution)
    * blank tier distribution (per §15 PWDF redistribute)
    * strip layout visualization (B/N alternation + flank diversity)
"""
import sys
import json
from pathlib import Path
from random import Random
from collections import Counter, defaultdict

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.core.engine.loader import load_engine
from slot_designer.core.devtools.analytic_rtp import analytic_profile


def jload(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


PAY_KIND = {
    1: 'line_3_same(high7)  10x',
    2: 'line_3_same(7bar)    6x',
    3: 'line_3_same(3bar)    5x',
    4: 'line_3_same(2bar)    4x',
    5: 'line_3_same(1bar)    3x',
    6: 'line_3_group(any-7)  2x',
    7: 'line_3_group(any-bar) 1x',
    8: 'center_grand_alone  100x',
    9: 'center mini/minor/major OR side-wild-alone',
    102: 'pure_wild_with_major 100x',
    103: 'pure_wild_with_minor  50x',
    104: 'pure_wild_with_mini   20x',
}


def dump_mode(mode_n):
    eng, _ = load_engine(
        spec_path=_ROOT / 'slot_designer/machines/M37/spec.json',
        strips_path=_ROOT / 'slot_designer/machines/M37/reel_strips.json',
        weights_path=_ROOT / f'slot_designer/weights/M37/mode_{mode_n}/weights.json',
    )
    prof = analytic_profile(eng)

    print(f'================================================================')
    print(f'  Mode {mode_n} player experience report (theoretical, post-reroll)')
    print(f'================================================================')
    print()
    print(f'核心指标:')
    print(f'  RTP            = {prof["rtp_pct"]:.2f}%')
    print(f'  hit rate       = {prof["hit_rate"]*100:.2f}%')
    print(f'  avg win/hit    = {prof["rtp_pct"]/(prof["hit_rate"]*100):.2f}×')
    print(f'  CV             = {prof["cv"]:.3f}  (波动系数 — 越高越大开大合)')
    print(f'  std return     = {prof["std_return_x"]:.2f}× per spin')
    print()

    # Per-pay_id
    print(f'分 pay_id 频率 + 贡献:')
    print(f'  {"pay_id":>6}  {"kind":<35}  {"hit%":>7}  {"RTP_pp":>8}  {"share":>6}  {"avg":>6}')
    pay_hits = prof['pay_hits']
    pay_rtp = prof['pay_rtp']
    rows = []
    for pid_str, hit_p in pay_hits.items():
        pid = int(pid_str)
        rtp_pp = pay_rtp.get(pid_str, 0) * 100
        rows.append((pid, hit_p*100, rtp_pp))
    rows.sort(key=lambda r: -r[1])
    total_hit = prof['hit_rate'] * 100
    total_rtp = prof['rtp_pct']
    for pid, hit_pp, rtp_pp in rows:
        kind = PAY_KIND.get(pid, '?')
        share = rtp_pp / total_rtp * 100
        avg = rtp_pp / hit_pp if hit_pp > 0 else 0
        print(f'  {pid:>6}  {kind:<35}  {hit_pp:>6.3f}%  {rtp_pp:>7.3f}pp  {share:>5.2f}%  {avg:>5.2f}×')
    print()

    # Bucket distribution
    print(f'分 bucket 频率 + 贡献:')
    print(f'  {"bucket":<18}  {"hit%":>7}  {"RTP_pp":>8}  {"share":>6}  {"avg":>7}  {"cycle (1in)":>11}')
    buckets = ['ge1_lt5', 'ge5_lt10', 'ge10_lt20', 'ge20_lt50', 'ge50_lt100',
               'ge100_lt200', 'ge200_lt500', 'ge500_lt1000', 'ge1000_lt5000']
    for b in buckets:
        hit_pp = prof['bucket_rate'].get(b, 0) * 100
        rtp_pp = prof['bucket_rtp'].get(b, 0) * 100
        avg = rtp_pp / hit_pp if hit_pp > 0 else 0
        share = rtp_pp / total_rtp * 100
        cycle = round(100/hit_pp) if hit_pp > 0.0001 else float('inf')
        cycle_str = f'1in{cycle}' if cycle != float('inf') else '——'
        print(f'  {b:<18}  {hit_pp:>6.3f}%  {rtp_pp:>7.3f}pp  {share:>5.2f}%  {avg:>6.1f}×  {cycle_str:>11}')
    print()

    # Big-win frequencies
    print(f'big-win frequencies:')
    for thr in [50, 100, 200, 500, 1000]:
        # Sum hit% across all buckets >= thr
        ge_buckets = [b for b in buckets if int(b.split('_')[0].replace('ge','')) >= thr]
        ge_hit = sum(prof['bucket_rate'].get(b, 0) for b in ge_buckets) * 100
        cycle = round(100/ge_hit) if ge_hit > 0.0001 else float('inf')
        cycle_str = f'1in{cycle}' if cycle != float('inf') else '——'
        print(f'  ≥{thr:>4}× win:  hit={ge_hit:.4f}%   cycle = {cycle_str}')
    print()

    # Empirical sim — dry spell + per-N RTP variance
    rng = Random(0xDEADBEEF + mode_n)
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

    sorted_dry = sorted(consecutive_losses)
    p50 = sorted_dry[len(sorted_dry)//2] if sorted_dry else 0
    p90 = sorted_dry[int(len(sorted_dry)*0.9)] if sorted_dry else 0
    p99 = sorted_dry[int(len(sorted_dry)*0.99)] if sorted_dry else 0
    p999 = sorted_dry[int(len(sorted_dry)*0.999)] if sorted_dry else 0
    max_dry = sorted_dry[-1] if sorted_dry else 0

    print(f'空转 streak 分位数 (consecutive 0-win spins, N={N}):')
    print(f'  p50  = {p50}')
    print(f'  p90  = {p90}')
    print(f'  p99  = {p99}')
    print(f'  p99.9= {p999}')
    print(f'  max  = {max_dry}')
    print()

    # Per-window RTP
    print(f'per-window RTP variance (player session feel):')
    bet = 1000
    for window in [10, 50, 100, 500]:
        windows = [sum(wins[i:i+window]) / (window * bet) * 100 for i in range(0, N, window)]
        windows.sort()
        wp10 = windows[len(windows)//10]
        wp50 = windows[len(windows)//2]
        wp90 = windows[int(len(windows)*0.9)]
        win_session_count = sum(1 for w in windows if w > 100) / len(windows) * 100
        print(f'  N={window}  spins:  p10={wp10:.1f}% / p50={wp50:.1f}% / p90={wp90:.1f}%   ({win_session_count:.1f}% sessions over 100% RTP)')
    print()

    # === REEL ANALYSIS (per universal §12-§15) ===
    print(f'REEL 分析 (universal §12 asymmetry + §13 flank diversity + §15 PWDF):')
    print()

    strips = jload(_ROOT / 'slot_designer/machines/M37/reel_strips.json')['reels']
    weights = jload(_ROOT / f'slot_designer/weights/M37/mode_{mode_n}/weights.json')['weights']

    # ---- 1. Per-reel symbol marginal ----
    all_syms = ['blank', 'wild', 'high7', '1bar', '2bar', '3bar', '7bar', 'mini', 'minor', 'major', 'grand']
    print(f'  1. Per-reel symbol marginal (mid-row probability):')
    print(f'     {"reel":<4} {"total":>6} | ' + ' '.join(f'{s:>6}' for s in all_syms))
    reel_marg = {}
    for ri in range(3):
        total = sum(weights[ri])
        margs = {}
        for sym in all_syms:
            ws = sum(weights[ri][p] for p, s in enumerate(strips[ri]) if s == sym)
            margs[sym] = ws / total
        reel_marg[ri] = margs
        marg_str = ' '.join(f'{margs[s]*100:>5.2f}%' for s in all_syms)
        print(f'     R{ri+1}   {total:>6} | {marg_str}')
    print()

    # ---- 2. Window visibility (3 cells per reel — top + mid + bot) ----
    # For 26-stop reel, window = 3 consecutive stops. P(symbol visible in window) =
    # avg over all stops of (1 if any of stop, stop+1, stop-1 is symbol).
    print(f'  2. Window visibility (P symbol shown anywhere in 3-row window):')
    print(f'     {"reel":<4} | ' + ' '.join(f'{s:>6}' for s in all_syms))
    win_vis = {}
    for ri in range(3):
        n = len(strips[ri])
        total_w = sum(weights[ri])
        # For each symbol, sum weights of stops where stop ∈ {p-1, p, p+1} contains symbol
        # In picked-stop model, each stop has equal landing probability (per its weight).
        # Window visibility = P(symbol appears in any of 3 cells given a stop choice).
        vis = {sym: 0.0 for sym in all_syms}
        for p in range(n):
            cells = (strips[ri][(p-1) % n], strips[ri][p], strips[ri][(p+1) % n])
            present = set(cells)
            for sym in present:
                if sym in vis:
                    vis[sym] += weights[ri][p] / total_w
        win_vis[ri] = vis
        vis_str = ' '.join(f'{vis[s]*100:>5.2f}%' for s in all_syms)
        print(f'     R{ri+1}   | {vis_str}')
    print()

    # ---- 3. Near-miss analysis ----
    # 3a. "tease" near-miss: 2 high7 on payline + 1 different non-blank (would-have-been if 3rd matched)
    # 3b. window phantom: 3 high7 on top OR bot row (player sees the win shape but not on payline)
    print(f'  3. Near-miss & phantom-win analysis:')
    # Baseline mid-row probabilities
    h7_R1 = reel_marg[0]['high7']
    h7_R2 = reel_marg[1]['high7']
    h7_R3 = reel_marg[2]['high7']
    wild_R1 = reel_marg[0]['wild']
    wild_R3 = reel_marg[2]['wild']
    grand_R2 = reel_marg[1]['grand']
    # Mid-row 3-h7 (winning combo)
    p_3h7_mid = h7_R1 * h7_R2 * h7_R3
    # 2-h7 + 1-other on payline (any reel has non-h7 non-substituting symbol)
    p_2h7_R3 = h7_R1 * h7_R2 * (1 - h7_R3 - wild_R3 - grand_R2 if False else 1 - h7_R3)  # rough
    # Actually compute "exactly 2 h7 + 1 non-substituting" — non-sub means non-wild, non-booster, non-h7
    def non_sub(reel_idx):
        m = reel_marg[reel_idx]
        return 1 - m.get('wild', 0) - m.get('high7', 0) - m.get('mini', 0) - m.get('minor', 0) - m.get('major', 0) - m.get('grand', 0)
    p_R3_nonsub = non_sub(2)
    p_R1_nonsub = non_sub(0)
    p_2h7_miss_R3 = h7_R1 * h7_R2 * p_R3_nonsub
    p_2h7_miss_R1 = p_R1_nonsub * h7_R2 * h7_R3
    p_2h7_miss_R2 = h7_R1 * (1 - h7_R2 - reel_marg[1].get('wild', 0) - reel_marg[1].get('mini', 0)
                              - reel_marg[1].get('minor', 0) - reel_marg[1].get('major', 0) - reel_marg[1].get('grand', 0)) * h7_R3
    p_2h7_total_miss = p_2h7_miss_R1 + p_2h7_miss_R2 + p_2h7_miss_R3
    # Window-phantom: 3 high7 on TOP or BOT row (visible but not on payline)
    # Need probability that stop+(±1) row shows 3-h7 across all 3 reels
    # For top row: P(R1 stop has h7 at top, R2 has h7 at top, R3 has h7 at top)
    def per_reel_top(reel_idx):
        n = len(strips[reel_idx])
        total = sum(weights[reel_idx])
        p_top = sum(weights[reel_idx][p] for p in range(n) if strips[reel_idx][(p-1) % n] == 'high7') / total
        p_bot = sum(weights[reel_idx][p] for p in range(n) if strips[reel_idx][(p+1) % n] == 'high7') / total
        return p_top, p_bot
    top_R1, bot_R1 = per_reel_top(0)
    top_R2, bot_R2 = per_reel_top(1)
    top_R3, bot_R3 = per_reel_top(2)
    p_phantom_top_3h7 = top_R1 * top_R2 * top_R3
    p_phantom_bot_3h7 = bot_R1 * bot_R2 * bot_R3
    p_phantom_either = p_phantom_top_3h7 + p_phantom_bot_3h7

    print(f'     mid-row 3-high7 (paying):              P={p_3h7_mid*100:.4f}%   1in{round(1/p_3h7_mid) if p_3h7_mid>0 else "∞"}')
    print(f'     2-h7 + 1 non-sub (tease near-miss):    P={p_2h7_total_miss*100:.4f}%   1in{round(1/p_2h7_total_miss) if p_2h7_total_miss>0 else "∞"}')
    print(f'     3-h7 on top row (phantom win):         P={p_phantom_top_3h7*100:.6f}%')
    print(f'     3-h7 on bot row (phantom win):         P={p_phantom_bot_3h7*100:.6f}%')
    print(f'     3-h7 phantom either row:               P={p_phantom_either*100:.6f}%   1in{round(1/p_phantom_either) if p_phantom_either>0 else "∞"}')
    # Grand near-miss: grand on top OR bot of R2 (player sees grand symbol in window, but not on payline)
    grand_top_R2 = sum(weights[1][p] for p in range(len(strips[1])) if strips[1][(p-1) % len(strips[1])] == 'grand') / sum(weights[1])
    grand_bot_R2 = sum(weights[1][p] for p in range(len(strips[1])) if strips[1][(p+1) % len(strips[1])] == 'grand') / sum(weights[1])
    p_grand_visible_not_mid = grand_top_R2 + grand_bot_R2  # rough (some overlap if grand at mid too, ignored)
    print(f'     R2 grand on top or bot row (visible non-paying): P={p_grand_visible_not_mid*100:.4f}%   1in{round(1/p_grand_visible_not_mid) if p_grand_visible_not_mid>0 else "∞"}')
    print()

    # ---- 4. REEL-ASYMMETRY check ----
    print(f'  4. REEL-ASYMMETRY (universal §12 — Strickland/Reid/Harrigan):')
    blanks = [reel_marg[i]['blank'] for i in range(3)]
    top_R1_d = h7_R1 + wild_R1 + reel_marg[0].get('7bar', 0)
    top_R3_d = h7_R3 + wild_R3 + reel_marg[2].get('7bar', 0)
    print(f'     blank: R1={blanks[0]*100:.2f}% R3={blanks[2]*100:.2f}% R2={blanks[1]*100:.2f}%')
    print(f'       rule R1 ≤ R3 ≤ R2: {"✓" if blanks[0] <= blanks[2] <= blanks[1] else "✗"}')
    print(f'     top-prize density (h7+wild+7bar): R1={top_R1_d*100:.2f}% R3={top_R3_d*100:.2f}%')
    print(f'       rule R1 ≥ R3: {"✓" if top_R1_d + 0.005 >= top_R3_d else "✗ (should be ≥)"}')
    print()

    # ---- 5. Blank tier distribution (per §15 PWDF redistribute) ----
    print(f'  5. Blank weight distribution by tier (T1=high-pay-adj, T4=none):')
    PRIORITY = {
        0: [['high7'], ['wild'], ['1bar', '2bar', '3bar', '7bar']],
        1: [['grand'], ['high7'], ['mini', 'minor', 'major']],
        2: [['high7'], ['wild'], ['1bar', '2bar', '3bar', '7bar']],
    }
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
            tier_weights[best_tier].append(weights[ri][p])
        total_blank = sum(weights[ri][p] for p, s in enumerate(strips[ri]) if s == 'blank')
        parts = []
        for t in range(4):
            n_pos = len(tier_weights[t])
            sum_w = sum(tier_weights[t])
            avg_w = sum_w / n_pos if n_pos > 0 else 0
            share_pct = sum_w / total_blank * 100 if total_blank > 0 else 0
            parts.append(f'T{t+1}: {n_pos} pos × ~{avg_w:.0f}w ({share_pct:.1f}% of blank)')
        print(f'     R{ri+1}: ' + ' | '.join(parts))
    print()

    # ---- 6. Strip layout visualization ----
    print(f'  6. Strip layout (B=blank, position-by-position with weights):')
    for ri in range(3):
        n = len(strips[ri])
        line = f'     R{ri+1}: '
        for p in range(n):
            sym = strips[ri][p]
            short = {'blank': 'B', 'wild': 'W', 'high7': 'H', '1bar': '1', '2bar': '2', '3bar': '3', '7bar': '7',
                     'mini': 'm', 'minor': 'n', 'major': 'M', 'grand': 'G'}[sym]
            line += short
        print(line)
    print()

    # ---- 7. Booster window visibility on R2 ----
    if mode_n in (2, 5):
        print(f'  7. R2 booster + grand window visibility (mode {mode_n}):')
        print(f'     mini visible (any row): {win_vis[1]["mini"]*100:.2f}%')
        print(f'     minor visible (any row): {win_vis[1]["minor"]*100:.2f}%')
        print(f'     major visible (any row): {win_vis[1]["major"]*100:.2f}%')
        print(f'     grand visible (any row): {win_vis[1]["grand"]*100:.2f}%   ← key "tease grand" frequency')
        print()


if __name__ == '__main__':
    for mode in [1, 2, 5, 7]:
        dump_mode(mode)
