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
          "bucket_rtp":    {key: rtp},    # Σ P(combo) × multiplier within each bucket
                                          #   (sum equals rtp_pct/100; players FEEL the bucket
                                          #    that has the most RTP weight)
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


def _is_blocked_combo(combo: tuple[str, ...], reroll_blocks: list) -> bool:
    """Match combo against reroll_blocks pattern list. None in pattern = wildcard."""
    if not reroll_blocks:
        return False
    for rule in reroll_blocks:
        pattern = rule.pattern
        if all(p is None or p == s for p, s in zip(pattern, combo)):
            return True
    return False


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
    """Closed-form RTP/bucket/pay_id profile, with reroll-block correction.

    If the engine declares ``reroll_blocks`` (M37 (wild,grand,wild)), the
    engine re-draws those spins until a non-blocked combo lands. In steady
    state this means the post-reroll P'(C) = P(C)/(1−P_blocked) for C not
    blocked, 0 otherwise. All return values reflect post-reroll metrics so
    they match what the simulator + production both produce. Without this
    correction, mode 5 analytic over-reported by ~2.4pp (combo P=0.024%,
    payout 100×, contribution 2.4pp lost when rerolled).
    """
    reroll_blocks = (
        engine.evaluator.rules.reroll_blocks
        if getattr(engine.evaluator, "rules", None) is not None
        else []
    )

    rtp = 0.0
    rtp_sq = 0.0
    hit_prob = 0.0
    bucket_prob: dict[str, float] = defaultdict(float)
    bucket_rtp: dict[str, float] = defaultdict(float)
    pay_prob: dict[str, float] = defaultdict(float)
    pay_rtp: dict[str, float] = defaultdict(float)
    total_prob = 0.0
    p_blocked = 0.0  # for reroll renormalization

    # Re-enumerate so we can check combos against reroll_blocks (the
    # enumerate_payline generator already lost the combo info).
    if len(engine.payline_positions) != engine.n_cols:
        raise NotImplementedError(
            "analytic_profile assumes 1 payline per column (M1-style)."
        )
    reel_marginals = [compute_reel_marginal(r) for r in engine.reels]
    symbols_per_reel = [list(m.keys()) for m in reel_marginals]
    import itertools
    for combo in itertools.product(*symbols_per_reel):
        prob = 1.0
        for marg, sym in zip(reel_marginals, combo):
            prob *= marg[sym]
        if prob == 0:
            continue
        if _is_blocked_combo(combo, reroll_blocks):
            p_blocked += prob
            continue  # blocked: contributes nothing to post-reroll metrics
        total_prob += prob
        result = engine.evaluator.evaluate_payline(list(combo))
        if result is None:
            continue
        mult = float(result.multiplier)
        rtp += prob * mult
        rtp_sq += prob * mult * mult
        hit_prob += prob
        pay_prob[str(result.pay_id)] += prob
        pay_rtp[str(result.pay_id)] += prob * mult
        bucket = multiplier_to_bucket(mult)
        if bucket is not None:
            bucket_prob[bucket] += prob
            bucket_rtp[bucket] += prob * mult

    # Renormalize post-reroll (safe no-op when p_blocked == 0)
    if p_blocked > 0:
        renorm = 1.0 / (1.0 - p_blocked)
        rtp *= renorm
        rtp_sq *= renorm
        hit_prob *= renorm
        total_prob *= renorm  # should now sum to 1.0
        for d in (bucket_prob, bucket_rtp, pay_prob, pay_rtp):
            for k in d:
                d[k] *= renorm

    # Var(multiplier) = E[M²] - E[M]²; std_return_x matches analyzer's
    # player_impact.volatility.std_return_x (= σ of per-spin multiplier)
    var = max(0.0, rtp_sq - rtp * rtp)
    import math
    std_return_x = math.sqrt(var)
    # Coefficient of variation per Lucas & Singh 2008: σ/par; higher = more
    # volatile, inversely correlated with player time-on-device
    cv = std_return_x / rtp if rtp > 0 else 0.0

    return {
        "rtp_pct": rtp * 100,
        "hit_rate": hit_prob,
        "std_return_x": std_return_x,
        "cv": cv,
        "bucket_rate": dict(bucket_prob),
        "bucket_rtp": dict(bucket_rtp),  # per-bucket RTP contribution (sums to rtp_pct/100)
        "pay_hits": dict(pay_prob),
        "pay_rtp": dict(pay_rtp),  # per-pay_id RTP contribution (probability-weighted multiplier sum, includes wild-substitution boost)
        "total_prob": total_prob,  # sanity: should equal 1.0
        "p_reroll_blocked": p_blocked,
    }


def analytic_profile_from_marginals(
    evaluator,
    reel_marginals: list[dict[str, float]],
) -> dict:
    """Same output as analytic_profile, but takes pre-computed reel marginals.

    Used by the tuner to avoid rebuilding ReelStrip/SpinEngine objects per
    candidate evaluation — we only need per-symbol probabilities for the
    middle-row of each reel.
    """
    import itertools

    rtp = 0.0
    rtp_sq = 0.0
    hit_prob = 0.0
    bucket_prob: dict[str, float] = defaultdict(float)
    bucket_rtp: dict[str, float] = defaultdict(float)
    pay_prob: dict[str, float] = defaultdict(float)
    pay_rtp: dict[str, float] = defaultdict(float)
    total_prob = 0.0

    symbols_per_reel = [list(m.keys()) for m in reel_marginals]
    for combo in itertools.product(*symbols_per_reel):
        prob = 1.0
        for marg, sym in zip(reel_marginals, combo):
            prob *= marg[sym]
        if prob == 0:
            continue
        total_prob += prob
        result = evaluator.evaluate_payline(list(combo))
        if result is None:
            continue
        mult = float(result.multiplier)
        rtp += prob * mult
        rtp_sq += prob * mult * mult
        hit_prob += prob
        pay_prob[str(result.pay_id)] += prob
        pay_rtp[str(result.pay_id)] += prob * mult
        bucket = multiplier_to_bucket(mult)
        if bucket is not None:
            bucket_prob[bucket] += prob
            bucket_rtp[bucket] += prob * mult

    var = max(0.0, rtp_sq - rtp * rtp)
    import math
    std_return_x = math.sqrt(var)
    cv = std_return_x / rtp if rtp > 0 else 0.0

    return {
        "rtp_pct": rtp * 100,
        "hit_rate": hit_prob,
        "std_return_x": std_return_x,
        "cv": cv,
        "bucket_rate": dict(bucket_prob),
        "bucket_rtp": dict(bucket_rtp),
        "pay_hits": dict(pay_prob),
        "pay_rtp": dict(pay_rtp),
        "total_prob": total_prob,
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
