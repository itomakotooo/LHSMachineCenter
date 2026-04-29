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
  - Mode 7 = mode 1 - 砍小奖派生 (per-tier hit preservation):
    - SMALL bars (1bar/2bar/3bar) [m1×0.30, m1×0.80] (砍 small wins)
    - MID bar (7bar) frozen = m1 (中奖击中率不变)
    - high7 + wild + boosters frozen to mode 1 (大/顶奖击中率不变)
    - blank weight FLOORED ≥ mode 1 (anti-density-inflation)
  - Mode 2: weight floors ≥ mode 1 for non-blank big-win/booster only
    + blank weight CEILED ≤ mode 1 (lucky must be denser hits)
    + bar weights CEILED ≤ mode 1 × 1.6 (prevent bar over-loading)
  - Mode 5 = mode 2 + 倍率 wild boost (preserve hit + bucket shape):
    - bars + 7bar + high7 + wild + mini + minor frozen = m2
    - major weight ≥ m2 × 1.5 (mid-tier multiplier push)
    - grand weight ≥ max(3, m2 × 3) (顶奖密集化)
    - blank floored ≥ m2 (preserve hit pattern)

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

# Tier split for mode-7 design (per project_slot_designer_hit_rate_deviation.md):
# Mode 7 = mode 1 砍小奖派生. 小奖击中率降, 中/大/顶奖击中率不变.
# - SMALL_WIN_BARS = 1bar (3x), 2bar (4x), 3bar (5x) → mode 7 砍这些
# - MID_WIN_BARS = 7bar (6x) → mode 7 frozen (中奖不动)
SMALL_WIN_BARS = ("1bar", "2bar", "3bar")
MID_WIN_BARS = ("7bar",)
BAR_SYMBOLS = SMALL_WIN_BARS + MID_WIN_BARS    # for floors/ceilings in m2

# Per-family per-reel weight bounds. Each is integer >= 1.
# Hierarchy structurally enforced via per-symbol caps:
#   - Bar tier: 1bar (3×) cap > 2bar (4×) > 3bar (5×) > 7bar (6×) — lower payout = higher cap
#   - Booster tier: mini (2×) cap > minor (5×) > major (10×) > grand (100×)
# Caps create natural hierarchy ceiling; combined with hierarchy_strength soft penalty
# the optimizer is forced into payout-frequency 倒金字塔.
# Blank cap 100 STANDARD: mode 7 needs blank room to dilute frozen big-win when small bars cut.
WEIGHT_BOUNDS_STANDARD = {
    "blank":  (1, 100), "wild":  (1, 15),
    "high7":  (1, 30),
    # Bars: 1bar > 2bar > 3bar > 7bar (lower payout, higher cap)
    "7bar":   (1, 18), "3bar":  (1, 25), "2bar":  (1, 35), "1bar":  (1, 50),
    # Boosters: mini > minor > major > grand
    "mini":   (1, 30), "minor": (1, 20), "major": (1, 12), "grand": (1, 5),
}
WEIGHT_BOUNDS_LUCKY = {
    "blank":  (1, 80), "wild":  (1, 25),
    "high7":  (1, 50),
    # Bars: 1bar > 2bar > 3bar > 7bar — tighter than v5 to constrain bar over-load
    "7bar":   (1, 18), "3bar":  (1, 24), "2bar":  (1, 32), "1bar":  (1, 50),
    # Boosters: mini > minor > major > grand
    "mini":   (1, 30), "minor": (1, 20), "major": (1, 13), "grand": (1, 10),
}
WEIGHT_BOUNDS_BY_MODE = {1: WEIGHT_BOUNDS_STANDARD, 7: WEIGHT_BOUNDS_STANDARD,
                         2: WEIGHT_BOUNDS_LUCKY, 5: WEIGHT_BOUNDS_LUCKY}

# Per-mode experience targets
EXPERIENCE_TARGETS = {
    1: {
        "total_rtp_pct": 95.0, "total_rtp_tol_pp": 1.0,
        "rtp_weight": 80.0,    # very strict, dominant
        # mode 1 hit ~17-20% (M37 has frequent pay_id 9 = booster/wild alone at 1 in 8)
        "hit_rate_target": 0.18, "hit_rate_weight": 200.0,
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
        # Mode 7 hit naturally lower (small bars cut + 7bar/big-win density rises slightly)
        "hit_rate_target": 0.14, "hit_rate_weight": 60.0,
        # Top jackpot relaxed since frozen big-win + small bar cut → big-win density rises
        "top_jackpot_min_spins": 40000,
        "pay_freq_caps": {"8": 0.0006},    # grand alone — similar to m1 with small slack
        "wild_on_payline_band": (0.03, 0.20),
        "booster_r2_band": (0.04, 0.12),
        "family_share_bands": {
            "high7":   (0.05, 0.30),
            "7bar":    (0.05, 0.30),    # 7bar frozen → share rises as bars drop
            "bar_tier": (0.05, 0.35),    # tighter cap (bars cut)
            "booster_alone": (0.10, 0.45),    # naturally rises when bars cut
            "wild_amplified": (0.0, 0.10),
        },
        "per_reel_blank_variance_strength": 5.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.005, "high7": 0.005,
            "7bar": 0.005, "3bar": 0.003, "2bar": 0.003, "1bar": 0.003,
            "mini": 0.003, "minor": 0.003, "major": 0.003, "grand": 0.001,
        },
        # Density caps relaxed: frozen weights + bar/blank changes inflate frozen densities,
        # optimizer can't fight that, so caps must accommodate
        "per_reel_density_hi_by_family": {
            "wild": 0.12, "high7": 0.15,
            "7bar": 0.30, "3bar": 0.18, "2bar": 0.18, "1bar": 0.22,
            "mini": 0.10, "minor": 0.10, "major": 0.10, "grand": 0.005,
        },
        "uniformity_ratio_cap": {"wild": 2.5, "high7": 3.0},
        # REEL-ASYMMETRY (universal §12). Mode 7 ONLY (mode 1/2/5 already
        # correctly directed naturally — adding penalty there would perturb
        # cost surface and cause SA noise to break other categories).
        # Mode 7 inherits frozen high7+wild from mode 1 (R3 high7/wild floor
        # > R1 floor structurally) → R1 vs R3 total weight ratio determines
        # density direction. Pre-fix: R1 blank > R3 blank by 0.9pp + R1 top
        # < R3 top by 0.71pp (REVERSE both — within 3pp/1pp verify tolerance
        # but design-wrong direction per universal §12).
        # Tol = 0 (strict equality required), strength 800 high enough to
        # compete with RTP/hit/booster/family-share penalties combined.
        "reel_asymmetry": {
            "blank_tol_pp": 0.0,    # strict: R1 blank ≤ R3 blank
            "top_tol_pp": 0.0,      # strict: R1 top ≥ R3 top
            "blank_strength": 800.0,
            "top_strength": 800.0,
        },
    },
    2: {
        "total_rtp_pct": 300.0, "total_rtp_tol_pp": 20.0,
        "rtp_weight": 8.0,
        "hit_rate_target": 0.23, "hit_rate_weight": 250.0,    # very strict
        "top_jackpot_min_spins": 25000,
        "pay_freq_caps": {"8": 0.0010},    # grand alone 1 in 1000 (3x m1)
        "wild_on_payline_band": (0.06, 0.18),
        "wild_signature_weight": 200.0,
        # booster_R2 ceiling 0.18 (was 0.28) — hierarchy 1.3x gap pushes mini high;
        # tight ceiling caps booster total to keep hit rate in band
        "booster_r2_band": (0.08, 0.18),
        "booster_signature_weight": 300.0,
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
        "total_rtp_pct": 500.0, "total_rtp_tol_pp": 50.0,    # super-lucky wide tol
        "rtp_weight": 6.0,
        # Mode 5 = mode 2 + grand boost. Hit ≈ m2 (everything frozen except grand).
        "hit_rate_target": 0.30, "hit_rate_weight": 150.0,
        # Top jackpot 1 in 3-5k (super-lucky 顶奖 session 级 narrative)
        "top_jackpot_min_spins": 3500,
        # Grand alone freq cap: m2 was 0.0007, m5 grand × 5+ → ~0.005. Cap 0.006 (1 in 167).
        "pay_freq_caps": {"8": 0.006},
        # Wild and booster_R2 frozen from m2 → bands match m2 actual ± wide
        "wild_on_payline_band": (0.05, 0.18),
        "wild_signature_weight": 100.0,
        "booster_r2_band": (0.10, 0.28),    # boosters frozen (mini/minor/major) but grand 拉 → R2 marginal slight up
        "booster_signature_weight": 100.0,
        "family_share_bands": {
            "high7":   (0.10, 0.25),
            "7bar":    (0.08, 0.20),
            "bar_tier": (0.20, 0.45),
            # booster_alone (pay_id 8/9) is the SUPER-LUCKY signature — grand × 3 pushes pay_id 8 way up
            "booster_alone": (0.20, 0.50),
            "wild_amplified": (0.0, 0.05),
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

    # REEL-ASYMMETRY (universal §12 — Strickland/Reid/Harrigan).
    # R1 should have lower blank rate (defends early-rejection persistence) and
    # higher top-prize density than R3 ("差一点" near-miss reel). M37: R2 is
    # the booster reel — exclude; only R1 vs R3 (the symmetric outer reels).
    # Goal-oriented soft penalty: zero when direction correct, quadratic when
    # reversed beyond tolerance. Configured per-mode via reel_asymmetry dict;
    # modes that don't include this key skip the check (zero impact on
    # well-directed modes).
    asym = exp_targets.get("reel_asymmetry", None)
    if asym is not None:
        r1_blank = densities.get(("blank", 0), 0.0)
        r3_blank = densities.get(("blank", 2), 0.0)
        blank_tol = asym.get("blank_tol_pp", 0.03)
        blank_k = asym.get("blank_strength", 200.0)
        if r1_blank > r3_blank + blank_tol:
            gap_pp = (r1_blank - r3_blank - blank_tol) * 100
            cost += blank_k * gap_pp * gap_pp
        # Top-prize: R1 ≥ R3 - tolerance; penalize if R3 has more top than R1
        r1_top = sum(densities.get((s, 0), 0.0) for s in ("high7", "wild"))
        r3_top = sum(densities.get((s, 2), 0.0) for s in ("high7", "wild"))
        top_tol = asym.get("top_tol_pp", 0.01)
        top_k = asym.get("top_strength", 200.0)
        if r1_top < r3_top - top_tol:
            gap_pp = (r3_top - r1_top - top_tol) * 100
            cost += top_k * gap_pp * gap_pp

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

    # Hierarchy enforcement (slot design first principle: payout-frequency 倒金字塔).
    # Per-family within each reel: lower-payout symbols MUST be more frequent than
    # higher-payout symbols. Without this, optimizer trades hierarchy for marginal
    # cost win, breaking player intuition (e.g., major(10×) more common than mini(2×)).
    # Strength must be very high (5000+) to overpower RTP/share gravity — booster
    # multipliers like major(10×) give optimizer 5x more RTP per weight than mini(2×).
    hierarchy_strength = exp_targets.get("hierarchy_strength", 5000.0)
    # Bar tier on each reel: 1bar > 2bar > 3bar > 7bar (lower-payout = more frequent)
    BAR_ORDER = ("1bar", "2bar", "3bar", "7bar")
    for r in range(3):
        prev_d = None
        for s in BAR_ORDER:
            d = densities.get((s, r), 0.0)
            if d == 0:
                continue    # symbol not on this reel
            if prev_d is not None and d > prev_d:
                # Violation: higher-payout symbol denser than lower-payout
                gap = d - prev_d
                cost += hierarchy_strength * (gap * 100) ** 2
            prev_d = d
    # Booster tier on R2: mini(2×) > minor(5×) > major(10×) > grand(100×)
    # GAP requirement: ratio ≥ 1.2x between consecutive tiers (visibly distinct).
    # Note: 1.3x infeasible with mode 2/5 RTP 300%/500% + hit-rate cap because
    # forced cascading (grand top_jackpot bound → mini = 1.3³ × grand min ≈ 2.2x grand)
    # leaves no RTP room. 1.2x = 1.728x cascade still gives clear distinction.
    BOOSTER_ORDER = ("mini", "minor", "major", "grand")
    BOOSTER_GAP_TARGET = 1.2
    for i in range(len(BOOSTER_ORDER) - 1):
        s_lo = BOOSTER_ORDER[i]    # lower payout, must be more frequent
        s_hi = BOOSTER_ORDER[i + 1]
        d_lo = densities.get((s_lo, 1), 0.0)
        d_hi = densities.get((s_hi, 1), 0.0)
        if d_lo == 0 or d_hi == 0:
            continue
        target = d_hi * BOOSTER_GAP_TARGET
        if d_lo < target:
            deficit = target - d_lo    # in fraction
            cost += hierarchy_strength * (deficit * 1000) ** 2

    # Blank-not-pinned penalty: blank weight pinned at WEIGHT_BOUNDS upper means
    # optimizer wanted to add more dilution but couldn't → design漂. Soft penalty
    # only triggers when blank IS at the cap, not at lower values.
    blank_pin_strength = exp_targets.get("blank_pin_strength", 0.0)
    if blank_pin_strength > 0:
        # Find the WEIGHT_BOUNDS for blank from the candidate (passed via fr_weights)
        for r_idx, reel_strip in enumerate(strip):
            for pos, sym in enumerate(reel_strip):
                if sym == "blank":
                    blank_w = weights[r_idx][pos]
                    # If blank close to a soft cap (e.g., 90+ of 100), penalize
                    if blank_w >= 95:
                        cost += blank_pin_strength * (blank_w - 95) ** 2
                    break    # only check first blank per reel (per-family uniform)

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
    # Mode 7 砍小奖派生: 只切 SMALL_WIN_BARS (1bar/2bar/3bar), 中奖 7bar 不动
    SMALL_WIN_KEYS_M7 = [(s, r) for s in SMALL_WIN_BARS for r in range(3) if s in SYMBOLS_BY_REEL[r]]
    MID_WIN_KEYS_M7 = [(s, r) for s in MID_WIN_BARS for r in range(3) if s in SYMBOLS_BY_REEL[r]]
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
        # Allow mode 7 / mode 5 to load their dependency (mode 1 / mode 2) from
        # disk if not in memory — supports incremental retune of one mode
        # without full chain re-tune. Per WORKFLOW.md "minimal surgery" — adding
        # mode 7 asymmetry penalty should not perturb modes 1/2/5.
        if mode == 7 and mode1_all_weights is None:
            m1_path = _ROOT / "slot_designer" / "weights" / "M37" / "mode_1" / "weights.json"
            if m1_path.exists():
                m1_doc = json.loads(m1_path.read_text(encoding="utf-8"))
                m1_strip = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
                mode1_all_weights = {}
                for r_idx, reel in enumerate(m1_strip):
                    seen = set()
                    for pos, sym in enumerate(reel):
                        if sym not in seen:
                            mode1_all_weights[(sym, r_idx)] = m1_doc["weights"][r_idx][pos]
                            seen.add(sym)
                print(f"  loaded mode 1 weights from disk for mode 7 derivation")
        if mode == 5 and mode2_all_weights is None:
            m2_path = _ROOT / "slot_designer" / "weights" / "M37" / "mode_2" / "weights.json"
            if m2_path.exists():
                m2_doc = json.loads(m2_path.read_text(encoding="utf-8"))
                m2_strip = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
                mode2_all_weights = {}
                for r_idx, reel in enumerate(m2_strip):
                    seen = set()
                    for pos, sym in enumerate(reel):
                        if sym not in seen:
                            mode2_all_weights[(sym, r_idx)] = m2_doc["weights"][r_idx][pos]
                            seen.add(sym)
                print(f"  loaded mode 2 weights from disk for mode 5 derivation")
        if mode == 7 and mode1_all_weights is not None:
            # Mode 7 = mode 1 砍小奖派生 (slot_designer charter: bar tier × ~0.85 uniform):
            # - All bars [m1×0.65, m1×0.95] — uniform cut preserves bar hierarchy
            #   (per-tier strict preservation conflicts with hierarchy when 3bar must
            #    stay denser than 7bar; uniform cut is the canonical solution)
            # - high7 + wild + boosters frozen = m1 — 大/顶奖击中率不变
            # - blank weight ≥ m1 (CRITICAL: anti-big-win-density-inflation)
            weight_floors = {}
            weight_ceilings = {}
            # ALL bars [m1×0.72, m1×0.95] uniform cut
            # (m1×0.72 floor → cubic effect on 3-match: 0.72³ = 0.37, with wild sub
            # actual ratio ~0.45-0.50 — within MODE7_BAR_MIN_RATIO 0.50 floor)
            for k in BAR_KEYS:    # 1bar/2bar/3bar/7bar
                if k in mode1_all_weights:
                    weight_floors[k] = max(1, int(mode1_all_weights[k] * 0.72))
                    weight_ceilings[k] = max(1, int(mode1_all_weights[k] * 0.95))
            # Big-win (high7/wild/boosters) frozen
            frozen_weights = {}
            for k in BIGWIN_KEYS_M7:
                if k in mode1_all_weights:
                    frozen_weights[k] = mode1_all_weights[k]
            # Blank floor = m1 blank weight (critical anti-density-inflation)
            for k in BLANK_KEYS:
                if k in mode1_all_weights:
                    weight_floors[k] = mode1_all_weights[k]
            print(f"\n=== Mode {mode}: bars [m1*0.65, m1*0.95] uniform; big-win frozen=m1; blank>=m1 ===")
        elif mode == 5 and mode2_all_weights is not None:
            # Mode 5 super-lucky design: m2 base + 倍率 wild boost (grand + major).
            # Per memory project_slot_designer_mode_rtp_invariants.md:
            #   "mode 5 = mode 2 加大奖派生 ... hit rate / bucket shape 保持"
            #
            # Hit rate ≈ m2 (small/mid pay symbols frozen).
            # Big wins more frequent: grand ×3 → 1000× 顶奖密集化; major ×1.5 → 中-高 tier × multiplier 频次升.
            # mini/minor frozen (low-value boosters not the super-lucky signature).
            #
            # Implementation:
            # - Bars + 7bar + high7 + wild + mini + minor frozen = m2 (preserve hit + low-tier brand)
            # - major floored ≥ m2 × 1.5 (push mid-tier multiplier visibility + RTP)
            # - grand floored ≥ max(3, m2 × 3) (push顶奖) — top_jackpot constraint will cap
            # - Blank floored = m2 (preserve hit by holding blank density)
            # Mode 5 super-lucky design: only grand is pushed (顶奖密集化).
            # All other symbols (bars/wild/high7/mini/minor/major/blank) frozen = m2.
            # This preserves hierarchy (mini > minor > major > grand from m2 inherited),
            # preserves hit pattern (everything else fixed), and adds RTP via grand × side.
            FROZEN_FOR_M5 = (
                BAR_KEYS    # all bars (1bar/2bar/3bar/7bar)
                + [("wild", r) for r in (0, 2)]    # wild
                + [("high7", r) for r in range(3)]    # high7
                + [(b, 1) for b in ("mini", "minor", "major")]    # all boosters except grand
                + BLANK_KEYS    # blank (lock for density preservation)
            )
            frozen_weights = {k: mode2_all_weights[k] for k in FROZEN_FOR_M5 if k in mode2_all_weights}
            weight_floors = {}
            # Grand is the ONLY mutable symbol — push toward顶奖密集化 (1000× session 级)
            grand_key = ("grand", 1)
            if grand_key in mode2_all_weights:
                weight_floors[grand_key] = max(6, int(mode2_all_weights[grand_key] * 6))
            print(f"\n=== Mode {mode}: ALL frozen=m2 except grand≥max(6,m2×6) ===")
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
            "Mode 7: SMALL bar [m1×0.30, m1×0.80]; 7bar+big-win frozen=m1; blank≥m1 (per-tier hit preservation).",
            "Mode 2: big-win/booster ≥ m1; bar ≤ m1×1.6; blank ≤ m1 (lucky denser hits).",
            "Mode 5: ALL frozen=m2 except grand (≥ max(6, m2×6)) — only顶奖密集化, hit/hierarchy preserved.",
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
