"""Verify M37 weights against player-experience design red lines.

Each check function references the player-experience target same as
tune_m37.py — no separate threshold copies. Runs all 4 modes if weights
present.

Usage:
    python -m slot_designer.scripts.verify_m37_design
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

# Re-import targets from tune_m37 — single source of truth
from slot_designer.scripts.tune_m37 import (
    RTP_TARGETS,
    RTP_TOLERANCE_PP,
    HIT_TARGETS,
    HIT_TOL,
    GRAND_FREQ_TARGETS,
    THREE_WILD_TARGETS_M1,
    TOP_FREQ_TARGETS,
    ROLE_BLANK_RANGES,
    PWDF_TARGETS,
    BUCKET_COUNT_RANGES,
    PAY9_DOMINANCE_CAP,
    TIER_TO_BUCKETS,
    PAY_TO_FAMILY,
    _window_visibility,
)

FREQ_TOL_FACTOR = 2.0  # actual freq within [target/2, target*2]


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


# ═══════════════════════════════════════════════════════════════════
# Checks
# ═══════════════════════════════════════════════════════════════════

def check_rtp(mode, pred):
    a = pred["rtp_pct"]
    t, tol = RTP_TARGETS[mode], RTP_TOLERANCE_PP[mode]
    return [("RTP", mode, f"{a:.2f}% vs {t}±{tol}", abs(a - t) <= tol)]


def check_hit(mode, pred):
    a = pred["hit_rate"]
    t, tol = HIT_TARGETS[mode], HIT_TOL[mode]
    return [("HIT", mode, f"{a:.1%} vs {t:.0%}±{tol:.0%}", abs(a - t) <= tol)]


def check_grand_freq(mode, pred):
    a = pred.get("pay_hits", {}).get("8", 0.0)
    t = GRAND_FREQ_TARGETS[mode]
    if a <= 0:
        return [("GRAND-FREQ", mode, "0 hits", False)]
    ratio = a / t
    ok = (1/FREQ_TOL_FACTOR) <= ratio <= FREQ_TOL_FACTOR
    return [("GRAND-FREQ", mode, f"1/{1/a:.0f} vs 1/{1/t:.0f} (ratio {ratio:.2f}x)", ok)]


def check_3wild_freq(mode, pred):
    if mode != 1:
        return []
    out = []
    for pid, t in THREE_WILD_TARGETS_M1.items():
        a = pred.get("pay_hits", {}).get(pid, 0.0)
        if a <= 0:
            out.append(("THREE-WILD-FREQ", mode, f"pay_id {pid}: 0 hits", False))
            continue
        ratio = a / t
        ok = (1/FREQ_TOL_FACTOR) <= ratio <= FREQ_TOL_FACTOR
        out.append(("THREE-WILD-FREQ", mode,
                    f"pay_id {pid}: 1/{1/a:.0f} vs 1/{1/t:.0f} ({ratio:.2f}x)", ok))
    return out


def check_top_freq(mode, densities):
    p_top = (
        (densities.get(("high7", 0), 0) + densities.get(("wild", 0), 0))
        * densities.get(("grand", 1), 0)
        * (densities.get(("high7", 2), 0) + densities.get(("wild", 2), 0))
    )
    t = TOP_FREQ_TARGETS[mode]
    if p_top <= 0:
        return [("TOP-FREQ", mode, "0 prob", False)]
    ratio = p_top / t
    ok = (1/FREQ_TOL_FACTOR) <= ratio <= FREQ_TOL_FACTOR
    return [("TOP-FREQ", mode, f"1/{1/p_top:.0f} vs 1/{1/t:.0f} ({ratio:.2f}x)", ok)]


def check_role_blank(mode, densities):
    out = []
    for r, (lo, hi) in ROLE_BLANK_RANGES.items():
        a = densities.get(("blank", r), 0.0)
        out.append(("ROLE-BLANK", mode,
                    f"R{r+1} blank {a:.1%} vs [{lo:.0%}, {hi:.0%}]",
                    lo <= a <= hi))
    return out


def check_pwdf(mode, densities):
    out = []
    g_vis = _window_visibility(densities.get(("grand", 1), 0))
    out.append(("PWDF-GRAND", mode,
                f"grand R2 vis {g_vis:.2%} vs ≥{PWDF_TARGETS['grand_r2']:.1%}",
                g_vis >= PWDF_TARGETS["grand_r2"]))

    h_r1 = _window_visibility(densities.get(("high7", 0), 0))
    h_r3 = _window_visibility(densities.get(("high7", 2), 0))
    h_c = 1 - (1 - h_r1) * (1 - h_r3)
    out.append(("PWDF-HIGH7", mode,
                f"high7 R1+R3 vis {h_c:.2%} vs ≥{PWDF_TARGETS['high7_outer']:.0%}",
                h_c >= PWDF_TARGETS["high7_outer"]))

    w_r1 = _window_visibility(densities.get(("wild", 0), 0))
    w_r3 = _window_visibility(densities.get(("wild", 2), 0))
    w_c = 1 - (1 - w_r1) * (1 - w_r3)
    out.append(("PWDF-WILD", mode,
                f"wild R1+R3 vis {w_c:.2%} vs ≥{PWDF_TARGETS['wild_outer']:.0%}",
                w_c >= PWDF_TARGETS["wild_outer"]))

    booster_d = sum(densities.get((s, 1), 0) for s in ("mini", "minor", "major", "grand"))
    b_vis = _window_visibility(booster_d)
    out.append(("PWDF-BOOSTER", mode,
                f"booster R2 vis {b_vis:.2%} vs ≥{PWDF_TARGETS['booster_r2']:.0%}",
                b_vis >= PWDF_TARGETS["booster_r2"]))
    return out


def check_bucket_count(mode, pred):
    out = []
    bucket_rate = pred.get("bucket_rate", {})
    hit = pred["hit_rate"]
    if hit <= 0:
        return [("BUCKET-COUNT", mode, "0 hits", False)]
    for tier, (lo, hi) in BUCKET_COUNT_RANGES.items():
        keys = TIER_TO_BUCKETS[tier]
        tier_hits = sum(bucket_rate.get(k, 0.0) for k in keys)
        share = tier_hits / hit
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
                        f"R2: {s}({d*100:.3f}%) > {prev}({prev_d*100:.3f}%) — REVERSED",
                        False))
        prev = s
        prev_d = d
    if not out:
        out.append(("HIERARCHY", mode, "all directions correct", True))
    return out


def check_reel_asymmetry(mode, densities):
    out = []
    r1b = densities.get(("blank", 0), 0)
    r3b = densities.get(("blank", 2), 0)
    out.append(("ASYMMETRY-BLANK", mode, f"R1 {r1b:.1%} vs R3 {r3b:.1%}", r1b <= r3b))
    r1t = densities.get(("high7", 0), 0) + densities.get(("wild", 0), 0)
    r3t = densities.get(("high7", 2), 0) + densities.get(("wild", 2), 0)
    out.append(("ASYMMETRY-TOP", mode, f"R1 {r1t:.1%} vs R3 {r3t:.1%}", r1t >= r3t))
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


def check_pay9_dominance(mode, pred):
    hit = pred.get("hit_rate", 0)
    p9 = pred.get("pay_hits", {}).get("9", 0)
    if hit <= 0:
        return [("PAY9-DOMINANCE", mode, "0 hits", True)]
    share = p9 / hit
    return [("PAY9-DOMINANCE", mode,
             f"pay_id 9 {share:.1%} of hits (cap {PAY9_DOMINANCE_CAP:.0%})",
             share <= PAY9_DOMINANCE_CAP)]


def check_mode_pair_mono(modes_preds):
    if not all(m in modes_preds for m in (1, 2, 5, 7)):
        return [("MODE-PAIR-MONO", 0, "skipped (not all modes)", True)]
    out = []
    rtp = {m: modes_preds[m]["rtp_pct"] for m in (1, 2, 5, 7)}
    hit = {m: modes_preds[m]["hit_rate"] for m in (1, 2, 5, 7)}
    pairs = [
        ("RTP m2 > m1", rtp[2] > rtp[1]),
        ("RTP m5 > m2", rtp[5] > rtp[2]),
        ("RTP m7 < m1", rtp[7] < rtp[1]),
        ("HIT m2 > m1", hit[2] > hit[1]),
        ("HIT m5 ≥ m2 (-2pp)", hit[5] >= hit[2] - 0.02),
        ("HIT m7 < m1", hit[7] < hit[1]),
    ]
    for d, ok in pairs:
        out.append(("MODE-PAIR-MONO", 0, d, ok))
    return out


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

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
        all_checks.extend(check_grand_freq(mode, pred))
        all_checks.extend(check_3wild_freq(mode, pred))
        all_checks.extend(check_top_freq(mode, densities))
        all_checks.extend(check_role_blank(mode, densities))
        all_checks.extend(check_pwdf(mode, densities))
        all_checks.extend(check_bucket_count(mode, pred))
        all_checks.extend(check_hierarchy(mode, densities))
        all_checks.extend(check_reel_asymmetry(mode, densities))
        all_checks.extend(check_blank_flank(mode, strips))
        all_checks.extend(check_pay9_dominance(mode, pred))

    all_checks.extend(check_mode_pair_mono(modes_preds))

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
