"""Compare two weights files via analytic predictions.

Typical use during tuning:

    python -m slot_designer.core.devtools.weight_diff \
        --spec slot_designer/machines/M1/spec.json \
        --weights-a slot_designer/machines/M1/weights/mode_1/weights.json \
        --weights-b /tmp/candidate.json \
        --target slot_designer/tuner/targets/M1_mode1_classic.target.json

Reports predicted RTP + bucket distribution for each, and shape distance
to the target (if provided). No sampling — all analytic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # repo root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import (
    ALL_BUCKET_KEYS,
    analytic_profile,
    structurally_reachable_buckets,
)
from slot_designer.core.devtools.shape_distance import shape_distance
from slot_designer.core.engine.loader import load_engine


def _format_row(label: str, va, vb=None, vt=None, fmt: str = "{:>10.4f}") -> str:
    parts = [f"{label:<28}"]
    parts.append(f"A={fmt.format(va)}")
    if vb is not None:
        parts.append(f"B={fmt.format(vb)}  Δ(B-A)={fmt.format(vb - va)}")
    if vt is not None:
        parts.append(f"target={fmt.format(vt)}")
    return "  ".join(parts)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--weights-a", required=True, type=Path, dest="a")
    p.add_argument("--weights-b", type=Path, dest="b", default=None)
    p.add_argument("--target", type=Path, default=None)
    args = p.parse_args()

    engine_a, _ = load_engine(args.spec, args.a)
    prof_a = analytic_profile(engine_a)
    reachable_a = structurally_reachable_buckets(engine_a)

    prof_b = None
    if args.b is not None:
        engine_b, _ = load_engine(args.spec, args.b)
        prof_b = analytic_profile(engine_b)

    target = None
    if args.target is not None:
        target = json.loads(args.target.read_text(encoding="utf-8"))

    # RTP + hit_rate + total_prob sanity
    print(f"Spec        : {args.spec}")
    print(f"Weights A   : {args.a}")
    if args.b: print(f"Weights B   : {args.b}")
    if args.target: print(f"Target      : {args.target.name} ({target.get('label','')})")
    print()

    def rtp_target():
        return target["rtp_pct"] if target else None

    def hit_target():
        return target["hit_rate"] if target else None

    print(_format_row("RTP %",
                      prof_a["rtp_pct"],
                      prof_b["rtp_pct"] if prof_b else None,
                      rtp_target()))
    print(_format_row("hit_rate",
                      prof_a["hit_rate"],
                      prof_b["hit_rate"] if prof_b else None,
                      hit_target()))
    print(_format_row("total_prob (sanity)",
                      prof_a["total_prob"],
                      prof_b["total_prob"] if prof_b else None))

    # Bucket table
    print(f"\nbucket rate (probability per spin), high→low multiplier:")
    print(f"  {'bucket':<18} {'A':>10} {'B':>10} {'target':>10}")
    for k in ALL_BUCKET_KEYS:
        a_val = prof_a["bucket_rate"].get(k, 0)
        b_val = prof_b["bucket_rate"].get(k, 0) if prof_b else None
        t_val = target["bucket_rate"].get(k, 0) if target else None
        star = " *" if k not in reachable_a else "  "
        line = f"  {k:<18} {a_val*100:>9.4f}%"
        line += f" {b_val*100:>9.4f}%" if b_val is not None else " " * 11
        line += f" {t_val*100:>9.4f}%" if t_val is not None else ""
        print(line + star)
    print("  * = bucket structurally unreachable in A's paytable (excluded from shape comparison)")

    # Shape distance to target
    if target is not None:
        sd_a = shape_distance(
            prof_a["bucket_rate"],
            target["bucket_rate"],
            reachable_buckets=reachable_a,
        )
        print(f"\nShape distance A → target:")
        for k, v in sd_a.items():
            print(f"  {k:<24} {v:>10.5f}")
        if prof_b is not None:
            sd_b = shape_distance(
                prof_b["bucket_rate"],
                target["bucket_rate"],
                reachable_buckets=reachable_a,
            )
            print(f"\nShape distance B → target:")
            for k, v in sd_b.items():
                print(f"  {k:<24} {v:>10.5f}")
            improved_js = sd_a["js_divergence"] - sd_b["js_divergence"]
            print(f"\nJS improvement B vs A: {improved_js:+.5f} "
                  f"({'better' if improved_js > 0 else 'worse'})")

    # Per-pay_id hit rate
    print(f"\nper-pay_id hit rate (probability per spin):")
    all_pids = sorted(set(prof_a["pay_hits"]) | (set(prof_b["pay_hits"]) if prof_b else set()),
                      key=lambda x: int(x) if x.isdigit() else -1)
    for pid in all_pids:
        a_val = prof_a["pay_hits"].get(pid, 0)
        b_val = prof_b["pay_hits"].get(pid, 0) if prof_b else None
        line = f"  pay_id {pid:>3}: A={a_val*100:>8.4f}%"
        if b_val is not None:
            line += f"  B={b_val*100:>8.4f}%  Δ={((b_val-a_val)*100):+7.4f}pp"
        print(line)


if __name__ == "__main__":
    main()
