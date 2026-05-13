"""Critic X v14d M5_HMV_plus — Phase 2 metrics.

Additional concerns:
  - Shipped v9 m5 high-mult share for comparison (Q9 coherence)
  - Integer-realization at higher scales (~50000) closer to engine
  - Hit margin survives engine integer-rounding via marginals_to_weights
  - Hard concerns triage
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
W_M5_SHIPPED = _M15 / "weights" / "mode_5" / "weights.json"
W_M7 = _M15 / "weights" / "mode_7" / "weights.json"

engine, _spec = load_engine(SPEC_PATH, W_M1, strips_path=STRIPS_PATH)
EV = engine.evaluator


def get_marginals_from_weights(weights_doc):
    """Extract per-reel marginal probabilities from a weights doc."""
    reels = weights_doc["weights"]
    margs = []
    for r in reels:
        total = sum(r.values())
        m = {sym: w / total for sym, w in r.items()}
        margs.append(m)
    return margs


# Load shipped v9 m5 — weights are per-stop integers parallel to reel_strips
M5_shipped_doc = json.loads(W_M5_SHIPPED.read_text(encoding="utf-8"))
STRIPS = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

def derive_marginals_from_weights(weights_list, strips):
    """weights_list[r_idx][stop_idx] -> integer weight. strips[r_idx][stop_idx] -> symbol str."""
    margs = []
    for r_idx, (w_arr, strip) in enumerate(zip(weights_list, strips)):
        assert len(w_arr) == len(strip), f"reel {r_idx} length mismatch"
        sym_w = defaultdict(float)
        for w, sym in zip(w_arr, strip):
            sym_w[sym] += w
        total = sum(sym_w.values())
        margs.append({sym: w / total for sym, w in sym_w.items()})
    return margs

margs_shipped = derive_marginals_from_weights(M5_shipped_doc["weights"], STRIPS)

FP_BY_MODE = {
    1: json.loads(W_M1.read_text(encoding="utf-8"))["feature_params"],
    2: json.loads(W_M2.read_text(encoding="utf-8"))["feature_params"],
    5: M5_shipped_doc["feature_params"],
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
        return {"ev": 0.0, "p_r_ge_200": 0.0, "p_r_ge_1000": 0.0,
                "p_accept": 0.0, "A": 0.0, "U": 0.0, "dist": dist}
    A = sum(r * p for r, p in dist if r >= accept_thr) / p_accept
    U = sum(r * p for r, p in dist)
    max_r = fp["max_rounds"]
    reject_streak = 1.0 - p_accept
    ev = 0.0
    for round_idx in range(1, max_r):
        ev += (reject_streak ** (round_idx - 1)) * p_accept * A
    ev += (reject_streak ** (max_r - 1)) * U
    p_r_ge_200 = sum(p for r, p in dist if r >= 200)
    p_r_ge_1000 = sum(p for r, p in dist if r >= 1000)
    return {"ev": ev, "p_r_ge_200": p_r_ge_200, "p_r_ge_1000": p_r_ge_1000,
            "p_accept": p_accept, "A": A, "U": U, "dist": dist}


FEAT = {m: feature_stats(fp) for m, fp in FP_BY_MODE.items()}

PAY_FAM = {"9": "cherry1", "71": "cherry2", "4": "cherry3", "1": "wild_pure",
           "2": "high7_wild", "21": "high7_pure", "3": "bar3", "5": "bar2",
           "7": "bar1", "8": "bar_mixed"}


def evaluate(margs, mode):
    prof = analytic_profile_from_marginals(EV, margs)
    base = prof["rtp_pct"]
    hit = prof["hit_rate"]
    trig = margs[2].get("topdollar", 0.0)
    feat = FEAT[mode]
    feat_rtp = trig * feat["ev"] * 100.0
    tot = base + feat_rtp
    fam_pp = defaultdict(float)
    for pid, rtp in prof["pay_rtp"].items():
        fam = PAY_FAM.get(pid)
        if fam is None:
            continue
        fam_pp[fam] += rtp * 100.0
    high7_combined = fam_pp.get("high7_wild", 0) + fam_pp.get("high7_pure", 0)
    fam_share = {}
    if base > 0:
        for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                    "bar_mixed", "wild_pure"):
            fam_share[fam] = fam_pp.get(fam, 0) / base * 100.0
        fam_share["high7"] = high7_combined / base * 100.0
    return {
        "mode": mode, "total_rtp_pct": tot, "base_rtp_pct": base,
        "feature_rtp_pct": feat_rtp,
        "base_hit_pct": hit * 100,
        "trigger_pct": trig * 100, "trigger": trig,
        "pay_hits": prof["pay_hits"], "pay_rtp": prof["pay_rtp"],
        "family_pp": dict(fam_pp), "family_share_pct": fam_share,
    }


def base_decomp_by_combo(margs):
    """Decompose base RTP by FINAL combo multiplier."""
    import itertools

    symbols_per_reel = [list(m.keys()) for m in margs]
    combo_tier_pp = {
        "1x_le1": 0.0, "ge2_lt5": 0.0, "ge5_lt10": 0.0, "ge10_lt20": 0.0,
        "ge20_lt30": 0.0, "ge30_lt50": 0.0, "ge50_lt100": 0.0,
        "ge100_lt200": 0.0, "ge200_lt500": 0.0, "ge500": 0.0,
    }
    pid_rtp_pp = defaultdict(float)
    for combo in itertools.product(*symbols_per_reel):
        prob = 1.0
        for marg, sym in zip(margs, combo):
            prob *= marg[sym]
        if prob == 0:
            continue
        result = EV.evaluate_payline(list(combo))
        if result is None:
            continue
        mult = float(result.multiplier)
        rtp_contrib = prob * mult * 100.0
        pid_rtp_pp[str(result.pay_id)] += rtp_contrib
        if mult <= 1:
            combo_tier_pp["1x_le1"] += rtp_contrib
        elif mult < 5:
            combo_tier_pp["ge2_lt5"] += rtp_contrib
        elif mult < 10:
            combo_tier_pp["ge5_lt10"] += rtp_contrib
        elif mult < 20:
            combo_tier_pp["ge10_lt20"] += rtp_contrib
        elif mult < 30:
            combo_tier_pp["ge20_lt30"] += rtp_contrib
        elif mult < 50:
            combo_tier_pp["ge30_lt50"] += rtp_contrib
        elif mult < 100:
            combo_tier_pp["ge50_lt100"] += rtp_contrib
        elif mult < 200:
            combo_tier_pp["ge100_lt200"] += rtp_contrib
        elif mult < 500:
            combo_tier_pp["ge200_lt500"] += rtp_contrib
        else:
            combo_tier_pp["ge500"] += rtp_contrib

    base_pp = sum(combo_tier_pp.values())
    ge_30_pp = (combo_tier_pp["ge30_lt50"] + combo_tier_pp["ge50_lt100"]
                + combo_tier_pp["ge100_lt200"] + combo_tier_pp["ge200_lt500"]
                + combo_tier_pp["ge500"])
    ge_30_share = ge_30_pp / base_pp * 100.0 if base_pp > 0 else 0.0
    payid_tier_pp = {
        "1x": pid_rtp_pp.get("9", 0.0),
        "lt15": (pid_rtp_pp.get("71", 0.0) + pid_rtp_pp.get("8", 0.0)
                 + pid_rtp_pp.get("7", 0.0)),
        "15": pid_rtp_pp.get("4", 0.0),
        "30": pid_rtp_pp.get("21", 0.0),
        "40_120": (pid_rtp_pp.get("2", 0.0) + pid_rtp_pp.get("3", 0.0)
                   + pid_rtp_pp.get("5", 0.0)),
        "200": pid_rtp_pp.get("1", 0.0),
    }
    payid_ge30_pp = (payid_tier_pp["30"] + payid_tier_pp["40_120"]
                     + payid_tier_pp["200"])
    payid_ge30_share = payid_ge30_pp / base_pp * 100.0 if base_pp > 0 else 0.0
    return {
        "tier_pp": combo_tier_pp,
        "pid_rtp_pp": dict(pid_rtp_pp),
        "base_pp": base_pp,
        "ge_30_pp": ge_30_pp,
        "ge_30_share_pct": ge_30_share,
        "payid_ge_30_share_pct": payid_ge30_share,
    }


# Compute shipped v9 m5 metrics
if margs_shipped is not None:
    M5_shipped_res = evaluate(margs_shipped, 5)
    M5_shipped_decomp = base_decomp_by_combo(margs_shipped)
    print("\n--- Shipped v9 m5 reference ---")
    print(f"  Base RTP: {M5_shipped_res['base_rtp_pct']:.3f}pp")
    print(f"  Total RTP: {M5_shipped_res['total_rtp_pct']:.3f}pp")
    print(f"  Base hit: {M5_shipped_res['base_hit_pct']:.3f}%")
    print(f"  Trigger: {M5_shipped_res['trigger_pct']:.4f}%")
    print(f"  >=30 share (payid): {M5_shipped_decomp['payid_ge_30_share_pct']:.2f}%")
    print(f"  >=30 share (combo): {M5_shipped_decomp['ge_30_share_pct']:.2f}%")
    print(f"  R1 blank: {margs_shipped[0]['blank']*100:.2f}%")
    print(f"  R3 blank: {margs_shipped[2]['blank']*100:.2f}%")
    print(f"\n  Shipped v9 m5 family share-of-base:")
    for fam in sorted(M5_shipped_res["family_share_pct"],
                      key=lambda f: -M5_shipped_res["family_share_pct"][f]):
        sh = M5_shipped_res["family_share_pct"][fam]
        print(f"    {fam:14s}  {sh:.2f}%")
