"""Independent metrics for v14c critique (Critic X).

Reproduces D's model + adds independent decompositions:
  1. bar_mixed P decomposition by tier-combination (per mode)
  2. Family share comparison cross-mode (m1, M2_LC, M5_LC+, shipped m2, shipped m5)
  3. LUCKY-MONO flip risk after integer rounding (scales 100, 1000, 10000)
  4. CV / SE math for m2 RTP
  5. P(R>=1000)/spin sanity m5 vs m2
  6. Per-family marginal lift ratios cross-mode
  7. Reel asymmetry direction comparison

No production files modified.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

M15 = ROOT / "slot_designer" / "machines" / "M15"
engine, spec = load_engine(
    M15 / "spec.json",
    M15 / "weights" / "mode_1" / "weights.json",
    strips_path=M15 / "reel_strips.json",
)
EV = engine.evaluator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stop_sym(stop):
    """Return symbol name from a strip stop (handles str or dict shape)."""
    if isinstance(stop, str):
        return stop
    return stop["symbol"]


def marginals_from_strip_weights(strip_path, weights_path):
    strips_obj = json.loads(strip_path.read_text(encoding="utf-8"))
    strips = strips_obj["reels"]
    weights_obj = json.loads(weights_path.read_text(encoding="utf-8"))
    weights = weights_obj["weights"]
    out = []
    for r_idx, strip in enumerate(strips):
        w = weights[r_idx]
        total = sum(w)
        by_sym = {}
        for stop, wt in zip(strip, w):
            sym = _stop_sym(stop)
            by_sym[sym] = by_sym.get(sym, 0.0) + wt / total
        out.append(by_sym)
    return out


PAY_FAM = {"9": "cherry1", "71": "cherry2", "4": "cherry3", "1": "wild_pure",
           "2": "high7_wild", "21": "high7_pure", "3": "bar3", "5": "bar2",
           "7": "bar1", "8": "bar_mixed"}


def compute_shares(margs):
    prof = analytic_profile_from_marginals(EV, margs)
    base = prof["rtp_pct"]
    fam_pp = {}
    for pid, rtp in prof["pay_rtp"].items():
        fam = PAY_FAM.get(pid)
        if not fam:
            continue
        fam_pp[fam] = fam_pp.get(fam, 0) + rtp * 100
    high7 = fam_pp.get("high7_wild", 0) + fam_pp.get("high7_pure", 0)
    fam_pp["high7"] = high7
    shares = {fam: (pp / base * 100 if base > 0 else 0) for fam, pp in fam_pp.items()}
    return base, fam_pp, shares, prof


def fmt_marg(margs):
    syms = ["blank", "cherry", "1bar", "2bar", "3bar", "high7", "doublediamond", "topdollar", "jackpot"]
    lines = []
    for r, m in enumerate(margs):
        parts = [f"{s}={m.get(s, 0)*100:.3f}" for s in syms if s in m]
        lines.append("  R{}: ".format(r+1) + " ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Marginals
# ---------------------------------------------------------------------------

STRIPS = M15 / "reel_strips.json"
W_M1 = M15 / "weights" / "mode_1" / "weights.json"
W_M2 = M15 / "weights" / "mode_2" / "weights.json"
W_M5 = M15 / "weights" / "mode_5" / "weights.json"
W_M7 = M15 / "weights" / "mode_7" / "weights.json"

M1_SHIP = marginals_from_strip_weights(STRIPS, W_M1)
M2_SHIP = marginals_from_strip_weights(STRIPS, W_M2)
M5_SHIP = marginals_from_strip_weights(STRIPS, W_M5)
M7_SHIP = marginals_from_strip_weights(STRIPS, W_M7)

# D's proposed M2_LC marginals (from design script, table 2.2)
M2_LC = [
    {"blank": 0.27528, "cherry": 0.0640, "1bar": 0.21805, "2bar": 0.17798, "3bar": 0.11146,
     "high7": 0.12168, "doublediamond": 0.02755, "jackpot": 0.004},
    {"blank": 0.24777, "cherry": 0.0630, "1bar": 0.23774, "2bar": 0.19483, "3bar": 0.10498,
     "high7": 0.12248, "doublediamond": 0.02520, "jackpot": 0.004},
    {"blank": 0.23190, "cherry": 0.0500, "1bar": 0.24282, "2bar": 0.19782, "3bar": 0.09882,
     "high7": 0.12220, "doublediamond": 0.02040, "topdollar": 0.03304, "jackpot": 0.003},
]
M5_LC = [
    {"blank": 0.28639, "cherry": 0.0640, "1bar": 0.21805, "2bar": 0.17798, "3bar": 0.11146,
     "high7": 0.11195, "doublediamond": 0.02617, "jackpot": 0.004},
    {"blank": 0.25505, "cherry": 0.0630, "1bar": 0.23774, "2bar": 0.19483, "3bar": 0.10498,
     "high7": 0.11268, "doublediamond": 0.02772, "jackpot": 0.004},
    {"blank": 0.23964, "cherry": 0.0500, "1bar": 0.24282, "2bar": 0.19782, "3bar": 0.09882,
     "high7": 0.11242, "doublediamond": 0.02244, "topdollar": 0.03304, "jackpot": 0.003},
]

print("=" * 78)
print("Section A — Shipped v9 marginals re-derived from production weights")
print("=" * 78)
print("\nM1 SHIPPED:")
print(fmt_marg(M1_SHIP))
print("\nM2 SHIPPED:")
print(fmt_marg(M2_SHIP))
print("\nM5 SHIPPED:")
print(fmt_marg(M5_SHIP))
print("\nM7 SHIPPED:")
print(fmt_marg(M7_SHIP))


# ---------------------------------------------------------------------------
# 1. Bar-mixed tier-combo decomposition
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Section B — bar_mixed P decomposition by tier combination")
print("=" * 78)

def bar_mixed_tier_combos(margs):
    bars = ["1bar", "2bar", "3bar"]
    combos = []
    for b1 in bars:
        for b2 in bars:
            for b3 in bars:
                p = margs[0].get(b1, 0) * margs[1].get(b2, 0) * margs[2].get(b3, 0)
                strict_same = (b1 == b2 == b3)
                combos.append((b1, b2, b3, p, strict_same))
    # Classify NON-strict-same:
    classes = {"112_majority": [], "122_majority": [], "133_majority": [],
               "diverse_3tier": [], "strict_same_excluded": []}
    for c in combos:
        b1, b2, b3, p, strict = c
        if strict:
            classes["strict_same_excluded"].append(c)
            continue
        cnt = {b: [b1, b2, b3].count(b) for b in bars}
        if max(cnt.values()) == 1:
            classes["diverse_3tier"].append(c)
        else:
            top = max(cnt, key=cnt.get)
            if top == "1bar":
                classes["112_majority"].append(c)
            elif top == "2bar":
                classes["122_majority"].append(c)
            else:
                classes["133_majority"].append(c)
    total_mixed = sum(p for c in combos if not c[4] for *_, p, _ in [c])
    total_mixed = sum(c[3] for c in combos if not c[4])
    return total_mixed, classes


for label, m in [("m1 SHIPPED", M1_SHIP), ("m2 SHIPPED", M2_SHIP),
                  ("M2_LC", M2_LC), ("M5_LC+", M5_LC), ("m5 SHIPPED", M5_SHIP)]:
    total, cls = bar_mixed_tier_combos(m)
    print(f"\n{label} bar_mixed P total = {total*100:.4f}%")
    print(f"  112-majority (1bar dom): P={sum(c[3] for c in cls['112_majority'])*100:.4f}%")
    print(f"  122-majority (2bar dom): P={sum(c[3] for c in cls['122_majority'])*100:.4f}%")
    print(f"  133-majority (3bar dom): P={sum(c[3] for c in cls['133_majority'])*100:.4f}%")
    print(f"  diverse-3tier (1+2+3):   P={sum(c[3] for c in cls['diverse_3tier'])*100:.4f}%")


# ---------------------------------------------------------------------------
# 2. Cross-mode family share comparison
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Section C — Family share comparison (cross-mode)")
print("=" * 78)

m1_b, m1_pp, m1_sh, m1_prof = compute_shares(M1_SHIP)
m2lc_b, m2lc_pp, m2lc_sh, m2lc_prof = compute_shares(M2_LC)
m5lc_b, m5lc_pp, m5lc_sh, m5lc_prof = compute_shares(M5_LC)
m2s_b, m2s_pp, m2s_sh, m2s_prof = compute_shares(M2_SHIP)
m5s_b, m5s_pp, m5s_sh, m5s_prof = compute_shares(M5_SHIP)

print(f"\nBase RTP pp:")
print(f"  m1 SHIPPED: {m1_b:.2f}  M2_LC: {m2lc_b:.2f}  M5_LC+: {m5lc_b:.2f}")
print(f"  m2 SHIPPED: {m2s_b:.2f}  m5 SHIPPED: {m5s_b:.2f}")

fams = ["bar_mixed", "bar1", "bar2", "bar3", "cherry1", "cherry2", "cherry3",
        "high7", "high7_wild", "high7_pure", "wild_pure"]
print(f"\nFamily share-of-base (%):")
print(f"  {'family':<14} {'m1':>8} {'M2_LC':>8} {'M5_LC+':>8} {'m2_ship':>8} {'m5_ship':>8}")
for fam in fams:
    print(f"  {fam:<14} {m1_sh.get(fam, 0):>8.2f} {m2lc_sh.get(fam, 0):>8.2f} "
          f"{m5lc_sh.get(fam, 0):>8.2f} {m2s_sh.get(fam, 0):>8.2f} {m5s_sh.get(fam, 0):>8.2f}")

print(f"\nFamily absolute RTP pp:")
print(f"  {'family':<14} {'m1':>8} {'M2_LC':>8} {'M5_LC+':>8} {'m2_ship':>8} {'m5_ship':>8}")
for fam in fams:
    print(f"  {fam:<14} {m1_pp.get(fam, 0):>8.3f} {m2lc_pp.get(fam, 0):>8.3f} "
          f"{m5lc_pp.get(fam, 0):>8.3f} {m2s_pp.get(fam, 0):>8.3f} {m5s_pp.get(fam, 0):>8.3f}")

print(f"\nTop 3 families per mode (excl high7 subtotals, sorted by share):")
for label, sh in [("m1 SHIPPED", m1_sh), ("M2_LC", m2lc_sh), ("M5_LC+", m5lc_sh),
                   ("m2 SHIPPED", m2s_sh), ("m5 SHIPPED", m5s_sh)]:
    sorted_sh = sorted(((f, s) for f, s in sh.items()
                        if f not in ("high7_wild", "high7_pure")),
                       key=lambda x: -x[1])
    print(f"  {label:<14}: " + ", ".join(f"{f}({s:.1f})" for f, s in sorted_sh[:3]))


# ---------------------------------------------------------------------------
# 3. Cross-mode family marginal lift ratios
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Section D — Family marginal lift ratios (m2/m1, m5/m2)")
print("=" * 78)

def sum_marg(margs, fam):
    return sum(m.get(fam, 0) for m in margs)


fam_groups = ["cherry", "1bar", "2bar", "3bar", "high7", "doublediamond", "topdollar", "jackpot", "blank"]
print(f"  {'family':<14} {'m1 sum':>10} {'M2_LC sum':>10} {'M2/M1':>8} {'M5_LC sum':>10} {'M5/M2':>8}")
for fam in fam_groups:
    a = sum_marg(M1_SHIP, fam)
    b = sum_marg(M2_LC, fam)
    c = sum_marg(M5_LC, fam)
    r21 = b/a if a else 0
    r52 = c/b if b else 0
    print(f"  {fam:<14} {a*100:>10.4f} {b*100:>10.4f} {r21:>8.3f} {c*100:>10.4f} {r52:>8.3f}")


# ---------------------------------------------------------------------------
# 4. Integer rounding flip risk
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Section E — LUCKY-MONO flip risk under integer rounding")
print("=" * 78)

strips_obj = json.loads(STRIPS.read_text(encoding="utf-8"))
strips = strips_obj["reels"]


def marg_to_int_weights(strip, marg_dict, scale):
    counts = {}
    for stop in strip:
        s = _stop_sym(stop)
        counts[s] = counts.get(s, 0) + 1
    weights = []
    for stop in strip:
        s = _stop_sym(stop)
        c = counts[s]
        m = marg_dict.get(s, 0)
        w = max(1, round(m * scale / c))
        weights.append(w)
    return weights


def realize_with_int(margs, scale):
    new_margs = []
    for r_idx, strip in enumerate(strips):
        w = marg_to_int_weights(strip, margs[r_idx], scale=scale)
        total = sum(w)
        by_sym = {}
        for stop, wt in zip(strip, w):
            s = _stop_sym(stop)
            by_sym[s] = by_sym.get(s, 0) + wt / total
        new_margs.append(by_sym)
    return new_margs


print(f"\nm2 realized RTP / hit / trigger by scale:")
for scale in [100, 500, 1000, 2000, 5000, 10000]:
    r = realize_with_int(M2_LC, scale)
    prof = analytic_profile_from_marginals(EV, r)
    print(f"  scale={scale:>6}: base RTP={prof['rtp_pct']:.3f}pp  hit={prof['hit_rate']*100:.4f}%  trig={r[2].get('topdollar', 0)*100:.4f}%")

print(f"\nm5 realized RTP / hit / trigger by scale:")
for scale in [100, 500, 1000, 2000, 5000, 10000]:
    r = realize_with_int(M5_LC, scale)
    prof = analytic_profile_from_marginals(EV, r)
    print(f"  scale={scale:>6}: base RTP={prof['rtp_pct']:.3f}pp  hit={prof['hit_rate']*100:.4f}%  trig={r[2].get('topdollar', 0)*100:.4f}%")

print(f"\nLUCKY-MONO hit (m5 hit >= m2 hit):")
for scale in [100, 500, 1000, 2000, 5000, 10000]:
    r2 = realize_with_int(M2_LC, scale)
    r5 = realize_with_int(M5_LC, scale)
    p2 = analytic_profile_from_marginals(EV, r2)
    p5 = analytic_profile_from_marginals(EV, r5)
    diff_pp = (p5['hit_rate'] - p2['hit_rate']) * 100
    flag = "PASS" if diff_pp >= 0 else "FAIL"
    print(f"  scale={scale:>6}: m5 hit={p5['hit_rate']*100:.4f}%  m2 hit={p2['hit_rate']*100:.4f}%  diff={diff_pp:+.4f}pp  {flag}")

print(f"\nLUCKY-MONO trigger (m5 trig >= m2 trig):")
for scale in [100, 500, 1000, 2000, 5000, 10000]:
    r2 = realize_with_int(M2_LC, scale)
    r5 = realize_with_int(M5_LC, scale)
    t2 = r2[2].get('topdollar', 0)
    t5 = r5[2].get('topdollar', 0)
    diff_pp = (t5 - t2) * 100
    flag = "PASS" if diff_pp >= 0 else "FAIL"
    print(f"  scale={scale:>6}: m5 trig={t5*100:.4f}%  m2 trig={t2*100:.4f}%  diff={diff_pp:+.4f}pp  {flag}")

print(f"\nTOP-JACKPOT-CADENCE m5/m2 wild_pure ratio (must >= 1.1):")
for scale in [100, 500, 1000, 2000, 5000, 10000]:
    r2 = realize_with_int(M2_LC, scale)
    r5 = realize_with_int(M5_LC, scale)
    pw2 = r2[0].get('doublediamond', 0) * r2[1].get('doublediamond', 0) * r2[2].get('doublediamond', 0)
    pw5 = r5[0].get('doublediamond', 0) * r5[1].get('doublediamond', 0) * r5[2].get('doublediamond', 0)
    ratio = pw5/pw2 if pw2 else 0
    flag = "PASS" if ratio >= 1.1 else "FAIL"
    print(f"  scale={scale:>6}: m5/m2 wild_pure={ratio:.4f}  {flag}")

# ---------------------------------------------------------------------------
# 5. SE math for m2 RTP
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Section F — m2 SE math")
print("=" * 78)
m2_base_rtp = m2lc_prof["rtp_pct"]
m2_base_cv = m2lc_prof["cv"]
m2_trigger = M2_LC[2]["topdollar"]

W_M2_data = json.loads(W_M2.read_text(encoding="utf-8"))
fp2 = W_M2_data["feature_params"]
dist2 = _round_payout_distribution(
    tuple(fp2["x_count_weights"]), tuple(fp2["y_count_weights"]),
    tuple(fp2["x_value_weights"]), tuple(fp2["y_value_weights"]))
accept_thr2 = fp2["accept_threshold"]
p_accept2 = sum(p for r, p in dist2 if r >= accept_thr2)
A2 = sum(r * p for r, p in dist2 if r >= accept_thr2) / p_accept2
U2 = sum(r * p for r, p in dist2)
ev2 = 0.0
streak2 = 1.0 - p_accept2
for round_idx in range(1, fp2["max_rounds"]):
    ev2 += (streak2 ** (round_idx - 1)) * p_accept2 * A2
ev2 += (streak2 ** (fp2["max_rounds"] - 1)) * U2

# Conditional Var(R | trigger triggered, mechanic complete)
# Approx: assume R_session has same shape as per-round dist (conservative under-estimate)
mean_R = ev2
# We approximate by per-round Var blown up by the 4-round geometric mechanic.
# A simple bound: assume Var(R | trigger) ≈ (CV_per_round_cond * EV_cond)^2 amplified.
mean_per_round_cond = A2
var_per_round_cond_acc = sum((r - A2) ** 2 * p / p_accept2 for r, p in dist2 if r >= accept_thr2)
cv_per_round_cond = var_per_round_cond_acc ** 0.5 / A2 if A2 else 0
# very approximate: Var_session ≈ Var_per_round / 1 round (since mechanic adds ~1 R typically)
var_R_given_trigger = var_per_round_cond_acc  # crude
print(f"m2 EV(R | trigger) = {ev2:.4f}")
print(f"m2 per-round cond mean A = {A2:.4f}  var = {var_per_round_cond_acc:.4f}  CV cond per round = {cv_per_round_cond:.4f}")

mu_base_per_spin = m2_base_rtp / 100
sigma_base = m2_base_cv * mu_base_per_spin
var_base = sigma_base ** 2

var_feat_per_spin = m2_trigger * (var_R_given_trigger + ev2**2) - (m2_trigger * ev2) ** 2
print(f"\nVar(base) per spin: {var_base:.4f}")
print(f"Var(feature) per spin: {var_feat_per_spin:.4f}")
total_var = var_base + var_feat_per_spin
print(f"Var(total) per spin: {total_var:.4f}")

import math
SE_1M = math.sqrt(total_var / 1e6) * 100
SE_100k = math.sqrt(total_var / 1e5) * 100
SE_10k = math.sqrt(total_var / 1e4) * 100
print(f"\nSE on  10k spins: {SE_10k:.3f}pp")
print(f"SE on 100k spins: {SE_100k:.3f}pp")
print(f"SE on   1M spins: {SE_1M:.3f}pp")

m2_total = m2_base_rtp + m2_trigger * ev2 * 100
margin = m2_total - 290
print(f"\nm2 total RTP (analytic): {m2_total:.3f}pp")
print(f"margin to 290 floor: {margin:.2f}pp")
print(f"  1M σ-buffer: {margin / SE_1M:.2f}σ")
print(f"  100k σ-buffer: {margin / SE_100k:.2f}σ")

# ---------------------------------------------------------------------------
# 6. P(R>=1000)/spin m5 vs m2
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Section G — P(R>=1000) per spin (m5 lower than m2 anomaly)")
print("=" * 78)

W_M5_data = json.loads(W_M5.read_text(encoding="utf-8"))
fp5 = W_M5_data["feature_params"]
dist5 = _round_payout_distribution(
    tuple(fp5["x_count_weights"]), tuple(fp5["y_count_weights"]),
    tuple(fp5["x_value_weights"]), tuple(fp5["y_value_weights"]))

p_r1000_m2_per_trig = sum(p for r, p in dist2 if r >= 1000)
p_r1000_m5_per_trig = sum(p for r, p in dist5 if r >= 1000)
p_r500_m2 = sum(p for r, p in dist2 if r >= 500)
p_r500_m5 = sum(p for r, p in dist5 if r >= 500)
p_r200_m2 = sum(p for r, p in dist2 if r >= 200)
p_r200_m5 = sum(p for r, p in dist5 if r >= 200)
m5_trigger = M5_LC[2]["topdollar"]

print(f"\nFeature x_value_weights (heavier right tail = more high-mult outcomes):")
print(f"  m2: {fp2['x_value_weights']}")
print(f"  m5: {fp5['x_value_weights']}")
print(f"  y_count_weights:")
print(f"  m2: {fp2['y_count_weights']}  (more 1-y heavy)")
print(f"  m5: {fp5['y_count_weights']}  (more 3-y heavy)")

print(f"\nPer-trigger P(R>=X):")
print(f"  P(R>=200):   m2 {p_r200_m2:.4f}  m5 {p_r200_m5:.4f}  ratio={p_r200_m5/p_r200_m2:.3f}")
print(f"  P(R>=500):   m2 {p_r500_m2:.4e}  m5 {p_r500_m5:.4e}  ratio={p_r500_m5/p_r500_m2:.3f}")
print(f"  P(R>=1000):  m2 {p_r1000_m2_per_trig:.4e}  m5 {p_r1000_m5_per_trig:.4e}  ratio={p_r1000_m5_per_trig/p_r1000_m2_per_trig if p_r1000_m2_per_trig else 0:.3f}")

print(f"\nPer-spin (trigger × P):")
print(f"  P(R>=200)/spin:  m2 {m2_trigger*p_r200_m2:.3e}  m5 {m5_trigger*p_r200_m5:.3e}")
print(f"  P(R>=1000)/spin: m2 {m2_trigger*p_r1000_m2_per_trig:.3e}  m5 {m5_trigger*p_r1000_m5_per_trig:.3e}")

# Show feature payout distribution shape sample
print(f"\nm2 feature dist (R, P): top 10 by P")
top10_m2 = sorted(dist2, key=lambda x: -x[1])[:10]
for r, p in top10_m2:
    print(f"  R={r:>6}  P={p:.4e}")

print(f"\nm5 feature dist (R, P): top 10 by P")
top10_m5 = sorted(dist5, key=lambda x: -x[1])[:10]
for r, p in top10_m5:
    print(f"  R={r:>6}  P={p:.4e}")

# Tail behavior
print(f"\nTail of dist (R, P) for high R only:")
print(f"  m2 (R>=200):")
for r, p in sorted(((r, p) for r, p in dist2 if r >= 200)):
    print(f"    R={r:>6}  P={p:.4e}")
print(f"  m5 (R>=200):")
for r, p in sorted(((r, p) for r, p in dist5 if r >= 200)):
    print(f"    R={r:>6}  P={p:.4e}")


# ---------------------------------------------------------------------------
# 7. Reel asymmetry direction
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Section H — Reel asymmetry direction (R1 vs R3 blank)")
print("=" * 78)

print(f"\n  {'mode':<20} {'R1 blank':>10} {'R2 blank':>10} {'R3 blank':>10} {'R1-R3':>8}")
for label, m in [("m1 SHIPPED", M1_SHIP), ("m2 SHIPPED", M2_SHIP), ("m5 SHIPPED", M5_SHIP),
                  ("m7 SHIPPED", M7_SHIP), ("M2_LC (D)", M2_LC), ("M5_LC+ (D)", M5_LC)]:
    r1, r2, r3 = (x["blank"] for x in m)
    print(f"  {label:<20} {r1*100:>10.3f} {r2*100:>10.3f} {r3*100:>10.3f} {(r1-r3)*100:>+8.3f}")


# ---------------------------------------------------------------------------
# 8. Per-pay-id frequency cross-mode summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Section I — Per-pay-id cross-mode frequency table")
print("=" * 78)

print(f"\n  {'pid':<4} {'family':<12} {'m1 P%':>10} {'m2_ship':>10} {'M2_LC':>10} {'m5_ship':>10} {'M5_LC+':>10}")
for pid in ["9", "71", "4", "1", "2", "21", "3", "5", "7", "8"]:
    fam = PAY_FAM.get(pid, "?")
    m1p = m1_prof["pay_hits"].get(pid, 0) * 100
    m2sp = m2s_prof["pay_hits"].get(pid, 0) * 100
    m2lp = m2lc_prof["pay_hits"].get(pid, 0) * 100
    m5sp = m5s_prof["pay_hits"].get(pid, 0) * 100
    m5lp = m5lc_prof["pay_hits"].get(pid, 0) * 100
    print(f"  {pid:<4} {fam:<12} {m1p:>10.4f} {m2sp:>10.4f} {m2lp:>10.4f} {m5sp:>10.4f} {m5lp:>10.4f}")


# ---------------------------------------------------------------------------
# 9. Mode 5 "multiplier shift higher" check: compare base RTP mass by mult
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Section J — m5 base 'multiplier shift higher' verification")
print("=" * 78)
# Sum base RTP contribution by multiplier bucket
def base_rtp_by_mult(prof, pay_mults):
    by_mult = {}
    for pid, rtp in prof["pay_rtp"].items():
        mult_str = pay_mults.get(pid, "")
        by_mult[mult_str] = by_mult.get(mult_str, 0) + rtp * 100
    return by_mult


PAY_MULT = {
    "9": "1x", "71": "5x", "4": "15x",
    "8": "2/4x", "7": "5/10/20x", "5": "10/20/40x", "3": "20/40/80x",
    "21": "30x", "2": "30/60/120x", "1": "200x"
}

m2lc_mult = base_rtp_by_mult(m2lc_prof, PAY_MULT)
m5lc_mult = base_rtp_by_mult(m5lc_prof, PAY_MULT)

# Group by "high mult" (>=30x) vs low mult (<30x)
def mult_class(label):
    if label == "1x":
        return "1x (cherry1)"
    if "200" in label:
        return "200x"
    if "120" in label or "80" in label or "60" in label or "40" in label:
        return "40-120x"
    if "30" in label:
        return "30x"
    if "15" in label:
        return "15x"
    return "<15x"

m2_grouped = {}
m5_grouped = {}
for k, v in m2lc_mult.items():
    g = mult_class(k)
    m2_grouped[g] = m2_grouped.get(g, 0) + v
for k, v in m5lc_mult.items():
    g = mult_class(k)
    m5_grouped[g] = m5_grouped.get(g, 0) + v

print(f"\nBase RTP contribution by max-multiplier bucket:")
print(f"  {'bucket':<12} {'M2_LC pp':>10} {'M5_LC+ pp':>10} {'delta':>10}")
for g in ["1x (cherry1)", "<15x", "15x", "30x", "40-120x", "200x"]:
    a = m2_grouped.get(g, 0)
    b = m5_grouped.get(g, 0)
    print(f"  {g:<12} {a:>10.3f} {b:>10.3f} {b-a:>+10.3f}")

# Compute proportion of base RTP coming from R>=30x mults (high-mult share)
high_mult_m2 = sum(v for k, v in m2_grouped.items() if k in ("30x", "40-120x", "200x"))
high_mult_m5 = sum(v for k, v in m5_grouped.items() if k in ("30x", "40-120x", "200x"))
print(f"\nHigh-mult (≥30x) base RTP:")
print(f"  M2_LC: {high_mult_m2:.3f}pp ({high_mult_m2/m2lc_b*100:.2f}% of base)")
print(f"  M5_LC+: {high_mult_m5:.3f}pp ({high_mult_m5/m5lc_b*100:.2f}% of base)")
print(f"  Delta: {high_mult_m5 - high_mult_m2:+.3f}pp absolute  /  {(high_mult_m5/m5lc_b - high_mult_m2/m2lc_b)*100:+.3f}pp share")

# Same comparison for shipped m2 vs shipped m5
m2s_mult = base_rtp_by_mult(m2s_prof, PAY_MULT)
m5s_mult = base_rtp_by_mult(m5s_prof, PAY_MULT)
m2s_grouped = {}
m5s_grouped = {}
for k, v in m2s_mult.items():
    g = mult_class(k)
    m2s_grouped[g] = m2s_grouped.get(g, 0) + v
for k, v in m5s_mult.items():
    g = mult_class(k)
    m5s_grouped[g] = m5s_grouped.get(g, 0) + v

high_mult_m2s = sum(v for k, v in m2s_grouped.items() if k in ("30x", "40-120x", "200x"))
high_mult_m5s = sum(v for k, v in m5s_grouped.items() if k in ("30x", "40-120x", "200x"))
print(f"\nShipped v9 comparison:")
print(f"  m2 SHIPPED: high-mult={high_mult_m2s:.3f}pp ({high_mult_m2s/m2s_b*100:.2f}% of base)")
print(f"  m5 SHIPPED: high-mult={high_mult_m5s:.3f}pp ({high_mult_m5s/m5s_b*100:.2f}% of base)")

print("\n" + "=" * 78)
print("END")
print("=" * 78)
