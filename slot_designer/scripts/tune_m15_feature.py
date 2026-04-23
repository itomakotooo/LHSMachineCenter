"""Binary-search x_value_weights to hit target EV per M15 mode.

Parameterization: weight on each card = base_value ^ alpha
  alpha < 0: biases low values (P(5) up, P(1000) down)
  alpha = 0: uniform
  alpha > 0: biases high values

Finds alpha for each target EV; reports the resulting per-card weights
and P(value) distribution for pasting into MODE_DESIGN.md.

Usage:
  python -m slot_designer.scripts.tune_m15_feature
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.engine.feature_m15 import FeatureSpec, analyze_feature


_X_POOL = (1000, 100, 50, 50, 20, 20, 10, 10, 5, 5)
SHARED_COUNT_X = (5, 40, 40, 12, 3)

# Per-mode count_y: mode 1/7 narrower (less y-amp → lower EV floor, lets
# alpha stay moderate so P(1000) stays non-zero for "dream moment" UX).
# mode 5 broader (more y multipliers — "feature buff" via multiplier layer too).
COUNT_Y_BY_MODE = {
    1: (75, 20, 5),
    7: (75, 20, 5),
    2: (60, 30, 10),
    5: (40, 35, 25),
}


TARGETS = {
    # Mode 1 EV around 46 (floor with chosen count_y is ~38-40, so alpha stays moderate).
    # Mode 2: ≤1.5× m1 = 69.
    # Mode 5: 2.2× m2 = 132.
    1: 46.0,
    7: 46.0,
    2: 60.0,
    5: 132.0,
}


# Feature RTP target in pp
FEATURE_RTP_TARGETS_PP = {
    1: 52.25,
    7: 52.25,
    2: 165.0,
    5: 365.0,
}


def weights_from_alpha(alpha: float) -> tuple[float, ...]:
    """Build per-card weights from power-law alpha."""
    return tuple(v ** alpha for v in _X_POOL)


def ev_at_alpha(alpha: float, count_y: tuple[float, ...]) -> float:
    ws = weights_from_alpha(alpha)
    spec = FeatureSpec(
        x_count_weights=SHARED_COUNT_X,
        y_count_weights=count_y,
        x_value_weights=ws,
    )
    return analyze_feature(spec).expected_payout


def solve_alpha(
    target_ev: float,
    count_y: tuple[float, ...],
    lo: float = -20.0,
    hi: float = 3.0,
    tol: float = 0.01,
) -> float:
    """Binary search alpha for given target EV and count_y."""
    ev_lo = ev_at_alpha(lo, count_y)
    ev_hi = ev_at_alpha(hi, count_y)
    if target_ev < ev_lo or target_ev > ev_hi:
        raise ValueError(
            f"target {target_ev} outside reachable range [{ev_lo:.2f}, {ev_hi:.2f}] for count_y={count_y}"
        )

    for _ in range(60):
        mid = 0.5 * (lo + hi)
        ev = ev_at_alpha(mid, count_y)
        if abs(ev - target_ev) < tol:
            return mid
        if ev < target_ev:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def pretty_weights_and_probs(ws: tuple[float, ...]) -> tuple[str, str]:
    """Format weights normalized to sum 100 and their per-value probs."""
    W = sum(ws)
    norm_100 = [100 * w / W for w in ws]
    by_value: dict[int, float] = {}
    for v, w in zip(_X_POOL, ws):
        by_value[v] = by_value.get(v, 0.0) + w
    probs = {v: 100 * w / W for v, w in by_value.items()}
    weights_str = "[" + ", ".join(f"{w:.3g}" for w in norm_100) + "]"
    probs_str = " | ".join(
        f"{v}: {probs[v]:.2f}%"
        for v in sorted(probs.keys(), reverse=True)
    )
    return weights_str, probs_str


def main():
    print(f"\n{'='*70}")
    print(f"M15 Feature Mode — solve x_value_weights for target EV")
    print(f"{'='*70}")
    print(f"Shared count_x: {SHARED_COUNT_X}")
    print(f"Per-mode count_y: {COUNT_Y_BY_MODE}")
    print(f"Parameterization: weight_i = value_i ^ alpha")
    print()

    results = []
    for mode_num, target in TARGETS.items():
        count_y = COUNT_Y_BY_MODE[mode_num]
        alpha = solve_alpha(target, count_y)
        ws = weights_from_alpha(alpha)
        actual_ev = ev_at_alpha(alpha, count_y)
        weights_str, probs_str = pretty_weights_and_probs(ws)

        spec = FeatureSpec(
            x_count_weights=SHARED_COUNT_X,
            y_count_weights=count_y,
            x_value_weights=ws,
        )
        stats = analyze_feature(spec)

        results.append((mode_num, target, actual_ev, alpha, ws, stats))

        feature_rtp_target_pp = FEATURE_RTP_TARGETS_PP[mode_num]
        required_trigger = feature_rtp_target_pp / actual_ev  # percent

        print(f"Mode {mode_num}: target EV = {target:.2f}x (count_y = {count_y})")
        print(f"  alpha = {alpha:.4f}")
        print(f"  actual EV = {actual_ev:.3f}x   (deviation {100*(actual_ev-target)/target:+.2f}%)")
        print(f"  weights (normalized to sum 100):")
        print(f"    {weights_str}")
        print(f"  P per value:")
        print(f"    {probs_str}")
        print(f"  One-round E[R] = {stats.round_ev_unconditional:.2f}x")
        print(f"  Accept rate = {stats.round_p_accept*100:.2f}%")
        print(f"  R range = [{stats.r_min:.0f}x, {stats.r_max:.0f}x]")
        print(f"  CV = {stats.cv:.2f}")
        print(f"  Feature RTP target: {feature_rtp_target_pp:.2f}pp")
        print(f"  Required trigger:   {required_trigger:.3f}% (= 1/{100/required_trigger:.0f})")
        print()

    print(f"{'='*70}")
    print(f"Paste-ready MODE_CANDIDATES (for verify_m15_modes.py):")
    print(f"{'='*70}")
    for mode_num, target, actual, alpha, ws, _stats in results:
        W = sum(ws)
        norm_100 = tuple(round(100 * w / W, 4) for w in ws)
        print(f"  mode {mode_num}: {norm_100}   # alpha={alpha:.4f}, EV={actual:.2f}x")


if __name__ == "__main__":
    main()
