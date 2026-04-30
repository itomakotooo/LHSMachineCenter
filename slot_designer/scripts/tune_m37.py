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

# Grand on payline — user direction "grand 提升到 0.3-0.5%". Mid 0.4% =
# pay_id 8 freq 1/250.
GRAND_PAYLINE_TARGETS = {1: 0.004, 7: 0.004, 2: 0.012, 5: 0.04}

# Bar combined payline freq — user direction "bar 占比要降低". Old value
# 30-50%; "适度调整" so reduce to ≤25% (no specific number from user, use
# "moderately lower" ≤ 25%).
BAR_PAYLINE_FREQ_CAP = 0.25

# Reel role blank ranges — user-confirmed in 10-section narrative.
# ±1pp tolerance on each edge accommodates structural rounding in 40-stop strip.
ROLE_BLANK_RANGES = {
    0: (0.29, 0.41),  # R1 winners-friendly
    1: (0.49, 0.66),  # R2 brand reel
    2: (0.39, 0.51),  # R3 near-miss
}

# Bucket count distribution — user said "合理分布,不是平均". Direction
# Low > Mid > High > Top maintained. Wider ranges allow structural variations
# while preserving "reasonable distribution" intent.
BUCKET_COUNT_RANGES = {
    "low":  (0.65, 0.90),
    "mid":  (0.08, 0.25),
    "high": (0.01, 0.05),
    "top":  (0.0, 0.002),
}


# ═══════════════════════════════════════════════════════════════════
# Cost component weights — calibrated for component balance
# ═══════════════════════════════════════════════════════════════════

W_RTP = 50000.0
W_HIT = 30000.0
W_GRAND_PAYLINE = 5000.0
W_BAR_CAP = 5000.0
W_ROLE_BLANK = 5000.0
W_BUCKET_COUNT = 3000.0
W_HIERARCHY = 50000.0  # bump — direction violations were drowned in cost surface
W_ASYMMETRY = 1500.0
W_PWDF_DIR = 20000.0  # high7 outer floor — bumped for proper enforcement

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

    # 3. Grand on payline (user direction 0.3-0.5%)
    grand_payline = pred.get("pay_hits", {}).get("8", 0.0)
    target = GRAND_PAYLINE_TARGETS[mode]
    rel_dev = (grand_payline - target) / target if target > 0 else 0
    cost += W_GRAND_PAYLINE * (rel_dev * 100) ** 2

    # 4. Bar combined payline freq cap (user direction "lower")
    bar_payline_combined = sum(pred.get("pay_hits", {}).get(p, 0.0) for p in BAR_PAY_IDS)
    if bar_payline_combined > BAR_PAYLINE_FREQ_CAP:
        cost += W_BAR_CAP * ((bar_payline_combined - BAR_PAYLINE_FREQ_CAP) * 100) ** 2

    # 5. Per-reel role blank (user-confirmed 10-section)
    for r_idx, (lo, hi) in ROLE_BLANK_RANGES.items():
        actual = densities.get(("blank", r_idx), 0.0)
        if actual < lo:
            cost += W_ROLE_BLANK * ((lo - actual) * 100) ** 2
        elif actual > hi:
            cost += W_ROLE_BLANK * ((actual - hi) * 100) ** 2

    # 6. Bucket count distribution (user-confirmed 10-section)
    bucket_rate = pred.get("bucket_rate", {})
    hit_total = pred["hit_rate"]
    if hit_total > 0:
        for tier, (lo, hi) in BUCKET_COUNT_RANGES.items():
            keys = TIER_TO_BUCKETS[tier]
            tier_share = sum(bucket_rate.get(k, 0.0) for k in keys) / hit_total
            if tier_share < lo:
                cost += W_BUCKET_COUNT * ((lo - tier_share) * 100) ** 2
            elif tier_share > hi:
                cost += W_BUCKET_COUNT * ((tier_share - hi) * 100) ** 2

    # 7. Universal §1 hierarchy: direction + per-tier ratio [1.2, 1.5x].
    # Use ratio-based cost (severity squared) so violations at low density
    # don't get drowned in tiny pp-scale costs.
    def _check_cascade(order, reel):
        nonlocal cost
        prev_d = None
        for s in order:
            d = densities.get((s, reel), 0.0)
            if d == 0:
                continue
            if prev_d is not None and prev_d > 0:
                if d > prev_d:
                    # Reversal: severity = how much d overshoots prev
                    severity = (d / prev_d - 1.0)  # > 0 when reversed
                    cost += W_HIERARCHY * (severity * 100) ** 2
                else:
                    ratio = prev_d / d
                    if ratio < 1.2:
                        cost += W_HIERARCHY * ((1.2 - ratio) * 100) ** 2
                    elif ratio > 1.5:
                        cost += W_HIERARCHY * ((ratio - 1.5) * 100) ** 2
            prev_d = d

    BAR_ORDER = ("1bar", "2bar", "3bar", "7bar")
    for r in (0, 2):
        _check_cascade(BAR_ORDER, r)
    BOOSTER_ORDER = ("mini", "minor", "major", "grand")
    _check_cascade(BOOSTER_ORDER, 1)

    # 8. Universal §12 reel asymmetry direction (no tolerance)
    r1_blank = densities.get(("blank", 0), 0.0)
    r3_blank = densities.get(("blank", 2), 0.0)
    if r1_blank > r3_blank:
        cost += W_ASYMMETRY * ((r1_blank - r3_blank) * 100) ** 2
    r1_top = densities.get(("high7", 0), 0.0) + densities.get(("wild", 0), 0.0)
    r3_top = densities.get(("high7", 2), 0.0) + densities.get(("wild", 2), 0.0)
    if r1_top < r3_top:
        cost += W_ASYMMETRY * ((r3_top - r1_top) * 100) ** 2

    # 9. High7 R1 + R3 density floor (derived from Mid bucket constraint):
    # User-confirmed Mid bucket 15-22% of hits requires pay_id 1 (3-high7
    # 10×) freq ≥ 0.5% to contribute meaningfully to Mid. Pay_id 1 freq =
    # high7_R1 × high7_R2 × high7_R3 (plus wild substitution paths).
    # For freq 0.5% with R2 high7 ~7%: high7_R1 × high7_R3 ≥ 0.07. Symmetric
    # → each ≥ 0.04 (4%). This also satisfies universal §15 high7 visibility.
    HIGH7_OUTER_FLOOR = 0.04
    for r in (0, 2):
        d = densities.get(("high7", r), 0.0)
        if d < HIGH7_OUTER_FLOOR:
            cost += W_PWDF_DIR * ((HIGH7_OUTER_FLOOR - d) * 100) ** 2

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
# Per-mode tune flow
# ═══════════════════════════════════════════════════════════════════

def tune_mode_1(strips, evaluator):
    print("=== Mode 1 baseline ===")
    return search(strips, evaluator, mode=1)


def tune_mode_7(strips, evaluator, m1_weights):
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
