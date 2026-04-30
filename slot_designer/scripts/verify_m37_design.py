"""Verify M37 weights against DESIGN.md §16 red lines.

v7 clean rebuild (2026-04-29). Each verify check references a DESIGN.md
§-number. No cross-machine hardcoded thresholds — every band/cap derives
from DESIGN.md §-numbered narrative.

Usage:
    python -m slot_designer.scripts.verify_m37_design

Output: per-mode metrics + per-category PASS/FAIL summary. Exit code 1 if
any RED.
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


# Re-import constants from tune_m37 — DESIGN.md is single source of truth
from slot_designer.scripts.tune_m37 import (
    RTP_TARGETS,
    RTP_TOLERANCE_PP,
    HIT_RATE_TARGETS,
    HIT_RATE_TOLERANCE,
    GRAND_ALONE_FREQ_TARGETS,
    THREE_WILD_FREQ_TARGETS_MODE1,
    TOP_JACKPOT_FREQ_TARGETS,
    TIER_TO_BUCKETS,
    PAY_TO_FAMILY,
)


# DESIGN.md §4/§5/§6: freq target tolerance "factor of 2" (per derivation chain)
FREQ_TARGET_TOLERANCE_FACTOR = 2.0

# DESIGN.md §1 + universal §8: M37 pay_id 9 is brand booster_alone family;
# universal §8 70% cap accepted as-is for M37.
PAY_ID_9_HIT_SHARE_CAP = 0.70


def _all_densities(weights, strips):
    out = defaultdict(float)
    for r in range(3):
        total = sum(weights[r])
        if total <= 0:
            continue
        for w, s in zip(weights[r], strips[r]):
            out[(s, r)] += w / total
    return dict(out)


def _family_rtp_breakdown(pred):
    out = defaultdict(float)
    for pid, rtp in (pred.get("pay_rtp") or {}).items():
        family = PAY_TO_FAMILY.get(pid, "other")
        out[family] += rtp * 100
    return dict(out)


def _load_pred(mode):
    weights_path = WEIGHTS_DIR / f"mode_{mode}" / "weights.json"
    engine, _ = load_engine(SPEC_PATH, weights_path)
    pred = analytic_profile(engine)
    weights = json.loads(weights_path.read_text(encoding="utf-8"))["weights"]
    strips = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    densities = _all_densities(weights, strips)
    return pred, weights, strips, densities


# ═══════════════════════════════════════════════════════════════════
# Verify checks per DESIGN.md §16
# ═══════════════════════════════════════════════════════════════════

def check_rtp(mode, pred):
    actual = pred["rtp_pct"]
    target = RTP_TARGETS[mode]
    tol = RTP_TOLERANCE_PP[mode]
    ok = abs(actual - target) <= tol
    return [("RTP", mode, f"{actual:.2f}% vs {target}±{tol}", ok)]


def check_hit(mode, pred):
    actual = pred["hit_rate"]
    target = HIT_RATE_TARGETS[mode]
    tol = HIT_RATE_TOLERANCE[mode]
    ok = abs(actual - target) <= tol
    return [("HIT", mode, f"{actual:.1%} vs {target:.0%}±{tol:.0%}", ok)]


def check_grand_freq(mode, pred):
    actual = pred.get("pay_hits", {}).get("8", 0.0)
    target = GRAND_ALONE_FREQ_TARGETS[mode]
    if actual <= 0:
        return [("GRAND-FREQ", mode, "0 hits", False)]
    ratio = actual / target
    ok = (1.0 / FREQ_TARGET_TOLERANCE_FACTOR) <= ratio <= FREQ_TARGET_TOLERANCE_FACTOR
    return [("GRAND-FREQ", mode,
             f"1/{1/actual:.0f} vs 1/{1/target:.0f} (ratio {ratio:.2f}x, tol [0.5x, 2x])", ok)]


def check_3wild_freq(mode, pred):
    if mode != 1:
        return []
    out = []
    for pid, target in THREE_WILD_FREQ_TARGETS_MODE1.items():
        actual = pred.get("pay_hits", {}).get(pid, 0.0)
        if actual <= 0:
            out.append(("THREE-WILD-FREQ", mode, f"pay_id {pid}: 0 hits", False))
            continue
        ratio = actual / target
        ok = (1.0 / FREQ_TARGET_TOLERANCE_FACTOR) <= ratio <= FREQ_TARGET_TOLERANCE_FACTOR
        out.append(("THREE-WILD-FREQ", mode,
                    f"pay_id {pid}: 1/{1/actual:.0f} vs 1/{1/target:.0f} (ratio {ratio:.2f}x)", ok))
    return out


def check_top_freq(mode, densities):
    p_top = (
        (densities.get(("high7", 0), 0) + densities.get(("wild", 0), 0))
        * densities.get(("grand", 1), 0)
        * (densities.get(("high7", 2), 0) + densities.get(("wild", 2), 0))
    )
    target = TOP_JACKPOT_FREQ_TARGETS[mode]
    if p_top <= 0:
        return [("TOP-FREQ", mode, "0 prob", False)]
    ratio = p_top / target
    ok = (1.0 / FREQ_TARGET_TOLERANCE_FACTOR) <= ratio <= FREQ_TARGET_TOLERANCE_FACTOR
    return [("TOP-FREQ", mode,
             f"1/{1/p_top:.0f} vs 1/{1/target:.0f} (ratio {ratio:.2f}x)", ok)]


def check_bucket_direction(mode, pred):
    bucket_rate = pred.get("bucket_rate", {})
    tier_hits = {
        tier: sum(bucket_rate.get(k, 0.0) for k in keys)
        for tier, keys in TIER_TO_BUCKETS.items()
    }
    tier_order = ("low", "mid", "high", "top")
    violations = []
    for i in range(len(tier_order) - 1):
        a, b = tier_order[i], tier_order[i + 1]
        if tier_hits[a] < tier_hits[b]:
            violations.append(f"{a}({tier_hits[a]:.4%}) < {b}({tier_hits[b]:.4%})")
    if violations:
        return [("BUCKET-DIRECTION", mode, "; ".join(violations), False)]
    return [("BUCKET-DIRECTION", mode,
             f"low={tier_hits['low']:.2%}>mid={tier_hits['mid']:.2%}>high={tier_hits['high']:.3%}>top={tier_hits['top']:.4%}",
             True)]


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
    r1_blank = densities.get(("blank", 0), 0)
    r3_blank = densities.get(("blank", 2), 0)
    r1_top = densities.get(("high7", 0), 0) + densities.get(("wild", 0), 0)
    r3_top = densities.get(("high7", 2), 0) + densities.get(("wild", 2), 0)
    out = [
        ("REEL-ASYMMETRY-BLANK", mode,
         f"R1 blank {r1_blank:.1%} {'<=' if r1_blank<=r3_blank else '>'} R3 blank {r3_blank:.1%}",
         r1_blank <= r3_blank),
        ("REEL-ASYMMETRY-TOP", mode,
         f"R1 top {r1_top:.1%} {'>=' if r1_top>=r3_top else '<'} R3 top {r3_top:.1%}",
         r1_top >= r3_top),
    ]
    return out


def check_alternation(mode, strips):
    out = []
    for r_idx, reel in enumerate(strips):
        violations = sum(
            1 for i, sym in enumerate(reel)
            if (i % 2 == 0 and sym != "blank") or (i % 2 == 1 and sym == "blank")
        )
        out.append(("ALTERNATION", mode, f"R{r_idx+1}: {violations} violations", violations == 0))
    return out


def check_blank_flank_diversity(mode, strips):
    out = []
    for r_idx, reel in enumerate(strips):
        n = len(reel)
        violations = []
        for i, sym in enumerate(reel):
            if sym != "blank":
                continue
            prev = reel[(i - 1) % n]
            nxt = reel[(i + 1) % n]
            if prev == nxt and prev != "blank":
                violations.append((i, prev))
        ok = len(violations) == 0
        desc = f"R{r_idx+1}: {len(violations)} X-blank-X violations"
        if violations:
            desc += f" (e.g. pos {violations[0][0]} flanked by {violations[0][1]})"
        out.append(("BLANK-FLANK-DIVERSITY", mode, desc, ok))
    return out


def check_pay_id_9_dominance(mode, pred):
    hit = pred.get("hit_rate", 0.0)
    pay9 = pred.get("pay_hits", {}).get("9", 0.0)
    if hit <= 0:
        return [("PAY9-DOMINANCE", mode, "0 hits", True)]
    share = pay9 / hit
    ok = share <= PAY_ID_9_HIT_SHARE_CAP
    return [("PAY9-DOMINANCE", mode,
             f"pay_id 9 {share:.1%} of hits (cap {PAY_ID_9_HIT_SHARE_CAP:.0%})", ok)]


def check_mode_pair_monotonicity(modes_preds):
    if not all(m in modes_preds for m in (1, 2, 5, 7)):
        return [("MODE-PAIR-MONO", 0, "skipped — not all modes loaded", True)]
    out = []
    rtp = {m: modes_preds[m]["rtp_pct"] for m in (1, 2, 5, 7)}
    hit = {m: modes_preds[m]["hit_rate"] for m in (1, 2, 5, 7)}
    pairs = [
        ("RTP m2 > m1", rtp[2] > rtp[1]),
        ("RTP m5 > m2", rtp[5] > rtp[2]),
        ("RTP m7 < m1", rtp[7] < rtp[1]),
        ("HIT m2 > m1", hit[2] > hit[1]),
        ("HIT m5 >= m2 (-2pp tol)", hit[5] >= hit[2] - 0.02),
        ("HIT m7 < m1", hit[7] < hit[1]),
    ]
    for desc, ok in pairs:
        out.append(("MODE-PAIR-MONO", 0, desc, ok))
    return out


def main():
    modes_preds = {}
    all_checks = []

    strips_data = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))
    strips = strips_data["reels"]

    for mode in (1, 2, 5, 7):
        weights_path = WEIGHTS_DIR / f"mode_{mode}" / "weights.json"
        if not weights_path.exists():
            print(f"WARN: mode {mode} weights missing — skipping")
            continue
        pred, weights, _, densities = _load_pred(mode)
        modes_preds[mode] = pred

        print(f"\n--- Mode {mode} ---")
        print(f"  RTP={pred['rtp_pct']:.2f}%  hit={pred['hit_rate']:.2%}  CV={pred.get('cv',0):.2f}")
        family_rtp = _family_rtp_breakdown(pred)
        for f in ("high7", "7bar", "bar_tier", "booster_alone", "wild_amplified"):
            rtp = family_rtp.get(f, 0)
            share = rtp / pred["rtp_pct"] * 100 if pred["rtp_pct"] else 0
            print(f"    {f:<18} {rtp:6.2f}pp ({share:5.1f}%)")

        all_checks.extend(check_rtp(mode, pred))
        all_checks.extend(check_hit(mode, pred))
        all_checks.extend(check_grand_freq(mode, pred))
        all_checks.extend(check_3wild_freq(mode, pred))
        all_checks.extend(check_top_freq(mode, densities))
        all_checks.extend(check_bucket_direction(mode, pred))
        all_checks.extend(check_hierarchy(mode, densities))
        all_checks.extend(check_reel_asymmetry(mode, densities))
        all_checks.extend(check_alternation(mode, strips))
        all_checks.extend(check_blank_flank_diversity(mode, strips))
        all_checks.extend(check_pay_id_9_dominance(mode, pred))

    all_checks.extend(check_mode_pair_monotonicity(modes_preds))

    print("\n=== Verification results ===")
    by_category = defaultdict(lambda: [0, 0])
    fails = []
    for cat, mode, desc, ok in all_checks:
        by_category[cat][1] += 1
        if ok:
            by_category[cat][0] += 1
        else:
            fails.append((cat, mode, desc))
    for cat in sorted(by_category):
        p, t = by_category[cat]
        status = "GREEN" if p == t else f"RED ({t-p}/{t} fail)"
        print(f"  [{cat:<26}] {p:>3} pass / {t:>3} total -- {status}")
    if fails:
        print("\nFAILED:")
        for cat, mode, desc in fails:
            print(f"  [{cat}] mode {mode}: {desc}")
        sys.exit(1)
    print("\nGREEN -- all checks pass")


if __name__ == "__main__":
    main()
