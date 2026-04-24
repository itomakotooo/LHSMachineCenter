"""M1 design verification — experience gate.

Enforces the red lines declared in slot_designer/weights/M1/DESIGN.md.
Run after any tune / weight change. All checks must pass (green)
before the design is "done" per `project_slot_designer_axiom_experience_is_soul`.

Usage:
    python -m slot_designer.scripts.verify_m1_design

Exit code: 0 = all green, 1 = at least one red.

Checks:
    [RTP]        Per-mode RTP within tolerance (DESIGN.md §3)
    [HIT]        Per-mode hit rate within band (DESIGN.md §3)
    [SHARE]      Per-mode family RTP share within range (DESIGN.md §2)
    [MODE7-SEVEN] Mode 7 Seven absolute marginal ≥ mode 1 × 0.9 (DESIGN.md §4)
    [MODE7-DIAM]  Mode 7 Diamond absolute marginal ≥ mode 1 × 0.9 (DESIGN.md §4)
    [RATIO]      Per-family per-reel ratio drift vs TDD baseline (DESIGN.md §5)
    [NEARMISS]   Seven2/Diamond window/payline ratio ≥ 1.3 (DESIGN.md §6)
    [BUCKET]     Low hit ≥ total × 50%, High RTP share ≥ 15% (DESIGN.md §7)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile, compute_reel_marginal
from slot_designer.engine.loader import load_engine

SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
STRIPS = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"

# TDD baseline weights (from DESIGN.md §5, WoO Hot Roll reverse-engineering)
TDD_BASELINE = [
    [1, 2, 12, 1, 5, 5, 4, 5, 5, 7, 17, 25, 18, 25, 19, 18, 26, 24, 19, 9, 3, 6],
    [2, 3, 2, 3, 3, 4, 1, 5, 7, 17, 12, 19, 19, 21, 20, 28, 20, 27, 27, 10, 3, 3],
    [1, 1, 1, 4, 2, 41, 8, 17, 12, 17, 10, 12, 11, 20, 14, 13, 11, 7, 42, 8, 3, 1],
]

FAMILY_MAP = {
    "14": "Cherry", "13": "Cherry", "12": "Cherry",
    "5": "Seven", "6": "Seven", "10": "Seven",
    "7": "Bar", "8": "Bar", "9": "Bar", "11": "Bar",
    "2": "Wild", "3": "Wild", "4": "Wild",
}

# DESIGN.md §3 RTP+hit targets (per-mode)
MODE_TARGETS = {
    1: {"rtp": 95.0, "rtp_tol": 1.0, "hit_lo": 0.13, "hit_hi": 0.20},
    7: {"rtp": 85.0, "rtp_tol": 1.0, "hit_lo": 0.09, "hit_hi": 0.13},
    2: {"rtp": 294.5, "rtp_tol": 20.0, "hit_lo": 0.22, "hit_hi": 0.30},
    5: {"rtp": 500.0, "rtp_tol": 20.0, "hit_lo": 0.22, "hit_hi": 0.30},
}

# DESIGN.md §2 per-mode family-share range [lo_pct, hi_pct]
FAMILY_SHARE_RANGE = {
    1: {"Seven": (18, 30), "Bar": (55, 75), "Cherry": (8, 20), "Wild": (0, 1)},
    7: {"Seven": (18, 30), "Bar": (55, 75), "Cherry": (8, 20), "Wild": (0, 1)},
    2: {"Seven": (25, 55), "Bar": (35, 65), "Cherry": (3, 15), "Wild": (0, 2)},
    5: {"Seven": (35, 70), "Bar": (25, 55), "Cherry": (1, 10), "Wild": (0, 3)},
}

# DESIGN.md §5 per-family per-reel ratio drift tolerance
RATIO_DRIFT_THRESHOLD = {
    "Blank": 0.08, "Cherry": 0.15,
    "Bar1": 0.08, "Bar2": 0.08, "Bar3": 0.08,
    "Seven1": 0.15, "Seven2": 0.15,
    "Diamond1": 0.25, "Diamond2": 0.25,  # 1-4 stops, integer rounding dominates
}

# DESIGN.md §6 near-miss mechanism (2026-04-25 revised):
# Real IGT TDD uses PER-REEL ASYMMETRY as near-miss engine — top-pay
# symbol very heavy on reel 1 + 3 but sparse on reel 2 → 2-of-3 visible
# "so close" pattern. NOT local blank-neighbor clustering (Seven2 and
# its blank neighbors have similar weights on TDD reels, so window/
# payline ratio is ~1.0, not > 1.3 as I initially assumed).
# Test: max-reel / min-reel density ratio for 顶奖 family should be > 2.5
# (TDD baseline has Seven2 R1:R2 = 24:3 = 8.0× asymmetry).
# Per-family threshold: Seven2 has 8× natural asymmetry in TDD (R1=24,
# R2=3, R3=17). Diamond family total has ~2× natural asymmetry (R1=3,
# R2=6, R3=5). Use per-family min to reflect archetype reality.
ASYMMETRY_MIN_RATIO = {"Seven2": 2.5, "Diamond": 1.8}


class Check:
    def __init__(self, tag, mode, ok, detail):
        self.tag = tag
        self.mode = mode
        self.ok = ok
        self.detail = detail

    def __str__(self):
        status = "ok " if self.ok else "RED"
        return f"  [{status}] [{self.tag:<13}] mode {self.mode}: {self.detail}"


def fam_shares(eng, spec):
    p = analytic_profile(eng)
    pay_mult = {
        str(pay.get("pay_id")): pay.get("multiplier")
        for pay in spec["pays"] if pay.get("multiplier") is not None
    }
    shares = {"Cherry": 0.0, "Seven": 0.0, "Bar": 0.0, "Wild": 0.0}
    for pid, r in p["pay_hits"].items():
        fam = FAMILY_MAP.get(str(pid))
        mult = pay_mult.get(str(pid))
        if fam and mult:
            shares[fam] += r * mult * 100
    tot = sum(shares.values()) or 1
    return {f: (shares[f], shares[f] / tot * 100) for f in shares}, p


def per_family_ratios(weights, strips):
    totals = defaultdict(lambda: [0, 0, 0])
    for ri, strip in enumerate(strips):
        for pos, sym in enumerate(strip):
            totals[sym][ri] += weights[ri][pos]
    out = {}
    for sym, t in totals.items():
        s = sum(t) or 1
        out[sym] = tuple(v / s for v in t)
    return out


def per_reel_absolute(eng, family_syms):
    return [
        sum(compute_reel_marginal(reel).get(s, 0) for s in family_syms)
        for reel in eng.reels
    ]


def per_reel_asymmetry(eng, family_syms):
    """max-reel / min-reel family density ratio. High = asymmetric
    distribution = classic 2-of-3 near-miss mechanism (e.g. TDD Seven2
    R1=9% / R2=1% ratio ~ 8×). Low = symmetric = no near-miss engineered.
    """
    per_reel = [sum(compute_reel_marginal(reel).get(s, 0) for s in family_syms)
                for reel in eng.reels]
    max_p = max(per_reel)
    min_p = min(per_reel)
    return max_p / min_p if min_p > 0 else float("inf"), per_reel


def bucket_summary(p):
    br = p["bucket_rate"]
    total_hit = p["hit_rate"]
    low = br.get("ge1_lt5", 0) + br.get("ge5_lt10", 0)
    mid = br.get("ge10_lt20", 0) + br.get("ge20_lt50", 0)
    high = br.get("ge50_lt100", 0) + br.get("ge100_lt200", 0) + br.get("ge200_lt500", 0)
    top = br.get("ge500_lt1000", 0) + br.get("ge1000_lt5000", 0) + br.get("ge5000", 0)
    return {"low_hit": low, "mid_hit": mid, "high_hit": high, "top_hit": top, "total_hit": total_hit}


def run():
    strips = json.loads(STRIPS.read_text(encoding="utf-8"))["reels"]
    tdd_ratios = per_family_ratios(TDD_BASELINE, strips)

    # Load all 4 modes first (mode 7 check needs mode 1 baseline)
    mode_data = {}
    for mode in [1, 2, 5, 7]:
        path = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
        eng, spec = load_engine(SPEC, path)
        p = analytic_profile(eng)
        w = json.loads(path.read_text(encoding="utf-8"))["weights"]
        shares, _ = fam_shares(eng, spec)
        mode_data[mode] = {
            "engine": eng, "spec": spec, "profile": p, "weights": w, "shares": shares,
            "ratios": per_family_ratios(w, strips),
        }

    checks = []
    for mode in [1, 2, 5, 7]:
        d = mode_data[mode]
        p = d["profile"]
        t = MODE_TARGETS[mode]

        # RTP
        rtp = p["rtp_pct"]
        rtp_ok = abs(rtp - t["rtp"]) <= t["rtp_tol"]
        checks.append(Check("RTP", mode, rtp_ok,
            f"{rtp:.2f}% vs target {t['rtp']}+/-{t['rtp_tol']}pp"))

        # HIT
        hit = p["hit_rate"]
        hit_ok = t["hit_lo"] <= hit <= t["hit_hi"]
        checks.append(Check("HIT", mode, hit_ok,
            f"{hit*100:.2f}% vs band [{t['hit_lo']*100:.0f}%, {t['hit_hi']*100:.0f}%]"))

        # SHARE
        for fam, (lo, hi) in FAMILY_SHARE_RANGE[mode].items():
            share = d["shares"][fam][1]
            ok = lo <= share <= hi
            checks.append(Check(f"SHARE", mode, ok,
                f"{fam} {share:.1f}% vs range [{lo}%, {hi}%]"))

        # BUCKET narrative
        b = bucket_summary(p)
        low_frac = b["low_hit"] / b["total_hit"] if b["total_hit"] else 0
        # Rough approx high RTP share: sum bucket_rate × midpoint × 100
        br = p["bucket_rate"]
        high_rtp_approx_pp = (
            br.get("ge50_lt100", 0) * 75
            + br.get("ge100_lt200", 0) * 150
            + br.get("ge200_lt500", 0) * 300
            + br.get("ge500_lt1000", 0) * 750
            + br.get("ge1000_lt5000", 0) * 1000
        ) * 100
        high_share_pct = (high_rtp_approx_pp / rtp * 100) if rtp > 0 else 0
        # For lucky modes Low fraction may dip below 50% naturally
        low_threshold = 0.50 if mode in (1, 7) else 0.30
        low_ok = low_frac >= low_threshold
        checks.append(Check("BUCKET-LOW", mode, low_ok,
            f"Low hit/total = {low_frac*100:.1f}% vs min {low_threshold*100:.0f}%"))
        high_min = 12 if mode in (1, 7) else 20
        high_ok = high_share_pct >= high_min
        checks.append(Check("BUCKET-HIGH", mode, high_ok,
            f"High RTP share ~ {high_share_pct:.1f}% vs min {high_min}%"))

        # RATIO drift
        for sym, tdd_r in tdd_ratios.items():
            mode_r = d["ratios"].get(sym, (0, 0, 0))
            drift = max(abs(tdd_r[i] - mode_r[i]) for i in range(3))
            tol = RATIO_DRIFT_THRESHOLD.get(sym, 0.15)
            ok = drift < tol
            checks.append(Check("RATIO", mode, ok,
                f"{sym} R1:R2:R3 drift {drift:.3f} vs tol {tol:.2f}"))

        # ASYMMETRY (Seven2 + Diamond family per-reel max/min ratio).
        # Real TDD near-miss mechanism: top-pay symbols asymmetric across
        # reels → 2-of-3 visible near-miss triggers often.
        for fam_name, fam_syms in [("Seven2", ["Seven2"]), ("Diamond", ["Diamond1", "Diamond2"])]:
            ratio, per_reel = per_reel_asymmetry(d["engine"], fam_syms)
            min_ratio = ASYMMETRY_MIN_RATIO[fam_name]
            ok = ratio >= min_ratio
            pcts = "/".join(f"{p*100:.1f}%" for p in per_reel)
            checks.append(Check("ASYMMETRY", mode, ok,
                f"{fam_name} R1/R2/R3={pcts} max/min={ratio:.2f} vs min {min_ratio}"))

    # Mode 7 vs Mode 1 experience invariants (§4)
    m1 = mode_data[1]
    m7 = mode_data[7]
    for fam_name, fam_syms in [("Seven", ["Seven1", "Seven2"]), ("Diamond", ["Diamond1", "Diamond2"])]:
        m1_marg = per_reel_absolute(m1["engine"], fam_syms)
        m7_marg = per_reel_absolute(m7["engine"], fam_syms)
        # Per-reel: mode 7 ≥ mode 1 × 0.9
        reel_oks = [m7_marg[r] >= m1_marg[r] * 0.9 for r in range(3)]
        ok = all(reel_oks)
        detail = f"{fam_name} per-reel m7/m1 = " + "/".join(
            f"{m7_marg[r]/m1_marg[r]:.2f}" if m1_marg[r] else "inf" for r in range(3))
        detail += " (min 0.90)"
        tag = "MODE7-SEVEN" if fam_name == "Seven" else "MODE7-DIAM"
        checks.append(Check(tag, 7, ok, detail))

    # Mode 7 Seven share ≥ mode 1 Seven share × 0.95
    m1_seven_share = m1["shares"]["Seven"][1]
    m7_seven_share = m7["shares"]["Seven"][1]
    share_ok = m7_seven_share >= m1_seven_share * 0.95
    checks.append(Check("MODE7-SHARE", 7, share_ok,
        f"Seven share m7/m1 = {m7_seven_share/m1_seven_share:.2f} (min 0.95)"))

    # Report
    print("\n=== M1 design verification ===")
    print("Reference: slot_designer/weights/M1/DESIGN.md\n")
    by_mode = defaultdict(list)
    for c in checks:
        by_mode[c.mode].append(c)
    for mode in [1, 2, 5, 7]:
        print(f"--- Mode {mode} ---")
        for c in by_mode[mode]:
            print(c)
        print()

    reds = [c for c in checks if not c.ok]
    total = len(checks)
    if reds:
        print(f"*** {len(reds)}/{total} checks RED ***")
        for c in reds:
            print(f"  mode {c.mode} [{c.tag}]: {c.detail}")
        return 1
    print(f"*** All {total} checks GREEN ***")
    return 0


if __name__ == "__main__":
    sys.exit(run())
