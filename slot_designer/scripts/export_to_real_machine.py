"""Generic exporter: slot_designer designed weights → real-machine M*Reel.xlsx.

Real-machine xlsx format:
    skinId | reel1 | weight1 | reel2 | weight2 | reel3 | weight3
    - Multiple skinIds, each with its own stop layout (rows)
    - skinId may map to slot_designer mode (verified per machine)
    - Weights per stop position (we set per-family per-reel uniform)

Usage:
    python export_to_real_machine.py --machine M37
    python export_to_real_machine.py --machine M1 --map "1=1,2=2,5=5,7=7"
    python export_to_real_machine.py --machine M15 --map "1=1,2=8,5=9,7=11"

Per-machine notes:
    M37: skinId == mode (direct mapping). 7 skinIds, all 26 stops, identical structure.
         (BUT: real machine actually reads ExcelNew/Machine2026/M37.xlsx PayoutWeights,
          NOT this M37Reel.xlsx — see commit history for explanation.)
    M1:  skinId == mode (direct). 7 skinIds with different stop counts (skin 6: 10 stops).
    M15: skinId != mode. Custom mapping needed.
         mode 1→skin 1, mode 2→skin 8, mode 5→skin 9, mode 7→skin 11
         (verified from rawdata ReelSkin field). Other skinIds (2-7, 10) for
         TopDollar feature spins, not in slot_designer 4-mode design.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import compute_reel_marginal
from slot_designer.engine.loader import load_engine

DEFAULT_MAPS = {
    "M37": {1: 1, 2: 2, 5: 5, 7: 7},
    "M1":  {1: 1, 2: 2, 5: 5, 7: 7},
    "M15": {1: 1, 2: 8, 5: 9, 7: 11},
}

XLSX_PATHS = {
    "M37": Path(r"C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Excel\Machine\M37\M37Reel.xlsx"),
    "M1":  Path(r"C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Excel\Machine\M1\M1Reel.xlsx"),
    "M15": Path(r"C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Excel\Machine\M15\M15Reel.xlsx"),
}

SCALE = 10000


def get_designed_marginals(machine: str, mode: int) -> dict:
    """Return {(reel, symbol): density}."""
    spec = _ROOT / "slot_designer" / "specs" / f"{machine}.spec.json"
    weights = _ROOT / "slot_designer" / "weights" / machine / f"mode_{mode}" / "weights.json"
    if not spec.exists() or not weights.exists():
        raise FileNotFoundError(f"Missing spec or weights for {machine} mode {mode}")
    engine, _ = load_engine(spec, weights)
    out = {}
    for r in range(len(engine.reels)):
        marg = compute_reel_marginal(engine.reels[r])
        for sym, d in marg.items():
            if d > 0:
                out[(r, sym)] = d
    return out


def parse_xlsx_layout(xlsx_path: Path) -> dict:
    """Parse {skinId: {reel: [(row, symbol), ...]}}."""
    wb = load_workbook(xlsx_path, data_only=True)
    s = wb["Sheet1"]
    layout = {}
    for r in range(2, s.max_row + 1):
        sid = s.cell(row=r, column=1).value
        if sid is None:
            continue
        d = layout.setdefault(sid, {0: [], 1: [], 2: []})
        d[0].append((r, s.cell(row=r, column=2).value))
        d[1].append((r, s.cell(row=r, column=4).value))
        d[2].append((r, s.cell(row=r, column=6).value))
    return layout


def compute_weights(reel_positions: dict, designed_marg: dict, scale: int = SCALE) -> dict:
    """Per-family per-reel uniform weights matching designed marginal density.

    reel_positions: {reel: [(row, symbol), ...]}
    designed_marg: {(reel, symbol): density}
    Returns: {(row, reel): weight}
    """
    out = {}
    for r, positions in reel_positions.items():
        cnt = Counter(sym for _, sym in positions)
        for row, sym in positions:
            d = designed_marg.get((r, sym), 0.0)
            if d == 0:
                # Symbol exists on real-machine reel but not in slot_designer design.
                # Set to 1 (minimum). This means slot_designer didn't model this symbol —
                # might happen if real machine has extra symbols (e.g., M15 'topdollar' on R3).
                w = 1
            else:
                n = cnt[sym]
                w = max(1, round(d * scale / n))
            out[(row, r)] = w
    return out


def write_xlsx(xlsx_path: Path, all_weights: dict, output_path: Path):
    """Write weights. all_weights: {skinId: {(row, reel): weight}}."""
    wb = load_workbook(xlsx_path)
    s = wb["Sheet1"]
    weight_cols = {0: 3, 1: 5, 2: 7}
    for r in range(2, s.max_row + 1):
        sid = s.cell(row=r, column=1).value
        if sid not in all_weights:
            continue
        for reel, col in weight_cols.items():
            w = all_weights[sid].get((r, reel))
            if w is not None:
                s.cell(row=r, column=col).value = int(w)
    wb.save(output_path)


def verify_conversion(xlsx_path: Path, target_skins: set):
    """Compute marginal density per skin/reel from xlsx after write."""
    wb = load_workbook(xlsx_path, data_only=True)
    s = wb["Sheet1"]
    by_skin = defaultdict(lambda: {0: [], 1: [], 2: []})
    for r in range(2, s.max_row + 1):
        sid = s.cell(row=r, column=1).value
        if sid is None:
            continue
        by_skin[sid][0].append((s.cell(row=r, column=2).value, s.cell(row=r, column=3).value))
        by_skin[sid][1].append((s.cell(row=r, column=4).value, s.cell(row=r, column=5).value))
        by_skin[sid][2].append((s.cell(row=r, column=6).value, s.cell(row=r, column=7).value))
    for sid in sorted(target_skins):
        if sid not in by_skin:
            continue
        print(f"\nskinId {sid}:")
        for r in range(3):
            sym_w = defaultdict(int)
            total = 0
            for sym, w in by_skin[sid][r]:
                w = int(w) if w is not None else 0
                sym_w[sym] += w
                total += w
            density_str = "  ".join(
                f"{sym}={sym_w[sym]/total*100:.3f}%"
                for sym in sorted(sym_w.keys()) if sym_w[sym] > 0
            )
            print(f"  R{r+1} (total={total}): {density_str}")


def parse_map(s: str) -> dict:
    out = {}
    for pair in s.split(","):
        m, sk = pair.split("=")
        out[int(m.strip())] = int(sk.strip())
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine", required=True, choices=list(XLSX_PATHS.keys()))
    parser.add_argument("--xlsx", default=None,
                        help="override xlsx path (defaults per machine)")
    parser.add_argument("--map", default=None,
                        help="mode→skin map, e.g. '1=1,2=8,5=9,7=11' (defaults per machine)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true",
                        help="skip backup creation")
    args = parser.parse_args()

    machine = args.machine
    xlsx_path = Path(args.xlsx) if args.xlsx else XLSX_PATHS[machine]
    mode_to_skin = parse_map(args.map) if args.map else DEFAULT_MAPS[machine]

    if not xlsx_path.exists():
        print(f"ERROR: xlsx not found: {xlsx_path}")
        sys.exit(1)

    print(f"Machine: {machine}")
    print(f"xlsx:    {xlsx_path}")
    print(f"Mapping: mode→skin = {mode_to_skin}")

    layout = parse_xlsx_layout(xlsx_path)
    available = sorted(layout.keys())
    print(f"Available skinIds in xlsx: {available}")

    target_skins = set(mode_to_skin.values())
    missing = target_skins - set(available)
    if missing:
        print(f"WARNING: target skins {missing} not found in xlsx")

    all_weights = {}
    for mode, skin in mode_to_skin.items():
        if skin not in layout:
            print(f"  mode {mode} → skin {skin}: SKIP (not in xlsx)")
            continue
        try:
            marg = get_designed_marginals(machine, mode)
        except FileNotFoundError as e:
            print(f"  mode {mode}: SKIP ({e})")
            continue
        weights = compute_weights(layout[skin], marg)
        all_weights[skin] = weights
        wmin, wmax = min(weights.values()), max(weights.values())
        print(f"  mode {mode} → skin {skin}: {len(weights)} weights, range [{wmin}, {wmax}]")

    if args.dry_run:
        print("\n[dry-run] no files written")
        return

    if not args.no_backup:
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        # CRITICAL: backup must NOT end in .xlsx — MachineBuilder build pipeline
        # picks up ALL *.xlsx files in directory and includes them in M*Cfg.txt.
        # If backup is .xlsx, it gets compiled alongside the original and runtime
        # engine may pick up the wrong one (verified with M1 case 2026-04-28).
        backup = xlsx_path.with_suffix(f".xlsx.backup_slot_designer_{ts}")
        shutil.copy2(xlsx_path, backup)
        print(f"\nBackup: {backup}")

    print(f"Writing: {xlsx_path}")
    write_xlsx(xlsx_path, all_weights, xlsx_path)

    print(f"\n=== Verification: marginal density on {machine} target skins ===")
    verify_conversion(xlsx_path, target_skins)


if __name__ == "__main__":
    main()
