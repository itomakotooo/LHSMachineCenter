"""Derive M1 mode 5 weights from mode 2 by copying base + scaling top-bucket.

Per FIRST_MACHINE.md §7 (non-feature machine mode 5 derivation rule):
  * Base (Cherry/Bar1/Bar2/Bar3/Blank) weights = mode 2's byte-identical
  * Top-bucket (Diamond1/Diamond2/Seven1/Seven2) weights scaled by uniform
    factor k to push total RTP from ~294% to 500% ±30pp

Per project_slot_designer_strips_identical_across_modes.md (canonical hard rule):
  * Reel strip layout byte-identical across all modes (shared file)
  * mode 5 ← mode 2 derivation (analogous to feature machines' "feature_params
    swap"): non-feature machines scale top-bucket only.

Why not free-tune (the broken pre-fix state): tuner finds Pareto-cheap RTP
routes that violate "mode 5 = mode 2 + super-lucky" narrative — observed:
R2 total weight collapse (520 → 106, 4.9× ratio max/min), Diamond R2 marginal
exploded 5.2% → 15.1%, Bar1 R2 weight=1 (effectively extinct, marginal 23%
→ 2.8%), Seven1 R2 marginal NOT monotonic m2 → m5 (7.5% → 6.6%, REVERSE).
Strict base lock prevents these pathologies and makes mode 5 a clean luck
variation of mode 2 (per axiom: 'modes are luck variations not N machines').

Usage:
  python -m slot_designer.scripts.derive_m1_mode_5 [--write] [--verify]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile
from slot_designer.engine.loader import load_engine


_SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
_STRIPS = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"
_MODE_2_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M1" / "mode_2" / "weights.json"
_MODE_5_DIR = _ROOT / "slot_designer" / "weights" / "M1" / "mode_5"
_MODE_5_WEIGHTS = _MODE_5_DIR / "weights.json"

TOP_BUCKET_SYMBOLS = ("Diamond1", "Diamond2", "Seven1", "Seven2")
WEIGHT_FLOOR = 3   # never let a top-bucket weight drop below 3 (visibility floor)
WEIGHT_CAP = 80    # never let a top-bucket weight exceed 80 (lucky upper bound)

TARGET_RTP = 500.0
TARGET_RTP_TOL = 30.0


def _scale_doc(mode_2_doc: dict, strips_reels: list[list[str]], k: float) -> dict:
    """Return mode 5 doc = mode 2 base + top-bucket weights × k."""
    doc = copy.deepcopy(mode_2_doc)
    doc["mode"] = 5
    doc.pop("_tuned_summary", None)
    doc.pop("_family_uniform_weights", None)
    doc.pop("_family_scales", None)
    for r_idx in range(len(strips_reels)):
        for p_idx in range(len(strips_reels[r_idx])):
            sym = strips_reels[r_idx][p_idx]
            if sym in TOP_BUCKET_SYMBOLS:
                w_new = int(round(mode_2_doc["weights"][r_idx][p_idx] * k))
                doc["weights"][r_idx][p_idx] = max(WEIGHT_FLOOR, min(WEIGHT_CAP, w_new))
    return doc


def _eval_doc(doc: dict) -> dict:
    tmp = Path(tempfile.mktemp(suffix=".json"))
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    try:
        eng, _ = load_engine(_SPEC, tmp, strips_path=_STRIPS)
        return analytic_profile(eng)
    finally:
        tmp.unlink(missing_ok=True)


def _bisect_k(mode_2_doc: dict, strips_reels: list[list[str]],
              target_rtp: float = TARGET_RTP) -> tuple[float, dict]:
    """Bisect uniform top-bucket scalar k so total RTP ≈ target_rtp."""
    lo, hi = 1.0, 5.0
    for _ in range(40):
        mid = (lo + hi) / 2
        rtp = _eval_doc(_scale_doc(mode_2_doc, strips_reels, mid))["rtp_pct"]
        if rtp < target_rtp:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-4:
            break
    k_best = (lo + hi) / 2
    return k_best, _eval_doc(_scale_doc(mode_2_doc, strips_reels, k_best))


def _family_breakdown(profile: dict, paytable: list[dict]) -> dict[str, float]:
    rtp_excluded = {str(p["pay_id"]) for p in paytable if p.get("rtp_excluded")}
    pay_to_fam = {
        "12": "Cherry", "13": "Cherry", "14": "Cherry",
        "2": "Diamond", "3": "Diamond", "4": "Diamond",
        "5": "Seven", "6": "Seven", "10": "Seven",
        "7": "Bar3", "8": "Bar2", "9": "Bar1",
        "11": "Bar_group",
    }
    family: dict[str, float] = {}
    for pid, rtp in profile.get("pay_rtp", {}).items():
        if pid in rtp_excluded:
            continue
        f = pay_to_fam.get(pid, "Unknown")
        if f == "Bar_group":
            for bar in ("Bar1", "Bar2", "Bar3"):
                family[bar] = family.get(bar, 0.0) + rtp / 3 * 100
        else:
            family[f] = family.get(f, 0.0) + rtp * 100
    return family


def _per_reel_top_marginals(doc: dict, strips_reels: list[list[str]]) -> dict[tuple[str, int], float]:
    out: dict[tuple[str, int], float] = {}
    for r_idx in range(len(strips_reels)):
        total = sum(doc["weights"][r_idx])
        for sym in TOP_BUCKET_SYMBOLS:
            w_sum = sum(
                w for w, s in zip(doc["weights"][r_idx], strips_reels[r_idx]) if s == sym
            )
            out[(sym, r_idx)] = w_sum / total if total > 0 else 0.0
    return out


def run(write: bool, verify: bool) -> int:
    print(f"{'='*70}")
    print(f"M1 mode 5 derivation — copy mode 2 base + scale top-bucket")
    print(f"{'='*70}\n")

    strips_doc = json.loads(_STRIPS.read_text(encoding="utf-8"))
    strips_reels = strips_doc["reels"]
    mode_2_doc = json.loads(_MODE_2_WEIGHTS.read_text(encoding="utf-8"))
    spec_doc = json.loads(_SPEC.read_text(encoding="utf-8"))

    print(f"Source: mode 2 ({_MODE_2_WEIGHTS.relative_to(_ROOT)})")
    print(f"Target: mode 5 ({_MODE_5_WEIGHTS.relative_to(_ROOT)})")
    print()

    print(f"Bisecting uniform top-bucket scalar k for RTP ≈ {TARGET_RTP:.0f}% ...")
    k_best, prof_m5 = _bisect_k(mode_2_doc, strips_reels, target_rtp=TARGET_RTP)
    print(f"  best k = {k_best:.4f}: RTP={prof_m5['rtp_pct']:.3f}%, "
          f"hit={prof_m5['hit_rate']:.3%}, CV={prof_m5.get('cv', 0):.2f}")
    print()

    mode_5_doc = _scale_doc(mode_2_doc, strips_reels, k_best)

    # Verify base byte-identical to mode 2
    base_diff = 0
    for r_idx in range(len(strips_reels)):
        for p_idx in range(len(strips_reels[r_idx])):
            sym = strips_reels[r_idx][p_idx]
            if sym not in TOP_BUCKET_SYMBOLS:
                if mode_5_doc["weights"][r_idx][p_idx] != mode_2_doc["weights"][r_idx][p_idx]:
                    base_diff += 1
    base_ok = base_diff == 0
    print(f"Base weights byte-identical to mode 2: "
          f"{'OK' if base_ok else f'BUG — {base_diff} positions differ'}")
    if not base_ok:
        return 1

    mode_5_doc["_notes"] = [
        "M1 mode 5 weights — derived from mode 2 (non-feature mode 5 rule).",
        "",
        f"Derivation: `python -m slot_designer.scripts.derive_m1_mode_5 --write`",
        "Base weights (Cherry/Bar1/Bar2/Bar3/Blank): byte-identical to mode 2.",
        f"Top-bucket weights (Diamond1/Diamond2/Seven1/Seven2): "
        f"× {k_best:.4f} uniform.",
        "Reel strips unchanged (shared byte-identical reel_strips.json).",
        "",
        f"Design target: Total RTP {TARGET_RTP:.0f}% ±{TARGET_RTP_TOL:.0f}pp.",
        f"  Achieved RTP: {prof_m5['rtp_pct']:.3f}%",
        f"  Achieved hit: {prof_m5['hit_rate']:.3%}",
        f"  Achieved CV:  {prof_m5.get('cv', 0):.2f}",
        "",
        "Per FIRST_MACHINE.md §7 (non-feature mode 5): mode 5 = mode 2 base +",
        "顶奖路径加强（top-bucket scaled）. Player feels mode 2's grind/cherry/",
        "bar pace UNCHANGED but顶奖密度 (Seven×3 / Diamond×3 frequencies) jumps.",
        "",
        "Do NOT tune this mode through Phase 4/5. Base is locked to mode 2 by",
        "design rule (project_slot_designer_strips_identical_across_modes.md).",
    ]
    mode_5_doc["_derivation"] = {
        "source_mode": 2,
        "method": "uniform_top_bucket_scalar",
        "scalar_k": round(k_best, 6),
        "scaled_symbols": list(TOP_BUCKET_SYMBOLS),
        "frozen_symbols": [
            "Blank", "Cherry", "Bar1", "Bar2", "Bar3",
        ],
    }

    family_rtp = _family_breakdown(prof_m5, spec_doc["pays"])
    mode_5_doc["_tuned_summary"] = {
        "rtp_pct": prof_m5["rtp_pct"],
        "hit_rate": prof_m5["hit_rate"],
        "cv": prof_m5.get("cv", 0.0),
        "family_rtp_pp": {f: round(v, 3) for f, v in family_rtp.items()},
        "method": "derive_m1_mode_5_uniform_top_bucket",
    }

    if write:
        _MODE_5_DIR.mkdir(parents=True, exist_ok=True)
        _MODE_5_WEIGHTS.write_text(
            json.dumps(mode_5_doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\n[write] wrote {_MODE_5_WEIGHTS.relative_to(_ROOT)}")
    else:
        print("\n[dry-run] use --write to persist mode_5/weights.json")

    if verify:
        print()
        print(f"{'-'*70}")
        print(f"Analytic verification")
        print(f"{'-'*70}")

        rtp = prof_m5["rtp_pct"]
        rtp_ok = abs(rtp - TARGET_RTP) <= TARGET_RTP_TOL
        print(f"  RTP {rtp:.3f}% vs target {TARGET_RTP}±{TARGET_RTP_TOL}pp: "
              f"{'OK' if rtp_ok else 'DRIFT'}")

        hit = prof_m5["hit_rate"]
        hit_ok = 0.20 <= hit <= 0.40
        print(f"  hit {hit:.2%} vs band [20%, 40%]: {'OK' if hit_ok else 'OUT'}")

        # Family share band check (matches verify_m1_design.py mode 5 bands)
        bands = {
            "Diamond": (0.02, 0.30),
            "Seven":   (0.50, 0.80),
            "Bar3":    (0.03, 0.20),
            "Bar2":    (0.02, 0.13),
            "Bar1":    (0.005, 0.10),
            "Cherry":  (0.01, 0.10),
        }
        all_share_ok = True
        for f, (lo, hi) in bands.items():
            actual_pp = family_rtp.get(f, 0.0)
            share = actual_pp / rtp if rtp > 0 else 0.0
            ok = lo <= share <= hi
            all_share_ok &= ok
            print(f"  {f:8s} share {share:5.1%} ({actual_pp:6.2f}pp) "
                  f"vs band [{lo:.0%}, {hi:.0%}]: {'OK' if ok else 'OUT'}")

        # Cross-mode monotonicity: m5 top-bucket marginals ≥ m2's
        eng_m2, _ = load_engine(_SPEC, _MODE_2_WEIGHTS, strips_path=_STRIPS)
        prof_m2 = analytic_profile(eng_m2)
        family_rtp_m2 = _family_breakdown(prof_m2, spec_doc["pays"])
        print()
        print("  Cross-mode top-bucket monotonicity (m5 ≥ m2):")
        for f in ("Diamond", "Seven"):
            v_m2 = family_rtp_m2.get(f, 0.0)
            v_m5 = family_rtp.get(f, 0.0)
            ok = v_m5 >= v_m2 - 0.01
            print(f"    {f:8s} m2={v_m2:6.2f}pp m5={v_m5:6.2f}pp Δ={v_m5-v_m2:+.2f}pp: "
                  f"{'OK' if ok else 'REGRESSION'}")

        # Per-reel total weight balance (no R-collapse)
        per_reel_total = [sum(mode_5_doc["weights"][r]) for r in range(len(strips_reels))]
        ratio = max(per_reel_total) / min(per_reel_total)
        ratio_ok = ratio <= 3.0  # mode 2 is 2.49x; allow modest worsening
        print()
        print(f"  Per-reel total weight: R1={per_reel_total[0]} R2={per_reel_total[1]} "
              f"R3={per_reel_total[2]} (max/min={ratio:.2f}×, cap 3.00×): "
              f"{'OK' if ratio_ok else 'COLLAPSE'}")

        if not (rtp_ok and hit_ok and all_share_ok and ratio_ok):
            return 1
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--write", action="store_true",
                   help="write mode_5/weights.json (default: dry-run)")
    p.add_argument("--verify", action="store_true",
                   help="run analytic verification (RTP/hit/share/balance)")
    args = p.parse_args()
    sys.exit(run(write=args.write, verify=args.verify))


if __name__ == "__main__":
    main()
