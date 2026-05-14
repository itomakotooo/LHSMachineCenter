"""
Stage 2.5 supplementary analysis — pay_id 8 predicate lock-down for M43.

Usage:
    python session_artifacts/M43/scripts/analyze_pay_id_8.py

Outputs to stdout only (no file write — caller decides what to do with output).
All strings kept ASCII-safe for Windows GBK stdout.
"""

import json
import os
import sys
import re
from collections import defaultdict, Counter

RAWDATA_DIR = "C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT/rawdata/M43/mode_1"
TARGET_PAY_ID = "8"
CONTROL_SAMPLE_SIZE = 10000   # non-pay_id-8 rounds to check false positives

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def parse_stop_col(col_str):
    """
    'top-mid-bot-' -> (top, mid, bot)
    """
    parts = col_str.rstrip('-').split('-')
    if len(parts) == 3:
        return tuple(parts)
    # fallback: some entries may have extra segments; take first 3
    return tuple(parts[:3])


def extract_grid(round_rec):
    """
    Returns (r1, r2, r3) where each is (top, mid, bot).
    Returns None if StopSymbolsByCol missing or malformed.
    """
    cols = round_rec.get('StopSymbolsByCol')
    if not cols or len(cols) < 3:
        return None
    try:
        r1 = parse_stop_col(cols[0])
        r2 = parse_stop_col(cols[1])
        r3 = parse_stop_col(cols[2])
        return (r1, r2, r3)
    except Exception:
        return None


def has_pay_id(round_rec, pid):
    piw = round_rec.get('PayoutIdToWinAmount', {})
    return str(pid) in piw


def get_pay_id_win(round_rec, pid):
    piw = round_rec.get('PayoutIdToWinAmount', {})
    return piw.get(str(pid), 0)


def iter_all_rounds(rawdata_dir):
    """Yield every round dict across all chunks."""
    chunk_files = sorted(
        f for f in os.listdir(rawdata_dir)
        if f.startswith('chunk_') and f.endswith('.json')
    )
    for fname in chunk_files:
        path = os.path.join(rawdata_dir, fname)
        with open(path, 'r', encoding='utf-8') as fh:
            chunk = json.load(fh)
        bet = chunk.get('_bet', 1000)
        # rounds are in chunk['response'] as serialized JSON strings
        response = chunk.get('response', [])
        for robot_result in response:
            if isinstance(robot_result, dict) and 'roundResult' in robot_result:
                raw = robot_result['roundResult']
                if isinstance(raw, str):
                    rounds = json.loads(raw)
                elif isinstance(raw, list):
                    rounds = raw
                else:
                    continue
                for r in rounds:
                    r['_bet'] = bet
                    yield r
            elif isinstance(robot_result, list):
                # direct list of rounds
                for r in robot_result:
                    r['_bet'] = bet
                    yield r


# ---------------------------------------------------------------------------
# candidate predicate functions
# (returns True if the predicate fires for this round's grid)
# ---------------------------------------------------------------------------

WILD_SYMS = {'wild', 'blankup', 'blankdown'}

def count_wilds_in_window(grid):
    """Count wild/blankup/blankdown across entire 3x3 window."""
    (r1t, r1m, r1b), (r2t, r2m, r2b), (r3t, r3m, r3b) = grid
    all_cells = [r1t, r1m, r1b, r2t, r2m, r2b, r3t, r3m, r3b]
    return sum(1 for s in all_cells if s in WILD_SYMS)


def count_sevens_in_window(grid):
    (r1t, r1m, r1b), (r2t, r2m, r2b), (r3t, r3m, r3b) = grid
    all_cells = [r1t, r1m, r1b, r2t, r2m, r2b, r3t, r3m, r3b]
    return sum(1 for s in all_cells if s == '7')


# Payline is mid-row of each reel: r1m, r2m, r3m

def predicate_A_near_three_sevens(grid):
    """
    Candidate A: '3 sevens visible in window but NOT all on payline'
    At least 3 cells with '7' anywhere in the 3x3 grid,
    but payline (r1m,r2m,r3m) is NOT (7,7,7).
    """
    (r1t, r1m, r1b), (r2t, r2m, r2b), (r3t, r3m, r3b) = grid
    payline = (r1m, r2m, r3m)
    n_sevens = count_sevens_in_window(grid)
    return n_sevens >= 3 and payline != ('7', '7', '7')


def predicate_B_two_wilds_one_blank(grid):
    """
    Candidate B: exactly 2 wild/blankup/blankdown cells on the payline
    plus 1 blank on the payline (i.e. 2 wild-markers + 1 blank on mid-row).
    """
    (r1t, r1m, r1b), (r2t, r2m, r2b), (r3t, r3m, r3b) = grid
    payline = [r1m, r2m, r3m]
    n_wild_on_payline = sum(1 for s in payline if s in WILD_SYMS)
    n_blank_on_payline = sum(1 for s in payline if s == 'blank')
    return n_wild_on_payline == 2 and n_blank_on_payline == 1


def predicate_C_wild_adjacent_row_bridge(grid):
    """
    Candidate C: payline has a blank-dominant pattern (all blank/blankup/blankdown)
    but adjacent rows (top and bot) contain 7s or wilds that 'bridge' toward the payline.
    Specifically: payline cells are all non-bar non-7 (i.e. blank or blank-markers),
    and at least 1 seven appears off the payline.
    """
    (r1t, r1m, r1b), (r2t, r2m, r2b), (r3t, r3m, r3b) = grid
    payline = [r1m, r2m, r3m]
    BLANK_SET = {'blank', 'blankup', 'blankdown'}
    payline_all_blank = all(s in BLANK_SET for s in payline)
    off_payline = [r1t, r1b, r2t, r2b, r3t, r3b]
    has_seven_off = any(s == '7' for s in off_payline)
    return payline_all_blank and has_seven_off


# ---------------------------------------------------------------------------
# main analysis
# ---------------------------------------------------------------------------

def main():
    print("=== M43 pay_id 8 deep analysis ===")
    print("Reading chunks from:", RAWDATA_DIR)
    print()

    hit_rounds = []       # rounds with pay_id=8
    control_rounds = []   # non-pay_id-8 ST=1 rounds for false-positive check
    control_cap = CONTROL_SAMPLE_SIZE

    chunk_hit_counts = defaultdict(int)
    chunk_files_seen = set()
    total_paid_rounds = 0
    payout_values = []

    for rnd in iter_all_rounds(RAWDATA_DIR):
        st = rnd.get('SpinType', 0)
        if st != 1:
            continue
        total_paid_rounds += 1

        # which chunk? We use SpinTimes as a proxy; not ideal but we count hits per chunk
        # we'll track via the _bet field presence; chunk tracking done externally
        # Instead, track via index counter

        if has_pay_id(rnd, TARGET_PAY_ID):
            grid = extract_grid(rnd)
            if grid is not None:
                win = get_pay_id_win(rnd, TARGET_PAY_ID)
                bet = rnd.get('_bet', 1000)
                hit_rounds.append({'grid': grid, 'win': win, 'bet': bet, 'round': rnd})
                payout_values.append(win)
        else:
            if len(control_rounds) < control_cap:
                grid = extract_grid(rnd)
                if grid is not None:
                    control_rounds.append({'grid': grid, 'round': rnd})

    n_hits = len(hit_rounds)
    print(f"Total ST=1 (paid) rounds scanned: {total_paid_rounds}")
    print(f"Pay_id 8 hits: {n_hits}")
    print(f"Control (non-pay_id-8) rounds collected: {len(control_rounds)}")
    print()

    # -----------------------------------------------------------------------
    # S1: Payout multiplier histogram
    # -----------------------------------------------------------------------
    print("=== S1: Payout value histogram ===")
    if payout_values:
        payout_counter = Counter(payout_values)
        sample_bet = hit_rounds[0]['bet'] if hit_rounds else 1000
        print(f"(bet={sample_bet})")
        for val, cnt in sorted(payout_counter.items()):
            mult = val / sample_bet if sample_bet > 0 else 0
            pct = 100 * cnt / n_hits
            print(f"  win={val:>8}  ({mult:5.1f}x bet)  count={cnt:4d}  ({pct:5.1f}%)")
        avg_win = sum(payout_values) / len(payout_values)
        avg_mult = avg_win / sample_bet if sample_bet > 0 else 0
        print(f"  avg win={avg_win:.0f}  avg mult={avg_mult:.2f}x")
        total_rtp_pp = (sum(payout_values) / (total_paid_rounds * sample_bet)) * 100
        print(f"  RTP contribution: {total_rtp_pp:.3f} pp")
    print()

    # -----------------------------------------------------------------------
    # S2: Mid-row (payline) payload distribution
    # -----------------------------------------------------------------------
    print("=== S2: Payline (mid-row) symbol distribution ===")
    payline_patterns = Counter()
    for h in hit_rounds:
        (r1t, r1m, r1b), (r2t, r2m, r2b), (r3t, r3m, r3b) = h['grid']
        payline_patterns[(r1m, r2m, r3m)] += 1
    for pat, cnt in payline_patterns.most_common(30):
        pct = 100 * cnt / n_hits
        print(f"  {pat[0]:<12} {pat[1]:<12} {pat[2]:<12}  n={cnt:4d}  ({pct:5.1f}%)")
    print()

    # -----------------------------------------------------------------------
    # S3: Adjacent row (top+bot) pattern distribution
    # -----------------------------------------------------------------------
    print("=== S3: Adjacent row (top+bot per reel) symbol distribution ===")
    # For each reel, what symbols appear on top/bot when pay_id=8 fires?
    top_patterns = Counter()  # (r1t, r2t, r3t)
    bot_patterns = Counter()  # (r1b, r2b, r3b)
    for h in hit_rounds:
        (r1t, r1m, r1b), (r2t, r2m, r2b), (r3t, r3m, r3b) = h['grid']
        top_patterns[(r1t, r2t, r3t)] += 1
        bot_patterns[(r1b, r2b, r3b)] += 1

    print("  Top row (r1top, r2top, r3top) most common:")
    for pat, cnt in top_patterns.most_common(20):
        pct = 100 * cnt / n_hits
        print(f"    {pat[0]:<12} {pat[1]:<12} {pat[2]:<12}  n={cnt:4d}  ({pct:5.1f}%)")
    print()
    print("  Bot row (r1bot, r2bot, r3bot) most common:")
    for pat, cnt in bot_patterns.most_common(20):
        pct = 100 * cnt / n_hits
        print(f"    {pat[0]:<12} {pat[1]:<12} {pat[2]:<12}  n={cnt:4d}  ({pct:5.1f}%)")
    print()

    # -----------------------------------------------------------------------
    # S4: Wild + blankup + blankdown position cross-tab
    # -----------------------------------------------------------------------
    print("=== S4: Wild/blankup/blankdown position cross-tab ===")
    # For each cell in the 3x3 grid, count how often it holds a wild-family symbol
    # Cells: r1t r1m r1b  r2t r2m r2b  r3t r3m r3b
    cell_names = [
        'R1-top','R1-mid','R1-bot',
        'R2-top','R2-mid','R2-bot',
        'R3-top','R3-mid','R3-bot',
    ]

    def grid_to_cells(grid):
        (r1t,r1m,r1b),(r2t,r2m,r2b),(r3t,r3m,r3b) = grid
        return [r1t,r1m,r1b,r2t,r2m,r2b,r3t,r3m,r3b]

    cell_wild_counts = [0]*9
    cell_blankup_counts = [0]*9
    cell_blankdown_counts = [0]*9
    cell_seven_counts = [0]*9

    for h in hit_rounds:
        cells = grid_to_cells(h['grid'])
        for i, s in enumerate(cells):
            if s == 'wild':
                cell_wild_counts[i] += 1
            elif s == 'blankup':
                cell_blankup_counts[i] += 1
            elif s == 'blankdown':
                cell_blankdown_counts[i] += 1
            elif s == '7':
                cell_seven_counts[i] += 1

    print(f"  Cell         | wild  | blankup | blankdown |   7   | any-wild-fam")
    print(f"  -------------|-------|---------|-----------|-------|-------------")
    for i, name in enumerate(cell_names):
        w  = cell_wild_counts[i]
        bu = cell_blankup_counts[i]
        bd = cell_blankdown_counts[i]
        sv = cell_seven_counts[i]
        any_wf = w + bu + bd
        print(f"  {name:<12} | {100*w/n_hits:5.1f}% | {100*bu/n_hits:7.1f}% | "
              f"{100*bd/n_hits:9.1f}% | {100*sv/n_hits:5.1f}% | {100*any_wf/n_hits:5.1f}%")
    print()

    # Also: total wild-family count distribution per round
    print("  Wild-family cell count per pay_id=8 round:")
    wf_count_dist = Counter()
    for h in hit_rounds:
        cells = grid_to_cells(h['grid'])
        n_wf = sum(1 for s in cells if s in WILD_SYMS)
        wf_count_dist[n_wf] += 1
    for k in sorted(wf_count_dist):
        pct = 100 * wf_count_dist[k] / n_hits
        print(f"    {k} wild-family cells: {wf_count_dist[k]:4d}  ({pct:5.1f}%)")
    print()

    # Seven count distribution per round
    print("  Seven count per pay_id=8 round:")
    seven_count_dist = Counter()
    for h in hit_rounds:
        cells = grid_to_cells(h['grid'])
        n7 = sum(1 for s in cells if s == '7')
        seven_count_dist[n7] += 1
    for k in sorted(seven_count_dist):
        pct = 100 * seven_count_dist[k] / n_hits
        print(f"    {k} sevens in window: {seven_count_dist[k]:4d}  ({pct:5.1f}%)")
    print()

    # -----------------------------------------------------------------------
    # S5: Predicate candidate evaluation on HIT rounds
    # -----------------------------------------------------------------------
    print("=== S5: Predicate candidate evaluation on pay_id=8 HIT rounds ===")

    preds = {
        'A_near_3_sevens':    predicate_A_near_three_sevens,
        'B_2wild_1blank_payline': predicate_B_two_wilds_one_blank,
        'C_blank_payline_off7': predicate_C_wild_adjacent_row_bridge,
    }

    hit_pred_counts = {name: 0 for name in preds}
    # combinations
    hit_combo = Counter()

    for h in hit_rounds:
        combo = []
        for name, fn in preds.items():
            fires = fn(h['grid'])
            if fires:
                hit_pred_counts[name] += 1
            combo.append('1' if fires else '0')
        hit_combo[tuple(combo)] += 1

    print(f"  n_hits = {n_hits}")
    for name, cnt in hit_pred_counts.items():
        coverage = 100 * cnt / n_hits if n_hits > 0 else 0
        print(f"  {name:<32}: fires on {cnt:4d} / {n_hits}  ({coverage:.1f}% hit coverage)")
    print()
    print("  Combination coverage (A B C):")
    for combo, cnt in sorted(hit_combo.items(), key=lambda x: -x[1]):
        pct = 100 * cnt / n_hits
        labels = ['A' if c=='1' else '_' for c in combo]
        labels[1] = 'B' if combo[1]=='1' else '_'
        labels[2] = 'C' if combo[2]=='1' else '_'
        print(f"    {''.join(labels)}  n={cnt:4d}  ({pct:5.1f}%)")
    print()

    # -----------------------------------------------------------------------
    # Also: explore exact full-grid pattern and payout correlation
    # -----------------------------------------------------------------------
    print("=== S5b: Full grid pattern distribution for pay_id=8 hits ===")
    grid_pattern_counter = Counter()
    for h in hit_rounds:
        (r1t,r1m,r1b),(r2t,r2m,r2b),(r3t,r3m,r3b) = h['grid']
        key = f"({r1t},{r1m},{r1b})|({r2t},{r2m},{r2b})|({r3t},{r3m},{r3b})"
        grid_pattern_counter[key] += 1

    print(f"  Distinct grid patterns across {n_hits} hits: {len(grid_pattern_counter)}")
    print("  Top 30 patterns:")
    for pat, cnt in grid_pattern_counter.most_common(30):
        pct = 100 * cnt / n_hits
        print(f"    {pat:<55}  n={cnt:3d}  ({pct:4.1f}%)")
    print()

    # -----------------------------------------------------------------------
    # Explore: payout correlation with grid features
    # -----------------------------------------------------------------------
    print("=== S5c: Payout split by wild-family count on payline ===")
    payline_wf_payout = defaultdict(list)
    for h in hit_rounds:
        (r1t,r1m,r1b),(r2t,r2m,r2b),(r3t,r3m,r3b) = h['grid']
        payline = [r1m, r2m, r3m]
        n_wf_pl = sum(1 for s in payline if s in WILD_SYMS)
        win = h['win']
        bet = h['bet']
        payline_wf_payout[n_wf_pl].append(win / bet)
    for k in sorted(payline_wf_payout):
        vals = payline_wf_payout[k]
        avg = sum(vals)/len(vals)
        mn = min(vals)
        mx = max(vals)
        val_dist = Counter(vals)
        print(f"  payline_wf={k}: n={len(vals):4d}  avg={avg:.2f}x  min={mn:.1f}x  max={mx:.1f}x  dist={dict(sorted(val_dist.items()))}")
    print()

    print("=== S5d: Payout split by total wild-family cells in window ===")
    window_wf_payout = defaultdict(list)
    for h in hit_rounds:
        cells = grid_to_cells(h['grid'])
        n_wf_win = sum(1 for s in cells if s in WILD_SYMS)
        win = h['win']
        bet = h['bet']
        window_wf_payout[n_wf_win].append(win / bet)
    for k in sorted(window_wf_payout):
        vals = window_wf_payout[k]
        avg = sum(vals)/len(vals)
        mn = min(vals)
        mx = max(vals)
        val_dist = Counter(vals)
        print(f"  window_wf={k}: n={len(vals):4d}  avg={avg:.2f}x  min={mn:.1f}x  max={mx:.1f}x  dist={dict(sorted(val_dist.items()))}")
    print()

    # -----------------------------------------------------------------------
    # S6: False-positive check on control (non-pay_id-8) rounds
    # -----------------------------------------------------------------------
    print("=== S6: False-positive check on non-pay_id-8 control rounds ===")
    n_ctrl = len(control_rounds)
    ctrl_pred_counts = {name: 0 for name in preds}

    for cr in control_rounds:
        for name, fn in preds.items():
            if fn(cr['grid']):
                ctrl_pred_counts[name] += 1

    for name, cnt in ctrl_pred_counts.items():
        fp_rate = 100 * cnt / n_ctrl if n_ctrl > 0 else 0
        print(f"  {name:<32}: fires on {cnt:4d} / {n_ctrl} control rounds  ({fp_rate:.3f}% FP rate)")
    print()

    # -----------------------------------------------------------------------
    # Summary decision
    # -----------------------------------------------------------------------
    print("=== SUMMARY ===")
    for name, fn in preds.items():
        n_hits_covered = hit_pred_counts[name]
        coverage = 100 * n_hits_covered / n_hits if n_hits > 0 else 0
        fp_count = ctrl_pred_counts[name]
        fp_rate = 100 * fp_count / n_ctrl if n_ctrl > 0 else 0
        print(f"  {name}")
        print(f"    hit coverage:  {coverage:.1f}%  ({n_hits_covered}/{n_hits})")
        print(f"    FP rate:       {fp_rate:.3f}%  ({fp_count}/{n_ctrl})")
        feasible = coverage >= 95 and fp_rate < 0.5
        print(f"    feasible:      {'YES (coverage>=95% AND FP<0.5%)' if feasible else 'NO'}")
        print()

    print("Done.")


if __name__ == '__main__':
    main()
