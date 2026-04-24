"""Compile ``slot_designer/weights/M15/feature_weights.tsv`` into each
mode's ``feature_params`` block inside ``mode_<N>/weights.json``.

The TSV is the designer-authored SOURCE OF TRUTH for all 4 modes'
Feature Play parameters. The per-mode ``weights.json`` ``feature_params``
block is a compiled mirror — never hand-edit the JSON block directly;
edit the TSV and re-run this compile step.

TSV schema:
  - Comment lines start with ``#``; blank lines ignored.
  - Data rows are TAB-separated: ``knob | description | mode_1 | mode_2 | mode_5 | mode_7``
  - Recognized knobs:
      count_x[1..5]         5 tuple → x_count_weights
      count_y[0..2]         3 tuple → y_count_weights
      x_val[V]              V ∈ {1000,100,50,20,10,5} → expanded to
                            10-slot x_value_weights aligned with
                            feature_m15._X_POOL
      y_val[slot_a|slot_b]  2 tuple → y_value_weights
      accept_threshold      scalar
      max_rounds            scalar int

Usage:
  python -m slot_designer.scripts.compile_m15_features_from_tsv
  python -m slot_designer.scripts.compile_m15_features_from_tsv --check
      (exit 1 if any mode's on-disk feature_params would change)

The ``--check`` mode is used by the regression test
``test_feature_tsv_is_source_of_truth`` to ensure TSV and JSON never
drift. Run it in CI after any TSV or weights.json edit.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.engine.feature_m15 import _X_POOL, _Y_POOL


_TSV_PATH = _ROOT / "slot_designer" / "weights" / "M15" / "feature_weights.tsv"
_MACHINE_DIR = _ROOT / "slot_designer" / "weights" / "M15"
_MODES = (1, 2, 5, 7)


def _parse_tsv(tsv_text: str) -> tuple[list[int], dict[str, list[str]]]:
    """Parse feature TSV into (modes_list, rows_dict).

    rows_dict maps knob-name → list of per-mode string values (in the
    order of modes_list). Raw string values; caller converts to numbers.
    """
    header: list[str] | None = None
    rows: dict[str, list[str]] = {}
    for raw_line in tsv_text.splitlines():
        line = raw_line.rstrip("\n").rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if header is None:
            if cols[0].strip() != "knob":
                raise ValueError(
                    f"first non-comment row must start with 'knob'; got {cols[0]!r}"
                )
            header = cols
            continue
        if len(cols) != len(header):
            raise ValueError(
                f"row has {len(cols)} cols, header has {len(header)}: {cols!r}"
            )
        knob = cols[0].strip()
        if knob in rows:
            raise ValueError(f"duplicate knob {knob!r} in TSV")
        rows[knob] = [c.strip() for c in cols[2:]]
    if header is None:
        raise ValueError("TSV has no header row")
    # Modes list from header columns 2..end
    modes: list[int] = []
    for col_name in header[2:]:
        col = col_name.strip()
        if not col.startswith("mode_"):
            raise ValueError(f"header column {col!r} must look like 'mode_<N>'")
        try:
            modes.append(int(col.split("_", 1)[1]))
        except (ValueError, IndexError):
            raise ValueError(f"can't parse mode number from header {col!r}")
    return modes, rows


def _num(s: str) -> float | int:
    """Parse a TSV cell as int if it's integral, else float."""
    try:
        i = int(s)
        if "." not in s and "e" not in s.lower():
            return i
    except ValueError:
        pass
    return float(s)


def _compile_mode(
    mode: int,
    modes: list[int],
    rows: dict[str, list[str]],
) -> dict:
    """Produce the feature_params dict for one mode from parsed TSV rows."""
    if mode not in modes:
        raise ValueError(f"TSV has no column for mode {mode}; header modes: {modes}")
    col = modes.index(mode)

    def cell(knob: str) -> str:
        if knob not in rows:
            raise ValueError(f"TSV missing required knob {knob!r}")
        return rows[knob][col]

    # count_x (5 tuple)
    x_count = [_num(cell(f"count_x[{k}]")) for k in range(1, 6)]
    # count_y (3 tuple)
    y_count = [_num(cell(f"count_y[{k}]")) for k in range(0, 3)]

    # x_value_weights: TSV gives per-unique-value weight; expand to 10-slot
    # aligned with _X_POOL.
    unique_vals = sorted(set(_X_POOL), reverse=True)
    per_value_weight: dict[int, float] = {}
    for v in unique_vals:
        per_value_weight[v] = float(_num(cell(f"x_val[{v}]")))
    x_value_weights = [per_value_weight[v] for v in _X_POOL]

    # y_value_weights (2 tuple)
    y_value_weights = [
        _num(cell("y_val[slot_a]")),
        _num(cell("y_val[slot_b]")),
    ]
    if len(y_value_weights) != len(_Y_POOL):
        raise ValueError(
            f"y_value_weights length {len(y_value_weights)} != _Y_POOL length "
            f"{len(_Y_POOL)}; TSV schema mismatch"
        )

    accept_threshold = _num(cell("accept_threshold"))
    max_rounds = _num(cell("max_rounds"))
    if not isinstance(max_rounds, int):
        max_rounds = int(max_rounds)

    fp: dict = {
        "_note": (
            f"v7+ mode {mode} Feature Play params. **AUTO-GENERATED** from "
            f"slot_designer/weights/M15/feature_weights.tsv — do NOT hand-edit "
            f"this block; edit the TSV and re-run compile_m15_features_from_tsv."
        ),
        "x_count_weights": x_count,
        "y_count_weights": y_count,
        "x_value_weights": x_value_weights,
        "y_value_weights": y_value_weights,
        "accept_threshold": accept_threshold,
        "max_rounds": max_rounds,
    }
    return fp


def _write_or_check_mode(
    mode: int,
    compiled_fp: dict,
    *,
    check_only: bool,
) -> bool:
    """Write compiled feature_params into ``mode_<mode>/weights.json``,
    or (if ``check_only``) compare to what's there and return True if
    they match.

    Returns True on success; False if check_only AND they diverge.
    Preserves any ``_analytic`` sub-block the designer added to the
    existing feature_params (analytic metadata isn't derivable from
    the TSV — keep the hand-authored block, just overlay the 6 knobs).
    """
    weights_path = _MACHINE_DIR / f"mode_{mode}" / "weights.json"
    doc = json.loads(weights_path.read_text(encoding="utf-8"))
    existing_fp = dict(doc.get("feature_params") or {})

    # Preserve hand-authored _analytic metadata
    preserved_analytic = existing_fp.get("_analytic")

    new_fp = copy.deepcopy(compiled_fp)
    if preserved_analytic is not None:
        new_fp["_analytic"] = preserved_analytic

    # Byte-level equality on the compiled-from-TSV fields
    compiled_keys = (
        "x_count_weights", "y_count_weights",
        "x_value_weights", "y_value_weights",
        "accept_threshold", "max_rounds",
    )
    drift_keys = [
        k for k in compiled_keys
        if existing_fp.get(k) != new_fp.get(k)
    ]

    if check_only:
        if drift_keys:
            print(
                f"  mode {mode}: DRIFT on {drift_keys}",
                file=sys.stderr,
            )
            for k in drift_keys:
                print(
                    f"    json:  {existing_fp.get(k)!r}\n"
                    f"    tsv:   {new_fp.get(k)!r}",
                    file=sys.stderr,
                )
            return False
        return True

    doc["feature_params"] = new_fp
    weights_path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    changed = bool(drift_keys)
    marker = "updated" if changed else "unchanged"
    print(
        f"  mode {mode}: {marker} "
        f"({len(drift_keys)} key{'s' if len(drift_keys) != 1 else ''} drifted)"
    )
    return True


def run(check_only: bool) -> int:
    if not _TSV_PATH.exists():
        print(f"TSV not found at {_TSV_PATH}", file=sys.stderr)
        return 2

    tsv_text = _TSV_PATH.read_text(encoding="utf-8")
    modes, rows = _parse_tsv(tsv_text)

    missing = set(_MODES) - set(modes)
    if missing:
        print(
            f"TSV header missing columns for mode(s) {sorted(missing)}; "
            f"found {modes}",
            file=sys.stderr,
        )
        return 2

    all_ok = True
    print(f"{'checking' if check_only else 'compiling'} TSV → feature_params ...")
    for mode in _MODES:
        compiled = _compile_mode(mode, modes, rows)
        if not _write_or_check_mode(mode, compiled, check_only=check_only):
            all_ok = False

    if check_only and not all_ok:
        print(
            "\n!! TSV and weights.json drift. Run without --check to resync.",
            file=sys.stderr,
        )
        return 1
    if check_only:
        print("all 4 modes in sync with TSV.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--check", action="store_true",
        help="Compare TSV to on-disk weights.json without writing; exit 1 "
             "if they drift. Use in CI / regression tests.",
    )
    args = p.parse_args()
    sys.exit(run(check_only=args.check))


if __name__ == "__main__":
    main()
