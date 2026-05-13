"""Restore missing skinIds 3/4/6/8/9/10/11 to M15Reel.xlsx from v8.1 backup.

After v14 ship, M15Reel.xlsx has only skinIds 1/2/5/7 (4 modes I designed).
But production build pipeline expects 11 skinIds (1-11). User flagged "其他几个
不用的 skinId 缺少数据，随便填一下".

This script:
1. Backs up current M15Reel.xlsx (v14 state)
2. Reads v8.1 backup for skin 3/4/6/8/9/10/11 data
3. Appends those skins to current xlsx (preserving v14 skin 1/2/5/7)
"""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import openpyxl

XLSX_PROD = Path('C:/Users/pangg/Documents/Projects/LHS/MachineBuilder/Buffalo/Assets/Config/Excel/Machine/M15/M15Reel.xlsx')
XLSX_V81 = Path('C:/Users/pangg/Documents/Projects/LHS/MachineBuilder/Buffalo/Assets/Config/Excel/Machine/M15/_backup/M15Reel.backup_slot_designer_v81_20260511T134731.bak')
TMP_V81 = Path('C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT/session_artifacts/M15/_tmp_v81_M15Reel.xlsx')
BACKUP_DIR = XLSX_PROD.parent / '_backup'

# Skins to restore from v8.1 (the "unused" ones in v14 production)
MISSING_SKINS = {3, 4, 6, 8, 9, 10, 11}
KEEP_SKINS = {1, 2, 5, 7}  # v14 designed modes — DO NOT TOUCH


def main():
    # Ensure v8.1 backup is readable (.bak → .xlsx)
    if not TMP_V81.exists():
        shutil.copy2(XLSX_V81, TMP_V81)
        print(f'Copied v8.1 backup → {TMP_V81}')

    # Read current xlsx (v14 state, 4 skins × 36 rows = 144 rows)
    wb_cur = openpyxl.load_workbook(XLSX_PROD, data_only=False)
    ws_cur = wb_cur.active
    print(f'Current xlsx: max_row={ws_cur.max_row}')

    # Collect current rows by skin
    cur_skin_rows = {}
    for r in range(2, ws_cur.max_row + 1):
        rid = ws_cur.cell(row=r, column=1).value
        if rid is None:
            continue
        cur_skin_rows.setdefault(rid, []).append([ws_cur.cell(row=r, column=c).value for c in range(1, 8)])
    print(f'Current skins + row counts: {dict(sorted((k, len(v)) for k, v in cur_skin_rows.items()))}')

    # Read v8.1 backup
    wb_v81 = openpyxl.load_workbook(TMP_V81, data_only=False)
    ws_v81 = wb_v81.active
    print(f'\nv8.1 backup xlsx: max_row={ws_v81.max_row}')

    v81_skin_rows = {}
    for r in range(2, ws_v81.max_row + 1):
        rid = ws_v81.cell(row=r, column=1).value
        if rid is None:
            continue
        v81_skin_rows.setdefault(rid, []).append([ws_v81.cell(row=r, column=c).value for c in range(1, 8)])
    print(f'v8.1 skins + row counts: {dict(sorted((k, len(v)) for k, v in v81_skin_rows.items()))}')

    # Build new xlsx with skins in order: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
    # Skins in KEEP_SKINS take from current; skins in MISSING_SKINS take from v8.1
    target_skins = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

    # Backup current xlsx before modifying
    ts = dt.datetime.now().strftime('%Y%m%dT%H%M%S')
    bak_path = BACKUP_DIR / f'M15Reel.backup_v14_pre_restore_unused_skins_{ts}.bak'
    shutil.copy2(XLSX_PROD, bak_path)
    print(f'\nBackup current xlsx → {bak_path}')

    # Open fresh workbook for write, preserving structure
    wb_new = openpyxl.load_workbook(XLSX_PROD, data_only=False)
    ws_new = wb_new.active

    # Clear existing data rows (keep header row 1)
    ws_new.delete_rows(2, ws_new.max_row)

    # Write in order
    row_cursor = 2
    final_skin_counts = {}
    for skin in target_skins:
        if skin in KEEP_SKINS:
            rows = cur_skin_rows.get(skin, [])
            source = 'v14 (current)'
        else:
            rows = v81_skin_rows.get(skin, [])
            source = 'v8.1 backup'

        if not rows:
            print(f'  WARNING: skin {skin} has no rows in {source}, skipping')
            continue

        final_skin_counts[skin] = len(rows)
        for row in rows:
            for c, val in enumerate(row, start=1):
                ws_new.cell(row=row_cursor, column=c).value = val
            row_cursor += 1
        print(f'  Wrote skin {skin} ({len(rows)} rows) from {source}')

    wb_new.save(XLSX_PROD)
    print(f'\nFinal: max_row={row_cursor - 1}, skins: {final_skin_counts}')
    print(f'Saved → {XLSX_PROD}')


if __name__ == '__main__':
    main()
