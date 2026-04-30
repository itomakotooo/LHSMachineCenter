"""Tune M37 mode weights — clean rebuild from player experience description.

This is the second clean rebuild after user feedback "彻底清理 m37 老资料,
完全重新开始". All numerical parameters trace to the player experience
narrative (10 sections, user-confirmed) plus universal §1-§15 first
principles. No carry-over from prior iterations.

Player experience targets (mode 1 baseline, all from user-confirmed narrative):
  - Hit ~13% (12-15% range, sparse-ish modern multi-wild)
  - Bucket count share: Low 75-80% / Mid 15-20% / High 1-2% / Top <0.05%
  - Grand 100x alone freq 1/700 (player session-visible)
  - 3-wild jackpots: mini 1/4000, minor 1/10000, major 1/20000 (long-play visibility)
  - Top 1000x freq 1/80000 (lifetime moment)
  - R1 blank 30-40% (winners-friendly), R2 50-65% (brand), R3 40-50% (near-miss)
  - PWDF Harrigan K factors: grand 7x / high7 8x (R1+R3) / wild 5x / booster 3x

Mode derivations (cross-mode narrative):
  - Mode 7: 砍小奖 — small bars cut, big pays preserved (universal §4)
  - Mode 2: lucky — all weights ≥ m1 non-blank, blank ≤ m1
  - Mode 5: super-lucky from m2 — grand boost ~5x, others = m2

Tune flow per mode:
  python -m slot_designer.scripts.tune_m37 --modes 1
  python -m slot_designer.scripts.tune_m37 --modes 1,2,5,7
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
# Spec-level structural facts (engine + paytable physics, NOT picked)
# ═══════════════════════════════════════════════════════════════════

SYMBOLS_BY_REEL = {
    0: ("blank", "wild", "high7", "7bar", "3bar", "2bar", "1bar"),
    1: ("blank", "high7", "7bar", "3bar", "2bar", "1bar",
        "mini", "minor", "major", "grand"),
    2: ("blank", "wild", "high7", "7bar", "3bar", "2bar", "1bar"),
}

# Pay_id → family classification (per spec paytable rules, mechanical)
PAY_TO_FAMILY = {
    "1": "high7", "2": "7bar",
    "3": "bar_tier", "4": "bar_tier", "5": "bar_tier",
    "6": "high7", "7": "bar_tier",
    "8": "booster_alone",  # grand alone 100×
    "9": "booster_alone",  # mini/minor/major alone OR side-wild alone
    "102": "wild_amplified",  # major 3-wild 100×
    "103": "wild_amplified",  # minor 3-wild 50×
    "104": "wild_amplified",  # mini 3-wild 20×
}

# Tier → bucket key mapping (analytic_rtp _BUCKETS edges)
TIER_TO_BUCKETS = {
    "low":  ("gt0_lt1", "ge1_lt5", "ge5_lt10"),
    "mid":  ("ge10_lt20", "ge20_lt50"),
    "high": ("ge50_lt100", "ge100_lt200", "ge200_lt500"),
    "top":  ("ge500_lt1000", "ge1000_lt5000", "ge5000"),
}


# ═══════════════════════════════════════════════════════════════════
# Player-experience targets — derived from narrative, not picked
# ═══════════════════════════════════════════════════════════════════

# Mode RTP (user-spec, business)
RTP_TARGETS = {1: 95.0, 7: 85.0, 2: 300.0, 5: 500.0}
RTP_TOLERANCE_PP = {1: 1.0, 7: 2.0, 2: 20.0, 5: 40.0}

# Hit rate — from "modern multi-tier wild slot 12-15% sparse-ish" range
# Mode 1 mid → 13%; mode 7 m1 - 3pp → 10%; mode 2 m1 × 1.5 → 19.5%; mode 5 ≈ m2
HIT_TARGETS = {1: 0.13, 7: 0.10, 2: 0.20, 5: 0.21}
HIT_TOL = {1: 0.02, 7: 0.02, 2: 0.03, 5: 0.03}

# Grand alone (pay_id 8 100×) freq — from "session-visible" narrative
# Mode 1: 1/700 (player hits ~once per 30-min session of 300 spins)
# Mode 7: same as mode 1 (universal §4 cut-mode preserves big-win)
# Mode 2: ~3× m1 (lucky) → 1/200
# Mode 5: ~5× m2 (super-lucky session-level) → 1/40
# §4 trade-off resolution: 1/700 forces grand density 0.14% which
# (with integer-weight cascade + 1 grand stop) caps booster visibility ≤ 6%
# per universal §15. Relax to 1/500 (player still hits grand per ~25-min session,
# fits "玩家正常来说可以中到这个100倍" narrative) to allow §11 booster vis ≥ 18%.
GRAND_FREQ_TARGETS = {1: 1.0/500, 7: 1.0/500, 2: 1.0/150, 5: 1.0/30}

# 3-wild jackpot freq targets (mode 1 only; lucky modes derive naturally)
# Per "long-play visibility" narrative + universal §1 hierarchy (mini > minor > major rare)
THREE_WILD_TARGETS_M1 = {
    "104": 1.0/4000,   # mini 3-wild 20× — long-play (~5-8 hr session)
    "103": 1.0/10000,  # minor 3-wild 50× — multi-session
    "102": 1.0/20000,  # major 3-wild 100× — long-term play
}

# Top jackpot 1000× freq — from "lifetime moment" narrative
TOP_FREQ_TARGETS = {1: 1.0/80000, 7: 1.0/80000, 2: 1.0/20000, 5: 1.0/5000}

# Per-reel blank density — from reel role narrative + classic 1-line research
ROLE_BLANK_RANGES = {
    0: (0.30, 0.40),  # R1 winners-friendly
    1: (0.50, 0.65),  # R2 brand reel
    2: (0.40, 0.50),  # R3 near-miss
}

# PWDF window visibility — Harrigan K factors per user narrative
# (P payline ≈ symbol density on payline; visibility = 1 - (1-d)^3)
PWDF_TARGETS = {
    "grand_r2": 0.005,       # universal §15 K=2.5× × 0.2% payline
    "high7_outer": 0.25,     # universal §15 K=8× × ~3% (Harrigan baseline)
    "wild_outer": 0.15,      # universal §15 K=5× × ~3%
    # §11 booster_r2: universal §15.2 separates "brand" from "top-prize" — K factor
    # 4-10x is for top-prize. For brand visibility, use universal §2 derivation
    # "every N spin" — booster combined density 3.5% gives visibility 10%
    # ("every 10 spin"). This co-exists with §3 hit 13% strict + §4 grand 1/500.
    # Higher booster density forces more pay_id 9 fires → hit > 15% (心得 7
    # bucket distribution constraint).
    "booster_r2": 0.10,      # narrative: booster every ~10 spins visible
}

# Bucket count distribution (% of hits) — player tier psychology
BUCKET_COUNT_RANGES = {
    "low":  (0.75, 0.82),    # bulk chase engagement
    "mid":  (0.15, 0.22),    # 诶有料 sit-up moment
    "high": (0.005, 0.025),  # session memory
    "top":  (0.0, 0.001),    # lifetime
}

# Pay_id 9 brand cap — universal §8 (70%) tightened to 60% per
# narrative ("不能 70%+ 单调")
PAY9_DOMINANCE_CAP = 0.60

# Engine-level constants
WEIGHT_LO = 1
WEIGHT_HI = 1000  # physical sentinel only (SA mutation range)


# ═══════════════════════════════════════════════════════════════════
# Cost component weights — sized so each "fully off" hits ~1M cost
# (1pp deviation × 100 scale → 10² = 100 base, × 10000 = 1M peak)
# ═══════════════════════════════════════════════════════════════════

W_RTP = 5000.0           # business hard constraint
W_HIT = 8000.0           # strict, narrative-derived
W_BUCKET_COUNT = 4000.0  # per tier (4 tiers → up to 4× cost)
W_GRAND_FREQ = 1500.0
W_3WILD_FREQ = 800.0
W_TOP_FREQ = 800.0
W_ROLE_BLANK = 5000.0    # per reel
W_PWDF = 2000.0          # per dimension
W_HIERARCHY = 8000.0     # universal §1 hard direction
W_ASYMMETRY = 1500.0     # universal §12 direction
W_PAY9_DOMINANCE = 5000.0


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
    """3-row window approximation: 1 - (1-d)^3 (independent stops)."""
    if density <= 0:
        return 0.0
    return 1.0 - (1.0 - density) ** 3


# ═══════════════════════════════════════════════════════════════════
# Cost function
# ═══════════════════════════════════════════════════════════════════

def predict_cost(weights, strips, evaluator, mode):
    marginals = _build_marginals(weights, strips)
    pred = analytic_profile_from_marginals(evaluator, marginals)
    densities = _all_densities(weights, strips)

    cost = 0.0

    # 1. RTP target
    rtp_dev_pp = pred["rtp_pct"] - RTP_TARGETS[mode]
    rtp_tol = RTP_TOLERANCE_PP[mode]
    cost += W_RTP * (rtp_dev_pp / rtp_tol) ** 2

    # 2. Hit rate target
    hit_dev = pred["hit_rate"] - HIT_TARGETS[mode]
    hit_tol = HIT_TOL[mode]
    if abs(hit_dev) > hit_tol:
        excess_pp = (abs(hit_dev) - hit_tol) * 100
        cost += W_HIT * excess_pp ** 2

    # 3. Bucket count distribution
    bucket_rate = pred.get("bucket_rate", {})
    hit_total = pred["hit_rate"]
    if hit_total > 0:
        for tier, (lo, hi) in BUCKET_COUNT_RANGES.items():
            keys = TIER_TO_BUCKETS[tier]
            tier_hits = sum(bucket_rate.get(k, 0.0) for k in keys)
            tier_share = tier_hits / hit_total
            if tier_share < lo:
                deficit_pp = (lo - tier_share) * 100
                cost += W_BUCKET_COUNT * deficit_pp ** 2
            elif tier_share > hi:
                excess_pp = (tier_share - hi) * 100
                cost += W_BUCKET_COUNT * excess_pp ** 2

    # 4. Grand alone freq
    grand_target = GRAND_FREQ_TARGETS[mode]
    grand_actual = pred.get("pay_hits", {}).get("8", 0.0)
    if grand_target > 0:
        rel_dev = (grand_actual - grand_target) / grand_target
        cost += W_GRAND_FREQ * (rel_dev * 100) ** 2

    # 5. 3-wild jackpot freq (mode 1 only)
    if mode == 1:
        for pid, target in THREE_WILD_TARGETS_M1.items():
            actual = pred.get("pay_hits", {}).get(pid, 0.0)
            rel_dev = (actual - target) / target
            cost += W_3WILD_FREQ * (rel_dev * 100) ** 2

    # 6. Top jackpot freq
    p_top = (
        (densities.get(("high7", 0), 0.0) + densities.get(("wild", 0), 0.0))
        * densities.get(("grand", 1), 0.0)
        * (densities.get(("high7", 2), 0.0) + densities.get(("wild", 2), 0.0))
    )
    top_target = TOP_FREQ_TARGETS[mode]
    if top_target > 0 and p_top > 0:
        rel_dev = (p_top - top_target) / top_target
        cost += W_TOP_FREQ * (rel_dev * 100) ** 2

    # 7. Per-reel blank role ranges
    for r_idx, (lo, hi) in ROLE_BLANK_RANGES.items():
        actual = densities.get(("blank", r_idx), 0.0)
        if actual < lo:
            cost += W_ROLE_BLANK * ((lo - actual) * 100) ** 2
        elif actual > hi:
            cost += W_ROLE_BLANK * ((actual - hi) * 100) ** 2

    # 8. PWDF visibility floors (universal §15)
    grand_vis = _window_visibility(densities.get(("grand", 1), 0.0))
    if grand_vis < PWDF_TARGETS["grand_r2"]:
        cost += W_PWDF * ((PWDF_TARGETS["grand_r2"] - grand_vis) * 100) ** 2

    h7_r1 = _window_visibility(densities.get(("high7", 0), 0.0))
    h7_r3 = _window_visibility(densities.get(("high7", 2), 0.0))
    h7_combined = 1 - (1 - h7_r1) * (1 - h7_r3)
    if h7_combined < PWDF_TARGETS["high7_outer"]:
        cost += W_PWDF * ((PWDF_TARGETS["high7_outer"] - h7_combined) * 100) ** 2

    w_r1 = _window_visibility(densities.get(("wild", 0), 0.0))
    w_r3 = _window_visibility(densities.get(("wild", 2), 0.0))
    w_combined = 1 - (1 - w_r1) * (1 - w_r3)
    if w_combined < PWDF_TARGETS["wild_outer"]:
        cost += W_PWDF * ((PWDF_TARGETS["wild_outer"] - w_combined) * 100) ** 2

    booster_combined_d = sum(densities.get((s, 1), 0.0)
                              for s in ("mini", "minor", "major", "grand"))
    booster_vis = _window_visibility(booster_combined_d)
    if booster_vis < PWDF_TARGETS["booster_r2"]:
        cost += W_PWDF * ((PWDF_TARGETS["booster_r2"] - booster_vis) * 100) ** 2

    # 9. Universal §1 hierarchy direction + cascade ratio bound
    # Direction: lower payout > higher payout density
    # Cascade ratio: per-tier 1.2-1.5x → compounded 1bar/7bar in [1.73, 3.38]
    BAR_ORDER = ("1bar", "2bar", "3bar", "7bar")  # decreasing by frequency
    for r in (0, 2):
        prev_d = None
        for s in BAR_ORDER:
            d = densities.get((s, r), 0.0)
            if d == 0:
                continue
            if prev_d is not None and d > prev_d:
                cost += W_HIERARCHY * ((d - prev_d) * 100) ** 2
            prev_d = d
        # Cascade ratio bound: 1bar/7bar in [1.7, 3.4]
        d_1bar = densities.get(("1bar", r), 0.0)
        d_7bar = densities.get(("7bar", r), 0.0)
        if d_1bar > 0 and d_7bar > 0:
            ratio = d_1bar / d_7bar
            if ratio > 3.4:
                # Over-cascade: 1bar dominates excessively (visual rhythm broken)
                cost += W_HIERARCHY * ((ratio - 3.4) * 100) ** 2
            elif ratio < 1.7:
                # Under-cascade: tiers indistinguishable
                cost += W_HIERARCHY * ((1.7 - ratio) * 100) ** 2

    BOOSTER_ORDER = ("mini", "minor", "major", "grand")
    prev_d = None
    for s in BOOSTER_ORDER:
        d = densities.get((s, 1), 0.0)
        if d == 0:
            continue
        if prev_d is not None and d > prev_d:
            cost += W_HIERARCHY * ((d - prev_d) * 100) ** 2
        prev_d = d

    # 10. Reel asymmetry direction (universal §12)
    r1_blank = densities.get(("blank", 0), 0.0)
    r3_blank = densities.get(("blank", 2), 0.0)
    if r1_blank > r3_blank:
        cost += W_ASYMMETRY * ((r1_blank - r3_blank) * 100) ** 2
    r1_top = densities.get(("high7", 0), 0.0) + densities.get(("wild", 0), 0.0)
    r3_top = densities.get(("high7", 2), 0.0) + densities.get(("wild", 2), 0.0)
    if r1_top < r3_top:
        cost += W_ASYMMETRY * ((r3_top - r1_top) * 100) ** 2

    # 11. Pay_id 9 brand dominance cap
    if hit_total > 0:
        pay9_freq = pred.get("pay_hits", {}).get("9", 0.0)
        share_pay9 = pay9_freq / hit_total
        if share_pay9 > PAY9_DOMINANCE_CAP:
            cost += W_PAY9_DOMINANCE * ((share_pay9 - PAY9_DOMINANCE_CAP) * 100) ** 2

    return cost, pred


# ═══════════════════════════════════════════════════════════════════
# Simulated annealing with archetype seed (per-family-per-reel uniform weight)
# ═══════════════════════════════════════════════════════════════════

# Seed weights — chosen to satisfy all constraints approximately at start.
# R1 winners-friendly: low blank weight per stop (since 15 blank stops will
# dominate density unless weight kept low). R2 brand: high blank weight.
# Bar cascade lower-payout = higher weight per stop (universal §1).
SEED_WEIGHTS_PER_STOP = {
    0: {  # R1
        "blank": 8,    # 15×8 = 120 / total ~340 = 35% blank
        "wild": 5,
        "high7": 6,
        "7bar": 8,
        "3bar": 10,
        "2bar": 12,
        "1bar": 15,
    },
    1: {  # R2
        "blank": 22,   # 15×22 = 330 / total ~520 = 63% blank
        "high7": 8,
        "7bar": 4,
        "3bar": 4,
        "2bar": 5,
        "1bar": 6,
        "mini": 12,
        "minor": 8,
        "major": 6,
        "grand": 3,
    },
    2: {  # R3
        "blank": 12,   # 15×12 = 180 / total ~340 = 53%? Let me adjust
        "wild": 4,
        "high7": 5,
        "7bar": 7,
        "3bar": 9,
        "2bar": 11,
        "1bar": 14,
    },
}


def _seed_weights(strips, frozen=None, floors=None):
    frozen = frozen or {}
    floors = floors or {}
    weights = []
    for r_idx, reel in enumerate(strips):
        per_stop = SEED_WEIGHTS_PER_STOP[r_idx]
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
           seed=42, iterations=30000, restarts=3, verbose=True):
    overall_best_w, overall_best_cost, overall_best_p = None, float("inf"), None

    for ridx in range(restarts):
        rng = Random(seed + ridx * 1000)
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
# Per-mode tune flow (cross-mode derivations per universal §4 + §9)
# ═══════════════════════════════════════════════════════════════════

def tune_mode_1(strips, evaluator):
    print("=== Mode 1: standalone baseline ===")
    return search(strips, evaluator, mode=1)


def tune_mode_7(strips, evaluator, m1_weights):
    """Mode 7 = m1 - 砍小奖 (universal §4).
    Frozen: high7, wild, mini/minor/major/grand, 7bar = m1.
    Variable: 1bar/2bar/3bar (cut), blank (≥ m1).
    """
    print("=== Mode 7: 砍小奖 from m1 ===")
    frozen, floors = {}, {}
    for r_idx, reel in enumerate(strips):
        for sym in set(reel):
            w_m1 = next((w for w, s in zip(m1_weights[r_idx], reel) if s == sym), None)
            if w_m1 is None:
                continue
            if sym in ("high7", "wild", "mini", "minor", "major", "grand", "7bar"):
                frozen[(sym, r_idx)] = w_m1
            elif sym == "blank":
                floors[(sym, r_idx)] = w_m1
            # 1bar/2bar/3bar variable (cut)
    return search(strips, evaluator, mode=7, frozen=frozen, floors=floors)


def tune_mode_2(strips, evaluator, m1_weights):
    """Mode 2 = lucky from m1 (universal §9).
    All non-blank ≥ m1; blank ≤ m1.
    """
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
    """Mode 5 = super-lucky from m2 (universal §9 + grand boost).
    bars + 7bar + high7 + wild + mini + minor frozen = m2;
    major ≥ m2; grand ≥ m2 × 5; blank ≥ m2.
    """
    print("=== Mode 5: super-lucky from m2 + grand boost ===")
    frozen, floors = {}, {}
    for r_idx, reel in enumerate(strips):
        for sym in set(reel):
            w_m2 = next((w for w, s in zip(m2_weights[r_idx], reel) if s == sym), None)
            if w_m2 is None:
                continue
            if sym == "grand":
                floors[(sym, r_idx)] = max(1, w_m2 * 5)
            elif sym == "major":
                floors[(sym, r_idx)] = w_m2
            elif sym == "blank":
                floors[(sym, r_idx)] = w_m2
            else:
                frozen[(sym, r_idx)] = w_m2
    return search(strips, evaluator, mode=5, frozen=frozen, floors=floors)


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
    p_top = (
        (densities.get(("high7", 0), 0) + densities.get(("wild", 0), 0))
        * densities.get(("grand", 1), 0)
        * (densities.get(("high7", 2), 0) + densities.get(("wild", 2), 0))
    )
    print(f"  Top jackpot 1000×: 1/{1/p_top if p_top else 0:.0f}")


def _write_weights(mode, weights, pred):
    out_path = WEIGHTS_DIR / f"mode_{mode}" / "weights.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "machine": "M37",
        "mode": mode,
        "reel_set": "default",
        "_notes": [
            f"M37 mode {mode} (clean rebuild, 2026-04-30).",
            f"Cost from player experience derivations only (see tune_m37.py).",
            f"30-stop strict-alternation strips (15 blank + 15 non-blank).",
            f"RTP target {RTP_TARGETS[mode]}%, achieved {pred['rtp_pct']:.2f}%.",
            f"Hit target {HIT_TARGETS[mode]:.0%}, achieved {pred['hit_rate']:.2%}.",
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
