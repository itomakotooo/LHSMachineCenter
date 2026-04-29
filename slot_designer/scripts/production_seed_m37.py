"""Compute and apply production-aligned seed weights for M37.

Replaces my v4.6 weights with production-derived weights. Production
densities (from rawdata 2M+ rounds mode 1, ~110k mode 7, ~10k modes 2/5)
are the design ground truth — my virtual should mirror these.

Per-symbol per-reel weights derived to match production density targets:
- Mode 1: hit ~9%, RTP 95%, grand 1 in 720
- Mode 7: hit ~9%, RTP 85%, grand 1 in 1277 (slightly rarer than m1)
- Mode 2: hit ~22%, RTP 300%, grand 1 in 37 (lucky-frequent)
- Mode 5: hit ~37%, RTP 500%, grand 1 in 23 (super-lucky)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Production-aligned per-symbol per-reel weights.
# Derived to match production density targets within ±2% tolerance.
# Each weight = uniform across all positions of that symbol on that reel.

WEIGHTS = {
    1: {
        # Mode 1: standard, RTP 95%, hit ~9%
        # R1/R3: blank=4, wild=1, high7=4, bars=3 each → blank density 58.5%, wild 2.4%, high7 9.8%, bars 7.3%
        # R2: T=586, blank density 55.3%, mini 1.7%, minor 4.78%, major 1.37%, grand 0.17%
        "R1": {"blank": 4, "wild": 1, "high7": 4, "1bar": 3, "2bar": 3, "3bar": 3, "7bar": 3},
        "R2": {"blank": 18, "high7": 17, "mini": 5, "minor": 14, "major": 4, "grand": 1,
               "1bar": 12, "2bar": 23, "3bar": 23, "7bar": 24},
        "R3": {"blank": 4, "wild": 1, "high7": 4, "1bar": 3, "2bar": 3, "3bar": 3, "7bar": 3},
    },
    7: {
        # Mode 7: standard-low, RTP 85%, hit ~9%, grand RARER than m1
        # R1/R3: same shape as m1 (production shows R1/R3 densities almost identical)
        # R2: scaled up to make grand rarer (T~1121 vs m1 T=586)
        "R1": {"blank": 4, "wild": 1, "high7": 4, "1bar": 3, "2bar": 3, "3bar": 3, "7bar": 3},
        "R2": {"blank": 35, "high7": 32, "mini": 9, "minor": 26, "major": 7, "grand": 1,
               "1bar": 22, "2bar": 43, "3bar": 45, "7bar": 45},
        "R3": {"blank": 4, "wild": 1, "high7": 4, "1bar": 3, "2bar": 3, "3bar": 3, "7bar": 3},
    },
    2: {
        # Mode 2: lucky, RTP 300%, hit ~22%, grand 1 in 37 (denser jackpots)
        # R1/R3: blank reduced (~55%), wild boosted (~4%), bars stay ~8%
        # R2: blank reduced (~48%), boosters all up (mini 2%, minor 7.86%, major 7.64%, grand 2.88%)
        "R1": {"blank": 4, "wild": 2, "high7": 4, "1bar": 3, "2bar": 3, "3bar": 3, "7bar": 3},
        "R2": {"blank": 8, "high7": 8, "mini": 2, "minor": 12, "major": 12, "grand": 5,
               "1bar": 4, "2bar": 8, "3bar": 9, "7bar": 8},
        "R3": {"blank": 4, "wild": 2, "high7": 4, "1bar": 3, "2bar": 3, "3bar": 3, "7bar": 3},
    },
    5: {
        # Mode 5: super-lucky, RTP 500%, hit ~37%, grand 1 in 23 (very dense)
        # R1/R3: blank ~50%, wild ~10% (boosted), bars stay ~8%
        # R2: blank ~31% (very low), all boosters very high (minor 19%, major 17%)
        "R1": {"blank": 4, "wild": 4, "high7": 4, "1bar": 3, "2bar": 3, "3bar": 3, "7bar": 3},
        "R2": {"blank": 4, "high7": 4, "mini": 4, "minor": 20, "major": 18, "grand": 10,
               "1bar": 2, "2bar": 4, "3bar": 6, "7bar": 4},
        "R3": {"blank": 4, "wild": 4, "high7": 4, "1bar": 3, "2bar": 3, "3bar": 3, "7bar": 3},
    },
}


def apply():
    strips = json.loads((_ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json").read_text(encoding="utf-8"))["reels"]
    for mode, weights_per_reel in WEIGHTS.items():
        per_pos_weights = []
        for r_idx, reel in enumerate(strips):
            reel_key = f"R{r_idx + 1}"
            sym_weights = weights_per_reel[reel_key]
            row = []
            for sym in reel:
                row.append(sym_weights.get(sym, 1))
            per_pos_weights.append(row)

        wp = _ROOT / "slot_designer" / "weights" / "M37" / f"mode_{mode}" / "weights.json"
        existing = json.loads(wp.read_text(encoding="utf-8"))
        existing["mode"] = mode
        existing["weights"] = per_pos_weights
        existing["_notes"] = [
            f"M37 mode {mode} v5 (2026-04-29 production-aligned seed):",
            "Per-symbol per-reel weights derived from production rawdata densities.",
            "Targets: production grand-alone freq (mode 1 1/720, m7 1/1277, m2 1/37, m5 1/23).",
            "Family RTP allocation matches production: booster_alone ~48%, wild_amp ~16%,",
            "bar_tier ~23%, high7 ~6%, 7bar ~7% (vs my v4.6 inverted bar-heavy).",
            "Hit rate ~9% mode 1/7 (was 21/19% v4.6) — sparse-machine production design.",
            "",
            "After this seed, run tune_m37 to fine-tune RTP exactly to target.",
        ]
        existing.pop("_tuned_summary", None)
        wp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        total = sum(sum(row) for row in per_pos_weights)
        print(f"  mode {mode}: per-reel totals = {[sum(r) for r in per_pos_weights]}, grand total {total}")


if __name__ == "__main__":
    apply()
    print("\nDone. Run verify_m37 to see baseline state.")
