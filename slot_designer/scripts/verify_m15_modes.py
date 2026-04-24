"""Verify M15 4-mode feature EV targets against v4 design candidates.

Runs each mode's candidate weights through analyze_feature and reports:
- Actual EV vs target (42 / 55 / 120 / 42 for modes 1 / 2 / 5 / 7)
- One-round EV, accept rate, R range, CV
- Feature RTP = trigger × EV — check against budget

Exit code:
  0 if all modes within ±10% EV target
  1 otherwise (EV drift — iterate x_value_weights)

Target source: slot_designer/weights/M15/MODE_DESIGN.md v4 (2026-04-23).

Usage:
  python -m slot_designer.scripts.verify_m15_modes
  python -m slot_designer.scripts.verify_m15_modes --verbose
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.engine.feature_m15 import FeatureSpec, analyze_feature, describe


# All modes share count_x; count_y varies per mode to let EV targets fit.
SHARED_COUNT_X = (5, 40, 40, 12, 3)


MODE_CANDIDATES = {
    1: {
        "name": "Classic standard",
        "count_y": (75, 20, 5),
        "x_value_weights": (0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684),
        "trigger": 0.01136,          # 1.136% = 1/88
        "feature_rtp_target_pp": 52.25,
        "ev_target": 46.0,
    },
    7: {
        "name": "Standard-low (slow grind, derived from mode 1)",
        "count_y": (75, 20, 5),
        "x_value_weights": (0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684),
        "trigger": 0.01136,
        "feature_rtp_target_pp": 52.25,
        "ev_target": 46.0,
    },
    2: {
        "name": "Lucky",
        "count_y": (60, 30, 10),
        "x_value_weights": (0.0009, 0.0914, 0.3687, 0.3687, 2.3289, 2.3289, 9.3906, 9.3906, 37.8657, 37.8657),
        "trigger": 0.0275,           # 2.75% = 1/36
        "feature_rtp_target_pp": 165.0,
        "ev_target": 60.0,
    },
    5: {
        "name": "Super-lucky (mode 2 + feature buff, v7 no 1000-jackpot)",
        "count_y": (40, 35, 25),
        # v7 2026-04-24: killed 1000-card weight (0.1918 → 0.0001) per user brief
        # "1000 倍以上的奖需要趋近 0"; redistributed to 100-card (1.6065 → 4.5).
        # See MODE_DESIGN.md §2 v7 table + §6 mode 5 section.
        "x_value_weights": (0.0001, 4.5, 3.5, 3.5, 7.0955, 7.0955, 13.453, 13.453, 25.5065, 25.5065),
        "trigger": 0.0276,           # 2.76% (actual from shipped mode 5 weights)
        "feature_rtp_target_pp": 367.0,
        "ev_target": 132.81,
    },
}


_X_POOL = (1000, 100, 50, 50, 20, 20, 10, 10, 5, 5)


def _pretty_value_probs(x_value_weights: tuple[float, ...]) -> str:
    """Render x value weights as per-unique-value probabilities."""
    total = sum(x_value_weights)
    by_value: dict[int, float] = {}
    for v, w in zip(_X_POOL, x_value_weights):
        by_value[v] = by_value.get(v, 0.0) + w
    return " | ".join(
        f"{v}: {100 * by_value[v] / total:.2f}%"
        for v in sorted(by_value.keys(), reverse=True)
    )


def run(verbose: bool = False) -> int:
    any_drift = False
    print(f"\n{'='*70}")
    print(f"M15 Feature Mode Verification (v4 design candidates)")
    print(f"{'='*70}")
    print(f"Shared count_x: {SHARED_COUNT_X}")

    results = []

    for mode_num, config in MODE_CANDIDATES.items():
        spec = FeatureSpec(
            x_count_weights=SHARED_COUNT_X,
            y_count_weights=config["count_y"],
            x_value_weights=config["x_value_weights"],
        )
        stats = analyze_feature(spec)

        trigger = config["trigger"]
        target_ev = config["ev_target"]
        target_rtp_pp = config["feature_rtp_target_pp"]

        actual_rtp_pp = 100.0 * trigger * stats.expected_payout
        ev_deviation_pct = 100.0 * (stats.expected_payout - target_ev) / target_ev
        rtp_deviation_pp = actual_rtp_pp - target_rtp_pp

        drift = abs(ev_deviation_pct) > 10
        if drift:
            any_drift = True

        results.append(
            dict(
                mode=mode_num,
                name=config["name"],
                target_ev=target_ev,
                actual_ev=stats.expected_payout,
                ev_deviation_pct=ev_deviation_pct,
                trigger=trigger,
                target_rtp_pp=target_rtp_pp,
                actual_rtp_pp=actual_rtp_pp,
                rtp_deviation_pp=rtp_deviation_pp,
                stats=stats,
                drift=drift,
                config=config,
            )
        )

        header = f"Mode {mode_num} - {config['name']}"
        divider = "-" * len(header)
        print(f"\n{header}")
        print(divider)
        print(f"  count_y:         {config['count_y']}")
        print(f"  x value probs:   {_pretty_value_probs(config['x_value_weights'])}")
        print(f"  One-round E[R]:  {stats.round_ev_unconditional:.2f}x")
        print(
            f"  Accept rate:     {stats.round_p_accept*100:.2f}%   "
            f"E[R|accept]={stats.round_ev_given_accept:.2f}x"
        )
        print(f"  R range:         [{stats.r_min:.0f}x, {stats.r_max:.0f}x]   CV={stats.cv:.2f}")
        print()
        marker = "!! DRIFT" if drift else "[OK]"
        print(
            f"  {marker}  EV:          target {target_ev:.2f}x   "
            f"actual {stats.expected_payout:.2f}x   ({ev_deviation_pct:+.1f}%)"
        )
        print(
            f"      Trigger:         {trigger*100:.2f}% (1/{1/trigger:.0f})"
        )
        print(
            f"      Feature RTP:     target {target_rtp_pp:.2f}pp   "
            f"actual {actual_rtp_pp:.2f}pp   ({rtp_deviation_pp:+.2f}pp)"
        )

        if verbose:
            print()
            print(describe(spec, stats))

    print(f"\n{'='*70}")
    print(f"Summary")
    print(f"{'='*70}")
    print(f"{'Mode':<6}{'Target EV':<12}{'Actual EV':<12}{'Dev %':<10}{'RTP pp':<12}{'Status':<10}")
    for r in results:
        status = "DRIFT" if r["drift"] else "OK"
        print(
            f"{r['mode']:<6}{r['target_ev']:<12.2f}{r['actual_ev']:<12.2f}"
            f"{r['ev_deviation_pct']:<+10.1f}{r['actual_rtp_pp']:<12.2f}{status:<10}"
        )

    if any_drift:
        print(
            "\n!! One or more modes drifted >10%. Iterate x_value_weights and re-run."
        )
        return 1
    else:
        print("\n[OK] All modes within +/-10% EV target.")
        return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-v", "--verbose", action="store_true", help="print full describe() output per mode")
    args = p.parse_args()
    sys.exit(run(verbose=args.verbose))


if __name__ == "__main__":
    main()
