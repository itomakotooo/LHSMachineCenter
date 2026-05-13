"""Verify M15TopDollar.xlsx + M15TopDollarTimes.xlsx in sync with sd feature_params.

User 2026-05-12 lock: feature_params byte-equal v9 for all 4 modes — these xlsx
files should NOT have changed across this session.

X-card mapping (M15TopDollar.xlsx):
  id 2 (rows 2-13)   = mode 1+7 X cards (10 cards) + Y cards (2 cards)
  id 4/5 (rows 14-25) = mode 2 X+Y cards
  id 6/7 (rows 26-37) = mode 5 X+Y cards

X/Y count mapping (M15TopDollarTimes.xlsx):
  id 2 = mode 1+7 X counts (times 2/3/4/5)
  id 3 = mode 1+7 Y counts (times 0/1/2)
  id 4 = mode 2 X counts
  id 5 = mode 2 Y counts
  id 6 = mode 5 X counts
  id 7 = mode 5 Y counts
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

_ROOT = Path('C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
_XLSX_TD = Path('C:/Users/pangg/Documents/Projects/LHS/MachineBuilder/Buffalo/Assets/Config/Excel/Machine/M15/M15TopDollar.xlsx')
_XLSX_TDT = Path('C:/Users/pangg/Documents/Projects/LHS/MachineBuilder/Buffalo/Assets/Config/Excel/Machine/M15/M15TopDollarTimes.xlsx')


def read_xlsx_rows(path):
    wb = openpyxl.load_workbook(path, data_only=False)
    ws = wb.active
    rows = []
    for r in range(2, ws.max_row + 1):
        rows.append([ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)])
    return rows


print('=== M15TopDollar.xlsx (X+Y card weights) ===\n')
td_rows = read_xlsx_rows(_XLSX_TD)

# Group by id
by_id = {}
for row in td_rows:
    rid = row[0]
    by_id.setdefault(rid, []).append(row)

print('Available ids:', sorted(by_id.keys()))
print()

mode_to_id_pair = {1: (2, 3), 7: (2, 3), 2: (4, 5), 5: (6, 7)}

for mode in (1, 2, 5, 7):
    print(f'--- mode {mode} ---')
    sd_fp_path = _ROOT / 'slot_designer' / 'machines' / 'M15' / 'weights' / f'mode_{mode}' / 'weights.json'
    sd_fp = json.loads(sd_fp_path.read_text(encoding='utf-8'))['feature_params']

    x_id, y_id = mode_to_id_pair[mode]
    x_xlsx_rows = [r for r in by_id.get(x_id, []) if r[4] == 0]  # type 0 = X cards
    y_xlsx_rows = [r for r in by_id.get(y_id, []) if r[4] == 1]  # type 1 = Y cards

    # X cards: sort by ratio desc to compare with sd x_value_weights (which is sorted by _X_POOL = (1000, 100, 50, 50, 20, 20, 10, 10, 5, 5))
    # xlsx X cards have (cellIndex, ratio, weight); _X_POOL ratios are (1000, 100, 50, 50, 20, 20, 10, 10, 5, 5) in same order
    # x_value_weights[i] corresponds to _X_POOL[i] (i=0 is 1000, i=9 is 5)
    # Normalize: sum of x_value_weights, then × 10000 → expected xlsx weight per card

    sd_x_val = sd_fp['x_value_weights']
    sd_x_val_sum = sum(sd_x_val)
    sd_x_val_xlsx_eq = [round(v * 10000 / sd_x_val_sum) for v in sd_x_val]

    # Compare xlsx X cards with sd (after sort)
    # xlsx X cards have cellIndex, ratio, weight in row[1], row[2], row[3]
    # Sort xlsx X cards by ratio desc to match _X_POOL order
    x_xlsx_sorted = sorted(x_xlsx_rows, key=lambda r: (-r[2], r[1]))  # ratio desc, cellIndex asc for ties
    print(f'  X cards: id={x_id}')
    print(f'    xlsx weights ({len(x_xlsx_sorted)} cards): {[r[3] for r in x_xlsx_sorted]}')
    print(f'    sd_x_val (raw):                            {sd_x_val}')
    print(f'    sd → xlsx-equiv (×10000/sum, rounded):     {sd_x_val_xlsx_eq}')

    sd_total = sum(sd_x_val_xlsx_eq)
    xlsx_total = sum(r[3] for r in x_xlsx_sorted)
    print(f'    Totals: xlsx={xlsx_total} sd_eq={sd_total}')

    # Y cards: sd Y values + weights
    sd_y_val = sd_fp['y_value_weights']
    sd_y_val_sum = sum(sd_y_val)
    sd_y_val_xlsx_eq = [round(v * 10000 / sd_y_val_sum) for v in sd_y_val]
    y_xlsx_sorted = sorted(y_xlsx_rows, key=lambda r: r[1])
    print(f'  Y cards: id={y_id}')
    print(f'    xlsx weights: {[r[3] for r in y_xlsx_sorted]}')
    print(f'    sd → xlsx-equiv: {sd_y_val_xlsx_eq}')
    print()


print('=== M15TopDollarTimes.xlsx (X/Y count weights) ===\n')
tdt_rows = read_xlsx_rows(_XLSX_TDT)

# Group by id
by_id_t = {}
for row in tdt_rows:
    rid = row[0]
    by_id_t.setdefault(rid, []).append(row)

print('Available ids:', sorted(by_id_t.keys()))
print()

# Mode map for times: id 1 + id 2 = mode 1+7 X count weights
# Per memory: id 1 has times=1 weight=1 (the count=1 entry maybe)
# id 2 has times 2/3/4/5
# id 3 has Y counts 0/1/2 for mode 1+7
# id 4 = mode 2 X counts 2/3/4/5
# id 5 = mode 2 Y counts
# id 6 = mode 5 X counts
# id 7 = mode 5 Y counts

# For mode 1+7 X count: combine id=1 (times 1) + id=2 (times 2/3/4/5)
mode_x_id = {1: (1, 2), 7: (1, 2), 2: (1, 4), 5: (1, 6)}  # combine id 1 with mode-specific id
mode_y_id = {1: 3, 7: 3, 2: 5, 5: 7}

for mode in (1, 2, 5, 7):
    print(f'--- mode {mode} ---')
    sd_fp_path = _ROOT / 'slot_designer' / 'machines' / 'M15' / 'weights' / f'mode_{mode}' / 'weights.json'
    sd_fp = json.loads(sd_fp_path.read_text(encoding='utf-8'))['feature_params']

    # X count: combine id 1 + mode-specific id
    base_id, mode_id = mode_x_id[mode]
    x_count_rows = []
    if base_id in by_id_t:
        x_count_rows += [r for r in by_id_t[base_id] if r[1] == 1]
    if mode_id in by_id_t:
        x_count_rows += [r for r in by_id_t[mode_id] if r[1] in (2, 3, 4, 5)]
    x_count_rows = sorted(x_count_rows, key=lambda r: r[1])

    sd_xc = sd_fp['x_count_weights']  # [count=1, count=2, ..., count=5]
    print(f'  x_count_weights (count 1-5):')
    print(f'    xlsx: {[(r[1], r[2]) for r in x_count_rows]}')
    print(f'    sd:   {sd_xc}')

    # Y count: mode-specific id
    y_id = mode_y_id[mode]
    y_count_rows = sorted([r for r in by_id_t.get(y_id, []) if r[1] in (0, 1, 2)], key=lambda r: r[1])
    sd_yc = sd_fp['y_count_weights']  # [count=0, count=1, count=2]
    print(f'  y_count_weights (count 0-2): id={y_id}')
    print(f'    xlsx: {[(r[1], r[2]) for r in y_count_rows]}')
    print(f'    sd:   {sd_yc}')
    print()
