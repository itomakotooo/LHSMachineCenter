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
  - Mode 7 = mode 1 - 略砍小奖派生:
    - high7 + booster + wild weights frozen to mode 1 (大奖 + brand 不动)
    - bar1/2/3/7bar weight ranges [mode 1 × 0.80, mode 1 × 0.95] (略砍 uniform)
  - Mode 2: weight floors ≥ mode 1 for all non-blank (lucky every pay frequency ↑)
  - Mode 5: weight floors ≥ mode 2 + booster TIER shift (more grand/major)

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
        "rtp_weight": 12.0,
        "hit_rate_target": 0.16, "hit_rate_weight": 100.0,    # accept ~16%
        "wild_on_payline_band": (0.05, 0.18),
        "wild_signature_weight": 500.0,
        "booster_r2_band": (0.07, 0.18),
        "booster_signature_weight": 600.0,    # KEY brand for "100x Diamond"
        "family_share_bands": {
            # of total RTP. Bar tier dominates base, high7 + booster_amplified provide wow.
            "high7":   (0.05, 0.25),
            "7bar":    (0.05, 0.25),
            "bar_tier": (0.20, 0.55),  # 1bar+2bar+3bar combined
            "booster_alone": (0.05, 0.25),  # pay_id 8/9 (booster center alone)
            "wild_amplified": (0.0, 0.20),  # pay_id 102/103/104 (pure-wild + booster)
        },
        "per_reel_blank_variance_strength": 25.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.005, "high7": 0.005,
            "7bar": 0.01, "3bar": 0.01, "2bar": 0.01, "1bar": 0.01,
            "mini": 0.005, "minor": 0.005, "major": 0.005, "grand": 0.001,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.10, "high7": 0.20,
            "7bar": 0.20, "3bar": 0.20, "2bar": 0.20, "1bar": 0.30,
            "mini": 0.10, "minor": 0.08, "major": 0.08, "grand": 0.02,
        },
        "uniformity_ratio_cap": {  # symbols on multiple reels
            "wild": 2.0, "high7": 3.0,  # cross-reel uniformity for top-tier
        },
        "base_cv_target": 11.0,    # M37 has 100×/1000× booster path; CV 6-9 unreachable structurally
    },
    7: {
        "total_rtp_pct": 85.0, "total_rtp_tol_pp": 1.5,
        "rtp_weight": 12.0,
        "hit_rate_target": 0.10, "hit_rate_weight": 100.0,
        "wild_on_payline_band": (0.03, 0.18),
        "booster_r2_band": (0.05, 0.18),
        "family_share_bands": {
            "high7":   (0.03, 0.25),
            "7bar":    (0.03, 0.25),
            "bar_tier": (0.15, 0.55),
            "booster_alone": (0.05, 0.30),
            "wild_amplified": (0.0, 0.20),
        },
        "per_reel_blank_variance_strength": 25.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.005, "high7": 0.005,
            "7bar": 0.005, "3bar": 0.005, "2bar": 0.005, "1bar": 0.005,
            "mini": 0.003, "minor": 0.003, "major": 0.003, "grand": 0.001,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.10, "high7": 0.20,
            "7bar": 0.20, "3bar": 0.20, "2bar": 0.20, "1bar": 0.30,
            "mini": 0.10, "minor": 0.10, "major": 0.10, "grand": 0.02,
        },
        "uniformity_ratio_cap": {"wild": 2.0, "high7": 3.0},
    },
    2: {
        "total_rtp_pct": 300.0, "total_rtp_tol_pp": 20.0,
        "hit_rate_target": 0.23, "hit_rate_weight": 60.0,
        "wild_on_payline_band": (0.05, 0.30),
        "booster_r2_band": (0.10, 0.30),
        "family_share_bands": {
            "high7":   (0.03, 0.25),
            "7bar":    (0.03, 0.25),
            "bar_tier": (0.15, 0.55),
            "booster_alone": (0.10, 0.40),
            "wild_amplified": (0.0, 0.30),
        },
        "per_reel_blank_variance_strength": 25.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.01, "high7": 0.01,
            "7bar": 0.01, "3bar": 0.01, "2bar": 0.01, "1bar": 0.01,
            "mini": 0.005, "minor": 0.005, "major": 0.005, "grand": 0.005,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.15, "high7": 0.22,
            "7bar": 0.22, "3bar": 0.22, "2bar": 0.22, "1bar": 0.32,
            "mini": 0.12, "minor": 0.12, "major": 0.12, "grand": 0.04,
        },
        "uniformity_ratio_cap": {"wild": 2.5, "high7": 3.0},
    },
    5: {
        "total_rtp_pct": 500.0, "total_rtp_tol_pp": 30.0,
        "hit_rate_target": 0.23, "hit_rate_weight": 150.0,
        "wild_on_payline_band": (0.05, 0.32),
        "booster_r2_band": (0.10, 0.35),
        "family_share_bands": {
            "high7":   (0.03, 0.25),
            "7bar":    (0.03, 0.25),
            "bar_tier": (0.10, 0.55),
            "booster_alone": (0.10, 0.45),
            "wild_amplified": (0.0, 0.35),
        },
        "per_reel_blank_variance_strength": 25.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.01, "high7": 0.01,
            "7bar": 0.01, "3bar": 0.01, "2bar": 0.01, "1bar": 0.01,
            "mini": 0.003, "minor": 0.005, "major": 0.005, "grand": 0.01,  # super-lucky pushes grand
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.18, "high7": 0.22,
            "7bar": 0.22, "3bar": 0.22, "2bar": 0.22, "1bar": 0.32,
            "mini": 0.10, "minor": 0.12, "major": 0.15, "grand": 0.06,  # grand higher in m5
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
    print(f"    Per-reel density:")
    densities = per_reel_family_density(weights, strip)
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

    for mode in modes_to_run:
        weights_path = _ROOT / "slot_designer" / "weights" / "M37" / f"mode_{mode}" / "weights.json"
        exp_targets = EXPERIENCE_TARGETS[mode]
        weight_bounds = WEIGHT_BOUNDS_BY_MODE[mode]

        frozen_weights = None
        weight_floors = None
        weight_ceilings = None
        if mode == 7 and mode1_all_weights is not None:
            frozen_weights = {k: mode1_all_weights[k] for k in BIGWIN_KEYS_M7 if k in mode1_all_weights}
            weight_floors = {
                k: max(1, int(mode1_all_weights[k] * 0.80))
                for k in SHAPE_ANCHOR_KEYS_M7 if k in mode1_all_weights
            }
            weight_ceilings = {
                k: max(1, int(mode1_all_weights[k] * 0.95))
                for k in SHAPE_ANCHOR_KEYS_M7 if k in mode1_all_weights
            }
            print(f"\n=== Mode {mode}: frozen big-win (high7+wild+boosters) = mode 1; bar [m1×0.80, ×0.95] ===")
        elif mode == 5 and mode2_all_weights is not None:
            # M37 mode 5 design: hit ≈ mode 2 (Bar frozen) + per-hit bigger
            # (big-win/boosters grow). NOT all-weights-floor because that
            # would inflate hit too.
            BIG_WIN_KEYS_M5 = (
                [("high7", r) for r in range(3)] +
                [("wild", r) for r in (0, 2)] +
                [(b, 1) for b in ("mini", "minor", "major", "grand")]
            )
            BAR_KEYS_M5 = [(s, r) for s in BAR_SYMBOLS for r in range(3) if s in SYMBOLS_BY_REEL[r]]
            # Frozen: Bar weights = mode 2 (preserve hit rate via Bar density)
            frozen_weights = {k: mode2_all_weights[k] for k in BAR_KEYS_M5 if k in mode2_all_weights}
            # Floor: big-win + booster ≥ mode 2 (super-lucky bigger wins)
            weight_floors = {k: mode2_all_weights[k] for k in BIG_WIN_KEYS_M5 if k in mode2_all_weights}
            print(f"\n=== Mode {mode}: bar frozen = mode 2 (hit preserved); big-win/booster floors = mode 2 (super-lucky bigger wins) ===")
        elif mode == 2 and mode1_all_weights is not None:
            weight_floors = {
                (sym, r): w for (sym, r), w in mode1_all_weights.items()
                if sym not in ("blank",)
            }
            print(f"\n=== Mode {mode}: lucky weight floors = mode 1's (non-blank, lucky monotonic) ===")
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
            f"M37 mode {mode} v2 (2026-04-26) — player-experience direct tune.",
            "Per-family per-reel uniform weights; goal-oriented soft penalties.",
            "Mode 7 frozen: high7 + wild + boosters; bar weights ∈ [m1×0.80, ×0.95].",
            "Mode 2 weight_floors = mode 1; Mode 5 weight_floors = mode 2 (lucky monotonic).",
            f"RTP {pred['rtp_pct']:.3f}%, hit {pred['hit_rate']:.3%}, CV {pred['cv']:.2f}, wild {wild_p*100:.2f}%, booster_R2 {booster_p*100:.2f}%",
        ]
        existing["_tuned_summary"] = {
            "rtp_pct": pred["rtp_pct"],
            "hit_rate": pred["hit_rate"],
            "cv": pred["cv"],
            "wild_on_payline": wild_p,
            "booster_on_r2": booster_p,
            "family_rtp_pp": {f: round(v, 3) for f, v in family_rtp.items()},
            "method": "player_experience_per_family_per_reel_uniform_v2",
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
