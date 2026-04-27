"""Tune M37 mode weights — player-experience direct objective.

M37 = "100x Diamond" — Lightning-Link/Dragon-Link inspired classic 3-reel
with multiplier-tier wilds (mini/minor/major/grand) on R2.

Per ``project_slot_designer_axiom_experience_is_soul``: cost function
targets player experience red lines directly.

Brand signature = **Booster diamonds on R2** (mini/minor/major/grand).
Player perception: "this is the Diamond machine" comes from seeing
boosters frequently. Top jackpot path = (high7|wild, grand, high7|wild)
= 1000×.

Hard rules:
  - Paytable LOCKED (incl. reroll block on (wild, grand, wild))
  - Strip layout LOCKED (36 stops, blank/non-blank alternation, wild only
    on R1+R3, boosters only on R2)
  - Mode RTP: 1=95%, 7=85% (standard); 2=300%, 5=500% (lucky)
  - Mode 7 = mode 1 - 砍小奖派生:
    - high7 + booster + wild weights frozen to mode 1 (大奖 + brand 不动)
    - blank weight FLOORED ≥ mode 1 (else big-win density inflates → RTP UP not DOWN)
    - bar1/2/3/7bar weight ranges [mode 1 × 0.40, mode 1 × 0.85] (wide cut)
  - Mode 2: weight floors ≥ mode 1 for non-blank big-win/booster only
    + blank weight CEILED ≤ mode 1 (lucky must be denser hits)
    + bar weights CEILED ≤ mode 1 × 1.6 (prevent bar over-loading)
  - Mode 5: bar frozen = mode 2 (preserve hit rate via Bar density);
    big-win/booster floored ≥ mode 2 + grand floor (super-lucky monotonic);
    blank CEILED ≤ mode 2.

Parameterization (per mode):
  - R1 + R3: 7 families each (blank, wild, high7, 7bar, 3bar, 2bar, 1bar)
  - R2: 10 families (blank, high7, 7bar, 3bar, 2bar, 1bar, mini, minor, major, grand)
  - Total = 7 + 10 + 7 = 24 dims
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import (
    analytic_profile_from_marginals,
    structurally_reachable_buckets,
    multiplier_to_bucket,
)
from slot_designer.engine.loader import load_engine
from slot_designer.engine.evaluator import PaytableEvaluator
from slot_designer.engine.rules import RuleSet
from slot_designer.engine.symbol import SymbolRegistry
from slot_designer.tuner.cost import CostWeights, evaluate_cost
from slot_designer.tuner.layout import marginals_from_counts


SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
STRIPS_PATH = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"

# Symbols available per reel (per strip layout invariants)
SYMBOLS_BY_REEL = {
    0: ("blank", "wild", "high7", "7bar", "3bar", "2bar", "1bar"),
    1: ("blank", "high7", "7bar", "3bar", "2bar", "1bar", "mini", "minor", "major", "grand"),
    2: ("blank", "wild", "high7", "7bar", "3bar", "2bar", "1bar"),
}

# Big-win symbols (frozen for mode 7) — high7 (top regular), wild, all boosters
BIGWIN_SYMBOLS_R1 = ("wild", "high7")
BIGWIN_SYMBOLS_R2 = ("high7", "mini", "minor", "major", "grand")
BIGWIN_SYMBOLS_R3 = ("wild", "high7")

# Bar tier (略砍 in mode 7 with weight range)
BAR_SYMBOLS = ("1bar", "2bar", "3bar", "7bar")

# Per-family per-reel weight bounds. Each is integer >= 1.
WEIGHT_BOUNDS_STANDARD = {
    "blank":  (1, 50), "wild":  (1, 15),
    "high7":  (1, 30), "7bar":  (1, 30), "3bar":  (1, 30),
    "2bar":   (1, 30), "1bar":  (1, 50),
    "mini":   (1, 15), "minor": (1, 15), "major": (1, 15), "grand": (1, 5),
}
WEIGHT_BOUNDS_LUCKY = {
    "blank":  (1, 40), "wild":  (1, 25),
    "high7":  (1, 50), "7bar":  (1, 50), "3bar":  (1, 50),
    "2bar":   (1, 50), "1bar":  (1, 80),
    "mini":   (1, 25), "minor": (1, 25), "major": (1, 25), "grand": (1, 10),
}
WEIGHT_BOUNDS_BY_MODE = {1: WEIGHT_BOUNDS_STANDARD, 7: WEIGHT_BOUNDS_STANDARD,
                         2: WEIGHT_BOUNDS_LUCKY, 5: WEIGHT_BOUNDS_LUCKY}

# Per-mode experience targets
EXPERIENCE_TARGETS = {
    1: {
        "total_rtp_pct": 95.0, "total_rtp_tol_pp": 1.0,
        "rtp_weight": 25.0,
        "hit_rate_target": 0.16, "hit_rate_weight": 150.0,
        "wild_on_payline_band": (0.05, 0.16),
        "wild_signature_weight": 500.0,
        # Booster on R2 brand: visible but NOT dominant. 5-10% means
        # 1 booster every 10-20 spins on R2 payline.
        "booster_r2_band": (0.05, 0.10),
        "booster_signature_weight": 300.0,
        # grand alone (pay_id 8) was 1 in 633 → 16% RTP dominant. Cap to 1 in 2500.
        "pay_freq_caps": {"8": 0.0004},
        # 1000x top jackpot was 1 in 13k → too frequent. Cap to 1 in 60k.
        "top_jackpot_min_spins": 60000,
        "family_share_bands": {
            # of total RTP. Bar tier ~30-45%, high7 + booster_alone share rest.
            "high7":   (0.05, 0.25),
            "7bar":    (0.05, 0.25),
            "bar_tier": (0.20, 0.45),    # 1bar+2bar+3bar combined — tighter cap
            "booster_alone": (0.10, 0.30),  # pay_id 8/9 — push higher
            "wild_amplified": (0.0, 0.20),  # pay_id 102/103/104
        },
        "per_reel_blank_variance_strength": 15.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.005, "high7": 0.005,
            "7bar": 0.015, "3bar": 0.015, "2bar": 0.015, "1bar": 0.02,    # bars ≥1.5-2% on each reel
            "mini": 0.005, "minor": 0.005, "major": 0.005, "grand": 0.0015,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.07, "high7": 0.06,
            "7bar": 0.13, "3bar": 0.13, "2bar": 0.13, "1bar": 0.18,    # tighter bar caps
            "mini": 0.06, "minor": 0.05, "major": 0.03, "grand": 0.004,
        },
        "uniformity_ratio_cap": {"wild": 2.0, "high7": 2.0},
        "base_cv_target": 9.0,
    },
    7: {
        "total_rtp_pct": 85.0, "total_rtp_tol_pp": 2.0,
        "rtp_weight": 30.0,    # very strict for mode 7
        "hit_rate_target": 0.13, "hit_rate_weight": 80.0,
        "top_jackpot_min_spins": 70000,    # slightly relaxed vs m1 (60k); not overly frequent
        "pay_freq_caps": {"8": 0.0005},    # grand alone cap similar to m1
        "wild_on_payline_band": (0.03, 0.16),
        "booster_r2_band": (0.04, 0.10),
        "family_share_bands": {
            "high7":   (0.03, 0.25),
            "7bar":    (0.03, 0.25),
            "bar_tier": (0.10, 0.40),    # tighter cap (bars cut)
            "booster_alone": (0.10, 0.40),    # naturally rises when bars cut
            "wild_amplified": (0.0, 0.20),
        },
        "per_reel_blank_variance_strength": 5.0,    # M37 R2 = booster reel (more blank natural)
        "per_reel_density_lo_by_family": {
            "wild": 0.005, "high7": 0.005,
            "7bar": 0.005, "3bar": 0.005, "2bar": 0.005, "1bar": 0.005,
            "mini": 0.003, "minor": 0.003, "major": 0.003, "grand": 0.001,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.07, "high7": 0.06,    # match mode 1 (frozen weight, blank floored)
            "7bar": 0.12, "3bar": 0.12, "2bar": 0.12, "1bar": 0.16,    # tighter bar caps for cut
            "mini": 0.06, "minor": 0.05, "major": 0.03, "grand": 0.004,
        },
        "uniformity_ratio_cap": {"wild": 2.0, "high7": 3.0},
    },
    2: {
        "total_rtp_pct": 300.0, "total_rtp_tol_pp": 20.0,
        "rtp_weight": 8.0,
        "hit_rate_target": 0.23, "hit_rate_weight": 250.0,    # very strict
        "top_jackpot_min_spins": 25000,
        "pay_freq_caps": {"8": 0.0010},    # grand alone 1 in 1000 (3x m1)
        "wild_on_payline_band": (0.06, 0.18),
        "wild_signature_weight": 200.0,
        "booster_r2_band": (0.08, 0.16),
        "booster_signature_weight": 200.0,
        "family_share_bands": {
            "high7":   (0.05, 0.30),
            "7bar":    (0.03, 0.25),
            "bar_tier": (0.15, 0.45),    # bars naturally still dominant at 3x lucky
            "booster_alone": (0.15, 0.45),    # push high
            "wild_amplified": (0.0, 0.10),    # structurally low (reroll block on grand+wild)
        },
        "per_reel_blank_variance_strength": 5.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.01, "high7": 0.01,
            "7bar": 0.01, "3bar": 0.01, "2bar": 0.01, "1bar": 0.01,
            "mini": 0.008, "minor": 0.008, "major": 0.008, "grand": 0.003,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.10, "high7": 0.16,    # high7 can grow more in lucky
            "7bar": 0.16, "3bar": 0.16, "2bar": 0.16, "1bar": 0.22,    # tighter (was up to 0.32)
            "mini": 0.10, "minor": 0.10, "major": 0.10, "grand": 0.012,
        },
        "uniformity_ratio_cap": {"wild": 2.5, "high7": 3.0},
    },
    5: {
        "total_rtp_pct": 500.0, "total_rtp_tol_pp": 40.0,    # super-lucky wide tol
        "rtp_weight": 6.0,
        # Mode 5 super-lucky: hit can rise to ~35% (everything denser → more pays)
        "hit_rate_target": 0.32, "hit_rate_weight": 150.0,
        "top_jackpot_min_spins": 10000,    # super-lucky 1 in 10k
        "pay_freq_caps": {"8": 0.0015},    # grand alone 1 in 666
        "wild_on_payline_band": (0.08, 0.22),
        "wild_signature_weight": 200.0,
        "booster_r2_band": (0.12, 0.28),    # super-lucky boosters visible (brand)
        "booster_signature_weight": 200.0,
        "family_share_bands": {
            "high7":   (0.05, 0.30),
            "7bar":    (0.03, 0.25),
            "bar_tier": (0.20, 0.50),    # bars naturally still big in super-lucky
            "booster_alone": (0.10, 0.40),
            "wild_amplified": (0.0, 0.10),
        },
        "per_reel_blank_variance_strength": 5.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.015, "high7": 0.015,
            "7bar": 0.01, "3bar": 0.01, "2bar": 0.01, "1bar": 0.01,
            "mini": 0.008, "minor": 0.008, "major": 0.008, "grand": 0.005,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.13, "high7": 0.18,    # high7 can grow more in super-lucky
            "7bar": 0.16, "3bar": 0.16, "2bar": 0.16, "1bar": 0.22,
            "mini": 0.12, "minor": 0.12, "major": 0.12, "grand": 0.020,
        },
        "uniformity_ratio_cap": {"wild": 3.0, "high7": 3.0},
    },
}

# pay_id -> family for RTP share aggregation
PAY_TO_FAMILY = {
    "1":   "high7",          # 3-high7 10×
    "2":   "7bar",           # 3-7bar 6×
    "3":   "bar_tier",       # 3-3bar 5×
    "4":   "bar_tier",       # 3-2bar 4×
    "5":   "bar_tier",       # 3-1bar 3×
    "6":   "high7",          # high7+7bar mixed (2×) — count in high7
    "7":   "bar_tier",       # bar mixed 1×
    "8":   "booster_alone",  # grand alone 100×
    "9":   "booster_alone",  # mini/minor/major alone OR side-wild alone
    "102": "wild_amplified", # pure-wild + major 100×
    "103": "wild_amplified", # pure-wild + minor 50×
    "104": "wild_amplified", # pure-wild + mini 20×
}


def family_rtp_breakdown(profile):
    family = defaultdict(float)
    for pid, contrib in profile.get("pay_rtp", {}).items():
        f = PAY_TO_FAMILY.get(pid)
        if f is None:
            continue
        family[f] += contrib
    return {k: v * 100 for k, v in family.items()}


def wild_on_payline_p(reel_marginals):
    """P(>=1 wild on payline). Wild only on R1 + R3."""
    p_no_wild = (1 - reel_marginals[0].get("wild", 0)) * (1 - reel_marginals[2].get("wild", 0))
    return 1 - p_no_wild


def booster_r2_p(reel_marginals):
    """P(any booster on R2 payline). Brand signature."""
    return (reel_marginals[1].get("mini", 0) + reel_marginals[1].get("minor", 0) +
            reel_marginals[1].get("major", 0) + reel_marginals[1].get("grand", 0))


def per_reel_family_density(weights, strip):
    out = {}
    for r_idx, (rw, rs) in enumerate(zip(weights, strip)):
        total = sum(rw)
        family_w = defaultdict(int)
        for w, sym in zip(rw, rs):
            family_w[sym] += w
        for f, w in family_w.items():
            out[(f, r_idx)] = w / total if total > 0 else 0
    return out


def build_weights_from_uniform(strip, fr_weights):
    out = []
    for r_idx, strip_reel in enumerate(strip):
        reel = []
        for sym in strip_reel:
            reel.append(int(fr_weights.get((sym, r_idx), 1)))
        out.append(reel)
    return out


def counts_from_weights(strips, weights):
    counts = []
    for reel_idx, strip in enumerate(strips):
        c = defaultdict(int)
        for pos, sym in enumerate(strip):
            c[sym] += weights[reel_idx][pos]
        counts.append(dict(c))
    return counts


def evaluate_candidate(fr_weights, strip, evaluator, paytable, exp_targets):
    weights = build_weights_from_uniform(strip, fr_weights)
    counts = counts_from_weights(strip, weights)
    marg = marginals_from_counts(counts)
    pred = analytic_profile_from_marginals(evaluator, marg)

    cost = 0.0

    # RTP target
    rtp_target = exp_targets["total_rtp_pct"]
    rtp_gap = abs(pred["rtp_pct"] - rtp_target)
    rtp_weight = exp_targets.get("rtp_weight", 4.0)
    cost += rtp_weight * (rtp_gap / 0.5) ** 2

    # Hit rate target (if specified)
    hit_target = exp_targets.get("hit_rate_target")
    hit_weight = exp_targets.get("hit_rate_weight", 0.0)
    if hit_target is not None and hit_weight > 0:
        hit_actual = pred.get("hit_rate", 0.0)
        cost += hit_weight * ((hit_actual - hit_target) / 0.01) ** 2

    # Family RTP shares
    family_rtp = family_rtp_breakdown(pred)
    total_rtp = pred["rtp_pct"]
    share_bands = exp_targets.get("family_share_bands", {})
    for f, (lo, hi) in share_bands.items():
        actual = family_rtp.get(f, 0.0) / total_rtp if total_rtp > 0 else 0
        if actual < lo:
            cost += 50.0 * ((lo - actual) * 100) ** 2
        elif actual > hi:
            cost += 50.0 * ((actual - hi) * 100) ** 2

    # Wild on payline
    wild_p = wild_on_payline_p(marg)
    wild_lo, wild_hi = exp_targets["wild_on_payline_band"]
    wild_w = exp_targets.get("wild_signature_weight", 200.0)
    if wild_p < wild_lo:
        cost += wild_w * ((wild_lo - wild_p) * 100) ** 2
    elif wild_p > wild_hi:
        cost += wild_w * ((wild_p - wild_hi) * 100) ** 2

    # Booster on R2 (brand signature) — KEY for M37 "100x Diamond" identity
    booster_p = booster_r2_p(marg)
    boost_lo, boost_hi = exp_targets["booster_r2_band"]
    boost_w = exp_targets.get("booster_signature_weight", 300.0)
    if booster_p < boost_lo:
        cost += boost_w * ((boost_lo - booster_p) * 100) ** 2
    elif booster_p > boost_hi:
        cost += boost_w * ((booster_p - boost_hi) * 100) ** 2

    # Per-family per-reel density caps
    densities = per_reel_family_density(weights, strip)
    lo_by = exp_targets.get("per_reel_density_lo_by_family", {})
    hi_by = exp_targets.get("per_reel_density_hi_by_family", {})
    for (f, r), d in densities.items():
        if f == "blank":
            continue
        den_lo = lo_by.get(f, 0.005)
        den_hi = hi_by.get(f, 0.20)
        if d < den_lo:
            cost += 50.0 * ((den_lo - d) * 100) ** 2
        elif d > den_hi:
            cost += 80.0 * ((d - den_hi) * 100) ** 2

    # Per-reel Blank variance
    blank_var_k = exp_targets.get("per_reel_blank_variance_strength", 0.0)
    if blank_var_k > 0:
        blanks_pp = [densities.get(("blank", r), 0.0) * 100 for r in range(3)]
        mean_b = sum(blanks_pp) / 3
        variance_pp2 = sum((b - mean_b) ** 2 for b in blanks_pp) / 3
        cost += blank_var_k * variance_pp2

    # Top-tier uniformity (wild on R1 vs R3, high7 across reels)
    uniformity_cap = exp_targets.get("uniformity_ratio_cap", {})
    for fam, ratio_cap in uniformity_cap.items():
        per_reel = []
        for r in range(3):
            d = densities.get((fam, r), 0.0)
            if d > 1e-6:
                per_reel.append(d)
        if len(per_reel) >= 2:
            mn = min(per_reel)
            mx = max(per_reel)
            ratio = mx / mn if mn > 0 else 1
            if ratio > ratio_cap:
                cost += 40.0 * (ratio - ratio_cap) ** 2

    # CV target
    cv_target = exp_targets.get("base_cv_target")
    if cv_target is not None:
        actual_cv = pred.get("cv", 0.0)
        if actual_cv > cv_target:
            cost += 80.0 * (actual_cv - cv_target) ** 2

    # Per-pay frequency caps (e.g., grand alone 100× max 1 in 5000)
    pay_freq_caps = exp_targets.get("pay_freq_caps", {})
    for pid, max_freq in pay_freq_caps.items():
        actual_freq = pred.get("pay_hits", {}).get(pid, 0.0)
        if actual_freq > max_freq:
            rel_over = (actual_freq - max_freq) / max_freq
            cost += 1000.0 * (rel_over * 100) ** 2

    # Top jackpot 1000× minimum spin gap
    top_jackpot_min_spins = exp_targets.get("top_jackpot_min_spins")
    if top_jackpot_min_spins is not None:
        # P(top jackpot) = (high7+wild)_R1 × grand_R2 × (high7+wild)_R3
        p_top = (
            (marg[0].get("high7", 0) + marg[0].get("wild", 0))
            * marg[1].get("grand", 0)
            * (marg[2].get("high7", 0) + marg[2].get("wild", 0))
        )
        max_p = 1.0 / top_jackpot_min_spins
        if p_top > max_p:
            rel_over = (p_top - max_p) / max_p
            cost += 1500.0 * (rel_over * 100) ** 2

    return cost, pred, family_rtp, wild_p, booster_p, weights


def search_weights(strip, evaluator, paytable, exp_targets, weight_bounds,
                   frozen_weights=None, weight_floors=None, weight_ceilings=None,
                   seed=0, iterations=15000, verbose=False):
    rng = Random(seed)
    frozen = frozen_weights or {}
    floors = weight_floors or {}
    ceilings = weight_ceilings or {}

    # Initialize per-reel
    fr_weights = {}
    for r_idx in range(3):
        for sym in SYMBOLS_BY_REEL[r_idx]:
            lo, hi = weight_bounds[sym]
            mid = (lo + hi) // 2
            fr_weights[(sym, r_idx)] = mid
    for key, val in frozen.items():
        fr_weights[key] = int(val)
    for key, fv in floors.items():
        if fr_weights.get(key, 0) < fv:
            fr_weights[key] = int(fv)
    for key, cv in ceilings.items():
        if fr_weights.get(key, 0) > cv:
            fr_weights[key] = int(cv)

    best = dict(fr_weights)
    best_cost, _, _, _, _, _ = evaluate_candidate(best, strip, evaluator, paytable, exp_targets)

    sigma_pct = 0.4
    success = 0
    window = 80
    win_evals = 0
    mutable_keys = [k for k in fr_weights.keys() if k not in frozen]

    for step in range(1, iterations + 1):
        cand = dict(best)
        n_mutate = rng.randint(2, 5)
        keys_to_mutate = rng.sample(mutable_keys, min(n_mutate, len(mutable_keys)))
        for key in keys_to_mutate:
            sym, r = key
            lo, hi = weight_bounds[sym]
            effective_lo = max(lo, floors.get(key, 0))
            effective_hi = min(hi, ceilings.get(key, hi))
            if effective_lo > effective_hi:
                effective_hi = effective_lo
            cur = cand[key]
            delta = rng.gauss(0, sigma_pct * (hi - lo))
            new = int(round(cur + delta))
            new = max(effective_lo, min(effective_hi, new))
            cand[key] = new

        cost, _, _, _, _, _ = evaluate_candidate(cand, strip, evaluator, paytable, exp_targets)
        if cost < best_cost:
            best, best_cost = cand, cost
            success += 1
        win_evals += 1
        if win_evals >= window:
            if success / win_evals > 0.2:
                sigma_pct = min(0.4, sigma_pct * 1.1)
            else:
                sigma_pct = max(0.02, sigma_pct * 0.9)
            success = 0
            win_evals = 0
        if verbose and (step <= 5 or step % 1500 == 0):
            print(f"    step {step:>5}  cost={best_cost:.3f}  sigma={sigma_pct:.3f}")
    return best, best_cost


def print_diagnostics(label, fr_weights, strip, evaluator, paytable, exp_targets):
    cost, pred, family_rtp, wild_p, booster_p, weights = evaluate_candidate(
        fr_weights, strip, evaluator, paytable, exp_targets,
    )
    print(f"\n  {label}: cost={cost:.3f}")
    print(f"    RTP={pred['rtp_pct']:.3f}%  hit={pred['hit_rate']:.3%}  CV={pred['cv']:.2f}")
    print(f"    wild_on_payline={wild_p*100:.2f}%  booster_on_R2={booster_p*100:.2f}%")
    print(f"    Family RTP (pp):")
    total = pred["rtp_pct"]
    for f in ("high7", "7bar", "bar_tier", "booster_alone", "wild_amplified"):
        v = family_rtp.get(f, 0.0)
        share = v / total * 100 if total > 0 else 0
        print(f"       {f:18s}: {v:6.2f}pp ({share:5.1f}%)")
    # Per-pay frequency table — "1 in N spins" + RTP contrib
    print(f"    Per-pay frequency:")
    print(f"       {'pay_id':>6s} {'freq':>10s} {'1 in':>9s} {'rtp_pp':>7s}")
    pay_hits = pred.get("pay_hits", {})
    pay_rtp = pred.get("pay_rtp", {})
    for pid in sorted(pay_hits.keys(), key=lambda p: int(p)):
        f = pay_hits[pid]
        rtp_pp = pay_rtp.get(pid, 0) * 100
        one_in = (1 / f) if f > 0 else float("inf")
        print(f"       {pid:>6s} {f:10.6f} {one_in:9.0f} {rtp_pp:7.3f}")
    # Top jackpot freq (high7|wild on R1+R3 + grand on R2)
    densities = per_reel_family_density(weights, strip)
    p_top = (
        (densities.get(("high7", 0), 0) + densities.get(("wild", 0), 0))
        * densities.get(("grand", 1), 0)
        * (densities.get(("high7", 2), 0) + densities.get(("wild", 2), 0))
    )
    top_one_in = (1 / p_top) if p_top > 0 else float("inf")
    print(f"    Top jackpot 1000× (high7|wild × grand × high7|wild): 1 in {top_one_in:,.0f} spins")
    print(f"    Per-reel density:")
    fams = ("blank", "wild", "high7", "7bar", "3bar", "2bar", "1bar", "mini", "minor", "major", "grand")
    print(f"       {'family':12s} R1     R2     R3")
    for f in fams:
        d = [densities.get((f, r), 0) * 100 for r in range(3)]
        print(f"       {f:12s} {d[0]:5.2f}% {d[1]:5.2f}% {d[2]:5.2f}%")
    return pred, family_rtp, wild_p, booster_p, weights


def main(modes_to_run=(1, 7)):
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    strip = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    symbols_reg = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"], reroll_blocks=spec.get("reroll_blocks"))
    evaluator = PaytableEvaluator(symbols_reg, rules, spec["evaluation_order"])
    paytable = spec["pays"]

    mode1_all_weights = None
    mode2_all_weights = None

    BIGWIN_KEYS_M7 = (
        # Frozen high7 + wild + boosters across reels (where they exist)
        [("high7", r) for r in range(3)] +
        [("wild", r) for r in (0, 2)] +
        [(b, 1) for b in ("mini", "minor", "major", "grand")]
    )
    SHAPE_ANCHOR_KEYS_M7 = (
        # Bar weights with range constraint
        [(s, r) for s in BAR_SYMBOLS for r in range(3) if s in SYMBOLS_BY_REEL[r]]
    )
    BLANK_KEYS = [("blank", r) for r in range(3)]
    BAR_KEYS = [(s, r) for s in BAR_SYMBOLS for r in range(3) if s in SYMBOLS_BY_REEL[r]]
    BIG_WIN_KEYS = (
        [("high7", r) for r in range(3)] +
        [("wild", r) for r in (0, 2)] +
        [(b, 1) for b in ("mini", "minor", "major", "grand")]
    )

    for mode in modes_to_run:
        weights_path = _ROOT / "slot_designer" / "weights" / "M37" / f"mode_{mode}" / "weights.json"
        exp_targets = EXPERIENCE_TARGETS[mode]
        weight_bounds = WEIGHT_BOUNDS_BY_MODE[mode]

        frozen_weights = None
        weight_floors = None
        weight_ceilings = None
        if mode == 7 and mode1_all_weights is not None:
            # Mode 7 = mode 1 砍小奖派生:
            # bars cut hard [m1×0.40, m1×0.85] (small wins ↓ frequency)
            # big-win in TIGHT band [m1×0.85, m1×1.05] (≈ density preserved when total drops
            #   from bar cut — without this, frozen big-win density INFLATES, RTP rises)
            # blank ≥ m1 (prevents big-win from inflating further)
            weight_floors = {
                k: max(1, int(mode1_all_weights[k] * 0.40))
                for k in SHAPE_ANCHOR_KEYS_M7 if k in mode1_all_weights
            }
            weight_ceilings = {
                k: max(1, int(mode1_all_weights[k] * 0.85))
                for k in SHAPE_ANCHOR_KEYS_M7 if k in mode1_all_weights
            }
            # Big-win wide-tolerance preservation (density approximately preserved)
            for k in BIGWIN_KEYS_M7:
                if k in mode1_all_weights:
                    weight_floors[k] = max(1, int(mode1_all_weights[k] * 0.80))
                    weight_ceilings[k] = max(1, int(mode1_all_weights[k] * 1.10))
            # Blank floor = mode 1 blank
            for k in BLANK_KEYS:
                if k in mode1_all_weights:
                    weight_floors[k] = mode1_all_weights[k]
            print(f"\n=== Mode {mode}: bar [m1×0.40, m1×0.85]; big-win [m1×0.80, m1×1.10]; blank ≥ mode 1 ===")
        elif mode == 5 and mode2_all_weights is not None:
            # Mode 5 super-lucky design: m2 weights × per-family scale-up.
            # Bars ≥ m2 (slight grow allowed), big-win + booster ≥ m2 × 1.5 (real lift),
            # grand ≥ m2 (top_jackpot constraint will let optimizer push).
            # Blank ≥ m2 × 0.6 (allow blank to shrink ~40% to lift density baseline).
            weight_floors = {}
            # Bars: floor at m2 (no shrink, but allow growth)
            for k in BAR_KEYS:
                if k in mode2_all_weights:
                    weight_floors[k] = mode2_all_weights[k]
            # Big-win (wild + high7): floor m2 × 1.3
            for sym in ("wild", "high7"):
                for r in range(3):
                    k = (sym, r)
                    if k in mode2_all_weights:
                        weight_floors[k] = max(1, int(mode2_all_weights[k] * 1.3))
            # Booster (mini/minor/major): floor m2 × 1.5
            for booster_sym in ("mini", "minor", "major"):
                k = (booster_sym, 1)
                if k in mode2_all_weights:
                    weight_floors[k] = max(1, int(mode2_all_weights[k] * 1.5))
            # Grand: floor = m2 (top_jackpot constraint will let it push)
            grand_key = ("grand", 1)
            if grand_key in mode2_all_weights:
                weight_floors[grand_key] = mode2_all_weights[grand_key]
            # Blank: floor = m2 × 0.6 (allow shrinkage but with floor)
            weight_ceilings = {}
            for k in BLANK_KEYS:
                if k in mode2_all_weights:
                    weight_floors[k] = max(1, int(mode2_all_weights[k] * 0.6))
            print(f"\n=== Mode {mode}: bar ≥ m2; big-win ≥ m2×1.3; booster ≥ m2×1.5; grand ≥ m2; blank ≥ m2×0.6 ===")
        elif mode == 2 and mode1_all_weights is not None:
            # Mode 2 lucky: big-win/booster ≥ mode 1 (lucky every pay frequency ↑),
            # bar capped ≤ m1 × 1.6 (prevent over-loading), blank ≤ mode 1.
            weight_floors = {k: mode1_all_weights[k] for k in BIG_WIN_KEYS if k in mode1_all_weights}
            weight_ceilings = {
                k: max(1, int(mode1_all_weights[k] * 1.6))
                for k in BAR_KEYS if k in mode1_all_weights
            }
            for k in BLANK_KEYS:
                if k in mode1_all_weights:
                    weight_ceilings[k] = mode1_all_weights[k]
            print(f"\n=== Mode {mode}: big-win/booster ≥ mode 1; bar ≤ m1×1.6; blank ≤ mode 1 ===")
        else:
            print(f"\n=== Mode {mode} M37 player-experience tune ===")

        best, best_cost = search_weights(
            strip, evaluator, paytable, exp_targets, weight_bounds,
            frozen_weights=frozen_weights, weight_floors=weight_floors, weight_ceilings=weight_ceilings,
            seed=mode * 13 + 17, iterations=15000, verbose=True,
        )
        pred, family_rtp, wild_p, booster_p, weights = print_diagnostics(
            f"Mode {mode} result", best, strip, evaluator, paytable, exp_targets,
        )

        if mode == 1:
            mode1_all_weights = dict(best)
        if mode == 2:
            mode2_all_weights = dict(best)

        # Persist
        existing = json.loads(weights_path.read_text(encoding="utf-8"))
        existing["mode"] = mode
        existing["weights"] = weights
        existing["_notes"] = [
            f"M37 mode {mode} v3 (2026-04-27) — player-experience direct tune.",
            "Per-family per-reel uniform weights; goal-oriented soft penalties.",
            "Mode 7: bar [m1×0.40, m1×0.85]; big-win [m1×0.80, m1×1.10]; blank ≥ m1.",
            "Mode 2: big-win/booster ≥ m1; bar ≤ m1×1.6; blank ≤ m1 (lucky denser hits).",
            "Mode 5: bar ≥ m2; big-win ≥ m2×1.3; booster ≥ m2×1.5; grand ≥ m2; blank ≥ m2×0.6.",
            f"RTP {pred['rtp_pct']:.3f}%, hit {pred['hit_rate']:.3%}, CV {pred['cv']:.2f}, wild {wild_p*100:.2f}%, booster_R2 {booster_p*100:.2f}%",
        ]
        existing["_tuned_summary"] = {
            "rtp_pct": pred["rtp_pct"],
            "hit_rate": pred["hit_rate"],
            "cv": pred["cv"],
            "wild_on_payline": wild_p,
            "booster_on_r2": booster_p,
            "family_rtp_pp": {f: round(v, 3) for f, v in family_rtp.items()},
            "method": "player_experience_per_family_per_reel_uniform_v3",
        }
        weights_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {weights_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", type=str, default="1,7")
    args = parser.parse_args()
    modes = tuple(int(m) for m in args.modes.split(","))
    main(modes_to_run=modes)
