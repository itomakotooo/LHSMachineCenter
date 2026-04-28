"""Export M37 slot_designer weights to real-machine M37Reel.xlsx format.

Real machine xlsx structure:
    skinId | reel1 | weight1 | reel2 | weight2 | reel3 | weight3
    - 7 skinIds (1-7), each with 26 stops per reel
    - skinId == mode (verified from rawdata: mode 1 → ReelSkin=1, etc.)
    - Strip layout (symbol arrangement) is FIXED in real machine
    - We update only the weights to match slot_designer marginal density

Mapping: skinId 1→mode 1, 2→mode 2, 5→mode 5, 7→mode 7. Other skinIds untouched.

Per-family per-reel uniform: all positions of same symbol on same reel get same weight
(consistent with slot_designer design philosophy).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import compute_reel_marginal, analytic_profile
from slot_designer.engine.loader import load_engine


SPEC = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
DEFAULT_XLSX = Path(
    r"C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Excel\Machine\M37\M37Reel.xlsx"
)
SCALE = 10000    # target reel total weight


def get_designed_marginals(mode: int) -> dict:
    """Return {(reel, symbol): density} for designed mode."""
    wp = _ROOT / "slot_designer" / "weights" / "M37" / f"mode_{mode}" / "weights.json"
    engine, _ = load_engine(SPEC, wp)
    out = {}
    for r in range(3):
        marg = compute_reel_marginal(engine.reels[r])
        for sym, d in marg.items():
            if d > 0:
                out[(r, sym)] = d
    return out


def parse_xlsx_layout(xlsx_path: Path) -> dict:
    """Parse layout: {skinId: {reel: [(row, symbol), ...]}}."""
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


def compute_weights_for_skin(reel_positions: dict, designed_marg: dict,
                             scale: int = SCALE) -> dict:
    """Compute per-position weights matching designed density.

    reel_positions: {reel: [(row, symbol), ...]}
    designed_marg: {(reel, symbol): density}
    Returns: {(row, reel): weight}
    """
    out = {}
    for r in range(3):
        # count positions per symbol
        positions = reel_positions[r]
        cnt = Counter(sym for _, sym in positions)
        # per-position weight = density * scale / num_positions, rounded to int (≥ 1)
        for row, sym in positions:
            d = designed_marg.get((r, sym), 0.0)
            if d == 0:
                w = 1    # symbol not in design → minimum weight (shouldn't happen)
            else:
                w = max(1, round(d * scale / cnt[sym]))
            out[(row, r)] = w
    return out


# NOTE 2026-04-28: M37 export to M37Reel.xlsx is OBSOLETE — real machine reads
# ExcelNew/Machine2026/M37.xlsx PayoutWeights model, NOT M37Reel.xlsx. This
# script is kept only as reference. For M1/M15 use export_to_real_machine.py.
# Backup files MUST NOT end in .xlsx (build pipeline globs *.xlsx in dir).


def write_xlsx(xlsx_path: Path, all_weights: dict, output_path: Path):
    """Write weights to xlsx. all_weights: {skinId: {(row, reel): weight}}."""
    wb = load_workbook(xlsx_path)
    s = wb["Sheet1"]
    weight_cols = {0: 3, 1: 5, 2: 7}    # weight1=col 3, weight2=col 5, weight3=col 7
    for r in range(2, s.max_row + 1):
        sid = s.cell(row=r, column=1).value
        if sid not in all_weights:
            continue
        for reel, col in weight_cols.items():
            w = all_weights[sid].get((r, reel))
            if w is not None:
                s.cell(row=r, column=col).value = int(w)
    wb.save(output_path)


def verify_conversion(xlsx_path: Path):
    """Read back xlsx and print resulting marginal density per skin/reel."""
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
    for sid in sorted(by_skin.keys()):
        if sid not in (1, 2, 5, 7):
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


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", default=str(DEFAULT_XLSX),
                        help="path to M37Reel.xlsx (read + write in place)")
    parser.add_argument("--output", default=None,
                        help="output path (default: overwrite xlsx)")
    parser.add_argument("--dry-run", action="store_true",
                        help="show planned changes without writing")
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    output_path = Path(args.output) if args.output else xlsx_path

    if not xlsx_path.exists():
        print(f"ERROR: xlsx not found: {xlsx_path}")
        sys.exit(1)

    print(f"Reading: {xlsx_path}")
    layout = parse_xlsx_layout(xlsx_path)
    print(f"Found skinIds: {sorted(layout.keys())}")

    all_weights = {}
    for skin_id in (1, 2, 5, 7):
        if skin_id not in layout:
            print(f"WARNING: skinId {skin_id} not found in xlsx, skipping")
            continue
        marg = get_designed_marginals(skin_id)
        weights = compute_weights_for_skin(layout[skin_id], marg)
        all_weights[skin_id] = weights
        print(f"  skinId {skin_id}: computed {len(weights)} weights")

    if args.dry_run:
        print("\n[dry-run] would write to:", output_path)
        for sid in sorted(all_weights.keys()):
            ws = all_weights[sid]
            print(f"  skinId {sid}: weight range [{min(ws.values())}, {max(ws.values())}]")
        return

    print(f"\nWriting: {output_path}")
    write_xlsx(xlsx_path, all_weights, output_path)
    print("\n=== Verification: actual marginal density on output xlsx ===")
    verify_conversion(output_path)


if __name__ == "__main__":
    main()
