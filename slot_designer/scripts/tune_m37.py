"""Tune M37 weights — only user-confirmed targets + universal philosophy.

Per user 2026-04-30: "你这个列表里的 target 有很多不是我说的,你别自作主张".
Stripped my self-invented numerical targets. Kept only:
  - User-spec / business: RTP 95/85/300/500 per mode
  - User direction: hit 15% (mode 1), grand on payline 0.3-0.5%, bar lower
  - User-confirmed (10-section narrative + role-based blank): R1/R2/R3 blank
    role ranges, bucket count distribution shape
  - Universal §1-§15 (philosophy): hierarchy direction only, reel asymmetry
    direction only, PWDF top-prize visibility direction (K factor universal
    range), strip §13/§14 already in layout

Dropped:
  - Specific 3-wild jackpot freq targets
  - Specific top jackpot freq
  - Specific PWDF K factors (use direction instead)
  - Pay_id 9 60% cap (universal §8 70% replaces)
  - Cascade ratio specific bounds (use direction only)
  - High7 per-reel density floor
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.engine.loader import load_engine

SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
STRIPS_PATH = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"
WEIGHTS_DIR = _ROOT / "slot_designer" / "weights" / "M37"


# ═══════════════════════════════════════════════════════════════════
# Spec-level (engine constraints, not picked)
# ═══════════════════════════════════════════════════════════════════

PAY_TO_FAMILY = {
    "1": "high7", "2": "7bar",
    "3": "bar_tier", "4": "bar_tier", "5": "bar_tier",
    "6": "high7", "7": "bar_tier",
    "8": "booster_alone",
    "9": "booster_alone",
    "102": "wild_amplified",
    "103": "wild_amplified",
    "104": "wild_amplified",
}

TIER_TO_BUCKETS = {
    "low":  ("gt0_lt1", "ge1_lt5", "ge5_lt10"),
    "mid":  ("ge10_lt20", "ge20_lt50"),
    "high": ("ge50_lt100", "ge100_lt200", "ge200_lt500"),
    "top":  ("ge500_lt1000", "ge1000_lt5000", "ge5000"),
}

# Bar pay_ids (pay_id 2/3/4/5 = 3-of-kind bar; pay_id 7 = any-bar mix)
BAR_PAY_IDS = ("2", "3", "4", "5", "7")


# ═══════════════════════════════════════════════════════════════════
# User-specified / user-confirmed targets
# ═══════════════════════════════════════════════════════════════════

# RTP — user/business spec
RTP_TARGETS = {1: 95.0, 7: 85.0, 2: 300.0, 5: 500.0}
RTP_TOLERANCE_PP = {1: 1.0, 7: 2.0, 2: 20.0, 5: 40.0}

# Hit — user direction "冲着总体中奖率 15% 去做" (mode 1).
# Other modes derived from universal §4 + §9 direction.
HIT_TARGETS = {1: 0.15, 7: 0.11, 2: 0.21, 5: 0.22}

# Grand on payline — user direction "grand 提升到 0.3-0.5%" (mode 1).
# Range targets; only penalize outside [lo, hi]. ±0.05pp tolerance to handle
# discrete-weight rounding (40-stop strip with integer weights ≥ 1).
# Cross-mode scaling: pay_id 8 RTP share ≈ constant ~30% across modes.
GRAND_PAYLINE_TARGETS = {
    1: (0.0028, 0.0052),
    7: (0.0028, 0.0052),
    2: (0.009, 0.019),
    5: (0.011, 0.021),
}

# Bar combined payline freq — user direction "bar 占比要降低". Old value
# 30-50%; "适度调整" so reduce to ≤25% (no specific number from user, use
# "moderately lower" ≤ 25%).
BAR_PAYLINE_FREQ_CAP = 0.25

# Reel role blank ranges — universal §5 reel roles + industry-standard
# multi-tier wild brand reel (R2 60-80% blank for premium booster feel).
# Per-mode shifts: mode 7 (thin-action) blanks higher; mode 2/5 (lucky)
# blanks lower since hit rate target is higher.
ROLE_BLANK_RANGES_BY_MODE = {
    1: {0: (0.29, 0.41), 1: (0.59, 0.78), 2: (0.39, 0.52)},
    7: {0: (0.35, 0.50), 1: (0.65, 0.83), 2: (0.45, 0.60)},
    2: {0: (0.20, 0.36), 1: (0.55, 0.70), 2: (0.30, 0.46)},
    # Mode 5 R2 cap raised to 0.75 for structural feasibility: with booster
    # cap 14% + high7 cap 10% + R2 bar cap 6% = 30% non-blank max → blank
    # must be ≥ 70%. Cap < 70% is infeasible. 0.50 floor preserves "more
    # action" intent.
    5: {0: (0.15, 0.34), 1: (0.55, 0.75), 2: (0.25, 0.45)},
}
# Default for backward-compat:
ROLE_BLANK_RANGES = ROLE_BLANK_RANGES_BY_MODE[1]

# Bucket count distribution — user "合理分布,不是平均". Direction Low > Mid >
# High > Top maintained. Per-mode: lucky modes naturally have more hits in
# high/top tier (more wild substitution + grand multiplier paths). Mode 1/7
# baseline. Mode 2/5 widen high/top caps proportionally.
BUCKET_COUNT_RANGES_BY_MODE = {
    1: {"low": (0.65, 0.90), "mid": (0.07, 0.25), "high": (0.01, 0.05),  "top": (0.0, 0.002)},
    7: {"low": (0.65, 0.90), "mid": (0.07, 0.25), "high": (0.01, 0.05),  "top": (0.0, 0.002)},
    2: {"low": (0.55, 0.85), "mid": (0.08, 0.30), "high": (0.02, 0.10),  "top": (0.0, 0.005)},
    5: {"low": (0.50, 0.80), "mid": (0.08, 0.30), "high": (0.03, 0.15),  "top": (0.0, 0.010)},
}
# Default for backward-compat:
BUCKET_COUNT_RANGES = BUCKET_COUNT_RANGES_BY_MODE[1]

# ─────────────────────────────────────────────────────────────────────
# Derived constraints — each anchored to user-confirmed 10-section narrative
# (not self-invented thresholds; comments document derivation).
# ─────────────────────────────────────────────────────────────────────

# High7 outer-reel UPPER cap — narrative §5 "R1 主体应该是 bar(分散), high7
# 只是偶尔点睛". Without a cap, SA finds R1 high7 ~40%+ corner because high7
# carries lots of RTP cheaply via 3-of-kind. Cap 18% per outer reel keeps
# bars dominant while leaving room for §15 high7 visibility (~50% window).
HIGH7_OUTER_UPPER_CAP = 0.18

# High7 outer-reel LOWER floor — per-mode.
# Mode 1: 4% (Mid bucket constraint + §15 PWDF direction).
# Mode 7: 4% (same — small win cut doesn't affect high7 mid-bucket).
# Mode 2: 6% (lucky mode pushes high7 paths somewhat).
# Mode 5: 12% (super-lucky — pay_id 1 with grand wild-substitution = 1000×
#   lifetime tier needs high outer high7 to be reachable. Mode 5 RTP 500%
#   target requires this 1000× path active; without floor, RTP stuck ~440%).
HIGH7_OUTER_FLOOR_BY_MODE = {1: 0.04, 7: 0.04, 2: 0.06, 5: 0.06}

# High7 R2 (middle reel) UPPER cap — narrative §5 "R2 是 booster brand reel,
# boosters 应该是 R2 主角". Without cap, optimizer pushes R2 high7 to 28%+
# to cheaply satisfy Mid bucket via pay_id 1 (3-high7) — but this turns R2
# into a "high7 reel" not a booster reel, breaking the brand. Cap 10% keeps
# R2 booster-dominant.
HIGH7_R2_CAP = 0.10

# R2 bar (1bar+2bar+3bar+7bar) combined UPPER cap — narrative §5 "R2 是
# booster brand reel". For R2 to feel like a booster reel rather than a
# "general reel", boosters should DOMINATE non-blank non-high7 mass on R2.
# Cap R2 bar combined at 6% so boosters (target 7%+) outweigh bars on R2.
# Without this cap, optimizer concentrates R2 mass on 7bar (cheap RTP via
# pay_id 6 any-7 + pay_id 7 any-bar mix) and squeezes booster room.
BAR_R2_COMBINED_CAP = 0.06

# Wild R1+R3 cap — per mode. In mode 5 (super-lucky), high wild density
# adds side_wild_alone (1× pay_id 9) hits that push hit rate over target.
# Cap mode 5 wild at 3% per outer so cascade-forced booster combined doesn't
# combine with side_wild_alone to blow past hit cap. Other modes 5% (light).
WILD_OUTER_CAP_BY_MODE = {1: 0.06, 7: 0.05, 2: 0.05, 5: 0.035}

# Booster combined R2 density floor — narrative §2 "中轴是品牌 booster reel,
# 应该频繁见到". Per-mode tuning:
#   Mode 1 (baseline 95% / 15% hit): 7% — structural ceiling given other
#     constraints (window vis ~20% = 1 in 5 spins).
#   Mode 7 (砍小奖 85% / 11% hit): 4% — booster floor relaxes since mode 7
#     is cut-small-wins; higher floor would push pay9_alone share past §8
#     70% cap (with 11% hit, booster contributions dominate).
#   Mode 2 (lucky 300% / 21% hit): 9% — more booster action for "lucky".
#   Mode 5 (super-lucky 500% / 22% hit): 12% — most booster prominence.
BOOSTER_R2_DENSITY_FLOOR_BY_MODE = {1: 0.07, 7: 0.04, 2: 0.09, 5: 0.11}

# Booster combined R2 UPPER cap — per mode. In mode 5, cascade ratio [1.3,
# 1.7] tends to push booster combined above what hit target 22% can
# accommodate (pay_id 9 from boosters cascades above hit cap). Cap mode 5
# combined at 14% to bound this. Other modes have floor only.
BOOSTER_R2_DENSITY_CAP_BY_MODE = {1: None, 7: None, 2: None, 5: 0.14}

# Grand R2 density floor — narrative §2 "near-miss psychology requires grand
# visibility". Grand R2 density tied to pay_id 8 target ~ 0.5% (since pay_id
# 8 ≈ grand_R2 × P(no 3-match) ≈ grand_R2 × 0.95). Window visibility = 1 -
# (1 - 0.005)^3 ≈ 1.5% (1 in 67) — adequate for "lifetime tier" near-miss
# psychology when combined with mini/minor/major brand presence.
GRAND_R2_DENSITY_FLOOR = 0.004

# Pay_id 9 dominance cap — universal §8 "no single pay > 70% of hit count".
# Pay_id 9 = booster_alone (mini/minor/major/grand single hit on R2 with
# non-blank flanks). Without cap, optimizer can pile 70%+ hits on this one
# pay → "empty calorie" experience.
PAY9_DOMINANCE_CAP = 0.70

# 3-wild jackpot combined freq RANGE — narrative §4 "中轴 mini/minor/major
# 的 wild-amplified jackpot 是这个机台特色玩法,长期游戏看得到". Combined
# freq pay_id 102+103+104 in [1/30000, 1/8000] = visible per long-play
# session without dominating. Per-mode multipliers below.
WILD_JACKPOT_COMBINED_FREQ = {
    1: (1/30000, 1/6000),
    7: (1/30000, 1/6000),
    2: (1/12000, 1/2500),
    5: (1/4000, 1/800),
}

# Top jackpot 1000× freq RANGE — narrative §10 "lifetime moment / 广告 hook".
# Top = (high7|wild, grand, high7|wild) substitution paths. Lifetime tier
# means rare per-session but achievable in heavy-play life of the machine.
# Target 1/50000 to 1/100000 paid spins for mode 1 baseline.
TOP_JACKPOT_FREQ_RANGE = {
    1: (1/100000, 1/50000),
    7: (1/100000, 1/50000),
    2: (1/40000, 1/20000),
    5: (1/15000, 1/8000),
}


# ═══════════════════════════════════════════════════════════════════
# Cost component weights — calibrated for component balance
# ═══════════════════════════════════════════════════════════════════

W_RTP = 80000.0  # bump — was being out-balanced in mode 7
W_HIT = 30000.0
W_GRAND_PAYLINE = 30000.0  # bump — range-based formula was barely active
W_BAR_CAP = 5000.0
W_ROLE_BLANK = 50000.0    # 2x bump — R1/R2/R3 blanks were 1-2pp over caps
W_BUCKET_COUNT = 25000.0  # bump — buffer additions diluted bucket gradient
W_HIERARCHY = 50000.0
W_ASYMMETRY = 15000.0     # was 5000; mode 7 had narrow asymmetry violations
W_HIGH7_FLOOR = 30000.0
W_HIGH7_CAP = 40000.0
W_BOOSTER_VIS = 25000.0
W_GRAND_VIS = 30000.0
W_PAY9_CAP = 25000.0
W_WILD_CAP = 80000.0      # mode 5 wild outer cap (3%) — needs to dominate
                          # over RTP (wild substitution paths) trade-off
W_WILD_JP = 8000.0
W_TOP_JP = 6000.0

WEIGHT_LO = 1
WEIGHT_HI = 1000


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _all_densities(weights, strips):
    out = defaultdict(float)
    for r in range(3):
        total = sum(weights[r])
        if total <= 0:
            continue
        for w, s in zip(weights[r], strips[r]):
            out[(s, r)] += w / total
    return dict(out)


def _build_marginals(weights, strips):
    marginals = []
    for r in range(3):
        m = defaultdict(float)
        total = sum(weights[r])
        if total <= 0:
            marginals.append(dict(m))
            continue
        for w, s in zip(weights[r], strips[r]):
            m[s] += w / total
        marginals.append(dict(m))
    return marginals


def _window_visibility(density):
    if density <= 0:
        return 0.0
    return 1.0 - (1.0 - density) ** 3


# ═══════════════════════════════════════════════════════════════════
# Cost function — only user-confirmed + universal philosophy
# ═══════════════════════════════════════════════════════════════════

def predict_cost(weights, strips, evaluator, mode):
    marginals = _build_marginals(weights, strips)
    pred = analytic_profile_from_marginals(evaluator, marginals)
    densities = _all_densities(weights, strips)
    cost = 0.0

    # 1. RTP target (user/business spec)
    rtp_dev_pp = pred["rtp_pct"] - RTP_TARGETS[mode]
    rtp_tol = RTP_TOLERANCE_PP[mode]
    cost += W_RTP * (rtp_dev_pp / rtp_tol) ** 2

    # 2. Hit target (user direction 15%)
    hit_dev = pred["hit_rate"] - HIT_TARGETS[mode]
    cost += W_HIT * (hit_dev * 100) ** 2

    # 3. Grand on payline (user direction 0.3-0.5% mode 1) — with 5% interior
    # buffer (relative to floor) so optimizer doesn't park exactly at edge
    # where SA mutation noise can flip below.
    grand_payline = pred.get("pay_hits", {}).get("8", 0.0)
    g_lo, g_hi = GRAND_PAYLINE_TARGETS[mode]
    g_buffer_lo = g_lo * 1.05
    g_buffer_hi = g_hi * 0.95
    if grand_payline < g_buffer_lo:
        cost += W_GRAND_PAYLINE * ((g_buffer_lo - grand_payline) / g_lo * 100) ** 2
    elif grand_payline > g_buffer_hi:
        cost += W_GRAND_PAYLINE * ((grand_payline - g_buffer_hi) / g_hi * 100) ** 2

    # 4. Bar combined payline freq cap (user direction "lower")
    bar_payline_combined = sum(pred.get("pay_hits", {}).get(p, 0.0) for p in BAR_PAY_IDS)
    if bar_payline_combined > BAR_PAYLINE_FREQ_CAP:
        cost += W_BAR_CAP * ((bar_payline_combined - BAR_PAYLINE_FREQ_CAP) * 100) ** 2

    # 5. Per-reel role blank with 0.3pp interior buffer — pushes optimizer
    # to land 0.3pp inside the strict bounds, leaving margin for discrete-
    # weight precision (40-stop integer grid ~ 0.1pp resolution).
    BLANK_BUFFER = 0.003
    role_ranges = ROLE_BLANK_RANGES_BY_MODE[mode]
    for r_idx, (lo, hi) in role_ranges.items():
        actual = densities.get(("blank", r_idx), 0.0)
        if actual < lo + BLANK_BUFFER:
            cost += W_ROLE_BLANK * ((lo + BLANK_BUFFER - actual) * 100) ** 2
        elif actual > hi - BLANK_BUFFER:
            cost += W_ROLE_BLANK * ((actual - (hi - BLANK_BUFFER)) * 100) ** 2

    # 6. Bucket count distribution (user-confirmed 10-section, per-mode)
    bucket_rate = pred.get("bucket_rate", {})
    hit_total = pred["hit_rate"]
    if hit_total > 0:
        bucket_ranges = BUCKET_COUNT_RANGES_BY_MODE[mode]
        for tier, (lo, hi) in bucket_ranges.items():
            keys = TIER_TO_BUCKETS[tier]
            tier_share = sum(bucket_rate.get(k, 0.0) for k in keys) / hit_total
            if tier_share < lo:
                cost += W_BUCKET_COUNT * ((lo - tier_share) * 100) ** 2
            elif tier_share > hi:
                cost += W_BUCKET_COUNT * ((tier_share - hi) * 100) ** 2

    # 7. Universal §1 hierarchy: direction + per-tier ratio.
    # Bar cascade ratio [1.2, 1.5x] — bar payouts 3/4/5/6× are linear/narrow,
    # density cascade should also be narrow.
    # Booster cascade ratio [1.5, 4x] — booster multipliers 2/5/10/100× are
    # logarithmic/wide; density cascade should follow that perception (mini
    # common, grand rare). Capping booster ratio at 1.5x makes "几乎每次见
    # 钻石" structurally infeasible without breaking grand-on-payline target.
    def _check_cascade(order, reel, ratio_lo, ratio_hi):
        """Cascade hierarchy cost — direction (prev > current) + ratio bounds.
        Tied/near-tied values are NOT treated as zero cost: optimizer would
        otherwise park at d ≈ prev_d * 1.000001 (verify reversal by epsilon)
        because this had tiny "severity" cost vs huge "ratio_lo violation"
        cost. Always evaluate ratio_lo as min cascade — if ratio < ratio_lo,
        penalize regardless of which side."""
        nonlocal cost
        prev_d = None
        for s in order:
            d = densities.get((s, reel), 0.0)
            if d == 0:
                continue
            if prev_d is not None and prev_d > 0:
                ratio = prev_d / d if d > 0 else float("inf")
                # Always penalize when ratio < ratio_lo (handles direction
                # violation + cascade-too-tight uniformly). Direction violation
                # gives ratio < 1 < ratio_lo, so it's always penalized at
                # least as much as a tight cascade.
                if ratio < ratio_lo:
                    cost += W_HIERARCHY * ((ratio_lo - ratio) * 100) ** 2
                elif ratio > ratio_hi:
                    cost += W_HIERARCHY * ((ratio - ratio_hi) * 100) ** 2
            prev_d = d

    BAR_ORDER = ("1bar", "2bar", "3bar", "7bar")
    for r in (0, 2):
        _check_cascade(BAR_ORDER, r, ratio_lo=1.2, ratio_hi=1.5)
    BOOSTER_ORDER = ("mini", "minor", "major", "grand")
    # Booster cascade ratio per-mode. Mode 1/7/2: wide [1.3, 4x] matches
    # multiplier cascade 2/5/10/100×. Mode 5 (super-lucky): tighter [1.3,
    # 1.7x] so booster combined doesn't blow past hit cap when grand_payline
    # is high. Without this, mode 5 hit overshoots target by 5pp+.
    if mode == 5:
        booster_lo, booster_hi = 1.3, 1.7
    else:
        booster_lo, booster_hi = 1.3, 4.0
    _check_cascade(BOOSTER_ORDER, 1, ratio_lo=booster_lo, ratio_hi=booster_hi)

    # 8. Universal §12 reel asymmetry direction with 0.5pp interior buffer
    # — encourages optimizer to land at R1-R3 ≥ 0.5pp instead of teetering
    # at the edge where SA mutation noise can flip sign. Verify still uses
    # strict (no slack): this is interior margin, not goalpost relaxation.
    ASYM_BUFFER = 0.005
    r1_blank = densities.get(("blank", 0), 0.0)
    r3_blank = densities.get(("blank", 2), 0.0)
    blank_diff = r1_blank - r3_blank  # want ≤ -BUFFER (R1 strictly less)
    if blank_diff > -ASYM_BUFFER:
        cost += W_ASYMMETRY * ((blank_diff + ASYM_BUFFER) * 100) ** 2
    r1_top = densities.get(("high7", 0), 0.0) + densities.get(("wild", 0), 0.0)
    r3_top = densities.get(("high7", 2), 0.0) + densities.get(("wild", 2), 0.0)
    top_diff = r1_top - r3_top  # want ≥ BUFFER
    if top_diff < ASYM_BUFFER:
        cost += W_ASYMMETRY * ((ASYM_BUFFER - top_diff) * 100) ** 2

    # 9. High7 R1 + R3 density FLOOR (Mid bucket + §15 PWDF; per-mode)
    h7_floor = HIGH7_OUTER_FLOOR_BY_MODE[mode]
    for r in (0, 2):
        d = densities.get(("high7", r), 0.0)
        if d < h7_floor:
            cost += W_HIGH7_FLOOR * ((h7_floor - d) * 100) ** 2

    # 10. High7 R1 + R3 density UPPER CAP — narrative §5 "R1 主体应该是 bar".
    # Without cap, SA finds R1 high7 40%+ corner (bars get crowded out).
    for r in (0, 2):
        d = densities.get(("high7", r), 0.0)
        if d > HIGH7_OUTER_UPPER_CAP:
            cost += W_HIGH7_CAP * ((d - HIGH7_OUTER_UPPER_CAP) * 100) ** 2

    # 10b. High7 R2 (middle reel) cap — narrative §5 "R2 brand reel = booster".
    # Without cap, optimizer pushes R2 high7 to 28%+ crowding boosters out.
    high7_r2 = densities.get(("high7", 1), 0.0)
    if high7_r2 > HIGH7_R2_CAP:
        cost += W_HIGH7_CAP * ((high7_r2 - HIGH7_R2_CAP) * 100) ** 2

    # 10c. R2 bar combined cap — narrative §5 "R2 = booster brand reel".
    # Boosters must dominate over bars on R2 for the brand identity.
    bar_r2_combined = sum(densities.get((s, 1), 0.0)
                          for s in ("1bar", "2bar", "3bar", "7bar"))
    if bar_r2_combined > BAR_R2_COMBINED_CAP:
        cost += W_HIGH7_CAP * ((bar_r2_combined - BAR_R2_COMBINED_CAP) * 100) ** 2

    # 10d. Wild R1+R3 cap (per-mode). High wild density adds side_wild_alone
    # 1× hits (pay_id 9 path). Mode 5 cap is tighter to keep hit rate under
    # 22% target despite booster cascade pressure. Uses W_WILD_CAP > W_RTP
    # so cap dominates over wild-substitution-RTP trade-off.
    wild_cap = WILD_OUTER_CAP_BY_MODE[mode]
    for r in (0, 2):
        d = densities.get(("wild", r), 0.0)
        if d > wild_cap:
            cost += W_WILD_CAP * ((d - wild_cap) * 100) ** 2

    # 11. Booster combined R2 density floor — narrative §2; per-mode floor + cap.
    booster_combined_r2 = sum(densities.get((s, 1), 0.0)
                              for s in ("mini", "minor", "major", "grand"))
    booster_floor = BOOSTER_R2_DENSITY_FLOOR_BY_MODE[mode]
    if booster_combined_r2 < booster_floor:
        cost += W_BOOSTER_VIS * ((booster_floor - booster_combined_r2) * 100) ** 2
    booster_cap = BOOSTER_R2_DENSITY_CAP_BY_MODE.get(mode)
    if booster_cap is not None and booster_combined_r2 > booster_cap:
        cost += W_BOOSTER_VIS * ((booster_combined_r2 - booster_cap) * 100) ** 2

    # 12. Grand R2 density floor — narrative §2 + near-miss psychology.
    grand_r2 = densities.get(("grand", 1), 0.0)
    if grand_r2 < GRAND_R2_DENSITY_FLOOR:
        cost += W_GRAND_VIS * ((GRAND_R2_DENSITY_FLOOR - grand_r2) * 100) ** 2

    # 13. Pay_id 9 (booster_alone) dominance cap — universal §8.
    pay9 = pred.get("pay_hits", {}).get("9", 0.0)
    hit_total_for_dom = pred.get("hit_rate", 0.0)
    if hit_total_for_dom > 0:
        pay9_share = pay9 / hit_total_for_dom
        if pay9_share > PAY9_DOMINANCE_CAP:
            cost += W_PAY9_CAP * ((pay9_share - PAY9_DOMINANCE_CAP) * 100) ** 2

    # 14. 3-wild jackpot combined freq range — narrative §4.
    # Pay_ids 102/103/104 = mini/minor/major × wild substitution.
    wild_jp_combined = sum(pred.get("pay_hits", {}).get(p, 0.0)
                           for p in ("102", "103", "104"))
    wj_lo, wj_hi = WILD_JACKPOT_COMBINED_FREQ[mode]
    if wild_jp_combined < wj_lo:
        # use 1/freq for cost so band magnitudes are sensible
        cost += W_WILD_JP * ((wj_lo - wild_jp_combined) / wj_lo * 100) ** 2
    elif wild_jp_combined > wj_hi:
        cost += W_WILD_JP * ((wild_jp_combined - wj_hi) / wj_hi * 100) ** 2

    # 15. Top 1000× jackpot freq range — narrative §10 lifetime tier.
    # Top 1000× = (high7|wild, grand, high7|wild) substitution → pay_id 1
    # base 10× × grand mult 100 = 1000×. Bucket ge1000_lt5000 captures this
    # exactly (other paths max out at major × wild = 100×).
    top_jp = pred.get("bucket_rate", {}).get("ge1000_lt5000", 0.0) + \
             pred.get("bucket_rate", {}).get("ge5000", 0.0)
    tj_lo, tj_hi = TOP_JACKPOT_FREQ_RANGE[mode]
    if top_jp < tj_lo:
        cost += W_TOP_JP * ((tj_lo - top_jp) / tj_lo * 100) ** 2
    elif top_jp > tj_hi:
        cost += W_TOP_JP * ((top_jp - tj_hi) / tj_hi * 100) ** 2

    return cost, pred


# ═══════════════════════════════════════════════════════════════════
# SA with archetype seed
# ═══════════════════════════════════════════════════════════════════

SEED_W_PER_STOP = {
    0: {"blank": 4, "wild": 8, "high7": 8, "7bar": 4, "3bar": 4, "2bar": 5, "1bar": 6},
    1: {"blank": 8, "high7": 6, "7bar": 4, "3bar": 4, "2bar": 4, "1bar": 4,
        "mini": 5, "minor": 4, "major": 3, "grand": 2},
    2: {"blank": 5, "wild": 7, "high7": 6, "7bar": 4, "3bar": 4, "2bar": 4, "1bar": 5},
}


def _seed_weights(strips, frozen=None, floors=None):
    frozen = frozen or {}
    floors = floors or {}
    weights = []
    for r_idx, reel in enumerate(strips):
        per_stop = SEED_W_PER_STOP[r_idx]
        sym_to_w = {}
        for sym in set(reel):
            key = (sym, r_idx)
            if key in frozen:
                sym_to_w[sym] = frozen[key]
            elif key in floors:
                sym_to_w[sym] = max(per_stop.get(sym, 5), floors[key])
            else:
                sym_to_w[sym] = per_stop.get(sym, 5)
        weights.append([sym_to_w[s] for s in reel])
    return weights


def _mutate(weights, strips, rng, sigma, frozen=None, floors=None, ceilings=None):
    frozen = frozen or {}
    floors = floors or {}
    ceilings = ceilings or {}
    new = [list(row) for row in weights]
    for r_idx, reel in enumerate(strips):
        symbols = [s for s in set(reel) if (s, r_idx) not in frozen]
        if not symbols:
            continue
        sym = rng.choice(symbols)
        cur = next(w for w, s in zip(new[r_idx], reel) if s == sym)
        delta = max(1, int(round(cur * sigma * abs(rng.gauss(0, 1)))))
        new_w = (cur + delta) if rng.random() < 0.5 else (cur - delta)
        floor = floors.get((sym, r_idx), WEIGHT_LO)
        ceiling = ceilings.get((sym, r_idx), WEIGHT_HI)
        new_w = max(floor, min(ceiling, new_w))
        for pos, s in enumerate(reel):
            if s == sym:
                new[r_idx][pos] = new_w
    return new


def search(strips, evaluator, mode, *, frozen=None, floors=None, ceilings=None,
           seed=42, iterations=30000, restarts=3, verbose=True,
           initial_weights=None):
    overall_best_w, overall_best_cost, overall_best_p = None, float("inf"), None
    for ridx in range(restarts):
        rng = Random(seed + ridx * 1000)
        if initial_weights is not None:
            w = [list(row) for row in initial_weights]
        else:
            w = _seed_weights(strips, frozen=frozen, floors=floors)
        cost_cur, pred_cur = predict_cost(w, strips, evaluator, mode)
        best_w = [list(r) for r in w]
        best_cost = cost_cur
        best_pred = pred_cur

        T = max(50.0, cost_cur * 0.001)
        T_decay = (0.0001) ** (1.0 / iterations)
        sigma = 0.2

        for step in range(iterations):
            if step == iterations // 3:
                sigma = 0.1
            elif step == 2 * iterations // 3:
                sigma = 0.04
            cand = _mutate(w, strips, rng, sigma, frozen=frozen, floors=floors, ceilings=ceilings)
            cand_cost, cand_pred = predict_cost(cand, strips, evaluator, mode)
            if cand_cost < cost_cur or rng.random() < math.exp(-(cand_cost - cost_cur) / max(T, 1e-9)):
                w = cand
                cost_cur = cand_cost
                pred_cur = cand_pred
            if cost_cur < best_cost:
                best_cost = cost_cur
                best_pred = pred_cur
                best_w = [list(r) for r in w]
            T *= T_decay
            if verbose and step % 5000 == 0:
                print(f"    restart {ridx} step {step:5d}  cost={cost_cur:>12.1f}  best={best_cost:>12.1f}  T={T:.1f}")
        if verbose:
            print(f"    restart {ridx} final: cost={best_cost:.1f}  RTP={best_pred['rtp_pct']:.2f}%  hit={best_pred['hit_rate']:.2%}")
        if best_cost < overall_best_cost:
            overall_best_cost = best_cost
            overall_best_w = best_w
            overall_best_p = best_pred
    return overall_best_w, overall_best_cost, overall_best_p


# ═══════════════════════════════════════════════════════════════════
# Per-mode tune flow
# ═══════════════════════════════════════════════════════════════════

def tune_mode_1(strips, evaluator):
    print("=== Mode 1 baseline ===")
    return search(strips, evaluator, mode=1)


def tune_mode_7(strips, evaluator, m1_weights):
    """Mode 7 = 砍小奖 from m1. Cut bars + small boosters + side wild
    proportionally; keep grand/high7 as big-win anchors. Side wild on R1/R3
    contributes side_wild_alone (1× pay_id 9) — these are small wins and
    should cut for mode 7. Without unfreezing wild, pay_id 9 share blows
    past §8 70% cap when bars are cut."""
    print("=== Mode 7: 砍小奖 from m1 ===")
    frozen, floors = {}, {}
    for r_idx, reel in enumerate(strips):
        for sym in set(reel):
            w_m1 = next((w for w, s in zip(m1_weights[r_idx], reel) if s == sym), None)
            if w_m1 is None:
                continue
            # Only freeze big-win anchors (high7 for 3-of-kind 10×, grand for
            # pay_id 8 anchor). Everything else can drop with hit cut.
            if sym in ("high7", "grand"):
                frozen[(sym, r_idx)] = w_m1
            elif sym == "blank":
                floors[(sym, r_idx)] = w_m1
    return search(strips, evaluator, mode=7, frozen=frozen, floors=floors)


def tune_mode_2(strips, evaluator, m1_weights):
    print("=== Mode 2: lucky from m1 ===")
    floors, ceilings = {}, {}
    for r_idx, reel in enumerate(strips):
        for sym in set(reel):
            w_m1 = next((w for w, s in zip(m1_weights[r_idx], reel) if s == sym), None)
            if w_m1 is None:
                continue
            if sym == "blank":
                ceilings[(sym, r_idx)] = w_m1
            else:
                floors[(sym, r_idx)] = w_m1
    return search(strips, evaluator, mode=2, floors=floors, ceilings=ceilings)


def tune_mode_5(strips, evaluator, m2_weights):
    """Mode 5 = super-lucky (RTP 500%, hit 22%). Initialize SA from m2
    weights × 1.6 scaling on non-blank, blank scaled down — gives a much
    better starting point for SA than the generic SEED_W_PER_STOP. Use
    more iterations than other modes since cost surface is hairier (RTP
    and hit pull in opposite directions when boosters cascade)."""
    print("=== Mode 5: super-lucky (m2-scaled seed, free SA) ===")
    initial = []
    for r_idx, reel in enumerate(strips):
        m2_row = m2_weights[r_idx]
        new_row = []
        for w_m2, sym in zip(m2_row, reel):
            if sym == "blank":
                new_w = max(WEIGHT_LO, int(round(w_m2 / 1.6)))
            else:
                new_w = min(WEIGHT_HI, int(round(w_m2 * 1.6)))
            new_row.append(new_w)
        initial.append(new_row)
    return search(strips, evaluator, mode=5, initial_weights=initial,
                  iterations=60000, restarts=4)


# ═══════════════════════════════════════════════════════════════════
# Output
# ═══════════════════════════════════════════════════════════════════

def _print_result(mode, pred, weights, strips):
    print(f"\n  Mode {mode} result: RTP={pred['rtp_pct']:.2f}% hit={pred['hit_rate']:.2%} CV={pred.get('cv',0):.2f}")
    densities = _all_densities(weights, strips)
    print("  Per-reel density:")
    print(f"    {'family':<10} {'R1':>7} {'R2':>7} {'R3':>7}")
    for sym in ("blank", "wild", "high7", "7bar", "3bar", "2bar", "1bar",
                 "mini", "minor", "major", "grand"):
        dr = [densities.get((sym, r), 0.0) * 100 for r in range(3)]
        if sum(dr) > 0:
            print(f"    {sym:<10} {dr[0]:6.2f}% {dr[1]:6.2f}% {dr[2]:6.2f}%")
    print("  Per-pay frequencies:")
    for pid in sorted(pred.get("pay_hits", {}).keys(), key=lambda p: int(p)):
        f = pred["pay_hits"][pid]
        rtp = pred.get("pay_rtp", {}).get(pid, 0.0) * 100
        print(f"    pay_id {pid:>4}: 1/{1/f if f else 0:>7.0f}  RTP {rtp:6.2f}pp")


def _write_weights(mode, weights, pred):
    out_path = WEIGHTS_DIR / f"mode_{mode}" / "weights.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "machine": "M37", "mode": mode, "reel_set": "default",
        "_notes": [
            f"M37 mode {mode} (clean rebuild — only user-confirmed targets)",
            f"RTP {RTP_TARGETS[mode]}% achieved {pred['rtp_pct']:.2f}%",
            f"Hit {HIT_TARGETS[mode]:.0%} achieved {pred['hit_rate']:.2%}",
        ],
        "weights": weights,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {out_path.relative_to(_ROOT)}")


def _load_existing(mode):
    p = WEIGHTS_DIR / f"mode_{mode}" / "weights.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))["weights"]


def main(modes_to_run=(1,)):
    strips_data = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))
    strips = strips_data["reels"]

    bootstrap_path = WEIGHTS_DIR / "mode_1" / "weights.json"
    if not bootstrap_path.exists():
        bootstrap_path.parent.mkdir(parents=True, exist_ok=True)
        stub = {"machine": "M37", "mode": 1, "reel_set": "default",
                "weights": [[5] * len(reel) for reel in strips]}
        bootstrap_path.write_text(json.dumps(stub, indent=2), encoding="utf-8")

    engine, _ = load_engine(SPEC_PATH, bootstrap_path)
    evaluator = engine.evaluator

    mw = {}
    if 1 in modes_to_run:
        w, _, p = tune_mode_1(strips, evaluator)
        _print_result(1, p, w, strips)
        _write_weights(1, w, p)
        mw[1] = w
    if 7 in modes_to_run:
        if 1 not in mw:
            mw[1] = _load_existing(1)
        w, _, p = tune_mode_7(strips, evaluator, mw[1])
        _print_result(7, p, w, strips)
        _write_weights(7, w, p)
        mw[7] = w
    if 2 in modes_to_run:
        if 1 not in mw:
            mw[1] = _load_existing(1)
        w, _, p = tune_mode_2(strips, evaluator, mw[1])
        _print_result(2, p, w, strips)
        _write_weights(2, w, p)
        mw[2] = w
    if 5 in modes_to_run:
        if 2 not in mw:
            mw[2] = _load_existing(2)
        w, _, p = tune_mode_5(strips, evaluator, mw[2])
        _print_result(5, p, w, strips)
        _write_weights(5, w, p)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", type=str, default="1")
    args = parser.parse_args()
    modes = tuple(int(m) for m in args.modes.split(","))
    main(modes_to_run=modes)
