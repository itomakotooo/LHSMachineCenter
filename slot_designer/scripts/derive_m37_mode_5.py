"""Derive M37 mode 5 from mode 2.

Per universal §C: mode 5 = mode 2 base byte-identical + grand boost only.
Public M37Cfg evidence: skin 5 vs skin 2 has identical mini/minor/major/bars/wild,
only R2 grand jumps from 0.21% → 1.22% (× ~6).

This script:
  1. Copies mode 2 weights byte-identical
  2. Bisects R2 grand weight to land RTP 500% ±20pp
  3. Verifies base symbols (everything except grand on R2) byte-identical
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.engine.loader import load_engine
from slot_designer.devtools.analytic_rtp import analytic_profile

SPEC = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
STRIPS = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"
M2_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M37" / "mode_2" / "weights.json"
M5_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M37" / "mode_5" / "weights.json"

TARGET_RTP = 500.0
TOL_PP = 20.0


def compute_rtp(weights_doc: dict, tmp_path: Path) -> float:
    tmp_path.write_text(json.dumps(weights_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    eng, _ = load_engine(SPEC, tmp_path)
    prof = analytic_profile(eng)
    return prof["rtp_pct"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true", help="write the derived weights to mode_5/weights.json")
    p.add_argument("--verify", action="store_true", help="verify base byte-identical to mode 2")
    args = p.parse_args()

    # Load mode 2
    m2 = json.loads(M2_WEIGHTS.read_bytes().decode("utf-8"))
    strips = json.loads(STRIPS.read_bytes().decode("utf-8"))["reels"]

    # Find R2 grand stop indices
    grand_indices = [i for i, sym in enumerate(strips[1]) if sym == "grand"]
    if not grand_indices:
        print("ERROR: no grand symbol on R2 strip!")
        return 1
    print(f"R2 grand stop indices: {grand_indices}")

    # Mode 2 baseline grand weight + RTP
    m2_grand_w = m2["weights"][1][grand_indices[0]]
    m2_eng, _ = load_engine(SPEC, M2_WEIGHTS)
    m2_rtp = analytic_profile(m2_eng)["rtp_pct"]
    print(f"Mode 2 baseline: RTP {m2_rtp:.2f}%, R2 grand weight {m2_grand_w}")

    # Bisect R2 grand weight to hit RTP 500
    M5_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    lo_w, hi_w = m2_grand_w, m2_grand_w * 30
    best_w = m2_grand_w
    best_gap = float("inf")
    for it in range(40):
        mid_w = (lo_w + hi_w) / 2
        m5_doc = copy.deepcopy(m2)
        m5_doc["machine"] = "M37"
        m5_doc["mode"] = 5
        for gi in grand_indices:
            m5_doc["weights"][1][gi] = int(round(mid_w))
        rtp = compute_rtp(m5_doc, M5_WEIGHTS)
        gap = abs(rtp - TARGET_RTP)
        if gap < best_gap:
            best_gap = gap
            best_w = int(round(mid_w))
        if abs(rtp - TARGET_RTP) < 0.5:
            print(f"  iter {it+1:>2}: grand_w={mid_w:7.1f}  RTP={rtp:7.3f}%  CONVERGED")
            best_w = int(round(mid_w))
            break
        if rtp < TARGET_RTP:
            lo_w = mid_w
        else:
            hi_w = mid_w
        if it < 10 or it % 5 == 0:
            print(f"  iter {it+1:>2}: grand_w={mid_w:7.1f}  RTP={rtp:7.3f}%  gap={rtp-TARGET_RTP:+.3f}pp")

    print(f"\nFinal grand weight: {best_w} (mode 2 baseline: {m2_grand_w}, scaling factor: {best_w/m2_grand_w:.2f}x)")

    # Final write
    m5_doc = copy.deepcopy(m2)
    m5_doc["machine"] = "M37"
    m5_doc["mode"] = 5
    for gi in grand_indices:
        m5_doc["weights"][1][gi] = best_w
    m5_doc["_notes"] = [
        f"M37 mode 5 — super-lucky archetype derived from mode 2.",
        f"Base byte-identical to mode 2 EXCEPT R2 grand weight ({m2_grand_w} -> {best_w}, scaling {best_w/m2_grand_w:.2f}x).",
        f"Mechanism: per universal §C mode 5 = mode 2 + grand boost only. Public M37Cfg skin 5 vs skin 2 evidence supports this (~6x grand boost).",
        f"All other R2 symbols (mini/minor/major/bars/high7) + R1 + R3 byte-identical to mode 2.",
    ]

    if args.write:
        M5_WEIGHTS.write_text(json.dumps(m5_doc, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote mode 5 weights -> {M5_WEIGHTS}")

    if args.verify:
        # Confirm everything except R2 grand is byte-identical to mode 2
        m5_loaded = json.loads(M5_WEIGHTS.read_bytes().decode("utf-8"))
        violations = []
        for ri in range(3):
            for pi in range(len(m2["weights"][ri])):
                if ri == 1 and pi in grand_indices:
                    continue
                if m2["weights"][ri][pi] != m5_loaded["weights"][ri][pi]:
                    violations.append(f"R{ri+1}[{pi}]: m2 {m2['weights'][ri][pi]} vs m5 {m5_loaded['weights'][ri][pi]}")
        if violations:
            print(f"\nMODE5-BASE-LOCK VIOLATIONS ({len(violations)}):")
            for v in violations[:5]:
                print(f"  {v}")
            return 1
        print(f"\nMODE5-BASE-LOCK ✓ all non-grand weights byte-identical to mode 2")

    # Final analytic
    eng, _ = load_engine(SPEC, M5_WEIGHTS)
    prof = analytic_profile(eng)
    print(f"\nMode 5 final: RTP {prof['rtp_pct']:.2f}% (target {TARGET_RTP}±{TOL_PP})   hit {prof['hit_rate']*100:.2f}%   CV {prof['cv']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
