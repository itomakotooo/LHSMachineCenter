"""M279 sim-based tuner v2 — bucket-shape + family-share + per-symbol granular.

v1 was family-level scaling (4 family scalars per reel × 3 reels = 12 dim)
which is too coarse: it can't disentangle high7 vs low7 vs mid7 within
the 7-family group, and the cost function only enforced RTP/hit/nudge
without bucket-shape or family-share constraints.

v2 cost function includes:
  - RTP / hit / nudge / wheel target gaps (v1 carryover)
  - Bucket-shape KS divergence vs target (NEW)
  - Family-share band penalty (7-family / bar / wild-jp / wheel) (NEW)
  - Top-jackpot freq target band (NEW)
  - Asymmetric reel: Reel 2 high7 marginal / Reel 1 high7 marginal <= 0.5 (NEW)

v2 search space:
  - Per-symbol per-reel weight scalars (NOT family-level).
  - 12 symbols × 3 reels = 36 scalars (vs v1's 12).
  - Coordinate descent over each (reel, symbol) pair with sigma 0.7/1.43.

Sample size:
  - Per-eval default 30000 spins (vs v1's 12000).
  - Reduces noise on the rare 250x jackpot — pay 101 needs ~200k spins
    for a single hit, so 30k still has high variance there. Acceptable
    for v1 baseline; for production tighten to 100k+.
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

from slot_designer.machines.M279.plugins.m279.engine import (
    M279SessionState,
    M279SpinEngine,
    ST_NUDGE,
    ST_PAID,
    ST_WHEEL,
)
from slot_designer.machines.M279.plugins.m279.loader import build_m279_engine, load_m279_engine


# Symbol families — used for share computation, NOT for tuner search dim.
PAYING_7 = {"low7", "mid7", "high7"}
PAYING_BAR = {"5bar", "bar"}
WILD_SINGLE = {"wild", "wild2x", "wild3x"}
WILD_STACK = {"wild_up", "wild2x_mid", "wild_down"}
WILD_JACKPOT_PAY_IDS = {101, 102, 103, 104}
SEVEN_PAY_IDS = {1, 2, 3, 6}        # high7, mid7, low7, mixed-7
BAR_PAY_IDS = {4, 5, 7}              # 5bar, bar, mixed-bar


# Bucket boundaries (matches verify + emit semantics).
BUCKET_BOUNDS = [
    ("gt0_lt1", 0.0, 1.0),
    ("ge1_lt5", 1.0, 5.0),
    ("ge5_lt10", 5.0, 10.0),
    ("ge10_lt20", 10.0, 20.0),
    ("ge20_lt50", 20.0, 50.0),
    ("ge50_lt100", 50.0, 100.0),
    ("ge100_lt200", 100.0, 200.0),
    ("ge200_lt500", 200.0, 500.0),
    ("ge500", 500.0, float("inf")),
]


def bucket_for(ret_x: float) -> str | None:
    if ret_x <= 0:
        return None
    for name, lo, hi in BUCKET_BOUNDS:
        if lo <= ret_x < hi:
            return name
    return None


def sim_metrics(
    engine: M279SpinEngine,
    n_spins: int,
    seed: int = 42,
) -> dict:
    """Comprehensive sim — returns RTP / hit / nudge / wheel / bucket /
    family share / top-jp freq / asymmetric reel. Used by both tuner
    cost function and verify."""
    state = M279SessionState()
    rng = Random(seed)
    total_win = 0
    total_bet = 0
    total_win_sq = 0  # for std/CV
    hit = 0
    nudge = 0
    wheel = 0
    pay_count = Counter()
    pay_win = Counter()
    bucket_count = Counter()
    pay_101_count = 0

    for _ in range(n_spins):
        rounds = engine.run_session(rng, state.meter)
        sw = sum(r.win_credits for r in rounds)
        total_win += sw
        total_bet += engine.bet_amount
        total_win_sq += (sw / engine.bet_amount) ** 2
        if sw > 0:
            hit += 1
            ret_x = sw / engine.bet_amount
            b = bucket_for(ret_x)
            if b:
                bucket_count[b] += 1
        if any(r.spin_type == ST_NUDGE for r in rounds):
            nudge += 1
        if any(r.spin_type == ST_WHEEL for r in rounds):
            wheel += 1
        for r in rounds:
            for p in r.pay_results:
                pay_count[p.pay_id] += 1
                pay_win[p.pay_id] += int(p.multiplier * engine.bet_amount)
                if p.pay_id == 101:
                    pay_101_count += 1
            # Wheel pay attribution
            if r.spin_type == ST_WHEEL:
                pay_win["wheel"] += r.win_credits

    avg_ret = total_win / total_bet
    var_ret = (total_win_sq / n_spins) - avg_ret ** 2
    std_ret = max(0.0, var_ret) ** 0.5

    # Family RTP shares
    seven_rtp = sum(pay_win[p] for p in SEVEN_PAY_IDS) / total_bet
    bar_rtp = sum(pay_win[p] for p in BAR_PAY_IDS) / total_bet
    wild_jp_rtp = sum(pay_win[p] for p in WILD_JACKPOT_PAY_IDS) / total_bet
    wheel_rtp = pay_win.get("wheel", 0) / total_bet
    total_rtp_pct = avg_ret * 100
    total_rtp_share_known = seven_rtp + bar_rtp + wild_jp_rtp + wheel_rtp

    return {
        "rtp_pct": total_rtp_pct,
        "hit_rate": hit / n_spins,
        "nudge_rate": nudge / n_spins,
        "wheel_rate": wheel / n_spins,
        "std_return": std_ret,
        "cv": std_ret / avg_ret if avg_ret > 0 else 0.0,
        "bucket_rate": {b[0]: bucket_count[b[0]] / n_spins for b in BUCKET_BOUNDS},
        "family_share": {
            "seven_family": seven_rtp / avg_ret if avg_ret > 0 else 0,
            "bar_family": bar_rtp / avg_ret if avg_ret > 0 else 0,
            "wild_jackpot": wild_jp_rtp / avg_ret if avg_ret > 0 else 0,
            "wheel_feature": wheel_rtp / avg_ret if avg_ret > 0 else 0,
        },
        "top_jp_freq_per_n_spins": (n_spins / pay_101_count) if pay_101_count > 0 else float("inf"),
        "n_spins": n_spins,
        "_pay_count": dict(pay_count),
    }


def _ks_divergence(a: dict[str, float], b: dict[str, float]) -> float:
    """Total variation between two bucket distributions (sums to 1).
    Both are dicts keyed by bucket name. Missing keys = 0."""
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys)


def cost_v2(metrics: dict, target: dict) -> tuple[float, dict]:
    """v2 cost function. Returns (total_cost, breakdown_dict)."""
    breakdown: dict[str, float] = {}

    # Carry-over from v1: RTP / hit / nudge
    rtp_gap = metrics["rtp_pct"] - target["rtp_pct"]
    rtp_tol = max(target.get("rtp_tolerance_pp", 1.0), 0.1)
    breakdown["rtp"] = (rtp_gap / rtp_tol) ** 2 * 1.5  # heaviest weight

    hit_gap = metrics["hit_rate"] - target["hit_rate"]
    hit_tol = max(target.get("hit_tolerance_pp", 1.0) / 100, 0.001)
    breakdown["hit"] = (hit_gap / hit_tol) ** 2 * 0.5

    nudge_gap = metrics["nudge_rate"] - target.get("nudge_rate", 0.122)
    nudge_tol = max(target.get("nudge_tolerance_pp", 3.0) / 100, 0.005)
    breakdown["nudge"] = (nudge_gap / nudge_tol) ** 2 * 0.3

    # NEW v2: bucket-shape KS divergence
    target_bucket = target.get("bucket_rate", {})
    if target_bucket:
        # Normalize both to sum-to-hit-rate (not sum-to-1) to weight by absolute
        # rate not just shape. KS scaled by 1/tol gives quadratic-like cost.
        ks = _ks_divergence(metrics["bucket_rate"], target_bucket)
        ks_tol = max(target.get("bucket_ks_tolerance", 0.10), 0.01)
        breakdown["bucket_ks"] = (ks / ks_tol) ** 2 * 0.3

    # NEW v2: family share band
    # v2.1: weight bumped from 0.4 to 5.0 — tuner was hitting RTP target by
    # cutting wild3x (collaterally killing wild_jp share). With family weight
    # 5.0 and wild_jp band [0.15, 0.22], a 5pp gap costs (0.05/0.05)^2 × 5 = 5,
    # competitive with RTP-gap costs.
    family_band = target.get("family_share_band", {})
    family_cost = 0.0
    for fam, (lo, hi) in family_band.items():
        actual = metrics["family_share"].get(fam, 0)
        if actual < lo:
            family_cost += ((lo - actual) / 0.03) ** 2  # tightened tol from 0.05 to 0.03
        elif actual > hi:
            family_cost += ((actual - hi) / 0.03) ** 2
    breakdown["family_share"] = family_cost * 5.0

    # NEW v2: top-jackpot freq band (multiplicative)
    top_jp = target.get("top_jp_freq_target", {})
    if top_jp.get("pay_101_per_n_spins"):
        target_freq = top_jp["pay_101_per_n_spins"]
        actual_freq = metrics["top_jp_freq_per_n_spins"]
        tol = top_jp.get("pay_101_tolerance", 0.5)
        if actual_freq != float("inf"):
            ratio = actual_freq / target_freq
            log_gap = abs(math_log(ratio)) if ratio > 0 else 1.0
            band = math_log(1 + tol)
            breakdown["top_jp"] = max(0, log_gap - band) ** 2 * 0.2
        else:
            breakdown["top_jp"] = 0.5  # mild penalty for never hitting

    total = sum(breakdown.values())
    return total, breakdown


def math_log(x: float) -> float:
    import math
    if x <= 0:
        return -float("inf")
    return math.log(x)


def _per_symbol_scaled_weights(
    strips: list[list[str]],
    base_weights: list[list[int]],
    sym_scales: list[dict[str, float]],
) -> list[list[int]]:
    """Apply per-(reel, symbol) scalars. Each ``sym_scales[i]`` is a
    dict {sym -> scalar}; symbols not in dict use scale=1.0."""
    out: list[list[int]] = []
    for reel_idx, (strip, weights) in enumerate(zip(strips, base_weights)):
        scales = sym_scales[reel_idx]
        new_w: list[int] = []
        for sym, w in zip(strip, weights):
            scale = scales.get(sym, 1.0)
            new_w.append(max(1, int(round(w * scale))))
        out.append(new_w)
    return out


def tune_v2(
    spec_path: Path,
    weights_path: Path,
    target: dict,
    *,
    n_eval_spins: int = 30000,
    max_iters: int = 30,
    sigma: float = 0.7,
    seed: int = 42,
    verbose: bool = True,
    locked_symbols: set[str] | None = None,
) -> dict:
    """v2 coordinate descent — per-symbol per-reel granular scaling.

    Each iteration tries scaling one (reel, symbol) pair up or down by
    sigma, accept if cost improves.
    """
    strips_doc = json.loads(
        (weights_path.parent.parent / "reel_strips.json").read_text(encoding="utf-8"),
    )
    weights_doc = json.loads(weights_path.read_text(encoding="utf-8"))
    spec_doc = json.loads(spec_path.read_text(encoding="utf-8"))
    strips = strips_doc["reels"]
    n_reels = len(strips)

    # All unique symbols across reels (excluding stack — we don't tune the
    # atomic trio individually because nudge mechanic depends on byte-
    # identical layout; tune them as a group OR not at all for v1).
    unique_syms_per_reel: list[list[str]] = []
    for reel in strips:
        unique_syms_per_reel.append(sorted(set(reel)))

    # Per-(reel, symbol) scale dict
    sym_scales: list[dict[str, float]] = [
        {sym: 1.0 for sym in syms}
        for syms in unique_syms_per_reel
    ]

    def _scaled():
        return _per_symbol_scaled_weights(strips, weights_doc["weights"], sym_scales)

    def _evaluate(weights_array: list[list[int]]) -> tuple[dict, float, dict]:
        # In-memory engine build — no disk roundtrip avoids race
        # conditions where the tuner's tmp file got read empty.
        tmp_doc = copy.deepcopy(weights_doc)
        tmp_doc["weights"] = weights_array
        engine = build_m279_engine(spec_doc, tmp_doc, strips_doc)
        m = sim_metrics(engine, n_eval_spins, seed=seed)
        c, breakdown = cost_v2(m, target)
        return m, c, breakdown

    if verbose:
        print(f"=== M279 sim-based tuner v2 (per-symbol per-reel granular) ===")
        print(f"target rtp={target['rtp_pct']} hit={target['hit_rate']} mode={weights_doc['mode']}")
    cur_weights = _scaled()
    cur_metrics, cur_cost, cur_break = _evaluate(cur_weights)
    if verbose:
        print(f"baseline: rtp={cur_metrics['rtp_pct']:.2f}% "
              f"hit={cur_metrics['hit_rate']*100:.2f}% "
              f"nudge={cur_metrics['nudge_rate']*100:.2f}% "
              f"7fam={cur_metrics['family_share']['seven_family']*100:.1f}% "
              f"bar={cur_metrics['family_share']['bar_family']*100:.1f}% "
              f" cost={cur_cost:.2f}")
        for k, v in cur_break.items():
            if v > 0.01:
                print(f"    {k}: {v:.3f}")

    iter_count = 0
    last_improvement = -1
    t0 = time.time()
    cur_sigma = sigma

    locked = locked_symbols or set()
    while iter_count < max_iters:
        improved = False
        for reel_idx in range(n_reels):
            # Iterate symbols; pick most-impactful one first by current cost
            for sym in unique_syms_per_reel[reel_idx]:
                # Don't tune blank to extreme - it's the dominant weight
                if sym in WILD_STACK:
                    # Tune stack as a group: same scale for all 3
                    continue  # for v1 leave stack at base
                # NEW v2.1: locked symbols (caller-specified) skip tuning.
                # Used for two-phase approach: Phase A locks paying+blank,
                # tunes wild family for wild_jp share; Phase B locks wild
                # family, tunes paying+blank for RTP.
                if sym in locked:
                    continue
                for direction in (cur_sigma, 1.0 / cur_sigma):
                    saved = sym_scales[reel_idx][sym]
                    sym_scales[reel_idx][sym] = saved * direction
                    trial_weights = _scaled()
                    trial_metrics, trial_cost, trial_break = _evaluate(trial_weights)
                    if trial_cost < cur_cost - 0.5:  # require meaningful improvement
                        cur_metrics = trial_metrics
                        cur_cost = trial_cost
                        cur_break = trial_break
                        cur_weights = trial_weights
                        improved = True
                        last_improvement = iter_count
                        if verbose:
                            print(f"  [iter {iter_count}] reel{reel_idx+1} {sym} ×{direction:.2f}: "
                                  f"rtp={cur_metrics['rtp_pct']:.2f}% "
                                  f"hit={cur_metrics['hit_rate']*100:.2f}% "
                                  f"nudge={cur_metrics['nudge_rate']*100:.2f}%  cost={cur_cost:.2f}")
                        break
                    else:
                        sym_scales[reel_idx][sym] = saved
        iter_count += 1
        if not improved:
            if cur_sigma < 1.05:
                if verbose:
                    print(f"  [iter {iter_count}] sigma converged; stopping")
                break
            cur_sigma = max(1.05, (cur_sigma - 1) * 0.5 + 1)
            if verbose:
                print(f"  [iter {iter_count}] no improvement; tightening sigma to {cur_sigma:.2f}")

    elapsed = time.time() - t0
    if verbose:
        print(f"\n=== final ({elapsed:.1f}s, {iter_count} iters) ===")
        print(f"rtp={cur_metrics['rtp_pct']:.2f}% (target {target['rtp_pct']})")
        print(f"hit={cur_metrics['hit_rate']*100:.2f}% (target {target['hit_rate']*100:.2f})")
        print(f"nudge={cur_metrics['nudge_rate']*100:.2f}%")
        print(f"family share: 7fam={cur_metrics['family_share']['seven_family']*100:.1f}% "
              f"bar={cur_metrics['family_share']['bar_family']*100:.1f}% "
              f"wild_jp={cur_metrics['family_share']['wild_jackpot']*100:.1f}% "
              f"wheel={cur_metrics['family_share']['wheel_feature']*100:.1f}%")
        print(f"top JP 1/{cur_metrics['top_jp_freq_per_n_spins']:.0f} spins")
        print(f"std_return={cur_metrics['std_return']:.2f}  CV={cur_metrics['cv']:.2f}")

    return {
        "weights": cur_weights,
        "metrics": cur_metrics,
        "sym_scales_per_reel": sym_scales,
        "cost": cur_cost,
        "iterations": iter_count,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="M279 sim-based tuner v2")
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--weights", required=True, type=Path)
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--out-weights", type=Path, default=None)
    p.add_argument("--n-eval-spins", type=int, default=30000)
    p.add_argument("--max-iters", type=int, default=15)
    p.add_argument("--sigma", type=float, default=0.7)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--verbose", action="store_true", default=True)
    p.add_argument(
        "--locked-symbols", default="",
        help="Comma-separated symbol names to LOCK (skip tuning). Used for "
             "two-phase tuning. Phase A locks paying+blank, tunes wild family. "
             "Phase B locks wild family, tunes paying+blank.",
    )
    args = p.parse_args()

    target = json.loads(args.target.read_text(encoding="utf-8"))
    locked_set = set(s.strip() for s in args.locked_symbols.split(",") if s.strip())
    result = tune_v2(
        args.spec, args.weights, target,
        n_eval_spins=args.n_eval_spins,
        max_iters=args.max_iters,
        sigma=args.sigma,
        seed=args.seed,
        verbose=args.verbose,
        locked_symbols=locked_set if locked_set else None,
    )

    out = args.out_weights or args.weights
    weights_doc = json.loads(args.weights.read_text(encoding="utf-8"))
    weights_doc["weights"] = result["weights"]
    weights_doc.setdefault("_tuned_summary", {}).update({
        "rtp_pct": result["metrics"]["rtp_pct"],
        "hit_rate": result["metrics"]["hit_rate"],
        "nudge_rate": result["metrics"]["nudge_rate"],
        "wheel_rate": result["metrics"]["wheel_rate"],
        "std_return": result["metrics"]["std_return"],
        "cv": result["metrics"]["cv"],
        "family_share": result["metrics"]["family_share"],
        "top_jp_freq_per_n_spins": result["metrics"]["top_jp_freq_per_n_spins"],
        "iterations": result["iterations"],
        "sym_scales_per_reel": result["sym_scales_per_reel"],
    })
    out.write_text(json.dumps(weights_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote tuned weights -> {out}")


if __name__ == "__main__":
    main()
