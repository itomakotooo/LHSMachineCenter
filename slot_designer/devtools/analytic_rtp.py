"""Closed-form RTP + bucket distribution calculator.

For single-payline 3-col machines like M1 the payline is a product of
independent reel marginals, so enumerating all payline combos is exact
and fast (9 symbols/reel × 3 reels = 729 combos on M1). Analyzer's
simulator is still ground-truth for everything that depends on round
sequence (streaks, session RTP, bankruptcy), but predicted RTP / bucket
shape / per-pay_id hit rate are obtainable analytically — which gives the
tuner a gradient signal thousands of times faster than running the real
simulator for each candidate.

API:
    analytic_profile(engine) -> dict
        {
          "rtp_pct":       float,         # Σ P(combo) × multiplier × 100
          "hit_rate":      float,         # Σ P(combo where pay fires)
          "bucket_rate":   {key: prob},   # P(multiplier ∈ bucket k), excluding zero-win
          "pay_hits":      {pid_str: prob}, # P(pay_id fires)
          "total_prob":    float,         # sanity: should equal 1.0
        }

Machines with multi-payline / bonus chain / cascading / ways-pay need
their own analytic path (future Phase). For those, `analytic_profile`
raises NotImplementedError rather than silently returning wrong math.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..engine.spin import SpinEngine


# Matches analyzer's return_bucket() thresholds (see MEMORY.md §22).
# Ordered high→low so first match wins.
_BUCKETS: tuple[tuple[float, str], ...] = (
    (5000.0, "ge5000"),
    (1000.0, "ge1000_lt5000"),
    (500.0, "ge500_lt1000"),
    (200.0, "ge200_lt500"),
    (100.0, "ge100_lt200"),
    (50.0, "ge50_lt100"),
    (20.0, "ge20_lt50"),
    (10.0, "ge10_lt20"),
    (5.0, "ge5_lt10"),
    (1.0, "ge1_lt5"),
    (0.0, "gt0_lt1"),  # 0 < mult < 1
)

ALL_BUCKET_KEYS = tuple(k for _, k in _BUCKETS)  # high → low order


def multiplier_to_bucket(multiplier: float) -> str | None:
    """Map multiplier → analyzer's return_bucket key. Returns None for 0-win."""
    if multiplier <= 0:
        return None
    for edge, key in _BUCKETS:
        if multiplier >= edge:
            return key
    # 0 < mult < 1 hits the (0.0, "gt0_lt1") sentinel above; unreachable.
    return None


def compute_reel_marginal(reel) -> dict[str, float]:
    """P(picked-stop's payline symbol == s) for one reel."""
    total = reel.total_weight
    weights: dict[str, int] = defaultdict(int)
    for stop in reel.stops:
        weights[stop.symbol] += stop.weight
    return {s: w / total for s, w in weights.items()}


def enumerate_payline(engine: SpinEngine) -> Iterable[tuple[float, int | None, float]]:
    """Yield (probability, pay_id_or_None, multiplier) for every payline combo.

    Payline-independent-reels assumption: M1-style classic 3-col slot
    where each reel's middle-row symbol is independent of the others.
    """
    if len(engine.payline_positions) != engine.n_cols:
        raise NotImplementedError(
            "analytic_profile assumes 1 payline per column (M1-style). "
            "Multi-payline / ways-pay machines need a dedicated analytic path."
        )

    reel_marginals = [compute_reel_marginal(r) for r in engine.reels]
    symbols_per_reel = [list(m.keys()) for m in reel_marginals]

    # 3 nested loops is fine for M1 (9×9×9); generalize to itertools.product
    # so it works for any n_cols.
    import itertools
    for combo in itertools.product(*symbols_per_reel):
        prob = 1.0
        for marg, sym in zip(reel_marginals, combo):
            prob *= marg[sym]
        if prob == 0:
            continue
        result = engine.evaluator.evaluate_payline(list(combo))
        if result is None:
            yield (prob, None, 0.0)
        else:
            yield (prob, result.pay_id, float(result.multiplier))


def analytic_profile(engine: SpinEngine) -> dict:
    rtp = 0.0
    hit_prob = 0.0
    bucket_prob: dict[str, float] = defaultdict(float)
    pay_prob: dict[str, float] = defaultdict(float)
    total_prob = 0.0

    for prob, pay_id, mult in enumerate_payline(engine):
        total_prob += prob
        rtp += prob * mult
        if pay_id is not None:
            hit_prob += prob
            pay_prob[str(pay_id)] += prob
            bucket = multiplier_to_bucket(mult)
            if bucket is not None:
                bucket_prob[bucket] += prob

    return {
        "rtp_pct": rtp * 100,
        "hit_rate": hit_prob,
        "bucket_rate": dict(bucket_prob),
        "pay_hits": dict(pay_prob),
        "total_prob": total_prob,  # sanity: should equal 1.0
    }


def structurally_reachable_buckets(engine: SpinEngine) -> set[str]:
    """Which buckets can this engine ever produce, given its paytable?

    Runs analytic_profile with probability-ignoring intent: any combo that
    can fire defines the bucket set. Useful for shape comparison (a bucket
    the machine can never reach shouldn't count as "mismatched").
    """
    reachable: set[str] = set()
    reel_marginals = [compute_reel_marginal(r) for r in engine.reels]
    symbols_per_reel = [list(m.keys()) for m in reel_marginals]
    import itertools
    for combo in itertools.product(*symbols_per_reel):
        result = engine.evaluator.evaluate_payline(list(combo))
        if result is not None:
            bucket = multiplier_to_bucket(result.multiplier)
            if bucket is not None:
                reachable.add(bucket)
    return reachable
