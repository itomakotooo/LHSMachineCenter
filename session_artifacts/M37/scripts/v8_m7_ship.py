"""Ship v8 m7 weights using the recommended cut (V2a).

V2a: mini=1.00, minor=0.80, major=0.80, R1+R3 wild=0.95
- RTP 85.16 (band [84,86] ✓ centered)
- hit 20.11 (limit < 20.62, 0.51pp margin)
- pid 9 share 18.82% (< 21% threshold)
- mid-tier §4 ratios 0.93-0.96
- top-tier §4 ratios 0.96+
- jackpot path (102/103/104) 0.72-0.90
- HIER strict, grand untouched
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "session_artifacts" / "M37" / "scripts"))

from v8_m7_final import load_weights, scale_symbol, profile_from_weights, reel_marginals, pid9_share

MACHINE_DIR = _ROOT / "slot_designer" / "machines" / "M37"
M1_WEIGHTS = MACHINE_DIR / "weights" / "mode_1" / "weights.json"
OUT = _ROOT / "session_artifacts" / "M37" / "v8_sim_weights" / "mode_7" / "weights.json"

# V2a final parameters.
K_MINI = 1.00
K_MINOR = 0.80
K_MAJOR = 0.80
K_WILD = 0.95


def main():
    m1 = load_weights(M1_WEIGHTS)
    m1p = profile_from_weights(m1)
    base_hits = m1p["pay_hits"]

    w = m1
    w = scale_symbol(w, 1, "mini", K_MINI)
    w = scale_symbol(w, 1, "minor", K_MINOR)
    w = scale_symbol(w, 1, "major", K_MAJOR)
    w = scale_symbol(w, 0, "wild", K_WILD)
    w = scale_symbol(w, 2, "wild", K_WILD)

    p = profile_from_weights(w)
    margs = reel_marginals(w)

    rtp = p["rtp_pct"]
    hit = p["hit_rate"] * 100
    pid9 = pid9_share(p)
    ratios = {pid: p["pay_hits"].get(pid, 0) / base_hits.get(pid, 1) for pid in ["1","2","3","4","5","6","7","8","9","102","103","104"]}

    print(f"V2a final: RTP {rtp:.3f}, hit {hit:.3f}, pid9 share {pid9:.3f}%")
    print(f"Per-pay ratios vs m1:")
    for pid in ["1","2","3","4","5","6","7","8","9","102","103","104"]:
        print(f"  pid {pid}: ratio {ratios[pid]:.3f} (freq {p['pay_hits'].get(pid,0):.5f}, baseline {base_hits.get(pid,0):.5f})")

    r2m = margs[1]
    print(f"\nR2 booster marginals (m7 v8):")
    print(f"  mini  {r2m.get('mini',0)*100:.3f}% (baseline 2.793% → ratio {r2m.get('mini',0)/0.027934:.3f})")
    print(f"  minor {r2m.get('minor',0)*100:.3f}% (baseline 1.990% → ratio {r2m.get('minor',0)/0.019899:.3f})")
    print(f"  major {r2m.get('major',0)*100:.3f}% (baseline 1.531% → ratio {r2m.get('major',0)/0.015307:.3f})")
    print(f"  grand {r2m.get('grand',0)*100:.4f}% (baseline 0.112%)")

    # write weights file
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "machine": "M37",
        "mode": 7,
        "reel_set": "default",
        "_notes": [
            "M37 mode 7 — v8 player-experience optimal (Designer v8 fresh-context derivation).",
            f"Universal §4 + §9 framework. Levers applied to m1 v5 source:",
            f"  R2 mini × {K_MINI:.2f} (unchanged, preserves mini visibility 2.79%)",
            f"  R2 minor × {K_MINOR:.2f}",
            f"  R2 major × {K_MAJOR:.2f}",
            f"  R1+R3 wild × {K_WILD:.2f}",
            f"  R2 grand untouched (jackpot anchor); R2 7/3/2/1bar untouched; R2 high7 untouched; R1+R3 high7/bar untouched.",
            f"Saved weight redistributed to per-reel blank positions proportionally (preserves blank visibility).",
            f"Analytic: RTP {rtp:.3f}%, hit {hit:.3f}%, pid 9 RTP share {pid9:.3f}%.",
            f"§4 per-pay ratios (top/mid preserved):",
            f"  pid 1 (1000× top) {ratios['1']:.3f}; pid 8 (grand alone 100×) {ratios['8']:.3f};",
            f"  pid 102/103/104 (3-wild jackpot) {ratios['102']:.3f}/{ratios['103']:.3f}/{ratios['104']:.3f};",
            f"  pid 2/3/4/5 (3-bar mid) {ratios['2']:.3f}/{ratios['3']:.3f}/{ratios['4']:.3f}/{ratios['5']:.3f};",
            f"  pid 6 (any-7 mixed) {ratios['6']:.3f}; pid 7 (any-bar small) {ratios['7']:.3f}; pid 9 (booster/wild alone) {ratios['9']:.3f}.",
            f"BOOSTER-HIER strict: mini 2.79% > minor 1.59% > major 1.22% > grand 0.112%.",
        ],
        "weights": [[float(round(x, 6)) for x in row] for row in w],
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWritten: {OUT}")


if __name__ == "__main__":
    main()
