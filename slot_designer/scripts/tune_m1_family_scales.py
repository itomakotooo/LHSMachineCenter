"""Tune M1 per-mode weights as family-scaled TDD baseline — with experience locks.

2026-04-24 v2: previous v1 tuner had bounded per-family scales
[0.25, 4.0] which lets Bar2 × 2.76 while Seven1 × 0.63 — numerically
OK (RTP target hit) but Seven family RTP share dropped from 20% to 10%.
Violates `project_slot_designer_axiom_experience_is_soul`.

v2 fix (per M1 DESIGN.md §8): Seven1/Seven2/Diamond1/Diamond2 family
scales STRICTLY LOCKED to 1.0 for standard modes (1, 7). Lucky modes
(2, 5) get a relaxed upper bound [1.0, 2.5] on Seven/Diamond so they
can be boosted while preserving "顶奖家族不会被砍" invariant.

Only Blank, Cherry, Bar1, Bar2, Bar3 have free [0.25, 4.0] bounds.
RTP target absorbed by adjusting filler (Blank) + small-win (Cherry/Bar)
densities, not by starving 顶奖 symbols.

Parameterization:
    weight[mode N][reel r][pos p] =
        round(TDD_baseline[r][p] × s_N[symbol_at(r, p)])

Where s_N is a 9-dim scalar vector with per-mode bounds from LOCK_CONFIG.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import (
    analytic_profile_from_marginals,
    structurally_reachable_buckets,
    analytic_profile,
)
from slot_designer.engine.loader import load_engine
from slot_designer.engine.evaluator import PaytableEvaluator
from slot_designer.engine.rules import RuleSet
from slot_designer.engine.symbol import SymbolRegistry
from slot_designer.tuner.cost import CostWeights, evaluate_cost
from slot_designer.tuner.layout import marginals_from_counts


SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
STRIPS = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"

# TDD baseline weights (22 stops × 3 reels, from WoO Hot Roll reverse-engineering)
TDD_BASELINE = [
    [1, 2, 12, 1, 5, 5, 4, 5, 5, 7, 17, 25, 18, 25, 19, 18, 26, 24, 19, 9, 3, 6],
    [2, 3, 2, 3, 3, 4, 1, 5, 7, 17, 12, 19, 19, 21, 20, 28, 20, 27, 27, 10, 3, 3],
    [1, 1, 1, 4, 2, 41, 8, 17, 12, 17, 10, 12, 11, 20, 14, 13, 11, 7, 42, 8, 3, 1],
]

# Per-mode family-scale bounds. Standard modes (1, 7) strictly lock
# Seven/Diamond (顶奖家族) at 1.0 to preserve TDD baseline family RTP share.
# Lucky modes (2, 5) allow [1.0, 2.5] upper bound to help hit higher RTP
# without collapsing family shares below benchmark (verified by
# verify_m1_design.py's family-share checks).
SYMBOLS = ("Blank", "Diamond1", "Diamond2", "Seven1", "Seven2",
           "Cherry", "Bar1", "Bar2", "Bar3")

LOCK_CONFIG: dict[int, dict[str, tuple[float, float]]] = {
    # Standard modes (1, 7): Seven/Diamond/Bar STRICT lock at 1.0.
    # Only Blank (fills) and Cherry (low-mult, minimal share impact)
    # are free. This preserves Seven/Bar RATIO exactly from TDD
    # baseline while giving tuner 2 dims to hit RTP/hit target.
    # Cherry bound tight [0.5, 2.0] — Cherry's 3-pay is 10× (small),
    # 1-pay is 1× (fillers), so wide Cherry scaling still preserves
    # Seven family dominance in big-win bucket.
    1: {
        "Blank": (0.10, 4.0),
        "Cherry": (0.50, 2.00),
        "Bar1": (1.0, 1.0),
        "Bar2": (1.0, 1.0),
        "Bar3": (1.0, 1.0),
        "Seven1": (1.0, 1.0),
        "Seven2": (1.0, 1.0),
        "Diamond1": (1.0, 1.0),
        "Diamond2": (1.0, 1.0),
    },
    7: {
        "Blank": (0.10, 4.0),
        "Cherry": (0.50, 2.00),
        "Bar1": (1.0, 1.0),
        "Bar2": (1.0, 1.0),
        "Bar3": (1.0, 1.0),
        "Seven1": (1.0, 1.0),
        "Seven2": (1.0, 1.0),
        "Diamond1": (1.0, 1.0),
        "Diamond2": (1.0, 1.0),
    },
    # Lucky modes (2, 5): relaxed. All non-Blank can boost above 1.0 but
    # not below 1.0 (keeping 顶奖 family at least at TDD density). Bar
    # can't exceed Seven/Diamond's cap so Bar can't Pareto-dominate.
    # Blank allowed lower (more non-blank density needed for 300-500% RTP).
    2: {
        "Blank": (0.08, 4.0),
        "Cherry": (1.0, 2.5),
        "Bar1": (1.0, 2.5),
        "Bar2": (1.0, 2.5),
        "Bar3": (1.0, 2.5),
        "Seven1": (1.0, 2.5),
        "Seven2": (1.0, 2.5),
        "Diamond1": (1.0, 2.5),
        "Diamond2": (1.0, 2.5),
    },
    5: {
        "Blank": (0.05, 4.0),
        "Cherry": (1.0, 4.0),
        "Bar1": (1.0, 4.0),
        "Bar2": (1.0, 4.0),
        "Bar3": (1.0, 4.0),
        "Seven1": (1.0, 4.0),
        "Seven2": (1.0, 4.0),
        "Diamond1": (1.0, 4.0),
        "Diamond2": (1.0, 4.0),
    },
}


def build_weights_from_scales(strips, scales):
    """scales: dict symbol -> float. Apply to TDD baseline."""
    out = []
    for reel_idx, strip in enumerate(strips):
        reel = []
        for pos, sym in enumerate(strip):
            base = TDD_BASELINE[reel_idx][pos]
            scale = scales.get(sym, 1.0)
            reel.append(max(1, int(round(base * scale))))
        out.append(reel)
    return out


def counts_from_weights(strips, weights):
    from collections import defaultdict
    counts = []
    for reel_idx, strip in enumerate(strips):
        c = defaultdict(int)
        for pos, sym in enumerate(strip):
            c[sym] += weights[reel_idx][pos]
        counts.append(dict(c))
    return counts


def evaluate_scales(scales, strips, evaluator, target, reachable, cost_weights):
    """Return (cost, predicted_profile) for a given scale dict."""
    w = build_weights_from_scales(strips, scales)
    counts = counts_from_weights(strips, w)
    marg = marginals_from_counts(counts)
    pred = analytic_profile_from_marginals(evaluator, marg)
    br = evaluate_cost(pred, target, reachable_buckets=reachable, weights=cost_weights)
    return br.total, pred


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


def search_family_scales(
    target, strips, evaluator, reachable, bounds_map,
    seed=0, iterations=8000, verbose=False,
):
    """Random-restart local search over n-dim scale vector with per-symbol bounds.

    ``bounds_map`` is {symbol: (lo, hi)}. Scales initialize at midpoint
    of each bound range (typically 1.0 for locked, 1.0 for free since
    [0.25, 4.0] midpoint on log scale ≈ 1.0).
    """
    rng = Random(seed)
    cost_weights = CostWeights(
        rtp_weight=1.0,
        shape_weight=2.0,
        cv_weight=0.3,
        hit_target=target.get("hit_rate"),
        hit_weight=2.0,
    )
    if "cv" not in target:
        target["cv"] = target.get("std_return_x", 0) / (target["rtp_pct"] / 100)

    # Initialize to 1.0 for all (clamped to bounds)
    best = {s: clamp(1.0, *bounds_map[s]) for s in SYMBOLS}
    best_cost, _ = evaluate_scales(best, strips, evaluator, target, reachable, cost_weights)
    sigma = 0.5
    success = 0
    window = 50
    win_evals = 0

    for step in range(1, iterations + 1):
        cand = dict(best)
        for s in SYMBOLS:
            lo, hi = bounds_map[s]
            if lo == hi:
                continue  # fully locked, skip
            delta = rng.gauss(0, sigma)
            cand[s] = clamp(cand[s] * (1 + delta), lo, hi)
        cost, _ = evaluate_scales(cand, strips, evaluator, target, reachable, cost_weights)
        if cost < best_cost:
            best, best_cost = cand, cost
            success += 1
        win_evals += 1
        if win_evals >= window:
            if success / win_evals > 0.2:
                sigma = min(0.5, sigma * 1.1)
            else:
                sigma = max(0.02, sigma * 0.9)
            success = 0
            win_evals = 0
        if verbose and (step <= 5 or step % 1000 == 0):
            print(f"  step {step:>5} cost={best_cost:.4f} sigma={sigma:.3f}")

    return best, best_cost


def main():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    strips = json.loads(STRIPS.read_text(encoding="utf-8"))["reels"]
    symbols_reg = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"], reroll_blocks=spec.get("reroll_blocks"))
    evaluator = PaytableEvaluator(symbols_reg, rules, spec["evaluation_order"])
    mode1_path = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"
    engine, _ = load_engine(SPEC, mode1_path)
    reachable = structurally_reachable_buckets(engine)

    for mode, target_file in [
        (1, "M1_mode1_classic.target.json"),
        (2, "M1_mode2_lucky.target.json"),
        (5, "M1_mode5_super_lucky.target.json"),
        (7, "M1_mode7_low_rtp.target.json"),
    ]:
        tpath = _ROOT / "slot_designer" / "tuner" / "targets" / target_file
        target = json.loads(tpath.read_text(encoding="utf-8"))
        bounds = LOCK_CONFIG[mode]
        locked = [s for s in SYMBOLS if bounds[s][0] == bounds[s][1]]
        free = [s for s in SYMBOLS if bounds[s][0] != bounds[s][1]]

        print(f"\n=== Mode {mode} family-scale search ===")
        print(f"  RTP target {target['rtp_pct']}% / hit target {target['hit_rate']:.2%}")
        print(f"  Locked at 1.0: {locked}")
        print(f"  Free ({len(free)} dims): {free}")
        best_scales, best_cost = search_family_scales(
            target, strips, evaluator, reachable, bounds,
            seed=mode, iterations=8000, verbose=True,
        )
        w = build_weights_from_scales(strips, best_scales)
        counts = counts_from_weights(strips, w)
        marg = marginals_from_counts(counts)
        pred = analytic_profile_from_marginals(evaluator, marg)
        print(f"  Result RTP {pred['rtp_pct']:.3f}% / hit {pred['hit_rate']:.3%} / CV {pred['cv']:.2f}")
        print(f"  Scales: {', '.join(f'{k}={v:.3f}' for k, v in best_scales.items())}")

        out_path = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        existing["mode"] = mode
        existing["weights"] = w
        existing["_family_scales"] = {k: round(v, 4) for k, v in best_scales.items()}
        existing["_notes"] = [
            f"M1 mode {mode} v4 (2026-04-24) — TDD archetype + experience-locked family scales.",
            f"Seven/Diamond families locked per DESIGN.md §8 (standard modes: strict 1.0; lucky modes: [1.0, upper])",
            "Free: Blank, Cherry, Bar1/2/3. Only fillers + small-win absorb RTP target, preserving 顶奖 family 绝对密度.",
            f"Source archetype: IGT Triple Double Diamond via Wizard of Odds Hot Roll reel mapping.",
            f"Post-tune: RTP {pred['rtp_pct']:.3f}% / hit {pred['hit_rate']:.3%} / CV {pred['cv']:.2f}",
            f"Family scales: {best_scales}",
        ]
        existing["_tuned_summary"] = {
            "rtp_pct": pred["rtp_pct"],
            "hit_rate": pred["hit_rate"],
            "cv": pred["cv"],
            "method": "family_scale_search_v2_locked",
            "family_scales": {k: round(v, 4) for k, v in best_scales.items()},
            "locked_families": locked,
        }
        out_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {out_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
