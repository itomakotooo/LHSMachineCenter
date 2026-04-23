"""M15 Feature Play simulator + analytic EV.

Paytable §5 semantics (2026-04-23):
  - 10 x-cards with values (1000, 100, 50, 50, 20, 20, 10, 10, 5, 5)
  - 2 y-cards, both value ×2
  - Per round:
      1. Pick count_x ∈ [1, 5] by weight w_count_x
      2. Pick count_y ∈ [0, 2] by weight w_count_y
      3. Draw count_x cards WITHOUT REPLACEMENT from 10 x-cards,
         weighted by x_value_weights (v4: designer dial)
      4. Draw count_y cards WITHOUT REPLACEMENT from 2 y-cards,
         weighted by y_value_weights (default uniform; both y=×2 so
         weight only matters for variance, not EV)
      5. Compute R = sum(x_drawn) × product(y_drawn)
  - Player decision: if R >= accept_threshold → accept, else reroll
    (up to 3 rerolls = 4 rounds total; round 4 is forced accept)

v4 (2026-04-23): `x_value_weights` is now a designer dial. Previously
value sampling was implicit-uniform over 10 cards (with duplicated
values providing implicit value weighting). Now the designer can
independently tune per-card weights to shift the payout distribution
from near-5× average (all low) to near-4880× (all high), decoupling
the conditional EV from the (fixed) x_pool structure.

Backward compat: omitting `x_value_weights` / `y_value_weights` yields
the pre-v4 uniform behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations, permutations
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
    # v4: per-card weights for x-card draw. 10-tuple aligned with _X_POOL.
    # Default = uniform (equivalent to pre-v4 behavior).
    x_value_weights: tuple[float, ...] = field(
        default_factory=lambda: (1.0,) * len(_X_POOL)
    )
    # v4: per-card weights for y-card draw. 2-tuple aligned with _Y_POOL.
    # Both y cards = ×2 so EV is weight-invariant; default uniform.
    y_value_weights: tuple[float, ...] = field(
        default_factory=lambda: (1.0,) * len(_Y_POOL)
    )
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


def _weighted_draw_dist(
    pool: tuple[int, ...],
    value_weights: tuple[float, ...],
    size: int,
) -> list[tuple[tuple[int, ...], float]]:
    """Enumerate all unordered combinations of `size` cards drawn WITHOUT
    replacement from `pool`, where card i has weight `value_weights[i]`.

    Returns list of (sorted-desc values tuple, probability) pairs.
    Sampling is weighted: P(card i drawn first) = w_i / sum(w);
    subsequent draws re-normalize over remaining cards' weights.

    When value_weights are all equal, this reduces to uniform sampling
    without replacement (= the pre-v4 `_tuple_prob` behavior).
    """
    n = len(pool)
    assert n == len(value_weights), "pool/value_weights length mismatch"
    assert 0 <= size <= n, f"invalid size {size} for pool of {n}"

    if size == 0:
        return [((), 1.0)]

    W = sum(value_weights)
    if W <= 0:
        return []

    outcomes: dict[tuple[int, ...], float] = {}

    # Iterate every k-subset of card indices; sum probability over k!
    # orderings. The probability of an ordered sequence (i_1, ..., i_k)
    # is prod_{t} w[i_t] / (W - sum_{s<t} w[i_s]).
    for combo_idx in combinations(range(n), size):
        subset_prob = 0.0
        for perm in permutations(combo_idx):
            remaining = W
            p = 1.0
            for idx in perm:
                p *= value_weights[idx] / remaining
                remaining -= value_weights[idx]
            subset_prob += p

        values = tuple(sorted((pool[i] for i in combo_idx), reverse=True))
        outcomes[values] = outcomes.get(values, 0.0) + subset_prob

    return list(outcomes.items())


def _round_payout_distribution(
    x_count_weights: tuple[float, ...],
    y_count_weights: tuple[float, ...],
    x_value_weights: tuple[float, ...] | None = None,
    y_value_weights: tuple[float, ...] | None = None,
) -> list[tuple[float, float]]:
    """Return list of (payout, probability) for ONE round's R outcome.

    Exhaustively enumerates every (count_x, count_y, x-multiset,
    y-multiset) outcome weighted by the respective probabilities.
    """
    if x_value_weights is None:
        x_value_weights = (1.0,) * len(_X_POOL)
    if y_value_weights is None:
        y_value_weights = (1.0,) * len(_Y_POOL)

    wx_sum = sum(x_count_weights)
    wy_sum = sum(y_count_weights)
    assert wx_sum > 0 and wy_sum > 0

    outcomes: dict[float, float] = {}

    for kx, wx in enumerate(x_count_weights, start=1):  # count_x ∈ [1, 5]
        if wx <= 0:
            continue
        p_kx = wx / wx_sum
        x_combos = _weighted_draw_dist(_X_POOL, x_value_weights, kx)

        for ky, wy in enumerate(y_count_weights, start=0):  # count_y ∈ [0, 2]
            if wy <= 0:
                continue
            p_ky = wy / wy_sum
            y_combos = _weighted_draw_dist(_Y_POOL, y_value_weights, ky)

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
    dist = _round_payout_distribution(
        spec.x_count_weights,
        spec.y_count_weights,
        spec.x_value_weights,
        spec.y_value_weights,
    )

    r_values = [r for r, _ in dist]
    r_probs = [p for _, p in dist]
    assert abs(sum(r_probs) - 1.0) < 1e-4, f"round dist must sum to 1; got {sum(r_probs)}"

    r_min = min(r_values)
    r_max = max(r_values)

    # One-round unconditional stats
    round_ev = sum(r * p for r, p in dist)
    round_e2 = sum((r ** 2) * p for r, p in dist)

    # One-round accept stats
    accept_prob = sum(p for r, p in dist if r >= spec.accept_threshold)
    accept_ev_numer = sum(r * p for r, p in dist if r >= spec.accept_threshold)
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
    xvw = spec.x_value_weights
    xw_sum = sum(xw)
    yw_sum = sum(yw)
    xvw_sum = sum(xvw)
    xw_norm = [f"{w/xw_sum:.1%}" for w in xw]
    yw_norm = [f"{w/yw_sum:.1%}" for w in yw]
    # Group x value weights by unique value for display
    xvw_by_value: dict[int, float] = {}
    for v, w in zip(_X_POOL, xvw):
        xvw_by_value[v] = xvw_by_value.get(v, 0.0) + w
    xvw_by_value_norm = {v: w / xvw_sum for v, w in xvw_by_value.items()}
    xvw_summary = ", ".join(
        f"{v}={p:.2%}" for v, p in sorted(xvw_by_value_norm.items(), reverse=True)
    )
    lines = [
        f"Feature Play EV analysis:",
        f"  count_x weights (1,2,3,4,5):  raw={xw}  norm={xw_norm}",
        f"  count_y weights (0,1,2):      raw={yw}  norm={yw_norm}",
        f"  x value weights (per card):   raw={xvw}",
        f"  x value probs (per value):    {xvw_summary}",
        f"  accept_threshold: {spec.accept_threshold}×",
        f"  max_rounds: {spec.max_rounds}",
        f"",
        f"One-round:",
        f"  E[R]:                     {stats.round_ev_unconditional:.2f}×",
        f"  P(R ≥ {spec.accept_threshold:.0f}):              {stats.round_p_accept*100:.2f}%",
        f"  E[R | R ≥ {spec.accept_threshold:.0f}]:          {stats.round_ev_given_accept:.2f}×",
        f"  R range:                  [{stats.r_min:.0f}×, {stats.r_max:.0f}×]",
        f"",
        f"Full {spec.max_rounds}-round feature play ({spec.max_rounds - 1} reroll + 1 forced):",
        f"  E[final payout]:          {stats.expected_payout:.2f}× bet",
        f"  std[final payout]:        {stats.std:.2f}",
        f"  CV (std/EV):              {stats.cv:.2f}",
    ]
    return "\n".join(lines)


def _weighted_choice_index(weights: tuple[float, ...], rng) -> int:
    """Return index drawn from `weights` with probability proportional to weight."""
    total = sum(weights)
    pick = rng.random() * total
    cum = 0.0
    for i, w in enumerate(weights):
        cum += w
        if pick < cum:
            return i
    return len(weights) - 1


def _weighted_sample_without_replacement(
    values: tuple[int, ...],
    weights: tuple[float, ...],
    k: int,
    rng,
) -> tuple[int, ...]:
    """Draw k cards without replacement, weighted by weights.
    Returns the drawn VALUES (with duplicates possible since pool has duplicates)."""
    n = len(values)
    assert k <= n
    remaining = list(range(n))
    remaining_weights = list(weights)
    drawn: list[int] = []
    for _ in range(k):
        total = sum(remaining_weights)
        if total <= 0:
            break
        pick = rng.random() * total
        cum = 0.0
        chosen = -1
        for j, w in enumerate(remaining_weights):
            cum += w
            if pick < cum:
                chosen = j
                break
        if chosen < 0:
            chosen = len(remaining_weights) - 1
        idx = remaining[chosen]
        drawn.append(values[idx])
        del remaining[chosen]
        del remaining_weights[chosen]
    return tuple(drawn)


@dataclass
class FeatureRound:
    """One round of the feature session (one ST=14 sub-spin in rawdata)."""
    round_index: int          # 1..max_rounds
    count_x: int              # how many x's drawn this round
    count_y: int              # how many y's drawn this round
    x_values: tuple[int, ...]  # the x values drawn
    y_values: tuple[int, ...]  # the y values drawn
    r_value: float            # sum(x) × product(y)
    accepted: bool            # was this round accepted (final round)?


def simulate_feature_session(spec: FeatureSpec, rng) -> list[FeatureRound]:
    """Run one Feature Play session per paytable §5:
      1. Roll count_x, count_y by weights
      2. Draw count_x x's, count_y y's (weighted, without replacement)
      3. Compute R = sum(x) × product(y); if 0 y, multiplier = 1
      4. Accept if R >= threshold (or round == max_rounds forced)
      5. Reject: reroll. Up to max_rounds total.

    Returns a list of FeatureRound, one per round played. The last round
    has accepted=True. Other rounds have accepted=False (rejected and
    rerolled). Length = 1..max_rounds.

    Rawdata mapping: each FeatureRound becomes one ST=14 spin with
    WinCredits = r_value × bet_amount. An ST=15 end marker follows.
    """
    rounds: list[FeatureRound] = []
    for round_idx in range(1, spec.max_rounds + 1):
        # Roll counts
        count_x = _weighted_choice_index(spec.x_count_weights, rng) + 1  # index 0 → count 1
        count_y = _weighted_choice_index(spec.y_count_weights, rng)      # index 0 → count 0
        # Draw x cards weighted w/o replacement
        x_drawn = _weighted_sample_without_replacement(
            _X_POOL, spec.x_value_weights, count_x, rng
        )
        # Draw y cards
        y_drawn = _weighted_sample_without_replacement(
            _Y_POOL, spec.y_value_weights, count_y, rng
        )
        # Compute R
        x_sum = sum(x_drawn)
        y_prod = 1
        for y in y_drawn:
            y_prod *= y
        r = x_sum * y_prod
        # Accept/reject
        is_last = (round_idx == spec.max_rounds)
        accepted = (r >= spec.accept_threshold) or is_last
        rounds.append(FeatureRound(
            round_index=round_idx,
            count_x=count_x,
            count_y=count_y,
            x_values=x_drawn,
            y_values=y_drawn,
            r_value=r,
            accepted=accepted,
        ))
        if accepted:
            break
    return rounds


if __name__ == "__main__":
    # Smoke: default uniform weights preview (backward compat path)
    default_spec = FeatureSpec(
        x_count_weights=(50, 30, 12, 5, 3),
        y_count_weights=(60, 30, 10),
    )
    stats = analyze_feature(default_spec)
    print("=== Default (uniform value weights — pre-v4 behavior) ===")
    print(describe(default_spec, stats))
