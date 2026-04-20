"""CLI: tune reel weights to match a target profile.

Pipeline:
  1. Load spec + base weights + target profile.
  2. Extract per-(symbol, reel) counts from base weights as starting point.
  3. Set up analytic cost function (RTP + shape + CV, all from marginals).
  4. Run (1+1)-ES with restarts.
  5. Generate tuned weights by rescaling base stops to best counts.
  6. Write tuned weights + summary report.

Usage:

    python -m slot_designer.scripts.tune \
        --spec slot_designer/specs/M1.spec.json \
        --base-weights slot_designer/weights/M1_mode1.current.json \
        --target slot_designer/tuner/targets/M14_mode1.target.json \
        --out-weights slot_designer/weights/M1_mode1.tuned.json \
        --out-report slot_designer/out/M1_tune_report.md \
        --evaluations 2000 --restarts 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import (
    ALL_BUCKET_KEYS,
    analytic_profile,
    analytic_profile_from_marginals,
    structurally_reachable_buckets,
)
from slot_designer.engine.evaluator import PaytableEvaluator
from slot_designer.engine.loader import load_engine
from slot_designer.engine.rules import RuleSet
from slot_designer.engine.symbol import SymbolRegistry
from slot_designer.tuner.cost import CostWeights, evaluate_cost
from slot_designer.tuner.layout import apply_counts, base_counts, marginals_from_counts
from slot_designer.tuner.loop import ESConfig, run_with_restarts


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--base-weights", required=True, type=Path)
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--out-weights", required=True, type=Path)
    p.add_argument("--out-report", type=Path, default=None)
    p.add_argument("--evaluations", type=int, default=800)
    p.add_argument("--restarts", type=int, default=3)
    p.add_argument("--sigma", type=float, default=8.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--rtp-weight", type=float, default=1.0)
    p.add_argument("--shape-weight", type=float, default=1.0)
    p.add_argument("--cv-weight", type=float, default=0.3)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    base_weights = json.loads(args.base_weights.read_text(encoding="utf-8"))
    target = json.loads(args.target.read_text(encoding="utf-8"))

    # Build evaluator once (paytable is fixed during tuning)
    symbols = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"])
    evaluator = PaytableEvaluator(symbols, rules, spec["evaluation_order"])

    # Reachable buckets depend on paytable only — compute once using the
    # baseline engine so shape_distance knows which target buckets to
    # exclude from comparison.
    base_engine, _ = load_engine(args.spec, args.base_weights)
    reachable = structurally_reachable_buckets(base_engine)
    base_profile = analytic_profile(base_engine)

    weights_cfg = CostWeights(
        rtp_weight=args.rtp_weight,
        shape_weight=args.shape_weight,
        cv_weight=args.cv_weight,
    )

    # Build target with derived cv if missing
    if "cv" not in target:
        tgt_std = target.get("std_return_x", 0.0)
        tgt_rtp_frac = target.get("rtp_pct", 100.0) / 100.0
        target["cv"] = tgt_std / tgt_rtp_frac if tgt_rtp_frac > 0 else 0.0

    def cost_fn(counts_list):
        marginals = marginals_from_counts(counts_list)
        pred = analytic_profile_from_marginals(evaluator, marginals)
        breakdown = evaluate_cost(pred, target, reachable_buckets=reachable, weights=weights_cfg)
        return breakdown.total, breakdown

    x0 = base_counts(base_weights)
    base_cost, base_breakdown = cost_fn(x0)

    print(f"=== baseline (user-provided weights) ===")
    print(f"  RTP              : {base_profile['rtp_pct']:.3f}%  (target {target['rtp_pct']:.3f}%)")
    print(f"  hit_rate         : {base_profile['hit_rate']*100:.3f}%  (target {target['hit_rate']*100:.3f}%)")
    print(f"  CV               : {base_profile['cv']:.3f}  (target {target['cv']:.3f})")
    print(f"  ΔRTP             : {base_breakdown.rtp_gap_pp:.3f}pp")
    print(f"  shape JS         : {base_breakdown.shape_js:.5f}")
    print(f"  cost (total)     : {base_cost:.4f}")
    print(f"  → components: rtp={base_breakdown.rtp_cost:.2f} shape={base_breakdown.shape_cost:.2f} cv={base_breakdown.cv_cost:.2f}")

    cfg = ESConfig(sigma_init=args.sigma)
    print(f"\n=== running (1+1)-ES: {args.restarts} restarts × {args.evaluations} evals ===")
    result = run_with_restarts(
        x0, cost_fn,
        restarts=args.restarts,
        evaluations_per_restart=args.evaluations,
        config=cfg,
        master_seed=args.seed,
        verbose=args.verbose,
    )

    best_marginals = marginals_from_counts(result.best_counts)
    best_profile = analytic_profile_from_marginals(evaluator, best_marginals)

    print(f"\n=== tuned result ===")
    print(f"  RTP              : {best_profile['rtp_pct']:.3f}%  (target {target['rtp_pct']:.3f}%)")
    print(f"  hit_rate         : {best_profile['hit_rate']*100:.3f}%  (target {target['hit_rate']*100:.3f}%)")
    print(f"  CV               : {best_profile['cv']:.3f}  (target {target['cv']:.3f})")
    print(f"  ΔRTP             : {result.best_breakdown.rtp_gap_pp:.3f}pp")
    print(f"  shape JS         : {result.best_breakdown.shape_js:.5f}")
    print(f"  cost (total)     : {result.best_cost:.4f}  (was {base_cost:.4f}; Δ={base_cost-result.best_cost:+.4f})")

    # Materialize tuned weights into a valid JSON file
    tuned_weights = apply_counts(base_weights, result.best_counts)
    tuned_weights["_tuned_from"] = str(args.base_weights)
    tuned_weights["_tuned_target"] = target.get("label", str(args.target))
    tuned_weights["_tuned_summary"] = {
        "rtp_pct": best_profile["rtp_pct"],
        "hit_rate": best_profile["hit_rate"],
        "cv": best_profile["cv"],
        "shape_js_to_target": result.best_breakdown.shape_js,
        "rtp_gap_pp": result.best_breakdown.rtp_gap_pp,
        "evaluations": result.evaluations * args.restarts,
    }
    args.out_weights.parent.mkdir(parents=True, exist_ok=True)
    args.out_weights.write_text(json.dumps(tuned_weights, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote tuned weights → {args.out_weights}")

    if args.out_report:
        _write_report(
            args.out_report, base_profile, best_profile, target,
            base_breakdown, result.best_breakdown, reachable,
            result.best_counts, x0,
        )
        print(f"wrote tune report   → {args.out_report}")


def _write_report(
    path, base_profile, best_profile, target,
    base_breakdown, best_breakdown, reachable,
    best_counts, base_counts_list,
) -> None:
    lines = []
    lines.append(f"# Tune report\n")
    lines.append(f"target: **{target.get('label','?')}** — RTP {target['rtp_pct']:.2f}%, CV {target['cv']:.3f}\n")
    lines.append(f"\n## Baseline → Tuned\n")
    lines.append(f"| metric | baseline | tuned | target | Δ to target |")
    lines.append(f"|---|---|---|---|---|")
    def row(label, b, t, tg, fmt="{:.3f}"):
        lines.append(f"| {label} | {fmt.format(b)} | {fmt.format(t)} | {fmt.format(tg)} | {fmt.format(t - tg)} |")
    row("RTP %", base_profile["rtp_pct"], best_profile["rtp_pct"], target["rtp_pct"])
    row("hit_rate", base_profile["hit_rate"], best_profile["hit_rate"], target["hit_rate"])
    row("CV", base_profile["cv"], best_profile["cv"], target["cv"])
    row("std_return_x", base_profile["std_return_x"], best_profile["std_return_x"],
        target.get("std_return_x", 0))

    lines.append(f"\n## Cost breakdown\n")
    lines.append(f"| cost | baseline | tuned |")
    lines.append(f"|---|---|---|")
    lines.append(f"| total | {base_breakdown.total:.4f} | {best_breakdown.total:.4f} |")
    lines.append(f"| rtp   | {base_breakdown.rtp_cost:.4f} | {best_breakdown.rtp_cost:.4f} |")
    lines.append(f"| shape | {base_breakdown.shape_cost:.4f} | {best_breakdown.shape_cost:.4f} |")
    lines.append(f"| cv    | {base_breakdown.cv_cost:.4f} | {best_breakdown.cv_cost:.4f} |")

    lines.append(f"\n## Bucket distribution (%)\n")
    lines.append(f"| bucket | baseline | tuned | target | reachable |")
    lines.append(f"|---|---|---|---|---|")
    for k in ALL_BUCKET_KEYS:
        b = base_profile["bucket_rate"].get(k, 0) * 100
        t = best_profile["bucket_rate"].get(k, 0) * 100
        tg = target["bucket_rate"].get(k, 0) * 100
        r = "✓" if k in reachable else "—"
        lines.append(f"| {k} | {b:.4f} | {t:.4f} | {tg:.4f} | {r} |")

    lines.append(f"\n## Count changes (per symbol × reel)\n")
    lines.append(f"| symbol | reel 1 | reel 2 | reel 3 |")
    lines.append(f"|---|---|---|---|")
    all_syms = sorted({s for reel in best_counts for s in reel.keys()})
    for sym in all_syms:
        cells = []
        for reel_idx in range(len(best_counts)):
            b = base_counts_list[reel_idx].get(sym, 0)
            t = best_counts[reel_idx].get(sym, 0)
            delta = t - b
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
            cells.append(f"{b}→{t} {arrow}{abs(delta)}")
        lines.append(f"| {sym} | {cells[0]} | {cells[1]} | {cells[2]} |")

    lines.append(f"\n## Pay_id hit rates (analytic)\n")
    lines.append(f"| pay_id | baseline % | tuned % |")
    lines.append(f"|---|---|---|")
    all_pids = sorted(
        set(base_profile.get("pay_hits", {}).keys()) | set(best_profile.get("pay_hits", {}).keys()),
        key=lambda x: int(x) if x.isdigit() else -1,
    )
    for pid in all_pids:
        b = base_profile.get("pay_hits", {}).get(pid, 0) * 100
        t = best_profile.get("pay_hits", {}).get(pid, 0) * 100
        lines.append(f"| {pid} | {b:.4f} | {t:.4f} |")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
