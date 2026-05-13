"""Inspect shipped v9 m5 marginals directly from production weights/strips."""
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
W_M5 = _M15 / "weights" / "mode_5" / "weights.json"

# Load shipped v9 m5 weights
weights = json.loads(W_M5.read_text(encoding="utf-8"))["weights"]
strips = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

# Compute per-reel marginals
margs = []
for r_idx in range(3):
    strip = strips[r_idx]
    w = weights[r_idx]
    assert len(strip) == len(w), f"len mismatch reel {r_idx}: {len(strip)} vs {len(w)}"
    total = sum(w)
    d = defaultdict(float)
    for sym, wt in zip(strip, w):
        d[sym] += wt / total
    margs.append(dict(d))

print("Shipped v9 m5 marginals (from production weights/strips):")
for r_idx, m in enumerate(margs):
    print(f"R{r_idx+1}: " + ", ".join(f"{k}={v*100:.3f}" for k, v in sorted(m.items())))

# Analytic profile
engine, _spec = load_engine(SPEC_PATH, W_M1, strips_path=STRIPS_PATH)
EV = engine.evaluator

prof = analytic_profile_from_marginals(EV, margs)
base_rtp = prof["rtp_pct"]
hit = prof["hit_rate"]
trig = margs[2].get("topdollar", 0.0)

# Feature stats
fp = json.loads(W_M5.read_text(encoding="utf-8"))["feature_params"]
dist = _round_payout_distribution(
    tuple(fp["x_count_weights"]),
    tuple(fp["y_count_weights"]),
    tuple(fp["x_value_weights"]),
    tuple(fp["y_value_weights"]),
)
accept_thr = fp["accept_threshold"]
p_accept = sum(p for r, p in dist if r >= accept_thr)
A = sum(r * p for r, p in dist if r >= accept_thr) / p_accept
U = sum(r * p for r, p in dist)
max_r = fp["max_rounds"]
reject_streak = 1.0 - p_accept
ev = 0.0
for round_idx in range(1, max_r):
    ev += (reject_streak ** (round_idx - 1)) * p_accept * A
ev += (reject_streak ** (max_r - 1)) * U

feat_rtp = trig * ev * 100.0
tot = base_rtp + feat_rtp

print(f"\nv9 m5 analytic profile:")
print(f"  Base RTP: {base_rtp:.3f}pp")
print(f"  Hit: {hit*100:.3f}%")
print(f"  Trigger: {trig*100:.4f}%")
print(f"  Feature EV: {ev:.2f}x")
print(f"  Feature RTP: {feat_rtp:.3f}pp")
print(f"  Total RTP: {tot:.3f}pp")

# Per-pay-id
print("\nPer-pay-id hits (P %) and RTP (pp):")
for pid in ("9", "71", "4", "1", "2", "21", "3", "5", "7", "8"):
    p = prof["pay_hits"].get(pid, 0)
    r = prof["pay_rtp"].get(pid, 0) * 100
    print(f"  pay_id {pid:<4} P={p*100:.4f}%  RTP={r:.3f}pp")

# Combo decomp
import itertools
PAY_FAM = {"9": "cherry1", "71": "cherry2", "4": "cherry3", "1": "wild_pure",
           "2": "high7_wild", "21": "high7_pure", "3": "bar3", "5": "bar2",
           "7": "bar1", "8": "bar_mixed"}

symbols_per_reel = [list(m.keys()) for m in margs]
combo_tier_pp = {
    "1x_le1": 0.0, "ge2_lt5": 0.0, "ge5_lt10": 0.0, "ge10_lt20": 0.0,
    "ge20_lt30": 0.0, "ge30_lt50": 0.0, "ge50_lt100": 0.0,
    "ge100_lt200": 0.0, "ge200_lt500": 0.0, "ge500": 0.0,
}
pid_rtp_pp = defaultdict(float)
fam_pp = defaultdict(float)
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
    fam_pp[PAY_FAM.get(str(result.pay_id), "?")] += rtp_contrib
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
ge30_combo = (combo_tier_pp["ge30_lt50"] + combo_tier_pp["ge50_lt100"]
              + combo_tier_pp["ge100_lt200"] + combo_tier_pp["ge200_lt500"]
              + combo_tier_pp["ge500"])

# Payid-anchored
pp = lambda k: pid_rtp_pp.get(k, 0.0)
payid_30_plus = pp("21") + pp("2") + pp("3") + pp("5") + pp("1")
payid_30_share = payid_30_plus / base_pp * 100.0 if base_pp > 0 else 0.0
ge30_combo_share = ge30_combo / base_pp * 100.0

print(f"\nCombo tier decomp:")
for tier, v in combo_tier_pp.items():
    print(f"  {tier:14s}: {v:.3f}pp")
print(f"\n≥30 share (combo): {ge30_combo_share:.2f}%")
print(f"≥30 share (payid): {payid_30_share:.2f}%")

print(f"\nFamily pp (sorted):")
for k, v in sorted(fam_pp.items(), key=lambda kv: -kv[1]):
    share = v / base_pp * 100.0 if base_pp > 0 else 0
    print(f"  {k:14s}: {v:.3f}pp ({share:.2f}% share)")
