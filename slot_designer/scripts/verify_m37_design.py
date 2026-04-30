"""Verify M37 weights against user-confirmed targets only.

Each check function references tune_m37 constants — single source of truth.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile
from slot_designer.engine.loader import load_engine

SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
STRIPS_PATH = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"
WEIGHTS_DIR = _ROOT / "slot_designer" / "weights" / "M37"

from slot_designer.scripts.tune_m37 import (
    RTP_TARGETS,
    RTP_TOLERANCE_PP,
    HIT_TARGETS,
    GRAND_PAYLINE_TARGETS,
    BAR_PAYLINE_FREQ_CAP,
    ROLE_BLANK_RANGES_BY_MODE,
    BUCKET_COUNT_RANGES_BY_MODE,
    TIER_TO_BUCKETS,
    PAY_TO_FAMILY,
    BAR_PAY_IDS,
)

# Hit tolerance — accept ±2pp from target (user said 15%, we accept 13-17%).
HIT_TOL_BY_MODE = {1: 0.02, 7: 0.02, 2: 0.02, 5: 0.02}


def _all_densities(weights, strips):
    out = defaultdict(float)
    for r in range(3):
        total = sum(weights[r])
        if total <= 0:
            continue
        for w, s in zip(weights[r], strips[r]):
            out[(s, r)] += w / total
    return dict(out)


def _family_rtp(pred):
    out = defaultdict(float)
    for pid, rtp in (pred.get("pay_rtp") or {}).items():
        out[PAY_TO_FAMILY.get(pid, "other")] += rtp * 100
    return dict(out)


def _load(mode):
    p = WEIGHTS_DIR / f"mode_{mode}" / "weights.json"
    engine, _ = load_engine(SPEC_PATH, p)
    pred = analytic_profile(engine)
    weights = json.loads(p.read_text(encoding="utf-8"))["weights"]
    strips = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    return pred, weights, strips, _all_densities(weights, strips)


def check_rtp(mode, pred):
    a = pred["rtp_pct"]
    t, tol = RTP_TARGETS[mode], RTP_TOLERANCE_PP[mode]
    return [("RTP", mode, f"{a:.2f}% vs {t}±{tol}", abs(a - t) <= tol)]


def check_hit(mode, pred):
    a = pred["hit_rate"]
    t = HIT_TARGETS[mode]
    tol = HIT_TOL_BY_MODE[mode]
    return [("HIT", mode, f"{a:.1%} vs {t:.0%}±{tol:.0%}", abs(a - t) <= tol)]


def check_grand_payline(mode, pred):
    a = pred.get("pay_hits", {}).get("8", 0.0)
    lo, hi = GRAND_PAYLINE_TARGETS[mode]
    if a <= 0:
        return [("GRAND-PAYLINE", mode, "0 hits", False)]
    ok = lo <= a <= hi
    return [("GRAND-PAYLINE", mode,
             f"{a*100:.3f}% vs [{lo*100:.2f}%, {hi*100:.2f}%]",
             ok)]


def check_bar_combined_freq(mode, pred):
    a = sum(pred.get("pay_hits", {}).get(p, 0.0) for p in BAR_PAY_IDS)
    return [("BAR-FREQ", mode, f"bars combined {a:.1%} vs cap {BAR_PAYLINE_FREQ_CAP:.0%}",
             a <= BAR_PAYLINE_FREQ_CAP)]


def check_role_blank(mode, densities):
    out = []
    role_ranges = ROLE_BLANK_RANGES_BY_MODE[mode]
    for r, (lo, hi) in role_ranges.items():
        a = densities.get(("blank", r), 0.0)
        out.append(("ROLE-BLANK", mode,
                    f"R{r+1} blank {a:.1%} vs [{lo:.0%}, {hi:.0%}]",
                    lo <= a <= hi))
    return out


def check_bucket_count(mode, pred):
    out = []
    bucket_rate = pred.get("bucket_rate", {})
    hit = pred["hit_rate"]
    if hit <= 0:
        return [("BUCKET-COUNT", mode, "0 hits", False)]
    bucket_ranges = BUCKET_COUNT_RANGES_BY_MODE[mode]
    for tier, (lo, hi) in bucket_ranges.items():
        keys = TIER_TO_BUCKETS[tier]
        share = sum(bucket_rate.get(k, 0.0) for k in keys) / hit
        out.append(("BUCKET-COUNT", mode,
                    f"{tier} {share:.1%} vs [{lo:.0%}, {hi:.1%}]",
                    lo <= share <= hi))
    return out


def check_hierarchy(mode, densities):
    out = []
    BAR_ORDER = ("1bar", "2bar", "3bar", "7bar")
    for r in (0, 2):
        prev = None
        prev_d = None
        for s in BAR_ORDER:
            d = densities.get((s, r), 0.0)
            if d == 0:
                continue
            if prev_d is not None and d > prev_d:
                out.append(("HIERARCHY-BAR", mode,
                            f"R{r+1}: {s}({d*100:.2f}%) > {prev}({prev_d*100:.2f}%) — REVERSED",
                            False))
            prev = s
            prev_d = d
    BOOSTER_ORDER = ("mini", "minor", "major", "grand")
    prev = None
    prev_d = None
    for s in BOOSTER_ORDER:
        d = densities.get((s, 1), 0.0)
        if d == 0:
            continue
        if prev_d is not None and d > prev_d:
            out.append(("HIERARCHY-BOOSTER", mode,
                        f"R2: {s}({d*100:.3f}%) > {prev}({prev_d*100:.3f}%) — REVERSED", False))
        prev = s
        prev_d = d
    if not out:
        out.append(("HIERARCHY", mode, "all directions correct", True))
    return out


def check_reel_asymmetry(mode, densities):
    out = []
    r1b = densities.get(("blank", 0), 0)
    r3b = densities.get(("blank", 2), 0)
    out.append(("ASYMMETRY-BLANK", mode, f"R1 {r1b:.1%} ≤ R3 {r3b:.1%}", r1b <= r3b))
    r1t = densities.get(("high7", 0), 0) + densities.get(("wild", 0), 0)
    r3t = densities.get(("high7", 2), 0) + densities.get(("wild", 2), 0)
    out.append(("ASYMMETRY-TOP", mode, f"R1 {r1t:.1%} ≥ R3 {r3t:.1%}", r1t >= r3t))
    return out


def check_blank_flank(mode, strips):
    out = []
    for r_idx, reel in enumerate(strips):
        n = len(reel)
        viol = []
        for i, s in enumerate(reel):
            if s != "blank":
                continue
            prev, nxt = reel[(i-1) % n], reel[(i+1) % n]
            if prev == nxt and prev != "blank":
                viol.append((i, prev))
        out.append(("BLANK-FLANK", mode,
                    f"R{r_idx+1}: {len(viol)} X-blank-X violations", len(viol) == 0))
    return out


def main():
    modes_preds = {}
    all_checks = []
    strips = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

    for mode in (1, 2, 5, 7):
        wp = WEIGHTS_DIR / f"mode_{mode}" / "weights.json"
        if not wp.exists():
            print(f"WARN: mode {mode} weights missing — skipping")
            continue
        pred, weights, _, densities = _load(mode)
        modes_preds[mode] = pred

        print(f"\n--- Mode {mode} ---")
        print(f"  RTP={pred['rtp_pct']:.2f}%  hit={pred['hit_rate']:.2%}  CV={pred.get('cv',0):.2f}")
        for f in ("high7", "7bar", "bar_tier", "booster_alone", "wild_amplified"):
            rtp = _family_rtp(pred).get(f, 0)
            share = rtp / pred["rtp_pct"] * 100 if pred["rtp_pct"] else 0
            print(f"    {f:<18} {rtp:6.2f}pp ({share:5.1f}%)")

        all_checks.extend(check_rtp(mode, pred))
        all_checks.extend(check_hit(mode, pred))
        all_checks.extend(check_grand_payline(mode, pred))
        all_checks.extend(check_bar_combined_freq(mode, pred))
        all_checks.extend(check_role_blank(mode, densities))
        all_checks.extend(check_bucket_count(mode, pred))
        all_checks.extend(check_hierarchy(mode, densities))
        all_checks.extend(check_reel_asymmetry(mode, densities))
        all_checks.extend(check_blank_flank(mode, strips))

    print("\n=== Verification results ===")
    by_cat = defaultdict(lambda: [0, 0])
    fails = []
    for cat, mode, desc, ok in all_checks:
        by_cat[cat][1] += 1
        if ok:
            by_cat[cat][0] += 1
        else:
            fails.append((cat, mode, desc))
    for cat in sorted(by_cat):
        p, t = by_cat[cat]
        status = "GREEN" if p == t else f"RED ({t-p}/{t})"
        print(f"  [{cat:<22}] {p:>2}/{t:>2} -- {status}")
    if fails:
        print("\nFAILED:")
        for cat, mode, desc in fails:
            print(f"  [{cat}] mode {mode}: {desc}")
        sys.exit(1)
    print("\nGREEN — all checks pass")


if __name__ == "__main__":
    main()
