"""Critic X v14d M5_HMV_plus — Phase 3: shipped m2 vs M2_LC for context.

The shipped m2 (after v14c ship) IS M2_LC. But shipped v9 m2 (PRE-ship) was different.
Important: which is the anchor referenced by 'm2' in the user's brief 'mode2 base'?

Also — final integer-rounding sweep at scale closer to engine reality.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

_M15 = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15 / "spec.json"
STRIPS_PATH = _M15 / "reel_strips.json"
W_M1 = _M15 / "weights" / "mode_1" / "weights.json"
W_M2 = _M15 / "weights" / "mode_2" / "weights.json"
W_M5 = _M15 / "weights" / "mode_5" / "weights.json"
W_M7 = _M15 / "weights" / "mode_7" / "weights.json"

engine, _spec = load_engine(SPEC_PATH, W_M1, strips_path=STRIPS_PATH)
EV = engine.evaluator

STRIPS = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

# Load shipped m2 from current weights.json
M2_shipped_doc = json.loads(W_M2.read_text(encoding="utf-8"))

def derive_marginals_from_weights(weights_list, strips):
    margs = []
    for r_idx, (w_arr, strip) in enumerate(zip(weights_list, strips)):
        sym_w = defaultdict(float)
        for w, sym in zip(w_arr, strip):
            sym_w[sym] += w
        total = sum(sym_w.values())
        margs.append({sym: w / total for sym, w in sym_w.items()})
    return margs

margs_m2_shipped = derive_marginals_from_weights(M2_shipped_doc["weights"], STRIPS)

FP_BY_MODE = {
    1: json.loads(W_M1.read_text(encoding="utf-8"))["feature_params"],
    2: M2_shipped_doc["feature_params"],
    5: json.loads(W_M5.read_text(encoding="utf-8"))["feature_params"],
    7: json.loads(W_M7.read_text(encoding="utf-8"))["feature_params"],
}


def feature_stats(fp):
    dist = _round_payout_distribution(
        tuple(fp["x_count_weights"]),
        tuple(fp["y_count_weights"]),
        tuple(fp["x_value_weights"]),
        tuple(fp["y_value_weights"]),
    )
    accept_thr = fp["accept_threshold"]
    p_accept = sum(p for r, p in dist if r >= accept_thr)
    if p_accept == 0:
        return {"ev": 0.0, "p_r_ge_200": 0.0, "p_r_ge_1000": 0.0}
    A = sum(r * p for r, p in dist if r >= accept_thr) / p_accept
    U = sum(r * p for r, p in dist)
    max_r = fp["max_rounds"]
    reject_streak = 1.0 - p_accept
    ev = 0.0
    for round_idx in range(1, max_r):
        ev += (reject_streak ** (round_idx - 1)) * p_accept * A
    ev += (reject_streak ** (max_r - 1)) * U
    return {"ev": ev,
            "p_r_ge_200": sum(p for r, p in dist if r >= 200),
            "p_r_ge_1000": sum(p for r, p in dist if r >= 1000)}


FEAT = {m: feature_stats(fp) for m, fp in FP_BY_MODE.items()}


def evaluate_quick(margs, mode):
    prof = analytic_profile_from_marginals(EV, margs)
    base = prof["rtp_pct"]
    hit = prof["hit_rate"]
    trig = margs[2].get("topdollar", 0.0)
    feat_rtp = trig * FEAT[mode]["ev"] * 100.0
    return {
        "base_rtp_pct": base, "total_rtp_pct": base + feat_rtp,
        "base_hit_pct": hit * 100, "trigger_pct": trig * 100,
        "trigger": trig, "pay_hits": prof["pay_hits"],
    }


print("--- Shipped m2 (current weights.json) ---")
shipped_m2_res = evaluate_quick(margs_m2_shipped, 2)
print(f"Base RTP: {shipped_m2_res['base_rtp_pct']:.3f}pp")
print(f"Total RTP: {shipped_m2_res['total_rtp_pct']:.3f}pp")
print(f"Base hit: {shipped_m2_res['base_hit_pct']:.4f}%")
print(f"Trigger: {shipped_m2_res['trigger_pct']:.4f}%")
print(f"R1 blank: {margs_m2_shipped[0]['blank']*100:.2f}%")
print(f"R3 blank: {margs_m2_shipped[2]['blank']*100:.2f}%")

# Marginals
print("\nShipped m2 marginals:")
for sym in ["blank", "cherry", "1bar", "2bar", "3bar", "high7",
            "doublediamond", "topdollar", "jackpot"]:
    v = [margs_m2_shipped[r].get(sym, 0) * 100 for r in range(3)]
    print(f"  {sym:14s}  R1={v[0]:6.3f}  R2={v[1]:6.3f}  R3={v[2]:6.3f}")
