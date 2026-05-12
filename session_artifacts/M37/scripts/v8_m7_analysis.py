"""Designer v8 m7 analysis — universal §4 player-experience optimal cut strategy.

Steps:
 1. Compute m1 v5 baseline (analytic): per-pay_id hit, per-symbol marginal, RTP, hit, pid9_share.
 2. Per-pay_id tier classification (designer's own analysis cited inline).
 3. Lever × per-pay impact matrix (probe each lever solo at moderate cut, measure delta).
 4. Candidate cutting strategies (5 candidates), each measured + scored.
 5. Recommend best by player-experience metric.
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


# Reel-strip layout cached for indexing levers.
with STRIPS.open("r", encoding="utf-8") as f:
    _strip_data = json.load(f)
REELS = _strip_data["reels"]  # 3 reels × 26 stops
# Map (reel_idx, symbol) -> list of position indices.
SYM_POS: dict[tuple[int, str], list[int]] = {}
for ri, reel in enumerate(REELS):
    for pi, sym in enumerate(reel):
        SYM_POS.setdefault((ri, sym), []).append(pi)


def load_weights(path: Path) -> list[list[float]]:
    with path.open("r", encoding="utf-8") as f:
        return [list(row) for row in json.load(f)["weights"]]


def profile_from_weights(weights: list[list[float]]) -> dict:
    """Construct a temporary weights.json + load engine + run analytic_profile."""
    import tempfile, os
    tmpdir = Path(tempfile.mkdtemp(prefix="m37_v8_"))
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
        engine, _spec = load_engine(machine_root / "spec.json", wpath)
        return analytic_profile(engine), engine
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def reel_marginals(weights: list[list[float]]) -> list[dict[str, float]]:
    """Per-reel symbol marginal from a raw weights matrix (without loading engine)."""
    out = []
    for ri, reel_weights in enumerate(weights):
        totals: dict[str, float] = {}
        total_w = sum(reel_weights)
        for pi, w in enumerate(reel_weights):
            sym = REELS[ri][pi]
            totals[sym] = totals.get(sym, 0.0) + w
        out.append({s: w / total_w for s, w in totals.items()})
    return out


def pid9_share(profile: dict) -> float:
    """pid 9 RTP / total RTP * 100."""
    return profile["pay_rtp"].get("9", 0.0) / (profile["rtp_pct"] / 100.0) * 100.0


# ----- Scale a symbol's weight on a given reel by factor k. -----
def scale_symbol(weights: list[list[float]], reel_idx: int, symbol: str, k: float, *, distribute_to: str = "blank") -> list[list[float]]:
    """Multiply every position of `symbol` on `reel_idx` by k. Conserves per-reel total
    weight by redistributing the saved/added weight to `distribute_to` positions (proportionally).
    Returns a NEW weights matrix."""
    out = [row[:] for row in weights]
    positions = SYM_POS.get((reel_idx, symbol), [])
    if not positions:
        return out
    old_sum = sum(out[reel_idx][p] for p in positions)
    new_sum = old_sum * k
    delta = new_sum - old_sum  # positive = boost, negative = cut (saved -> distribute)
    for p in positions:
        out[reel_idx][p] = out[reel_idx][p] * k
    # Distribute -delta to `distribute_to` positions (proportionally to current weight).
    dist_positions = SYM_POS.get((reel_idx, distribute_to), [])
    if not dist_positions:
        return out
    dist_total = sum(out[reel_idx][p] for p in dist_positions)
    if dist_total == 0:
        return out
    # absorb -delta proportionally
    for p in dist_positions:
        share = out[reel_idx][p] / dist_total
        out[reel_idx][p] -= delta * share
    return out


def scale_symbols(weights: list[list[float]], scales: list[tuple[int, str, float]]) -> list[list[float]]:
    """Apply multiple (reel, symbol, k) scales sequentially. distribute_to=blank for all."""
    out = [row[:] for row in weights]
    for ri, sym, k in scales:
        out = scale_symbol(out, ri, sym, k)
    return out


def print_profile(label: str, profile: dict, *, baseline: dict | None = None):
    rtp = profile["rtp_pct"]
    hit = profile["hit_rate"] * 100
    pid9 = pid9_share(profile)
    print(f"\n=== {label} ===")
    print(f"RTP: {rtp:.3f}%  hit: {hit:.3f}%  pid9 share: {pid9:.2f}%")
    # per-pay frequency (probability of pay_id firing per spin)
    keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "102", "103", "104"]
    print(f"{'pid':<5} {'freq':>10} {'rtp_pp':>8} {'mult_avg':>10} {'ratio_vs_base':>14}")
    for k in keys:
        p = profile["pay_hits"].get(k, 0.0)
        r = profile["pay_rtp"].get(k, 0.0) * 100  # rtp percentage points (sum to rtp_pct)
        mult_avg = (r / 100.0) / p if p > 0 else 0.0
        ratio_str = ""
        if baseline is not None:
            base_p = baseline["pay_hits"].get(k, 0.0)
            if base_p > 0:
                ratio = p / base_p
                ratio_str = f"{ratio:.3f}"
            else:
                ratio_str = "n/a"
        print(f"{k:<5} {p:>10.5f} {r:>8.3f} {mult_avg:>10.2f} {ratio_str:>14}")


def main():
    # ---------- Step 1: m1 v5 baseline ----------
    m1_weights = load_weights(M1_WEIGHTS)
    m1_profile, _engine = profile_from_weights(m1_weights)
    print_profile("M1 v5 baseline", m1_profile)
    print("\nm1 reel marginals (mode 1):")
    margs = reel_marginals(m1_weights)
    for ri, m in enumerate(margs):
        print(f"  R{ri+1}: ", {k: round(v, 4) for k, v in sorted(m.items(), key=lambda x: -x[1])})

    # ---------- Step 3: Lever × per-pay impact matrix ----------
    print("\n\n===== LEVER × PER-PAY IMPACT MATRIX =====")
    print("Each lever applied at k=0.5 (50% cut). Reports per-pay frequency ratio vs baseline.\n")
    levers = [
        ("R2 mini ÷2", [(1, "mini", 0.5)]),
        ("R2 minor ÷2", [(1, "minor", 0.5)]),
        ("R2 major ÷2", [(1, "major", 0.5)]),
        ("R2 high7 ÷2", [(1, "high7", 0.5)]),
        ("R2 7bar ÷2", [(1, "7bar", 0.5)]),
        ("R2 3bar ÷2", [(1, "3bar", 0.5)]),
        ("R2 2bar ÷2", [(1, "2bar", 0.5)]),
        ("R2 1bar ÷2", [(1, "1bar", 0.5)]),
        ("R1 wild ÷2", [(0, "wild", 0.5)]),
        ("R3 wild ÷2", [(2, "wild", 0.5)]),
        ("R1+R3 wild ÷2", [(0, "wild", 0.5), (2, "wild", 0.5)]),
        ("R1+R3 7bar ÷2", [(0, "7bar", 0.5), (2, "7bar", 0.5)]),
        ("R1+R3 3bar ÷2", [(0, "3bar", 0.5), (2, "3bar", 0.5)]),
        ("R1+R3 2bar ÷2", [(0, "2bar", 0.5), (2, "2bar", 0.5)]),
        ("R1+R3 1bar ÷2", [(0, "1bar", 0.5), (2, "1bar", 0.5)]),
        ("R1+R3 high7 ÷2", [(0, "high7", 0.5), (2, "high7", 0.5)]),
    ]
    pids = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "102", "103", "104"]
    header = f"{'lever':<22} {'RTP%':>7} {'hit%':>6} {'pid9%':>6}  " + " ".join(f"{p:>5}" for p in pids)
    print(header)
    print(header.replace("R", "-")[:len(header)].replace("0", "-"))
    base_hits = m1_profile["pay_hits"]
    for label, scales in levers:
        w2 = scale_symbols(m1_weights, scales)
        p, _ = profile_from_weights(w2)
        ratios = []
        for pid in pids:
            base_p = base_hits.get(pid, 0.0)
            new_p = p["pay_hits"].get(pid, 0.0)
            if base_p > 0:
                ratios.append(f"{new_p/base_p:>5.2f}")
            else:
                ratios.append(f"{'-':>5}")
        print(f"{label:<22} {p['rtp_pct']:>7.2f} {p['hit_rate']*100:>6.2f} {pid9_share(p):>6.2f}  " + " ".join(ratios))


    # ---------- Step 4: Cutting strategy candidates ----------
    print("\n\n===== CANDIDATE CUTTING STRATEGIES (target RTP 84-86, hit < 20.62, §4 mid/big/top preserve) =====")
    strategies = {
        # Strategy A: cut R2 mini hard (small-tier center booster alone),
        #            cut R1+R3 wild moderate (side-wild-alone = small pid9 mult1),
        #            cut R1+R3 1bar moderate (pid 7 anybar small).
        "A: R2 mini ÷ + R13 wild ÷ + R13 1bar ÷": [
            (1, "mini", 0.45),
            (0, "wild", 0.75), (2, "wild", 0.75),
            (0, "1bar", 0.80), (2, "1bar", 0.80),
        ],
        # Strategy B: R2 mini+minor cut (both small-tier alone if minor is small).
        "B: R2 mini ÷ + R2 minor ÷ + R13 wild ÷": [
            (1, "mini", 0.40),
            (1, "minor", 0.55),
            (0, "wild", 0.75), (2, "wild", 0.75),
        ],
        # Strategy C: cut R2 mini deep alone (focus on cheapest small-cost lever).
        "C: R2 mini ÷ deep + R13 wild mild": [
            (1, "mini", 0.30),
            (0, "wild", 0.85), (2, "wild", 0.85),
        ],
        # Strategy D: cut R13 1bar + R13 2bar (mostly pid 7 + small pid 5/4 mid).
        "D: R13 bar low-tier cut + R13 wild ÷": [
            (0, "1bar", 0.70), (2, "1bar", 0.70),
            (0, "2bar", 0.70), (2, "2bar", 0.70),
            (0, "wild", 0.75), (2, "wild", 0.75),
        ],
        # Strategy E: cut R2 mini ÷ + cut R13 wild ÷.
        "E: R2 mini ÷ + R13 wild ÷ (clean)": [
            (1, "mini", 0.30),
            (0, "wild", 0.70), (2, "wild", 0.70),
        ],
        # Strategy F: cut R13 1bar only (pid 7 anybar - 100% small).
        "F: R13 1bar ÷ deep + R2 mini ÷": [
            (0, "1bar", 0.40), (2, "1bar", 0.40),
            (1, "mini", 0.50),
        ],
    }
    for name, scales in strategies.items():
        w2 = scale_symbols(m1_weights, scales)
        p, _ = profile_from_weights(w2)
        print_profile(name, p, baseline=m1_profile)


if __name__ == "__main__":
    main()
