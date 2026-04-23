"""Derive M15 mode 5 weights from mode 2 by copying base + swapping feature.

M15 mode 5 design (see slot_designer/weights/M15/MODE_DESIGN.md §6):
  * Total RTP 500% ±20pp (loose tolerance for lucky mode)
  * Base RTP 135pp — **byte-identical to mode 2 base weights**
  * Feature RTP 364.98pp — via enhanced feature_params only
  * Trigger rate 2.75% — same as mode 2 (base weights → same reel 3)
  * Feature EV 132× — 2.2× mode 2's 60×

Why "copy mode 2 base": mode 5 is explicitly "mode 2 + feature buff" per
user brief. Base experience (cherry/bar hit rate, payline frequency,
bucket shape) is IDENTICAL to mode 2 — player can't tell base mode 2 from
mode 5 at all. The entire differentiation happens inside the Feature
Play session (x_value_weights give higher cards, count_y biases to more
multipliers → R distribution shifts up 2.2×).

The reel strip layout is NOT modified — per
``project_slot_designer_strips_identical_across_modes.md``, all modes
of a machine share byte-identical ``reel_strips.json``. Only the per-
position weight arrays in ``mode_<N>/weights.json`` differ (and mode 5's
are the SAME as mode 2's).

Usage:
  python -m slot_designer.scripts.derive_m15_mode_5 [--write] [--verify]
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

from slot_designer.devtools.analytic_rtp import analytic_profile
from slot_designer.engine.feature_m15 import FeatureSpec, analyze_feature
from slot_designer.engine.loader import load_engine


_SPEC = _ROOT / "slot_designer" / "specs" / "M15.spec.json"
_STRIPS = _ROOT / "slot_designer" / "weights" / "M15" / "reel_strips.json"
_MODE_2_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M15" / "mode_2" / "weights.json"
_MODE_5_DIR = _ROOT / "slot_designer" / "weights" / "M15" / "mode_5"
_MODE_5_WEIGHTS = _MODE_5_DIR / "weights.json"


# Mode 5 feature_params (MODE_DESIGN.md §6). Only x_value_weights + y_count
# change vs mode 2 — x_count_weights stays locked across all modes.
_MODE_5_FEATURE_PARAMS = {
    "_note": (
        "v5 mode 5 Feature Play params (per MODE_DESIGN.md §6). "
        "EV 132x (2.2x mode 2 buff). Trigger inherited from mode 2 "
        "base weights (~2.75%), so feature RTP = 2.75% x 132 ~ 363pp."
    ),
    "x_count_weights": [5, 40, 40, 12, 3],
    "y_count_weights": [40, 35, 25],
    "x_value_weights": [
        0.1918, 1.6065, 3.0458, 3.0458,
        7.0955, 7.0955, 13.453, 13.453,
        25.5065, 25.5065,
    ],
    "y_value_weights": [1, 1],
    "accept_threshold": 40,
    "max_rounds": 4,
    "_analytic": {
        "ev_per_trigger": 132.0,
        "target_trigger_rate": 0.0275,
        "target_feature_rtp_pp": 365.0,
    },
}


def _build_mode_5_doc(mode_2_doc: dict) -> dict:
    """Copy mode 2 weights verbatim; swap feature_params; rewrite notes."""
    doc = copy.deepcopy(mode_2_doc)
    doc["mode"] = 5
    doc["feature_params"] = copy.deepcopy(_MODE_5_FEATURE_PARAMS)
    doc["_notes"] = [
        "M15 mode 5 weights (v5 2026-04-23, derived from mode 2).",
        "",
        "Derivation: `python -m slot_designer.scripts.derive_m15_mode_5 --write`",
        "Base weights: byte-identical to mode 2 (no tune; no scale).",
        "Feature params: enhanced (count_y (40,35,25), x_value_weights biased high).",
        "Reel strips unchanged (shared byte-identical reel_strips.json across all modes).",
        "",
        "Design target (MODE_DESIGN.md §6): Total 500% +/-20pp loose.",
        "  Base ~135pp (inherited from mode 2)",
        "  Feature ~365pp via EV 132x at trigger 2.75%",
        "  Trigger rate identical to mode 2 (same base weights).",
        "",
        "User brief: 'mode 5 = mode 2 base + feature supercharge'. Player",
        "cannot distinguish mode 5 from mode 2 at the base level (same",
        "cherry/bar/wild marginals, same hit rate, same trigger rate). The",
        "entire 'super-lucky' UX differentiation happens inside Feature Play:",
        "  * Higher single-pick mean (94x vs mode 2's 37x)",
        "  * P(1000-card) = 0.19% (vs mode 2's 0%) — the ONLY mode with",
        "    real jackpot-card dream",
        "  * Accept rate 64.5% (vs mode 2's 35%) — almost never reject",
        "  * One-round E[R] 94x (vs mode 2's 37x) — 2.56x buff",
        "",
        "Do NOT tune this mode through Phase 4/5. Base is locked to mode 2.",
    ]
    # Mode 5 inherits mode 2 marginals → don't carry mode 2's _tuned_summary
    # (that's a Phase-4-iteration artifact specific to mode 2's tune run).
    if "_tuned_summary" in doc:
        del doc["_tuned_summary"]
    return doc


def _actual_trigger_rate(strips_reels: list[list[str]], weights: list[list[float]],
                         symbol: str = "topdollar", reel_idx: int = 2) -> float:
    """Compute exact trigger rate from on-disk reel weights."""
    syms = strips_reels[reel_idx]
    wts = weights[reel_idx]
    trig = sum(float(w) for s, w in zip(syms, wts) if s == symbol)
    total = sum(float(w) for w in wts)
    return trig / total if total > 0 else 0.0


def run(write: bool, verify: bool) -> int:
    print(f"{'='*70}")
    print(f"M15 mode 5 derivation — copy mode 2 base + enhanced feature")
    print(f"{'='*70}\n")

    strips_doc = json.loads(_STRIPS.read_text(encoding="utf-8"))
    mode_2_doc = json.loads(_MODE_2_WEIGHTS.read_text(encoding="utf-8"))

    print(f"Source: mode 2 ({_MODE_2_WEIGHTS.relative_to(_ROOT)})")
    print(f"Target: mode 5 ({_MODE_5_WEIGHTS.relative_to(_ROOT)})")
    print()

    mode_5_doc = _build_mode_5_doc(mode_2_doc)
    base_identical = mode_5_doc["weights"] == mode_2_doc["weights"]
    print(f"base weights byte-identical to mode 2: "
          f"{'YES' if base_identical else 'NO (bug — should be byte-identical!)'}")

    if write:
        _MODE_5_DIR.mkdir(parents=True, exist_ok=True)
        _MODE_5_WEIGHTS.write_text(
            json.dumps(mode_5_doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[write] wrote {_MODE_5_WEIGHTS.relative_to(_ROOT)}")
    else:
        print("[dry-run] use --write to persist mode_5/weights.json")

    if verify and write:
        print()
        print(f"{'-'*70}")
        print(f"Analytic verification")
        print(f"{'-'*70}")
        strips_reels = strips_doc["reels"]

        eng_m2, _ = load_engine(_SPEC, _MODE_2_WEIGHTS)
        prof_m2 = analytic_profile(eng_m2)
        eng_m5, _ = load_engine(_SPEC, _MODE_5_WEIGHTS)
        prof_m5 = analytic_profile(eng_m5)

        trigger_m2 = _actual_trigger_rate(strips_reels, mode_2_doc["weights"])
        trigger_m5 = _actual_trigger_rate(strips_reels, mode_5_doc["weights"])

        def _feature_stats(doc):
            fp = doc["feature_params"]
            fs = FeatureSpec(
                x_count_weights=tuple(fp["x_count_weights"]),
                y_count_weights=tuple(fp["y_count_weights"]),
                x_value_weights=tuple(fp["x_value_weights"]),
                y_value_weights=tuple(fp["y_value_weights"]),
                accept_threshold=float(fp["accept_threshold"]),
                max_rounds=int(fp["max_rounds"]),
            )
            return analyze_feature(fs)

        fs_m2 = _feature_stats(mode_2_doc)
        fs_m5 = _feature_stats(mode_5_doc)

        f_rtp_m2 = 100.0 * trigger_m2 * fs_m2.expected_payout
        f_rtp_m5 = 100.0 * trigger_m5 * fs_m5.expected_payout
        total_m2 = prof_m2["rtp_pct"] + f_rtp_m2
        total_m5 = prof_m5["rtp_pct"] + f_rtp_m5

        print(f"\n  {'':>10}{'Trigger':>10}{'Base RTP':>14}{'Feat EV':>12}"
              f"{'Feat RTP':>12}{'Total':>12}")
        print(f"  {'mode 2':>10}{trigger_m2*100:>9.3f}%{prof_m2['rtp_pct']:>14.3f}"
              f"{fs_m2.expected_payout:>12.2f}{f_rtp_m2:>12.3f}{total_m2:>12.3f}")
        print(f"  {'mode 5':>10}{trigger_m5*100:>9.3f}%{prof_m5['rtp_pct']:>14.3f}"
              f"{fs_m5.expected_payout:>12.2f}{f_rtp_m5:>12.3f}{total_m5:>12.3f}")

        base_ok = prof_m5["rtp_pct"] == prof_m2["rtp_pct"]
        print(f"\n  base RTP identity (m5 ≡ m2): "
              f"{'OK' if base_ok else 'DRIFT'}")

        trigger_ok = abs(trigger_m5 - trigger_m2) < 1e-9
        print(f"  trigger rate identity (m5 ≡ m2): "
              f"{'OK' if trigger_ok else 'DRIFT'}")

        total_target = 500.0
        total_tolerance = 20.0
        total_ok = abs(total_m5 - total_target) <= total_tolerance
        status = "OK" if total_ok else "DRIFT"
        print(f"\n  mode 5 target total: {total_target} ±{total_tolerance}pp (loose)")
        print(f"  mode 5 actual total: {total_m5:.3f}  → [{status}]")
        if not total_ok:
            return 1
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--write", action="store_true",
                   help="write mode_5/weights.json (default: dry-run)")
    p.add_argument("--verify", action="store_true",
                   help="after --write, run analytic base + feature RTP check")
    args = p.parse_args()
    sys.exit(run(write=args.write, verify=args.verify))


if __name__ == "__main__":
    main()
