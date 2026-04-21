"""CLI: tune reel weights (Phase 4) + order (Phase 5), emit rawdata.

Two-stage pipeline:

  Phase 4 — count tuning (hard constraints):
    base weights → ES on per-(symbol, reel) counts → marginals match
    target RTP + bucket shape + CV

  Phase 5 — order tuning (experience):
    Phase 4 counts fixed; simulated annealing on stop ORDER within
    each reel. Preserves marginals (= hard constraints) by construction.
    Optimizes 2-of-3 near-miss rate, PWDF, blank clustering (Harrigan
    2009).

Final deliverable is rawdata chunks — existing analyzer reads them and
produces a standard report for side-by-side comparison with the real
machine.

Usage:

    python -m slot_designer.scripts.tune \\
        --spec slot_designer/specs/M1.spec.json \\
        --base-weights slot_designer/weights/M1_mode1.current.json \\
        --target slot_designer/tuner/targets/M14_mode1.target.json \\
        --out-weights slot_designer/weights/M1_mode1.tuned.json \\
        --out-report slot_designer/out/M1_tune_report.md \\
        --evaluations 1500 --restarts 3 --sa-steps 5000
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
from slot_designer.devtools.player_experience import experience_metrics
from slot_designer.emitter.driver import emit_simulation_to_dir
from slot_designer.engine.evaluator import PaytableEvaluator
from slot_designer.engine.loader import load_engine
from slot_designer.engine.rules import RuleSet
from slot_designer.engine.symbol import SymbolRegistry
from slot_designer.tuner.cost import CostWeights, evaluate_cost
from slot_designer.tuner.layout import apply_counts, base_counts, marginals_from_counts
from slot_designer.tuner.loop import ESConfig, run_with_restarts
from slot_designer.tuner.ordering import (
    ExperienceCostWeights,
    SAConfig,
    evaluate_experience_cost,
    run_simulated_annealing,
)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Tune reel weights and emit rawdata chunks as the deliverable."
    )
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--base-weights", required=True, type=Path)
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--out-weights", required=True, type=Path,
                   help="(intermediate) tuned weights JSON — for reproducibility / inspection")
    p.add_argument("--out-rawdata-dir", type=Path, default=None,
                   help="(primary deliverable) directory to emit rawdata chunks into; "
                        "defaults to slot_designer/rawdata/<machine>sim/mode_<N>/ "
                        "— which the virtual console reads natively")
    p.add_argument("--virtual-machine", default=None,
                   help="virtual machine name (defaults to <source_machine>sim). "
                        "Should be registered in configs/machines_virtual.json")
    p.add_argument("--out-report", type=Path, default=None)
    p.add_argument("--evaluations", type=int, default=800)
    p.add_argument("--restarts", type=int, default=3)
    p.add_argument("--sigma", type=float, default=8.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--rtp-weight", type=float, default=1.0)
    p.add_argument("--shape-weight", type=float, default=1.0)
    p.add_argument("--cv-weight", type=float, default=0.3)
    p.add_argument("--hit-target", type=float, default=None,
                   help="optional hit_rate soft target (fraction 0-1). "
                        "when set, tuner adds quadratic penalty on "
                        "(pred_hit - target). use for classic single-line "
                        "machines where industry typical is 0.09-0.13 "
                        "(pass e.g. 0.15). off by default.")
    p.add_argument("--hit-weight", type=float, default=0.5,
                   help="weight on the hit_target penalty (default 0.5). "
                        "Higher values make the tuner more aggressive about "
                        "hitting the exact hit_target at the cost of RTP / "
                        "bucket shape / CV. Only active with --hit-target.")
    p.add_argument("--verbose", action="store_true")

    # Phase 5 (order optimization) parameters
    p.add_argument("--sa-steps", type=int, default=5000,
                   help="simulated annealing steps for order optimization (default 5000). "
                        "Set 0 to skip Phase 5 (only count tuning).")
    p.add_argument("--nm-min", type=float, default=0.01,
                   help="Phase 5 lower band for 2-of-3 near-miss rate (default 0.01)")
    p.add_argument("--nm-max", type=float, default=0.10,
                   help="Phase 5 upper band for 2-of-3 near-miss rate (default 0.10)")
    p.add_argument("--high-value", nargs="+",
                   default=["Seven1", "Seven2", "Diamond1", "Diamond2"],
                   help="symbols considered 'high-value' for experience metrics")

    # Rawdata emission parameters
    p.add_argument("--emit-chunks", type=int, default=110,
                   help="number of chunks to emit (default 110 → ~1.1M spins at 10×1000)")
    p.add_argument("--emit-robots", type=int, default=10)
    p.add_argument("--emit-spins-per-robot", type=int, default=1000)
    p.add_argument("--emit-seed", type=int, default=42)
    p.add_argument("--skip-rawdata", action="store_true",
                   help="skip rawdata emission (debug only — weights file is not the deliverable)")
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
        hit_target=args.hit_target,
        hit_weight=args.hit_weight,
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
    _hit_part = (f" hit={base_breakdown.hit_cost:.2f}"
                 if args.hit_target is not None else "")
    print(f"  → components: rtp={base_breakdown.rtp_cost:.2f} shape={base_breakdown.shape_cost:.2f} cv={base_breakdown.cv_cost:.2f}{_hit_part}")
    if args.hit_target is not None:
        print(f"  hit_target       : {args.hit_target*100:.2f}% (soft, weight={args.hit_weight})")

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

    # Materialize Phase-4 tuned weights into a valid JSON file
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

    # ─────────────────────────────────────────────────────────────────────
    # Phase 5: order optimization (preserves marginals, optimizes
    # near-miss / PWDF / blank-adjacency)
    # ─────────────────────────────────────────────────────────────────────
    exp_before = experience_metrics(
        tuned_weights["reel_sets"]["default"]["reels"],
        high_value=args.high_value,
    )
    print(f"\n=== Phase 5: order-only optimization ({args.sa_steps} SA steps) ===")
    print(f"  experience before: nm_total={exp_before['near_miss_rate_total']*100:.3f}%  "
          f"avg_pwdf={sum(exp_before['avg_pwdf'].values())/len(exp_before['avg_pwdf']):.3f}  "
          f"avg_blank_adj={exp_before['avg_blank_adj']:.3f}")

    if args.sa_steps > 0:
        exp_weights_cfg = ExperienceCostWeights(
            nm_min=args.nm_min,
            nm_max=args.nm_max,
        )

        def exp_cost_fn(reels_list):
            b = evaluate_experience_cost(
                reels_list,
                high_value=args.high_value,
                weights=exp_weights_cfg,
            )
            return b.total, b

        # Snapshot counts BEFORE SA runs; the post-SA invariant check
        # compares counts dict equality (SA swap preserves per-(sym,reel)
        # totals by construction; any mismatch means swap implementation
        # bug, not rounding drift).
        pre_sa_counts = base_counts(tuned_weights)

        from random import Random
        sa_result = run_simulated_annealing(
            tuned_weights["reel_sets"]["default"]["reels"],
            exp_cost_fn,
            config=SAConfig(max_steps=args.sa_steps),
            rng=Random(args.seed + 1),
            verbose=args.verbose,
        )
        # Install the best-ordered reels back into the weights dict
        tuned_weights["reel_sets"]["default"]["reels"] = sa_result.best_reels

        exp_after = experience_metrics(
            tuned_weights["reel_sets"]["default"]["reels"],
            high_value=args.high_value,
        )
        print(f"  experience after : nm_total={exp_after['near_miss_rate_total']*100:.3f}%  "
              f"avg_pwdf={sum(exp_after['avg_pwdf'].values())/len(exp_after['avg_pwdf']):.3f}  "
              f"avg_blank_adj={exp_after['avg_blank_adj']:.3f}")

        # Phase 5 invariant: SA only swaps stop positions within a reel,
        # so per-(symbol, reel) totals MUST be identical pre-SA vs post-SA.
        # Comparing RTP was the wrong proxy — it conflates SA behavior
        # with apply_counts rounding drift (apply_counts rounds int
        # weights from the tuner's float-free counts; RTP computed from
        # those rounded weights will drift up to ~0.3pp from best_profile
        # when some symbols have count=1, but that's rounding, not a
        # Phase 5 violation). Check counts directly instead.
        post_sa_counts = base_counts(tuned_weights)
        assert post_sa_counts == pre_sa_counts, (
            f"Phase 5 SA violated marginal preservation! "
            f"per-(symbol, reel) counts differ pre vs post SA:\n"
            f"  pre:  {pre_sa_counts}\n"
            f"  post: {post_sa_counts}"
        )

        tuned_weights["_tuned_summary"]["phase5_near_miss_before"] = exp_before["near_miss_rate_total"]
        tuned_weights["_tuned_summary"]["phase5_near_miss_after"] = exp_after["near_miss_rate_total"]
        tuned_weights["_tuned_summary"]["phase5_blank_adj_before"] = exp_before["avg_blank_adj"]
        tuned_weights["_tuned_summary"]["phase5_blank_adj_after"] = exp_after["avg_blank_adj"]
        tuned_weights["_tuned_summary"]["phase5_sa_steps"] = args.sa_steps
    else:
        exp_after = exp_before

    args.out_weights.parent.mkdir(parents=True, exist_ok=True)
    args.out_weights.write_text(json.dumps(tuned_weights, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote tuned weights (intermediate) → {args.out_weights}")

    if args.out_report:
        _write_report(
            args.out_report, base_profile, best_profile, target,
            base_breakdown, result.best_breakdown, reachable,
            result.best_counts, x0,
            exp_before=exp_before, exp_after=exp_after,
        )
        print(f"wrote tune report                  → {args.out_report}")

    # Primary deliverable: rawdata chunks via the actual simulator running
    # on tuned weights. Existing player_impact_analyzer --from-cache can
    # consume these directly and produce a report indistinguishable from
    # a real-sampling run.
    #
    # Default destination = slot_designer/rawdata/<machine>sim/mode_<N>/
    # which the virtual console (port 8878) reads from natively. That
    # machine name (<machine>sim) must exist in configs/machines_virtual.json
    # or be added via virtual_app's refresh on next boot.
    if not args.skip_rawdata:
        source_machine = spec["machine"]
        mode = int(spec["mode"])
        # Virtual-machine naming convention: suffix "sim" (per user, 2026-04-21)
        virtual_machine = args.virtual_machine or f"{source_machine}sim"
        rawdata_dir = args.out_rawdata_dir or (
            _ROOT / "slot_designer" / "rawdata" / virtual_machine / f"mode_{mode}"
        )

        # MD5 tags for console's version tracking — single helper
        # shared with virtual_app refresh + virtual_analyzer emit.
        # config_md5 covers spec + ALL mode weights files for this
        # machine; code_md5 covers engine + emitter sources. Any change
        # to those → new md5 → console's _classify_chunks auto-splits
        # old (tuned-v1) chunks from new (tuned-v2) chunks.
        #
        # Refresh machines_virtual.json BEFORE stamping chunks, so the
        # registry and the chunks share the same md5 (weights just
        # changed; registry was last refreshed on virtual console boot
        # with PREVIOUS weights → stale). Without this refresh,
        # classify_chunks sees chunk_md5 != registry_md5 and flags
        # these fresh chunks as "stale version" immediately.
        from slot_designer.backend.machine_version import compute_machine_md5
        from slot_designer.backend.virtual_app import (
            VIRTUAL_MACHINES_CONFIG,
            refresh_machines_virtual,
        )
        try:
            if VIRTUAL_MACHINES_CONFIG.exists():
                refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)
        except Exception as _exc:
            print(f"  [warn] failed to refresh virtual registry: {_exc}")

        # Look up this virtual machine in the refreshed registry so the
        # helper sees the SAME entry (including all modes' weights) that
        # virtual_analyzer will see at sampling time.
        _registry = json.loads(VIRTUAL_MACHINES_CONFIG.read_text(encoding="utf-8"))
        _entry = next(
            (m for m in _registry["machines"] if m.get("machine") == virtual_machine),
            None,
        )
        if _entry is None:
            # Fall back to a synthesized entry (machine not yet registered;
            # operator will need to add it before the virtual console picks
            # up the chunks).
            _entry = {
                "machine": virtual_machine,
                "modes": [mode],
                "_spec_path": str(args.spec.relative_to(_ROOT))
                    if args.spec.is_absolute() else str(args.spec),
                "_weights_path_template": str(
                    args.out_weights.relative_to(_ROOT)
                    if args.out_weights.is_absolute() else args.out_weights
                ),
            }
            print(f"  [warn] {virtual_machine!r} not in machines_virtual.json — "
                  f"chunks tagged but won't appear in virtual console until added")
        config_md5, code_md5 = compute_machine_md5(_entry)

        print(f"\n=== emitting rawdata chunks (primary deliverable) → {rawdata_dir} ===")
        print(f"  virtual machine: {virtual_machine}  (source: {source_machine})")
        print(f"  config_md5: {config_md5[:12]}...  code_md5: {code_md5[:12]}...")

        # Engine reloads from the final weights (which already include
        # Phase 5's ordering). We temporarily rebrand the spec to the
        # virtual machine name so envelope fields + PayoutIdToWinAmount
        # align with how the virtual console will look it up.
        tuned_engine, tuned_spec = load_engine(args.spec, args.out_weights)
        emit_spec = dict(tuned_spec)
        emit_spec["machine"] = virtual_machine

        def _progress(ci, total):
            if ci == 1 or ci % 10 == 0 or ci == total:
                print(f"  chunk {ci:>4}/{total} ({args.emit_robots}×{args.emit_spins_per_robot} spins)")

        emit_summary = emit_simulation_to_dir(
            emit_spec, tuned_engine, rawdata_dir,
            chunks=args.emit_chunks,
            robots=args.emit_robots,
            spins_per_robot=args.emit_spins_per_robot,
            seed=args.emit_seed,
            progress=_progress,
            config_md5=config_md5,
            code_md5=code_md5,
        )
        print(f"\nemitted {len(emit_summary['chunks_written'])} chunks, "
              f"{emit_summary['total_rounds']} rounds total")
        print(f"realized sim RTP (single-seed sample): "
              f"{emit_summary['realized_rtp_pct']:.3f}%  "
              f"(analytic prediction: {best_profile['rtp_pct']:.3f}%)")
        print(f"\nDeliverable: {rawdata_dir}")
        print(f"Start the virtual console:")
        print(f"  powershell -File slot_designer/scripts/start_virtual_console.ps1")
        print(f"  → http://127.0.0.1:8878/console/  (machine: {virtual_machine})")


def _write_report(
    path, base_profile, best_profile, target,
    base_breakdown, best_breakdown, reachable,
    best_counts, base_counts_list,
    exp_before=None, exp_after=None,
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

    if exp_before and exp_after:
        lines.append(f"\n## Phase 5 — experience metrics (order optimization)\n")
        lines.append(f"| metric | before | after | Δ |")
        lines.append(f"|---|---|---|---|")
        lines.append(f"| 2-of-3 near-miss rate (total) | "
                     f"{exp_before['near_miss_rate_total']*100:.4f}% | "
                     f"{exp_after['near_miss_rate_total']*100:.4f}% | "
                     f"{(exp_after['near_miss_rate_total']-exp_before['near_miss_rate_total'])*100:+.4f}pp |")
        lines.append(f"| avg blank-adj to high-value  | "
                     f"{exp_before['avg_blank_adj']:.4f} | "
                     f"{exp_after['avg_blank_adj']:.4f} | "
                     f"{exp_after['avg_blank_adj']-exp_before['avg_blank_adj']:+.4f} |")
        lines.append(f"\nPWDF per high-value symbol (averaged across reels):\n")
        lines.append(f"| symbol | before | after |")
        lines.append(f"|---|---|---|")
        for sym in sorted(exp_before["avg_pwdf"].keys()):
            lines.append(f"| {sym} | {exp_before['avg_pwdf'][sym]:.3f} | "
                         f"{exp_after['avg_pwdf'][sym]:.3f} |")
        lines.append(f"\nNear-miss rate per high-value symbol:\n")
        lines.append(f"| symbol | before (%) | after (%) |")
        lines.append(f"|---|---|---|")
        for sym in sorted(exp_before["near_miss_rate_per_symbol"].keys()):
            lines.append(f"| {sym} | {exp_before['near_miss_rate_per_symbol'][sym]*100:.4f} | "
                         f"{exp_after['near_miss_rate_per_symbol'][sym]*100:.4f} |")

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
