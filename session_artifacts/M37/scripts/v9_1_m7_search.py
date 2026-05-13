"""Designer v9.1 m7 narrow search — K_bar=0.83 + K_wild=1.0 alone gives RTP 84.48 (just below 84.5).
Need RTP in [84.5, 85.5]. Narrow refinement:
  K_bar ∈ [0.825, 0.840] step 0.005
  K_wild ∈ {0.95, 1.0}
  K_mini ∈ {0.88, 0.91, 0.94, 0.97, 1.00}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from session_artifacts.M37.scripts.v9_m7_grid import (
    M1_WEIGHTS, load_weights, profile_from_weights, build_m7_candidate, reel_marginals,
    pid9_share, per_pay_ratios
)


def check_hier_monotone(margs):
    r2 = margs[1]
    return r2.get("mini", 0) > r2.get("minor", 0) > r2.get("major", 0) > r2.get("grand", 0)


def main():
    m1 = load_weights(M1_WEIGHTS)
    base = profile_from_weights(m1)
    print(f"M1 v5 baseline: RTP {base['rtp_pct']:.3f}%  hit {base['hit_rate']*100:.3f}%")

    k_bar_grid = [round(0.825 + 0.005*i, 3) for i in range(4)]  # 0.825, 0.830, 0.835, 0.840
    k_wild_grid = [0.95, 1.00]
    k_mini_grid = [0.88, 0.91, 0.94, 0.97, 1.00]

    cands = []
    print(f"\n{'k_bar':>6} {'k_wild':>6} {'k_mini':>6} {'RTP':>8} {'hit':>7} {'pid9':>6} {'pid2':>5} {'pid7':>5} {'pid102':>6} {'pid104':>6} {'OK':>4}")
    for k_bar in k_bar_grid:
        for k_wild in k_wild_grid:
            for k_mini in k_mini_grid:
                w = build_m7_candidate(m1, k_bar, k_wild, k_mini)
                p = profile_from_weights(w)
                rtp = p["rtp_pct"]; hit = p["hit_rate"]*100
                r = per_pay_ratios(p, base)
                margs = reel_marginals(w)

                rtp_ok = 84.5 <= rtp <= 85.5
                hit_ok = 14.0 <= hit <= 17.5
                hit_safety = hit < 20.62
                top_big = all(r.get(pid, 0) >= 0.85 for pid in ["1", "8", "102", "103", "104"])
                mid_bar = all(r.get(pid, 0) >= 0.68 for pid in ["2", "3", "4"])
                hier_ok = check_hier_monotone(margs)
                all_ok = rtp_ok and hit_ok and hit_safety and top_big and mid_bar and hier_ok

                marker = "PASS" if all_ok else "----"
                print(f"  {k_bar:>4.3f} {k_wild:>4.2f} {k_mini:>4.2f} "
                      f"{rtp:>7.3f}% {hit:>6.3f}% {pid9_share(p):>5.2f}% "
                      f"{r.get('2',0):>5.3f} {r.get('7',0):>5.3f} "
                      f"{r.get('102',0):>6.3f} {r.get('104',0):>6.3f} {marker:>4}")

                if all_ok:
                    cands.append({
                        "k_bar": k_bar, "k_wild": k_wild, "k_mini": k_mini,
                        "rtp": rtp, "hit": hit, "pid9": pid9_share(p),
                        "ratios": r,
                    })

    print(f"\nTotal feasible: {len(cands)}")
    if not cands:
        print("NO FEASIBLE in narrow grid — widen search.")
        return

    # Prefer: K_wild closest to 1.0, K_mini closest to 1.0, RTP closest to band center (85.0)
    cands.sort(key=lambda r: (-r["k_wild"], -r["k_mini"], abs(r["rtp"]-85.0), abs(r["hit"]-15.7)))
    print("\nTop 10 feasible (sorted by preference: K_wild=1.0, K_mini→1.0, RTP→85.0):")
    for r in cands[:10]:
        print(f"  K_bar={r['k_bar']:.3f} K_wild={r['k_wild']:.2f} K_mini={r['k_mini']:.2f}: "
              f"RTP={r['rtp']:.3f}% hit={r['hit']:.3f}% pid9={r['pid9']:.2f}% "
              f"pid2={r['ratios'].get('2',0):.3f} pid102={r['ratios'].get('102',0):.3f}")

    best = cands[0]
    print(f"\n=== RECOMMENDED ===")
    print(f"  K_bar={best['k_bar']:.3f}  K_wild={best['k_wild']:.2f}  K_mini={best['k_mini']:.2f}")
    print(f"  RTP {best['rtp']:.3f}%  hit {best['hit']:.3f}%  pid9 {best['pid9']:.2f}%")


if __name__ == "__main__":
    main()
