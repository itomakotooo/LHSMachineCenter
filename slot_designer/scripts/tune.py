"""CLI: tune reel weights (Phase 4) + shared strip order (Phase 5), emit dev rawdata.

Two-stage pipeline:

  Phase 4 — count tuning (per-mode, hard constraints):
    base weights → ES on per-(symbol, reel) counts → marginals match
    target RTP + bucket shape + CV. Runs ONLY on the mode being tuned
    (each mode's marginals are independent).

  Phase 5 — JOINT stop-order tuning (shared across modes):
    Since 2026-04-22 all modes of a machine share one ``reel_strips.json``
    (position → symbol map). Phase 5 runs joint simulated annealing over
    the shared strip + every sibling mode's weights simultaneously, with
    co-swap mutation that preserves each mode's marginals while keeping
    strips identical across modes. Cost = sum of per-mode experience
    metrics (near-miss / PWDF / blank-adjacency).

Deliverables:
  1. **reel_strips.json** (shared) — written to ``--out-strips``
     (defaults to overwriting ``--strips`` in place). Joint Phase 5
     updates it.
  2. **mode_<N>/weights.json** (per mode) — written to ``--out-weights``.
     Phase 4 + Phase 5 both update this mode's weights.
  3. **Sibling mode weights.json** — joint Phase 5 CO-SWAPS positions
     across all siblings, so their weights.json files also get written
     back (positions reshuffled, marginals unchanged).
  4. **Dev rawdata chunks** (scratch) — ``slot_designer/_dev_scratch/
     rawdata/<machine>/mode_<N>/``, for ``player_impact_analyzer
     --from-cache`` to cross-check realized vs analytic.

Usage:

    python -m slot_designer.scripts.tune \\
        --spec slot_designer/specs/M1.spec.json \\
        --strips slot_designer/weights/M1/reel_strips.json \\
        --base-weights slot_designer/weights/M1/mode_1/weights.json \\
        --target slot_designer/tuner/targets/M14_mode1.target.json \\
        --out-weights slot_designer/weights/M1/mode_1/weights.json \\
        --out-report slot_designer/weights/M1/mode_1/TUNE_REPORT.md \\
        --evaluations 1500 --restarts 3 --sa-steps 5000
"""
from __future__ import annotations

import argparse
import copy
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
from slot_designer.tuner.layout import (
    apply_counts,
    base_counts,
    base_counts_from_assembled,
    disassemble_to_weights_array,
    extract_symbol_layout,
    marginals_from_counts,
)
from slot_designer.tuner.loop import ESConfig, run_with_restarts
from slot_designer.tuner.ordering import (
    ExperienceCostWeights,
    SAConfig,
    count_alternation_violations,
    evaluate_experience_cost,
    initialize_alternating,
    run_joint_simulated_annealing,
)


def _load_strips(strips_path: Path) -> dict:
    return json.loads(strips_path.read_text(encoding="utf-8"))


def _load_weights(weights_path: Path) -> dict:
    return json.loads(weights_path.read_text(encoding="utf-8"))


def _assemble_from_strips_weights(strips_doc: dict, weights_doc: dict) -> list[list[dict]]:
    """Assemble strips + weights into [[{symbol, weight}, ...], ...] shape."""
    return [
        [{"symbol": s, "weight": int(w)} for s, w in zip(strip, wts)]
        for strip, wts in zip(strips_doc["reels"], weights_doc["weights"])
    ]


def _write_strips(strips_path: Path, strips_doc: dict, reels_layout: list[list[str]]) -> None:
    out = copy.deepcopy(strips_doc)
    out["reels"] = reels_layout
    strips_path.parent.mkdir(parents=True, exist_ok=True)
    strips_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def _write_weights(
    weights_path: Path,
    weights_doc: dict,
    weights_array: list[list[int]],
    *,
    extra_fields: dict | None = None,
) -> None:
    out = copy.deepcopy(weights_doc)
    out["weights"] = weights_array
    if extra_fields:
        out.setdefault("_tuned_summary", {}).update(extra_fields)
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    weights_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def _find_sibling_modes(base_weights_path: Path, this_mode: int) -> dict[int, Path]:
    """Find all sibling ``mode_<N>/weights.json`` files next to the one
    being tuned. Convention: weights.json lives at
    ``<machine_dir>/mode_<N>/weights.json``; siblings are all other
    ``mode_*/weights.json`` in the grandparent (machine dir).

    Returns {mode_int: path} EXCLUDING this_mode. Missing machine dir
    or no siblings → empty dict (joint Phase 5 degenerates to the
    single-mode case, still valid).
    """
    machine_dir = base_weights_path.parent.parent
    out: dict[int, Path] = {}
    if not machine_dir.is_dir():
        return out
    for mode_dir in sorted(machine_dir.glob("mode_*")):
        if not mode_dir.is_dir():
            continue
        try:
            m = int(mode_dir.name.split("_", 1)[1])
        except (ValueError, IndexError):
            continue
        if m == this_mode:
            continue
        wp = mode_dir / "weights.json"
        if wp.exists():
            out[m] = wp
    return out


def main() -> None:
    p = argparse.ArgumentParser(
        description="Tune reel weights (Phase 4) + joint strip order (Phase 5).",
    )
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--strips", required=True, type=Path,
                   help="slot_designer/weights/<machine>/reel_strips.json — "
                        "the shared symbol-at-position layout for ALL modes "
                        "of this machine. Joint Phase 5 SA updates it.")
    p.add_argument("--base-weights", required=True, type=Path,
                   help="slot_designer/weights/<machine>/mode_<N>/weights.json "
                        "— per-stop weights for THIS mode (the starting point "
                        "for Phase 4 count rescaling).")
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--out-weights", required=True, type=Path,
                   help="Destination for this mode's tuned weights.json "
                        "(normally the same path as --base-weights; the "
                        "tuner overwrites it in place).")
    p.add_argument("--out-strips", type=Path, default=None,
                   help="Destination for the updated reel_strips.json. "
                        "Defaults to overwriting --strips in place — joint "
                        "Phase 5 changes the shared layout, so this affects "
                        "every mode of the machine.")
    p.add_argument("--out-rawdata-dir", type=Path, default=None,
                   help="(dev scratch) directory for sim rawdata chunks; "
                        "defaults to slot_designer/_dev_scratch/rawdata/"
                        "<machine>/mode_<N>/ (ephemeral). Not a console "
                        "artifact — console rawdata comes from batch-run.")
    p.add_argument("--virtual-machine", default=None,
                   help="virtual machine name (defaults to <source_machine>sim). "
                        "Should be registered in configs/machines_virtual.json.")
    p.add_argument("--mode", type=int, default=None,
                   help="mode (rtp_id) to stamp on emitted dev-scratch chunks. "
                        "Defaults to spec[\"mode\"]. Use when tuning a "
                        "non-primary mode that shares spec/rules with mode 1 "
                        "but has different reel weights.")
    p.add_argument("--out-report", type=Path, default=None)
    p.add_argument("--evaluations", type=int, default=800)
    p.add_argument("--restarts", type=int, default=3)
    p.add_argument("--sigma", type=float, default=8.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--rtp-weight", type=float, default=1.0)
    p.add_argument("--shape-weight", type=float, default=1.0)
    p.add_argument("--cv-weight", type=float, default=0.3)
    p.add_argument("--hit-target", type=float, default=None,
                   help="optional hit_rate soft target (fraction 0-1).")
    p.add_argument("--hit-weight", type=float, default=0.5)
    p.add_argument("--verbose", action="store_true")

    # Phase 5 (joint order optimization) parameters
    p.add_argument("--sa-steps", type=int, default=5000,
                   help="joint SA steps for shared-strip order optimization. "
                        "Set 0 to skip Phase 5 entirely (Phase 4 only).")
    p.add_argument("--nm-min", type=float, default=0.01)
    p.add_argument("--nm-max", type=float, default=0.10)
    p.add_argument("--high-value", nargs="+",
                   default=["Seven1", "Seven2", "Diamond1", "Diamond2"])

    # Rawdata emission parameters
    p.add_argument("--emit-chunks", type=int, default=110)
    p.add_argument("--emit-robots", type=int, default=10)
    p.add_argument("--emit-spins-per-robot", type=int, default=1000)
    p.add_argument("--emit-seed", type=int, default=42)
    p.add_argument("--skip-rawdata", action="store_true")
    args = p.parse_args()

    out_strips_path = args.out_strips or args.strips

    # ────────────────── Load + prepare state ──────────────────
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    strips_doc = _load_strips(args.strips)
    base_weights_doc = _load_weights(args.base_weights)
    target = json.loads(args.target.read_text(encoding="utf-8"))

    # Detect the blank symbol used by this machine. M1 uses "Blank"
    # (PascalCase); M15+ aligns to production rawdata with lowercase
    # "blank". Pick whichever filler symbol appears on all reels.
    _all_syms_flat = [s for strip in strips_doc["reels"] for s in strip]
    if "Blank" in _all_syms_flat:
        blank_symbol = "Blank"
    elif "blank" in _all_syms_flat:
        blank_symbol = "blank"
    else:
        # Fall back: most common filler-kind symbol
        from collections import Counter
        _filler_syms = [s for s in _all_syms_flat
                        if spec.get("symbols", {}).get(s, {}).get("kind") == "filler"]
        if _filler_syms:
            blank_symbol = Counter(_filler_syms).most_common(1)[0][0]
        else:
            blank_symbol = "Blank"  # last resort; will likely fail alternation

    # Assemble base reels (shared strips + this mode's weights)
    base_reels = _assemble_from_strips_weights(strips_doc, base_weights_doc)

    # Build evaluator once (paytable is fixed during tuning)
    symbols = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"])
    evaluator = PaytableEvaluator(symbols, rules, spec["evaluation_order"])

    # Reachable buckets depend on paytable only; compute once.
    base_engine, _ = load_engine(args.spec, args.base_weights)
    reachable = structurally_reachable_buckets(base_engine)
    base_profile = analytic_profile(base_engine)

    cost_weights_cfg = CostWeights(
        rtp_weight=args.rtp_weight,
        shape_weight=args.shape_weight,
        cv_weight=args.cv_weight,
        hit_target=args.hit_target,
        hit_weight=args.hit_weight,
    )

    if "cv" not in target:
        tgt_std = target.get("std_return_x", 0.0)
        tgt_rtp_frac = target.get("rtp_pct", 100.0) / 100.0
        target["cv"] = tgt_std / tgt_rtp_frac if tgt_rtp_frac > 0 else 0.0

    def cost_fn(counts_list):
        marginals = marginals_from_counts(counts_list)
        pred = analytic_profile_from_marginals(evaluator, marginals)
        breakdown = evaluate_cost(
            pred, target, reachable_buckets=reachable, weights=cost_weights_cfg,
        )
        return breakdown.total, breakdown

    x0 = base_counts_from_assembled(base_reels)
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

    # ────────────────── Phase 4: count ES ──────────────────
    cfg = ESConfig(sigma_init=args.sigma)
    print(f"\n=== Phase 4 — (1+1)-ES count tuning: {args.restarts} restarts × {args.evaluations} evals ===")
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

    print(f"\n=== Phase 4 result ===")
    print(f"  RTP              : {best_profile['rtp_pct']:.3f}%  (target {target['rtp_pct']:.3f}%)")
    print(f"  hit_rate         : {best_profile['hit_rate']*100:.3f}%  (target {target['hit_rate']*100:.3f}%)")
    print(f"  CV               : {best_profile['cv']:.3f}  (target {target['cv']:.3f})")
    print(f"  ΔRTP             : {result.best_breakdown.rtp_gap_pp:.3f}pp")
    print(f"  shape JS         : {result.best_breakdown.shape_js:.5f}")
    print(f"  cost (total)     : {result.best_cost:.4f}  (was {base_cost:.4f}; Δ={base_cost-result.best_cost:+.4f})")

    # Materialize new counts onto the existing strip — uses apply_counts's
    # per-symbol rescale, wrapped in the old weights_dict envelope so
    # the helper works unchanged.
    base_weights_envelope = {
        "reel_sets": {"default": {"reels": base_reels}},
    }
    tuned_envelope = apply_counts(base_weights_envelope, result.best_counts)
    tuned_reels = tuned_envelope["reel_sets"]["default"]["reels"]

    # ────────────────── Phase 5: joint order SA ──────────────────
    exp_before = experience_metrics(tuned_reels, high_value=args.high_value, blank_symbol=blank_symbol)
    print(f"\n=== Phase 5 — joint shared-strip order SA ({args.sa_steps} steps) ===")
    print(f"  experience before: nm_total={exp_before['near_miss_rate_total']*100:.3f}%  "
          f"avg_pwdf={sum(exp_before['avg_pwdf'].values())/len(exp_before['avg_pwdf']):.3f}  "
          f"avg_blank_adj={exp_before['avg_blank_adj']:.3f}")

    this_mode_key = str(int(args.mode) if args.mode is not None else int(spec["mode"]))

    # Build the joint state: shared strips (from tuned_reels) + every mode's weights
    # (this mode from tuned_reels, siblings from their existing weights.json files).
    shared_strips = extract_symbol_layout(tuned_reels)
    # blank_symbol was detected earlier from strips_doc (see Load + prepare state).
    weights_per_mode: dict[str, list[list[int]]] = {
        this_mode_key: disassemble_to_weights_array(tuned_reels),
    }
    sibling_paths = _find_sibling_modes(
        args.base_weights.resolve(),
        int(this_mode_key),
    )
    for mode_num, wp in sibling_paths.items():
        sib_doc = _load_weights(wp)
        weights_per_mode[str(mode_num)] = sib_doc["weights"]

    if args.sa_steps > 0:
        # Enforce alternation on the shared strip before SA. If already
        # alternating (normal case on a re-tune), initialize_alternating
        # is a no-op. For a first-time tune, this co-migrates each
        # mode's weights onto the alternating positions.
        pre_alt_violations = sum(
            count_alternation_violations(
                [{"symbol": s} for s in strip], blank_symbol
            )
            for strip in shared_strips
        )
        if pre_alt_violations > 0:
            # Pair each non-blank symbol at its current position across
            # modes, and Blank for every position that's currently Blank.
            # initialize_alternating re-permutes stops; we need to apply
            # the same permutation to every mode's weight array.
            from slot_designer.tuner.ordering import initialize_alternating
            new_shared_strips: list[list[str]] = []
            new_weights_per_mode: dict[str, list[list[int]]] = {
                m: [] for m in weights_per_mode
            }
            for ri, strip in enumerate(shared_strips):
                # Assemble for this reel in ANY mode to drive init, then
                # reuse the chosen permutation across all modes' weights.
                stops = [
                    {"symbol": sym, "weight": weights_per_mode[this_mode_key][ri][pos]}
                    for pos, sym in enumerate(strip)
                ]
                # initialize_alternating interleaves blanks and non-blanks
                # in the order they appear. We need to record the
                # position→new_position permutation so we can apply it to
                # the OTHER modes' weights too.
                new_reel = initialize_alternating(stops, blank_symbol)
                # Reconstruct permutation: old position i → new position
                # where stops[i]'s new location in new_reel is found by
                # identity. Since symbol and weight are preserved,
                # locate by (sym, weight, index-within-same-symbol).
                # Simpler approach: initialize_alternating sorts blanks
                # and non-blanks by original order then interleaves; we
                # re-implement inline to get an explicit permutation.
                blanks_src = [i for i, s in enumerate(strip) if s == blank_symbol]
                nonblanks_src = [i for i, s in enumerate(strip) if s != blank_symbol]
                perm: list[int] = []
                for b, n in zip(blanks_src, nonblanks_src):
                    perm.append(b)
                    perm.append(n)
                # Build new strip + new weights using the permutation
                new_shared_strips.append([strip[perm[i]] for i in range(len(perm))])
                for mk, mw in weights_per_mode.items():
                    new_weights_per_mode[mk].append(
                        [mw[ri][perm[i]] for i in range(len(perm))]
                    )
            shared_strips = new_shared_strips
            weights_per_mode = new_weights_per_mode
            if args.verbose:
                print(f"  alternation init: {pre_alt_violations} → 0 adjacency "
                      f"violations across {len(shared_strips)} reels")

        exp_cfg = ExperienceCostWeights(
            nm_min=args.nm_min,
            nm_max=args.nm_max,
        )

        from random import Random
        joint = run_joint_simulated_annealing(
            shared_strips,
            weights_per_mode,
            high_value=args.high_value,
            cost_weights=exp_cfg,
            config=SAConfig(max_steps=args.sa_steps),
            rng=Random(args.seed + 1),
            blank_symbol=blank_symbol,
            verbose=args.verbose,
        )
        shared_strips = joint.best_strips
        weights_per_mode = joint.best_weights_per_mode

        # Per-mode experience summary
        print("  experience after (per mode):")
        for mk, bd in joint.best_breakdowns.items():
            print(f"    mode {mk}: nm={bd.near_miss_rate_total*100:.3f}%  "
                  f"avg_pwdf={bd.avg_pwdf:.3f}  blank_adj={bd.avg_blank_adj:.3f}  "
                  f"alternation_violations={bd.alternation_violations}")

    # Rebuild this mode's assembled reels from (shared_strips + this mode's weights)
    final_this_mode_reels = [
        [{"symbol": s, "weight": int(w)} for s, w in zip(strip, wts)]
        for strip, wts in zip(shared_strips, weights_per_mode[this_mode_key])
    ]
    exp_after = experience_metrics(final_this_mode_reels, high_value=args.high_value, blank_symbol=blank_symbol)
    post_alt_violations = sum(count_alternation_violations(r, blank_symbol) for r in final_this_mode_reels)

    # Phase 5 marginal-preservation invariant — class-preserving co-swap
    # must leave per-(symbol, reel) totals for this mode unchanged from
    # end of Phase 4. Any mismatch = operator bug.
    pre_sa_counts = base_counts_from_assembled(tuned_reels)
    post_sa_counts = base_counts_from_assembled(final_this_mode_reels)
    assert post_sa_counts == pre_sa_counts, (
        f"Phase 5 joint SA violated marginal preservation for mode "
        f"{this_mode_key}!\n  pre:  {pre_sa_counts}\n  post: {post_sa_counts}"
    )

    # ────────────────── Write outputs ──────────────────
    _write_strips(out_strips_path, strips_doc, shared_strips)
    print(f"\nwrote shared strips → {out_strips_path}")

    extra_summary = {
        "rtp_pct": best_profile["rtp_pct"],
        "hit_rate": best_profile["hit_rate"],
        "cv": best_profile["cv"],
        "shape_js_to_target": result.best_breakdown.shape_js,
        "rtp_gap_pp": result.best_breakdown.rtp_gap_pp,
        "evaluations": result.evaluations * args.restarts,
        "phase5_near_miss_before": exp_before["near_miss_rate_total"],
        "phase5_near_miss_after": exp_after["near_miss_rate_total"],
        "phase5_blank_adj_before": exp_before["avg_blank_adj"],
        "phase5_blank_adj_after": exp_after["avg_blank_adj"],
        "phase5_sa_steps": args.sa_steps,
        "alternation_violations": post_alt_violations,
    }
    _write_weights(
        args.out_weights, base_weights_doc,
        weights_per_mode[this_mode_key],
        extra_fields=extra_summary,
    )
    print(f"wrote tuned weights (mode {this_mode_key}) → {args.out_weights}")

    # Write sibling modes' weight arrays (Phase 5 joint SA may have
    # co-swapped positions; their marginals are preserved but arrays differ)
    for mode_num, wp in sibling_paths.items():
        sib_doc = _load_weights(wp)
        new_weights = weights_per_mode[str(mode_num)]
        _write_weights(wp, sib_doc, new_weights)
        print(f"wrote sibling weights (mode {mode_num}) → {wp}  "
              f"[positions co-swapped, marginals preserved]")

    if args.out_report:
        _write_report(
            args.out_report, base_profile, best_profile, target,
            base_breakdown, result.best_breakdown, reachable,
            result.best_counts, x0,
            exp_before=exp_before, exp_after=exp_after,
        )
        print(f"wrote tune report → {args.out_report}")

    # ────────────────── Dev-scratch rawdata ──────────────────
    if args.skip_rawdata:
        return

    source_machine = spec["machine"]
    mode = int(args.mode) if args.mode is not None else int(spec["mode"])
    virtual_machine = args.virtual_machine or f"{source_machine}sim"
    rawdata_dir = args.out_rawdata_dir or (
        _ROOT / "slot_designer" / "_dev_scratch" / "rawdata"
        / virtual_machine / f"mode_{mode}"
    )
    if rawdata_dir.is_dir():
        wiped = 0
        for _p in rawdata_dir.glob("chunk_*.json"):
            try:
                _p.unlink()
                wiped += 1
            except OSError:
                pass
        if wiped:
            print(f"  [info] wiped {wiped} pre-existing chunk(s) in {rawdata_dir}")

    from slot_designer.backend.machine_version import compute_machine_md5
    from slot_designer.backend.virtual_registry import (
        VIRTUAL_MACHINES_CONFIG,
        refresh_machines_virtual,
    )
    try:
        if VIRTUAL_MACHINES_CONFIG.exists():
            refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)
    except Exception as _exc:
        print(f"  [warn] failed to refresh virtual registry: {_exc}")

    _registry = json.loads(VIRTUAL_MACHINES_CONFIG.read_text(encoding="utf-8"))
    _entry = next(
        (m for m in _registry["machines"] if m.get("machine") == virtual_machine),
        None,
    )
    if _entry is None:
        # Fall back to a synthesized entry so md5 computation works, but
        # warn that the machine isn't registered.
        _entry = {
            "machine": virtual_machine,
            "modes": [mode],
            "_spec_path": str(args.spec.relative_to(_ROOT))
                if args.spec.is_absolute() else str(args.spec),
            "_strips_path": str(out_strips_path.relative_to(_ROOT))
                if out_strips_path.is_absolute() else str(out_strips_path),
            "_weights_path_template": str(
                args.out_weights.relative_to(_ROOT).parent.parent
                / "mode_{mode}" / "weights.json"
            ) if args.out_weights.is_absolute() else str(
                args.out_weights.parent.parent / "mode_{mode}" / "weights.json"
            ),
        }
        print(f"  [warn] {virtual_machine!r} not in machines_virtual.json — "
              f"chunks tagged but won't appear in virtual console until added")
    config_md5, code_md5 = compute_machine_md5(_entry)

    print(f"\n=== emitting rawdata chunks (primary deliverable) → {rawdata_dir} ===")
    print(f"  virtual machine: {virtual_machine}  (source: {source_machine})")
    print(f"  config_md5: {config_md5[:12]}...  code_md5: {code_md5[:12]}...")

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
        mode=mode,
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
