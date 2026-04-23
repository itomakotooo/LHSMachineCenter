"""**DEPRECATED 2026-04-23** — see MODE_DESIGN.md §4.2 v6.

This direct-scale script was the v5 approach. It achieved RTP 32.5pp but
only 7.5% hit rate (user wanted 12-13% to match mode 1's 13%). Root cause:
scaling paying-symbol weights down reduces RTP via marginal-probability
cut, which inherently also reduces hit rate. Direct-scale cannot hit
low-RTP + same-hit-rate targets simultaneously.

v6 uses Phase 4 tune instead (same strips locked, hit_target + trigger_
target as explicit constraints):

  python -m slot_designer.scripts.tune \\
      --spec slot_designer/specs/M15.spec.json \\
      --strips slot_designer/weights/M15/reel_strips.json \\
      --base-weights slot_designer/weights/M15/mode_7/weights.json \\
      --target slot_designer/tuner/targets/M15_mode7_standard_low.target.json \\
      --out-weights slot_designer/weights/M15/mode_7/weights.json \\
      --mode 7 --sa-steps 0 --skip-rawdata \\
      --hit-target 0.125 --hit-weight 1.5 \\
      --trigger-target 0.01136 --trigger-symbol topdollar \\
      --trigger-reel 3 --trigger-weight 2.0

Kept for historical reference only. Do NOT use for production tuning.
See memory/project_slot_designer_hit_rate_deviation.md for the design
principle behind the change.

---

Derive M15 mode 7 weights from mode 1 by direct per-symbol scaling.

M15 mode 7 design (see slot_designer/weights/M15/MODE_DESIGN.md §4):
  * Total RTP 85% (= mode 1 - 10pp)
  * Base RTP ~32.5pp (mode 1 - 10pp; "base 砍小奖")
  * Feature RTP 52.26pp — **identical to mode 1**
  * feature_params — **byte-identical to mode 1**

Why direct scale (not tuner): see ``feedback_tuner_pareto_trap.md``. A
tuner chasing "match bucket shape + low RTP" can silently pareto small-
pay families to zero — 砍 cherry & bar exactly matches the brief, and
scaling preserves hit distribution intuition.

Rule (same formula as M1 mode 7, validated by prior research):
  * Cherry positions × 0.5
  * 1bar/2bar/3bar positions × 0.9
  * All other symbols (blank/high7/doublediamond/topdollar/jackpot) unchanged

The reel strip layout is NOT modified — per
``project_slot_designer_strips_identical_across_modes.md``, all modes
of a machine share byte-identical ``reel_strips.json``. Only the per-
position weight arrays in ``mode_<N>/weights.json`` differ.

Usage:
  python -m slot_designer.scripts.derive_m15_mode_7 [--write] [--verify]

Default dry-run: prints analytic summary without touching files.
``--write`` overwrites ``slot_designer/weights/M15/mode_7/weights.json``.
``--verify`` also runs feature analysis + total RTP check.
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

from slot_designer.devtools.analytic_rtp import analytic_profile
from slot_designer.engine.feature_m15 import FeatureSpec, analyze_feature
from slot_designer.engine.loader import load_engine


_SPEC = _ROOT / "slot_designer" / "specs" / "M15.spec.json"
_STRIPS = _ROOT / "slot_designer" / "weights" / "M15" / "reel_strips.json"
_MODE_1_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M15" / "mode_1" / "weights.json"
_MODE_7_DIR = _ROOT / "slot_designer" / "weights" / "M15" / "mode_7"
_MODE_7_WEIGHTS = _MODE_7_DIR / "weights.json"

# M15 mode 7 design scale factors. The "(Cherry × 0.5, Bar × 0.9)" formula
# from MODE_DESIGN.md §4.2 was inherited from M1 mode 7 and gave only
# ~5pp base RTP drop on M15 (vs 10pp needed): M15's pure_wild (pay_id 1,
# 200×) and wild-boosted high7 (pay_id 2, 30×) inflate when cherry/bar
# marginals drop, partly offsetting the cut. Retuned 2026-04-23 via
# analytic iteration:
#   Cherry × 0.3, Bar × 0.77 → base 32.67pp → total 84.92pp (85% ±1pp ✓)
_SCALE_DEFAULT = {
    "cherry": 0.3,
    "1bar": 0.77,
    "2bar": 0.77,
    "3bar": 0.77,
}


def _scale_weights(
    strips: list[list[str]],
    weights: list[list[float]],
    scale: dict[str, float],
) -> list[list[float]]:
    """Apply per-symbol scale to each reel position."""
    out: list[list[float]] = []
    for strip_reel, weight_reel in zip(strips, weights):
        scaled_reel: list[float] = []
        for sym, w in zip(strip_reel, weight_reel):
            factor = scale.get(sym, 1.0)
            scaled_reel.append(float(w) * factor)
        out.append(scaled_reel)
    return out


def _pin_trigger_rate(
    strips: list[list[str]],
    scaled_weights: list[list[float]],
    *,
    trigger_symbol: str = "topdollar",
    trigger_reel_idx: int = 2,
    target_rate: float = 0.01136,
) -> list[list[float]]:
    """Adjust ``trigger_symbol`` weights on ``trigger_reel_idx`` to hit
    ``target_rate`` exactly. Needed because scaling cherry/bar *down* on
    reel 3 reduces its total weight → topdollar marginal INCREASES even
    though topdollar weight is unchanged. Pinning keeps mode 7's feature
    trigger identical to mode 1 (the brief: 'feature 100% 同 mode 1').

    Math: Let R_other = sum of non-trigger weights on reel; T = sum of
    trigger weights. Target rate r = T / (T + R_other). Solving:
      T_new = r * R_other / (1 - r)

    Since topdollar has N stops (2 on M15 reel 3), per-stop weight =
    T_new / N. All non-topdollar weights on the reel are left exactly as
    the caller passed them in — base RTP impact is just the small shift
    in reel total weight (other symbols' marginals rescale very mildly).
    """
    out = [list(reel) for reel in scaled_weights]
    reel = strips[trigger_reel_idx]
    weights = out[trigger_reel_idx]
    trigger_idxs = [i for i, s in enumerate(reel) if s == trigger_symbol]
    if not trigger_idxs:
        return out
    other_total = sum(w for i, w in enumerate(weights) if i not in set(trigger_idxs))
    if 1.0 - target_rate <= 0:
        raise ValueError(f"target_rate must be < 1.0; got {target_rate}")
    t_total = target_rate * other_total / (1.0 - target_rate)
    per_stop = t_total / len(trigger_idxs)
    for i in trigger_idxs:
        weights[i] = per_stop
    return out


def _build_mode_7_doc(
    mode_1_doc: dict,
    scaled_weights: list[list[float]],
    scale: dict[str, float],
) -> dict:
    """Build the complete mode 7 weights.json dict (weights + feature_params copy)."""
    doc = copy.deepcopy(mode_1_doc)
    doc["mode"] = 7
    doc["weights"] = scaled_weights
    scale_str = ", ".join(f"{s} × {f}" for s, f in scale.items())
    # Replace notes with mode 7-specific text, keeping feature_params identical.
    doc["_notes"] = [
        "M15 mode 7 weights (v5 2026-04-23, derived from mode 1).",
        "",
        "Derivation: `python -m slot_designer.scripts.derive_m15_mode_7 --write`",
        f"Scale rule: {scale_str} per stop position.",
        "Reel strips unchanged (shared byte-identical reel_strips.json across all modes).",
        "",
        "Feature params: 100% identical to mode 1 (same trigger rate, EV, count/value weights).",
        "",
        "Design target (MODE_DESIGN.md §4): Total 85% ±1pp strict.",
        "  Base target ~32.5pp (mode 1 - 10pp via small-pay cull).",
        "  Feature 52.26pp (inherited from mode 1 feature_params).",
        "",
        "NOTE: M1's historical Cherry×0.5, Bar×0.9 formula dropped M15 by only",
        "~5pp (not 10pp), because M15's pure_wild (200×) + wild-boosted high7",
        "(pay_id 2 30×) inflate when cherry/bar marginals drop. Retuned to",
        f"{scale_str} empirically for M15's paytable.",
        "",
        "Do NOT tune this mode through Phase 4/5. Any strip modification or",
        "weight-rebalance that breaks the mode 1 ↔ mode 7 scale relationship",
        "breaks the 'mode 7 = 砍小奖 of mode 1' design contract.",
    ]
    # Blank out the mode-1-specific _tuned_summary (mode 7 wasn't tuned).
    # Keep the structure minimal — analytic verification lives in this script.
    if "_tuned_summary" in doc:
        del doc["_tuned_summary"]
    return doc


def _analytic_base_rtp(mode_weights_path: Path) -> dict:
    """Run analytic_profile on the given mode's engine."""
    engine, _ = load_engine(_SPEC, mode_weights_path)
    return analytic_profile(engine)


def _feature_rtp_pp(doc: dict, trigger_rate: float) -> tuple[float, float]:
    """Return (ev_per_trigger, feature_rtp_pp) for the mode's feature_params."""
    fp = doc["feature_params"]
    spec = FeatureSpec(
        x_count_weights=tuple(fp["x_count_weights"]),
        y_count_weights=tuple(fp["y_count_weights"]),
        x_value_weights=tuple(fp["x_value_weights"]),
        y_value_weights=tuple(fp["y_value_weights"]),
        accept_threshold=float(fp["accept_threshold"]),
        max_rounds=int(fp["max_rounds"]),
    )
    stats = analyze_feature(spec)
    ev = stats.expected_payout
    return ev, 100.0 * trigger_rate * ev


def _trigger_rate_from_mode_1(mode_1_doc: dict) -> float:
    """Trigger rate = reel-3 topdollar weight / reel-3 total.

    Mode 7 has same reel 3 weights as mode 1 at topdollar positions (no
    scale factor applied to topdollar), so trigger rate is identical.
    """
    # Read from _analytic block in mode 1 if present; else compute from weights.
    fp = mode_1_doc.get("feature_params", {})
    return float(fp.get("_analytic", {}).get("target_trigger_rate") or 0.01136)


def run(write: bool, verify: bool, scale: dict[str, float]) -> int:
    print(f"{'='*70}")
    print(f"M15 mode 7 derivation — direct scale from mode 1")
    print(f"{'='*70}\n")

    strips_doc = json.loads(_STRIPS.read_text(encoding="utf-8"))
    mode_1_doc = json.loads(_MODE_1_WEIGHTS.read_text(encoding="utf-8"))

    strips = strips_doc["reels"]
    mode_1_weights = mode_1_doc["weights"]

    print(f"Scale rule: {scale}")
    print(f"Source: mode 1 ({_MODE_1_WEIGHTS.relative_to(_ROOT)})")
    print(f"Target: mode 7 ({_MODE_7_WEIGHTS.relative_to(_ROOT)})")
    print()

    scaled = _scale_weights(strips, mode_1_weights, scale)

    # Pin trigger rate on reel 3 — scaling cherry/bar on reel 3 reduced
    # reel 3 total weight, inflating topdollar's marginal (1.136% → 1.254%).
    # Left uncorrected, mode 7's feature RTP jumps from 52.26 to ~57.7pp
    # and total RTP overshoots the 85% ±1pp strict target. Re-normalize
    # topdollar weight to preserve mode 1's exact trigger rate.
    mode_1_trigger = _trigger_rate_from_mode_1(mode_1_doc)
    scaled = _pin_trigger_rate(
        strips, scaled,
        trigger_symbol="topdollar",
        trigger_reel_idx=2,
        target_rate=mode_1_trigger,
    )

    # Show pre/post marginals per reel for sanity
    print("Per-reel scaled-vs-original symbol totals:")
    print(f"  {'reel':<6}{'symbol':<16}{'before':<12}{'after':<12}{'ratio':<8}")
    for ri, (strip_reel, wr_before, wr_after) in enumerate(
        zip(strips, mode_1_weights, scaled)
    ):
        sym_before: dict[str, float] = {}
        sym_after: dict[str, float] = {}
        for sym, wb, wa in zip(strip_reel, wr_before, wr_after):
            sym_before[sym] = sym_before.get(sym, 0.0) + float(wb)
            sym_after[sym] = sym_after.get(sym, 0.0) + float(wa)
        for sym in sorted(sym_before):
            b, a = sym_before[sym], sym_after[sym]
            ratio = a / b if b else 0.0
            marker = " ←" if sym in scale else ""
            print(
                f"  {ri+1:<6}{sym:<16}{b:<12.4f}{a:<12.4f}{ratio:<8.3f}{marker}"
            )
    print()

    mode_7_doc = _build_mode_7_doc(mode_1_doc, scaled, scale)

    if write:
        _MODE_7_DIR.mkdir(parents=True, exist_ok=True)
        _MODE_7_WEIGHTS.write_text(
            json.dumps(mode_7_doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[write] wrote {_MODE_7_WEIGHTS.relative_to(_ROOT)}")
    else:
        print("[dry-run] use --write to persist mode_7/weights.json")

    if verify and write:
        print()
        print(f"{'-'*70}")
        print(f"Analytic verification")
        print(f"{'-'*70}")
        prof_mode_1 = _analytic_base_rtp(_MODE_1_WEIGHTS)
        prof_mode_7 = _analytic_base_rtp(_MODE_7_WEIGHTS)

        # Compute ACTUAL trigger rates from the on-disk reel weights, not
        # from the mode 1 _analytic block — pin_trigger_rate should bring
        # mode 7 back to mode 1's rate, but prove it from the data.
        def _actual_trigger(weights_path: Path) -> float:
            doc = json.loads(weights_path.read_text(encoding="utf-8"))
            reel_3_syms = strips[2]
            reel_3_wts = doc["weights"][2]
            td = sum(float(w) for s, w in zip(reel_3_syms, reel_3_wts)
                     if s == "topdollar")
            tot = sum(float(w) for w in reel_3_wts)
            return td / tot if tot > 0 else 0.0

        trigger_m1 = _actual_trigger(_MODE_1_WEIGHTS)
        trigger_m7 = _actual_trigger(_MODE_7_WEIGHTS)
        ev_m1, f_rtp_m1 = _feature_rtp_pp(mode_1_doc, trigger_m1)
        ev_m7, f_rtp_m7 = _feature_rtp_pp(mode_7_doc, trigger_m7)

        print(f"\n  {'':>10}{'Trigger':>10}{'Base RTP':>14}{'Feature RTP':>14}{'Total RTP':>14}")
        total_m1 = prof_mode_1["rtp_pct"] + f_rtp_m1
        total_m7 = prof_mode_7["rtp_pct"] + f_rtp_m7
        print(
            f"  {'mode 1':>10}"
            f"{trigger_m1*100:>9.3f}%"
            f"{prof_mode_1['rtp_pct']:>14.3f}"
            f"{f_rtp_m1:>14.3f}"
            f"{total_m1:>14.3f}"
        )
        print(
            f"  {'mode 7':>10}"
            f"{trigger_m7*100:>9.3f}%"
            f"{prof_mode_7['rtp_pct']:>14.3f}"
            f"{f_rtp_m7:>14.3f}"
            f"{total_m7:>14.3f}"
        )
        print(f"\n  mode 7 target total:  85.0 ±1pp (strict)")
        ok = 84.0 <= total_m7 <= 86.0
        status = "OK" if ok else "DRIFT"
        print(f"  mode 7 actual total: {total_m7:.3f}  → [{status}]")
        trigger_gap = abs(trigger_m7 - trigger_m1) * 100
        trigger_ok = trigger_gap < 0.01
        trigger_status = "OK" if trigger_ok else "DRIFT"
        print(f"  trigger rate identity (m7 vs m1): gap {trigger_gap:.4f}pp  [{trigger_status}]")
        if not ok:
            print(
                f"\n!! Base RTP drift outside ±1pp strict band. Mode 7 scale"
                f" factors need adjustment or design target needs revision."
            )
            return 1
        print(f"  feature params identity check (mode 7 ≡ mode 1):"
              f" {'OK' if mode_7_doc['feature_params'] == mode_1_doc['feature_params'] else 'DRIFT'}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--write", action="store_true",
                   help="write mode_7/weights.json (default: dry-run)")
    p.add_argument("--verify", action="store_true",
                   help="after --write, run analytic base + feature RTP check")
    p.add_argument("--cherry", type=float, default=_SCALE_DEFAULT["cherry"],
                   help=f"cherry scale factor (default {_SCALE_DEFAULT['cherry']})")
    p.add_argument("--bar", type=float, default=_SCALE_DEFAULT["1bar"],
                   help=f"bar scale factor — applies to 1bar/2bar/3bar "
                        f"(default {_SCALE_DEFAULT['1bar']})")
    p.add_argument("--i-know-this-is-deprecated", action="store_true",
                   help="Explicit opt-in to the deprecated direct-scale path. "
                        "Required since 2026-04-23 to prevent accidental use.")
    args = p.parse_args()
    if not args.i_know_this_is_deprecated:
        print(
            "\n!! DEPRECATED: this direct-scale path hits RTP but misses the\n"
            "   hit-rate design constraint (mode 7 lands at 7.5% vs target 13%).\n"
            "   Use scripts/tune.py with M15_mode7_standard_low.target.json\n"
            "   instead. See MODE_DESIGN.md §4.2 v6 for the current invocation.\n"
            "\n   To force-run anyway (historical / debugging only), pass\n"
            "   --i-know-this-is-deprecated.\n",
            file=sys.stderr,
        )
        sys.exit(2)
    scale = {"cherry": args.cherry, "1bar": args.bar, "2bar": args.bar, "3bar": args.bar}
    sys.exit(run(write=args.write, verify=args.verify, scale=scale))


if __name__ == "__main__":
    main()
