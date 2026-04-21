"""Extract a tuning target profile from a reference machine's summary.

The target profile captures only the fields tuning cares about, so
downstream cost functions read from a compact stable schema instead of
the full analyzer summary.

Hard-constraint fields: rtp, bucket_rate
Soft-constraint fields: hit_rate, zero_rate, std_return_x
Shape-check fields:     tail_dep_ge{10,20,50,100}x, max_return_x,
                        loss_streak_p95, big_win_x10_rate

Use via CLI:

    python -m slot_designer.tuner.target_profile \
        --summary <path/to/player_impact_summary.json> \
        --out slot_designer/tuner/targets/<label>.target.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def extract_target(summary: dict[str, Any], label: str) -> dict[str, Any]:
    pi = summary["player_impact"]
    vol = pi["volatility"]
    hit = pi["hit_and_payout"]
    streaks = pi.get("streaks", {})
    derived = summary.get("guideline_assessment", {}).get("derived_metrics", {})
    sampling = summary.get("sampling", {})

    return {
        "label": label,
        "source_machine": summary.get("machine"),
        "source_mode": summary.get("mode"),
        "source_spins": sampling.get("total_spins"),
        "source_rtp_ci_pp": sampling.get("session_level_halfwidth_pp"),

        # Hard constraint — must match tightly
        "rtp_pct": vol["avg_return_x"] * 100,
        "bucket_rate": dict(vol["return_bucket_rate"]),

        # Soft — allowed to deviate per machine-specific structure
        "hit_rate": hit["win_hit_rate"],
        "zero_win_rate": hit["zero_win_rate"],
        "std_return_x": vol["std_return_x"],

        # Shape-check — sanity only, not optimized against directly
        "max_return_x": vol["max_observed_return_x"],
        "big_win_x10_rate": hit.get("big_win_x10_rate", 0),
        "tail_dep_ge10x": derived.get("tail_dependency_ge10x", 0),
        "tail_dep_ge20x": derived.get("tail_dependency_ge20x", 0),
        "tail_dep_ge50x": derived.get("tail_dependency_ge50x", 0),
        "tail_dep_ge100x": derived.get("tail_dependency_ge100x", 0),
        "loss_streak_p95": streaks.get("loss_streak_p95", 0),
        "loss_streak_max": streaks.get("loss_streak_max", 0),
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Extract tuning target profile from analyzer summary."
    )
    p.add_argument("--summary", required=True, type=Path,
                   help="path to player_impact_summary.json")
    p.add_argument("--out", required=True, type=Path,
                   help="path to write target JSON")
    p.add_argument("--label", default="",
                   help="human-readable label (defaults to auto-generated from summary)")
    args = p.parse_args()

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    label = args.label or f"{summary.get('machine')}_mode{summary.get('mode')}_{summary.get('sampling',{}).get('total_spins')}spins"

    target = extract_target(summary, label)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(target, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote target → {args.out}")
    print(f"  RTP {target['rtp_pct']:.2f}%  hit {target['hit_rate']*100:.2f}%  "
          f"std {target['std_return_x']:.2f}  tail_ge10x {target['tail_dep_ge10x']:.3f}")


if __name__ == "__main__":
    main()
