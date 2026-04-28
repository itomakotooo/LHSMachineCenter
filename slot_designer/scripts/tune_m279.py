"""M279 sim-based tuner.

The existing analytic_rtp + ES tuner (scripts/tune.py) assumes single-
payline + no chained-feature mechanics. M279 (9-line + nudge chain +
collect + wheel) doesn't fit that — paylines aren't independent (they
share grid cells) and the nudge chain produces correlated wins on top
of the base spin. Closed-form analytic RTP is intractable.

Approach: simulate-based coordinate descent over per-symbol weights.

Tuning dimensions (per reel):
  - 6 paying-symbol weights: low7 / mid7 / high7 / 5bar / bar / wild family
  - 1 single-wild weight (wild)
  - 1 single-2x weight (wild2x)
  - 1 single-3x weight (wild3x)
  - 1 stack-anchor weight (applied to all 3 stack symbols × 2 anchor positions = 6 stops)
  - 1 blank weight (anchored as fixed multiplier)

Cost = (RTP_target - RTP_actual)² + (hit_target - hit_actual)² × hit_weight +
       (nudge_target - nudge_actual)² × nudge_weight

Tunes until RTP within ±1pp + hit within ±1pp + nudge within ±2pp.

Per-mode targets are read from
  slot_designer/tuner/targets/M279_mode<N>.target.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from collections import Counter
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.engine.m279.engine import M279SessionState, M279SpinEngine, ST_PAID, ST_NUDGE, ST_WHEEL
from slot_designer.engine.m279.loader import load_m279_engine


# Symbol families per the M279 archetype. Used to group stops on the
# strip into a 1-dimensional weight scalar per family per reel.
PAYING_SYMBOLS = {"low7", "mid7", "high7", "5bar", "bar"}
SINGLE_WILDS = {"wild", "wild2x", "wild3x"}
STACK_SYMBOLS = {"wild_up", "wild2x_mid", "wild_down"}


def sim_rtp(
    engine: M279SpinEngine,
    n_spins: int,
    seed: int = 42,
) -> dict:
    """Simulate ``n_spins`` paid spins, return aggregate metrics.

    Returns dict with: rtp_pct, hit_rate, nudge_rate, wheel_rate,
    avg_session_win, big_win_x10_rate.
    """
    state = M279SessionState()
    rng = Random(seed)
    total_win = 0
    total_bet = 0
    hit_count = 0
    nudge_count = 0
    wheel_count = 0
    big_x10 = 0
    for _ in range(n_spins):
        rounds = engine.run_session(rng, state.meter)
        sw = sum(r.win_credits for r in rounds)
        total_win += sw
        total_bet += engine.bet_amount
        if sw > 0:
            hit_count += 1
        if any(r.spin_type == ST_NUDGE for r in rounds):
            nudge_count += 1
        if any(r.spin_type == ST_WHEEL for r in rounds):
            wheel_count += 1
        if sw >= engine.bet_amount * 10:
            big_x10 += 1
    return {
        "rtp_pct": (total_win / total_bet) * 100 if total_bet else 0.0,
        "hit_rate": hit_count / n_spins,
        "nudge_rate": nudge_count / n_spins,
        "wheel_rate": wheel_count / n_spins,
        "big_win_x10_rate": big_x10 / n_spins,
        "avg_session_win": total_win / n_spins if n_spins else 0,
    }


def cost(metrics: dict, target: dict) -> float:
    rtp_gap = metrics["rtp_pct"] - target["rtp_pct"]
    hit_gap = metrics["hit_rate"] - target["hit_rate"]
    rtp_cost = (rtp_gap / max(target.get("rtp_tolerance_pp", 1.0), 0.1)) ** 2
    hit_cost = (hit_gap / max(target.get("hit_tolerance_pp", 1.0) / 100, 0.001)) ** 2
    cost_total = rtp_cost + 0.3 * hit_cost
    if "nudge_rate" in target:
        nudge_gap = metrics["nudge_rate"] - target["nudge_rate"]
        cost_total += (nudge_gap / 0.02) ** 2 * 0.2
    return cost_total


def family_of(symbol: str) -> str:
    if symbol == "blank":
        return "blank"
    if symbol in PAYING_SYMBOLS:
        return "paying"
    if symbol in SINGLE_WILDS:
        return "single_wild"
    if symbol in STACK_SYMBOLS:
        return "stack"
    return "other"


def apply_weight_scales(
    strips: list[list[str]],
    base_weights: list[list[int]],
    scales_per_reel: list[dict[str, float]],
) -> list[list[int]]:
    """Apply per-(reel, symbol) weight scaling.

    Each scales_per_reel[i] is a dict {sym -> scalar}, e.g. {"low7": 1.0,
    "high7": 0.8, "wild": 0.5}. Symbols not in dict use scale=1.0.
    Result is rounded to int (min 1) to satisfy ReelStrip invariant.
    """
    out: list[list[int]] = []
    for reel_idx, (strip, weights) in enumerate(zip(strips, base_weights)):
        scales = scales_per_reel[reel_idx]
        new_w: list[int] = []
        for sym, w in zip(strip, weights):
            scale = scales.get(sym, 1.0)
            new_w.append(max(1, int(round(w * scale))))
        out.append(new_w)
    return out


def tune_coordinate_descent(
    spec_path: Path,
    weights_path: Path,
    target: dict,
    *,
    n_eval_spins: int = 30000,
    max_iters: int = 30,
    sigma: float = 0.7,
    seed: int = 42,
    verbose: bool = True,
) -> dict:
    """Coordinate-descent tuner over per-(reel, family) scalars.

    Each iteration tries scaling one (reel, family) up or down by
    ``sigma`` and keeps the change if cost improves. Repeats until
    no improvement in a full pass OR ``max_iters`` reached.
    """
    # Load the strips + initial weights
    strips_doc = json.loads(
        (weights_path.parent.parent / "reel_strips.json").read_text(encoding="utf-8"),
    )
    weights_doc = json.loads(weights_path.read_text(encoding="utf-8"))
    strips = strips_doc["reels"]
    n_reels = len(strips)

    # Initial scales: 1.0 across the board
    scales: list[dict[str, float]] = [
        {"blank": 1.0, "paying": 1.0, "single_wild": 1.0, "stack": 1.0}
        for _ in range(n_reels)
    ]
    # Per-symbol fine-grained scales (overrides family). Empty initially;
    # tuner can populate selectively if needed.
    sym_scales: list[dict[str, float]] = [{} for _ in range(n_reels)]

    def _scaled_weights() -> list[list[int]]:
        # Build per-reel symbol-specific scales from family fallback
        per_reel_dicts: list[dict[str, float]] = []
        for r_idx in range(n_reels):
            d: dict[str, float] = {}
            for sym in set(strips[r_idx]):
                fam = family_of(sym)
                base = scales[r_idx].get(fam, 1.0)
                fine = sym_scales[r_idx].get(sym, 1.0)
                d[sym] = base * fine
            per_reel_dicts.append(d)
        return apply_weight_scales(strips, weights_doc["weights"], per_reel_dicts)

    def _evaluate(weights_array: list[list[int]]) -> tuple[dict, float]:
        # Write to a temp weights doc + load via M279 loader to get a fresh
        # engine instance (no mutating cached engine). Cheap because spec
        # parse is small.
        tmp_doc = copy.deepcopy(weights_doc)
        tmp_doc["weights"] = weights_array
        tmp_path = weights_path.parent / ".tune_tmp_weights.json"
        tmp_path.write_text(json.dumps(tmp_doc), encoding="utf-8")
        engine, _ = load_m279_engine(spec_path, tmp_path)
        m = sim_rtp(engine, n_eval_spins, seed=seed)
        c = cost(m, target)
        return m, c

    # Baseline
    if verbose:
        print(f"=== M279 sim-based tuner ===")
        print(f"target: {target}")
    cur_weights = _scaled_weights()
    cur_metrics, cur_cost = _evaluate(cur_weights)
    if verbose:
        print(f"baseline: rtp={cur_metrics['rtp_pct']:.2f}% "
              f"hit={cur_metrics['hit_rate']*100:.2f}% "
              f"nudge={cur_metrics['nudge_rate']*100:.2f}% "
              f"wheel={cur_metrics['wheel_rate']*100:.2f}%  cost={cur_cost:.2f}")

    families = ["paying", "stack", "single_wild", "blank"]
    iter_count = 0
    last_improvement = -1
    t0 = time.time()
    while iter_count < max_iters:
        improved = False
        for reel_idx in range(n_reels):
            for fam in families:
                for direction in (sigma, 1.0 / sigma):
                    trial_scales = copy.deepcopy(scales)
                    trial_scales[reel_idx][fam] = trial_scales[reel_idx].get(fam, 1.0) * direction
                    # build trial
                    saved_scales = scales
                    scales[:] = trial_scales
                    trial_weights = _scaled_weights()
                    trial_metrics, trial_cost = _evaluate(trial_weights)
                    if trial_cost < cur_cost:
                        cur_metrics = trial_metrics
                        cur_cost = trial_cost
                        cur_weights = trial_weights
                        improved = True
                        last_improvement = iter_count
                        if verbose:
                            print(f"  [iter {iter_count}] reel{reel_idx+1} {fam} ×{direction:.2f}: "
                                  f"rtp={cur_metrics['rtp_pct']:.2f}% "
                                  f"hit={cur_metrics['hit_rate']*100:.2f}% "
                                  f"nudge={cur_metrics['nudge_rate']*100:.2f}%  cost={cur_cost:.2f}")
                        break  # accept this direction and move on
                    else:
                        scales[:] = saved_scales
                if improved and direction == 1.0 / sigma:
                    continue
        iter_count += 1
        if not improved:
            if verbose:
                print(f"  [iter {iter_count}] no improvement; stopping")
            break
        # Tighten sigma after each successful pass for finer descent
        if iter_count - last_improvement > 2:
            sigma = max(1.05, (sigma - 1) * 0.5 + 1)

    # Cleanup temp file
    tmp_path = weights_path.parent / ".tune_tmp_weights.json"
    if tmp_path.exists():
        tmp_path.unlink()

    elapsed = time.time() - t0
    if verbose:
        print(f"\n=== final ({elapsed:.1f}s, {iter_count} iters) ===")
        print(f"rtp={cur_metrics['rtp_pct']:.2f}% (target {target['rtp_pct']})")
        print(f"hit={cur_metrics['hit_rate']*100:.2f}% (target {target['hit_rate']*100:.2f})")
        print(f"nudge={cur_metrics['nudge_rate']*100:.2f}%")
        print(f"wheel={cur_metrics['wheel_rate']*100:.4f}%")
        print(f"big_x10={cur_metrics['big_win_x10_rate']*100:.2f}%")
        print(f"final scales per reel: {scales}")

    return {
        "weights": cur_weights,
        "metrics": cur_metrics,
        "scales_per_reel": scales,
        "cost": cur_cost,
        "iterations": iter_count,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="M279 sim-based tuner")
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--weights", required=True, type=Path)
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--out-weights", type=Path, default=None,
                   help="defaults to overwriting --weights")
    p.add_argument("--n-eval-spins", type=int, default=30000)
    p.add_argument("--max-iters", type=int, default=20)
    p.add_argument("--sigma", type=float, default=0.7)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--verbose", action="store_true", default=True)
    args = p.parse_args()

    target = json.loads(args.target.read_text(encoding="utf-8"))

    result = tune_coordinate_descent(
        args.spec,
        args.weights,
        target,
        n_eval_spins=args.n_eval_spins,
        max_iters=args.max_iters,
        sigma=args.sigma,
        seed=args.seed,
        verbose=args.verbose,
    )

    out = args.out_weights or args.weights
    weights_doc = json.loads(args.weights.read_text(encoding="utf-8"))
    weights_doc["weights"] = result["weights"]
    weights_doc.setdefault("_tuned_summary", {}).update({
        "rtp_pct": result["metrics"]["rtp_pct"],
        "hit_rate": result["metrics"]["hit_rate"],
        "nudge_rate": result["metrics"]["nudge_rate"],
        "wheel_rate": result["metrics"]["wheel_rate"],
        "scales_per_reel": result["scales_per_reel"],
        "iterations": result["iterations"],
    })
    out.write_text(json.dumps(weights_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote tuned weights → {out}")


if __name__ == "__main__":
    main()
