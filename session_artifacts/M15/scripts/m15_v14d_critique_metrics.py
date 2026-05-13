"""Critic X v14d M5_HMV_plus — independent metrics audit.

Reconstructs M5_HMV_plus from scalar lifts over M2_LC (shipped) and independently
verifies D's claims:
  - Base RTP 98.68pp, Total RTP 508.21pp
  - Base hit 33.91%, Trigger 3.3205%
  - Base >=30x mult share 40.12% (payid) / 23.81% (combo)
  - Bar S1 hierarchy P values (D: tied-tol 0.10pp)
  - wild_pure cadence 1/60,993
  - bar1 share-of-base
  - LUCKY-MONO integer-rounded margins

Also runs deeper checks D did not:
  - Engine-realized integer rounding at scales 1000/2000/5000/10000
  - bar1 family alive vs cosmetic
  - per-mode total RTP ceiling probability under SE
  - Cherry lift impact on low-mult bucket (Q7)
  - Cross-mode coherence vs shipped v9 m5
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

FP_BY_MODE = {
    1: json.loads(W_M1.read_text(encoding="utf-8"))["feature_params"],
    2: json.loads(W_M2.read_text(encoding="utf-8"))["feature_params"],
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


def normalize(m):
    out = dict(m)
    nb = sum(v for k, v in out.items() if k != "blank")
    out["blank"] = max(0.0, 1.0 - nb)
    return out


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
    p_wild = prof["pay_hits"].get("1", 0)
    return {
        "mode": mode, "total_rtp_pct": tot, "base_rtp_pct": base,
        "feature_rtp_pct": feat_rtp,
        "hit_session_pct": (hit + trig) * 100,
        "base_hit_pct": hit * 100,
        "trigger_pct": trig * 100, "trigger": trig,
        "r1_blank_pct": margs[0]["blank"] * 100,
        "r2_blank_pct": margs[1]["blank"] * 100,
        "r3_blank_pct": margs[2]["blank"] * 100,
        "pay_hits": prof["pay_hits"], "pay_rtp": prof["pay_rtp"],
        "family_pp": dict(fam_pp), "family_share_pct": fam_share,
        "high7_combined_pp": high7_combined,
        "wild_cad": 1.0 / p_wild if p_wild > 0 else float("inf"),
        "p_r_ge_1000_spin": trig * feat["p_r_ge_1000"],
        "p_r_ge_200_spin": trig * feat["p_r_ge_200"],
        "cv": prof["cv"], "margs": margs,
    }


def base_decomp_by_combo(margs):
    """Decompose base RTP by FINAL combo multiplier (post-wild-boost)."""
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

    # Payid-anchored (D's convention) — full pay rtp by anchor family
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
        "payid_tier_pp": payid_tier_pp,
        "pid_rtp_pp": dict(pid_rtp_pp),
        "base_pp": base_pp,
        "ge_30_pp": ge_30_pp,
        "ge_30_share_pct": ge_30_share,
        "payid_ge_30_pp": payid_ge30_pp,
        "payid_ge_30_share_pct": payid_ge30_share,
    }


# =============================================================================
# Reconstruct M5_HMV_plus from scalar lifts (as D specifies)
# =============================================================================

# Shipped m2 marginals (M2_LC after v14c ship)
M2_MARGINALS = [
    {"cherry": 0.06400, "1bar": 0.21805, "2bar": 0.17798, "3bar": 0.11146,
     "high7": 0.12168, "doublediamond": 0.02755, "jackpot": 0.004},
    {"cherry": 0.06300, "1bar": 0.23774, "2bar": 0.19483, "3bar": 0.10498,
     "high7": 0.12248, "doublediamond": 0.02520, "jackpot": 0.004},
    {"cherry": 0.05000, "1bar": 0.24282, "2bar": 0.19782, "3bar": 0.09882,
     "high7": 0.12220, "doublediamond": 0.02040, "topdollar": 0.03304,
     "jackpot": 0.003},
]
M2_MARGINALS = [normalize(m) for m in M2_MARGINALS]
M2_RES = evaluate(M2_MARGINALS, 2)
M2_DECOMP = base_decomp_by_combo(M2_MARGINALS)


def make_m5_hmv_plus():
    """Build M5_HMV+ via D's scalar values."""
    c_lift = 1.13
    b1_lift = 0.85
    b2_lift = 1.03
    b3_lift = 1.05
    h_lift = 1.03
    dd_lift = 1.05
    td_lift = 1.005
    margs = []
    for m in M2_MARGINALS:
        new = {}
        for sym, mg in m.items():
            if sym == "blank":
                continue
            elif sym == "doublediamond":
                new[sym] = mg * dd_lift
            elif sym == "topdollar":
                new[sym] = mg * td_lift
            elif sym == "cherry":
                new[sym] = mg * c_lift
            elif sym == "1bar":
                new[sym] = mg * b1_lift
            elif sym == "2bar":
                new[sym] = mg * b2_lift
            elif sym == "3bar":
                new[sym] = mg * b3_lift
            elif sym == "high7":
                new[sym] = mg * h_lift
            else:
                new[sym] = mg
        margs.append(normalize(new))
    return margs


M5_HMV_MARGINALS = make_m5_hmv_plus()
M5_HMV_RES = evaluate(M5_HMV_MARGINALS, 5)
M5_HMV_DECOMP = base_decomp_by_combo(M5_HMV_MARGINALS)


# =============================================================================
# Integer-rounded marginals (engine reality)
# =============================================================================

def marginals_to_int_weights(margs, scale):
    """Round marginals to integer weights at given scale."""
    int_margs = []
    for m in margs:
        # Use blank=remainder
        items = [(sym, mg) for sym, mg in m.items()]
        weights = {sym: round(mg * scale) for sym, mg in items}
        total = sum(weights.values())
        # Renormalize to marginals
        if total > 0:
            new_m = {sym: w / total for sym, w in weights.items()}
        else:
            new_m = m
        int_margs.append(new_m)
    return int_margs


# =============================================================================
# Section A: Validate D's headline claims
# =============================================================================

print("=" * 80)
print("CRITIC X — M5_HMV_plus v14d — INDEPENDENT METRICS AUDIT")
print("=" * 80)

print("\n--- M5_HMV_plus reconstructed marginals ---")
print(f"{'symbol':14s}  {'R1':>8s}  {'R2':>8s}  {'R3':>8s}")
for sym in ["blank", "cherry", "1bar", "2bar", "3bar", "high7",
            "doublediamond", "topdollar", "jackpot"]:
    v = [M5_HMV_MARGINALS[r].get(sym, 0) * 100 for r in range(3)]
    print(f"{sym:14s}  {v[0]:8.4f}  {v[1]:8.4f}  {v[2]:8.4f}")

print("\n--- D's headline claims — INDEPENDENT recompute ---")
print(f"D claim  Total RTP: 508.21pp  |  recompute: {M5_HMV_RES['total_rtp_pct']:.3f}pp")
print(f"D claim  Base RTP:  98.68pp   |  recompute: {M5_HMV_RES['base_rtp_pct']:.3f}pp")
print(f"D claim  Feature RTP: 409.53pp|  recompute: {M5_HMV_RES['feature_rtp_pct']:.3f}pp")
print(f"D claim  Base hit:  33.91%    |  recompute: {M5_HMV_RES['base_hit_pct']:.4f}%")
print(f"D claim  Trigger:   3.3205%   |  recompute: {M5_HMV_RES['trigger_pct']:.4f}%")
print(f"D claim  Wild_cad:  1/60,993  |  recompute: 1/{M5_HMV_RES['wild_cad']:.0f}")
print(f"D claim  >=30 share (payid): 40.12% | recompute: "
      f"{M5_HMV_DECOMP['payid_ge_30_share_pct']:.2f}%")
print(f"D claim  >=30 share (combo): 23.81% | recompute: "
      f"{M5_HMV_DECOMP['ge_30_share_pct']:.2f}%")
print(f"M2_LC anchor >=30 share (payid): 36.17%  | recompute: "
      f"{M2_DECOMP['payid_ge_30_share_pct']:.2f}%")
print(f"M2_LC anchor >=30 share (combo): 21.38%  | recompute: "
      f"{M2_DECOMP['ge_30_share_pct']:.2f}%")
print(f">=30 share shift (payid): "
      f"{M5_HMV_DECOMP['payid_ge_30_share_pct'] - M2_DECOMP['payid_ge_30_share_pct']:+.2f}pp")
print(f">=30 share shift (combo): "
      f"{M5_HMV_DECOMP['ge_30_share_pct'] - M2_DECOMP['ge_30_share_pct']:+.2f}pp")


# =============================================================================
# Section B: Per-payid contribution to the +3.95pp shift (Q1 decomposition)
# =============================================================================
print("\n--- Per-payid contribution to >=30 share shift (Q1 decomp) ---")
print(f"{'pay_id':>6s}  {'family':>12s}  {'M2 pp':>7s}  {'M5 pp':>7s}  {'delta':>7s}  contributes to >=30?")
for pid in sorted(M5_HMV_DECOMP["pid_rtp_pp"].keys()):
    m2_pp = M2_DECOMP["pid_rtp_pp"].get(pid, 0)
    m5_pp = M5_HMV_DECOMP["pid_rtp_pp"].get(pid, 0)
    delta = m5_pp - m2_pp
    fam = PAY_FAM.get(pid, "?")
    # By D's payid scheme: 1 (wild 200x), 2 (h7w 30/60/120), 21 (h7p 30), 3 (bar3 20/40/80), 5 (bar2 10/20/40)
    is_ge30 = pid in ("1", "2", "21", "3", "5")  # D's convention
    is_ge30_strict = pid in ("1", "2", "21")  # strict combo-final-mult anchor
    print(f"  {pid:>4s}  {fam:>12s}  {m2_pp:>7.3f}  {m5_pp:>7.3f}  {delta:>+7.3f}  "
          f"payid_ge30={is_ge30} strict={is_ge30_strict}")


# =============================================================================
# Section C: Bar S1 hierarchy P-values (exact)
# =============================================================================
print("\n--- Bar S1 hierarchy P-values (Q3) ---")
b1 = M5_HMV_RES["pay_hits"].get("7", 0) * 100
b2 = M5_HMV_RES["pay_hits"].get("5", 0) * 100
b3 = M5_HMV_RES["pay_hits"].get("3", 0) * 100
print(f"P(bar1_pure) = {b1:.4f}%")
print(f"P(bar2_pure) = {b2:.4f}%")
print(f"P(bar3_pure) = {b3:.4f}%")
print(f"b1 - b2 = {b1-b2:+.4f}pp  (verify HIERARCHY_TIED_TOL = 0.10pp)")
print(f"b2 - b3 = {b2-b3:+.4f}pp")
print(f"strict P(b1) > P(b2)?  {b1 > b2}  (margin {b1-b2:+.4f}pp)")

# Compare with M2_LC
m2_b1 = M2_RES["pay_hits"].get("7", 0) * 100
m2_b2 = M2_RES["pay_hits"].get("5", 0) * 100
m2_b3 = M2_RES["pay_hits"].get("3", 0) * 100
print(f"\nM2_LC reference:")
print(f"M2 P(bar1) = {m2_b1:.4f}%, P(bar2) = {m2_b2:.4f}%, P(bar3) = {m2_b3:.4f}%")
print(f"M2 b1 - b2 = {m2_b1 - m2_b2:+.4f}pp (strict pyramid?)")


# =============================================================================
# Section D: bar1 family share-of-base (Q2 alive/cosmetic)
# =============================================================================
print("\n--- bar1 share alive vs cosmetic (Q2) ---")
b1_share_m5 = M5_HMV_RES["family_share_pct"]["bar1"]
b1_pp_m5 = M5_HMV_RES["family_pp"]["bar1"]
b1_share_m2 = M2_RES["family_share_pct"]["bar1"]
b1_pp_m2 = M2_RES["family_pp"]["bar1"]
print(f"M2_LC bar1 share-of-base: {b1_share_m2:.2f}%  (absolute {b1_pp_m2:.2f}pp)")
print(f"M5_HMV bar1 share-of-base: {b1_share_m5:.2f}%  (absolute {b1_pp_m5:.2f}pp)")
print(f"share delta: {b1_share_m5 - b1_share_m2:+.2f}pp (M5 lower? {b1_share_m5 < b1_share_m2})")
print(f"alive criteria ('>=1%'): bar1_share={b1_share_m5:.2f}% "
      f"{'ALIVE' if b1_share_m5 >= 1.0 else 'COSMETIC'}")

# bar1_pure P(b1)
print(f"\nbar1_pure (3 1bar on payline) P: {b1:.4f}%  "
      f"(1 in {100/b1:.0f} if b1>0)")
print(f"bar1 family TOTAL P_hit (incl wild-boosted variants): "
      f"{M5_HMV_RES['pay_hits'].get('7', 0)*100:.4f}%")


# =============================================================================
# Section E: Family share — does anything else dominate?
# =============================================================================
print("\n--- Family share-of-base (Q11 dominance) ---")
print(f"{'family':14s}  {'M2 share':>10s}  {'M5 share':>10s}  {'delta':>10s}")
for fam in sorted(M5_HMV_RES["family_share_pct"],
                  key=lambda f: -M5_HMV_RES["family_share_pct"][f]):
    m5_sh = M5_HMV_RES["family_share_pct"][fam]
    m2_sh = M2_RES["family_share_pct"].get(fam, 0)
    print(f"  {fam:12s}  {m2_sh:>9.2f}%  {m5_sh:>9.2f}%  {m5_sh - m2_sh:>+9.2f}pp")

# Top family share for M5
max_fam = max(M5_HMV_RES["family_share_pct"],
              key=lambda f: M5_HMV_RES["family_share_pct"][f])
print(f"M5 top family: {max_fam} at {M5_HMV_RES['family_share_pct'][max_fam]:.2f}%")


# =============================================================================
# Section F: Cherry impact on low-mult bucket (Q7)
# =============================================================================
print("\n--- Cherry lift Q7: 'shift higher' or 'spread out'? ---")
print(f"{'bucket':14s}  {'M2 pp':>9s}  {'M5 pp':>9s}  {'delta':>9s}")
for tier in ("1x_le1", "ge2_lt5", "ge5_lt10", "ge10_lt20", "ge20_lt30",
             "ge30_lt50", "ge50_lt100", "ge100_lt200", "ge200_lt500"):
    cur = M5_HMV_DECOMP["tier_pp"].get(tier, 0)
    m2v = M2_DECOMP["tier_pp"].get(tier, 0)
    print(f"  {tier:12s}  {m2v:>8.3f}  {cur:>8.3f}  {cur-m2v:>+8.3f}")

# 1x bucket grew by +1.75 (cherry1 lift); is this offset by ge30 growth?
low_delta = (M5_HMV_DECOMP["tier_pp"]["1x_le1"]
             + M5_HMV_DECOMP["tier_pp"]["ge2_lt5"]
             + M5_HMV_DECOMP["tier_pp"]["ge5_lt10"]) - (
    M2_DECOMP["tier_pp"]["1x_le1"]
    + M2_DECOMP["tier_pp"]["ge2_lt5"]
    + M2_DECOMP["tier_pp"]["ge5_lt10"]
)
high_delta = (M5_HMV_DECOMP["tier_pp"]["ge30_lt50"]
              + M5_HMV_DECOMP["tier_pp"]["ge50_lt100"]
              + M5_HMV_DECOMP["tier_pp"]["ge100_lt200"]
              + M5_HMV_DECOMP["tier_pp"]["ge200_lt500"]) - (
    M2_DECOMP["tier_pp"]["ge30_lt50"]
    + M2_DECOMP["tier_pp"]["ge50_lt100"]
    + M2_DECOMP["tier_pp"]["ge100_lt200"]
    + M2_DECOMP["tier_pp"]["ge200_lt500"]
)
print(f"\nSum delta low tier (1x + 2-5 + 5-10): {low_delta:+.3f}pp")
print(f"Sum delta high tier (>=30x): {high_delta:+.3f}pp")
print(f"Direction: {'High > Low (shift higher)' if high_delta > abs(low_delta) else 'Mixed / spread'}")


# =============================================================================
# Section G: Integer-rounding sensitivity (Q5)
# =============================================================================
print("\n--- Integer-rounded engine realization (Q5) ---")
print(f"{'scale':>6s}  {'m2 hit':>9s}  {'m5 hit':>9s}  {'hit diff':>9s}  "
      f"{'m2 trig':>9s}  {'m5 trig':>9s}  {'trig diff':>11s}  LUCKY-MONO?")
for scale in (100, 500, 1000, 2000, 5000, 10000):
    m2_int = marginals_to_int_weights(M2_MARGINALS, scale)
    m5_int = marginals_to_int_weights(M5_HMV_MARGINALS, scale)
    m2_res = evaluate(m2_int, 2)
    m5_res = evaluate(m5_int, 5)
    h_diff = m5_res["base_hit_pct"] - m2_res["base_hit_pct"]
    t_diff = m5_res["trigger_pct"] - m2_res["trigger_pct"]
    hit_pass = h_diff >= -1e-9
    trig_pass = t_diff >= -1e-9
    print(f"  {scale:>5d}  {m2_res['base_hit_pct']:>8.4f}%  "
          f"{m5_res['base_hit_pct']:>8.4f}%  {h_diff:>+8.4f}pp  "
          f"{m2_res['trigger_pct']:>8.4f}%  {m5_res['trigger_pct']:>8.4f}%  "
          f"{t_diff:>+10.4f}pp  hit={'PASS' if hit_pass else 'FAIL'} "
          f"trig={'PASS' if trig_pass else 'FAIL'}")


# =============================================================================
# Section H: Total RTP ceiling risk (Q6)
# =============================================================================
print("\n--- RTP ceiling risk (Q6) ---")
print(f"Analytic Total RTP: {M5_HMV_RES['total_rtp_pct']:.3f}pp")
print(f"verify.py m5 RTP band: [480.0, 520.0]  (margin to ceiling: "
      f"{520.0 - M5_HMV_RES['total_rtp_pct']:+.2f}pp)")
print(f"D's task-target band: [491.5, 508.5]  (margin: "
      f"{508.5 - M5_HMV_RES['total_rtp_pct']:+.2f}pp)")

# SE for 1M paid spins (from prior critique v14c)
SE_base_per_spin = 4.62 * 0.987  # CV*mu approximation
SE_feat_per_spin_var = 187.9     # from prior critique v14c
SE_total_per_spin_var = (SE_base_per_spin ** 2 + SE_feat_per_spin_var)
N_PROD = 1_000_000
SE_pp_1M = (SE_total_per_spin_var / N_PROD) ** 0.5 * 100.0
print(f"\nSE for 1M paid spins: ~{SE_pp_1M:.2f}pp")
print(f"With engine drift +/-0.5pp (M1 v14 observed), upper bound: "
      f"{M5_HMV_RES['total_rtp_pct'] + 0.5 + SE_pp_1M:.2f}pp")
print(f"Margin from 520 ceiling assuming +0.5pp drift +1*SE: "
      f"{520.0 - (M5_HMV_RES['total_rtp_pct'] + 0.5 + SE_pp_1M):+.2f}pp")


# =============================================================================
# Section I: Cross-mode coherence vs shipped v9
# =============================================================================
print("\n--- Cross-mode coherence (Section 4 / Q9 cosmic noise) ---")
print(f"Feature RTP m5: {M5_HMV_RES['feature_rtp_pct']:.2f}pp")
print(f"Base RTP m5: {M5_HMV_RES['base_rtp_pct']:.2f}pp")
print(f"Feature/Total ratio: "
      f"{M5_HMV_RES['feature_rtp_pct']/M5_HMV_RES['total_rtp_pct']*100:.1f}%")
print(f"Base-game high-mult delta vs m2 (combo view): "
      f"{(M5_HMV_DECOMP['ge_30_pp'] - M2_DECOMP['ge_30_pp']):+.2f}pp absolute")
print(f"= base lift / total m5 ratio: "
      f"{(M5_HMV_DECOMP['ge_30_pp'] - M2_DECOMP['ge_30_pp'])/M5_HMV_RES['total_rtp_pct']*100:.2f}% of total m5 RTP")
print(f"\n=> base shape difference accounts for ~"
      f"{(M5_HMV_DECOMP['ge_30_pp'] - M2_DECOMP['ge_30_pp'])/M5_HMV_RES['total_rtp_pct']*100:.2f}% of total")
print(f"   while feature accounts for ~80% of total m5 RTP")
print(f"   → cosmic noise check: is base shape diff distinguishable vs feature variance?")
