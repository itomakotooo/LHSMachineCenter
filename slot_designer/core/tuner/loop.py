"""Lightweight (1+1)-ES with 1/5 success rule + multi-restart.

Zero third-party deps. Works on 27-variable count space for single-line slots. For
bigger machines (more symbols / reels), bump restart count or sigma.

Why (1+1)-ES:
  - Cost surface for RTP/shape tuning is smooth and unimodal once we
    rescale symbol counts. Gradient-free with self-adapting step size
    handles the mild non-convexity from integer rounding / ReelStrip
    regeneration without needing population-based methods.
  - 1/5 rule (Rechenberg) adapts sigma: σ ← σ·c if success rate over a
    window > 1/5, else σ ← σ/c. Standard c = 0.82^(1/n) for n-d problem.
  - Multi-restart guards against local minima from integer rounding.

Reporting: per-step diagnostic prints cost breakdown so we can watch the
trajectory. Final best candidate is returned as a counts list suitable
for `layout.apply_counts`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from random import Random
from typing import Callable


@dataclass
class ESConfig:
    sigma_init: float = 8.0          # initial mutation std (in count units)
    sigma_min: float = 0.5
    sigma_max: float = 50.0
    count_min: int = 1               # scalar fallback min count per (symbol, reel)
    count_max: int = 2000            # maximum — prevents runaway
    window: int = 30                 # evaluations between sigma adaptations
    c_adapt: float = 0.82            # 1/5 rule decay factor
    # machine 2026-04-24: per-(symbol, reel) count floor. Prevents tuner's
    # internal-state / apply_counts drift when a symbol has >1 stop per
    # reel and tuner explores counts below n_stops — apply_counts clamps
    # per-stop weight to min=1 → materialized count = n_stops × 1 ≠
    # tuner's reported count. When this dict is provided, key is
    # (reel_idx, symbol) and floor overrides ``count_min``. Missing keys
    # use the scalar ``count_min``.
    count_min_per_key: dict | None = None


@dataclass
class ESResult:
    best_counts: list[dict[str, int]]
    best_cost: float
    best_breakdown: object           # CostBreakdown
    evaluations: int
    sigma_final: float
    trace: list[dict] = field(default_factory=list)


def flatten(counts: list[dict[str, int]]) -> tuple[list[int], list[tuple[int, str]]]:
    """counts → (flat list, keys). Enables vector-style mutation."""
    flat: list[int] = []
    keys: list[tuple[int, str]] = []
    for reel_idx, reel in enumerate(counts):
        for sym in sorted(reel.keys()):
            keys.append((reel_idx, sym))
            flat.append(reel[sym])
    return flat, keys


def unflatten(flat: list[int], keys: list[tuple[int, str]], n_reels: int) -> list[dict[str, int]]:
    out: list[dict[str, int]] = [dict() for _ in range(n_reels)]
    for (reel_idx, sym), v in zip(keys, flat):
        out[reel_idx][sym] = v
    return out


def run_one_plus_one_es(
    x0: list[dict[str, int]],
    cost_fn: Callable[[list[dict[str, int]]], tuple[float, object]],
    max_evaluations: int,
    *,
    config: ESConfig | None = None,
    rng: Random | None = None,
    verbose: bool = False,
) -> ESResult:
    cfg = config or ESConfig()
    rng = rng or Random(0)
    n_reels = len(x0)
    flat_best, keys = flatten(x0)
    cost_best, break_best = cost_fn(x0)

    sigma = cfg.sigma_init
    success_count = 0
    adapt_count = 0
    window_evals = 0
    trace: list[dict] = []

    # Expected-1/5 adaptation schedule (Rechenberg): n-dimensional c_adapt.
    c_per_axis = cfg.c_adapt ** (1.0 / max(1, len(flat_best)))

    # Per-key count floor: use per_key dict if supplied, else scalar count_min.
    per_key_min = cfg.count_min_per_key or {}
    def _floor_for(i: int) -> int:
        return per_key_min.get(keys[i], cfg.count_min)

    for step in range(1, max_evaluations + 1):
        # Gaussian mutation in count units, round to integers, clamp
        mutation = [rng.gauss(0.0, sigma) for _ in flat_best]
        flat_cand = [
            max(_floor_for(i), min(cfg.count_max, int(round(flat_best[i] + mutation[i]))))
            for i in range(len(flat_best))
        ]
        x_cand = unflatten(flat_cand, keys, n_reels)
        cost_cand, break_cand = cost_fn(x_cand)

        improved = cost_cand < cost_best
        if improved:
            flat_best = flat_cand
            cost_best = cost_cand
            break_best = break_cand
            success_count += 1

        # Adaptive step (1/5 rule on sliding window)
        window_evals += 1
        if window_evals >= cfg.window:
            success_rate = success_count / window_evals
            if success_rate > 0.2:
                sigma = min(cfg.sigma_max, sigma / c_per_axis ** cfg.window)
            else:
                sigma = max(cfg.sigma_min, sigma * c_per_axis ** cfg.window)
            success_count = 0
            window_evals = 0
            adapt_count += 1

        if verbose and (step <= 5 or step % 100 == 0 or improved):
            print(f"  step {step:>5} cost={cost_best:<10.4f} σ={sigma:<6.2f} "
                  f"ΔRTP={break_best.rtp_gap_pp:+.3f}pp JS={break_best.shape_js:.4f} "
                  f"{'*' if improved else ' '}")
        trace.append({
            "step": step, "cost": cost_cand, "improved": improved,
            "sigma": sigma, "rtp_gap_pp": break_cand.rtp_gap_pp,
            "shape_js": break_cand.shape_js,
        })

    return ESResult(
        best_counts=unflatten(flat_best, keys, n_reels),
        best_cost=cost_best,
        best_breakdown=break_best,
        evaluations=max_evaluations,
        sigma_final=sigma,
        trace=trace,
    )


def run_with_restarts(
    x0: list[dict[str, int]],
    cost_fn: Callable[[list[dict[str, int]]], tuple[float, object]],
    *,
    restarts: int = 3,
    evaluations_per_restart: int = 800,
    config: ESConfig | None = None,
    master_seed: int = 0,
    verbose: bool = False,
) -> ESResult:
    """Run (1+1)-ES multiple times with different RNG seeds + mild x0 jitter,
    return globally best result. Guards against sigma-collapse local minima.
    """
    cfg_eff = config or ESConfig()
    per_key_min = cfg_eff.count_min_per_key or {}
    best: ESResult | None = None
    for r in range(restarts):
        rng = Random(master_seed + r * 1000)
        # Jitter starting point mildly after first restart
        if r == 0:
            start = x0
        else:
            flat, keys = flatten(x0)
            jitter_sigma = cfg_eff.sigma_init * 1.5
            flat_j = [
                max(
                    per_key_min.get(keys[i], cfg_eff.count_min),
                    int(round(flat[i] + rng.gauss(0.0, jitter_sigma))),
                )
                for i in range(len(flat))
            ]
            start = unflatten(flat_j, keys, len(x0))
        if verbose:
            print(f"\n=== restart {r+1}/{restarts} ===")
        result = run_one_plus_one_es(
            start, cost_fn, evaluations_per_restart,
            config=config, rng=rng, verbose=verbose,
        )
        if best is None or result.best_cost < best.best_cost:
            best = result
    assert best is not None
    return best
