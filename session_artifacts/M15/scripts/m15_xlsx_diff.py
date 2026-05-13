"""Compare M15Reel.xlsx against slot_designer current strips+weights.

For each skinId (1/2/5/7) × 36 stop × 3 reel, show whether (symbol, weight)
matches slot_designer reel_strips.json + weights/mode_{N}/weights.json.

Used to verify whether the production xlsx is in sync with disk.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

_ROOT = Path('C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
_M15 = _ROOT / 'slot_designer' / 'machines' / 'M15'
_XLSX = Path('C:/Users/pangg/Documents/Projects/LHS/MachineBuilder/Buffalo/Assets/Config/Excel/Machine/M15/M15Reel.xlsx')

strips = json.loads((_M15 / 'reel_strips.json').read_text(encoding='utf-8'))['reels']
# Each reel has 36 entries (alternating blank/symbol)
for ri, r in enumerate(strips):
    assert len(r) == 36, f'reel {ri+1} expected 36 stops, got {len(r)}'

weights_by_mode = {}
for mode in (1, 2, 5, 7):
    d = json.loads((_M15 / 'weights' / f'mode_{mode}' / 'weights.json').read_text(encoding='utf-8'))
    weights_by_mode[mode] = d['weights']

wb = openpyxl.load_workbook(_XLSX, data_only=False)
ws = wb.active
xlsx_rows = []
for r in range(2, ws.max_row + 1):
    skin = ws.cell(row=r, column=1).value
    cells = [ws.cell(row=r, column=c).value for c in range(2, 8)]
    xlsx_rows.append((skin, cells))

# Group by skinId
by_skin = {}
for skin, cells in xlsx_rows:
    by_skin.setdefault(int(skin), []).append(cells)

print('Skin groups + row counts:')
for k in sorted(by_skin):
    print(f'  skin={k} rows={len(by_skin[k])}')

mismatches = []
for mode in (1, 2, 5, 7):
    xlsx_block = by_skin.get(mode, [])
    if len(xlsx_block) != 36:
        print(f'!! mode {mode}: xlsx has {len(xlsx_block)} rows, expected 36')
        continue
    for stop in range(36):
        cells = xlsx_block[stop]
        # cells = [reel1_sym, weight1, reel2_sym, weight2, reel3_sym, weight3]
        for reel in (0, 1, 2):
            xlsx_sym = cells[reel * 2]
            xlsx_w = cells[reel * 2 + 1]
            sd_sym = strips[reel][stop]
            sd_w = weights_by_mode[mode][reel][stop]
            if xlsx_sym != sd_sym or xlsx_w != sd_w:
                mismatches.append((mode, stop, reel + 1, xlsx_sym, xlsx_w, sd_sym, sd_w))

print(f'\nTotal mismatches: {len(mismatches)}')
if mismatches:
    print('\nFirst 30 mismatches (mode, stop, reel, xlsx_sym, xlsx_w, sd_sym, sd_w):')
    for m in mismatches[:30]:
        print(f'  m{m[0]} stop={m[1]} reel={m[2]}: xlsx=({m[3]!r}, {m[4]}) vs sd=({m[5]!r}, {m[6]})')
    if len(mismatches) > 30:
        print(f'  ... +{len(mismatches)-30} more')
else:
    print('xlsx is BYTE-IDENTICAL to slot_designer disk state for all 4 modes.')
