"""M15 Feature Play simulator + analytic EV.

Paytable §5 semantics (2026-04-23):
  - 10 x-options: 1000, 100, 50, 50, 20, 20, 10, 10, 5, 5
  - 2 y-options: ×2, ×2
  - Per round:
      1. Pick count_x ∈ [1, 5] by weight w_count_x
      2. Pick count_y ∈ [0, 2] by weight w_count_y
      3. Draw count_x x-values without replacement from the 10 x pool
      4. Draw count_y y-values without replacement from the 2 y pool
      5. Compute R = sum(x_drawn) × product(y_drawn)  (y=[] → product=1)
  - Player decision: if R >= accept_threshold → accept, else reroll
    (up to 3 rerolls = 4 rounds total; round 4 is forced accept)
  - Spec says test strategy: threshold = 40×

The feature's expected payout per trigger is what this module computes.
Total RTP contribution per paid spin = trigger_rate × feature_ev.

The x_count_weights and y_count_weights are DESIGN PARAMETERS — not
specified in the paytable (it just says "按预设权重控制"). The designer
picks these to hit the target feature RTP. This module provides the
analytic EV + variance for any given weight set so the designer can
sweep / tune without running Monte Carlo.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from math import sqrt


_X_POOL: tuple[int, ...] = (1000, 100, 50, 50, 20, 20, 10, 10, 5, 5)
_Y_POOL: tuple[int, ...] = (2, 2)


@dataclass
class FeatureSpec:
    """Full parameter set for the M15 feature EV calculation."""
    # Weights for picking how many x-values this round (index 0 = count 1, ..., index 4 = count 5)
    x_count_weights: tuple[float, float, float, float, float]
    # Weights for picking how many y-values (index 0 = count 0, ..., index 2 = count 2)
    y_count_weights: tuple[float, float, float]
    # Accept threshold: if R >= threshold on round 1-3, accept. Round 4 forced.
    accept_threshold: float = 40.0
    # Max rounds (3 reroll + 1 forced accept = 4 per spec)
    max_rounds: int = 4


@dataclass
class FeatureStats:
    expected_payout: float       # E[final feature R]
    variance: float              # Var[final feature R]
    std: float                   # sqrt(Var)
    cv: float                    # std / expected_payout (conditional CV of feature)
    p_accept_round1: float       # prob of accepting on round 1
    round_ev_unconditional: float  # E[R] on any single round (for round 4 forced)
    round_ev_given_accept: float   # E[R | R >= threshold] on any single round
    round_p_accept: float          # P(R >= threshold) on any single round
    r_min: float                 # smallest reachable R (floor)
    r_max: float                 # largest reachable R (cap)


def _tuple_prob(pool: tuple[int, ...], size: int) -> list[tuple[tuple[int, ...], float]]:
    """Enumerate every sorted-combination of `size` items drawn without
    replacement from `pool`, with its probability (uniform across
    the ``C(len(pool), size)`` combinations).

    Returns list of (values, prob) pairs.
    """
    n = len(pool)
    assert 0 <= size <= n
    combos = list(combinations(pool, size))
    p = 1.0 / len(combos) if combos else 1.0
    # Aggregate identical value-sets (pool has duplicates like the two 50s)
    counts: dict[tuple[int, ...], int] = {}
    for c in combos:
        key = tuple(sorted(c, reverse=True))
        counts[key] = counts.get(key, 0) + 1
    return [(vals, cnt * p) for vals, cnt in counts.items()]


def _round_payout_distribution(
    x_count_weights: tuple[float, ...],
    y_count_weights: tuple[float, ...],
) -> list[tuple[float, float]]:
    """Return list of (payout, probability) for ONE round's R outcome.

    Exhaustively enumerates every (count_x, count_y, x-multiset,
    y-multiset) outcome weighted by the respective probabilities.
    """
    wx_sum = sum(x_count_weights)
    wy_sum = sum(y_count_weights)
    assert wx_sum > 0 and wy_sum > 0

    outcomes: dict[float, float] = {}

    for kx, wx in enumerate(x_count_weights, start=1):  # count_x ∈ [1, 5]
        if wx <= 0:
            continue
        p_kx = wx / wx_sum
        x_combos = _tuple_prob(_X_POOL, kx)

        for ky, wy in enumerate(y_count_weights, start=0):  # count_y ∈ [0, 2]
            if wy <= 0:
                continue
            p_ky = wy / wy_sum
            y_combos = _tuple_prob(_Y_POOL, ky)

            for x_vals, px in x_combos:
                x_sum = sum(x_vals)
                for y_vals, py in y_combos:
                    y_prod = 1
                    for y in y_vals:
                        y_prod *= y
                    r = x_sum * y_prod
                    prob = p_kx * p_ky * px * py
                    outcomes[r] = outcomes.get(r, 0.0) + prob

    return sorted(outcomes.items())


def analyze_feature(spec: FeatureSpec) -> FeatureStats:
    """Compute E[R], Var[R], and related stats for the full 4-round
    accept/reroll flow under the given weight set."""
    dist = _round_payout_distribution(spec.x_count_weights, spec.y_count_weights)

    r_values = [r for r, _ in dist]
    r_probs = [p for _, p in dist]
    assert abs(sum(r_probs) - 1.0) < 1e-9, f"round dist must sum to 1; got {sum(r_probs)}"

    r_min = min(r_values)
    r_max = max(r_values)

    # One-round unconditional stats
    round_ev = sum(r * p for r, p in dist)
    round_e2 = sum((r ** 2) * p for r, p in dist)

    # One-round accept stats
    accept_prob = sum(p for r, p in dist if r >= spec.accept_threshold)
    accept_ev_numer = sum(r * p for r, p in dist if r >= spec.accept_threshold)
    reject_ev_numer = sum(r * p for r, p in dist if r < spec.accept_threshold)
    accept_ev = (accept_ev_numer / accept_prob) if accept_prob > 0 else 0.0

    # 4-round feature EV
    # Let p = accept_prob, A = E[R | R>=t], U = E[R]
    # Rounds 1-3: accept with prob p each (given not accepted earlier)
    # Round 4: forced accept, unconditional E = U
    # E[final payout] = p·A + (1-p)·p·A + (1-p)²·p·A + (1-p)³·U
    p = accept_prob
    A = accept_ev
    U = round_ev

    if spec.max_rounds < 1:
        exp_payout = 0.0
    elif spec.max_rounds == 1:
        # Single round, no rerolls: forced accept
        exp_payout = U
    else:
        reject_streak = 1.0 - p
        accept_contrib = 0.0
        for round_idx in range(1, spec.max_rounds):  # rounds 1..(max-1), reroll allowed
            accept_contrib += (reject_streak ** (round_idx - 1)) * p * A
        # Round `max_rounds`: forced accept
        accept_contrib += (reject_streak ** (spec.max_rounds - 1)) * U
        exp_payout = accept_contrib

    # Variance of final feature payout
    # Var[final] = E[final²] - (E[final])²
    # Each accepting branch contributes E[R² | accept] × branch_prob
    accept_e2_numer = sum((r ** 2) * p for r, p in dist if r >= spec.accept_threshold)
    accept_e2 = (accept_e2_numer / p) if p > 0 else 0.0
    forced_e2 = round_e2

    if spec.max_rounds < 1:
        exp_r2 = 0.0
    elif spec.max_rounds == 1:
        exp_r2 = forced_e2
    else:
        reject_streak = 1.0 - p
        e2 = 0.0
        for round_idx in range(1, spec.max_rounds):
            e2 += (reject_streak ** (round_idx - 1)) * p * accept_e2
        e2 += (reject_streak ** (spec.max_rounds - 1)) * forced_e2
        exp_r2 = e2

    variance = max(0.0, exp_r2 - exp_payout ** 2)
    std = sqrt(variance)
    cv = (std / exp_payout) if exp_payout > 0 else 0.0

    return FeatureStats(
        expected_payout=exp_payout,
        variance=variance,
        std=std,
        cv=cv,
        p_accept_round1=accept_prob,
        round_ev_unconditional=round_ev,
        round_ev_given_accept=accept_ev,
        round_p_accept=accept_prob,
        r_min=r_min,
        r_max=r_max,
    )


def describe(spec: FeatureSpec, stats: FeatureStats) -> str:
    """Pretty-print a feature stats summary for human eyeball."""
    xw = spec.x_count_weights
    yw = spec.y_count_weights
    xw_sum = sum(xw)
    yw_sum = sum(yw)
    xw_norm = [f"{w/xw_sum:.1%}" for w in xw]
    yw_norm = [f"{w/yw_sum:.1%}" for w in yw]
    lines = [
        f"Feature Play EV analysis:",
        f"  count_x weights (1,2,3,4,5):  raw={xw}  norm={xw_norm}",
        f"  count_y weights (0,1,2):      raw={yw}  norm={yw_norm}",
        f"  accept_threshold: {spec.accept_threshold}×",
        f"  max_rounds: {spec.max_rounds}",
        f"",
        f"One-round:",
        f"  E[R]:                     {stats.round_ev_unconditional:.2f}×",
        f"  P(R ≥ {spec.accept_threshold:.0f}):              {stats.round_p_accept*100:.1f}%",
        f"  E[R | R ≥ {spec.accept_threshold:.0f}]:          {stats.round_ev_given_accept:.2f}×",
        f"  R range:                  [{stats.r_min:.0f}×, {stats.r_max:.0f}×]",
        f"",
        f"Full 4-round feature play (3 reroll + 1 forced):",
        f"  E[final payout]:          {stats.expected_payout:.2f}× bet",
        f"  std[final payout]:        {stats.std:.2f}",
        f"  CV (std/EV):              {stats.cv:.2f}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    # Smoke: default weights preview
    default_spec = FeatureSpec(
        x_count_weights=(50, 30, 12, 5, 3),
        y_count_weights=(60, 30, 10),
    )
    stats = analyze_feature(default_spec)
    print(describe(default_spec, stats))
