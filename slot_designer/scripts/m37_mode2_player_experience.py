"""M37 mode 2 v4 player experience analysis.

Dump comprehensive player-felt metrics for review:
  - Bucket distribution (where RTP comes from + where hits happen)
  - Per-pay_id breakdown (which paths fire most)
  - Big-win frequencies (200×/500×/1000× cycles)
  - Volatility (CV, dry-spell stats, max-loss percentile via simulation)
  - 5-spin / 50-spin / 500-spin RTP distribution from sim
"""
import sys
import json
from pathlib import Path
from random import Random
from collections import Counter, defaultdict

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.engine.loader import load_engine
from slot_designer.devtools.analytic_rtp import analytic_profile


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
        spec_path=_ROOT / 'slot_designer/specs/M37.spec.json',
        strips_path=_ROOT / 'slot_designer/weights/M37/reel_strips.json',
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


if __name__ == '__main__':
    for mode in [1, 2, 5, 7]:
        dump_mode(mode)
