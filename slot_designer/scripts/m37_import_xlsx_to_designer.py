"""Reverse import: read MachineBuilder/.../M37/M37Reel.xlsx and write
slot_designer/weights/M37/{reel_strips.json, mode_N/weights.json}
so the virtual_console engine samples with EXACTLY the same reel data
that goes into the real Buffalo cfg.

Used so user can pull rawdata from virtual_console + compare to real
Buffalo rawdata side-by-side, without any transformation drift.
"""
from __future__ import annotations
import json, hashlib
from pathlib import Path
import openpyxl

_ROOT = Path(__file__).resolve().parent.parent.parent
XLSX_PATH = Path(r'C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Excel\Machine\M37\M37Reel.xlsx')
WEIGHTS_DIR = _ROOT / 'slot_designer' / 'weights' / 'M37'

# skinId → mode mapping
SKIN_TO_MODE = {1: 1, 2: 2, 5: 5, 7: 7}


def read_skin(ws, sid: int):
    rows = []
    for r in range(2, ws.max_row + 1):
        if ws.cell(r, 1).value != sid: continue
        rows.append({
            'r1_sym': ws.cell(r, 2).value, 'r1_w': ws.cell(r, 3).value,
            'r2_sym': ws.cell(r, 4).value, 'r2_w': ws.cell(r, 5).value,
            'r3_sym': ws.cell(r, 6).value, 'r3_w': ws.cell(r, 7).value,
        })
    if len(rows) != 26:
        raise ValueError(f'expected 26 stops for skin {sid}, got {len(rows)}')
    strips = [
        [r['r1_sym'] for r in rows],
        [r['r2_sym'] for r in rows],
        [r['r3_sym'] for r in rows],
    ]
    weights = [
        [int(r['r1_w']) for r in rows],
        [int(r['r2_w']) for r in rows],
        [int(r['r3_w']) for r in rows],
    ]
    return strips, weights


def main():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb[wb.sheetnames[0]]
    print(f'reading {XLSX_PATH}')

    # All active skins should share same symbol layout (slot_designer convention)
    skins_data = {sid: read_skin(ws, sid) for sid in SKIN_TO_MODE.keys()}

    # Verify all skins have IDENTICAL symbol layout
    base_strips, _ = skins_data[1]
    for sid in SKIN_TO_MODE.keys():
        sk_strips, _ = skins_data[sid]
        for ri in range(3):
            if sk_strips[ri] != base_strips[ri]:
                print(f'  WARN: skin {sid} R{ri+1} layout differs from skin 1!')
                # Show diff
                for i in range(26):
                    if sk_strips[ri][i] != base_strips[ri][i]:
                        print(f'    pos {i}: skin1={base_strips[ri][i]}, skin{sid}={sk_strips[ri][i]}')

    # Write reel_strips.json (shared across modes)
    strips_doc = {
        'machine': 'M37',
        'reel_set': 'default',
        '_source': 'imported from MachineBuilder M37Reel.xlsx skin 1 layout',
        'reels': base_strips,
    }
    strips_path = WEIGHTS_DIR / 'reel_strips.json'
    strips_path.write_text(json.dumps(strips_doc, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'  wrote: {strips_path}')

    # Write per-mode weights
    for sid, mode in SKIN_TO_MODE.items():
        _, weights = skins_data[sid]
        wpath = WEIGHTS_DIR / f'mode_{mode}' / 'weights.json'
        wpath.parent.mkdir(parents=True, exist_ok=True)
        # Read existing notes if any
        try:
            existing = json.loads(wpath.read_text(encoding='utf-8'))
            notes = existing.get('_notes', [])
        except (FileNotFoundError, json.JSONDecodeError):
            notes = []
        if isinstance(notes, list):
            notes.append(f'imported from MachineBuilder M37Reel.xlsx skin {sid}')
        doc = {
            'machine': 'M37',
            'mode': mode,
            'reel_set': 'default',
            '_notes': notes,
            'weights': weights,
        }
        wpath.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding='utf-8')
        totals = [sum(w) for w in weights]
        print(f'  mode {mode} (skin {sid}): wrote {wpath}, totals R1/R2/R3 = {totals}')

    # Print summary
    print(f'\\nDone. virtual_console engine will now sample with exactly the data')
    print(f'in {XLSX_PATH.name}.')

if __name__ == '__main__':
    main()
