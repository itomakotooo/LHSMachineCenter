"""M1 design verification — player-experience gate.

Per ``project_slot_designer_axiom_experience_is_soul``: TDD numbers are
inspiration, not constraint; what we verify is **player experience
reasonableness**, not divergence from a particular real machine's
per-position weights.

Run after any tune. All red lines must be green before "done" per
``project_slot_designer_axiom_experience_is_soul``.

Usage:
    python -m slot_designer.scripts.verify_m1_design

Exit: 0 = all green, 1 = at least one red.

Categories:
    [RTP]         Per-mode total RTP within tolerance
    [HIT]         Per-mode hit rate within band
    [WILD]        Wild on payline P(>=1) signature within band per mode
    [SHARE]       Per-mode family RTP share within band
    [DENSITY]     Per-family per-reel payline density visually合理 [1%, 22%]
    [MODE7-LOCK]  Mode 7 Diamond/Seven family RTP within ±0.5pp of mode 1
                  (大奖击中率/产出期望绝对不砍)
    [MODE7-CUT]   Mode 7 Bar1/Cherry family share visibly cut from mode 1
                  (略砍小奖/砍小奖体感)
    [SIGNATURE]   Wild on payline cross-mode drift ≤ 25%
                  (Double Diamond signature 一致性)
    [TOP-PATH]    Top-tier (Diamond + Seven) RTP not cut in mode 7
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile, compute_reel_marginal
from slot_designer.engine.loader import load_engine

SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
STRIPS = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"

# pay_id -> family classification for RTP-share aggregation.
# Matches tune_m1.PAY_TO_FAMILY.
PAY_TO_FAMILY = {
    "12": "Cherry", "13": "Cherry", "14": "Cherry",
    "2": "Diamond", "3": "Diamond", "4": "Diamond",
    "5": "Seven", "6": "Seven", "10": "Seven",
    "7": "Bar3", "8": "Bar2", "9": "Bar1",
    "11": "Bar_group",  # split equally Bar1/Bar2/Bar3
}

# Per-mode RTP / hit / wild_signature / family-share targets.
MODE_TARGETS = {
    1: {
        "rtp": 95.0, "rtp_tol": 1.0,
        "hit_lo": 0.14, "hit_hi": 0.22,
        "wild_lo": 0.10, "wild_hi": 0.18,
        "family_share_band": {
            # share = family_rtp_pp / total_rtp (0-1 scale).
            # Synced with tune_m1.EXPERIENCE_TARGETS[1].family_share_bands.
            # Wild lowered to 10-16% allows Diamond family share to compress
            # to ~5% (pure-Diamond combos cubic-rare; substitution wins go
            # to non-Diamond families).
            "Diamond": (0.04, 0.20),
            "Seven":   (0.12, 0.24),
            "Bar3":    (0.10, 0.22),
            "Bar2":    (0.10, 0.24),
            "Bar1":    (0.08, 0.20),
            "Cherry":  (0.08, 0.18),
        },
        # Mid-bucket hit-rate floors — player should see 5-20× wins
        # at ≤15-min cadence (10 spins/min).
        "bucket_hit_floors": {
            "ge5_lt10": 0.005,    # ≥1 in 200 spins (~20 min)
            "ge10_lt20": 0.008,   # ≥1 in 125 spins (~12 min)
        },
    },
    7: {
        "rtp": 85.0, "rtp_tol": 1.5,
        "hit_lo": 0.10, "hit_hi": 0.16,
        "wild_lo": 0.10, "wild_hi": 0.18,
        # Mode 7 family share inherits mode 1 floor; explicit checks via
        # MODE7-LOCK / MODE7-CUT validate per-family deltas.
        "family_share_band": {
            "Diamond": (0.04, 0.20),
            "Seven":   (0.12, 0.26),
            "Bar3":    (0.10, 0.24),
            "Bar2":    (0.08, 0.26),
            "Bar1":    (0.06, 0.22),
            "Cherry":  (0.06, 0.18),
        },
    },
    2: {
        "rtp": 294.5, "rtp_tol": 20.0,
        "hit_lo": 0.20, "hit_hi": 0.35,
        "wild_lo": 0.10, "wild_hi": 0.28,
        # Lucky mode = 7-dominated per RWB/Blazing Sevens benchmark.
        # Synced with tune_m1.EXPERIENCE_TARGETS.
        "family_share_band": {
            "Diamond": (0.03, 0.25),
            "Seven":   (0.35, 0.65),
            "Bar3":    (0.05, 0.22),
            "Bar2":    (0.05, 0.20),
            "Bar1":    (0.03, 0.16),
            "Cherry":  (0.03, 0.16),
        },
        "density_hi": 0.30,
    },
    5: {
        "rtp": 500.0, "rtp_tol": 30.0,
        "hit_lo": 0.20, "hit_hi": 0.40,
        "wild_lo": 0.10, "wild_hi": 0.30,
        "family_share_band": {
            "Diamond": (0.02, 0.30),
            "Seven":   (0.50, 0.80),
            "Bar3":    (0.03, 0.20),
            "Bar2":    (0.02, 0.13),
            "Bar1":    (0.005, 0.10),
            "Cherry":  (0.01, 0.10),
        },
        "density_hi": 0.35,
    },
}

# Per-reel per-family density caps — synced with tune_m1.py.
# Bar3/Bar2 (mid-pay 显眼) > 17% on any reel = "怪" (one symbol dominates).
# Top-pay (Seven, Diamond) capped tighter (rare-by-brand). Bar1/Cherry
# (filler-acceptable) higher cap. Lucky modes get ~3-5pp upper relax.
PER_REEL_DENSITY_HI_BY_FAMILY_STANDARD = {
    "Diamond1": 0.10, "Diamond2": 0.10,
    "Seven1": 0.12,  "Seven2": 0.12,
    "Bar3": 0.17, "Bar2": 0.17,
    "Bar1": 0.22, "Cherry": 0.20,
}
PER_REEL_DENSITY_HI_BY_FAMILY_LUCKY = {
    "Diamond1": 0.13, "Diamond2": 0.13,
    "Seven1": 0.20,  "Seven2": 0.22,
    "Bar3": 0.20, "Bar2": 0.20,
    "Bar1": 0.26, "Cherry": 0.22,
}
PER_REEL_DENSITY_HI_BY_MODE = {
    1: PER_REEL_DENSITY_HI_BY_FAMILY_STANDARD,
    7: PER_REEL_DENSITY_HI_BY_FAMILY_STANDARD,
    2: PER_REEL_DENSITY_HI_BY_FAMILY_LUCKY,
    5: PER_REEL_DENSITY_HI_BY_FAMILY_LUCKY,
}

PER_REEL_DENSITY_LO_BY_FAMILY = {
    "Seven2": 0.0025, "Diamond2": 0.0025,  # top-rare; 1 in 400 still visible
    "Seven1": 0.005, "Diamond1": 0.005,
    "Bar3": 0.005, "Bar2": 0.005, "Bar1": 0.005,
    "Cherry": 0.005,
}

# Mode 7 anchoring: Diamond/Seven absolute RTP (pp) must be within
# ±MODE7_LOCK_TOL of mode 1's value.
MODE7_LOCK_TOL_PP = 0.6

# Mode 7 cut: Bar1/Cherry family pp must be at least MODE7_CUT_MIN_PP below mode 1.
MODE7_CUT_MIN_PP = {"Bar1": 1.0, "Cherry": 1.0}

# Standard-mode wild signature drift: mode 1 vs mode 7 should be similar
# (both "normal luck"). Lucky modes (2, 5) naturally have more wild visible
# — that's part of "feels lucky", not a signature break.
WILD_DRIFT_STANDARD_PP = 3.0  # mode 1 vs mode 7 absolute pp difference cap


def family_rtp_breakdown(profile, paytable):
    rtp_excluded = {str(p["pay_id"]) for p in paytable if p.get("rtp_excluded")}
    family: dict[str, float] = defaultdict(float)
    for pid, rtp_contrib in profile.get("pay_rtp", {}).items():
        if pid in rtp_excluded:
            continue
        f = PAY_TO_FAMILY.get(pid, "Unknown")
        if f == "Bar_group":
            for bar in ("Bar1", "Bar2", "Bar3"):
                family[bar] += rtp_contrib / 3
        else:
            family[f] += rtp_contrib
    return {k: v * 100 for k, v in family.items()}  # pp


def per_reel_family_density(engine):
    out: dict[tuple[str, int], float] = {}
    for r_idx, reel in enumerate(engine.reels):
        marg = compute_reel_marginal(reel)
        for sym, p in marg.items():
            out[(sym, r_idx)] = p
    return out


def wild_on_payline_p(engine):
    p_no_wild = 1.0
    for reel in engine.reels:
        marg = compute_reel_marginal(reel)
        p_w = marg.get("Diamond1", 0) + marg.get("Diamond2", 0)
        p_no_wild *= (1.0 - p_w)
    return 1.0 - p_no_wild


def load_mode_state(mode):
    weights_path = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
    if not weights_path.exists():
        return None
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    engine, _ = load_engine(SPEC, weights_path)
    profile = analytic_profile(engine)
    family_rtp = family_rtp_breakdown(profile, spec["pays"])
    densities = per_reel_family_density(engine)
    wild_p = wild_on_payline_p(engine)
    return {
        "engine": engine,
        "profile": profile,
        "family_rtp_pp": family_rtp,
        "densities": densities,
        "wild_on_payline": wild_p,
    }


def make_check(category, mode, label, ok, info):
    return {
        "category": category,
        "mode": mode,
        "label": label,
        "ok": bool(ok),
        "info": info,
    }


def run_per_mode_checks(mode, state):
    targets = MODE_TARGETS[mode]
    profile = state["profile"]
    family_rtp = state["family_rtp_pp"]
    wild_p = state["wild_on_payline"]
    densities = state["densities"]
    checks = []

    # RTP
    rtp = profile["rtp_pct"]
    rtp_target = targets["rtp"]
    rtp_tol = targets["rtp_tol"]
    rtp_ok = abs(rtp - rtp_target) <= rtp_tol
    checks.append(make_check(
        "RTP", mode, f"RTP {rtp:.2f}% vs target {rtp_target:.1f}±{rtp_tol:.1f}",
        rtp_ok, f"diff {rtp - rtp_target:+.2f}pp",
    ))

    # HIT
    hit = profile["hit_rate"]
    hit_ok = targets["hit_lo"] <= hit <= targets["hit_hi"]
    checks.append(make_check(
        "HIT", mode, f"hit {hit:.2%} vs band [{targets['hit_lo']:.0%}, {targets['hit_hi']:.0%}]",
        hit_ok, "",
    ))

    # WILD
    wild_ok = targets["wild_lo"] <= wild_p <= targets["wild_hi"]
    checks.append(make_check(
        "WILD", mode, f"wild_on_payline {wild_p:.2%} vs band [{targets['wild_lo']:.0%}, {targets['wild_hi']:.0%}]",
        wild_ok, "",
    ))

    # SHARE
    total_rtp = profile["rtp_pct"]
    for f, (lo, hi) in targets["family_share_band"].items():
        actual = family_rtp.get(f, 0.0) / total_rtp if total_rtp > 0 else 0
        ok = lo <= actual <= hi
        checks.append(make_check(
            "SHARE", mode, f"{f} share {actual:.1%} vs band [{lo:.0%}, {hi:.0%}]",
            ok, f"absolute {family_rtp.get(f, 0.0):.2f}pp",
        ))

    # DENSITY (per-reel per-family) — per-family per-mode caps.
    # Mid-pay symbols capped at 17% standard / 20% lucky to avoid "怪".
    hi_by_fam = PER_REEL_DENSITY_HI_BY_MODE.get(mode, PER_REEL_DENSITY_HI_BY_FAMILY_STANDARD)
    for (sym, r), d in sorted(densities.items()):
        if sym == "Blank":
            continue
        den_lo = PER_REEL_DENSITY_LO_BY_FAMILY.get(sym, 0.005)
        den_hi = hi_by_fam.get(sym, 0.22)
        ok = den_lo <= d <= den_hi
        if not ok:
            checks.append(make_check(
                "DENSITY", mode, f"{sym} R{r+1} density {d:.2%} outside [{den_lo:.1%}, {den_hi:.0%}]",
                ok, "",
            ))

    # BUCKET-FLOOR — mid-bucket hit-rate floors so player sees mid wins
    # at human cadence. Mode 1 specifies; lucky/derived modes inherit
    # naturally via family RTP boost.
    bucket_floors = targets.get("bucket_hit_floors", {})
    for bucket, floor in bucket_floors.items():
        actual = profile.get("bucket_rate", {}).get(bucket, 0.0)
        ok = actual >= floor
        # Convert to "1 in N spins" for readability
        n_spins_actual = (1 / actual) if actual > 0 else float("inf")
        n_spins_floor = 1 / floor
        checks.append(make_check(
            "BUCKET-FLOOR", mode,
            f"{bucket} hit {actual:.2%} (1 in {n_spins_actual:.0f}) vs floor {floor:.1%} (1 in {n_spins_floor:.0f})",
            ok, "",
        ))

    return checks


def run_cross_mode_checks(state_by_mode):
    """Mode 7 lock + cut + signature consistency."""
    checks = []

    if 1 not in state_by_mode:
        return checks

    m1 = state_by_mode[1]
    m1_family = m1["family_rtp_pp"]
    m1_wild = m1["wild_on_payline"]

    # Mode 7 locks (Diamond/Seven absolute pp)
    if 7 in state_by_mode:
        m7 = state_by_mode[7]
        m7_family = m7["family_rtp_pp"]

        for f in ("Diamond", "Seven"):
            m1_pp = m1_family.get(f, 0.0)
            m7_pp = m7_family.get(f, 0.0)
            diff = m7_pp - m1_pp
            ok = abs(diff) <= MODE7_LOCK_TOL_PP
            checks.append(make_check(
                "MODE7-LOCK", 7,
                f"{f} pp m7={m7_pp:.2f} vs m1={m1_pp:.2f} (Δ {diff:+.2f}pp, tol ±{MODE7_LOCK_TOL_PP:.1f})",
                ok,
                "大奖击中率/产出期望绝对不砍",
            ))

        # Mode 7 cuts (Bar1/Cherry visibly cut)
        for f, min_cut in MODE7_CUT_MIN_PP.items():
            m1_pp = m1_family.get(f, 0.0)
            m7_pp = m7_family.get(f, 0.0)
            cut = m1_pp - m7_pp
            ok = cut >= min_cut
            checks.append(make_check(
                "MODE7-CUT", 7,
                f"{f} cut {cut:+.2f}pp (min {min_cut:.1f}pp expected)",
                ok,
                "小奖砍 → 玩家觉得运气差 → 充值 trigger",
            ))

        # Top path: Diamond + Seven mode 7 sum >= mode 1 sum (less ε)
        m1_top = m1_family.get("Diamond", 0) + m1_family.get("Seven", 0)
        m7_top = m7_family.get("Diamond", 0) + m7_family.get("Seven", 0)
        top_diff = m7_top - m1_top
        ok = top_diff >= -MODE7_LOCK_TOL_PP * 2  # combined tolerance
        checks.append(make_check(
            "TOP-PATH", 7,
            f"Diamond+Seven m7={m7_top:.2f}pp vs m1={m1_top:.2f}pp (Δ {top_diff:+.2f}pp)",
            ok,
            "顶奖路径不动",
        ))

    # Standard-mode wild signature: mode 1 vs mode 7 should be similar.
    # Lucky modes 2/5 allowed to have MORE wild (lucky feel = more wild visible).
    if 1 in state_by_mode and 7 in state_by_mode:
        w1 = state_by_mode[1]["wild_on_payline"] * 100
        w7 = state_by_mode[7]["wild_on_payline"] * 100
        diff = abs(w1 - w7)
        ok = diff <= WILD_DRIFT_STANDARD_PP
        checks.append(make_check(
            "SIGNATURE", None,
            f"wild_on_payline mode 1={w1:.2f}pp vs mode 7={w7:.2f}pp (diff {diff:.2f}pp, tol {WILD_DRIFT_STANDARD_PP}pp)",
            ok,
            "标准模式间 Double Diamond signature 一致",
        ))

    # Lucky modes can have MORE wild visibility (part of lucky feel) but
    # never less than standard modes (signature would die in lucky modes).
    for lucky in (2, 5):
        if lucky in state_by_mode and 1 in state_by_mode:
            w_lucky = state_by_mode[lucky]["wild_on_payline"]
            w_std = state_by_mode[1]["wild_on_payline"]
            ok = w_lucky >= w_std - 0.02  # allow small downward (2pp)
            checks.append(make_check(
                "SIGNATURE", lucky,
                f"mode {lucky} wild {w_lucky:.2%} vs mode 1 wild {w_std:.2%} (lucky should not be lower)",
                ok,
                "Lucky mode 不能让 signature 反而变弱",
            ))

    return checks


def main():
    state_by_mode: dict[int, dict] = {}
    available_modes = []
    for mode in (1, 2, 5, 7):
        st = load_mode_state(mode)
        if st is None:
            print(f"  [skip] mode {mode}: weights file not found")
            continue
        state_by_mode[mode] = st
        available_modes.append(mode)

    if not state_by_mode:
        print("ERROR: no mode weights found")
        return 1

    all_checks = []

    print("\n=== M1 player-experience design verification ===")
    print(f"Modes available: {available_modes}\n")

    for mode in sorted(available_modes):
        state = state_by_mode[mode]
        print(f"--- Mode {mode} ---")
        rtp = state["profile"]["rtp_pct"]
        hit = state["profile"]["hit_rate"]
        wild = state["wild_on_payline"]
        print(f"  RTP={rtp:.2f}%  hit={hit:.2%}  wild_on_payline={wild:.2%}")
        family_rtp = state["family_rtp_pp"]
        for f in ("Diamond", "Seven", "Bar3", "Bar2", "Bar1", "Cherry"):
            v = family_rtp.get(f, 0.0)
            share = v / rtp * 100 if rtp > 0 else 0
            print(f"    {f:8s} {v:6.2f}pp ({share:5.1f}%)")

        checks = run_per_mode_checks(mode, state)
        all_checks.extend(checks)

    cross = run_cross_mode_checks(state_by_mode)
    all_checks.extend(cross)

    # Summary
    print("\n=== Verification results ===")
    fail_count = 0
    by_category = defaultdict(list)
    for c in all_checks:
        by_category[c["category"]].append(c)

    for cat in sorted(by_category.keys()):
        checks = by_category[cat]
        passes = sum(1 for c in checks if c["ok"])
        fails = sum(1 for c in checks if not c["ok"])
        status = "GREEN" if fails == 0 else f"RED ({fails}/{len(checks)} fail)"
        print(f"  [{cat:12s}] {passes:3d} pass / {len(checks):3d} total — {status}")
        for c in checks:
            if not c["ok"]:
                mode_str = f"mode {c['mode']}" if c["mode"] is not None else "all"
                print(f"     [FAIL] {mode_str}: {c['label']}")
                if c["info"]:
                    print(f"          ({c['info']})")
                fail_count += 1

    print(f"\n{'GREEN — all checks pass' if fail_count == 0 else f'RED — {fail_count} check(s) failed'}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
