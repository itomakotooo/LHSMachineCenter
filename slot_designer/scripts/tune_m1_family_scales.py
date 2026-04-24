"""Tune M1 per-mode weights as family-scaled TDD baseline.

The archetype constraint (2026-04-24): M1 is IGT Triple Double Diamond
(Hot Roll-derived 22-stop virtual reel). Mode 1 should be the TDD
baseline reproduced on M1's paytable; modes 2/5/7 should be 'luck
variants' — weights can change per mode BUT per-reel RATIOS within each
symbol family stay locked to TDD.

Without this lock, the (1+1)-ES tuner freely changes weights to hit
RTP targets and produces "weird" distributions (e.g. 18% wild on one
reel, near-zero on others) that don't resemble any real slot machine.

Parameterization: each mode N has 9 scalars, one per symbol family:
    s_N = (s_Blank, s_Diamond1, s_Diamond2, s_Seven1, s_Seven2,
           s_Cherry, s_Bar1, s_Bar2, s_Bar3)
and weight[mode N][reel r][pos p] = round(TDD_baseline[r][p] × s_N[sym_at(r,p)])

RTP differences across modes come from these 9 scalars only. Real-reel
ratio (R1:R2:R3) per family is preserved by construction — the TDD
archetype shape is 100% intact across all modes.

Search: grid over reasonable scalar ranges + local refinement.
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


def search_family_scales(
    target, strips, evaluator, reachable,
    symbols=("Blank", "Diamond1", "Diamond2", "Seven1", "Seven2",
             "Cherry", "Bar1", "Bar2", "Bar3"),
    seed=0, iterations=8000, verbose=False,
    scale_bounds=(0.25, 4.0),  # "not weird" bounds — no family vanishes or explodes
):
    """Random-restart local search over 9-dim scale vector.

    ``scale_bounds`` enforces the user's "假但不怪" constraint: each
    symbol family's scale stays within [0.25, 4.0] of TDD baseline.
    Without bounds the tuner zeros out whole families (Cherry=0.011,
    Bar1=0.012) which is the same Pareto "怪" artifact in family space
    that we fixed in position space.
    """
    rng = Random(seed)
    cost_weights = CostWeights(
        rtp_weight=1.0,
        shape_weight=2.0,
        cv_weight=0.3,
        hit_target=target.get("hit_rate"),
        hit_weight=2.0,  # stronger hit pressure since we want both RTP + hit
    )
    if "cv" not in target:
        target["cv"] = target.get("std_return_x", 0) / (target["rtp_pct"] / 100)

    lo, hi = scale_bounds
    # Seed candidate: Blank=1.0, others=1.0
    best = {s: 1.0 for s in symbols}
    best_cost, _ = evaluate_scales(best, strips, evaluator, target, reachable, cost_weights)
    sigma = 0.5
    success = 0
    window = 50
    win_evals = 0

    for step in range(1, iterations + 1):
        cand = dict(best)
        for s in symbols:
            delta = rng.gauss(0, sigma)
            cand[s] = max(lo, min(hi, cand[s] * (1 + delta)))
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
    # Build engine once for reachable-bucket computation
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

        print(f"\n=== Mode {mode} family-scale search (target RTP {target['rtp_pct']}%, hit {target['hit_rate']:.2%}) ===")
        best_scales, best_cost = search_family_scales(
            target, strips, evaluator, reachable,
            seed=mode, iterations=6000, verbose=True,
        )
        # Compute final metrics
        w = build_weights_from_scales(strips, best_scales)
        counts = counts_from_weights(strips, w)
        marg = marginals_from_counts(counts)
        pred = analytic_profile_from_marginals(evaluator, marg)
        print(f"Mode {mode} RTP: {pred['rtp_pct']:.3f}% (target {target['rtp_pct']}), hit {pred['hit_rate']:.3%} (target {target['hit_rate']:.3%}), CV {pred['cv']:.2f}")
        print(f"  family scales: {', '.join(f'{k}={v:.3f}' for k, v in best_scales.items())}")

        # Write out weights.json
        out_path = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        existing["mode"] = mode
        existing["weights"] = w
        existing["_family_scales"] = {k: round(v, 4) for k, v in best_scales.items()}
        existing["_notes"] = [
            f"M1 mode {mode} v3 (2026-04-24) — TDD family-scaled derivation.",
            "Weights = TDD baseline (Hot Roll / WoO) × per-symbol-family scalar. Per-reel RATIOS preserved exactly from TDD archetype; only absolute levels vary across modes ('假' allowed, '怪' forbidden — no per-position Pareto artifacts).",
            f"Source archetype: IGT Triple Double Diamond via Wizard of Odds Hot Roll reel mapping (https://wizardofodds.com/games/slots/hot-roll/).",
            f"RTP: {pred['rtp_pct']:.3f}% / hit: {pred['hit_rate']:.3%} / CV: {pred['cv']:.2f}",
            f"Family scales: {best_scales}",
        ]
        existing["_tuned_summary"] = {
            "rtp_pct": pred["rtp_pct"],
            "hit_rate": pred["hit_rate"],
            "cv": pred["cv"],
            "method": "family_scale_search",
            "family_scales": {k: round(v, 4) for k, v in best_scales.items()},
        }
        out_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {out_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
