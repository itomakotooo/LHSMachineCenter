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
    """DEPRECATED — uniform per-(symbol, reel) weights. Use compute_weights_per_position
    instead to preserve PWDF redistribution.

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
                w = 1
            else:
                n = cnt[sym]
                w = max(1, round(d * scale / n))
            out[(row, r)] = w
    return out


def compute_weights_per_position(reel_positions: dict,
                                  sd_weights: list[list[int]],
                                  sd_strips: list[list[str]],
                                  scale: int = SCALE) -> dict:
    """Preserve slot_designer per-position weights (not just per-(symbol, reel)
    marginals). Critical for PWDF redistribution where same-symbol positions
    have DIFFERENT weights (top-adj Blanks heavy, non-top-adj light).

    Scale per reel: each reel's xlsx total ≈ `scale`. Per-position xlsx weight
    = sd_weight[r][p] × scale / sum(sd_weights[r]). Min weight 1.

    reel_positions: {reel: [(row, symbol), ...]}  (xlsx layout, must match
                    sd_strips byte-for-byte after symbol-sync upstream)
    sd_weights: slot_designer's per-position weights array [reel][position]
    sd_strips: slot_designer's strips [reel][position]
    """
    out = {}
    for r, positions in reel_positions.items():
        sd_total = sum(sd_weights[r])
        if sd_total <= 0:
            for row, _ in positions:
                out[(row, r)] = 1
            continue
        # Scale slot_designer weights to xlsx total ~scale, preserving
        # per-position ratios.
        for p, (row, xlsx_sym) in enumerate(positions):
            sd_sym = sd_strips[r][p]
            if sd_sym != xlsx_sym:
                # symbol mismatch — caller must have not done symbol-sync first
                # Fallback: weight 1
                out[(row, r)] = 1
                continue
            sd_w = sd_weights[r][p]
            xlsx_w = max(1, round(sd_w * scale / sd_total))
            out[(row, r)] = xlsx_w
    return out


def write_xlsx(xlsx_path: Path, all_weights: dict, output_path: Path,
               all_symbols: dict | None = None):
    """Write weights + (optionally) symbols.

    all_weights: {skinId: {(row, reel): weight}}
    all_symbols: {skinId: {(row, reel): symbol}} — when provided, also rewrite
                 symbol-at-position columns. Required when slot_designer strip
                 layout differs from xlsx layout (e.g., M1 alternation fix
                 changed pos 13 from Blank to Cherry — without this, xlsx
                 keeps stale 3-consecutive-blank layout).
    """
    wb = load_workbook(xlsx_path)
    s = wb["Sheet1"]
    weight_cols = {0: 3, 1: 5, 2: 7}
    symbol_cols = {0: 2, 1: 4, 2: 6}
    all_symbols = all_symbols or {}
    for r in range(2, s.max_row + 1):
        sid = s.cell(row=r, column=1).value
        if sid not in all_weights:
            continue
        for reel, col in weight_cols.items():
            w = all_weights[sid].get((r, reel))
            if w is not None:
                s.cell(row=r, column=col).value = int(w)
        # Optionally rewrite symbols for slot_designer-mapped skins
        if sid in all_symbols:
            for reel, col in symbol_cols.items():
                sym = all_symbols[sid].get((r, reel))
                if sym is not None:
                    s.cell(row=r, column=col).value = sym
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

    # Load slot_designer's canonical strip layout for symbol-column sync
    strips_path = _ROOT / "slot_designer" / "weights" / machine / "reel_strips.json"
    sd_strips = None
    if strips_path.exists():
        sd_strips = json.loads(strips_path.read_text(encoding="utf-8"))["reels"]
        print(f"Strip layout source: {strips_path.relative_to(_ROOT)} ({len(sd_strips[0])} stops)")

    all_weights = {}
    all_symbols = {}
    for mode, skin in mode_to_skin.items():
        if skin not in layout:
            print(f"  mode {mode} → skin {skin}: SKIP (not in xlsx)")
            continue
        try:
            marg = get_designed_marginals(machine, mode)
        except FileNotFoundError as e:
            print(f"  mode {mode}: SKIP ({e})")
            continue

        # Symbol-column sync (only when slot_designer strip layout differs from xlsx).
        # Required for layouts that changed structurally (e.g. M1 alternation fix
        # 2026-04-28: pos 13 R0/R3 + pos 15 R2 changed Blank → Cherry).
        skin_layout = layout[skin]
        skin_n = len(skin_layout[0])

        # Load slot_designer per-position weights (for PWDF redistribution preservation)
        sd_weights_path = _ROOT / "slot_designer" / "weights" / machine / f"mode_{mode}" / "weights.json"
        sd_weights = None
        if sd_weights_path.exists():
            sd_weights = json.loads(sd_weights_path.read_text(encoding="utf-8")).get("weights")

        if sd_strips is not None and skin_n == len(sd_strips[0]):
            sym_map = {}
            xlsx_layout_differs = False
            for reel_idx in range(3):
                for pos_idx, (row_idx, xlsx_sym) in enumerate(skin_layout[reel_idx]):
                    sd_sym = sd_strips[reel_idx][pos_idx]
                    sym_map[(row_idx, reel_idx)] = sd_sym
                    if sd_sym != xlsx_sym:
                        xlsx_layout_differs = True
            all_symbols[skin] = sym_map
            # Build sd-symbol layout (post-symbol-sync representation)
            synced_layout = {
                r_idx: [(skin_layout[r_idx][p_idx][0], sd_strips[r_idx][p_idx])
                        for p_idx in range(skin_n)]
                for r_idx in range(3)
            }
            if sd_weights is not None:
                # PER-POSITION WEIGHT EXPORT — preserves PWDF redistribution
                # (top-adj Blanks heavy, non-top-adj at floor)
                weights = compute_weights_per_position(
                    synced_layout, sd_weights, sd_strips
                )
                if xlsx_layout_differs:
                    print(f"  mode {mode} → skin {skin}: layout differs from xlsx — "
                          f"sync symbols + per-position weights to slot_designer")
                else:
                    print(f"  mode {mode} → skin {skin}: per-position weight export "
                          f"(PWDF redistribution preserved)")
            else:
                # Fallback: per-(symbol, reel) uniform (loses per-position info)
                weights = compute_weights(synced_layout if xlsx_layout_differs else skin_layout, marg)
                print(f"  mode {mode} → skin {skin}: per-symbol uniform fallback "
                      f"(no slot_designer weights file)")
        else:
            weights = compute_weights(skin_layout, marg)
            if sd_strips is not None:
                print(f"  mode {mode} → skin {skin}: skin stop count {skin_n} ≠ "
                      f"slot_designer {len(sd_strips[0])} — keeping xlsx layout")

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
    write_xlsx(xlsx_path, all_weights, xlsx_path, all_symbols=all_symbols)

    print(f"\n=== Verification: marginal density on {machine} target skins ===")
    verify_conversion(xlsx_path, target_skins)


if __name__ == "__main__":
    main()
