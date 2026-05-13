"""Ship M5_HMV2_M7 to slot_designer mode 5 + M15Reel.xlsx skinId=5 block.

Per user 2026-05-12: ship mode 5 + update all 3 production xlsx files.

M5_HMV2_M7: super-lucky 500% RTP with base ≥30× shift to 45.05% (vs M2_LC 36.17%).
Trade-off accepted: base hit drops 31.94% (vs m2 33.85%); LUCKY-MONO hit ladder
breaks in agent-derived philosophy (NOT user-stated).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path('C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

M15_DIR = _ROOT / 'slot_designer' / 'machines' / 'M15'
SD_WEIGHTS_PATH = M15_DIR / 'weights' / 'mode_5' / 'weights.json'
STRIPS_PATH = M15_DIR / 'reel_strips.json'
SPEC_PATH = M15_DIR / 'spec.json'

XLSX_REEL = Path('C:/Users/pangg/Documents/Projects/LHS/MachineBuilder/Buffalo/Assets/Config/Excel/Machine/M15/M15Reel.xlsx')
XLSX_BACKUP_DIR = XLSX_REEL.parent / '_backup'

# M5_HMV2_M7 per-reel marginals (percent) from design_v14e_mode5.md §1
TARGET_MARG_PCT = [
    {'cherry': 8.448, '1bar': 14.827, '2bar': 12.103, '3bar': 15.604,
     'high7': 13.385, 'doublediamond': 3.168, 'jackpot': 0.400},
    {'cherry': 8.316, '1bar': 16.166, '2bar': 13.248, '3bar': 14.697,
     'high7': 13.473, 'doublediamond': 2.898, 'jackpot': 0.400},
    {'cherry': 6.600, '1bar': 16.512, '2bar': 13.452, '3bar': 13.835,
     'high7': 13.442, 'doublediamond': 2.346, 'topdollar': 3.327,
     'jackpot': 0.300},
]


def stop_counts_per_reel(strips):
    out = []
    for reel in strips:
        c = defaultdict(int)
        for s in reel:
            c[s] += 1
        out.append(dict(c))
    return out


def marginals_to_weights(strips, marg_pct, scale=10000):
    counts_per_reel = stop_counts_per_reel(strips)
    out = []
    for ri, reel in enumerate(strips):
        target = marg_pct[ri]
        counts = counts_per_reel[ri]
        non_blank_pct = sum(target.values())
        blank_pct = 100 - non_blank_pct
        wps = {}
        for sym, pct in target.items():
            cnt = counts.get(sym, 0)
            if cnt == 0:
                continue
            w = scale * (pct / 100.0) / cnt
            wps[sym] = max(1, int(round(w)))
        wps['blank'] = max(1, int(round(scale * blank_pct / 100.0 / counts['blank'])))
        row = [wps.get(s, 1) for s in reel]
        out.append(row)
    return out


def apply_mechanism_b_blanks(strips, weights, top_symbols=('doublediamond', 'high7', 'topdollar'), floor=1):
    out = [list(r) for r in weights]
    top = set(top_symbols)
    for ri, reel in enumerate(strips):
        n = len(reel)
        total_blank = sum(out[ri][i] for i in range(n) if reel[i] == 'blank')
        top_adj, non_top_adj = [], []
        for i in range(n):
            if reel[i] != 'blank':
                continue
            if reel[(i - 1) % n] in top or reel[(i + 1) % n] in top:
                top_adj.append(i)
            else:
                non_top_adj.append(i)
        if not top_adj:
            continue
        reserve = floor * len(non_top_adj)
        leftover = total_blank - reserve
        if leftover <= 0:
            continue
        per = leftover // len(top_adj)
        rem = leftover - per * len(top_adj)
        for i in non_top_adj:
            out[ri][i] = floor
        for k, i in enumerate(top_adj):
            out[ri][i] = per + (1 if k < rem else 0)
    return out


def compute_session_profile(weights, strips, fp):
    margs = []
    for ri in range(3):
        by_sym = defaultdict(float)
        for stop, sym in enumerate(strips[ri]):
            by_sym[sym] += weights[ri][stop]
        tot = sum(by_sym.values())
        margs.append({s: w / tot for s, w in by_sym.items()})

    tmp_path = _ROOT / 'session_artifacts' / 'M15' / '_tmp_v14e_ship_mode5.json'
    tmp_path.write_text(json.dumps({
        'machine': 'M15', 'mode': 5, 'reel_set': 'default',
        'weights': weights, 'feature_params': fp,
    }, indent=2), encoding='utf-8')
    engine, _ = load_engine(SPEC_PATH, tmp_path, strips_path=STRIPS_PATH)
    prof = analytic_profile_from_marginals(engine.evaluator, margs)
    tmp_path.unlink()

    trigger = margs[2].get('topdollar', 0.0)
    base_rtp = prof['rtp_pct']
    base_hit = prof['hit_rate']
    dist = _round_payout_distribution(tuple(fp['x_count_weights']),
                                       tuple(fp['y_count_weights']),
                                       tuple(fp['x_value_weights']),
                                       tuple(fp['y_value_weights']))
    p_accept = sum(p for r, p in dist if r >= fp['accept_threshold'])
    accept = [(r, p) for r, p in dist if r >= fp['accept_threshold']]
    final = defaultdict(float)
    for ri in range(1, fp['max_rounds']):
        b = ((1 - p_accept) ** (ri - 1)) * p_accept
        for r, p in accept:
            final[r] += b * (p / p_accept) if p_accept > 0 else 0
    b = (1 - p_accept) ** (fp['max_rounds'] - 1)
    for r, p in dist:
        final[r] += b * p
    feat_total = sum(r * p for r, p in final.items())

    return {
        'margs': margs,
        'base_rtp': base_rtp,
        'feature_rtp': trigger * feat_total * 100,
        'total_rtp': base_rtp + trigger * feat_total * 100,
        'hit_session': (base_hit + trigger) * 100,
        'base_hit': base_hit * 100,
        'trigger': trigger * 100,
        'r1_blank': margs[0]['blank'] * 100,
        'r3_blank': margs[2]['blank'] * 100,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args()

    strips = json.loads(STRIPS_PATH.read_text(encoding='utf-8'))['reels']
    fp = json.loads(SD_WEIGHTS_PATH.read_text(encoding='utf-8'))['feature_params']

    print('=== Building M5_HMV2_M7 weights ===')
    w0 = marginals_to_weights(strips, TARGET_MARG_PCT, scale=10000)
    w = apply_mechanism_b_blanks(strips, w0)
    print(f'  R1 sum={sum(w[0])} R2 sum={sum(w[1])} R3 sum={sum(w[2])}')
    print()

    prof = compute_session_profile(w, strips, fp)
    print('=== Resulting profile ===')
    for k in ('total_rtp', 'feature_rtp', 'base_rtp', 'hit_session',
              'base_hit', 'trigger', 'r1_blank', 'r3_blank'):
        print(f'  {k:18s} = {prof[k]:7.3f}')
    print()
    print('=== Cross-mode checks vs M2_LC + M1 C38 (shipped) ===')
    print(f'  CROSS-RTP m5    = {prof["total_rtp"]:.3f}  band [490, 510]')
    print(f'  RTP m5 > m2     = {prof["total_rtp"]:.3f} > 295.78  {"PASS" if prof["total_rtp"] > 295.78 else "FAIL"}')
    print(f'  Trigger m5 > m2 = {prof["trigger"]:.3f} > 3.30  {"PASS" if prof["trigger"] > 3.30 else "FAIL"}')
    print(f'  R1 ≥ R3 blank   = {prof["r1_blank"]:.3f} >= {prof["r3_blank"]:.3f}  {"PASS" if prof["r1_blank"] >= prof["r3_blank"] else "FAIL"}')
    print(f'  Hit m5 vs m2    = {prof["hit_session"]:.3f} vs ~37.13 (m2 session); INFO ONLY — user accepts -1.91pp base hit per "mult shift" priority')

    expected = {'total_rtp': 506.03, 'base_hit': 31.94, 'r1_blank': 32.07, 'r3_blank': 30.19}
    print()
    print('=== Compared to D v14e M5_HMV2_M7 ===')
    actual = {'total_rtp': prof['total_rtp'], 'base_hit': prof['base_hit'],
              'r1_blank': prof['r1_blank'], 'r3_blank': prof['r3_blank']}
    for k in expected:
        diff = actual[k] - expected[k]
        print(f'  {k:14s}  expected={expected[k]:7.3f}  actual={actual[k]:7.3f}  diff={diff:+6.3f}')

    if not args.write:
        print('\n(dry-run — re-run with --write to commit to disk + xlsx)')
        return

    ts = dt.datetime.now().strftime('%Y%m%dT%H%M%S')
    backup_sd = _ROOT / 'session_artifacts' / 'M15' / '_backup'
    backup_sd.mkdir(parents=True, exist_ok=True)
    sd_backup_path = backup_sd / f'mode_5_weights_v9_pre_v14e_{ts}.json'
    shutil.copy2(SD_WEIGHTS_PATH, sd_backup_path)
    print(f'\nBackup sd weights → {sd_backup_path}')

    weights_doc = json.loads(SD_WEIGHTS_PATH.read_text(encoding='utf-8'))
    weights_doc['weights'] = w
    weights_doc['notes'] = (f'v14e M5_HMV2_M7 — super-lucky 500% RTP with base ≥30× mult share 45% '
                            f'(vs M2_LC 36%, target ≥45% met). Derived from M2_LC anchor via per-family scalars: '
                            f'c×1.32 b1×0.68 b2×0.68 b3×1.40 h×1.10 dd×1.15 td×1.007. Mass shifted from low-mult '
                            f'(bar_mixed/bar1/bar2) to high-mult (bar3/h7/wild_pure). Trade-off: base hit 31.94% '
                            f'(-1.91pp vs m2 33.85%) — agent-philosophy LUCKY-MONO hit ladder fails but '
                            f'this is NOT user-stated (user 2026-05-11: "mode 2/5/7 不是 user-stated"; user 2026-05-12: '
                            f'"mode 5 比 mode 2 倍率向高 shift" prioritized over hit ladder). feature_params byte-equal v9 (locked).')
    SD_WEIGHTS_PATH.write_text(json.dumps(weights_doc, indent=2), encoding='utf-8')
    print(f'Wrote new sd mode 5 weights → {SD_WEIGHTS_PATH}')

    import openpyxl
    XLSX_BACKUP_DIR.mkdir(exist_ok=True)
    xlsx_backup_path = XLSX_BACKUP_DIR / f'M15Reel.backup_mode5_v9_to_v14e_{ts}.bak'
    shutil.copy2(XLSX_REEL, xlsx_backup_path)
    print(f'Backup xlsx → {xlsx_backup_path}')

    wb = openpyxl.load_workbook(XLSX_REEL, data_only=False)
    ws = wb.active
    # skin 1: rows 2-37, skin 2: 38-73, skin 5: 74-109, skin 7: 110-145
    skin_5_start_row = 74
    for stop in range(36):
        r = skin_5_start_row + stop
        for reel in range(3):
            col_sym = 2 + reel * 2
            col_w = 3 + reel * 2
            ws.cell(row=r, column=col_sym).value = strips[reel][stop]
            ws.cell(row=r, column=col_w).value = w[reel][stop]
    wb.save(XLSX_REEL)
    print(f'Updated xlsx mode 5 / skinId=5 → {XLSX_REEL}')


if __name__ == '__main__':
    main()
