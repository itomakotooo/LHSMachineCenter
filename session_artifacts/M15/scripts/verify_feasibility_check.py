"""M15 feasibility numerator check (process_improvements #22).

Independent of `slot_designer/machines/M15/verify.py`:

  * `verify.py` checks "design red lines satisfied by current weights?"
  * THIS script checks "are the target.json bands themselves REACHABLE
    by the design v2 candidate levers?"

Rationale (per process_improvement #22):

> "Without a feasibility check, Stage 5 Verifier writes red lines for
>  unreachable targets — tuner Pareto-traps trying to satisfy
>  contradictory cost signals. M15 design v0 target base RTP 47.5pp was
>  unreachable via D's stated levers. If V writes a red line 'base RTP
>  in [44, 51pp]' and tuner ships base 38pp, RED forever."

What this script does:

  1. Reads ``session_artifacts/M15/targets_v2/M15_mode{1,2,5,7}_target.json``
     for the target bands and `v2_feasibility` measured values.
  2. Builds the v2 design candidate weights via the same transforms as
     ``session_artifacts/M15/scripts/design_v2_feasibility.py``
     (re-uses build_candidate_modeN functions).
  3. Runs ``analytic_profile`` + ``analyze_feature`` end-to-end and
     reports for each target band:
       * MATCH      — within band; design is feasible
       * NEAR-MISS  — outside band by a small margin; Stage 6 tuner
                       expected to close (e.g., m2 RTP -5.6pp, m5 +19.7,
                       m7 -0.3pp)
       * STRUCTURAL — empirically unreachable within paytable / philosophy
                       constraints (e.g., m1 base CV [3,5] — see Fix #1)
  4. Optionally writes the v2 candidate weights to a directory so that
     ``python -m slot_designer.machines.M15.verify --weights-dir <dir>``
     can be run against them for the iter0 RED capture.

Usage:

    # Just print feasibility report
    python session_artifacts/M15/scripts/verify_feasibility_check.py

    # Materialize v2 candidate weights to a directory (for verify.py iter0)
    python session_artifacts/M15/scripts/verify_feasibility_check.py \
        --materialize-to /tmp/m15_v2_weights

Exit:

    0 = all targets MATCH or are flagged NEAR-MISS / STRUCTURAL with
        evidence in target.json
    1 = at least one target has FAIL with no documented justification
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Reuse v2 feasibility candidate builders (already author-verified).
from session_artifacts.M15.scripts.design_v2_feasibility import (  # noqa: E402
    build_candidate_mode1,
    build_candidate_mode2,
    build_candidate_mode5,
    build_candidate_mode7,
    load_v7_weights,
)
from slot_designer.core.devtools.analytic_rtp import (  # noqa: E402
    analytic_profile,
    compute_reel_marginal,
)
from slot_designer.core.engine.loader import load_engine  # noqa: E402
from slot_designer.machines.M15.plugins.feature import (  # noqa: E402
    FeatureSpec,
    _X_POOL,
    _Y_POOL,
    _round_payout_distribution,
    analyze_feature,
)

_M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15_DIR / "spec.json"
STRIPS_PATH = _M15_DIR / "reel_strips.json"
TARGETS_DIR = _ROOT / "session_artifacts" / "M15" / "targets_v2"


def _profile_candidate(candidate_doc: dict, label: str) -> dict:
    """Run analytic_profile + feature analysis on a v2 candidate doc.

    Mirrors `design_v2_feasibility.py:_profile_candidate` but kept local
    to avoid coupling on private functions in the design script.
    """
    tmp = Path("__tmp_feasibility_weights.json")
    tmp.write_text(json.dumps(candidate_doc, indent=2), encoding="utf-8")
    try:
        engine, _spec = load_engine(SPEC_PATH, tmp, strips_path=STRIPS_PATH)
        profile = analytic_profile(engine)

        reel_margs = [compute_reel_marginal(r) for r in engine.reels]
        trig_prob = reel_margs[-1].get("topdollar", 0.0)

        fp = candidate_doc.get("feature_params") or {}
        fspec = FeatureSpec(
            x_count_weights=tuple(fp["x_count_weights"]),
            y_count_weights=tuple(fp["y_count_weights"]),
            x_value_weights=tuple(fp.get("x_value_weights") or (1.0,) * len(_X_POOL)),
            y_value_weights=tuple(fp.get("y_value_weights") or (1.0,) * len(_Y_POOL)),
            accept_threshold=float(fp["accept_threshold"]),
            max_rounds=int(fp["max_rounds"]),
        )
        fstats = analyze_feature(fspec)

        round_dist = _round_payout_distribution(
            tuple(fp["x_count_weights"]),
            tuple(fp["y_count_weights"]),
            tuple(fp.get("x_value_weights") or (1.0,) * len(_X_POOL)),
            tuple(fp.get("y_value_weights") or (1.0,) * len(_Y_POOL)),
        )
        p_r_ge_1000_per_trigger = sum(p for r, p in round_dist if r >= 1000)
        p_r_ge_1000_per_spin = trig_prob * p_r_ge_1000_per_trigger

        feature_rtp_pp = trig_prob * fstats.expected_payout * 100.0

        return {
            "label": label,
            "base_rtp_pp": profile["rtp_pct"],
            "feature_rtp_pp": feature_rtp_pp,
            "total_rtp_pct": profile["rtp_pct"] + feature_rtp_pp,
            "hit_rate": profile["hit_rate"],
            "base_cv": profile["cv"],
            "trigger_rate": trig_prob,
            "feature_ev": fstats.expected_payout,
            "feature_cv": fstats.cv,
            "p_r_ge_1000_per_spin": p_r_ge_1000_per_spin,
            "p_count_x_eq_1": fp["x_count_weights"][0] / sum(fp["x_count_weights"]),
            "jackpot_per_reel": [m.get("jackpot", 0.0) for m in reel_margs],
            "pay_hits": profile["pay_hits"],
            "pay_rtp": profile["pay_rtp"],
        }
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_target(mode: int) -> dict:
    path = TARGETS_DIR / f"M15_mode{mode}_target.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _classify(val: float, lo: float | None, hi: float | None) -> str:
    """Classify a measurement against a band."""
    if lo is not None and val < lo:
        return "BELOW"
    if hi is not None and val > hi:
        return "ABOVE"
    return "MATCH"


def _check(target_name: str, val: float, lo: float | None, hi: float | None,
           *, label: str, doc_status: str = "", fmt: str = "{:.4f}") -> dict:
    """Run a single band check + categorize per process_improvements #22 + #27."""
    cls = _classify(val, lo, hi)
    if cls == "MATCH":
        category = "MATCH"
    elif "STRUCTURAL" in doc_status.upper():
        category = "STRUCTURAL"
    elif "NEAR-MISS" in doc_status.upper() or "tuner-closable" in doc_status.lower():
        category = "NEAR-MISS"
    else:
        category = "FAIL"
    lo_s = "-inf" if lo is None else fmt.format(lo)
    hi_s = "+inf" if hi is None else fmt.format(hi)
    return {
        "name": target_name,
        "label": label,
        "value": val,
        "band_lo": lo,
        "band_hi": hi,
        "class": category,
        "raw_class": cls,
        "doc_status": doc_status,
        "fmt": fmt,
        "lo_s": lo_s,
        "hi_s": hi_s,
    }


def _report_mode(mode: int, m: dict, target: dict) -> tuple[list[dict], int]:
    """Run feasibility checks for one mode. Returns (results, num_FAIL)."""
    out = []
    t = target["_design_targets_v2_M15_only"]

    rtp_block = t.get("rtp", {})
    band = rtp_block.get("band_pct", [None, None])
    out.append(_check("rtp", m["total_rtp_pct"], band[0], band[1],
                      label=f"Total RTP %", doc_status=rtp_block.get("v2_status", ""),
                      fmt="{:.3f}"))

    hit_block = t.get("hit_rate", {})
    hit_band = hit_block.get("band")
    if hit_band:
        out.append(_check("hit_rate", m["hit_rate"], hit_band[0], hit_band[1],
                          label="Base hit rate",
                          doc_status=hit_block.get("v2_status", "")))

    # Universal: 1000+ + jackpot
    out.append(_check("p_r_ge_1000_per_spin", m["p_r_ge_1000_per_spin"], None, 1e-5,
                      label="P(R>=1000/spin)", doc_status="PASS", fmt="{:.2e}"))
    for r_idx, m_jp in enumerate(m["jackpot_per_reel"]):
        out.append(_check(f"jackpot_R{r_idx+1}", m_jp, None, 0.006,
                          label=f"Jackpot R{r_idx+1} marginal",
                          doc_status="PASS"))

    # Per-pay frequency floors (cherry2/cherry3)
    pp_block = t.get("per_pay_frequency_floors_pct", {})
    for fam_key, pid_str in [("cherry2_pay_id_71", "71"), ("cherry3_pay_id_4", "4")]:
        fam = pp_block.get(fam_key, {})
        floor_pct = fam.get("floor_pct") or fam.get("floor_pct_relaxed_cut_mode")
        cap_pct = fam.get("cap_pct")
        if cap_pct is None:
            continue
        p_pct = m["pay_hits"].get(pid_str, 0.0) * 100.0
        out.append(_check(f"per_pay_floor_{fam_key}",
                          p_pct, floor_pct, cap_pct,
                          label=f"{fam_key} frequency P",
                          doc_status=fam.get("v2_status", "")))

    fail_count = sum(1 for o in out if o["class"] == "FAIL")
    return out, fail_count


def _materialize_weights(out_dir: Path, candidates: dict[int, dict]) -> None:
    """Write v2 candidate weights to ``out_dir/mode_N/weights.json`` + a
    copy of reel_strips.json so ``load_engine`` can auto-discover it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # reel_strips.json one level up from weights/<mode>/weights.json
    machine_root = out_dir.parent
    machine_root.mkdir(parents=True, exist_ok=True)
    strips_dst = machine_root / "reel_strips.json"
    if not strips_dst.exists():
        strips_dst.write_text(STRIPS_PATH.read_text(encoding="utf-8"),
                              encoding="utf-8")
    for mode, doc in candidates.items():
        mode_dir = out_dir / f"mode_{mode}"
        mode_dir.mkdir(exist_ok=True)
        (mode_dir / "weights.json").write_text(
            json.dumps(doc, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="M15 feasibility numerator check (proc_imp #22)",
    )
    p.add_argument("--materialize-to", type=Path, default=None,
                   help="Write v2 candidate weights to this directory's "
                        "weights/mode_<N>/ subtree so verify.py can be run "
                        "against them via --weights-dir.")
    args = p.parse_args(argv)

    # Build v2 candidates from v7 baselines + transforms.
    v7_m1 = load_v7_weights(1)
    v7_m2 = load_v7_weights(2)
    v7_m5 = load_v7_weights(5)
    v7_m7 = load_v7_weights(7)
    m1 = build_candidate_mode1(v7_m1)
    m2 = build_candidate_mode2(v7_m2, v7_m1)
    m5 = build_candidate_mode5(v7_m5, m2)
    m7 = build_candidate_mode7(v7_m7, m1)
    candidates = {1: m1, 2: m2, 5: m5, 7: m7}

    # Optional materialize
    if args.materialize_to is not None:
        _materialize_weights(args.materialize_to, candidates)
        print(f"v2 candidate weights written to: {args.materialize_to}")
        print(f"  spec : {SPEC_PATH}  (read-only, not copied)")
        print(f"  strips: {args.materialize_to.parent / 'reel_strips.json'}")
        for mode in (1, 2, 5, 7):
            print(f"  mode {mode}: {args.materialize_to / f'mode_{mode}' / 'weights.json'}")
        print()
        print("Then run:")
        print(f"  python -m slot_designer.machines.M15.verify --weights-dir "
              f"{args.materialize_to}")

    # Run feasibility report
    print()
    print("=" * 70)
    print("M15 v2 candidate feasibility report (process_improvements #22)")
    print("=" * 70)

    total_fail = 0
    for mode in (1, 2, 5, 7):
        target = _load_target(mode)
        m_res = _profile_candidate(candidates[mode], f"v2_mode_{mode}")
        results, fail = _report_mode(mode, m_res, target)
        total_fail += fail

        print()
        print(f"--- mode {mode} ---")
        print(f"  Total RTP:       {m_res['total_rtp_pct']:.3f}%   "
              f"base {m_res['base_rtp_pp']:.2f}pp + feature {m_res['feature_rtp_pp']:.2f}pp")
        print(f"  Hit:             {m_res['hit_rate']*100:.3f}%")
        print(f"  Base CV:         {m_res['base_cv']:.3f}    feature CV: {m_res['feature_cv']:.3f}")
        print(f"  Trigger:         {m_res['trigger_rate']*100:.4f}%  "
              f"(1 in {1/m_res['trigger_rate']:.0f})")
        print(f"  Feature EV:      {m_res['feature_ev']:.2f}x bet")
        print(f"  P(R>=1000/spin): {m_res['p_r_ge_1000_per_spin']:.2e}")
        print()
        for r in results:
            tag = {
                "MATCH": "[MATCH]",
                "NEAR-MISS": "[N-MISS]",
                "STRUCTURAL": "[STRUCT]",
                "FAIL": "[FAIL ]",
            }[r["class"]]
            print(f"  {tag} {r['label']:<35} got={r['fmt'].format(r['value'])}  "
                  f"band=[{r['lo_s']}, {r['hi_s']}]")
            if r["doc_status"] and r["class"] in ("NEAR-MISS", "STRUCTURAL"):
                print(f"            (target.json: {r['doc_status']})")

    print()
    print("=" * 70)
    if total_fail == 0:
        print("FEASIBILITY OK  — all targets MATCH or documented NEAR-MISS / STRUCTURAL")
    else:
        print(f"FEASIBILITY FAIL — {total_fail} target(s) unreachable without "
              f"documented justification")
    print("=" * 70)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
