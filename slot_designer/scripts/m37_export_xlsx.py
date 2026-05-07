"""Export M37 mode 1/2/7 weights to MachineBuilder xlsx (skinId 1/2/7).

Skin 5 already in xlsx; user request: fill 1/2/7 to match latest slot_designer
weights. xlsx uses different R1 strip layout (2 1bar / 3 wild vs slot_designer's
3 1bar / 2 wild) — preserve per-symbol MARGINAL, recompute per-position weight
on xlsx's layout, then re-apply PWDF blank tier redistribute on xlsx layout.

Output verification: per-symbol marginal in xlsx must match slot_designer.
"""
import sys
import json
from pathlib import Path
from openpyxl import load_workbook

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

XLSX_PATH = Path(r'C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Excel\Machine\M37\M37Reel.xlsx')


def jload(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


# Per-mode RIGHT-tier ratio for blank PWDF redistribute
MODE_RATIOS = {1: (4, 3, 2, 1), 7: (4, 3, 2, 1), 2: (5, 4, 2, 1), 5: (5, 4, 2, 1)}

# Per-reel priority groups (T1=highest visual priority, T4=none)
PRIORITY_BY_REEL = {
    0: [['high7'], ['wild'], ['1bar', '2bar', '3bar', '7bar']],  # R1
    1: [['grand'], ['high7'], ['mini', 'minor', 'major']],         # R2
    2: [['high7'], ['wild'], ['1bar', '2bar', '3bar', '7bar']],  # R3
}


def classify_blank_tiers(strip, priority_groups):
    """Per universal §15.7 PWDF redistribute. Returns list of (position, tier_idx)
    for each blank in strip."""
    n = len(strip)
    result = []
    for p in range(n):
        if strip[p] != 'blank':
            continue
        prev_sym = strip[(p - 1) % n]
        next_sym = strip[(p + 1) % n]
        best_tier = len(priority_groups)  # T4 default
        for sym in (prev_sym, next_sym):
            for t_idx, group in enumerate(priority_groups):
                if sym in group:
                    if t_idx < best_tier:
                        best_tier = t_idx
                    break
        result.append((p, best_tier))
    return result


def compute_per_symbol_marginal(strip, weights):
    total = sum(weights)
    margs = {}
    for p, sym in enumerate(strip):
        margs[sym] = margs.get(sym, 0) + weights[p]
    return {s: w / total for s, w in margs.items()}, total


def assign_xlsx_weights(xlsx_strip, sd_marginals, sd_total, mode, reel_idx):
    """Apply slot_designer's per-symbol marginal to xlsx layout.
    For non-blank symbols: per-position weight = (sd_marg × xlsx_total) / count_in_xlsx.
    For blanks: apply PWDF redistribute with mode-specific tier ratio.
    """
    # Pick xlsx_total = sd_total (keeps weight magnitudes similar; ratios are what matter)
    xlsx_total = sd_total
    n = len(xlsx_strip)

    # Count xlsx symbols per reel
    sym_count = {}
    for sym in xlsx_strip:
        sym_count[sym] = sym_count.get(sym, 0) + 1

    # Per-symbol uniform weight (non-blank)
    weights = [0] * n
    for sym, count in sym_count.items():
        if sym == 'blank':
            continue
        target_marg = sd_marginals.get(sym, 0)
        if count == 0 or target_marg == 0:
            continue
        per_pos = max(1, round(target_marg * xlsx_total / count))
        for p in range(n):
            if xlsx_strip[p] == sym:
                weights[p] = per_pos

    # Total non-blank weight assigned
    non_blank_assigned = sum(weights[p] for p in range(n) if xlsx_strip[p] != 'blank')
    # Blank target: keep ratio so total approximates xlsx_total
    target_blank_marg = sd_marginals.get('blank', 0)
    target_total_blank = round(target_blank_marg / (1 - target_blank_marg) * non_blank_assigned)

    # Blank tier classification
    priority = PRIORITY_BY_REEL[reel_idx]
    tier_info = classify_blank_tiers(xlsx_strip, priority)
    if not tier_info:
        return weights

    ratio = MODE_RATIOS[mode]
    n_tiers = len(ratio)
    tier_blanks = [[] for _ in range(n_tiers)]
    for p, t in tier_info:
        t_clamped = min(t, n_tiers - 1)
        tier_blanks[t_clamped].append(p)

    units = sum(len(tier_blanks[t]) * ratio[t] for t in range(n_tiers))
    if units == 0:
        return weights

    base_w = max(1, target_total_blank // units)
    leftover = target_total_blank - base_w * units

    # Initial per-tier weight; round-robin leftover from highest tier first
    flat_blanks = []
    for t_idx in range(n_tiers):
        for p in tier_blanks[t_idx]:
            flat_blanks.append((t_idx, p))

    extras = [0] * len(flat_blanks)
    i = 0
    while leftover > 0:
        extras[i % len(flat_blanks)] += 1
        leftover -= 1
        i += 1

    for (t_idx, p), extra in zip(flat_blanks, extras):
        weights[p] = base_w * ratio[t_idx] + extra

    return weights


def main():
    # Load xlsx
    wb = load_workbook(XLSX_PATH)
    s = wb['Sheet1']

    # 2026-05-07 layout v3: slot_designer is single source of truth.
    # xlsx symbol layout fully overwritten from slot_designer's reel_strips.
    sd_strips = jload(_ROOT / 'slot_designer/weights/M37/reel_strips.json')['reels']
    xlsx_strips = sd_strips  # use slot_designer layout directly

    print('Layout v3 (slot_designer = xlsx, single source of truth):')
    for ri, label in enumerate(['R1', 'R2', 'R3']):
        from collections import Counter
        non_blank = [s for s in sd_strips[ri] if s != 'blank']
        cnt = Counter(non_blank)
        print(f'  {label}: {dict(cnt)}')

    # For each mode, compute marginals + write to xlsx
    # 2026-05-07 v3: also write skin 5 (slot_designer is authoritative)
    skin_to_row = {1: 2, 2: 28, 5: 106, 7: 158}
    for mode in [1, 2, 5, 7]:
        sd_w = jload(_ROOT / f'slot_designer/weights/M37/mode_{mode}/weights.json')['weights']
        print(f'\n=== Mode {mode} export to skinId {mode} (rows {skin_to_row[mode]}-{skin_to_row[mode]+25}) ===')

        for reel_idx in range(3):
            sd_marg, sd_total = compute_per_symbol_marginal(sd_strips[reel_idx], sd_w[reel_idx])
            new_weights = assign_xlsx_weights(xlsx_strips[reel_idx], sd_marg, sd_total, mode, reel_idx)

            # Verify marginal preservation
            xlsx_total = sum(new_weights)
            xlsx_marg_check = {}
            for p, sym in enumerate(xlsx_strips[reel_idx]):
                xlsx_marg_check[sym] = xlsx_marg_check.get(sym, 0) + new_weights[p]
            xlsx_marg_check = {s: w / xlsx_total for s, w in xlsx_marg_check.items()}

            # Print marginal comparison
            label = ['R1', 'R2', 'R3'][reel_idx]
            print(f'  {label} marginal check (sd → xlsx):')
            for sym in sorted(set(xlsx_strips[reel_idx])):
                sd = sd_marg.get(sym, 0)
                xl = xlsx_marg_check.get(sym, 0)
                diff = (xl - sd) * 100
                flag = '✓' if abs(diff) < 0.05 else '⚠'
                print(f'    {sym:6s} sd={sd*100:6.3f}%  xlsx={xl*100:6.3f}%  Δ={diff:+.3f}pp {flag}')

            # Write to xlsx
            sym_col = 2 + reel_idx * 2  # B(2)=R1, D(4)=R2, F(6)=R3
            wt_col = sym_col + 1         # C(3)=w1, E(5)=w2, G(7)=w3
            base_row = skin_to_row[mode]
            for p in range(26):
                s.cell(row=base_row + p, column=sym_col).value = xlsx_strips[reel_idx][p]
                s.cell(row=base_row + p, column=wt_col).value = new_weights[p]

    wb.save(XLSX_PATH)
    print(f'\n✓ xlsx saved: {XLSX_PATH}')


if __name__ == '__main__':
    main()
