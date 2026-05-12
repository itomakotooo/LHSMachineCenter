"""Designer v8 m7 tune — find best player-experience cut to land RTP [84,86] + §4 preserve.

Uses lever matrix from v8_m7_analysis.py:
- R2 mini cut: clean small-tier driver (pid 9 mini-alone) but mini substitutes on 3-match
  so mid pays mildly hit (~0.90)
- R1+R3 wild cut: drives side-wild-alone (pid 9 mult 1×); modest mid-pay impact (~0.95)
- R1+R3 bar/high7 cut: catastrophic mid/top — avoid
- R2 bar/high7 cut: catastrophic mid — avoid
- R2 minor/major cut: cuts pid 9 booster-alone — but minor (5×) is mid-tier per slot
  convention; major (10×) is mid-tier; cutting these violates §4 mid preserve

Plan: 5 candidates, all combo of (R2 mini cut, R1+R3 wild cut) at different ratios,
plus one with also R2 minor mild cut as test.
"""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile, compute_reel_marginal
from slot_designer.core.engine.loader import load_engine

MACHINE_DIR = _ROOT / "slot_designer" / "machines" / "M37"
SPEC = MACHINE_DIR / "spec.json"
STRIPS = MACHINE_DIR / "reel_strips.json"
M1_WEIGHTS = MACHINE_DIR / "weights" / "mode_1" / "weights.json"

with STRIPS.open("r", encoding="utf-8") as f:
    _strip_data = json.load(f)
REELS = _strip_data["reels"]
SYM_POS: dict[tuple[int, str], list[int]] = {}
for ri, reel in enumerate(REELS):
    for pi, sym in enumerate(reel):
        SYM_POS.setdefault((ri, sym), []).append(pi)


def load_weights(path: Path) -> list[list[float]]:
    with path.open("r", encoding="utf-8") as f:
        return [list(row) for row in json.load(f)["weights"]]


def profile_from_weights(weights: list[list[float]]) -> dict:
    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix="m37_v8t_"))
    try:
        machine_root = tmpdir / "M37"
        mode_dir = machine_root / "weights" / "mode_1"
        mode_dir.mkdir(parents=True)
        spec_data = json.loads(SPEC.read_text(encoding="utf-8"))
        (machine_root / "spec.json").write_text(json.dumps(spec_data), encoding="utf-8")
        (machine_root / "reel_strips.json").write_text(json.dumps(_strip_data), encoding="utf-8")
        weight_payload = {"machine": "M37", "mode": 1, "reel_set": "default", "weights": weights}
        wpath = mode_dir / "weights.json"
        wpath.write_text(json.dumps(weight_payload), encoding="utf-8")
        engine, _ = load_engine(machine_root / "spec.json", wpath)
        return analytic_profile(engine)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def reel_marginals(weights: list[list[float]]) -> list[dict[str, float]]:
    out = []
    for ri, reel_weights in enumerate(weights):
        totals: dict[str, float] = {}
        total_w = sum(reel_weights)
        for pi, w in enumerate(reel_weights):
            sym = REELS[ri][pi]
            totals[sym] = totals.get(sym, 0.0) + w
        out.append({s: w / total_w for s, w in totals.items()})
    return out


def scale_symbol(weights, reel_idx, symbol, k, distribute_to="blank"):
    out = [row[:] for row in weights]
    positions = SYM_POS.get((reel_idx, symbol), [])
    if not positions:
        return out
    old_sum = sum(out[reel_idx][p] for p in positions)
    new_sum = old_sum * k
    delta = new_sum - old_sum
    for p in positions:
        out[reel_idx][p] = out[reel_idx][p] * k
    dist_positions = SYM_POS.get((reel_idx, distribute_to), [])
    if not dist_positions:
        return out
    dist_total = sum(out[reel_idx][p] for p in dist_positions)
    if dist_total == 0:
        return out
    for p in dist_positions:
        share = out[reel_idx][p] / dist_total
        out[reel_idx][p] -= delta * share
    return out


def scale_symbols(weights, scales):
    out = [row[:] for row in weights]
    for ri, sym, k in scales:
        out = scale_symbol(out, ri, sym, k)
    return out


def pid9_share(profile):
    return profile["pay_rtp"].get("9", 0.0) / (profile["rtp_pct"] / 100.0) * 100.0


def gen3():
    m1 = load_weights(M1_WEIGHTS)
    m1p = profile_from_weights(m1)
    base_hits = m1p["pay_hits"]
    base_pay_rtp = m1p["pay_rtp"]

    def check_strategy(label, scales):
        w = scale_symbols(m1, scales)
        p = profile_from_weights(w)
        # §4 check: mid/big/top pids = 1, 2, 3, 4, 5, 6, 102, 103, 104; small = 7, 9
        # pid 8 (grand alone) is "lifetime top" — preserve.
        # pid 9 multi-tier breakdown unavailable here (pay_id 9 lumps wild-alone+booster-alone)
        mid_big_top_pids = ["1", "2", "3", "4", "5", "6", "8", "102", "103", "104"]
        small_pids = ["7", "9"]
        ratios = {}
        violations = []
        for pid in mid_big_top_pids:
            bp = base_hits.get(pid, 0.0)
            np_ = p["pay_hits"].get(pid, 0.0)
            if bp > 0:
                r = np_ / bp
                ratios[pid] = r
                if r < 0.85:
                    violations.append(f"pid {pid} ratio {r:.3f} < 0.85")
        # check booster hier still holds in m7 weights (margs):
        margs = reel_marginals(w)
        r2 = margs[1]
        mini_m = r2.get("mini", 0)
        minor_m = r2.get("minor", 0)
        major_m = r2.get("major", 0)
        grand_m = r2.get("grand", 0)
        hier = (mini_m > minor_m > major_m > grand_m)
        # ratio
        ratio_min_mn = mini_m / minor_m if minor_m else 0
        ratio_mn_mj = minor_m / major_m if major_m else 0
        ratio_mj_g = major_m / grand_m if grand_m else 0
        # hit check
        new_hit = p["hit_rate"] * 100
        new_rtp = p["rtp_pct"]
        in_rtp = 84 <= new_rtp <= 86
        in_hit = new_hit < 20.62
        return {
            "label": label,
            "rtp": new_rtp,
            "hit": new_hit,
            "pid9_share": pid9_share(p),
            "ratios": ratios,
            "violations": violations,
            "in_rtp_band": in_rtp,
            "in_hit_band": in_hit,
            "hier_ok": hier,
            "hier_ratios": [round(ratio_min_mn, 3), round(ratio_mn_mj, 3), round(ratio_mj_g, 3)],
            "r2_high7_marg": r2.get("high7", 0),
            "weights": w,
            "profile": p,
        }

    # Strategy candidates — designer's 5 picks:
    strategies = {
        # A: R2 mini deep cut (mini alone = pid 9 mult 2× = small per slot convention)
        #    + R1+R3 wild cut (pid 9 mult 1× = small).
        #    Idea: ONLY hit small-tier levers. Mid pays accept ~0.85-0.95 drift.
        "A: mini ÷0.30 + R13 wild ÷0.65": [
            (1, "mini", 0.30),
            (0, "wild", 0.65), (2, "wild", 0.65),
        ],
        # A2: less aggressive mini, less aggressive wild
        "A2: mini ÷0.40 + R13 wild ÷0.70": [
            (1, "mini", 0.40),
            (0, "wild", 0.70), (2, "wild", 0.70),
        ],
        # A3: targets RTP ~85
        "A3: mini ÷0.35 + R13 wild ÷0.70": [
            (1, "mini", 0.35),
            (0, "wild", 0.70), (2, "wild", 0.70),
        ],
        # A4: mini-only deep cut (no wild cut)
        "A4: mini ÷0.10 (only)": [
            (1, "mini", 0.10),
        ],
        # A5: wild only deep cut
        "A5: R13 wild ÷0.20 (only)": [
            (0, "wild", 0.20), (2, "wild", 0.20),
        ],
        # B: mini cut + wild cut + minor mild
        "B: mini ÷0.35 + R13 wild ÷0.70 + minor ÷0.80": [
            (1, "mini", 0.35),
            (0, "wild", 0.70), (2, "wild", 0.70),
            (1, "minor", 0.80),
        ],
        # C: balanced. mini ÷0.5 + wild ÷0.6 + R2 minor +mild
        "C: mini ÷0.50 + R13 wild ÷0.55": [
            (1, "mini", 0.50),
            (0, "wild", 0.55), (2, "wild", 0.55),
        ],
        # tuning toward 85
        "tune1: mini ÷0.30 + R13 wild ÷0.70": [
            (1, "mini", 0.30),
            (0, "wild", 0.70), (2, "wild", 0.70),
        ],
        "tune2: mini ÷0.25 + R13 wild ÷0.75": [
            (1, "mini", 0.25),
            (0, "wild", 0.75), (2, "wild", 0.75),
        ],
        "tune3: mini ÷0.40 + R13 wild ÷0.60": [
            (1, "mini", 0.40),
            (0, "wild", 0.60), (2, "wild", 0.60),
        ],
        "tune4: mini ÷0.50 + R13 wild ÷0.50": [
            (1, "mini", 0.50),
            (0, "wild", 0.50), (2, "wild", 0.50),
        ],
        "tune5: mini ÷0.45 + R13 wild ÷0.60": [
            (1, "mini", 0.45),
            (0, "wild", 0.60), (2, "wild", 0.60),
        ],
    }

    print("\n===== CANDIDATE SCORING (sweep, target RTP 84-86, hit < 20.62, §4 mid/big/top ≥ 0.85) =====\n")
    print(f"{'strategy':<55} {'RTP':>7} {'hit':>6} {'pid9%':>7} {'§4 OK':>7} {'hier':>6} {'mid ratios (1,2,3,4,5,6)':<40}")
    results = {}
    for label, scales in strategies.items():
        r = check_strategy(label, scales)
        results[label] = r
        rats = [r["ratios"].get(p, 0) for p in ["1", "2", "3", "4", "5", "6"]]
        rstr = " ".join(f"{x:.2f}" for x in rats)
        s4 = "yes" if not r["violations"] else f"NO({len(r['violations'])})"
        print(f"{label:<55} {r['rtp']:>7.2f} {r['hit']:>6.2f} {r['pid9_share']:>7.2f} {s4:>7} {'yes' if r['hier_ok'] else 'NO':>6} {rstr:<40}")

    # Find the best — within RTP band, §4 OK, prefer high mid-tier ratios
    print("\n\nWinners:")
    for label, r in results.items():
        if r["in_rtp_band"] and r["in_hit_band"] and not r["violations"] and r["hier_ok"]:
            avg_mid = sum(r["ratios"].get(p, 0) for p in ["1", "2", "3", "4", "5", "6"]) / 6
            print(f"  ✓ {label}: RTP {r['rtp']:.2f}, hit {r['hit']:.2f}, pid9 {r['pid9_share']:.2f}%, avg-mid {avg_mid:.3f}")

    return results, m1


if __name__ == "__main__":
    gen3()
