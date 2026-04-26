"""Tune M15 mode weights — player-experience direct objective.

Per ``project_slot_designer_axiom_experience_is_soul``: TDD numbers are
inspiration, not constraint. Cost function targets player experience red
lines directly.

Hard rules:
  - Paytable LOCKED
  - Strict Blank-non-Blank alternation in strip (硬约束)
  - topdollar ONLY on R3 (Feature trigger)
  - Mode RTP: 1=95%, 7=85% (standard); 2=300%, 5=500% (lucky)
  - Mode 7 = mode 1 - 砍小奖派生：大奖击中率/产出期望绝对不砍
    (high7 + doublediamond weights frozen to mode 1)
  - **No R≥1000 anywhere** — Feature payout naturally < 1000 via x_value_weights

M15 design intent (Top Dollar brand):
  - Headline = Feature Play (topdollar on R3 → reveal game)
  - Base = consolation: low-volatility frequent small wins (CV ≤ 4 mode 1)
  - Feature = mid-high volatility, but capped < 1000 per session

Parameterization (per mode):
  - Per-family per-reel uniform weights (25-dim: 9 families × 3 reels minus
    2 absent topdollar positions on R1/R2)
  - topdollar weight on R3 controls Feature trigger rate
  - Feature_params (count_y, x_value_weights) come from disk (per mode)

Total RTP = base_RTP + topdollar_R3_density × feature_EV
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
from slot_designer.engine.feature_m15 import FeatureSpec, analyze_feature
from slot_designer.tuner.cost import CostWeights, evaluate_cost
from slot_designer.tuner.layout import marginals_from_counts


SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M15.spec.json"
STRIPS_PATH = _ROOT / "slot_designer" / "weights" / "M15" / "reel_strips.json"

# 9 symbol families. topdollar appears ONLY on R3.
SYMBOLS = ("blank", "cherry", "1bar", "2bar", "3bar", "high7",
           "doublediamond", "topdollar", "jackpot")

# Big-win symbols (顶奖路径) that mode 7 freezes to mode 1.
# doublediamond carries pay_id 1 (3-wild 200×) AND wild-substitution
# amplification for high7/bar pays. high7 carries pay_id 2/21 (30×) +
# wild-amplified versions.
BIGWIN_SYMBOLS = ("doublediamond", "high7")

# Symbols that exist on each reel (some don't appear on all)
SYMBOLS_BY_REEL = {
    0: ("blank", "cherry", "1bar", "2bar", "3bar", "high7", "doublediamond", "jackpot"),
    1: ("blank", "cherry", "1bar", "2bar", "3bar", "high7", "doublediamond", "jackpot"),
    2: ("blank", "cherry", "1bar", "2bar", "3bar", "high7", "doublediamond", "topdollar", "jackpot"),
}

# Per-family per-reel weight bounds (integer >= 1 typically; topdollar
# can be float for trigger fine-tune via post-process clamp).
WEIGHT_BOUNDS_STANDARD: dict[str, tuple[int, int]] = {
    "blank":         (1, 50),    # alternation enforced by strip; weights free
    "cherry":        (1, 50),
    "1bar":          (1, 80),
    "2bar":          (1, 80),
    "3bar":          (1, 80),
    "high7":         (1, 30),    # tighter to keep base CV down
    "doublediamond": (1, 20),    # wild — moderate cap
    "topdollar":     (1, 40),    # only R3, controls trigger
    "jackpot":       (1, 5),     # filler, low weight
}

WEIGHT_BOUNDS_LUCKY: dict[str, tuple[int, int]] = {
    "blank":         (1, 40),
    "cherry":        (1, 60),
    "1bar":          (1, 100),
    "2bar":          (1, 100),
    "3bar":          (1, 100),
    "high7":         (1, 50),
    "doublediamond": (1, 30),
    "topdollar":     (1, 80),    # higher trigger for lucky
    "jackpot":       (1, 5),
}

WEIGHT_BOUNDS_BY_MODE = {
    1: WEIGHT_BOUNDS_STANDARD,
    7: WEIGHT_BOUNDS_STANDARD,
    2: WEIGHT_BOUNDS_LUCKY,
    5: WEIGHT_BOUNDS_LUCKY,
}

# Player experience targets per mode.
EXPERIENCE_TARGETS = {
    1: {
        # Total RTP target (base + feature) — primary
        "total_rtp_pct": 95.0,
        "total_rtp_tol_pp": 1.0,
        # Base RTP target — secondary (controls split with Feature)
        "base_rtp_pct": 42.75,
        "base_rtp_tol_pp": 1.5,
        # Per-mode trigger rate (controls feature contribution)
        "trigger_rate_target": 0.01136,    # 1/88
        "trigger_rate_tol": 0.001,
        # Family RTP share bands (BASE only)
        # Wild + high7 kept LOW share for CV control. Bar/Cherry main.
        "family_share_bands_base": {
            "wild_pure":  (0.0, 0.03),    # 200× pure-wild kept rare
            "high7":      (0.03, 0.15),
            "bar3":       (0.05, 0.18),
            "bar2":       (0.05, 0.20),
            "bar1":       (0.05, 0.20),
            "bar_mixed":  (0.05, 0.20),
            "cherry":     (0.15, 0.40),   # Cherry primary smoother
        },
        "wild_on_payline_band": (0.04, 0.12),   # tighter — wild rare for low CV
        "per_reel_density_lo_by_family": {
            "doublediamond": 0.005, "high7": 0.005,
            "3bar": 0.005, "2bar": 0.01, "1bar": 0.01,
            "cherry": 0.005, "jackpot": 0.0,
        },
        "per_reel_density_hi_by_family": {
            "doublediamond": 0.04,    # ↓ from 0.10 (CV control)
            "high7": 0.05,            # ↓ from 0.10 (CV control)
            "3bar": 0.15, "2bar": 0.20, "1bar": 0.30,
            "cherry": 0.10, "jackpot": 0.05,
        },
        "uniformity_ratio_cap": {
            "doublediamond": 2.5, "high7": 2.5,
        },
        "per_reel_blank_variance_strength": 15.0,
        # Base CV target — KEY low-volatility constraint
        "base_cv_target": 4.0,
    },
    7: {
        "total_rtp_pct": 85.0,
        "total_rtp_tol_pp": 1.5,
        "base_rtp_pct": 32.75,
        "base_rtp_tol_pp": 1.5,
        "trigger_rate_target": 0.01136,    # SAME as mode 1 (frozen)
        "trigger_rate_tol": 0.001,
        # Mode 7 family bands: Bar/Cherry can drop (略砍 small wins)
        # but Bar should still appear on R3 (per-reel balance)
        "family_share_bands_base": {
            "wild_pure":  (0.0, 0.04),
            "high7":      (0.03, 0.18),
            "bar3":       (0.03, 0.20),
            "bar2":       (0.03, 0.20),
            "bar1":       (0.03, 0.20),
            "bar_mixed":  (0.03, 0.20),
            "cherry":     (0.10, 0.40),
        },
        "wild_on_payline_band": (0.04, 0.14),  # similar to mode 1 (frozen)
        "per_reel_density_lo_by_family": {
            "doublediamond": 0.005, "high7": 0.005,
            "3bar": 0.005, "2bar": 0.005, "1bar": 0.005,
            "cherry": 0.003, "jackpot": 0.0,
        },
        "per_reel_density_hi_by_family": {
            "doublediamond": 0.05, "high7": 0.07,
            "3bar": 0.18, "2bar": 0.20, "1bar": 0.30,
            "cherry": 0.10, "jackpot": 0.05,
        },
        "uniformity_ratio_cap": {
            "doublediamond": 3.0, "high7": 3.0,
        },
        "per_reel_blank_variance_strength": 15.0,  # prevent R3 emptying
    },
    2: {
        "total_rtp_pct": 294.5,
        "total_rtp_tol_pp": 20.0,
        "base_rtp_pct": 135.0,
        "base_rtp_tol_pp": 5.0,
        "hit_rate_target": 0.225,          # ~1.5x mode 1
        "hit_rate_weight": 80.0,
        "trigger_rate_target": 0.0275,    # 1/36 (lucky)
        "trigger_rate_tol": 0.002,
        "family_share_bands_base": {
            "wild_pure":  (0.0, 0.05),
            "high7":      (0.03, 0.18),
            "bar3":       (0.05, 0.20),
            "bar2":       (0.05, 0.22),
            "bar1":       (0.05, 0.22),
            "bar_mixed":  (0.05, 0.22),
            "cherry":     (0.10, 0.40),
        },
        "wild_on_payline_band": (0.10, 0.25),
        "per_reel_density_lo_by_family": {
            "doublediamond": 0.01, "high7": 0.01,
            "3bar": 0.01, "2bar": 0.01, "1bar": 0.01,
            "cherry": 0.005, "jackpot": 0.0,
        },
        "per_reel_density_hi_by_family": {
            "doublediamond": 0.15, "high7": 0.15,
            "3bar": 0.20, "2bar": 0.22, "1bar": 0.32,
            "cherry": 0.12, "jackpot": 0.05,
        },
        "uniformity_ratio_cap": {
            "doublediamond": 3.0, "high7": 3.0,
        },
        "per_reel_blank_variance_strength": 15.0,
    },
    5: {
        "total_rtp_pct": 500.0,
        "total_rtp_tol_pp": 30.0,
        "trigger_rate_target": 0.0276,    # ≈ same as mode 2
        "trigger_rate_tol": 0.005,
        "wild_on_payline_band": (0.10, 0.32),
        "per_reel_density_lo_by_family": {
            "doublediamond": 0.01, "high7": 0.01,
            "3bar": 0.01, "2bar": 0.01, "1bar": 0.01,
            "cherry": 0.005, "jackpot": 0.0,
        },
        "per_reel_density_hi_by_family": {
            "doublediamond": 0.18, "high7": 0.18,
            "3bar": 0.20, "2bar": 0.22, "1bar": 0.32,
            "cherry": 0.12, "jackpot": 0.05,
        },
        "uniformity_ratio_cap": {
            "doublediamond": 3.0, "high7": 3.0,
        },
        "per_reel_blank_variance_strength": 15.0,
    },
}


# pay_id -> family classification for RTP share aggregation
PAY_TO_FAMILY = {
    "1":   "wild_pure",       # 3-doublediamond 200×
    "2":   "high7",           # high7 wild_required (counts as high7 family contribution)
    "21":  "high7",           # high7 pure
    "3":   "bar3",            # 3-3bar 20×
    "5":   "bar2",            # 3-2bar 10×
    "7":   "bar1",            # 3-1bar 5×
    "8":   "bar_mixed",       # mixed 3-bar 2×
    "4":   "cherry",          # 3-cherry 15×
    "71":  "cherry",          # 2-cherry 5×
    "9":   "cherry",          # 1-cherry 1×
    "666": "topdollar_trigger",  # scatter trigger, multiplier 0
}


def family_rtp_breakdown_base(profile: dict) -> dict[str, float]:
    """Per-family BASE RTP contribution (in pp). Excludes Feature."""
    family_rtp: dict[str, float] = defaultdict(float)
    for pid, rtp_contrib in profile.get("pay_rtp", {}).items():
        family = PAY_TO_FAMILY.get(pid, "unknown")
        if family == "topdollar_trigger":
            continue  # multiplier 0, no RTP contribution
        family_rtp[family] += rtp_contrib
    return {k: v * 100 for k, v in family_rtp.items()}


def wild_on_payline_p(reel_marginals: list[dict[str, float]]) -> float:
    """P(>=1 doublediamond on payline)."""
    p_no = 1.0
    for marg in reel_marginals:
        p_no *= (1.0 - marg.get("doublediamond", 0))
    return 1.0 - p_no


def trigger_rate_from_marginals(reel_marginals: list[dict[str, float]]) -> float:
    """topdollar lands on R3 payline = Feature trigger rate."""
    return reel_marginals[2].get("topdollar", 0.0)


def per_reel_family_density(weights: list[list[int]],
                             strip: list[list[str]]) -> dict[tuple[str, int], float]:
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
                                fr_weights: dict[tuple[str, int], int]) -> list[list[int]]:
    out = []
    for r_idx, strip_reel in enumerate(strip):
        reel = []
        for sym in strip_reel:
            key = (sym, r_idx)
            reel.append(int(fr_weights.get(key, 1)))
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


def load_feature_spec(weights_path: Path) -> FeatureSpec | None:
    """Read feature_params from a mode's weights.json file."""
    try:
        data = json.loads(weights_path.read_text(encoding="utf-8"))
        fp = data.get("feature_params")
        if not fp:
            return None
        return FeatureSpec(
            x_count_weights=tuple(fp["x_count_weights"]),
            y_count_weights=tuple(fp["y_count_weights"]),
            x_value_weights=tuple(fp.get("x_value_weights", (1.0,) * 10)),
            y_value_weights=tuple(fp.get("y_value_weights", (1.0,) * 2)),
            accept_threshold=fp.get("accept_threshold", 40),
            max_rounds=fp.get("max_rounds", 4),
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def evaluate_candidate(
    fr_weights: dict[tuple[str, int], int],
    strip: list[list[str]],
    evaluator,
    paytable: list[dict],
    cost_weights: CostWeights,
    experience_targets: dict,
    feature_ev: float,
    frozen_weights: dict[tuple[str, int], int] | None = None,
):
    """Return (cost, predicted_profile, family_rtp, wild_p, trigger, weights)."""
    weights = build_weights_from_uniform(strip, fr_weights)
    counts = counts_from_weights(strip, weights)
    marg = marginals_from_counts(counts)
    pred = analytic_profile_from_marginals(evaluator, marg)

    base_rtp_pp = pred["rtp_pct"]
    trigger = trigger_rate_from_marginals(marg)
    feature_rtp_pp = trigger * feature_ev * 100  # trigger as fraction × EV(in x) × 100 for pp
    total_rtp_pp = base_rtp_pp + feature_rtp_pp

    cost = 0.0

    # Total RTP target (primary)
    total_target = experience_targets["total_rtp_pct"]
    rtp_gap = abs(total_rtp_pp - total_target)
    cost += 4.0 * (rtp_gap / 0.5) ** 2

    # Base RTP target (secondary — fixes split with Feature)
    base_target = experience_targets.get("base_rtp_pct")
    if base_target is not None:
        base_gap = abs(base_rtp_pp - base_target)
        cost += 6.0 * (base_gap / 0.5) ** 2

    # Trigger rate target (independent — controls Feature contribution)
    trigger_target = experience_targets["trigger_rate_target"]
    trigger_gap = abs(trigger - trigger_target)
    cost += 100.0 * (trigger_gap / 0.001) ** 2

    # Hit rate target (mode 2 specifically wants ~1.5x mode 1)
    hit_target = experience_targets.get("hit_rate_target")
    hit_weight = experience_targets.get("hit_rate_weight", 0.0)
    if hit_target is not None and hit_weight > 0:
        hit_actual = pred.get("hit_rate", 0.0)
        cost += hit_weight * ((hit_actual - hit_target) / 0.01) ** 2

    # Family RTP shares (base only)
    family_rtp = family_rtp_breakdown_base(pred)
    base_rtp = pred["rtp_pct"]

    share_bands = experience_targets.get("family_share_bands_base", {})
    for f, (lo, hi) in share_bands.items():
        actual = family_rtp.get(f, 0.0) / base_rtp if base_rtp > 0 else 0
        if actual < lo:
            cost += 50.0 * ((lo - actual) * 100) ** 2
        elif actual > hi:
            cost += 50.0 * ((actual - hi) * 100) ** 2

    # Wild on payline
    wild_p = wild_on_payline_p(marg)
    wild_lo, wild_hi = experience_targets["wild_on_payline_band"]
    if wild_p < wild_lo:
        cost += 200.0 * ((wild_lo - wild_p) * 100) ** 2
    elif wild_p > wild_hi:
        cost += 200.0 * ((wild_p - wild_hi) * 100) ** 2

    # Per-family per-reel density caps
    densities = per_reel_family_density(weights, strip)
    lo_by_fam = experience_targets.get("per_reel_density_lo_by_family", {})
    hi_by_fam = experience_targets.get("per_reel_density_hi_by_family", {})
    for (f, r), d in densities.items():
        if f == "blank" or f == "topdollar":
            continue  # filler / scatter handled separately
        den_lo = lo_by_fam.get(f, 0.005)
        den_hi = hi_by_fam.get(f, 0.20)
        if d < den_lo:
            cost += 50.0 * ((den_lo - d) * 100) ** 2
        elif d > den_hi:
            cost += 80.0 * ((d - den_hi) * 100) ** 2

    # Per-reel Blank balance variance
    blank_var_k = experience_targets.get("per_reel_blank_variance_strength", 0.0)
    if blank_var_k > 0:
        blanks_pp = [densities.get(("blank", r), 0.0) * 100 for r in range(3)]
        mean_b = sum(blanks_pp) / 3
        variance_pp2 = sum((b - mean_b) ** 2 for b in blanks_pp) / 3
        cost += blank_var_k * variance_pp2

    # Top-tier uniformity (high7, doublediamond) cross-reel
    uniformity_cap = experience_targets.get("uniformity_ratio_cap", {})
    for fam, ratio_cap in uniformity_cap.items():
        per_reel = [densities.get((fam, r), 0.0) for r in range(3)]
        mn = min(per_reel)
        mx = max(per_reel)
        if mn > 1e-6:
            ratio = mx / mn
            if ratio > ratio_cap:
                cost += 40.0 * (ratio - ratio_cap) ** 2

    # Base CV target (mode 1 specifically)
    base_cv_target = experience_targets.get("base_cv_target")
    if base_cv_target is not None:
        actual_cv = pred.get("cv", 0.0)
        if actual_cv > base_cv_target:
            cost += 100.0 * (actual_cv - base_cv_target) ** 2

    return cost, pred, family_rtp, wild_p, trigger, weights, total_rtp_pp


def search_weights(
    strip,
    evaluator,
    paytable,
    experience_targets,
    cost_weights,
    weight_bounds,
    feature_ev: float,
    frozen_weights=None,
    weight_floors=None,
    seed=0,
    iterations=15000,
    verbose=False,
):
    rng = Random(seed)
    frozen = frozen_weights or {}
    floors = weight_floors or {}

    # Initialize
    fr_weights: dict[tuple[str, int], int] = {}
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

    best = dict(fr_weights)
    best_cost, _, _, _, _, _, _ = evaluate_candidate(
        best, strip, evaluator, paytable, cost_weights, experience_targets,
        feature_ev, frozen_weights=frozen,
    )
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
            cur = cand[key]
            delta = rng.gauss(0, sigma_pct * (hi - lo))
            new = int(round(cur + delta))
            new = max(effective_lo, min(hi, new))
            cand[key] = new

        cost, _, _, _, _, _, _ = evaluate_candidate(
            cand, strip, evaluator, paytable, cost_weights, experience_targets,
            feature_ev, frozen_weights=frozen,
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
        if verbose and (step <= 5 or step % 1500 == 0):
            print(f"    step {step:>5}  cost={best_cost:.3f}  sigma={sigma_pct:.3f}")

    return best, best_cost


def print_diagnostics(label, fr_weights, strip, evaluator, paytable, exp_targets,
                      cost_weights, feature_ev: float, frozen_weights=None):
    cost, pred, family_rtp, wild_p, trigger, weights, total_rtp = evaluate_candidate(
        fr_weights, strip, evaluator, paytable, cost_weights, exp_targets,
        feature_ev, frozen_weights=frozen_weights,
    )
    print(f"\n  {label}:")
    print(f"    cost={cost:.3f}")
    print(f"    Total RTP={total_rtp:.3f}% (base={pred['rtp_pct']:.3f}% + feature={trigger*feature_ev*100:.3f}%)")
    print(f"    Base hit={pred['hit_rate']:.3%}  Base CV={pred['cv']:.2f}")
    print(f"    Wild on payline={wild_p*100:.2f}%  Trigger={trigger*100:.3f}% (1 in {1/trigger if trigger > 0 else 0:.0f})")
    print(f"    Family RTP (base, pp):")
    base_total = pred["rtp_pct"]
    for f in ("wild_pure", "high7", "bar3", "bar2", "bar1", "bar_mixed", "cherry"):
        v = family_rtp.get(f, 0.0)
        share = v / base_total * 100 if base_total > 0 else 0
        print(f"       {f:12s}: {v:6.2f}pp ({share:5.1f}%)")
    print(f"    Per-reel density:")
    densities = per_reel_family_density(weights, strip)
    fams_in_order = ("doublediamond", "high7", "3bar", "2bar", "1bar", "cherry", "topdollar", "jackpot", "blank")
    print(f"       {'family':14s} R1     R2     R3")
    for f in fams_in_order:
        d = [densities.get((f, r), 0) * 100 for r in range(3)]
        print(f"       {f:14s} {d[0]:5.2f}% {d[1]:5.2f}% {d[2]:5.2f}%")
    return pred, family_rtp, wild_p, trigger, weights, total_rtp


def main(modes_to_run=(1, 7)):
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    strip = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    symbols_reg = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"], reroll_blocks=spec.get("reroll_blocks"))
    evaluator = PaytableEvaluator(symbols_reg, rules, spec["evaluation_order"])
    paytable = spec["pays"]

    mode1_bigwin_weights: dict[tuple[str, int], int] | None = None
    mode1_all_weights: dict[tuple[str, int], int] | None = None
    mode2_all_weights: dict[tuple[str, int], int] | None = None

    for mode in modes_to_run:
        weights_path = _ROOT / "slot_designer" / "weights" / "M15" / f"mode_{mode}" / "weights.json"
        feature_spec = load_feature_spec(weights_path)
        if feature_spec is None:
            print(f"  [skip] mode {mode}: no feature_params on disk")
            continue
        from slot_designer.engine.feature_m15 import analyze_feature
        feature_stats = analyze_feature(feature_spec)
        feature_ev = feature_stats.expected_payout
        print(f"\n=== Mode {mode} M15 player-experience tune ===")
        print(f"  feature EV (from disk feature_params) = {feature_ev:.3f}×")

        exp_targets = EXPERIENCE_TARGETS[mode]
        cost_weights = CostWeights(rtp_weight=0, shape_weight=0, cv_weight=0, hit_weight=0)
        # cost_weights is dummy here; tune_m15 has its own cost components

        # Mode 7: freeze high7 + doublediamond weights to mode 1.
        # Mode 5: ALL weights byte-copy from mode 2 (per design — mode 5 differs from mode 2 only in feature_params).
        # Mode 2: weight floors for ALL non-blank symbols ≥ mode 1's value
        # → lucky enforces "every pay frequency ≥ standard" at the per-position level.
        frozen_weights = None
        weight_floors = None
        if mode == 7 and mode1_bigwin_weights is not None:
            frozen_weights = dict(mode1_bigwin_weights)
            print(f"  frozen big-win weights (high7 + doublediamond) = mode 1's")
        elif mode == 5 and mode2_all_weights is not None:
            frozen_weights = dict(mode2_all_weights)
            print(f"  ALL weights frozen = mode 2 (mode 5 differs only in feature_params)")
        elif mode == 2 and mode1_all_weights is not None:
            # Lucky mode: every non-blank symbol weight ≥ mode 1's per position.
            # blank can drop (more pays in lucky), topdollar special (controls trigger).
            weight_floors = {
                (sym, r): w for (sym, r), w in mode1_all_weights.items()
                if sym not in ("blank", "topdollar")
            }
            print(f"  lucky weight floors = mode 1's weights (non-blank/non-topdollar)")

        weight_bounds = WEIGHT_BOUNDS_BY_MODE[mode]
        best, best_cost = search_weights(
            strip, evaluator, paytable, exp_targets, cost_weights, weight_bounds,
            feature_ev=feature_ev, frozen_weights=frozen_weights,
            weight_floors=weight_floors,
            seed=mode * 11 + 23, iterations=15000, verbose=True,
        )

        pred, family_rtp, wild_p, trigger, weights, total_rtp = print_diagnostics(
            f"Mode {mode} result", best, strip, evaluator, paytable, exp_targets,
            cost_weights, feature_ev, frozen_weights=frozen_weights,
        )

        if mode == 1:
            mode1_bigwin_weights = {
                (sym, r): best[(sym, r)]
                for sym in BIGWIN_SYMBOLS
                for r in range(3)
            }
            # Capture ALL mode 1 weights for mode 2 lucky floor
            mode1_all_weights = dict(best)
        if mode == 2:
            mode2_all_weights = dict(best)

        # Persist (preserve feature_params block from existing file)
        existing = json.loads(weights_path.read_text(encoding="utf-8"))
        existing["mode"] = mode
        existing["weights"] = weights
        existing["_notes"] = [
            f"M15 mode {mode} v8 (2026-04-26) — player-experience direct tune.",
            "Per-family per-reel uniform weights search (M1 framework).",
            "Cost: total_RTP + base_CV (mode 1) + per-reel Blank variance + family share + wild signature.",
            "Mode 7 freezes high7+doublediamond weights to mode 1 (大奖路径不动).",
            f"Total RTP {total_rtp:.3f}% (base {pred['rtp_pct']:.3f}% + feature {trigger*feature_ev*100:.3f}%)",
            f"Base hit {pred['hit_rate']:.3%}, base CV {pred['cv']:.3f}, wild_on_payline {wild_p*100:.2f}%, trigger {trigger*100:.3f}%",
        ]
        existing["_tuned_summary"] = {
            "total_rtp_pct": total_rtp,
            "base_rtp_pct": pred["rtp_pct"],
            "feature_rtp_pp": trigger * feature_ev * 100,
            "base_hit_rate": pred["hit_rate"],
            "base_cv": pred["cv"],
            "wild_on_payline": wild_p,
            "trigger_rate": trigger,
            "feature_ev": feature_ev,
            "family_rtp_pp_base": {f: round(v, 3) for f, v in family_rtp.items()},
            "method": "player_experience_per_family_per_reel_uniform_v8",
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
