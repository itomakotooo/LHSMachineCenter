"""Bucket-shape distance metric for tuning.

User constraint: "数值分桶的分布形状" is a hard constraint. Not逐桶值
matching (M1 physically can't make sub-1× pays; M14 has 9.9% there).
Rather: the **shape** of the win-bearing distribution — decay rate,
shoulder position, tail falloff — should align.

Implementation:
  1. Exclude buckets the candidate machine can't structurally reach.
  2. Renormalize both candidate and target to mass = 1 across reachable
     win-bearing buckets.
  3. Compare via Jensen-Shannon divergence (symmetric, bounded in
     [0, ln2 ≈ 0.693], monotone in "distance").

Also provides helper metrics:
  - `log_decay_slope`: least-squares slope of log(bucket_rate) vs log(bucket_mid_x)
  - `tail_mass_above(x)`: Σ prob over buckets whose lower-bound ≥ x

These let the tuner reason about "does M1's shape echo M14's general
decay pattern" beyond just distributional distance.
"""
from __future__ import annotations

import math
from typing import Iterable


# Bucket midpoint for log-decay regression (geometric mean of bounds).
# Top bucket "ge5000" is open-ended; use 10_000 as a finite proxy.
_BUCKET_MID: dict[str, float] = {
    "gt0_lt1":       0.5,
    "ge1_lt5":       math.sqrt(1 * 5),
    "ge5_lt10":      math.sqrt(5 * 10),
    "ge10_lt20":     math.sqrt(10 * 20),
    "ge20_lt50":     math.sqrt(20 * 50),
    "ge50_lt100":    math.sqrt(50 * 100),
    "ge100_lt200":   math.sqrt(100 * 200),
    "ge200_lt500":   math.sqrt(200 * 500),
    "ge500_lt1000":  math.sqrt(500 * 1000),
    "ge1000_lt5000": math.sqrt(1000 * 5000),
    "ge5000":        10_000.0,
}

_BUCKET_LOWER: dict[str, float] = {
    "gt0_lt1":       1e-6,
    "ge1_lt5":       1.0,
    "ge5_lt10":      5.0,
    "ge10_lt20":     10.0,
    "ge20_lt50":     20.0,
    "ge50_lt100":    50.0,
    "ge100_lt200":   100.0,
    "ge200_lt500":   200.0,
    "ge500_lt1000":  500.0,
    "ge1000_lt5000": 1000.0,
    "ge5000":        5000.0,
}


def normalize_to_unit_mass(
    bucket_rate: dict[str, float],
    *,
    exclude: Iterable[str] = (),
) -> dict[str, float]:
    """Drop zero buckets and `exclude` keys, renormalize remaining to sum=1."""
    exclude_set = set(exclude)
    filtered = {
        k: v for k, v in bucket_rate.items()
        if k not in exclude_set and v > 0
    }
    total = sum(filtered.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in filtered.items()}


def _kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """KL(p || q). Assumes p, q share support (any p[k] > 0 implies q[k] > 0)."""
    s = 0.0
    for k, pv in p.items():
        if pv <= 0:
            continue
        qv = q.get(k, 0.0)
        if qv <= 0:
            # p puts mass where q has none → infinite KL. Clip to a large
            # finite penalty so the tuner can still make progress.
            s += pv * 30.0
        else:
            s += pv * math.log(pv / qv)
    return s


def js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon divergence. Returns a value in [0, ln2]."""
    all_keys = set(p) | set(q)
    if not all_keys:
        return 0.0
    m = {k: 0.5 * (p.get(k, 0.0) + q.get(k, 0.0)) for k in all_keys}
    return 0.5 * (_kl_divergence(p, m) + _kl_divergence(q, m))


def shape_distance(
    candidate_bucket_rate: dict[str, float],
    target_bucket_rate: dict[str, float],
    *,
    reachable_buckets: Iterable[str] | None = None,
) -> dict[str, float]:
    """Compare two bucket distributions in a shape-preserving way.

    If `reachable_buckets` is provided (typically computed once via
    `analytic_rtp.structurally_reachable_buckets`), target mass in
    non-reachable buckets is excluded before normalization.

    Returns:
        {
          "js_divergence":  float,      # in [0, ln2]; 0 = identical shape
          "l1_distance":    float,      # Σ |p_k - q_k|
          "candidate_log_slope": float, # decay rate (see below)
          "target_log_slope":   float,
          "slope_delta":        float,
          "candidate_tail_100": float,  # mass ≥ 100x (post-normalization)
          "target_tail_100":    float,
        }

    "log slope" is the least-squares slope of log(bucket_rate) vs
    log(bucket_midpoint). A shallower slope → slower decay → fatter tail.
    """
    exclude = ()
    if reachable_buckets is not None:
        reachable = set(reachable_buckets)
        exclude = [k for k in target_bucket_rate if k not in reachable]

    p = normalize_to_unit_mass(candidate_bucket_rate, exclude=exclude)
    q = normalize_to_unit_mass(target_bucket_rate, exclude=exclude)

    js = js_divergence(p, q)
    l1 = sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in set(p) | set(q))

    p_slope = _log_decay_slope(p)
    q_slope = _log_decay_slope(q)

    p_tail = sum(v for k, v in p.items() if _BUCKET_LOWER.get(k, 0) >= 100)
    q_tail = sum(v for k, v in q.items() if _BUCKET_LOWER.get(k, 0) >= 100)

    return {
        "js_divergence": js,
        "l1_distance": l1,
        "candidate_log_slope": p_slope,
        "target_log_slope": q_slope,
        "slope_delta": p_slope - q_slope,
        "candidate_tail_100": p_tail,
        "target_tail_100": q_tail,
    }


def _log_decay_slope(normalized_buckets: dict[str, float]) -> float:
    """Least-squares slope of log(rate) vs log(midpoint) across buckets with
    positive probability. Returns 0 if <2 data points."""
    pts = [
        (math.log(_BUCKET_MID[k]), math.log(v))
        for k, v in normalized_buckets.items()
        if v > 0 and k in _BUCKET_MID
    ]
    if len(pts) < 2:
        return 0.0
    n = len(pts)
    mean_x = sum(x for x, _ in pts) / n
    mean_y = sum(y for _, y in pts) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in pts)
    den = sum((x - mean_x) ** 2 for x, _ in pts)
    return num / den if den > 0 else 0.0
