"""Tune M1 mode weights — player-experience direct objective.

Per ``project_slot_designer_axiom_experience_is_soul``: TDD numbers are
inspiration, not constraint. Cost function targets player experience red
lines (family RTP share, wild signature, per-reel density) directly.

Hard rules:
  - Paytable LOCKED
  - Physical Blank-non-Blank alternation LOCKED (in strip layout)
  - Mode RTP: 1=95%, 7=85% (standard); 2=300%, 5=500% (lucky)
  - Mode 7 = mode 1 - 砍小奖派生：大奖击中率/产出期望绝对不砍
    (Diamond/Seven family RTP contribution = mode 1's, ±0.6pp)

Player experience targets (Double Diamond signature, M1 specific):
  - Wild on payline P(>=1 wild) — see EXPERIENCE_TARGETS
  - Family RTP shares — band per mode
  - Per-reel per-family density — bounded to be视觉 reasonable

Parameterization (27-dim per mode):
  weights[reel r][pos p] = W[(family_at(r, p), r)]
  All positions of same family on same reel share one weight.

Search: random-restart local search with adaptive sigma. Cost combines
RTP/hit/bucket numeric targets with family share / wild signature /
density experience penalties (experience layered ON TOP of numeric).
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


SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
STRIPS_PATH = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"

SYMBOLS = ("Blank", "Diamond1", "Diamond2", "Seven1", "Seven2",
           "Cherry", "Bar1", "Bar2", "Bar3")

# Per-family per-reel weight bounds. Each is integer >= 1.
# Lower bound floor=1 means "family stays present, never zero out".
# Standard modes (1, 7) use tight bounds to preserve TDD-style classic feel.
# Lucky modes (2, 5) need wider upper bounds — particularly Seven family
# which is the "7-dominated" engine for the lucky/super-lucky feel.
WEIGHT_BOUNDS_STANDARD: dict[str, tuple[int, int]] = {
    "Blank":     (3, 30),
    "Diamond1":  (3, 12),
    "Diamond2":  (3, 12),
    "Seven1":    (1, 20),
    "Seven2":    (1, 20),
    "Cherry":    (1, 30),
    "Bar1":      (1, 30),
    "Bar2":      (1, 30),
    "Bar3":      (1, 30),
}

WEIGHT_BOUNDS_LUCKY: dict[str, tuple[int, int]] = {
    "Blank":     (1, 30),     # less filler, more pay in lucky modes
    "Diamond1":  (3, 18),
    "Diamond2":  (3, 18),
    "Seven1":    (1, 60),     # 7-dominated lucky engine
    "Seven2":    (1, 60),
    "Cherry":    (1, 40),
    "Bar1":      (1, 40),
    "Bar2":      (1, 40),
    "Bar3":      (1, 40),
}

WEIGHT_BOUNDS_BY_MODE = {
    1: WEIGHT_BOUNDS_STANDARD,
    7: WEIGHT_BOUNDS_STANDARD,
    2: WEIGHT_BOUNDS_LUCKY,
    5: WEIGHT_BOUNDS_LUCKY,
}

# Player experience targets — ground truth for "假但不怪".
# Sources: classic 1-line slot benchmarks (RWB/Blazing Sevens published
# data) + Double Diamond brand expectation + IGT TDD WoO data.
EXPERIENCE_TARGETS = {
    1: {
        # User: wild can drop further to release CV. Band 10-16% trades
        # signature for CV ~9 + RTP-strict 95%.
        "wild_on_payline_band": (0.10, 0.16),
        # Lower wild density naturally compresses Diamond family RTP
        # share. 5% floor keeps Diamond family present-but-not-dominant.
        "family_share_bands": {
            "Diamond": (0.05, 0.20),
            "Seven":   (0.12, 0.22),
            "Bar3":    (0.10, 0.20),
            "Bar2":    (0.10, 0.22),
            "Bar1":    (0.08, 0.18),
            "Cherry":  (0.08, 0.17),
        },
        # Per-family per-reel density caps — "假但不怪" boundary.
        # Visual mid-pay (Bar3/Bar2) ≤ 17% on any reel: > that and
        # player feels Bar3 dominates a reel which is不怪 territory.
        # Top-pay (Seven, Diamond) capped lower (rare-by-brand).
        # Filler-acceptable (Bar1, Cherry, Blank-implicit) higher.
        "per_reel_density_lo_by_family": {
            "Diamond1": 0.01, "Diamond2": 0.005,
            "Seven1": 0.01,  "Seven2": 0.005,  # raised to push more uniform
            "Bar3": 0.01, "Bar2": 0.01, "Bar1": 0.01,
            "Cherry": 0.01,
        },
        "per_reel_density_hi_by_family": {
            "Diamond1": 0.10, "Diamond2": 0.10,
            "Seven1": 0.12,  "Seven2": 0.12,
            "Bar3": 0.17, "Bar2": 0.17,
            "Bar1": 0.22, "Cherry": 0.20,
        },
        # Top-tier symbols (Seven/Diamond) should appear roughly
        # uniformly across reels (player perceives consistent brand).
        # Mid-pay (Bar) NOT in this dict — asymmetric Bar3 is the
        # intentional near-miss mechanism for 3-reel slots.
        "uniformity_ratio_cap": {
            "Seven1": 2.0, "Seven2": 2.0,
            "Diamond1": 2.0, "Diamond2": 2.0,
        },
        # Note: per_reel_blank_variance_strength only on lucky modes (2/5).
        # Standard modes (1/7) RTP target doesn't push optimizer toward
        # R-stuffing, so don't need it.
        "top_jackpot_max_spins": 300_000,
        "bucket_hit_floors": {
            "ge5_lt10":  0.008,
            "ge10_lt20": 0.010,
        },
        "cv_target": 9.0,
        # REEL-ASYMMETRY (Strickland/Reid/Harrigan universal rule).
        # R1 less blank than R3 (defends early rejection) + R1 top-prize
        # density ≥ R3 (creates near-miss on R3 when fails).
        "reel_asymmetry": {
            "blank_tol_pp": 0.03,    # R1 may exceed R3 Blank by ≤ 3pp
            "top_tol_pp": 0.01,      # R1 may fall below R3 top-prize by ≤ 1pp
            "blank_strength": 200.0,
            "top_strength": 200.0,
        },
        # R1 Blank 绝对 band — M1-specific design target (1-line classic):
        # 玩家从左到右扫，R1 Blank ≤ 40% 才有"winning visibility"; ≥ 30% 才不
        # 让中奖密度过头（R1 cherry/seven 视觉上需要"有空"才有 reveal drama）。
        # User-pinned 2026-04-28. NOT universal — multi-line / video slot 应
        # 重新校准（线越多 R1 blank 可越低）。
        "r1_blank_band": (0.30, 0.40),
        "r1_blank_strength": 300.0,
        # WINDOW-VISIBILITY: handled as post-tune optimization (see main()
        # PWDF sweep), not as in-tune cost. Floor 50% per DESIGN.md §2.
    },
    7: {
        "wild_on_payline_band": (0.10, 0.18),
        "per_reel_density_lo_by_family": {
            "Diamond1": 0.01, "Diamond2": 0.005,
            "Seven1": 0.01,  "Seven2": 0.005,
            "Bar3": 0.01, "Bar2": 0.01, "Bar1": 0.01,
            "Cherry": 0.01,
        },
        "per_reel_density_hi_by_family": {
            "Diamond1": 0.10, "Diamond2": 0.10,
            "Seven1": 0.12,  "Seven2": 0.12,
            "Bar3": 0.17, "Bar2": 0.17,
            "Bar1": 0.22, "Cherry": 0.20,
        },
        "uniformity_ratio_cap": {
            "Seven1": 2.0, "Seven2": 2.0,
            "Diamond1": 2.0, "Diamond2": 2.0,
        },
        "top_jackpot_max_spins": 300_000,
        # REEL-ASYMMETRY (mode 7 strict — "运气差 mode" 不能再 R1 早期拒绝).
        "reel_asymmetry": {
            "blank_tol_pp": 0.03,
            "top_tol_pp": 0.01,
            "blank_strength": 200.0,
            "top_strength": 200.0,
        },
        # R1 Blank band — mode 7 RTP=85% 物理约束 blank 整体偏高，但 R1 仍要
        # 防早期拒绝。R1 30-40% 跟 mode 1 一致（"运气差但不早期拒绝"）。
        # If 物理无法满足（mode 7 RTP 拉不下来），tune cost 会平衡。
        "r1_blank_band": (0.30, 0.40),
        "r1_blank_strength": 300.0,
        # WINDOW-VISIBILITY (PWDF): handled post-tune by redistribute_m1_blanks.py
        # (RTP-neutral, applied uniformly to all 4 modes from a tuned baseline).
    },
    2: {
        "wild_on_payline_band": (0.12, 0.25),
        "family_share_bands": {
            "Diamond": (0.04, 0.22),
            "Seven":   (0.35, 0.65),
            "Bar3":    (0.05, 0.20),
            "Bar2":    (0.05, 0.18),
            "Bar1":    (0.03, 0.15),
            "Cherry":  (0.03, 0.15),
        },
        "per_reel_density_lo_by_family": {
            "Diamond1": 0.01, "Diamond2": 0.005,
            "Seven1": 0.02,  "Seven2": 0.01,   # lucky has more presence
            "Bar3": 0.01, "Bar2": 0.01, "Bar1": 0.01,
            "Cherry": 0.01,
        },
        "per_reel_density_hi_by_family": {
            "Diamond1": 0.12, "Diamond2": 0.12,
            "Seven1": 0.18,  "Seven2": 0.18,
            "Bar3": 0.20, "Bar2": 0.20,
            "Bar1": 0.25, "Cherry": 0.22,
        },
        "uniformity_ratio_cap": {
            "Seven1": 2.5, "Seven2": 2.5,
            "Diamond1": 2.5, "Diamond2": 2.5,
        },
        # Per-reel Blank balance — variance penalty (goal-oriented soft).
        # Replaces hard "blank ≥ X%" floor (anti-pattern: arbitrary picked
        # number). Variance pulls toward 3 reels having similar Blank
        # density without specifying any number — gradient-friendly,
        # encodes goal "reels look alike to player" directly.
        "per_reel_blank_variance_strength": 6.0,
        "top_jackpot_max_spins": 300_000,
        # REEL-ASYMMETRY (lucky modes wider tolerance — high RTP dilutes
        # near-miss psychology, but direction must still hold).
        "reel_asymmetry": {
            "blank_tol_pp": 0.08,    # 8pp tolerance for lucky
            "top_tol_pp": 0.02,
            "blank_strength": 100.0,
            "top_strength": 100.0,
        },
        # R1 Blank band — mode 2 lucky 整体 blank 已低（~32%），保持在 30-40%。
        "r1_blank_band": (0.30, 0.40),
        "r1_blank_strength": 300.0,
        # WINDOW-VISIBILITY (PWDF): handled post-tune by redistribute_m1_blanks.py.
    },
    5: {
        "wild_on_payline_band": (0.12, 0.28),
        "family_share_bands": {
            "Diamond": (0.03, 0.25),
            "Seven":   (0.50, 0.80),
            "Bar3":    (0.03, 0.18),
            "Bar2":    (0.02, 0.12),
            "Bar1":    (0.01, 0.10),
            "Cherry":  (0.01, 0.10),
        },
        "per_reel_density_lo_by_family": {
            "Diamond1": 0.01, "Diamond2": 0.005,
            "Seven1": 0.03,  "Seven2": 0.02,
            "Bar3": 0.005, "Bar2": 0.005, "Bar1": 0.005,
            "Cherry": 0.005,
        },
        "per_reel_density_hi_by_family": {
            "Diamond1": 0.15, "Diamond2": 0.15,
            "Seven1": 0.22,  "Seven2": 0.22,
            "Bar3": 0.20, "Bar2": 0.20,
            "Bar1": 0.25, "Cherry": 0.22,
        },
        "uniformity_ratio_cap": {
            "Seven1": 2.5, "Seven2": 2.5,
            "Diamond1": 2.5, "Diamond2": 2.5,
        },
        # Per-reel Blank balance variance penalty (same goal as mode 2).
        "per_reel_blank_variance_strength": 6.0,
        "top_jackpot_max_spins": 300_000,
    },
}


# Map pay_id -> family for RTP share aggregation.
# Per spec/M1.spec.json:
#   Cherry: pay_id 12, 13, 14 (cherry_count)
#   Diamond/Wild: pay_id 2, 3, 4 (pure_wild + pure_wild_group)
#                  Note: pay_id 4 is rtp_excluded; included in family share
#                  computation only via direct hit, not RTP contribution.
#   Seven: pay_id 5 (Seven2x3), 6 (Seven1x3), 10 (line_3_group seven)
#   Bar3:  pay_id 7
#   Bar2:  pay_id 8
#   Bar1:  pay_id 9
#   Bar_group: pay_id 11 (line_3_group bar) — split evenly across Bar1/2/3 for share
PAY_TO_FAMILY: dict[str, str] = {
    "12": "Cherry", "13": "Cherry", "14": "Cherry",
    "2": "Diamond", "3": "Diamond", "4": "Diamond",
    "5": "Seven", "6": "Seven", "10": "Seven",
    "7": "Bar3",
    "8": "Bar2",
    "9": "Bar1",
    "11": "Bar_group",  # split below
}

PAY_MULTIPLIER: dict[str, float] = {
    "14": 1.0, "13": 2.0, "12": 10.0,
    "2": 500.0, "3": 300.0,  # weighted avg of 240 and 360 — close enough
    "4": 1000.0,
    "5": 50.0, "6": 40.0,
    "7": 20.0, "8": 15.0, "9": 10.0,
    "10": 25.0, "11": 5.0,
}


def family_rtp_breakdown(profile: dict, paytable: list[dict]) -> dict[str, float]:
    """Compute per-family absolute RTP contribution (in % points).

    Uses ``pay_rtp`` from analytic_profile (= prob × actual_multiplier_per_combo,
    which INCLUDES wild substitution boost). So Bar3×3 with one 2x wild
    contributes its full 40× to Bar3 family, not the base 20×.
    """
    rtp_excluded_pids = {str(p["pay_id"]) for p in paytable if p.get("rtp_excluded")}

    family_rtp: dict[str, float] = defaultdict(float)
    for pid, rtp_contrib in profile.get("pay_rtp", {}).items():
        if pid in rtp_excluded_pids:
            continue  # top jackpot doesn't count toward RTP
        family = PAY_TO_FAMILY.get(pid, "Unknown")
        if family == "Bar_group":
            for bar in ("Bar1", "Bar2", "Bar3"):
                family_rtp[bar] += rtp_contrib / 3
        else:
            family_rtp[family] += rtp_contrib

    # rtp_contrib is fractional (0-1 range); convert to RTP pp
    return {f: r * 100 for f, r in family_rtp.items()}


def wild_on_payline_p(reel_marginals: list[dict[str, float]]) -> float:
    """P(>=1 wild on payline). 1 - prod(1 - density of any Diamond per reel)."""
    p_no_wild_all = 1.0
    for marg in reel_marginals:
        p_wild_reel = marg.get("Diamond1", 0) + marg.get("Diamond2", 0)
        p_no_wild_all *= (1.0 - p_wild_reel)
    return 1.0 - p_no_wild_all


def top_jackpot_expected_spins(reel_marginals: list[dict[str, float]]) -> float:
    """Expected spins to hit Diamond2×3."""
    p = 1.0
    for marg in reel_marginals:
        p *= marg.get("Diamond2", 0)
    return float("inf") if p == 0 else 1.0 / p


def per_reel_family_density(weights: list[list[int]],
                            strip: list[list[str]]) -> dict[tuple[str, int], float]:
    """{(family, reel_idx): density}."""
    out: dict[tuple[str, int], float] = {}
    for r_idx, (rw, rs) in enumerate(zip(weights, strip)):
        total = sum(rw)
        family_w: dict[str, int] = defaultdict(int)
        for w, sym in zip(rw, rs):
            family_w[sym] += w
        for f, w in family_w.items():
            out[(f, r_idx)] = w / total if total > 0 else 0
    return out


def build_weights_from_uniform(strip: list[list[str]],
                                fr_weights: dict) -> list[list[int]]:
    """fr_weights: {(family, reel_idx): weight}. Apply per-(family, reel)
    uniform weight to all positions of that family on that reel.

    Note: PWDF (per-position weight differentiation, e.g. top-adj Blanks
    heavier) is handled as POST-tune transform in `redistribute_m1_blanks.py`
    (RTP-neutral redistribution). This function emits uniform weights only.
    """
    out = []
    for r_idx, strip_reel in enumerate(strip):
        reel = [max(1, int(fr_weights[(sym, r_idx)])) for sym in strip_reel]
        out.append(reel)
    return out


def counts_from_weights(strips, weights):
    counts = []
    for reel_idx, strip in enumerate(strips):
        c: dict[str, int] = defaultdict(int)
        for pos, sym in enumerate(strip):
            c[sym] += weights[reel_idx][pos]
        counts.append(dict(c))
    return counts


def evaluate_candidate(
    fr_weights: dict[tuple[str, int], int],
    strip: list[list[str]],
    evaluator,
    target: dict,
    paytable: list[dict],
    reachable: set,
    cost_weights: CostWeights,
    experience_targets: dict,
    family_rtp_anchor: dict[str, float] | None = None,
    family_rtp_anchor_tol: dict[str, tuple[float, float]] | None = None,
    bigwin_pay_freq_floor: dict[tuple[str, int], float] | None = None,
):
    """Return (cost, predicted_profile, family_rtp, wild_p, weights_array).

    family_rtp_anchor: for mode 7, dict of {family: target_rtp_pp} from mode 1.
    family_rtp_anchor_tol: {family: (lo_offset, hi_offset)} relative to anchor.

    Note: mode 7's per-symbol weight LOCK for big-win symbols (Seven1/Seven2/
    Diamond1/Diamond2) is handled in search_weights via ``frozen_weights``,
    not as a cost penalty. Frozen weights guarantee 顶奖路径 doesn't change at
    the per-position level — densities may rise (Bar/Cherry weights drop →
    smaller total → big-win density rises naturally), which is fine because
    that means MORE top-tier hits in mode 7, not fewer.
    """
    weights = build_weights_from_uniform(strip, fr_weights)
    counts = counts_from_weights(strip, weights)
    marg = marginals_from_counts(counts)
    pred = analytic_profile_from_marginals(evaluator, marg)

    # Base cost: RTP + bucket shape + CV + hit
    br = evaluate_cost(pred, target, reachable_buckets=reachable, weights=cost_weights)
    cost = br.total

    # Family RTP share penalty
    family_rtp = family_rtp_breakdown(pred, paytable)
    total_rtp = pred["rtp_pct"]

    if family_rtp_anchor is not None:
        # Mode 7 path: lock specific families to mode 1's absolute pp
        for f, anchor_pp in family_rtp_anchor.items():
            actual_pp = family_rtp.get(f, 0.0)
            if family_rtp_anchor_tol and f in family_rtp_anchor_tol:
                lo_off, hi_off = family_rtp_anchor_tol[f]
                lo = anchor_pp + lo_off
                hi = anchor_pp + hi_off
                if actual_pp < lo:
                    cost += 50.0 * (lo - actual_pp) ** 2
                elif actual_pp > hi:
                    cost += 50.0 * (actual_pp - hi) ** 2
            else:
                # Strict equality (Diamond/Seven absolute lock — 大奖 family
                # 击中率/产出期望绝对不砍 per axiom).
                cost += 500.0 * (actual_pp - anchor_pp) ** 2
    else:
        # Mode 1 path: use share band targets
        share_bands = experience_targets.get("family_share_bands", {})
        for f, (lo, hi) in share_bands.items():
            actual = family_rtp.get(f, 0.0) / total_rtp if total_rtp > 0 else 0
            if actual < lo:
                cost += 80.0 * ((lo - actual) * 100) ** 2
            elif actual > hi:
                cost += 80.0 * ((actual - hi) * 100) ** 2

    # Wild on payline signature penalty — strong (300×) so optimizer
    # respects the band tightly even when other penalties pull opposite.
    wild_p = wild_on_payline_p(marg)
    wild_lo, wild_hi = experience_targets["wild_on_payline_band"]
    if wild_p < wild_lo:
        cost += 300.0 * ((wild_lo - wild_p) * 100) ** 2
    elif wild_p > wild_hi:
        cost += 300.0 * ((wild_p - wild_hi) * 100) ** 2

    # Per-reel per-family density visual penalty — per-family caps.
    densities = per_reel_family_density(weights, strip)
    lo_by_fam = experience_targets.get("per_reel_density_lo_by_family", {})
    hi_by_fam = experience_targets.get("per_reel_density_hi_by_family", {})
    if not hi_by_fam and "per_reel_density_band" in experience_targets:
        single_lo, single_hi = experience_targets["per_reel_density_band"]
        for f in ("Diamond1", "Diamond2", "Seven1", "Seven2", "Bar3", "Bar2", "Bar1", "Cherry"):
            lo_by_fam.setdefault(f, single_lo)
            hi_by_fam.setdefault(f, single_hi)
    for (f, r), d in densities.items():
        if f == "Blank":
            continue
        den_lo = lo_by_fam.get(f, 0.005)
        den_hi = hi_by_fam.get(f, 0.22)
        if d < den_lo:
            cost += 50.0 * ((den_lo - d) * 100) ** 2
        elif d > den_hi:
            cost += 80.0 * ((d - den_hi) * 100) ** 2

    # Per-reel Blank balance — variance penalty (goal-oriented soft).
    blank_var_k = experience_targets.get("per_reel_blank_variance_strength", 0.0)
    if blank_var_k > 0:
        blanks_pp = [densities.get(("Blank", r), 0.0) * 100 for r in range(3)]
        mean_b = sum(blanks_pp) / 3
        variance_pp2 = sum((b - mean_b) ** 2 for b in blanks_pp) / 3
        cost += blank_var_k * variance_pp2

    # R1 Blank absolute band — M1-specific user-pinned target (1-line classic).
    # User: "R1 blank 30-40% 才有 winning visibility 但不至于过密" (2026-04-28).
    # Strict band cost: penalize quadratically when R1 blank outside [lo, hi].
    r1_blank_band = experience_targets.get("r1_blank_band", None)
    if r1_blank_band is not None:
        r1_blank = densities.get(("Blank", 0), 0.0)
        lo, hi = r1_blank_band
        k_r1 = experience_targets.get("r1_blank_strength", 300.0)
        if r1_blank < lo:
            gap_pp = (lo - r1_blank) * 100
            cost += k_r1 * gap_pp * gap_pp
        elif r1_blank > hi:
            gap_pp = (r1_blank - hi) * 100
            cost += k_r1 * gap_pp * gap_pp

    # WINDOW-VISIBILITY (PWDF): NOT in this cost function. Handled as
    # post-tune RTP-neutral redistribution in `redistribute_m1_blanks.py`
    # (preserves total Blank weight per reel → marginals invariant → RTP
    # unchanged → top-symbol visibility raised by per-position weight bias).
    # Earlier attempt to integrate PWDF as in-tune cost competed with RTP
    # constraint and failed to converge.

    # REEL-ASYMMETRY: per project_slot_designer_reel_asymmetry.md universal
    # rule (Strickland/Reid/Harrigan). R1 should have lower Blank rate +
    # higher top-prize density than R3 (the "near-miss reel"). Tuner without
    # this penalty pareto-stuffs top-prize on whichever reel is RTP-cheapest
    # (often R3) — counter to player psychology.
    asym = experience_targets.get("reel_asymmetry", None)
    if asym is not None:
        # blank: R1 ≤ R3 + tolerance; penalize if R1 too blanky
        r1_blank = densities.get(("Blank", 0), 0.0)
        r3_blank = densities.get(("Blank", 2), 0.0)
        blank_tol = asym.get("blank_tol_pp", 0.03)
        blank_k = asym.get("blank_strength", 200.0)
        if r1_blank > r3_blank + blank_tol:
            gap_pp = (r1_blank - r3_blank - blank_tol) * 100
            cost += blank_k * gap_pp * gap_pp
        # top-prize: R1 ≥ R3 - tolerance; penalize if R3 stuffed
        r1_top = sum(densities.get((s, 0), 0.0) for s in ("Diamond1", "Diamond2", "Seven1", "Seven2"))
        r3_top = sum(densities.get((s, 2), 0.0) for s in ("Diamond1", "Diamond2", "Seven1", "Seven2"))
        top_tol = asym.get("top_tol_pp", 0.01)
        top_k = asym.get("top_strength", 200.0)
        if r1_top < r3_top - top_tol:
            gap_pp = (r3_top - r1_top - top_tol) * 100
            cost += top_k * gap_pp * gap_pp

    # Big-win pay frequency floor (mode 5 vs mode 2 monotonic): each
    # specific pay_id frequency must be ≥ reference. Direct goal — what
    # player actually experiences (how often they see a big win), not
    # symbol density (which is an intermediate quantity).
    if bigwin_pay_freq_floor:
        for pid, ref_freq in bigwin_pay_freq_floor.items():
            actual_freq = pred.get("pay_hits", {}).get(pid, 0.0)
            if actual_freq < ref_freq and ref_freq > 0:
                rel_gap = (ref_freq - actual_freq) / ref_freq
                cost += 200.0 * (rel_gap * 100) ** 2

    # Per-family REEL-UNIFORMITY penalty for top-tier symbols.
    # Seven/Diamond are top-pay/brand symbols — player should see them
    # consistently across all 3 reels (not "Seven always on middle reel").
    # Mid-pay (Bar3) intentionally asymmetric for 3-reel near-miss feel.
    # Constraint: max(R1,R2,R3) / min(R1,R2,R3) ≤ ratio_cap.
    uniformity_ratio_cap = experience_targets.get("uniformity_ratio_cap", {})
    for fam, ratio_cap in uniformity_ratio_cap.items():
        per_reel = [densities.get((fam, r), 0.0) for r in range(3)]
        mn = min(per_reel)
        mx = max(per_reel)
        if mn > 1e-6:
            ratio = mx / mn
            if ratio > ratio_cap:
                cost += 40.0 * (ratio - ratio_cap) ** 2

    # Top jackpot reachability
    tj_max = experience_targets.get("top_jackpot_max_spins", 300_000)
    tj_spins = top_jackpot_expected_spins(marg)
    if tj_spins > tj_max:
        cost += 5.0 * ((tj_spins - tj_max) / tj_max) ** 2

    # Bucket hit-rate floor — push mid-bucket frequency to player-visible
    # cadence (e.g. ge10_lt20 >= 1.0% so player sees 10× wins ~1 in 100 spins).
    bucket_floors = experience_targets.get("bucket_hit_floors", {})
    if bucket_floors:
        bucket_rate = pred.get("bucket_rate", {})
        for bucket, floor in bucket_floors.items():
            actual = bucket_rate.get(bucket, 0.0)
            if actual < floor:
                cost += 1500.0 * ((floor - actual) * 100) ** 2

    # Explicit CV target — overrides target file's CV when present.
    cv_target = experience_targets.get("cv_target")
    if cv_target is not None:
        actual_cv = pred.get("cv", 0.0)
        if actual_cv > cv_target:
            cost += 120.0 * (actual_cv - cv_target) ** 2

    return cost, pred, family_rtp, wild_p, weights


def search_weights(
    target,
    strip,
    evaluator,
    paytable,
    reachable,
    experience_targets,
    cost_weights,
    weight_bounds,
    family_rtp_anchor=None,
    family_rtp_anchor_tol=None,
    frozen_weights=None,
    weight_floors=None,
    bigwin_pay_freq_floor=None,
    seed=0,
    iterations=12000,
    verbose=False,
):
    """frozen_weights: {(symbol, reel): weight}. LOCKED at the given
    weight value, NOT mutated. Used in mode 7 to lock big-win symbol
    weights to mode 1's values (顶奖路径绝对不动 per-position).

    weight_floors: {(symbol, reel): min_weight}. Search may set this
    weight HIGHER but never LOWER than the floor. Used in mode 2/5
    (lucky modes) to enforce big-win weights ≥ mode 1's value (lucky
    should NOT make top-tier rarer than standard mode)."""
    rng = Random(seed)
    frozen = frozen_weights or {}
    floors = weight_floors or {}

    # Initialize: midpoint of bounds, then overwrite with frozen values,
    # then bump up to floor where applicable.
    fr_weights: dict = {}
    for sym in SYMBOLS:
        lo, hi = weight_bounds[sym]
        mid = (lo + hi) // 2
        for r in range(3):
            fr_weights[(sym, r)] = mid
    for key, val in frozen.items():
        fr_weights[key] = int(val)
    for key, floor_val in floors.items():
        if fr_weights.get(key, 0) < floor_val:
            fr_weights[key] = int(floor_val)

    best = dict(fr_weights)
    best_cost, _, _, _, _ = evaluate_candidate(
        best, strip, evaluator, target, paytable, reachable,
        cost_weights, experience_targets, family_rtp_anchor, family_rtp_anchor_tol,
        bigwin_pay_freq_floor=bigwin_pay_freq_floor,
    )

    sigma_pct = 0.4
    success = 0
    window = 80
    win_evals = 0

    # Mutable keys exclude frozen positions
    mutable_keys = [k for k in fr_weights.keys() if k not in frozen]

    for step in range(1, iterations + 1):
        cand = dict(best)
        n_mutate = rng.randint(2, 5)
        keys_to_mutate = rng.sample(mutable_keys, min(n_mutate, len(mutable_keys)))
        for key in keys_to_mutate:
            sym, r = key
            lo, hi = weight_bounds[sym]
            # Apply per-position floor (lucky modes for big-win symbols)
            effective_lo = max(lo, floors.get(key, 0))
            cur = cand[key]
            delta = rng.gauss(0, sigma_pct * (hi - lo))
            new = int(round(cur + delta))
            new = max(effective_lo, min(hi, new))
            cand[key] = new

        cost, _, _, _, _ = evaluate_candidate(
            cand, strip, evaluator, target, paytable, reachable,
            cost_weights, experience_targets, family_rtp_anchor, family_rtp_anchor_tol,
            bigwin_pay_freq_floor=bigwin_pay_freq_floor,
        )
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
        if verbose and (step <= 5 or step % 1000 == 0):
            print(f"    step {step:>5}  cost={best_cost:.3f}  sigma={sigma_pct:.3f}")

    return best, best_cost


def report_candidate(
    fr_weights,
    strip,
    evaluator,
    paytable,
    reachable,
    experience_targets,
    cost_weights,
    family_rtp_anchor=None,
    family_rtp_anchor_tol=None,
):
    cost, pred, family_rtp, wild_p, weights = evaluate_candidate(
        fr_weights, strip, evaluator, target_dummy_for_repr(),
        paytable, reachable, cost_weights, experience_targets,
        family_rtp_anchor, family_rtp_anchor_tol,
    )
    return cost, pred, family_rtp, wild_p, weights


def target_dummy_for_repr():
    return {"rtp_pct": 95.0, "bucket_rate": {}, "cv": 5.0}


def print_diagnostics(label, fr_weights, strip, evaluator, paytable,
                      reachable, target, experience_targets, cost_weights,
                      family_rtp_anchor=None, family_rtp_anchor_tol=None):
    cost, pred, family_rtp, wild_p, weights = evaluate_candidate(
        fr_weights, strip, evaluator, target, paytable, reachable,
        cost_weights, experience_targets, family_rtp_anchor, family_rtp_anchor_tol,
    )
    print(f"\n  {label}:")
    print(f"    cost={cost:.3f}")
    print(f"    RTP={pred['rtp_pct']:.3f}%  hit={pred['hit_rate']:.3%}  CV={pred['cv']:.2f}")
    print(f"    wild_on_payline={wild_p*100:.2f}% (band {experience_targets['wild_on_payline_band'][0]*100:.0f}-{experience_targets['wild_on_payline_band'][1]*100:.0f}%)")
    print(f"    Top jackpot expected spins: {top_jackpot_expected_spins(marginals_from_counts(counts_from_weights(strip, weights))):,.0f}")
    print(f"    family RTP (pp):")
    total = pred["rtp_pct"]
    for f in ("Diamond", "Seven", "Bar3", "Bar2", "Bar1", "Cherry"):
        v = family_rtp.get(f, 0.0)
        share = v / total * 100 if total > 0 else 0
        print(f"       {f:8s}: {v:6.2f}pp ({share:5.1f}%)")
    print(f"    per-reel per-family density:")
    densities = per_reel_family_density(weights, strip)
    fams_in_order = ("Diamond1", "Diamond2", "Seven1", "Seven2", "Bar3", "Bar2", "Bar1", "Cherry", "Blank")
    print(f"       {'family':10s} R1     R2     R3")
    for f in fams_in_order:
        d1 = densities.get((f, 0), 0) * 100
        d2 = densities.get((f, 1), 0) * 100
        d3 = densities.get((f, 2), 0) * 100
        print(f"       {f:10s} {d1:5.2f}% {d2:5.2f}% {d3:5.2f}%")
    return pred, family_rtp, wild_p, weights


def _write_reel_table_tsv(mode: int, strip: list[list[str]], weights: list[list[int]]) -> None:
    """Regenerate human-readable reel_weights.tsv (策划速查) after tune.
    Format: header `reel1\tweight1\treel2\tweight2\treel3\tweight3` + 22 rows
    of (symbol, weight) per reel. Idempotent — overwrites prior tsv."""
    out_path = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "reel_weights.tsv"
    n = len(strip[0])
    lines = ["reel1\tweight1\treel2\tweight2\treel3\tweight3"]
    for p in range(n):
        cells = []
        for r in range(3):
            cells.append(strip[r][p])
            cells.append(str(int(weights[r][p])))
        lines.append("\t".join(cells))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(modes_to_run=(1, 7)):
    # Mode 5 must NOT be free-tuned via this script. Per FIRST_MACHINE.md §7
    # + DESIGN.md §3.5, non-feature M1 mode 5 is DERIVED from mode 2 by
    # `derive_m1_mode_5.py` (base byte-identical, top-bucket × k). Free-tuning
    # mode 5 reproduces the pareto trap that this fix removed: R-collapse,
    # Bar1 R2 extinction, Seven1 R2 reverse-monotonic m2 → m5.
    if 5 in modes_to_run:
        raise SystemExit(
            "tune_m1.py does NOT tune mode 5. Mode 5 is derived from mode 2 "
            "by `python -m slot_designer.scripts.derive_m1_mode_5 --write --verify`. "
            "See DESIGN.md §3.5 + verify_m1_design.py [MODE5-BASE-LOCK]."
        )

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    strip = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    symbols_reg = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"], reroll_blocks=spec.get("reroll_blocks"))
    evaluator = PaytableEvaluator(symbols_reg, rules, spec["evaluation_order"])
    paytable = spec["pays"]

    # reachable buckets — use mode 1 weights file as engine seed
    mode1_weights = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"
    engine, _ = load_engine(SPEC_PATH, mode1_weights)
    reachable = structurally_reachable_buckets(engine)

    mode1_anchor: dict[str, float] | None = None
    mode1_bigwin_weights: dict[tuple[str, int], int] | None = None
    mode2_bigwin_weights: dict[tuple[str, int], int] | None = None
    mode2_bigwin_pay_freqs: dict[str, float] | None = None  # pay_id -> P(fires)

    BIGWIN_SYMBOLS = ("Seven1", "Seven2", "Diamond1", "Diamond2")
    # pay_ids classified as "big-win" = mode 5 must have ≥ mode 2 freq.
    # Diamond pure pays (2, 3) + Seven family (5, 6, 10).
    # pay_id 4 (Diamond2x3 = 1000x) is rtp_excluded so doesn't fire from
    # regular spins — skip it (always 0 hit rate via evaluator).
    BIGWIN_PAY_IDS = ("2", "3", "5", "6", "10")

    def _extract_bigwin_weights_from_disk(mode_n: int) -> dict[tuple[str, int], int] | None:
        """Read mode N's saved weights.json + extract big-win symbol weights
        per (symbol, reel)."""
        path = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode_n}" / "weights.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            w_array = data.get("weights")
            strip_data = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
            if not w_array:
                return None
            out: dict[tuple[str, int], int] = {}
            for sym in BIGWIN_SYMBOLS:
                for r_idx, strip_reel in enumerate(strip_data):
                    for pos, s in enumerate(strip_reel):
                        if s == sym:
                            out[(sym, r_idx)] = int(w_array[r_idx][pos])
                            break
            return out
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    # Load mode 1 anchor for mode 7 (frozen) or mode 2/5 (floor) when not in same run
    if (7 in modes_to_run or 2 in modes_to_run or 5 in modes_to_run) and 1 not in modes_to_run:
        mode1_path = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"
        try:
            mode1_data = json.loads(mode1_path.read_text(encoding="utf-8"))
            saved = mode1_data.get("_tuned_summary", {}).get("family_rtp_pp", {})
            if saved:
                mode1_anchor = {k: float(v) for k, v in saved.items()}
                print(f"[anchor] loaded mode 1 family RTP from disk")
            # Load mode 1's actual per-position weights to extract big-win symbol weights
            m1_weights_array = mode1_data.get("weights")
            m1_strip_data = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
            if m1_weights_array:
                mode1_bigwin_weights = {}
                # For each big-win symbol, find its first position on each reel
                # and capture the weight. Per-family uniform weight = same value
                # at all positions of that family on that reel.
                for sym in BIGWIN_SYMBOLS:
                    for r_idx, strip_reel in enumerate(m1_strip_data):
                        for pos, s in enumerate(strip_reel):
                            if s == sym:
                                mode1_bigwin_weights[(sym, r_idx)] = int(m1_weights_array[r_idx][pos])
                                break
                print(f"[anchor] loaded mode 1 big-win weights (FROZEN in mode 7): "
                      f"{ {f'{s}_R{r}': w for (s, r), w in mode1_bigwin_weights.items()} }")
        except (FileNotFoundError, json.JSONDecodeError):
            print("[anchor] could not load mode 1 anchor from disk")

    # Load mode 2 big-win weights from disk if mode 5 is being tuned alone
    if 5 in modes_to_run and 2 not in modes_to_run:
        mode2_bigwin_weights = _extract_bigwin_weights_from_disk(2)
        if mode2_bigwin_weights:
            print(f"[anchor] loaded mode 2 big-win weights (mode 5 floor)")

    for mode in modes_to_run:
        target_path = _ROOT / "slot_designer" / "tuner" / "targets" / f"M1_mode{mode}_{ {1: 'classic', 2: 'lucky', 5: 'super_lucky', 7: 'low_rtp'}[mode] }.target.json"
        target = json.loads(target_path.read_text(encoding="utf-8"))
        if "cv" not in target:
            target["cv"] = target.get("std_return_x", 0) / (target["rtp_pct"] / 100)

        # Mode 1: strict RTP target (must not exceed 95%+1pp); other
        # cost components are strong enough that without high rtp_weight
        # optimizer happily overshoots into 96%+ territory.
        # Mode 7: family anchor bands also need strong RTP pull.
        rtp_weight = 6.0 if mode in (1, 7) else 2.0
        cost_weights = CostWeights(
            rtp_weight=rtp_weight,
            shape_weight=1.0,
            cv_weight=0.2,
            hit_target=target.get("hit_rate"),
            hit_weight=1.0,
        )

        exp_targets = EXPERIENCE_TARGETS[mode]

        family_anchor = None
        family_anchor_tol = None
        frozen_weights = None
        weight_floors = None
        bigwin_pay_freq_floor = None
        if mode == 7 and mode1_bigwin_weights is not None:
            frozen_weights = dict(mode1_bigwin_weights)
        elif mode == 2 and mode1_bigwin_weights is not None:
            # Mode 2 (lucky) ≥ mode 1 (standard) for big-win weights.
            # Weight floor is fine here because mode 1 is standard (no
            # extreme reel-weight inflation), so weight ≥ → density ≥.
            weight_floors = dict(mode1_bigwin_weights)
        elif mode == 5 and mode2_bigwin_pay_freqs is not None:
            # Mode 5 (super-lucky) ≥ mode 2 (lucky) for big-win pay_id
            # frequencies. Direct goal — what player actually feels.
            # Penalize when any P(big-win pay fires) < mode 2's value.
            bigwin_pay_freq_floor = dict(mode2_bigwin_pay_freqs)
            print(f"  big-win pay frequency floor (mode 2 baseline):")
            for pid, freq in sorted(bigwin_pay_freq_floor.items(), key=lambda x: int(x[0])):
                n = 1/freq if freq > 0 else 0
                print(f"     pay_id {pid}: P(fire) ≥ {freq:.6f} (1 in {n:,.0f})")
        elif mode == 5 and mode1_bigwin_weights is not None:
            weight_floors = dict(mode1_bigwin_weights)
            print(f"  big-win weight floors (mode 1 baseline; mode 2 not in run)")
        if mode == 7 and mode1_anchor is not None:
            # Mode 7 inherits Diamond/Seven absolute pp from mode 1
            family_anchor = {
                "Diamond": mode1_anchor["Diamond"],
                "Seven": mode1_anchor["Seven"],
            }
            # Bar3/Bar2 略砍 (-2 to -1pp), Bar1/Cherry 砍 (-3 to -2pp)
            family_anchor_tol = {
                # Diamond/Seven omitted -> strict equality penalty
            }
            # Add Bar3/Bar2/Bar1/Cherry as anchored with tolerance windows
            # Mode 7 RTP target = 85, mode 1 = ~94.6, gap = ~9.6pp.
            # Diamond + Seven locked → flex families absorb 9.6pp cut.
            # Distribution honoring user's 略砍 (mid) + 砍 (low):
            #   Bar3:   -1.5pp ± 0.5  (略砍, brand mid-tier)
            #   Bar2:   -1.5pp ± 0.5  (略砍)
            #   Bar1:   -3pp   ± 1    (砍, small)
            #   Cherry: -3.5pp ± 1    (砍, smallest)
            # Sum target ≈ -9.5pp → mode 7 ≈ 85.1pp
            family_anchor["Bar3"] = mode1_anchor["Bar3"]
            family_anchor_tol["Bar3"] = (-2.0, -1.0)
            family_anchor["Bar2"] = mode1_anchor["Bar2"]
            family_anchor_tol["Bar2"] = (-2.0, -1.0)
            family_anchor["Bar1"] = mode1_anchor["Bar1"]
            family_anchor_tol["Bar1"] = (-4.0, -2.0)
            family_anchor["Cherry"] = mode1_anchor["Cherry"]
            family_anchor_tol["Cherry"] = (-4.5, -2.5)

        print(f"\n=== Mode {mode} player-experience tune ===")
        print(f"  target: RTP {target['rtp_pct']}%  hit {target['hit_rate']:.2%}")
        if family_anchor:
            print(f"  family anchor (mode 1):")
            for f, v in family_anchor.items():
                tol_str = ""
                if family_anchor_tol and f in family_anchor_tol:
                    tol_str = f" (cut {family_anchor_tol[f][0]:+.1f} to {family_anchor_tol[f][1]:+.1f}pp)"
                else:
                    tol_str = " (strict)"
                print(f"     {f:8s}: anchor {v:.2f}pp{tol_str}")

        weight_bounds = WEIGHT_BOUNDS_BY_MODE[mode]
        best, best_cost = search_weights(
            target, strip, evaluator, paytable, reachable, exp_targets,
            cost_weights, weight_bounds, family_anchor, family_anchor_tol,
            frozen_weights=frozen_weights, weight_floors=weight_floors,
            bigwin_pay_freq_floor=bigwin_pay_freq_floor,
            seed=mode * 7 + 13, iterations=15000, verbose=True,
        )

        pred, family_rtp, wild_p, weights = print_diagnostics(
            f"Mode {mode} result",
            best, strip, evaluator, paytable, reachable, target, exp_targets,
            cost_weights, family_anchor, family_anchor_tol,
        )

        if mode == 1:
            mode1_anchor = dict(family_rtp)
            # Capture mode 1's big-win symbol weights (will be FROZEN
            # in mode 7 search to guarantee "顶奖路径绝对不动" at the
            # per-position level — not just family RTP total).
            mode1_bigwin_weights = {
                (sym, r): best[(sym, r)]
                for sym in BIGWIN_SYMBOLS
                for r in range(3)
            }
        if mode == 2:
            mode2_bigwin_weights = {
                (sym, r): best[(sym, r)]
                for sym in BIGWIN_SYMBOLS
                for r in range(3)
            }
            # Capture mode 2's big-win pay_id frequencies as floor for
            # mode 5 (super-lucky must improve over lucky for these pays).
            mode2_bigwin_pay_freqs = {
                pid: pred.get("pay_hits", {}).get(pid, 0.0)
                for pid in BIGWIN_PAY_IDS
            }

        # NOTE: PWDF (per-Blank-position weight differentiation for window
        # visibility) is NOT applied here. It's a SEPARATE post-tune transform
        # in `redistribute_m1_blanks.py` (RTP-neutral redistribution) — run
        # AFTER tune. Tune emits per-(family, reel) uniform weights; redistribution
        # rebalances Blank weights within each reel preserving total Blank
        # weight (marginals invariant). This decoupling avoids
        # PWDF/RTP cost-function conflict that earlier in-tune mult mechanism
        # caused.

        # Persist
        out_path = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        existing["mode"] = mode
        existing["weights"] = weights
        existing["_family_uniform_weights"] = {
            f"{sym}_R{r}": int(best[(sym, r)]) for sym in SYMBOLS for r in range(3)
        }
        # Drop any prior _blank_top_adj_mult metadata (mechanism replaced)
        existing.pop("_blank_top_adj_mult", None)
        existing["_notes"] = [
            f"M1 mode {mode} — player-experience direct tune (per-(family, reel) uniform weights).",
            "Cost: RTP + hit + bucket + family RTP share + wild signature + per-reel "
            "density + REEL-ASYMMETRY + R1-BLANK-BAND.",
            "PWDF (window visibility): apply post-tune via "
            "`python -m slot_designer.scripts.redistribute_m1_blanks --write`.",
            f"RTP {pred['rtp_pct']:.3f}%, hit {pred['hit_rate']:.3%}, wild_on_payline {wild_p*100:.2f}%",
        ]
        existing["_tuned_summary"] = {
            "rtp_pct": pred["rtp_pct"],
            "hit_rate": pred["hit_rate"],
            "cv": pred["cv"],
            "wild_on_payline": wild_p,
            "family_rtp_pp": {f: round(v, 3) for f, v in family_rtp.items()},
            "method": "player_experience_per_family_per_reel_uniform",
        }
        out_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        _write_reel_table_tsv(mode, strip, weights)
        print(f"  wrote {out_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", type=str, default="1,7")
    args = parser.parse_args()
    modes = tuple(int(m) for m in args.modes.split(","))
    main(modes_to_run=modes)
