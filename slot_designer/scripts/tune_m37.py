"""Tune M37 mode weights — player-experience direct objective.

M37 = "100x Diamond" — Lightning-Link/Dragon-Link inspired classic 3-reel
with multiplier-tier wilds (mini/minor/major/grand) on R2.

Per ``project_slot_designer §A axiom``: cost function
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

# Tier split for mode-7 design (per project_slot_designer.md (§D hit rate)):
# Mode 7 = mode 1 砍小奖派生. 小奖击中率降, 中/大/顶奖击中率不变.
# - SMALL_WIN_BARS = 1bar (3x), 2bar (4x), 3bar (5x) → mode 7 砍这些
# - MID_WIN_BARS = 7bar (6x) → mode 7 frozen (中奖不动)
SMALL_WIN_BARS = ("1bar", "2bar", "3bar")
MID_WIN_BARS = ("7bar",)
BAR_SYMBOLS = SMALL_WIN_BARS + MID_WIN_BARS    # for floors/ceilings in m2

# v6: Tier → bucket key mapping (matches DESIGN.md §7 + analytic_rtp _BUCKETS).
# Used by bucket_rtp_share_targets cost in _predict_cost.
TIER_TO_BUCKETS = {
    "low":  ("gt0_lt1", "ge1_lt5", "ge5_lt10"),
    "mid":  ("ge10_lt20", "ge20_lt50"),
    "high": ("ge50_lt100", "ge100_lt200", "ge200_lt500"),
    "top":  ("ge500_lt1000", "ge1000_lt5000", "ge5000"),
}

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
    # 2026-04-29 v5: grand bound bumped 5 → 10 to allow normal-hittable signature visibility
    "mini":   (1, 30), "minor": (1, 20), "major": (1, 12), "grand": (1, 10),
}
WEIGHT_BOUNDS_LUCKY = {
    "blank":  (1, 80), "wild":  (1, 25),
    "high7":  (1, 50),
    # Bars: 1bar > 2bar > 3bar > 7bar — tighter than v5 to constrain bar over-load
    "7bar":   (1, 18), "3bar":  (1, 24), "2bar":  (1, 32), "1bar":  (1, 50),
    # Boosters: mini > minor > major > grand
    # 2026-04-29 v5: grand bound bumped 10 → 30 (lucky modes need much more grand for "session-level moment" design)
    "mini":   (1, 30), "minor": (1, 20), "major": (1, 13), "grand": (1, 30),
}
WEIGHT_BOUNDS_BY_MODE = {1: WEIGHT_BOUNDS_STANDARD, 7: WEIGHT_BOUNDS_STANDARD,
                         2: WEIGHT_BOUNDS_LUCKY, 5: WEIGHT_BOUNDS_LUCKY}

# Per-mode experience targets
EXPERIENCE_TARGETS = {
    1: {
        "total_rtp_pct": 95.0, "total_rtp_tol_pp": 1.0,
        # v6: rtp_weight bumped 80 → 250 to ensure 95% RTP holds against
        # bucket_share/hit/asymmetry pull (v5 80 was sufficient pre-bucket
        # constraint; v6 bucket_share 1000 + asymmetry 1000 dominated).
        "rtp_weight": 250.0,
        # v6: DESIGN.md §7 spec'd Mode 1 hit ~13% (was 16% target chasing
        # v4.6 21% achieved). v5 grand-signature pulled hit DOWN from 21% to
        # 17% but still 4pp over design — 45% of hits are 1-2× bet-back pays
        # per adversarial review. Tightening to 13% per design intent.
        "hit_rate_target": 0.13, "hit_rate_weight": 250.0,
        # Wild upper tightened: less side wild alone (1× empty-feeling pays).
        "wild_on_payline_band": (0.04, 0.10),
        "wild_signature_weight": 400.0,
        # Booster on R2: M37 signature. v6: floor 0.10 enforced strongly to
        # ensure R2 has enough non-blank density (more 3-match-with-booster
        # mid pays). Counters the v5 R2 blank 84% over-dilution.
        "booster_r2_band": (0.10, 0.20),
        "booster_signature_weight": 600.0,
        # v6: keep grand alone signature freq target (kept from v5).
        # 3-wild jackpot freq targets DROPPED — too aggressive, optimizer
        # found degenerate corner (R3 wild 17%, R2 booster 3.5%). Instead,
        # rely on per_reel_density floors + bucket_share to keep mini/minor/
        # major naturally visible (~1/5-15k range, hittable per session).
        # v6: grand alone target 1/716 → 1/1000. 1/716 dominates High bucket
        # (grand 100× alone = 14pp = 14.7% RTP, structurally pins High at
        # 30%+). Reducing to 1/1000 = 9pp lets Mid bucket grow per DESIGN.md.
        # Player still hits grand 100× per ~1 hour session = "normally
        # hittable signature" intent satisfied.
        "pay_freq_targets": {"8": 0.001},  # 1/1000 grand alone
        # 1000x top jackpot via high7-grand-high7 substitution.
        # min_spins = floor (top must NOT fire MORE often than 1/30k).
        # max_spins = ceiling (top must NOT be RARER than 1/120k — visibility
        # per 50-100hr session lifetime; v6 added because cutting high7 to
        # control Mid bucket made top 1/347k = effectively never seen).
        "top_jackpot_min_spins": 30000,
        "top_jackpot_max_spins": 120000,
        # v6: NEW bucket-level RTP share constraint. DESIGN.md §7 specifies
        # Low ~35% / Mid ~40% / High ~20% / Top ~5%. v5 actual was
        # Low 32.5 / Mid 31.6 / High 30.7 / Top 5.2 — Mid UNDER 8.4pp,
        # High OVER 10.7pp. Without this constraint, family_share alone is
        # blind to WITHIN-bucket distribution (booster_alone could be 50%
        # from 1× side-wild-alone OR 50% from 100× grand-alone — totally
        # different player feel).
        "bucket_rtp_share_targets": {
            "low": 0.35,    # gt0_lt1 + ge1_lt5 + ge5_lt10
            "mid": 0.40,    # ge10_lt20 + ge20_lt50 (DESIGN.md "咦有料 accept" core)
            "high": 0.20,   # ge50_lt100 + ge100_lt200 + ge200_lt500
            "top": 0.05,    # ge500_lt1000 + ge1000_lt5000+
        },
        "bucket_share_weight": 1000.0,
        "family_share_bands": {
            # v6: relaxed — bucket_rtp_share_targets is the primary distribution
            # constraint. Family bands kept as guardrails to prevent wild swings.
            "high7":   (0.05, 0.20),
            "7bar":    (0.05, 0.18),
            "bar_tier": (0.18, 0.40),
            "booster_alone": (0.25, 0.50),    # capped 50% (was 50, kept)
            "wild_amplified": (0.0, 0.10),
        },
        "per_reel_blank_variance_strength": 8.0,
        "per_reel_density_lo_by_family": {
            # v6: high7 floor raised 0.005 → 0.05 to anchor top jackpot path
            # (3-high7 × grand = 1000× legendary moment). Without this,
            # bucket-share Mid pull cuts high7 to <2% making top 1/300k+.
            "wild": 0.005, "high7": 0.05,
            "7bar": 0.005, "3bar": 0.005, "2bar": 0.005, "1bar": 0.01,
            # v6: mini floor lifted (need 3-wild mini visibility)
            "mini": 0.008, "minor": 0.006, "major": 0.004, "grand": 0.0012,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.08, "high7": 0.10,
            "7bar": 0.12, "3bar": 0.12, "2bar": 0.12, "1bar": 0.16,
            "mini": 0.08, "minor": 0.06, "major": 0.04, "grand": 0.0020,
        },
        "uniformity_ratio_cap": {"wild": 2.0, "high7": 2.0},
        "base_cv_target": 10.0,
        # v6: REEL-ASYMMETRY for mode 1 too (universal §12). v5 had R1 top
        # > R3 top naturally; v6 cost surface (bucket_share + family_share
        # at higher weights) freed optimizer to flip direction. Add explicit
        # constraint so direction stays correct.
        "reel_asymmetry": {
            "blank_tol_pp": 0.02,
            "top_tol_pp": 0.005,
            "blank_strength": 600.0,
            "top_strength": 600.0,
        },
    },
    7: {
        "total_rtp_pct": 85.0, "total_rtp_tol_pp": 2.0,
        "rtp_weight": 100.0,    # v6: bumped 30 → 100 (mode 1 baseline change)
        # Mode 7 hit slightly lower than mode 1 (砍 small bars)
        "hit_rate_target": 0.14, "hit_rate_weight": 60.0,
        "top_jackpot_min_spins": 30000,
        # 2026-04-29 v5: per design "中/大/顶奖击中率不变" (mode 7 = mode 1 砍小奖派生),
        # mode 7 grand alone freq = mode 1's = 1/700. Bigwin frozen handles this.
        "pay_freq_targets": {"8": 0.0014},  # = mode 1 target (大奖击中率不变)
        "wild_on_payline_band": (0.03, 0.20),
        "booster_r2_band": (0.06, 0.16),
        "family_share_bands": {
            "high7":   (0.05, 0.22),
            "7bar":    (0.05, 0.22),
            "bar_tier": (0.10, 0.32),    # mode 7 砍 bars
            # v6: booster_alone cap kept tight at 0.62 — verify hardcodes
            # 0.65 cap. Don't move goalposts; instead push optimizer to hit
            # under 65% by tighter tune cap.
            "booster_alone": (0.30, 0.62),
            "wild_amplified": (0.0, 0.10),
        },
        "per_reel_blank_variance_strength": 5.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.005, "high7": 0.005,
            "7bar": 0.005, "3bar": 0.003, "2bar": 0.003, "1bar": 0.003,
            "mini": 0.003, "minor": 0.003, "major": 0.003, "grand": 0.0008,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.10, "high7": 0.12,
            "7bar": 0.20, "3bar": 0.16, "2bar": 0.16, "1bar": 0.18,
            "mini": 0.08, "minor": 0.06, "major": 0.04, "grand": 0.008,
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
        "top_jackpot_min_spins": 8000,
        # 2026-04-29 v5: lucky mode grand 6x more frequent than m1 (m1 1/700 → m2 1/120)
        "pay_freq_targets": {"8": 0.008},  # 1/125 grand alone — lucky frequent
        "wild_on_payline_band": (0.06, 0.20),
        "wild_signature_weight": 200.0,
        "booster_r2_band": (0.10, 0.22),
        "booster_signature_weight": 300.0,
        "family_share_bands": {
            "high7":   (0.05, 0.25),
            "7bar":    (0.03, 0.20),
            "bar_tier": (0.15, 0.40),
            "booster_alone": (0.30, 0.55),    # signature dominant in lucky
            "wild_amplified": (0.0, 0.08),
        },
        "per_reel_blank_variance_strength": 5.0,
        "per_reel_density_lo_by_family": {
            # v6: high7 R1/R3 floor raised 0.04 → 0.06 to ensure SHARE >5%
            # (was 3.8% with floor 0.04 — needed higher).
            "wild": 0.01, "high7": 0.06,
            "7bar": 0.01, "3bar": 0.01, "2bar": 0.01, "1bar": 0.01,
            "mini": 0.008, "minor": 0.008, "major": 0.008, "grand": 0.003,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.12, "high7": 0.18,
            "7bar": 0.14, "3bar": 0.14, "2bar": 0.14, "1bar": 0.20,
            # 2026-04-29 v5: grand cap bumped 1.2% → 3% (lucky needs significant grand)
            "mini": 0.10, "minor": 0.10, "major": 0.10, "grand": 0.030,
        },
        "uniformity_ratio_cap": {"wild": 2.5, "high7": 3.0},
        # v6: REEL-ASYMMETRY (universal §12). Mode 2 had R1 top 6.5% < R3
        # 14.7% (8pp gap, REVERSED from §12 R1≥R3 top intent). Adding
        # constraint to push optimizer to symmetric direction. Inherits to
        # mode 5 (mode 5 base = mode 2 base byte-identical).
        "reel_asymmetry": {
            "blank_tol_pp": 0.03,    # 3pp tol — lucky modes have flatter blank
            "top_tol_pp": 0.01,      # 1pp tol — top symmetry strict
            "blank_strength": 600.0,
            "top_strength": 600.0,
        },
    },
    5: {
        "total_rtp_pct": 500.0, "total_rtp_tol_pp": 40.0,
        # 2026-04-29 v5: rtp_weight bumped 6 → 20 so RTP target keeps mode 5 in band
        # (was overshooting 551% > 540 with grand boost + m2 base RTP)
        "rtp_weight": 20.0,
        # Mode 5 = mode 2 + grand boost. Hit ≈ m2.
        "hit_rate_target": 0.30, "hit_rate_weight": 100.0,
        # Top jackpot 1 in 2-3k (super-lucky session-level narrative)
        "top_jackpot_min_spins": 2000,
        # 2026-04-29 v5: target 1/50 (slightly rarer than initial 1/40 to keep RTP in band)
        "pay_freq_targets": {"8": 0.020},  # 1/50 grand alone — super-lucky session moments
        "wild_on_payline_band": (0.06, 0.22),
        "wild_signature_weight": 100.0,
        "booster_r2_band": (0.15, 0.32),
        "booster_signature_weight": 100.0,
        "family_share_bands": {
            "high7":   (0.05, 0.25),
            "7bar":    (0.05, 0.20),
            "bar_tier": (0.15, 0.40),
            "booster_alone": (0.30, 0.60),    # super-lucky — booster dominant
            "wild_amplified": (0.0, 0.08),
        },
        "per_reel_blank_variance_strength": 5.0,
        "per_reel_density_lo_by_family": {
            "wild": 0.015, "high7": 0.06,
            "7bar": 0.01, "3bar": 0.01, "2bar": 0.01, "1bar": 0.01,
            # v6: super-lucky needs grand ~4% to hit pay_id 8 = 1/50 freq.
            # Hierarchy 1.2x means major ≥ 4×1.2 = 4.8%. Floor major 0.05.
            "mini": 0.06, "minor": 0.05, "major": 0.05, "grand": 0.030,
        },
        "per_reel_density_hi_by_family": {
            "wild": 0.13, "high7": 0.20,
            "7bar": 0.16, "3bar": 0.16, "2bar": 0.16, "1bar": 0.22,
            # v6: grand cap 0.040 (allow super-lucky grand ~4%); hierarchy
            # enforced via major floor ≥ grand × 1.2 = 0.048 (set major
            # floor 0.050).
            "mini": 0.12, "minor": 0.12, "major": 0.12, "grand": 0.040,
        },
        # v6: tightened from 3.0 → 2.5 (was barely failing at 2.51 ratio)
        "uniformity_ratio_cap": {"wild": 2.5, "high7": 3.0},
        # v6: REEL-ASYMMETRY (universal §12) — inherits intent from mode 2
        # since mode 5 = m2 base byte-identical + grand boost.
        "reel_asymmetry": {
            "blank_tol_pp": 0.03,
            "top_tol_pp": 0.01,
            "blank_strength": 600.0,
            "top_strength": 600.0,
        },
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

    # Family RTP shares — v6 weight bumped 50 → 500 to compete with bucket
    # /RTP/asymmetry. v5 50 was OK pre-bucket but now drowned in 100K+ cost
    # surface, leaving optimizer free to violate share bands by 3pp+.
    family_rtp = family_rtp_breakdown(pred)
    total_rtp = pred["rtp_pct"]
    share_bands = exp_targets.get("family_share_bands", {})
    for f, (lo, hi) in share_bands.items():
        actual = family_rtp.get(f, 0.0) / total_rtp if total_rtp > 0 else 0
        if actual < lo:
            cost += 500.0 * ((lo - actual) * 100) ** 2
        elif actual > hi:
            cost += 500.0 * ((actual - hi) * 100) ** 2

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
    # v6: uniformity penalty bumped 40 → 3000. With family_share at 500
    # contributing 1.8M+ when off-band by 6pp, 1000 was still drowned.
    # 3000 with 0.6 ratio violation → 1080 cost — competitive.
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
                cost += 3000.0 * (ratio - ratio_cap) ** 2

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

    # Per-pay frequency caps (e.g., max freq for over-frequent pays)
    pay_freq_caps = exp_targets.get("pay_freq_caps", {})
    for pid, max_freq in pay_freq_caps.items():
        actual_freq = pred.get("pay_hits", {}).get(pid, 0.0)
        if actual_freq > max_freq:
            rel_over = (actual_freq - max_freq) / max_freq
            cost += 1000.0 * (rel_over * 100) ** 2

    # Per-pay frequency TARGETS (goal-oriented bidirectional pull).
    # Use for pays that should be at SPECIFIC freq (not bounded by cap).
    # E.g., "grand should be normally hittable" → target ~1/720 mode 1.
    # Penalty quadratic on relative deviation from target. Pulls equally
    # from above and below — different from cap (one-sided ceiling).
    pay_freq_targets = exp_targets.get("pay_freq_targets", {})
    pay_freq_weight = exp_targets.get("pay_freq_targets_weight", 500.0)
    for pid, target in pay_freq_targets.items():
        actual_freq = pred.get("pay_hits", {}).get(pid, 0.0)
        if target > 0:
            rel_dev = (actual_freq - target) / target
            cost += pay_freq_weight * (rel_dev * 100) ** 2

    # v6: Bucket-level RTP share constraint (DESIGN.md §7 player tier intent).
    # Family-share alone is blind to WITHIN-bucket distribution — booster_alone
    # at 50% share could be 50% from 1× side-wild-alone (Low feel-bad bucket)
    # OR 50% from 100× grand-alone (High session-memory bucket). Bucket targets
    # supplement family share by directly constraining the player's felt tier
    # distribution.
    bucket_targets = exp_targets.get("bucket_rtp_share_targets", {})
    bucket_weight = exp_targets.get("bucket_share_weight", 0.0)
    if bucket_targets and bucket_weight > 0:
        bucket_rtp = pred.get("bucket_rtp", {})
        rtp_total = pred["rtp_pct"] / 100.0
        if rtp_total > 0:
            for tier_name, target_share in bucket_targets.items():
                keys = TIER_TO_BUCKETS.get(tier_name, ())
                actual_rtp = sum(bucket_rtp.get(k, 0.0) for k in keys)
                actual_share = actual_rtp / rtp_total
                dev = actual_share - target_share
                cost += bucket_weight * (dev * 100) ** 2

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

    # Top jackpot 1000× minimum spin gap (one-sided cap: too frequent = bad)
    top_jackpot_min_spins = exp_targets.get("top_jackpot_min_spins")
    p_top = (
        (marg[0].get("high7", 0) + marg[0].get("wild", 0))
        * marg[1].get("grand", 0)
        * (marg[2].get("high7", 0) + marg[2].get("wild", 0))
    )
    if top_jackpot_min_spins is not None:
        max_p = 1.0 / top_jackpot_min_spins
        if p_top > max_p:
            rel_over = (p_top - max_p) / max_p
            cost += 1500.0 * (rel_over * 100) ** 2
    # v6: top jackpot 1000× MAX spin gap (one-sided floor: too rare = bad).
    # DESIGN.md §3 Top tier intent = "legendary moment / advertising hook —
    # 玩家会记住". 1/300k+ effectively means never seen. Pull p_top up if
    # rarer than 1/max_spins so the legendary moment exists.
    top_jackpot_max_spins = exp_targets.get("top_jackpot_max_spins")
    if top_jackpot_max_spins is not None:
        min_p = 1.0 / top_jackpot_max_spins
        if 0 < p_top < min_p:
            rel_under = (min_p - p_top) / min_p
            cost += 1500.0 * (rel_under * 100) ** 2

    # Top-jackpot freq match — direct expression of "mode 7 中/大/顶奖击中率不变"
    # design intent (per project_slot_designer.md §D hit rate deviation rules).
    # Without this, frozen big-win weights don't guarantee frozen P(top) because
    # mode 7's R1/R3 total weight differs from mode 1 (bar cuts + asymmetric
    # blank floor) → density-based 顶奖 path freq drifts.
    # Goal-oriented soft penalty: 0 cost when ratio ≈ 1.0; quadratic on
    # log-ratio so over/under symmetric.
    top_jackpot_freq_target_ref = exp_targets.get("top_jackpot_freq_target_ref")
    if top_jackpot_freq_target_ref is not None and p_top > 1e-12:
        log_ratio = abs((p_top / top_jackpot_freq_target_ref) - 1.0)
        # tolerance: 5pp deviation = 0.05 → cost 1000 × 5 = 5000 (significant)
        # tighter would dominate other goals; this lets RTP/hit also influence
        cost += 1000.0 * (log_ratio * 100) ** 2

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
            # Compute mode 1's actual P(top jackpot) from its weights — pass as
            # tune target to keep mode 7 顶奖击中率 ≈ mode 1's (per design intent
            # "中/大/顶奖击中率不变"). Without this, frozen big-win weights guarantee
            # nothing for P(top) which is multi-reel density product → R1/R3 total
            # weight drift drags it down (or up).
            def _compute_p_top_m1(m1_weights):
                # build per-reel density for high7+wild on R1+R3, grand on R2
                m1_strip = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
                p_per = []
                for r_idx, reel in enumerate(m1_strip):
                    counts = defaultdict(int)
                    for pos, sym in enumerate(reel):
                        w = m1_weights.get((sym, r_idx))
                        if w is None:
                            continue
                        counts[sym] += w
                    total = sum(counts.values())
                    if r_idx in (0, 2):
                        p_per.append((counts.get("high7", 0) + counts.get("wild", 0)) / total)
                    else:
                        p_per.append(counts.get("grand", 0) / total)
                return p_per[0] * p_per[1] * p_per[2]
            p_top_m1 = _compute_p_top_m1(mode1_all_weights)
            # Inject as exp_targets for this run (don't mutate global dict)
            exp_targets = dict(exp_targets)
            exp_targets["top_jackpot_freq_target_ref"] = p_top_m1
            print(f"\n=== Mode {mode}: bars [m1*0.65, m1*0.95] uniform; big-win frozen=m1; blank>=m1; top-jackpot freq target = m1's P_top {p_top_m1:.6e} (1 in {1/p_top_m1:.0f}) ===")
        elif mode == 5 and mode2_all_weights is not None:
            # Mode 5 super-lucky design: m2 base + 倍率 wild boost (grand + major).
            # Per memory project_slot_designer.md (§C mode RTP):
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
            #
            # 2026-04-29 (post-WORKFLOW.md adversarial review): blank UNFROZEN
            # in narrow band [m2 blank - 2, m2 blank]. Reason: grand × 6 expands
            # R2 total weight by ~5 units → R2 booster densities (mini/minor/
            # major) drop ~1% vs mode 2 → wild_amp pays (102/103/104) m5/m2
            # ratio 0.99 < 1.0, violating LUCKY-MONO design intent
            # ("super-lucky m5 ≥ m2 monotonic"). Letting blank drop slightly
            # compensates: optimizer can lower R2 blank weight 15 → 13-14 to
            # bring R2 total back to / below mode 2 487 → booster densities
            # rise → wild_amp ratios ≥ 1.0. Verify hit/RTP within band.
            # 2026-04-29 v5: redesign mode 5 derivation for grand-signature design.
            # Old: grand weight ≥ max(6, m2_grand × 6) — works when m2_grand=1, but
            # with v5 m2_grand 5+, × 6 = 30+ overshoots (RTP 1200%+).
            # New: grand weight FREE (let optimizer find via pay_freq_target 0.025);
            # all other R2 weights frozen = m2; blank narrow band as before.
            # bars + wild + high7 still frozen (mode 5 = m2 base + grand-only buff).
            FROZEN_FOR_M5 = (
                BAR_KEYS    # all bars (1bar/2bar/3bar/7bar)
                + [("wild", r) for r in (0, 2)]    # wild
                + [("high7", r) for r in range(3)]    # high7
                + [(b, 1) for b in ("mini", "minor", "major")]    # all boosters except grand
                # NOTE: blank + grand NOT in frozen list — see comment above
            )
            frozen_weights = {k: mode2_all_weights[k] for k in FROZEN_FOR_M5 if k in mode2_all_weights}
            weight_floors = {}
            weight_ceilings = {}
            # Grand: FREE within weight bounds, pulled by pay_freq_targets (1/40 m5)
            # Floor = m2 grand (must be ≥ m2's, super-lucky monotonic LUCKY-MONO rule)
            grand_key = ("grand", 1)
            if grand_key in mode2_all_weights:
                weight_floors[grand_key] = mode2_all_weights[grand_key]
            # Blank in narrow band [m2 blank - 3, m2 blank + 1] — wider than before
            # to absorb grand expansion (grand boosts R2 total by ~5-10 weight).
            for k in BLANK_KEYS:
                if k in mode2_all_weights:
                    m2_b = mode2_all_weights[k]
                    weight_floors[k] = max(1, m2_b - 3)
                    weight_ceilings[k] = m2_b + 1
            print(f"\n=== Mode {mode}: frozen=m2 except grand (floor=m2_grand, freq target 1/40) + blank ∈ [m2-3, m2+1] ===")
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
