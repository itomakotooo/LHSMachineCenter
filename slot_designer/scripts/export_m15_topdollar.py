"""Export slot_designer M15 feature_params → real-machine TopDollar config.

Real-machine M15 TopDollar feature uses 3 files:
    M15TopDollar.xlsx       — per-cell ratio weights (10 ratio cells + 2 extraRatio cells per config)
    M15TopDollarTimes.xlsx  — per-config times-count weights (x_count + y_count)
    M15.js                  — SmallGameRewardIDByRtp mapping (RTP → SmallGameReward Id)

Build pipeline: M15.js + xlsx → M15Cfg.txt (real machine reads this).

Slot_designer M15 has 4 modes with feature_params:
    mode 1, 7 — identical feature_params (1+7 share)
    mode 2 — separate
    mode 5 — separate (super-lucky, currently unused in real machine!)

Real machine M15.js currently has:
    SmallGameRewardIDByRtp = { 1:1, 2:2, 5:2 }    # mode 5 shares mode 2 config
    SmallGameReward[] has 3 entries: Id 1, Id 2, Id 5 (Id 5 = unused slot waiting for wiring)

Mapping (TopDollar id ↔ slot_designer mode):
    SmallGameReward Id 1 → mode 1 (also default for mode 7) — TopDollar 2/3, Times 2/3
    SmallGameReward Id 2 → mode 2                            — TopDollar 4/5, Times 4/5
    SmallGameReward Id 5 → mode 5 (after wiring)             — TopDollar 6/7, Times 6/7

This script:
    1. Updates M15TopDollar.xlsx with slot_designer x_value_weights + y_value_weights
       (mode 1 → ids 2,3; mode 2 → ids 4,5; mode 5 → ids 6,7)
    2. Updates M15TopDollarTimes.xlsx with x_count_weights[1:5] (drop count=1) + y_count_weights
    3. Patches M15.js SmallGameRewardIDByRtp to add `5: 5` so mode 5 uses its own config

Caveat: x_count_weights[0] (count=1, ~5% in mode 1) is dropped — xlsx times range is [2,5] only.
Real machine doesn't allow 1-card TopDollar pulls. Slot_designer's expected feature RTP
contribution from count=1 is small (~1pp) and gets folded into [2,5] via re-normalization.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

XLSX_TOPDOLLAR = Path(r"C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Excel\Machine\M15\M15TopDollar.xlsx")
XLSX_TIMES = Path(r"C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Excel\Machine\M15\M15TopDollarTimes.xlsx")
JS_FILE = Path(r"C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Json\Machine\M15.js")

# Slot_designer mode → SmallGameReward Id ↔ (TopDollar ratio_id, TopDollar extraRatio_id, Times ratio_id, Times extraRatio_id)
MODE_TO_TOPDOLLAR = {
    1: {"sgr_id": 1, "ratio_id": 2, "extra_id": 3, "times_ratio_id": 2, "times_extra_id": 3},
    2: {"sgr_id": 2, "ratio_id": 4, "extra_id": 5, "times_ratio_id": 4, "times_extra_id": 5},
    5: {"sgr_id": 5, "ratio_id": 6, "extra_id": 7, "times_ratio_id": 6, "times_extra_id": 7},
    # mode 7 shares mode 1 (DefaultSmallGameRewardID = 1)
}

SCALE = 10000


def get_feature_params(mode: int) -> dict:
    wf = _ROOT / "slot_designer" / "weights" / "M15" / f"mode_{mode}" / "weights.json"
    return json.loads(wf.read_text(encoding="utf-8")).get("feature_params", {})


def parse_topdollar_xlsx(xlsx_path: Path) -> dict:
    """Returns {id: [(row, cellIndex, ratio, type), ...]}."""
    wb = load_workbook(xlsx_path, data_only=True)
    s = wb["Sheet1"]
    out = defaultdict(list)
    for r in range(2, s.max_row + 1):
        tid = s.cell(row=r, column=1).value
        cell_idx = s.cell(row=r, column=2).value
        ratio = s.cell(row=r, column=3).value
        typ = s.cell(row=r, column=5).value
        if tid is None:
            continue
        out[tid].append((r, cell_idx, ratio, typ))
    return out


def parse_times_xlsx(xlsx_path: Path) -> dict:
    """Returns {id: [(row, times), ...]}."""
    wb = load_workbook(xlsx_path, data_only=True)
    s = wb["Sheet1"]
    out = defaultdict(list)
    for r in range(2, s.max_row + 1):
        tid = s.cell(row=r, column=1).value
        times = s.cell(row=r, column=2).value
        if tid is None:
            continue
        out[tid].append((r, times))
    return out


def compute_ratio_weights(x_value_weights: list, ratio_cells: list) -> dict:
    """
    Map slot_designer x_value_weights (10 entries for [1000,100,50,50,20,20,10,10,5,5])
    to xlsx ratio cells.

    Real-machine cells have fixed ratio values; we need to set their weight.
    Strategy: per ratio value, sum slot_designer weights for cells with that value,
    then divide equally among xlsx cells with that ratio.
    """
    # slot_designer x_pool (must match spec, hardcoded)
    SLOT_DESIGNER_X_POOL = [1000, 100, 50, 50, 20, 20, 10, 10, 5, 5]
    if len(x_value_weights) != len(SLOT_DESIGNER_X_POOL):
        raise ValueError(f"x_value_weights len {len(x_value_weights)} != x_pool {len(SLOT_DESIGNER_X_POOL)}")

    # Sum weights per unique ratio value
    weight_per_ratio = defaultdict(float)
    count_per_ratio = defaultdict(int)
    for v, w in zip(SLOT_DESIGNER_X_POOL, x_value_weights):
        weight_per_ratio[v] += w
        count_per_ratio[v] += 1

    # For each xlsx cell, compute weight = (weight_per_ratio[V] / count_per_ratio[V]) × scale
    # Use scale=SCALE so weights are reasonable integers
    total_weight = sum(weight_per_ratio.values())
    out = {}
    for row, cell_idx, ratio, typ in ratio_cells:
        if ratio not in weight_per_ratio:
            # Shouldn't happen, but guard
            out[row] = 0
            continue
        per_cell = weight_per_ratio[ratio] / count_per_ratio[ratio]
        # Normalize to scale
        w_int = max(0, round(per_cell / total_weight * SCALE))
        out[row] = w_int
    return out


def compute_extra_weights(y_value_weights: list, extra_cells: list) -> dict:
    """y_value_weights for 2 extraRatio cells (both ratio=2 in slot_designer).
    Real machine has 2 cells with type=1, ratio doesn't matter (they're multipliers).
    """
    if len(extra_cells) != len(y_value_weights):
        raise ValueError(f"extra_cells {len(extra_cells)} != y_value_weights {len(y_value_weights)}")
    total = sum(y_value_weights)
    out = {}
    for (row, _, _, _), w in zip(extra_cells, y_value_weights):
        out[row] = max(1, round(w / total * SCALE))
    return out


def compute_x_count_weights(x_count_weights: list, count_entries: list) -> dict:
    """
    slot_designer x_count_weights has 5 entries for count_x = 1..5.
    xlsx times entries are typically [2, 3, 4, 5] (count=1 not allowed in real machine).
    We drop slot_designer count=1 and renormalize.
    """
    if len(x_count_weights) != 5:
        raise ValueError(f"x_count_weights must have 5 entries, got {len(x_count_weights)}")
    # Drop count=1 (index 0)
    weights_2_5 = x_count_weights[1:5]
    total = sum(weights_2_5)
    if total == 0:
        return {row: 0 for row, _ in count_entries}
    # xlsx count_entries should map to times 2,3,4,5 in order
    xlsx_times = [t for _, t in count_entries]
    # Build map by times
    out = {}
    for (row, t), w in zip(count_entries, weights_2_5):
        out[row] = max(1, round(w / total * 100))
    return out


def compute_y_count_weights(y_count_weights: list, count_entries: list) -> dict:
    """y_count_weights has 3 entries for count_y = 0..2. Maps directly to xlsx times [0, 1, 2]."""
    if len(y_count_weights) != 3:
        raise ValueError(f"y_count_weights must have 3 entries, got {len(y_count_weights)}")
    total = sum(y_count_weights)
    out = {}
    for (row, t), w in zip(count_entries, y_count_weights):
        out[row] = max(1, round(w / total * 100))
    return out


def update_topdollar_xlsx(xlsx_path: Path, mode_data: dict, output_path: Path):
    """Update M15TopDollar.xlsx weights per mode → ratio_id/extra_id."""
    wb = load_workbook(xlsx_path)
    s = wb["Sheet1"]

    # Build flat row → weight map
    row_to_weight = {}
    for mode, info in mode_data.items():
        fp = info["fp"]
        td = info["td_layout"]
        # ratio_id cells
        ratio_cells = td.get(info["ratio_id"], [])
        ratio_weights = compute_ratio_weights(fp["x_value_weights"], ratio_cells)
        row_to_weight.update(ratio_weights)
        # extra_id cells
        extra_cells = td.get(info["extra_id"], [])
        extra_weights = compute_extra_weights(fp["y_value_weights"], extra_cells)
        row_to_weight.update(extra_weights)

    # Apply
    for r in range(2, s.max_row + 1):
        if r in row_to_weight:
            s.cell(row=r, column=4).value = int(row_to_weight[r])

    wb.save(output_path)


def update_times_xlsx(xlsx_path: Path, mode_data: dict, output_path: Path):
    """Update M15TopDollarTimes.xlsx weights per mode → times_ratio_id (x_count) / times_extra_id (y_count)."""
    wb = load_workbook(xlsx_path)
    s = wb["Sheet1"]

    row_to_weight = {}
    for mode, info in mode_data.items():
        fp = info["fp"]
        times = info["times_layout"]
        # times_ratio_id = x_count
        x_entries = times.get(info["times_ratio_id"], [])
        x_weights = compute_x_count_weights(fp["x_count_weights"], x_entries)
        row_to_weight.update(x_weights)
        # times_extra_id = y_count
        y_entries = times.get(info["times_extra_id"], [])
        y_weights = compute_y_count_weights(fp["y_count_weights"], y_entries)
        row_to_weight.update(y_weights)

    for r in range(2, s.max_row + 1):
        if r in row_to_weight:
            s.cell(row=r, column=3).value = int(row_to_weight[r])

    wb.save(output_path)


def patch_m15_js(js_path: Path, output_path: Path):
    """Add `5: 5,` to SmallGameRewardIDByRtp so mode 5 uses its own SmallGameReward Id 5.

    Original:
        SmallGameRewardIDByRtp:
        {
            1 : 1,
            2 : 2,
            5 : 2,
        },

    Target:
        SmallGameRewardIDByRtp:
        {
            1 : 1,
            2 : 2,
            5 : 5,
        },
    """
    content = js_path.read_text(encoding="utf-8")
    old = "5 : 2,"    # within SmallGameRewardIDByRtp
    new = "5 : 5,"
    if old not in content:
        if new in content:
            return False, "already patched"
        return False, "expected `5 : 2,` not found in M15.js"
    # Only replace the FIRST occurrence (in SmallGameRewardIDByRtp section)
    new_content = content.replace(old, new, 1)
    output_path.write_text(new_content, encoding="utf-8")
    return True, "patched"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--skip-js", action="store_true",
                        help="Don't patch M15.js (mode 5 will share mode 2 config)")
    args = parser.parse_args()

    print(f"TopDollar xlsx: {XLSX_TOPDOLLAR}")
    print(f"Times xlsx: {XLSX_TIMES}")
    print(f"M15.js: {JS_FILE}")

    # Parse layouts
    td_layout = parse_topdollar_xlsx(XLSX_TOPDOLLAR)
    times_layout = parse_times_xlsx(XLSX_TIMES)
    print(f"\nTopDollar ids: {sorted(td_layout.keys())}")
    print(f"Times ids: {sorted(times_layout.keys())}")

    # Build mode data
    mode_data = {}
    for mode, ids in MODE_TO_TOPDOLLAR.items():
        if args.skip_js and mode == 5:
            print(f"[skip-js] skipping mode 5 (would need M15.js patch)")
            continue
        fp = get_feature_params(mode)
        if not fp:
            print(f"WARNING: mode {mode} has no feature_params, skipping")
            continue
        mode_data[mode] = {
            "fp": fp,
            "td_layout": td_layout,
            "times_layout": times_layout,
            **ids,
        }
        print(f"\nMode {mode}: SGR Id {ids['sgr_id']}, TopDollar id {ids['ratio_id']}/{ids['extra_id']}, Times id {ids['times_ratio_id']}/{ids['times_extra_id']}")
        print(f"  x_value_weights: {fp['x_value_weights']}")
        print(f"  y_value_weights: {fp['y_value_weights']}")
        print(f"  x_count_weights: {fp['x_count_weights']}")
        print(f"  y_count_weights: {fp['y_count_weights']}")

    if args.dry_run:
        print("\n[dry-run] no files written")
        return

    # Backup
    if not args.no_backup:
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        for f in [XLSX_TOPDOLLAR, XLSX_TIMES, JS_FILE]:
            if f == JS_FILE and args.skip_js:
                continue
            # CRITICAL: backup must NOT end in .xlsx (build pipeline globs *.xlsx).
            # f.suffix + ".backup_..." produces e.g. "M15TopDollar.xlsx.backup_..."
            # which doesn't end in .xlsx — safe.
            bak = f.with_suffix(f.suffix + f".backup_slot_designer_{ts}")
            shutil.copy2(f, bak)
            print(f"Backup: {bak}")

    # Update files
    print(f"\nUpdating {XLSX_TOPDOLLAR}")
    update_topdollar_xlsx(XLSX_TOPDOLLAR, mode_data, XLSX_TOPDOLLAR)

    print(f"Updating {XLSX_TIMES}")
    update_times_xlsx(XLSX_TIMES, mode_data, XLSX_TIMES)

    if not args.skip_js and 5 in mode_data:
        print(f"Patching {JS_FILE}")
        ok, msg = patch_m15_js(JS_FILE, JS_FILE)
        print(f"  → {msg}")

    print("\nDone. User must run build pipeline (M15.js + xlsx → M15Cfg.txt) to deploy.")


if __name__ == "__main__":
    main()
